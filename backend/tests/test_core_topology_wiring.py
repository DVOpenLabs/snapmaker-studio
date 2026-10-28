from __future__ import annotations

import copy
import subprocess
from pathlib import Path

from snapstudio_core import firmware_caps, gcode, preflight, preserve
from snapstudio_core.foundation.topology import (
    FeederUnit, Lane, PhysicalToolhead, Topology, head_id, lane_id,
    unit_id,
)


def topology(heads=4, lanes=0, *, reach=None, complete=True, kind="bmcu"):
    uid = unit_id(kind, "fixture")
    feeder_lanes = [Lane(lane_id(uid, i), uid, i,
                         list(reach(i)) if callable(reach) else reach)
                    for i in range(lanes)]
    units = [FeederUnit(uid, kind, lanes=feeder_lanes)] if lanes else []
    return Topology(
        snapshot_id="fixture", received_at="2026-01-01T00:00:00Z",
        heads=[PhysicalToolhead(head_id(i), i) for i in range(heads)],
        units=units, complete=complete,
    ).to_dict()


def project(n):
    return {"filament_count": {"value": n}}


def test_preflight_assignability_and_legacy_fallback():
    printer = {"reachable": True, "toolhead_count": 4,
               "topology": topology(lanes=8, reach=lambda i: [head_id(i % 4)])}
    out = preflight._toolheads_vs_filaments(project(8), printer)
    assert out["result"] == preflight.OK
    assert "More materials than toolheads" not in out["title"]
    assert "4 physical toolheads" in out["evidence"] and "8 feeder lane" in out["evidence"]
    assert "8 physical toolheads" not in out["evidence"]
    assert "can serve every material" in out["consequence"]
    assert "simultaneous" not in str(out).lower() and "guaranteed" not in str(out).lower()
    assert "100%" not in str(out)

    contended = preflight._toolheads_vs_filaments(
        project(8), {**printer, "topology": topology(lanes=2, reach=[head_id(0)])})
    assert contended["result"] == preflight.ATTENTION
    assert "slot:0" in contended["evidence"] or "slot:1" in contended["evidence"]

    unknown_reach = preflight._toolheads_vs_filaments(
        project(8), {**printer, "topology": topology(lanes=8, reach=None)})
    assert unknown_reach["result"] == preflight.UNKNOWN
    incomplete = preflight._toolheads_vs_filaments(
        project(2), {**printer, "topology": topology(lanes=0, complete=False)})
    assert incomplete["result"] == preflight.UNKNOWN

    legacy_printer = {"reachable": True, "toolhead_count": 4}
    assert preflight._toolheads_vs_filaments(project(8), legacy_printer) == \
        preflight._toolheads_vs_filaments(project(8), {**legacy_printer, "topology": {"invalid": True}})
    assert preflight._toolheads_vs_filaments(project(8), legacy_printer)["title"] == "More materials than toolheads"


def test_firmware_caps_topology_details_and_legacy_text():
    objs = ["extruder", "extruder1", "extruder2", "extruder3"]
    no_topology = firmware_caps.interpret(objs, 4, None)
    legacy_invalid_topology = firmware_caps.interpret(objs, 4, None, topology={"invalid": True})
    assert no_topology == legacy_invalid_topology

    stock = firmware_caps.interpret(objs, 4, None, topology=topology(kind="stock"))
    multi = firmware_caps.interpret(objs, 4, None,
                                    topology=topology(lanes=8, reach=lambda i: [head_id(i % 4)]))
    incomplete = firmware_caps.interpret(objs, 4, None,
                                         topology=topology(complete=False))
    stock_feature = next(x for x in stock["features"] if "multimaterial" in x["name"])
    assert stock_feature["name"] == "4-toolhead multimaterial"
    assert "4 physical toolheads" in stock_feature["detail"]
    assert "no feeder lanes reported" in stock_feature["detail"]
    feature = next(x for x in multi["features"] if "multimaterial" in x["name"])
    assert "4 physical toolheads" in feature["detail"] and "8 feeder lanes" in feature["detail"]
    assert "prints up to" not in feature["detail"]
    assert any("head count unknown" in x["name"] for x in incomplete["features"])


