"""A printer setup reaching the real preparation entry point (convert_to_u1 -> repair -> preserve).

Evidence label: fixture-tested. Synthetic projects; hand-built topologies, not read from a device.
Accessory support stays partial: no production caller reads a setup from a printer without being given one.
"""
from __future__ import annotations

import copy
import hashlib
import zipfile
from pathlib import Path

import pytest

from snapstudio_core import preserve
from snapstudio_core.config_io import load_project_settings
from snapstudio_core.convert import convert_to_u1
from snapstudio_core.foundation.topology import SlotBinding, head_id, slot_id
from tests.integration.setup_helpers import FILAMENT_SCOPE, HEAD_SCOPE, project_cfg, topology
from tests.test_project_materials import _project


def saved(result):
    return load_project_settings(zipfile.ZipFile(result.output_path).read("Metadata/project_settings.config"))


def prepare(tmp_path, n, topo, name="p"):
    src = _project(tmp_path, project_cfg(n), name=f"{name}.3mf")
    return src, convert_to_u1(str(src), out_dir=str(tmp_path / name), prepare_mode="preserve", topology=topo)


def vec(key, n):
    return [f"{key}-{i}" for i in range(n)]


def test_absent_setup_keeps_the_stock_u1_behaviour(tmp_path):
    _, res = prepare(tmp_path, 8, None)
    out = saved(res)
    assert all(out[k] == vec(k, 8)[:4] for k in FILAMENT_SCOPE + HEAD_SCOPE)
    assert "setup" not in res.settings_summary


def test_valid_eight_slot_setup_keeps_each_vector_at_its_own_scope(tmp_path):
    _, res = prepare(tmp_path, 8, topology())
    out = saved(res)
    assert all(out[k] == vec(k, 8) for k in FILAMENT_SCOPE)          # one entry per project filament
    assert all(out[k] == vec(k, 4) for k in HEAD_SCOPE)              # one entry per physical head, not eight
    assert len(out["filament_colour"]) == 8
    assert res.settings_summary["setup"] == {"state": "valid", "heads": 4, "slots": 8, "unbound": []}


def test_dict_form_of_a_valid_setup_is_accepted(tmp_path):
    _, res = prepare(tmp_path, 8, topology().to_dict(), name="d")
    assert saved(res)["nozzle_temperature"] == vec("nozzle_temperature", 8)


def test_a_four_slot_setup_leaves_a_four_filament_project_as_stock(tmp_path):
    _, with_setup = prepare(tmp_path, 4, topology(slots=4), name="w")
    _, without = prepare(tmp_path, 4, None, name="x")
    a, b = saved(with_setup), saved(without)
    assert {k: a[k] for k in FILAMENT_SCOPE + HEAD_SCOPE} == {k: b[k] for k in FILAMENT_SCOPE + HEAD_SCOPE}


def test_unbound_slots_stay_visibly_unresolved(tmp_path):
    _, res = prepare(tmp_path, 8, topology(unbound=(2, 5)), name="u")
    assert res.settings_summary["setup"]["unbound"] == ["slot:2", "slot:5"]
    warnings = " ".join(res.settings_summary["warnings"])
    assert "2 of 8 material slots" in warnings and "did not assign" in warnings
    assert "ready" not in warnings.lower()
    assert saved(res)["nozzle_temperature"] == vec("nozzle_temperature", 8)       # nothing dropped


INVALID = {
    "binding_to_missing_head": lambda: topology(bind_to=lambda i: head_id(9)),
    "dangling_binding": lambda: topology(extra_binding=SlotBinding(slot_id(40), head_id(0), [])),
    "contradictory_binding": lambda: topology(extra_binding=SlotBinding(slot_id(0), head_id(3), [])),
    "incomplete_head_list": lambda: topology(complete=False),
    "no_slots": lambda: topology(slots=0),
    "six_heads_for_a_u1_copy": lambda: topology(heads=6, slots=6),
    "one_head_for_a_u1_copy": lambda: topology(heads=1, slots=4),
}


@pytest.mark.parametrize("name", sorted(INVALID))
def test_an_invalid_setup_blocks_the_conversion_and_writes_nothing(tmp_path, name):
    src = _project(tmp_path, project_cfg(8), name="src.3mf")
    digest = hashlib.sha256(Path(src).read_bytes()).hexdigest()
    out_dir = tmp_path / "out"
    res = convert_to_u1(str(src), out_dir=str(out_dir), prepare_mode="preserve", topology=INVALID[name]())
    assert res.blocked is True
    assert res.output_path == "" and not out_dir.exists()
    assert hashlib.sha256(Path(src).read_bytes()).hexdigest() == digest        # the source is untouched
    message = " ".join(res.errors)
    assert "cannot be used" in message and "Nothing was prepared" in message
    assert res.settings_summary["setup"]["state"] == "invalid" and res.settings_summary["setup"]["reasons"]


def test_repair_itself_refuses_an_invalid_setup(tmp_path):
    from snapstudio_core.container import ThreeMF
    from snapstudio_core.repair import repair
    tm = ThreeMF.open(_project(tmp_path, project_cfg(8), name="r.3mf"))
    with pytest.raises(ValueError, match="cannot be used"):
        repair(copy.deepcopy(tm), mode="preserve", dry_run=True, topology=topology(complete=False))


def test_assess_setup_distinguishes_absent_invalid_and_valid():
    assert preserve.assess_setup(None) == {"state": "absent"}
    assert preserve.assess_setup(topology(complete=False))["state"] == "invalid"
    assert preserve.assess_setup({"not": "a topology"})["state"] == "invalid"
    assert preserve.assess_setup(["x"])["state"] == "invalid"
    assert preserve.assess_setup(object())["state"] == "invalid"
    v = preserve.assess_setup(topology(unbound=(1,)))
    assert v["state"] == "valid" and v["unbound"] == ["slot:1"] and v["heads"] == 4 and v["slots"] == 8
    bad_types = topology()
    bad_types.heads[0].id = None           # a hand-built object with a bad id is refused, not a crash
    assert preserve.assess_setup(bad_types)["state"] == "invalid"


def test_a_four_slot_setup_with_an_eight_filament_project_keeps_filament_vectors_at_eight(tmp_path):
    _, res = prepare(tmp_path, 8, topology(slots=4), name="s")
    out = saved(res)
    assert all(out[k] == vec(k, 8) for k in FILAMENT_SCOPE)      # the project's filaments, not the setup's slot count
    assert all(out[k] == vec(k, 4) for k in HEAD_SCOPE)
    assert res.settings_summary["setup"]["slots"] == 4


def test_a_valid_setup_on_a_starter_conversion_is_reported_as_not_applied(tmp_path):
    stl = tmp_path / "cube.stl"
    stl.write_text('solid c\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 10 0 0\nvertex 0 10 0\nendloop\nendfacet\nendsolid c\n')
    res = convert_to_u1(str(stl), out_dir=str(tmp_path / "o"), topology=topology())
    summary = res.settings_summary
    assert summary["setup"]["applied"] is False and summary["setup"]["slots"] == 8
    assert any("not applied" in w for w in summary["warnings"])
    blocked = convert_to_u1(str(stl), out_dir=str(tmp_path / "o2"), topology=topology(complete=False))
    assert blocked.blocked is True and not (tmp_path / "o2").exists()
