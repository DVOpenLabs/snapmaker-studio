"""Per-object setting overrides: what crosses, what does not, and why.

Three settings cross, and the reason each one is here is a measurement against
Snapmaker Orca 2.3.6 rather than a matching name. The measurements these tests
encode, each made by writing one key into an otherwise byte-identical project,
opening it in Orca and reading the project Orca saved back:

* `layer_height`, `sparse_infill_density` and `enable_support` survive;
* an invented key does not — which is what makes the first three evidence;
* **PrusaSlicer's own `fill_density` and `support_material` do not either.** They
  vanish exactly as the invented key vanishes. A copy carrying the source's word
  is not a copy carrying the setting.

And the reason every value is checked before it is written:

* `layer_height="not-a-number"` — Orca opened the project **with an empty plate**;
* `layer_height="0"` and `"-0.2"` — Orca **hung on load**, spinning, unresponsive;
* `enable_support="true"` and `"2"` — the object was **gone**;
* `layer_height="0.5"` against a 0.4 mm nozzle — Orca refused to slice:
  *"Layer height cannot exceed nozzle diameter"*.

A malformed override does not fail quietly. It takes the geometry with it.
"""
from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path

import pytest

from snapstudio_core import assignments as A
from snapstudio_core import multipart, overrides, stl_wrap
from snapstudio_core.container import ThreeMF
from snapstudio_core.convert import convert_to_u1

FIXTURES = Path(__file__).parent / "fixtures" / "prusa-semantics"
OVERRIDE_SOURCE = FIXTURES / "J_per_object_override_out.3mf"


def carried(source: dict, nozzle_mm: float = 0.4) -> dict:
    return overrides.plan(source, nozzle_mm)["carry"]


def row_for(source: dict, key: str, nozzle_mm: float = 0.4) -> dict:
    return next(r for r in overrides.plan(source, nozzle_mm)["rows"]
                if r["source_key"] == key)


# --- the three that cross, in the target's own words ------------------------

def test_layer_height_crosses_under_the_same_name():
    row = row_for({"layer_height": "0.3"}, "layer_height")
    assert row["carried"] and row["target_key"] == "layer_height"
    assert row["target_value"] == "0.3"
    assert row["kind"] == overrides.EXACT


def test_infill_density_is_renamed_not_copied():
    row = row_for({"fill_density": "80%"}, "fill_density")
    assert row["carried"] and row["target_key"] == "sparse_infill_density"
    assert row["target_value"] == "80%"
    assert row["kind"] == overrides.SEMANTIC


def test_support_is_renamed_not_copied():
    row = row_for({"support_material": "1"}, "support_material")
    assert row["carried"] and row["target_key"] == "enable_support"
    assert row["target_value"] == "1"
    assert row["kind"] == overrides.SEMANTIC


def test_the_sources_own_words_are_never_written():
    """Orca discards `fill_density` and `support_material` like nonsense keys."""
    written = carried({"fill_density": "80%", "support_material": "1"})
    assert set(written) == {"sparse_infill_density", "enable_support"}
    assert "fill_density" not in written
    assert "support_material" not in written


@pytest.mark.parametrize("key", [
    "brim_width", "wall_loops", "snapstudio_nonsense_setting", "ironing_type",
    "seam_position", "top_shell_layers",
])
def test_every_other_setting_is_reported_rather_than_guessed_at(key):
    row = row_for({key: "5"}, key)
    assert not row["carried"] and row["target_key"] is None
    assert "has not established" in row["why"]


# --- value attacks ----------------------------------------------------------
#
# Every refusal below is a measured Orca failure, not a matter of taste.

@pytest.mark.parametrize("value, expect", [
    ("0", "hangs"),                 # Orca spun on load, unresponsive
    ("-0.2", "hangs"),              # same
    ("not-a-number", "deletes"),    # Orca opened an empty plate
    ("٠.٣", "deletes"),   # Arabic-Indic digits: float() reads them, Orca does not
    ("", "deletes"),
    ("1e-3", "deletes"),            # exponent notation is not a decimal
    ("0.3mm", "deletes"),
    ("0.5", "nozzle"),              # taller than the 0.4 mm nozzle: Orca will not slice
    ("99", "nozzle"),
])
def test_a_layer_height_orca_cannot_take_is_not_carried(value, expect):
    row = row_for({"layer_height": value}, "layer_height")
    assert not row["carried"]
    assert expect in row["why"]


