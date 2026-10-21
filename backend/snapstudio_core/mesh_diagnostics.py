"""Mesh diagnostics — real, read-only geometry analysis for Design Intelligence.

Runs on the indexed mesh from `geometry.load_mesh` (STL or 3MF, any ecosystem) and
produces plain-language findings: mesh integrity (manifold / watertight / holes /
normals / degenerate / duplicate), overhang + support prediction, stability /
tip-risk, and volume + an honest material *estimate*.

Rules:
- Pure Python + math (no heavy deps).
- Never fabricate numbers: the material estimate is shown only when the mesh is
  watertight (so volume is meaningful) and is always labelled an estimate. No print
  time, no exact filament/purge — those need a slicer (Orca's job).
- Read-only: never mutates the file or geometry.
"""
from __future__ import annotations
import math
from .geometry import load_mesh, Mesh
from . import geometry_basis

SCHEMA_VERSION = "mesh/1"

# Overhang: a downward-facing surface needs support when it tilts past ~45° from
# vertical (Prusa/Orca default band: <45 clean, 45-60 marginal, >60 support).
_SIN45 = math.sin(math.radians(45))
_SIN60 = math.sin(math.radians(60))
_PLA_DENSITY_G_CM3 = 1.24  # typical PLA; estimate only


def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def _dot(a, b): return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def _face_area_normal(v0, v1, v2):
    cx, cy, cz = _cross(_sub(v1, v0), _sub(v2, v0))
    mag = math.sqrt(cx*cx + cy*cy + cz*cz)
    if mag == 0:
        return 0.0, (0.0, 0.0, 0.0)
    return 0.5 * mag, (cx / mag, cy / mag, cz / mag)


def _integrity(m: Mesh) -> dict:
    edge_count: dict = {}        # undirected edge -> count
    directed: set = set()        # directed edge -> winding check
    winding_ok = True
    degenerate = 0
    seen_faces: set = set()
    duplicate = 0
    for (a, b, c) in m.faces:
        if a == b or b == c or a == c:
            degenerate += 1
            continue
        key = frozenset((a, b, c))
        if key in seen_faces:
            duplicate += 1
        else:
            seen_faces.add(key)
        for u, v in ((a, b), (b, c), (c, a)):
            e = (u, v) if u < v else (v, u)
            edge_count[e] = edge_count.get(e, 0) + 1
            if (u, v) in directed:
                winding_ok = False      # same directed edge twice => inconsistent normals
            directed.add((u, v))
    open_edges = [e for e, n in edge_count.items() if n == 1]
    nonmanifold = sum(1 for n in edge_count.values() if n > 2)
    holes = _count_loops(open_edges)
    return {
        "watertight": len(open_edges) == 0 and nonmanifold == 0,
        "manifold": nonmanifold == 0,
        "open_edges": len(open_edges),
        "holes": holes,
        "non_manifold_edges": nonmanifold,
        "degenerate_faces": degenerate,
        "duplicate_faces": duplicate,
        "winding_consistent": winding_ok,
    }


def _count_loops(open_edges: list) -> int:
    """Number of connected boundary loops (≈ hole count) via union-find on endpoints."""
    if not open_edges:
        return 0
    parent: dict = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(x, y):
        parent[find(x)] = find(y)
    pts = set()
    for u, v in open_edges:
        union(u, v); pts.add(u); pts.add(v)
    return len({find(p) for p in pts})


def _volume_centroid_area(m: Mesh):
    """Signed volume (mm³, abs), volume centroid, and total surface area (mm²)."""
    vol6 = 0.0
    cx = cy = cz = 0.0
    area = 0.0
    for (a, b, c) in m.faces:
        v0, v1, v2 = m.verts[a], m.verts[b], m.verts[c]
        d = _dot(v0, _cross(v1, v2))      # 6*signed tetra volume
        vol6 += d
        cx += (v0[0] + v1[0] + v2[0]) * d
        cy += (v0[1] + v1[1] + v2[1]) * d
        cz += (v0[2] + v1[2] + v2[2]) * d
        ar, _ = _face_area_normal(v0, v1, v2)
        area += ar
    vol = vol6 / 6.0
    if abs(vol6) < 1e-9:
        centroid = None
    else:
        centroid = (cx / (4.0 * vol6), cy / (4.0 * vol6), cz / (4.0 * vol6))
    return abs(vol), centroid, area


