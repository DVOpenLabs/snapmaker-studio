"""Routes of the Creative track: inspect a local creative project (3MF), list the supported formats,
and write a prepared copy with a verification of what the copy kept.

    POST /creative/inspect  {path, format?}           -> what Studio read (origin, facts, kept, not understood)
    POST /creative/formats  {}                        -> SUPPORTED_FORMATS: what each format reads and does not
    POST /creative/prepare  {path, format?, out_dir?} -> a NEW prepared file, member-by-member comparison with
                                                         the original, and a re-hash of the original

Inspect opens the file for reading only. Prepare calls the existing Prepare service, which writes one new
file, never over or in place of the original, into `out_dir` (a local directory) or, when none is given,
into the `creative-prepared` folder of Studio's own data directory. Nothing slices, nothing contacts a
printer, nothing here makes a network request (the local-path check is best-effort, see
snapstudio_core/localpath.py). Recipes are simulated: `execution_supported` is False. An unrecognised or
ambiguous generator is reported as such and is never guessed, and Prepare refuses it with an explanation.
"""
from __future__ import annotations

import hashlib
import os

from snapstudio_core import localpath, paths
from snapstudio_core.creative import container, formats, generators, readers

from . import ext_routes
from . import request_validation as rv

#: Same ceiling the 3MF reader enforces; a larger file is refused before it is read.
MAX_FILE_BYTES = container.MAX_ARCHIVE_BYTES
MAX_PATH_CHARS = 1024
#: Longest list of names put into one comparison answer.
MAX_LISTED = 200

EVIDENCE = "fixture-tested; fixtures are hand-written to published shapes, not captures"
ADVISORY = ("Advisory read of one project file. Studio does not slice, does not run recipes and "
            "does not change the file. What it could not interpret is listed, not guessed.")
PREPARE_ADVISORY = ("Advisory comparison by part name and content hash. A prepared copy is a new file; it is "
                    "checked here only for what it kept, changed, dropped and added, not for how it slices "
                    "or prints. Review it in Snapmaker Orca before slicing.")

#: format hint -> reader. "auto" picks by the markers or keys the project contains.
_READERS = {
    "ditherforge": generators.read_ditherforge,
    "kromacut": generators.read_kromacut,
    "sindricad": generators.read_sindricad,
    "forcaslicer": readers.read_forca,
    "lixnix": readers.read_lixnix,
    "fullspectrum": readers.read_fullspectrum,
    "imagemap": readers.read_imagemap,
    "lumina": readers.read_lumina,
}
_FORMATS = ("auto",) + formats.KEYS
#: Key-identified formats: a chosen format whose published keys are all absent is the wrong shape.
_KEY_FORMATS = {
    "forcaslicer": readers._FORCA_KEYS,
    "lixnix": readers._LIX_KEYS,
    "fullspectrum": readers._FULLSPECTRUM_KEYS,
}
_FORMAT_BY_KEY = {f["key"]: f for f in formats.SUPPORTED_FORMATS}

_ERROR_TEXT = {
    "bad_zip": "That file is not a readable 3MF archive.",
    "archive_too_large": "That file is larger than the inspector reads.",
    "too_many_members": "That archive holds more parts than the inspector reads.",
    "unsafe_member_name": "That archive has a part name that is not safe to read.",
    "duplicate_member": "That archive lists the same part name twice.",
    "member_too_large": "A part inside that archive is larger than the inspector reads.",
    "archive_expanded_too_large": "That archive expands to more data than the inspector reads.",
    "compression_ratio_exceeded": "A part inside that archive expands far more than a normal 3MF.",
    "bad_zip_member": "A part inside that archive could not be read.",
    "truncated_member": "A part inside that archive is truncated.",
    "missing_model": "That archive has no 3D model part, so it is not a 3MF project.",
    "unsafe_xml": "The model part uses XML features the inspector does not read.",
    "bad_xml": "The model part is not valid XML.",
    "unsupported_3mf_version": "That 3MF uses a core namespace the inspector does not read.",
    "bad_project_settings": "The project settings part is not a JSON object.",
}


