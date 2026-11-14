"""Firmware Capability Intelligence — read what THIS printer's firmware can do.

A Klipper machine's loaded object list is a truthful manifest of real features:
mesh levelling, input shaping, eddy-current probing, runout sensing, object
exclusion, pause/resume, multi-toolhead, and any custom macros the owner (or
extended/community firmware) has added. This turns that raw list into a
plain-language capability set, and flags when the firmware looks extended beyond
stock.

Nothing in here is particular to one manufacturer. Every feature is concluded from
a Klipper object being present, which is the same evidence on any printer running
Klipper behind Moonraker — the Snapmaker U1 that Studio was built against, and a
VORON, and anything else on that stack.

Read-only and honest: it reports only what the object list proves is present, and
never claims a capability it can't see.
"""
from __future__ import annotations

SCHEMA_VERSION = "firmwarecaps/1"

# A stock printer exposes a handful of gcode_macros — the U1 does, and so does the
# base VORON configuration, which declares five. Well beyond that means
# somebody has added their own — which may be a community firmware build, and may
# equally be the owner, who is entitled to write macros on their own printer.
# Counting them is a fact; concluding "extended firmware" from the count was not,
# and the badge that said so was shown to people running stock.
_MANY_MACROS = 15


def _prefix(obj: str) -> str:
    """Klipper objects are 'kind' or 'kind name' — return the kind."""
    return obj.split(" ", 1)[0].strip().lower()


def interpret(objects, toolhead_count=None, bed_mm=None, extended_probe=None,
              printer_name: str | None = None, topology=None) -> dict:
    """Map a klipper object list to a plain-language capability set.

    objects: the GET /printer/objects/list result (a list of strings).
    toolhead_count, bed_mm: already-derived values from capabilities(), if known.
    printer_name: what to call this machine in the summary. Every capability below
        is read from the object list and holds on any Klipper printer; only the
        name of the machine in the sentence is specific to one, and when Studio
        has not identified the printer it says "this printer" rather than naming
        a model it has no evidence for.
    """
    objs = [str(o) for o in (objects or [])]
    if not objs:
        return {"schema_version": SCHEMA_VERSION, "available": False,
                "reason": "no firmware object list available from this printer"}

    kinds = [_prefix(o) for o in objs]
    kindset = set(kinds)
    has = lambda *names: any(k in kindset for k in names)
    has_prefix = lambda p: any(k.startswith(p) for k in kinds)

    features: list[dict] = []

    if has("bed_mesh"):
        features.append({"name": "Automatic bed mesh levelling",
                         "detail": "compensates for an uneven bed across the whole plate"})
    if has_prefix("probe_eddy_current") or has("eddy", "probe_eddy_current"):
        features.append({"name": "Eddy-current bed probing",
                         "detail": "a contactless eddy-current probe — fast auto-levelling"})
    elif has("probe", "bltouch"):
        features.append({"name": "Auto bed probing", "detail": "automatic Z/level probing"})
    if has("input_shaper"):
        features.append({"name": "Input shaping",
                         "detail": "resonance compensation for cleaner walls at speed"})
    if has("exclude_object"):
        features.append({"name": "Object exclusion",
                         "detail": "cancel one failed object mid-print without losing the rest"})
    if has("pause_resume"):
        features.append({"name": "Pause / resume", "detail": "safely pause and continue a print"})

    runout = [k for k in kinds if k in ("filament_switch_sensor", "filament_motion_sensor")]
    if runout:
        features.append({"name": "Filament runout detection",
                         "detail": "stops the print if filament runs out or jams"})

    macro_count = sum(1 for k in kinds if k == "gcode_macro")
    if macro_count:
        features.append({"name": "Custom macros",
                         "detail": f"{macro_count} gcode macro{'s' if macro_count != 1 else ''} on this printer"})

    topology_counts = None
    topology_kinds = []
    topology_contradicts = False
    if isinstance(topology, dict):
        from .foundation.topology import Topology, counts, validate
        decoded = Topology.from_dict(topology)
        if decoded.value is not None:
            topology_counts = counts(decoded.value)
            if any(d.severity == "error" for d in validate(decoded.value)):
                # A self-contradicting topology gives no head count.
                topology_counts = {**topology_counts, "complete": False, "physical_heads": None}
                topology_contradicts = True
            topology_kinds = sorted({unit.kind for unit in decoded.value.units})

    tc = toolhead_count or sum(1 for k in kinds if k == "extruder" or
                               (k.startswith("extruder") and k[8:].isdigit()))
    if topology_counts is not None and topology_counts["complete"]:
        heads = topology_counts["physical_heads"]
        lane_count = topology_counts["lanes"]
        if heads is not None and (heads > 1 or lane_count > 1):
            if lane_count:
                detail = (f"{heads} physical toolheads; {lane_count} feeder lanes reported by "
                          f"{', '.join(topology_kinds) or 'reported feeder units'}")
            else:
                detail = f"{heads} physical toolheads; no feeder lanes reported"
            features.append({"name": f"{heads}-toolhead multimaterial", "detail": detail})
        tc = heads
    elif topology_counts is not None:
        tc = None
        features.append({"name": "Multimaterial topology (head count unknown)",
                         "detail": ("physical toolhead count is unknown because the reported topology contradicts itself"
                                    if topology_contradicts else
                                    "physical toolhead count is unknown because the topology head list is incomplete")})
    elif tc and tc > 1:
        features.append({"name": f"{tc}-toolhead multimaterial",
                         "detail": f"prints up to {tc} colours/materials in one job"})

    # Positive detection only. A community firmware announces itself — its own web
    # interface answers on a path stock firmware does not have — and that is the
    # only thing worth calling detection. Nothing here ever concludes "stock" from
    # the absence of a marker: not finding something is not finding it.
    probe = extended_probe or {}
    extended = bool(probe.get("detected"))
    many_macros = macro_count >= _MANY_MACROS

    bed_txt = (f"{bed_mm['x']}×{bed_mm['y']}×{bed_mm['z']} mm bed"
               if isinstance(bed_mm, dict) and bed_mm.get("x") else None)
    head_txt = f"{tc} toolhead{'s' if (tc or 0) != 1 else ''}" if tc else None
    bits = [b for b in (head_txt, bed_txt) if b]
    who = printer_name or "This printer"
    summary = (f"{who} reports " + ", ".join(bits) + "; " if bits else f"{who} reports ") + \
              f"{len(features)} capabilit{'ies' if len(features) != 1 else 'y'} detected" + \
              (" (community firmware answered on this printer)." if extended
               else f" ({macro_count} custom macros on it)." if many_macros else ".")

    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "toolhead_count": tc or None,
        "bed_mm": bed_mm,
        "macro_count": macro_count,
        "many_custom_macros": many_macros,
        "extended_firmware": extended,
        "extended_firmware_evidence": probe.get("evidence"),
        "features": features,
        "summary": summary,
    }
