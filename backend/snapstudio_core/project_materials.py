"""Project Materials: which spool, and which installed Orca preset, for each filament slot.

Read-only analysis plus the pieces Prepare needs. Nothing here talks to a provider,
writes to one, or decrements anything: the caller hands in what a provider already
returned. Nothing is chosen for the person — every candidate list is a ranked
suggestion with the reasons attached, so the app shows reasons it was given instead
of recomputing them.

Measured on Orca 2.3.6 (the GUI matrices):

* a real installed preset name makes Orca restore that preset's `filament_ids` and print
  values; undeclared print/identity overrides revert to it;
* a *declared* override survives, but Orca copies it, with its declaration, to every
  slot that uses the same preset;
* colour is project state and needs no declaration.

So Project Materials writes the real preset name and the spool colour, declares nothing,
and refuses (:func:`guard`) a project whose existing vendor/type declarations Orca would
propagate between slots that share a preset.
"""
from __future__ import annotations

from . import material_mapping, material_plan, spool_choices
from .config_io import load_project_settings
from .filaments import filament_count
from .preset_catalog import NEEDS_CONFIRMATION, NO_MATCH, PROVEN

SCHEMA = "project-materials/1"

#: Slot identity keys Orca restores from the named preset unless the slot declares them.
IDENTITY_KEYS = ("filament_vendor", "filament_type")

#: Two top candidates this close in colour (RGB distance) count as a close call.
CLOSE_COLOUR = 10.0
DEFAULT_LIMIT = 5

SETTINGS = "Metadata/project_settings.config"

_PRESET_TIER = {PROVEN: 2, NEEDS_CONFIRMATION: 1, NO_MATCH: 0}


def _list(value) -> list:
    return list(value) if isinstance(value, list) else []


def _item(values: list, index: int):
    if index >= len(values):
        return None
    text = str(values[index]).strip()
    return text or None


def hex6(value) -> str | None:
    """`#RRGGBB` from `#RRGGBB`, `RRGGBB` or `#RRGGBBAA`; None when unreadable."""
    text = str(value or "").strip().lstrip("#")
    if len(text) not in (6, 8):
        return None
    try:
        int(text, 16)
    except ValueError:
        return None
    return "#" + text[:6].upper()


def declared_keys(cfg: dict, slot: int) -> list[str]:
    """What the project declares for one filament slot (`different_settings_to_system`)."""
    entries = cfg.get("different_settings_to_system")
    if not isinstance(entries, list):
        return []
    index = 1 + slot                       # entry 0 is the process preset
    if index >= len(entries) - 1:          # the last entry is the printer
        return []
    return sorted({p.strip() for p in str(entries[index] or "").split(";") if p.strip()})


def required_grams(plates: list[dict] | None) -> dict[int, float]:
    """Grams per 0-based slot the source file's OWN slice reports. Absent means unknown."""
    out: dict[int, float] = {}
    for plate in plates or []:
        for entry in plate.get("filaments") or []:
            grams = entry.get("used_g")
            try:
                slot = int(entry.get("id")) - 1
            except (TypeError, ValueError):
                continue
            if grams is None or slot < 0:
                continue
            out[slot] = out.get(slot, 0.0) + float(grams)
    return {k: round(v, 2) for k, v in out.items()}


def project_nozzle(cfg: dict) -> str:
    """The nozzle Prepare will name in the copy, so presets are checked against it."""
    from . import process_preset
    from .profile import load_profile
    from .u1_identity import U1_PRINTER_VARIANT

    # Prepare applies the U1 profile before it names the printer, and that profile sets the nozzle, so
    # the copy is written for the profile's nozzle whatever the source used. Presets must fit THAT.
    probe = dict(cfg)
    profile_nozzle = load_profile("snapmaker_u1")["keys"].get("nozzle_diameter")
    if profile_nozzle is not None:
        probe["nozzle_diameter"] = profile_nozzle
    chosen = process_preset.choose(probe)
    return str(chosen["printer_variant"]) if chosen.get("matched") else U1_PRINTER_VARIANT