def _overhang(m: Mesh, zmin: float, bed_eps: float) -> dict:
    """Area-weighted fraction of steep downward-facing surface (support-likely).
    Faces resting on the build plate (the bottom, all verts within bed_eps of zmin)
    are NOT overhangs — exclude them so a flat base isn't mistaken for a ceiling."""
    total = 0.0
    steep = 0.0       # >45° from vertical, downward
    severe = 0.0      # >60°
    for (a, b, c) in m.faces:
        v0, v1, v2 = m.verts[a], m.verts[b], m.verts[c]
        ar, n = _face_area_normal(v0, v1, v2)
        if ar == 0:
            continue
        total += ar
        nz = n[2]
        on_bed = max(v0[2], v1[2], v2[2]) <= zmin + bed_eps
        if nz < 0 and not on_bed:         # downward underside, not the base
            tilt = abs(nz)                # sin(angle from horizontal); 1 == flat ceiling
            if tilt >= _SIN45:
                steep += ar
            if tilt >= _SIN60:
                severe += ar
    if total == 0:
        return {"overhang_pct": 0.0, "severe_pct": 0.0, "supports_likely": False}
    pct = round(100.0 * steep / total, 1)
    return {
        "overhang_pct": pct,
        "severe_pct": round(100.0 * severe / total, 1),
        "supports_likely": pct >= 5.0,
    }


