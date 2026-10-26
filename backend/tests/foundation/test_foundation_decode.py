"""Decoded / Reader: external data never raises and never yields a half-trusted value."""
import json

import pytest

from snapstudio_core.foundation import decode as d

SV = "demo/1"


@pytest.mark.parametrize("parts,extra", [
    ({"revision": "caller"}, None),
    ({"stable": 1}, {"stable": 2}),
    ({"stable": 1}, {"revision": "caller"}),
])
def test_revision_envelope_rejects_replacement_fields(parts, extra):
    with pytest.raises(ValueError, match="revision fields cannot be replaced"):
        d.revision_envelope(parts, extra)


def build(r):
    name = r.string("name")
    count = r.integer("count", minimum=0)
    return {"name": name, "count": count, "tags": r.string_list("tags"), "kind": r.enum("kind", ("a", "b"), required=False)}


def decode(raw):
    return d.decode_document(raw, SV, build)


GOOD = {"schema_version": SV, "name": "x", "count": 2}


def test_valid_document_decodes():
    out = decode(GOOD)
    assert out.value == {"name": "x", "count": 2, "tags": [], "kind": None}
    assert out.valid_for_evaluation is True
    assert out.schema_version == SV
    assert out.diagnostics == []
    assert out.raw is None


def test_valid_document_from_json_text_and_bytes():
    assert decode(json.dumps(GOOD)).valid_for_evaluation
    assert decode(json.dumps(GOOD).encode()).valid_for_evaluation


@pytest.mark.parametrize("raw", ["{not json", b"\xff\xfe\x00", "", "[1,2]", "42", "null", None, 7, [1], 1.5])
def test_malformed_or_non_object_never_raises(raw):
    out = decode(raw)
    assert out.value is None
    assert out.valid_for_evaluation is False
    assert d.has_error(out.diagnostics)
    assert out.diagnostics


def test_deeply_nested_json_does_not_raise():
    out = decode("[" * 100000 + "]" * 100000)
    assert out.value is None and out.valid_for_evaluation is False


@pytest.mark.parametrize("patch,code,field", [
    ({"name": 5}, "wrong_type", "name"),
    ({"name": "  "}, "wrong_type", "name"),
    ({"count": "2"}, "wrong_type", "count"),
    ({"count": True}, "wrong_type", "count"),
    ({"count": 2.0}, "wrong_type", "count"),
    ({"count": -1}, "out_of_range", "count"),
    ({"tags": "abc"}, "wrong_type", "tags"),
    ({"tags": ["ok", 3]}, "wrong_type", "tags[1]"),
    ({"kind": "z"}, "bad_enum", "kind"),
    ({"kind": 3}, "bad_enum", "kind"),
])
def test_wrong_types_give_named_diagnostic_and_no_value(patch, code, field):
    out = decode({**GOOD, **patch})
    assert out.value is None
    assert out.valid_for_evaluation is False
    assert any(x.code == code and x.field == field and x.severity == d.ERROR for x in out.diagnostics)
    assert out.raw is not None


def test_missing_required_fields():
    out = decode({"schema_version": SV})
    assert {(x.code, x.field) for x in out.diagnostics} == {("missing_field", "name"), ("missing_field", "count")}
    assert out.value is None


def test_null_required_counts_as_missing_and_null_optional_as_absent():
    out = decode({**GOOD, "name": None})
    assert out.value is None
    ok = decode({**GOOD, "kind": None, "tags": None})
    assert ok.value["kind"] is None and ok.value["tags"] == []


def test_unknown_schema_version_preserves_raw_and_is_not_evaluated():
    raw = {"schema_version": "demo/99", "name": "x", "count": 1, "future": {"a": [1]}}
    out = decode(raw)
    assert out.value is None
    assert out.valid_for_evaluation is False
    assert out.schema_version == "demo/99"
    assert out.raw == raw
    assert [x.code for x in out.diagnostics] == ["unknown_schema_version"]


def test_unknown_schema_version_from_text_keeps_content():
    out = decode(json.dumps({"schema_version": "demo/2", "x": 1}))
    assert out.raw == {"schema_version": "demo/2", "x": 1}
    assert out.value is None


def test_missing_schema_version():
    out = decode({"name": "x", "count": 1})
    assert [x.code for x in out.diagnostics] == ["missing_schema_version"]
    assert out.schema_version is None and out.value is None and out.raw == {"name": "x", "count": 1}


def test_non_string_schema_version_is_unknown_not_a_crash():
    out = decode({"schema_version": 3, "name": "x", "count": 1})
    assert out.schema_version is None
    assert out.value is None and d.has_error(out.diagnostics)


def test_malformed_text_keeps_original_text_opaque():
    out = decode(b"{oops")
    assert out.raw == "{oops"


def test_builder_defect_is_a_diagnostic_not_an_exception():
    def bad(r):
        raise KeyError("boom")

    out = d.decode_document(GOOD, SV, bad)
    assert out.value is None and out.valid_for_evaluation is False
    assert [x.code for x in out.diagnostics] == ["decode_failed"]


def test_programming_errors_still_raise():
    def bad(r):
        raise RuntimeError("our bug")

    with pytest.raises(RuntimeError):
        d.decode_document(GOOD, SV, bad)


def test_warning_does_not_invalidate():
    def warn(r):
        r.warn("odd", "name")
        return 1

    out = d.decode_document(GOOD, SV, warn)
    assert out.value == 1 and out.valid_for_evaluation is True
    assert out.diagnostics[0].severity == d.WARNING


