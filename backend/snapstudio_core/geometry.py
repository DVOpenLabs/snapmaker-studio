"""Indexed-mesh loader — the shared geometry foundation for Design Intelligence.

Loads an STL or 3MF into one in-memory indexed mesh (deduped vertices + triangle
index triples) so the diagnostics layer can run real geometry analysis (integrity,
overhang, stability, volume) on ANY ecosystem's file. Read-only: never mutates input.

Pure Python, no heavy deps (no trimesh/Open3D) — keeps the frozen sidecar light.
Guarded for size so an interactive call degrades to "too large to analyze" instead
of stalling.
"""
from __future__ import annotations
from dataclasses import dataclass
import copy
from pathlib import Path

from .container import ThreeMF
from .config_io import load_model_settings
from . import units as _units

# Mirror intelligence.py's byte guard; plus a triangle cap for analysis cost.
_MAX_BYTES = 80 * 1024 * 1024
_MAX_TRIANGLES = 2_000_000
_3MF_CORE_NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


class _TooLarge(Exception):
    pass


@dataclass
class Mesh:
    verts: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int]]

    @property
    def triangle_count(self) -> int:
        return len(self.faces)


def _model_parts(tm: ThreeMF) -> list[str]:
    return [p for p in tm.list_parts() if p.endswith(".model")]


def _parse_3mf_model(raw: bytes, verts: list, faces: list) -> None:
    """Append one .model part's vertices + triangles to the accumulators. Uses the
    hardened XML parser (no XXE/DTD/network). Triangle indices are local to each
    <mesh>, so we offset by the vertex count at the start of that mesh."""
    root = load_model_settings(raw)
    scale = _units.mm_per_unit(raw)   # the part's declared unit -> millimetres (1.0 for mm)
    for mesh in root.iter(f"{_3MF_CORE_NS}mesh"):
        vstart = len(verts)
        vnode = mesh.find(f"{_3MF_CORE_NS}vertices")
        tnode = mesh.find(f"{_3MF_CORE_NS}triangles")
        if vnode is None or tnode is None:
            continue
        for v in vnode.iterfind(f"{_3MF_CORE_NS}vertex"):
            if scale == 1.0:
                verts.append((float(v.get("x", 0)), float(v.get("y", 0)), float(v.get("z", 0))))
            else:
                verts.append((float(v.get("x", 0)) * scale, float(v.get("y", 0)) * scale,
                              float(v.get("z", 0)) * scale))
        for t in tnode.iterfind(f"{_3MF_CORE_NS}triangle"):
            faces.append((vstart + int(t.get("v1")), vstart + int(t.get("v2")), vstart + int(t.get("v3"))))
            if len(faces) > _MAX_TRIANGLES:
                raise _TooLarge()


_3MF_PROD_NS = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}"
_MAX_VERTS = 8_000_000


def _xform(s):
    """Parse a 3MF transform string (12 floats) -> list, or None."""
    if not s:
        return None
    try:
        f = [float(x) for x in s.split()]
        return f if len(f) == 12 else None
    except (TypeError, ValueError):
        return None


def _apply(v, m):
    if not m:
        return v
    x, y, z = v
    return (m[0] * x + m[3] * y + m[6] * z + m[9],
            m[1] * x + m[4] * y + m[7] * z + m[10],
            m[2] * x + m[5] * y + m[8] * z + m[11])


def _compose(a, b):
    """a∘b — apply b then a (both 12-float 3x4 transforms)."""
    if a is None:
        return b
    if b is None:
        return a
    def appA(v):
        x, y, z = v
        return (a[0] * x + a[3] * y + a[6] * z, a[1] * x + a[4] * y + a[7] * z, a[2] * x + a[5] * y + a[8] * z)
    c0, c1, c2 = appA(b[0:3]), appA(b[3:6]), appA(b[6:9])
    t = appA(b[9:12])
    return [c0[0], c0[1], c0[2], c1[0], c1[1], c1[2], c2[0], c2[1], c2[2],
            t[0] + a[9], t[1] + a[10], t[2] + a[11]]


ROOT_MODEL = "3D/3dmodel.model"


def normalize_part(path: str | None) -> str | None:
    """A ``p:path`` as an archive entry name (leading slash removed); None when absent."""
    if not path:
        return None
    return path.lstrip("/")


def build_items(root: bytes | str) -> list[dict]:
    """Every build item of a root model, in document order, read with the XML parser.

    The ONE reader of build items: ``item_index`` is the ordinal among all ``<item>``
    elements, so a commented-out tag or a namespace prefix cannot make two readers number
    the items differently. ``part`` is the item's ``p:path`` (None when it has none) and
    ``attributes`` is every attribute of the element, by name.
    """
    data = root.encode("utf-8") if isinstance(root, str) else root
    out = []
    for ordinal, it in enumerate(load_model_settings(data).iter(f"{_3MF_CORE_NS}item")):
        out.append({"item_index": ordinal,
                    "object_id": it.get("objectid"),
                    "transform": it.get("transform"),
                    "part": normalize_part(it.get(f"{_3MF_PROD_NS}path")),
                    "attributes": dict(it.attrib)})
    return out


