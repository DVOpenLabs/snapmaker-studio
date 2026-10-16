"""Authored 3MF / STL fixtures for the scene/1 tests and benchmark.

Everything here is synthetic. Archives are written with ZIP_STORED and fixed timestamps so the bytes
are deterministic. Nothing here reads a real user file.
"""
from __future__ import annotations

import struct
import zipfile
from pathlib import Path

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
MODEL_REL = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"

CUBE_TRIS = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]


def cube_vertices(size: float = 10.0, origin=(0.0, 0.0, 0.0)):
    ox, oy, oz = origin
    s = size
    return [(ox, oy, oz), (ox + s, oy, oz), (ox + s, oy + s, oz), (ox, oy + s, oz),
            (ox, oy, oz + s), (ox + s, oy, oz + s), (ox + s, oy + s, oz + s), (ox, oy + s, oz + s)]


def mesh_xml(vertices, triangles) -> str:
    v = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in vertices)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in triangles)
    return f"<mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh>"


def cube_object(oid, size=10.0, origin=(0.0, 0.0, 0.0)) -> str:
    return f'<object id="{oid}" type="model">{mesh_xml(cube_vertices(size, origin), CUBE_TRIS)}</object>'


def composite_object(oid, comps) -> str:
    """comps: [(objectid, path|None, transform|None)]"""
    inner = ""
    for cid, path, tf in comps:
        attrs = f'objectid="{cid}"'
        if path is not None:
            attrs += f' p:path="{path}"'
        if tf:
            attrs += f' transform="{tf}"'
        inner += f"<component {attrs}/>"
    return f'<object id="{oid}" type="model"><components>{inner}</components></object>'


def model_xml(objects, items, unit="millimeter", prolog='<?xml version="1.0" encoding="UTF-8"?>') -> str:
    build = ""
    for item in items:           # (objectid, transform) or (objectid, transform, p:path)
        oid, tf = item[0], item[1]
        path = item[2] if len(item) > 2 else None
        build += (f'<item objectid="{oid}"' + (f' p:path="{path}"' if path is not None else "")
                  + (f' transform="{tf}"' if tf else "") + "/>")
    return (f'{prolog}<model unit="{unit}" xmlns="{CORE}" xmlns:p="{PROD}">'
            f"<resources>{''.join(objects)}</resources><build>{build}</build></model>")


def sub_model_xml(objects, unit="millimeter") -> str:
    return (f'<?xml version="1.0" encoding="UTF-8"?><model unit="{unit}" xmlns="{CORE}" xmlns:p="{PROD}">'
            f"<resources>{''.join(objects)}</resources><build/></model>")


def rels_xml(target="/3D/3dmodel.model", extra="") -> str:
    return (f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{REL_NS}">'
            f'<Relationship Id="rel0" Type="{MODEL_REL}" Target="{target}"/>{extra}</Relationships>')


