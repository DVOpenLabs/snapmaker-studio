"""Setup report: what the host adapters established about a printer setup, and what they did not.

Pure. Takes already-parsed adapter results (no network, no storage) and returns one JSON-serialisable
document. Everything is reported as one of four states, with a plain reason:

    available    the data was read and is current enough to show
    unavailable  the host could not be read at all (unreachable, key needed, not a known host)
    stale        the data was read but is older than its lifetime
    unknown      the host answered but did not say (Studio does not guess)

Head counts come only from `topology.counts`. The verdict on a project's materials is the
topology's material-to-head assignability; it is advisory, never a promise about a print.
"""
from __future__ import annotations

from typing import Any, Iterable

from .adapters.base import AdapterResult
from .foundation import observations as obs_mod
from .foundation import topology as topo
from .foundation.decode import revision_envelope
from .foundation.materials import MaterialFact

SCHEMA_VERSION = "setup_report/1"

AVAILABLE, UNAVAILABLE, STALE, UNKNOWN = "available", "unavailable", "stale", "unknown"
STATES = (AVAILABLE, UNAVAILABLE, STALE, UNKNOWN)

LEGACY_NOTICE = ("Older Studio screens assume four heads, and legacy preparation is not validated "
                 "for this setup. Review any prepared copy in Orca before slicing.")

# capability key -> (label, observation fields that back it; None = the whole read)
_CAPABILITIES = (
    ("host_identity", "Host identity", ("service", "moonraker_version", "octoprint_version")),
    ("physical_heads", "Physical heads", None),
    ("nozzle_diameter", "Nozzle diameters", ("nozzle_mm",)),
    ("logical_slots", "Logical material slots", None),
    ("slot_mapping", "Slot-to-head mapping", None),
    ("slot_occupancy", "Physical-head occupancy", ("occupancy",)),
    ("material_data", "Material data", ("material", "colour", "brand")),
    ("spool_identity", "Spool identity", ("spool",)),
    ("feeder_lanes", "Feeder lanes", None),
)

_VERDICT_TEXT = {
    True: "Each requested material can be matched to a head on this setup. This is advisory.",
    False: "This setup cannot give every requested material a head. This is advisory.",
    None: "Whether every requested material can be matched is not known from what was read.",
}


def _entry_input(item: Any, index: int) -> dict:
    """Accept an `AdapterResult` or a dict {label, status, reason, result}."""
    if isinstance(item, AdapterResult):
        return {"label": f"setup {index + 1}", "status": "ok", "reason": None, "result": item}
    if isinstance(item, dict):
        return {"label": str(item.get("label") or f"setup {index + 1}"),
                "status": str(item.get("status") or "ok"), "reason": item.get("reason"),
                "result": item.get("result"), "kind": item.get("kind"), "variant": item.get("variant")}
    raise TypeError("setup entries must be adapter results or dicts")


def _requirements(items: Iterable | None) -> list:
    out = []
    for i, item in enumerate(items or []):
        if isinstance(item, topo.ProjectSlotRequirement):
            out.append(item)
        elif isinstance(item, dict):
            out.append(topo.ProjectSlotRequirement(int(item.get("index", i)), item.get("material"),
                                                   item.get("colour"), item.get("recipe_id")))
        else:
            raise TypeError("requirements must be ProjectSlotRequirement or dict")
    return out


def _freshness_row(obs: obs_mod.Observation, now: Any) -> dict:
    fr = obs_mod.freshness(obs, now)
    return {"observation_id": obs.observation_id, "subject": dict(obs.subject), "field": obs.field,
            "value": obs.value, "state": fr["state"], "age_s": fr["age_s"],
            "usable_for_loadout": fr["usable_for_loadout"], "reason": fr["reason"],
            "historical": bool(obs.historical), "observed_at": obs.observed_at,
            "received_at": obs.received_at}


