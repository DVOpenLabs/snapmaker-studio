"""Painted multi-material colour, read from a project before anything is sliced.

Until this module existed, Studio could prove a project *had* painted regions and
nothing more, and said so: "painted colour cannot be classified without slicing".
That was true of the marker it was reading — a byte count — and untrue of the
file. The paint is in the project, in full, and it can be read.

What this reads, and what each fact is worth:

* **Which filament slots the painting references.** Exact. This is what turns a
  six-colour project with four toolheads from "cannot classify" into a real
  answer about which colours are actually needed.
* **How much of each object is painted.** Two different facts, kept apart:
  the number of painted facets, and the painted *area*. A mesh's triangles are
  not equal in size, so "40% of the triangles" is not "40% of the surface", and
  Studio reports both rather than letting one stand in for the other.
* **Where each painted colour sits in Z.** Reconstructed from the painted patches
  themselves and put through the object's own transforms, so the heights are the
  heights on the plate.

And what it deliberately does not answer: whether two colours land on the *same
printed layer*. Bounding heights that overlap do not prove a shared layer, and
proving one needs the slicer. :func:`coexistence` states which pairs are proven
separate, which are proven to overlap in Z, and which remain unknown — the last
being an honest answer, not a failure.

The layouts read here are the ones the PrusaSlicer and BambuStudio/OrcaSlicer
families publish and have kept stable for interchange. This is an independent
reader of a container format; the encoding itself lives in :mod:`paint_codec`.
"""
from __future__ import annotations

import re
from array import array

from . import paint_codec
from .container import ThreeMF
from .errors import UnsafeArchive

SCHEMA_VERSION = "paintedcolor/1"

# The two dialects of the same encoding. They differ in the attribute's name and
# in which metadata records the format version — not in the bits.
DIALECT_PRUSA = "prusa"
DIALECT_BAMBU = "bambu"

_ATTRIBUTE = {
    DIALECT_PRUSA: "slic3rpe:mmu_segmentation",
    DIALECT_BAMBU: "paint_color",
}
_VERSION_METADATA = {
    DIALECT_PRUSA: "slic3rpe:MmPaintingVersion",
    DIALECT_BAMBU: "BambuStudio:MmPaintingVersion",
}
# The dialect a file is in is decided by the attribute actually present, because
# that is the thing being decoded. Prusa is checked first: its attribute is
# namespaced and cannot be confused with anything else.
_DIALECT_ORDER = (DIALECT_PRUSA, DIALECT_BAMBU)

MODEL_PART = "3D/3dmodel.model"
BAMBU_MODEL_SETTINGS = "Metadata/model_settings.config"
PRUSA_MODEL_CONFIG = "Metadata/Slic3r_PE_model.config"

# Confidence tiers, matching project_traits.
CONFIRMED = "confirmed"
LIKELY = "likely"
UNKNOWN = "unknown"

# Bounds. Every one of these is a refusal to let a file decide how much work
# Studio does. Exceeding one is reported, never silently ignored.
MAX_OBJECTS = 512
MAX_VERTICES_PER_OBJECT = 4_000_000
MAX_TRIANGLES_PER_OBJECT = 4_000_000
MAX_PAINTED_TRIANGLES = 400_000
# Facets bound the work only if each is cheap. A finely subdivided facet decodes
# into thousands of patches, so the patches are bounded too — otherwise a project
# with a modest facet count could still ask for an unbounded amount of work.
MAX_PAINTED_LEAVES = 2_000_000
MAX_MALFORMED_REPORTED = 20

_OBJECT_SPLIT_RE = re.compile(rb"<object\b")
_TAG_ATTR_RE = re.compile(rb"""([A-Za-z_:][\w.:-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_VERTEX_RE = re.compile(rb"<vertex\b([^>]*)/?>")
_TRIANGLE_RE = re.compile(rb"<triangle\b([^>]*?)/?>")
_COMPONENT_RE = re.compile(rb"<component\b([^>]*)/?>")
# The exact shape every slicer in this family writes, matched in one pass so a
# mesh with a million facets costs one regex rather than one per attribute. A
# file written any other way falls back to the general parser below, so the fast
# path can never change *what* is read — only how quickly.
_FAST_VERTEX_RE = re.compile(rb'<vertex x="([^"]*)" y="([^"]*)" z="([^"]*)"')
_FAST_TRIANGLE_RE = re.compile(
    rb'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"'
    rb'(?:\s+(?:paint_color|slic3rpe:mmu_segmentation)="([^"]*)")?\s*/?>')
_METADATA_RE = re.compile(
    rb"""<metadata\b[^>]*\bname=(?:"([^"]+)"|'([^']+)')[^>]*>([^<]*)</metadata>""")
_XML_KEY_VALUE_RE = re.compile(
    r"""<metadata\b[^>]*\bkey="([^"]+)"[^>]*\bvalue="([^"]*)\"""")


def _attrs(fragment: bytes) -> dict:
    return {name.decode("ascii", "ignore"): (dq if dq else sq).decode("utf-8", "ignore")
            for name, dq, sq in _TAG_ATTR_RE.findall(fragment)}


def _floats(text: str) -> list[float]:
    out = []
    for token in text.replace(",", " ").split():
        try:
            out.append(float(token))
        except ValueError:
            return []
    return out


def _identity() -> tuple:
    return (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)


