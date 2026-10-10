"""Release correction: Studio must not express more confidence than it has.

Four claims, each checked through the real producers (service entry points), on
fixtures built at test time from the committed Bambu Studio-authored base project
(no third-party model file is committed):

1. A multi-plate project is never reported as "every object is inside".
2. Preflight's bed check on such a project is unknown, and Ready Now does not
   treat it as ready.
3. The Doctor's READY action carries the unresolved-placement note.
4. Use Studio's U1 starter settings (Recommended) says when it drops the creator's
   supports, and no report says the creator's values are kept where they are not.
"""
from __future__ import annotations

import json
import os
import re
import zipfile

import pytest

from snapstudio_api import service
from snapstudio_core import fingerprint, plate_placement
from snapstudio_core import preflight as pf
from snapstudio_core import readiness as rd
from snapstudio_core.container import ThreeMF
from snapstudio_core.filaments import PER_FILAMENT_KEYS
from tests.test_readiness import PROJECT, printer, spool, traits

HERE = os.path.dirname(__file__)
BASE = os.path.join(HERE, "fixtures", "painted", "bambustudio-2.08.02.61-authored.3mf")

MODEL = "3D/3dmodel.model"
MODEL_SETTINGS = "Metadata/model_settings.config"
SETTINGS = "Metadata/project_settings.config"

# Bambu H2C-class bed, and the plate stride the authoring slicer uses for it
# (bed width x 1.2). The second plate's object sits one stride to the right.
BED_W, BED_D = 330, 320
STRIDE = 396

NOTE = ("Each plate fits on its own, but Studio cannot check where the plates sit. "
        "Open the project in Snapmaker Orca and use Arrange all plates before slicing.")


def build(tmp_path, name="two-plate.3mf", *, plates=2, plate_json=0, supports=False,
          painted_supports=False, source_declares_supports=True):
    """The base project with `plates` plates, one slab each, at Bambu-stride offsets."""
    out = tmp_path / name
    with zipfile.ZipFile(BASE) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == MODEL:
                text = data.decode("utf-8")
                objects, items = "", ""
                for n in range(1, plates):
                    oid = 2 + n
                    objects += (f'  <object id="{oid}" type="model"><components>'
                                '<component p:path="/3D/Objects/object_1.model" objectid="1" '
                                'transform="1 0 0 0 1 0 0 0 1 0 0 0"/></components></object>\n')
                    items += (f'  <item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 '
                              f'{100 + STRIDE * n} 100 4" printable="1"/>\n')
                text = text.replace(" </resources>", objects + " </resources>")
                text = text.replace(" </build>", items + " </build>")
                data = text.encode("utf-8")
            elif item.filename == MODEL_SETTINGS:
                text = data.decode("utf-8")
                block = re.search(r'  <object id="2">.*?\n  </object>\n', text, re.S).group(0)
                objs, pls = "", ""
                for n in range(1, plates):
                    oid = 2 + n
                    objs += block.replace('id="2"', f'id="{oid}"')
                    pls += (f'  <plate>\n    <metadata key="plater_id" value="{n + 1}"/>\n'
                            '    <metadata key="locked" value="false"/>\n'
                            f'    <model_instance>\n      <metadata key="object_id" value="{oid}"/>\n'
                            '      <metadata key="instance_id" value="0"/>\n'
                            '    </model_instance>\n  </plate>\n')
                text = text.replace("  <plate>", objs + "  <plate>", 1)
                text = text.replace("  <assemble>", pls + "  <assemble>", 1)
                data = text.encode("utf-8")
            elif item.filename == SETTINGS:
                cfg = json.loads(data)
                # Four filaments, as a U1-shaped project has, so a prepared copy is
                # internally consistent and the Doctor can judge it on its own merits.
                for key in PER_FILAMENT_KEYS:
                    if isinstance(cfg.get(key), list) and cfg[key]:
                        cfg[key] = (cfg[key] + [cfg[key][-1]] * 4)[:4]
                cfg["flush_volumes_matrix"] = ["0"] * 16
                cfg["printable_area"] = ["0x0", f"{BED_W}x0", f"{BED_W}x{BED_D}", f"0x{BED_D}"]
                if supports:
                    cfg["enable_support"] = "1"
                    cfg["support_type"] = "tree(manual)"
                    if source_declares_supports:
                        cfg["different_settings_to_system"] = [
                            "enable_support;support_type", "", "", "", ""]
                data = json.dumps(cfg, indent=4).encode("utf-8")
            elif item.filename == "3D/Objects/object_1.model" and painted_supports:
                data = data.replace(b'<triangle v1="4" v2="5" v3="6"/>',
                                    b'<triangle v1="4" v2="5" v3="6" paint_supports="4"/>')
            dst.writestr(item, data)
        for n in range(1, plate_json + 1):
            dst.writestr(f"Metadata/plate_{n}.json", "{}")
    return str(out)


