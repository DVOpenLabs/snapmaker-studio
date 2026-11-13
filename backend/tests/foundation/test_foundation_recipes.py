"""Virtual recipes: decode, validation, dialect preservation, physical inputs."""
import json
import os

import pytest

from snapstudio_core.foundation import recipes as r
from snapstudio_core.foundation.topology import SlotBinding

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIX, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def codes(diags):
    return {d.code for d in diags}


def recipe(*comps, rid="gen:1", kind="fullspectrum"):
    return r.VirtualRecipe(rid, {"name": "gen", "version": None}, kind,
                           [r.RecipeComponent(s, ratio, rk) for s, ratio, rk in comps], True)


def test_fixture_round_trips():
    raw = load("virtual_recipe")
    dec = r.VirtualRecipe.from_dict(raw)
    assert dec.valid_for_evaluation and dec.diagnostics == []
    assert dec.value.to_dict() == raw
    assert raw["simulated"] is True


def test_simulated_is_always_true_even_if_document_says_otherwise():
    raw = load("virtual_recipe")
    raw["simulated"] = False
    assert r.VirtualRecipe.from_dict(raw).value.to_dict()["simulated"] is True


def test_valid_recipe_has_no_diagnostics():
    rec = recipe(("slot:0", 0.5, "mass"), ("slot:1", 0.5, "mass"))
    assert r.validate(rec, known_slots=["slot:0", "slot:1"]) == []
    out, diags = r.assess(rec, known_slots=["slot:0", "slot:1"])
    assert out is rec and diags == [] and out.execution_supported is True


def test_missing_component_slot():
    rec = recipe(("slot:0", 1.0, "mass"), ("slot:5", 1.0, "mass"))
    found = [d for d in r.validate(rec, known_slots=["slot:0", "slot:1"]) if d.code == "missing_component"]
    assert [d.field for d in found] == ["components[1]"]


def test_missing_recipe_component_needs_recipe_table():
    rec = recipe(("recipe:other", 1.0, "mass"))
    assert "missing_component" not in codes(r.validate(rec))                 # nothing to check against
    assert "missing_component" in codes(r.validate(rec, recipes={}))


def test_recipe_cycle_direct_and_indirect():
    a = recipe(("recipe:b", 1.0, "mass"), rid="a")
    b = recipe(("recipe:c", 1.0, "mass"), rid="b")
    c = recipe(("recipe:a", 1.0, "mass"), rid="c")
    table = {"a": a, "b": b, "c": c}
    for x in (a, b, c):
        assert "recipe_cycle" in codes(r.validate(x, recipes=table))
    selfie = recipe(("recipe:s", 1.0, "mass"), rid="s")
    assert "recipe_cycle" in codes(r.validate(selfie, recipes={"s": selfie}))
    assert "recipe_cycle" in codes(r.validate(selfie))                       # also without a table


def test_diamond_reference_is_not_a_cycle():
    top = recipe(("recipe:l", 1.0, "mass"), ("recipe:r", 1.0, "mass"), rid="top")
    left = recipe(("recipe:leaf", 1.0, "mass"), rid="l")
    right = recipe(("recipe:leaf", 1.0, "mass"), rid="r")
    leaf = recipe(("slot:0", 1.0, "mass"), rid="leaf")
    table = {x.recipe_id: x for x in (top, left, right, leaf)}
    assert "recipe_cycle" not in codes(r.validate(top, recipes=table, known_slots=["slot:0"]))


@pytest.mark.parametrize("ratio,code", [(-0.1, "negative_ratio"), (float("nan"), "non_finite_ratio"),
                                        (float("inf"), "non_finite_ratio")])
def test_invalid_ratio_values(ratio, code):
    assert code in codes(r.validate(recipe(("slot:0", ratio, "mass"))))


def test_zero_and_none_ratio_are_not_errors():
    assert codes(r.validate(recipe(("slot:0", 0.0, "mass"), ("slot:1", None, "mass")))) == set()


def test_bad_ratio_in_document_is_dropped_with_warning_not_read_as_number():
    raw = load("virtual_recipe")
    raw["components"][0]["ratio"] = "lots"
    dec = r.VirtualRecipe.from_dict(raw)
    assert dec.valid_for_evaluation and "bad_ratio" in codes(dec.diagnostics)
    assert dec.value.components[0].ratio is None
    raw["components"][0]["ratio"] = True
    assert r.VirtualRecipe.from_dict(raw).value.components[0].ratio is None


def test_negative_ratio_survives_decode_and_is_reported_by_validate():
    raw = load("virtual_recipe")
    raw["components"][0]["ratio"] = -2
    value = r.VirtualRecipe.from_dict(raw).value
    assert value.components[0].ratio == -2.0 and "negative_ratio" in codes(r.validate(value))


def test_unknown_ratio_semantics_kept_unknown_never_read_as_mass():
    raw = load("virtual_recipe")
    raw["components"][0]["ratio_kind"] = "volume_fraction_of_a_thing"
    dec = r.VirtualRecipe.from_dict(raw)
    assert "unknown_ratio_kind" in codes(dec.diagnostics)
    comp = dec.value.components[0]
    assert comp.ratio_kind == "unknown" and comp.ratio == 0.6
    out, diags = r.assess(dec.value)
    assert out.execution_supported is False and "unknown_ratio_kind" in codes(diags)
    # Absent ratio_kind is silent in decode but equally unknown for validation.
    del raw["components"][0]["ratio_kind"]
    assert r.VirtualRecipe.from_dict(raw).value.components[0].ratio_kind == "unknown"


