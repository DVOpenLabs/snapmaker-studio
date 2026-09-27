"""v1.2 fix round 3, backend part (F6 + Opus N7) — spec: "AGREED DECISION"
section of v12-rediagnosis.md. Each test is written to FAIL against the
round-2 code first, then the fix makes it pass.
"""
from __future__ import annotations

from snapstudio_core import nozzle_confirm as nc, post_slice, preflight as pf


# --- F6: an ordered position whose expected value is None is excluded ------
# from `relevant` exactly like a beyond-length position, BEFORE counting
# known/relevant; empty relevant -> UNKNOWN.

def test_match_verdict_null_expected_position_is_skipped_not_a_mismatch():
    assert nc.match_verdict([0, 1], [0.4, None], {"0.4"}, [0.4, 0.6]) == nc.OK


def test_match_verdict_only_position_null_expected_and_empty_relevant_is_unknown():
    assert nc.match_verdict([0], [None], {"0.4"}, [0.4]) == nc.UNKNOWN


def test_match_verdict_null_expected_position_does_not_hide_a_real_mismatch():
    assert nc.match_verdict([0, 1], [0.4, None], {"0.4"}, [0.6, 0.6]) == nc.ATTENTION


def test_match_verdict_null_expected_and_reported_missing_is_still_unknown():
    assert nc.match_verdict([0], [None], {"0.4"}, [None]) == nc.UNKNOWN


def test_f6_through_preflight_null_expected_position_is_skipped():
    """Same case as the direct matrix test, through preflight._nozzle: the
    project's ordered per-toolhead trait has an explicit null (toolhead 1's
    size unknown to the slicer) — the printer's answer there must never be
    treated as a mismatch."""
    project = {"nozzle_diameters": {"value": ["0.4"], "confidence": "confirmed"},
              "nozzle_diameters_by_toolhead": {"value": [0.4, None], "confidence": "confirmed"}}
    printer = {"nozzle_diameters": [0.4, 0.6], "nozzle_confirmed_by": "printer"}
    out = pf.evaluate(project, printer)
    check = next(c for c in out["checks"] if c["id"] == "nozzle.match")
    assert check["result"] == pf.OK


def test_f6_through_post_slice_null_expected_position_is_skipped():
    facts = {"available": True, "nozzle_diameter_mm": [0.4, None], "tools_used": None}
    printer = {"nozzle_diameters": [0.4, 0.6], "nozzle_confirmed_by": "printer"}
    out = post_slice.analyse(facts, printer)
    check = next(c for c in out["checks"] if c["id"] == "gcode.nozzle")
    assert check["result"] == post_slice.OK


# --- N7: live_error "not_checked" documented; dead code removed ------------

def test_resolve_has_no_unreachable_trailing_dead_code():
    """The final fallback `return` in `resolve()` (host and request_diameters
    both falsy, no live reading) must be the ONLY code path reachable after
    the `if host:` block — not a second, unreachable duplicate of the same
    return sitting after it."""
    import inspect
    src = inspect.getsource(nc.resolve)
    # Every `return {"diameters": None, ...}` shaped fallback line, so a
    # leftover duplicate after the reachable one would be caught here too.
    fallback_returns = src.count('return {"diameters": None, "confirmed_by": None, "confirmed_at": None,')
    # One inside `except InvalidHost`, one inside `if host:` for "nothing
    # stored", and one final catch-all for "no host at all" — exactly three,
    # never four.
    assert fallback_returns == 3


def test_resolve_with_no_host_and_nothing_else_returns_directly():
    assert nc.resolve(None, None, 7125, None, None) == {
        "diameters": None, "confirmed_by": None, "confirmed_at": None,
        "revision": 0, "conflicts": [], "stored": {},
    }
