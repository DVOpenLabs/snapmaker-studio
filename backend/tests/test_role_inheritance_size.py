"""Printing roles propagate down through assemblies, seen through the size entry points: the Bed-Fit API,
the validation report and Design Health's per-object sizes (same fixtures and rule as the placement tests)."""
from __future__ import annotations

import pytest

from snapstudio_api import service
from snapstudio_core import geometry
from snapstudio_core.intelligence import project_info
from tests.test_role_inheritance_placement import (HELPER_ROLES, REV, SEAM_WORDS, bed_fit_check,
                                                   nested_assembly, on_assembly, on_nested_record,
                                                   ready_placement)


def fits_check(path):
    return next(c for c in service.report(path)["checks"] if c["name"] == "Fits the print bed")


@pytest.mark.parametrize("where", [on_assembly, on_nested_record], ids=["on_assembly", "on_nested_record"])
@pytest.mark.parametrize("role", HELPER_ROLES + SEAM_WORDS)
def test_a_helper_role_on_an_assembly_keeps_the_size_to_what_prints(tmp_path, role, where):
    path = nested_assembly(tmp_path, where(role))
    [size] = geometry.object_sizes(path)
    assert size["dimensions"]["z"] == 10.0
    info = project_info(path, placement_aware=True)
    assert info["object_sizes_mm"][0]["dimensions_mm"]["z"] == 10.0
    result = service.bed_fit(path)
    assert result["overall_level"] == "ok", result["overall_text"]
    assert result["dims_mm"]["z"] == 10.0
    check = fits_check(path)
    assert check["status"] == "pass" and "10.0 mm" in check["detail"]


def test_a_missing_role_is_a_normal_part_and_makes_the_object_too_tall(tmp_path):
    path = nested_assembly(tmp_path, {"100": [("1", "normal_part")]})
    assert geometry.object_sizes(path)[0]["dimensions"]["z"] == 300.0
    result = service.bed_fit(path)
    assert result["overall_level"] == "risk"
    assert fits_check(path)["status"] == "warn"


def test_conflicting_records_count_toward_the_size(tmp_path):
    path = nested_assembly(tmp_path, {"100": [("1", "normal_part"), ("5", "modifier_part"), ("5", "normal_part")]})
    assert geometry.object_sizes(path)[0]["dimensions"]["z"] == 300.0          # unknown cannot be proven away
    assert service.bed_fit(path)["overall_level"] == "risk"


def test_a_child_cannot_print_again_beneath_a_non_printing_assembly(tmp_path):
    records = {"100": [("1", "normal_part"), ("5", "modifier_part")], "5": [("3", "normal_part")]}
    path = nested_assembly(tmp_path, records)
    assert geometry.object_sizes(path)[0]["dimensions"]["z"] == 10.0
    assert service.bed_fit(path)["overall_level"] == "ok"


@pytest.mark.parametrize("role", ["modifier_part", "precise_seam_center"])
def test_one_fixture_every_consumer_agrees(tmp_path, monkeypatch, role):
    """The 10 mm printable part beside a 300 mm helper volume under a nested assembly: preflight, Ready Now,
    the Bed-Fit API, the validation report, the overall extents and the scene say the same thing."""
    from snapstudio_core import plate_placement as pp, scene
    path = nested_assembly(tmp_path, on_assembly(role))
    assert bed_fit_check(path, monkeypatch)["result"] == "ok"                                  # preflight
    assert pp.over_height(ready_placement(path)) == []                                         # Ready Now
    assert service.bed_fit(path)["overall_level"] == "ok"                                      # Bed-Fit API
    assert fits_check(path)["status"] == "pass"                                                # validation report
    assert project_info(path)["dimensions_mm"]["z"] == 10.0                                    # overall extents
    sc = scene.build_scene_dict(path, REV)                                                     # scene
    assert next(n for n in sc["nodes"] if n["id"] == "b0")["bounds_mm"]["max"][2] == 10.0
    assert not any(f["kind"] in ("size", "placement") for f in sc["findings"])
