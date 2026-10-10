"""One source object with several volumes, carried as several real parts.

PrusaSlicer stores an object's volumes as **triangle ranges inside one mesh**:
`<volume firstid="0" lastid="5">` and `<volume firstid="6" lastid="11">` describe
two parts of a twelve-facet cube, each able to carry its own filament. Studio used
to wrap that geometry verbatim and write one `<part>` record over it, so a source
saying "this half prints in filament 2 and that half in filament 5" arrived as one
undifferentiated object and the audit reported the second filament as not carried.

The target dialect can hold it. Two Snapmaker-Orca-family projects in the test
fixtures prove the shape:

    3D/3dmodel.model
      <object id="R" type="model">
        <components>
          <component p:path="/3D/Objects/object_1.model" objectid="1" transform=.../>
          <component p:path="/3D/Objects/object_1.model" objectid="2" transform=.../>
        </components>
      </object>
      <build><item objectid="R" .../></build>

    3D/Objects/object_1.model
      <object id="1" type="model"><mesh>…</mesh></object>
      <object id="2" type="model"><mesh>…</mesh></object>

    Metadata/model_settings.config
      <object id="R">
        <metadata key="extruder" value="…"/>       ← the object's own assignment
        <part id="1" subtype="normal_part">…<metadata key="extruder" value="2"/>
        <part id="2" subtype="normal_part">…<metadata key="extruder" value="5"/>

`part id` in the metadata, `objectid` on the component and the object id inside
the Objects file are **the same number**. That identity is what makes the metadata
describe the geometry rather than decorate it, and it is the thing this module
exists to get right — a `<part>` record over a single mesh is a claim, not a part.

Nothing here invents geometry. Each part's mesh is the source triangles of that
volume's range, with their vertices carried across unchanged and their attributes —
including the per-facet painting Studio spent two releases learning to read —
copied verbatim.
"""
from __future__ import annotations

import html as _html
import re

from . import overrides as object_overrides
from .orca_nonnullable import NON_NULLABLE_VECTORS

SCHEMA_VERSION = "multipart/1"

#: The namespaces a root model needs to declare components and the production
#: extension. Taken from what the writer already emits for the single-part path.
_MESH_OBJECT = re.compile(r"<object\b[^>]*\bid=\"(\d+)\"[^>]*>(.*?)</object>", re.S)
_VERTEX = re.compile(r"<vertex\b[^>]*/>")
_TRIANGLE = re.compile(r"<triangle\b[^>]*/>")
_V_ATTR = re.compile(r'\b(x|y|z)="([^"]*)"')
_T_ATTR = re.compile(r'\bv([123])="(\d+)"')


class Unsplittable(Exception):
    """The source object cannot be split into parts without inventing something."""


def _vertex_key(tag: str) -> tuple:
    found = dict(_V_ATTR.findall(tag))
    return (found.get("x", ""), found.get("y", ""), found.get("z", ""))


def read_mesh(object_xml: str) -> tuple[list[str], list[str]]:
    """The vertex and triangle tags of one mesh, verbatim and in order."""
    return _VERTEX.findall(object_xml), _TRIANGLE.findall(object_xml)


def _triangle_indices(tag: str) -> tuple[int, int, int]:
    found = {slot: int(value) for slot, value in _T_ATTR.findall(tag)}
    if len(found) != 3:
        raise Unsplittable(f"a triangle does not name three vertices: {tag[:60]}")
    return found["1"], found["2"], found["3"]


def _retarget(tag: str, mapping: dict[int, int]) -> str:
    """Rewrite a triangle's vertex indices, leaving every other attribute alone.

    Painting lives in the attributes this does not touch —
    `slic3rpe:mmu_segmentation` and its Bambu/Orca equivalents — so a facet keeps
    exactly what it was painted with.
    """
    def swap(match: re.Match) -> str:
        return f'v{match.group(1)}="{mapping[int(match.group(2))]}"'

    return _T_ATTR.sub(swap, tag)


