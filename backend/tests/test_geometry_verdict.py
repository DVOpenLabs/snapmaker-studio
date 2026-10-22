"""A size-dependent verdict is given only when the model's physical size is established.

A 3MF can declare a unit other than millimetres, and can place its meshes through rotations or
scales that Studio's raw-mesh measurement ignores. Bed fit, the readiness "fits" check, the
print-success estimate, first-layer footprint checks and the Scale Doctor must then say "not
checked" with the SAME reason, never "fits" / "ready" / "likely". Valid millimetre files, and
identity / translation / mirror placements, keep their verdicts.

Every test goes through the real service functions (the same ones the HTTP routes call).
Fixtures are synthetic 10 x 20 x 30 boxes written in a temp dir.
"""
from __future__ import annotations

import json
import struct
import zipfile

import pytest

from snapstudio_api import service
from snapstudio_core import geometry_basis, intelligence_report, success_predict
from snapstudio_core.validation_report import readiness_report

_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
_V = [(0, 0, 0), (10, 0, 0), (10, 20, 0), (0, 20, 0), (0, 0, 30), (10, 0, 30), (10, 20, 30), (0, 20, 30)]
_F = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
      (2, 3, 7), (2, 7, 6), (1, 2, 6), (1, 6, 5), (3, 0, 4), (3, 4, 7)]
_IDENT = "1 0 0 0 1 0 0 0 1 0 0 0"
_SCALE20 = "20 0 0 0 20 0 0 0 20 0 0 0"
_SCALE6 = "6 0 0 0 6 0 0 0 6 0 0 0"
_ROT_X90 = "1 0 0 0 0 1 0 -1 0 0 0 0"        # 90 degrees about X: swaps the Y and Z extents
_ROT_Z90 = "0 1 0 -1 0 0 0 0 1 0 0 0"
_MIRROR_X = "-1 0 0 0 1 0 0 0 1 0 0 0"
_TRANSLATE = "1 0 0 0 1 0 0 0 1 100 50 0"

_CT = ('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
       '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
_RELS = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
         'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')


def _mesh_xml(oid: int, yxz: bool = False) -> str:
    # yxz: attribute order y,x,z, valid XML that Studio's raw size scan cannot read (dimensions None)
    vs = "".join((f'<vertex y="{y}" x="{x}" z="{z}"/>' if yxz else f'<vertex x="{x}" y="{y}" z="{z}"/>')
                 for x, y, z in _V)
    ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in _F)
    return f'<object id="{oid}" type="model"><mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh></object>'


def _model(body: str, build: str, unit: str | None = "millimeter") -> str:
    u = f' unit="{unit}"' if unit else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?><model{u} xmlns="{_CORE}" xmlns:p="{_PROD}">'
            f'<resources>{body}</resources><build>{build}</build></model>')


def _write(path, parts: dict) -> str:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        for name, text in parts.items():
            z.writestr(name, text)
    return str(path)


def make(tmp_path, name, *, unit="millimeter", items=(("1", _IDENT),), extra_objects="", sub=None, yxz=False):
    """items: [(objectid, transform-or-None)]. Object 1 is the box; `extra_objects` adds more resources."""
    build = "".join(f'<item objectid="{oid}"' + (f' transform="{tf}"' if tf is not None else "") + "/>"
                    for oid, tf in items)
    parts = {"3D/3dmodel.model": _model(_mesh_xml(1, yxz) + extra_objects, build, unit)}
    for k, v in (sub or {}).items():
        parts[k] = v
    return _write(tmp_path / f"{name}.3mf", parts)


def make_stl(tmp_path, name="box.stl"):
    out = bytearray(b"synthetic".ljust(80, b" ")) + struct.pack("<I", len(_F))
    for a, b, c in _F:
        out += struct.pack("<3f", 0, 0, 0)
        for i in (a, b, c):
            out += struct.pack("<3f", *map(float, _V[i]))
        out += b"\0\0"
    p = tmp_path / name
    p.write_bytes(bytes(out))
    return str(p)


def _surfaces(path):
    """Every size-dependent surface, through the service functions."""
    return {
        "insights": service.insights(path),
        "bed_fit": service.bed_fit(path),
        "readiness": readiness_report(path),
        "predict": service.predict_success(path),
        "first_layer": service.first_layer(path),
        "scale_preview": service.scale_preview(path, 150),
        "scale_options": service.scale_options(path),
        "mesh": service.mesh(path),
    }


