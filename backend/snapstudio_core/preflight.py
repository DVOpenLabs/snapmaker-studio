"""Preflight — does *this* project match *this* printer?

Studio already knew two things separately: what a project needs (traits, placement,
filament count, nozzle sizes, capability dependencies) and what a printer reports
(toolheads, bed volume, firmware capabilities, current state). Nothing joined them,
so the app could tell you a project used six filaments and, on another page, that
your printer has four toolheads — and never put those two sentences together.

This module is that join. It takes the project facts and the printer facts and
produces one list of checks, each with a result, the evidence behind it, how
confident Studio is, what it means for the print, and what to do.

The rule that matters most:

    **Not detected is not the same as not supported.**

Stock Snapmaker U1 firmware does not report which nozzle is fitted — which was
established by looking, on a U1. That makes the nozzle check `unknown`, and
`unknown` is a real answer that tells the user to go and look; it is never quietly
rewritten as a pass or a failure. Every check here can return `unknown`, and
several usually do.

Nothing in this module is written for one printer. Every check reads what the
machine reported — its toolheads, its axis limits, its Klipper objects, its
filament state if it has any — so a machine that reports fewer toolheads, a
different bed, or no filament state at all is described as it is rather than as a
U1 with parts missing.

Read-only: this module never contacts a printer itself. It is a pure function over
facts gathered elsewhere, which is what makes every branch testable without hardware.
"""
from __future__ import annotations

SCHEMA_VERSION = "preflight/1"

# Results, worst to best. `attention` is deliberately not called "fail": most of
# these are things to check or change before slicing, not verdicts on the print.
BLOCKED = "blocked"        # this cannot work as-is on this printer
ATTENTION = "attention"    # a real mismatch the user has to resolve
UNKNOWN = "unknown"        # Studio could not determine it — say so, do not guess
OK = "ok"

_ORDER = {BLOCKED: 0, ATTENTION: 1, UNKNOWN: 2, OK: 3}

CONFIRMED = "confirmed"
LIKELY = "likely"
INFORMATIONAL = "informational"


def _check(cid: str, title: str, result: str, *, evidence: str | None,
           confidence: str, consequence: str, action: str | None = None,
           source: str | None = None) -> dict:
    return {
        "id": cid,
        "title": title,
        "result": result,
        "evidence": evidence,
        "confidence": confidence,
        "consequence": consequence,
        "action": action,
        "source": source,
    }


def _fallback_name() -> str:
    """The machine Studio compares against when no printer answered."""
    from . import printer_profiles

    return printer_profiles.display_name(printer_profiles.prepare_target())


def _trait(project: dict, key: str):
    """Value of a graded trait, or None when it was never measured."""
    entry = (project or {}).get(key)
    if isinstance(entry, dict) and "value" in entry:
        return entry["value"]
    return entry


def _trait_evidence(project: dict, key: str) -> str | None:
    entry = (project or {}).get(key)
    return entry.get("evidence") if isinstance(entry, dict) else None


# --- individual checks ------------------------------------------------------

def _printer_found(printer: dict) -> dict:
    if printer.get("reachable"):
        host = printer.get("host") or "your printer"
        return _check(
            "printer.reachable", "Printer found", OK,
            evidence=f"{host} answered on port {printer.get('port')}",
            confidence=CONFIRMED,
            consequence="Studio can compare this project against your actual printer.",
            source="Moonraker /server/info")
    return _check(
        "printer.reachable", "Printer not found", UNKNOWN,
        evidence=printer.get("error") or "no printer answered",
        confidence=CONFIRMED,
        consequence=("Studio can still check the project, but it cannot compare it "
                     "against your printer — everything below that needs the printer "
                     "stays unknown."),
        # The printer's own hint when there is one. The fallback stays generic:
        # Studio does not know what machine failed to answer, so telling someone
        # to change a setting on a specific model would be a guess.
        action=(printer.get("hint")
                or "Check the printer is powered on and on this network, then put the "
                   "address it shows into Printer Hub."),
        source="Moonraker /server/info")