def _path(data: dict) -> str:
    raw = rv.require_path_string(data, "path")
    if len(raw) > MAX_PATH_CHARS or "\x00" in raw:
        raise rv.ValidationError("Invalid 'path'")
    return raw


def _format(data: dict) -> str:
    value = data.get("format", "auto")
    if not isinstance(value, str) or value not in _FORMATS:
        raise rv.ValidationError("Invalid 'format'")
    return value


def _read_source(path: str) -> bytes:
    """The file bytes, after checking it is a regular file under the size cap. Read-only open."""
    try:
        if localpath.is_network_or_device_path(path) or not localpath.is_local_regular_file(path):
            raise rv.ValidationError("That path is not a local file Studio can read.")
        if os.path.getsize(path) > MAX_FILE_BYTES:
            raise rv.ValidationError("That file is larger than the inspector reads.")
        with open(path, "rb") as fh:
            blob = fh.read(MAX_FILE_BYTES + 1)
    except rv.ValidationError:
        raise
    except OSError:
        raise rv.ValidationError("That file could not be opened.") from None
    if len(blob) > MAX_FILE_BYTES:
        raise rv.ValidationError("That file is larger than the inspector reads.")
    return blob


def _detect(manifest: container.ThreeMFManifest) -> list[str]:
    """Formats whose published keys or markers are present. Several can match; none means unknown."""
    keys = set(manifest.project_settings or {})
    found = list(generators.detect(manifest))
    if keys & readers._FORCA_KEYS:
        found.append("forcaslicer")
    if keys & readers._LIX_KEYS:
        found.append("lixnix")
    if keys & readers._FULLSPECTRUM_KEYS:
        found.append("fullspectrum")
    return found


def _wrap(exc: container.ContainerError) -> rv.ValidationError:
    code = str(exc)
    return rv.ValidationError(_ERROR_TEXT.get(code, "That file could not be read as a 3MF project."))


def _seen_sentence(manifest: container.ThreeMFManifest) -> str:
    app = ""
    try:
        app = generators._model_metadata(generators._xml(manifest.model_xml)).get("Application", "")
    except container.ContainerError:
        pass
    keys = len(manifest.project_settings or {})
    text = f"a 3MF project with {len(manifest.members)} parts and {keys} project settings keys"
    return text + (f", Application tag `{app[:60]}`" if app else ", no Application tag")


def _wrong_shape_message(key: str, manifest: container.ThreeMFManifest, expected: list[str]) -> str:
    label = formats.LABELS[key]
    return (f"That file does not carry what Studio reads for {label}. Studio looks for: "
            f"{'; '.join(expected)}. This file is {_seen_sentence(manifest)}. "
            "What to do: choose Detect from settings, pick the format of the tool that wrote the file, "
            "or open it in that tool. Studio does not guess a format.")


def _explain(origin: dict, manifest: container.ThreeMFManifest) -> dict | None:
    """Plain explanation for an origin Studio could not decide: what was seen, what is not supported, what to do."""
    seen = _seen_sentence(manifest)
    if origin["status"] == "unknown":
        return {"kind": "unknown_origin", "seen": f"This file is {seen}.",
                "not_supported": "None of the supported tools' markers or settings keys were found, so Studio "
                                 "does not say which tool wrote it and does not read it as one of them.",
                "what_to_do": ["If you know which tool wrote the file, choose its format from the list and inspect again.",
                               "Otherwise the file is still listed part by part below, untouched."]}
    if origin["status"] == "ambiguous":
        names = " and ".join(formats.LABELS.get(c, c) for c in origin["candidates"])
        return {"kind": "ambiguous_origin", "seen": f"This file is {seen}.",
                "not_supported": f"Markers of more than one tool are present ({names}), so Studio does not decide "
                                 "which one wrote it.",
                "what_to_do": ["Choose the format you know it came from and inspect again."]}
    return None


