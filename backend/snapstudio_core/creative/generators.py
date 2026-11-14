"""Readers for 3MF projects written by DitherForge, Kromacut and SindriCAD.

Each reader is built only from the output shape its upstream exporter source documents (commits
and paths are listed in tests/fixtures/creative/PROVENANCE.md and docs/internal/CREATIVE_COMPAT.md).
Kromacut and SindriCAD are AGPL-3.0: only the output FORMAT (member names, element and attribute
names, JSON keys) was learned from them; no code, comment or sample was copied.

A generator is identified from its documented markers, never from "it is a ZIP". When markers of
more than one generator are present the caller reports the origin as ambiguous. Anything beyond the
named facts is passed through by name and SHA-256 or listed as could-not-interpret.
"""
from __future__ import annotations

from typing import Any
from xml.etree import ElementTree

from .container import CORE_NS, ContainerError, ThreeMFManifest, read_3mf
from .readers import CreativeProject, _digest_obj

_C = f"{{{CORE_NS}}}"
_P = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}"
_M = "{http://schemas.microsoft.com/3dmanufacturing/material/2015/02}"

GENERATORS = ("ditherforge", "kromacut", "sindricad")
SETTINGS_PART = "Metadata/project_settings.config"
MODEL_SETTINGS_PART = "Metadata/model_settings.config"
KROMACUT_CONFIG_PART = "Metadata/kromacut.config"
_KROMACUT_NS = b'xmlns:Kromacut="https://github.com/vycdev/Kromacut"'

#: Parts each generator is documented to write. Absent ones are reported as missing, not guessed.
_EXPECTED_PARTS = {
    "ditherforge": (MODEL_SETTINGS_PART, SETTINGS_PART),
    "kromacut": (MODEL_SETTINGS_PART, KROMACUT_CONFIG_PART, SETTINGS_PART),
    "sindricad": (MODEL_SETTINGS_PART, SETTINGS_PART),
}
#: Metadata keys of model_settings.config each exporter writes. Others are listed as not interpreted.
_KNOWN_MODEL_SETTINGS_KEYS = {
    "ditherforge": {"name", "extruder", "face_count", "source_file", "subtype"},
    "kromacut": {"name", "extruder", "plater_id", "plater_name", "locked", "object_id", "instance_id"},
    "sindricad": {"name", "extruder"},
}
#: project_settings.config keys each reader names. Every other key is passed through by digest.
_KNOWN_SETTINGS_KEYS = {
    "ditherforge": ("filament_colour", "filament_type", "printer_settings_id", "print_settings_id"),
    "kromacut": ("filament_colour", "layer_height", "initial_layer_print_height"),
    "sindricad": ("filament_colour", "filament_type"),
}

MARKERS = {
    "ditherforge": ("model metadata Application starting `ditherforge-` or containing `+ditherforge-`",),
    "kromacut": ("model metadata Application `Kromacut_Print`", "model namespace `xmlns:Kromacut`",
                 f"archive member `{KROMACUT_CONFIG_PART}`"),
    "sindricad": ("model metadata Application `SindriCAD`",),
}


class WrongShape(ValueError):
    """The file does not carry the documented markers of the format that was asked for."""

    def __init__(self, generator: str, seen: list[str]):
        super().__init__(generator)
        self.generator = generator
        self.expected = list(MARKERS[generator])
        self.seen = seen


def _xml(blob: bytes) -> ElementTree.Element:
    upper = blob.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ContainerError("unsafe_xml")
    try:
        return ElementTree.fromstring(blob)
    except ElementTree.ParseError as exc:
        raise ContainerError("bad_xml") from exc


def _model_metadata(root: ElementTree.Element) -> dict[str, str]:
    return {el.get("name", ""): (el.text or "") for el in root if el.tag == f"{_C}metadata"}


def markers_present(manifest: ThreeMFManifest) -> dict[str, list[str]]:
    """generator -> markers that matched. Pure inspection of the already-read container."""
    root = _xml(manifest.model_xml)
    meta = _model_metadata(root)
    app = meta.get("Application", "")
    found: dict[str, list[str]] = {}
    if app.startswith("ditherforge-") or "+ditherforge-" in app:
        found["ditherforge"] = [MARKERS["ditherforge"][0]]
    kro = []
    if app == "Kromacut_Print":
        kro.append(MARKERS["kromacut"][0])
    if _KROMACUT_NS in manifest.model_xml:
        kro.append(MARKERS["kromacut"][1])
    if KROMACUT_CONFIG_PART in manifest.parts:
        kro.append(MARKERS["kromacut"][2])
    if kro:
        found["kromacut"] = kro
    if app == "SindriCAD":
        found["sindricad"] = [MARKERS["sindricad"][0]]
    return found