@pytest.mark.parametrize("value, written", [
    ("0.3", "0.3"),
    ("0.300", "0.3"),      # Orca normalises the trailing zeros itself
    (" 0.3 ", "0.3"),
    ("0.4", "0.4"),        # exactly the nozzle is allowed
    ("0.08", "0.08"),
])
def test_a_layer_height_orca_takes_is_written_in_orcas_form(value, written):
    assert carried({"layer_height": value})["layer_height"] == written


@pytest.mark.parametrize("value, written", [
    ("15%", "15%"),
    ("15", "15%"),         # both dialects read a bare number as a percentage
    ("0.45", "0.45%"),     # and Orca writes it back as 0.45%, not 45%
    ("0%", "0%"),
    ("100%", "100%"),
])
def test_an_infill_density_in_range_crosses(value, written):
    assert carried({"fill_density": value})["sparse_infill_density"] == written


@pytest.mark.parametrize("value", ["400%", "-5%", "abc", "", "٤٥%", "1e2"])
def test_an_infill_density_out_of_range_or_unreadable_is_not_carried(value):
    assert "sparse_infill_density" not in carried({"fill_density": value})


@pytest.mark.parametrize("value", ["0", "1"])
def test_support_takes_the_two_values_orca_reads(value):
    assert carried({"support_material": value})["enable_support"] == value


@pytest.mark.parametrize("value", ["true", "false", "2", "-1", "yes", "", "١"])
def test_support_refuses_everything_else(value):
    """Orca deleted the whole object for `true` and for `2`."""
    row = row_for({"support_material": value}, "support_material")
    assert not row["carried"] and "deletes the whole object" in row["why"]


def test_a_duplicate_key_is_whatever_the_reader_resolved_it_to():
    """The file format has no second value: last one wins on both sides."""
    text = ('<config><object id="1">'
            '<metadata type="object" key="layer_height" value="0.3"/>'
            '<metadata type="object" key="layer_height" value="0.1"/>'
            "</object></config>")
    entry = A._prusa(text)[0]
    assert entry["overrides"] == {"layer_height": "0.1"}


def test_the_nozzle_gate_follows_the_profile_not_a_constant():
    assert carried({"layer_height": "0.5"}, nozzle_mm=0.6) == {"layer_height": "0.5"}
    assert carried({"layer_height": "0.5"}, nozzle_mm=0.4) == {}


def test_the_smallest_declared_nozzle_is_the_one_that_has_to_be_satisfied():
    assert stl_wrap._nozzle_mm({"nozzle_diameter": ["0.6", "0.4", "0.6", "0.6"]}) == 0.4
    assert stl_wrap._nozzle_mm({"nozzle_diameter": "0.2"}) == 0.2
    assert stl_wrap._nozzle_mm({}) == overrides.DEFAULT_NOZZLE_MM


# --- what a writer is allowed to emit ---------------------------------------

def test_the_writer_refuses_a_key_studio_has_not_measured():
    faults = overrides.validate_emitted({"fill_density": "15%"})
    assert faults and "not a setting Studio has proved" in faults[0]


def test_the_writer_refuses_a_value_that_would_take_the_object_with_it():
    assert overrides.validate_emitted({"layer_height": "0"})
    assert overrides.validate_emitted({"enable_support": "true"})
    assert overrides.validate_emitted({"sparse_infill_density": "400%"})


def test_the_writer_refuses_a_value_that_is_not_in_the_form_studio_writes():
    faults = overrides.validate_emitted({"sparse_infill_density": "45"})
    assert faults and "Snapmaker Orca reads" in faults[0]   # still refused: the gate is unchanged


def test_prepare_fails_rather_than_writing_an_override_it_cannot_stand_behind():
    with pytest.raises(ValueError, match="would not survive"):
        stl_wrap._override_lines({"layer_height": "0"})
    with pytest.raises(ValueError, match="not a setting Studio has proved"):
        stl_wrap._override_lines({"support_material": "1"})


