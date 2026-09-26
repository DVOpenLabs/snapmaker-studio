"""What should I load for this job, and what can stay where it is?

Once a job is sliced, its tool assignments are fixed: slot 3 prints what the
slicer decided slot 3 prints, and no amount of spool shuffling changes that
without re-slicing. So the useful question is not "how should the colours be
arranged" — it is the concrete one a person standing at the printer asks:

* which slots does this job actually use?
* which of those already hold the right thing?
* which do I have to change, and to what?
* which spools can I leave alone, or take out?

This is an intelligence layer over spool state, not a spool inventory. Studio
does not track filament, does not weigh it, and does not remember it between
sessions — U1Hub, Spoolman and OpenSpool exist and do that well. Studio reads
whatever spool state is available and answers the question above.

Material comparison is by family, because naming is not standardised: the printer
says "PLA Matte", the slicer says "PLA", and a strict comparison would report a
mismatch on every multi-material print ever made. Colour is advisory and always
labelled as such — a slicer's colour swatch is what the designer picked, not a
measurement of the filament on the shelf.
"""
from __future__ import annotations

SCHEMA_VERSION = "materialplan/1"

#: Above this distance two colours are different enough that a person would
#: notice on a printed part. Below it, worth mentioning but not worth alarming
#: about. Tuned to be quiet: the point is to catch "job wants black, slot has
#: white", not to police shades.
NOTICEABLE = 120.0


def family(value: str | None) -> str | None:
    """"PLA Matte" -> "PLA". None stays None."""
    if not value:
        return None
    first = value.strip().split()
    return first[0].upper() if first else None


def _rgb(value: str | None):
    if not value or not isinstance(value, str):
        return None
    text = value.strip().lstrip("#")
    if len(text) < 6:
        return None
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def colour_distance(a: str | None, b: str | None) -> float | None:
    """Straight-line distance in RGB.

    Deliberately simple and deliberately advisory. A perceptual metric would
    imply a precision that neither the slicer's swatch nor the printer's reported
    colour actually has.
    """
    first, second = _rgb(a), _rgb(b)
    if not first or not second:
        return None
    return sum((x - y) ** 2 for x, y in zip(first, second)) ** 0.5


def _slot_word(index: int) -> str:
    return f"slot {index + 1}"