def extract_slots(cfg: dict, plates: list[dict] | None = None) -> list[dict]:
    """One entry per filament slot, from what the project states. Nothing is invented."""
    from .material_providers import _family_and_subtype

    colours = _list(cfg.get("filament_colour"))
    types = _list(cfg.get("filament_type"))
    names = _list(cfg.get("filament_settings_id"))
    vendors = _list(cfg.get("filament_vendor"))
    grams = required_grams(plates)
    out = []
    for slot in range(filament_count(cfg)):
        material = _item(types, slot)
        family, subtype = _family_and_subtype(material)
        declared = declared_keys(cfg, slot)
        out.append({
            "slot": slot,
            "material": material,
            "family": family,
            "subtype": subtype,
            "colour": hex6(_item(colours, slot)),
            "required_g": grams.get(slot),
            "required_source": "the source file's own slice" if slot in grams else None,
            "settings_id": _item(names, slot),
            "vendor": _item(vendors, slot),
            "declared_keys": declared,
            "declared_identity": [k for k in declared if k in IDENTITY_KEYS],
        })
    return out


def read_project(tm) -> tuple[dict | None, list[dict]]:
    """The settings and the author's per-plate figures from an opened 3MF, or (None, [])."""
    from . import project_traits

    if SETTINGS not in tm.list_parts():
        return None, []
    cfg = load_project_settings(tm.read_part(SETTINGS))
    try:
        plates = project_traits._plate_predictions(tm)
    except Exception:
        plates = []
    return cfg, plates


# --- same-preset guard ---------------------------------------------------------

def guard(cfg: dict, slots: list[dict], confirmed: dict | None, catalog, nozzle: str) -> dict:
    """Would Orca copy a slot's vendor/type declaration onto another slot with the same preset?

    Measured: a declared override is written, with its declaration, to every slot that
    uses the same installed preset. Where those slots hold different vendor/type values
    that silently rewrites a slot. Project Materials creates no such declaration itself;
    this finds the ones the source project already carries. It reports and blocks — it
    never strips or rewrites a declaration.

    `confirmed` is the person's slot -> preset choice. The guard only BLOCKS when there is
    one (Project Materials is in use); otherwise it reports what Orca will do anyway.
    """
    confirmed = confirmed or {}
    out = {"applies": bool(confirmed), "blocking": False, "conflicts": [], "shared": [],
           "warnings": [], "resolution": None}
    if catalog is None:
        return out
    groups: dict[str, list[int]] = {}
    for s in slots:
        name = confirmed.get(s["slot"]) or s["settings_id"]
        if not name:
            continue
        found = catalog.evaluate(name, nozzle)
        if found.get("base_name"):
            groups.setdefault(found["base_name"], []).append(s["slot"])
    by_slot = {s["slot"]: s for s in slots}
    for base, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        out["shared"].append({"preset": base, "slots": members})
        for key in IDENTITY_KEYS:
            declared_by = [m for m in members if key in by_slot[m]["declared_keys"]]
            if not declared_by:
                continue
            values = {m: _item(_list(cfg.get(key)), m) for m in members}
            if len(set(values.values())) > 1:
                out["conflicts"].append({"key": key, "preset": base, "slots": members,
                                         "declared_in": declared_by, "values": values})
        extra = sorted({k for m in members for k in by_slot[m]["declared_keys"]
                        if k not in IDENTITY_KEYS and k != "filament_colour"})
        declarers = [m for m in members if set(by_slot[m]["declared_keys"]) - set(IDENTITY_KEYS)
                     - {"filament_colour"}]
        if extra and declarers:
            out["warnings"].append({"preset": base, "slots": members, "declared_in": declarers,
                                    "keys": extra,
                                    "text": ("Snapmaker Orca copies a declared value to every slot "
                                             "that uses the same preset.")})
    if out["conflicts"]:
        out["blocking"] = bool(confirmed)
        out["resolution"] = (
            "These slots share one installed Orca preset but the project declares a different "
            "vendor or type for one of them, and Snapmaker Orca copies a declared value to every "
            "slot that uses the same preset. Choose a different installed preset for each slot, "
            "or remove the declaration in the source project. Studio does not edit it for you.")
    return out