def split_triangles(vertices: list[str], triangles: list[str],
                    ranges: list[tuple[int, int]]) -> list[dict]:
    """Cut one mesh into the meshes its volume ranges describe.

    Each part gets only the vertices its own triangles reference, renumbered from
    zero — which is what makes it a standalone mesh rather than a view into a
    shared one. Vertex *tags* are copied unchanged, so coordinates cross exactly as
    written rather than through a float round-trip.
    """
    if not ranges:
        raise Unsplittable("no volume ranges to split on")
    parts: list[dict] = []
    for order, (first, last) in enumerate(ranges):
        if first < 0 or last < first or last >= len(triangles):
            raise Unsplittable(
                f"volume {order + 1} names triangles {first}-{last} and the mesh has "
                f"{len(triangles)}")
        mine = triangles[first:last + 1]
        mapping: dict[int, int] = {}
        kept: list[str] = []
        for tag in mine:
            for index in _triangle_indices(tag):
                if index >= len(vertices):
                    raise Unsplittable(
                        f"a triangle references vertex {index} and the mesh has "
                        f"{len(vertices)}")
                if index not in mapping:
                    mapping[index] = len(kept)
                    kept.append(vertices[index])
        parts.append({
            "index": order,
            "vertices": kept,
            "triangles": [_retarget(tag, mapping) for tag in mine],
            "source_range": (first, last),
        })
    covered = sum(len(part["triangles"]) for part in parts)
    if covered != len(triangles):
        # Every facet belongs to exactly one volume, or the split would silently
        # drop or duplicate geometry. Refusing is the only honest answer.
        raise Unsplittable(
            f"the volume ranges cover {covered} of {len(triangles)} triangles")
    return parts


def geometry_digest(vertices: list[str], triangles: list[str]) -> str:
    """A digest of what a mesh actually is, independent of vertex numbering.

    Triangles are hashed by their vertices' *coordinates* rather than their
    indices, because splitting a mesh renumbers indices by design. Two meshes with
    the same digest describe the same solid in the same winding order, whatever
    order their vertex table happens to be in.
    """
    import hashlib

    keys = [_vertex_key(tag) for tag in vertices]
    lines = []
    for tag in triangles:
        a, b, c = _triangle_indices(tag)
        try:
            lines.append("|".join(",".join(keys[i]) for i in (a, b, c)))
        except IndexError as exc:
            raise Unsplittable("a triangle references a vertex that is not there") from exc
    digest = hashlib.sha256()
    for line in lines:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


# --- emitting the target structure -------------------------------------------

_PROD_NS = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
            'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"')


#: The same painting, written two ways. PrusaSlicer names the attribute
#: `slic3rpe:mmu_segmentation`; the Orca/Bambu family names it `paint_color`. The
#: encoded value is the same string — the OrcaSlicer and PrusaSlicer painted-cube
#: fixtures carry byte-identical values for the same eight facets — so translating
#: is a rename of the attribute and nothing else.
#:
#: Measured against Snapmaker Orca 2.3.5: a copy carrying the PrusaSlicer name
#: opens with no painting at all, and the same copy carrying `paint_color` opens
#: with all eight facets, the same slots and the same areas.
SOURCE_PAINT_ATTRIBUTE = "slic3rpe:mmu_segmentation"
TARGET_PAINT_ATTRIBUTE = "paint_color"

_PAINT_ATTR = re.compile(rf'\b{SOURCE_PAINT_ATTRIBUTE}="')


def to_target_paint(tag: str) -> str:
    """One facet's paint attribute, renamed into the target's vocabulary.

    Only multi-material painting is touched. Support and seam painting use the
    same attribute names on both sides, and a name Studio has not measured is
    left exactly as the source wrote it rather than guessed at.
    """
    return _PAINT_ATTR.sub(f'{TARGET_PAINT_ATTRIBUTE}="', tag)


