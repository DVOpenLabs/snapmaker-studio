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
    for p in model_parts:
        raw = tm.read_part(p)
        # Each part's coordinates are in the unit its own header declares; the result is
        # millimetres. Millimetre parts (the default) are multiplied by exactly 1.0.
        scale = _units.mm_per_unit(raw)
        for m in _VERT_RE.finditer(raw):
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


def project_info(path: str) -> dict:
    """Rich, read-only insights for a design. Builds on the Doctor diagnosis and
    adds real geometry + material detail. Never raises on geometry — returns what
    it can and leaves the rest null."""
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
        "triangles": triangles,
        "complexity": _complexity(triangles),
        "issues": [*(diag.get("validation_issues") or []), *(diag.get("compatibility_issues") or [])],
    }
