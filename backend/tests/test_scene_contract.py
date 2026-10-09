"""scene/1 contract: the committed JSON Schema, the golden scene, and the fixture matrix.

The schema is validated with the real `jsonschema` validator (a test-only extra); only the
invariants JSON Schema cannot express (volumes partition all triangles, index ranges, matrix
finiteness, base64 byte lengths) are checked by the small helper below.
"""
import base64
import json
import math
import struct
from pathlib import Path

import jsonschema
import pytest

from snapstudio_core import scene, scene_limits as L
from tests import scene_fixtures as fx

FIX = Path(__file__).parent / "fixtures" / "scene"
GOLDEN_REV = "0123456789abcdef" * 4


def validator():
    s = scene.load_schema()
    jsonschema.Draft202012Validator.check_schema(s)
    return jsonschema.Draft202012Validator(s)


def sub_validator(name):
    s = scene.load_schema()
    return jsonschema.Draft202012Validator({"$schema": s["$schema"], "$defs": s["$defs"], "$ref": f"#/$defs/{name}"})


def check_invariants(sc: dict) -> None:
    """What JSON Schema cannot say."""
    keys = set()
    for mesh in sc["meshes"]:
        key = (mesh["key"]["part"], mesh["key"]["object_id"])
        assert key not in keys
        keys.add(key)
        pos = base64.b64decode(mesh["positions_f32le_base64"], validate=True)
        idx = base64.b64decode(mesh["indices_u32le_base64"], validate=True)
        assert len(pos) == mesh["vertex_count"] * 12
        assert len(idx) == mesh["triangle_count"] * 12
        floats = struct.unpack(f"<{mesh['vertex_count'] * 3}f", pos)
        assert all(math.isfinite(f) for f in floats)
        ints = struct.unpack(f"<{mesh['triangle_count'] * 3}I", idx)
        assert all(i < mesh["vertex_count"] for i in ints)
        cursor = 0
        for vol in mesh["volumes"]:                      # partition: no gap, no overlap
            assert vol["triangle_start"] == cursor
            cursor += vol["triangle_count"]
        assert cursor == mesh["triangle_count"]
    ids = [n["id"] for n in sc["nodes"]]
    assert len(set(ids)) == len(ids)
    for n in sc["nodes"]:
        assert all(math.isfinite(x) for x in n["world_mm"] + n["local_to_parent_mm"])
        assert n["parent_id"] is None or n["parent_id"] in ids
        if n["mesh_key"] is not None:
            assert (n["mesh_key"]["part"], n["mesh_key"]["object_id"]) in keys
        assert len(n["id"]) <= L.MAX_ID_LENGTH
    fids = {f["id"] for f in sc["findings"]}
    assert len(fids) == len(sc["findings"])
    for n in sc["nodes"]:
        assert set(n["finding_ids"]) <= fids
    for f in sc["findings"]:
        assert all(t in ids for t in f["target_ids"])
    assert sc["counts"]["nodes"] == len(sc["nodes"])
    assert sc["counts"]["rendered_triangles"] == sum(
        next(m for m in sc["meshes"] if (m["key"]["part"], m["key"]["object_id"]) == (n["mesh_key"]["part"], n["mesh_key"]["object_id"]))["triangle_count"]
        for n in sc["nodes"] if n["mesh_key"])


def assert_valid(sc: dict) -> None:
    errors = sorted(validator().iter_errors(sc), key=lambda e: list(e.path))
    assert not errors, errors[0].message
    check_invariants(sc)


def test_schema_is_a_valid_closed_schema():
    s = scene.load_schema()
    jsonschema.Draft202012Validator.check_schema(s)
    assert s["additionalProperties"] is False
    # every scene object definition is closed and requires every property it declares
    for name in ("source", "bed", "mesh", "volume", "node", "plate", "finding", "limitation", "counts", "limits",
                 "plate_ref", "instance_ref", "resource_key"):
        d = s["$defs"][name]
        assert d["additionalProperties"] is False, name
        assert set(d["required"]) == set(d["properties"]), name


def test_schema_enums_match_the_code():
    d = scene.load_schema()["$defs"]
    assert tuple(d["error_code"]["enum"]) == scene.ERROR_CODES
    assert "WORKER_WEDGED" in scene.ERROR_CODES and "BUSY" not in scene.ERROR_CODES
    assert set(d["limitation_code"]["enum"]) == set(scene._Limitations.ORDER)
    assert set(scene.PARTIAL_LIMITATIONS | scene.INFORMATIONAL_LIMITATIONS) == set(scene._Limitations.ORDER)
    assert set(d["finding"]["properties"]["kind"]["enum"]) == {"placement", "size", "note"}
    from snapstudio_core import units
    assert set(d["unit_name"]["enum"]) == set(units.MM_PER_UNIT)
    limits = d["limits"]["properties"]
    assert set(limits) == set(L.LIMITS_ECHO)


def test_golden_scene_validates_and_is_reproduced_exactly(tmp_path):
    golden = json.loads((FIX / "golden-scene-1.json").read_text("utf-8"))
    assert_valid(golden)
    path = fx.plain_cube_3mf(tmp_path / "cube.3mf", size=10.0, at=(50.0, 60.0, 0.0))
    built = scene.build_scene_dict(str(path), GOLDEN_REV)
    assert built == golden
    assert json.loads(scene.serialize(built)) == golden


def test_finding_kind_is_required_and_closed():
    v = sub_validator("finding")
    good = {"id": "f0", "engine": "scene", "schema": "scene/1", "pointer": "/nodes/0", "scope": "instance",
            "kind": "placement", "target_ids": ["b0"], "value": {"code": "PLACEMENT_OUTSIDE_BED", "overhang_mm": None}}
    assert not list(v.iter_errors(good))
    bad = dict(good)
    del bad["kind"]
    assert list(v.iter_errors(bad))
    assert list(v.iter_errors({**good, "kind": "opinion"}))
    assert list(v.iter_errors({**good, "extra": 1}))


@pytest.mark.parametrize("name", ["error_response"])
def test_error_response_accepts_every_code(name):
    v = sub_validator(name)
    for code in scene.ERROR_CODES:
        assert not list(v.iter_errors({"error": code, "message": "x"}))
    assert list(v.iter_errors({"error": "BUSY", "message": "x"}))


def test_schema_rejects_mutations_of_the_golden():
    golden = json.loads((FIX / "golden-scene-1.json").read_text("utf-8"))
    v = validator()
    for mutate in (
        lambda s: s.pop("limits"),
        lambda s: s.update(extra=1),
        lambda s: s["nodes"][0].pop("placement_state"),
        lambda s: s["nodes"][0].update(world_mm=[1.0] * 15),
        lambda s: s["nodes"][0]["plate"].update(state="maybe"),
        lambda s: s["meshes"][0]["volumes"][0].update(role="solid"),
        lambda s: s["bed"].update(policy="guess"),
        lambda s: s.update(status="done"),
        lambda s: s["sources"][0].update(unit="yard"),
    ):
        broken = json.loads(json.dumps(golden))
        mutate(broken)
        assert list(v.iter_errors(broken))