def _backing_state(rows: list) -> tuple[str, bool, str | None]:
    """(state, historical, reason) from freshness rows. Stale only when nothing backing is current."""
    if not rows:
        return UNKNOWN, False, None
    current = [r for r in rows if r["state"] in (obs_mod.FRESH, obs_mod.AGEING)]
    historical = all(r["historical"] for r in rows)
    if current:
        return AVAILABLE, historical, "Restored from an earlier session." if historical else None
    if all(r["state"] in (obs_mod.STALE, obs_mod.UNUSABLE) for r in rows):
        return STALE, historical, "This was read earlier and is older than its lifetime."
    return UNKNOWN, historical, "Nothing records when this was last true."


def _capability(key: str, label: str, state: str, reason: str, historical: bool = False) -> dict:
    return {"key": key, "label": label, "state": state, "reason": reason, "historical": historical}


def _all_state(label_keys: Iterable, state: str, reason: str) -> list:
    return [_capability(k, lab, state, reason) for k, lab, _ in label_keys]


def _data_state(key: str, result: AdapterResult, counts: dict | None) -> tuple[str, str]:
    """(available|unknown, reason) from the parsed data alone, before freshness is considered."""
    unknowns = set(result.unknowns)
    topology = result.topology
    facts = [f for f in result.material_facts if isinstance(f, MaterialFact)]
    if key == "host_identity":
        has = any(o.field in ("service", "moonraker_version", "octoprint_version") for o in result.observations)
        return (AVAILABLE, "The host named itself.") if has else (UNKNOWN, "The host did not identify itself.")
    if key == "physical_heads":
        n = counts["physical_heads"] if counts else None
        if n is not None:
            return AVAILABLE, f"The host reports {n} physical head{'s' if n != 1 else ''}."
        return UNKNOWN, "The host did not report how many physical heads there are."
    if key == "nozzle_diameter":
        if any(o.field == "nozzle_mm" for o in result.observations):
            return AVAILABLE, "Nozzle diameters were reported."
        return UNKNOWN, "Nozzle diameters were not reported."
    if key == "logical_slots":
        n = counts["logical_slots"] if counts else 0
        if n and "logical_slots_beyond_filament_arrays" not in unknowns and "bindings" not in unknowns:
            return AVAILABLE, f"The host reports {n} logical material slot{'s' if n != 1 else ''}."
        if n:
            # The entries counted here come from per-physical-extruder arrays; the host's own list of
            # logical (T) mappings is longer or was not read, so the logical count is not known.
            return UNKNOWN, (f"The host reported {n} filament entr{'ies' if n != 1 else 'y'}, one per physical "
                             "extruder. Its logical tool mappings are not fully shown, so the number of "
                             "logical slots is not known.")
        return UNKNOWN, "The host did not report any material slots."
    if key == "slot_mapping":
        if topology is not None and (topology.bindings or any(s.binding for s in topology.slots)):
            if "bindings" in unknowns:
                return AVAILABLE, "Some slot-to-head mappings were reported; the rest are unknown."
            if "logical_slots_beyond_filament_arrays" in unknowns:
                return AVAILABLE, ("Mappings for the entries shown were reported; the host lists more "
                                   "logical tool mappings that are not shown.")
            return AVAILABLE, "The host reported which head each slot uses."
        return UNKNOWN, "The host did not say which head each slot uses. Studio does not assume slot n is head n."
    if key == "slot_occupancy":
        if any(o.field == "occupancy" for o in result.observations):
            return AVAILABLE, "Whether each physical head holds filament was reported. This is not a per-slot answer."
        return UNKNOWN, "Whether each physical head holds filament was not reported."
    if key == "material_data":
        if any(o.field in ("material", "colour", "brand") for o in result.observations):
            return AVAILABLE, "Material details were reported."
        return UNKNOWN, "Material details were not reported."
    if key == "spool_identity":
        if any(f.field == "spool" for f in facts):
            if "spool" in unknowns:
                return AVAILABLE, "Some spool identities were reported; the rest are unknown."
            return AVAILABLE, "Spool identities were reported."
        return UNKNOWN, "The host did not report which spool is loaded. It is not treated as cleared."
    if key == "feeder_lanes":
        n = counts["lanes"] if counts else 0
        if n:
            return AVAILABLE, f"{n} feeder lane{'s' if n != 1 else ''} reported."
        return UNKNOWN, "No feeder lane data was reported."
    return UNKNOWN, ""


