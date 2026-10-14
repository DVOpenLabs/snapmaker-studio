"""Multi-plate Bambu/Orca projects built at test time from the committed Orca-authored base.

The base is ``fixtures/painted/orcaslicer-2.4.2-painted-cube.3mf``: one 20 mm painted cube (centred on its own
origin) on a single U1 plate. Everything else (more plates, a larger source bed, tower positions, support
intent) is written into a copy of it, so no third-party model is in the repository.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from snapstudio_core import regrid

BASE = Path(__file__).parent / "fixtures" / "painted" / "orcaslicer-2.4.2-painted-cube.3mf"
ROOT = "3D/3dmodel.model"
SETTINGS = "Metadata/project_settings.config"
MODEL_SETTINGS = "Metadata/model_settings.config"
OBJECT_PART = "3D/Objects/sample_cube_1.model"

IDENT = "1 0 0 0 1 0 0 0 1"


def bed_polygon(width: float, depth: float, min_x: float = 0.0, min_y: float = 0.0) -> list[str]:
    return [f"{min_x:g}x{min_y:g}", f"{min_x + width:g}x{min_y:g}",
            f"{min_x + width:g}x{min_y + depth:g}", f"{min_x:g}x{min_y + depth:g}"]


def source_origin(index: int, plates: int, bed: tuple[float, float]) -> tuple[float, float]:
    """Where plate ``index`` starts on the SOURCE grid, by Orca's rule (the fixture's own copy of it)."""
    stride = (int(bed[0]) * 1.2, int(bed[1]) * 1.2)
    cols = regrid.column_count(plates)
    return (index % cols) * stride[0], -(index // cols) * stride[1]


def read(path) -> dict:
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def write(path, entries: dict) -> str:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return str(path)


def items_of(path) -> list[dict]:
    """(transform text, other attributes) of every build item of a project, in order."""
    root = read(path)[ROOT].decode("utf-8")
    return [{"transform": (re.search(r'transform="([^"]*)"', t) or [None, None])[1], "tag": t}
            for t in re.findall(r"<item\b[^>]*/>", root)]


def settings_of(path) -> dict:
    return json.loads(read(path)[SETTINGS])


def project(tmp_path, name="multi.3mf", *, plates=2, bed=(330.0, 320.0), local=(165.0, 160.0),
            transforms=None, cfg=None, supports=None, instances=None):
    """A ``plates``-plate project on a source bed of ``bed`` mm.

    ``local`` is each item's position in its plate's own frame (so it lands in the cell the formula predicts);
    ``transforms`` overrides the full 12-token transform of item ``i``; ``cfg`` updates project settings;
    ``supports`` is a token or a set of them ("paint" = enforcer paint, "paint_blocker", "enforcer" and
    "blocker" volumes, "object" = enable_support 1 on the object, "object_off" = 0) written into the copy.
    """
    entries = read(BASE)
    root = entries[ROOT].decode("utf-8")
    items = []
    for i in range(plates):
        ox, oy = source_origin(i, plates, bed)
        text = (transforms or {}).get(i) or f"{IDENT} {ox + local[0]:g} {oy + local[1]:g} 10"
        items.append(f'  <item objectid="2" p:UUID="00000002-b1ec-4553-aec9-835e5b7240{i:02d}" '
                     f'transform="{text}" printable="1" auto_drop="1"/>')
    root = re.sub(r"<build\b([^>]*)>.*?</build>",
                  lambda m: f"<build{m.group(1)}>\n" + "\n".join(items) + "\n </build>", root, flags=re.S)
    entries[ROOT] = root.encode("utf-8")

    ms = entries[MODEL_SETTINGS].decode("utf-8")
    blocks = []
    for i in range(plates):
        blocks.append(f"""  <plate>
    <metadata key="plater_id" value="{i + 1}"/>
    <metadata key="plater_name" value=""/>
    <metadata key="locked" value="false"/>
    <metadata key="filament_map_mode" value="Auto For Flush"/>
    <metadata key="filament_maps" value="1"/>
    <metadata key="gcode_file" value=""/>
    <model_instance>
      <metadata key="object_id" value="2"/>
      <metadata key="instance_id" value="{i}"/>
      <metadata key="identify_id" value="{8 + i}"/>
    </model_instance>
  </plate>
""")
    ms = re.sub(r"  <plate>.*</plate>\n", "".join(blocks), ms, flags=re.S)
    wanted = set([supports] if isinstance(supports, str) else (supports or ()))
    helper_volumes = [t for t in ("enforcer", "blocker") if t in wanted]
    for n, kind in enumerate(helper_volumes):
        # a small extra mesh in the object file, referenced by the root object as component 3 / 4
        number = 3 + n
        part = entries[OBJECT_PART].decode("utf-8")
        block = re.search(r'<object id="1".*?</object>', part, re.S).group(0)
        clean = re.sub(r' paint_[a-z]+="[^"]*"', "", block).replace('id="1"', f'id="{number}"', 1)
        clean = re.sub(r'p:UUID="[^"]*"', f'p:UUID="0003000{number}-81cb-4c03-9d28-80fed5dfa1dc"', clean, count=1)
        clean = clean.replace('type="model"', 'type="other"', 1)          # a helper volume is typed "other"
        entries[OBJECT_PART] = part.replace("</resources>", clean + "\n </resources>", 1).encode("utf-8")
        root = entries[ROOT].decode("utf-8")
        root = root.replace("</components>", f'<component p:path="/3D/Objects/sample_cube_1.model" '
                            f'objectid="{number}" p:UUID="0003000{number}-b206-40ff-9872-83e8017abed1" '
                            'transform="1 0 0 0 1 0 0 0 1 0 0 0"/></components>', 1)
        entries[ROOT] = root.encode("utf-8")
        ms = ms.replace("  </object>", f'    <part id="{number}" subtype="support_{kind}">\n'
                        f'      <metadata key="name" value="{kind}"/>\n    </part>\n  </object>', 1)
    for flag, value in (("object", "1"), ("object_off", "0")):
        if flag in wanted:
            ms = ms.replace('<metadata key="extruder" value="1"/>',
                            f'<metadata key="extruder" value="1"/>\n    <metadata key="enable_support" value="{value}"/>', 1)
    entries[MODEL_SETTINGS] = ms.encode("utf-8")

    for flag, state in (("paint", "4"), ("paint_blocker", "8")):
        if flag in wanted:
            part = entries[OBJECT_PART].decode("utf-8")
            part = re.sub(r'(<triangle [^>]*?)(/>)', rf' paint_supports="{state}"', part, count=1)
            assert "paint_supports" in part
            entries[OBJECT_PART] = part.encode("utf-8")

    settings = json.loads(entries[SETTINGS])
    settings["printable_area"] = bed_polygon(*bed)
    settings.update({"enable_support": "1", "support_type": "tree(manual)", "support_filament": "2",
                     "support_interface_filament": "2"})
    settings["different_settings_to_system"] = [
        "enable_support;support_filament;support_interface_filament;support_type", "", "", "", "", ""]
    settings.update(cfg or {})
    entries[SETTINGS] = json.dumps(settings, indent=4).encode("utf-8")
    return write(Path(tmp_path) / name, entries)