def objects_model_xml(parts: list[dict], uuids: list[str] | None = None,
                      roles: list | None = None,
                      ids: list[int] | None = None) -> bytes:
    """`3D/Objects/object_1.model` — one mesh object per part, ids from 1.

    The id given here is the number the root's component references and the number
    the metadata calls a part. Keeping the three the same is the whole point.

    A helper volume's mesh is not a model to print, and its own `type` says so.
    """
    uuids = uuids or [""] * len(parts)
    roles = roles or ["part"] * len(parts)
    ids = ids or [part["index"] + 1 for part in parts]
    body = []
    for part, uuid, role, part_id in zip(parts, uuids, roles, ids):
        stamp = f' p:UUID="{uuid}"' if uuid else ""
        body.append(
            f'<object id="{part_id}"{stamp} '
            f'type="{object_type_for(role)}"><mesh>'
            f'<vertices>{"".join(part["vertices"])}</vertices>'
            '<triangles>'
            f'{"".join(to_target_paint(t) for t in part["triangles"])}'
            '</triangles>'
            "</mesh></object>")
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<model unit="millimeter" xml:lang="en-US" {_PROD_NS}>'
            '<metadata name="BambuStudio:3mfVersion">1</metadata>'
            f'<resources>{"".join(body)}</resources></model>').encode("utf-8")


def root_model_xml(part_count: int, transform: str, root_id: int = 2,
                   objects_path: str = "/3D/Objects/object_1.model",
                   uuids: dict | None = None) -> bytes:
    """The root model: one composite object, one component per part, one item."""
    uuids = uuids or {}
    components = "".join(
        f'<component p:path="{objects_path}" objectid="{index + 1}"'
        + (f' p:UUID="{uuids.get(f"comp{index}")}"' if uuids.get(f"comp{index}") else "")
        + ' transform="1 0 0 0 1 0 0 0 1 0 0 0"/>'
        for index in range(part_count))
    meta = "".join(f'<metadata name="{key}"></metadata>' for key in
                   ["Copyright", "CreationDate", "Description", "Designer",
                    "DesignerCover", "DesignerUserId", "License", "ModificationDate",
                    "Origin", "Title"])
    root_uuid = f' p:UUID="{uuids["root"]}"' if uuids.get("root") else ""
    build_uuid = f' p:UUID="{uuids["build"]}"' if uuids.get("build") else ""
    item_uuid = f' p:UUID="{uuids["item"]}"' if uuids.get("item") else ""
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<model unit="millimeter" xml:lang="en-US" {_PROD_NS}>'
            '<metadata name="Application">SnapmakerStudio-u1convert</metadata>'
            '<metadata name="BambuStudio:3mfVersion">1</metadata>' + meta +
            f'<resources><object id="{root_id}"{root_uuid} type="model">'
            f'<components>{components}</components></object></resources>'
            f'<build{build_uuid}><item objectid="{root_id}"{item_uuid} '
            f'transform="{transform}" printable="1"/></build></model>').encode("utf-8")


def root_model_multi_xml(objects: list[dict]) -> bytes:
    """One composite object per logical source object, each placed by its own item.

    This is the shape Snapmaker Orca writes for a project of several objects: its
    own badge fixture holds three, each with its own object file, its own
    components and its own build item, and mesh ids that are unique across the
    whole project rather than restarting per object. Flattening them into one
    composite would put three separate models under a single placement.
    """
    resources = []
    for entry in objects:
        components = "".join(
            f'<component p:path="{entry["path"]}" objectid="{part_id}" '
            'transform="1 0 0 0 1 0 0 0 1 0 0 0"/>'
            for part_id in entry["part_ids"])
        resources.append(f'<object id="{entry["root_id"]}" type="model">'
                         f"<components>{components}</components></object>")
    items = "".join(
        f'<item objectid="{entry["root_id"]}" transform="{entry["transform"]}" '
        'printable="1"/>'
        for entry in objects)
    meta = "".join(f'<metadata name="{key}"></metadata>' for key in
                   ["Copyright", "CreationDate", "Description", "Designer",
                    "DesignerCover", "DesignerUserId", "License", "ModificationDate",
                    "Origin", "Title"])
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<model unit="millimeter" xml:lang="en-US" {_PROD_NS}>'
            '<metadata name="Application">SnapmakerStudio-u1convert</metadata>'
            '<metadata name="BambuStudio:3mfVersion">1</metadata>' + meta +
            f'<resources>{"".join(resources)}</resources>'
            f"<build>{items}</build></model>").encode("utf-8")


