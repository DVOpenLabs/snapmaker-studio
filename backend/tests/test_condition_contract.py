"""The condition contract (#92): every consumer is built from the same condition set, so they cannot disagree.

Verified TOGETHER on real producer output: real first_layer.assess, mm_doctor.assess, toolhead_fit.assess,
failure_patterns.assess + health_score.score, and success_predict.findings. Nothing here is a hand-built Doctor result.
For each case: the Print risk signals card (predict["signals"]), the Intelligence Report findings (risks, risks_found,
biggest_risk, next_action, printer_status) and the printer health result the Printers chip/card use must agree.
"""
import json
import re
from pathlib import Path

from snapstudio_core import conditions as C
from snapstudio_core import failure_patterns as fp
from snapstudio_core import first_layer as fl
from snapstudio_core import health_score as hs
from snapstudio_core import intelligence_report as ir
from snapstudio_core import mm_doctor
from snapstudio_core import success_predict as sp
from snapstudio_core import toolhead_fit as tf

READY = {"klippy_state": "ready", "warnings": [], "failed_components": []}


def _jobs(*statuses, name="other"):
    return [{"filename": f"{name}-{i}.gcode", "status": st} for i, st in enumerate(statuses)]


def _health(statuses, diagnostics=None):
    return hs.score(diagnostics=diagnostics or READY, failures=fp.assess(_jobs(*statuses)))


def _layer(area=80, bed_range=0.3):
    out = fl.assess({"base_area_mm2": area, "min_dim_mm": 8, "width_x_mm": 10, "width_y_mm": 8}, {"height_mm": 20},
                    {"available": True, "range_mm": bed_range, "center_range_mm": bed_range, "corner_spread_mm": 0.1})
    out["available"] = True
    return out


def _status_count(report):
    m = re.fullmatch(r"Answered, (\d+) concerns?", report["printer_status"])
    return int(m.group(1)) if m else 0


def _agree(predict, report, health=None):
    """Cross-consumer agreement for one case."""
    ids = [r["condition"] for r in report["risks"]]
    assert len(ids) == len(set(ids)), "one finding per condition id"
    assert report["risks_found"] == len(report["risks"])
    assert report["biggest_risk"] == (report["risks"][0] if report["risks"] else None)
    if report["risks"]:
        top = report["risks"][0]
        assert report["next_action"] == (top.get("action") or f"Look into: {top['text']}")
    by_id = {r["condition"]: r for r in report["risks"]}
    for sg in (predict or {}).get("signals", []):          # the card is a subset of the report, same severity
        assert sg["id"] in by_id, sg["id"]
        assert by_id[sg["id"]]["level"] == sg["level"], sg["id"]
        if sg["id"] in C.PREDICTOR_ADDS_EVIDENCE:
            assert by_id[sg["id"]]["text"] == sg["title"], sg["id"]
    if health and health.get("available"):                # printer line == health conditions == chip/card input
        assert _status_count(report) == len(health["conditions"]) == len(
            [d for d in health["drivers"] if "no problems" not in d.lower()])
    return by_id


def test_small_base_warn_and_bed_variance_risk():
    layer = _layer()
    predict = sp.findings(readiness={"ready": True}, first_layer=layer)
    report = ir.build(predict=predict, first_layer=layer)
    by_id = _agree(predict, report)
    assert by_id["first-layer-adhesion"]["level"] == "warn" and by_id["first-layer-bed-flatness"]["level"] == "risk"
    assert report["risks_found"] == 3                       # adhesion, bed flatness, orientation: one each, none doubled
    assert report["biggest_risk"]["condition"] == "first-layer-bed-flatness"
    assert "bed leveling" in report["next_action"].lower() and "Small base" not in report["next_action"]


def test_five_colors_with_a_metadata_issue():
    mm = mm_doctor.assess(5, heads=4, heads_known=True, metadata_issues=["filament array mismatch"])
    predict = sp.findings(readiness={"ready": True}, toolfit=tf.assess(5, 4, True))
    report = ir.build(predict=predict, mm=mm)
    by_id = _agree(predict, report)
    assert set(by_id) == {"toolhead-fit", "filament-metadata"}
    assert by_id["toolhead-fit"]["level"] == "risk" and by_id["filament-metadata"]["level"] == "warn"
    assert report["biggest_risk"]["condition"] == "toolhead-fit" and report["next_action"].startswith("Remap")
    assert by_id["filament-metadata"]["action"].startswith("Run repair")   # its own fix, not the colors one


