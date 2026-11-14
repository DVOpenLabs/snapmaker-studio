import json
import pytest
from snapstudio_core.calibration import palette, service

def test_upstream_ditherforge_numeric_td_and_comments():
    result = palette.parse_ditherforge("# Collection comment\n#FF0000 1.9 Red\n#00FF00 0.4 Green\n#0000FF Blue")
    assert result.valid_for_evaluation
    assert [(e.label,e.td,e.td_provenance) for e in result.value.entries] == [
        ("Red",1.9,"provided"),("Green",0.4,"provided"),("Blue",1.0,"derived")]

@pytest.mark.parametrize("td", ["0", "-1", "1e999"])
def test_numeric_td_must_be_positive_finite(td):
    assert palette.parse_ditherforge(f"#FF0000 {td} Red").value is None

def test_kromacut_exported_v2_colors_names_and_disabled_indices():
    raw = {"version":2,"name":"Synthetic palette","colors":["#FF0000","#00FF00"],
           "colorNames":["Red","Green"],"disabledColors":[1],"createdAt":1,"updatedAt":1}
    result=palette.parse_kromacut(json.dumps(raw))
    assert result.valid_for_evaluation
    assert [e.color for e in result.value.entries] == ["#FF0000","#00FF00"]
    assert [e.label for e in result.value.entries] == ["Red","Green"]
    assert [e.enabled for e in result.value.entries] == [True,False]
    assert all(e.td_provenance=="derived" for e in result.value.entries)

@pytest.mark.parametrize("changes", [
    {"colors":["not-a-colour"]},{"disabledColors":[9]},{"disabledColors":[True]},
    {"colorNames":"not-an-array"}])
def test_invalid_kpal_metadata_is_refused(changes):
    raw={"version":2,"colors":["#FF0000"],"colorNames":["Red"],"disabledColors":[]}
    assert palette.parse_kromacut({**raw,**changes}).value is None

def test_basis_distinguishes_generator_model_and_first_layer():
    common=("frontlit",0.2,0.4,"PLA")
    a=service.basis_document(*common,source="ditherforge_txt",model="swatch-A",first_layer_height_mm=0.2)
    for changes in [dict(source="kromacut_json"),dict(model="swatch-B"),dict(first_layer_height_mm=0.3)]:
        b=service.basis_document(*common,**{**dict(source="ditherforge_txt",model="swatch-A",first_layer_height_mm=0.2),**changes})
        assert a["calibration_basis_id"] != b["calibration_basis_id"]

def test_disabled_color_keeps_its_index_without_claiming_a_physical_reading():
    from snapstudio_core.calibration.service import evaluate
    parsed = palette.parse_kromacut({"version": 2, "colors": ["#112233", "#445566"], "disabledColors": [0]}).value.to_dict()
    result = evaluate(parsed, service.basis_document("frontlit", .2, .4, "PLA"), {"0": "#aaaaaa", "1": "#bbbbbb"}, [])
    assert result["entries"][0]["enabled"] is False
    assert result["entries"][0]["physical_color"] is None
    assert result["entries"][1]["physical_color"] == "#bbbbbb"

def test_route_persists_basis_identity_and_real_kpal_rows(tmp_path, monkeypatch):
    from snapstudio_api.routes_calibration import evaluate, get_history
    import json
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path))
    code, body = evaluate({"source": "kromacut_json", "content": json.dumps({"version": 2, "colors": ["#123456"]}),
        "family": "backlit", "layer_height_mm": .16, "nozzle_mm": .6, "material": "PETG", "model": "synthetic-swatch-2", "first_layer_height_mm": .24})
    assert code == 200 and body["status"] == "evaluated"
    basis = body["result"]["calibration_basis"]
    assert basis["source"] == "kromacut_json" and basis["model"] == "synthetic-swatch-2"
    assert basis["first_layer_height_mm"] == .24 and basis["nozzle_mm"] == .6
    assert get_history({})[1]["runs"][0]["calibration_basis"] == basis

@pytest.mark.parametrize("row", ["#FF0000 td=oops Red", "#FF0000 td=1.2junk Red", "#FF0000 1.9 Red td=1..2", "#FF0000 1.9 Red td=2"])
def test_invalid_or_conflicting_td_does_not_fall_back_to_nominal(row):
    assert palette.parse_ditherforge(row).value is None

@pytest.mark.parametrize("row", ["#FF0000 1.9 Red td=1.9 td=2", "#FF0000 td=1.9 Red td=oops", "#FF0000 td 1.9 Red td=2", "#FF0000 td=1.9 td=1.9"])
def test_all_explicit_td_values_are_validated(row):
    assert palette.parse_ditherforge(row).value is None

@pytest.mark.parametrize("material", ["", "   "])
def test_empty_material_is_not_silently_replaced_with_pla(tmp_path, monkeypatch, material):
    from snapstudio_api.routes_calibration import evaluate
    from snapstudio_api.request_validation import ValidationError
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path))
    with pytest.raises(ValidationError):
        evaluate({"source":"ditherforge_txt", "content":"#FF0000 Red", "family":"frontlit", "layer_height_mm":.2, "material": material})
