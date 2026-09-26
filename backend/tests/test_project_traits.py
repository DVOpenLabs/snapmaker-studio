"""Project trait extraction.

These build real 3MF archives rather than mocking the reader, because the whole
point of the module is that it tells the truth about bytes on disk. The two
things under test are (a) does it read the right facts out of the layouts real
slicers write, and (b) does it grade its own certainty honestly when it cannot.
"""
from __future__ import annotations

import json
import zipfile

from snapstudio_core import project_traits as pt

MODEL_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<model unit="{unit}" xml:lang="en-US"'
    ' xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'
    ' xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"'
    '{extra}>'
    '<metadata name="Application">{app}</metadata>'
    '<resources/><build>{items}</build></model>'
)


def _model(unit="millimeter", app="OrcaSlicer-2.2.0", items=1, extra=""):
    return MODEL_HEAD.format(unit=unit, app=app, extra=extra,
                             items="".join('<item objectid="1"/>' for _ in range(items))).encode()


def _write(path, entries: dict) -> str:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data if isinstance(data, bytes) else data.encode())
    return str(path)


def _painted_model(attribute: str) -> bytes:
    """A model part whose mesh carries painted colour — where a slicer puts it."""
    return _model().decode().replace(
        "<resources/>",
        '<resources><object id="1" type="model"><mesh><triangles>'
        f'<triangle v1="0" v2="1" v3="2" {attribute}/>'
        "</triangles></mesh></object></resources>").encode()


def _bambu(tmp_path, name="p.3mf", settings=None, extra_parts=None, model=None):
    parts = {
        "[Content_Types].xml": "<x/>",
        "3D/3dmodel.model": model or _model(),
        "Metadata/project_settings.config": json.dumps(settings or {
            "printer_model": "Snapmaker U1",
            "filament_colour": ["#FF0000", "#00FF00"],
            "filament_type": ["PLA", "PLA"],
            "nozzle_diameter": ["0.4", "0.4"],
        }),
    }
    parts.update(extra_parts or {})
    return _write(tmp_path / name, parts)


def test_reads_a_u1_project(tmp_path):
    t = pt.extract(_bambu(tmp_path))
    assert t["readable"] is True
    assert t["origin_family"]["value"] == "bambu-family"
    assert t["origin_family"]["confidence"] == pt.CONFIRMED
    assert t["target_printer"]["value"] == "Snapmaker U1"
    assert t["is_u1_project"]["value"] is True
    assert t["foreign_printer"]["value"] is False
    assert t["filament_count"]["value"] == 2
    assert t["origin_application"]["value"] == "OrcaSlicer-2.2.0"


def test_detects_a_foreign_printer(tmp_path):
    p = _bambu(tmp_path, settings={"printer_model": "Bambu Lab X1 Carbon"})
    t = pt.extract(p)
    assert t["foreign_printer"]["value"] is True
    assert t["is_u1_project"]["value"] is False
    assert "Bambu Lab X1 Carbon" in t["foreign_printer"]["evidence"]


def test_sliced_project_is_recognised(tmp_path):
    p = _bambu(tmp_path, extra_parts={"Metadata/plate_1.gcode": "G1 X0\n"})
    t = pt.extract(p)
    assert t["is_sliced"]["value"] is True
    assert t["is_sliced"]["confidence"] == pt.CONFIRMED


def test_unsliced_project_is_not_claimed_sliced(tmp_path):
    t = pt.extract(_bambu(tmp_path))
    assert t["is_sliced"]["value"] is False


def test_plate_count_prefers_recorded_plates_over_thumbnails(tmp_path):
    ms = "<config><plate><metadata key='index' value='1'/></plate><plate/></config>"
    p = _bambu(tmp_path, extra_parts={
        "Metadata/model_settings.config": ms,
        "Metadata/plate_1.png": b"\x89PNG",
    })
    t = pt.extract(p)
    assert t["plate_count"]["value"] == 2
    assert t["plate_count"]["confidence"] == pt.CONFIRMED


