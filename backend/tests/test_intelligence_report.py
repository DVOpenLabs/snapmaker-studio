"""Studio Intelligence Report — the one screen that makes the Doctors a product.

Synthesises every Doctor's output into a single verdict a user grasps in 15s:
will it print, what it costs, what to sell it for, the profit, the biggest risk,
and the next action. The Doctors become evidence behind one Studio Intelligence
Score. Pure synthesis over already-computed dicts — no network here.
"""
import json
import re

from snapstudio_core import intelligence_report as ir


def test_stl_bbox_guard_handles_missing_and_oversized(tmp_path, monkeypatch):
    from snapstudio_core import intelligence
    # missing file -> graceful (None, None), no uncaught OSError (read_bytes guarded)
    assert intelligence._stl_bbox_and_triangles(str(tmp_path / "nope.stl")) == (None, None)
    # oversized -> graceful (None, None)
    import snapstudio_core.geometry as geo
    monkeypatch.setattr(geo, "_MAX_BYTES", 5)
    big = tmp_path / "big.stl"; big.write_bytes(b"x" * 50)
    assert intelligence._stl_bbox_and_triangles(str(big)) == (None, None)


def test_unavailable_with_nothing():
    out = ir.build()
    assert out["available"] is False


_SCORE_KEYS = {"studio_score", "print_success_score", "expected_improvement"}


def test_headline_from_printer_health_and_no_success_percentage():
    out = ir.build(
        predict={"available": True, "signals": []},
        health={"available": True, "score": 90, "grade": "A", "drivers": []},
    )
    assert out["available"] is True
    assert not _SCORE_KEYS & set(out)   # no number: not even the printer's own health figure
    assert out["schema_version"] == "report/2"
    assert not re.search(r"\d\s*(%|/\s*100)", out["verdict"])
    assert out["printer_status"] == "Answered, no concerns"
    assert "printer_compatibility" not in out


def test_money_headline_from_cost_and_profit():
    out = ir.build(
        cost={"available": True, "true_cost": 4.0, "suggested_price": 10.0,
              "margin": 6.0, "margin_pct": 60.0, "currency": "$"},
        profit={"available": True, "profit_per_print": 6.0, "margin_pct": 60.0},
    )
    assert out["cost"] == 4.0
    assert out["suggested_price"] == 10.0
    assert out["margin_pct"] == 60.0


def test_risks_collected_and_biggest_is_highest_severity():
    out = ir.build(
        bed_fit={"available": True, "overall_level": "risk",
                 "findings": [{"level": "risk", "text": "Too big for the bed"}],
                 "fixes": ["Scale to 84%"]},
        mm={"available": True, "overall_level": "warn",
            "findings": [{"level": "warn", "text": "Colour layout needs a swap"}],
            "fixes": ["Remap in Orca"]},
    )
    assert len(out["risks"]) >= 2
    assert out["biggest_risk"]["level"] == "risk"      # risk outranks warn
    assert "bed" in out["biggest_risk"]["text"].lower()
    # recommendations gather the doctors' fixes
    assert any("scale" in r.lower() for r in out["recommendations"])


def test_next_action_when_clean_is_positive():
    out = ir.build(
        predict={"available": True, "signals": []},
        bed_fit={"available": True, "overall_level": "ok", "findings": [], "fixes": []},
    )
    assert out["biggest_risk"] is None
    assert isinstance(out["next_action"], str) and out["next_action"]


def test_doctors_summarised_as_evidence():
    out = ir.build(
        bed_fit={"available": True, "overall_level": "ok", "findings": [], "fixes": []},
        health={"available": True, "score": 90, "grade": "A", "drivers": []},
    )
    names = [d["doctor"] for d in out["supporting"]]
    assert "Project Doctor" in names
    assert "Printer Doctor" in names
    assert all("status" in d for d in out["supporting"])


def test_demo_is_a_complete_compelling_report():
    out = ir.demo()
    assert out["available"] is True and out["is_demo"] is True
    assert not _SCORE_KEYS & set(out)
    assert out["risks_found"] >= 1
    assert out["cost"] and out["suggested_price"]      # money headline present
    assert out["biggest_risk"] is not None             # shows real value (a caught risk)
    assert len(out["recommendations"]) >= 1
    assert len(out["supporting"]) >= 5                  # the Doctors as evidence
    assert "comparison" in out                          # why-not-Orca
    assert out["comparison"]["issues_found"] >= 1


def test_comparison_present_in_every_report():
    out = ir.build(
        bed_fit={"available": True, "overall_level": "risk",
                 "findings": [{"level": "risk", "text": "Too big"}], "fixes": ["Scale"]},
        cost={"available": True, "true_cost": 4.0, "suggested_price": 10.0,
              "margin": 6.0, "margin_pct": 60.0, "currency": "$"},
    )
    comp = out["comparison"]
    assert comp["issues_found"] >= 1
    assert comp["fixes_offered"] >= 1
    assert "orca" in comp["orca_line"].lower()
    assert isinstance(comp["studio_line"], str) and comp["studio_line"]