def test_prior_failure_once_with_printer_8_of_10_failed_and_streak_6():
    statuses = ["error"] * 6 + ["completed"] * 2 + ["error"] * 2
    health = _health(statuses)
    predict = sp.findings(readiness={"ready": True}, health=health, prior_failures=1, printer_checked=True)
    report = ir.build(predict=predict, health=health)
    by_id = _agree(predict, report, health)
    assert list(by_id) == ["printer-failure-history"] and report["risks_found"] == 1
    text = by_id["printer-failure-history"]["text"]
    assert "failed 1 time before" in text and "8 of the last 10" in text and "6 prints failed in a row" in text
    assert [s["title"] for s in predict["signals"]] == [text]                 # the card says the same sentence
    assert report["printer_status"] == "Answered, 1 concern" and len(health["conditions"]) == 1


def test_repeat_signal_alone():
    predict = sp.findings(readiness={"ready": True}, prior_failures=2, printer_checked=True)
    report = ir.build(predict=predict)
    by_id = _agree(predict, report)
    assert list(by_id) == ["printer-failure-history"] and by_id["printer-failure-history"]["level"] == "risk"
    assert report["risks_found"] == 1


def test_firmware_warning_only():
    health = _health(["completed"] * 5, diagnostics={**READY, "warnings": ["w"]})
    predict = sp.findings(readiness={"ready": True}, health=health, printer_checked=True)
    report = ir.build(predict=predict, health=health)
    by_id = _agree(predict, report, health)
    assert list(by_id) == ["firmware-warning"] and report["printer_status"] == "Answered, 1 concern"
    assert "nothing concerning" not in health["verdict"].lower()


def test_clean_printer():
    health = _health(["completed"] * 5)
    predict = sp.findings(readiness={"ready": True}, health=health, printer_checked=True)
    report = ir.build(predict=predict, health=health)
    _agree(predict, report, health)
    assert report["risks_found"] == 0 and report["printer_status"] == "Answered, no concerns"
    assert health["conditions"] == [] and "nothing concerning" in health["verdict"].lower()


def test_unverified_spacing_only():
    layer = fl.assess({"base_area_mm2": 2500, "min_dim_mm": 50, "width_x_mm": 50, "width_y_mm": 50}, {"height_mm": 20}, None)
    layer["available"] = True
    predict = sp.findings(readiness={"ready": True}, first_layer=layer, spacing_unverified=True)
    report = ir.build(predict=predict, first_layer=layer, spacing={"status": "unknown"})
    _agree(predict, report)
    assert report["risks_found"] == 0 and report["not_verified"] == ["object spacing"] and report["biggest_risk"] is None
    assert "object spacing" in predict["not_checked"]


def test_merge_never_uses_display_text_for_identity():
    """Same words, different condition ids stay two findings; different words, same id become one."""
    a = C.contribution("toolhead-fit", "warn", "Same words")
    b = C.contribution("filament-metadata", "warn", "Same words")
    assert len(C.merge([a, b])) == 2
    c = C.contribution("toolhead-fit", "risk", "Other words", source="predictor")
    merged = C.merge([a, c])
    assert len(merged) == 1 and merged[0]["level"] == "risk"          # max severity over contributors
    # an id-less finding is its own condition and is never merged
    doc = {"findings": [{"level": "warn", "text": "x"}, {"level": "warn", "text": "x"}]}
    assert len(C.merge(C.doctor_contributions(doc, "Some Doctor"))) == 2


# --- the Printers chip/card read the same health result: a real fixture the desktop tests consume ---
FIXTURE = Path(__file__).resolve().parents[2] / "desktop" / "src" / "lib" / "printerHealth.real.json"


def _fixture():
    return {
        "failures-only-no-warning": _health(["error"] + ["completed"] * 4),
        "failures-and-firmware-warning": _health(["error"] * 6 + ["completed"] * 2 + ["error"] * 2, {**READY, "warnings": ["w"]}),
        "clean": _health(["completed"] * 5),
    }


def test_desktop_printer_health_fixture_is_the_real_producer_output():
    """desktop/src/lib/printerHealth.real.json is generated from the real formatter; regenerate it if this fails
    (py -3.13 -c "import json,tests.test_condition_contract as t; ..." writes it; see the test body)."""
    expected = json.loads(json.dumps(_fixture()))
    if not FIXTURE.exists():
        FIXTURE.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == expected


