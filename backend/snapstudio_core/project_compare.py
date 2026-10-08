"""Read-only comparison of a source 3MF and the copy Studio prepared from it.

Built for support: when someone reports "the prepared file still shows the wrong filament", attach both files and
run ::

    py -m snapstudio_core.project_compare source.3mf prepared.3mf        # compare
    py -m snapstudio_core.project_compare source.3mf                     # one file's slots and where they are used

It opens each file, reads it, prints JSON, and writes nothing: the files are never modified and nothing leaves the
computer. Object and part NAMES are not printed (they can identify a private model); ids, counts and the project's
filament settings are.

What it reports, per filament slot (numbered from 1, as Orca shows them):

* the project's identity for the slot: colour, type, vendor, preset name (`filament_settings_id`), `filament_ids`,
  and the keys the project declares as different from the system preset;
* where the project REFERENCES the slot, by kind, so "unused" is never guessed: an object's extruder, a part's
  extruder (and the part's subtype), painted facets, a recorded colour change, a process role (wall, infill,
  support, support interface, wipe tower), and the grams the project's own slice reports;
* whether any reference was found. `no_reference_found` is the strongest thing this can say - it means none of the
  places above names the slot, not that the slot is certainly unused - and it is withheld (`unknown`) whenever
  the painting or the object list could not be read in full.

Not read, and said so in the output (`not_read`): per-layer-range modifiers. A slot named only there reads as
`no_reference_found`.

Compared across the two files: the slot count, each slot's identity fields, the declarations, and every top-level
setting whose name starts with `filament_` or `default_filament`, so exactly what Project Materials changed is
visible.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from . import color_plan, painted_color
from .container import ThreeMF

SCHEMA = "project-compare/1"

PROJECT_SETTINGS = "Metadata/project_settings.config"
MODEL_SETTINGS = "Metadata/model_settings.config"
SLICE_INFO = "Metadata/slice_info.config"
CUSTOM_GCODE = "Metadata/custom_gcode_per_layer.xml"

#: Process settings that name a filament slot (1-based; 0 means "use the object's").
PROCESS_ROLES = ("wall_filament", "sparse_infill_filament", "solid_infill_filament", "support_filament",
                 "support_interface_filament", "wipe_tower_filament")

_ATTR = re.compile(r'([A-Za-z_:][\w.:-]*)\s*=\s*"([^"]*)"')
_FILAMENT = re.compile(r'<filament\b([^>]*)/?>')

_SUBTYPES = ("normal_part", "negative_part", "modifier_part", "support_blocker", "support_enforcer")
IDENTITY_FIELDS = ("settings_id", "colour", "type", "vendor", "filament_id")

#: The object list is read only up to these limits; past either, it is reported as not read (never as "no objects").
MAX_OBJECT_LIST_BYTES = 8 * 1024 * 1024
MAX_OBJECT_LIST_NODES = 200_000


def _text_strict(tm: ThreeMF, part: str) -> str:
    """The part's text, or an error: a part that is absent or cannot be read is NOT an empty one."""
    if not tm.has_part(part):
        raise ValueError(f"{part} is not in the project")
    return tm.read_part(part).decode("utf-8", "ignore")


def _text(tm: ThreeMF, part: str) -> str:
    if not tm.has_part(part):
        return ""
    try:
        return tm.read_part(part).decode("utf-8", "ignore")
    except Exception:
        return ""


def _settings(tm: ThreeMF) -> dict:
    try:
        out = json.loads(_text(tm, PROJECT_SETTINGS) or "{}")
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {}


def _at(cfg: dict, key: str, index: int):
    values = cfg.get(key)
    if isinstance(values, list) and index < len(values):
        value = values[index]
        return None if value in (None, "") else value
    return None


def _declared(cfg: dict, index: int) -> list[str]:
    entries = cfg.get("different_settings_to_system")
    if not isinstance(entries, list) or 1 + index >= len(entries) - 1:
        return []
    return sorted({p.strip() for p in str(entries[1 + index] or "").split(";") if p.strip()})


def _extruder(node) -> int | None:
    """The slot an object or part names for itself. 0 means "inherit", the same as naming none."""
    for meta in node.findall("metadata"):
        if meta.get("key") == "extruder" and str(meta.get("value", "")).isdigit():
            return int(meta.get("value")) or None
    return None