def detect(manifest: ThreeMFManifest) -> list[str]:
    return sorted(markers_present(manifest))


def _decode_paint(value: str) -> int | None:
    """1-based extruder for a documented 1-2 character `paint_color`, else None (not decoded)."""
    if value == "4":
        return 1
    if value == "8":
        return 2
    if len(value) == 2 and value.endswith("C") and value[0] in "0123456789ABCDEF":
        return int(value[0], 16) + 3
    return None


def _mesh_stats(root: ElementTree.Element) -> dict[str, Any]:
    triangles = painted = 0
    values: dict[str, int] = {}
    for tri in root.iter(f"{_C}triangle"):
        triangles += 1
        value = tri.get("paint_color") or ""
        if value:
            painted += 1
            values[value] = values.get(value, 0) + 1
    return {"triangles": triangles, "painted": painted, "values": values}


def _objects(root: ElementTree.Element) -> list[dict[str, Any]]:
    out = []
    for obj in root.iter(f"{_C}object"):
        comps = [{"objectid": c.get("objectid"), "path": c.get(f"{_P}path")}
                 for c in obj.iter(f"{_C}component")]
        out.append({"id": obj.get("id"), "name": obj.get("name"), "pid": obj.get("pid"),
                    "pindex": obj.get("pindex"), "has_mesh": obj.find(f"{_C}mesh") is not None,
                    "components": comps})
    return out


def _metadata_rows(el: ElementTree.Element) -> dict[str, str]:
    return {m.get("key", ""): m.get("value", "") for m in el.findall("metadata") if m.get("key")}


def _model_settings(blob: bytes) -> tuple[list[dict[str, Any]], set[str]]:
    """Objects (and their parts) with name and extruder, plus every metadata key seen."""
    root = _xml(blob)
    if root.tag != "config":
        raise ContainerError("bad_xml")
    keys: set[str] = set()
    objects = []
    for obj in root.findall("object"):
        rows = _metadata_rows(obj)
        keys |= set(rows)
        parts = []
        for part in obj.findall("part"):
            prow = _metadata_rows(part)
            keys |= set(prow)
            parts.append({"id": part.get("id"), "name": prow.get("name"), "extruder": _int(prow.get("extruder"))})
        objects.append({"id": obj.get("id"), "name": rows.get("name"), "extruder": _int(rows.get("extruder")),
                        "parts": parts})
    for plate in root.findall("plate"):
        keys |= set(_metadata_rows(plate))
        for inst in plate.findall("model_instance"):
            keys |= set(_metadata_rows(inst))
    return objects, keys


def _int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _palette(root: ElementTree.Element) -> list[dict[str, str]]:
    bases = [b for b in root.iter() if b.tag in (f"{_C}base", f"{_M}base")]
    return [{"name": b.get("name", ""), "colour": b.get("displaycolor", "")} for b in bases]


def _str_list(value: Any) -> list[str] | None:
    return [x for x in value] if isinstance(value, list) and all(isinstance(x, str) for x in value) else None