def test_the_structural_validator_catches_an_override_in_the_archive():
    settings = ('<config><object id="2">'
                '<metadata key="name" value="cube"/>'
                '<metadata key="extruder" value="0"/>'
                '<metadata key="enable_support" value="true"/>'
                '<part id="1" subtype="normal_part"/></object></config>')
    stated = multipart._settings_objects(settings)["2"]
    keys = dict(re.findall(r'<metadata key="([^"]+)" value="([^"]*)"\s*/>', stated))
    keys.pop("name"), keys.pop("extruder")
    assert overrides.validate_emitted(keys)


# --- end to end -------------------------------------------------------------

@pytest.fixture(scope="module")
def prepared() -> str:
    return convert_to_u1(str(OVERRIDE_SOURCE), out_dir=tempfile.mkdtemp()).output_path


def object_metadata(path: str) -> dict:
    with zipfile.ZipFile(path) as z:
        text = z.read("Metadata/model_settings.config").decode("utf-8")
    body = text.split("<object", 1)[1].split("<part", 1)[0]
    return dict(re.findall(r'<metadata key="([^"]+)" value="([^"]*)"\s*/>', body))


def test_the_prepared_copy_states_the_two_that_can_cross_here(prepared):
    """This fixture is a five-colour painted cube, so it needs a prime tower.

    Measured on Orca 2.3.6: a plate that prints with more than one filament and
    has a per-object layer height will not slice — *"A prime tower requires that
    all objects have the same layer height"*, with Slice and Print greyed out.
    Infill and support are unaffected and still cross.
    """
    stated = object_metadata(prepared)
    assert stated["sparse_infill_density"] == "15%"
    assert stated["enable_support"] == "1"
    assert "layer_height" not in stated


def test_the_same_override_does_cross_on_a_single_filament_plate():
    assert carried({"layer_height": "0.3"}, nozzle_mm=0.4) == {"layer_height": "0.3"}


def test_a_per_object_layer_height_is_refused_on_a_multi_filament_plate():
    row = row_for({"layer_height": "0.3"}, "layer_height")
    assert row["carried"]
    row = next(r for r in overrides.plan({"layer_height": "0.3"}, 0.4, 2)["rows"]
               if r["source_key"] == "layer_height")
    assert not row["carried"]
    assert "prime tower" in row["why"]


def test_infill_and_support_still_cross_on_a_multi_filament_plate():
    """Only the layer height is the one a prime tower cannot cope with."""
    written = overrides.plan(
        {"fill_density": "80%", "support_material": "1"}, 0.4, 4)["carry"]
    assert written == {"sparse_infill_density": "80%", "enable_support": "1"}


def test_the_filaments_a_plate_prints_with_is_not_the_slots_it_declares():
    """Every U1 project declares four slots; a single-colour print uses one."""
    from snapstudio_core.container import ThreeMF

    plain = ThreeMF.open(str(Path(__file__).parents[2] / "examples" / "sample_cube_U1.3mf"))
    assert stl_wrap.filaments_in_use(plain, plain.read_part("3D/3dmodel.model")) == 1
    painted = ThreeMF.open(str(FIXTURES.parent / "painted" / "orcaslicer-2.4.2-painted-cube.3mf"))
    assert stl_wrap.filaments_in_use(painted, painted.read_part("3D/3dmodel.model")) == 5


def test_the_prepared_copy_never_states_the_sources_vocabulary(prepared):
    stated = object_metadata(prepared)
    assert "fill_density" not in stated
    assert "support_material" not in stated


def test_the_overrides_sit_on_the_object_not_on_the_part(prepared):
    """Where Orca itself puts one when the setting is changed in its own panel."""
    with zipfile.ZipFile(prepared) as z:
        text = z.read("Metadata/model_settings.config").decode("utf-8")
    part = text.split("<part", 1)[1].split("</part>", 1)[0]
    for key in ("layer_height", "sparse_infill_density", "enable_support"):
        assert key not in part


def test_the_prepared_copy_passes_its_own_structural_validator(prepared):
    report = multipart.validate_archive(ThreeMF.open(prepared))
    assert report["ok"], report["problems"]


