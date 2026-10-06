"""What Project Materials did to each filament slot, said in plain language.

Built at Prepare time from the two configs that actually exist (the source and the prepared
copy) plus the person's selections. Everything that can be read from the files is read from
them — changed fields, declarations kept or removed — and only the facts the files cannot
carry (which spool, how the preset was matched, what Studio chose not to declare) come from
the selection. When the report is shown later it is checked against the prepared file again
(:func:`verify`), so a record that no longer matches the copy says so instead of being
believed.

The record holds the selected spool's identity and nothing else about a provider: no
address, key, token or remaining-weight history.
"""
from __future__ import annotations

from . import project_materials as pm
from . import spool_choices
from .config_io import load_project_settings
from .filaments import filament_count
from .preset_catalog import NO_MATCH, PROVEN
from .u1_identity import FILAMENT_IDENTITY_NOTICE

SCHEMA = "project-materials-fidelity/1"

#: What the installed preset decides once Orca loads it (measured on Orca 2.3.6: restored from
#: the named preset unless the slot - or another slot using the same preset - declares them).
_LABEL_KEYS = (
    ("temperature", ("nozzle_temperature", "nozzle_temperature_initial_layer",
                     "nozzle_temperature_range_low", "nozzle_temperature_range_high")),
    ("flow", ("filament_flow_ratio",)),
    ("volumetric speed", ("filament_max_volumetric_speed",)),
    ("pressure advance", ("pressure_advance", "enable_pressure_advance")),
    ("cooling", ("fan_min_speed", "fan_max_speed")),
    ("bed temperature", ("hot_plate_temp", "hot_plate_temp_initial_layer", "textured_plate_temp",
                         "textured_plate_temp_initial_layer", "cool_plate_temp",
                         "cool_plate_temp_initial_layer", "eng_plate_temp", "eng_plate_temp_initial_layer")),
    ("density", ("filament_density",)),
    ("cost", ("filament_cost",)),
)


def _controlled(preset: str | None, declared: set) -> dict:
    """What the preset controls for this slot, and what the project's own declarations keep from it."""
    if not preset:
        return {"fields": [], "keys": [], "kept_by_declaration": []}
    fields, keys, kept = [], [], []
    for label, group in _LABEL_KEYS:
        held = [k for k in group if k in declared]
        kept += held
        if not held:
            fields.append(label)
        keys += [k for k in group if k not in declared]
    return {"fields": fields, "keys": keys, "kept_by_declaration": sorted(kept)}

MAPPING_SOURCES = ("saved_spool", "saved_signature", "slicer_filament_confirmed", "manual")

_IDENTITY_FIELDS = ("filament_settings_id", "filament_colour", "filament_vendor", "filament_type")
_KEY_WORD = {"filament_vendor": "vendor", "filament_type": "type"}


def _at(cfg: dict, key: str, slot: int):
    values = cfg.get(key)
    if isinstance(values, list) and slot < len(values):
        return values[slot]
    return None


def _cap(text: str | None) -> str | None:
    return (text[:1].upper() + text[1:]) if text else text


def _norm(text) -> str:
    return "".join(ch for ch in str(text or "").casefold() if ch.isalnum())


def spool_label(spool: dict | None) -> str | None:
    """"Yoopai PLA+ Red #124" — enough to tell two similar spools apart."""
    if not spool:
        return None
    colour_word = _cap(spool.get("color_name") or spool_choices.color_name(spool.get("colour")))
    material = " ".join(x for x in (spool.get("material"), spool.get("subtype")) if x) or None
    text = " ".join(p for p in (spool.get("vendor"), material, colour_word) if p)
    sid = spool.get("id")
    return f"{text} #{sid}" if sid not in (None, "") and text else (text or (f"spool #{sid}" if sid else None))


def _colour_phrase(hex_value: str) -> str:
    name = spool_choices.color_name(hex_value)
    return _cap(name) if name else hex_value