def _id(value) -> str | None:
    """Object and part ids are printed, so only a plain number is: anything else could carry a name."""
    return value if isinstance(value, str) and value.isdigit() and len(value) <= 9 else None


def _override_slots(node) -> dict[str, int]:
    return {m.get("key"): int(m.get("value")) for m in node.findall("metadata")
            if m.get("key") in PROCESS_ROLES and str(m.get("value", "")).isdigit() and int(m.get("value")) > 0}


def _objects(model_settings: str) -> list[dict]:
    """Each object's extruder and each part's extruder + subtype, by id. Names are deliberately not read.

    Parsed as XML, so quoting style and attribute order do not matter. A file that is not well-formed XML
    yields no objects, and :func:`slot_usage` then says so instead of calling slots unreferenced."""
    from lxml import etree

    raw = model_settings.encode("utf-8")
    if not raw.strip():
        raise ValueError("the object list is empty")
    if len(raw) > MAX_OBJECT_LIST_BYTES:
        raise ValueError("the object list is too large to read here")
    root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False))
    out = []
    nodes = 0
    for obj in root.iter("object"):
        nodes += 1 + len(obj)
        if nodes > MAX_OBJECT_LIST_NODES:
            raise ValueError("the object list has too many entries to read here")
        parts = [{"id": _id(p.get("id")), "subtype": p.get("subtype") if p.get("subtype") in _SUBTYPES else None,
                  "extruder": _extruder(p), "overrides": _override_slots(p)} for p in obj.findall("part")]
        out.append({"id": _id(obj.get("id")), "extruder": _extruder(obj), "parts": parts,
                    "overrides": _override_slots(obj)})
    return out


def _sliced_grams(tm: ThreeMF) -> dict[int, float]:
    out: dict[int, float] = {}
    for attrs in _FILAMENT.findall(_text(tm, SLICE_INFO)):
        a = dict(_ATTR.findall(attrs))
        try:
            out[int(a["id"])] = out.get(int(a["id"]), 0.0) + float(a["used_g"])
        except (KeyError, ValueError):
            continue
    return out


def slot_usage(tm: ThreeMF) -> dict:
    """Where each filament slot is referenced in a project. Read-only. Slots are numbered from 1."""
    cfg = _settings(tm)
    count = len(cfg.get("filament_colour") or []) if isinstance(cfg.get("filament_colour"), list) else 0
    slots: dict[int, dict] = {i: {"object_extruder": [], "part_extruder": [], "painted": False, "colour_changes": [],
                                  "process_roles": [], "sliced_g": None} for i in range(1, count + 1)}

    try:
        objects = _objects(_text_strict(tm, MODEL_SETTINGS))
        readable = True
    except Exception:
        objects, readable = [], False
    # An object prints with the first filament for whatever has no extruder of its own: the object itself, or
    # any of its ordinary parts.
    without_extruder = [o["id"] for o in objects if o["extruder"] is None and (
        not o["parts"] or any(p["extruder"] is None and p["subtype"] in (None, "normal_part") for p in o["parts"]))]
    for o in objects:
        if o["extruder"] in slots:
            slots[o["extruder"]]["object_extruder"].append(o["id"])
        for p in o["parts"]:
            if p["extruder"] in slots:
                slots[p["extruder"]]["part_extruder"].append({"object": o["id"], "part": p["id"], "subtype": p["subtype"]})
    # An object with no extruder at all prints with the first filament; say so rather than leave slot 1 looking idle.
    if without_extruder and 1 in slots:
        slots[1]["default_extruder_for"] = without_extruder

    for o in objects:
        for key, value in o["overrides"].items():
            if value in slots:
                slots[value]["process_roles"].append(f"{key} (set on object {o['id']})")
        for part in o["parts"]:
            for key, value in part["overrides"].items():
                if value in slots:
                    slots[value]["process_roles"].append(f"{key} (set on part {part['id']} of object {o['id']})")

    paint = painted_color.read_container(tm)
    painted_slots = set(paint.get("slots_referenced") or [])
    for i in painted_slots:
        if i in slots:
            slots[i]["painted"] = True
    paint_complete = (not paint.get("truncated") and bool(paint.get("default_slot_resolved", True))
                      and not paint.get("malformed_triangle_count") and not paint.get("facets_outside_mesh")
                      ) if paint.get("available") else True      # no painting in the file: nothing was left unread
    complete = paint_complete and readable            # an unreadable object list is not evidence of absence

    for change in color_plan._layer_changes(_text(tm, CUSTOM_GCODE)):
        if change.get("extruder") in slots:
            slots[change["extruder"]]["colour_changes"].append(change.get("z_mm"))

    for key in PROCESS_ROLES:
        raw = cfg.get(key)
        for value in (raw if isinstance(raw, list) else [raw]):
            if str(value or "").isdigit() and int(value) in slots:
                slots[int(value)]["process_roles"].append(key)

    for i, grams in _sliced_grams(tm).items():
        if i in slots:
            slots[i]["sliced_g"] = round(grams, 2)

    for i, s in slots.items():
        kinds = [k for k in ("object_extruder", "part_extruder", "colour_changes", "process_roles") if s[k]]
        if s["painted"]:
            kinds.append("painted")
        if s.get("default_extruder_for"):
            kinds.append("default_extruder")
        if s["sliced_g"]:
            kinds.append("sliced_usage")
        s["referenced_by"] = kinds
        s["verdict"] = "referenced" if kinds else ("no_reference_found" if complete else "unknown")
    return {"slots": slots, "painting": {"present": bool(paint.get("painted_triangle_count")), "complete": paint_complete,
                                         "truncated": bool(paint.get("truncated"))},
            "object_list_readable": readable}