def effective_guard(source_cfg: dict, prepared_cfg: dict, confirmed: dict | None, catalog,
                    nozzle: str, mode: str = "preserve") -> dict:
    """The guard, judged on the declarations that will actually be WRITTEN.

    Orca propagates what the prepared file declares, not what the source declared. A mode
    that removes the source's declarations (Recommended) leaves nothing to propagate, so
    nothing blocks; a mode that keeps them (Preserve) does. The source's own conflicts are
    still reported (``source_conflicts``), and the ones the mode took away are listed in
    ``removed_by_mode``. Neither config is changed."""
    out = guard(prepared_cfg, extract_slots(prepared_cfg), confirmed, catalog, nozzle)
    source = guard(source_cfg, extract_slots(source_cfg), confirmed, catalog, nozzle)

    def ident(c):
        return (c["key"], c["preset"], tuple(c["slots"]))

    surviving = {ident(c) for c in out["conflicts"]}
    out["source_conflicts"] = source["conflicts"]
    out["removed_by_mode"] = [c for c in source["conflicts"] if ident(c) not in surviving]
    out["mode"] = mode
    if out["conflicts"] and mode == "preserve":
        out["resolution"] = (out["resolution"] or "") + (
            " Recommended mode removes the source's declarations before it writes the copy.")
    return out


def guard_message(result: dict) -> str:
    parts = []
    for c in result.get("conflicts", []):
        slots = ", ".join(str(s + 1) for s in c["slots"])
        parts.append(f"slots {slots} share “{c['preset']}” but disagree on {c['key']}")
    return ("Prepare stopped: " + "; ".join(parts) + ". " + (result.get("resolution") or "")).strip()


# --- candidates and recommendation ----------------------------------------------

def loaded_slots(state: dict | None) -> dict[str, int]:
    """Spool id -> the provider slot it is mapped to, when a slot map says so."""
    out: dict[str, int] = {}
    for slot in (state or {}).get("slots") or []:
        if slot.get("present") and slot.get("spool_id") is not None:
            out.setdefault(str(slot["spool_id"]), slot.get("slot"))
    return out


def _subtype_tier(slot_sub, spool_sub) -> tuple[int, dict]:
    a = (slot_sub or "").strip().casefold()
    b = (spool_sub or "").strip().casefold()
    if a and b and a == b:
        return 3, {"code": "subtype_exact", "text": f"Subtype matches: {spool_sub}"}
    if not a or not b:
        why = "the model does not name a subtype" if not a else "the spool has no subtype"
        return 2, {"code": "subtype_unspecified", "text": f"Subtype not compared: {why}"}
    return 0, {"code": "subtype_differs",
               "text": f"Subtype differs: model {slot_sub}, spool {spool_sub}"}


def _weight(slot: dict, spool: dict) -> tuple[int, dict]:
    needed, have = slot.get("required_g"), spool.get("remaining_g")
    if needed is None and have is None:
        return 1, {"code": "amount_unknown",
                   "text": "Amount unknown: the model does not say how much it needs and the "
                           "provider does not report what is left"}
    if needed is None:
        return 1, {"code": "amount_needed_unknown", "data": {"available_g": have},
                   "text": f"{have:g} g recorded; the model does not say how much it needs"}
    if have is None:
        return 1, {"code": "amount_unknown", "data": {"needed_g": needed},
                   "text": f"Remaining amount unknown ({needed:g} g needed)"}
    verdict = material_plan._sufficiency(needed, have, spool.get("remaining_quality") or "unknown",
                                         spool.get("remaining_as_of"))
    data = {"available_g": have, "needed_g": needed, "verdict": verdict["verdict"],
            "trusted": verdict["trusted"]}
    if verdict["verdict"] in ("insufficient", "probably_short"):
        return 0, {"code": "weight_short", "data": data,
                   "text": f"May not be enough: {have:g} g available / {needed:g} g needed"}
    text = f"Enough filament: {have:g} g available / {needed:g} g needed"
    if verdict["verdict"] == "enough" and verdict["trusted"]:
        return 3, {"code": "weight_enough", "data": data, "text": text}
    return 2, {"code": "weight_enough_untrusted", "data": data,
               "text": text + " (a figure Studio cannot fully trust)"}


def _preset_reason(mapping: dict) -> dict:
    status = mapping["status"]
    if status == PROVEN:
        return {"code": "preset_proven",
                "text": f"Preset proven: {mapping['preset_name']}"}
    if status == NEEDS_CONFIRMATION:
        return {"code": "preset_needs_confirmation",
                "text": "Preset needs confirmation: " + (mapping.get("reason") or "")}
    return {"code": "preset_none", "text": "No installed preset chosen for this spool yet"}