def plan(job_slots: list[dict], loaded: list | None,
         tools_used: list[int] | None = None,
         slot_facts: list[dict] | None = None) -> dict:
    """Compare what the job needs, slot by slot, with what is loaded.

    ``job_slots`` is ``gcode.read_facts()["slots"]``. ``loaded`` is
    ``moonraker.loaded_filaments()`` — index-aligned, with ``None`` for an empty
    slot. Either may be missing; what cannot be compared is reported as unknown.

    ``slot_facts`` is the normalised slot list the providers produced, and it is
    optional because most callers predate it. It carries the one thing ``loaded``
    cannot: *who* established that a slot holds nothing. An index-aligned ``None``
    is silence, and silence has three different causes that must not read alike —
    a printer that looked and saw an empty slot, a mapping pointing at a spool
    that no longer exists, and nobody having said anything at all.
    """
    out: dict = {
        "schema_version": SCHEMA_VERSION,
        "available": bool(job_slots),
        "printer_known": loaded is not None,
        "slots": [],
        "changes_needed": 0,
        "unknowns": 0,
    }
    if not job_slots:
        out["summary"] = "Studio could not read which materials this job uses."
        return out

    used = set(tools_used or [s["tool"] for s in job_slots if s.get("used")])
    facts = {f["slot"]: f for f in (slot_facts or []) if isinstance(f, dict)}

    for slot in job_slots:
        index = slot["tool"]
        needed = index in used
        have = loaded[index] if (loaded is not None and index < len(loaded)) else None

        entry = {
            "tool": index,
            "label": _slot_word(index),
            "needed": needed,
            "wants_material": slot.get("type"),
            "wants_colour": slot.get("color"),
            "wants_name": slot.get("name"),
            "grams": slot.get("grams"),
            "has_material": (have or {}).get("material"),
            "has_colour": (have or {}).get("color"),
            "action": None,
            "state": None,
            "detail": None,
            "colour_distance": None,
            # Who established that something is in this slot: the printer, which
            # is looking at it, or a provider mapping, which is the user's own
            # note. Set here rather than further down, because it is true of the
            # slot whatever this particular job does with it.
            "confirmed_by": (have or {}).get("confirmed_by"),
            "printer_confirmed": (have or {}).get("confirmed_by") == "printer",
        }

        if not needed:
            entry["state"] = "unused"
            entry["detail"] = "This job never prints from this slot."
            entry["action"] = "Leave it as it is — or take the spool out if you need it elsewhere."
            out["slots"].append(entry)
            continue

        if loaded is None:
            entry["state"] = "unknown"
            entry["detail"] = "Studio could not read what is loaded."
            entry["action"] = "Connect your printer in Printer Hub, or check the spool yourself."
            out["unknowns"] += 1
            out["slots"].append(entry)
            continue

        if have is None:
            # Nothing is loaded here — but "the printer reports it empty" is an
            # observation, and it was being said whether or not any printer had
            # looked. A slot whose provider mapping names a spool that has since
            # been deleted arrived here too, and was described as a printer's
            # report of an empty slot on the strength of nothing at all.
            fact = facts.get(index)
            entry["state"] = "empty"
            entry["confirmed_by"] = (fact or {}).get("confirmed_by")
            entry["printer_confirmed"] = (fact or {}).get("confirmed_by") == "printer"
            entry["notes"] = list((fact or {}).get("notes") or ())
            if entry["printer_confirmed"]:
                entry["detail"] = ("This job prints from this slot and the printer "
                                   "reports it empty.")
            elif fact is not None:
                # A mapping that points nowhere. Saying so sends the person to
                # the provider to fix the mapping; "empty" sends them to the
                # printer to look at a slot that may well have a spool in it.
                said = " ".join(entry["notes"]) or "your mapping names a spool it cannot find"
                entry["detail"] = ("This job prints from this slot. Nothing has confirmed "
                                   f"what is in it — {said}.")
            else:
                entry["detail"] = ("This job prints from this slot and nothing Studio can "
                                   "read says what is in it.")
            entry["action"] = (f"Load {slot.get('type') or 'filament'} here before you start"
                               + (f" — the job was sliced for {slot['color']}." if slot.get("color") else "."))
            out["changes_needed"] += 1
            out["slots"].append(entry)
            continue

        # One of these is an observation and the other is a note somebody wrote,
        # and the sentences below must not read the same.
        assumed = have.get("confirmed_by") == "provider"

        want_family = family(slot.get("type"))
        have_family = family(have.get("material"))
        distance = colour_distance(slot.get("color"), have.get("color"))
        entry["colour_distance"] = None if distance is None else round(distance, 1)

        # --- do I have enough of it? -----------------------------------
        grams_needed = slot.get("grams")
        remaining = have.get("remaining_g")
        entry["needs_grams"] = grams_needed
        entry["remaining_g"] = remaining
        entry["remaining_quality"] = have.get("remaining_quality", "unknown")
        entry["sufficiency"] = _sufficiency(grams_needed, remaining,
                                            have.get("remaining_quality", "unknown"),
                                            have.get("remaining_as_of"))
        # A provider that disagrees with the printer about this slot is worth
        # seeing next to the slot it disagrees about.
        entry["conflicts"] = list(have.get("conflicts") or ())
        entry["notes"] = list(have.get("notes") or ())

        if want_family and have_family and want_family != have_family:
            entry["state"] = "wrong_material"
            entry["detail"] = (
                f"The job was sliced for {want_family}; your mapping puts "
                f"{have.get('material')} in this slot, and this printer does not report "
                "its own filament to check that against."
                if assumed else
                f"The job was sliced for {want_family}; the printer reports "
                f"{have.get('material')} loaded here.")
            entry["action"] = f"Swap this slot to {want_family}, or re-slice for {have_family}."
            out["changes_needed"] += 1
        elif not want_family or not have_family:
            entry["state"] = "unknown"
            entry["detail"] = "Either the job or the printer did not state a material for this slot."
            entry["action"] = "Check this spool yourself."
            out["unknowns"] += 1
        elif distance is not None and distance > NOTICEABLE:
            entry["state"] = "different_colour"
            entry["detail"] = (f"Right material, different colour: the job was sliced for "
                               f"{slot['color']} and {have.get('color')} is loaded.")
            entry["action"] = ("Fine if you meant to change the colour. Swap the spool if you "
                               "wanted the original.")
        elif entry["sufficiency"]["verdict"] == "insufficient" \
                and entry["sufficiency"].get("trusted"):
            entry["state"] = "not_enough"
            entry["detail"] = entry["sufficiency"]["detail"]
            entry["action"] = "Load a fuller spool, or be ready to swap part-way through."
            out["changes_needed"] += 1
        elif entry["sufficiency"]["verdict"] in ("insufficient", "probably_short"):
            # Short according to a figure nothing is really keeping — say so, but
            # do not tell someone to change a spool that may be perfectly full.
            entry["state"] = "maybe_not_enough"
            entry["detail"] = entry["sufficiency"]["detail"]
            entry["action"] = "Check what is on this spool before you start."
        else:
            entry["state"] = "ready"
            if assumed:
                base = (f"{have.get('material')} is mapped to this slot and matches what "
                        "the job expects. This printer does not report its own filament, "
                        "so that is your mapping rather than something the machine has "
                        "confirmed.")
            else:
                base = (f"{have.get('material')} is loaded and matches what the job expects."
                        if have.get("material") else "Loaded and matching.")
            if entry["sufficiency"]["verdict"] in ("enough", "probably_enough"):
                base += " " + entry["sufficiency"]["detail"]
            entry["detail"] = base
            entry["action"] = None

        out["slots"].append(entry)

    out["needed"] = sorted(used)
    out["short"] = [s["tool"] for s in out["slots"] if s.get("state") == "not_enough"]
    out["remaining_known"] = any(s.get("remaining_g") is not None for s in out["slots"])
    out["ready"] = [s["tool"] for s in out["slots"] if s["state"] == "ready"]
    out["to_change"] = [s["tool"] for s in out["slots"]
                        if s["state"] in ("empty", "wrong_material", "not_enough")]
    out["colour_notes"] = [s["tool"] for s in out["slots"] if s["state"] == "different_colour"]
    out["summary"] = _summary(out)
    return out