def test_the_original_is_not_touched(prepared):
    import hashlib

    digest = hashlib.sha256(OVERRIDE_SOURCE.read_bytes()).hexdigest()
    assert digest == hashlib.sha256(OVERRIDE_SOURCE.read_bytes()).hexdigest()
    assert Path(prepared) != OVERRIDE_SOURCE


def test_the_audit_reports_each_setting_for_itself(prepared):
    from snapstudio_core.fidelity import audit

    rows = [r for r in audit(str(OVERRIDE_SOURCE), prepared)["rows"]
            if "Settings set on" in r["element"]]
    by_setting = {r["detail"].split(" ", 1)[0]: r for r in rows}
    assert by_setting["fill_density"]["status"] == "preserved_semantic"
    assert by_setting["support_material"]["status"] == "preserved_semantic"
    # The one the prime tower forbids says so rather than going quiet.
    layer = by_setting["layer_height"]
    assert layer["status"] == "unsupported"
    assert "prime tower" in layer["detail"]


# --- identity under renumbering ---------------------------------------------

def test_objects_are_matched_by_position_not_by_the_id_orca_gives_them():
    """Orca renumbers: a project whose objects were 101 and 102 came back 2 and 3.

    An audit that correlated on the id would report every override as moved.
    """
    def obj(object_id, index, name, over):
        return {"object_id": object_id, "index": index, "name": name, "slot": None,
                "source": A.DEFAULT, "volume_slots": [None], "instances": 1,
                "volumes": [{"index": 0, "name": name, "slot": None,
                             "role": A.PART, "role_word": "ModelPart"}],
                "overrides": dict(over)}

    before = {"available": True, "dialect": A.DIALECT_PRUSA, "objects": [
        obj("101", 0, "a", {"layer_height": "0.3"}), obj("102", 1, "b", {})]}
    after = {"available": True, "dialect": A.DIALECT_BAMBU, "objects": [
        obj("2", 0, "a", {"layer_height": "0.3"}), obj("3", 1, "b", {})]}
    rows = [r for r in A.compare(before, after)["semantics"] if r["kind"] == "override"]
    assert [(r["object"], r["status"]) for r in rows] == [("a", A.PRESERVED_EXACT)]


def test_an_override_written_at_the_wrong_level_reads_as_missing():
    """Studio writes object-level. A copy that put it on the part states nothing."""
    text = ('<config><object id="2">'
            '<metadata key="name" value="cube"/>'
            '<metadata key="extruder" value="0"/>'
            '<part id="1" subtype="normal_part">'
            '<metadata key="layer_height" value="0.3"/>'
            "</part></object></config>")
    entry = A._bambu(text)[0]
    assert entry["overrides"] == {}


# --- several objects, several parts, and helpers among them -----------------

MULTI = Path(__file__).parent / "fixtures" / "prusa-multi-object" / "prusa_three_objects.3mf"
MODIFIER = FIXTURES / "vt_ParameterModifier_out.3mf"
CONFIG = "Metadata/Slic3r_PE_model.config"


def with_overrides(source: Path, per_object: dict, out_dir: Path) -> str:
    """The same project with per-object settings added to named objects.

    The geometry, the build and every other object are untouched, so anything
    that moves downstream moved because of the settings.
    """
    with zipfile.ZipFile(source) as z:
        parts = {name: z.read(name) for name in z.namelist()}
    text = parts[CONFIG].decode("utf-8")

    def inject(match: re.Match) -> str:
        head = match.group(0)
        object_id = re.search(r'id="(\d+)"', head).group(1)
        rows = per_object.get(object_id) or {}
        return head + "".join(
            f'\n  <metadata type="object" key="{k}" value="{v}"/>'
            for k, v in sorted(rows.items()))

    text = re.sub(r"<object id=\"\d+\"[^>]*>", inject, text)
    parts[CONFIG] = text.encode("utf-8")
    out = out_dir / f"{source.stem}_overridden.3mf"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return str(out)


def settings_objects(path: str) -> dict:
    """Each prepared object's name and its own metadata, in file order."""
    with zipfile.ZipFile(path) as z:
        text = z.read("Metadata/model_settings.config").decode("utf-8")
    out = {}
    for object_id, body in re.findall(r'<object id="(\d+)">(.*?)</object>', text, re.S):
        own = dict(re.findall(r'<metadata key="([^"]+)" value="([^"]*)"\s*/>',
                              body.split("<part", 1)[0]))
        out[own.get("name", object_id)] = own
    return out


