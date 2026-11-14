"""paintedpreview/1 -- a read-only, bounded description of a project's painted colour for a viewer.

The 3D view needs two things the scene/1 contract does not carry: *which filament each patch of
surface prints in*, and *where the project's own colours are*. This module adds them without
changing scene/1:

* Geometry, units, placement, repeated instances and the bed come from :mod:`scene`, the one
  producer of the bounded, unit-normalised scene. Nothing here re-derives a transform.
* Painting comes from the project's own paint data, decoded by :mod:`paint_codec`. Every painted
  facet is replayed into the exact patches the slicer's subdivision describes, and each patch is
  assigned the slot its state names. These are not sampled colours: a patch is drawn where the
  paint boundary actually is.
* An unpainted patch prints in whatever its part is assigned, by the same rules
  :mod:`painted_color` uses. Where the project does not say, the patch is drawn with slot
  ``null`` (neutral) and the result says so; slot 1 is never assumed.

What it deliberately does not do, and says so instead:

* It draws only millimetre projects. A project in another unit is reported ``unsupported``; the
  unit is never guessed or converted silently.
* It never shortens a result. Past the triangle budget, or when a facet's paint is finer than the
  decoder follows, the state is ``limit`` and nothing is returned for that file.
* It does not say what the print will look like. Colours are the filament colours the project
  lists (or, in the viewer, the ones a person picks); they are labels for slots.

Output colours are carried per *slot*, not per patch, so the viewer can recolour a project from
a different slot table (the project's, or the person's draft) without asking for the geometry again.
"""
from __future__ import annotations

import base64
import os
from array import array

from . import paint_codec
from . import painted_color as pc
from . import scene
from .container import ThreeMF
from .errors import SnapStudioError

SCHEMA = "paintedpreview/1"

#: Drawn triangles (whole unpainted facets plus painted patches). 120,000 * 36 bytes * 4/3 stays well
#: under the scene body cap (8 MiB), so a result is never close to the size that was refused elsewhere.
MAX_TRIANGLES_OUT = 120_000
#: Painted facets and their attribute text are bounded before anything is decoded.
MAX_PAINTED_FACETS = pc.MAX_PAINTED_TRIANGLES
#: What the viewer actually draws: the split triangles of each mesh times the placed instances that use it.
MAX_RENDERED_TRIANGLES = 600_000
MAX_NOTES = 8

_STATES = ("ok", "unsupported", "unreadable", "limit")
_BASE_NOTE = ("Colours are the filament colours the project lists, or the ones you choose. "
              "They label which filament prints where; they are not a picture of the printed result.")


class _Refusal(Exception):
    def __init__(self, state: str, reason: str):
        assert state in _STATES
        self.state, self.reason = state, reason
        super().__init__(reason)


def _refuse(state: str, reason: str) -> dict:
    return {"schema": SCHEMA, "available": False, "state": state, "reason": reason, "kind": None,
            "bed": None, "slots": [], "unknown_default": False, "meshes": [], "instances": [],
            "counts": {"triangles_out": 0, "painted_triangles": 0, "leaves": 0, "malformed": 0, "triangles_drawn": 0},
            "limits": _limits(), "notes": []}


def _limits() -> dict:
    return {"max_triangles_out": MAX_TRIANGLES_OUT, "max_painted_facets": MAX_PAINTED_FACETS, "max_rendered_triangles": MAX_RENDERED_TRIANGLES,
            "max_leaves_per_facet": paint_codec.MAX_LEAVES_PER_TRIANGLE}


def build(path: str) -> dict:
    """The painted preview of ``path``. Never raises for a UI caller: a refusal is a result with a plain reason."""
    try:
        return _build(str(path))
    except _Refusal as refusal:
        return _refuse(refusal.state, refusal.reason)
    except scene.SceneError as exc:
        state = "limit" if exc.code == "LIMIT_EXCEEDED" else "unsupported" if exc.code == "UNSUPPORTED_FORMAT" else "unreadable"
        return _refuse(state, exc.message)
    except SnapStudioError as exc:
        return _refuse("unreadable", str(exc) or "Studio could not read this file to draw it.")
    except (OSError, ValueError, KeyError, IndexError):
        return _refuse("unreadable", "Studio could not read this file to draw it.")


# --------------------------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------------------------

def _norm(part: str) -> str:
    return part.lstrip("/").casefold()


def _decode_mesh(mesh: dict) -> tuple[array, array]:
    """A scene mesh's vertices (float32) and triangle corner indices (uint32)."""
    pos, idx = array("f"), array("I")
    pos.frombytes(base64.b64decode(mesh["positions_f32le_base64"]))
    idx.frombytes(base64.b64decode(mesh["indices_u32le_base64"]))
    return pos, idx