def _slot_record(s: int, source: dict, prepared: dict, src_slot: dict, out_slot: dict, report: dict,
                 presets: dict, colours: dict, context: dict, catalog, nozzle: str, guard: dict,
                 withdrawn: dict, withdrawn_info: dict | None = None) -> dict:
    withdrawn_info = withdrawn_info or {}
    ctx = context.get(s) or {}
    spool = ctx.get("spool")
    mapping = ctx.get("mapping") or {}
    preset = presets.get(s)
    wanted_colour = colours.get(s)
    involved = preset is not None or wanted_colour is not None
    pin = ctx.get("preset") or {}
    found = (catalog.evaluate(preset, nozzle, pin.get("ref"), pin.get("source"))
             if (catalog is not None and preset) else None)

    changed, preserved = [], []
    for key in ("filament_settings_id", "filament_colour"):
        old, new = _at(source, key, s), _at(prepared, key, s)
        if old != new:
            changed.append({"key": key, "old": old, "new": new})
    if s == 0:
        old = (source.get("default_filament_profile") or [None])[0] \
            if isinstance(source.get("default_filament_profile"), list) else None
        new = (prepared.get("default_filament_profile") or [None])[0] \
            if isinstance(prepared.get("default_filament_profile"), list) else None
        if old != new:
            changed.append({"key": "default_filament_profile", "old": old, "new": new})
    changed_keys = {c["key"] for c in changed}
    for key in _IDENTITY_FIELDS:
        value = _at(prepared, key, s)
        if key not in changed_keys and value not in (None, ""):
            preserved.append({"key": key, "value": value})

    colour_changed = any(c["key"] == "filament_colour" for c in changed)
    source_declared = src_slot["declared_keys"]
    effective = out_slot["declared_keys"]
    gone_by_mode = sorted(set(source_declared) - set(effective))
    declarations = {
        "source": source_declared,
        "retained": sorted(set(source_declared) & set(effective)),
        "withdrawn_studio_added": withdrawn.get(s, []),
        "removed_by_mode": gone_by_mode,
        "declared_by_studio": sorted(set(effective) - set(source_declared)),
        "propagation": [],
    }
    for group in guard.get("shared", []):
        if s in group["slots"]:
            others = [m for m in group["slots"] if m != s]
            declarations["propagation"].append({
                "kind": "shared_preset", "preset": group["preset"], "slots": group["slots"],
                "text": (f"Slot {s + 1} shares “{group['preset']}” with "
                         f"{_slots_phrase(others)}.")})
    for w in guard.get("warnings", []):
        if s in w["slots"]:
            declarations["propagation"].append({
                "kind": "declared_values", "preset": w["preset"], "slots": w["slots"],
                "keys": w["keys"], "declared_in": w["declared_in"],
                "text": (f"Snapmaker Orca copies declared values ({', '.join(w['keys'])}) from "
                         f"{_slots_phrase(w['declared_in'])} to every slot using “{w['preset']}”.")})
    for c in guard.get("conflicts", []):
        if s in c["slots"]:
            declarations["propagation"].append({
                "kind": "conflict", "preset": c["preset"], "slots": c["slots"], "keys": [c["key"]],
                "declared_in": c["declared_in"],
                "text": (f"Conflicting {_KEY_WORD.get(c['key'], c['key'])} declarations on slots "
                         f"sharing “{c['preset']}” survive in the copy.")})

    # Orca copies a declared value to every slot using the same preset, so a declaration held by any slot
    # in this slot's group keeps that value from the preset here too.
    declared_here = set(effective)
    for group in guard.get("shared", []):
        if s in group["slots"]:
            for member in group["slots"]:
                declared_here |= set(pm.declared_keys(prepared, member))
    controlled = _controlled(preset, declared_here)

    discrepancies = []
    if found and found.get("preset_name") and spool:
        spool_material, preset_type = spool.get("material"), found.get("filament_type")
        if spool_material and preset_type and _norm(spool_material) != _norm(preset_type):
            discrepancies.append({
                "code": "material_mismatch",
                "text": f"The provider lists {spool_material}; the installed preset is {preset_type}."})
        spool_vendor, preset_vendor = spool.get("vendor"), found.get("vendor")
        if spool_vendor and preset_vendor and _norm(spool_vendor) != _norm(preset_vendor):
            discrepancies.append({
                "code": "vendor_mismatch",
                "text": (f"The provider lists {spool_vendor}; the installed preset’s vendor is "
                         f"{preset_vendor}. Studio did not override it.")})
    if preset and (ctx.get("preset") or {}).get("proof") == "user_confirmed":
        discrepancies.append({
            "code": "user_preset_unproven",
            "text": ("Studio could not tell from this preset of yours which printers it is for; "
                     "you confirmed it is a U1 preset.")})
    if mapping.get("stale"):
        discrepancies.append({
            "code": "stale_mapping",
            "text": ("The mapping saved for this spool no longer identifies the same installed "
                     "preset; the preset you confirmed for this Prepare was used instead.")})
    elif mapping.get("saved_base") and found and mapping["saved_base"] != found.get("base_name"):
        discrepancies.append({
            "code": "mapping_overridden",
            "text": (f"The saved mapping says “{mapping['saved_base']}”; you chose "
                     f"“{found.get('base_name')}” for this Prepare.")})
    if not preset:
        name = _at(prepared, "filament_settings_id", s)
        known = (catalog.evaluate(name, nozzle)["status"] != NO_MATCH) if (catalog and name) else False
        if not known:
            discrepancies.append({"code": "customized_preset_possible", "text": FILAMENT_IDENTITY_NOTICE})

    selection = None
    if involved:
        selection = {
            "provider": (spool or {}).get("provider"), "spool_id": (spool or {}).get("id"),
            "vendor": (spool or {}).get("vendor"), "material": (spool or {}).get("material"),
            "subtype": (spool or {}).get("subtype"), "colour": (spool or {}).get("colour"),
            "color_name": (spool or {}).get("color_name") or spool_choices.color_name((spool or {}).get("colour")),
            "label": spool_label(spool), "preset": preset,
            "mapping_source": (mapping.get("source") or "manual") if preset else None,
            "preset_source": ((ctx.get("preset") or {}).get("source") or "system") if preset else None,
            "preset_proof": (ctx.get("preset") or {}).get("proof") if preset else None,
        }

    record = {
        "slot": s, "label": f"Slot {s + 1}", "involved": involved,
        "source": {"settings_id": src_slot["settings_id"], "vendor": src_slot["vendor"],
                   "type": src_slot["material"], "colour": src_slot["colour"],
                   "declared_keys": source_declared},
        "selection": selection,
        "output": {
            "preset_written": preset,
            "colour_written": _hex(wanted_colour) if wanted_colour else None,
            "colour_changed": colour_changed,
            "vendor_type_origin": "preset" if preset else "project",
            "changed_fields": changed, "preserved_fields": preserved,
            "preset_controlled": controlled,
        },
        "declarations": declarations,
        "discrepancies": discrepancies,
    }
    record["declarations"]["withdrawn_reason"] = (withdrawn_info.get(s) or {}).get("reason")
    record["line"] = _line(record, spool)
    return record


