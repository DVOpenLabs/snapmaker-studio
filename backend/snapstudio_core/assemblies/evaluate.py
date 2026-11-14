"""Cumulative material need of an assembly against shared spools. Advisory.

Foundation-aware on purpose. Supply is an `Observation` of a spool's remaining grams, and what it
may be leaned on for comes from `observations.freshness` (`usable_for_loadout`). The legacy
`material_plan` sufficiency helper takes plain quantities with no lifetime, so it is not used
here.

Rules the result follows:
  * grams that are not stated stay unknown; they are never counted as zero;
  * a spool is one `SpoolRef` (or an alias group), counted once however many slots and tiles use it;
  * a slot with no role, an ambiguous role, or a role with no spool binding has no known physical
    consumption, so the verdict cannot be "enough";
  * a stale reading is reported as stale: neither a shortage nor "enough".
"""
from __future__ import annotations

import time
from typing import Any, Callable

from snapstudio_core.foundation import observations as obs_mod
from snapstudio_core.foundation.decode import is_finite_number
from snapstudio_core.foundation.materials import SpoolRef, same_spool

from .model import Assembly, AssemblyInputError, grams_or_none, spool_ref

MAX_SUPPLY = 64
SCALE_TOLERANCE = 0.001

ENOUGH, SHORTAGE, STALE, UNKNOWN = "enough", "shortage", "stale", "unknown"
ADVISORY = ("Advisory only: this adds up the grams the tiles state and compares them with the last stated "
            "remaining weight of each shared spool. It does not measure the spool and does not promise a print.")


