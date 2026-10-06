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
#: the named preset unless the slot declares them), as plain labels and as project keys.
PRESET_CONTROLLED = {
    "fields": ["temperature", "flow", "volumetric speed", "pressure advance", "cooling",
               "bed temperature", "density", "cost"],
    "keys": ["nozzle_temperature", "nozzle_temperature_initial_layer", "filament_flow_ratio",
             "filament_max_volumetric_speed", "pressure_advance", "enable_pressure_advance",
             "fan_min_speed", "fan_max_speed", "hot_plate_temp", "textured_plate_temp",
             "cool_plate_temp", "eng_plate_temp", "filament_density", "filament_cost"],
}

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
                 withdrawn: dict) -> dict:
    ctx = context.get(s) or {}
    spool = ctx.get("spool")
    mapping = ctx.get("mapping") or {}
    preset = presets.get(s)
    wanted_colour = colours.get(s)
    involved = preset is not None or wanted_colour is not None
    found = catalog.evaluate(preset, nozzle) if (catalog is not None and preset) else None

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

    discrepancies = []
    if found and found["status"] == PROVEN and spool:
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
            "preset_controlled": (dict(PRESET_CONTROLLED) if preset else {"fields": [], "keys": []}),
        },
        "declarations": declarations,
        "discrepancies": discrepancies,
    }
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
        head = (f"Slot {n}: {who} mapped to '{out['preset_written']}'." if who else
                f"Slot {n}: mapped to '{out['preset_written']}' (chosen by you).")
        return (head + colour_text + f" Temperature, flow and cooling come from the installed "
                f"{out['preset_written']} preset.")
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
    withdrawn = {w["slot"]: w["withdrawn"]
                 for w in report.get("project_materials_declarations_withdrawn", []) or []}
    src_slots, out_slots = pm.extract_slots(source), pm.extract_slots(prepared)
    slots = [_slot_record(i, source, prepared, src_slots[i], out_slots[i], report, presets, colours,
                          context, catalog, nozzle, guard, withdrawn)
             for i in range(min(filament_count(source), filament_count(prepared)))]
    lines = [r["line"] for r in slots if r["involved"]]
    for r in slots:
        if r["declarations"]["withdrawn_studio_added"]:
            keys = ", ".join(r["declarations"]["withdrawn_studio_added"])
            lines.append(f"Slot {r['slot'] + 1}: Studio did not declare {keys}, so Snapmaker Orca takes "
                         f"them from '{r['output']['preset_written']}'.")
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
        "guard": {k: guard.get(k) for k in ("applies", "blocking", "mode", "conflicts", "shared",
                                             "warnings", "source_conflicts", "removed_by_mode")},
    }


# --- later display: clean what comes back, then check it against the prepared file ---------------

_TOP = ("schema", "mode", "nozzle", "slots", "lines", "counts", "guard")
_SLOT = ("slot", "label", "involved", "source", "selection", "output", "declarations",
         "discrepancies", "line")
_MAX_TEXT, _MAX_LIST, _MAX_DEPTH = 400, 64, 6


def _clean(value, depth=0):
    if depth > _MAX_DEPTH:
        return None
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:_MAX_TEXT]
    if isinstance(value, list):
        return [_clean(v, depth + 1) for v in value[:_MAX_LIST]]
    if isinstance(value, dict):
        return {str(k)[:60]: _clean(v, depth + 1) for k, v in list(value.items())[:_MAX_LIST]}
    return None


def sanitize(record) -> dict | None:
    """Keep only the shape :func:`build` writes. Anything else (extra keys, wrong types) is dropped."""
    if not isinstance(record, dict) or record.get("schema") != SCHEMA \
            or not isinstance(record.get("slots"), list):
        return None
    out = {k: _clean(record.get(k)) for k in _TOP if k in record}
    out["slots"] = [{k: _clean(s.get(k)) for k in _SLOT if k in s}
                    for s in record["slots"][:_MAX_LIST] if isinstance(s, dict)]
    return out


def verify(record: dict, prepared: dict | None) -> dict:
    """Mark each slot as confirmed or not against the prepared project, never trusting the record."""
    out = dict(record)
    out["verified"] = prepared is not None
    slots = []
    for slot in record.get("slots", []):
        slot = dict(slot)
        notes = []
        if prepared is None:
            notes.append("The prepared copy's settings could not be read, so this was not checked.")
        else:
            i = slot.get("slot")
            o = slot.get("output") or {}
            if isinstance(i, int):
                if o.get("preset_written") and _at(prepared, "filament_settings_id", i) != o["preset_written"]:
                    notes.append("The copy does not carry the preset this record says was written.")
                if o.get("colour_written") and pm.hex6(_at(prepared, "filament_colour", i)) != o["colour_written"]:
                    notes.append("The copy does not carry the colour this record says was written.")
        slot["verified"] = not notes
        slot["verification"] = notes
        slots.append(slot)
        out["verified"] = out["verified"] and not notes
    out["slots"] = slots
    return out


def attach(report: dict, materials, prepared_tm) -> dict:
    """Add the checked materials section to a fidelity report. Schema bumps only when there is one."""
    clean = sanitize(materials)
    if clean is None:
        return report
    prepared = None
    try:
        if pm.SETTINGS in prepared_tm.list_parts():
            prepared = load_project_settings(prepared_tm.read_part(pm.SETTINGS))
    except Exception:
        prepared = None
    report["materials"] = verify(clean, prepared)
    report["schema_version"] = "fidelity/2"
    return report