def _hex(value) -> str | None:
    return pm.hex6(value)


def _slots_phrase(slots: list[int]) -> str:
    nums = [str(m + 1) for m in slots]
    return ("slot " + nums[0]) if len(nums) == 1 else ("slots " + ", ".join(nums[:-1]) + " and " + nums[-1])


def _line(rec: dict, spool: dict | None) -> str:
    n = rec["slot"] + 1
    out = rec["output"]
    sel = rec["selection"]
    if not rec["involved"]:
        return f"Slot {n}: no Project Materials choice; Studio keeps the project's own filament identity."
    who = (sel or {}).get("label")
    colour = out["colour_written"]
    colour_text = ""
    if colour:
        colour_text = (f" Colour changed to {_colour_phrase(colour)}." if out["colour_changed"]
                       else f" Colour was already {_colour_phrase(colour)}.")
    if out["preset_written"]:
        mine = " (a preset you made)" if (sel or {}).get("preset_source") == "user" else ""
        head = (f"Slot {n}: {who} mapped to '{out['preset_written']}'{mine}." if who else
                f"Slot {n}: mapped to '{out['preset_written']}' (chosen by you{', a preset you made' if mine else ''}).")
        pc = out["preset_controlled"]
        if mine:
            # Measured on Snapmaker Orca 2.4.0: a project naming one of the person's own presets kept the project's
            # values (isolated profile: Customized Preset prompt; normal profile: no prompt, preset shown as modified
            # with the project's values as unsaved changes). Studio cannot say Orca applies a user preset's values,
            # so for those it says only what is certain.
            held = (f" The project declares {', '.join(pc['kept_by_declaration'])}, so Orca keeps the project's own "
                    "value for it." if pc["kept_by_declaration"] else "")
            return (head + colour_text + " Studio cannot confirm Snapmaker Orca will apply this preset's temperature, "
                    "flow and cooling: when tested, Orca kept the project's values and showed the preset as modified "
                    "(as a Customized Preset in one profile). Manual check in Orca required. "
                    "Check the filament in Orca before slicing." + held)
        if not pc["kept_by_declaration"]:
            return (head + colour_text + f" Temperature, flow and cooling come from the installed "
                    f"{out['preset_written']} preset.")
        held = ", ".join(pc["kept_by_declaration"])
        why = "it" if len(pc["kept_by_declaration"]) == 1 else "them"
        lead = (f" The installed {out['preset_written']} preset controls {', '.join(pc['fields'])}; "
                if pc["fields"] else " ")
        return (head + colour_text + lead + f"Snapmaker Orca keeps the project's own value for {held}, "
                f"because the project declares {why}.")
    if colour and out["colour_changed"]:
        text = f"Slot {n}: Colour changed to {_colour_phrase(colour)}" + (f" (from {who})" if who else "") + "."
    else:
        text = f"Slot {n}:" + colour_text
    identity = rec["source"]["settings_id"]
    text += f" Studio keeps the project's filament identity '{identity}'." if identity else \
        " Studio keeps the project's filament identity."
    if any(d["code"] == "customized_preset_possible" for d in rec["discrepancies"]):
        text += " If Snapmaker Orca does not recognize that preset, Orca may treat it as a Customized Preset and rename it."
    return text


