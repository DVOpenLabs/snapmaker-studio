"""Ready Now — which projects in the library could be printed on this printer today?

This is not a new analysis engine. Every fact below was already established by
something else: what a project is and asks for (`project_traits`), whether it fits
the printer as it stands (`preflight.evaluate`), and whether a loaded spool suits a
material (`material_plan.family`, `colour_distance`, `_sufficiency`). This module
only joins those answers into one bucket per project, and says why.

Buckets, in the order they are decided (the first that applies wins):

  1. needs_preparation  a project from another printer; Studio can prepare a U1 copy.
                        Needs no printer, so it holds when the printer is offline.
  2. needs_attention    preflight found something to resolve (bed, toolheads, nozzle,
                        busy printer), or a spool is trustworthily too light.
  3. cant_determine     Studio does not know: no printer, no readable file, no stated
                        materials, nothing says what is loaded, or the project's weight
                        is known and the spool's is not.
  4. one_change_away    a material has no suitable spool, but a load or swap fixes it.
  5. ready_now          every material has a suitable loaded spool.

Two honesty rules the buckets rest on. A different colour of the right material is a
note, never a pass or a fail ("Prints now, but the loaded colour differs from the
project") and Studio never calls it correct. And a weight nobody checked is said to be
unchecked (`amount_checked: false`) — it is never implied to be enough.

Unlike `material_plan.plan` (which compares a sliced job slot N to printer slot N,
because a slice fixes its tool numbers), an unsliced project has not chosen tools yet,
so its materials are matched SET-WISE: any loaded spool may serve any project slot.

Pure: nothing here contacts a printer, a provider or the disk.
"""
from __future__ import annotations

from . import material_plan as mp
from . import preflight as pf

SCHEMA_VERSION = "readiness/1"

NEEDS_PREPARATION = "needs_preparation"
NEEDS_ATTENTION = "needs_attention"
CANT_DETERMINE = "cant_determine"
ONE_CHANGE_AWAY = "one_change_away"
READY_NOW = "ready_now"

#: Decision order, and the order results are listed in.
BUCKETS = (NEEDS_PREPARATION, NEEDS_ATTENTION, CANT_DETERMINE, ONE_CHANGE_AWAY, READY_NOW)
_RANK = {b: i for i, b in enumerate(BUCKETS)}

CONFIRMED, LIKELY, INFORMATIONAL, UNKNOWN = "confirmed", "likely", "informational", "unknown"

#: The one sentence a colour-only mismatch is allowed to say.
COLOUR_NOTE = "Prints now, but the loaded colour differs from the project."
AMOUNT_NOT_CHECKED = "Amount not checked"
AMOUNT_UNTRUSTED = "Amount not checked — remaining weight is not a trusted figure"

#: Preflight checks this module deliberately does not turn into attention: how many
#: materials are loaded is answered better, per slot, by the set-wise match below, and
#: a nozzle note that disagrees with the printer is advice about the note, not the print.
_NOT_ATTENTION = {"materials.loaded", "nozzle.confirmation_conflict"}

#: Firmware features are a note about the printer, not a reason a project cannot print
#: now: shown in `unknowns`, never an attention bucket.
_NOTE_ONLY = {"capability.exclude_object"}


def sort_key(result: dict) -> int:
    return _RANK[result["bucket"]]


# --- what the project asks for ------------------------------------------------

def required_slots(traits: dict | None) -> list[dict]:
    """The project's filament slots, with the grams its author's slicer predicted.

    Grams come only from a slice the author already ran (`plate_predictions`); a project
    never sliced has none, and that is reported as unknown rather than estimated. A
    Bambu-family `slice_info` numbers filaments from 1, so filament id N is slot N-1.
    Where several plates predict a slot, the heaviest is used, because one plate is
    printed at a time and the heaviest is the one that must fit. When predictions exist
    at all, a slot no plate prints with is `used: False` and is not asked for.
    """
    slots = pf._trait(traits or {}, "filament_slots") or []
    grams: dict[int, float] = {}
    seen: set[int] = set()
    for plate in (traits or {}).get("plate_predictions") or []:
        for fil in plate.get("filaments") or []:
            try:
                tool = int(str(fil.get("id")).strip()) - 1
            except (TypeError, ValueError):
                continue
            seen.add(tool)
            used_g = fil.get("used_g")
            if isinstance(used_g, (int, float)) and used_g > 0:
                grams[tool] = max(grams.get(tool, 0.0), float(used_g))
    out = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        tool = slot.get("tool")
        out.append({
            "tool": tool,
            "type": slot.get("type") or None,
            "color": slot.get("color") or None,
            "name": slot.get("name"),
            "grams": grams.get(tool),
            "used": (tool in seen) if seen else True,
        })
    return out


