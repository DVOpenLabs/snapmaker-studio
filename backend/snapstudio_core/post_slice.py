"""Post-Slice Doctor — what the printer is actually going to execute.

Everything Studio checked before this point looked at the *source project*: its
geometry, its materials, its settings. That answers "is this file sensible?". It
does not answer "is the thing I am about to press Print on going to work?",
because between the two sits a slicer that made hundreds of decisions.

This module reads the sliced job's own statements (`gcode.read_facts`) and joins
them to the printer as it is *right now*. The interesting failures live exactly
here and nowhere else:

* the job uses tool 2 and slot 2 is empty;
* the job was sliced for PETG and PLA is loaded;
* the job was sliced for a different machine entirely;
* the job needs object exclusion and this firmware does not list it.

None of those are visible in the project file, and none are visible on the
printer alone.

The honesty rules are the same as everywhere else in Studio. A fact the G-code
does not state is unknown. A printer that cannot be reached makes printer-dependent
checks unknown, never failed. Nothing here contacts a printer or changes anything:
it is a pure function over facts gathered elsewhere, which is why every branch is
testable without hardware.
"""
from __future__ import annotations

SCHEMA_VERSION = "post_slice/1"

BLOCKED = "blocked"
ATTENTION = "attention"
UNKNOWN = "unknown"
OK = "ok"

_ORDER = {BLOCKED: 0, ATTENTION: 1, UNKNOWN: 2, OK: 3}

CONFIRMED = "confirmed"
LIKELY = "likely"
INFORMATIONAL = "informational"


def _check(cid: str, title: str, result: str, *, evidence: str | None,
           confidence: str, consequence: str, action: str | None = None,
           source: str | None = None) -> dict:
    return {
        "id": cid, "title": title, "result": result, "evidence": evidence,
        "confidence": confidence, "consequence": consequence,
        "action": action, "source": source,
    }


def _normalise_material(value: str | None) -> str | None:
    """"PLA Matte" and "PLA" compare equal at the family level.

    Material naming is not standardised: the printer says "PLA Matte", the slicer
    says "PLA", and a strict comparison would report a mismatch on every
    multi-material print anyone has ever done. Compare families, and say so.
    """
    if not value:
        return None
    return value.strip().split()[0].upper()


def _slot_word(index: int) -> str:
    return f"slot {index + 1}"


# --- individual checks ------------------------------------------------------

def _machine_match(g: dict, printer: dict) -> dict:
    """Was this job sliced for the machine it is about to run on?

    This check used to be the clearest U1 assumption in Studio: it asked whether
    the model name in the file contained "u1" or "snapmaker", so a job correctly
    sliced for any other printer was reported as wrong, and a job sliced for a
    *different Snapmaker* was reported as right. The question it should ask is
    whether the job's machine and the connected machine are the same machine.

    When no printer has been identified there is no connected machine to compare
    with, so the comparison falls back to the one Studio prepares copies for — and
    says so in those words, because "this is not the printer Studio prepares for"
    and "this is not the printer you are about to use" are different statements.
    """
    from . import printer_profiles

    sliced_for = g.get("printer_model")
    identity = (printer or {}).get("identity") or {}
    target_id = identity.get("printer_id")
    live = bool(target_id)
    if not live:
        target_id = printer_profiles.PREPARE_TARGET_ID
    try:
        target = printer_profiles.load(target_id)
    except KeyError:
        target = printer_profiles.prepare_target()
    target_name = printer_profiles.display_name(target)
    against = ("the printer Studio has identified" if live
               else f"the {target_name} Studio prepares copies for")

    if not sliced_for:
        return _check(
            "gcode.machine", "Which machine this was sliced for", UNKNOWN,
            evidence="the file does not name a printer model",
            confidence=CONFIRMED,
            consequence=("Studio cannot tell whether this job was made for the machine you "
                         "are about to print on or for another printer."),
            action="Check in your slicer which printer profile produced this file.",
            source="G-code configuration block")

    stated = printer_profiles.identify_model_string(sliced_for)
    if stated.get("matched") and stated["printer_id"] == target_id:
        return _check(
            "gcode.machine",
            "Sliced for this machine" if live else "Sliced for the machine Studio prepares for",
            OK,
            evidence=f"the file says it was sliced for {sliced_for}",
            confidence=CONFIRMED,
            consequence=f"The job's commands were generated for a {target_name}.",
            source="G-code configuration block")

    if stated.get("matched"):
        other = printer_profiles.display_name(printer_profiles.load(stated["printer_id"]))
        detail = f"the file says it was sliced for {sliced_for}, which is a {other}"
    else:
        # Studio does not recognise the name. That is not proof of a mismatch —
        # but it is not this machine's name either, and a job carrying another
        # machine's toolpaths is the failure this check exists for.
        detail = (f"the file says it was sliced for {sliced_for}, which is not a name "
                  f"Studio recognises as {target_name}")

    return _check(
        "gcode.machine", "Sliced for a different printer", ATTENTION,
        evidence=detail,
        confidence=CONFIRMED if stated.get("matched") else LIKELY,
        consequence=("Toolpaths, temperatures and machine commands are generated for one "
                     f"specific machine. Sending another printer's job to a {target_name} "
                     "usually fails immediately and can crash the toolhead."),
        action=(f"Re-slice this model with a {target_name} profile."
                if target_id != printer_profiles.PREPARE_TARGET_ID
                else "Re-slice this model in Snapmaker Orca with a U1 profile."),
        source=f"G-code configuration block, compared against {against}")


