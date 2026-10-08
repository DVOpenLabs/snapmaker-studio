"""The read-only diagnostic comparator: what it reports for a source and a prepared copy, and that it changes nothing."""
import hashlib
import json
import zipfile

import pytest

from snapstudio_api import service
from snapstudio_core import project_compare as pc
from tests.test_project_materials import MATTE, _cfg, env, profiles  # noqa: F401  (fixtures)

MODEL_SETTINGS = """<?xml version="1.0"?><config>
<object id="1"><metadata key="name" value="Private Model Name"/><metadata key="extruder" value="1"/>
<part id="1" subtype="normal_part"><metadata key="name" value="Private Part"/><metadata key="extruder" value="2"/></part>
<part id="2" subtype="modifier_part"><metadata key="extruder" value="2"/></part></object>
<object id="2"><metadata key="name" value="Another"/></object></config>"""
CUSTOM = ('<?xml version="1.0"?><custom_gcodes_per_layer><plate><plate_info id="1"/>'
          '<layer top_z="4.2" type="2" extruder="4" color="#FFFFFF"/></plate></custom_gcodes_per_layer>')
SLICE = ('<config><plate><filament id="1" used_g="12.5"/><filament id="2" used_g="3"/></plate></config>')


def _five_colour_project(tmp_path, name="p.3mf", **cfg_over):
    cfg = _cfg(filament_colour=["#FF0000", "#00FF00", "#0000FF", "#FFFFFF", "#FFFF00"],
               filament_type=["PLA"] * 5, filament_vendor=["Bambu Lab"] * 5,
               filament_settings_id=["Bambu PLA Basic @BBL H2D"] * 5, filament_ids=["GFA00"] * 5,
               different_settings_to_system=["", "", "filament_vendor", "", "", "", ""],
               support_filament="3", **cfg_over)
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("3D/3dmodel.model", '<?xml version="1.0"?><model/>')
        z.writestr("Metadata/project_settings.config", json.dumps(cfg))
        z.writestr("Metadata/model_settings.config", MODEL_SETTINGS)
        z.writestr("Metadata/custom_gcode_per_layer.xml", CUSTOM)
        z.writestr("Metadata/slice_info.config", SLICE)
    return path


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_each_kind_of_reference_is_reported_apart(tmp_path):
    snap = pc.snapshot(_five_colour_project(tmp_path))
    by = {s["slot"]: s["usage"] for s in snap["slots"]}
    assert by[1]["object_extruder"] == ["1"] and "default_extruder" in by[1]["referenced_by"]   # object 2 has none
    assert by[2]["part_extruder"] == [{"object": "1", "part": "1", "subtype": "normal_part"},
                                      {"object": "1", "part": "2", "subtype": "modifier_part"}]
    assert by[3]["process_roles"] == ["support_filament"]
    assert by[4]["colour_changes"] == [4.2] and by[4]["verdict"] == "referenced"
    assert by[1]["sliced_g"] == 12.5 and "sliced_usage" in by[1]["referenced_by"]


def test_a_slot_nothing_names_is_no_reference_found_not_unused(tmp_path):
    snap = pc.snapshot(_five_colour_project(tmp_path))
    last = snap["slots"][4]["usage"]
    assert last["verdict"] == "no_reference_found" and last["referenced_by"] == []
    assert snap["painting"] == {"present": False, "complete": True, "truncated": False}


def test_an_unreadable_painting_withholds_the_no_reference_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(pc.painted_color, "read_container", lambda tm: {"available": True, "truncated": True, "slots_referenced": []})
    snap = pc.snapshot(_five_colour_project(tmp_path))
    assert snap["slots"][4]["usage"]["verdict"] == "unknown" and snap["painting"]["complete"] is False


def test_object_and_part_names_are_never_printed(tmp_path, capsys):
    pc.main([str(_five_colour_project(tmp_path))])
    out = capsys.readouterr().out
    assert "Private" not in out and "Another" not in out
    assert json.loads(out)["filament_count"] == 5


def test_slot_identity_and_declarations_are_reported(tmp_path):
    slot = pc.snapshot(_five_colour_project(tmp_path))["slots"][1]
    assert slot["settings_id"] == "Bambu PLA Basic @BBL H2D" and slot["vendor"] == "Bambu Lab"
    assert slot["filament_id"] == "GFA00" and slot["declared"] == ["filament_vendor"]


def test_compare_shows_exactly_what_project_materials_changed_and_modifies_neither_file(env, tmp_path):
    src = _five_colour_project(tmp_path)
    result = service.convert(str(src), str(tmp_path / "out"), "preserve", False,
                             {"selections": [{"slot": 1, "preset": MATTE, "colour": "#00AA11"}]})
    prepared = result["output_path"]
    before = (_sha(src), _sha(tmp_path / "out" / prepared.split("\\")[-1].split("/")[-1]))
    report = pc.compare(src, prepared)
    changed = {(c["slot"], c.get("field")) for c in report["slot_changes"]}
    assert (2, "settings_id") in changed and (2, "colour") in changed
    assert all(c["slot"] == 2 for c in report["slot_changes"] if c.get("field") in ("settings_id", "colour"))
    assert {"filament_settings_id", "filament_colour"} <= set(report["differing_filament_settings"])
    assert report["slot_changes"][0]["source"] is not None
    assert (_sha(src), _sha(tmp_path / "out" / prepared.split("\\")[-1].split("/")[-1])) == before
    assert "not proof" in report["note"]


def test_the_command_line_needs_one_or_two_files(capsys):
    assert pc.main([]) == 2
    assert pc.main(["a", "b", "c"]) == 2


def test_nothing_is_written(tmp_path):
    src = _five_colour_project(tmp_path)
    names = sorted(p.name for p in tmp_path.iterdir())
    pc.snapshot(src)
    assert sorted(p.name for p in tmp_path.iterdir()) == names
