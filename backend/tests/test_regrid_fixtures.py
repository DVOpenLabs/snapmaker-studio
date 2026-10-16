"""The test helper that writes support paint into a project must leave the mesh well-formed.

The helper once replaced the whole ``<triangle .../>`` tag with a bare attribute, so a project built with
``supports="paint"`` carried malformed XML; Snapmaker Orca refused it ("Loading of model file failed") while the
engine, which never parses the mesh for this, still reported it valid. This is a test-fixture defect, not an engine one.
"""
from __future__ import annotations

import pytest
from lxml import etree

from tests import regrid_fixtures as rf


def _triangles(path):
    part = rf.read(path)[rf.OBJECT_PART]
    root = etree.fromstring(part)                         # raises on malformed XML
    return [el for el in root.iter() if etree.QName(el).localname == "triangle"]


@pytest.mark.parametrize("flag,state", [("paint", "4"), ("paint_blocker", "8")])
def test_support_paint_injection_keeps_the_mesh_well_formed(tmp_path, flag, state):
    plain = _triangles(rf.project(tmp_path, name="plain.3mf", plates=1))
    painted = _triangles(rf.project(tmp_path, name="painted.3mf", plates=1, supports=flag))
    assert len(painted) == len(plain)                      # no triangle was lost
    marked = [t for t in painted if t.get("paint_supports") is not None]
    assert len(marked) == 1 and marked[0].get("paint_supports") == state
    assert all(marked[0].get(v) is not None for v in ("v1", "v2", "v3"))   # its vertices survived
