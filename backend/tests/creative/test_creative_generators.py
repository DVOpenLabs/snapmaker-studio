"""Per-tool reader tests for DitherForge, Kromacut and SindriCAD, plus the SUPPORTED_FORMATS contract.

Evidence label: fixture-tested. Every archive is SYNTHETIC, built by fixtures/creative/zip_factory.py from
the shapes recorded in fixtures/creative/PROVENANCE.md.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from snapstudio_core.creative import formats, generators
from snapstudio_core.creative.container import ContainerError, read_3mf
from fixtures.creative.zip_factory import (
    make_3mf, make_ditherforge, make_kromacut, make_sindricad, model_xml,
)


# -- DitherForge -----------------------------------------------------------------------------

def test_ditherforge_understood_facts() -> None:
    project = generators.read_ditherforge(make_ditherforge(parts=2))
    facts = project.understood
    assert facts["variant"] == "generic" and facts["application"] == "ditherforge-0.6.3"
    assert facts["build_item_count"] == 2
    assert facts["object_part_files"] == ["3D/Objects/object_1.model", "3D/Objects/object_2.model"]
    assert facts["triangle_count"] == 8 and facts["painted_triangle_count"] == 6
    assert facts["per_face_paint"] is True
    assert facts["paint_extruders_used"] == [1, 2, 3]
    assert [o["name"] for o in facts["objects"]] == ["ditherforge_output_part1", "ditherforge_output_part2"]
    assert facts["filament_colour"] == ["#FF0000", "#00FF00", "#0000FF"]
    assert facts["printer_settings_id"] == "Synthetic U1 0.4 nozzle"
    assert project.missing == () and project.unknown == ()


def test_ditherforge_bambu_variant_tag_is_recognised() -> None:
    project = generators.read_ditherforge(make_ditherforge(application="BambuStudio-02.00.00.00+ditherforge-0.6.3"))
    assert project.understood["variant"] == "bambu_project"


def test_ditherforge_unknown_settings_and_members_are_passed_through_by_name_and_digest() -> None:
    project = generators.read_ditherforge(make_ditherforge(
        settings={"some_profile_key": "7"}, extra={"Metadata/plate_1.json": b"{}"}))
    names = {item["name"] for item in project.passed_through}
    assert {"some_profile_key", "layer_height", "Metadata/plate_1.json", "Metadata/model_settings.config"} <= names
    assert all(len(item["sha256"]) == 64 for item in project.passed_through)
    assert "some_profile_key" not in project.understood


def test_ditherforge_missing_expected_parts_are_listed_not_guessed() -> None:
    project = generators.read_ditherforge(make_ditherforge(with_settings=False))
    assert project.missing == ("Metadata/project_settings.config",)
    assert "filament_colour" not in project.understood


def test_long_paint_strings_stay_undecoded() -> None:
    project = generators.read_ditherforge(make_ditherforge(parts=1, paint=("4", "8", "0123456789", "")))
    assert project.understood["paint_extruders_used"] == [1, 2]
    assert any(item.startswith("paint_color values not decoded") for item in project.unknown)


# -- Kromacut --------------------------------------------------------------------------------

def test_kromacut_understood_facts() -> None:
    project = generators.read_kromacut(make_kromacut(layers=3))
    facts = project.understood
    assert facts["application"] == "Kromacut_Print"
    assert facts["layer_object_count"] == 3 and facts["assembly_present"] is True
    assert facts["layer_height"] == "0.08" and facts["first_layer_height"] == "0.2"
    assert [p["extruder"] for p in facts["parts"]] == [1, 2, 3]
    assert [c["name"] for c in facts["palette"]] == ["FF0000", "00FF00", "0000FF"]
    assert facts["per_face_paint"] is False
    assert len(facts["markers_matched"]) == 3
    # the opaque sidecar is kept by name and digest and flagged as not interpreted
    assert "Metadata/kromacut.config" in {item["name"] for item in project.passed_through}
    assert any("kromacut.config payload" in item for item in project.unknown)


def test_kromacut_identified_by_namespace_alone_when_application_tag_is_absent() -> None:
    project = generators.read_kromacut(make_kromacut(application="Something", with_config=False))
    assert project.understood["markers_matched"] == ["model namespace `xmlns:Kromacut`"]
    assert project.missing == ("Metadata/kromacut.config",)


def test_kromacut_unknown_model_settings_key_is_not_interpreted() -> None:
    project = generators.read_kromacut(make_kromacut(
        model_settings_extra='<plate><metadata key="mystery_key" value="1"/></plate>'))
    assert any("mystery_key" in item for item in project.unknown)


# -- SindriCAD -------------------------------------------------------------------------------

def test_sindricad_understood_facts_and_one_based_extruders() -> None:
    project = generators.read_sindricad(make_sindricad(bodies=2))
    facts = project.understood
    assert facts["body_count"] == 2
    assert facts["bodies"] == [{"name": "Plate", "palette_slot": 0, "extruder": 1},
                               {"name": "Lid", "palette_slot": 1, "extruder": 2}]
    assert facts["palette"] == [{"name": "Red", "colour": "#FF0000FF"}, {"name": "Blue", "colour": "#0000FFFF"}]
    assert facts["per_face_paint"] is True and facts["painted_triangle_count"] == 2
    assert facts["paint_extruders_used"] == [2]
    assert facts["filament_type"] == ["PLA", "PETG"]
    assert project.diagnostics == ()


def test_sindricad_flags_extruder_that_disagrees_with_palette_slot() -> None:
    project = generators.read_sindricad(make_sindricad(bodies=2, extruders=(1, 1)))
    assert project.diagnostics == ("extruder_disagrees_with_palette_slot:Lid",)


# -- detection, ambiguity, wrong shape -------------------------------------------------------

def test_detection_uses_markers_not_zip_shape() -> None:
    assert generators.detect(read_3mf(make_ditherforge())) == ["ditherforge"]
    assert generators.detect(read_3mf(make_kromacut())) == ["kromacut"]
    assert generators.detect(read_3mf(make_sindricad())) == ["sindricad"]
    assert generators.detect(read_3mf(make_3mf(settings={"layer_height": "0.2"}))) == []


def test_shared_markers_are_reported_as_both_candidates() -> None:
    blob = make_sindricad(extra={"Metadata/kromacut.config": b"x"})
    assert generators.detect(read_3mf(blob)) == ["kromacut", "sindricad"]
    # each reader still reads its own facts and names the other's markers
    assert "markers_of_other_generators_present:kromacut" in generators.read_sindricad(blob).diagnostics


@pytest.mark.parametrize("reader,expected_word", [
    (generators.read_ditherforge, "ditherforge-"), (generators.read_kromacut, "Kromacut_Print"),
    (generators.read_sindricad, "SindriCAD"),
])
def test_wrong_shape_is_refused_with_what_was_expected(reader, expected_word) -> None:
    with pytest.raises(generators.WrongShape) as raised:
        reader(make_3mf(settings={"layer_height": "0.2"}))
    assert any(expected_word in item for item in raised.value.expected)


def test_wrong_shape_for_a_different_tool_is_refused() -> None:
    with pytest.raises(generators.WrongShape):
        generators.read_kromacut(make_sindricad())


def test_malformed_archives_are_container_errors() -> None:
    with pytest.raises(ContainerError):
        generators.read_ditherforge(b"not a zip")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("readme.txt", "x")
    with pytest.raises(ContainerError, match="missing_model"):
        generators.read_sindricad(buf.getvalue())


def test_traversal_member_names_are_refused() -> None:
    blob = make_ditherforge(extra={"../escape.txt": b"x"})
    with pytest.raises(ContainerError, match="unsafe_member_name"):
        generators.read_ditherforge(blob)


def test_doctype_in_a_part_file_is_not_parsed() -> None:
    evil = (b'<?xml version="1.0"?><!DOCTYPE m [<!ENTITY a "x">]><model xmlns="'
            + b"http://schemas.microsoft.com/3dmanufacturing/core/2015/02" + b'"/>')
    project = generators.read_ditherforge(make_ditherforge(extra={"3D/Objects/object_9.model": evil}))
    assert "object_model_unreadable:3D/Objects/object_9.model" in project.diagnostics


def test_unreadable_model_settings_is_a_diagnostic() -> None:
    blob = make_sindricad(extra={"Metadata/model_settings.config": b"<config"})
    assert "model_settings_unreadable" in generators.read_sindricad(blob).diagnostics


def test_bad_core_namespace_is_refused_by_the_container() -> None:
    with pytest.raises(ContainerError, match="unsupported_3mf_version"):
        generators.read_sindricad(make_3mf(model=model_xml(namespace="urn:other")))


# -- SUPPORTED_FORMATS contract --------------------------------------------------------------

def test_supported_formats_contract() -> None:
    keys = [f["key"] for f in formats.SUPPORTED_FORMATS]
    assert keys == ["ditherforge", "kromacut", "sindricad", "forcaslicer", "lixnix", "fullspectrum",
                    "imagemap", "lumina"]
    required = {"key", "label", "carrier", "selection", "identified_by", "reads", "kept_untouched", "not_read",
                "upstream"}
    for entry in formats.SUPPORTED_FORMATS:
        assert set(entry) - {"prepare_limits"} == required
        assert ("prepare_limits" in entry) == (entry["key"] == "ditherforge")
        assert entry["carrier"].startswith("3MF")
        assert entry["reads"] and entry["not_read"] and entry["kept_untouched"]
        assert entry["selection"] in ("automatic", "manual only")
    # a manual-only format has no identifying marker and says so; an automatic one always has one
    for entry in formats.SUPPORTED_FORMATS:
        assert (entry["selection"] == "manual only") == (entry["identified_by"] == [])
    assert formats.MANUAL_ONLY == ("imagemap", "lumina")
    by_key = {f["key"]: f for f in formats.SUPPORTED_FORMATS}
    assert "AGPL" in by_key["kromacut"]["upstream"] and "AGPL" in by_key["sindricad"]["upstream"]
    assert "MIT" in by_key["ditherforge"]["upstream"]
    text = repr(formats.SUPPORTED_FORMATS).lower()
    for banned in ("guarantee", "100%", "ready", "coming soon"):
        assert banned not in text