def test_plate_count_from_thumbnails_is_only_likely(tmp_path):
    p = _bambu(tmp_path, extra_parts={
        "Metadata/plate_1.png": b"\x89PNG",
        "Metadata/plate_2.png": b"\x89PNG",
    })
    t = pt.extract(p)
    assert t["plate_count"]["value"] == 2
    assert t["plate_count"]["confidence"] == pt.LIKELY


def test_non_millimeter_unit_is_flagged(tmp_path):
    p = _bambu(tmp_path, model=_model(unit="inch"))
    t = pt.extract(p)
    assert t["unit"]["value"] == "inch"
    assert t["non_mm_unit"]["value"] is True


def test_mixed_nozzle_sizes(tmp_path):
    p = _bambu(tmp_path, settings={
        "printer_model": "Snapmaker U1",
        "nozzle_diameter": ["0.2", "0.4", "0.4", "0.8"],
    })
    t = pt.extract(p)
    assert t["mixed_nozzle_sizes"]["value"] is True
    assert t["nozzle_diameters"]["value"] == ["0.2", "0.4", "0.8"]
    # Opus delta review of 9b638c6: nozzle_diameters is deduplicated and sorted,
    # so preflight cannot use it to tell which size belongs to which toolhead.
    # nozzle_diameters_by_toolhead keeps the original, one-entry-per-toolhead
    # order, duplicates and all — the shape preflight actually needs.
    assert t["nozzle_diameters_by_toolhead"]["value"] == ["0.2", "0.4", "0.4", "0.8"]


def test_uniform_nozzles_are_not_called_mixed(tmp_path):
    p = _bambu(tmp_path, settings={"printer_model": "Snapmaker U1",
                                   "nozzle_diameter": ["0.4", "0.4"]})
    assert pt.extract(p)["mixed_nozzle_sizes"]["value"] is False


def test_texture_and_painted_colour_detection(tmp_path):
    # Painting is carried on the mesh triangles. Studio used to look for it in
    # model_settings.config, where no slicer has ever written it, so every
    # painted project was reported as unpainted.
    p = _bambu(tmp_path, model=_painted_model('paint_color="8"'),
               extra_parts={"3D/Textures/skin.png": b"\x89PNG"})
    t = pt.extract(p)
    assert t["has_texture"]["value"] is True
    assert t["has_painted_color"]["value"] is True
    assert "3D/3dmodel.model" in t["has_painted_color"]["evidence"]


def test_the_prusa_dialect_of_painting_is_detected_too(tmp_path):
    model = _painted_model('slic3rpe:mmu_segmentation="8"')
    assert pt.extract(_bambu(tmp_path, model=model))[
        "has_painted_color"]["value"] is True


def test_a_project_with_no_painting_does_not_claim_any(tmp_path):
    t = pt.extract(_bambu(tmp_path))
    assert t["has_painted_color"]["value"] is False
    assert t["has_painted_color"]["evidence"] is None


def test_unknown_required_extension_is_reported(tmp_path):
    extra = (' xmlns:weird="http://example.invalid/ext/1"'
             ' requiredextensions="weird"')
    p = _bambu(tmp_path, model=_model(extra=extra))
    t = pt.extract(p)
    assert t["unknown_required_extensions"]["value"] is True
    assert "http://example.invalid/ext/1" in t["required_extensions"]["value"]
    assert any("does not recognise" in n for n in t["notes"])


def test_known_required_extension_is_not_reported(tmp_path):
    p = _bambu(tmp_path, model=_model(extra=' requiredextensions="p"'))
    t = pt.extract(p)
    assert t["unknown_required_extensions"]["value"] is False