def build_item_dims(path: str) -> list[dict]:
    """Per-build-item bounding-box dimensions (mm), with the 3MF build transform and
    nested component transforms applied — i.e. each placed object's real on-plate
    size, one entry per build item (a repeated object appears once per item).
    Read-only, exception-safe (returns [] on any failure). Used by the Scale Doctor
    size-options ladder for per-plate dimensions.

    An item (or component) that names a ``p:path`` is looked up in THAT part and nowhere
    else; one that cannot be found is left out here and reported by ``measure_items``."""
    return _measure(path)[0]


def measure_items(path: str) -> tuple[list[dict], list[dict]]:
    """``(placed items, unresolved items)``.

    ``unresolved`` lists the build items whose object could not be found where the file says
    it is (a ``p:path`` naming a part that is absent, or an object the part does not hold).
    They are never measured against some other object that happens to share the id."""
    items, unresolved, _sizes = _measure(path)
    return items, unresolved


def object_sizes(path: str) -> list[dict]:
    """Per-object size (mm): each object as modelled, keyed by (part, object id), with its nested
    component transforms applied but BEFORE any build item moves, turns or scales it. One entry per
    distinct object (``instance_count`` says how many build items use it). This is a SIZE measure
    and says nothing about where anything sits."""
    return _measure(path)[2]


def measure(path: str) -> tuple[list[dict], list[dict], list[dict]]:
    """``(placed items, unresolved items, object sizes)`` from a single read of the project."""
    return _measure(path)


#: The last few projects measured, keyed by file identity: one request often asks for the size, the
#: placement and the layout of the same file, and each of those used to re-read every mesh.
_CACHE: dict = {}
_CACHE_SLOTS = 4


def stat_identity(path: str):
    """``(resolved path, mtime, size)`` or None."""
    try:
        resolved = Path(path).resolve()
        st = resolved.stat()
    except OSError:
        return None
    return (str(resolved), st.st_mtime_ns, st.st_size)


def file_identity(path: str):
    """What a remembered measurement is keyed by: the stat identity PLUS a fingerprint of the content.

    A replacement of the same size that kept its timestamp (a copy that preserves times, a build that
    rewrites in place) still changes the fingerprint, so a stale measurement is never served."""
    import hashlib

    base = stat_identity(path)
    if base is None:
        return None
    digest = hashlib.blake2b(digest_size=16)
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return base + (digest.hexdigest(),)


def _measure(path: str):
    key = file_identity(path)
    if key is not None and key in _CACHE:
        items, unresolved, sizes = _CACHE[key]
        return copy.deepcopy((items, unresolved, sizes))
    result = _measure_uncached(path)
    # only remember it if the file is still the one that was read: a change during the measurement
    # would otherwise be filed under the identity of the old content
    if key is not None and stat_identity(path) == key[:3]:
        while len(_CACHE) >= _CACHE_SLOTS:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = copy.deepcopy(result)
    return result


