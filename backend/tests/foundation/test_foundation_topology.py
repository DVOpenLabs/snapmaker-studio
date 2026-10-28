"""Topology: ids, index bases, validation, counts, assignability."""
import json
import os

import pytest

from snapstudio_core.foundation import topology as t

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
T0 = "2026-01-01T12:00:00Z"


def codes(diags):
    return {d.code for d in diags}


def load(name):
    with open(os.path.join(FIX, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def heads(n):
    return [t.PhysicalToolhead(t.head_id(i), i) for i in range(n)]


def unit_with(kind, name, reach, paths=None, count=None):
    uid = t.unit_id(kind, name)
    n = count if count is not None else len(reach)
    lanes = [t.Lane(t.lane_id(uid, i), uid, i, reachable_heads=reach[i],
                    path=(paths[i] if paths else None)) for i in range(n)]
    return t.FeederUnit(uid, kind, None, lanes)


def topo(h=0, units=(), slots=0, complete=True, bindings=()):
    return t.Topology("s", T0, heads=heads(h), units=list(units),
                      slots=[t.LogicalSlot(t.slot_id(i), i) for i in range(slots)],
                      bindings=list(bindings), complete=complete)


def reqs(*idx):
    return [t.ProjectSlotRequirement(i) for i in idx]


# -- ids and index bases ------------------------------------------------------
def test_id_builders_and_kinds():
    assert t.head_id(0) == "head:0" and t.slot_id(7) == "slot:7"
    u = t.unit_id("afc", "box-1")
    assert u == "unit:afc:box-1" and t.lane_id(u, 3) == "lane:unit:afc:box-1:3"
    assert [t.id_kind(x) for x in ("head:1", "slot:2", u, t.lane_id(u, 0), "head:x", 5)] == \
        ["head", "slot", "unit", "lane", None, None]
    assert t.id_suffix_index(t.lane_id(u, 3)) == 3 and t.id_suffix_index(u) is None


def test_revision_extra_cannot_replace_mapping_revision():
    with pytest.raises(ValueError, match="mapping_revision"):
        t.assignability(topo(), [], revisions={"mapping_revision": "fixed"})


@pytest.mark.parametrize("bad", [-1, True, 1.0, "1", None])
def test_negative_or_non_int_index_rejected(bad):
    with pytest.raises(ValueError):
        t.head_id(bad)


def test_unit_id_rejects_unknown_kind_and_odd_names():
    with pytest.raises(ValueError):
        t.unit_id("bogus", "a")
    with pytest.raises(ValueError):
        t.unit_id("afc", "a b")
    with pytest.raises(ValueError):
        t.lane_id("head:0", 0)


@pytest.mark.parametrize("source,wire,internal", [("gcode_t", 0, 0), ("gcode_t", 3, 3), ("orca_filament", 1, 0),
                                                  ("orca_filament", 4, 3), ("display", 1, 0),
                                                  ("multiace_wire", 0, 0), ("internal", 2, 2)])
def test_zero_vs_one_based_normalisation(source, wire, internal):
    assert t.normalise_index(source, wire) == internal
    assert t.denormalise_index(source, internal) == wire


def test_one_based_zero_is_not_an_index_and_junk_is_none():
    assert t.normalise_index("orca_filament", 0) is None
    assert t.normalise_index("gcode_t", -1) is None
    assert t.normalise_index("gcode_t", True) is None
    assert t.normalise_index("gcode_t", "1") is None


def test_unknown_index_source_is_a_programming_error():
    for fn in (lambda: t.normalise_index("bogus", 1), lambda: t.denormalise_index("bogus", 1),
               lambda: t.index_base_diagnostic("bogus")):
        with pytest.raises(ValueError):
            fn()
    assert t.index_base_diagnostic("orca_filament").code == "index_base_source"


def test_display_index_is_one_based():
    assert heads(2)[1].display_index == 2
    assert t.LogicalSlot("slot:0", 0).display_index == 1
    assert t.Lane("lane:unit:afc:a:0", "unit:afc:a", 0).display_index == 1


# -- validation ---------------------------------------------------------------
def test_valid_topology_has_no_diagnostics():
    u = unit_with("multiace", "a", [["head:0"], ["head:1"]])
    assert t.validate(topo(2, [u], 2)) == []


def test_duplicate_ids_flagged():
    tp = topo(2, slots=1)
    tp.heads.append(t.PhysicalToolhead("head:0", 0))
    assert "duplicate_id" in codes(t.validate(tp))


def test_invalid_id_kind_flagged():
    tp = topo(0, slots=0)
    tp.heads.append(t.PhysicalToolhead("slot:0", 0))
    assert "invalid_id" in codes(t.validate(tp))


def test_lane_unit_mismatch():
    u = unit_with("afc", "a", [None])
    u.lanes[0].unit_id = "unit:afc:other"
    assert "lane_unit_mismatch" in codes(t.validate(topo(1, [u])))


def test_dangling_reachable_head():
    u = unit_with("afc", "a", [["head:9"]])
    assert "lane_unknown_head" in codes(t.validate(topo(1, [u])))


def test_dangling_binding_slot_and_target():
    u = unit_with("afc", "a", [None])
    tp = topo(1, [u], 1, bindings=[t.SlotBinding("slot:5", "head:0"),
                                   t.SlotBinding("slot:0", "lane:unit:afc:a:9")])
    found = [d for d in t.validate(tp) if d.code == "binding_dangling"]
    assert {d.field for d in found} == {"slot:5", "slot:0->lane:unit:afc:a:9"}


def test_contradictory_binding_between_slot_field_and_binding_record():
    tp = topo(2, slots=1, bindings=[t.SlotBinding("slot:0", "head:1")])
    tp.slots[0].binding = "head:0"
    assert "contradictory_binding" in codes(t.validate(tp))


def test_agreeing_binding_in_both_places_is_fine():
    tp = topo(2, slots=1, bindings=[t.SlotBinding("slot:0", "head:1")])
    tp.slots[0].binding = "head:1"
    assert t.validate(tp) == []


def test_mixed_index_bases_flagged():
    tp = topo(0)
    tp.heads = [t.PhysicalToolhead("head:0", 0), t.PhysicalToolhead("head:2", 1)]
    assert "mixed_index_bases" in codes(t.validate(tp))


def test_id_index_off_by_one_flagged():
    tp = topo(0)
    tp.heads = [t.PhysicalToolhead("head:1", 0), t.PhysicalToolhead("head:2", 1)]
    assert "index_id_mismatch" in codes(t.validate(tp))


# -- counts -------------------------------------------------------------------
def test_counts_unknown_head_count_when_incomplete():
    c = t.counts(topo(2, slots=8, complete=False))
    assert c["physical_heads"] is None and c["logical_slots"] == 8 and c["complete"] is False


def test_counts_never_derived_from_slots():
    c = t.counts(topo(4, slots=8, complete=True))
    assert c["physical_heads"] == 4 and c["logical_slots"] == 8


def test_complete_with_no_heads_is_still_unknown_not_zero():
    assert t.counts(topo(0, slots=3, complete=True))["physical_heads"] is None


def test_counts_lane_reach_knowledge():
    u = unit_with("afc", "a", [["head:0"], None, []])
    c = t.counts(topo(1, [u]))
    assert c["lanes"] == 3 and c["lanes_with_known_reach"] == 2


# -- assignability ------------------------------------------------------------
def test_four_heads_eight_slots_bounds_not_from_slot_count():
    # 8 slots but a single unit whose lanes only reach heads 0..3.
    u = unit_with("multiace", "a", [[f"head:{i % 4}"] for i in range(8)])
    tp = topo(4, [u], 8)
    res = t.assignability(tp, reqs(*range(8)), t.ResourceConstraints(heads_single_active=True,
                                                                  exclusive_paths=[]))
    assert res["bound"] == {"min": 4, "max": 4}      # four heads, never eight
    assert res["assignable"] is False
    four = t.assignability(tp, reqs(0, 1, 2, 3), t.ResourceConstraints(heads_single_active=True,
                                                                     exclusive_paths=[]))
    assert four["assignable"] is True and four["bound"] == {"min": 4, "max": 4}


def test_one_head_two_requirements_contended_or_impossible():
    u = unit_with("afc", "a", [["head:0"], ["head:0"]])
    res = t.assignability(topo(1, [u], 2), reqs(0, 1),
                          t.ResourceConstraints(heads_single_active=True, exclusive_paths=[]))
    assert res["assignable"] is False and res["bound"] == {"min": 1, "max": 1}


def test_multiple_lanes_competing_for_one_head_unknown_exclusivity_gives_range():
    u = unit_with("afc", "a", [["head:0"], ["head:0"]])
    res = t.assignability(topo(1, [u], 2), reqs(0, 1))
    assert res["assignable"] is None
    assert res["bound"] == {"min": 1, "max": 2}
    assert any("only one lane at a time" in r for r in res["reasons"])


def test_heads_not_exclusive_lets_both_use_one_head():
    u = unit_with("afc", "a", [["head:0"], ["head:0"]])
    res = t.assignability(topo(1, [u], 2), reqs(0, 1),
                          t.ResourceConstraints(heads_single_active=False, exclusive_paths=[]))
    assert res["assignable"] is True and res["bound"] == {"min": 2, "max": 2}


def test_unknown_lane_reach_never_exact():
    u = unit_with("afc", "a", [None, None])
    res = t.assignability(topo(2, [u], 2), reqs(0, 1))
    assert res["assignable"] is None and res["bound"]["min"] == 0 and res["bound"]["max"] == 2
    assert any("reach" in r for r in res["reasons"])
    assert {p["result"] for p in res["per_requirement"]} == {"unknown"}


def test_known_unreachable_lane_is_unreachable_not_unknown():
    u = unit_with("afc", "a", [[]])
    res = t.assignability(topo(1, [u], 1), reqs(0))
    assert res["assignable"] is False
    assert res["per_requirement"][0]["result"] == "unreachable"


def test_disconnected_irrelevant_lane_does_not_affect_result():
    # Lane 1 only reaches head:1 and is never requested; requesting slot 0 stays exact.
    u = unit_with("afc", "a", [["head:0"], ["head:1"]])
    tp = topo(2, [u], 2, bindings=[t.SlotBinding("slot:0", t.lane_id(u.id, 0))])
    res = t.assignability(tp, reqs(0), t.ResourceConstraints(heads_single_active=True, exclusive_paths=[]))
    assert res["assignable"] is True and res["bound"] == {"min": 1, "max": 1}
    assert res["per_requirement"][0]["candidates"] == [t.lane_id(u.id, 0)]


def test_disconnected_lane_with_unknown_reach_does_not_taint_bound_requirement():
    u = unit_with("afc", "a", [["head:0"], None])
    tp = topo(1, [u], 2, bindings=[t.SlotBinding("slot:0", t.lane_id(u.id, 0))])
    res = t.assignability(tp, reqs(0), t.ResourceConstraints(heads_single_active=True, exclusive_paths=[]))
    assert res["assignable"] is True and res["bound"] == {"min": 1, "max": 1}


def test_binding_to_head_directly():
    tp = topo(2, slots=2, bindings=[t.SlotBinding("slot:0", "head:0"), t.SlotBinding("slot:1", "head:1")])
    res = t.assignability(tp, reqs(0, 1))
    assert res["assignable"] is True and res["bound"] == {"min": 2, "max": 2}
    both = topo(2, slots=2, bindings=[t.SlotBinding("slot:0", "head:0"), t.SlotBinding("slot:1", "head:0")])
    assert t.assignability(both, reqs(0, 1))["assignable"] is False


def test_binding_to_missing_target_is_reasoned_and_unassignable():
    tp = topo(1, slots=1, bindings=[t.SlotBinding("slot:0", "lane:unit:afc:zz:0")])
    res = t.assignability(tp, reqs(0))
    assert res["assignable"] is False
    assert any("does not contain" in r for r in res["reasons"])


def test_contradictory_binding_is_unknown_for_that_requirement():
    tp = topo(2, slots=1, bindings=[t.SlotBinding("slot:0", "head:0"), t.SlotBinding("slot:0", "head:1")])
    res = t.assignability(tp, reqs(0))
    assert res["per_requirement"][0]["result"] == "unknown"
    assert res["assignable"] is False   # no usable option for that requirement


def test_no_units_unbound_slots_use_heads_directly():
    res = t.assignability(topo(3, slots=3), reqs(0, 1, 2))
    assert res["assignable"] is True and res["bound"] == {"min": 3, "max": 3}
    assert t.assignability(topo(3, slots=4), reqs(0, 1, 2, 3))["assignable"] is False


def test_declared_exclusive_path_group_blocks_simultaneous_lanes():
    u = unit_with("afc", "a", [["head:0"], ["head:1"]])
    ex = t.ResourceConstraints(heads_single_active=True, exclusive_paths=[[u.lanes[0].id, u.lanes[1].id]])
    res = t.assignability(topo(2, [u], 2), reqs(0, 1), ex)
    assert res["assignable"] is False and res["bound"] == {"min": 1, "max": 1}


def test_shared_path_without_declaration_is_unknown_not_exclusive():
    u = unit_with("afc", "a", [["head:0"], ["head:1"]], paths=[["hub:1"], ["hub:1"]])
    res = t.assignability(topo(2, [u], 2), reqs(0, 1), t.ResourceConstraints(heads_single_active=True))
    assert res["assignable"] is None and res["bound"] == {"min": 1, "max": 2}
    assert any("sharing a feeder path" in r for r in res["reasons"])
    declared_free = t.assignability(topo(2, [u], 2), reqs(0, 1),
                                    t.ResourceConstraints(heads_single_active=True, exclusive_paths=[]))
    assert declared_free["assignable"] is True


def test_asymmetry_when_heads_not_exclusive_min_never_exceeds_max():
    # Known issue: _max_assign with heads_exclusive False. The low bound must not exceed the high bound
    # and, with heads known not exclusive, the lanes' shared head is simply reused.
    u = unit_with("afc", "a", [["head:0"], ["head:0"], ["head:0"]])
    for cons in (t.ResourceConstraints(heads_single_active=False),
                 t.ResourceConstraints(heads_single_active=False, exclusive_paths=[]),
                 t.ResourceConstraints(heads_single_active=None),
                 t.ResourceConstraints(heads_single_active=True)):
        res = t.assignability(topo(1, [u], 3), reqs(0, 1, 2), cons)
        assert res["bound"]["min"] <= res["bound"]["max"] <= 3


def test_direct_head_binding_and_lane_through_same_head_conflict_regardless_of_exclusivity():
    u = unit_with("afc", "a", [["head:0"]])
    tp = topo(1, [u], 2, bindings=[t.SlotBinding("slot:0", "head:0"), t.SlotBinding("slot:1", t.lane_id(u.id, 0))])
    res = t.assignability(tp, reqs(0, 1), t.ResourceConstraints(heads_single_active=False, exclusive_paths=[]))
    assert res["bound"] == {"min": 1, "max": 1}


def test_search_limit_gives_unknown(monkeypatch):
    monkeypatch.setattr(t, "_NODE_BUDGET", 3)
    u = unit_with("afc", "a", [["head:0", "head:1"]] * 6)
    res = t.assignability(topo(2, [u], 6), reqs(*range(6)))
    assert res["assignable"] is None and res["bound"] is None
    assert any("too large" in r for r in res["reasons"])


def test_empty_request_is_trivially_assignable():
    res = t.assignability(topo(1, slots=1), [])
    assert res["assignable"] is True and res["bound"] == {"min": 0, "max": 0}


# -- documents and fixtures -----------------------------------------------------
def test_fixture_round_trips():
    raw = load("topology")
    dec = t.Topology.from_dict(raw)
    assert dec.valid_for_evaluation and dec.diagnostics == []
    assert dec.value.to_dict() == raw
    assert t.validate(dec.value) == []


def test_fixture_decodes_from_json_text_too():
    with open(os.path.join(FIX, "topology.json"), "rb") as fh:
        assert t.Topology.from_dict(fh.read()).valid_for_evaluation


def test_unknown_schema_version_preserved_never_evaluated():
    raw = load("unknown_schema_version")
    dec = t.Topology.from_dict(raw)
    assert dec.value is None and dec.valid_for_evaluation is False
    assert dec.raw == raw and dec.schema_version == "topology/99"
    assert codes(dec.diagnostics) == {"unknown_schema_version"}


def test_missing_schema_version_and_not_an_object():
    assert codes(t.Topology.from_dict({"snapshot_id": "x"}).diagnostics) == {"missing_schema_version"}
    assert codes(t.Topology.from_dict([1]).diagnostics) == {"not_an_object"}
    assert codes(t.Topology.from_dict("{bad").diagnostics) == {"malformed_json"}


def test_decode_missing_required_and_bad_types_never_raise():
    raw = load("topology")
    del raw["complete"]
    raw["heads"] = "nope"
    dec = t.Topology.from_dict(raw)
    assert dec.value is None and {"missing_field", "wrong_type"} <= codes(dec.diagnostics)


def test_reachable_heads_none_vs_empty_survive_round_trip():
    raw = load("topology")
    lanes = raw["units"][0]["lanes"]
    lanes[0]["reachable_heads"] = []
    lanes[1]["reachable_heads"] = None
    value = t.Topology.from_dict(raw).value
    assert value.units[0].lanes[0].reachable_heads == []
    assert value.units[0].lanes[1].reachable_heads is None
    out = value.to_dict()["units"][0]["lanes"]
    assert out[0]["reachable_heads"] == [] and out[1]["reachable_heads"] is None


def test_negative_index_in_document_is_an_error():
    raw = load("topology")
    raw["heads"][0]["index"] = -1
    dec = t.Topology.from_dict(raw)
    assert dec.value is None and "out_of_range" in codes(dec.diagnostics)


def test_unreadable_time_is_warning_not_error():
    raw = load("topology")
    raw["observed_at"] = "not a time"
    dec = t.Topology.from_dict(raw)
    assert dec.valid_for_evaluation and "time_unreadable" in codes(dec.diagnostics)


def test_project_requirements_are_separate_from_bindings():
    r = t.ProjectSlotRequirement(0, "PLA", "#fff", "gen:1")
    assert r.to_dict() == {"index": 0, "material": "PLA", "colour": "#fff", "recipe_id": "gen:1"}
    assert not hasattr(r, "target")


def test_direct_head_vs_lane_conflict_is_order_independent_when_heads_not_exclusive():
    # Regression: _max_assign used to track lane heads only when heads_exclusive, so the answer
    # depended on whether the lane slot or the direct-head slot was listed first.
    u = unit_with("afc", "a", [["head:0"]])
    lane = t.lane_id(u.id, 0)
    cons = t.ResourceConstraints(heads_single_active=False, exclusive_paths=[])
    first = topo(1, [u], 2, bindings=[t.SlotBinding("slot:0", lane), t.SlotBinding("slot:1", "head:0")])
    second = topo(1, [u], 2, bindings=[t.SlotBinding("slot:0", "head:0"), t.SlotBinding("slot:1", lane)])
    a = t.assignability(first, reqs(0, 1), cons)
    b = t.assignability(second, reqs(0, 1), cons)
    assert a["bound"] == b["bound"] == {"min": 1, "max": 1}


# -- inputs_revision envelope (R10) -----------------------------------------------
def _rev(tp, q=None, cons=None, **kw):
    out = t.assignability(tp, q if q is not None else reqs(0), cons, **kw)
    return out["inputs_revision"]


def test_assignability_result_carries_serialisable_inputs_revision():
    u = unit_with("afc", "a", [["head:0"]])
    tp = topo(1, [u], 1)
    tp.mapping_revision = "map-1"
    env = _rev(tp, revisions={"artifact_hashes": ["sha256:aa"], "observation_revision": "o1", "calibration_revision": "c1"})
    assert env["topology"]["snapshot_id"] == "s" and env["topology"]["hash"].startswith("sha256:")
    assert env["mapping_revision"] == "map-1" and env["revision"].startswith("sha256:")
    assert env["artifact_hashes"] == ["sha256:aa"] and env["observation_revision"] == "o1"
    assert json.loads(json.dumps(env)) == env


def test_each_changed_dependency_changes_the_revision():
    def build(**over):
        u = unit_with("afc", "a", [["head:0"]])
        tp = topo(1, [u], 1)
        tp.mapping_revision = over.get("mapping", "m1")
        return tp
    base = _rev(build())["revision"]
    assert _rev(build())["revision"] == base                                     # deterministic
    assert _rev(build(mapping="m2"))["revision"] != base                         # mapping revision
    assert _rev(build(), reqs(0, 1))["revision"] != base                         # requested materials
    assert _rev(build(), cons=t.ResourceConstraints(heads_single_active=True))["revision"] != base
    for key, val in (("artifact_hashes", ["sha256:aa"]), ("observation_revision", "o2"), ("calibration_revision", "c2")):
        assert _rev(build(), revisions={key: val})["revision"] != base
    changed = build()
    changed.heads = heads(2)
    assert _rev(changed)["revision"] != base                                     # topology content
    moved = build()
    moved.snapshot_id = "other"
    assert _rev(moved)["topology"]["snapshot_id"] == "other" and _rev(moved)["revision"] != base


def test_revision_ignores_read_times_so_an_unchanged_topology_keeps_it():
    a, b = topo(1, [unit_with("afc", "a", [["head:0"]])], 1), topo(1, [unit_with("afc", "a", [["head:0"]])], 1)
    b.received_at = "2026-02-02T00:00:00Z"
    assert _rev(a)["revision"] == _rev(b)["revision"]