def _tie_key(spool: dict) -> tuple:
    """vendor, material, subtype, colour, then the spool's own name, then its id."""
    base = spool_choices.sort_key({
        "vendor": spool.get("vendor"), "material": spool.get("material"),
        "subtype": spool.get("subtype"), "color_name": spool.get("color_name"),
        "color": spool.get("color"), "id": spool.get("id")})
    return base[:-1] + (spool_choices._text_key(spool.get("name")),) + base[-1:]


def candidate(provider: str, slot: dict, spool: dict, loaded: int | None, catalog, store,
              nozzle: str) -> dict | None:
    """One spool as a candidate for one slot, with the facts and the reasons. None if the family differs."""
    family = (spool.get("material") or "").strip().upper()
    if not family or family != (slot.get("family") or "").upper() or spool.get("archived"):
        return None
    mapping = material_mapping.resolve(catalog, store, provider, spool, nozzle)
    sub_tier, sub_reason = _subtype_tier(slot.get("subtype"), spool.get("subtype"))
    weight_tier, weight_reason = _weight(slot, spool)
    distance = material_plan.colour_distance(slot.get("colour"), spool.get("color"))
    if distance is None:
        colour_reason = {"code": "colour_unknown", "text": "Colour could not be compared"}
    else:
        colour_reason = {"code": "colour_distance", "data": {"distance": round(distance)},
                         "text": f"Colour distance: {round(distance)}"}
    reasons = [{"code": "material_exact", "text": f"Material matches: {family}"}, sub_reason,
               _preset_reason(mapping), weight_reason, colour_reason]
    if loaded is not None:
        reasons.append({"code": "loaded", "data": {"slot": loaded},
                        "text": f"Already loaded in {material_plan._slot_word(int(loaded))}"})
    return {
        "provider": provider, "spool_id": spool.get("id"),
        "label": spool.get("label") or spool_choices._label(
            spool.get("vendor"), spool.get("material"), spool.get("subtype"), spool.get("name"),
            spool.get("id")),
        "vendor": spool.get("vendor"), "material": family, "subtype": spool.get("subtype"),
        "colour": hex6(spool.get("color")), "color_name": spool.get("color_name")
        or spool_choices.color_name(spool.get("color")),
        "remaining_g": spool.get("remaining_g"),
        "remaining_quality": spool.get("remaining_quality"),
        "remaining_as_of": spool.get("remaining_as_of"),
        "loaded_slot": loaded, "slicer_filament": spool.get("slicer_filament") or None,
        "mapping": mapping, "reasons": reasons,
        "_rank": (sub_tier, _PRESET_TIER[mapping["status"]], weight_tier,
                  -(distance if distance is not None else 1e9), 1 if loaded is not None else 0),
        "_distance": distance,
        "_tie": _tie_key(spool),
    }


def recommend(slot: dict, provider: str, spools: list[dict], state: dict | None, catalog, store,
              nozzle: str, limit: int = DEFAULT_LIMIT) -> dict:
    """Ranked candidates for one slot. Order: family (filter), subtype, proven preset, trusted
    sufficient weight, nearest colour, already loaded, then vendor/name/id. Never selects one."""
    loaded = loaded_slots(state)
    found = []
    for spool in spools or []:
        c = candidate(provider, slot, spool, loaded.get(str(spool.get("id"))), catalog, store, nozzle)
        if c:
            found.append(c)
    found.sort(key=lambda c: c["_tie"])                       # deterministic base order
    found.sort(key=lambda c: c["_rank"], reverse=True)        # stable: ties keep the base order
    close = False
    if len(found) >= 2:
        a, b = found[0], found[1]
        same = a["_rank"][:3] == b["_rank"][:3]
        da, db = a["_distance"], b["_distance"]
        near = (da is None and db is None) or (da is not None and db is not None
                                               and abs(da - db) <= CLOSE_COLOUR)
        close = same and near
    top = found[:max(0, int(limit))]
    for i, c in enumerate(top):
        c["rank"] = i + 1
    for c in found:
        for k in ("_rank", "_distance", "_tie"):
            c.pop(k, None)
    return {"candidates": top, "candidate_count": len(found), "close_call": close,
            "selected": None}