def test_preserve_per_logical_vectors_and_legacy_behavior():
    cfg = {"nozzle_temperature": [float(i) for i in range(8)]}
    original = copy.deepcopy(cfg)
    changes, warnings = preserve.prepare_preserved_values(cfg, 8, logical_slots=8)
    assert cfg == original and not warnings
    assert changes[0]["category"] == "kept_per_logical"
    assert "logical slot" in changes[0]["reason"]

    short = {"nozzle_temperature": [1, 2, 3]}
    _, warnings = preserve.prepare_preserved_values(short, 8, logical_slots=8)
    assert len(short["nozzle_temperature"]) == 4 and warnings

    before = {"nozzle_temperature": [float(i) for i in range(8)]}
    changes, warnings = preserve.prepare_preserved_values(before, 8)
    # explicit legacy result, not a comparison of the implementation with itself
    assert before == {"nozzle_temperature": [0.0, 1.0, 2.0, 3.0]}
    assert warnings == [] and len(changes) == 1
    assert changes[0]["category"] == "mapped" and changes[0]["reason"] == "resized to 4 toolheads (values preserved)"
    assert changes[0]["old"] == [float(i) for i in range(8)]


def _gcode(tmp_path, nozzle_line):
    path = tmp_path / "fixture.gcode"
    path.write_text(
        "; generated by OrcaSlicer 2.3.0 on 2026-01-01\n"
        "; CONFIG_BLOCK_START\n"
        f"; nozzle_diameter = {nozzle_line}\n"
        "; CONFIG_BLOCK_END\nG1 X1 Y1\n; total layer number = 1\n",
        encoding="utf-8")
    return path


def test_gcode_distinguishes_physical_nozzle_vector(tmp_path):
    eight = ",".join(["0.4"] * 8)
    facts = gcode.read_facts(_gcode(tmp_path, eight))
    assert facts["slot_count"] == 8
    assert facts["nozzle_vector_scope"] == "unknown"
    assert facts["physical_head_count"] is None
    assert "the physical toolhead count (the nozzle list can be per filament)" in facts["unknowns"]

    path = _gcode(tmp_path, eight)
    text = path.read_text(encoding="utf-8").replace(
        "; CONFIG_BLOCK_END", "; fos_physical_nozzle_diameter = 0.4,0.4,0.4,0.4\n; CONFIG_BLOCK_END")
    path.write_text(text, encoding="utf-8")
    facts = gcode.read_facts(path)
    assert facts["physical_head_count"] == 4
    assert facts["physical_nozzle_diameter_mm"] == [0.4] * 4


def test_color_plan_is_untouched():
    repo = Path(__file__).resolve().parents[2]
    baseline = subprocess.check_output(
        ["git", "show", "HEAD:backend/snapstudio_core/color_plan.py"], cwd=repo)
    assert (repo / "backend/snapstudio_core/color_plan.py").read_bytes() == baseline


# --- cases a-e through the whole preflight check ---------------------------------------

BMCU_LIKE = dict(lanes=8, reach=lambda i: [head_id(i % 4)])
BANNED = ("simultaneous", "guaranteed", "100%")


def check(n, topo, **printer):
    entry = {"reachable": True, "toolhead_count": 4, "topology": topo, **printer}
    return preflight._toolheads_vs_filaments(project(n) if n is not None else {}, entry)


def assert_no_overclaim(out):
    text = str(out).lower()
    for word in BANNED:
        assert word not in text
    assert "8 physical toolheads" not in text and "8 toolheads" not in text


def test_case_a_stock_four_heads_without_lanes():
    fits = check(4, topology())
    assert fits["result"] == preflight.OK
    assert "4 physical toolheads" in fits["evidence"]
    assert "feeder lane that reaches" not in fits["evidence"]   # there are no lanes to name
    assert "its own physical toolhead" in fits["evidence"]
    too_many = check(8, topology())
    assert too_many["result"] == preflight.ATTENTION
    assert "4 physical toolheads" in too_many["evidence"]
    assert "no feeder lanes" in too_many["evidence"]
    assert too_many["title"] != "More materials than toolheads"
    for out in (fits, too_many):
        assert_no_overclaim(out)


def test_case_b_eight_lanes_four_heads_is_not_eight_heads():
    out = check(8, topology(**BMCU_LIKE))
    assert out["result"] == preflight.OK
    assert out["title"] != "More materials than toolheads"
    assert "4 physical toolheads" in out["evidence"] and "8 feeder lane" in out["evidence"]
    assert "take turns" in out["consequence"]
    assert_no_overclaim(out)
    # the legacy count comparison would have said ATTENTION for 8 > 4 and must not decide here
    legacy = preflight._toolheads_vs_filaments(project(8), {"reachable": True, "toolhead_count": 4})
    assert legacy["title"] == "More materials than toolheads" and legacy["result"] != out["result"]