def _matrix(text: str | None) -> tuple | None:
    """A 3MF transform: nine rotation/scale terms then three of translation."""
    if not text:
        return None
    values = _floats(text)
    if len(values) == 12:
        return tuple(values)
    if len(values) == 16:
        # A 4x4 written row-major with the trivial last row, as model_settings
        # records a part's matrix. The same twelve numbers, differently arranged.
        return (values[0], values[1], values[2],
                values[4], values[5], values[6],
                values[8], values[9], values[10],
                values[3], values[7], values[11])
    return None


def _apply(matrix: tuple, point: tuple) -> tuple:
    x, y, z = point
    return (matrix[0] * x + matrix[3] * y + matrix[6] * z + matrix[9],
            matrix[1] * x + matrix[4] * y + matrix[7] * z + matrix[10],
            matrix[2] * x + matrix[5] * y + matrix[8] * z + matrix[11])


def _compose(outer: tuple, inner: tuple) -> tuple:
    """Outer applied after inner."""
    cols = []
    for col in range(3):
        base = (inner[col * 3], inner[col * 3 + 1], inner[col * 3 + 2])
        x, y, z = base
        cols.extend([outer[0] * x + outer[3] * y + outer[6] * z,
                     outer[1] * x + outer[4] * y + outer[7] * z,
                     outer[2] * x + outer[5] * y + outer[8] * z])
    translated = _apply(outer, (inner[9], inner[10], inner[11]))
    return tuple(cols) + translated


def _dialect_of(blob: bytes) -> str | None:
    for dialect in _DIALECT_ORDER:
        if _ATTRIBUTE[dialect].encode("ascii") in blob:
            return dialect
    return None


def _version(tm: ThreeMF, dialect: str) -> tuple[int | None, str | None]:
    """The painting format version the file declares, if it declares one."""
    name = _VERSION_METADATA[dialect].encode("ascii")
    for part in tm.list_parts():
        if not part.lower().endswith(".model"):
            continue
        try:
            head = tm.read_part(part)[:64 * 1024]
        except Exception:
            continue
        if name not in head:
            continue
        for dq, sq, text in _METADATA_RE.findall(head):
            if (dq or sq) == name:
                try:
                    return int(text.strip()), part
                except ValueError:
                    return None, part
    return None, None


def volume_of(ranges: list[tuple], facet: int) -> int | None:
    """Which volume owns this facet, or None when the file does not say.

    Measured against PrusaSlicer 2.9.6: `firstid`/`lastid` are **inclusive**, and
    the slicer always writes contiguous ascending ranges that partition the mesh.
    Handed a project whose ranges left a gap it re-laid the volumes contiguously
    and wrote a shorter mesh; handed overlapping ranges it duplicated the shared
    triangles into the second volume and renumbered; handed a reversed range, or
    one past the end of the mesh, it refused to write a file at all.

    So a genuine file always answers this question exactly once. A file that is
    not genuine may answer it twice or not at all, and both of those are
    **unknown** — never the slot of whichever volume happens to be first, which
    is how an object's second volume used to inherit the first one's filament.
    """
    owner = None
    for index, (first, last) in enumerate(ranges):
        if first is None or last is None or first > last:
            continue
        if first <= facet <= last:
            if owner is not None:
                return None            # two volumes claim it; the file is wrong
            owner = index
    return owner


def _slot_bucket(slot: int) -> dict:
    """One filament slot's tally across a whole project."""
    return {"slot": slot, "triangles_touching": 0, "facet_equivalent": 0.0,
            "leaf_count": 0, "area_mm2": 0.0,
            # Where the slot is used at all — painting and assigned body both.
            "z_min_mm": None, "z_max_mm": None,
            # Where its *painting* is, which is a different and narrower fact.
            "painted_z_min_mm": None, "painted_z_max_mm": None,
            "objects": [], "from_painting": False, "from_assignment": False}


class _Budget:
    """The painting work one file is allowed, shared by every object in it."""

    def __init__(self, facets: int, leaves: int):
        self.facets = facets
        self.leaves = leaves
        self.exhausted = False

    def take(self) -> bool:
        if self.facets <= 0 or self.leaves <= 0:
            self.exhausted = True
            return False
        self.facets -= 1
        return True

    def spend_leaves(self, count: int) -> None:
        self.leaves -= count


def _object_regions(blob: bytes) -> list[tuple[bytes, bytes]]:
    """(open tag, body) for each <object> in a model part."""
    out = []
    starts = [m.start() for m in _OBJECT_SPLIT_RE.finditer(blob)]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(blob)
        chunk = blob[start:end]
        close = chunk.find(b">")
        if close < 0:
            continue
        out.append((chunk[:close + 1], chunk[close + 1:]))
        if len(out) >= MAX_OBJECTS:
            break
    return out


def _vertices(body: bytes) -> tuple[array, bool]:
    """A mesh's corners as a flat array of coordinates.

    Flat rather than a list of tuples because a painted model routinely carries a
    million of them, and three floats in an array cost a fraction of what three
    float objects in a tuple do. Matches are walked one at a time rather than
    collected, so peak memory does not scale with the mesh either.
    """
    out = array("d")
    limit = MAX_VERTICES_PER_OBJECT * 3
    for match in _VERTEX_RE.finditer(body):
        fast = _FAST_VERTEX_RE.match(match.group(0))
        try:
            if fast:
                out.extend((float(fast.group(1)), float(fast.group(2)),
                            float(fast.group(3))))
            else:
                attrs = _attrs(match.group(1))
                out.extend((float(attrs.get("x", "0")), float(attrs.get("y", "0")),
                            float(attrs.get("z", "0"))))
        except ValueError:
            out.extend((0.0, 0.0, 0.0))
        if len(out) > limit:
            return out, True
    return out, False


