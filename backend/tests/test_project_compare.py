"""The read-only diagnostic comparator: what it reports for a source and a prepared copy, and that it changes nothing."""
import hashlib
import json
import zipfile

import pytest

from snapstudio_api import service
from snapstudio_core import project_compare as pc
from snapstudio_core import project_materials as pm
from tests.test_project_materials import MATTE, _cfg, env, profiles  # noqa: F401  (fixtures)

MODEL_SETTINGS = """<?xml version="1.0"?><config>
<object id="1"><metadata key="name" value="Private Model Name"/><metadata key="extruder" value="1"/>
<part id="1" subtype="normal_part"><metadata key="name" value="Private Part"/><metadata key="extruder" value="2"/></part>
<part id="2" subtype="modifier_part"><metadata key="extruder" value="2"/></part></object>
<object id="2"><metadata key="name" value="Another"/></object></config>"""
CUSTOM = ('<?xml version="1.0"?><custom_gcodes_per_layer><plate><plate_info id="1"/>'
          '<layer top_z="4.2" type="2" extruder="4" color="#FFFFFF"/></plate></custom_gcodes_per_layer>')
SLICE = ('<config><plate><filament id="1" used_g="12.5"/><filament id="2" used_g="3"/></plate></config>')


def _five_colour_project(tmp_path, name="p.3mf", model_settings=None, **cfg_over):
    cfg = _cfg(filament_colour=["#FF0000", "#00FF00", "#0000FF", "#FFFFFF", "#FFFF00"],
               filament_type=["PLA"] * 5, filament_vendor=["Bambu Lab"] * 5,
               filament_settings_id=["Bambu PLA Basic @BBL H2D"] * 5, filament_ids=["GFA00"] * 5,
               different_settings_to_system=["", "", "filament_vendor", "", "", "", ""],
               support_filament="3", **cfg_over)
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("3D/3dmodel.model", '<?xml version="1.0"?><model/>')
        z.writestr("Metadata/project_settings.config", json.dumps(cfg))
        z.writestr("Metadata/model_settings.config", model_settings or MODEL_SETTINGS)
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


def test_a_painting_with_unreadable_facets_is_not_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(pc.painted_color, "read_container", lambda tm: {
        "available": True, "truncated": False, "slots_referenced": [], "malformed_triangle_count": 3})
    snap = pc.snapshot(_five_colour_project(tmp_path))
    assert snap["slots"][4]["usage"]["verdict"] == "unknown"


def test_a_filament_an_object_sets_for_itself_counts_as_a_reference(tmp_path):
    ms = ("<config><object id='1'><metadata key='extruder' value='1'/>"
          "<metadata key='support_filament' value='5'/></object></config>")
    slot5 = pc.snapshot(_five_colour_project(tmp_path, model_settings=ms))["slots"][4]["usage"]
    assert slot5["verdict"] == "referenced" and "support_filament (set on object 1)" in slot5["process_roles"]


def test_a_part_without_an_extruder_still_prints_with_the_first_filament(tmp_path):
    ms = ("<config><object id='1'>"
          "<part id='1' subtype='normal_part'><metadata key='extruder' value='2'/></part>"
          "<part id='2' subtype='normal_part'/></object></config>")
    usage = pc.snapshot(_five_colour_project(tmp_path, model_settings=ms))["slots"][0]["usage"]
    assert "default_extruder" in usage["referenced_by"]


def test_an_unreadable_painting_withholds_the_no_reference_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(pc.painted_color, "read_container", lambda tm: {"available": True, "truncated": True, "slots_referenced": []})
    snap = pc.snapshot(_five_colour_project(tmp_path))
    assert snap["slots"][4]["usage"]["verdict"] == "unknown" and snap["painting"]["complete"] is False


def test_the_object_list_is_read_as_xml_whatever_the_quoting_or_attribute_order(tmp_path):
    reordered = ("<?xml version='1.0'?><config>"
                 "<object name='X' id='7'><metadata value='3' key='extruder'/>"
                 "<part subtype='normal_part' id='1'><metadata value='2' key='extruder'/></part></object></config>")
    path = _five_colour_project(tmp_path, model_settings=reordered)
    cfg_slots = pc.slot_usage(pc.ThreeMF.open(path))["slots"]
    assert cfg_slots[3]["object_extruder"] == ["7"] and cfg_slots[2]["part_extruder"][0]["part"] == "1"


