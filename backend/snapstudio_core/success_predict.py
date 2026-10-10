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

from . import conditions as C

SCHEMA_VERSION = "successpredict/3"   # 3: one signal per stable condition id (snapstudio_core.conditions)

# `kind` uses the same evidence kinds as the rest of the app: "engine" is one of
# Studio's own checks, "estimate" is derived output, "orca" is advice to verify in
# Snapmaker Orca.

# Things no signal here can tell you, whatever was checked.
LIMITATIONS = [
    "Studio checks only what it lists under \u201cStudio checked.\u201d It cannot know your "
    "slicer settings, how the filament has been stored, how clean or level the bed "
    "is, or how the printer behaves mid-print.",
    "Studio does not slice and does not verify spacing between objects. "
    "Verify in Snapmaker Orca before you print.",
]


def _limitations(bed_measured: bool, spacing_unverified: bool) -> list:
    """The fixed limits, minus any claim the inputs actually covered."""
    first, second = LIMITATIONS
    if bed_measured:
        first = first.replace("how clean or level the bed is", "how clean the bed is")
    if not spacing_unverified:
        second = "Studio does not slice. Verify in Snapmaker Orca before you print."
    return [first, second]


def findings(readiness=None, toolfit=None, first_layer=None, health=None,
             prior_failures: int = 0, printer_checked: bool = False,
             spacing_unverified: bool = True) -> dict:
    """List the risk signals found in the pre-print checks Studio already has.

    readiness: validation_report.readiness_report() output (ready + warnings).
    toolfit:   toolhead_fit.assess() output (overall_level).
    first_layer: first_layer.assess() output (overall_level).
    health:    health_score.score() output (available + drivers).
    prior_failures: times this exact file name has failed in the printer's history.
    printer_checked: True when a printer answered and its history was read, so
        history counts as checked even when it found no failures.
    spacing_unverified: False for a single-object model, where spacing does not apply.
    """
    health_ok = bool(health and health.get("available"))
    toolfit_ok = bool(toolfit and toolfit.get("available"))
    # An unavailable result is a gap, not a clean result.
    readiness_ok = bool(readiness and readiness.get("available") is not False)
    first_layer_ok = bool(first_layer and first_layer.get("available") is not False
                          and first_layer.get("overall_level"))
    bed_measured = bool(first_layer_ok and first_layer.get("bed_aware"))
    have = {
        "design validation": readiness_ok,
        "colors against toolheads": toolfit_ok,
        "first-layer risk": first_layer_ok,
        "printer health": health_ok,
        "printer history for the same file name": bool(printer_checked or prior_failures),
    }
    if not any(have.values()):
        return {"schema_version": SCHEMA_VERSION, "available": False,
                "reason": "no design or printer information was available to check",
                "limitations": _limitations(False, spacing_unverified)}

    # Gather what each source says about each condition, then build ONE signal per condition id.
    contribs: list = []

    if readiness_ok and readiness.get("ready") is False:
        warnings = [str(w) for w in (readiness.get("warnings") or [])]
        n = len(warnings)
        title = (f"Design validation flagged {n} issue{'s' if n != 1 else ''}" if n
                 else "Design validation flagged an issue")
        contribs.append(C.contribution(
            C.DESIGN_VALIDATION, "warn", title,
            facts=[title] + warnings[:5] + ([f"and {n - 5} more in Design Health"] if n > 5 else [])))

    if toolfit_ok:
        lvl = toolfit.get("overall_level")
        if lvl in ("risk", "warn"):
            contribs.append(C.contribution(
                C.TOOLHEAD_FIT, lvl,
                "More colors than toolheads" if lvl == "risk" else "Color layout needs a swap or remap",
                action=("Remap to fewer colors in Snapmaker Orca, or plan a filament swap." if lvl == "risk"
                        else "Check the color-to-toolhead mapping in Snapmaker Orca.")))

    if first_layer_ok:
        contribs.extend(C.doctor_contributions(first_layer, "First Layer Doctor"))

    if health_ok:
        for cond in (health.get("conditions") or []):
            contribs.append(C.contribution(cond["id"], cond.get("level", "warn"), cond["text"], source="health"))

    if prior_failures and prior_failures > 0:
        contribs.append(C.contribution(
            C.PRINTER_FAILURE_HISTORY, "risk" if prior_failures >= 2 else "warn",
            f"A print with this file name failed {prior_failures} time{'s' if prior_failures != 1 else ''} before",
            source="history"))

    signals: list[dict] = []
    for f in C.merge(contribs):
        kind, meaning, action = C.COPY.get(f["id"], ("engine", "Studio's check flagged this.", None))
        sig = {"id": f["id"], "kind": kind, "level": f["level"], "title": f["text"],
               "meaning": meaning, "action": f["action"] or action or "Verify in Snapmaker Orca.",
               "facts": f["evidence"]}
        if f["id"] == C.DESIGN_VALIDATION and len(f["evidence"]) > 1:
            sig["details"] = f["evidence"][1:]
        signals.append(sig)

    checked = [name for name, ok in have.items() if ok]
    not_checked = [name for name, ok in have.items() if not ok]
    if spacing_unverified:
        not_checked.append("object spacing")

    n = len(signals)
    if n:
        summary = (f"Studio found {n} thing{'s' if n != 1 else ''} to sort out before you slice. "
                   "Each says what it means and what to do.")
    else:
        summary = ("Studio's checks did not flag anything in what they covered: "
                   + ", ".join(checked) + ". That is not a sign the print will succeed.")

    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "signals": signals,
        "checked": checked,
        "not_checked": not_checked,
        "limitations": _limitations(bed_measured, spacing_unverified),
        "summary": summary,
    }