def _capabilities(result: AdapterResult, counts: dict | None, rows: list) -> list:
    out = []
    by_field: dict = {}
    for row in rows:
        by_field.setdefault(row["field"], []).append(row)
    for key, label, fields in _CAPABILITIES:
        state, reason = _data_state(key, result, counts)
        historical = False
        if state == AVAILABLE:
            backing = rows if fields is None else [r for f in fields for r in by_field.get(f, [])]
            if backing:
                fresh_state, historical, fresh_reason = _backing_state(backing)
                if fresh_state == STALE:
                    state, reason = STALE, f"{reason} {fresh_reason}"
                elif fresh_state == AVAILABLE and fresh_reason:
                    reason = f"{reason} {fresh_reason}"
        out.append(_capability(key, label, state, reason, historical))
    return out


def _identity_binding(topology: topo.Topology) -> tuple[bool, int]:
    """(every binding is slot:n -> head:n, number of non-identity bindings)."""
    targets: dict = {}
    for slot in topology.slots:
        if slot.binding is not None:
            targets.setdefault(slot.id, set()).add(slot.binding)
    for binding in topology.bindings:
        if binding.target is not None:
            targets.setdefault(binding.slot_id, set()).add(binding.target)
    bad = 0
    for slot_ref, tset in targets.items():
        n = topo.id_suffix_index(slot_ref)
        expected = topo.head_id(n) if n is not None else None
        if tset != {expected}:
            bad += 1
    return bad == 0, bad


def legacy_limitation(topologies: list) -> dict:
    """The notice older screens need. Applies for every topology that is not a plain four-head setup."""
    reasons: list = []
    if not topologies:
        reasons.append("Nothing was read, so the number of physical heads is not known.")
    for t in topologies:
        c = topo.counts(t)
        heads = c["physical_heads"]
        if heads is None:
            reasons.append("The number of physical heads is not known.")
        elif heads != 4:
            reasons.append(f"This setup reports {heads} physical head{'s' if heads != 1 else ''}, "
                           "and older screens assume four.")
        if c["logical_slots"] > 4:
            reasons.append(f"This setup reports {c['logical_slots']} logical slots, more than the four "
                           "older screens assume.")
        ok, bad = _identity_binding(t)
        if not ok:
            reasons.append(f"{bad} slot{'s are' if bad != 1 else ' is'} mapped to something other than "
                           "the head with the same number.")
    unique = list(dict.fromkeys(reasons))
    return {"applies": bool(unique), "reasons": unique, "text": LEGACY_NOTICE if unique else None}


def _assignability(topology: topo.Topology, reqs: list, constraints: topo.ResourceConstraints | None) -> dict:
    raw = topo.assignability(topology, reqs, constraints)
    n = len(reqs)
    bound = raw["bound"]
    verdict = {True: "can_match", False: "cannot_match", None: "unknown"}[raw["assignable"]]
    text = _VERDICT_TEXT[raw["assignable"]]
    if bound is not None:
        if raw["assignable"] is False:
            text += f" At most {bound['max']} of the {n} requested materials can be matched."
        elif raw["assignable"] is None:
            text += f" Between {bound['min']} and {bound['max']} of the {n} requested materials can be matched."
    return {"verdict": verdict, "assignable": raw["assignable"], "text": text,
            "requested": n, "bound": bound, "per_requirement": raw["per_requirement"],
            "reasons": list(raw["reasons"]), "inputs_revision": raw["inputs_revision"]}