def _measure_uncached(path: str):
    try:
        tm = ThreeMF.open(path)
    except Exception:
        return [], [], []
    try:
        model_files = {p: tm.read_part(p) for p in tm.list_parts() if p.endswith(".model")}
        if sum(len(b) for b in model_files.values()) > _MAX_BYTES:
            return [], [], []

        # (part, object_id) -> (verts, [(component_objectid, component_part|None, component_xform)])
        parsed: dict[str, dict[str, tuple]] = {}
        unit_scale: dict[str, float] = {}
        for fname, raw in model_files.items():
            root = load_model_settings(raw)
            scale = _units.mm_per_unit(raw)   # this part's declared unit -> millimetres
            unit_scale[fname] = scale
            objs: dict[str, tuple] = {}
            for ob in root.iter(f"{_3MF_CORE_NS}object"):
                oid = ob.get("id")
                verts = []
                mesh = ob.find(f"{_3MF_CORE_NS}mesh")
                if mesh is not None:
                    vn = mesh.find(f"{_3MF_CORE_NS}vertices")
                    if vn is not None:
                        for v in vn.iterfind(f"{_3MF_CORE_NS}vertex"):
                            if scale == 1.0:
                                verts.append((float(v.get("x", 0)), float(v.get("y", 0)), float(v.get("z", 0))))
                            else:
                                verts.append((float(v.get("x", 0)) * scale, float(v.get("y", 0)) * scale,
                                              float(v.get("z", 0)) * scale))
                comps = []
                cn = ob.find(f"{_3MF_CORE_NS}components")
                if cn is not None:
                    for c in cn.iterfind(f"{_3MF_CORE_NS}component"):
                        comps.append((c.get("objectid"),
                                      normalize_part(c.get(f"{_3MF_PROD_NS}path")),
                                      _units.scale_translation(_xform(c.get("transform")), scale)))
                objs[oid] = (verts, comps)
            parsed[fname] = objs

        root_file = ROOT_MODEL
        if root_file not in parsed:
            return [], [], []

        def find_obj(objid, part, explicit):
            """The part that holds ``objid``. A named part is the only place looked in; with no
            ``p:path`` the current part is preferred and any other part is a legacy fallback."""
            if part in parsed and objid in parsed[part]:
                return part
            if explicit:
                return None
            for f, oo in parsed.items():
                if objid in oo:
                    return f
            return None

        # The size of the objects and the placing of the items are counted against the vertex limit
        # separately, so measuring both does not halve what a project may hold.
        budget = [0]
        placed_budget = [0]

        def collect(objid, part, explicit, xform, acc, seen, bad):
            f = find_obj(objid, part, explicit)
            if f is None:
                bad.append(f"object {objid} is not in {part}")
                return
            key = (f, objid)
            if key in seen or len(seen) > 4096:   # cycle / runaway-nesting guard
                return
            seen = seen | {key}
            verts, comps = parsed[f][objid]
            for v in verts:
                acc.append(_apply(v, xform))
                budget[0] += 1
                if budget[0] > _MAX_VERTS:
                    raise _TooLarge()
            for cid, cpart, ctf in comps:
                collect(cid, cpart or f, cpart is not None, _compose(xform, ctf), acc, seen, bad)

        def box_of(points):
            xs = [p[0] for p in points]; ys = [p[1] for p in points]; zs = [p[2] for p in points]
            return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

        items = build_items(model_files[root_file])
        uses: dict[tuple, int] = {}
        for it in items:
            part = it["part"] or root_file
            uses[(part, it["object_id"])] = uses.get((part, it["object_id"]), 0) + 1

        # Each distinct object is collected once, as modelled; an item then only moves those points.
        collected: dict[tuple, tuple] = {}
        out = []
        unresolved = []
        sizes: dict[tuple, dict] = {}
        for it in items:
            oid = it["object_id"]
            part = it["part"] or root_file
            key = (part, oid)
            if key not in collected:
                points: list = []
                bad: list = []
                collect(oid, part, it["part"] is not None, None, points, frozenset(), bad)
                collected[key] = (points, bad)
                if points and not bad:
                    lo, hi = box_of(points)
                    sizes[key] = {"object_id": oid, "part": part, "instance_count": uses[key],
                                  "dimensions": {"x": round(hi[0] - lo[0], 2),
                                                 "y": round(hi[1] - lo[1], 2),
                                                 "z": round(hi[2] - lo[2], 2)}}
            points, bad = collected[key]
            if bad:
                unresolved.append({"item_index": it["item_index"], "object_id": oid,
                                   "part": part, "reason": bad[0]})
                continue
            if not points:
                continue
            xform = _units.scale_translation(_xform(it["transform"]), unit_scale[root_file])
            placed_budget[0] += len(points)
            if placed_budget[0] > _MAX_VERTS:
                raise _TooLarge()
            lo, hi = box_of([_apply(v, xform) for v in points])
            # `item_index` is the build item's ordinal in the root model: one object used by two items is
            # two entries, and this tells them apart (an item with no geometry leaves a gap in the sequence).
            out.append({"object_id": oid,
                        "item_index": it["item_index"],
                        "part": part,
                        "dimensions": {"x": round(hi[0] - lo[0], 2),
                                       "y": round(hi[1] - lo[1], 2),
                                       "z": round(hi[2] - lo[2], 2)},
                        "bounds": {"min": lo, "max": hi}})
        return out, unresolved, list(sizes.values())
    except _TooLarge:
        return [], [], []
    except Exception:
        return [], [], []


def load_mesh(path: str) -> Mesh | None:
    """Load an STL or 3MF into one indexed mesh, or None if unreadable / too large.
    Best-effort and exception-safe (returns None, never raises out to callers)."""
    p = Path(path)
    try:
        if p.suffix.lower() == ".stl":
            data = p.read_bytes()
            if len(data) > _MAX_BYTES:
                return None
            from .stl_io import parse_stl
            verts, faces = parse_stl(data)
            if not verts or not faces or len(faces) > _MAX_TRIANGLES:
                return None
            return Mesh(list(verts), list(faces))
        # 3MF (Bambu/Orca/Prusa) — accumulate every .model part into one mesh.
        tm = ThreeMF.open(path)
        parts = _model_parts(tm)
        if sum(len(tm.read_part(pt)) for pt in parts) > _MAX_BYTES:
            return None
        verts: list = []
        faces: list = []
        for part in parts:
            _parse_3mf_model(tm.read_part(part), verts, faces)
        if not verts or not faces:
            return None
        return Mesh(verts, faces)
    except _TooLarge:
        return None
    except Exception:
        return None
