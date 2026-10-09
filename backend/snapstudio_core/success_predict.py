"""Print risk signals — what Studio found that is worth settling before you slice.

Studio already knows, separately: whether the design passed validation, whether
its colors fit the toolheads, whether the first layer looks risky, how healthy
the printer is, and whether this exact file name has failed before. This lists
the ones that raised a flag, each with what it means and what to do, and says
plainly what was checked and what Studio cannot know.

It deliberately returns no percentage, band or "will it print" verdict: nothing
here is calibrated against real print outcomes, so a number would read as a
probability it is not. (Issue #92.)

Pure read-only synthesis of signals Studio already has — no webcam, no AI vision,
no control, no new printer calls.
"""
from __future__ import annotations

SCHEMA_VERSION = "successpredict/2"

# `kind` uses the same evidence kinds as the rest of the app: "engine" is one of
# Studio's own checks, "estimate" is derived output, "orca" is advice to verify in
# Snapmaker Orca.

# Things no signal here can tell you, whatever was checked.
LIMITATIONS = [
    "Studio checks the things listed above. It cannot know your slicer settings, "
    "how the filament has been stored, how clean or level the bed is, or how the "
    "printer behaves mid-print.",
    "Studio does not slice and does not verify spacing between objects. "
    "Verify in Snapmaker Orca before you print.",
]


def _signal(sid: str, kind: str, level: str, title: str, meaning: str, action: str,
            details: list | None = None) -> dict:
    out = {"id": sid, "kind": kind, "level": level, "title": title,
           "meaning": meaning, "action": action}
    if details:
        out["details"] = details
    return out


def findings(readiness=None, toolfit=None, first_layer=None, health=None,
             prior_failures: int = 0, printer_checked: bool = False) -> dict:
    """List the risk signals found in the pre-print checks Studio already has.

    readiness: validation_report.readiness_report() output (ready + warnings).
    toolfit:   toolhead_fit.assess() output (overall_level).
    first_layer: first_layer.assess() output (overall_level).
    health:    health_score.score() output (available + drivers).
    prior_failures: times this exact file name has failed in the printer's history.
    printer_checked: True when a printer was asked, so history counts as checked
        even when it found no failures.
    """
    health_ok = bool(health and health.get("available"))
    toolfit_ok = bool(toolfit and toolfit.get("available"))
    have = {
        "design validation": bool(readiness),
        "colors against toolheads": toolfit_ok,
        "first-layer risk": bool(first_layer),
        "printer health": health_ok,
        "this file's print history": bool(printer_checked or prior_failures),
    }
    if not any(have.values()):
        return {"schema_version": SCHEMA_VERSION, "available": False,
                "reason": "no design or printer information was available to check",
                "limitations": list(LIMITATIONS)}

    signals: list[dict] = []

    if readiness and readiness.get("ready") is False:
        warnings = [str(w) for w in (readiness.get("warnings") or [])]
        n = len(warnings)
        signals.append(_signal(
            "design-validation", "engine", "warn",
            f"Design validation flagged {n} issue{'s' if n != 1 else ''}" if n
            else "Design validation flagged an issue",
            "Studio's validation found something in the design that can cause trouble when slicing.",
            "Read the issues in Design Health and fix or check them in Snapmaker Orca.",
            warnings[:5] + ([f"and {n - 5} more in Design Health"] if n > 5 else [])))

    if toolfit_ok:
        lvl = toolfit.get("overall_level")
        if lvl == "risk":
            signals.append(_signal(
                "toolhead-fit", "engine", "risk",
                "More colors than toolheads",
                "The design uses more colors than the U1 can load at once.",
                "Remap to fewer colors in Snapmaker Orca, or plan a filament swap."))
        elif lvl == "warn":
            signals.append(_signal(
                "toolhead-fit", "engine", "warn",
                "Color layout needs a swap or remap",
                "The color layout does not map cleanly onto the four toolheads.",
                "Check the color-to-toolhead mapping in Snapmaker Orca."))

    if first_layer:
        lvl = first_layer.get("overall_level")
        if lvl == "risk":
            signals.append(_signal(
                "first-layer", "estimate", "risk",
                "First-layer adhesion looks risky",
                "The first layer has little contact area or an awkward shape for this printer. This is an estimate from the geometry.",
                "Look at the first layer in Snapmaker Orca's preview and consider a brim."))
        elif lvl == "warn":
            signals.append(_signal(
                "first-layer", "estimate", "warn",
                "First layer is marginal",
                "The first layer may not stick well. This is an estimate from the geometry.",
                "Watch the first layer, and check adhesion settings in Snapmaker Orca."))

    if health_ok:
        drivers = [str(d) for d in (health.get("drivers") or []) if "no problem" not in str(d).lower()]
        if drivers:
            signals.append(_signal(
                "printer-health", "estimate", "warn",
                "The printer's own readings show concerns",
                "The printer's diagnostics or print history point to something worth looking at.",
                "Open Printer Doctor and review these before a long print.",
                drivers[:5]))

    if prior_failures and prior_failures > 0:
        signals.append(_signal(
            "repeat-failure", "engine", "risk" if prior_failures >= 2 else "warn",
            f"A file with this name failed {prior_failures} time{'s' if prior_failures != 1 else ''} before",
            "The printer's history lists failed jobs with the same file name. Studio matches on the name only, not the contents.",
            "Check why the earlier print failed before starting this one."))

    checked = [name for name, ok in have.items() if ok]
    not_checked = [name for name, ok in have.items() if not ok]
    not_checked += ["object spacing", "your slicer settings"]

    n = len(signals)
    if n:
        summary = (f"Studio found {n} thing{'s' if n != 1 else ''} worth settling before you slice. "
                   "Each says what it means and what to do.")
    else:
        summary = ("Studio's checks did not flag anything in what they covered: "
                   + ", ".join(checked) + ". That is not a sign the print will succeed.")

    signals.sort(key=lambda s: 0 if s["level"] == "risk" else 1)
    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "signals": signals,
        "checked": checked,
        "not_checked": not_checked,
        "limitations": list(LIMITATIONS),
        "summary": summary,
    }