def snapshot(path: str | Path, label: str = "file") -> dict:
    """`label` names the file in the output together with a short digest, never its real name: a 3MF's file name is
    usually the model's name, and this output is meant to be pasted into a support thread."""
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:                                # streamed: the file is not held in memory for its digest
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()[:12]
    tm = ThreeMF.open(path)
    cfg = _settings(tm)
    usage = slot_usage(tm)
    slots = []
    for index in range(len(cfg.get("filament_colour") or [])):
        n = index + 1
        slots.append({
            "slot": n,
            "settings_id": _at(cfg, "filament_settings_id", index), "colour": _at(cfg, "filament_colour", index),
            "type": _at(cfg, "filament_type", index), "vendor": _at(cfg, "filament_vendor", index),
            "filament_id": _at(cfg, "filament_ids", index), "declared": _declared(cfg, index),
            "usage": usage["slots"].get(n),
        })
    return {"file": f"{label} (sha256 {digest}…)", "filament_count": len(slots),
            "default_filament_profile": cfg.get("default_filament_profile"), "slots": slots,
            "painting": usage["painting"], "object_list_readable": usage["object_list_readable"],
            "filament_settings": {k: v for k, v in sorted(cfg.items())
                                  if k.startswith(("filament_", "default_filament")) and k != "filament_notes"}}


def compare(source: str | Path, prepared: str | Path) -> dict:
    a, b = snapshot(source, "source"), snapshot(prepared, "prepared")
    changes = []
    for n in range(1, max(a["filament_count"], b["filament_count"]) + 1):
        sa = next((s for s in a["slots"] if s["slot"] == n), None)
        sb = next((s for s in b["slots"] if s["slot"] == n), None)
        if sa is None or sb is None:
            changes.append({"slot": n, "change": "added" if sa is None else "removed"})
            continue
        for field in (*IDENTITY_FIELDS, "declared"):
            if sa[field] != sb[field]:
                changes.append({"slot": n, "field": field, "source": sa[field], "prepared": sb[field]})
    keys = sorted(set(a["filament_settings"]) | set(b["filament_settings"]))
    differing = [k for k in keys if a["filament_settings"].get(k) != b["filament_settings"].get(k)]
    usage_moved = [{"slot": sa["slot"], "source": sa["usage"]["referenced_by"], "prepared": sb["usage"]["referenced_by"]}
                   for sa, sb in zip(a["slots"], b["slots"])
                   if sa["usage"] and sb["usage"] and sa["usage"]["referenced_by"] != sb["usage"]["referenced_by"]]
    return {"schema": SCHEMA, "source": a, "prepared": b,
            "slot_changes": changes, "differing_filament_settings": differing,
            "usage_changed": usage_moved,
            "not_read": ["per-layer-range modifiers"],
            "note": "Read-only. 'no_reference_found' means no place Studio reads names the slot; it is not proof the "
                    "slot is unused."}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) not in (1, 2):
        print("usage: python -m snapstudio_core.project_compare SOURCE.3mf [PREPARED.3mf]", file=sys.stderr)
        return 2
    result = snapshot(args[0], "source") if len(args) == 1 else compare(args[0], args[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
