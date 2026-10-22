"""Scale Doctor — size-options ladder. Analysis-only; writes nothing.

build_item_dims is monkeypatched so these are hermetic (no real 3MF needed). The
real motivating file (contenitore+2+v1) was validated manually to produce
128 / 130 / 134 / 134.3% with matching per-plate dimensions.
"""
import os

from snapstudio_core import scale_doctor as sd

P1 = {"x": 200.93, "y": 200.93, "z": 117.28}
P2 = {"x": 191.99, "y": 192.00, "z": 22.00}


def _patch(monkeypatch, parts):
    monkeypatch.setattr(sd, "build_item_dims",
                        lambda path: [{"object_id": str(i + 1), "dimensions": d} for i, d in enumerate(parts)])
    monkeypatch.setattr(sd, "_plate_map", lambda path: {})
    # these tests use a path that is not a real file; its geometry basis is covered in
    # test_geometry_verdict.py, so treat the size as established here
    monkeypatch.setattr(sd.geometry_basis, "assess", lambda path: {"established": True})


def test_theoretical_max_about_134(monkeypatch):
    _patch(monkeypatch, [P1])
    r = sd.scale_options("x.3mf")
    assert r["available"]
    absolute = r["options"][-1]
    assert 134.0 <= absolute["scale_percent"] <= 134.5   # 270/200.93 ~ 134.4


def test_safe_novice_max_about_128(monkeypatch):
    _patch(monkeypatch, [P1])
    r = sd.scale_options("x.3mf", margin_mm=5)
    assert r["recommended_scale_percent"] == r["options"][0]["scale_percent"]
    assert 126 <= r["recommended_scale_percent"] <= 129


def test_multi_plate_uses_most_limiting(monkeypatch):
    _patch(monkeypatch, [P1, P2])
    r = sd.scale_options("x.3mf")
    assert r["group_scaling_recommended"] is True
    # limiting is the larger plate (P1), so recommended scale is driven by it
    assert 126 <= r["recommended_scale_percent"] <= 129
    assert len(r["current_parts"]) == 2


def test_dimensions_computed_per_option(monkeypatch):
    _patch(monkeypatch, [P1, P2])
    r = sd.scale_options("x.3mf")
    safe = r["options"][0]
    pct = safe["scale_percent"] / 100.0
    row1 = safe["dimensions_by_part"][0]["dimensions"]
    assert abs(row1["x"] - round(P1["x"] * pct, 1)) < 0.05
    assert abs(row1["z"] - round(P1["z"] * pct, 1)) < 0.05


def test_absolute_option_not_recommended(monkeypatch):
    _patch(monkeypatch, [P1])
    r = sd.scale_options("x.3mf")
    absolute = r["options"][-1]
    assert "not recommended" in absolute["label"].lower()
    assert absolute["recommendation"] == "Not recommended"
    assert absolute["risk_level"] == "high"


def test_height_limited_uses_z_axis(monkeypatch):
    _patch(monkeypatch, [{"x": 50.0, "y": 50.0, "z": 260.0}])
    r = sd.scale_options("x.3mf")
    assert r["limiting_axis"] == "z"


def test_degenerate_dims_do_not_crash(monkeypatch):
    _patch(monkeypatch, [{"x": 0.0, "y": 0.0, "z": 0.0}])
    r = sd.scale_options("x.3mf")
    assert r["available"] is False


def test_no_file_writes(monkeypatch, tmp_path):
    _patch(monkeypatch, [P1, P2])
    before = sorted(os.listdir(tmp_path))
    sd.scale_options(str(tmp_path / "nope.3mf"))
    assert sorted(os.listdir(tmp_path)) == before


def test_no_guarantee_language(monkeypatch):
    _patch(monkeypatch, [P1])
    r = sd.scale_options("x.3mf")
    blob = " ".join(r["warnings"] + r["next_steps"]).lower()
    for o in r["options"]:
        blob += " " + o["explanation"].lower()
    assert "guarantee of print success" in " ".join(r["warnings"]).lower()
    assert "guaranteed" not in blob
