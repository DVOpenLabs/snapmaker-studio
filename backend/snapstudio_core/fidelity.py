"""Fidelity audit — what actually survived preparing a copy.

Every converter in this space tells a user the same thing: *converted*. None of
them tells the user what that cost. The interesting question is not "did it
work" — it is "what is different now, and what could not be carried over at all".

This module answers that by comparing the original project with the prepared copy
and classifying every element it can identify:

* ``preserved_exact``     — byte-identical
* ``preserved_semantic``  — the bytes moved but the meaning did not
* ``changed``             — deliberately different, with the reason
* ``removed``             — deliberately dropped, with the reason
* ``added``               — the prepared copy carries something new
* ``unsupported``         — data Studio does not understand well enough to judge
* ``unverified``          — Studio could not confirm either way

The last two categories are the point. A report that can only say "preserved" or
"changed" has to lie about the parts it does not understand, and those are
exactly the parts — Full Spectrum data, a slicer extension nobody has documented,
a vendor's private metadata — where a user most needs to know that nobody checked.

**Studio never claims nothing was lost unless this audit proves it for that
project.** ``claims`` at the end of the report is what public copy is allowed to
say, computed rather than asserted.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .container import ThreeMF
from .errors import UnsafeArchive

SCHEMA_VERSION = "fidelity/1"

PRESERVED_EXACT = "preserved_exact"
PRESERVED_SEMANTIC = "preserved_semantic"
CHANGED = "changed"
REMOVED = "removed"
ADDED = "added"
UNSUPPORTED = "unsupported"
UNVERIFIED = "unverified"

# Order for display: what a user needs to see first.
_ORDER = {UNVERIFIED: 0, UNSUPPORTED: 1, REMOVED: 2, CHANGED: 3,
          ADDED: 4, PRESERVED_SEMANTIC: 5, PRESERVED_EXACT: 6}

PROJECT_SETTINGS = "Metadata/project_settings.config"
MODEL_SETTINGS = "Metadata/model_settings.config"
SLICE_INFO = "Metadata/slice_info.config"
ROOT_MODEL = "3D/3dmodel.model"

_PLATE_GCODE_RE = re.compile(r"^Metadata/plate_\d+\.(gcode|json)$")
_PLATE_IMAGE_RE = re.compile(r"^Metadata/(plate|top|pick)_\d+.*\.png$")

# Parts Studio deliberately rewrites or drops, and why. Anything changed that is
# not in this table is reported as unverified rather than excused.
_INTENTIONAL = {
    PROJECT_SETTINGS: ("the U1 machine profile and Snapmaker Orca import fixes are "
                       "applied here"),
    SLICE_INFO: ("the authoring slicer's version stamp is blanked so Snapmaker Orca "
                 "does not refuse the project as newer than itself"),
    ROOT_MODEL: "object placement is rewritten only when a placement fix was applied",
}

_HUMAN = {
    "[Content_Types].xml": "Archive index",
    "_rels/.rels": "Archive relationships",
    "3D/_rels/3dmodel.model.rels": "Model relationships",
    PROJECT_SETTINGS: "Print settings",
    MODEL_SETTINGS: "Per-object settings and plate layout",
    SLICE_INFO: "Slicing summary recorded by the original slicer",
    ROOT_MODEL: "Model geometry and object placement",
}


def _row(element: str, status: str, *, detail: str, reason: str | None = None,
         part: str | None = None) -> dict:
    """One fact, answered twice.

    `status` is Studio's own comparison of the two files. `target` is whether
    Snapmaker Orca was measured to act on the fact at all — a separate question,
    and the one a copy can pass on paper while failing on the plate. A row nobody
    has measured carries no target verdict rather than a reassuring one.
    """
    from . import target_reachability

    target, target_detail = target_reachability.of(element)
    return {"element": element, "status": status, "detail": detail,
            "reason": reason, "part": part,
            "target": target, "target_detail": target_detail}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _human(part: str) -> str:
    if part in _HUMAN:
        return _HUMAN[part]
    if _PLATE_GCODE_RE.match(part):
        return "Sliced output from the original printer"
    if _PLATE_IMAGE_RE.match(part):
        return "Plate picture"
    if part.startswith("3D/Textures/"):
        return "Texture image"
    if part.startswith("3D/Objects/"):
        return "Mesh data"
    if part.startswith("Auxiliaries/"):
        return "Extra files packaged with the project"
    return part


def _json_or_none(tm: ThreeMF, part: str):
    if not tm.has_part(part):
        return None
    try:
        return json.loads(tm.read_part(part).decode("utf-8", "ignore"))
    except Exception:
        return None


def _text(tm: ThreeMF, part: str) -> str:
    if not tm.has_part(part):
        return ""
    try:
        return tm.read_part(part).decode("utf-8", "ignore")
    except Exception:
        return ""


# --- part-by-part -----------------------------------------------------------

def _classify_part(part: str, before: bytes, after: bytes | None,
                   placement_applied: bool, moved: tuple = (b"", b"")) -> dict:
    name = _human(part)
    if after is None:
        if _PLATE_GCODE_RE.match(part):
            return _row(name, REMOVED, part=part,
                        detail="dropped from the prepared copy",
                        reason=("these toolpaths were generated for the original "
                                "printer, so Snapmaker Orca must slice again for the U1"))
        return _row(name, UNVERIFIED, part=part,
                    detail="present in the original, missing from the prepared copy",
                    reason="Studio cannot account for this — report it as a bug")
    if before == after:
        return _row(name, PRESERVED_EXACT, part=part,
                    detail="byte-for-byte identical")
    if part == ROOT_MODEL:
        return _model_part_row(part, before, after, placement_applied, moved)
    if part in _INTENTIONAL:
        return _row(name, CHANGED, part=part, detail="rewritten by Studio",
                    reason=_INTENTIONAL[part])
    if part.startswith("3D/Objects/"):
        return _row(name, UNVERIFIED, part=part,
                    detail="mesh data differs and Studio did not intend to change it",
                    reason="Studio does not rewrite mesh parts — report this as a bug")
    return _row(name, UNVERIFIED, part=part, detail="content differs",
                reason="Studio has no rule that should have changed this part")


_VERTEX_RE = re.compile(rb"<vertex\b")
_TRIANGLE_RE = re.compile(rb"<triangle\b")
_ITEM_RE = re.compile(rb"<item\b")
_PAINT_RE = re.compile(rb"paint_color|paint_supports|mmu_segmentation|paint_seam")


def _model_part_row(part: str, before: bytes, after: bytes,
                    placement_applied: bool, moved: tuple = (b"", b"")) -> dict:
    """The root model changes only when placement was rewritten. Geometry itself
    must be identical either way, and that is checked rather than assumed.

    A multi-part copy moves the meshes out of the root and into their own object
    file, so counting only the root sees every facet disappear and reports a copy
    that is perfectly intact as unverified. The parts that hold the geometry are
    counted with it, wherever the geometry ended up.
    """
    moved_before, moved_after = moved
    before, after = before + moved_before, after + moved_after
    counts_before = (len(_VERTEX_RE.findall(before)), len(_TRIANGLE_RE.findall(before)),
                     len(_ITEM_RE.findall(before)), len(_PAINT_RE.findall(before)))
    counts_after = (len(_VERTEX_RE.findall(after)), len(_TRIANGLE_RE.findall(after)),
                    len(_ITEM_RE.findall(after)), len(_PAINT_RE.findall(after)))
    if counts_before != counts_after:
        return _row(_human(part), UNVERIFIED, part=part,
                    detail=(f"vertices/triangles/objects/painted markers went from "
                            f"{counts_before} to {counts_after}"),
                    reason="Studio does not add or remove geometry — report this as a bug")
    if placement_applied:
        return _row(_human(part), CHANGED, part=part,
                    detail="the same geometry, moved to different coordinates",
                    reason="a placement fix moved the objects onto the U1 plate")
    if moved_after and not moved_before:
        return _row(_human(part), PRESERVED_SEMANTIC, part=part,
                    detail="the same geometry, split into one mesh per part",
                    reason=("the copy holds each part's mesh in its own object file "
                            "and the root references them; the facet, vertex and "
                            "painted-marker counts are unchanged"))
    return _row(_human(part), PRESERVED_SEMANTIC, part=part,
                detail="the same geometry, re-serialised",
                reason="the mesh, object count and painted markers are unchanged")


# --- semantic elements ------------------------------------------------------

# Settings other slicers write and Snapmaker Orca does not; each has its own wording, not the "original printer" one.
NOT_WRITTEN_BY_ORCA = frozenset({"nozzle_volume_type"})


def _settings_row(before: dict | None, after: dict | None) -> list[dict]:
    if before is None or after is None:
        return [_row("Print settings", UNVERIFIED,
                     detail="one of the projects has no readable print settings")]
    changed = sorted(k for k in set(before) & set(after)
                     if before[k] != after[k])
    kept = sum(1 for k in before if k in after and after[k] == before[k])
    dropped = sorted(k for k in before if k not in after)
    added = sorted(k for k in after if k not in before)
    rows = [_row("Print settings kept", PRESERVED_EXACT,
                 detail=f"{kept} setting(s) carried over unchanged")]
    if changed:
        rows.append(_row("Print settings changed", CHANGED,
                         detail=f"{len(changed)} setting(s) differ: "
                                + ", ".join(changed[:8])
                                + (" …" if len(changed) > 8 else ""),
                         reason=("U1 machine profile, Snapmaker Orca import fixes, or "
                                 "Studio-recommended settings if you chose them")))
    not_written = [k for k in dropped if k in NOT_WRITTEN_BY_ORCA]
    dropped = [k for k in dropped if k not in NOT_WRITTEN_BY_ORCA]
    if dropped:
        rows.append(_row("Print settings not carried over", REMOVED,
                         detail=f"{len(dropped)} setting(s): " + ", ".join(dropped[:8])
                                + (" …" if len(dropped) > 8 else ""),
                         reason=("these belong to the original printer and have no "
                                 "meaning on a U1")))
    if not_written:
        rows.append(_row("Print settings Snapmaker Orca does not write", REMOVED,
                         detail=f"{len(not_written)} setting(s): " + ", ".join(not_written),
                         reason=("projects saved by Snapmaker Orca do not contain these; leaving them out is not "
                                 "confirmed in Snapmaker Orca to change how the copy opens")))
    if added:
        rows.append(_row("Print settings added", ADDED,
                         detail=f"{len(added)} setting(s): " + ", ".join(added[:8])
                                + (" …" if len(added) > 8 else ""),
                         reason="required by the U1 profile"))
    return rows


def _count_row(label: str, before: int, after: int, *, unchanged_reason: str,
               changed_reason: str) -> dict:
    if before == after:
        return _row(label, PRESERVED_EXACT, detail=f"{before} before and after",
                    reason=unchanged_reason)
    return _row(label, CHANGED, detail=f"{before} → {after}", reason=changed_reason)


def _logical_objects(tm: ThreeMF) -> int:
    """How many objects a person would say the project holds.

    A composite object built from components is one object however many meshes it
    references; a project that has no composites is counted by its meshes.
    """
    try:
        root = _text(tm, ROOT_MODEL)
    except Exception:
        return 0
    composites = re.findall(r'<object id="[0-9]+"[^>]*>\s*<components>', root)
    if composites:
        return len(composites)
    total = len(re.findall(r"<object[^>]*>", root))
    for part in tm.list_parts():
        if part.startswith(OBJECTS_DIR):
            total += len(re.findall(
                r"<object[^>]*>", tm.read_part(part).decode("utf-8", "ignore")))
    return total


def _semantic_rows(a: ThreeMF, b: ThreeMF) -> list[dict]:
    from .fingerprint import compute_fingerprint

    rows: list[dict] = []
    try:
        fa, fb = compute_fingerprint(a), compute_fingerprint(b)
    except Exception:
        return [_row("Objects, plates and colours", UNVERIFIED,
                     detail="Studio could not read one of the projects well enough to compare")]

    # How many objects the person has, not how many `<object>` elements are in the
    # file. A prepared copy states each object as a composite plus one mesh object
    # per part, so counting elements makes three objects look like seven.
    rows.append(_count_row("Objects", _logical_objects(a), _logical_objects(b),
                           unchanged_reason="every object in the original is in the copy",
                           changed_reason="Studio does not add or remove objects — "
                                          "report this as a bug"))
    # Painted colour used to be compared by counting how often a marker appeared
    # in the bytes, which cannot tell a preserved painting from a rewritten one.
    # It is compared properly in _painted_rows; what stays here is the marker for
    # the other kinds of painting — supports and seams — which Studio does not
    # decode and therefore does not claim to have checked semantically.
    other_paint_a = sum(_other_paint_markers(a).values())
    other_paint_b = sum(_other_paint_markers(b).values())
    if other_paint_a or other_paint_b:
        rows.append(_count_row("Painted supports and seams", other_paint_a, other_paint_b,
                               unchanged_reason="the same number of marked facets, and "
                                                "Studio does not decode these",
                               changed_reason="Studio does not repaint models — "
                                              "report this as a bug"))
    rows.append(_count_row("Filament slots", fa.filament_count, fb.filament_count,
                           unchanged_reason="every colour slot survives, in its original order",
                           changed_reason="a filament remap was applied"))
    if fa.filament_colors and fb.filament_colors:
        if tuple(fa.filament_colors) == tuple(fb.filament_colors):
            rows.append(_row("Filament colours", PRESERVED_EXACT,
                             detail=f"{len(fa.filament_colors)} colour(s), same values in "
                                    "the same order"))
        else:
            rows.append(_row("Filament colours", CHANGED,
                             detail="the colour list differs",
                             reason="a filament remap or preset normalisation was applied"))

    # Per-object records: plate assignment, tool assignment, per-object overrides.
    ms_a, ms_b = _text(a, MODEL_SETTINGS), _text(b, MODEL_SETTINGS)
    if ms_a and ms_b:
        plates_a = len(re.findall(r"<plate\b", ms_a))
        plates_b = len(re.findall(r"<plate\b", ms_b))
        rows.append(_count_row("Plates", plates_a, plates_b,
                               unchanged_reason="the plate layout is unchanged",
                               changed_reason="Studio does not add or remove plates — "
                                              "report this as a bug"))
        extruders_a = re.findall(r'key="extruder"\s+value="(\d+)"', ms_a)
        extruders_b = re.findall(r'key="extruder"\s+value="(\d+)"', ms_b)
        if extruders_a == extruders_b:
            rows.append(_row("Which colour each object uses", PRESERVED_EXACT,
                             detail=f"{len(extruders_a)} assignment(s) unchanged"))
        else:
            rows.append(_row("Which colour each object uses", CHANGED,
                             detail=f"{len(extruders_a)} → {len(extruders_b)} assignment(s) "
                                    "or different values",
                             reason="a plate colour remap was applied"))
    elif ms_a and not ms_b:
        rows.append(_row("Per-object settings and plate layout", REMOVED,
                         detail="present in the original, absent from the copy",
                         reason="Studio cannot account for this — report it as a bug"))
    return rows


# --- optional data other tools rely on --------------------------------------

_OPTIONAL = {
    "Metadata/layer_heights_profile.txt": "Variable layer height profile",
    "Metadata/custom_gcode_per_layer.xml": "Colour changes and pauses at set layers",
    "Metadata/layer_config_ranges.xml": "Per-height setting ranges",
    "Metadata/brim_ear_points.txt": "Brim ear positions",
    "Metadata/cut_information.xml": "Cut information",
    "Metadata/filament_sequence.json": "Filament sequence",
}


def _optional_rows(a: ThreeMF, b: ThreeMF) -> list[dict]:
    """Data a creator spent time on that a converter can silently drop."""
    rows = []
    for part, label in _OPTIONAL.items():
        in_a, in_b = a.has_part(part), b.has_part(part)
        if not in_a and not in_b:
            continue
        if in_a and not in_b:
            rows.append(_row(label, REMOVED, part=part,
                             detail="present in the original, absent from the copy",
                             reason="Studio did not intend to drop this — report it as a bug"))
        elif in_a and in_b:
            same = a.read_part(part) == b.read_part(part)
            rows.append(_row(label, PRESERVED_EXACT if same else UNVERIFIED, part=part,
                             detail="byte-for-byte identical" if same else "content differs",
                             reason=None if same else
                             "Studio has no rule that should have changed this"))
        else:
            rows.append(_row(label, ADDED, part=part,
                             detail="only in the prepared copy"))
    return rows


def _unsupported_rows(a: ThreeMF) -> list[dict]:
    """Anything the original declares that Studio does not understand.

    A required 3MF extension Studio has never seen means there may be data in the
    file it neither read nor checked, and saying so is the whole point of this
    report.
    """
    from . import project_traits

    rows = []
    head = _text(a, ROOT_MODEL)[:project_traits._MODEL_HEAD_BYTES]
    tag = re.search(r"<model\b[^>]*>", head, re.S)
    if tag:
        attrs = project_traits._attrs(tag.group(0))
        prefixes = [p for p in re.split(r"\s+", attrs.get("requiredextensions", "").strip()) if p]
        declared = {k.split(":", 1)[1]: v for k, v in attrs.items() if k.startswith("xmlns:")}
        unknown = [declared.get(p, p) for p in prefixes
                   if declared.get(p, p) not in project_traits._KNOWN_EXTENSIONS]
        if unknown:
            rows.append(_row("Slicer extensions Studio does not understand", UNSUPPORTED,
                             detail=", ".join(unknown),
                             reason=("this project requires a 3MF extension Studio has no "
                                     "reader for, so any data it carries was copied "
                                     "verbatim but never checked")))

    # PrusaSlicer stores several things Snapmaker Orca has no equivalent for. The
    # copy is still usable; saying which parts did not survive is the whole point
    # of this report, and it is better said here than discovered on the plate.
    rows.extend(_prusa_rows(a))
    return rows


def _prusa_rows(tm) -> list[dict]:
    from . import prusa

    try:
        parts = set(tm.list_parts())
        if prusa.SETTINGS_PART not in parts:
            return []
        settings_raw = tm.read_part(prusa.SETTINGS_PART)
        model_raw = tm.read_part(prusa.MODEL_CONFIG_PART) if prusa.MODEL_CONFIG_PART in parts else None
        summary = prusa.summarise(settings_raw, model_raw)
    except Exception:
        return []

    return [_row(item["element"], UNSUPPORTED, detail="from PrusaSlicer",
                 reason=item["reason"])
            for item in prusa.not_carried(summary)]


# --- entry point ------------------------------------------------------------

def audit(original: str, prepared: str, materials: dict | None = None) -> dict:
    """Compare an original project with a prepared copy. Never raises.

    `materials` is the Project Materials record Prepare returned. It is cleaned and checked
    against the prepared file, then attached as `materials` (the schema becomes fidelity/2).
    Without it the report is exactly what it always was."""
    try:
        a = ThreeMF.open(original)
    except UnsafeArchive as e:
        return _unavailable(str(e))
    except Exception:
        return _unavailable("Studio could not open the original as a 3MF project.")
    try:
        b = ThreeMF.open(prepared)
    except UnsafeArchive as e:
        return _unavailable(str(e))
    except Exception:
        return _unavailable("Studio could not open the prepared copy as a 3MF project.")

    parts_a, parts_b = a.list_parts(), b.list_parts()
    set_b = set(parts_b)

    placement_applied = False
    if a.has_part(ROOT_MODEL) and b.has_part(ROOT_MODEL):
        placement_applied = _placement_moved(a.read_part(ROOT_MODEL), b.read_part(ROOT_MODEL))

    # Geometry a multi-part copy moved out of the root, on each side, so the
    # row about the root model can count what the root no longer holds.
    moved = (b"".join(a.read_part(p) for p in parts_a if p.startswith(OBJECTS_DIR)),
             b"".join(b.read_part(p) for p in parts_b if p.startswith(OBJECTS_DIR)))

    rows: list[dict] = []
    for part in parts_a:
        if part.endswith("/") or part == PROJECT_SETTINGS:
            continue
        after = b.read_part(part) if part in set_b else None
        rows.append(_classify_part(part, a.read_part(part), after, placement_applied,
                                   moved))
    for part in parts_b:
        if part.endswith("/") or part in set(parts_a):
            continue
        rows.append(_row(_human(part), ADDED, part=part,
                         detail="only in the prepared copy",
                         reason="added while preparing the U1 copy"))

    rows += _settings_rows(a, b)
    rows += _part_shape_rows(a, b)
    rows += _semantic_rows(a, b)
    rows += _painted_rows(a, b)
    rows += _assignment_rows(a, b)
    rows += _optional_rows(a, b)
    rows += _unsupported_rows(a)

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    ordered = sorted(rows, key=lambda r: (_ORDER[r["status"]], r["element"]))
    claims = _claims(counts)
    report = {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "original": Path(original).name,
        "prepared": Path(prepared).name,
        "rows": ordered,
        "counts": counts,
        "kept": [r for r in ordered if r["status"] in (PRESERVED_EXACT, PRESERVED_SEMANTIC)],
        "changed": [r for r in ordered if r["status"] in (CHANGED, ADDED)],
        "not_carried": [r for r in ordered if r["status"] in (REMOVED, UNSUPPORTED)],
        "unverified": [r for r in ordered if r["status"] == UNVERIFIED],
        "claims": claims,
        # Whether the copy fits the printer's plate is not a comparison between the
        # two files: Studio can preserve a placement perfectly and the target still
        # be unable to print it there. It is reported beside the rows rather than
        # as one of them, so a preserved placement is never counted as a loss.
        "placement": _placement_report(prepared),
        "summary": _summary(counts, claims),
        "disclaimer": ("This compares what Studio can identify in both files. Anything it "
                       "could not identify is listed as unverified rather than assumed to "
                       "be fine."),
    }
    if materials is not None:
        from . import materials_fidelity
        report = materials_fidelity.attach(report, materials, b, a)
    return report


#: Splitting a mesh costs about what preparing it did, so a project far larger
#: than anything a person hands a slicer is reported rather than re-split here.
_MAX_FACETS_TO_RESPLIT = 200_000
OBJECTS_DIR = "3D/Objects/"
PRUSA_MODEL_CONFIG = "Metadata/Slic3r_PE_model.config"


_PAINT_VALUE = re.compile(r'(?:paint_color|slic3rpe:mmu_segmentation)="([^"]*)"')


def _paint_of(triangles: list[str]) -> list[str]:
    """One entry per facet: its paint value, or empty where it is unpainted.

    Position matters as much as the values do. A copy that carries every painted
    value but hangs them on different facets has moved the colour, and comparing
    only the set of values would call that preserved.
    """
    out = []
    for tag in triangles:
        found = _PAINT_VALUE.search(tag)
        out.append(found.group(1) if found else "")
    return out


def _prepared_objects(tm: ThreeMF) -> list[dict] | None:
    """Each prepared object: its parts, their shapes, their painting, its place.

    Keyed by the object the metadata declares, because a project may hold several
    and a total across all of them hides one object's parts landing under
    another's.
    """
    from . import multipart

    settings = _text(tm, "Metadata/model_settings.config")
    root = _text(tm, ROOT_MODEL)
    if not settings or not root:
        return None
    by_object = multipart._parts_by_object(settings)
    if not by_object:
        return None

    shapes: dict[str, tuple] = {}
    for name in sorted(p for p in tm.list_parts() if p.startswith(OBJECTS_DIR)):
        body = tm.read_part(name).decode("utf-8", "ignore")
        for mesh_id in re.findall(r'<object id="(\d+)"', body):
            block = re.search(rf'<object id="{mesh_id}".*?</object>', body, re.S)
            if not block:
                continue
            vertices, triangles = multipart.read_mesh(block.group(0))
            shapes[mesh_id] = (multipart.geometry_digest(vertices, triangles),
                               _paint_of(triangles))
    if not shapes:
        return None

    placements = dict(re.findall(
        r'<item[^>]* objectid="([0-9]+)"[^>]* transform="([^"]*)"', root))
    out = []
    for object_id, parts in by_object.items():
        rows = [shapes.get(part_id) for part_id, _subtype in parts]
        if any(row is None for row in rows):
            return None
        out.append({
            "object_id": object_id,
            "part_ids": [part_id for part_id, _s in parts],
            "digests": [row[0] for row in rows],
            "paint": [row[1] for row in rows],
            "transform": placements.get(object_id),
        })
    return out


def _source_objects(tm: ThreeMF) -> list[dict] | None:
    """Each source object's volumes, cut out of the one mesh PrusaSlicer wrote.

    The source states its volumes as inclusive triangle ranges over a single mesh
    per object, so the only way to compare a part with the volume it came from is
    to cut the same ranges again and hash what falls out. Vertex numbering is
    renumbered by the split on both sides, which is why the digest hashes
    coordinates.
    """
    from . import multipart

    if not tm.has_part(PRUSA_MODEL_CONFIG) or not tm.has_part(ROOT_MODEL):
        return None
    config = tm.read_part(PRUSA_MODEL_CONFIG).decode("utf-8", "ignore")
    volumes_by_object = multipart.source_volumes(config)
    if not volumes_by_object:
        return None
    names = dict(re.findall(
        r'<object id="([^"]+)"[^>]*>\s*<metadata type="object" key="name" '
        r'value="([^"]*)"', config))

    root = tm.read_part(ROOT_MODEL).decode("utf-8", "ignore")
    ids = re.findall(r'<object[^>]* id="([0-9]+)"[^>]*>.*?</object>', root, re.S)
    bodies = re.findall(r"<object[^>]*>.*?</object>", root, re.S)
    if len(ids) != len(bodies):
        return None
    placements = dict(re.findall(
        r'<item[^>]* objectid="([0-9]+)"[^>]* transform="([^"]*)"', root))

    out = []
    for source_id, body in zip(ids, bodies):
        volumes = volumes_by_object.get(source_id)
        if not volumes:
            return None
        vertices, triangles = multipart.read_mesh(body)
        if len(triangles) > _MAX_FACETS_TO_RESPLIT:
            return None
        parts = multipart.split_triangles(
            vertices, triangles, [v["range"] for v in volumes])
        out.append({
            "object_id": source_id,
            "name": names.get(source_id) or f"object {source_id}",
            "digests": [multipart.geometry_digest(p["vertices"], p["triangles"])
                        for p in parts],
            "paint": [_paint_of(p["triangles"]) for p in parts],
            "transform": placements.get(source_id),
        })
    return out


def _part_shape_rows(a: ThreeMF, b: ThreeMF) -> list[dict]:
    """Does each object's every part hold the shape, colour and place it came from?

    A part record and a mesh can agree with each other and still describe the
    wrong solid, and a project's totals can be right while two objects have
    swapped their parts. So each source object is answered for itself.
    """
    try:
        source = _source_objects(a)
        prepared = _prepared_objects(b)
    except Exception:
        return []
    if not source or not prepared:
        return []

    if len(source) != len(prepared):
        return [_row("Objects carried", CHANGED,
                     detail=(f"the source has {len(source)} object(s) and the copy "
                             f"{len(prepared)}"),
                     reason="Studio writes one prepared object per source object")]

    rigid = _rigid_offset(source, prepared)
    rows = []
    for origin, copy in zip(source, prepared):
        name = origin["name"]
        if len(origin["digests"]) != len(copy["digests"]):
            rows.append(_row(f"The parts of {name}", CHANGED,
                             detail=(f"{len(origin['digests'])} volume(s) in the "
                                     f"source, {len(copy['digests'])} part(s) in the "
                                     "copy"),
                             reason="Studio writes one part per source volume"))
            continue

        wrong = [str(i + 1) for i, (x, y)
                 in enumerate(zip(origin["digests"], copy["digests"])) if x != y]
        rows.append(_row(
            f"The shape of each part of {name}",
            CHANGED if wrong else PRESERVED_EXACT,
            detail=(f"part(s) {', '.join(wrong)} hold different geometry" if wrong
                    else f"all {len(origin['digests'])} part(s) hold the facets of "
                         "the volume they came from, in winding order"),
            reason=("each part must hold the facets of the volume it came from — "
                    "report this as a bug") if wrong else None))

        if any(any(value for value in values) for values in origin["paint"]):
            moved = [str(i + 1) for i, (x, y)
                     in enumerate(zip(origin["paint"], copy["paint"])) if x != y]
            rows.append(_row(
                f"The painting on each part of {name}",
                CHANGED if moved else PRESERVED_EXACT,
                detail=(f"part(s) {', '.join(moved)} carry different painting than "
                        "the volume they came from" if moved
                        else "every painted facet kept its colour and its place in "
                             "the part it came from"),
                reason=("a facet's colour crosses with that facet — report this as "
                        "a bug") if moved else None))

        if origin["transform"] and copy["transform"]:
            rows.append(_placement_row(name, origin["transform"], copy["transform"],
                                       rigid))
    return rows


def _rigid_offset(source: list[dict], prepared: list[dict]) -> tuple | None:
    """The one translation every object moved by, if there is one.

    A whole plate moved together keeps every distance and every orientation
    somebody chose, so it is a different fact from one object drifting away from
    the others — and it is what an explicit "move onto the plate" does.
    """
    from . import placement

    offsets = set()
    for origin, copy in zip(source, prepared):
        one = placement.parse_transform(origin.get("transform"))
        two = placement.parse_transform(copy.get("transform"))
        if one is None or two is None:
            return None
        if one[0] != two[0] or one[1] != two[1] or one[2] != two[2]:
            return None                       # a rotation or a scale, not a move
        if abs(two[3][2] - one[3][2]) > placement.TOLERANCE:
            return None                       # height changed; not a plate move
        offsets.add((round(two[3][0] - one[3][0], 4), round(two[3][1] - one[3][1], 4)))
    if len(offsets) != 1:
        return None
    dx, dy = offsets.pop()
    if abs(dx) <= placement.TOLERANCE and abs(dy) <= placement.TOLERANCE:
        return None
    return dx, dy


def _placement_row(name: str, before: str, after: str, rigid: tuple | None) -> dict:
    from . import placement

    if before == after:
        return _row(f"Where {name} sits on the plate", PRESERVED_EXACT,
                    detail="placed exactly where the source placed it")
    if rigid:
        dx, dy = rigid
        return _row(f"Where {name} sits on the plate", PRESERVED_SEMANTIC,
                    detail=(f"moved with the rest of the plate, "
                            f"{placement._offset(dx, dy)}"),
                    reason=("the whole arrangement moved together, so every distance "
                            "and every orientation is as it was — this is what "
                            "moving a project onto the printer's plate does"))
    return _row(f"Where {name} sits on the plate", CHANGED,
                detail=f"{before} → {after}",
                reason=("Studio does not move objects while preparing them, and this "
                        "one did not move with the rest of the plate — report this as "
                        "a bug"))


def _placement_report(prepared: str) -> dict | None:
    from . import placement

    try:
        report = placement.assess(prepared)
    except Exception:  # noqa: BLE001 — a report, never a crash
        return None
    return report if report.get("available") else None


def _settings_rows(a: ThreeMF, b: ThreeMF) -> list[dict]:
    return _settings_row(_json_or_none(a, PROJECT_SETTINGS), _json_or_none(b, PROJECT_SETTINGS))


def _placement_moved(before: bytes, after: bytes) -> bool:
    """True when the build-item transforms differ but nothing else about the
    geometry does — i.e. a placement fix ran."""
    grab = lambda raw: re.findall(rb'<item\b[^>]*transform="([^"]*)"', raw)
    return grab(before) != grab(after)


def _claims(counts: dict) -> dict:
    """What Studio is allowed to say about this project, computed not asserted."""
    nothing_unverified = counts.get(UNVERIFIED, 0) == 0
    nothing_removed = counts.get(REMOVED, 0) == 0
    nothing_unsupported = counts.get(UNSUPPORTED, 0) == 0
    return {
        "geometry_unchanged": nothing_unverified,
        "nothing_removed": nothing_removed and nothing_unsupported,
        "fully_accounted": nothing_unverified,
        "may_claim_nothing_lost": nothing_unverified and nothing_removed and nothing_unsupported,
    }


def _summary(counts: dict, claims: dict) -> str:
    kept = counts.get(PRESERVED_EXACT, 0) + counts.get(PRESERVED_SEMANTIC, 0)
    changed = counts.get(CHANGED, 0) + counts.get(ADDED, 0)
    removed = counts.get(REMOVED, 0)
    unsupported = counts.get(UNSUPPORTED, 0)
    unverified = counts.get(UNVERIFIED, 0)
    parts = [f"{kept} element(s) kept", f"{changed} changed"]
    if removed:
        parts.append(f"{removed} not carried over")
    if unsupported:
        parts.append(f"{unsupported} Studio does not understand")
    if unverified:
        parts.append(f"{unverified} Studio could not verify")
    text = ", ".join(parts) + "."
    if claims["may_claim_nothing_lost"]:
        return text + " Everything Studio can identify is accounted for."
    if unverified:
        return text + " Some elements could not be accounted for — check them yourself."
    return text + " The elements that were not carried over are listed with the reason."


def _unavailable(reason: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "available": False, "reason": reason,
            "rows": [], "counts": {}, "kept": [], "changed": [], "not_carried": [],
            "unverified": [],
            "claims": {"geometry_unchanged": False, "nothing_removed": False,
                       "fully_accounted": False, "may_claim_nothing_lost": False},
            "summary": reason}


# --- painted colour ---------------------------------------------------------
#
# Painting is exactly the kind of work a converter can destroy quietly: the mesh
# survives, the file opens, and the hours someone spent painting it are gone. So
# this does not ask whether the geometry survived. It compares the painting
# itself — every slot, every facet, every painted area — and it will not call
# painting preserved because the triangles are still there.

_OTHER_PAINT_MARKERS = (b"paint_supports", b"paint_seam",
                        b"slic3rpe:custom_supports", b"slic3rpe:custom_seam")


def _other_paint_markers(tm: ThreeMF) -> dict:
    """Support and seam painting, which Studio counts but does not decode."""
    out = {}
    for part in tm.list_parts():
        if not part.lower().endswith(".model"):
            continue
        try:
            blob = tm.read_part(part)
        except Exception:
            continue
        count = sum(blob.count(marker) for marker in _OTHER_PAINT_MARKERS)
        if count:
            out[part] = count
    return out


def _paint_attributes(tm: ThreeMF) -> list[str]:
    """Every paint attribute in the project, in the order the meshes carry them.

    Part names can legitimately change between an original and a copy, so the
    attributes are compared as a sequence of values rather than by where they
    live.
    """
    out: list[str] = []
    for part in sorted(tm.list_parts()):
        if not part.lower().endswith(".model"):
            continue
        try:
            blob = tm.read_part(part)
        except Exception:
            continue
        out += [match.group(1).decode("ascii", "ignore")
                for match in _PAINT_ATTR_RE.finditer(blob)]
    return out


_PAINT_ATTR_RE = re.compile(
    rb'(?:paint_color|slic3rpe:mmu_segmentation)="([^"]*)"')


def _paint_shape(result: dict, *, painted_only: bool = False) -> dict:
    """The meaning of a project's painting, independent of how it is written.

    Both what was painted and what was left for the mesh's own filament, because
    both are things a copy can get wrong. That was not always safe to compare: the
    source reader used to attribute every unpainted patch of an object to the
    first volume that stated a filament, so a copy that faithfully carried each
    part's own filament looked repainted by 50 mm². The reader answers per volume
    now and the two sides agree, so the comparison can include it again.

    `painted_only` drops the unpainted side for the cases where a project states
    no slot for it at all and the comparison would be between two unknowns.
    """
    areas: dict[int, float] = {}
    heights: dict[int, tuple] = {}
    for entry in result.get("objects") or ():
        for assignment in entry.get("assignments") or ():
            if assignment.get("slot") is None:
                continue
            if painted_only and not assignment.get("painted"):
                continue
            slot = assignment["slot"]
            areas[slot] = round(areas.get(slot, 0.0) + (assignment.get("area_mm2") or 0.0), 3)
            low, high = assignment.get("z_min_mm"), assignment.get("z_max_mm")
            if low is None:
                continue
            before = heights.get(slot)
            heights[slot] = ((low, high) if before is None
                             else (min(before[0], low), max(before[1], high)))
    return {
        "slots": sorted(areas),
        "facets": result.get("painted_triangle_count", 0),
        "areas": areas,
        "heights": heights,
    }


def _paint_dialect_reason(tm: ThreeMF) -> str | None:
    """Will the target act on this painting, or only carry it?

    Two things have to be true before Snapmaker Orca reads a facet's colour, and
    both were measured against Orca 2.3.5 by handing it one file at a time:

    * the attribute must be `paint_color`. The identical painting written as
      PrusaSlicer's `slic3rpe:mmu_segmentation` opened with nothing painted.
    * the mesh must be in its own object file behind a component. The identical
      painting, in `paint_color`, left in the root model opened with nothing
      painted; moved behind a component it opened complete.

    A row saying the painting is preserved is true of the two files either way,
    and is easy to read as a promise about the plate.
    """
    advice = ("The colours are in the file \u2014 paint them again in Orca, or keep "
              "slicing this one in PrusaSlicer")
    root_painted = False
    object_painted = False
    wrong_dialect = False
    for part in sorted(tm.list_parts()):
        if not part.lower().endswith(".model"):
            continue
        try:
            blob = tm.read_part(part)
        except Exception:
            continue
        painted = b'paint_color="' in blob or b'slic3rpe:mmu_segmentation="' in blob
        if not painted:
            continue
        if b'slic3rpe:mmu_segmentation="' in blob:
            wrong_dialect = True
        if part.startswith(OBJECTS_DIR):
            object_painted = True
        elif part == ROOT_MODEL:
            root_painted = True

    if wrong_dialect:
        return ("this is PrusaSlicer's way of writing painted colour and Snapmaker "
                "Orca reads its own; measured against Orca 2.3.5, the copy opens "
                "with no painting. " + advice)
    if root_painted and not object_painted:
        return ("the painted mesh is in the project's root rather than in its own "
                "object file, and measured against Orca 2.3.5 the painting is not "
                "read from there. " + advice)
    return None


def _painted_rows(a: ThreeMF, b: ThreeMF) -> list[dict]:
    from . import painted_color

    before, after = _paint_attributes(a), _paint_attributes(b)
    if not before and not after:
        return []
    if before and not after:
        return [_row("Painted colour", REMOVED,
                     detail=f"{len(before)} painted facet(s) in the original, none in "
                            "the copy",
                     reason="Studio does not remove painting — report this as a bug")]
    if after and not before:
        return [_row("Painted colour", ADDED,
                     detail=f"{len(after)} painted facet(s) only in the copy",
                     reason="Studio does not paint models — report this as a bug")]

    original = painted_color.read_container(a)
    copy = painted_color.read_container(b)
    if not original.get("available") or not copy.get("available"):
        return [_row("Painted colour", UNVERIFIED,
                     detail="one of the projects could not be read as painted data")]
    if original.get("truncated") or copy.get("truncated"):
        return [_row("Painted colour", UNVERIFIED,
                     detail="the painting is larger than Studio decodes in full, so "
                            "the comparison would not cover all of it")]

    rows = []
    slots = ", ".join(str(s) for s in original["slots_referenced"])
    translated = original.get("dialect") != copy.get("dialect")
    if before == after and not translated:
        rows.append(_row("Painted colour", PRESERVED_EXACT,
                         detail=f"{len(before)} painted facet(s), byte-identical, "
                                f"using slot(s) {slots}",
                         reason=_paint_dialect_reason(b)))
        return rows

    shape_a, shape_b = _paint_shape(original), _paint_shape(copy)
    if shape_a == shape_b:
        if translated:
            # The values are the same string; only the attribute's name changed,
            # because the two families write the same encoding under different
            # names. That is a re-statement of the same painting, not the same
            # bytes, so it is semantic preservation and says which way it went.
            # A warning about painting that will not arrive outranks the note
            # about how it was written: being in the target's vocabulary is no
            # help if the mesh is somewhere the target does not look.
            translated_reason = (
                f"written in Snapmaker Orca's own vocabulary instead of "
                f"{original.get('dialect')}'s, which is the form Orca reads")
            rows.append(_row("Painted colour", PRESERVED_SEMANTIC,
                             detail=(f"{len(before)} painted facet(s) over the same "
                                     f"area at the same heights, using slot(s) {slots}"),
                             reason=_paint_dialect_reason(b) or translated_reason))
        else:
            rows.append(_row("Painted colour", PRESERVED_SEMANTIC,
                             detail="the paint data is written differently but names "
                                    "the same slots over the same area at the same "
                                    "heights",
                             reason="the copy was re-serialised"))
        return rows

    differences = []
    if shape_a["slots"] != shape_b["slots"]:
        differences.append(f"slots {shape_a['slots']} → {shape_b['slots']}")
    if shape_a["facets"] != shape_b["facets"]:
        differences.append(f"{shape_a['facets']} → {shape_b['facets']} painted facets")
    if shape_a["areas"] != shape_b["areas"]:
        differences.append("the painted area per slot differs")
    if shape_a["heights"] != shape_b["heights"]:
        differences.append("the painted heights differ")
    rows.append(_row("Painted colour", CHANGED,
                     detail="; ".join(differences) or "the paint data differs",
                     reason="Studio does not repaint models — report this as a bug"))
    return rows


# --- which filament each object prints in ------------------------------------
#
# The quietest thing a converter can destroy. Studio reassigned every PrusaSlicer
# object to filament 1 while reporting the geometry byte-identical and nothing
# removed, which is exactly the shape of failure this audit exists to catch.

def _filament_count(tm: ThreeMF) -> int | None:
    """How many filaments the prepared copy's profile configures."""
    settings = _json_or_none(tm, PROJECT_SETTINGS)
    if not isinstance(settings, dict):
        return None
    for key in ("filament_settings_id", "filament_colour", "filament_type"):
        value = settings.get(key)
        if isinstance(value, list) and value:
            return len(value)
    return None