def _bed_fit(g: dict, printer: dict) -> dict | None:
    sliced_bed = g.get("bed_mm")
    if not sliced_bed:
        return None
    live = (printer or {}).get("bed_mm")
    if not live:
        return _check(
            "gcode.bed", "The bed this was sliced for", UNKNOWN,
            evidence=f"sliced for a {sliced_bed['x']} × {sliced_bed['y']} mm bed; "
                     "Studio could not reach a printer to compare",
            confidence=CONFIRMED,
            consequence="Studio cannot confirm the job fits the machine you will print on.",
            action="Connect your printer in Printer Hub to compare.",
            source="G-code configuration block")

    too_wide = sliced_bed["x"] > float(live.get("x", 0)) + 1
    too_deep = sliced_bed["y"] > float(live.get("y", 0)) + 1
    if too_wide or too_deep:
        return _check(
            "gcode.bed", "Sliced for a bigger bed than this printer", ATTENTION,
            evidence=(f"sliced for {sliced_bed['x']} × {sliced_bed['y']} mm; "
                      f"this printer reports {live.get('x')} × {live.get('y')} mm"),
            confidence=CONFIRMED,
            consequence="Anything the slicer placed outside this printer's area will not print where it should.",
            action="Re-slice with the correct printer profile.",
            source="G-code vs the printer's own reported bed")

    return _check(
        "gcode.bed", "Bed size matches", OK,
        evidence=(f"sliced for {sliced_bed['x']} × {sliced_bed['y']} mm; "
                  f"this printer reports {live.get('x')} × {live.get('y')} mm"),
        confidence=CONFIRMED,
        consequence="The job was sliced for this printer's bed.",
        source="G-code vs the printer's own reported bed")


def _tools_available(g: dict, printer: dict) -> dict | None:
    tools = g.get("tools_used")
    if tools is None:
        return _check(
            "gcode.tools", "Which tools this job uses", UNKNOWN,
            evidence="the file does not report per-tool filament use",
            confidence=CONFIRMED,
            consequence="Studio cannot tell which toolheads this job needs.",
            action="Open the job in Snapmaker Orca to see its tool assignments.",
            source="G-code summary block")

    count = (printer or {}).get("toolhead_count")
    needed = max(tools) + 1 if tools else 0
    listed = ", ".join(_slot_word(t) for t in tools) or "none"
    if count is None:
        return _check(
            "gcode.tools", "Tools this job needs", UNKNOWN,
            evidence=f"the job prints from {listed}; Studio could not ask a printer how many toolheads it has",
            confidence=CONFIRMED,
            consequence="Studio cannot confirm your printer has the toolheads this job expects.",
            action="Connect your printer in Printer Hub to compare.",
            source="G-code summary block")

    if needed > int(count):
        return _check(
            "gcode.tools", "The job needs a toolhead this printer does not have", BLOCKED,
            evidence=f"the job prints from {listed}; this printer reports {count} toolheads",
            confidence=CONFIRMED,
            consequence="The printer cannot select a toolhead that does not exist. The job will fail at the first tool change.",
            action="Re-slice with the tools your printer actually has.",
            source="G-code vs Klipper extruder objects")

    return _check(
        "gcode.tools", "Every toolhead this job needs exists", OK,
        evidence=f"the job prints from {listed}; this printer reports {count} toolheads",
        confidence=CONFIRMED,
        consequence="The printer can select every tool the job asks for.",
        source="G-code vs Klipper extruder objects")


