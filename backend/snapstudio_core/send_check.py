"""Ready to send? — the last thing Studio says before a person presses the button.

Printer Hub can upload a sliced job and start it, and every one of those actions
already requires an explicit confirmation. This is what that confirmation should
be able to show: everything Studio can establish about whether this job, on this
machine, right now, is going to do what the person expects.

Three buckets, and the separation is the whole point:

* **Blocker** — a provable mismatch. The job asks for a tool the printer does not
  have; a slot it prints from is empty; it was sliced for another machine.
* **Warning** — a real concern that is not proof. A different colour is loaded; the
  printer is busy; the job pauses part-way through and nobody is standing there.
* **Unknown** — Studio cannot verify it. Free storage on a firmware that does
  not report any. The fitted nozzle, when neither the printer nor a person
  has said — firmware that does report it turns this into a pass or a
  warning instead (a nozzle mismatch is a real concern, not proof the print
  will fail, so it warns rather than blocks).

An unknown is never promoted to a blocker to look thorough, and never demoted to
a pass to look clean. And nothing here sends anything: this module returns a
report, and a person decides.
"""
from __future__ import annotations

from . import material_plan, post_slice
from .post_slice import _profile

SCHEMA_VERSION = "sendcheck/1"

BLOCKER = "blocker"
WARNING = "warning"
UNKNOWN = "unknown"
READY = "ready"


def _item(kind: str, title: str, detail: str, *, action: str | None = None,
          source: str | None = None) -> dict:
    return {"kind": kind, "title": title, "detail": detail,
            "action": action, "source": source}