def _instances(sc: dict) -> list[dict]:
    nodes = sc["nodes"]
    by_id = {n["id"]: n for n in nodes}
    tops = [n for n in nodes if n.get("parent_id") is None]
    counts: dict = {}
    for n in tops:
        key = (n["resource"]["part"], n["resource"]["object_id"])
        counts[key] = counts.get(key, 0) + 1
    ordinal: dict[str, int] = {}
    per_key: dict = {}
    for n in tops:
        key = (n["resource"]["part"], n["resource"]["object_id"])
        ordinal[n["id"]] = per_key.get(key, 0)
        per_key[key] = ordinal[n["id"]] + 1
    out = []
    for n in nodes:
        if n.get("mesh_key") is None:
            continue
        top = n
        while top.get("parent_id") is not None:
            top = by_id[top["parent_id"]]
        key = (top["resource"]["part"], top["resource"]["object_id"])
        total, index = counts[key], ordinal[top["id"]]
        label = f"Object {top['resource']['object_id']}" if total <= 1 else \
            f"Object {top['resource']['object_id']} · instance {index + 1} of {total}"
        mk = n["mesh_key"]
        out.append({"id": n["id"], "object_node": top["id"], "mesh": f"{mk['part']}#{mk['object_id']}", "world_mm": list(n["world_mm"]),
                    "build_index": n.get("build_index"), "label": label, "instance_index": index,
                    "instance_count": total, "plate_id": (n.get("plate") or {}).get("plate_id"),
                    "bounds_mm": n.get("bounds_mm")})
    return out


class _Slots:
    """What each slot prints, tallied as geometry is emitted."""

    def __init__(self) -> None:
        self.stats: dict[int, dict] = {}

    def entry(self, slot: int) -> dict:
        found = self.stats.get(slot)
        if found is None:
            found = self.stats[slot] = {"painted_facets": 0, "area": 0.0, "painted_area": 0.0,
                                        "from_painting": False, "from_assignment": False}
        return found


def _area(a, b, c) -> float:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    return 0.5 * (cx * cx + cy * cy + cz * cz) ** 0.5


class _Out:
    """Triangles per (mesh, slot), counted against the budget as they are added."""

    def __init__(self) -> None:
        self.parts: dict[str, dict] = {}
        self.total = 0

    def add(self, mesh: str, slot, points) -> None:
        self.total += 1
        if self.total > MAX_TRIANGLES_OUT:
            raise _Refusal("limit", f"This project draws to more than {MAX_TRIANGLES_OUT:,} triangles once its paint is "
                                    "split exactly. Studio shows the preview only when it can show all of it.")
        buf = self.parts.setdefault(mesh, {}).setdefault(slot, array("f"))
        for p in points:
            buf.extend((p[0], p[1], p[2]))


def _note(notes: list[str], why: str | None) -> None:
    """A plain sentence for the person, once, however many facets share the reason."""
    if not why:
        return
    text = why[:1].upper() + why[1:] + "."
    if text not in notes and len(notes) < MAX_NOTES:
        notes.append(text)


def _b64(buf: array) -> str:
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _dialect(tm: ThreeMF, model_parts: list[str]) -> tuple[str | None, bool]:
    """(dialect, has_paint). The dialect is the one whose attribute is present; failing that, the one whose
    settings part is present (a project can assign filaments without painting)."""
    for part in model_parts:
        try:
            found = pc._dialect_of(tm.read_part(part))
        except Exception:
            continue
        if found:
            return found, True
    if tm.has_part(pc.BAMBU_MODEL_SETTINGS):
        return pc.DIALECT_BAMBU, False
    if tm.has_part(pc.PRUSA_MODEL_CONFIG):
        return pc.DIALECT_PRUSA, False
    return None, False


def _stamp(path: str):
    try:
        st = os.stat(path)
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return None