def build(*, source: dict, prepared: dict, report: dict, mode: str, confirmed_presets: dict | None,
          confirmed_colours: dict | None, context: dict | None, catalog, nozzle: str,
          guard: dict | None) -> dict:
    """The materials section for one Prepare. Reads only the two configs and the selections."""
    presets, colours = dict(confirmed_presets or {}), dict(confirmed_colours or {})
    context = context or {}
    guard = guard or {"shared": [], "warnings": [], "conflicts": [], "source_conflicts": [],
                      "removed_by_mode": []}
    info = {w["slot"]: w for w in report.get("project_materials_declarations_withdrawn", []) or []}
    withdrawn = {slot: w["withdrawn"] for slot, w in info.items()}
    src_slots, out_slots = pm.extract_slots(source), pm.extract_slots(prepared)
    slots = [_slot_record(i, source, prepared, src_slots[i], out_slots[i], report, presets, colours,
                          context, catalog, nozzle, guard, withdrawn, info)
             for i in range(min(filament_count(source), filament_count(prepared)))]
    lines = [r["line"] for r in slots if r["involved"]]
    group_lines, grouped = {}, set()
    for slot, w in sorted(info.items()):
        if w.get("reason") == "shared_preset_group" and len(w.get("group") or []) > 1:
            entry = group_lines.setdefault(w["preset"], {"slots": w["group"], "keys": set()})
            entry["keys"] |= set(w["withdrawn"])
            grouped.add(slot)
    withdrawn_groups = []
    for preset, entry in group_lines.items():
        keys = sorted(entry["keys"])
        phrase = ", ".join(k.replace("_", "-") for k in keys[:-1])
        phrase = (phrase + " and " if phrase else "") + keys[-1].replace("_", "-")
        mine = any((slots[m]["selection"] or {}).get("preset_source") == "user" for m in entry["slots"]
                   if m < len(slots))
        lines.append(f"{_cap(_slots_phrase(entry['slots']))} use '{preset}'. Studio removed its own {phrase} "
                     + ("declarations from this shared-preset group." if mine else
                        "declarations from this shared-preset group so Snapmaker Orca can apply the installed "
                        "preset consistently."))
        withdrawn_groups.append({"preset": preset, "slots": entry["slots"], "keys": keys})
    for r in slots:
        if r["declarations"]["withdrawn_studio_added"] and r["slot"] not in grouped:
            keys = ", ".join(r["declarations"]["withdrawn_studio_added"])
            if (r["selection"] or {}).get("preset_source") == "user":
                lines.append(f"Slot {r['slot'] + 1}: Studio did not declare {keys}, leaving those values to your preset "
                             f"'{r['output']['preset_written']}'.")
            else:
                lines.append(f"Slot {r['slot'] + 1}: Studio did not declare {keys}, so Snapmaker Orca takes "
                             f"them from '{r['output']['preset_written']}'.")
        in_group = r["slot"] in {s for g in withdrawn_groups for s in g["slots"]}
        if (r["involved"] or in_group) and r["declarations"]["retained"]:
            lines.append(f"Slot {r['slot'] + 1}: the project's own declaration of "
                         f"{', '.join(r['declarations']['retained'])} remains. Studio does not remove "
                         "declarations the source made.")
        if r["declarations"]["removed_by_mode"] and mode == "recommended":
            lines.append(f"Slot {r['slot'] + 1}: Recommended mode removed the declarations "
                         f"{', '.join(r['declarations']['removed_by_mode'])} before Prepare.")
    for c in guard.get("removed_by_mode", []):
        lines.append(f"Source contained conflicting {_KEY_WORD.get(c['key'], c['key'])} declarations "
                     f"on slots sharing '{c['preset']}'. Recommended mode removed those declarations "
                     "before Prepare, so no Orca propagation conflict remains.")
    for r in slots:
        for p in r["declarations"]["propagation"]:
            if p["kind"] == "declared_values" and r["slot"] == p["slots"][0]:
                lines.append(p["text"])
    return {
        "schema": SCHEMA, "mode": mode, "nozzle": nozzle, "slots": slots, "lines": lines,
        "counts": {"slots": len(slots), "involved": sum(1 for r in slots if r["involved"]),
                   "presets_written": sum(1 for r in slots if r["output"]["preset_written"]),
                   "colours_written": sum(1 for r in slots if r["output"]["colour_written"])},
        "withdrawn_groups": withdrawn_groups,
        "guard": {k: guard.get(k) for k in ("applies", "blocking", "mode", "conflicts", "shared",
                                             "warnings", "source_conflicts", "removed_by_mode")},
    }