def _inspect(path: str, hint: str):
    """Shared by inspect and prepare. Returns (body, blob, manifest). Reads only."""
    blob = _read_source(path)
    before = hashlib.sha256(blob).hexdigest()
    try:
        manifest = container.read_3mf(blob)
    except container.ContainerError as exc:
        raise _wrap(exc) from None

    settings = manifest.project_settings or {}
    if hint in _KEY_FORMATS and not (set(settings) & _KEY_FORMATS[hint]):
        raise rv.ValidationError(_wrong_shape_message(hint, manifest, list(_FORMAT_BY_KEY[hint]["identified_by"])))
    names = [hint] if hint != "auto" else _detect(manifest)
    projects = []
    try:
        for name in names:
            projects.append(_READERS[name](blob))
    except container.ContainerError as exc:
        raise _wrap(exc) from None
    except generators.WrongShape as exc:
        raise rv.ValidationError(_wrong_shape_message(exc.generator, manifest, exc.expected)) from None

    if not projects:
        # Unknown generator: container identity only. Every part is preserved, nothing is interpreted.
        passed = [{"name": m.name, "sha256": m.sha256} for m in manifest.passed_through]
        passed += [{"name": k, "sha256": readers._digest_obj({k: v})["sha256"]} for k, v in sorted(settings.items())]
        origin = {"generator": "unknown", "status": "unknown", "candidates": []}
        understood = [p for p in manifest.understood_parts]
        unknown: list = []
        missing: list = []
        diagnostics = ["generator_not_recognized"]
        recipes: list = []
        slots = None
        facts: dict = {}
    else:
        status = "detected" if len(projects) == 1 else "ambiguous"
        origin = {"generator": projects[0].source_format if len(projects) == 1 else "unknown",
                  "status": status if hint == "auto" else "chosen",
                  "candidates": [p.source_format for p in projects]}
        understood = sorted({k for p in projects for k in p.understood})
        seen = set()
        passed = []
        for p in projects:
            for item in p.passed_through:
                key = (item["name"], item["sha256"])
                if key not in seen:
                    seen.add(key)
                    passed.append(item)
        # A key one reader understood is not passed through by another reading of the same file.
        passed = [i for i in passed if i["name"] not in understood]
        unknown = sorted({u for p in projects for u in p.unknown})
        missing = sorted({m for p in projects for m in p.missing})
        diagnostics = [d for p in projects for d in p.diagnostics]
        recipes = [r.to_dict() for p in projects for r in p.recipes]
        slots = next((p.physical_slots_needed for p in projects if p.recipes), None)
        facts = {p.source_format: p.understood for p in projects if p.source_format in generators.GENERATORS}

    after = _read_source(path)
    after_hash = hashlib.sha256(after).hexdigest()
    candidates = origin["candidates"] if origin["status"] != "unknown" else []
    body = {
        "origin": origin,
        "understood": list(understood),
        "facts": facts,
        "passed_through": passed,
        "could_not_interpret": list(unknown),
        "missing": list(missing),
        "diagnostics": list(diagnostics),
        "recipes": recipes,
        "physical_slots_needed": slots,
        "format_info": [_FORMAT_BY_KEY[c] for c in candidates if c in _FORMAT_BY_KEY],
        "explanation": _explain(origin, manifest),
        "source": {"name": os.path.basename(path), "size_bytes": len(blob), "sha256_before": before,
                   "sha256_after": after_hash, "unchanged": before == after_hash},
        "evidence": EVIDENCE,
        "advisory": ADVISORY,
    }
    return body, blob, manifest


@ext_routes.route("/creative/inspect")
def inspect(data: dict) -> tuple[int, dict]:
    body, _blob, _manifest = _inspect(_path(data), _format(data))
    return 200, body


@ext_routes.route("/creative/formats")
def supported_formats(data: dict) -> tuple[int, dict]:
    return 200, {"formats": [dict(f) for f in formats.SUPPORTED_FORMATS], "evidence": EVIDENCE,
                 "manual_only": list(formats.MANUAL_ONLY),
                 "note": "Support is listed per format. Studio does not infer support from the fact that a file is a ZIP."}


# -- prepare --------------------------------------------------------------------------------

DEFAULT_OUT_FOLDER = "creative-prepared"


