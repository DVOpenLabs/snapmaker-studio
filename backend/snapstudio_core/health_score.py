"""Printer Health Score — one honest number for "is my U1 in good shape?"

A U1 owner can already see telemetry (Fluidd), history (Moonraker), and Studio's
failure patterns — but nothing rolls them into a single answer. This does: it
folds the printer's OWN read-only signals (firmware/connectivity state + warnings
+ failed components, and the print-history failure pattern) into a 0–100 score, a
letter grade, and the plain-language drivers behind it.

Pure aggregation of data Studio already fetches read-only — no new printer calls,
no control, no telemetry re-display. Honest by design: it scores only the signals
it actually has, lists what pulled the score down (most impactful first), and
returns unavailable when there's nothing to score.
"""
from __future__ import annotations

SCHEMA_VERSION = "healthscore/1"


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def score(diagnostics=None, failures=None) -> dict:
    """Roll the U1's read-only health signals into a 0–100 score.

    diagnostics: snapstudio_core.moonraker.diagnostics() output (or None).
    failures: snapstudio_core.failure_patterns.assess() output (or None).
    """
    have_fail = bool(failures and failures.get("available"))
    have_diag = bool(diagnostics)
    if not have_fail and not have_diag:
        return {"schema_version": SCHEMA_VERSION, "available": False,
                "reason": "no printer diagnostics or print history to score"}

    # Each driver: (penalty_points, plain-language reason).
    drivers: list[tuple[int, str]] = []

    if have_fail:
        rate = float(failures.get("failure_rate") or 0.0)
        if rate > 0:
            p = round(rate * 40)
            if p:
                drivers.append((p, f"{failures.get('failed')} of the last {failures.get('total')} prints failed"))
        streak = int(failures.get("recent_failure_streak") or 0)
        if streak >= 4:
            drivers.append((25, f"{streak} prints failed in a row"))
        elif streak >= 2:
            drivers.append((15, f"{streak} prints failed in a row"))

    if have_diag:
        st = diagnostics.get("klippy_state")
        if st and st != "ready":
            drivers.append((30, f"firmware not ready ({st})"))
        fc = diagnostics.get("failed_components") or []
        if fc:
            drivers.append((min(40, 20 * len(fc)), f"{len(fc)} failed firmware component{'s' if len(fc) != 1 else ''}"))
        warns = diagnostics.get("warnings") or []
        if warns:
            drivers.append((min(15, 5 * len(warns)), f"{len(warns)} firmware warning{'s' if len(warns) != 1 else ''}"))

    penalty = sum(p for p, _ in drivers)
    value = max(0, min(100, 100 - penalty))
    grade = _grade(value)

    # Most impactful first; if nothing pulled it down, say so.
    drivers.sort(key=lambda d: d[0], reverse=True)
    has_concerns = bool(drivers)
    driver_text = [t for _, t in drivers] or ["No problems found in firmware state or recent history."]

    basis_parts = []
    if have_diag:
        basis_parts.append("firmware state")
    if have_fail:
        basis_parts.append(f"last {failures.get('total')} prints")
    basis = " + ".join(basis_parts)

    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "score": value,
        "grade": grade,
        "drivers": driver_text,
        "basis": basis,
        "verdict": _verdict(value, grade, has_concerns),
    }


def _verdict(value: int, grade: str, has_concerns: bool = False) -> str:
    if has_concerns and grade in ("A", "B"):
        return "A few things in the printer's own readings are worth a look; see the list below."
    if grade in ("A", "B"):
        return "Nothing concerning in the printer's own readings."
    if grade == "C":
        return "Worth a check before a long print."
    return "The printer's own readings show concerns; see the list below."