def _slots_loaded(g: dict, printer: dict) -> dict | None:
    tools = g.get("tools_used")
    if not tools:
        return None
    loaded = (printer or {}).get("loaded_filaments")
    if loaded is None:
        return _check(
            "gcode.loaded", "Whether the slots this job uses are loaded", UNKNOWN,
            evidence="Studio could not read the printer's loaded filament",
            confidence=CONFIRMED,
            consequence="A job that starts with an empty slot stops at the first tool change.",
            action="Connect your printer in Printer Hub, or check the spools yourself.",
            source="printer filament state")

    empty = [t for t in tools if t >= len(loaded) or not loaded[t]]
    if empty:
        which = ", ".join(_slot_word(t) for t in empty)
        return _check(
            "gcode.loaded", "This job needs a slot that is empty", ATTENTION,
            evidence=f"the job prints from {which}, and the printer reports nothing loaded there",
            confidence=CONFIRMED,
            consequence="The print will stop when it reaches that tool, part-way through.",
            action=f"Load filament into {which} before starting.",
            source="G-code tool use vs printer filament state")

    return _check(
        "gcode.loaded", "Every slot this job uses is loaded", OK,
        evidence=f"{len(tools)} slot(s) in use, all reporting a spool",
        confidence=CONFIRMED,
        consequence="Nothing will stop for a missing spool.",
        source="G-code tool use vs printer filament state")


def _material_match(g: dict, printer: dict) -> dict | None:
    tools = g.get("tools_used")
    loaded = (printer or {}).get("loaded_filaments")
    if not tools or loaded is None:
        return None

    slots = {s["tool"]: s for s in g.get("slots", [])}
    mismatches = []
    compared = 0
    for tool in tools:
        want = _normalise_material((slots.get(tool) or {}).get("type"))
        have_entry = loaded[tool] if tool < len(loaded) else None
        have = _normalise_material((have_entry or {}).get("material"))
        if not want or not have:
            continue
        compared += 1
        if want != have:
            mismatches.append(
                f"{_slot_word(tool)}: sliced for {want}, loaded {(have_entry or {}).get('material')}")

    if not compared:
        return _check(
            "gcode.material", "Material match", UNKNOWN,
            evidence="either the job or the printer did not state a material for the slots in use",
            confidence=CONFIRMED,
            consequence="Printing PETG settings with PLA loaded, or the reverse, ruins the print and can block the nozzle.",
            action="Check the spools against the job's materials yourself.",
            source="G-code filament types vs printer filament state")

    if mismatches:
        return _check(
            "gcode.material", "Loaded material differs from the job", ATTENTION,
            evidence="; ".join(mismatches),
            confidence=CONFIRMED,
            consequence=("The temperatures, speeds and cooling in this job were generated for a "
                         "different material. At best the print looks wrong; at worst the nozzle jams."),
            action="Load the material the job was sliced for, or re-slice for what is loaded.",
            source="G-code filament types vs printer filament state")

    return _check(
        "gcode.material", "Loaded material matches the job", OK,
        evidence=f"{compared} slot(s) compared at material-family level",
        confidence=LIKELY,
        consequence="The job's temperatures and speeds suit what is loaded.",
        action=None,
        source="G-code filament types vs printer filament state — compared by family, so PLA Matte counts as PLA")