# --- later display: rebuild what comes back from a strict schema, then check it against the files -----

_S = str
_ANY = object()          # a plain JSON scalar of any kind
_MAX_TEXT, _MAX_LIST = 400, 64

_SLOT_SCHEMA = {
    "slot": int, "label": _S, "involved": bool, "line": _S,
    "source": {"settings_id": _S, "vendor": _S, "type": _S, "colour": _S, "declared_keys": [_S]},
    "selection": {"provider": _S, "spool_id": _S, "vendor": _S, "material": _S, "subtype": _S, "colour": _S,
                  "color_name": _S, "label": _S, "preset": _S, "mapping_source": _S,
                  "preset_source": _S, "preset_proof": _S},
    "output": {
        "preset_written": _S, "colour_written": _S, "colour_changed": bool, "vendor_type_origin": _S,
        "changed_fields": [{"key": _S, "old": _ANY, "new": _ANY}],
        "preserved_fields": [{"key": _S, "value": _ANY}],
        "preset_controlled": {"fields": [_S], "keys": [_S], "kept_by_declaration": [_S]},
    },
    "declarations": {
        "source": [_S], "retained": [_S], "withdrawn_studio_added": [_S], "removed_by_mode": [_S],
        "declared_by_studio": [_S], "withdrawn_reason": _S,
        "propagation": [{"kind": _S, "preset": _S, "slots": [int], "keys": [_S], "declared_in": [int], "text": _S}],
    },
    "discrepancies": [{"code": _S, "text": _S}],
}
_CONFLICT = {"key": _S, "preset": _S, "slots": [int], "declared_in": [int]}
_SCHEMA = {
    "schema": _S, "mode": _S, "nozzle": _S, "lines": [_S],
    "counts": {"slots": int, "involved": int, "presets_written": int, "colours_written": int},
    "withdrawn_groups": [{"preset": _S, "slots": [int], "keys": [_S]}],
    "guard": {"applies": bool, "blocking": bool, "mode": _S, "conflicts": [_CONFLICT],
              "source_conflicts": [_CONFLICT], "removed_by_mode": [_CONFLICT],
              "shared": [{"preset": _S, "slots": [int]}],
              "warnings": [{"preset": _S, "slots": [int], "keys": [_S], "declared_in": [int], "text": _S}]},
}