# --- the controls: valid files keep their verdicts ------------------------------------------


@pytest.mark.parametrize("label,tf", [
    ("no transform", None), ("identity", _IDENT), ("translation only", _TRANSLATE), ("mirror along X", _MIRROR_X),
])
def test_established_cases_keep_every_verdict(tmp_path, label, tf):
    s = _surfaces(make(tmp_path, "ok", items=(("1", tf),)))
    assert s["insights"]["geometry_basis"]["established"] is True, label
    # Bed fit judges size and, separately, where the items sit: a mesh authored at the plate corner (no/identity
    # transform) or mirrored off it is a placement concern, not a change of the size verdict.
    assert s["bed_fit"]["available"] is True and s["bed_fit"]["overall_text"].startswith("By size")
    if label == "translation only":
        assert s["bed_fit"]["overall_level"] == "ok"
    fit = next(c for c in s["readiness"]["checks"] if c["name"] == "Fits the print bed")
    assert fit["status"] == "pass"
    assert isinstance(s["predict"]["likelihood"], int) and s["predict"]["band"] in ("likely", "uncertain", "risky")
    assert s["first_layer"].get("overall_level") in ("ok", "warn", "risk")
    assert s["scale_preview"]["fits_build_volume"] is True
    assert s["scale_options"]["available"] is True
    assert s["mesh"]["geometry_basis"]["established"] is True


def test_stl_stays_established(tmp_path):
    s = _surfaces(make_stl(tmp_path))
    assert s["insights"]["geometry_basis"]["established"] is True
    assert s["bed_fit"]["overall_level"] == "ok"
    assert s["predict"]["likelihood"] is not None


def test_composed_transforms_that_cancel_are_established(tmp_path):
    """Two 90-degree Z rotations (component, then item) compose to a 180-degree turn: extents kept."""
    obj2 = (f'<object id="2" type="model"><components>'
            f'<component objectid="1" transform="{_ROT_Z90}"/></components></object>')
    p = make(tmp_path, "composed", items=(("2", _ROT_Z90),), extra_objects=obj2)
    assert geometry_basis.assess(p)["established"] is True


def test_real_orca_shaped_project_is_established(tmp_path):
    """Root object -> component with p:path into 3D/Objects/*.model, translated build item."""
    sub = {"3D/Objects/object_1.model": _model(_mesh_xml(1), "", "millimeter")}
    root = (f'<object id="2" type="model"><components>'
            f'<component p:path="/3D/Objects/object_1.model" objectid="1" transform="{_IDENT}"/></components></object>')
    parts = {"3D/3dmodel.model": _model(root, f'<item objectid="2" transform="{_TRANSLATE}"/>')}
    parts.update(sub)
    assert geometry_basis.assess(_write(tmp_path / "orca.3mf", parts))["established"] is True


# --- not established: declared unit ------------------------------------------------------


def test_declared_inch_file_is_not_checked_everywhere(tmp_path):
    """Raw 10 x 20 x 30 in an inch file is 254 x 508 x 762 mm: it does NOT fit a 270 mm bed."""
    s = _surfaces(make(tmp_path, "inch", unit="inch"))
    basis = s["insights"]["geometry_basis"]
    assert basis["established"] is False and basis["reasons"] == ["unit_not_millimeter"]
    assert "inch" in basis["summary"]

    assert s["bed_fit"]["available"] is False and s["bed_fit"]["status"] == "not_checked"
    assert "overall_level" not in s["bed_fit"]                      # no ok / warn / risk at all
    fit = next(c for c in s["readiness"]["checks"] if c["name"] == "Fits the print bed")
    assert fit["status"] == "not_checked" and basis["summary"] in fit["detail"]
    assert s["readiness"]["ready"] is False and s["readiness"]["print_setup_ready"] is False
    assert s["predict"]["likelihood"] is None and s["predict"]["band"] == "unknown"
    assert "likely" not in s["predict"]["verdict"].lower().replace("print-success", "")
    assert s["first_layer"]["available"] is False and s["first_layer"]["status"] == "not_checked"
    assert s["scale_preview"]["fits_build_volume"] is None and s["scale_preview"]["recommendation"] == "not checked"
    assert s["scale_options"]["available"] is False and s["scale_options"]["status"] == "not_checked"
    assert s["mesh"]["geometry_basis"]["established"] is False