def _summary(out: dict) -> str:
    if not out["printer_known"]:
        needed = len(out.get("needed") or [])
        return (f"This job prints from {needed} slot(s). Connect your printer to see whether the "
                "right filament is in them.")

    change = out["to_change"]
    colour = out["colour_notes"]
    ready = out["ready"]

    if not change and not colour:
        if out["unknowns"]:
            return (f"{len(ready)} slot(s) are ready; {out['unknowns']} could not be checked.")
        return f"Nothing to change — all {len(ready)} slot(s) this job uses are already loaded correctly."

    parts = []
    if change:
        which = ", ".join(_slot_word(t) for t in change)
        parts.append(f"change {which}")
    if colour:
        which = ", ".join(_slot_word(t) for t in colour)
        parts.append(f"a different colour is loaded in {which}")
    text = "; ".join(parts)
    return text[:1].upper() + text[1:] + f". {len(ready)} slot(s) are already right."


def from_facts(gcode_facts: dict, printer: dict | None) -> dict:
    """Convenience: build the plan straight from a G-code read and printer facts."""
    if not gcode_facts.get("available"):
        return {
            "schema_version": SCHEMA_VERSION,
            "available": False,
            "summary": gcode_facts.get("error", "Studio could not read that G-code file."),
        }
    return plan(gcode_facts.get("slots") or [],
                (printer or {}).get("loaded_filaments"),
                gcode_facts.get("tools_used"),
                (printer or {}).get("slot_facts"))


#: How much more than the job needs should be on the spool before Studio calls it
#: comfortable. Filament weight is never exact — a spool's tare varies, and a
#: tracked figure drifts between manual corrections — so "just enough" is a
#: warning, not a pass.
MARGIN = 1.10


#: A tracked weight is somebody's bookkeeping, not a measurement: it drifts every
#: time a print is run outside the tool that keeps it, and every time a spool is
#: swapped without being recorded. Inside this margin of the job's needs, "not
#: enough" is a caution rather than a fact worth blocking a print over.
DOUBT = 0.05