def test_unsupported_dialect_preserved_with_execution_unsupported():
    raw = load("virtual_recipe")
    raw["kind"] = "hologram"
    raw["execution_supported"] = True
    dec = r.VirtualRecipe.from_dict(raw)
    assert dec.valid_for_evaluation and "unknown_kind" in codes(dec.diagnostics)
    assert dec.value.kind == "unknown" and len(dec.value.components) == 2        # nothing dropped
    out, diags = r.assess(dec.value)
    assert "unsupported_dialect" in codes(diags)
    assert out.execution_supported is False
    assert out.to_dict()["components"] == dec.value.to_dict()["components"]
    assert out.recipe_id == dec.value.recipe_id and out is not dec.value
    assert dec.value.execution_supported is True                                # input untouched


def test_assess_blocks_on_errors_but_keeps_recipe():
    rec = recipe(("slot:9", 1.0, "mass"))
    out, diags = r.assess(rec, known_slots=["slot:0"])
    assert out.execution_supported is False and "missing_component" in codes(diags)
    assert out.components[0].slot_ref == "slot:9"


def test_no_components_and_duplicates_and_unknown_slot_ref():
    assert "no_components" in codes(r.validate(recipe()))
    assert "duplicate_component" in codes(r.validate(recipe(("slot:0", 1, "mass"), ("slot:0", 1, "mass"))))
    assert "unknown_slot_ref" in codes(r.validate(recipe(("garbage", 1, "mass"))))


def test_project_refs_zero_and_one_based():
    rec = recipe(("project:0:2", 1, "mass"), ("project:1:3", 1, "mass"))
    assert r.validate(rec, known_slots=["slot:2"]) == []
    # project:0:2 and project:1:3 both mean slot:2.
    assert r.physical_inputs(rec, [SlotBinding("slot:2", "head:0")]) == {"slot_ids": ["slot:2"], "count": 1}
    # project:1:0 would be slot:-1: not a valid reference.
    assert "unknown_slot_ref" in codes(r.validate(recipe(("project:1:0", 1, "mass"))))


def test_unknown_kind_and_missing_generator_in_document():
    raw = load("virtual_recipe")
    del raw["generator"]
    assert r.VirtualRecipe.from_dict(raw).value is None
    assert r.VirtualRecipe.from_dict(load("unknown_schema_version")).value is None


def test_execution_supported_none_when_absent():
    raw = load("virtual_recipe")
    del raw["execution_supported"]
    assert r.VirtualRecipe.from_dict(raw).value.execution_supported is None


# -- physical_inputs ------------------------------------------------------------
def test_physical_inputs_counts_distinct_targets_not_components():
    rec = recipe(("slot:0", 1, "mass"), ("slot:1", 1, "mass"), ("slot:2", 1, "mass"))
    bindings = [SlotBinding("slot:0", "head:0"), SlotBinding("slot:1", "head:0"), SlotBinding("slot:2", "head:1")]
    assert r.physical_inputs(rec, bindings) == {"slot_ids": ["slot:0", "slot:1", "slot:2"], "count": 2}


def test_physical_inputs_unknown_when_unbound_contradictory_or_nested():
    rec = recipe(("slot:0", 1, "mass"), ("slot:1", 1, "mass"))
    assert r.physical_inputs(rec, [SlotBinding("slot:0", "head:0")])["count"] is None
    clash = [SlotBinding("slot:0", "head:0"), SlotBinding("slot:0", "head:1"), SlotBinding("slot:1", "head:1")]
    assert r.physical_inputs(rec, clash)["count"] is None
    nested = recipe(("slot:0", 1, "mass"), ("recipe:x", 1, "mass"))
    assert r.physical_inputs(nested, [SlotBinding("slot:0", "head:0")])["count"] is None
    assert r.physical_inputs(recipe(), [])["count"] == 0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True, False, "0.5", 10 ** 400, [0.5], {"a": 1}])
def test_decoded_invalid_ratio_keeps_the_recipe_but_loses_execution_approval(bad):
    raw = load("virtual_recipe")
    raw["execution_supported"] = True
    raw["components"][0]["ratio"] = bad
    dec = r.VirtualRecipe.from_dict(raw)
    assert dec.value is not None                                  # preserved, not dropped
    assert dec.value.components[0].ratio is None and dec.value.components[0].ratio_invalid is True
    assert dec.value.execution_supported is True                  # decode does not decide; assess does
    assessed, diags = r.assess(dec.value)
    assert assessed.execution_supported is False
    assert "non_finite_ratio" in codes(diags)
    assert assessed.components[0].ratio_invalid is True
    assert assessed.to_dict()["components"][0]["ratio_invalid"] is True
    again = r.VirtualRecipe.from_dict(json.loads(json.dumps(assessed.to_dict())))
    assert r.assess(again.value)[0].execution_supported is False   # still withdrawn after a round trip