def _nozzle_number(value) -> str:
    """Normalise a nozzle-size value for comparison: 0.4, "0.4", "0.40" and
    0.4000000059604645 (real float noise a firmware or a job can report) all
    compare equal. Falls back to the raw string for anything not numeric,
    rather than crashing on malformed G-code or firmware data."""
    try:
        return f"{round(float(value), 2):g}"
    except (TypeError, ValueError):
        return str(value)


def _nozzles_match(wanted: list, reported: list) -> bool:
    """Same toolhead count on both sides: compare position by position — a
    job sliced for [0.4, 0.6, 0.4, 0.4] and a printer reporting
    [0.4, 0.4, 0.6, 0.4] have the identical sizes but on different
    toolheads, a real mismatch a set comparison would call a match.
    Different counts: there is no toolhead to align position by position,
    so fall back to comparing which sizes exist at all."""
    if len(wanted) == len(reported):
        return all(_nozzle_number(w) == _nozzle_number(r) for w, r in zip(wanted, reported))
    return {_nozzle_number(w) for w in wanted} == {_nozzle_number(r) for r in reported}


def _nozzle(g: dict, printer: dict) -> dict:
    sizes = g.get("nozzle_diameter_mm") or []
    unique = sorted({s for s in sizes if s})
    stated = ", ".join(f"{s:g} mm" for s in unique) if unique else None
    if not stated:
        return _check(
            "gcode.nozzle", "Nozzle size — check this yourself", UNKNOWN,
            evidence="the file does not state a nozzle diameter",
            confidence=CONFIRMED,
            consequence="Printing with a different nozzle than the job expects changes every line width.",
            action="Check the nozzle on the printer before starting.",
            source="G-code configuration block")

    # Once a job is sliced, the same live-firmware or user-confirmed reading
    # preflight() already joins against the *project* can be joined against
    # the *job* instead — a stock U1 genuinely does publish this via
    # /machine/system_info (printer_facts() reads it), and a person can
    # confirm it themselves when firmware does not. Neither is invented here;
    # this only reads what printer_facts() already put on `printer`.
    reported = (printer or {}).get("nozzle_diameters")
    if reported:
        confirmed_by = (printer or {}).get("nozzle_confirmed_by")
        if confirmed_by == "printer":
            label, who, verb = "this printer's firmware", "the printer", "reports"
        elif confirmed_by == "user":
            label, who, verb = "user confirmed", "you", "confirmed"
        else:
            label, who, verb = "an unstated source", "something Studio read", "reports"
        if _nozzles_match(sizes, reported):
            return _check(
                "gcode.nozzle", "Nozzle size matches", OK,
                evidence=f"the job was sliced for {stated}; {who} {verb} the same",
                confidence=CONFIRMED,
                consequence=f"The job was sliced for the nozzle {who} {verb}.",
                source=f"G-code configuration block; {label}")
        # Same toolhead count: show the real per-toolhead values, not the
        # deduplicated `stated` set — [0.4, 0.6] vs [0.4, 0.6] would otherwise
        # look identical in the evidence even though the sizes sit on
        # different toolheads, which is exactly the mismatch being reported.
        # Different counts: there is no toolhead to line up, so fall back to
        # the deduplicated sets, same as _nozzles_match's own fallback.
        if len(sizes) == len(reported):
            stated_mismatch_txt = ", ".join(f"{_nozzle_number(s)} mm" for s in sizes)
            reported_txt = ", ".join(f"{_nozzle_number(n)} mm" for n in reported)
        else:
            stated_mismatch_txt = stated
            reported_txt = ", ".join(f"{n} mm" for n in sorted({_nozzle_number(n) for n in reported}))
        return _check(
            "gcode.nozzle", "Nozzle size does not match", ATTENTION,
            evidence=(f"the job was sliced for {stated_mismatch_txt}; {who} {verb} " + reported_txt),
            confidence=CONFIRMED,
            consequence=("Printing with a different nozzle than the job was sliced for changes "
                        "line width and can ruin fine detail."),
            action="Fit the nozzle the job expects, or re-slice for the nozzle you have.",
            source=f"G-code configuration block; {label}")

    # "Stock firmware does not report which nozzle is fitted" is a fact about the
    # U1, established by looking. Stated flatly it becomes a claim about every
    # machine Studio is pointed at, which this project has not checked. So that
    # evidence is only offered for a printer it was actually established on.
    profile = _profile(printer)
    if profile is not None and profile.get("reports_fitted_nozzle") is False:
        why = "this printer's firmware does not report which nozzle is fitted"
        source = "G-code configuration block; this printer's firmware exposes no nozzle diameter"
    else:
        why = "Studio has no reading of which nozzle is fitted"
        source = "G-code configuration block; no nozzle diameter was read from the printer"
    return _check(
        "gcode.nozzle", "Nozzle size — check this yourself", UNKNOWN,
        evidence=f"the job was sliced for {stated}; {why}",
        confidence=CONFIRMED,
        consequence=("Printing with a different nozzle than the job was sliced for changes line "
                     "width and can ruin fine detail — and Studio has no way to see which one is installed."),
        action=f"Check the nozzle on the printer is {stated} before starting.",
        source=source)