def _toolheads_vs_filaments(project: dict, printer: dict) -> dict:
    needed = _trait(project, "filament_count")
    have = printer.get("toolhead_count")
    if not printer.get("reachable") or have is None:
        return _check(
            "materials.toolheads", "Toolheads and materials", UNKNOWN,
            evidence="the printer did not report how many toolheads it has",
            confidence=INFORMATIONAL,
            consequence="Studio cannot tell whether this project's materials fit your printer.",
            action="Connect the printer, then run this check again.",
            source="Klipper extruder objects")
    if not needed:
        return _check(
            "materials.toolheads", "Toolheads and materials", OK,
            evidence=f"this project assigns no filaments; your printer has {have} toolheads",
            confidence=CONFIRMED,
            consequence="You will choose materials in the slicer.",
            source="Klipper extruder objects")
    if needed <= have:
        return _check(
            "materials.toolheads", "Toolheads and materials", OK,
            evidence=f"project uses {needed} filament slot(s); printer reports {have} toolheads",
            confidence=CONFIRMED,
            consequence="Every material in this project has a toolhead to load it into.",
            source="Klipper extruder objects")
    return _check(
        "materials.toolheads", "More materials than toolheads", ATTENTION,
        evidence=f"project uses {needed} filament slot(s); printer reports {have} toolheads",
        confidence=CONFIRMED,
        consequence=(f"This project asks for {needed} materials and your printer can hold "
                     f"{have} at once. Some will need to be combined, dropped, or swapped "
                     "by hand during the print."),
        action="Open Colours & Materials to see which colours could be handled as swaps.",
        source="Klipper extruder objects")


def _nozzle(project: dict, printer: dict) -> dict:
    """The check that most often has to answer 'I do not know', and must.

    Stock U1 firmware DOES publish the fitted nozzle diameter, via
    /machine/system_info's product_info.nozzle_diameter (confirmed live
    against a real U1) — printer_facts() reads it and stamps
    nozzle_confirmed_by="printer" when it did. When the printer did not
    answer that (unreachable, or firmware genuinely omits the field), a
    user can confirm it themselves; that path is stamped
    nozzle_confirmed_by="user" and is reported as such, never blended into
    a live reading. Only when neither exists does this stay UNKNOWN.
    """
    wanted = _trait(project, "nozzle_diameters") or []
    reported = printer.get("nozzle_diameters")
    confirmed_by = printer.get("nozzle_confirmed_by")
    if not wanted:
        return _check(
            "nozzle.match", "Nozzle size", UNKNOWN,
            evidence="this project does not record a nozzle size",
            confidence=INFORMATIONAL,
            consequence="Studio cannot compare nozzles for this project.",
            action="Check the nozzle setting in the slicer before you print.",
            source="project settings")
    wanted_txt = ", ".join(f"{w} mm" for w in wanted)
    if not reported:
        return _check(
            "nozzle.match", "Nozzle size — check this yourself", UNKNOWN,
            evidence=f"project expects {wanted_txt}; the printer does not report which "
                     "nozzle is fitted",
            confidence=CONFIRMED,
            consequence=("Printing with a different nozzle than the project was made for "
                         "changes line width and can ruin fine detail — and Studio has no "
                         "way to see which one is installed."),
            action=f"Check the nozzle on the printer is {wanted_txt} before slicing, "
                   "or confirm it in Printer settings so Studio can check it for you.",
            source="firmware exposes no nozzle diameter")
    if confirmed_by == "printer":
        source, who, verb = "printer firmware", "the printer", "reports"
    else:
        source, who, verb = "user confirmed", "you", "confirmed"
    reported_set = {str(n) for n in reported}
    if reported_set == {str(w) for w in wanted}:
        return _check(
            "nozzle.match", "Nozzle size", OK,
            evidence=f"project expects {wanted_txt}; {who} {verb} the same",
            confidence=CONFIRMED,
            consequence=f"The project was made for the nozzle {who} {verb}.",
            source=source)
    return _check(
        "nozzle.match", "Nozzle size does not match", ATTENTION,
        evidence=f"project expects {wanted_txt}; {who} {verb} "
                 + ", ".join(f"{n} mm" for n in sorted(reported_set)),
        confidence=CONFIRMED,
        consequence=("Line width and detail will not come out as the creator intended, "
                     "and very fine features may disappear."),
        action="Fit the nozzle the project expects, or re-slice for the nozzle you have.",
        source=source)