# --- set-wise matching ----------------------------------------------------------

def _slot_entry(slot: dict) -> dict:
    return {
        "tool": slot["tool"],
        "required_material": slot.get("type"),
        "required_colour": slot.get("color"),
        "required_grams": slot.get("grams"),
        "printer_slot": None,
        "loaded_material": None,
        "loaded_colour": None,
        "state": "unused" if not slot.get("used", True) else "unknown",
        "amount": "not_checked",
        "colour_differs": False,
        "confirmed_by": None,
        "detail": None,
        "sufficiency": None,
    }


def match_slots_setwise(slots: list[dict], loaded: list | None) -> list[dict]:
    """Give each project slot a loaded spool that suits it, in ANY printer slot.

    A small deterministic greedy assignment; the order is the contract:

      * project slots are taken tightest constraint first — fewest family-compatible
        spools, ties by project slot number;
      * a spool must be the same material FAMILY ("PLA Matte" suits "PLA");
      * among those, a colour a person would not notice as different
        (`mp.NOTICEABLE`) beats one they would — an unknown colour counts as different;
      * then enough weight beats not enough (trusted-short last, unknown weight neutral);
      * then the nearest colour, then the lower printer slot.

    Each spool serves one project slot. A slot with no suitable spool is `wrong_material`
    when some other material is loaded unclaimed, `empty` when nothing is left, and
    `unknown` when Studio cannot tell (the project or a loaded spool states no material).
    Entries are returned in project slot order.
    """
    entries = [_slot_entry(s) for s in slots]
    wanted = [(e, s) for e, s in zip(entries, slots) if s.get("used", True)]
    spools = [(i, f) for i, f in enumerate(loaded or []) if isinstance(f, dict)]

    def suits(slot, spool):
        fam = mp.family(slot.get("type"))
        return fam is not None and fam == mp.family(spool.get("material"))

    wanted.sort(key=lambda es: (sum(1 for _, sp in spools if suits(es[1], sp)), es[1]["tool"]))
    claimed: set[int] = set()
    for entry, slot in wanted:
        if mp.family(slot.get("type")) is None:
            entry["detail"] = "The project does not state a material for this slot."
            continue
        free = [(i, sp) for i, sp in spools if i not in claimed]
        fits = [(i, sp) for i, sp in free if suits(slot, sp)]
        if not fits:
            if any(mp.family(sp.get("material")) is None for _, sp in free):
                entry["detail"] = "A loaded spool states no material, so Studio cannot tell."
            elif free:
                entry["state"] = "wrong_material"
                entry["detail"] = (f"Needs {mp.family(slot['type'])}; only other materials "
                                   "are loaded.")
            else:
                entry["state"] = "empty"
                entry["detail"] = (f"Needs {mp.family(slot['type'])}; no loaded spool is "
                                   "left for it.")
            continue

        def rank(item):
            idx, sp = item
            dist = mp.colour_distance(slot.get("color"), sp.get("color"))
            suff = _sufficiency_of(slot, sp)
            amount = (2 if suff and suff["verdict"] == "insufficient" and suff["trusted"]
                      else 1 if suff and suff["verdict"] == "probably_short" else 0)
            return (dist is None or dist > mp.NOTICEABLE, amount,
                    dist if dist is not None else 0.0, idx)

        idx, spool = min(fits, key=rank)
        claimed.add(idx)
        _fill_match(entry, slot, idx, spool)
    return entries


def _sufficiency_of(slot: dict, spool: dict) -> dict | None:
    if slot.get("grams") is None or spool.get("remaining_g") is None:
        return None
    return mp._sufficiency(slot["grams"], spool["remaining_g"],
                           spool.get("remaining_quality", "unknown"),
                           spool.get("remaining_as_of"))


