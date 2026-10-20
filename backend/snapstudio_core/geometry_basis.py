"""Is this model's physical size established for the current analysis?

Studio's size-dependent checks (bed fit, the readiness "fits" check, the success estimate,
first-layer footprint, the Scale Doctor preview) measure the numbers stored in a file's
mesh. Those numbers are the physical size only when two things hold:

1. the file's unit is millimetres (declared, or the 3MF default). A declared inch/metre/...
   file is read as if its numbers were millimetres; Studio does not convert units.
2. every placed mesh reaches the build plate through a transform that keeps its axis
   extents: the identity, a translation, a mirror along an axis (a diagonal +-1 matrix).
   A rotation, a scale or a shear changes the extents, and the mesh measurement is taken
   BEFORE that transform.

When either fails, the size is "not established": a verdict built on it would be a guess
presented as a measurement, so every consuming surface reports "not checked" with the
same reason instead. Unknown stays unknown: this module never turns it into a failure,
a zero dimension or a probability.

Translations are deliberately not a failure: a placement offset does not change a part's
extents, and an arrangement of several objects is still reported by the existing
largest-object proxy ("the whole arrangement must fit" is already stated by bed fit).

Read-only; never raises. STL files carry no unit and no transform: they stay established
with the millimetre assumption Studio already makes.
"""
from __future__ import annotations

import math
import os

from .config_io import load_model_settings
from .container import ThreeMF

SCHEMA_VERSION = "geometry-basis/1"

_CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
_PROD = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}"
_ROOT_PART = "3D/3dmodel.model"
_TOL = 1e-3
_MAX_VISITS = 100_000
_MAX_DEPTH = 64

# Stable order so every surface prints the same sentence for the same file.
_REASON_ORDER = ("unit_not_millimeter", "transform_rotated", "transform_scaled",
                 "transform_unreadable", "structure_unresolved", "structure_unreadable")

#: What a not-established size withholds. Shared by every surface so scope agrees.
WITHHELD = ("bed fit", "the size-based readiness check", "the print-success estimate",
            "first-layer footprint checks", "the Scale Doctor size preview")

_cache: dict = {}