def evaluate(gcode_facts: dict, printer: dict | None,
             plan: dict | None = None, timeline: dict | None = None,
             provenance: dict | None = None) -> dict:
    """Compose the send confirmation from facts gathered elsewhere."""
    if not gcode_facts.get("available"):
        return {
            "schema_version": SCHEMA_VERSION,
            "available": False,
            "verdict": UNKNOWN,
            "items": [],
            "headline": gcode_facts.get("error", "Studio could not read that G-code file."),
            "disclaimer": DISCLAIMER,
        }

    printer = printer or {}
    reachable = bool(printer.get("reachable"))
    checks = post_slice.analyse(gcode_facts, printer).get("checks", [])
    materials = plan or material_plan.from_facts(gcode_facts, printer)

    items: list[dict] = []

    # --- what the post-slice join already established ------------------------
    for check in checks:
        if check["result"] == post_slice.BLOCKED:
            items.append(_item(BLOCKER, check["title"], check["consequence"],
                               action=check.get("action"), source=check.get("source")))
        elif check["result"] == post_slice.ATTENTION:
            items.append(_item(WARNING, check["title"], check["consequence"],
                               action=check.get("action"), source=check.get("source")))
        elif check["result"] == post_slice.UNKNOWN:
            items.append(_item(UNKNOWN, check["title"], check["consequence"],
                               action=check.get("action"), source=check.get("source")))

    # An empty slot the job prints from stops the print part-way. That is a
    # blocker, not a warning — the filament runs out at layer 34, not at layer 0.
    if materials.get("printer_known"):
        for slot in materials.get("slots", []):
            if slot["state"] == "empty":
                items.append(_item(
                    BLOCKER, f"{slot['label'].capitalize()} is empty and this job uses it",
                    "The print will stop when it reaches that tool, part-way through.",
                    action=slot.get("action"),
                    source="G-code tool use vs printer filament state"))
            elif slot["state"] == "different_colour":
                items.append(_item(
                    WARNING, f"A different colour is loaded in {slot['label']}",
                    slot.get("detail") or "",
                    action=slot.get("action"),
                    source="G-code filament colour vs printer filament state"))

    # --- is this even the right file? ----------------------------------------
    #
    # Every check above is about a job. If that job is not the slice of the
    # project the user just checked, those checks are answering the wrong
    # question, which is worse than not answering.
    if provenance:
        verdict = provenance.get("verdict")
        if verdict == "no_match":
            items.append(_item(
                BLOCKER, "This does not look like the slice of your project",
                provenance.get("summary") or "",
                action="Pick the G-code that came from this project, or re-slice it.",
                source="project and job compared"))
        elif verdict == "ambiguous":
            items.append(_item(
                WARNING, "Studio cannot tie this job to your project",
                provenance.get("summary") or "",
                action="Check you picked the right file before you send it.",
                source="project and job compared"))
        elif verdict == "unknown":
            items.append(_item(
                UNKNOWN, "Whether this is the slice of your project",
                "Neither file states enough for Studio to tell.",
                action="Check the file yourself.",
                source="project and job compared"))

    # --- material sufficiency, where anything actually tracks it -------------
    for slot in (materials.get("slots") or []):
        sufficiency = slot.get("sufficiency") or {}
        # A blocker says "this print will fail". Only a figure that says where it
        # came from earns that: a tracked weight, short by more than the tracking
        # itself can drift. Anything less certain is a warning — stopping someone
        # from sending a job over bookkeeping that has not been updated since the
        # last three prints would teach them to ignore the warnings that matter.
        if sufficiency.get("verdict") == "insufficient" and sufficiency.get("trusted"):
            items.append(_item(
                BLOCKER, "Not enough filament in " + slot["label"],
                sufficiency.get("detail") or "",
                action=slot.get("action"),
                source=sufficiency.get("source")))
        elif sufficiency.get("verdict") in ("insufficient", "probably_short"):
            items.append(_item(
                WARNING, slot["label"].capitalize() + " may not have enough filament",
                sufficiency.get("detail") or "",
                action="Check the spool before you start, or have another to hand.",
                source=sufficiency.get("source")))
        elif sufficiency.get("verdict") == "probably_enough":
            items.append(_item(
                WARNING, slot["label"].capitalize() + " has little to spare",
                sufficiency.get("detail") or "",
                action="Have a spare spool to hand.",
                source=sufficiency.get("source")))

    # --- things only this moment can answer ----------------------------------
    size = gcode_facts.get("size_bytes")
    free = (printer or {}).get("free_bytes")
    if size and reachable:
        if free:
            if free < size:
                items.append(_item(
                    BLOCKER, "Not enough room on the printer",
                    f"The job is {size / 1e6:.0f} MB and the printer reports {free / 1e6:.0f} MB free.",
                    action="Delete some jobs from the printer first.",
                    source="printer storage"))
        else:
            # Why nothing could be read is evidence, and evidence belongs to the
            # machine it was gathered on. The U1 sentence below was traced on a
            # real U1; offered for any printer it becomes a claim about hardware
            # nobody looked at. An unidentified printer gets the plain fact that
            # Studio read no figure, which is all that is actually known.
            profile = _profile(printer)
            note = (profile or {}).get("storage_note")
            explain = (note if (profile or {}).get("reports_free_storage") is False and note
                       else "Studio read no free-space figure from this printer")
            items.append(_item(
                UNKNOWN, "Free space on the printer",
                f"This job is {size / 1e6:.0f} MB. Studio cannot tell you whether it will fit, "
                "because nothing it can read says how much room is left.",
                action="If uploads have failed before, clear some old jobs first.",
                source=explain))

    if not reachable:
        items.append(_item(
            UNKNOWN, "No printer to check against",
            "Studio checked the job on its own. Everything that depends on the machine "
            "stays unknown until it can reach one.",
            action="Connect your printer in Printer Hub.",
            source="no printer reachable"))

    # A job that stops for a person is worth knowing about before you walk away.
    pauses = (timeline or {}).get("pauses") or 0
    if pauses:
        items.append(_item(
            WARNING, "This job pauses and waits for you",
            f"It stops {pauses} time(s) and will not continue on its own.",
            action="Plan to be there, or expect to find it waiting.",
            source="pause commands in the job"))

    order = {BLOCKER: 0, WARNING: 1, UNKNOWN: 2}
    items.sort(key=lambda i: order.get(i["kind"], 9))

    counts = {kind: sum(1 for i in items if i["kind"] == kind)
              for kind in (BLOCKER, WARNING, UNKNOWN)}
    verdict = (BLOCKER if counts[BLOCKER] else
               WARNING if counts[WARNING] else
               UNKNOWN if counts[UNKNOWN] else READY)

    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "printer_reachable": reachable,
        "verdict": verdict,
        "counts": counts,
        "items": items,
        "materials": materials,
        "job": post_slice._job_brief(gcode_facts),
        "headline": _headline(verdict, counts, reachable),
        "disclaimer": DISCLAIMER,
    }


DISCLAIMER = ("This is what Studio can establish before you send. It is not a promise that "
              "the print will succeed, and Studio never sends anything on its own.")


def _headline(verdict: str, counts: dict, reachable: bool) -> str:
    if verdict == BLOCKER:
        return (f"{counts[BLOCKER]} thing(s) will stop this job on this printer. "
                "Sending it now wastes the upload.")
    if verdict == WARNING:
        return (f"Nothing blocks this job, but {counts[WARNING]} thing(s) are worth "
                "settling before you send it.")
    if verdict == UNKNOWN:
        if not reachable:
            return ("Nothing in the job itself looks wrong. Connect your printer to check it "
                    "against the machine you will print on.")
        return (f"Nothing Studio can check is wrong. {counts[UNKNOWN]} thing(s) it cannot "
                "check for you are listed below.")
    return "Everything Studio can check about this job on this printer looks right."