def object_rels_multi_xml(paths: list[str]) -> bytes:
    """Every object file declared, because geometry nobody declared is not read."""
    relationships = "".join(
        f'<Relationship Target="{path}" Id="rel-{order + 1}" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        for order, path in enumerate(paths))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{relationships}</Relationships>").encode("utf-8")


def object_rels_xml(objects_path: str = "/3D/Objects/object_1.model") -> bytes:
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Target="{objects_path}" Id="rel-1" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
            '</Relationships>').encode("utf-8")


#: Studio's normalised role, and the word Snapmaker Orca uses for it.
#:
#: Every pairing here was measured against Snapmaker Orca 2.3.5 rather than read
#: off a matching name: a project claiming the role was handed to Orca, Orca saved
#: the project back, and the saved file was read. A made-up role word came back
#: rewritten to `normal_part`, so surviving that round trip means Orca recognises
#: the word rather than that it copies whatever it is given. All four helper roles
#: survived; the nonsense one did not.
TARGET_ROLES = {
    "part": "normal_part",
    "modifier": "modifier_part",
    "negative": "negative_part",
    "support_enforcer": "support_enforcer",
    "support_blocker": "support_blocker",
}

#: The roles that print nothing, which is the claim that actually matters.
#: Measured the same way: two cubes that do not touch, the second one carrying the
#: role under test. As a `normal_part` Snapmaker Orca sliced a plate covering both
#: — 500 mm² — and as any of these four it sliced a plate covering only the first
#: — 400 mm², with byte-identical plate thumbnails. None of them becomes plastic.
HELPER_ROLES = frozenset(TARGET_ROLES) - {"part"}


def object_type_for(role: str) -> str:
    """The `type` on the mesh object a part points at.

    A genuine Orca project writes `type="other"` on the geometry behind a
    `modifier_part` and `type="model"` behind a `normal_part`. Orca normalises the
    attribute to `model` when it saves, so it does not *require* `other` — but
    `other` is the form measured to load correctly, and matching what the target
    writes is the safer of two answers that both work.
    """
    if role not in TARGET_ROLES:
        raise Unsplittable(f"no proven target representation for the role {role!r}")
    return "model" if role == "part" else "other"


def part_records(parts: list[dict], name: str, slots: list,
                 roles: list | None = None, ids: list[int] | None = None) -> str:
    """The `<part>` block for `model_settings.config`, one entry per real part.

    A slot of `None` writes no extruder at all rather than a 1: an object nobody
    assigned is not an object assigned to filament 1, and that distinction is the
    same one the object level already keeps.
    """
    roles = roles or ["part"] * len(parts)
    ids = ids or [part["index"] + 1 for part in parts]
    out = []
    for part, slot, role, part_id in zip(parts, slots, roles, ids):
        if role not in TARGET_ROLES:
            # Never fall back to `normal_part`. That fallback is precisely how a
            # modifier becomes solid plastic, and Snapmaker Orca already does it
            # to a word it does not know — Studio must not hand it one.
            raise Unsplittable(f"no proven target representation for the role {role!r}")
        subtype = TARGET_ROLES[role]
        extruder = (f'      <metadata key="extruder" value="{int(slot)}"/>\n'
                    # A helper volume prints nothing, so a filament on it
                    # would choose a material for something no material is made
                    # from; the target's own projects state none on one. A slot
                    # the source did state is reported by the audit, not dropped.
                    if slot and role == "part" else "")
        out.append(
            f'    <part id="{part_id}" subtype="{subtype}">\n'
            f'      <metadata key="name" value="{name}_{part["index"] + 1}"/>\n'
            '      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
            + extruder +
            '      <mesh_stat edges_fixed="0" degenerate_facets="0" facets_removed="0" '
            'facets_reversed="0" backwards_edges="0"/>\n'
            '    </part>\n')
    return "".join(out)


