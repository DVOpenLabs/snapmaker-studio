"""Capabilities: scoped evidence, conflicts, alternatives, calibration-basis scope."""
import json
import os

import pytest

from snapstudio_core.foundation import capabilities as c

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIX, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def cset(*caps):
    s = c.CapabilitySet()
    for cap in caps:
        s.add(cap)
    return s


def result(reqs, s, **scope):
    return [x["result"] for x in c.evaluate(reqs, s, scope=scope or None)]


def test_fixture_round_trips():
    raw = load("capability_set")
    dec = c.CapabilitySet.from_dict(raw)
    assert dec.valid_for_evaluation and dec.diagnostics == []
    assert dec.value.to_dict() == raw


def test_revision_extra_cannot_replace_capability_set():
    with pytest.raises(ValueError, match="capability_set"):
        c.evaluate([], c.CapabilitySet(), revisions={"capability_set": "fixed"})


def test_unknown_schema_version_preserved_not_evaluated():
    raw = load("unknown_schema_version")
    dec = c.CapabilitySet.from_dict(raw)
    assert dec.value is None and dec.raw == raw and not dec.valid_for_evaluation


def test_missing_key_is_unknown_never_unsupported():
    assert result([c.Requirement("multi_head")], c.CapabilitySet()) == ["unknown"]
    assert result([c.Requirement("multi_head")], cset(c.Capability("other", "supported"))) == ["unknown"]


def test_supported_and_unsupported_unscoped():
    s = cset(c.Capability("a", "supported", evidence=["e1"]), c.Capability("b", "unsupported", evidence=["e2"]))
    out = c.evaluate([c.Requirement("a"), c.Requirement("b")], s)
    assert [x["result"] for x in out] == ["satisfied", "unmet"]
    assert out[0]["evidence"] == ["e1"] and out[1]["matched"].key == "b"


def test_explicit_unknown_state_is_unknown_with_evidence():
    out = c.evaluate([c.Requirement("a")], cset(c.Capability("a", "unknown", evidence=["why"])))
    assert out[0]["result"] == "unknown" and out[0]["evidence"] == ["why"]


def test_conflicting_evidence_is_unknown_and_keeps_both_pieces():
    s = cset(c.Capability("a", "supported", evidence=["says yes"]),
             c.Capability("a", "unsupported", evidence=["says no"]))
    out = c.evaluate([c.Requirement("a")], s)
    assert out[0]["result"] == "unknown" and out[0]["matched"] is None
    assert out[0]["evidence"] == ["says yes", "says no"]
    declared = cset(c.Capability("a", "conflicting", evidence=["x"]), c.Capability("a", "supported"))
    assert result([c.Requirement("a")], declared) == ["unknown"]


def test_scope_must_match_context():
    s = cset(c.Capability("a", "supported", {"slicer": "orca", "version": "2.3"}))
    assert result([c.Requirement("a")], s, slicer="orca", version="2.3") == ["satisfied"]
    assert result([c.Requirement("a")], s, slicer="orca", version="2.4") == ["unknown"]
    assert result([c.Requirement("a")], s, slicer="other", version="2.3") == ["unknown"]
    assert result([c.Requirement("a")], s) == ["unknown"]                   # context does not say


def test_unscoped_capability_applies_everywhere():
    s = cset(c.Capability("a", "unsupported"))
    assert result([c.Requirement("a")], s, host="h1", slicer="s") == ["unmet"]


def test_scoped_evidence_from_different_scopes_does_not_conflict():
    s = cset(c.Capability("a", "supported", {"host": "h1"}), c.Capability("a", "unsupported", {"host": "h2"}))
    assert result([c.Requirement("a")], s, host="h1") == ["satisfied"]
    assert result([c.Requirement("a")], s, host="h2") == ["unmet"]
    assert result([c.Requirement("a")], s, host="h3") == ["unknown"]


def test_calibration_basis_change_gives_non_pass():
    s = cset(c.Capability("lut_colour_match", "supported", {"process": "basis-A"}, ["measured under A"]))
    assert result([c.Requirement("lut_colour_match")], s, process="basis-A") == ["satisfied"]
    after = result([c.Requirement("lut_colour_match")], s, process="basis-B")
    assert after == ["unknown"] and after != ["satisfied"]
    # Even a previously 'unsupported' under A does not turn into 'unmet' under B.
    neg = cset(c.Capability("lut_colour_match", "unsupported", {"process": "basis-A"}))
    assert result([c.Requirement("lut_colour_match")], neg, process="basis-B") == ["unknown"]