def _extent(body: bytes) -> tuple[float | None, float | None]:
    """The height a mesh spans, in its own coordinates.

    Cheap on purpose: the corners are read once and only their Z is kept, so an
    unpainted mesh costs a scan rather than a decode.
    """
    vertices, _ = _vertices(body)
    if not vertices:
        return None, None
    heights = vertices[2::3]
    return min(heights), max(heights)


def _facets(body: bytes):
    """(v1, v2, v3, paint attribute) for every triangle in a mesh.

    The attribute order every slicer in this family writes is matched in one
    step; a facet written any other way falls back to full attribute parsing, so
    the shortcut changes how fast a mesh is read and never what is read from it.
    """
    for match in _TRIANGLE_RE.finditer(body):
        tag = match.group(0)
        fast = _FAST_TRIANGLE_RE.match(tag)
        if fast is not None:
            painted = fast.group(4)
            yield (int(fast.group(1)), int(fast.group(2)), int(fast.group(3)),
                   painted.decode("ascii", "ignore") if painted else "")
            continue
        attrs = _attrs(match.group(1))
        try:
            corners = (int(attrs["v1"]), int(attrs["v2"]), int(attrs["v3"]))
        except (KeyError, ValueError):
            yield (None, None, None, None)
            continue
        yield corners + (attrs.get("paint_color")
                         or attrs.get("slic3rpe:mmu_segmentation") or "",)


def _read_object(open_tag: bytes, body: bytes, attribute: str,
                 budget: _Budget, ranges: list | None = None) -> dict | None:
    """Everything one mesh says about its painting.

    `ranges` are the source volumes' inclusive triangle ranges, where the dialect
    has them. They decide which volume an unpainted patch belongs to, and so which
    filament it prints in — a question one answer per mesh cannot answer for an
    object whose volumes disagree.
    """
    attrs = _attrs(open_tag)
    object_id = attrs.get("id")
    painted_marker = attribute.encode("ascii")
    components = [_attrs(m.group(1)) for m in _COMPONENT_RE.finditer(body)]

    if painted_marker not in body:
        triangle_count = body.count(b"<triangle ")
        if triangle_count == 0 and not components:
            return None
        # An unpainted mesh still has a height, and that height is what makes a
        # painted colour provably separate from a colour assigned to a whole
        # object. Without it every comparison against an assigned colour ends in
        # "cannot be proven", which is honest and useless.
        low, high = _extent(body)
        return {"object_id": object_id, "name": attrs.get("name"),
                "triangle_count": triangle_count, "painted_triangle_count": 0,
                "components": components, "painted": False,
                "z_min": low, "z_max": high}

    vertices, vertices_truncated = _vertices(body)
    counts: dict[int, dict] = {}
    unpainted_by_volume: dict[object, dict] = {}
    triangle_count = 0
    painted_count = 0
    leaf_total = 0
    malformed: list[str] = []
    malformed_count = 0
    outside_mesh = 0
    truncated = vertices_truncated
    total_area = 0.0

    vertex_count = len(vertices) // 3
    area_of = paint_codec.area
    decode = paint_codec.decode
    for v1, v2, v3, painted in _facets(body):
        triangle_count += 1
        if triangle_count > MAX_TRIANGLES_PER_OBJECT:
            truncated = True
            break
        if v1 is None:
            malformed_count += 1
            if len(malformed) < MAX_MALFORMED_REPORTED:
                malformed.append("a triangle does not name three vertices")
            continue
        corners = None
        if 0 <= v1 < vertex_count and 0 <= v2 < vertex_count and 0 <= v3 < vertex_count:
            corners = ((vertices[v1 * 3], vertices[v1 * 3 + 1], vertices[v1 * 3 + 2]),
                       (vertices[v2 * 3], vertices[v2 * 3 + 1], vertices[v2 * 3 + 2]),
                       (vertices[v3 * 3], vertices[v3 * 3 + 1], vertices[v3 * 3 + 2]))
            total_area += area_of(corners)
        elif painted:
            # A painted facet pointing outside its own mesh has no place, so its
            # area and height cannot be known — but which filament it names still
            # can be, and dropping that would lose a fact the file does carry.
            # It is decoded without geometry and counted as what it is.
            outside_mesh += 1
        if not painted:
            continue
        if not budget.take():
            truncated = True
            break
        try:
            leaves, leaf_truncated = decode(painted, corners)
        except paint_codec.PaintFormatError as exc:
            malformed_count += 1
            if len(malformed) < MAX_MALFORMED_REPORTED:
                malformed.append(str(exc))
            continue
        truncated = truncated or leaf_truncated
        painted_count += 1
        leaf_total += len(leaves)
        budget.spend_leaves(len(leaves))
        whole_area = area_of(corners) if corners else 0.0
        seen_here = set()
        owner = (volume_of(ranges, triangle_count - 1)
                 if ranges else None)
        for leaf in leaves:
            if leaf.state == paint_codec.STATE_UNPAINTED and ranges is not None:
                # An unpainted patch prints in whatever its own volume is
                # assigned, so it is tallied against that volume rather than
                # against the mesh as a whole.
                entry = unpainted_by_volume.get(owner)
                if entry is None:
                    entry = unpainted_by_volume[owner] = {
                        "leaf_count": 0, "facet_share": 0.0, "area_mm2": 0.0,
                        "triangles": 0, "z_min": None, "z_max": None}
                seen_key = ("unpainted", owner)
            else:
                entry = counts.get(leaf.state)
                if entry is None:
                    entry = counts[leaf.state] = {
                        "leaf_count": 0, "facet_share": 0.0, "area_mm2": 0.0,
                        "triangles": 0, "z_min": None, "z_max": None}
                seen_key = leaf.state
            entry["leaf_count"] += 1
            if seen_key not in seen_here:
                # How many of the mesh's own facets this slot appears on, counted
                # once each however finely the facet is subdivided.
                seen_here.add(seen_key)
                entry["triangles"] += 1
            entry["facet_share"] += leaf.fraction
            entry["area_mm2"] += whole_area * leaf.fraction
            if leaf.points:
                zs = (leaf.points[0][2], leaf.points[1][2], leaf.points[2][2])
                low, high = min(zs), max(zs)
                entry["z_min"] = low if entry["z_min"] is None else min(entry["z_min"], low)
                entry["z_max"] = high if entry["z_max"] is None else max(entry["z_max"], high)

    heights = vertices[2::3]
    return {"object_id": object_id, "name": attrs.get("name"),
            "triangle_count": triangle_count,
            "painted_triangle_count": painted_count,
            "facets_outside_mesh": outside_mesh,
            "z_min": min(heights) if heights else None,
            "z_max": max(heights) if heights else None,
            "leaf_count": leaf_total,
            "states": counts,
            "unpainted_by_volume": unpainted_by_volume,
            "mesh_area_mm2": total_area,
            "malformed_triangle_count": malformed_count,
            "malformed_examples": malformed,
            "components": components,
            "truncated": truncated,
            "painted": painted_count > 0 or malformed_count > 0}