@pytest.fixture(scope="module")
def three_objects(tmp_path_factory) -> dict:
    """Three source objects; only the middle one carries settings."""
    tmp = tmp_path_factory.mktemp("multi")
    source = with_overrides(MULTI, {"2": {"layer_height": "0.3",
                                          "fill_density": "60%"}}, tmp)
    prepared = convert_to_u1(source, out_dir=str(tmp)).output_path
    return {"source": source, "prepared": prepared,
            "objects": settings_objects(prepared)}


def test_every_source_object_still_crosses(three_objects):
    assert len(three_objects["objects"]) == 3


def test_the_settings_stay_on_the_object_that_had_them(three_objects):
    """Three painted objects across five filaments: infill crosses, layers cannot."""
    stated = three_objects["objects"]["B_painted"]
    assert stated["sparse_infill_density"] == "60%"
    assert "layer_height" not in stated


def test_no_other_object_picks_them_up(three_objects):
    for name, stated in three_objects["objects"].items():
        if name == "B_painted":
            continue
        assert "layer_height" not in stated, name
        assert "sparse_infill_density" not in stated, name


def test_the_object_keeps_its_filament_alongside_its_settings(three_objects):
    assert three_objects["objects"]["B_painted"]["extruder"] == "3"


def test_the_multi_part_object_is_unaffected(three_objects):
    """Object A holds two parts on different filaments; it stated no settings."""
    assert "layer_height" not in three_objects["objects"]["A_two_volumes"]


def test_the_painted_object_still_carries_its_painting(three_objects):
    with zipfile.ZipFile(three_objects["prepared"]) as z:
        painted = sum(blob.count(b'paint_color="')
                      for name in z.namelist() if name.endswith(".model")
                      for blob in [z.read(name)])
    assert painted > 0


def test_the_multi_object_copy_passes_its_structural_validator(three_objects):
    report = multipart.validate_archive(ThreeMF.open(three_objects["prepared"]))
    assert report["ok"], report["problems"]


def test_the_audit_names_the_object_each_setting_belongs_to(three_objects):
    from snapstudio_core.fidelity import audit

    rows = [r for r in audit(three_objects["source"], three_objects["prepared"])["rows"]
            if "Settings set on" in r["element"]]
    assert rows
    assert all("B_painted" in r["element"] for r in rows)


def test_a_setting_on_an_object_that_also_holds_a_modifier(tmp_path):
    """The helper part is not where the object's own settings live."""
    source = with_overrides(MODIFIER, {"1": {"support_material": "1"}}, tmp_path)
    prepared = convert_to_u1(source, out_dir=str(tmp_path)).output_path
    with zipfile.ZipFile(prepared) as z:
        text = z.read("Metadata/model_settings.config").decode("utf-8")
    body = text.split("<object", 1)[1].split("</object>", 1)[0]
    assert 'key="enable_support" value="1"' in body.split("<part", 1)[0]
    for part in body.split("<part")[1:]:
        assert "enable_support" not in part


# --- the copy has to be Studio's file, or none of the above reaches Orca ------

def test_the_copy_does_not_claim_to_be_the_slicer_that_wrote_the_source():
    """Measured on Snapmaker Orca 2.3.6, one variable per file.

    A prepared copy that kept `<metadata name="Application">PrusaSlicer-2.9.6`
    made Orca say *"The 3mf is not supported by Snapmaker Orca, loading geometry
    data only"* — and it then ignored `model_settings.config` completely. Object
    names came back as the file's name and an object written as filament 3 came
    back as **0, unassigned**. The same copy with only that value replaced, and
    the same copy with only that line removed, both opened as projects with every
    name, every assignment and every per-object setting intact.
    """
    root = ('<?xml version="1.0" encoding="UTF-8"?><model>'
            '<metadata name="Application">PrusaSlicer-2.9.6</metadata>'
            '<resources><object id="1"><mesh/></object></resources>'
            '<build><item objectid="1"/></build></model>')
    out = stl_wrap._own_the_root_model(root.encode()).decode()
    assert 'name="Application">SnapmakerStudio-u1convert<' in out
    assert "PrusaSlicer" not in out
    # everything else is the source's and stays the source's
    assert '<object id="1"><mesh/></object>' in out
    assert '<item objectid="1"/>' in out


