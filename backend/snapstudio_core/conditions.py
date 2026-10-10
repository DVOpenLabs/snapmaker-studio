"""Stable condition identities (#92).

Every source of a pre-print finding (Doctor findings, the Print risk signals card, the printer's
health conditions, print history, "not verified" notes) names the *condition* it is about with an id
defined here, once. A report is then built with one finding per condition id:

  severity = the maximum over its contributors,
  evidence = every contributor's facts, merged,
  action   = the action of the contributor that belongs to that condition,
  rank     = severity, then how much evidence backs it.

Nothing here compares display text to decide that two findings are the same thing; identity comes
from the id the producer attached. Findings from older or hand-built inputs that carry no id are
never merged with anything (each becomes its own `unmapped:` condition).
"""
from __future__ import annotations

# --- design / project ---
DESIGN_VALIDATION = "design-validation"
TOOLHEAD_FIT = "toolhead-fit"
FILAMENT_METADATA = "filament-metadata"
PAINTED_REGIONS = "painted-regions"
# --- fit on the plate ---
BED_HEIGHT = "bed-height"
BED_FOOTPRINT = "bed-footprint"
BED_NEAR_FULL = "bed-near-full"
BED_PRIME_TOWER = "bed-prime-tower-room"
# --- first layer ---
FIRST_LAYER_ADHESION = "first-layer-adhesion"
FIRST_LAYER_BED_FLATNESS = "first-layer-bed-flatness"
FIRST_LAYER_CORNER_LIFT = "first-layer-corner-lift"
FIRST_LAYER_ORIENTATION = "first-layer-orientation"
# --- what the printer reported ---
PRINTER_FAILURE_HISTORY = "printer-failure-history"
FIRMWARE_NOT_READY = "firmware-not-ready"
FIRMWARE_FAILED_COMPONENT = "firmware-failed-component"
FIRMWARE_WARNING = "firmware-warning"
# --- business / limits ---
PROFIT_BELOW_COST = "profit-below-cost"
OBJECT_SPACING_UNVERIFIED = "object-spacing-unverified"

PRINTER_CONDITIONS = frozenset({PRINTER_FAILURE_HISTORY, FIRMWARE_NOT_READY, FIRMWARE_FAILED_COMPONENT, FIRMWARE_WARNING})
# Conditions where the Print risk signals card holds evidence no Doctor result carries (the file-name history); for the rest a
# signal only restates what the Doctor already says.
PREDICTOR_ADDS_EVIDENCE = frozenset({DESIGN_VALIDATION, PRINTER_FAILURE_HISTORY})
# Conditions whose several facts read as one sentence ("…failed 1 time before; 8 of the last 10 prints failed").
JOIN_FACTS = frozenset({PRINTER_FAILURE_HISTORY})

DOCTOR_LABEL = {
    DESIGN_VALIDATION: "Project Doctor",
    TOOLHEAD_FIT: "Multi-Material Doctor", FILAMENT_METADATA: "Multi-Material Doctor", PAINTED_REGIONS: "Multi-Material Doctor",
    BED_HEIGHT: "Size fit (dimensions only)", BED_FOOTPRINT: "Size fit (dimensions only)",
    BED_NEAR_FULL: "Size fit (dimensions only)", BED_PRIME_TOWER: "Size fit (dimensions only)",
    FIRST_LAYER_ADHESION: "First Layer Doctor", FIRST_LAYER_BED_FLATNESS: "First Layer Doctor",
    FIRST_LAYER_CORNER_LIFT: "First Layer Doctor", FIRST_LAYER_ORIENTATION: "First Layer Doctor",
    PRINTER_FAILURE_HISTORY: "Printer Doctor", FIRMWARE_NOT_READY: "Printer Doctor",
    FIRMWARE_FAILED_COMPONENT: "Printer Doctor", FIRMWARE_WARNING: "Printer Doctor",
    PROFIT_BELOW_COST: "Profit Doctor",
}

