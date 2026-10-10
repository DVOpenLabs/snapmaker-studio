"""Project Intelligence — a richer, read-only read of a design on top of the
Doctor diagnosis. Adds real geometry (bounding-box dimensions, triangle count)
and material details. Pure: no network, no mutation, no fake data — every value
is derived from the file or the existing engine.
"""
from __future__ import annotations
import re
from pathlib import Path

from .doctor import diagnose_path, READY
from .container import ThreeMF
from .config_io import load_project_settings
from . import units as _units

SCHEMA_VERSION = "insights/1"
SETTINGS = "Metadata/project_settings.config"

# Guard: don't scan vertices on a huge mesh (e.g. a 200 MB Prusa export) — report
# dimensions as unavailable rather than stalling an interactive call.
_MAX_GEOMETRY_BYTES = 80 * 1024 * 1024

_VERT_RE = re.compile(rb'<vertex[^>]*\bx="(-?[\d.eE+]+)"[^>]*\by="(-?[\d.eE+]+)"[^>]*\bz="(-?[\d.eE+]+)"')
_TRI_RE = re.compile(rb"<triangle ")
_OBJECT_BLOCK_RE = re.compile(rb"<object\b[^>]*>.*?</object>", re.S)
_ID_RE = re.compile(rb'\bid="([^"]*)"')


def _object_id(block: bytes) -> str:
    found = _ID_RE.search(block[:block.index(b">") + 1])
    return found.group(1).decode("utf-8", "replace") if found else ""


def _bbox_and_triangles(tm: ThreeMF):
    """Bounding box (mm) + triangle count from the 3MF mesh parts. Returns
    (dims|None, triangles|None); None dims if geometry is too large to scan."""
    model_parts = [p for p in tm.list_parts() if p.endswith(".model")]
    total = sum(len(tm.read_part(p)) for p in model_parts)
    tris = 0
    for p in model_parts:
        tris += len(_TRI_RE.findall(tm.read_part(p)))
    if total > _MAX_GEOMETRY_BYTES:
        return None, (tris or None)
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    seen = False
    # Meshes that are only ever non-printing volumes (modifiers, negative volumes, support helpers) are not
    # part of the model's extents: the same role rule as the placed bounds and the sizes (see ``roles``).
    from . import geometry

    helpers = geometry.nonprinting_meshes(tm)
    for p in model_parts:
        raw = tm.read_part(p)
        # Each part's coordinates are in the unit its own header declares; the result is
        # millimetres. Millimetre parts (the default) are multiplied by exactly 1.0.
        scale = _units.mm_per_unit(raw)
        if any(part == p for part, _oid in helpers):
            matches = (m for block in _OBJECT_BLOCK_RE.finditer(raw)
                       if (p, _object_id(block.group(0))) not in helpers
                       for m in _VERT_RE.finditer(block.group(0)))
        else:
            matches = _VERT_RE.finditer(raw)
        for m in matches:
            seen = True
            for i in range(3):
                v = float(m.group(i + 1)) * scale
                if v < lo[i]: lo[i] = v
                if v > hi[i]: hi[i] = v
    if not seen:
        return None, (tris or None)
    dims = {"x": round(hi[0] - lo[0], 1), "y": round(hi[1] - lo[1], 1), "z": round(hi[2] - lo[2], 1)}
    return dims, (tris or None)


def _stl_bbox_and_triangles(path: str):
    from .stl_io import parse_stl
    from .geometry import _MAX_BYTES
    try:
        if Path(path).stat().st_size > _MAX_BYTES:
            return None, None   # too large to analyze — degrade gracefully
        raw = Path(path).read_bytes()   # in the try: file may vanish/change after stat
    except OSError:
        return None, None
    if len(raw) > _MAX_BYTES:           # TOCTOU: file may have grown between stat and read
        return None, None
    verts, tris = parse_stl(raw)
    if not verts:
        return None, (len(tris) or None)
    xs = [v[0] for v in verts]; ys = [v[1] for v in verts]; zs = [v[2] for v in verts]
    dims = {"x": round(max(xs) - min(xs), 1), "y": round(max(ys) - min(ys), 1), "z": round(max(zs) - min(zs), 1)}
    return dims, (len(tris) or None)