def test_every_surface_gives_the_same_reason_and_names_its_own_scope(tmp_path):
    s = _surfaces(make(tmp_path, "inch2", unit="inch"))
    reason = s["insights"]["geometry_basis"]["summary"]
    assert reason
    for name in ("bed_fit", "predict", "first_layer", "scale_preview", "scale_options"):
        assert s[name]["reason"] == reason, name
        assert s[name]["geometry_basis"]["reasons"] == ["unit_not_millimeter"], name
    scopes = {s[n]["scope"] for n in ("bed_fit", "predict", "first_layer", "scale_options")}
    assert len(scopes) == 4                                           # each says what IT withheld
    assert set(s["insights"]["geometry_basis"]["withheld"]) >= {"bed fit", "the print-success estimate"}


def test_unit_declared_only_by_a_sub_model_part_is_caught(tmp_path):
    sub = {"3D/Objects/object_1.model": _model(_mesh_xml(1), "", "centimeter")}
    root = ('<object id="2" type="model"><components>'
            '<component p:path="/3D/Objects/object_1.model" objectid="1"/></components></object>')
    parts = {"3D/3dmodel.model": _model(root, '<item objectid="2"/>', "millimeter")}
    parts.update(sub)
    basis = geometry_basis.assess(_write(tmp_path / "subunit.3mf", parts))
    assert basis["established"] is False and basis["reasons"] == ["unit_not_millimeter"]


# --- not established: transforms Studio's measurement ignores ----------------------------


@pytest.mark.parametrize("tf,reason", [
    (_SCALE20, "transform_scaled"), (_SCALE6, "transform_scaled"),
    (_ROT_X90, "transform_rotated"), (_ROT_Z90, "transform_rotated"),
])
def test_scaled_or_rotated_placement_is_not_checked_even_when_it_would_fit(tmp_path, tf, reason):
    """Scale 6 really does fit (60 x 120 x 180) and still is not judged: the measurement ignores it."""
    s = _surfaces(make(tmp_path, "tf", items=(("1", tf),)))
    assert s["insights"]["geometry_basis"]["reasons"] == [reason]
    assert s["bed_fit"]["status"] == "not_checked" and s["predict"]["likelihood"] is None
    assert s["scale_options"]["status"] == "not_checked"
    assert s["scale_preview"]["fits_build_volume"] is None
    assert next(c for c in s["readiness"]["checks"] if c["name"] == "Fits the print bed")["status"] == "not_checked"


def test_build_scaled_item_insights_and_scale_doctor_no_longer_disagree(tmp_path):
    """Before: insights said 10 x 20 x 30 and bed fit "fits", while Scale Doctor placed it at
    200 x 400 x 600. Now neither gives a size-based verdict and both say why."""
    s = _surfaces(make(tmp_path, "scale20", items=(("1", _SCALE20),)))
    assert s["bed_fit"]["status"] == s["scale_options"]["status"] == "not_checked"
    assert s["bed_fit"]["reason"] == s["scale_options"]["reason"]


def test_mixed_objects_cannot_hide_an_unchecked_one(tmp_path):
    """Object 1 is plain; the item for object 3 scales a second copy by 20."""
    obj3 = '<object id="3" type="model"><components><component objectid="1"/></components></object>'
    p = make(tmp_path, "mixed", items=(("1", _IDENT), ("3", _SCALE20)), extra_objects=obj3)
    basis = geometry_basis.assess(p)
    assert basis["established"] is False and basis["reasons"] == ["transform_scaled"]
    assert len(basis["unchecked_objects"]) == 1 and basis["objects_total"] == 2
    assert service.bed_fit(p)["status"] == "not_checked"
    assert "1 of 2" in basis["summary"]