def _bambu_parts(tm: ThreeMF) -> dict:
    """Part-level facts from model_settings.config: names and slot assignments."""
    if not tm.has_part(BAMBU_MODEL_SETTINGS):
        return {}
    try:
        text = tm.read_part(BAMBU_MODEL_SETTINGS).decode("utf-8", "ignore")
    except Exception:
        return {}
    out = {}
    for chunk in re.split(r"<object\b", text)[1:]:
        head = chunk.split(">", 1)
        object_id = None
        match = re.search(r'id="([^"]+)"', head[0] if head else "")
        if match:
            object_id = match.group(1)
        body = chunk
        object_extruder = None
        for key, value in _XML_KEY_VALUE_RE.findall(body.split("<part", 1)[0]):
            if key == "extruder" and value.strip().isdigit():
                object_extruder = int(value)
        parts = {}
        for part_chunk in re.split(r"<part\b", body)[1:]:
            part_id = None
            match = re.search(r'id="([^"]+)"', part_chunk.split(">", 1)[0])
            if match:
                part_id = match.group(1)
            info = {"extruder": None, "name": None, "matrix": None,
                    "subtype": None}
            match = re.search(r'subtype="([^"]+)"', part_chunk.split(">", 1)[0])
            if match:
                info["subtype"] = match.group(1)
            for key, value in _XML_KEY_VALUE_RE.findall(part_chunk):
                if key == "extruder" and value.strip().isdigit():
                    info["extruder"] = int(value)
                elif key == "name":
                    info["name"] = value
                elif key == "matrix":
                    info["matrix"] = value
            if part_id:
                parts[part_id] = info
        if object_id:
            out[object_id] = {"extruder": object_extruder, "parts": parts}
    return out


def _prusa_volumes(tm: ThreeMF) -> dict:
    """Volume ranges and their slots, from the Prusa dialect's model config."""
    if not tm.has_part(PRUSA_MODEL_CONFIG):
        return {}
    try:
        text = tm.read_part(PRUSA_MODEL_CONFIG).decode("utf-8", "ignore")
    except Exception:
        return {}
    out = {}
    for chunk in re.split(r"<object\b", text)[1:]:
        match = re.search(r'id="([^"]+)"', chunk.split(">", 1)[0])
        object_id = match.group(1) if match else None
        object_slot = None
        for key, value in re.findall(
                r'<metadata\s+type="object"\s+key="([^"]+)"\s+value="([^"]*)"',
                chunk.split("<volume", 1)[0]):
            if key == "extruder" and value.strip().isdigit():
                object_slot = int(value)
        volumes = []
        for volume_chunk in re.split(r"<volume\b", chunk)[1:]:
            head = volume_chunk.split(">", 1)[0]
            first = re.search(r'firstid="(\d+)"', head)
            last = re.search(r'lastid="(\d+)"', head)
            info = {"first_triangle": int(first.group(1)) if first else None,
                    "last_triangle": int(last.group(1)) if last else None,
                    "extruder": None, "name": None}
            for key, value in re.findall(
                    r'<metadata[^>]*\bkey="([^"]+)"[^>]*\bvalue="([^"]*)"',
                    volume_chunk):
                if key == "extruder" and value.strip().isdigit():
                    info["extruder"] = int(value)
                elif key == "name":
                    info["name"] = value
            volumes.append(info)
        if object_id:
            out[object_id] = {"volumes": volumes, "extruder": object_slot}
    return out