# --- reading the source's volume graph ---------------------------------------

_PRUSA_OBJECT = re.compile(r"<object(?P<head>[^>]*)>(?P<body>.*?)</object>", re.S)
_PRUSA_VOLUME = re.compile(
    r'<volume[^>]*firstid="(\d+)"[^>]*lastid="(\d+)"[^>]*>(.*?)</volume>', re.S)
_META = re.compile(r'<metadata\s+type="volume"\s+key="([^"]+)"\s+value="([^"]*)"')


def source_volumes(config_xml: str) -> dict[str, list[dict]]:
    """Each Prusa object's volumes: triangle range, filament and role.

    Keyed by the object id the file itself uses, so nothing depends on ordering
    surviving the crossing.
    """
    from .assignments import _int, role_of

    out: dict[str, list[dict]] = {}
    for match in _PRUSA_OBJECT.finditer(config_xml):
        found = re.search(r'id="([^"]+)"', match.group("head"))
        if not found:
            continue
        volumes = []
        for order, (first, last, body) in enumerate(_PRUSA_VOLUME.findall(match.group("body"))):
            meta = dict(_META.findall(body))
            volumes.append({
                "index": order,
                "range": (int(first), int(last)),
                "slot": _int(meta.get("extruder", "")),
                "role": role_of(meta.get("volume_type")),
                "name": meta.get("name"),
            })
        if volumes:
            out[found.group(1)] = volumes
    return out


def worth_splitting(volumes: list[dict]) -> bool:
    """Is there more than one part, and does the split carry a fact?

    A single volume is the existing path and stays on it. Several volumes that all
    say the same thing — or say nothing — carry no information the object level
    cannot hold, and splitting them would churn the geometry for no gain. What
    earns a split is volumes that disagree, or a volume with a role of its own.
    """
    if len(volumes) < 2:
        return False
    slots = {v["slot"] for v in volumes if v["slot"]}
    roles = {v["role"] for v in volumes}
    return len(slots) > 1 or roles != {"part"}

# --- does the archive say the same thing three times? ------------------------

_COMPOSITE = re.compile(r'<object id="(\d+)"[^>]*>\s*<components>(.*?)</components>', re.S)
_SETTINGS_OBJECT = re.compile(r'<object id="(\d+)"[^>]*>(.*?)</object>', re.S)
_PART_HEAD = re.compile(r'<part id="(\d+)"([^>]*)>')


def _composite_objects(root_xml: str) -> dict:
    """Each object built from components, and the mesh ids it references."""
    return {object_id: re.findall(r'objectid="(\d+)"', block)
            for object_id, block in _COMPOSITE.findall(root_xml)}


def _parts_by_object(settings_xml: str) -> dict:
    """Each settings object's part ids and roles, scoped to that object."""
    out: dict[str, list] = {}
    for object_id, body in _SETTINGS_OBJECT.findall(settings_xml):
        entries = []
        for part_id, head in _PART_HEAD.findall(body):
            found = re.search(r'subtype="([^"]*)"', head)
            entries.append((part_id, found.group(1) if found else None))
        out[object_id] = entries
    return out


#: Every option Orca 2.4.0 declares as a non-nullable vector; see that module.
NIL_UNREADABLE = NON_NULLABLE_VECTORS


_OBJECT_TAG = re.compile(r'<object id="(\d+)"')
_TYPE_ATTR = re.compile(r'type="([^"]*)"')


def _object_label(body: str) -> str:
    name = re.search(r'<metadata key="name" value="([^"]*)"', body)
    shown = _html.unescape(name.group(1))[:60].replace('"', "'") if name else ""
    return f' ("{shown}")' if shown else ""


