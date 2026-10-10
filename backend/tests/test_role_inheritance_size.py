"""Printing roles propagate down through assemblies, seen through the size entry points: the Bed-Fit API,
the validation report and Design Health's per-object sizes (same fixtures and rule as the placement tests)."""
from __future__ import annotations

import pytest

from snapstudio_api import service
from snapstudio_core import geometry
from snapstudio_core.intelligence import project_info
from tests.test_role_inheritance_placement import (HELPER_ROLES, nested_assembly, on_assembly,
                                                   on_nested_record)


def fits_check(path):
    return next(c for c in service.report(path)["checks"] if c["name"] == "Fits the print bed")


@pytest.mark.parametrize("where", [on_assembly, on_nested_record], ids=["on_assembly", "on_nested_record"])
@pytest.mark.parametrize("role", HELPER_ROLES)
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
