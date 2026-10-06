"""The U1 base project may not accrete values nobody owns.

The template was captured from a real Snapmaker Orca project, so it states most
of its presets' values inline. That is mostly harmless and mostly pointless:
measured on Orca 2.3.6, a value a project states is only used when the project
also **declares** it deviates, and an undeclared value is replaced by the preset
the project names. A restated preset default is a comment the slicer overwrites.

Eight keys were removed because they were neither: they differed from the preset,
had no owning feature in Studio, and were replaced on load — so they had never
reached a print. The machine's own start and end G-code were among them, five
weeks out of date against the preset that owns them.

These tests keep that from happening again. Every key must belong to a group
`data/templates/PROVENANCE.md` describes, and every group has an owner in the
code.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from snapstudio_core import preset_deviation, stl_wrap
from snapstudio_core.filaments import PER_FILAMENT_KEYS
from snapstudio_core.optimize import load_optimization
from snapstudio_core.prusa import CARRIED as PRUSA_CARRIED

TEMPLATES = Path(stl_wrap.__file__).parent / "data" / "templates"
TEMPLATE = TEMPLATES / "u1_base_project_settings.json"
PROVENANCE = TEMPLATES / "PROVENANCE.md"

#: The project describing itself: how many filaments, which colours, how they
#: purge. Not a preset's to own.
PROJECT_STRUCTURE = set(PER_FILAMENT_KEYS) | {
    "filament_colour", "filament_settings_id", "flush_volumes_matrix",
    "flush_volumes_vector", "filament_maps", "different_settings_to_system",
    "print_sequence", "is_custom_defined",
}

#: Which machine and which presets this project is.
TARGET_IDENTITY = {
    "printer_model", "printer_variant", "printer_settings_id",
    "print_settings_id", "filament_settings_id", "nozzle_diameter",
    "version", "name", "from",
}

#: A fact carried from the project being prepared.
SOURCE_CARRIED = {target for _source, target, _label in PRUSA_CARRIED} | {"brim_type"}

#: Values that stop Snapmaker Orca misbehaving on a U1.
STUDIO_COMPATIBILITY = {
    "exclude_object", "brim_type", "support_style", "filament_self_index",
    "raft_first_layer_expansion",
}

#: Whatever an optimization profile sets, in optimize mode only.
STUDIO_OPTIMIZATION = set()
for _profile in ("u1_fast_prime_tower",):
    STUDIO_OPTIMIZATION |= set(load_optimization(_profile).get("set", {}))

#: Removed on 2026-08-26. Each differed from the preset the template names, had
#: no owning feature, and was replaced by Orca on load — so none had ever reached
#: a print. Listed so a later capture cannot quietly bring them back.
REMOVED = {
    "machine_start_gcode", "machine_end_gcode", "layer_change_gcode",
    "nozzle_type", "default_print_profile", "enable_pressure_advance",
    "supertack_plate_temp", "supertack_plate_temp_initial_layer",
}


@pytest.fixture(scope="module")
def template() -> dict:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def test_the_provenance_document_exists_and_names_every_group():
    text = PROVENANCE.read_text(encoding="utf-8")
    for group in ("preset_default", "project_structure", "target_identity",
                  "source_carried", "studio_compatibility",
                  "studio_optimization", "no_preset_equivalent"):
        assert group in text, group


def test_nothing_removed_has_crept_back(template):
    """A later capture from a real project would bring these with it."""
    back = REMOVED & set(template)
    assert not back, f"removed keys are in the template again: {sorted(back)}"


def test_the_machine_never_gets_its_own_gcode_from_studio(template):
    """The start and end G-code are what the printer runs.

    They belong to the installed printer preset, which tracks the firmware.
    Studio shipped a snapshot dated 20251222 against a preset dated 20260128.
    """
    for key in ("machine_start_gcode", "machine_end_gcode", "layer_change_gcode"):
        assert key not in template, key


def test_a_prepared_copy_states_no_more_than_the_template(template):
    """The template is the contract; nothing may add keys behind its back."""
    import tempfile
    import zipfile

    from snapstudio_core.convert import convert_to_u1

    source = (Path(__file__).parent / "fixtures" / "prusa-semantics"
              / "J_per_object_override_out.3mf")
    prepared = convert_to_u1(str(source), out_dir=tempfile.mkdtemp()).output_path
    with zipfile.ZipFile(prepared) as z:
        cfg = json.loads(z.read("Metadata/project_settings.config").decode("utf-8"))
    extra = set(cfg) - set(template)
    assert not extra, f"the prepared copy invented keys: {sorted(extra)}"


def test_every_owned_group_is_actually_in_the_template(template):
    """A group with no keys left is a group whose owner has gone away."""
    for name, keys in (("project_structure", PROJECT_STRUCTURE),
                       ("target_identity", TARGET_IDENTITY),
                       ("source_carried", SOURCE_CARRIED),
                       ("studio_compatibility", STUDIO_COMPATIBILITY),
                       ("studio_optimization", STUDIO_OPTIMIZATION)):
        assert keys & set(template), f"{name} owns nothing in the template"


def test_the_declaration_slot_exists_for_every_owner():
    """Process, filament and printer each have their own entry, measured.

    A key declared in the wrong one is ignored: `nozzle_temperature` in the
    process entry left the value reset from 230 to 215, and `nozzle_type`
    anywhere but the printer entry left it reset to the preset's.
    """
    cfg: dict = {}
    change = preset_deviation.declare(
        cfg, ["brim_type", "nozzle_temperature", "nozzle_type"], filaments=4)
    entries = cfg["different_settings_to_system"]
    assert entries[preset_deviation.PROCESS] == "brim_type"
    assert "nozzle_temperature" in entries[preset_deviation.FIRST_FILAMENT]
    assert entries[preset_deviation.PRINTER] == "nozzle_type"
    assert change["printer_keys"] == ["nozzle_type"]


#: The one module allowed to look at Orca's preset files: it lists WHICH presets are installed (name, type,
#: vendor, parent and which printers each is stated to fit) so Project Materials can map a spool to a real
#: installed preset. It never reads, resolves or copies a preset's print VALUES - see the next test.
_PRESET_CATALOGUE = "preset_catalog.py"


def test_studio_never_reads_orcas_preset_files_at_runtime():
    """That would be a second preset resolver to keep in step with every release.

    Studio knows what it changed because Studio made the change. The installed-preset catalogue is the
    single, named exception: identity only, never values.
    """
    import snapstudio_core

    root = Path(snapstudio_core.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == _PRESET_CATALOGUE:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "resources/profiles" in text or "resources\\\\profiles" in text:
            offenders.append(path.name)
    assert not offenders, f"these read Orca's shipped presets: {offenders}"


def test_the_preset_catalogue_reads_identity_never_print_values():
    """It may ask which printers a preset is for, what it inherits and what it is called - not what it prints at."""
    import snapstudio_core

    text = (Path(snapstudio_core.__file__).parent / _PRESET_CATALOGUE).read_text(encoding="utf-8")
    values = ("nozzle_temperature", "filament_flow_ratio", "filament_max_volumetric_speed", "pressure_advance",
              "fan_min_speed", "fan_max_speed", "hot_plate_temp", "textured_plate_temp", "filament_density",
              "filament_cost")
    assert [k for k in values if k in text] == []
    assert "write_text" not in text and "open(" not in text and ".unlink" not in text and "os.replace" not in text