def _out_dir(data: dict) -> tuple[str, str]:
    """(directory, kind). A given directory must be an existing local one; otherwise Studio's own folder."""
    raw = data.get("out_dir")
    if raw is None or raw == "":
        target = os.path.join(paths.data_dir(), DEFAULT_OUT_FOLDER)
        os.makedirs(target, exist_ok=True)
        return target, "studio_default"
    if not isinstance(raw, str) or len(raw) > MAX_PATH_CHARS or "\x00" in raw:
        raise rv.ValidationError("Invalid 'out_dir'")
    if localpath.is_network_or_device_path(raw) or not localpath.is_local_directory(raw):
        raise rv.ValidationError("That output folder is not an existing local folder Studio can write to.")
    return raw, "chosen"


def _refusal(kind: str, body: dict, explanation: dict) -> tuple[int, dict]:
    return 200, {"prepared": False, "refusal": {"kind": kind, **explanation},
                 "origin": body["origin"], "source": body["source"], "advisory": PREPARE_ADVISORY}


def _model_parts(parts: dict) -> list[bytes]:
    names = ["3D/3dmodel.model"] + sorted(n for n in parts if n.startswith("3D/Objects/") and n.endswith(".model"))
    return [parts[n] for n in names if n in parts]


def _paint_count(parts: dict) -> int | None:
    """Painted triangles over the root model and the object part files; None when a part cannot be parsed."""
    total = 0
    try:
        for blob in _model_parts(parts):
            total += generators._mesh_stats(generators._xml(blob))["painted"]
    except container.ContainerError:
        return None
    return total


def compare_members(original: container.ThreeMFManifest, exported: container.ThreeMFManifest) -> dict:
    """Name-based comparison of two archives' non-directory members."""
    old = {m.name: m.sha256 for m in original.members}
    new = {m.name: m.sha256 for m in exported.members}
    return {
        "preserved": sorted(n for n in old if n in new and old[n] == new[n]),
        "modified": sorted(n for n in old if n in new and old[n] != new[n]),
        "dropped": sorted(n for n in old if n not in new),
        "added": sorted(n for n in new if n not in old),
    }


def _settings_delta(original: dict | None, exported: dict | None) -> dict:
    a, b = original or {}, exported or {}
    return {"removed_keys": sorted(k for k in a if k not in b)[:MAX_LISTED],
            "changed_keys": sorted(k for k in a if k in b and a[k] != b[k])[:MAX_LISTED],
            "added_key_count": sum(1 for k in b if k not in a)}


def _verify(original: container.ThreeMFManifest, out_path: str) -> dict:
    """Open the exported archive and compare it with the original. Never raises on a bad export."""
    try:
        blob = _read_source(out_path)
        exported = container.read_3mf(blob)
    except (rv.ValidationError, container.ContainerError) as exc:
        return {"opens_as_zip": False, "problem": str(exc) if isinstance(exc, rv.ValidationError)
                else _ERROR_TEXT.get(str(exc), "The exported file could not be read.")}
    diff = compare_members(original, exported)
    before, after = _paint_count(original.parts), _paint_count(exported.parts)
    return {
        "opens_as_zip": True, "size_bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
        "members": [{"name": m.name, "sha256": m.sha256} for m in exported.members],
        "comparison": {k: v[:MAX_LISTED] for k, v in diff.items()},
        "counts": {k: len(v) for k, v in diff.items()},
        "settings": _settings_delta(original.project_settings, exported.project_settings),
        "per_face_paint": {"original_triangles": before, "exported_triangles": after,
                           "kept": None if before is None or after is None else after >= before},
    }