def test_nested_component_scale_is_found(tmp_path):
    inner = '<object id="3" type="model"><components><component objectid="1" transform="%s"/></components></object>' % _SCALE20
    outer = '<object id="4" type="model"><components><component objectid="3"/></components></object>'
    p = make(tmp_path, "nested", items=(("4", _IDENT),), extra_objects=inner + outer)
    assert geometry_basis.assess(p)["reasons"] == ["transform_scaled"]


def test_unreadable_transform_and_broken_references_are_unknown_not_fine(tmp_path):
    bad = make(tmp_path, "badtf", items=(("1", "not numbers"),))
    assert geometry_basis.assess(bad)["reasons"] == ["transform_unreadable"]
    missing = make(tmp_path, "missing", items=(("99", _IDENT),))
    assert geometry_basis.assess(missing)["reasons"] == ["structure_unresolved"]
    loop = ('<object id="5" type="model"><components><component objectid="6"/></components></object>'
            '<object id="6" type="model"><components><component objectid="5"/></components></object>')
    cyc = make(tmp_path, "cycle", items=(("5", _IDENT),), extra_objects=loop)
    assert geometry_basis.assess(cyc)["reasons"] == ["structure_unresolved"]
    assert service.bed_fit(cyc)["status"] == "not_checked"


def test_unreadable_3mf_is_not_established(tmp_path):
    p = tmp_path / "broken.3mf"
    p.write_bytes(b"not a zip")
    assert geometry_basis.assess(str(p))["established"] is False


# --- what stays available / what is never invented -----------------------------------------


def test_unrelated_signals_survive_and_are_not_turned_into_a_probability():
    basis = {"established": False, "reasons": ["unit_not_millimeter"], "summary": "S.", "withheld": [],
             "schema_version": "geometry-basis/1"}
    out = success_predict.predict(readiness={"ready": False, "warnings": ["a"]},
                                  toolfit={"available": True, "overall_level": "risk"},
                                  first_layer={"overall_level": "risk"}, health={"available": True, "score": 40},
                                  prior_failures=2, geometry_basis=basis)
    assert out["likelihood"] is None and out["band"] == "unknown" and out["available"] is True
    assert any("colours than toolheads" in f for f in out["factors"])
    assert any("printer health is low" in f for f in out["factors"])
    assert any("failed 2" in f for f in out["factors"])
    assert not any("first-layer" in f or "validation-ready" in f for f in out["factors"])


def test_mesh_integrity_findings_stay_available_when_size_is_not_established(tmp_path):
    m = service.mesh(make(tmp_path, "inch3", unit="inch"))
    assert m["available"] is True and m["integrity"]["watertight"] is True and "overhang" in m


def test_scale_preview_keeps_the_arithmetic_but_not_the_verdict(tmp_path):
    r = service.scale_preview(make(tmp_path, "inch4", unit="inch"), 150)
    assert r["available"] is True and r["scaled_dimensions"] == {"x": 15.0, "y": 30.0, "z": 45.0}
    assert r["fits_build_volume"] is None
    assert r["risks"][0].startswith("Not checked:")


def test_intelligence_report_does_not_claim_no_blockers(tmp_path):
    rep = service.intelligence_report(make(tmp_path, "inch5", unit="inch"))
    texts = [r["text"] for r in rep.get("risks", [])]
    assert any(t.startswith("Size-based checks not run") for t in texts)
    assert not any("fits" in t.lower() and "bed" in t.lower() and "doesn" not in t.lower() for t in texts)


def test_quality_evidence_drops_raw_footprint_when_size_is_not_established(tmp_path):
    ev = service.quality_check("bed_adhesion", make(tmp_path, "inch6", unit="inch"))
    labels = {e["label"] for e in (ev.get("result") or {}).get("evidence", [])}
    assert "Footprint" not in labels and "Bed fit" not in labels


def test_every_payload_is_json_serialisable(tmp_path):
    json.dumps(_surfaces(make(tmp_path, "inch7", unit="inch")), default=str)


def test_basis_is_cached_per_file_version_and_refreshes_when_the_file_changes(tmp_path):
    p = make(tmp_path, "cache")
    assert geometry_basis.assess(p)["established"] is True
    make(tmp_path, "cache", unit="inch")                              # rewrite the same path
    assert geometry_basis.assess(p)["established"] is False


# --- review blockers: boundaries that must not slip through ----------------------------------