def _build_transforms(tm: ThreeMF) -> dict:
    """Object id -> the transform the plate places that object with."""
    if not tm.has_part(MODEL_PART):
        return {}
    try:
        blob = tm.read_part(MODEL_PART)
    except Exception:
        return {}
    out = {}
    build = blob.split(b"<build", 1)
    if len(build) < 2:
        return {}
    for match in re.finditer(rb"<item\b([^>]*)/?>", build[1]):
        attrs = _attrs(match.group(1))
        object_id = attrs.get("objectid")
        if object_id:
            out.setdefault(object_id, _matrix(attrs.get("transform")) or _identity())
    return out


def read(path: str) -> dict:
    """Read a project's painted colour. Never raises for a caller in a UI."""
    try:
        tm = ThreeMF.open(path)
    except UnsafeArchive as exc:
        return _unavailable(str(exc))
    except Exception:
        return _unavailable("Studio could not read this file as a 3MF project.")
    return read_container(tm)


def read_container(tm: ThreeMF) -> dict:
    model_parts = [p for p in tm.list_parts() if p.lower().endswith(".model")]
    if not model_parts:
        return _unavailable("This project carries no model geometry.")

    dialect = None
    readable = failed = 0
    for part in model_parts:
        try:
            found = _dialect_of(tm.read_part(part))
            readable += 1
        except Exception:
            failed += 1
            continue
        if found:
            dialect = found
            break
    if dialect is None:
        if failed:
            # A part that could not be read may be the painted one: nothing can be said about painting.
            return _unavailable(f"Studio could not read {failed} of {len(model_parts)} model geometry part(s).")
        return _none_found(readable)

    attribute = _ATTRIBUTE[dialect]
    version, version_part = _version(tm, dialect)
    budget = _Budget(MAX_PAINTED_TRIANGLES, MAX_PAINTED_LEAVES)

    # The volume graph is read first: a mesh cannot be attributed to volumes it
    # has not been told about.
    settings = (_bambu_parts(tm) if dialect == DIALECT_BAMBU else _prusa_volumes(tm))

    # Mesh-level reading, keyed by the id each mesh object carries.
    meshes: dict[str, dict] = {}
    mesh_part: dict[str, str] = {}
    for part in model_parts:
        try:
            blob = tm.read_part(part)
        except Exception:
            continue
        for open_tag, body in _object_regions(blob):
            ranges = None
            if dialect == DIALECT_PRUSA:
                found = re.search(rb'id="([^"]+)"', open_tag)
                entry = settings.get(found.group(1).decode("ascii", "ignore")) if found else None
                if entry:
                    ranges = [(v.get("first_triangle"), v.get("last_triangle"))
                              for v in entry.get("volumes") or []]
            info = _read_object(open_tag, body, attribute, budget, ranges)
            if info is None:
                continue
            key = f"{part}#{info.get('object_id')}"
            info["part"] = part
            meshes[key] = info
            if info.get("object_id"):
                mesh_part.setdefault(info["object_id"], key)

    placements = _build_transforms(tm)

    objects = []
    slots: dict[int, dict] = {}
    unresolved_default = False
    for key, info in meshes.items():
        if not info.get("painted"):
            continue
        entry = _describe(info, key, dialect, settings, placements, meshes, mesh_part)
        objects.append(entry)
        if entry["default_slot"] is None and entry["unpainted_facet_share"] > 0:
            unresolved_default = True
        if entry["default_slot"] is not None and entry["z_min_mm"] is not None:
            # The parts of this mesh nobody painted print in its own slot, over
            # the mesh's whole height — not only where a painted facet happens to
            # leave a gap.
            bucket = slots.setdefault(entry["default_slot"],
                                      _slot_bucket(entry["default_slot"]))
            bucket["from_assignment"] = True
            for name, value, pick in (("z_min_mm", entry["z_min_mm"], min),
                                      ("z_max_mm", entry["z_max_mm"], max)):
                bucket[name] = value if bucket[name] is None else pick(bucket[name], value)
        for assignment in entry["assignments"]:
            slot = assignment["slot"]
            if slot is None:
                continue
            bucket = slots.setdefault(slot, _slot_bucket(slot))
            bucket["triangles_touching"] += assignment["triangles_touching"]
            bucket["facet_equivalent"] += assignment["facet_equivalent"]
            bucket["leaf_count"] += assignment["leaf_count"]
            bucket["area_mm2"] += assignment["area_mm2"]
            bucket["objects"].append(entry["object_id"])
            bucket["from_painting"] = bucket["from_painting"] or assignment["painted"]
            bucket["from_assignment"] = (bucket["from_assignment"]
                                         or not assignment["painted"])
            # Two ranges, because they answer two questions. The painted range is
            # where this colour was painted; the used range is everywhere the
            # slot prints, painting and assigned body together, and that is the
            # one a shared layer depends on.
            for name, value, pick in (("z_min_mm", assignment["z_min_mm"], min),
                                      ("z_max_mm", assignment["z_max_mm"], max)):
                if value is None:
                    continue
                bucket[name] = value if bucket[name] is None else pick(bucket[name], value)
            if assignment["painted"]:
                for name, value, pick in (
                        ("painted_z_min_mm", assignment["z_min_mm"], min),
                        ("painted_z_max_mm", assignment["z_max_mm"], max)):
                    if value is None:
                        continue
                    bucket[name] = (value if bucket[name] is None
                                    else pick(bucket[name], value))

    # A mesh that carries no painting still occupies a height, and the slot it is
    # assigned to therefore has a measured extent. Without this, a painted colour
    # could never be proven separate from a colour assigned to a whole object —
    # which is every colour in most real projects, so the honest answer would
    # always have been "cannot be proven".
    for key, info in meshes.items():
        if info.get("painted"):
            continue
        slot, _ = _default_slot(info, dialect, settings, meshes)
        low, high = info.get("z_min"), info.get("z_max")
        if slot is None or low is None:
            continue
        transform, transform_known = _transform_for(
            info.get("object_id"), dialect, settings, placements, meshes)
        if transform is not None and _z_depends_only_on_z(transform):
            low, high = _placed_z({"z_min": low, "z_max": high}, transform)
        elif not transform_known:
            pass
        bucket = slots.setdefault(slot, _slot_bucket(slot))
        bucket["from_assignment"] = True
        bucket["objects"].append(info.get("object_id"))
        for name, value, pick in (("z_min_mm", round(low, 4), min),
                                  ("z_max_mm", round(high, 4), max)):
            bucket[name] = value if bucket[name] is None else pick(bucket[name], value)

    if not objects:
        # The attribute was present but nothing decoded from it — an empty
        # attribute on every triangle, for instance. That is a real state and is
        # reported as one.
        return _none_found(len(model_parts), marker_seen=True)

    truncated = any(o["truncated"] for o in objects)
    malformed = sum(o["malformed_triangle_count"] for o in objects)
    outside = sum(o["facets_outside_mesh"] for o in objects)
    painted_total = sum(o["painted_triangle_count"] for o in objects)

    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "reason": None,
        "dialect": dialect,
        "attribute": attribute,
        "format_version": version,
        "format_version_source": version_part,
        "format_version_known": version is not None,
        "objects": objects,
        "slots": [slots[key] for key in sorted(slots)],
        # The slots the *painting* names. A slot that only appears because an
        # object is assigned to it is in `slots` with its measured height, but it
        # is not something this project paints with, and saying otherwise would
        # overstate what was read.
        "slots_referenced": sorted(key for key, bucket in slots.items()
                                   if bucket["from_painting"]),
        "painted_triangle_count": painted_total,
        "malformed_triangle_count": malformed,
        "facets_outside_mesh": outside,
        "truncated": truncated,
        "default_slot_resolved": not unresolved_default,
        "confidence": _confidence(truncated, malformed + outside, version, dialect),
        "evidence": (f"{painted_total:,} painted facets read from "
                     f"{len(objects)} mesh(es) in this project, decoded from the "
                     f"{attribute} data the project carries"),
        "limits": {
            "max_painted_triangles": MAX_PAINTED_TRIANGLES,
            "max_painted_leaves": MAX_PAINTED_LEAVES,
            "max_leaves_per_triangle": paint_codec.MAX_LEAVES_PER_TRIANGLE,
            "budget_exhausted": budget.exhausted,
        },
    }