def test_slicer_own_predictions_are_read(tmp_path):
    slice_info = (
        "<config><plate>"
        "<metadata key='index' value='1'/>"
        "<metadata key='prediction' value='5400'/>"
        "<metadata key='weight' value='42.5'/>"
        "<filament id='1' type='PLA' color='#FF0000' used_m='14.2' used_g='42.5'/>"
        "</plate></config>"
    )
    p = _bambu(tmp_path, extra_parts={"Metadata/slice_info.config": slice_info})
    plates = pt.extract(p)["plate_predictions"]
    assert len(plates) == 1
    assert plates[0]["predicted_seconds"] == 5400.0
    assert plates[0]["predicted_weight_g"] == 42.5
    assert plates[0]["filaments"][0]["used_g"] == 42.5
    assert plates[0]["filaments"][0]["type"] == "PLA"


def test_prusa_project(tmp_path):
    p = _write(tmp_path / "prusa.3mf", {
        "3D/3dmodel.model": _model(app="PrusaSlicer-2.8.0"),
        "Metadata/Slic3r_PE.config": "; printer_model = MK4\n; filament_type = PETG\n",
    })
    t = pt.extract(p)
    assert t["origin_family"]["value"] == "prusa"
    assert t["target_printer"]["value"] == "MK4"
    assert t["foreign_printer"]["value"] is True


def test_generic_3mf_claims_nothing_it_cannot_see(tmp_path):
    p = _write(tmp_path / "plain.3mf", {"3D/3dmodel.model": _model(app="FreeCAD")})
    t = pt.extract(p)
    assert t["origin_family"]["value"] == "generic"
    assert t["target_printer"]["value"] is None
    assert t["target_printer"]["confidence"] == pt.UNKNOWN
    assert t["is_u1_project"]["confidence"] == pt.UNKNOWN


def test_stl_traits(tmp_path):
    p = tmp_path / "m.stl"
    p.write_bytes(b"solid x\nendsolid x\n")
    t = pt.extract(str(p))
    assert t["format"]["value"] == "stl"
    assert t["filament_count"]["value"] == 0
    assert t["unit"]["confidence"] == pt.UNKNOWN


def test_missing_file_is_unreadable_not_an_exception():
    t = pt.extract("does-not-exist.3mf")
    assert t["readable"] is False
    assert t["format"]["confidence"] == pt.UNKNOWN
    # Every documented trait key is still present so callers never KeyError.
    for key in pt.TRAIT_KEYS:
        assert key in t


def test_garbage_file_is_unreadable(tmp_path):
    p = tmp_path / "junk.3mf"
    p.write_bytes(b"this is not a zip")
    t = pt.extract(str(p))
    assert t["readable"] is False
    assert "3MF" in t["notes"][0]


def test_zip_bomb_is_reported_as_unreadable_with_its_reason(tmp_path, monkeypatch):
    from snapstudio_core import container
    monkeypatch.setattr(container, "MAX_TOTAL_UNCOMPRESSED", 1024)
    monkeypatch.setattr(container, "MAX_PART_UNCOMPRESSED", 1024)
    p = _write(tmp_path / "bomb.3mf", {"big.bin": b"\0" * 200_000})
    t = pt.extract(p)
    assert t["readable"] is False
    assert "Studio will open" in t["notes"][0]


def test_likely_makerworld_stays_likely(tmp_path):
    p = _bambu(tmp_path, settings={"printer_model": "Bambu Lab P1S"},
               extra_parts={"Auxiliaries/.thumbnails/a.png": b"\x89PNG"})
    t = pt.extract(p)
    assert t["likely_makerworld"]["value"] is True
    assert t["likely_makerworld"]["confidence"] == pt.LIKELY


def test_u1_project_is_never_called_makerworld(tmp_path):
    p = _bambu(tmp_path, extra_parts={"Auxiliaries/.thumbnails/a.png": b"\x89PNG"})
    assert pt.extract(p)["likely_makerworld"]["value"] is False


def test_values_flattens_graded_traits(tmp_path):
    v = pt.values(pt.extract(_bambu(tmp_path)))
    assert v["is_u1_project"] is True
    assert "schema_version" not in v
    assert "notes" not in v