def _bed(project: dict, printer: dict, placement: dict | None) -> dict:
    bed = printer.get("bed_mm")
    if not printer.get("reachable") or not bed:
        return _check(
            "bed.fit", "Fits the printer's bed", UNKNOWN,
            evidence="the printer did not report its bed size",
            confidence=INFORMATIONAL,
            consequence=("Studio checked the project against the recorded volume of the "
                         f"{_fallback_name()} instead."),
            action="Connect the printer to check against its real bed.",
            source="Klipper toolhead axis limits")
    size = f"{bed.get('x')} × {bed.get('y')} × {bed.get('z')} mm"
    if not placement or not placement.get("available"):
        return _check(
            "bed.fit", "Fits the printer's bed", UNKNOWN,
            evidence=f"printer bed is {size}; Studio could not read where the objects sit",
            confidence=INFORMATIONAL,
            consequence="Studio cannot confirm the objects land on this printer's plate.",
            action="Open the project in the slicer to see the plate.",
            source="Klipper toolhead axis limits")
    off = placement.get("off_plate") or []
    if not off:
        return _check(
            "bed.fit", "Fits the printer's bed", OK,
            evidence=f"every object sits inside this printer's {size} area",
            confidence=CONFIRMED,
            consequence="Nothing is placed off the plate.",
            source="project geometry vs printer bed")
    return _check(
        "bed.fit", "Objects sit outside this printer's bed", ATTENTION,
        evidence=f"{len(off)} object(s) fall outside this printer's {size} area",
        confidence=CONFIRMED,
        consequence=("The slicer will refuse to slice, or the print will start off the "
                     "plate."),
        action=("Use Studio's object-placement fix to move them on — it saves a copy and "
                "leaves your original alone." if placement.get("fixable")
                else "Open the project in Snapmaker Orca and use Arrange."),
        source="project geometry vs printer bed")


def _object_exclusion(project: dict, printer: dict) -> dict:
    """Only reported when the project actually depends on it."""
    objects = printer.get("klipper_objects") or []
    exposed = any(str(o).split(" ", 1)[0].strip().lower() == "exclude_object" for o in objects)
    wants = bool(_trait(project, "expects_object_exclusion"))
    if not wants:
        # The project does not rely on it, so raising it either way would be noise.
        # A U1 copy prepared by Studio always does, which is when it matters.
        return None
    if not printer.get("reachable") or not objects:
        return _check(
            "capability.exclude_object", "Skipping a failed object", UNKNOWN,
            evidence="the printer did not report its firmware features",
            confidence=INFORMATIONAL,
            consequence="Studio cannot confirm this printer can cancel one object mid-print.",
            action="Connect the printer to check.",
            source="Klipper object list")
    if exposed:
        return _check(
            "capability.exclude_object", "Skipping a failed object", OK,
            evidence="the printer's firmware exposes object exclusion",
            confidence=CONFIRMED,
            consequence=("If one object on the plate fails you can cancel just that one "
                         "and keep the rest."),
            source="Klipper object list")
    return _check(
        "capability.exclude_object", "Skipping a failed object is not available", ATTENTION,
        evidence="the printer's firmware does not list object exclusion",
        confidence=CONFIRMED,
        consequence=("If one object fails you will lose the whole plate, and adaptive bed "
                     "mesh has no object outlines to work from."),
        action="This is a firmware feature — nothing to change in the project.",
        source="Klipper object list")


def _printer_busy(printer: dict) -> dict | None:
    state = (printer.get("print_state") or "").strip().lower()
    if not printer.get("reachable") or not state:
        return None
    if state in ("printing", "paused"):
        return _check(
            "printer.busy", "Printer is busy", ATTENTION,
            evidence=f"the printer reports it is {state}",
            confidence=CONFIRMED,
            consequence="You cannot start this project until the current job finishes.",
            action="Wait for the current print, or cancel it from Printer Hub yourself.",
            source="Klipper print_stats")
    return _check(
        "printer.busy", "Printer is free", OK,
        evidence=f"the printer reports it is {state}",
        confidence=CONFIRMED,
        consequence="Nothing else is using the printer.",
        source="Klipper print_stats")