def _unknown_assignability(n: int) -> dict:
    """An incomplete head list has no candidate heads; that is unknown, never a counted zero."""
    return {"verdict": "unknown", "assignable": None, "text": _VERDICT_TEXT[None], "requested": n,
            "bound": None, "per_requirement": [], "inputs_revision": None,
            "reasons": ["The host did not report a complete list of physical heads."]}


def _entry_report(item: dict, reqs: list, constraints: Any, now: Any) -> dict:
    result = item["result"]
    status = item["status"]
    entry = {"label": item["label"], "status": status, "kind": item.get("kind"),
             "variant": item.get("variant"), "adapter_id": getattr(result, "adapter_id", None),
             "source_version": getattr(result, "source_version", None)}
    if status != "ok" or not isinstance(result, AdapterResult):
        why = item.get("reason") or "not_read"
        text = {"api_key_missing": "This host needs an API key. Enter one and read it again.",
                "auth_required": "The host refused the API key.",
                "unreachable": "The host did not answer.",
                "not_moonraker_or_octoprint": "The host answered, but Studio does not recognise it."}.get(
                    why, "The host could not be read.")
        entry.update({"reason": why, "reason_text": text, "counts": None, "topology": None,
                      "capabilities": _all_state(_CAPABILITIES, UNAVAILABLE, text), "observations": [],
                      "unknowns": [], "assignability": None})
        return entry
    topology = result.topology
    counts = topo.counts(topology) if topology is not None else None
    rows = [_freshness_row(o, now) for o in result.observations]
    if result.errors:
        text = "The host reply could not be understood, so nothing is claimed from it."
        entry.update({"reason": "unreadable_reply", "reason_text": text, "counts": counts,
                      "topology": None, "capabilities": _all_state(_CAPABILITIES, UNKNOWN, text),
                      "observations": rows, "unknowns": list(result.unknowns), "assignability": None,
                      "errors": [d.to_dict() for d in result.errors]})
        return entry
    entry.update({"reason": None, "reason_text": None, "counts": counts,
                  "topology": topology.to_dict() if topology is not None else None,
                  "capabilities": _capabilities(result, counts, rows), "observations": rows,
                  "unknowns": list(result.unknowns),
                  "assignability": (_assignability(topology, reqs, constraints)
                                    if counts and counts["complete"] else _unknown_assignability(len(reqs)))
                  if (reqs and topology is not None) else None})
    return entry


def evaluate(entries: Iterable, *, requirements: Iterable | None = None,
             constraints: topo.ResourceConstraints | None = None, now: Any = None,
             revisions: dict | None = None) -> dict:
    """Build the setup report.

    `entries`: adapter results, or dicts {label, status, reason, result, kind, variant}.
    `requirements`: the project's material requirements (optional); with them each setup also gets
    a material-to-head assignability verdict.
    """
    items = [_entry_input(e, i) for i, e in enumerate(entries)]
    reqs = _requirements(requirements)
    reports = [_entry_report(it, reqs, constraints, now) for it in items]
    topologies = [it["result"].topology for it in items
                  if it["status"] == "ok" and isinstance(it["result"], AdapterResult)
                  and not it["result"].errors and it["result"].topology is not None]
    legacy = legacy_limitation(topologies)
    def _part(it: dict, rep: dict) -> dict:
        res = it["result"]
        t = res.topology if isinstance(res, AdapterResult) and not res.errors else None
        return {"label": rep["label"], "status": rep["status"], "adapter_id": rep["adapter_id"],
                "source_version": rep["source_version"],
                "topology": ({"snapshot_id": t.snapshot_id, "hash": t.content_hash()} if t is not None else None),
                "observation_ids": [o["observation_id"] for o in rep["observations"]]}

    parts = {"entries": [_part(it, rep) for it, rep in zip(items, reports)],
             "requirements": [q.to_dict() for q in reqs]}
    return {"schema_version": SCHEMA_VERSION, "entries": reports, "legacy_limitation": legacy,
            "inputs_revision": revision_envelope(parts, revisions),
            "advisory": "This report describes what was read. It is advisory and does not promise a print outcome."}