def analyze(cfg: dict, plates: list[dict] | None, *, provider: str | None, state: dict | None,
            catalog, store, limit: int = DEFAULT_LIMIT, confirmed: dict | None = None) -> dict:
    """Everything the Project Materials card needs for one project. Nothing is selected."""
    nozzle = project_nozzle(cfg)
    slots = extract_slots(cfg, plates)
    spools = (state or {}).get("spools") or [] if (state or {}).get("available") else []
    out = {"schema": SCHEMA, "supported": True, "nozzle": nozzle,
           "catalog": {"available": catalog is not None,
                       "source": catalog.source if catalog else None,
                       "fingerprint": catalog.fingerprint if catalog else None},
           "provider": ({"kind": provider, "available": bool((state or {}).get("available")),
                         "error_code": (state or {}).get("error_code")} if provider else None),
           "slots": [], "guard": None}
    for s in slots:
        rec = recommend(s, provider or "", spools, state, catalog, store, nozzle, limit)
        current = (catalog.evaluate(s["settings_id"], nozzle) if catalog and s["settings_id"]
                   else None)
        suggestion = catalog.suggest_generic(s["family"], nozzle) if catalog and s["family"] else None
        out["slots"].append({**s, "current_preset": current, "suggestion": suggestion, **rec})
    out["guard"] = guard(cfg, slots, confirmed, catalog, nozzle)
    return out


# --- Prepare inputs --------------------------------------------------------------

def apply_colours(cfg: dict, colours: dict | None) -> list[dict]:
    """Write the selected spools' colours into `filament_colour`. Returns what changed."""
    changes = []
    current = cfg.get("filament_colour")
    if not colours or not isinstance(current, list):
        return changes
    updated = list(current)
    for slot, wanted in sorted(colours.items()):
        new = hex6(wanted)
        if new is None or not 0 <= slot < len(updated):
            continue
        old = str(updated[slot])
        # Keep the project's own notation: an 8-digit value keeps its alpha pair.
        value = new + old.lstrip("#")[6:8].upper() if len(old.lstrip("#")) == 8 else new
        if old.upper() != value.upper():
            changes.append({"slot": slot, "old": old, "new": value})
            updated[slot] = value
    if changes:
        cfg["filament_colour"] = updated
    return changes


def same_preset_groups(cfg: dict, catalog, nozzle: str) -> dict[str, list[int]]:
    """Base preset name -> the slots whose effective filament preset is that installed preset."""
    groups: dict[str, list[int]] = {}
    if catalog is None:
        return groups
    names = _list(cfg.get("filament_settings_id"))
    for slot in range(filament_count(cfg)):
        name = _item(names, slot)
        if not name:
            continue
        found = catalog.evaluate(name, nozzle)
        if found.get("base_name"):
            groups.setdefault(found["base_name"], []).append(slot)
    return groups


def withdraw_studio_declarations(cfg: dict, before, confirmed, filaments: int,
                                 groups: dict | None = None) -> list[dict]:
    """Take Studio's OWN declarations back off every slot that must follow a confirmed preset.

    Orca keeps a declared value over the preset's and copies it, with its declaration, to every
    slot using the same installed preset. So a print value Studio declared would defeat the preset
    the person chose, on the confirmed slot and on any slot that shares that preset. This
    restores, for those slots, the declaration they had before Studio's step.

    * a confirmed slot, and every other slot in its same-preset group, are covered;
    * only what Studio added is removed - `before` is the state just ahead of Studio's
      declaration step, so a declaration the project itself made is never touched;
    * slots on a different preset are left exactly as they were.
    """
    from . import preset_deviation

    entries = cfg.get("different_settings_to_system")
    if not isinstance(entries, list):
        return []
    confirmed = set(confirmed or ())
    reason: dict[int, tuple[str, str | None, list[int]]] = {s: ("confirmed_slot", None, [s]) for s in confirmed}
    for base, members in sorted((groups or {}).items()):
        if confirmed & set(members):
            for m in members:
                if m not in confirmed:
                    reason[m] = ("shared_preset_group", base, list(members))
                elif len(members) > 1:
                    reason[m] = ("shared_preset_group", base, list(members))
    original = preset_deviation._entries(before, filaments)
    out = []
    for slot in sorted(reason):
        index = preset_deviation.FIRST_FILAMENT + slot
        if index >= len(entries) - 1 or index >= len(original) - 1:
            continue
        added = (set(p.strip() for p in str(entries[index]).split(";") if p.strip())
                 - set(p.strip() for p in str(original[index]).split(";") if p.strip()))
        if added:
            entries[index] = original[index]
            why, base, members = reason[slot]
            out.append({"slot": slot, "withdrawn": sorted(added), "reason": why, "preset": base,
                        "group": members})
    return out