def test_nested_reader_paths():
    def nested(r):
        child = r.child(r.mapping("inner", required=True), "inner")
        child.string("a")
        return 1

    out = d.decode_document({"schema_version": SV, "inner": {}}, SV, nested)
    assert [(x.code, x.field) for x in out.diagnostics] == [("missing_field", "inner.a")]
    out = d.decode_document({"schema_version": SV, "inner": [1]}, SV, nested)
    assert out.diagnostics[0].field == "inner"


@pytest.mark.parametrize("value,expected", [
    (1, True), (1.5, True), (0, True), (-3, True),
    (True, False), (False, False), (float("nan"), False), (float("inf"), False), (float("-inf"), False),
    ("1", False), (None, False), ([], False),
])
def test_is_finite_number(value, expected):
    assert d.is_finite_number(value) is expected


def test_number_rejects_non_finite_and_bool():
    for bad in (float("nan"), float("inf"), True, "3"):
        r = d.Reader({"n": bad})
        assert r.number("n") is None
        assert d.has_error(r.diagnostics)
    r = d.Reader({"n": 3})
    assert r.number("n") == 3.0 and r.diagnostics == []


def test_optional_string_list_distinguishes_unknown_from_empty():
    assert d.Reader({}).optional_string_list("x") is None
    assert d.Reader({"x": None}).optional_string_list("x") is None
    assert d.Reader({"x": []}).optional_string_list("x") == []
    assert d.Reader({"x": ["a"]}).optional_string_list("x") == ["a"]


def test_boolean_strict():
    r = d.Reader({"b": 1})
    assert r.boolean("b") is None and d.has_error(r.diagnostics)
    assert d.Reader({"b": True}).boolean("b") is True


def test_diagnostic_rejects_unknown_severity_and_serialises():
    with pytest.raises(ValueError):
        d.Diagnostic("c", "f", "fatal")
    assert d.diag("c", "f", d.NOTE).to_dict() == {"code": "c", "field": "f", "severity": "note"}


def test_decoded_to_dict_is_json_safe():
    out = decode({"schema_version": "demo/9", "z": 1})
    text = json.dumps(out.to_dict())
    assert json.loads(text)["valid_for_evaluation"] is False
    assert json.loads(text)["raw"] == {"schema_version": "demo/9", "z": 1}


def test_parse_json_never_raises():
    assert d.parse_json("{bad").diagnostics[0].code == "malformed_json"
    assert d.parse_json(b"\xff").diagnostics[0].code == "malformed_json"
    assert d.parse_json('{"a": 1}').value == {"a": 1}


# -- oversized JSON integers (R9) -------------------------------------------------
HUGE = 10 ** 400


def test_huge_integers_do_not_escape_the_number_helpers():
    assert d.is_finite_number(HUGE) is False
    assert d.is_finite_number(-HUGE) is False
    reader = d.Reader({"x": HUGE})
    assert reader.number("x") is None
    assert [x.code for x in reader.diagnostics] == ["wrong_type"]


def test_huge_integer_in_a_builder_that_overflows_is_a_diagnostic_not_an_exception():
    def overflowing(r):
        return float(r.raw["n"])

    out = d.decode_document({"schema_version": SV, "n": HUGE}, SV, overflowing)
    assert out.value is None and out.diagnostics[0].code == "decode_failed"


def _fixture_classes():
    from snapstudio_core.foundation import artifacts, capabilities, materials, observations, recipes, topology
    return {"artifact_ref.json": artifacts.ArtifactRef.from_dict, "derivation.json": artifacts.Derivation.from_dict,
            "capability_set.json": capabilities.CapabilitySet.from_dict, "material_view.json": materials.MaterialView.from_dict,
            "observation.json": observations.Observation.from_dict, "topology.json": topology.Topology.from_dict,
            "virtual_recipe.json": recipes.VirtualRecipe.from_dict}


def _numeric_paths(node, prefix=()):
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        yield prefix
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _numeric_paths(v, prefix + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _numeric_paths(v, prefix + (i,))


def _with(node, path, value):
    import copy
    out = copy.deepcopy(node)
    cur = out
    for key in path[:-1]:
        cur = cur[key]
    cur[path[-1]] = value
    return out


def test_every_numeric_field_of_every_document_survives_oversized_integers():
    import os
    base = os.path.join(os.path.dirname(__file__), "fixtures")
    checked = 0
    for name, decode_fn in _fixture_classes().items():
        doc = json.load(open(os.path.join(base, name), encoding="utf-8"))
        for path in _numeric_paths(doc):
            for big in (HUGE, -HUGE, 10 ** 309):
                mutated = _with(doc, path, big)
                for raw in (mutated, json.dumps(mutated)):
                    out = decode_fn(raw)                   # must not raise
                    assert out.value is None or out.diagnostics is not None
                checked += 1
    assert checked > 10


def test_oversized_ttl_and_ratio_are_rejected_not_raised():
    from snapstudio_core.foundation import observations, recipes
    import os
    base = os.path.join(os.path.dirname(__file__), "fixtures")
    obs = json.load(open(os.path.join(base, "observation.json"), encoding="utf-8"))
    out = observations.Observation.from_dict({**obs, "ttl_s": HUGE})
    assert out.value is None and any(x.code in ("wrong_type", "ttl_invalid") for x in out.diagnostics)
    rec = json.load(open(os.path.join(base, "virtual_recipe.json"), encoding="utf-8"))
    rec["execution_supported"] = True
    rec["components"][0]["ratio"] = HUGE
    decoded = recipes.VirtualRecipe.from_dict(rec)
    assert decoded.value is not None and decoded.value.components[0].ratio_invalid is True
    assessed, diags = recipes.assess(decoded.value)
    assert assessed.execution_supported is False
    assert any(x.code == "non_finite_ratio" for x in diags)
