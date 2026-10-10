"""Printer Health Score — one 0–100 from the U1's own read-only signals.

Folds firmware/connectivity diagnostics and print-history failure patterns into a
single score + letter grade + plain-language drivers. Pure aggregation of data
Studio already reads; no new printer calls, no telemetry re-display.
"""
from snapstudio_core import health_score as hs


def test_unavailable_with_no_signals():
    out = hs.score(diagnostics=None, failures=None)
    assert out["available"] is False


def test_perfect_printer_scores_top_grade():
    diag = {"klippy_state": "ready", "warnings": [], "failed_components": [], "healthy": True}
    fail = {"available": True, "failure_rate": 0.0, "recent_failure_streak": 0}
    out = hs.score(diagnostics=diag, failures=fail)
    assert out["available"] is True
    assert out["score"] == 100
    assert out["grade"] == "A"
    assert isinstance(out["drivers"], list)


def test_high_failure_rate_lowers_score():
    diag = {"klippy_state": "ready", "warnings": [], "failed_components": []}
    fail = {"available": True, "failure_rate": 0.5, "recent_failure_streak": 0}
    out = hs.score(diagnostics=diag, failures=fail)
    # 50% failure rate -> -20
    assert out["score"] == 80
    assert any("fail" in d.lower() for d in out["drivers"])


def test_recent_streak_and_firmware_fault_compound():
    diag = {"klippy_state": "shutdown", "warnings": ["heater drift"],
            "failed_components": ["mcu"]}
    fail = {"available": True, "failure_rate": 0.2, "recent_failure_streak": 4}
    out = hs.score(diagnostics=diag, failures=fail)
    # rate 0.2->-8, streak4->-25, state not ready->-30, 1 component->-20, 1 warn->-5
    assert out["score"] == max(0, 100 - 8 - 25 - 30 - 20 - 5)  # 12
    assert out["grade"] == "F"
    # one line per condition, most impactful first: the failure history (rate + streak, 33 points as ONE condition)
    # outranks "firmware not ready" (30)
    assert [c["id"] for c in out["conditions"]] == ["printer-failure-history", "firmware-not-ready",
                                                    "firmware-failed-component", "firmware-warning"]
    assert out["drivers"] == [c["text"] for c in out["conditions"]]
    assert "failed" in out["drivers"][0].lower() and "in a row" in out["drivers"][0]


def test_score_clamps_at_zero():
    diag = {"klippy_state": "error", "warnings": ["a", "b", "c", "d"],
            "failed_components": ["x", "y", "z"]}
    fail = {"available": True, "failure_rate": 1.0, "recent_failure_streak": 6}
    out = hs.score(diagnostics=diag, failures=fail)
    assert out["score"] == 0
    assert out["grade"] == "F"


def test_history_only_still_scores():
    fail = {"available": True, "failure_rate": 0.1, "recent_failure_streak": 0}
    out = hs.score(diagnostics=None, failures=fail)
    assert out["available"] is True
    assert 0 <= out["score"] <= 100
    assert isinstance(out["verdict"], str) and out["verdict"]


def test_grade_boundaries():
    assert hs._grade(90) == "A"
    assert hs._grade(75) == "B"
    assert hs._grade(60) == "C"
    assert hs._grade(40) == "D"
    assert hs._grade(39) == "F"