def _settings_objects(settings_xml: str) -> dict:
    """Each settings object's own metadata, above its parts."""
    return {object_id: body.split("<part", 1)[0]
            for object_id, body in _SETTINGS_OBJECT.findall(settings_xml)}


def validate_archive(tm) -> dict:
    """Check that geometry, component graph and metadata all agree.

    A prepared multi-part project makes the same claim in three places: the root
    model's components, the mesh objects they point at, and the `<part>` records
    in `model_settings.config`. If those three drift apart the file is wrong even
    though every one of them is individually well-formed — and Snapmaker Orca
    should not be the first thing to notice.

    Never raises. Returns the findings, so a caller can report them rather than
    lose the file.
    """
    problems: list[str] = []
    mesh_types: dict[str, str] = {}

    def read(name: str) -> str:
        try:
            return tm.read_part(name).decode("utf-8", "ignore") if tm.has_part(name) else ""
        except Exception:
            return ""

    root = read("3D/3dmodel.model")
    settings = read("Metadata/model_settings.config")
    if not root:
        return {"schema_version": SCHEMA_VERSION, "multipart": False,
                "ok": False, "problems": ["no root model in the archive"]}

    components = re.findall(r'<component[^>]*objectid="(\d+)"[^>]*/>', root)
    paths = set(re.findall(r'<component[^>]*p:path="([^"]+)"', root))
    if not components:
        return {"schema_version": SCHEMA_VERSION, "multipart": False,
                "ok": True, "problems": []}

    # every referenced object file exists, and is declared as a relationship
    rels = read("3D/_rels/3dmodel.model.rels")
    mesh_ids: list[str] = []
    for path in sorted(paths):
        name = path.lstrip("/")
        if not tm.has_part(name):
            problems.append(f"a component points at {path}, which is not in the archive")
            continue
        if path not in rels:
            problems.append(f"{path} holds geometry but is not declared in the relationships")
        body = read(name)
        # One linear pass with str.find: regexes over a many-megabyte mesh (a lazy `.*?`, or
        # a search per object from the top of the file) made the Doctor several times slower.
        pos = 0
        while True:
            start = body.find('<object id="', pos)
            if start < 0:
                break
            tag_end = body.find(">", start)
            if tag_end < 0:
                break
            tag = _OBJECT_TAG.match(body, start, tag_end)
            pos = tag_end
            if not tag:
                continue
            object_id = tag.group(1)
            mesh_ids.append(object_id)
            kind = _TYPE_ATTR.search(body, start, tag_end)
            if kind:
                mesh_types[object_id] = kind.group(1)
            end = body.find("</object>", tag_end)
            if end >= 0:
                if body.find("<triangle", tag_end, end) < 0:
                    problems.append(f"object {object_id} in {path} carries no geometry")
                pos = end

    missing = [c for c in components if c not in mesh_ids]
    if missing:
        problems.append(
            f"component(s) {sorted(set(missing))} reference an object that no file defines")

    # build item must place a composite object, not a mesh
    composites = _composite_objects(root)
    items = re.findall(r'<item[^>]*objectid="(\d+)"', root)
    if composites and items and not set(items) & set(composites):
        problems.append(
            f"the build places object(s) {sorted(set(items))} and the composite "
            f"object(s) are {sorted(composites)}")

    # a part's role and the geometry under it must say the same thing
    for object_id, part_ids in sorted(_parts_by_object(settings).items()):
        for part_id, subtype in part_ids:
            if subtype is None:
                continue
            if subtype not in TARGET_ROLES.values():
                problems.append(
                    f"part {part_id} of object {object_id} claims the role "
                    f"{subtype!r}, which is not one Studio has proven the target "
                    "represents")
                continue
            wanted = "model" if subtype == "normal_part" else "other"
            found = mesh_types.get(part_id)
            if found is not None and found != wanted:
                problems.append(
                    f"part {part_id} of object {object_id} is a {subtype} and the "
                    f"geometry under it is typed {found!r}; a {subtype} is described "
                    f"by type {wanted!r}")

    # Every object's parts must match that object's components, one for one. Both
    # numbers belong to their object: two objects may each hold a part 1, and one
    # mesh may be referenced by several objects. Reading the whole file as if it
    # described a single object called a genuine eight-object project broken.
    by_object = _parts_by_object(settings)
    for object_id, own_components in sorted(composites.items()):
        own_parts = [part_id for part_id, _subtype in by_object.get(object_id, [])]
        if object_id not in by_object:
            problems.append(f"object {object_id} has components and no part records")
            continue
        if len(own_parts) != len(own_components):
            problems.append(
                f"object {object_id} lists {len(own_parts)} part(s) and has "
                f"{len(own_components)} component(s)")
        if sorted(own_parts) != sorted(own_components):
            problems.append(
                f"object {object_id}: part ids {sorted(own_parts)} do not match its "
                f"component ids {sorted(own_components)}")
        # A repeated part id or a mesh referenced by two components is legitimate:
        # 3MF Core allows a component to be instanced more than once and Bambu
        # Studio writes exactly that. The count and the multiset above are the
        # whole rule; uniqueness is not.

    # Two objects referencing one mesh is **not** a fault: a genuine Snapmaker Orca
    # project in the fixtures holds eight objects that all build from the same two
    # meshes, which is how it states eight copies of one pair. A check that called
    # that broken was written here and removed again when the file disproved it.

    # Every object the metadata describes must be one the geometry has.
    for object_id in sorted(by_object):
        if object_id not in composites:
            problems.append(
                f"the metadata describes object {object_id}, which the geometry "
                "does not build from components")

    # Every per-object setting the copy states must be one Studio has measured
    # the target to act on, in the form it was measured in. Snapmaker Orca does
    # not ignore a per-object value it cannot read: handed one, it opened the
    # project with an empty plate, and handed a zero layer height it hung on
    # load. A malformed override costs the geometry, so it is caught here rather
    # than by the person opening the file.
    for object_id, body in _settings_objects(settings).items():
        stated = {key: value for key, value in
                  re.findall(r'<metadata key="([^"]+)" value="([^"]*)"\s*/>', body)
                  if key not in ("name", "extruder")}
        label = _object_label(body)
        for fault in object_overrides.validate_emitted(stated):
            problems.append(f"object {object_id}{label}: {fault}")

    # Part-level values Snapmaker Orca 2.4.0 cannot read. Bambu Studio writes `nil`
    # ("not overridden") into per-part speed lists; in Orca 2.4.0 these options are
    # not nullable (PrintConfig.cpp: coFloats / coFloatsOrPercents, added with plain
    # `add`; the only nullable options are the `filament_*` retraction ones), and
    # Config.hpp throws "Deserializing nil into a non-nullable object", so the whole
    # project fails to load. Refused with the part named, never silently edited.
    for object_id, body in _SETTINGS_OBJECT.findall(settings):
        label = _object_label(body)
        for part_id, part_body in re.findall(r'<part id="(\d+)"[^>]*>(.*?)</part>', body, re.S):
            bad = [key for key, value in
                   re.findall(r'<metadata key="([^"]+)" value="([^"]*)"\s*/>', part_body)
                   if key in NIL_UNREADABLE and "nil" in [t.strip() for t in value.split(",")]]
            if bad:
                problems.append(
                    f"part {part_id} of object {object_id}{label}: has values "
                    f"Snapmaker Orca 2.4.0 cannot read (nil in {', '.join(sorted(bad))})")

    for matrix in re.findall(r'key="matrix" value="([^"]*)"', settings):
        values = matrix.split()
        if len(values) not in (12, 16):
            problems.append(f"a part matrix has {len(values)} values")
            continue
        try:
            [float(v) for v in values]
        except ValueError:
            problems.append("a part matrix is not numeric")

    return {"schema_version": SCHEMA_VERSION, "multipart": True,
            "parts": len(components), "ok": not problems, "problems": problems}