def _fill_match(entry: dict, slot: dict, idx: int, spool: dict) -> None:
    dist = mp.colour_distance(slot.get("color"), spool.get("color"))
    entry.update(printer_slot=idx, loaded_material=spool.get("material"),
                 loaded_colour=spool.get("color"), confirmed_by=spool.get("confirmed_by"),
                 colour_differs=dist is not None and dist > mp.NOTICEABLE,
                 colour_compared=dist is not None)
    if slot.get("grams") is None:
        entry["amount"] = "not_checked"
    elif spool.get("remaining_g") is None:
        entry["amount"] = "unknown_remaining"
    else:
        suff = _sufficiency_of(slot, spool)
        # Only a trusted figure that covers the job counts as the amount being
        # checked; a figure nothing keeps up to date is shown, not relied on.
        entry["amount"] = ("checked" if suff["trusted"] and suff["verdict"] in
                           ("enough", "probably_enough", "insufficient") else "not_verified")
        entry["sufficiency"] = {"verdict": suff["verdict"], "trusted": suff["trusted"],
                                "detail": suff["detail"]}
    suff = entry["sufficiency"]
    if suff and suff["verdict"] == "insufficient" and suff["trusted"]:
        entry["state"] = "not_enough"
        entry["detail"] = suff["detail"]
    elif entry["colour_differs"]:
        entry["state"] = "different_colour"
        entry["detail"] = (f"Right material, different colour: the project asks for "
                           f"{slot.get('color')} and {spool.get('color')} is loaded.")
    elif suff and suff["verdict"] in ("insufficient", "probably_short"):
        entry["state"] = "maybe_not_enough"
        entry["detail"] = suff["detail"]
    else:
        entry["state"] = "ready"


# --- classification -------------------------------------------------------------

def _label(entry: dict) -> str:
    return f"filament {entry['tool'] + 1}"


def _result(project: dict, bucket: str, reason: str, action: str | None, confidence: str, *,
            evidence=(), unknowns=(), colour_notes=(), amount_checked: bool = False,
            slots=(), file_state: str = "ok") -> dict:
    return {
        "path": project.get("path"),
        "name": project.get("name"),
        "bucket": bucket,
        "top_reason": reason,
        "top_action": action,
        "confidence": confidence,
        "evidence": list(evidence),
        "unknowns": list(unknowns),
        "colour_notes": list(colour_notes),
        "amount_checked": bool(amount_checked),
        "slots": list(slots),
        "file_state": file_state,
    }


