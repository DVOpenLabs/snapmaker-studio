"""Small synthetic 3MF ZIP builder used by creative reader contract tests."""
from __future__ import annotations

import io
import json
import zipfile

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"


def model_xml(*, namespace: str = CORE) -> bytes:
    return f'<model xmlns="{namespace}" unit="millimeter"><resources/><build/></model>'.encode()


PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
MAT = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
_CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
                  'package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.'
                  'openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="'
                  'application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/'
         'package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://'
         'schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
# A tetrahedron: the smallest closed mesh. Offset moves it so several bodies do not overlap.
_VERTS = ((0, 0, 0), (10, 0, 0), (0, 10, 0), (0, 0, 10))
_TRIS = ((0, 2, 1), (0, 1, 3), (1, 2, 3), (0, 3, 2))


def mesh_xml(paint: tuple[str, ...] | None = None, offset: float = 0.0) -> str:
    """<mesh> of one tetrahedron; `paint` is one paint_color per triangle ('' = unpainted)."""
    verts = "".join(f'<vertex x="{x + offset}" y="{y}" z="{z}"/>' for x, y, z in _VERTS)
    tris = ""
    for i, (a, b, c) in enumerate(_TRIS):
        p = paint[i] if paint and paint[i] else ""
        tris += f'<triangle v1="{a}" v2="{b}" v3="{c}"' + (f' paint_color="{p}"' if p else "") + "/>"
    return f"<mesh><vertices>{verts}</vertices><triangles>{tris}</triangles></mesh>"