def _profile(printer: dict | None) -> dict | None:
    """The profile of the printer that actually answered, or None.

    None is the common case and the correct one: Moonraker publishes no model
    name, so most machines stay unidentified, and every check here works without
    knowing which machine it is talking to. Identification only ever adds
    evidence — it never gates a check.
    """
    from . import printer_profiles

    identity = (printer or {}).get("identity") or {}
    pid = identity.get("printer_id")
    if not pid:
        return None
    try:
        return printer_profiles.load(pid)
    except KeyError:
        return None


def _busy(printer: dict) -> dict | None:
    state = (printer or {}).get("print_state")
    if not state:
        return None
    if state.lower() in ("printing", "paused"):
        return _check(
            "printer.busy", "The printer is busy", ATTENTION,
            evidence=f"the printer reports it is {state}",
            confidence=CONFIRMED,
            consequence="Starting another job now will be refused, or will interrupt the one running.",
            action="Wait for the current job to finish.",
            source="Klipper print_stats")
    return _check(
        "printer.busy", "Printer is free", OK,
        evidence=f"the printer reports it is {state}",
        confidence=CONFIRMED,
        consequence="Nothing else is using the printer.",
        source="Klipper print_stats")


def _exclusion(g: dict, printer: dict) -> dict | None:
    exclude = g.get("exclude_object") or {}
    if not exclude.get("present"):
        return None
    objects = (printer or {}).get("klipper_objects")
    if not objects:
        return _check(
            "gcode.exclusion", "This job can skip failed objects — if the firmware supports it", UNKNOWN,
            evidence=f"the job defines {exclude.get('objects')} excludable object(s); "
                     "Studio could not read the firmware's object list",
            confidence=CONFIRMED,
            consequence="Without firmware support the exclusion commands are ignored, which is harmless.",
            action="Connect your printer in Printer Hub to confirm.",
            source="EXCLUDE_OBJECT_DEFINE in the job")
    has = any("exclude_object" in str(o) for o in objects)
    return _check(
        "gcode.exclusion",
        "Failed objects can be skipped" if has else "This job's object exclusion will be ignored",
        OK if has else ATTENTION,
        evidence=(f"the job defines {exclude.get('objects')} excludable object(s); "
                  f"the firmware {'lists' if has else 'does not list'} an exclude_object module"),
        confidence=CONFIRMED,
        consequence=("If one object fails you can cancel just that one." if has else
                     "If one object fails you can only cancel the whole plate."),
        action=None if has else "Nothing to fix — the print still works, you just lose per-object cancelling.",
        source="EXCLUDE_OBJECT_DEFINE vs the firmware's own object list")