# -- supply ----------------------------------------------------------------------
def read_supply(raw: Any, now: Any = None) -> list:
    """Request supply entries -> [(SpoolRef, Observation)]. Bad shapes are refused; bad times are not:
    an unreadable or missing time becomes an unknown/unusable freshness, which the verdict reports."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_SUPPLY:
        raise AssemblyInputError("supply must be a list of spool readings.")
    received = obs_mod.to_iso(time.time() if now is None else float(now))
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise AssemblyInputError("A supply reading must be an object.")
        ref = spool_ref(item.get("spool"), "A supply reading's spool")
        grams = grams_or_none(item.get("remaining_g"), "remaining_g")
        observed = item.get("observed_at")
        if observed is not None and (isinstance(observed, bool) or not isinstance(observed, (str, int, float))):
            raise AssemblyInputError("observed_at must be a time or null.")
        obs = obs_mod.Observation(
            observation_id=f"supply:{i}", subject={"kind": "spool", "id": ref.provider_spool_id},
            field="remaining_g", value=grams, source={"provider_instance_id": ref.provider_instance_id,
                                                      "kind": "live_query", "source_version": None, "snapshot_id": None},
            observed_at=observed, received_at=received, ttl_s=item.get("ttl_s"),
            ageing_ok=bool(item.get("ageing_ok", False)), historical=bool(item.get("historical", False)))
        out.append((ref, obs))
    return out


# -- tile checks -----------------------------------------------------------------
LibraryLookup = Callable[[int], "dict | None"]


def library_status(tile, lookup: LibraryLookup | None) -> dict:
    """linked | changed | missing | unverified | unlinked. The library is asked by project id; no foreign key."""
    ref = tile.library
    if ref is None:
        return {"status": "unlinked", "detail": "No library project is recorded for this tile."}
    if lookup is None:
        return {"status": "unverified", "detail": "The library was not checked."}
    try:
        found = lookup(ref.project_id)
    except Exception:  # an unreadable library is "not checked", never a crash
        return {"status": "unverified", "detail": "The library could not be read."}
    if found is None:
        return {"status": "missing", "detail": "That library project is no longer in the library."}
    current = found.get("sha256")
    if ref.sha256 is None or current is None:
        return {"status": "unverified", "detail": "The library project exists but its contents were not compared."}
    if current.lower() != ref.sha256:
        return {"status": "changed", "detail": "The library project's file differs from the one recorded for this tile."}
    return {"status": "linked", "detail": "The library project matches the recorded checksum."}


def seam_scale(assembly: Assembly) -> dict:
    """Tiles that meet at seams should be printed at one scale. Unknown scales stay unknown."""
    known = [(t.tile_id, t.scale) for t in assembly.tiles if t.scale is not None]
    unknown = [t.tile_id for t in assembly.tiles if t.scale is None]
    mismatch = False
    if len(known) > 1:
        values = [s for _, s in known]
        mismatch = max(values) / min(values) - 1.0 > SCALE_TOLERANCE
    if mismatch:
        status = "mismatch"
    elif unknown:
        status = "unknown"
    else:
        status = "consistent"
    return {"status": status, "known": [{"tile_id": t, "scale": s} for t, s in known], "unknown": unknown}


def role_summary(assembly: Assembly) -> list:
    out = []
    names = sorted({r for t in assembly.tiles for r in t.roles} | set(assembly.bindings))
    for role in names:
        tiles = [t for t in assembly.tiles if role in t.roles]
        plates = sorted({t.plate for t in tiles if t.plate is not None})
        binding = assembly.bindings.get(role)
        out.append({"role": role, "tiles": [t.tile_id for t in tiles], "plates": plates,
                    "shared_across_plates": len(plates) > 1,
                    "spool": binding.to_dict() if binding else None})
    return out


def parts_report(assembly: Assembly) -> dict:
    covered = {t.part_id for t in assembly.tiles if t.part_id}
    listed = {p["part_id"] for p in assembly.parts}
    return {"missing": [p for p in assembly.parts if p["part_id"] not in covered],
            "unlisted_tiles": [t.tile_id for t in assembly.tiles if t.part_id and t.part_id not in listed]}


# -- consumption -----------------------------------------------------------------
def _rows(assembly: Assembly) -> tuple[list, list]:
    """Per tile slot: grams (None unknown), the role it serves and the spool bound to that role.

    Returns (rows, unresolved). A tile slot is a slot the tile names a role for or has a gram entry for.
    """
    rows, unresolved = [], []
    for tile in assembly.tiles:
        by_slot: dict = {}
        for role, slot in tile.roles.items():
            by_slot.setdefault(slot, []).append(role)
        for slot in sorted(set(by_slot) | set(tile.usage), key=lambda s: int(s.split(":")[1])):
            grams = tile.usage.get(slot)
            roles = by_slot.get(slot, [])
            spool, why = None, None
            if len(roles) != 1:
                why = "no_role" if not roles else "ambiguous_role"
            elif roles[0] not in assembly.bindings:
                why = "no_binding"
            else:
                spool = assembly.bindings[roles[0]]
            row = {"tile_id": tile.tile_id, "slot": slot, "role": roles[0] if len(roles) == 1 else None,
                   "grams": grams, "spool": spool, "unresolved": why}
            rows.append(row)
            if why and grams != 0.0:
                unresolved.append({"tile_id": tile.tile_id, "slot": slot, "grams": grams, "reason": why,
                                   "roles": roles})
    return rows, unresolved


def _group_key(ref: SpoolRef, groups: list, aliases: list) -> int:
    for i, members in enumerate(groups):
        if any(same_spool(ref, m, aliases) for m in members):
            members.append(ref)
            return i
    groups.append([ref])
    return len(groups) - 1


def _supply_for(members: list, supply: list, aliases: list) -> list:
    return [(ref, ob) for ref, ob in supply if any(same_spool(ref, m, aliases) for m in members)]


def _supply_state(matches: list, now: Any) -> dict:
    """{state: usable|stale|unknown, remaining_g, reason, freshness}."""
    if not matches:
        return {"state": UNKNOWN, "remaining_g": None, "reason": "No remaining-weight reading was given for this spool.",
                "freshness": None}
    values = {ob.value for _, ob in matches}
    if len(values) > 1:
        return {"state": UNKNOWN, "remaining_g": None, "freshness": None,
                "reason": "Readings for this spool disagree, so none of them is used."}
    ref, ob = matches[0]
    fresh = obs_mod.freshness(ob, now)
    grams = ob.value
    base = {"remaining_g": grams if is_finite_number(grams) else None, "freshness": fresh}
    if grams is None:
        return {**base, "state": UNKNOWN, "reason": "The reading states no remaining weight."}
    if fresh["usable_for_loadout"]:
        return {**base, "state": "usable", "reason": fresh["reason"]}
    if fresh["state"] in (obs_mod.STALE, obs_mod.AGEING) or ob.historical:
        return {**base, "state": STALE, "reason": fresh["reason"]}
    return {**base, "state": UNKNOWN, "reason": fresh["reason"]}


def _spool_verdict(contribs: list, supply: dict) -> dict:
    """contribs: [{tile_id, grams (known sum) | None, unknown}] in tile order."""
    known = sum(c["grams"] or 0.0 for c in contribs)
    unknown_tiles = [c["tile_id"] for c in contribs if c["unknown"]]
    out = {"need_known_g": round(known, 3), "unknown_tiles": unknown_tiles, "need_complete": not unknown_tiles}
    state = supply["state"]
    if state == STALE:
        return {**out, "verdict": STALE, "starving_tiles": [], "shortfall_g": None,
                "reason": "The last remaining-weight reading is too old to rely on: " + supply["reason"]}
    if state == UNKNOWN:
        return {**out, "verdict": UNKNOWN, "starving_tiles": [], "shortfall_g": None, "reason": supply["reason"]}
    remaining = supply["remaining_g"]
    if known > remaining + 1e-9:
        running, starving = 0.0, []
        for c in contribs:
            running += c["grams"] or 0.0
            if running > remaining + 1e-9 or starving:
                starving.append(c["tile_id"])
        note = " The stated need is only a lower bound: some tiles state no grams." if unknown_tiles else ""
        return {**out, "verdict": SHORTAGE, "starving_tiles": starving,
                "shortfall_g": round(known - remaining, 3),
                "reason": f"The tiles state {known:g} g against {remaining:g} g left.{note}"}
    if unknown_tiles:
        return {**out, "verdict": UNKNOWN, "starving_tiles": [], "shortfall_g": None,
                "reason": "Some tiles state no grams for this spool, so the total need is not known."}
    return {**out, "verdict": ENOUGH, "starving_tiles": [], "shortfall_g": None,
            "reason": f"The tiles state {known:g} g against {remaining:g} g left."}


def evaluate(assembly: Assembly, supply: list | None = None, *, now: Any = None,
             lookup: LibraryLookup | None = None) -> dict:
    """The advisory report: per-tile need, per-spool verdict, overall verdict, and every unknown named."""
    supply = supply or []
    rows, unresolved = _rows(assembly)

    groups: list = []
    per_group: dict = {}
    for row in rows:
        if row["spool"] is None:
            continue
        g = _group_key(row["spool"], groups, assembly.aliases)
        per_group.setdefault(g, []).append(row)

    spools = []
    for g, members in enumerate(groups):
        contribs = []
        for tile in assembly.tiles:
            mine = [r for r in per_group.get(g, []) if r["tile_id"] == tile.tile_id]
            if not mine:
                continue
            unknown = any(r["grams"] is None for r in mine)
            contribs.append({"tile_id": tile.tile_id, "grams": sum(r["grams"] or 0.0 for r in mine), "unknown": unknown,
                             "roles": sorted({r["role"] for r in mine})})
        state = _supply_state(_supply_for(members, supply, assembly.aliases), now)
        verdict = _spool_verdict(contribs, state)
        spools.append({"spool": members[0].to_dict(), "same_spool_as": [m.to_dict() for m in members[1:]],
                       "roles": sorted({r["role"] for r in per_group.get(g, [])}),
                       "remaining_g": state["remaining_g"], "supply_state": state["state"],
                       "freshness": state["freshness"], "tiles": contribs, **verdict})

    link = {t.tile_id: library_status(t, lookup) for t in assembly.tiles}
    tiles = []
    for tile in assembly.tiles:
        trows = [r for r in rows if r["tile_id"] == tile.tile_id]
        known = [r["grams"] for r in trows if r["grams"] is not None]
        unknown_slots = [r["slot"] for r in trows if r["grams"] is None]
        tiles.append({
            "tile_id": tile.tile_id, "name": tile.name, "plate": tile.plate, "part_id": tile.part_id,
            "usage_source": tile.usage_source, "scale": tile.scale, "library": link[tile.tile_id],
            "attribution": dict(tile.attribution),
            "slots": [{"slot": r["slot"], "role": r["role"], "grams": r["grams"],
                       "spool": r["spool"].to_dict() if r["spool"] else None, "unresolved": r["unresolved"]}
                      for r in trows],
            "need_known_g": round(sum(known), 3),
            # No slot at all means no stated figure: the need is unknown, not zero.
            "need_complete": bool(trows) and not unknown_slots,
            "unknown_slots": unknown_slots,
        })

    verdicts = [s["verdict"] for s in spools]
    if SHORTAGE in verdicts:
        overall = SHORTAGE
    elif STALE in verdicts:
        overall = STALE
    elif not spools or UNKNOWN in verdicts or unresolved or any(not t["need_complete"] for t in tiles):
        overall = UNKNOWN
    else:
        overall = ENOUGH

    return {"name": assembly.name, "advisory": ADVISORY, "verdict": overall,
            "tiles": tiles, "spools": spools, "unresolved": unresolved,
            "roles": role_summary(assembly), "parts": parts_report(assembly), "seam_scale": seam_scale(assembly),
            "attribution": [dict(a) for a in assembly.attribution]}