def test_risks_carry_community_guidance():
    out = ir.build(
        bed_fit={"available": True, "overall_level": "risk",
                 "findings": [{"level": "risk", "text": "out of bounds — too big for the bed"}],
                 "fixes": ["Scale to 84%"]},
    )
    rk = out["biggest_risk"]
    assert "community" in rk
    assert rk["community"]["fix"]
    assert rk["community"]["confidence"] in ("High", "Medium")
    assert rk["community"]["sources"]


def test_no_expected_success_percentage_after_fixes():
    out = ir.build(
        predict={"available": True,
                 "signals": [{"id": "toolhead-fit", "level": "warn", "title": "More colors than toolheads"}]},
        bed_fit={"available": True, "overall_level": "risk",
                 "findings": [{"level": "risk", "text": "out of bounds"}], "fixes": ["Scale"]},
    )
    assert "expected_improvement" not in out
    assert any(r["text"] == "More colors than toolheads" for r in out["risks"])


def test_headline_questions_present():
    out = ir.build(predict={"available": True, "signals": [{"id": "x", "level": "warn", "title": "x"}]},
                   health={"available": True, "score": 70, "grade": "C", "drivers": []})
    for k in ("risks_found", "cost", "suggested_price",
              "margin_pct", "printer_status", "risks", "biggest_risk",
              "recommendations", "next_action", "supporting", "verdict"):
        assert k in out


def test_flawed_file_without_a_reachable_printer_never_gets_a_green_score():
    """The old hero read 100/100 for a file with validation issues and an unreachable printer."""
    out = ir.build(
        predict={"available": True,
                 "signals": [{"id": "design-validation", "level": "warn", "title": "Design validation flagged 6 issues"}]},
        first_layer={"overall_level": "ok", "findings": []},
    )
    assert not _SCORE_KEYS & set(out)
    assert out["risks_found"] == 1
    assert "1 risk found" in out["verdict"] and "Design validation flagged 6 issues" in out["verdict"]
    assert not re.search(r"\d\s*(%|/\s*100)|100", out["verdict"])


def test_spacing_notice_is_not_counted_as_a_risk_found():
    out = ir.build(
        first_layer={"overall_level": "ok", "findings": []},
        spacing={"status": "unknown"},
    )
    assert out["risks_found"] == 0
    assert out["risks"] == [] and out["biggest_risk"] is None   # a limitation, not a finding
    assert out["not_verified"] == ["object spacing"]
    assert "object spacing was not verified" in out["verdict"]


def test_clean_report_does_not_say_the_print_will_succeed():
    out = ir.build(first_layer={"overall_level": "ok", "findings": []})
    assert out["risks_found"] == 0
    assert "not a sign the print will succeed" in out["verdict"]


def test_printer_line_states_what_was_read_never_compatible_and_has_no_health_number():
    healthy = ir.build(
        first_layer={"overall_level": "ok", "findings": []},
        health={"available": True, "score": 100, "grade": "A", "drivers": ["No problems found."],
                "verdict": "Healthy (100/100) \u2014 good to print."},
    )
    concerned = ir.build(
        first_layer={"overall_level": "ok", "findings": []},
        health={"available": True, "drivers": ["firmware warning", "2 of the last 10 prints failed"]},
    )
    silent = ir.build(first_layer={"overall_level": "ok", "findings": []})
    assert healthy["printer_status"] == "Answered, no concerns"
    assert concerned["printer_status"] == "Answered, 2 concerns"
    assert silent["printer_status"] == "Not checked"
    for out in (healthy, concerned, silent, ir.demo()):
        blob = json.dumps(out).lower()
        assert "compatible" not in out["printer_status"].lower()
        assert not re.search(r"\d+\s*/\s*100|good to print|healthy \(|\"score\"|\"grade\"", blob)


def test_comparison_uses_the_same_count_as_risks_found():
    out = ir.build(
        predict={"available": True, "signals": [{"id": "x", "level": "warn", "title": "One finding"}]},
        first_layer={"overall_level": "ok", "findings": []},
        spacing={"status": "unknown"},          # a notice, not a risk found
    )
    assert out["risks_found"] == 1
    assert out["comparison"]["issues_found"] == 1
    assert "1 risk" in out["comparison"]["studio_line"] and "2" not in out["comparison"]["studio_line"].split("offered")[0]


def test_clean_comparison_says_what_was_checked_not_that_it_would_be_fine():
    out = ir.build(first_layer={"overall_level": "ok", "findings": []})
    blob = (out["comparison"]["orca_line"] + " " + out["comparison"]["studio_line"]).lower()
    assert "no major blockers" not in blob and "it'd be fine" not in blob
    assert "do not cover slicer settings" in blob and "verify in snapmaker orca" in blob


def test_printer_health_concerns_are_not_counted_twice():
    out = ir.build(
        predict={"available": True, "signals": [
            {"id": "printer-health", "level": "warn", "title": "The printer's own readings show concerns"}]},
        health={"available": True, "drivers": ["1 firmware warning"]},
    )
    assert out["risks_found"] == 1
    assert [r["text"] for r in out["risks"]] == ["1 firmware warning"]