def test_a_missing_or_empty_object_list_is_unknown_not_no_reference_found(tmp_path):
    for name, content in (("missing", None), ("empty", "  ")):
        path = tmp_path / f"{name}.3mf"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("3D/3dmodel.model", "<model/>")
            z.writestr("Metadata/project_settings.config", json.dumps(_cfg(filament_colour=["#FF0000", "#00FF00"])))
            if content is not None:
                z.writestr("Metadata/model_settings.config", content)
        snap = pc.snapshot(path)
        assert [s["usage"]["verdict"] for s in snap["slots"]] == ["unknown", "unknown"], name
        assert snap["object_list_readable"] is False


def test_an_oversized_or_huge_object_list_is_refused_not_expanded(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "MAX_OBJECT_LIST_BYTES", 200)
    big = _five_colour_project(tmp_path, model_settings="<config>" + "<object id='1'/>" * 50 + "</config>")
    assert pc.snapshot(big)["slots"][4]["usage"]["verdict"] == "unknown"
    monkeypatch.setattr(pc, "MAX_OBJECT_LIST_BYTES", 8 * 1024 * 1024)
    monkeypatch.setattr(pc, "MAX_OBJECT_LIST_NODES", 10)
    many = _five_colour_project(tmp_path, name="many.3mf", model_settings="<config>" + "<object id='1'/>" * 50 + "</config>")
    snap = pc.snapshot(many)
    assert snap["slots"][4]["usage"]["verdict"] == "unknown" and snap["object_list_readable"] is False


def test_an_id_that_is_not_a_number_is_never_printed(tmp_path, capsys):
    ms = ("<config><object id='Secret Client Bracket.stl'><metadata key='extruder' value='2'/>"
          "<part id='Another Name' subtype='Secret Subtype'><metadata key='extruder' value='3'/></part></object></config>")
    pc.main([str(_five_colour_project(tmp_path, model_settings=ms))])
    out = capsys.readouterr().out
    assert "Secret" not in out and "Another" not in out and "Bracket" not in out


def test_a_part_level_filament_override_counts_and_inherit_zero_does_not_count_as_naming_a_slot(tmp_path):
    ms = ("<config><object id='1'><part id='2' subtype='normal_part'><metadata key='extruder' value='0'/>"
          "<metadata key='wall_filament' value='3'/></part></object></config>")
    by = {s["slot"]: s["usage"] for s in pc.snapshot(_five_colour_project(tmp_path, model_settings=ms))["slots"]}
    assert "wall_filament (set on part 2 of object 1)" in by[3]["process_roles"]
    assert "default_extruder" in by[1]["referenced_by"]            # an extruder of 0 inherits, so the first filament prints


def test_the_digest_is_streamed_and_names_no_file(tmp_path):
    snap = pc.snapshot(_five_colour_project(tmp_path, name="Client Name.3mf"), "source")
    assert snap["file"].startswith("source (sha256 ") and "Client" not in snap["file"]


def test_an_unreadable_object_list_is_unknown_not_no_reference_found(tmp_path):
    path = tmp_path / "bad.3mf"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("3D/3dmodel.model", "<model/>")
        z.writestr("Metadata/project_settings.config", json.dumps(_cfg(filament_colour=["#FF0000", "#00FF00"])))
        z.writestr("Metadata/model_settings.config", "<config><object id='1'><metadata key='extruder' value='2'/>")
    snap = pc.snapshot(path)
    assert [s["usage"]["verdict"] for s in snap["slots"]] == ["unknown", "unknown"]


def test_object_part_and_file_names_are_never_printed(tmp_path, capsys):
    pc.main([str(_five_colour_project(tmp_path, name="Secret Client Bracket.3mf"))])
    out = capsys.readouterr().out
    assert "Private" not in out and "Another" not in out and "Secret" not in out and "Bracket" not in out
    assert "source (sha256 " in out
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