def _project_match(g: dict, project: dict | None) -> dict | None:
    """Does this sliced job plausibly belong to the project Studio has open?"""
    if not project:
        return None
    project_tools = project.get("filament_slots") or project.get("filament_count")
    job_tools = g.get("tools_used")
    if not project_tools or job_tools is None:
        return None
    if len(job_tools) > int(project_tools):
        return _check(
            "gcode.project", "The sliced job uses more materials than the open project", ATTENTION,
            evidence=f"the job prints from {len(job_tools)} slot(s); the open project defines {project_tools}",
            confidence=LIKELY,
            consequence="This G-code may have been sliced from a different file than the one Studio has open.",
            action="Check you picked the right G-code for this project.",
            source="G-code tool use vs the open project")
    return _check(
        "gcode.project", "The sliced job matches the open project", OK,
        evidence=f"the job prints from {len(job_tools)} slot(s); the project defines {project_tools}",
        confidence=LIKELY,
        consequence="The job looks like it came from this project.",
        source="G-code tool use vs the open project")


# --- the report -------------------------------------------------------------

def analyse(gcode_facts: dict, printer: dict | None = None,
            project: dict | None = None) -> dict:
    """Join a sliced job to a printer and, optionally, to the open project."""
    if not gcode_facts.get("available"):
        return {
            "schema_version": SCHEMA_VERSION,
            "available": False,
            "checks": [],
            "counts": {},
            "summary": gcode_facts.get("error", "Studio could not read that G-code file."),
            "disclaimer": DISCLAIMER,
        }

    printer = printer or {}
    reachable = bool(printer.get("reachable"))

    checks = [c for c in (
        _machine_match(gcode_facts, printer),
        _tools_available(gcode_facts, printer),
        _slots_loaded(gcode_facts, printer),
        _material_match(gcode_facts, printer),
        _bed_fit(gcode_facts, printer),
        _nozzle(gcode_facts, printer),
        _exclusion(gcode_facts, printer),
        _busy(printer),
        _project_match(gcode_facts, project),
    ) if c]

    checks.sort(key=lambda c: _ORDER.get(c["result"], 9))
    counts: dict[str, int] = {}
    for check in checks:
        counts[check["result"]] = counts.get(check["result"], 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "printer_reachable": reachable,
        "job": _job_brief(gcode_facts),
        "checks": checks,
        "counts": counts,
        "needs_attention": [c for c in checks if c["result"] in (BLOCKED, ATTENTION)],
        "unknowns": [c for c in checks if c["result"] == UNKNOWN],
        "summary": _summary(checks, reachable),
        "disclaimer": DISCLAIMER,
    }


DISCLAIMER = ("This reads what the sliced file says it will do. It is not a simulation of "
              "the print, and Studio does not slice — Snapmaker Orca does.")


def _job_brief(g: dict) -> dict:
    filament = g.get("filament") or {}
    return {
        "slicer": g.get("slicer"),
        "slicer_version": g.get("slicer_version"),
        "printer_model": g.get("printer_model"),
        "layer_count": g.get("layer_count"),
        "layer_height_mm": g.get("layer_height_mm"),
        "max_z_mm": g.get("max_z_mm"),
        "estimated_seconds": g.get("estimated_seconds"),
        "tools_used": g.get("tools_used"),
        "total_g": filament.get("total_g"),
        "size_bytes": g.get("size_bytes"),
        "purge": g.get("purge"),
    }


def _summary(checks: list[dict], reachable: bool) -> str:
    blocked = [c for c in checks if c["result"] == BLOCKED]
    attention = [c for c in checks if c["result"] == ATTENTION]
    unknown = [c for c in checks if c["result"] == UNKNOWN]

    if blocked:
        return (f"{len(blocked)} thing(s) will stop this job on this printer. "
                "Fix those before you send it.")
    parts = []
    if attention:
        parts.append(f"{len(attention)} thing(s) to sort out before you print")
    if unknown:
        parts.append(f"{len(unknown)} thing(s) Studio cannot check for you")
    if not parts:
        if not reachable:
            return ("Nothing in the job itself looks wrong. Connect your printer to check it "
                    "against the machine you will actually print on.")
        return "Everything Studio can check about this job against this printer looks right."
    text = " and ".join(parts)
    return text[:1].upper() + text[1:] + "."