def convert(path, mode, tmp_path):
    out_dir = tmp_path / f"out-{mode}"
    r = service.convert(path, out_dir=str(out_dir), prepare_mode=mode)
    assert r["validated_ok"], r["errors"]
    return r


# --- 1. the plate count and the placement card ------------------------------------

@pytest.mark.parametrize("plate_json", [0, 1])
def test_plate_count_comes_from_the_plates_the_project_declares(tmp_path, plate_json):
    path = build(tmp_path, plate_json=plate_json)  # 2 plates, fewer than 2 plate_N.json
    assert fingerprint.compute_fingerprint(ThreeMF.open(path)).plate_count == 2
    assert service.doctor(path)["plate_count"] == 2


def test_plate_count_falls_back_to_the_slice_cache_without_plate_records(tmp_path):
    path = tmp_path / "no-plates.3mf"
    with zipfile.ZipFile(BASE) as src, zipfile.ZipFile(path, "w") as dst:
        for item in src.infolist():
            if item.filename != MODEL_SETTINGS:
                dst.writestr(item, src.read(item.filename))
        dst.writestr("Metadata/plate_1.json", "{}")
        dst.writestr("Metadata/plate_2.json", "{}")
    assert fingerprint.compute_fingerprint(ThreeMF.open(str(path))).plate_count == 2


def test_multi_plate_placement_is_never_every_object_inside(tmp_path):
    check = service.placement_check(build(tmp_path))
    assert check["available"] and check["plate_count"] == 2
    assert check["off_plate"] == []           # each plate fits on its own...
    assert check["placement_established"] is False
    assert check["summary"] == NOTE            # ...and Studio says what it cannot check
    assert "inside" not in check["summary"].lower()


def test_single_plate_placement_is_still_established(tmp_path):
    check = service.placement_check(build(tmp_path, "one.3mf", plates=1))
    assert check["plate_count"] == 1 and check["placement_established"] is True
    assert "sits inside" in check["summary"]


# --- 2. preflight and Ready Now ----------------------------------------------------

def _prepared_multi_plate(tmp_path):
    out = convert(build(tmp_path), "preserve", tmp_path)["output_path"]
    return out


def test_preflight_bed_fit_is_unknown_for_multi_plate_with_a_printer(tmp_path):
    path = _prepared_multi_plate(tmp_path)
    bed = {"min_x": 0.0, "min_y": 0.0, "max_x": 270.0, "max_y": 270.0}
    placement = plate_placement.assess(path, bed=bed, bed_name="this printer's")
    check = next(c for c in pf.evaluate(traits(), printer([spool()]), placement)["checks"]
                 if c["id"] == "bed.fit")
    assert check["result"] == pf.UNKNOWN
    assert check["confidence"] == pf.INFORMATIONAL
    assert "Arrange all plates" in check["action"]
    assert "Nothing is placed off the plate" not in json.dumps(check)


def test_preflight_bed_fit_stays_ok_for_a_single_plate_project(tmp_path):
    one = convert(build(tmp_path, "one.3mf", plates=1), "preserve", tmp_path)["output_path"]
    bed = {"min_x": 0.0, "min_y": 0.0, "max_x": 270.0, "max_y": 270.0}
    placement = plate_placement.assess(one, bed=bed)
    check = next(c for c in pf.evaluate(traits(), printer([spool()]), placement)["checks"]
                 if c["id"] == "bed.fit")
    assert check["result"] == pf.OK