def test_case_c_lanes_that_all_reach_one_head_are_named_as_contended():
    out = check(8, topology(lanes=2, reach=[head_id(0)]))
    assert out["result"] == preflight.ATTENTION
    assert "slot:0" in out["evidence"] and "affected requirements" in out["evidence"]
    assert "2 feeder lane" in out["evidence"]
    assert_no_overclaim(out)


def test_case_d_unknown_reach_never_falls_back_to_counting():
    for materials in (2, 4, 8):
        out = check(materials, topology(lanes=8, reach=None))
        assert out["result"] == preflight.UNKNOWN, materials
        assert "unknown" in out["evidence"].lower()
        assert_no_overclaim(out)


def test_case_e_incomplete_head_list_is_unknown_even_when_counts_match():
    out = check(4, topology(heads=4, lanes=4, reach=lambda i: [head_id(i)], complete=False))
    assert out["result"] == preflight.UNKNOWN
    assert "unknown number of physical toolheads" in out["evidence"]
    assert "4 physical toolheads" not in out["evidence"]


def test_unmeasured_material_count_is_unknown_not_zero():
    for bad in (None, "four", True, -1):
        out = preflight._toolheads_vs_filaments(
            {"filament_count": {"value": bad}},
            {"reachable": True, "toolhead_count": 4, "topology": topology(**BMCU_LIKE)})
        assert out["result"] == preflight.UNKNOWN, bad
        assert "not measured" in out["evidence"]
    assert check(None, topology(**BMCU_LIKE))["result"] == preflight.UNKNOWN


def test_zero_materials_with_a_complete_topology_is_ok():
    assert check(0, topology())["result"] == preflight.OK


def test_undecodable_topology_leaves_legacy_result_untouched():
    legacy = {"reachable": True, "toolhead_count": 4}
    expected = preflight._toolheads_vs_filaments(project(8), legacy)
    for junk in ("text", 3, [], {}, {"heads": "x"}, {"snapshot_id": 1}):
        got = preflight._toolheads_vs_filaments(project(8), {**legacy, "topology": junk})
        assert got == expected, junk
    assert expected["title"] == "More materials than toolheads"


# --- firmware capability text ------------------------------------------------------------

OBJECTS = ["extruder", "extruder1", "extruder2", "extruder3"]


def features(topo):
    return {f["name"]: f["detail"] for f in
            firmware_caps.interpret(OBJECTS, 4, None, topology=topo)["features"]}


def test_firmware_caps_wording_for_each_topology_case():
    stock = features(topology())
    assert stock == {"4-toolhead multimaterial": "4 physical toolheads; no feeder lanes reported"}
    lanes = features(topology(**BMCU_LIKE))
    assert lanes["4-toolhead multimaterial"] == "4 physical toolheads; 8 feeder lanes reported by bmcu"
    unknown = features(topology(complete=False))
    assert list(unknown) == ["Multimaterial topology (head count unknown)"]
    assert "unknown" in unknown["Multimaterial topology (head count unknown)"]
    for text in (*stock.values(), *lanes.values(), *unknown.values()):
        assert "prints up to" not in text and "colours/materials in one job" not in text
        assert not any(word in text.lower() for word in BANNED)


def test_firmware_caps_single_head_without_lanes_is_not_multimaterial():
    got = features(topology(heads=1))
    assert not any("multimaterial" in name for name in got)


def test_firmware_caps_legacy_text_is_unchanged_without_a_topology():
    assert features(None) == {"4-toolhead multimaterial": "prints up to 4 colours/materials in one job"}


# --- preserved per-extruder vectors ------------------------------------------------------

def test_preserve_keeps_every_per_logical_vector_when_the_slot_count_matches():
    keys = sorted(preserve.PER_EXTRUDER_VECTORS)
    cfg = {key: [f"{key}-{i}" for i in range(8)] for key in keys}
    original = copy.deepcopy(cfg)
    changes, warnings = preserve.prepare_preserved_values(cfg, 8, logical_slots=8)
    assert cfg == original and warnings == []
    assert sorted(c["key"] for c in changes) == keys
    assert all(c["category"] == "kept_per_logical" and c["new"] == c["old"] for c in changes)


def test_preserve_still_resizes_when_the_slot_count_does_not_match():
    for slots in (None, 6, 4, True, False, "8", 0):
        cfg = {"nozzle_temperature": list(range(8))}
        changes, warnings = preserve.prepare_preserved_values(cfg, 8, logical_slots=slots)
        assert cfg["nozzle_temperature"] == [0, 1, 2, 3], slots
        assert changes[0]["category"] == "mapped", slots
    cfg = {"nozzle_temperature": list(range(8))}
    _, warnings = preserve.prepare_preserved_values(cfg, 6, logical_slots=None)
    assert warnings and "mapped to four U1 toolheads" in warnings[0]
    five = {"nozzle_temperature": [1, 2, 3, 4, 5]}
    _, warnings = preserve.prepare_preserved_values(five, 8, logical_slots=8)
    assert five["nozzle_temperature"] == [1, 2, 3, 4] and warnings