def _slots_beyond_the_profile(source: dict, prepared: ThreeMF) -> list[int]:
    """Slots the source states that the prepared printer has no filament for.

    Carrying the number is still right — PrusaSlicer round-trips a slot beyond its
    own filament count, so the source really does say it and a copy saying anything
    else would be a different project. What is not right is letting "preserved"
    stand alone: handed a part on filament 5 against a four-filament U1 profile,
    Snapmaker Orca 2.3.5 discarded the assignment to unassigned rather than
    clamping it. The same file with the part on filament 4 kept it exactly.
    """
    count = _filament_count(prepared)
    if not count:
        return []
    slots = {volume.get("slot")
             for entry in source.get("objects") or []
             for volume in (entry.get("volumes") or [])
             if volume.get("slot")}
    return sorted(slot for slot in slots if slot > count)


def _assignment_rows(a: ThreeMF, b: ThreeMF) -> list[dict]:
    from . import assignments

    before = assignments.read(a)
    after = assignments.read(b)
    if not before.get("available"):
        return []
    if not after.get("available"):
        return [_row("Which filament each object uses", REMOVED,
                     detail="the source assigns filaments per object; the copy "
                            "records no assignments at all",
                     reason="Studio does not drop object assignments — report this as a bug")]

    # How many filaments the prepared plate prints with, because one of the
    # per-object settings is only allowed on a plate that needs no prime tower.
    # Without it the audit calls Studio's correct refusal a fault.
    try:
        from .stl_wrap import filaments_in_use

        in_use = filaments_in_use(a, a.read_part("3D/3dmodel.model"))
    except Exception:
        in_use = 1
    verdict = assignments.compare(before, after, filaments=in_use)
    if not verdict.get("available"):
        return [_row("Which filament each object uses", UNVERIFIED,
                     detail=verdict.get("reason", "the two sides cannot be compared"))]

    rows = []
    for entry in verdict["rows"]:
        label = f"Filament for {entry['object']}"
        status = entry["status"]
        if status == assignments.PRESERVED:
            rows.append(_row(label, PRESERVED_SEMANTIC, detail=entry["detail"]))
        elif status == assignments.NOT_REPRESENTABLE:
            rows.append(_row(label, UNSUPPORTED, detail=entry["detail"],
                             reason="a prepared U1 object is a single part"))
        elif status == assignments.LOST:
            rows.append(_row(label, REMOVED, detail=entry["detail"],
                             reason="Studio does not drop object assignments — "
                                    "report this as a bug"))
        elif status == assignments.CHANGED:
            rows.append(_row(label, CHANGED, detail=entry["detail"],
                             reason="Studio does not renumber object assignments — "
                                    "report this as a bug"))
        else:
            rows.append(_row(label, UNVERIFIED, detail=entry["detail"]))

    # The facts underneath the assignment get their own rows. One line saying
    # "objects preserved" is how a copy passes an audit while a part's filament,
    # a modifier's role or a per-object setting quietly went missing beneath it.
    labels = {
        "volume_filament": "Filament for each part of {object}",
        "volume_role": "Part roles in {object}",
        "instances": "Copies of {object}",
        "override": "Settings set on {object}",
    }
    mapping = {
        assignments.PRESERVED_EXACT: PRESERVED_EXACT,
        assignments.PRESERVED_SEMANTIC: PRESERVED_SEMANTIC,
        assignments.CHANGED: CHANGED,
        assignments.UNSUPPORTED: UNSUPPORTED,
        assignments.UNVERIFIED: UNVERIFIED,
    }
    beyond = _slots_beyond_the_profile(before, b)
    for entry in verdict.get("semantics") or ():
        template = labels.get(entry["kind"], "{object}")
        reason = None
        if entry["kind"] == "volume_filament" and beyond:
            listed = ", ".join(str(slot) for slot in beyond)
            reason = (f"the copy states filament {listed} and declares {_filament_count(b)} "
                      "filament slot(s). Measured against Snapmaker Orca 2.3.5, a slot "
                      "above the declared count is dropped to unassigned when the "
                      "project is opened, so set that part's filament in Orca before "
                      "slicing")
        rows.append(_row(template.format(object=entry["object"]),
                         mapping.get(entry["status"], UNVERIFIED),
                         detail=entry["detail"], reason=reason))
    return rows
