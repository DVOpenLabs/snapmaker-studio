"""Studio Intelligence Report — the one screen that makes the Doctors a product.

Synthesises every Doctor's output into a single verdict a user grasps in 15s:
will it print, what it costs, what to sell it for, the profit, the biggest risk,
and the next action. The Doctors become evidence behind one Studio Intelligence
Score. Pure synthesis over already-computed dicts — no network here.
"""
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


def test_headline_from_printer_health_and_no_success_percentage():
    out = ir.build(
        predict={"available": True, "signals": []},
        health={"available": True, "score": 90, "grade": "A", "drivers": []},
    )
    assert out["available"] is True
    assert out["studio_score"] == 90
    assert "print_success_score" not in out
    assert out["printer_compatibility"] in ("Compatible", "Check", "Unknown")


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
    assert out["studio_score"] is not None
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
    for k in ("studio_score", "cost", "suggested_price",
              "margin_pct", "printer_compatibility", "risks", "biggest_risk",
              "recommendations", "next_action", "supporting", "verdict"):
        assert k in out