def _fingerprint(path: str):
    try:
        st = os.stat(path)
        return (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _parse_transform(raw):
    """-> (linear 3x3 as 9 floats row-major per 3MF column convention, status).
    status: 'identity' | 'ok' | 'unreadable'."""
    if raw is None or not str(raw).strip():
        return (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0), "identity"
    try:
        v = [float(x) for x in str(raw).split()]
    except ValueError:
        return None, "unreadable"
    if len(v) != 12 or not all(math.isfinite(x) for x in v):
        return None, "unreadable"
    # 3MF transform = row vector convention: [m00 m01 m02 m10 m11 m12 m20 m21 m22 tx ty tz]
    return tuple(v[:9]), "ok"


def _mul(a, b):
    """Row-major 3x3 product a*b (apply a first, then b, as a row-vector chain)."""
    return tuple(sum(a[3 * i + k] * b[3 * k + j] for k in range(3)) for i in range(3) for j in range(3))


def _classify(m) -> str | None:
    """None when the matrix keeps axis extents; else the reason code."""
    off = (m[1], m[2], m[3], m[5], m[6], m[7])
    if all(abs(x) <= _TOL for x in off) and all(abs(abs(m[i]) - 1.0) <= _TOL for i in (0, 4, 8)):
        return None
    # orthonormal rows/columns with |det| == 1: a rotation (possibly with a mirror)
    gram = [sum(m[3 * i + k] * m[3 * j + k] for k in range(3)) for i in range(3) for j in range(3)]
    ident = all(abs(gram[3 * i + j] - (1.0 if i == j else 0.0)) <= _TOL for i in range(3) for j in range(3))
    if ident:
        return "transform_rotated"
    return "transform_scaled"


def _unit_reason(declared) -> str | None:
    if declared is None:
        return None                   # the 3MF default is millimetres
    return None if str(declared).strip().lower() == "millimeter" else str(declared).strip()


def _safe_label(text: str) -> str:
    cleaned = "".join(ch for ch in text.lower() if ch.isalnum())[:24]
    return cleaned or "an unknown unit"


def _summary(reasons: list, declared_units: list, unchecked: list, total: int) -> str:
    parts = []
    if "unit_not_millimeter" in reasons:
        names = ", ".join(sorted({_safe_label(u) for u in declared_units})) or "an unknown unit"
        parts.append(f"The file declares its unit as {names}, but Studio reads its numbers as millimetres "
                     "and does not convert them.")
    if "transform_rotated" in reasons:
        parts.append("Part of the model is rotated by its placement transform, and Studio measured it "
                     "before that rotation.")
    if "transform_scaled" in reasons:
        parts.append("Part of the model is scaled or reshaped by its placement transform, and Studio "
                     "measured it before that transform.")
    if "transform_unreadable" in reasons:
        parts.append("The file has a placement transform Studio could not read.")
    if "structure_unresolved" in reasons:
        parts.append("Studio could not follow how this file places all of its objects.")
    if "structure_unreadable" in reasons:
        parts.append("Studio could not read how this file is built.")
    if unchecked and total:
        parts.append(f"{len(unchecked)} of {total} placed object{'s' if total != 1 else ''} affected.")
    return " ".join(parts)


def _established(unit_source: str, unit: str | None) -> dict:
    return {"schema_version": SCHEMA_VERSION, "established": True, "reasons": [],
            "unit": {"unit": unit, "source": unit_source}, "objects_total": None,
            "unchecked_objects": [], "summary": "", "withheld": []}


def _read_parts(tm: ThreeMF):
    from .geometry import _MAX_BYTES        # the same size guard the geometry loaders use
    names = [n for n in tm.list_parts() if n.endswith(".model")]
    if sum(len(tm.read_part(n)) for n in names) > _MAX_BYTES:
        raise ValueError("too large to analyze")
    return {n.lstrip("/"): load_model_settings(tm.read_part(n)) for n in names}


def _index_objects(root):
    objs = {}
    for ob in root.iter(f"{_CORE}object"):
        oid = ob.get("id")
        mesh = ob.find(f"{_CORE}mesh") is not None
        comps = []
        cn = ob.find(f"{_CORE}components")
        if cn is not None:
            for c in cn.iterfind(f"{_CORE}component"):
                comps.append((c.get("objectid"), (c.get(f"{_PROD}path") or "").lstrip("/") or None,
                              c.get("transform")))
        objs[oid] = (mesh, comps)
    return objs


def _compute(path: str) -> dict:
    if str(path).lower().endswith(".stl"):
        return _established("assumed", "millimeter")
    try:
        tm = ThreeMF.open(path)
        parts = _read_parts(tm)
    except Exception:  # noqa: BLE001 - unreadable file: say so, do not vouch
        return _not_established(["structure_unreadable"], [], [], 0, None)
    if _ROOT_PART not in parts:
        return _not_established(["structure_unreadable"], [], [], 0, None)

    reasons: set = set()
    declared_bad: list = []
    declared_any = False
    for name, root in parts.items():
        declared = root.get("unit")
        declared_any = declared_any or declared is not None
        bad = _unit_reason(declared)
        if bad is not None:
            reasons.add("unit_not_millimeter")
            declared_bad.append(bad)

    index = {name: _index_objects(root) for name, root in parts.items()}
    visits = [0]
    unchecked: dict = {}

    def locate(oid, prefer):
        if prefer and prefer in index and oid in index[prefer]:
            return prefer
        if prefer is None:
            return None
        for name, objs in index.items():
            if oid in objs:
                return name
        return None

    def walk(oid, prefer, matrix, chain, item_id):
        visits[0] += 1
        if visits[0] > _MAX_VISITS or len(chain) > _MAX_DEPTH:
            unchecked.setdefault(item_id, set()).add("structure_unresolved")
            return
        where = locate(oid, prefer) or locate(oid, _ROOT_PART)
        if where is None or (where, oid) in chain:
            unchecked.setdefault(item_id, set()).add("structure_unresolved")
            return
        has_mesh, comps = index[where][oid]
        if has_mesh:
            code = _classify(matrix)
            if code:
                unchecked.setdefault(item_id, set()).add(code)
        for cid, cpath, ctf in comps:
            lin, status = _parse_transform(ctf)
            if status == "unreadable":
                unchecked.setdefault(item_id, set()).add("transform_unreadable")
                continue
            walk(cid, cpath or where, _mul(lin, matrix), chain | {(where, oid)}, item_id)

    items = list(parts[_ROOT_PART].iter(f"{_CORE}item"))
    for n, it in enumerate(items):
        item_id = it.get("objectid") or f"item{n + 1}"
        key = f"{item_id}#{n + 1}"
        lin, status = _parse_transform(it.get("transform"))
        if status == "unreadable":
            unchecked.setdefault(key, set()).add("transform_unreadable")
            continue
        walk(it.get("objectid"), _ROOT_PART, lin, frozenset(), key)

    for codes in unchecked.values():
        reasons |= codes
    return _not_established(sorted(reasons, key=_REASON_ORDER.index), declared_bad,
                            sorted(unchecked), len(items),
                            "declared" if declared_any else "default")


def _not_established(reasons: list, declared_units: list, unchecked: list, total: int,
                     unit_source) -> dict:
    if not reasons:
        return _established(unit_source or "default", "millimeter")
    return {"schema_version": SCHEMA_VERSION, "established": False, "reasons": reasons,
            "unit": {"unit": None if declared_units else "millimeter", "source": unit_source or "unknown"},
            "objects_total": total or None, "unchecked_objects": unchecked,
            "summary": _summary(reasons, declared_units, unchecked, total),
            "withheld": list(WITHHELD)}


def assess(path: str) -> dict:
    """The geometry basis for `path`. Cached per file version; never raises."""
    key = _fingerprint(path)
    if key is not None and key in _cache:
        return _cache[key]
    try:
        out = _compute(path)
    except Exception:  # noqa: BLE001 - a crash must not read as "established"
        out = _not_established(["structure_unreadable"], [], [], 0, None)
    if key is not None:
        if len(_cache) > 64:
            _cache.clear()
        _cache[key] = out
    return out


def is_established(basis: dict | None) -> bool:
    """Unknown (no basis) is treated as established only for callers that never had one to ask."""
    return bool(basis is None or basis.get("established"))


def not_checked(basis: dict, scope: str) -> dict:
    """The block every surface attaches when it withholds a size-dependent verdict.
    `reason` is the same sentence everywhere; `scope` names what this surface withheld."""
    return {"status": "not_checked", "reason": basis["summary"], "scope": scope,
            "geometry_basis": basis}
