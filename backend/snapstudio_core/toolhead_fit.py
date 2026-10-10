"""Toolhead-Fit Intelligence — does this design's colour count fit the toolheads?

Fuses the design's filament/colour count with the printer's REAL toolhead count
(from Moonraker when reachable, else the profile of the machine Studio is
preparing for) into one plain-language answer: "Can my printer print all these
colours in a single run, or will it need a filament swap / remap?" Pure +
read-only; the service layer gathers the inputs.

The offline fallback used to be a module constant, `U1_TOOLHEADS = 4`, which meant
that with no printer connected Studio told everybody they had four toolheads. It
now comes from the profile of the printer the file is being prepared for, and the
answer says which machine it was measured against, so a number that came from a
profile never reads as a number that came from hardware.

This is insight, not telemetry: it turns two numbers the user already has into a
clear go / plan-a-swap recommendation, and never fabricates swap counts or times.
"""
from __future__ import annotations

SCHEMA_VERSION = "toolheadfit/1"


def _f(level: str, text: str, id: str | None = None, action: str | None = None) -> dict:
    out = {"level": level, "text": text}
    if id:
        out["id"] = id         # the stable condition id (snapstudio_core.conditions)
    if action:
        out["action"] = action  # the step that belongs to THIS finding
    return out


def assess(color_count, toolhead_count=None, printer_known: bool = False,
           profile: dict | None = None) -> dict:
    """Return toolhead-fit findings.

    color_count: distinct filament/colour slots the design uses (int or None).
    toolhead_count: real toolhead count from a connected printer (int) or None.
    printer_known: True when toolhead_count came from a reachable printer.
    profile: the printer profile to fall back on when no printer answered.
        Defaults to the machine Studio prepares copies for.
    """
    from . import printer_profiles

    profile = profile or printer_profiles.prepare_target()
    fallback = profile.get("tool_count")
    heads = int(toolhead_count) if toolhead_count else (int(fallback) if fallback else 1)
    name = printer_profiles.display_name(profile)
    source = ("your connected printer" if printer_known
              else f"the {name} this would be prepared for")
    findings: list = []
    worst = "ok"

    def bump(level: str) -> None:
        nonlocal worst
        order = {"ok": 0, "warn": 1, "risk": 2}
        if order[level] > order[worst]:
            worst = level

    if color_count is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "available": False,
            "reason": "colour count unavailable",
            "printer_aware": printer_known,
            "toolhead_count": heads,
            "toolhead_count_source": "live" if printer_known else "profile",
            "measured_against": printer_profiles.summarise(None if printer_known else profile),
        }

    n = int(color_count)
    # A single-toolhead machine is not a four-toolhead machine with three broken
    # ones, and it should not be described in the plural as though it were.
    heads_txt = f"{heads} toolhead{'' if heads == 1 else 's'}"
    if n <= 1:
        where = (f"{source}'s single toolhead" if heads == 1
                 else f"any one of {source}'s {heads} toolheads")
        findings.append(_f("ok", f"Single colour — prints on {where}, no colour setup needed."))
    elif n <= heads:
        spare = heads - n
        spare_txt = f" ({spare} toolhead{'' if spare == 1 else 's'} to spare)" if spare > 0 else ""
        findings.append(_f("ok", f"Uses {n} colours and {source} has {heads_txt}{spare_txt} — load one filament per colour and it prints in a single run."))
    else:
        over = n - heads
        bump("risk")
        findings.append(_f("risk", f"This design uses {n} colours but {source} has only {heads_txt} — {over} colour{'' if over == 1 else 's'} can't be loaded at the same time.", id="toolhead-fit"))
        swap_to = ("a single colour" if heads == 1 else f"{heads} colours")
        findings.append(_f("warn", f"To print it as designed, swap filament mid-print (pause-and-swap), or remap it down to {swap_to} in your slicer. Either way Studio keeps all {n} original colours in the file."))

    overall_text = {
        "ok": "Your toolheads cover this design's colours.",
        "warn": "Workable with a filament swap or remap (see below).",
        "risk": "More colours than toolheads — plan a swap or remap before printing.",
    }[worst]
    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "printer_aware": printer_known,
        "color_count": n,
        "toolhead_count": heads,
        "toolhead_count_source": "live" if printer_known else "profile",
        "measured_against": printer_profiles.summarise(None if printer_known else profile),
        "overall_level": worst,
        "overall_text": overall_text,
        "findings": findings,
    }