def _loaded_materials(project: dict, printer: dict) -> dict | None:
    """Only meaningful when the printer actually reports what is loaded."""
    loaded = printer.get("loaded_filaments")
    needed = _trait(project, "filament_count") or 0
    if not printer.get("reachable"):
        return None
    if loaded is None:
        if not needed:
            return None
        return _check(
            "materials.loaded", "What is loaded right now", UNKNOWN,
            evidence="this printer does not report which filaments are loaded",
            confidence=CONFIRMED,
            consequence=("Studio cannot tell whether the colours in this project are the "
                         "ones currently in the machine."),
            action="Check the spools on the printer against the project's colours.",
            source="firmware does not expose loaded filament")
    filled = [f for f in loaded if f]
    if needed and len(filled) < needed:
        return _check(
            "materials.loaded", "Fewer materials loaded than the project uses", ATTENTION,
            evidence=f"printer reports {len(filled)} loaded; project uses {needed}",
            confidence=CONFIRMED,
            consequence="Some of the project's materials have nothing to print with.",
            action="Load the missing materials before you start.",
            source="printer filament state")
    return _check(
        "materials.loaded", "What is loaded right now", OK,
        evidence=f"printer reports {len(filled)} loaded material(s)",
        confidence=CONFIRMED,
        consequence="The printer has at least as many materials loaded as the project uses.",
        source="printer filament state")


def _sliced_state(project: dict) -> dict:
    if _trait(project, "is_sliced"):
        return _check(
            "project.sliced", "Already sliced", OK,
            evidence=_trait_evidence(project, "is_sliced") or "plate g-code in the project",
            confidence=CONFIRMED,
            consequence=("This project already contains toolpaths from another machine. "
                         "Studio removes them when it prepares a U1 copy so Snapmaker Orca "
                         "slices fresh."),
            action="Prepare a U1 copy, then slice it in Snapmaker Orca.",
            source="project archive")
    return _check(
        "project.sliced", "Not sliced yet", OK,
        evidence="no toolpaths in this project",
        confidence=CONFIRMED,
        consequence="Snapmaker Orca will slice it. Studio does not slice.",
        action="Prepare a U1 copy, then open it in Snapmaker Orca.",
        source="project archive")


# --- assembly ---------------------------------------------------------------

def evaluate(project: dict, printer: dict, placement: dict | None = None) -> dict:
    """Join project facts to printer facts. Pure — never contacts anything.

    ``project`` is the graded dict from ``project_traits.extract``.
    ``printer`` is the fact bundle described in ``printer_facts``.
    ``placement`` is an optional ``plate_placement.assess`` result, ideally run
    against the printer's real bed.
    """
    project = project or {}
    printer = printer or {}

    checks = [
        _printer_found(printer),
        _bed(project, printer, placement),
        _toolheads_vs_filaments(project, printer),
        _nozzle(project, printer),
        _loaded_materials(project, printer),
        _object_exclusion(project, printer),
        _printer_busy(printer),
        _sliced_state(project),
    ]
    checks = [c for c in checks if c]

    counts = {BLOCKED: 0, ATTENTION: 0, UNKNOWN: 0, OK: 0}
    for c in checks:
        counts[c["result"]] += 1

    ordered = sorted(checks, key=lambda c: _ORDER[c["result"]])
    return {
        "schema_version": SCHEMA_VERSION,
        "checks": ordered,
        "counts": counts,
        "needs_attention": [c for c in ordered if c["result"] in (BLOCKED, ATTENTION)],
        "unknowns": [c for c in ordered if c["result"] == UNKNOWN],
        "printer_reachable": bool(printer.get("reachable")),
        "summary": _summary(counts, printer),
        "disclaimer": ("These are checks against what your printer reports right now. "
                       "They are advisory — Studio cannot promise a print will succeed."),
    }


def _summary(counts: dict, printer: dict) -> str:
    if not printer.get("reachable"):
        return ("Studio could not reach a printer, so it checked the project on its own. "
                "Connect your printer to compare this project against the actual machine.")
    attention = counts[BLOCKED] + counts[ATTENTION]
    unknown = counts[UNKNOWN]
    if attention == 0 and unknown == 0:
        return "Nothing to resolve — this project matches what your printer reports."
    parts = []
    if attention:
        parts.append(f"{attention} thing{'s' if attention != 1 else ''} to resolve")
    if unknown:
        parts.append(f"{unknown} thing{'s' if unknown != 1 else ''} Studio cannot check for you")
    # capitalize() would lowercase the rest of the sentence, which turns
    # "Studio" into "studio". Only the first character should change.
    text = " and ".join(parts)
    return text[:1].upper() + text[1:] + " before you slice."
