"""Dict-level, network-free Moonraker helpers shared by the stock and paxx adapters.

These re-implement, as pure functions over already-fetched JSON, what the legacy
`moonraker.loaded_filaments / capabilities / machine_info / extended_firmware` do after
their network calls. Nothing here (or anywhere in `adapters/`) opens a connection: the host
layer in `reader.py` fetches through `netguard.local_request` and hands the payload over.

Moonraker wraps replies as `{"result": ...}`; `result_of` accepts both the wrapped and the
bare form so fixtures can be either.
"""
from __future__ import annotations

import re
from typing import Any

from ...foundation.decode import content_hash, is_finite_number

#: Bundle schema these adapters read (Studio's own envelope around pre-fetched replies).
BUNDLE_VERSION = "host_bundle/1"
#: Upper bound on logical entries read from one printer; a larger payload is refused, not truncated.
MAX_SLOTS = 256

_HEAD_OBJECT = re.compile(r"^extruder([1-9]\d*)?$")


def result_of(reply: Any) -> dict:
    """The `result` mapping of a Moonraker reply (or the reply itself when unwrapped); {} otherwise."""
    if not isinstance(reply, dict):
        return {}
    inner = reply.get("result")
    if isinstance(inner, dict):
        return inner
    return reply


def status_of(reply: Any) -> dict:
    """`/printer/objects/query` status mapping."""
    inner = result_of(reply).get("status")
    return inner if isinstance(inner, dict) else {}


def print_task_config(reply: Any) -> dict | None:
    cfg = status_of(reply).get("print_task_config")
    if cfg is None:
        cfg = result_of(reply).get("print_task_config")
    return cfg if isinstance(cfg, dict) and cfg else None


def toolhead_indices(objects_reply: Any) -> list | None:
    """Sorted head indices from `/printer/objects/list` names (`extruder`, `extruder1`, ...).

    None when the reply has no object list at all (unknown); [] when it lists no toolhead.
    """
    objects = result_of(objects_reply).get("objects")
    if not isinstance(objects, list):
        return None
    found = set()
    for name in objects:
        if isinstance(name, str):
            m = _HEAD_OBJECT.match(name)
            if m:
                found.add(int(m.group(1)) if m.group(1) else 0)
    return sorted(found)


def contiguous_from_zero(indices: list) -> bool:
    return bool(indices) and indices == list(range(len(indices)))


def machine_info_from(system_info_reply: Any) -> dict:
    """Only `product_info.nozzle_diameter` and `sd_info.total_bytes`; nothing else is read.

    Device name, serial numbers, MAC and IP addresses are never touched.
    """
    info = result_of(system_info_reply).get("system_info")
    info = info if isinstance(info, dict) else {}
    product = info.get("product_info")
    product = product if isinstance(product, dict) else {}
    sd = info.get("sd_info")
    sd = sd if isinstance(sd, dict) else {}
    diameters = product.get("nozzle_diameter")
    if (not isinstance(diameters, list) or not diameters
            or not all(positive_number(d) for d in diameters)):
        diameters = None
    storage = sd.get("total_bytes")
    return {"nozzle_diameters": diameters, "storage_bytes": storage if positive_number(storage) else None}


def positive_number(value: Any) -> bool:
    return is_finite_number(value) and value > 0


def hex_colour(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        # The whole value must be RRGGBB or RRGGBBAA (filament_color_rgba is eight characters in
        # u1_print_task_config.py); a longer string with a valid prefix is not a colour.
        text = value.strip().lstrip("#").upper()
        if re.fullmatch(r"[0-9A-F]{6}(?:[0-9A-F]{2})?", text):
            return "#" + text[:6]
    return None


def column(cfg: dict, *names: str) -> list | None:
    for name in names:
        value = cfg.get(name)
        if isinstance(value, list) and value:
            return value
    return None


def at(seq: Any, i: int) -> Any:
    return seq[i] if isinstance(seq, list) and i < len(seq) else None


def loaded_filaments_from(cfg: dict) -> list:
    """Per logical entry: `{"present": True|False|None, "material", "colour", "vendor"}`.

    `filament_exist is False` is an empty entry (no material, no colour). An entry the
    printer did not describe at all stays `present: None` (unknown), never "empty".
    """
    types = column(cfg, "filament_type")
    # Colour source is `filament_color_rgba` only: an 8-hex string, RRGGBB then AA
    # (u1-klipper print_task_config.py blob 340b4232, lines 236-237 and 331). The integer
    # `filament_color` (named ARGB_COLOR upstream, line 336; layout (alpha<<24)|RGB, lines 661-692)
    # is deliberately NOT converted: Studio keeps one colour source, so a colour known only from
    # the integer stays UNKNOWN.
    colours = column(cfg, "filament_color_rgba")
    subtypes = column(cfg, "filament_sub_type")
    vendors = column(cfg, "filament_vendor")
    present = column(cfg, "filament_exist")
    count = max((len(c) for c in (types, colours, subtypes, vendors, present) if c), default=0)
    out = []
    for i in range(count):
        flag = at(present, i)
        exists = flag if isinstance(flag, bool) else None
        if exists is False:
            out.append({"present": False, "material": None, "colour": None, "vendor": None})
            continue
        material = at(types, i)
        sub = at(subtypes, i)
        # Upstream writes the string "NONE" for a vendor, type or sub-type that was never set
        # (print_task_config.py lines 26-28 and 862); that is not data.
        def text(value):
            return value.strip() if isinstance(value, str) and value.strip() not in ("", "NONE") else None
        material, sub, vendor = text(material), text(sub), text(at(vendors, i))
        out.append({"present": exists,
                    "material": f"{material} {sub}" if (material and sub) else material,
                    "colour": hex_colour(at(colours, i)),
                    "vendor": vendor})
    return out


def extruder_map(cfg: dict, status: dict) -> list | None:
    """The `extruder_map_table` list (logical entry -> physical extruder index) when present."""
    for source in (cfg, status):
        value = source.get("extruder_map_table") if isinstance(source, dict) else None
        if isinstance(value, list):
            return value
    return None


def extended_firmware_from(page: bytes | None, control: bytes | None, phrase: str) -> dict:
    """Positive detection only, from two already-fetched pages (marker page and control page).

    A server that answers every path with the same page proves nothing; identical bytes are
    not a marker. The result is detected or unknown, never "this printer is stock".
    """
    if not page or (control is not None and control == page):
        return {"detected": False, "known": False}
    if phrase.encode("utf-8") not in page.lower():
        return {"detected": False, "known": False}
    return {"detected": True, "known": True}


def snapshot_id_of(data: Any) -> str:
    """Stable id of one bundle. Payloads that cannot be canonicalised (NaN, odd types) hash their repr."""
    try:
        digest = content_hash(data)
    except (ValueError, TypeError, OverflowError):
        digest = content_hash(repr(data))
    return "snap:" + digest[7:23]