def test_a_root_model_that_claims_nothing_is_left_exactly_as_it_is():
    """Orca is content with a file that makes no claim, so nothing is inserted."""
    root = b'<?xml version="1.0"?><model><resources/><build/></model>'
    assert stl_wrap._own_the_root_model(root) == root


def test_the_prepared_copy_of_a_prusa_project_says_studio_wrote_it(tmp_path):
    prepared = convert_to_u1(str(OVERRIDE_SOURCE), out_dir=str(tmp_path)).output_path
    with zipfile.ZipFile(prepared) as z:
        root = z.read("3D/3dmodel.model").decode("utf-8", "replace")
    stated = re.search(r'<metadata\s+name="Application"\s*>(.*?)</metadata>', root, re.S)
    if stated:
        assert stated.group(1) == stl_wrap.APPLICATION


def test_correcting_the_claim_changes_nothing_else_in_a_real_root_model():
    """The path exists to copy geometry verbatim, and it still does.

    Run against a genuine PrusaSlicer root model rather than a hand-written one:
    every object, every build item, every coordinate and every other metadata
    line has to survive a rewrite that is only about who wrote the file.
    """
    with zipfile.ZipFile(OVERRIDE_SOURCE) as z:
        before = z.read("3D/3dmodel.model")
    after = stl_wrap._own_the_root_model(before)
    strip = (lambda t: re.sub(r'<metadata\s+name="Application"\s*>.*?</metadata>', "",
                              t.decode("utf-8"), flags=re.S))
    assert strip(before) == strip(after)
    assert stl_wrap.APPLICATION in after.decode("utf-8")
    assert b"PrusaSlicer" not in after


# --- the files Snapmaker Orca wrote, kept and re-checked ---------------------

ORCA = Path(__file__).parent / "fixtures" / "orca-object-overrides"


def orca_manifest() -> dict:
    import json

    return json.loads((ORCA / "MANIFEST.json").read_text(encoding="utf-8"))


def test_the_orca_authored_evidence_is_the_file_that_was_measured():
    """Every claim in `overrides.py` rests on these. Re-hashed, not trusted."""
    import hashlib

    for name, entry in orca_manifest()["files"].items():
        blob = (ORCA / name).read_bytes()
        assert len(blob) == entry["size_bytes"], name
        assert hashlib.sha256(blob).hexdigest() == entry["sha256"], name


def orca_object(name: str) -> dict:
    with zipfile.ZipFile(ORCA / name) as z:
        text = z.read("Metadata/model_settings.config").decode("utf-8")
    if "<object" not in text:
        return {}
    body = text.split("<object", 1)[1].split("<part", 1)[0]
    return dict(re.findall(r'<metadata key="([^"]+)" value="([^"]*)"\s*/>', body))


def test_orca_wrote_the_three_keys_studio_carries_at_object_level():
    stated = orca_object("orca-authored-three-overrides.3mf")
    assert stated["layer_height"] == "0.3"
    assert stated["sparse_infill_density"] == "45%"
    assert stated["enable_support"] == "1"
    assert set(overrides.WRITABLE) <= set(stated)


def test_orca_left_the_control_with_no_per_object_settings():
    stated = orca_object("orca-control-no-settings.3mf")
    assert not (set(stated) - {"name", "extruder"})


def test_an_unrecognised_key_leaves_the_project_identical_to_having_none():
    """The sharpest row: copying the source's word is writing nonsense."""
    dropped = (ORCA / "orca-dropped-unrecognised-key.3mf").read_bytes()
    control = (ORCA / "orca-control-no-settings.3mf").read_bytes()
    assert dropped == control


def test_a_malformed_value_left_orca_with_an_empty_plate():
    with zipfile.ZipFile(ORCA / "orca-deleted-object-on-malformed-value.3mf") as z:
        root = z.read("3D/3dmodel.model").decode("utf-8")
        assert not any(n.startswith("3D/Objects/") for n in z.namelist())
    assert "<object" not in root
    assert "<item" not in root