def _describe(info: dict, key: str, dialect: str, settings: dict,
              placements: dict, meshes: dict, mesh_part: dict) -> dict:
    """One painted mesh, with its slots resolved and its heights placed."""
    object_id = info.get("object_id")
    default_slot, default_source = _default_slot(info, dialect, settings, meshes)
    transform, transform_known = _transform_for(object_id, dialect, settings,
                                                placements, meshes)
    # A transform that leaves height depending on height alone can be applied to
    # a Z range exactly. One that tilts the object cannot: the height of a
    # painted patch then depends on where it sits in X and Y too, and Studio
    # reports the mesh's own heights and says they are not placed rather than
    # transforming two numbers that no longer describe the same thing.
    z_placeable = transform is not None and _z_depends_only_on_z(transform)

    assignments = []
    painted_share = 0.0
    unpainted_share = 0.0
    mesh_area = info.get("mesh_area_mm2") or 0.0

    # An unpainted patch prints in whatever its own volume is assigned. Where the
    # dialect states volumes, each one gets its own entry; where it does not, the
    # mesh has a single default and there is one entry, as before.
    by_volume = info.get("unpainted_by_volume") or {}
    entries = [(state, info["states"][state], None)
               for state in sorted(info.get("states", {}))]
    entries += [(paint_codec.STATE_UNPAINTED, stats, volume)
                for volume, stats in sorted(
                    by_volume.items(),
                    key=lambda pair: (pair[0] is None, pair[0]))]

    for state, stats, volume in entries:
        share = stats["facet_share"]
        if state == paint_codec.STATE_UNPAINTED:
            unpainted_share += share
            if volume is None and by_volume:
                slot, source = None, (
                    "no volume of this object claims that facet, so Studio cannot "
                    "say which colour its unpainted area prints in")
            elif volume is None:
                slot, source = default_slot, default_source
            else:
                slot, source = _volume_slot(volume, info, settings)
            painted = False
            evidence = (f"left unpainted, so it prints in slot {slot} — {source}"
                        if slot is not None else f"left unpainted, and {source}")
        else:
            painted_share += share
            slot = state
            painted = True
            evidence = (f"painted with slot {state}, read from this mesh's "
                        f"{_ATTRIBUTE[dialect]} data")
        z_min, z_max = stats["z_min"], stats["z_max"]
        if z_placeable and z_min is not None:
            z_min, z_max = _placed_z(stats, transform)
        assignments.append({
            "slot": slot,
            "state": state,
            "volume": volume,
            "painted": painted,
            # Two different facts, deliberately not merged: how many of the
            # mesh's own triangles carry any of this slot, and how much whole-
            # triangle area those parts add up to.
            "triangles_touching": stats["triangles"],
            "facet_equivalent": round(share, 6),
            "leaf_count": stats["leaf_count"],
            "area_mm2": round(stats["area_mm2"], 4),
            "area_share": (round(stats["area_mm2"] / mesh_area, 6)
                           if mesh_area > 0 else None),
            "z_min_mm": None if z_min is None else round(z_min, 4),
            "z_max_mm": None if z_max is None else round(z_max, 4),
            "z_is_placed": bool(transform_known and z_placeable and z_min is not None),
            "evidence": evidence,
        })

    mesh_low, mesh_high = info.get("z_min"), info.get("z_max")
    if mesh_low is not None and z_placeable:
        mesh_low, mesh_high = _placed_z({"z_min": mesh_low, "z_max": mesh_high},
                                        transform)
    return {
        "object_id": object_id,
        "part": info.get("part"),
        "z_min_mm": None if mesh_low is None else round(mesh_low, 4),
        "z_max_mm": None if mesh_high is None else round(mesh_high, 4),
        "name": info.get("name"),
        "triangle_count": info.get("triangle_count", 0),
        "painted_triangle_count": info.get("painted_triangle_count", 0),
        "unpainted_triangle_count": max(
            0, info.get("triangle_count", 0) - info.get("painted_triangle_count", 0)),
        "leaf_count": info.get("leaf_count", 0),
        "mesh_area_mm2": round(mesh_area, 4),
        "painted_facet_share": round(painted_share, 6),
        "unpainted_facet_share": round(unpainted_share, 6),
        "default_slot": default_slot,
        "default_slot_source": default_source,
        "assignments": assignments,
        "malformed_triangle_count": info.get("malformed_triangle_count", 0),
        "malformed_examples": info.get("malformed_examples", []),
        "facets_outside_mesh": info.get("facets_outside_mesh", 0),
        "truncated": bool(info.get("truncated")),
        "transform_known": transform_known,
    }


