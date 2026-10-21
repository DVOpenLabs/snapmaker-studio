"""A Bambu Studio composite object may instance one mesh more than once.

Real shape (a downloaded Bambu Studio 02.02 project, not committed): one composite
object whose components are meshes 1, 2 and 2 again, each with its own transform,
and three part records with ids 1, 2 and 2. 3MF Core allows a component to be
instanced repeatedly, Bambu Studio and Snapmaker Orca write it, and the count and
the multiset of ids match. Studio used to refuse such a file as "uses a part id
twice"; the fixture here is built at test time from the committed Bambu-authored
base so no third-party model is committed.
"""
from __future__ import annotations

import os
import re
import zipfile

import pytest

from snapstudio_core import convert as conv
from snapstudio_core import multipart as MP
from snapstudio_core.container import ThreeMF
from snapstudio_core.fidelity import audit

BASE = os.path.join(os.path.dirname(__file__), "fixtures", "painted",
                    "bambustudio-2.08.02.61-authored.3mf")
ROOT, MESH, SETTINGS = "3D/3dmodel.model", "3D/Objects/object_1.model", "Metadata/model_settings.config"

CUBE = """  <object id="2" p:UUID="00010001-81cb-4c03-9d28-80fed5dfa1dc" type="model">
   <mesh>
    <vertices>
     <vertex x="0" y="0" z="0"/>
     <vertex x="10" y="0" z="0"/>
     <vertex x="10" y="10" z="0"/>
     <vertex x="0" y="10" z="0"/>
     <vertex x="0" y="0" z="10"/>
     <vertex x="10" y="0" z="10"/>
     <vertex x="10" y="10" z="10"/>
     <vertex x="0" y="10" z="10"/>
    </vertices>
    <triangles>
     <triangle v1="0" v2="2" v3="1"/>
     <triangle v1="0" v2="3" v3="2"/>
     <triangle v1="4" v2="5" v3="6"/>
     <triangle v1="4" v2="6" v3="7"/>
     <triangle v1="0" v2="1" v3="5"/>
     <triangle v1="0" v2="5" v3="4"/>
     <triangle v1="1" v2="2" v3="6"/>
     <triangle v1="1" v2="6" v3="5"/>
     <triangle v1="2" v2="3" v3="7"/>
     <triangle v1="2" v2="7" v3="6"/>
     <triangle v1="3" v2="0" v3="4"/>
     <triangle v1="3" v2="4" v3="7"/>
    </triangles>
   </mesh>
  </object>
"""


def _part(pid: int, name: str, dx: int) -> str:
    return f"""    <part id="{pid}" subtype="normal_part">
      <metadata key="name" value="{name}"/>
      <metadata key="matrix" value="1 0 0 {dx} 0 1 0 0 0 0 1 0 0 0 0 1"/>
      <metadata key="source_file" value="fixture.stl"/>
      <metadata key="source_object_id" value="0"/>
      <metadata key="source_volume_id" value="{pid}"/>
      <metadata key="extruder" value="1"/>
      <mesh_stat face_count="12" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>
    </part>
"""


def _repeated(tmp_path, parts=((1, "slab", 0), (2, "cube", 5), (2, "cube", 40)),
              name="repeated.3mf") -> str:
    """Composite object 2: components 1, 2, 2; part records from `parts`."""
    out = tmp_path / name
    with zipfile.ZipFile(BASE) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == MESH:
                text = data.decode("utf-8")
                text = text.replace(" </resources>", CUBE + " </resources>")
                data = text.encode("utf-8")
            elif item.filename == ROOT:
                text = data.decode("utf-8")
                comp = ('    <component p:path="/3D/Objects/object_1.model" objectid="{oid}" '
                        'p:UUID="0001000{n}-b206-40ff-9872-83e8017abed1" transform="{tf}"/>\n')
                block = (comp.format(oid=1, n=0, tf="1 0 0 0 1 0 0 0 1 0 0 0")
                         + comp.format(oid=2, n=1, tf="1 0 0 0 1 0 0 0 1 -60 0 4")
                         + comp.format(oid=2, n=2, tf="1 0 0 0 1 0 0 0 1 60 0 4"))
                text, n = re.subn(r"    <component [^\n]*/>\n", lambda m: block, text, count=1)
                assert n
                data = text.encode("utf-8")
            elif item.filename == SETTINGS:
                text = data.decode("utf-8")
                records = "".join(_part(p, n, dx) for p, n, dx in parts)
                text, n = re.subn(r"    <part id=\"1\".*?</part>\n", lambda m: records, text,
                                  count=1, flags=re.S)
                assert n
                data = text.encode("utf-8")
            dst.writestr(item, data)
    return str(out)


def _problems(path):
    return MP.validate_archive(ThreeMF.open(path))["problems"]


def test_a_repeated_component_and_part_id_is_a_valid_structure(tmp_path):
    src = _repeated(tmp_path)
    assert _problems(src) == []
    assert conv.structure_problems(ThreeMF.open(src)) == []


def test_a_duplicated_part_record_without_a_component_still_fails(tmp_path):
    # ids {1,2,2,2} against components {1,2,2}: a genuine duplicate record
    src = _repeated(tmp_path, parts=((1, "slab", 0), (2, "cube", 5), (2, "cube", 40),
                                     (2, "cube", 80)))
    assert any("lists 4 part(s) and has 3 component(s)" in p for p in _problems(src))


def test_a_swapped_part_id_with_matching_count_still_fails(tmp_path):
    # count equal (3 and 3) but ids {1,1,2} are not the multiset {1,2,2}
    src = _repeated(tmp_path, parts=((1, "slab", 0), (1, "slab", 5), (2, "cube", 40)))
    assert any("do not match its component ids" in p for p in _problems(src))


def test_convert_and_audit_keep_both_instances(tmp_path):
    src = _repeated(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = conv.convert_to_u1(src, str(out_dir))
    assert result.validated_ok, result.errors
    out = result.output_path
    with zipfile.ZipFile(out) as z:
        root = z.read(ROOT).decode()
        settings = z.read(SETTINGS).decode()
    assert len(re.findall(r"<component ", root)) == 3
    assert len(re.findall(r'<component [^>]*objectid="2"', root)) == 2
    assert re.findall(r'<part id="(\d+)"', settings) == ["1", "2", "2"]
    # the two instances keep their own placement: nothing collapsed or dropped
    assert len(set(re.findall(r'<component [^>]*transform="([^"]*)"', root))) == 3
    assert len(set(re.findall(r'key="matrix" value="([^"]*)"', settings))) == 3
    report = audit(src, out)
    bad = [r for r in report["rows"] if r["status"] in ("unverified", "unsupported")]
    assert not bad, bad