def _loss_notes(verify: dict) -> list[str]:
    notes = []
    counts = verify["counts"]
    if counts["dropped"]:
        notes.append(f"{counts['dropped']} part(s) of the original are not in the copy: "
                     + ", ".join(verify["comparison"]["dropped"][:6]) + ".")
    if counts["modified"]:
        notes.append(f"{counts['modified']} part(s) differ from the original: "
                     + ", ".join(verify["comparison"]["modified"][:6]) + ".")
    paint = verify["per_face_paint"]
    if paint["kept"] is False:
        notes.append(f"Per-face paint: the original has {paint['original_triangles']} painted triangle(s), "
                     f"the copy has {paint['exported_triangles']}.")
    if paint["kept"] is None:
        notes.append("Per-face paint could not be counted in one of the two files.")
    removed = verify["settings"]["removed_keys"]
    if removed:
        notes.append(f"{len(removed)} project setting(s) of the original are not in the copy.")
    if not notes:
        notes.append("By part name and content hash, nothing was dropped and nothing differs except the parts "
                     "listed as modified or added.")
    return notes


def _summary_subset(result: dict) -> dict:
    summary = result.get("settings_summary") or {}
    pick = lambda key: [i if isinstance(i, (str, int, float)) else dict(i) for i in (summary.get(key) or [])][:MAX_LISTED]  # noqa: E731
    return {"compat_changed": pick("compat_changed"), "mapped_to_u1": pick("mapped_to_u1"),
            "could_not_carry": pick("could_not_carry"), "warnings": pick("warnings")}


@ext_routes.route("/creative/prepare")
def prepare(data: dict) -> tuple[int, dict]:
    from snapstudio_core.errors import SnapStudioError

    from . import service

    path = _path(data)
    hint = _format(data)
    body, blob, manifest = _inspect(path, hint)
    explanation = body["explanation"]
    if explanation is not None:
        return _refusal(explanation["kind"], body, {
            "seen": explanation["seen"],
            "not_supported": explanation["not_supported"] + " Nothing was prepared.",
            "what_to_do": explanation["what_to_do"]})
    out_dir, out_kind = _out_dir(data)
    original_sha = hashlib.sha256(blob).hexdigest()
    try:
        result = service.convert(path, out_dir, "preserve")
    except SnapStudioError as exc:
        problems = list(getattr(exc, "problems", []))
        return _refusal("prepare_refused", body, {
            "seen": f"This file was read as {formats.LABELS.get(body['origin']['generator'], body['origin']['generator'])}.",
            "not_supported": f"Studio's Prepare could not produce a copy it can vouch for. {exc}",
            "what_to_do": ["Open the original in Snapmaker Orca to check it, or re-export it from the tool that wrote it.",
                           "Nothing was written and the original was not changed."],
            "problems": problems[:20]})
    except ValueError as exc:
        return _refusal("prepare_refused", body, {
            "seen": "The file was read, but Prepare refused it.", "not_supported": str(exc),
            "what_to_do": ["Nothing was written and the original was not changed."]})
    if result.get("blocked") or not result.get("output_path"):
        return _refusal("prepare_blocked", body, {
            "seen": "The file was read, but Prepare did not write a copy.",
            "not_supported": " ".join(str(e) for e in result.get("errors") or []) or "Prepare wrote no file.",
            "what_to_do": ["Nothing was written and the original was not changed."]})

    out_path = result["output_path"]
    verify = _verify(manifest, out_path)
    after = hashlib.sha256(_read_source(path)).hexdigest()
    same_place = os.path.dirname(os.path.abspath(out_path)) == os.path.dirname(os.path.abspath(path))
    return 200, {
        "prepared": True,
        "origin": body["origin"],
        "output": {"name": os.path.basename(out_path), "path": out_path, "location": out_kind,
                   "location_label": ("Studio's creative-prepared folder" if out_kind == "studio_default"
                                      else out_dir),
                   "in_source_folder": same_place},
        "prepare": {"mode": result.get("prepare_mode"), "validated_ok": bool(result.get("validated_ok")),
                    "errors": [str(e) for e in result.get("errors") or []][:MAX_LISTED],
                    **_summary_subset(result)},
        "verification": verify,
        "loss_notes": _loss_notes(verify) if verify.get("opens_as_zip") else
                      ["The exported file could not be re-read, so nothing can be said about what it kept."],
        "original": {"name": os.path.basename(path), "sha256_before": original_sha, "sha256_after": after,
                     "original_unchanged": original_sha == after},
        "source": body["source"],
        "advisory": PREPARE_ADVISORY,
    }