def _default_slot(info: dict, dialect: str, settings: dict,
                  meshes: dict) -> tuple[int | None, str]:
    """Which slot an unpainted facet of this mesh prints in.

    Unpainted is not "no colour": it is "whatever this part is already assigned".
    Where the project does not say, Studio does not guess — an unknown default is
    reported as unknown, because assuming slot 1 would invent a colour the
    project never asked for.
    """
    object_id = info.get("object_id")
    if dialect == DIALECT_BAMBU:
        for parent_id, entry in settings.items():
            for part_id, part in entry.get("parts", {}).items():
                if part_id != object_id:
                    continue
                if part.get("extruder"):
                    return part["extruder"], (
                        f"this part is assigned slot {part['extruder']} in the "
                        "project's own part settings")
                if entry.get("extruder"):
                    return entry["extruder"], (
                        f"this part's object is assigned slot {entry['extruder']} "
                        "in the project's own settings")
                return None, ("the project does not record a slot for this part, "
                              "so Studio cannot say which colour its unpainted "
                              "area prints in")
        return None, ("Studio could not match this mesh to a part in the "
                      "project's settings, so the unpainted area's slot is unknown")
    # The mesh-wide answer, used only where the file states no volumes at all.
    # Taking "the first volume with an extruder" as the whole object's default is
    # the defect this replaced: an object whose second volume prints in filament 5
    # had that volume's unpainted area counted under the first volume's filament.
    entry = settings.get(object_id) or {}
    if entry.get("extruder"):
        return entry["extruder"], (
            f"this object is assigned slot {entry['extruder']} in the project's "
            "own model config")
    volumes = entry.get("volumes") or []
    if len(volumes) == 1 and volumes[0].get("extruder"):
        return volumes[0]["extruder"], (
            f"this object's only volume is assigned slot {volumes[0]['extruder']} "
            "in the project's own model config")
    return None, ("the project does not record a slot for this volume, so "
                  "Studio cannot say which colour its unpainted area prints in")


def _volume_slot(volume: int, info: dict, settings: dict) -> tuple[int | None, str]:
    """Which slot one volume's unpainted area prints in.

    In order, and each step is a different fact: the volume's own assignment, the
    object's where the volume is silent, and otherwise unknown. Nothing inherits
    from a sibling volume, because a sibling's filament is a statement about the
    sibling.
    """
    entry = settings.get(info.get("object_id")) or {}
    volumes = entry.get("volumes") or []
    if volume >= len(volumes):
        return None, ("the project states no volume there, so Studio cannot say "
                      "which colour its unpainted area prints in")
    own = volumes[volume]
    if own.get("extruder"):
        return own["extruder"], (
            f"volume {volume + 1} is assigned slot {own['extruder']} in the "
            "project's own model config")
    if entry.get("extruder"):
        return entry["extruder"], (
            f"volume {volume + 1} states no slot of its own and its object is "
            f"assigned slot {entry['extruder']}")
    return None, (f"neither volume {volume + 1} nor its object states a slot, so "
                  "Studio cannot say which colour its unpainted area prints in")


def _transform_for(object_id, dialect, settings, placements, meshes):
    """The transform that takes this mesh's coordinates onto the plate.

    Returns (matrix, known). When the chain cannot be resolved the heights are
    still reported, but flagged as the mesh's own rather than the plate's.
    """
    if not object_id:
        return None, False
    if dialect == DIALECT_PRUSA:
        placed = placements.get(object_id)
        return (placed, True) if placed else (None, False)

    # The Bambu dialect nests: a plate item places an assembly object, which
    # carries components pointing at the meshes that were painted.
    for key, info in meshes.items():
        for component in info.get("components", []):
            if component.get("objectid") != object_id:
                continue
            parent_id = info.get("object_id")
            inner = _matrix(component.get("transform")) or _identity()
            outer = placements.get(parent_id)
            if outer is None:
                return inner, False
            return _compose(outer, inner), True
    placed = placements.get(object_id)
    return (placed, True) if placed else (None, False)