def change_records(filament: dict) -> list[dict]:
    """The settings Project Materials changed, as accountable change records.

    Prepare's preservation check requires every changed setting to have a stated reason;
    these are the reasons, and they are the only filament changes Project Materials makes."""
    out = []
    applied = filament.get("applied") or []
    if applied:
        out.append({"key": "filament_settings_id",
                    "reason": "Project Materials: the installed Orca preset you confirmed"})
        if any(a["slot"] == 0 for a in applied):
            out.append({"key": "default_filament_profile",
                        "reason": "Project Materials: follows the preset confirmed for slot 1"})
    if filament.get("colours"):
        out.append({"key": "filament_colour",
                    "reason": "Project Materials: the colour of the spool you selected"})
    return out


def prepare_inputs(selections: list[dict] | None, cfg: dict, catalog, nozzle: str,
                   proofs: dict | None = None) -> tuple[dict, dict]:
    """Turn the person's explicit selections into (confirmed_presets, confirmed_colours).

    Each selection: ``{"slot": 0, "preset": "<installed preset name>"|None, "colour": "#RRGGBB"|None,
    "source": "system"|"user"|None, "ref": "<user preset file>"|None, "accept_unproven": bool}``.
    A preset must be PROVEN in the installed catalogue right now - a remembered or suggested name is
    not enough until the person has confirmed it by sending it here. The one exception is one of the
    person's own presets that does not say which printers it is for: it is used only when the person
    says it is a U1 preset (``accept_unproven``). `source`/`ref` pin one installed preset when a name is
    ambiguous. A slot with no preset keeps the project's own filament identity. When `proofs` is given
    it is filled with how each preset was established, for the fidelity record.
    """
    presets: dict[int, str] = {}
    colours: dict[int, str] = {}
    count = filament_count(cfg)
    for sel in selections or []:
        if not isinstance(sel, dict):
            raise ValueError("each material selection must be an object")
        slot = sel.get("slot")
        if not isinstance(slot, int) or isinstance(slot, bool) or not 0 <= slot < count:
            raise ValueError(f"material selection names slot {slot!r}, but the project has {count} filaments")
        if slot in presets or slot in colours:
            raise ValueError(f"slot {slot + 1} appears twice in the material selections")
        preset = (sel.get("preset") or "").strip() if isinstance(sel.get("preset"), str) else ""
        if sel.get("preset") not in (None, "") and not preset:
            raise ValueError("preset must be a name")
        # validated on every selection, with or without a preset, so a malformed flag is never silently ignored
        ref, source, accept = sel.get("ref"), sel.get("source"), sel.get("accept_unproven")
        if ref is not None and not isinstance(ref, str):
            raise ValueError("ref must be text")
        if source not in (None, "system", "user"):
            raise ValueError("source must be 'system' or 'user'")
        if accept is not None and type(accept) is not bool:
            raise ValueError("accept_unproven must be true or false")
        if preset:
            if catalog is None:
                raise ValueError("Snapmaker Orca's installed filament presets could not be read, "
                                 "so no preset can be applied")
            found = catalog.evaluate(preset, nozzle, ref, source)
            proven = found["status"] == PROVEN
            if not proven and not (found.get("confirmable") and accept is True):
                hint = (" It is one of your own presets and does not say which printers it is for; confirm "
                        "that it is a U1 preset to use it." if found.get("confirmable") else "")
                raise ValueError(f"“{preset}” is not a proven installed preset for the {nozzle} mm "
                                 f"nozzle: {found['reason']}{hint}")
            sent = sel.get("fingerprint")
            if (not proven and sent != found.get("fingerprint")) or (proven and sent not in (None, found.get("fingerprint"))):
                # the person chose the preset they were shown; it has been replaced since, so it is not applied
                raise ValueError(f"“{preset}” has changed since you confirmed it. Choose it again to confirm it.")
            presets[slot] = found["preset_name"]
            if proofs is not None:
                proofs[slot] = {"source": found.get("source"), "ref": found.get("ref"),
                                "proof": found.get("proof") if proven else "user_confirmed"}
        if sel.get("colour") not in (None, ""):
            value = hex6(sel.get("colour"))
            if value is None:
                raise ValueError(f"colour {sel.get('colour')!r} is not a hex colour")
            colours[slot] = value
    return presets, colours