def write_zip(path, entries: dict, order=None) -> Path:
    path = Path(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        for name in (order or list(entries)):
            data = entries[name]
            if isinstance(data, str):
                data = data.encode("utf-8")
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            z.writestr(info, data)
    return path


def three_mf(path, root_model: str, extra: dict | None = None, rels: str | None = None) -> Path:
    entries = {"_rels/.rels": rels or rels_xml(), "3D/3dmodel.model": root_model}
    entries.update(extra or {})
    return write_zip(path, entries)


IDENT = "1 0 0 0 1 0 0 0 1"


def tf(tx=0.0, ty=0.0, tz=0.0, lin=IDENT) -> str:
    return f"{lin} {tx} {ty} {tz}"


def plain_cube_3mf(path, size=10.0, unit="millimeter", at=(50.0, 60.0, 0.0)) -> Path:
    return three_mf(path, model_xml([cube_object("1", size)], [("1", tf(*at))], unit=unit))


# --- Bambu/Orca style ------------------------------------------------------------------------

def model_settings_xml(objects: dict, plates: list) -> str:
    """objects: {oid: [(part_id, subtype)]}; plates: [(plater_id, [(oid, instance_id|None)])]"""
    out = ['<?xml version="1.0" encoding="UTF-8"?><config>']
    for oid, parts in objects.items():
        out.append(f'<object id="{oid}"><metadata key="name" value="o{oid}"/>')
        for pid, sub in parts:
            attr = f' subtype="{sub}"' if sub is not None else ""
            out.append(f'<part id="{pid}"{attr}><metadata key="name" value="p{pid}"/></part>')
        out.append("</object>")
    for plater, members in plates:
        out.append(f'<plate><metadata key="plater_id" value="{plater}"/><metadata key="plater_name" value=""/>')
        for oid, inst in members:
            inst_xml = f'<metadata key="instance_id" value="{inst}"/>' if inst is not None else ""
            out.append(f'<model_instance><metadata key="object_id" value="{oid}"/>{inst_xml}</model_instance>')
        out.append("</plate>")
    out.append("<assemble></assemble></config>")
    return "".join(out)


def bambu_project(path, *, parts, items, plates, roles=None, unit="millimeter", sizes=None, origins=None,
                  omit_parts=()) -> Path:
    """One composite root object `100` made of meshes 1..n in 3D/Objects/object_1.model.

    parts: number of mesh parts; roles: [subtype per part]; items: [(objectid, transform)].
    """
    roles = roles or ["normal_part"] * parts
    sizes = sizes or [10.0] * parts
    origins = origins or [(i * 20.0, 0.0, 0.0) for i in range(parts)]
    sub = sub_model_xml([cube_object(str(i + 1), sizes[i], origins[i]) for i in range(parts)], unit=unit)
    root = model_xml(
        [composite_object("100", [(str(i + 1), "/3D/Objects/object_1.model", None) for i in range(parts)])],
        items, unit=unit)
    settings = model_settings_xml({"100": [(str(i + 1), roles[i]) for i in range(parts) if (i + 1) not in omit_parts]},
                                  plates)
    rels3d = (f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{REL_NS}">'
              f'<Relationship Id="r1" Type="{MODEL_REL}" Target="/3D/Objects/object_1.model"/></Relationships>')
    return three_mf(path, root, {"3D/Objects/object_1.model": sub, "3D/_rels/3dmodel.model.rels": rels3d,
                                 "Metadata/model_settings.config": settings})


# --- Prusa style -----------------------------------------------------------------------------

def prusa_project(path, *, volumes, items=None, unit="millimeter", last_first=False) -> Path:
    """One object `1` with 12 triangles per cube volume; volumes: [(first, last, volume_type)]."""
    n = max(last for _first, last, _ in volumes) // 12 + 1 if volumes else 1
    verts, tris = [], []
    for k in range(n):
        base = len(verts)
        verts += cube_vertices(10.0, (k * 20.0, 0.0, 0.0))
        tris += [(a + base, b + base, c + base) for a, b, c in CUBE_TRIS]
    obj = f'<object id="1" type="model">{mesh_xml(verts, tris)}</object>'
    root = model_xml([obj], items or [("1", tf(100, 100, 0))], unit=unit)
    attrs = (lambda a, b: f'lastid="{b}" firstid="{a}"') if last_first else (lambda a, b: f'firstid="{a}" lastid="{b}"')
    vol = "".join(
        f'<volume {attrs(a, b)}><metadata type="volume" key="volume_type" value="{vt}"/></volume>'
        for a, b, vt in volumes)
    cfg = f'<?xml version="1.0" encoding="UTF-8"?><config><object id="1" instances_count="1">{vol}</object></config>'
    return three_mf(path, root, {"Metadata/Slic3r_PE_model.config": cfg})


# --- STL -------------------------------------------------------------------------------------

def binary_stl(path, size=10.0) -> Path:
    verts = cube_vertices(size)
    body = b"\x00" * 80 + struct.pack("<I", len(CUBE_TRIS))
    for a, b, c in CUBE_TRIS:
        body += struct.pack("<12fH", 0, 0, 0, *verts[a], *verts[b], *verts[c], 0)
    Path(path).write_bytes(body)
    return Path(path)


def big_grid_3mf(path, triangles_target: int, *, at=(50.0, 60.0, 0.0)) -> Path:
    """A single mesh of about `triangles_target` triangles (a flat triangulated grid with shared vertices)."""
    side = max(2, int((triangles_target / 2) ** 0.5))
    verts = [(x * 0.1, y * 0.1, 0.0) for y in range(side + 1) for x in range(side + 1)]
    tris = []
    w = side + 1
    for y in range(side):
        for x in range(side):
            a = y * w + x
            tris.append((a, a + 1, a + w))
            tris.append((a + 1, a + w + 1, a + w))
    return three_mf(path, model_xml([f'<object id="1" type="model">{mesh_xml(verts, tris)}</object>'],
                                    [("1", tf(*at))]))