def test_unicode_digits_are_not_numbers_here(tmp_path, capsys):
    """str.isdigit() accepts superscripts (int() then raises) and other scripts' digits (int() accepts them): neither is a slot number or a printable id."""
    # A superscript extruder must not make the whole object list unreadable.
    ms = ("<config><object id='1'><metadata key='extruder' value='\u00b2'/>"
          "<part id='\u0663' subtype='normal_part'><metadata key='extruder' value='3'/></part></object></config>")
    snap = pc.snapshot(_five_colour_project(tmp_path, model_settings=ms))
    by = {s["slot"]: s["usage"] for s in snap["slots"]}
    assert by[3]["verdict"] == "referenced"
    # Arabic-Indic digits in an override value name no slot; they are ignored, not read as 2.
    ms2 = ("<config><object id='1'><metadata key='extruder' value='1'/>"
           "<metadata key='support_filament' value='\u0662'/></object></config>")
    by2 = {s["slot"]: s["usage"] for s in pc.snapshot(_five_colour_project(tmp_path, name="q.3mf", model_settings=ms2))["slots"]}
    assert not any("support_filament (set on object 1)" in r for r in by2[2]["process_roles"])
    # Neither is a printable id.
    pc.main([str(_five_colour_project(tmp_path, name="r.3mf", model_settings=ms))])
    assert "\u0663" not in capsys.readouterr().out
    # A project-level value written in another script's digits names no slot either.
    project = _five_colour_project(tmp_path, name="s.3mf", wall_filament="\u0662")
    by3 = {s["slot"]: s["usage"] for s in pc.snapshot(project)["slots"]}
    assert "wall_filament" not in by3[2]["process_roles"]


# --- the Project Materials card carries the usage verdicts (issue 39), read-only ---------------

def test_project_materials_reports_usage_per_slot_and_the_toolhead_overflow(env, tmp_path):
    out = service.project_materials(str(_five_colour_project(tmp_path)))
    assert out["toolheads"] == 4 and out["beyond_toolheads"] == 1 and out["usage_readable"] is True
    verdicts = [s["usage"]["verdict"] for s in out["slots"]]
    assert verdicts == ["referenced", "referenced", "referenced", "referenced", "no_reference_found"]
    assert out["slots"][3]["usage"]["referenced_by"] == ["colour_changes"]
    # existing shape is untouched: the new fields only add
    assert {"slot", "material", "colour", "candidates", "current_preset"} <= set(out["slots"][0])


def test_unreadable_object_list_keeps_an_unreferenced_slot_unknown(env, tmp_path):
    path = _five_colour_project(tmp_path, model_settings="<config><object")        # not well-formed
    out = service.project_materials(str(path))
    assert out["usage_readable"] is False
    assert out["slots"][4]["usage"]["verdict"] == "unknown"


def test_no_usage_at_all_is_unknown_never_unused():
    analysis = {"slots": [{"slot": 0}, {"slot": 1}]}
    out = pm.attach_usage(analysis, None)
    assert [s["usage"]["verdict"] for s in out["slots"]] == ["unknown", "unknown"]
    assert out["beyond_toolheads"] == 0 and out["usage_readable"] is False


def test_the_usage_answer_names_no_object_and_does_not_change_the_file(env, tmp_path):
    path = _five_colour_project(tmp_path)
    before = _sha(path)
    out = service.project_materials(str(path))
    assert _sha(path) == before
    assert "Private" not in json.dumps(out["slots"][0]["usage"])
    assert set(out["slots"][0]["usage"]) == {"verdict", "referenced_by"}


def _fixture(name):
    from pathlib import Path
    return str(Path(__file__).parent / "fixtures" / "painted" / name)


def test_painted_only_slots_are_referenced_through_the_service(env):
    out = service.project_materials(_fixture("bambustudio-2.08.02.61-authored.3mf"))
    by = {s["slot"]: s["usage"] for s in out["slots"]}
    assert by[1] == {"verdict": "referenced", "referenced_by": ["painted"]}        # nothing but its paint names this slot
    assert by[2]["verdict"] == "no_reference_found" and out["usage_readable"] is True


def test_incomplete_painting_makes_usage_unreadable_and_unreferenced_slots_unknown(env):
    out = service.project_materials(_fixture("snapmaker-orca-2.3.5-authored.3mf"))
    by = {s["slot"]: s["usage"]["verdict"] for s in out["slots"]}
    assert by[1] == by[2] == by[3] == "referenced" and by[4] == "unknown"
    assert out["usage_readable"] is False and out["beyond_toolheads"] == 1


def test_usage_readable_needs_the_object_list_and_the_painting():
    ok = {"slots": {}, "object_list_readable": True, "painting": {"complete": True}}
    assert pm.attach_usage({"slots": []}, ok)["usage_readable"] is True
    assert pm.attach_usage({"slots": []}, {**ok, "painting": {"complete": False}})["usage_readable"] is False
    assert pm.attach_usage({"slots": []}, {**ok, "object_list_readable": False})["usage_readable"] is False
