"""What Studio checked, so it can tell whether it is still true when you send.

The send check answers a question about a moment: this job, this printer, these
spools, now. Then a person reads it, thinks about it, walks to the machine, comes
back — and presses send. Everything the check looked at can have changed in
between, and nothing about the answer on screen would look any different.

That is the gap this closes. The check records a fingerprint of exactly what it
looked at; the send re-reads the same things and compares. If nothing moved, the
upload goes ahead on evidence rather than on the assumption that the world held
still. If something moved, the send stops and says which part changed, in the
words the check itself used.

The fingerprint deliberately covers only what would change the answer:

* the job — its size and modification time, because re-slicing to the same name is
  ordinary and produces a completely different file;
* the printer — whether it is reachable, what it is doing, how many tools it has,
  and what its firmware exposes;
* the spools — the material and colour in each slot, and any tracked weight;
* whether the job still ties back to the project the user opened.

Nothing here talks to a printer or a file. It is given facts and returns a
comparison, so the same code answers "is this still true?" wherever the facts came
from.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA_VERSION = "sendstate/1"


def _hash(value) -> str:
    blob = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def fingerprint(gcode_facts: dict | None, printer: dict | None,
                provenance: dict | None = None, *,
                file_stat: dict | None = None) -> dict:
    """A comparable summary of everything a send decision rests on."""
    facts = gcode_facts or {}
    machine = printer or {}

    job = {
        # A hash, not the name: a model's filename is the user's business, and this
        # fingerprint travels to the app and back with every send.
        "file": _hash(facts.get("file")),
        "size": (file_stat or {}).get("size_bytes", facts.get("size_bytes")),
        "modified": (file_stat or {}).get("modified"),
        # The ends of the file, hashed. A re-slice that happens to land on the
        # same byte count in the same timestamp tick is otherwise invisible.
        "content": (file_stat or {}).get("content"),
        "layers": facts.get("layer_count"),
        "tools": facts.get("tools_used"),
        "objects": (facts.get("objects") or {}).get("name_digest"),
    }

    loaded = []
    for slot in (machine.get("loaded_filaments") or []):
        if not slot:
            loaded.append(None)
            continue
        loaded.append({
            "material": slot.get("material"),
            "colour": slot.get("color"),
            "spool": slot.get("spool_id"),
            "remaining": slot.get("remaining_g"),
        })

    # B8 (Opus LOW): a stored note's OWN conflict list carries the printer's
    # live value alongside it (so the person can see both sides on screen) —
    # but that means the raw list would change hash the moment the LIVE
    # reading moves, even when the note itself never changed. Reduced to just
    # which toolhead, from which source, confirmed what, so a live-only
    # change is invisible here and shows up under "printer" instead, never
    # double-reported (or mis-reported) as "your nozzle notes changed".
    note_conflicts_signature = sorted(
        (c.get("toolhead"), c.get("confirmed"), c.get("source"))
        for c in (machine.get("nozzle_conflicts") or []))

    parts = {
        "job": job,
        "printer": {
            "reachable": bool(machine.get("reachable")),
            "state": machine.get("print_state"),
            "tools": machine.get("toolhead_count"),
            # The capability list changes when firmware restarts or is updated, and
            # object exclusion appearing or disappearing changes what Studio may
            # promise about cancelling one object mid-print.
            "capabilities": _hash(sorted(machine.get("klipper_objects") or [])),
            # B2/B8: the printer's own live nozzle reading lives HERE — a
            # change in what the firmware itself reports is a printer change,
            # never "your nozzle notes changed".
            "nozzle_live": machine.get("_live_nozzle_diameters"),
        },
        "materials": loaded,
        "provenance": (provenance or {}).get("verdict"),
        # A1.12/R2-B3 (Sol 3): a nozzle confirmation the person saved (or
        # removed) after the check ran is a change worth catching — even when
        # a live reading already matches it and always wins. Keyed on the
        # STORED snapshot itself (every toolhead, including an explicit "not
        # sure" null) and the stored revision, never on the resolved
        # `nozzle_diameters` (that value IS the live reading whenever one
        # exists, and belongs to the printer part above) and never on
        # `observed_at` (ticks on every read, live or not).
        "nozzle_notes": {
            "stored": sorted(
                (toolhead, entry.get("diameter"))
                for toolhead, entry in (machine.get("_stored_nozzle_confirmations") or {}).items()),
            "revision": machine.get("nozzle_revision"),
            "conflicts": note_conflicts_signature,
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "parts": parts,
        "hashes": {name: _hash(value) for name, value in parts.items()},
        "token": _hash(parts),
    }


#: What each part of the fingerprint is called when it has to be explained.
WORDS = {
    "job": "the job file",
    "printer": "the printer",
    "materials": "what is loaded in the slots",
    "provenance": "whether this job came from your project",
    "nozzle_notes": "your nozzle notes",
}

#: What a change in each part means for someone about to press send.
CONSEQUENCE = {
    "job": "The file has been written again since Studio checked it, so this is not the "
           "job that was checked.",
    "printer": "The printer is not in the state it was checked against.",
    "materials": "The spools are not the ones the job was checked against.",
    "provenance": "Studio no longer reads this job the same way against your project.",
    "nozzle_notes": "The nozzle note you saved has changed since Studio checked this job.",
}


def changes(before: dict | None, after: dict | None) -> list[dict]:
    """Which parts of a send decision are no longer what they were."""
    if not before or not after:
        return []
    old, new = before.get("hashes") or {}, after.get("hashes") or {}
    found = []
    for name in ("job", "printer", "materials", "provenance", "nozzle_notes"):
        if name in old and name in new and old[name] != new[name]:
            found.append({
                "part": name,
                "title": WORDS[name] + " changed",
                "detail": CONSEQUENCE[name],
                "was": (before.get("parts") or {}).get(name),
                "now": (after.get("parts") or {}).get(name),
            })
    return found


def describe(found: list[dict]) -> str:
    """One sentence for a confirmation dialog."""
    if not found:
        return "Nothing has changed since Studio checked this job."
    what = ", ".join(WORDS[item["part"]] for item in found)
    return (f"{what.capitalize()} changed after Studio checked this job. "
            "The checks you read no longer describe what would happen.")