def test_unverified_spacing_is_never_reported_as_found_nothing():
    out = ir.build(first_layer={"overall_level": "ok", "findings": []}, spacing={"status": "unknown"})
    assert out["risks_found"] == 0 and out["biggest_risk"] is None
    assert out["not_verified"] == ["object spacing"]
    assert "Orca slices the file as you give it" not in out["comparison"]["orca_line"]
    assert "spacing" in out["next_action"].lower() and "Snapmaker Orca" in out["next_action"]
    for text in (out["verdict"], out["comparison"]["studio_line"]):
        assert "object spacing was not verified" in text
        assert "found nothing in this file." not in text
    assert "found no risks. That" not in out["verdict"]
    with_risk = ir.build(
        predict={"available": True, "signals": [{"id": "x", "level": "warn", "title": "One finding"}]},
        spacing={"status": "unknown"})
    assert with_risk["risks_found"] == 1 and with_risk["not_verified"] == ["object spacing"]
    assert with_risk["next_action"].startswith("Look into:") and "Address:" not in with_risk["next_action"]


def test_health_verdict_has_no_number_or_good_to_print():
    from snapstudio_core import health_score
    for failures in (None, {"available": True, "failure_rate": 0.5, "failed": 5, "total": 10, "recent_failure_streak": 0}):
        v = health_score.score(diagnostics={"klippy_state": "ready", "warnings": [], "failed_components": []}, failures=failures)["verdict"]
        assert not re.search(r"[0-9]|good to print|healthy", v.lower()), v


# --- real Doctor/predictor output, not hand-set levels ---
from snapstudio_core import bed_fit as _bf, health_score as _hs, mm_doctor as _mm, success_predict as _sp, toolhead_fit as _tf


def test_failure_history_counts_once_and_keeps_the_exact_file_evidence():
    """Rate driver + streak driver + exact-file repeat signal are one condition: keep the strongest (the file signal)."""
    health = _hs.score(
        diagnostics={"klippy_state": "ready", "warnings": [], "failed_components": []},
        failures={"available": True, "failure_rate": 0.4, "failed": 4, "total": 10, "recent_failure_streak": 4},
    )
    predict = _sp.findings(readiness={"ready": True}, prior_failures=2, health=health, printer_checked=True)
    assert any("prints failed" in d for d in health["drivers"]) and len([d for d in health["drivers"] if "failed" in d]) == 2
    out = ir.build(predict=predict, health=health)
    failure = [r for r in out["risks"] if "failed" in r["text"]]
    assert len(failure) == 1
    assert failure[0]["level"] == "risk" and "file name" in failure[0]["text"]   # success_predict marks >=2 same-name failures a risk
    assert out["risks_found"] == 1 and out["biggest_risk"]["level"] == "risk"


def test_generic_failure_driver_alone_still_counts_once():
    health = _hs.score(
        diagnostics={"klippy_state": "ready", "warnings": [], "failed_components": []},
        failures={"available": True, "failure_rate": 0.4, "failed": 4, "total": 10, "recent_failure_streak": 4},
    )
    out = ir.build(predict=_sp.findings(readiness={"ready": True}, health=health, printer_checked=True), health=health)
    assert len(out["risks"]) == 1 and "failed" in out["risks"][0]["text"]   # rate and streak describe the same jobs


def test_five_color_project_is_one_risk_not_two():
    """The Multi-Material Doctor and the predictor describe the same colors-vs-toolheads condition."""
    mm = _mm.assess(5, heads=4, heads_known=True)
    tf = _tf.assess(5, 4, True)
    predict = _sp.findings(readiness={"ready": True}, toolfit=tf)
    assert any(sg["id"] == "toolhead-fit" for sg in predict["signals"])
    out = ir.build(predict=predict, mm=mm)
    assert out["risks_found"] == 1 and out["risks"][0]["doctor"] == "Multi-Material Doctor"
    assert out["risks"][0]["level"] == "risk"


def test_first_layer_condition_is_not_counted_by_both_doctor_and_predictor():
    fl = {"available": True, "overall_level": "warn", "findings": [{"level": "warn", "text": "Small contact area"}],
          "fixes": ["Add a brim."]}
    predict = _sp.findings(readiness={"ready": True}, first_layer=fl)
    out = ir.build(predict=predict, first_layer=fl)
    assert out["risks_found"] == 1 and out["risks"][0]["doctor"] == "First Layer Doctor"


def test_next_action_goes_with_the_biggest_risk():
    """Near-full bed (warn) listed first by Doctor order + too many colors (risk): Next must be the colors step."""
    bed = _bf.assess({"x": 268, "y": 100, "z": 10}, bed={"x": 270, "y": 270, "z": 270}, bed_known=True,
                     object_count=1, multi_material=False)
    mm = _mm.assess(5, heads=4, heads_known=True)
    out = ir.build(bed_fit=bed, mm=mm)
    assert out["biggest_risk"]["doctor"] == "Multi-Material Doctor" and out["biggest_risk"]["level"] == "risk"
    assert out["next_action"] == mm["fixes"][0]
    assert out["next_action"] != bed["fixes"][0]