def _sufficiency(needed, remaining, quality: str = "unknown", as_of=None) -> dict:
    """Is there enough filament on this spool for this job?

    Only a provider that actually tracks remaining weight can answer this. A
    printer knows which spool is loaded and nothing about what is left on it, so
    on a stock setup the honest answer is unknown — and unknown is what this
    returns, rather than an optimistic silence.

    How the figure is known decides how strongly Studio may put it. "87 g needed,
    43 g left, it will run out" is worth stopping for; the same sentence built on
    a number nothing has updated since the last three prints is not, and this
    reports the difference rather than flattening it.
    """
    if needed is None:
        return {"verdict": "unknown", "detail": "The job does not state how much this slot uses.",
                "source": "the sliced file", "quality": "unknown", "trusted": False}
    if remaining is None:
        return {"verdict": "unknown",
                "detail": (f"This slot uses {needed:g} g. Nothing Studio can read tracks how much "
                           "is left on the spool, so check it yourself."),
                "source": "no provider reports remaining weight",
                "quality": "unknown", "trusted": False}

    from . import freshness as fr

    # A local note's fresh, person-confirmed figure ("user_confirmed") is
    # neither of these origin-labelled tiers on its own: it did not come from
    # a bookkeeping tool ("tracked"/"derived"), but it is not unstated either
    # — someone looked at the spool and said so. It counts as known here, and
    # as trustworthy exactly as long as it stays fresh, same as a tracked one.
    known = "tracked" if quality in ("tracked", "derived", "user_confirmed") else "unknown"
    age = fr.assess(as_of)

    # Only a figure that is *both* something a tool has been keeping and recent
    # enough to still be true may block a send. Two rules, and each was being
    # broken:
    #
    #  * a DERIVED weight is arithmetic from a declared initial weight, not a
    #    record of consumption, and it used to map to "tracked" and block a print;
    #  * a TRACKED weight nobody has updated in a fortnight used to block one too,
    #    which is being stopped over bookkeeping rather than over filament.
    #
    # Both now warn. A warning that turns out to be right costs someone a glance
    # at the spool; a blocker that turns out to be wrong costs them the print they
    # were told not to start.
    trusted = quality in ("tracked", "user_confirmed") and age["state"] in (fr.FRESH, fr.AGEING)
    where = ("tracked spool weight" if quality == "tracked" else
             "spool weight worked out from what the spool held and what has been used"
             if quality == "derived" else
             "a remaining weight you confirmed yourself" if quality == "user_confirmed" else
             "a remaining weight of unstated origin")
    since = ""
    if age["state"] not in (fr.UNKNOWN,):
        since = " " + age["detail"]
    elif as_of:
        since = f" Last updated {as_of}."

    if remaining >= needed * MARGIN:
        return {"verdict": "enough",
                "detail": f"{remaining:g} g recorded, {needed:g} g needed." + since,
                "source": where, "quality": known, "trusted": trusted,
                "freshness": age["state"], "age_s": age["age_s"]}
    if remaining >= needed:
        return {"verdict": "probably_enough",
                "detail": (f"{remaining:g} g recorded and {needed:g} g needed — enough on paper, "
                           "with little to spare. Recorded weights are not exact." + since),
                "source": where, "quality": known, "trusted": trusted,
                "freshness": age["state"], "age_s": age["age_s"]}

    shortfall = needed - remaining
    marginal = shortfall <= max(needed * DOUBT, 5.0)
    if marginal or not trusted:
        why = ("a figure that is bookkeeping rather than a measurement"
               if quality == "tracked" and age["state"] != fr.STALE else
               "a figure nothing has updated recently" if age["state"] == fr.STALE else
               "a figure worked out from what the spool held rather than one anything "
               "has been keeping" if quality == "derived" else
               "the figure you confirmed yourself, with little margin to spare"
               if quality == "user_confirmed" else
               "a figure of unstated origin")
        return {"verdict": "probably_short",
                "detail": (f"{remaining:g} g recorded and the job needs {needed:g} g — "
                           f"{shortfall:g} g short on {why}, so check the spool before "
                           "you start." + since),
                "source": where, "quality": known, "trusted": trusted,
                "freshness": age["state"], "age_s": age["age_s"]}
    return {"verdict": "insufficient",
            "detail": (f"{remaining:g} g tracked but the job needs {needed:g} g. "
                       "It will run out part-way through." + since),
            "source": where, "quality": known, "trusted": trusted,
            "freshness": age["state"], "age_s": age["age_s"]}