def test_readiness_is_blocked_even_when_raw_dimensions_are_unavailable(tmp_path):
    """Attribute order y,x,z is valid XML but the raw size scan cannot read it: no dimensions.
    An unestablished basis must still produce a not-checked check and no green ready."""
    p = make(tmp_path, "inchyxz", unit="inch", yxz=True)
    assert service.insights(p)["dimensions_mm"] is None
    rep = readiness_report(p)
    fit = next(c for c in rep["checks"] if c["name"] == "Fits the print bed")
    assert fit["status"] == "not_checked"
    assert rep["ready"] is False and rep["print_setup_ready"] is False


@pytest.mark.parametrize("tf", [
    "1.0009 0 0 0 1.0009 0 0 0 1.0009 0 0 0",            # a real scale that looks like identity
    "1 0 0 0 1 0 0 0 1.0009 0 0 0",                      # one axis only
    "1 0.0005 0 0 1 0 0 0 1 0 0 0",                      # a tiny shear
])
def test_near_identity_scales_and_shears_are_not_noise(tmp_path, tf):
    p = make(tmp_path, "near", items=(("1", tf),))
    assert geometry_basis.assess(p)["established"] is False
    assert service.bed_fit(p)["status"] == "not_checked"
    assert service.scale_preview(p, 100)["fits_build_volume"] is None


def test_serialisation_noise_in_an_identity_is_still_identity(tmp_path):
    p = make(tmp_path, "noise", items=(("1", "1.0000001 0 0 0 0.9999999 0 0 0 1 0 0 0"),))
    assert geometry_basis.assess(p)["established"] is True


def test_component_part_and_object_references_are_resolved_strictly(tmp_path):
    """The explicit part is missing, but ANOTHER part has an object with the same id: not a match."""
    other = {"3D/Objects/other.model": _model(_mesh_xml(1), "", "millimeter")}
    root = ('<object id="2" type="model"><components>'
            '<component p:path="/3D/missing.model" objectid="1"/></components></object>')
    parts = {"3D/3dmodel.model": _model(_mesh_xml(1) + root, '<item objectid="2"/>', "millimeter")}
    parts.update(other)
    basis = geometry_basis.assess(_write(tmp_path / "ref1.3mf", parts))
    assert basis["established"] is False and basis["reasons"] == ["structure_unresolved"]

    # a component with no path refers to the SAME part; an object that only another part has is unresolved
    root2 = ('<object id="2" type="model"><components><component objectid="7"/></components></object>')
    sub = {"3D/Objects/other.model": _model(_mesh_xml(7), "", "millimeter")}
    parts2 = {"3D/3dmodel.model": _model(root2, '<item objectid="2"/>', "millimeter")}
    parts2.update(sub)
    basis2 = geometry_basis.assess(_write(tmp_path / "ref2.3mf", parts2))
    assert basis2["reasons"] == ["structure_unresolved"]


def test_basis_returned_to_callers_cannot_corrupt_the_cache(tmp_path):
    p = make(tmp_path, "mut", unit="inch")
    a = geometry_basis.assess(p)
    a["established"] = True
    a["reasons"].clear()
    assert geometry_basis.assess(p)["established"] is False


def test_headline_score_is_withheld_when_any_doctor_withheld_its_verdict(tmp_path):
    """Before: health-only or the multi-material level alone produced a green 100/100 / 88."""
    rep = service.intelligence_report(make(tmp_path, "inchscore", unit="inch"))
    assert rep["studio_score"] is None
    out = intelligence_report.build(
        predict={"available": True, "status": "not_checked", "likelihood": None, "band": "unknown",
                 "reason": "R."},
        bed_fit={"available": False, "status": "not_checked", "reason": "R."},
        health={"available": True, "score": 88, "grade": "B", "verdict": "ok", "drivers": []})
    assert out["studio_score"] is None
    ok = intelligence_report.build(predict={"available": True, "likelihood": 90, "band": "likely", "factors": []})
    assert ok["studio_score"] == 90                                  # control: ordinary reports keep a score


def test_canonical_view_carries_the_basis_beside_the_raw_dimensions(tmp_path):
    c = service.canonical(make(tmp_path, "canon", unit="inch"))
    assert c["dimensions_mm"] and c["geometry_basis"]["established"] is False