def _materials(tm: ThreeMF | None) -> list[dict]:
    if tm is None or not tm.has_part(SETTINGS):
        return []
    cfg = load_project_settings(tm.read_part(SETTINGS))
    colors = cfg.get("filament_colour") or []
    types = cfg.get("filament_type") or []
    out = []
    for i, c in enumerate(colors):
        out.append({"color": c, "type": (types[i] if i < len(types) else None)})
    return out


def _complexity(triangles: int | None) -> str | None:
    if triangles is None:
        return None
    if triangles < 50_000:
        return "low"
    if triangles < 500_000:
        return "medium"
    return "high"


def project_info(path: str, placement_aware: bool = False) -> dict:
    """Rich, read-only insights for a design. Builds on the Doctor diagnosis and
    adds real geometry + material detail. Never raises on geometry — returns what
    it can and leaves the rest null.

    ``placement_aware`` also reads every object's size and every instance's placed bounds
    (``object_sizes_mm``, ``placed``). That means reading each mesh once more, so it is asked for
    only by the callers that use it (Design Health, the bed-fit check, the validation report); the
    rest keep the cost they had and get ``None`` for those three keys."""
    diag = diagnose_path(path).to_dict()
    is_stl = str(path).lower().endswith(".stl")

    dims = triangles = None
    materials: list[dict] = []
    try:
        if is_stl:
            dims, triangles = _stl_bbox_and_triangles(path)
        else:
            tm = ThreeMF.open(path)
            dims, triangles = _bbox_and_triangles(tm)
            materials = _materials(tm)
    except Exception:
        pass  # geometry/materials are best-effort; diagnosis still stands

    # SIZE and PLACEMENT are different facts and are kept apart here.
    #   object_sizes_mm  how big each object is (per object, millimetres, before any build item
    #                    moves, turns or scales it). Says nothing about where anything sits.
    #   placed           where each instance sits and on which plate (placed bounds).
    #   dimensions_mm    kept for existing readers: the overall extents of all the mesh data
    #                    together. A size-only figure; for several objects it is NOT one object's
    #                    size and NOT a position (dimensions_basis says so).
    object_sizes: list[dict] | None = []
    unmeasured: int | None = 0   # build items whose object could not be found, so have no size here
    placed: dict | None
    if not placement_aware:
        object_sizes, unmeasured, placed = None, None, None
    elif is_stl:
        if dims:
            object_sizes = [{"object_id": None, "instance_count": 1, "dimensions_mm": dict(dims)}]
        placed = {"available": False, "basis": "placed_bounds", "instances": [],
                  "plate_count": 0, "plate_extents": [], "combined_extent_mm": None,
                  "reason": "A bare STL has no placement of its own; Studio centers it when it wraps "
                            "the model into a U1 project."}
    else:
        try:
            from . import geometry, plate_placement
            placed_items, unresolved, sizes = geometry.measure(path)
            object_sizes = [{"object_id": s["object_id"], "part": s["part"],
                             "instance_count": s["instance_count"],
                             "dimensions_mm": {k: round(v, 1) for k, v in s["dimensions"].items()}}
                            for s in sizes]
            unmeasured = len(unresolved)
            placed = plate_placement.placed_instances(path, measured=(placed_items, unresolved))
        except Exception:
            placed = {"available": False, "basis": "placed_bounds", "instances": [],
                      "plate_count": 0, "plate_extents": [], "combined_extent_mm": None,
                      "reason": "Studio could not read where the objects sit in this project."}

    return {
        "schema_version": SCHEMA_VERSION,
        "name": Path(path).name,
        "source_type": diag.get("input_type"),
        "source_family": diag.get("family"),
        "verdict": diag.get("verdict"),
        "readiness_score": diag.get("score"),
        "is_compatible": diag.get("verdict") == READY,
        "recommended_action": diag.get("recommended_action"),
        "objects": diag.get("object_count"),
        "plates": diag.get("plate_count"),
        "colors": diag.get("filament_count"),
        "painted": diag.get("painted"),
        "materials": materials,
        "dimensions_mm": dims,
        "dimensions_basis": "overall_extents_by_size",
        "object_sizes_mm": object_sizes,
        "objects_unmeasured": unmeasured,
        "placed": placed,
        "triangles": triangles,
        "complexity": _complexity(triangles),
        "issues": [*(diag.get("validation_issues") or []), *(diag.get("compatibility_issues") or [])],
    }
