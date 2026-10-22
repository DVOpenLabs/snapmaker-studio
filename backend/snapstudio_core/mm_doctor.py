"""Multi-Material Doctor — does this multicolour print actually work on the U1?

The U1's headline feature is 4-toolhead multimaterial, and "my multicolour print
failed / printed wrong colours" is a top community pain that Orca doesn't explain.
This unifies the multicolour checks Studio computes separately — colours vs the
U1's toolheads, filament-settings consistency (Orca's "Customized Preset" trap),
and painted-region mapping — into one plain-language pre-flight verdict + fixes.

Read-only and honest: only meaningful for multicolour designs, uses the connected
U1's REAL toolhead count when known (else the U1's 4), and explains rather than
re-displays.
"""
from __future__ import annotations

SCHEMA_VERSION = "mmdoctor/1"

U1_TOOLHEADS = 4


def _f(level: str, text: str, id: str | None = None, action: str | None = None) -> dict:
    out = {"level": level, "text": text}
    if id:
        out["id"] = id         # the stable condition id (snapstudio_core.conditions)
    if action:
        out["action"] = action  # the step that belongs to THIS finding
    return out


def assess(colors, heads=None, heads_known: bool = False, painted: bool = False,
           metadata_issues=None, object_count: int = 1) -> dict:
    """One verdict for a multicolour U1 print.

    colors: filament/colour count in the design.
    heads: the printer's toolhead count; falls back to the U1's 4.
    heads_known: True when `heads` came from a connected printer.
    painted: design has painted (per-region colour) areas.
    metadata_issues: filament-array/purge inconsistencies already detected.
    """
    n = int(colors or 0)
    h = int(heads or U1_TOOLHEADS)
    source = "your U1" if heads_known else "the U1"
    multi = n > 1

    findings: list[dict] = []
    fixes: list[str] = []
    worst = "ok"

    def bump(level: str) -> None:
        nonlocal worst
        order = {"ok": 0, "warn": 1, "risk": 2}
        if order[level] > order[worst]:
            worst = level

    if not multi:
        if painted:
            bump("warn")
            _fix = "Add the other filament colours in Orca (or remap the painted regions), then re-check."
            findings.append(_f("warn", "This design has painted regions but only one filament "
                                       "colour is configured — the paint won't print as separate colours.",
                               id="painted-regions", action=_fix))
            fixes.append(_fix)
        else:
            findings.append(_f("ok", "Single colour — no multi-material setup needed."))
    else:
        if n <= h:
            findings.append(_f("ok", f"Uses {n} colours and {source} has {h} toolheads — "
                                     f"load one filament per toolhead and you're set."))
        else:
            over = n - h
            bump("risk")
            _fix = (f"Remap to {h} colours in Orca, or pause-and-swap filament mid-print. "
                    f"Studio keeps all {n} original colours in the file either way.")
            findings.append(_f("risk", f"{n} colours but only {h} toolheads — {over} colour"
                                       f"{'s' if over != 1 else ''} can't be loaded at once. This is the most "
                                       f"common reason a multicolour print fails or prints wrong on the U1.",
                               id="toolhead-fit", action=_fix))
            fixes.append(_fix)
        if painted:
            findings.append(_f("ok", "Painted regions present — check each region is assigned to "
                                     "the right toolhead/colour in Orca before slicing."))

    if metadata_issues:
        bump("warn")
        detail = "; ".join(str(m) for m in metadata_issues)
        _fix = "Run repair to conform the filament arrays and purge volumes to the colour count."
        findings.append(_f("warn", f"Filament settings are inconsistent ({detail}) — Orca flags "
                                   f"this as a Customized Preset and can misprint or refuse the colours.",
                           id="filament-metadata", action=_fix))
        fixes.append(_fix)

    overall_text = {
        "ok": ("Single colour print." if not multi else "Multi-material setup looks correct."),
        "warn": "Multi-material setup needs a tweak — see below before slicing.",
        "risk": "This won't print as designed — too many colours for the toolheads.",
    }[worst]

    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "multi_material": multi,
        "colors": n,
        "heads": h,
        "heads_known": bool(heads_known),
        "overall_level": worst,
        "overall_text": overall_text,
        "findings": findings,
        "fixes": fixes,
        "verdict": overall_text,
    }