def _zip(members: dict[str, bytes | str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, value)
    return output.getvalue()


def make_ditherforge(*, application: str = "ditherforge-0.6.3", parts: int = 2,
                     paint: tuple[str, ...] = ("4", "8", "0C", ""), settings: dict | None = None,
                     extra: dict[str, bytes] | None = None, with_settings: bool = True) -> bytes:
    """SYNTHETIC DitherForge-shaped 3MF (generic path): production-extension components pointing at
    3D/Objects/object_N.model, per-triangle paint_color, model_settings object names, filament_colour."""
    objs, items, rels, members = "", "", "", {}
    cfg = ""
    for i in range(parts):
        oid = 2 + i
        inner = f"3D/Objects/object_{i + 1}.model"
        objs += (f'<object id="{oid}" p:UUID="00000000-0000-4000-8000-00000000000{i}" type="model"><components>'
                 f'<component p:path="/{inner}" objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></components></object>')
        items += f'<item objectid="{oid}" printable="1"/>'
        rels += f'<Relationship Target="/{inner}" Id="rel-{i + 1}" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        members[inner] = (f'<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" xmlns="{CORE}" '
                          f'xmlns:p="{PROD}" requiredextensions="p"><resources><object id="{oid}" type="model">'
                          f'{mesh_xml(paint, i * 20)}</object></resources><build/></model>')
        name = "ditherforge_output" if parts == 1 else f"ditherforge_output_part{i + 1}"
        cfg += (f'<object id="{oid}"><metadata key="name" value="{name}"/><metadata key="extruder" value="1"/>'
                f'<metadata face_count="4"/><part id="1" subtype="normal_part"><metadata key="name" value="shell"/>'
                f'<metadata key="extruder" value="1"/></part></object>')
    main = (f'<?xml version="1.0" encoding="UTF-8"?><model xmlns="{CORE}" xmlns:p="{PROD}" unit="millimeter" '
            f'requiredextensions="p"><metadata name="Application">{application}</metadata>'
            f'<metadata name="Designer">ditherforge</metadata><metadata name="Title">ditherforge output</metadata>'
            f'<resources>{objs}</resources><build>{items}</build></model>')
    out: dict[str, bytes | str] = {"[Content_Types].xml": _CONTENT_TYPES, "_rels/.rels": _RELS,
                                   "3D/3dmodel.model": main,
                                   "3D/_rels/3dmodel.model.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + rels + "</Relationships>"}
    out.update(members)
    out["Metadata/model_settings.config"] = f'<?xml version="1.0" encoding="UTF-8"?><config>{cfg}</config>'
    if with_settings:
        proj = {"filament_colour": ["#FF0000", "#00FF00", "#0000FF"], "filament_type": ["Generic PLA"] * 3,
                "printer_settings_id": "Synthetic U1 0.4 nozzle", "layer_height": "0.2",
                "mmu_segmented_region_max_width": "1.5"}
        proj.update(settings or {})
        out["Metadata/project_settings.config"] = json.dumps(proj)
    out.update(extra or {})
    return _zip(out)


def make_kromacut(*, layers: int = 3, with_config: bool = True, application: str = "Kromacut_Print",
                  extra: dict[str, bytes] | None = None, model_settings_extra: str = "") -> bytes:
    """SYNTHETIC Kromacut-shaped 3MF: one object per colour layer (pid/pindex into basematerials),
    an assembly object of components, model_settings parts with extruder, kromacut.config."""
    colours = ["FF0000", "00FF00", "0000FF", "FFFF00"][:max(layers, 1)]
    base = "".join(f'<base name="{c}" displaycolor="#{c}FF"/>' for c in colours)
    objs, comps, parts = "", "", ""
    for i in range(layers):
        oid = 2 + i
        objs += (f'<object id="{oid}" p:UUID="00000000-0000-4000-8000-00000000010{i}" pid="1" pindex="{i}" '
                 f'type="model" name="Layer {i + 1} (#{colours[i]})">{mesh_xml(None, i * 20)}</object>')
        comps += f'<component objectid="{oid}" p:UUID="00000000-0000-4000-8000-00000000020{i}"/>'
        parts += (f'<part id="{oid}" subtype="normal_part"><metadata key="name" value="Layer {i + 1} (#{colours[i]})"/>'
                  f'<metadata key="extruder" value="{i + 1}"/></part>')
    asm = 2 + layers
    model = (f'<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" xml:lang="en-US" xmlns="{CORE}" '
             f'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
             f'xmlns:p="{PROD}" xmlns:Kromacut="https://github.com/vycdev/Kromacut" requiredextensions="p">'
             f'<metadata name="BambuStudio:3mfVersion">1</metadata><metadata name="Application">{application}</metadata>'
             f'<metadata name="slic3rpe:layer_height">0.08</metadata><metadata name="slic3rpe:first_layer_height">0.2</metadata>'
             f'<resources><basematerials id="1">{base}</basematerials>{objs}'
             f'<object id="{asm}" p:UUID="00000000-0000-4000-8000-000000000300" type="model" name="Kromacut Model">'
             f'<components>{comps}</components></object></resources>'
             f'<build p:UUID="00000000-0000-4000-8000-000000000400"><item objectid="{asm}"/></build></model>')
    cfg = (f'<?xml version="1.0" encoding="UTF-8"?><config><object id="{asm}"><metadata key="name" value="Kromacut Model"/>'
           f'<metadata key="extruder" value="1"/>{parts}</object><plate><metadata key="plater_id" value="1"/>'
           f'<metadata key="locked" value="false"/><model_instance><metadata key="object_id" value="{asm}"/>'
           f'<metadata key="instance_id" value="0"/></model_instance></plate>{model_settings_extra}</config>')
    out: dict[str, bytes | str] = {"[Content_Types].xml": _CONTENT_TYPES, "_rels/.rels": _RELS,
                                   "3D/3dmodel.model": model, "Metadata/model_settings.config": cfg}
    if with_config:
        out["Metadata/kromacut.config"] = "synthetic opaque kromacut config payload"
    out["Metadata/project_settings.config"] = json.dumps({
        "layer_height": "0.08", "initial_layer_print_height": "0.2",
        "filament_colour": ["#" + c for c in colours], "filament_type": ["PLA"] * len(colours)})
    out.update(extra or {})
    return _zip(out)


def make_sindricad(*, bodies: int = 2, extruders: tuple[int, ...] | None = None,
                   paint: tuple[str, ...] | None = ("8", "", "", "8"), extra: dict[str, bytes] | None = None,
                   application: str = "SindriCAD") -> bytes:
    """SYNTHETIC SindriCAD-shaped 3MF: one object per body (pid/pindex), meshes inline, 1-based
    model_settings extruder, 0-based palette slot, per-triangle paint_color."""
    names = ["Plate", "Lid", "Hinge", "Peg"][:bodies]
    palette = [("Red", "#FF0000"), ("Blue", "#0000FF")]
    mats = "".join(f'<m:base name="{n}" displaycolor="{c}FF"/>' for n, c in palette)
    objs, cfg = "", ""
    for i, name in enumerate(names):
        oid = 2 + i
        slot = i % len(palette)
        ext = extruders[i] if extruders else slot + 1
        objs += (f'<object id="{oid}" type="model" name="{name}" pid="1" pindex="{slot}">'
                 f'{mesh_xml(paint if i == 0 else None, i * 20)}</object>')
        cfg += (f'<object id="{oid}"><metadata key="name" value="{name}"/><metadata key="extruder" value="{ext}"/>'
                f'<part id="1" subtype="normal_part"><metadata key="name" value="{name}"/></part></object>')
    items = "".join(f'<item objectid="{2 + i}" transform="1 0 0 0 1 0 0 0 1 0 0 0" printable="1"/>' for i in range(bodies))
    model = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" xmlns="{CORE}" '
             f'xmlns:m="{MAT}" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021">'
             f'<metadata name="Application">{application}</metadata><metadata name="BambuStudio:3mfVersion">1</metadata>'
             f'<resources><m:basematerials id="1">{mats}</m:basematerials>{objs}</resources><build>{items}</build></model>')
    out: dict[str, bytes | str] = {
        "[Content_Types].xml": _CONTENT_TYPES, "_rels/.rels": _RELS, "3D/3dmodel.model": model,
        "Metadata/model_settings.config": f'<?xml version="1.0" encoding="UTF-8"?>\n<config>\n{cfg}\n</config>',
        "Metadata/project_settings.config": json.dumps({"filament_colour": [c for _, c in palette],
                                                         "filament_type": ["PLA", "PETG"]}, indent=1)}
    out.update(extra or {})
    return _zip(out)


def make_3mf(*, settings: dict | None = None, members: dict[str, bytes] | None = None,
             model: bytes | None = None, duplicate: tuple[str, bytes, bytes] | None = None,
             compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        archive.writestr("3D/3dmodel.model", model if model is not None else model_xml())
        if settings is not None:
            archive.writestr("Metadata/project_settings.config", json.dumps(settings).encode())
        for name, value in (members or {}).items():
            archive.writestr(name, value)
        if duplicate is not None:
            name, first, second = duplicate
            archive.writestr(name, first)
            archive.writestr(name, second)
    return output.getvalue()