# (evidence kind, what it means, what to do) for conditions the Print risk signals card explains.
# Kinds are the app's evidence kinds: "engine" = one of Studio's own checks, "estimate" = derived output.
COPY = {
    DESIGN_VALIDATION: ("engine", "Studio's validation found something in this project that can cause trouble when slicing.",
                        "Read the issues in Design Health and fix or check them in Snapmaker Orca."),
    TOOLHEAD_FIT: ("engine", "The design uses more colors than the U1 can load at once.",
                   "Remap to fewer colors in Snapmaker Orca, or plan a filament swap."),
    FIRST_LAYER_ADHESION: ("estimate", "The base is small or narrow for this printer. This is an estimate from the geometry.",
                           "Look at the first layer in Snapmaker Orca's preview and consider a brim."),
    FIRST_LAYER_BED_FLATNESS: ("estimate", "The printer's measured bed is uneven under this print. This is an estimate from the bed mesh.",
                               "Re-run bed leveling, or add a brim and watch the first layer."),
    FIRST_LAYER_CORNER_LIFT: ("estimate", "A wide, flat, tall print can lift at the corners. This is an estimate from the geometry.",
                              "Add a brim and keep the print draft-free."),
    FIRST_LAYER_ORIENTATION: ("estimate", "A larger, flatter face on the bed would make the first layer more reliable. This is an estimate from the geometry.",
                              "Look at the orientation in Snapmaker Orca's preview."),
    PRINTER_FAILURE_HISTORY: ("engine", "The printer's own history lists failed prints. A file name is matched by name only, not by contents.",
                              "Check why the earlier print failed before starting this one."),
    FIRMWARE_NOT_READY: ("engine", "The printer's firmware did not report a ready state.", "Open Printer Hub and review the firmware state before printing."),
    FIRMWARE_FAILED_COMPONENT: ("engine", "The printer reported a failed firmware component.", "Open Printer Hub and review it before a long print."),
    FIRMWARE_WARNING: ("engine", "The printer's firmware reported a warning.", "Open Printer Hub and review it before a long print."),
}

_LEVEL = {"ok": 0, "warn": 1, "risk": 2}
# Evidence strength tie-break between contributors: a Doctor's own measurement, then the printer's history, then its
# readings, then a restatement by the predictor.
_SOURCE_RANK = {"doctor": 0, "history": 1, "health": 2, "predictor": 3}


def level_rank(level: str) -> int:
    return _LEVEL.get(level, 0)


def contribution(cid: str, level: str, headline: str, *, facts=None, action=None, source: str = "doctor") -> dict:
    """One source's statement about one condition. `facts=[]` means it only restates (adds severity/action, no new evidence)."""
    return {"id": cid, "level": level, "headline": headline,
            "facts": [headline] if facts is None else list(facts),
            "action": action, "source": source}


def merge(contributions: list) -> list:
    """One finding per condition id: max severity, merged evidence, the owning action, ranked."""
    groups: dict = {}
    order: dict = {}
    for c in contributions:
        groups.setdefault(c["id"], []).append(c)
        order.setdefault(c["id"], len(order))
    findings = []
    for cid, cs in groups.items():
        cs = sorted(cs, key=lambda c: (-level_rank(c["level"]), _SOURCE_RANK.get(c["source"], 9)))
        top = cs[0]
        facts: list = []
        for c in sorted(cs, key=lambda c: _SOURCE_RANK.get(c["source"], 9)):   # the order facts read in does not depend on severity
            for fact in c["facts"]:
                if fact and fact not in facts:   # display-level only: identical strings are shown once
                    facts.append(fact)
        text = "; ".join(facts) if (cid in JOIN_FACTS and len(facts) > 1) else top["headline"]
        action = next((c["action"] for c in cs if c.get("action")), None) or (COPY.get(cid) or (None, None, None))[2]
        findings.append({
            "id": cid, "level": top["level"], "text": text, "evidence": facts or [top["headline"]],
            "action": action, "doctor": (cid.split(":")[1] if cid.startswith("unmapped:") else DOCTOR_LABEL.get(cid, "Project Doctor")),
            "sources": sorted({c["source"] for c in cs}), "_order": order[cid],
        })
    findings.sort(key=lambda f: (-level_rank(f["level"]), -len(f["evidence"]), f["_order"]))
    for f in findings:
        f.pop("_order")
    return findings


def doctor_contributions(doc, label: str, source: str = "doctor") -> list:
    """Contributions from a Doctor result whose non-ok findings carry `id` (and optionally `action`).
    A finding with no id is its own, never-merged condition."""
    out = []
    if not doc or not doc.get("available", True):
        return out
    for i, f in enumerate(doc.get("findings") or []):
        if f.get("level") not in ("warn", "risk"):
            continue
        cid = f.get("id") or f"unmapped:{label}:{i}"
        out.append(contribution(cid, f["level"], f["text"], action=f.get("action"), source=source))
    return out