def _z_depends_only_on_z(transform: tuple) -> bool:
    """Whether this placement's height depends on height alone.

    True for the placements slicers actually write on a plate — translation,
    scaling, rotation about the vertical axis, and mirroring — and false for a
    tilt, which is the case Studio refuses to place.
    """
    return abs(transform[2]) <= 1e-9 and abs(transform[5]) <= 1e-9


def _placed_z(stats: dict, transform: tuple) -> tuple[float | None, float | None]:
    """A painted region's Z range after the object's own placement.

    Only the extremes need transforming: with height depending on height alone
    the mapping is linear in Z, so the range's ends stay its ends — and a
    negative scale, which mirrors, swaps which is which.
    """
    lo, hi = stats["z_min"], stats["z_max"]
    if lo is None:
        return None, None
    scale, offset = transform[8], transform[11]
    ends = [lo * scale + offset, hi * scale + offset]
    return min(ends), max(ends)


def _confidence(truncated: bool, malformed: int, version, dialect: str) -> str:
    if truncated or malformed:
        return LIKELY
    return CONFIRMED


def coexistence(result: dict, *, separation_mm: float = 0.0) -> dict:
    """Which painted slots can be proven not to share height, and which cannot.

    Three answers, and the third is the honest one most of the time:

    * ``separate`` — one slot's painting ends below where the other's begins.
      Proven from geometry: they cannot appear on the same layer.
    * ``overlaps`` — their painted heights overlap. This proves the *possibility*
      of a shared layer and nothing more; whether a given printed layer really
      contains both depends on the slice, which Studio does not do.
    * ``unknown`` — one of them has no usable height, so nothing is claimed.

    ``separation_mm`` is a margin a caller can demand before believing a
    separation, for the case where a layer straddles the boundary.
    """
    # Every slot whose height was measured takes part, painted or assigned: a
    # painted colour is only separate from an assigned one if the assigned one's
    # extent is known, and that is exactly the comparison a user needs.
    slots = [s for s in result.get("slots", [])
             if s.get("z_min_mm") is not None and s.get("z_max_mm") is not None]
    pairs = []
    for index, first in enumerate(slots):
        for second in slots[index + 1:]:
            verdict, reason = _pair_verdict(first, second, separation_mm)
            pairs.append({"slots": [first["slot"], second["slot"]],
                          "verdict": verdict, "reason": reason})
    proven_together = sorted({slot for pair in pairs if pair["verdict"] == "overlaps"
                              for slot in pair["slots"]})
    return {
        "pairs": pairs,
        "slots_overlapping": proven_together,
        "slots_separate": sorted({slot for pair in pairs
                                  if pair["verdict"] == "separate"
                                  for slot in pair["slots"]}
                                 - set(proven_together)),
        "unknown_pairs": [pair for pair in pairs if pair["verdict"] == "unknown"],
        "note": ("Overlapping heights show two colours *can* meet on a layer. "
                 "Whether a printed layer really carries both is a fact about "
                 "the slice, and Studio does not slice."),
    }


def _pair_verdict(first: dict, second: dict, margin: float) -> tuple[str, str]:
    low_a, high_a = first.get("z_min_mm"), first.get("z_max_mm")
    low_b, high_b = second.get("z_min_mm"), second.get("z_max_mm")
    if None in (low_a, high_a, low_b, high_b):
        return "unknown", ("one of these colours has no readable height, so "
                           "Studio will not say whether they meet")
    if high_a + margin < low_b:
        return "separate", (f"slot {first['slot']} is painted only up to "
                            f"{high_a:.2f} mm and slot {second['slot']} starts at "
                            f"{low_b:.2f} mm")
    if high_b + margin < low_a:
        return "separate", (f"slot {second['slot']} is painted only up to "
                            f"{high_b:.2f} mm and slot {first['slot']} starts at "
                            f"{low_a:.2f} mm")
    return "overlaps", (f"both are painted between "
                        f"{max(low_a, low_b):.2f} mm and "
                        f"{min(high_a, high_b):.2f} mm")


def _none_found(model_parts: int, marker_seen: bool = False) -> dict:
    reason = ("This project carries no painted colour data."
              if not marker_seen else
              "This project mentions painting but carries no decodable paint.")
    return {
        "schema_version": SCHEMA_VERSION, "available": True, "reason": reason,
        "dialect": None, "attribute": None, "format_version": None,
        "format_version_source": None, "format_version_known": False,
        "objects": [], "slots": [], "slots_referenced": [],
        "painted_triangle_count": 0, "malformed_triangle_count": 0,
        "truncated": False, "default_slot_resolved": True, "paint_marker_undecodable": marker_seen,
        "confidence": CONFIRMED,
        "evidence": f"no paint attribute in {model_parts} mesh part(s)",
        "limits": {},
    }


def _unavailable(reason: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION, "available": False, "reason": reason,
        "dialect": None, "attribute": None, "format_version": None,
        "format_version_source": None, "format_version_known": False,
        "objects": [], "slots": [], "slots_referenced": [],
        "painted_triangle_count": 0, "malformed_triangle_count": 0,
        "truncated": False, "default_slot_resolved": False,
        "confidence": UNKNOWN, "evidence": None, "limits": {},
    }