# --- additions: severity follows the failure pattern, standalone findings, one toolhead source, community fixes ---
def test_failure_severity_follows_the_failure_pattern_and_keeps_the_streak():
    statuses = ["error"] * 6 + ["completed"] * 2 + ["error"] * 2
    assert fp.assess(_jobs(*statuses))["overall_level"] == "risk"       # 80% failed, 6 in a row
    health = _health(statuses)
    assert health["conditions"][0]["level"] == "risk"
    predict = sp.findings(readiness={"ready": True}, health=health, prior_failures=1, printer_checked=True)
    report = ir.build(predict=predict, health=health)
    by_id = _agree(predict, report, health)
    f = by_id["printer-failure-history"]
    assert f["level"] == "risk" and "6 prints failed in a row" in f["text"] and "failed 1 time before" in f["text"]
    assert report["biggest_risk"]["level"] == "risk"
    # a mild history stays a warn
    mild = _health(["error"] + ["completed"] * 4)
    assert fp.assess(_jobs("error", *["completed"] * 4))["overall_level"] != "risk" and mild["conditions"][0]["level"] == "warn"


def test_toolhead_signal_without_a_doctor_finding_is_its_own_finding_not_a_promoted_neighbor():
    """mm_doctor sees 8 toolheads (no colors problem) + a metadata issue; an independent predictor sees 4."""
    mm = mm_doctor.assess(5, heads=8, heads_known=True, metadata_issues=["filament array mismatch"])
    assert [f.get("id") for f in mm["findings"] if f["level"] != "ok"] == ["filament-metadata"]
    predict = sp.findings(readiness={"ready": True}, toolfit=tf.assess(5, 4, True))
    report = ir.build(predict=predict, mm=mm)
    by_id = _agree(predict, report)
    assert set(by_id) == {"filament-metadata", "toolhead-fit"}
    assert by_id["filament-metadata"]["level"] == "warn" and by_id["filament-metadata"]["action"].startswith("Run repair")
    assert by_id["toolhead-fit"]["level"] == "risk" and by_id["toolhead-fit"]["action"].startswith("Remap")
    assert report["biggest_risk"]["condition"] == "toolhead-fit"


def test_service_doctors_share_one_toolhead_count_source(monkeypatch, tmp_path):
    from snapstudio_api import service
    from snapstudio_core import moonraker
    calls = []
    monkeypatch.setattr(moonraker, "capabilities", lambda h, p: (calls.append((h, p)) or {"toolhead_count": 8}))
    assert service._toolhead_count("host", 7125) == (8, True)
    assert service._toolhead_count(None) == (None, False)
    monkeypatch.setattr(moonraker, "capabilities", lambda h, p: (_ for _ in ()).throw(OSError("down")))
    assert service._toolhead_count("host", 7125) == (None, False)
    import inspect
    assert "moonraker.capabilities" not in inspect.getsource(service.mm_doctor)
    assert "moonraker.capabilities" not in inspect.getsource(service.toolhead_fit)


def test_bed_fit_finding_carries_its_own_action_so_next_is_never_look_into():
    from snapstudio_core import bed_fit as bf
    bed = bf.assess({"x": 268, "y": 100, "z": 10}, bed={"x": 270, "y": 270, "z": 270}, bed_known=True, object_count=1, multi_material=False)
    non_ok = [f for f in bed["findings"] if f["level"] != "ok"]
    assert non_ok and all(f.get("action") for f in non_ok)
    report = ir.build(bed_fit=bed)
    assert report["biggest_risk"]["condition"] == "bed-near-full"
    assert report["next_action"] == non_ok[0]["action"] and not report["next_action"].startswith("Look into")


def test_community_fix_needs_a_full_symptom_phrase_and_never_attaches_to_failure_history():
    for statuses, prior in ((["error"] + ["completed"] * 4, 1), (["error"] * 6 + ["completed"] * 2 + ["error"] * 2, 1)):
        health = _health(statuses)
        predict = sp.findings(readiness={"ready": True}, health=health, prior_failures=prior, printer_checked=True)
        report = ir.build(predict=predict, health=health)
        failure = next(r for r in report["risks"] if r["condition"] == "printer-failure-history")
        assert "community" not in failure, failure["text"]
    repeat_only = ir.build(predict=sp.findings(readiness={"ready": True}, prior_failures=1, printer_checked=True))
    assert all("community" not in r for r in repeat_only["risks"])
    # the positive case: a real colors-vs-toolheads risk still gets its entry
    mm = mm_doctor.assess(5, heads=4, heads_known=True)
    colors = ir.build(mm=mm, predict=sp.findings(readiness={"ready": True}, toolfit=tf.assess(5, 4, True)))
    assert "More colours than toolheads" in colors["risks"][0]["community"]["success_pattern"]
    # ...and so does a real out-of-bounds risk, while a number shared with a symptom ("5 colours") means nothing
    from snapstudio_core import bed_fit as bf
    big = ir.build(bed_fit=bf.assess({"x": 300, "y": 100, "z": 10}, bed={"x": 270, "y": 270, "z": 270}, bed_known=True))
    assert "Out of bounds" in big["risks"][0]["community"]["success_pattern"]
