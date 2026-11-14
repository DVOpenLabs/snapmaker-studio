"""Contract tests for the exact published key allowlists and safe 3MF reading."""
from __future__ import annotations

import zipfile

import pytest

from snapstudio_core.creative.container import ContainerError, read_3mf
from snapstudio_core.creative.readers import (
    _FORCA_KEYS, _FULLSPECTRUM_KEYS, _LIX_KEYS,
    read_forca, read_fullspectrum, read_imagemap, read_lixnix, read_lumina,
)
from fixtures.creative.zip_factory import make_3mf, model_xml


def test_forca_fixture_published_key_contract() -> None:
    """Research lines device-research.json:134-150 and fos_config receipts name these keys."""
    config = {key: [0.4] for key in _FORCA_KEYS}
    config["fos_mms_topology"] = "opaque documented key"
    project = read_forca(config)
    assert set(project.understood) == set(_FORCA_KEYS)
    assert project.missing == ()
    changed = read_forca({**config, "fos_unpublished_guess": True})
    assert "fos_unpublished_guess" in changed.unknown
    archive_read = read_forca(make_3mf(settings={"fos_physical_nozzle_diameter": [0.4], "other": "kept"},
                                       members={"Metadata/vendor/opaque.bin": b"opaque"}))
    assert "Metadata/vendor/opaque.bin" in {item["name"] for item in archive_read.passed_through}
    assert "other" in {item["name"] for item in archive_read.passed_through}


def test_lixnix_fixture_published_key_contract() -> None:
    """Research lines device-research.json:155-168 and lix_config receipts name these keys."""
    config = {"extruder_layer_height": [0.1, 0.2], "extruder_layer_height_exact": True}
    project = read_lixnix(config)
    assert set(project.understood) == set(_LIX_KEYS)
    assert read_lixnix({"extruder_layer_height": [0.1]}).missing == ("extruder_layer_height_exact",)
    assert "extruder_layer_height_unpublished" in read_lixnix(
        {**config, "extruder_layer_height_unpublished": [0.3]}
    ).unknown


def test_fullspectrum_published_mixed_rows_become_simulated_virtual_recipes() -> None:
    """Packaging notes:162-211, and workflow-research xipit entry:232-272."""
    project = read_fullspectrum({"mixed_filament_definitions": "1,2,1,1,50,0,g,w,m2,z0,xa0,xb0,d0,o0,u17"})
    assert set(project.understood) == set(_FULLSPECTRUM_KEYS)
    assert project.physical_slots_needed == 2
    assert project.source_component_ids == (1, 2)
    assert project.simulated is True
    assert project.recipes[0].recipe_id == "fullspectrum:17"
    assert all(recipe.simulated is True for recipe in project.recipes)
    assert all(recipe.execution_supported is False for recipe in project.recipes)
    assert all(component.slot_ref.startswith("project:1:") for recipe in project.recipes for component in recipe.components)
    gradient = read_fullspectrum({"mixed_filament_definitions": "1,2,1,1,50,0,g123,w50/25/25,m2,z0,xa0,xb0,d0,o0,u18"})
    assert gradient.source_component_ids == (1, 2, 3)
    assert gradient.physical_slots_needed == 3
    assert read_fullspectrum({"mixed_filament_definitions": {"draft": True}}).unknown == (
        "mixed_filament_definitions",
    )
    assert read_fullspectrum({}).missing == ("mixed_filament_definitions",)


def test_3mf_manifest_hashes_unknown_members_without_rewriting() -> None:
    extension = b"opaque extension bytes\x00"
    data = make_3mf(members={"Metadata/vendor/extension.bin": extension})
    manifest = read_3mf(data)
    passthrough = next(part for part in manifest.passed_through if part.name == "Metadata/vendor/extension.bin")
    import hashlib
    assert passthrough.sha256 == hashlib.sha256(extension).hexdigest()
    assert "Metadata/vendor/extension.bin" not in manifest.understood_parts
    assert {"name": "Metadata/vendor/extension.bin", "sha256": passthrough.sha256} in manifest.to_dict()["passed_through"]


def test_imagemap_shape_stays_unknown_but_archive_identity_is_available() -> None:
    """Research says serialized ImageMap 3MF carrier is not established (creative-research:138-156)."""
    result = read_imagemap(make_3mf(members={"Metadata/image-zones.bin": b"zones"}))
    assert result.unknown == ("ImageMap serialized metadata carrier and zone shape",)
    assert result.diagnostics == ("shape_not_established_in_research",)


def test_lumina_reader_reports_only_3mf_artifact_identity() -> None:
    result = read_lumina(make_3mf(settings={"private_generator_state": "opaque"}), file_id="opaque-id")
    assert set(result.understood) == {"3mf_artifact_identity"}
    assert result.artifact_identity["file_id"] == "opaque-id"
    assert result.unknown == ("Lumina generation provenance",)


@pytest.mark.parametrize("payload", [make_3mf()[:-12], b"not a zip"])
def test_truncated_or_invalid_zip_is_rejected(payload: bytes) -> None:
    with pytest.raises(ContainerError):
        read_3mf(payload)


def test_expansion_cap_rejects_large_member() -> None:
    data = make_3mf(members={"Metadata/large.bin": b"x" * (16 * 1024 * 1024 + 1)}, compression=zipfile.ZIP_STORED)
    with pytest.raises(ContainerError, match="member_too_large"):
        read_3mf(data)


@pytest.mark.parametrize("name", ["../escape", "Metadata/../../escape", "/absolute", "C:/drive"])
def test_path_traversal_member_names_are_rejected(name: str) -> None:
    with pytest.raises(ContainerError, match="unsafe_member_name"):
        read_3mf(make_3mf(members={name: b"x"}))


def test_duplicate_member_is_rejected() -> None:
    with pytest.warns(UserWarning):
        data = make_3mf(duplicate=("Metadata/repeat.bin", b"one", b"two"))
    with pytest.raises(ContainerError, match="duplicate_member"):
        read_3mf(data)


def test_bad_xml_and_wrong_3mf_namespace_are_rejected() -> None:
    with pytest.raises(ContainerError, match="bad_xml"):
        read_3mf(make_3mf(model=b"<model><broken>"))
    with pytest.raises(ContainerError, match="unsupported_3mf_version"):
        read_3mf(make_3mf(model=model_xml(namespace="urn:unsupported:3mf:2")))


def test_missing_model_is_rejected() -> None:
    output = __import__("io").BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("Metadata/project_settings.config", b"{}")
    with pytest.raises(ContainerError, match="missing_model"):
        read_3mf(output.getvalue())


def test_missing_required_forca_key_and_contradictory_nozzle_semantics_stay_explicit() -> None:
    project = read_forca({"nozzle_diameter": [0.4], "fos_filament_nozzle": [0.6]})
    assert project.missing == ("fos_physical_nozzle_diameter",)
    assert "nozzle_diameter" not in project.understood
    assert "nozzle_diameter" in {item["name"] for item in project.passed_through}
    assert project.unknown == ()


def test_lixnix_exact_flag_with_empty_vector_is_reported_as_contradictory() -> None:
    project = read_lixnix({"extruder_layer_height": [], "extruder_layer_height_exact": True})
    assert project.diagnostics == ("exact_flag_without_layer_height_values",)
