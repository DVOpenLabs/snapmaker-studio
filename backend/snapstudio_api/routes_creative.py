"""Routes of the Creative track: inspect one local creative project (3MF) and say what Studio read.

    POST /creative/inspect   {path, format?}  -> {origin, understood, passed_through, could_not_interpret,
                                                  missing, diagnostics, recipes, source, evidence, advisory}

The handler opens the file for reading only. It never writes, renames or deletes anything, never
slices, never contacts a printer and never touches the network. `source` carries the SHA-256 of the
file before the readers ran and again afterwards, so the response itself shows the original is
unchanged. Recipes are simulated: `execution_supported` is False and nothing here runs them. An
unrecognised generator is reported as origin "unknown", never guessed.
"""
from __future__ import annotations

import hashlib
import os

from snapstudio_core import localpath
from snapstudio_core.creative import container, readers

from . import ext_routes
from . import request_validation as rv

#: Same ceiling the 3MF reader enforces; a larger file is refused before it is read.
MAX_FILE_BYTES = container.MAX_ARCHIVE_BYTES
MAX_PATH_CHARS = 1024

EVIDENCE = "fixture-tested; fixtures are hand-written to published shapes, not captures"
ADVISORY = ("Advisory read of one project file. Studio does not slice, does not run recipes and "
            "does not change the file. What it could not interpret is listed, not guessed.")

#: format hint -> reader. "auto" picks by the keys the project settings contain.
_READERS = {
    "forcaslicer": readers.read_forca,
    "lixnix": readers.read_lixnix,
    "fullspectrum": readers.read_fullspectrum,
    "imagemap": readers.read_imagemap,
    "lumina": readers.read_lumina,
}
_FORMATS = ("auto",) + tuple(_READERS)

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


def _detect(settings: dict) -> list[str]:
    """Formats whose published keys are present. Several can match; none means unknown."""
    keys = set(settings)
    found = []
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


@ext_routes.route("/creative/inspect")
def inspect(data: dict) -> tuple[int, dict]:
    path = _path(data)
    hint = _format(data)
    blob = _read_source(path)
    before = hashlib.sha256(blob).hexdigest()
    try:
        manifest = container.read_3mf(blob)
    except container.ContainerError as exc:
        raise _wrap(exc) from None

    settings = manifest.project_settings or {}
    names = [hint] if hint != "auto" else _detect(settings)
    projects = []
    try:
        for name in names:
            projects.append(_READERS[name](blob))
    except container.ContainerError as exc:
        raise _wrap(exc) from None

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

    after = _read_source(path)
    after_hash = hashlib.sha256(after).hexdigest()
    return 200, {
        "origin": origin,
        "understood": list(understood),
        "passed_through": passed,
        "could_not_interpret": list(unknown),
        "missing": list(missing),
        "diagnostics": list(diagnostics),
        "recipes": recipes,
        "physical_slots_needed": slots,
        "source": {"name": os.path.basename(path), "size_bytes": len(blob),
                   "sha256_before": before, "sha256_after": after_hash,
                   "unchanged": before == after_hash},
        "evidence": EVIDENCE,
        "advisory": ADVISORY,
    }