def test_repair_path_truncates_per_logical_vectors_inside_preserve_not_before():
    """repair.py skips per-extruder vectors in conform_filament_arrays, then calls
    prepare_preserved_values without logical_slots, which is where the cut to four happens.
    Wiring the keyword through repair is the integration PR."""
    from snapstudio_core.filaments import conform_filament_arrays
    vectors = {key: list(range(8)) for key in preserve.PER_EXTRUDER_VECTORS}
    cfg = copy.deepcopy(vectors)
    conform_filament_arrays(cfg, 8)
    assert cfg == vectors                       # the earlier pass leaves them alone
    changes, _ = preserve.prepare_preserved_values(cfg, 8)      # what repair.py does today
    assert all(value == [0, 1, 2, 3] for value in cfg.values())
    assert {c["category"] for c in changes} == {"mapped"}
    repair_source = (Path(__file__).resolve().parents[1] / "snapstudio_core" / "repair.py").read_text(encoding="utf-8")
    assert "logical_slots" not in repair_source        # nothing in repair.py passes the slot count yet


def test_self_contradicting_topology_is_unknown_not_a_fit():
    raw = topology(lanes=2, reach=[head_id(0)])
    raw["units"][0]["lanes"][1]["reachable_heads"] = [head_id(9)]     # head:9 is not listed
    out = check(2, raw)
    assert out["result"] == preflight.UNKNOWN and "lane_unknown_head" in out["evidence"]
    caps = firmware_caps.interpret(OBJECTS, 4, None, topology=raw)
    assert [f["name"] for f in caps["features"]] == ["Multimaterial topology (head count unknown)"]


def test_gcode_empty_or_nonfinite_physical_entries_are_not_a_count(tmp_path):
    for raw in ("0.4,,0.4,0.4", ",0.4,0.4", "0.4,0.4,", "0.4,inf,0.4,0.4", "0.4,nan,0.4,0.4"):
        facts = gcode_facts(tmp_path, ",".join(["0.4"] * 8), raw)
        assert facts["physical_head_count"] is None, raw
        assert any("physical toolhead count" in item for item in facts["unknowns"]), raw


# --- G-code facts ----------------------------------------------------------------------------

def gcode_facts(tmp_path, nozzles, physical=None):
    path = _gcode(tmp_path, nozzles)
    if physical is not None:
        text = path.read_text(encoding="utf-8").replace(
            "; CONFIG_BLOCK_END", f"; fos_physical_nozzle_diameter = {physical}\n; CONFIG_BLOCK_END")
        path.write_text(text, encoding="utf-8")
    return gcode.read_facts(path)


UNKNOWN_HEADS = "the physical toolhead count (the nozzle list can be per filament)"


def test_gcode_four_nozzles_without_a_physical_vector_adds_no_unknown(tmp_path):
    facts = gcode_facts(tmp_path, "0.4,0.4,0.4,0.4")
    assert facts["slot_count"] == 4 and facts["physical_head_count"] is None
    assert UNKNOWN_HEADS not in facts["unknowns"]


def test_gcode_physical_vector_is_reported_as_read_and_not_as_the_nozzle_list(tmp_path):
    facts = gcode_facts(tmp_path, ",".join(["0.4"] * 8), ",".join(["0.4", "0.6", "0.4", "0.4"]))
    assert facts["slot_count"] == 8 and facts["physical_head_count"] == 4
    assert facts["physical_nozzle_diameter_mm"] == [0.4, 0.6, 0.4, 0.4]
    assert UNKNOWN_HEADS not in facts["unknowns"]
    wide = gcode_facts(tmp_path, ",".join(["0.4"] * 8), ",".join(["0.4"] * 8))
    assert wide["physical_head_count"] == 8 and wide["slot_count"] == 8


def test_gcode_unreadable_physical_vector_never_invents_a_count(tmp_path):
    for raw in ("0.4,abc,0.4,0.4", "0.4,0,0.4,0.4", "0.4,-1", "abc", ""):
        facts = gcode_facts(tmp_path, ",".join(["0.4"] * 8), raw)
        assert facts["physical_head_count"] is None, raw
        assert "physical_nozzle_diameter_mm" not in facts, raw
        assert any("physical toolhead count" in item for item in facts["unknowns"]), raw
        assert facts["slot_count"] == 8