def test_fixture_scoped_lut_capability_unknown_under_other_basis():
    s = c.CapabilitySet.from_dict(load("capability_set")).value
    assert result([c.Requirement("lut")], s, process="basis-A") == ["unmet"]
    assert result([c.Requirement("lut")], s, process="basis-B") == ["unknown"]


def test_alternatives_any_satisfying_option_wins():
    s = cset(c.Capability("a", "unsupported"), c.Capability("b", "supported", evidence=["ok"]))
    req = c.Requirement("a", alternatives=[c.Requirement("b")], source="gen")
    out = c.evaluate([req], s)
    assert out[0]["result"] == "satisfied" and out[0]["key"] == "a" and out[0]["evidence"] == ["ok"]


def test_alternatives_unknown_beats_unmet_and_all_unmet_is_unmet():
    s = cset(c.Capability("a", "unsupported", evidence=["no a"]), c.Capability("b", "unsupported", evidence=["no b"]))
    both = c.Requirement("a", alternatives=[c.Requirement("b")])
    out = c.evaluate([both], s)[0]
    assert out["result"] == "unmet" and out["evidence"] == ["no a", "no b"]
    with_unknown = c.Requirement("a", alternatives=[c.Requirement("zzz")])
    assert result([with_unknown], s) == ["unknown"]


def test_params_are_carried_not_matched():
    s = cset(c.Capability("a", "supported"))
    req = c.Requirement("a", params={"heads": 4})
    assert result([req], s) == ["satisfied"]
    assert req.to_dict()["params"] == {"heads": 4}


def test_evaluation_order_and_serialisation():
    s = cset(c.Capability("a", "supported"))
    out = c.evaluate([c.Requirement("a"), c.Requirement("z")], s)
    assert [x["key"] for x in out] == ["a", "z"]
    ser = c.evaluation_to_dict(out)
    assert ser[0]["matched"]["state"] == "supported" and ser[1]["matched"] is None
    json.dumps(ser)


def test_invalid_state_raises_programming_error_but_document_does_not():
    with pytest.raises(ValueError):
        c.Capability("a", "maybe")
    raw = load("capability_set")
    raw["capabilities"]["multi_head"][0]["state"] = "maybe"
    dec = c.CapabilitySet.from_dict(raw)
    assert dec.value is None and "bad_enum" in {d.code for d in dec.diagnostics}


def test_bad_scope_key_or_type_in_document_is_error():
    raw = load("capability_set")
    raw["capabilities"]["multi_head"][0]["scope"]["colour"] = "red"
    assert c.CapabilitySet.from_dict(raw).value is None
    raw = load("capability_set")
    raw["capabilities"]["multi_head"][0]["scope"]["slicer"] = 5
    assert c.CapabilitySet.from_dict(raw).value is None
    raw = load("capability_set")
    raw["capabilities"]["multi_head"] = "nope"
    assert c.CapabilitySet.from_dict(raw).value is None


def test_non_string_scope_values_are_normalised_to_unscoped_in_python_api():
    cap = c.Capability("a", "supported", {"host": 5, "bogus": "x"})
    assert cap.scope == {"host": None, "slicer": None, "generator": None, "version": None, "process": None}


# -- inputs_revision envelope (R10) -----------------------------------------------
def test_evaluation_carries_and_serialises_inputs_revision():
    s = cset(c.Capability("a", "supported", {"host": "h1"}, ["e1"]))
    out = c.evaluate([c.Requirement("a")], s, scope={"host": "h1"}, revisions={"calibration_revision": "c1"})
    env = out.inputs_revision
    assert env["revision"].startswith("sha256:") and env["calibration_revision"] == "c1"
    doc = c.evaluation_to_document(out)
    assert doc["inputs_revision"] == env and doc["results"][0]["result"] == "satisfied"
    assert json.loads(json.dumps(doc)) == doc


def test_changed_capabilities_requirements_scope_or_revisions_change_the_revision():
    def rev(s, reqs=None, scope=None, **revisions):
        return c.evaluate(reqs or [c.Requirement("a")], s, scope=scope, revisions=revisions or None).inputs_revision["revision"]
    s1 = cset(c.Capability("a", "supported", {"host": "h1"}, ["e1"]))
    base = rev(s1, scope={"host": "h1"})
    assert rev(s1, scope={"host": "h1"}) == base
    assert rev(cset(c.Capability("a", "unsupported", {"host": "h1"}, ["e1"])), scope={"host": "h1"}) != base
    assert rev(s1, scope={"host": "h2"}) != base
    assert rev(s1, [c.Requirement("b")], scope={"host": "h1"}) != base
    assert rev(s1, scope={"host": "h1"}, observation_revision="o2") != base