def _convex_hull(points: list) -> list:
    """Andrew's monotone chain (2D). Returns hull vertices CCW."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts
    def cross(o, a, b): return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _point_in_hull(pt, hull) -> tuple[bool, float]:
    """Inside test + min distance (mm) to nearest hull edge."""
    if len(hull) < 3:
        return False, 0.0
    inside = True
    min_d = float("inf")
    n = len(hull)
    for i in range(n):
        ax, ay = hull[i]; bx, by = hull[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        crossv = ex * (pt[1] - ay) - ey * (pt[0] - ax)   # CCW hull: inside is left of each edge
        if crossv < 0:
            inside = False
        elen = math.hypot(ex, ey)
        if elen > 0:
            min_d = min(min_d, abs(crossv) / elen)
    return inside, (min_d if min_d != float("inf") else 0.0)


def _stability(m: Mesh, centroid) -> dict:
    zs = [v[2] for v in m.verts]
    zmin, zmax = min(zs), max(zs)
    height = zmax - zmin
    eps = max(0.5, 0.01 * height)        # base = vertices within 0.5mm / 1% of height
    base = [(v[0], v[1]) for v in m.verts if v[2] <= zmin + eps]
    xs = [v[0] for v in m.verts]; ys = [v[1] for v in m.verts]
    foot = min(max(xs) - min(xs), max(ys) - min(ys)) or 1e-6
    hull = _convex_hull(base)
    if centroid is None or len(hull) < 3:
        return {"tip_risk": False, "com_over_base": True, "margin_mm": None,
                "height_mm": round(height, 1), "aspect": round(height / foot, 2)}
    inside, margin = _point_in_hull((centroid[0], centroid[1]), hull)
    aspect = height / foot
    # Tip risk: center of mass projects OUTSIDE the base footprint (will fall), OR the
    # part is tall AND has a narrow base (easy to knock over / tower-tip on the U1).
    tall_narrow = aspect > 4.0 and foot < 30.0
    tip = (not inside) or tall_narrow
    return {
        "tip_risk": bool(tip),
        "com_over_base": bool(inside),
        "margin_mm": round(margin, 1),
        "height_mm": round(height, 1),
        "aspect": round(aspect, 2),
    }


def _hull_area(hull) -> float:
    """Polygon area (mm²) via the shoelace formula on a convex hull (CCW)."""
    n = len(hull)
    if n < 3:
        return 0.0
    a = 0.0
    for i in range(n):
        x1, y1 = hull[i]; x2, y2 = hull[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _footprint(m: Mesh) -> dict:
    """Base contact footprint — the area + smallest dimension of the part resting on
    the bed. Feeds adhesion / first-layer / corner-lift reasoning."""
    zs = [v[2] for v in m.verts]
    zmin, zmax = min(zs), max(zs)
    eps = max(0.5, 0.01 * (zmax - zmin))
    base = [(v[0], v[1]) for v in m.verts if v[2] <= zmin + eps]
    hull = _convex_hull(base)
    area = _hull_area(hull)
    xs = [p[0] for p in base] or [0.0]
    ys = [p[1] for p in base] or [0.0]
    width_x = max(xs) - min(xs)
    width_y = max(ys) - min(ys)
    # center of the footprint, used to map onto the bed mesh (assume centered print).
    cx = (max(xs) + min(xs)) / 2.0 if base else 0.0
    cy = (max(ys) + min(ys)) / 2.0 if base else 0.0
    return {
        "base_area_mm2": round(area, 1),
        "width_x_mm": round(width_x, 1),
        "width_y_mm": round(width_y, 1),
        "min_dim_mm": round(min(width_x, width_y), 1),
        "center_xy": [round(cx, 1), round(cy, 1)],
    }


def _plain(integrity, overhang, stability, vol_cm3, grams) -> list:
    out = []
    if integrity["watertight"]:
        out.append({"level": "ok", "text": "Mesh is watertight and manifold — readable by the slicer."})
    else:
        if integrity["holes"]:
            out.append({"level": "risk", "text": f"{integrity['holes']} hole(s) in the mesh — may print with gaps or fail. Repair before printing."})
        if integrity["non_manifold_edges"]:
            out.append({"level": "risk", "text": f"{integrity['non_manifold_edges']} non-manifold edge(s) — slicers may misread the surface. Repair recommended."})
    if not integrity["winding_consistent"]:
        out.append({"level": "warn", "text": "Some surface normals are inconsistent — flipped faces can confuse slicing."})
    if integrity["degenerate_faces"]:
        out.append({"level": "warn", "text": f"{integrity['degenerate_faces']} zero-area face(s) — harmless but messy; a repair pass cleans them."})
    if overhang["supports_likely"]:
        out.append({"level": "warn", "text": f"{overhang['overhang_pct']}% of surfaces are steep overhangs — supports will likely be needed."})
    else:
        out.append({"level": "ok", "text": "Few steep overhangs — likely prints without supports."})
    if stability["tip_risk"]:
        out.append({"level": "warn", "text": "Tall and narrow relative to its base — may tip over or knock off the bed. Consider a brim or reorienting."})
    if grams is not None:
        out.append({"level": "ok", "text": f"About {vol_cm3} cm³ of material (~{grams} g PLA, estimate — your slicer gives the exact figure)."})
    return out


def analyze(path: str) -> dict:
    """Full read-only mesh diagnosis. Returns {available: False, reason} when geometry
    can't be loaded (unreadable / too large) — callers degrade gracefully."""
    m = load_mesh(path)
    if m is None:
        return {"schema_version": SCHEMA_VERSION, "available": False,
                "reason": "geometry unavailable or too large to analyze"}
    zs = [v[2] for v in m.verts]
    zmin = min(zs)
    bed_eps = max(0.5, 0.01 * (max(zs) - zmin))
    integrity = _integrity(m)
    overhang = _overhang(m, zmin, bed_eps)
    vol, centroid, area = _volume_centroid_area(m)
    stability = _stability(m, centroid)
    vol_cm3 = round(vol / 1000.0, 1) if vol else 0.0
    # Material estimate ONLY when watertight (volume is meaningful), always "estimate".
    grams = round(vol / 1000.0 * _PLA_DENSITY_G_CM3, 1) if (integrity["watertight"] and vol) else None
    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "triangle_count": m.triangle_count,
        "integrity": integrity,
        "overhang": overhang,
        "stability": stability,
        "volume_mm3": round(vol, 1),
        "volume_cm3": vol_cm3,
        "surface_area_mm2": round(area, 1),
        "material_estimate_g": grams,
        "footprint": _footprint(m),
        "findings": _plain(integrity, overhang, stability, vol_cm3, grams),
        # footprint, stability height and volume are measured on the file's raw mesh; this says
        # whether that raw mesh is the physical size, so a consumer can qualify or withhold them.
        "geometry_basis": geometry_basis.assess(path),
    }