def _build(path: str) -> dict:
    before = _stamp(path)
    sc = scene.build_scene_dict(path)
    is_3mf = path.lower().endswith(".3mf")
    notes: list[str] = [_BASE_NOTE]
    codes = {lim.get("code") for lim in sc.get("limitations", [])}
    if codes & {"UNSUPPORTED_UNIT", "NON_MM_SOURCE_UNIT"}:
        raise _Refusal("unsupported", "This project's unit is not a millimetre Studio can rely on, and Studio draws the preview only for "
                                      "millimetre projects. It does not guess or convert units.")
    if "UNKNOWN_VOLUME_ROLE" in codes or any(
            n.get("mesh_key") is not None and (n.get("role_context") not in (None, "part") or n.get("has_non_part_volumes"))
            for n in sc.get("nodes", [])):
        raise _Refusal("unsupported", "This project has modifiers, negative parts or helper volumes that do not print as surface. "
                                      "Studio does not draw those, so it does not draw this project's colours.")

    if is_3mf:
        odd = [s for s in sc.get("sources", []) if s.get("unit") != "millimeter" or s.get("mm_per_unit") != 1.0]
        if odd:
            raise _Refusal("unsupported", "This project is not in millimetres, and Studio draws the preview only for "
                                          "millimetre projects. It does not convert units on its own.")
    else:
        notes.append("An STL file carries no unit; it is drawn as millimetres.")

    meshes_by_key = {f"{m['key']['part']}#{m['key']['object_id']}": m for m in sc["meshes"]}
    instances = _instances(sc)
    if not instances:
        raise _Refusal("unsupported", "This file has nothing placed on a plate to draw.")

    slots = _Slots()
    out = _Out()
    counts = {"triangles_out": 0, "painted_triangles": 0, "leaves": 0, "malformed": 0}
    unknown_default = False
    declared: list[dict] = []
    kind = "geometry"

    tm = ThreeMF.open(path) if is_3mf else None
    dialect, has_paint = (None, False)
    model_parts: list[str] = []
    if tm is not None:
        model_parts = [p for p in tm.list_parts() if p.lower().endswith(".model")]
        dialect, has_paint = _dialect(tm, model_parts)

    if tm is not None:
        cfg, _plates = _read_settings(tm)
        if cfg is not None:
            from .project_materials import extract_slots
            declared = extract_slots(cfg)
        elif dialect == pc.DIALECT_PRUSA:
            notes.append("This project does not list filament colours, so its slots have no colour here.")

    if dialect is None:
        # No slot information at all (an STL, or a 3MF with no project settings): geometry only, one neutral part.
        for key, mesh in meshes_by_key.items():
            pos, idx = _decode_mesh(mesh)
            for t in range(0, len(idx), 3):
                out.add(key, None, [pos[idx[t + k] * 3: idx[t + k] * 3 + 3] for k in range(3)])
        unknown_default = True
        notes.append("This file carries no filament assignment, so it is drawn in one neutral colour.")
    else:
        kind = "painted" if has_paint else "assigned"
        settings = pc._bambu_parts(tm) if dialect == pc.DIALECT_BAMBU else pc._prusa_volumes(tm)
        part_name = {_norm(m["key"]["part"]): m["key"]["part"] for m in meshes_by_key.values()}
        for part in model_parts:
            if _norm(part) not in part_name:
                continue
            for open_tag, body in pc._object_regions(tm.read_part(part)):
                oid = pc._attrs(open_tag).get("id")
                if oid is None:
                    continue
                key = f"{part_name[_norm(part)]}#{oid}"
                if key not in meshes_by_key:
                    continue
                unknown_default |= _emit_mesh(key, oid, body, dialect, settings, slots, out, counts, notes,
                                              meshes_by_key[key]["triangle_count"])
        missing = [k for k in meshes_by_key if k not in out.parts]
        if missing:
            raise _Refusal("unsupported", "Studio could not match this project's painting to its geometry, so it does not draw it.")

    counts["triangles_out"] = out.total
    uses: dict[str, int] = {}
    for inst in instances:
        uses[inst["mesh"]] = uses.get(inst["mesh"], 0) + 1
    rendered = sum(sum(len(b) // 9 for b in parts.values()) * uses.get(key, 0) for key, parts in out.parts.items())
    if rendered > MAX_RENDERED_TRIANGLES:
        raise _Refusal("limit", f"Drawn once for every placed copy this project is {rendered:,} triangles, more than the {MAX_RENDERED_TRIANGLES:,} "
                                "Studio draws. Studio shows the preview only when it can show all of it.")
    counts["triangles_drawn"] = rendered
    if _stamp(path) != before or before is None:
        raise _Refusal("unreadable", "The file changed while Studio was reading it, so the preview was not drawn. Open it again.")
    slot_rows = _slot_rows(declared, slots)
    notes = notes[:MAX_NOTES - 2]
    if unknown_default:
        notes.append("Some surface has no filament stated by the project; it is drawn in a neutral colour, not assumed to be slot 1.")
    if counts["malformed"]:
        notes.append(f"{counts['malformed']:,} painted facet(s) could not be decoded; they are drawn neutral, not as painted.")

    meshes = [{"key": key, "parts": [{"slot": slot, "triangles": len(buf) // 9, "positions_f32le_base64": _b64(buf)}
                                     for slot, buf in sorted(parts.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))]}
              for key, parts in sorted(out.parts.items())]
    bed = sc.get("bed") or {}
    return {"schema": SCHEMA, "available": True, "state": "ok", "reason": None, "kind": kind,
            "bed": {"polygon_mm": bed.get("polygon_mm"), "height_mm": bed.get("height_mm")} if bed else None,
            "slots": slot_rows, "unknown_default": bool(unknown_default), "meshes": meshes, "instances": instances,
            "counts": counts, "limits": _limits(), "notes": notes}


def _read_settings(tm: ThreeMF):
    from .project_materials import read_project
    try:
        return read_project(tm)
    except Exception:
        return None, []


def _emit_mesh(key: str, oid: str, body: bytes, dialect: str, settings: dict, slots: _Slots, out: _Out,
               counts: dict, notes: list[str], expected_triangles: int) -> bool:
    """Emit one mesh's triangles by slot. Returns True when some surface has no stated slot."""
    vertices, truncated = pc._vertices(body)
    if truncated:
        raise _Refusal("limit", "A mesh has more vertices than Studio will read to draw its paint.")
    vcount = len(vertices) // 3
    ranges = None
    if dialect == pc.DIALECT_PRUSA:
        entry = settings.get(oid) or {}
        ranges = [(v.get("first_triangle"), v.get("last_triangle")) for v in entry.get("volumes") or []] or None
    info = {"object_id": oid}
    cache: dict = {}
    unknown = False

    def default_for(tri: int):
        if ranges is not None:
            vol = pc.volume_of(ranges, tri)
            k = ("v", vol)
            if k not in cache:
                cache[k] = (None, "no volume of this object claims that facet") if vol is None else pc._volume_slot(vol, info, settings)
            return cache[k]
        if "d" not in cache:
            cache["d"] = pc._default_slot(info, dialect, settings, {})
        return cache["d"]

    seen = 0
    painted_facets = 0
    for tri, (v1, v2, v3, painted) in enumerate(pc._facets(body)):
        seen += 1
        if v1 is None or not (0 <= v1 < vcount and 0 <= v2 < vcount and 0 <= v3 < vcount):
            raise _Refusal("unsupported", "A triangle refers to a vertex that does not exist, so Studio does not draw this project's paint.")
        corners = tuple(tuple(vertices[i * 3: i * 3 + 3]) for i in (v1, v2, v3))
        slot, why = default_for(tri)
        if painted:
            painted_facets += 1
            counts["painted_triangles"] += 1
            if counts["painted_triangles"] > MAX_PAINTED_FACETS:
                raise _Refusal("limit", f"This project has more than {MAX_PAINTED_FACETS:,} painted facets; Studio shows the preview only when it can show all of it.")
            try:
                leaves, leaf_truncated = paint_codec.decode(painted, corners)
            except paint_codec.PaintFormatError:
                counts["malformed"] += 1
                out.add(key, None, corners)
                continue
            if leaf_truncated:
                raise _Refusal("limit", "A facet's paint is finer than Studio follows, so the preview is not drawn rather than drawn partly.")
            counts["leaves"] += len(leaves)
            touched = set()
            for leaf in leaves:
                if not leaf.points:
                    raise _Refusal("unsupported", "A painted facet could not be placed, so Studio does not draw this project's paint.")
                state = leaf.state
                target = slot if state == paint_codec.STATE_UNPAINTED else state
                if target is None:
                    unknown = True
                    _note(notes, why)
                a = _area(*leaf.points)
                if target is not None:
                    row = slots.entry(target)
                    row["area"] += a
                    if state != paint_codec.STATE_UNPAINTED:
                        row["painted_area"] += a
                        row["from_painting"] = True
                        touched.add(target)
                    else:
                        row["from_assignment"] = True
                out.add(key, target, leaf.points)
            for target in touched:
                slots.entry(target)["painted_facets"] += 1
        else:
            if slot is None:
                unknown = True
                _note(notes, why)
            else:
                row = slots.entry(slot)
                row["area"] += _area(*corners)
                row["from_assignment"] = True
            out.add(key, slot, corners)
    if seen != expected_triangles:
        raise _Refusal("unsupported", "Studio could not match this project's painting to its geometry, so it does not draw it.")
    return unknown


def _slot_rows(declared: list[dict], slots: _Slots) -> list[dict]:
    rows = []
    known = {d["slot"] + 1: d for d in declared}
    for number in sorted(set(known) | set(slots.stats)):
        d = known.get(number) or {}
        s = slots.stats.get(number) or {}
        rows.append({"slot": number, "colour": d.get("colour"), "material": d.get("material"),
                     "painted_triangles": s.get("painted_facets", 0), "area_mm2": round(s.get("area", 0.0), 4),
                     "painted_area_mm2": round(s.get("painted_area", 0.0), 4),
                     "from_painting": bool(s.get("from_painting")), "from_assignment": bool(s.get("from_assignment")),
                     "declared": number in known})
    return rows