def classify_project(project: dict, traits: dict | None, printer: dict | None,
                     preflight_result: dict | None, file_state: str = "ok") -> dict:
    """One library project -> one bucket and the evidence behind it. Pure.

    ``project`` is ``{"path", "name"}``. ``traits`` is ``project_traits.extract``.
    ``printer`` is the facts bundle (with providers folded in). ``preflight_result`` is
    ``preflight.evaluate`` against that printer, or None when none was run.
    """
    printer = printer or {}
    cant = lambda why, action, **kw: _result(                      # noqa: E731
        project, CANT_DETERMINE, why, action, UNKNOWN, file_state=file_state, **kw)

    if file_state != "ok":
        if file_state == "missing":
            why, action = ("The project file could not be found.",
                           "Check the file is still where the library says it is.")
        else:
            # Studio's own, path-free reason (for example its size-safety limit), else a plain one.
            notes = (traits or {}).get("notes") or []
            why = str(notes[0]) if notes else "Studio could not read this file."
            action = "Open it in your slicer to check it, or re-export it."
        return cant(why, action, unknowns=[f"The project file is {file_state}."])

    if pf._trait(traits or {}, "foreign_printer") is True:
        target = pf._trait(traits, "target_printer")
        return _result(project, NEEDS_PREPARATION,
                       "This project was made for another printer.",
                       "Prepare a U1 copy first",
                       (traits.get("foreign_printer") or {}).get("confidence") or CONFIRMED,
                       evidence=[f"Made for {target}." if target else
                                 "Its printer profile is not a Snapmaker U1."])

    if not printer.get("reachable"):
        return cant("Studio could not reach your printer.",
                    "Connect the printer in Printer Hub, then scan again.",
                    unknowns=["Nothing can be compared with a printer that did not answer."])
    if preflight_result is None:
        return cant("Studio did not run its printer checks for this project.",
                    "Scan again.", unknowns=["Printer checks were not run."])

    checks = preflight_result.get("checks") or []
    attention = [c for c in checks if c["result"] in (pf.BLOCKED, pf.ATTENTION)
                 and c["id"] not in _NOT_ATTENTION and c["id"] not in _NOTE_ONLY]
    unknown_checks = [c for c in checks if c["id"] not in _NOT_ATTENTION
                      and c["id"] != "printer.reachable"
                      and (c["result"] == pf.UNKNOWN
                           or (c["id"] in _NOTE_ONLY and c["result"] in (pf.BLOCKED, pf.ATTENTION)))]

    slots = match_slots_setwise(required_slots(traits), printer.get("loaded_filaments"))
    needed = [s for s in slots if s["state"] != "unused"]
    short = [s for s in needed if s["state"] == "not_enough"]

    if attention or short:
        first = attention[0] if attention else None
        reason = (f"{first['title']}." if first else
                  f"Not enough filament for {_label(short[0])}.")
        action = (first.get("action") if first else
                  "Load a fuller spool, or be ready to swap part-way through.")
        evidence = [c["evidence"] for c in attention if c.get("evidence")]
        evidence += [s["detail"] for s in short]
        return _result(project, NEEDS_ATTENTION, reason,
                       action or "Resolve this, then scan again.",
                       first["confidence"] if first else LIKELY, evidence=evidence,
                       unknowns=[c["title"] for c in unknown_checks],
                       slots=slots, file_state=file_state)

    why_unknown = None
    if printer.get("loaded_filaments") is None:
        why_unknown = "Nothing Studio can read says what is loaded in the printer."
    elif not needed:
        why_unknown = "The project does not state which materials it uses."
    elif any(s["state"] == "unknown" for s in needed):
        why_unknown = next(s["detail"] for s in needed if s["state"] == "unknown")
    elif any(s["amount"] == "unknown_remaining" for s in needed):
        why_unknown = ("The project's filament weight is known, but nothing says how much "
                       "is left on the matching spool.")
    if why_unknown:
        return cant(why_unknown, "Check the spools yourself, or connect a spool provider.",
                    unknowns=[why_unknown] + [c["title"] for c in unknown_checks],
                    slots=slots)

    change = [s for s in needed if s["state"] in ("wrong_material", "empty")]
    if change:
        first = change[0]
        want = mp.family(first["required_material"])
        return _result(project, ONE_CHANGE_AWAY,
                       f"{_label(first).capitalize()} needs {want}, and none is loaded for it.",
                       f"Load {want} for {_label(first)}.",
                       CONFIRMED if first["state"] == "wrong_material" else LIKELY,
                       evidence=[s["detail"] for s in change],
                       unknowns=[c["title"] for c in unknown_checks],
                       slots=slots, file_state=file_state)

    # A check Studio could not answer (bed fit, nozzle size, toolhead count) means it cannot
    # honestly say "ready": unknown stays unknown.
    blocking = [c for c in unknown_checks if c["id"] not in _NOTE_ONLY and c["result"] == pf.UNKNOWN]
    if blocking:
        why = f"Studio could not check: {blocking[0]['title']}."
        return cant(why, "Connect the printer or open the project in Snapmaker Orca to check.",
                    unknowns=[c["title"] for c in unknown_checks], slots=slots)

    # Ready. Say exactly how much of that was checked.
    amount_checked = all(s["amount"] == "checked" for s in needed)
    colour_notes = [s["detail"] for s in needed if s["state"] == "different_colour"]
    evidence = [f"{len(needed)} material(s) each matched to a loaded spool."]
    unknowns = [c["title"] for c in unknown_checks]
    if any(s["amount"] == "not_verified" for s in needed):
        evidence.append(AMOUNT_UNTRUSTED)
    if any(s["amount"] == "not_checked" for s in needed):
        evidence.append(AMOUNT_NOT_CHECKED)
    unknowns += [s["detail"] for s in needed if s["state"] == "maybe_not_enough"]
    # A colour note must not hide a possible shortage on the same spool.
    short_too = [s["sufficiency"]["detail"] for s in needed
                 if s["state"] == "different_colour" and s.get("sufficiency")
                 and s["sufficiency"]["verdict"] in ("insufficient", "probably_short")]
    unknowns += short_too
    unknowns += [f"Colour not compared for {_label(s)}." for s in needed
                 if not s.get("colour_compared", False)]
    assumed = any(s["confirmed_by"] != "printer" for s in needed)
    if assumed:
        unknowns.append("Some loaded materials come from your own notes, not the printer.")
    sure = amount_checked and not colour_notes and not unknowns
    if short_too:
        reason = "Every material is loaded, but a spool may not hold enough and its colour differs."
    else:
        reason = COLOUR_NOTE if colour_notes else "Every material it asks for is loaded."
    return _result(project, READY_NOW, reason,
                   "Prepare it in Snapmaker Orca to slice." if not pf._trait(traits, "is_sliced")
                   else "Open it in Snapmaker Orca.",
                   CONFIRMED if sure else LIKELY, evidence=evidence, unknowns=unknowns,
                   colour_notes=colour_notes, amount_checked=amount_checked, slots=slots,
                   file_state=file_state)


def summarise(results: list[dict]) -> dict:
    """Counts per bucket, every bucket always present."""
    counts = {b: 0 for b in BUCKETS}
    for r in results:
        counts[r["bucket"]] += 1
    return counts