def _conform(value, spec):
    """`value` rebuilt to `spec`: unknown keys dropped, wrong types become empty, text is bounded."""
    if spec is _ANY:
        if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
            return value
        return value[:_MAX_TEXT] if isinstance(value, str) else None
    if spec is _S:
        if isinstance(value, bool) or value is None:
            return None
        return str(value)[:_MAX_TEXT] if isinstance(value, (str, int, float)) else None
    if spec is int:
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    if spec is bool:
        return value if isinstance(value, bool) else None
    if isinstance(spec, list):
        if not isinstance(value, list):
            return []
        return [c for c in (_conform(v, spec[0]) for v in value[:_MAX_LIST])
                if c is not None and (not isinstance(spec[0], dict) or c)]
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            return None
        return {k: _conform(value.get(k), sub) for k, sub in spec.items() if k in value}
    return None


def sanitize(record) -> dict | None:
    """Rebuild a record to exactly the shape :func:`build` writes. Anything else is dropped, so a
    forged or oversized field (a provider key under `selection`, say) cannot ride along."""
    if not isinstance(record, dict) or record.get("schema") != SCHEMA \
            or not isinstance(record.get("slots"), list):
        return None
    out = {k: _conform(record.get(k), spec) for k, spec in _SCHEMA.items() if k in record}
    out["slots"] = [c for c in (_conform(s, _SLOT_SCHEMA) for s in record["slots"][:_MAX_LIST]) if c]
    return out


def verify(record: dict, prepared: dict | None, original: dict | None = None) -> dict:
    """Mark each slot confirmed or not against the project files, never trusting the record.

    Checked from the files: the preset and colour written, that every declaration the record says
    "remains" is really declared in the copy, and that the recorded source facts are the original's.
    The selected spool's own facts cannot be checked from a file and are not claimed to be."""
    out = dict(record)
    out["verified"] = prepared is not None
    src_slots = pm.extract_slots(original) if original is not None else None
    slots = []
    for slot in record.get("slots", []):
        slot = dict(slot)
        notes = []
        if prepared is None:
            notes.append("The prepared copy's settings could not be read, so this was not checked.")
        else:
            i = slot.get("slot")
            o = slot.get("output") or {}
            count = filament_count(prepared)
            shaped = all(isinstance(slot.get(k), dict) for k in ("source", "output", "declarations"))
            if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < count:
                notes.append("This slot cannot be checked: it does not name a filament slot of the copy.")
            elif not shaped:
                notes.append("This slot's record is incomplete, so it cannot be checked.")
            else:
                if o.get("preset_written") and _at(prepared, "filament_settings_id", i) != o["preset_written"]:
                    notes.append("The copy does not carry the preset this record says was written.")
                if o.get("colour_written") and pm.hex6(_at(prepared, "filament_colour", i)) != o["colour_written"]:
                    notes.append("The copy does not carry the colour this record says was written.")
                declared = set(pm.declared_keys(prepared, i))
                if not set((slot.get("declarations") or {}).get("retained") or []) <= declared:
                    notes.append("The copy does not declare everything this record says remains declared.")
                if src_slots is not None and 0 <= i < len(src_slots):
                    src = src_slots[i]
                    claimed = slot.get("source") or {}
                    for key, actual in (("settings_id", src["settings_id"]), ("vendor", src["vendor"]),
                                        ("colour", src["colour"]), ("declared_keys", src["declared_keys"])):
                        if key in claimed and claimed[key] != actual and not (claimed[key] in (None, "") and actual in (None, "")):
                            notes.append("The recorded source facts do not match the original project.")
                            break
        slot["verified"] = not notes
        slot["verification"] = notes
        slots.append(slot)
        out["verified"] = out["verified"] and not notes
    out["slots"] = slots
    return out


def _settings_of(tm):
    try:
        if tm is not None and pm.SETTINGS in tm.list_parts():
            return load_project_settings(tm.read_part(pm.SETTINGS))
    except Exception:
        return None
    return None


def attach(report: dict, materials, prepared_tm, original_tm=None) -> dict:
    """Add the checked materials section to a fidelity report. Schema bumps only when there is one."""
    clean = sanitize(materials)
    if clean is None:
        return report
    report["materials"] = verify(clean, _settings_of(prepared_tm), _settings_of(original_tm))
    report["schema_version"] = "fidelity/2"
    return report