def test_ready_now_does_not_call_a_multi_plate_project_ready(tmp_path):
    bed = {"min_x": 0.0, "min_y": 0.0, "max_x": 270.0, "max_y": 270.0}
    p = printer([spool()])

    def bucket(path):
        placement = plate_placement.assess(path, bed=bed, bed_name="this printer's")
        pre = pf.evaluate(traits(), p, placement)
        return rd.classify_project(PROJECT, traits(), p, pre, "ok")

    one = convert(build(tmp_path, "one.3mf", plates=1), "preserve", tmp_path)["output_path"]
    assert bucket(one)["bucket"] == rd.READY_NOW           # control: the same flow, one plate
    multi = bucket(_prepared_multi_plate(tmp_path))
    assert multi["bucket"] == rd.CANT_DETERMINE            # unresolved, not blocked, not ready
    assert "Fits the printer's bed" in multi["top_reason"]


# --- 3. the Doctor ------------------------------------------------------------------

def test_doctor_ready_carries_the_unresolved_placement_note_for_multi_plate(tmp_path):
    prepared = _prepared_multi_plate(tmp_path)
    d = service.doctor(prepared)
    assert d["verdict"] == "READY" and d["plate_count"] == 2
    assert d["recommended_action"].startswith(
        "Ready for Snapmaker U1 - open it in Snapmaker Orca and slice.")
    assert "Arrange all plates" in d["recommended_action"]
    assert "has not checked where they sit" in d["recommended_action"]


def test_doctor_ready_for_a_single_plate_project_is_unchanged(tmp_path):
    one = convert(build(tmp_path, "one.3mf", plates=1), "preserve", tmp_path)["output_path"]
    d = service.doctor(one)
    assert d["verdict"] == "READY"
    assert d["recommended_action"] == "Ready for Snapmaker U1 - open it in Snapmaker Orca and slice."


# --- 4. Recommended mode and the creator's supports ---------------------------------

def test_recommended_says_it_does_not_keep_the_creators_supports(tmp_path):
    src = build(tmp_path, supports=True, painted_supports=True)
    summary = convert(src, "recommended", tmp_path)["settings_summary"]
    note = summary["supports_note"]
    assert note.startswith("Supports: the creator turned supports on. This mode does not keep them;")
    assert "Snapmaker Orca will open with supports off" in note
    assert "Support tab" in note and "Preserve creator settings" in note
    assert "painted support areas" in note


def test_recommended_does_not_mention_painted_supports_that_do_not_exist(tmp_path):
    summary = convert(build(tmp_path, supports=True), "recommended", tmp_path)["settings_summary"]
    assert "painted" not in summary["supports_note"]


def test_the_note_is_computed_from_the_config_not_asserted(tmp_path):
    # Supports off in the source: nothing to say, even in Recommended.
    off = convert(build(tmp_path, "off.3mf"), "recommended", tmp_path)["settings_summary"]
    assert "supports_note" not in off


def test_preserve_keeps_the_supports_and_says_nothing_about_dropping_them(tmp_path):
    src = build(tmp_path, supports=True, painted_supports=True)
    r = convert(src, "preserve", tmp_path)
    assert "supports_note" not in r["settings_summary"]
    with zipfile.ZipFile(r["output_path"]) as z:
        cfg = json.loads(z.read(SETTINGS))
    assert cfg["enable_support"] == "1"
    assert "enable_support" in cfg["different_settings_to_system"][0]  # Orca will use it


def test_recommended_still_writes_what_it_always_wrote_for_supports(tmp_path):
    # Disclosure only: Recommended's output is not changed to re-declare the support keys.
    r = convert(build(tmp_path, supports=True), "recommended", tmp_path)
    with zipfile.ZipFile(r["output_path"]) as z:
        cfg = json.loads(z.read(SETTINGS))
    assert "enable_support" not in cfg["different_settings_to_system"][0]


def test_validation_report_only_says_values_are_kept_where_that_is_true(tmp_path):
    src = build(tmp_path, supports=True)
    rec = convert(src, "recommended", tmp_path)["output_path"]
    pres = convert(src, "preserve", tmp_path)["output_path"]

    def changes(path, mode):
        return " | ".join(service.report(path, mode)["changes"])

    assert "your setting values are kept" in changes(pres, "preserve")
    rec_text = changes(rec, "recommended")
    assert "values are kept" not in rec_text
    assert "replaced by Studio's U1 starter settings" in rec_text
    # The file alone does not say how it was prepared: no promise either way.
    unknown = changes(rec, None)
    assert "your setting values are kept" not in unknown
    assert "only when prepared with Preserve creator settings" in unknown
    assert "your setting values are kept" not in changes(pres, None)
