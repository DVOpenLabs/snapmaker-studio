"""Print risk signals (issue #92) — a list of what Studio found, never a percentage.

Synthesises design validation, toolhead fit, first-layer risk, printer health and
whether this exact file name has failed before into specific signals, each with
what it means and what to do, plus what was and was not checked.
"""
import json
import re

from snapstudio_core import success_predict as sp

_SCORE_KEYS = {"likelihood", "band", "verdict", "factors", "score"}


def _titles(out):
    return [s["title"] for s in out["signals"]]


def test_unavailable_with_no_signals():
    out = sp.findings()
    assert out["available"] is False
    assert out["limitations"]


def test_clean_design_says_what_was_checked_and_not_that_it_will_succeed():
    out = sp.findings(
        readiness={"ready": True, "warnings": []},
        toolfit={"available": True, "overall_level": "ok"},
        first_layer={"overall_level": "ok"},
        health={"available": True, "score": 95, "drivers": ["No problems found"]},
    )
    assert out["available"] is True
    assert out["signals"] == []
    assert "design validation" in out["checked"] and "printer health" in out["checked"]
    assert "object spacing" in out["not_checked"] and "your slicer settings" in out["not_checked"]
    assert "not a sign the print will succeed" in out["summary"]
    assert any("Verify in Snapmaker Orca" in x for x in out["limitations"])


def test_no_printer_means_printer_signals_are_listed_as_not_checked():
    out = sp.findings(readiness={"ready": True, "warnings": []})
    assert "printer health" in out["not_checked"]
    assert "this file's print history" in out["not_checked"]
    assert sp.findings(readiness={"ready": True}, printer_checked=True)["checked"].count("this file's print history") == 1


def test_each_signal_says_what_it_means_and_what_to_do():
    out = sp.findings(
        readiness={"ready": False, "warnings": ["a", "b"]},
        toolfit={"available": True, "overall_level": "risk"},
        first_layer={"overall_level": "warn"},
        health={"available": True, "score": 40, "drivers": ["Firmware is old"]},
        prior_failures=2,
    )
    ids = {s["id"] for s in out["signals"]}
    assert ids == {"design-validation", "toolhead-fit", "first-layer", "printer-health", "repeat-failure"}
    for s in out["signals"]:
        assert s["kind"] in ("engine", "estimate", "orca")
        assert s["level"] in ("warn", "risk")
        assert s["meaning"] and s["action"] and s["title"]
    assert "Design validation flagged 2 issues" in _titles(out)
    assert out["signals"][0]["level"] == "risk"  # risks sort first
    assert any("colors than toolheads" in t for t in _titles(out))
    assert any("failed 2 times" in t for t in _titles(out))


def test_repeat_failure_matches_by_name_and_says_so():
    out = sp.findings(readiness={"ready": True}, prior_failures=1)
    sig = out["signals"][0]
    assert sig["level"] == "warn" and "name only" in sig["meaning"]


def test_never_returns_a_score_band_or_percentage():
    worst = sp.findings(
        readiness={"ready": False, "warnings": ["a", "b", "c", "d"]},
        toolfit={"available": True, "overall_level": "risk"},
        first_layer={"overall_level": "risk"},
        health={"available": True, "score": 20, "drivers": ["x"]},
        prior_failures=3,
    )
    clean = sp.findings(readiness={"ready": True})
    for out in (worst, clean):
        assert not _SCORE_KEYS & set(out)
        blob = json.dumps(out)
        assert not re.search(r"\d\s*%", blob)
        assert "likely to print" not in blob.lower()
        assert "firmware" not in out["summary"].lower()  # plain language in the headline


def _service_with_printer(monkeypatch, diagnostics):
    from snapstudio_api import service
    from snapstudio_core import moonraker
    monkeypatch.setattr(service, "toolhead_fit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(service, "first_layer", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(service, "printer_health", lambda *a, **k: {"available": True, "score": 100, "drivers": ["No problems found."]})
    monkeypatch.setattr(moonraker, "diagnostics", lambda *a, **k: diagnostics)
    monkeypatch.setattr(moonraker, "history", lambda *a, **k: {"jobs": [], "totals": {}})
    return service


def test_unreachable_printer_is_not_reported_as_checked(monkeypatch, tmp_path):
    service = _service_with_printer(monkeypatch, {"klippy_state": None, "warnings": []})
    cube = tmp_path / "c.stl"
    cube.write_bytes(b"\0" * 80 + (0).to_bytes(4, "little"))
    out = service.predict_success(str(cube), host="printer.invalid")
    assert "printer health" not in out.get("checked", [])
    assert "printer health" in out.get("not_checked", [])
    assert "this file's print history" in out.get("not_checked", [])


def test_reachable_printer_counts_health_and_history_as_checked(monkeypatch, tmp_path):
    service = _service_with_printer(monkeypatch, {"klippy_state": "ready", "warnings": []})
    cube = tmp_path / "c.stl"
    cube.write_bytes(b"\0" * 80 + (0).to_bytes(4, "little"))
    out = service.predict_success(str(cube), host="printer.invalid")
    assert "printer health" in out["checked"] and "this file's print history" in out["checked"]