def _build(generator: str, data: bytes) -> CreativeProject:
    manifest = read_3mf(data)
    markers = markers_present(manifest)
    if generator not in markers:
        raise WrongShape(generator, sorted(manifest.parts))
    root = _xml(manifest.model_xml)
    meta = _model_metadata(root)
    settings = manifest.project_settings or {}
    facts: dict[str, Any] = {"application": meta.get("Application", ""), "markers_matched": markers[generator]}
    unknown: list[str] = []
    diagnostics: list[str] = []
    other = sorted(g for g in markers if g != generator)
    if other:
        diagnostics.append("markers_of_other_generators_present:" + ",".join(other))

    # -- geometry facts: main model plus every object part file (DitherForge keeps meshes there)
    models = [("3D/3dmodel.model", root)]
    for name in sorted(manifest.parts):
        if name.startswith("3D/Objects/") and name.endswith(".model"):
            try:
                models.append((name, _xml(manifest.parts[name])))
            except ContainerError:
                diagnostics.append(f"object_model_unreadable:{name}")
    stats = {"triangles": 0, "painted": 0, "values": {}}
    for _, tree in models:
        part = _mesh_stats(tree)
        stats["triangles"] += part["triangles"]
        stats["painted"] += part["painted"]
        for key, count in part["values"].items():
            stats["values"][key] = stats["values"].get(key, 0) + count
    objects = _objects(root)
    mesh_objects = [o for o in objects if o["has_mesh"]]
    decoded = {k: _decode_paint(k) for k in stats["values"]}
    undecoded = sorted(k for k, v in decoded.items() if v is None)
    slots_used = sorted({v for v in decoded.values() if v is not None})

    # -- model_settings.config
    ms_objects: list[dict[str, Any]] = []
    if MODEL_SETTINGS_PART in manifest.parts:
        try:
            ms_objects, ms_keys = _model_settings(manifest.parts[MODEL_SETTINGS_PART])
            for key in sorted(ms_keys - _KNOWN_MODEL_SETTINGS_KEYS[generator]):
                unknown.append(f"{MODEL_SETTINGS_PART} metadata key {key}")
        except ContainerError:
            diagnostics.append("model_settings_unreadable")
    missing = [p for p in _EXPECTED_PARTS[generator] if p not in manifest.parts]

    if generator == "ditherforge":
        app = facts["application"]
        facts["variant"] = "bambu_project" if app.startswith("BambuStudio-") else "generic"
        facts["designer"] = meta.get("Designer", "")
        facts["build_item_count"] = len(list(root.iter(f"{_C}item")))
        facts["object_part_files"] = [n for n, _ in models[1:]]
        facts["triangle_count"] = stats["triangles"]
        facts["per_face_paint"] = stats["painted"] > 0
        facts["painted_triangle_count"] = stats["painted"]
        facts["paint_extruders_used"] = slots_used
        facts["objects"] = [{"name": o["name"], "extruder": o["extruder"]} for o in ms_objects]
    elif generator == "kromacut":
        facts["layer_object_count"] = len(mesh_objects)
        facts["assembly_present"] = any(o["components"] for o in objects)
        for key, fact in (("slic3rpe:layer_height", "layer_height"),
                          ("slic3rpe:first_layer_height", "first_layer_height"),
                          ("Kromacut:SmoothMeshingStrength", "smooth_meshing_strength")):
            if key in meta:
                facts[fact] = meta[key]
        parts = [part for o in ms_objects for part in o["parts"]]
        facts["parts"] = [{"name": p["name"], "extruder": p["extruder"]} for p in parts]
        facts["palette"] = _palette(root)
        facts["per_face_paint"] = stats["painted"] > 0
        if KROMACUT_CONFIG_PART in manifest.parts:
            unknown.append(f"{KROMACUT_CONFIG_PART} payload (format not documented in the exporter output)")
    else:  # sindricad
        bodies = []
        for o in mesh_objects:
            ext = next((m["extruder"] for m in ms_objects if m["id"] == o["id"]), None)
            slot = _int(o["pindex"])
            bodies.append({"name": o["name"], "palette_slot": slot, "extruder": ext})
            if ext is not None and slot is not None and ext != slot + 1:
                diagnostics.append(f"extruder_disagrees_with_palette_slot:{o['name']}")
        facts["body_count"] = len(mesh_objects)
        facts["bodies"] = bodies
        facts["palette"] = _palette(root)
        facts["per_face_paint"] = stats["painted"] > 0
        facts["painted_triangle_count"] = stats["painted"]
        facts["paint_extruders_used"] = slots_used
    if undecoded:
        unknown.append("paint_color values not decoded: " + ", ".join(undecoded[:8]))

    known_keys = _KNOWN_SETTINGS_KEYS[generator]
    understood: dict[str, Any] = dict(facts)
    for key in known_keys:
        if key in settings:
            value = settings[key]
            if key in ("filament_colour", "filament_type"):
                value = _str_list(value)
                if value is None:
                    unknown.append(f"{key} (not a list of strings)")
                    continue
            understood[key] = value
    passed = tuple({"name": m.name, "sha256": m.sha256} for m in manifest.passed_through)
    passed += tuple({"name": k, "sha256": _digest_obj({k: v})["sha256"]}
                    for k, v in sorted(settings.items()) if k not in understood)
    project = CreativeProject(generator, _digest_obj(settings), understood, passed, tuple(unknown),
                              tuple(missing), tuple(diagnostics))
    return project


def read_ditherforge(data: bytes) -> CreativeProject:
    """DitherForge 3MF: Application `ditherforge-<semver>` (generic) or `BambuStudio-<v>+ditherforge-<semver>`."""
    return _build("ditherforge", data)


def read_kromacut(data: bytes) -> CreativeProject:
    """Kromacut 3MF: Application `Kromacut_Print`, `xmlns:Kromacut`, or `Metadata/kromacut.config`."""
    return _build("kromacut", data)


def read_sindricad(data: bytes) -> CreativeProject:
    """SindriCAD 3MF: Application `SindriCAD`; bodies with `pindex` and extruder rows."""
    return _build("sindricad", data)
