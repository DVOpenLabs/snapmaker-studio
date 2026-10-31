"""Policy and accounting for preserving creator-owned slicer settings."""
from __future__ import annotations

import copy
import json
import re
from importlib.resources import files


def load_policy() -> dict:
    return json.loads((files("snapstudio_core.data") / "u1_preserve_keys.json")
                      .read_text("utf-8"))


POLICY = load_policy()
CATEGORY_A = frozenset(POLICY["category_a"])
PER_EXTRUDER_VECTORS = frozenset(POLICY["per_extruder_vectors"])
VALID_BED_TYPES = frozenset(POLICY["valid_bed_types"])


def load_scopes() -> dict:
    return json.loads((files("snapstudio_core.data") / "u1_setting_scopes.json").read_text("utf-8"))


SCOPES = load_scopes()
LOGICAL_FILAMENT = frozenset(SCOPES["logical_filament"])     # one entry per project filament
PHYSICAL_HEAD = frozenset(SCOPES["physical_head"])           # one entry per physical extruder


def machine_compat_keys(profile: dict) -> set[str]:
    """The profile-owned (category B) keys; category A is deliberately absent."""
    return set(profile["keys"]) - CATEGORY_A


def assess_setup(topology) -> dict:
    """Judge a supplied printer setup. Three different answers, never merged:

    absent   -> {"state": "absent"}                       (the caller supplied none: stock behaviour)
    invalid  -> {"state": "invalid", "reasons": [...]}    (supplied but unusable: the caller must not convert)
    valid    -> {"state": "valid", "heads": H, "slots": S, "bound": [...], "unbound": [...]}

    Valid means: complete head list, no error diagnostic (no dangling or contradictory binding, no
    reference to an unknown head, no mixed index base), slots numbered 0..n-1. Unbound slots are
    reported and stay unresolved; nothing here assigns a head to them."""
    if topology is None:
        return {"state": "absent"}
    try:
        from .foundation.topology import Topology, validate
        if isinstance(topology, dict):
            decoded = topology_from_dict(topology)
            if decoded is None:
                return _invalid("the printer setup could not be read")
            topology = decoded
        if not isinstance(topology, Topology):
            return _invalid("the printer setup has an unexpected form")
        errors = [d for d in list(topology.diagnostics) + validate(topology) if d.severity == "error"]
        if errors:
            return _invalid("the printer setup contradicts itself (" + ", ".join(sorted({d.code for d in errors})) + ")")
        if not topology.complete or not topology.heads:
            return _invalid("the printer setup does not list every physical head")
        if len(topology.heads) != _u1_heads():
            return _invalid(f"the printer setup has {len(topology.heads)} physical heads but a U1 has {_u1_heads()}; "
                            "preparing a U1 copy for another printer is not supported")
        indexes = sorted(slot.index for slot in topology.slots)
        if not indexes or indexes != list(range(len(indexes))):
            return _invalid("the printer setup's material slots are missing or not numbered from zero without gaps")
        targets = {b.slot_id for b in topology.bindings if b.target is not None}
        targets |= {sl.id for sl in topology.slots if sl.binding is not None}
        slot_ids = [sl.id for sl in sorted(topology.slots, key=lambda x: x.index)]
        return {"state": "valid", "heads": len(topology.heads), "slots": len(indexes),
                "bound": [i for i in slot_ids if i in targets], "unbound": [i for i in slot_ids if i not in targets]}
    except Exception:          # a malformed hand-built object must be refused, not crash the conversion
        return _invalid("the printer setup could not be checked")


def _u1_heads() -> int:
    from .profile import load_profile
    return len(load_profile("snapmaker_u1")["keys"]["nozzle_diameter"])


def _invalid(reason: str) -> dict:
    return {"state": "invalid", "reasons": [reason]}


def accepted_logical_slots(topology) -> tuple[int | None, str | None]:
    """Compatibility view of assess_setup: (slot count, None) when valid, else (None, reason or None)."""
    verdict = assess_setup(topology)
    if verdict["state"] == "valid":
        return verdict["slots"], None
    if verdict["state"] == "invalid":
        return None, verdict["reasons"][0]
    return None, None


def topology_from_dict(raw: dict):
    from .foundation.topology import Topology
    decoded = Topology.from_dict(raw)
    if decoded.value is None or any(d.severity == "error" for d in decoded.diagnostics):
        return None
    return decoded.value


def prepare_preserved_values(cfg: dict, filament_total: int, *, physical_heads=None) -> tuple[list[dict], list[str]]:
    """Apply the few U1 representation constraints without replacing values.

    With no validated setup (`physical_heads` is None) every per-extruder vector is mapped to the four
    U1 toolheads, as before. With one, each vector is addressed by its own scope (data/u1_setting_scopes.json):
    a physical-head vector has one entry per physical head, a logical-filament vector one entry per project
    filament. The scope comes from the setting, never from a vector happening to have the same length."""
    changes: list[dict] = []
    warnings: list[str] = []
    for key in ("curr_bed_type", "default_bed_type"):
        value = cfg.get(key)
        if value is not None and value not in VALID_BED_TYPES:
            cfg[key] = "Textured PEI Plate"
            changes.append({"key": key, "old": value, "new": cfg[key],
                            "reason": "mapped to a supported U1 plate"})

    for key in PER_EXTRUDER_VECTORS:
        if key not in cfg:
            continue
        old = copy.deepcopy(cfg[key])
        values = old if isinstance(old, list) else [old]
        if not values:
            continue
        if isinstance(physical_heads, int) and not isinstance(physical_heads, bool) and physical_heads > 0 \
                and key in (PHYSICAL_HEAD | LOGICAL_FILAMENT):
            scope = "physical head" if key in PHYSICAL_HEAD else "project filament"
            target = physical_heads if key in PHYSICAL_HEAD else max(1, filament_total)
            if len(values) == target:
                continue
            new = values[:target] if len(values) > target else values + [values[-1]] * (target - len(values))
            warnings.append(f"{key} is a per-{scope} setting with {len(values)} entries; "
                            f"the printer setup needs {target}, so it was resized to {target}.")
            cfg[key] = new
            changes.append({"key": key, "old": old, "new": new,
                            "reason": f"resized to {target} entries (one per {scope})", "category": "mapped"})
            continue
        if len(values) == 4:
            continue
        if len(values) < 4:
            new = values + [values[-1]] * (4 - len(values))
            if len(values) != filament_total:
                warnings.append(
                    f"Source tool mapping for {key} had {len(values)} slots; "
                    "mapped to four U1 toolheads.")
        else:
            new = values[:4]
            if len(values) != filament_total:
                warnings.append(
                    f"Source tool mapping for {key} had {len(values)} slots; "
                    "mapped to four U1 toolheads.")
        cfg[key] = new
        changes.append({"key": key, "old": old, "new": new,
                        "reason": "resized to 4 toolheads (values preserved)",
                        "category": "mapped"})

    key = "wipe_tower_filament"
    if key in cfg:
        old = cfg[key]
        try:
            index = int(old)
        except (TypeError, ValueError):
            index = -1
        if not (0 <= index < max(1, filament_total)):
            cfg[key] = "0" if isinstance(old, str) else 0
            changes.append({"key": key, "old": old, "new": cfg[key],
                            "reason": "mapped to an available filament"})
    return changes, warnings


def config_diff(before: dict, after: dict) -> list[dict]:
    """Independent whole-config diff used for the preservation invariant."""
    missing = object()
    result = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key, missing), after.get(key, missing)
        if old != new:
            result.append({"key": key,
                           "old": None if old is missing else old,
                           "new": None if new is missing else new,
                           "removed": new is missing})
    return result


_SENSITIVE_SUMMARY_KEY = re.compile(
    r"printhost|api_key|password|token|serial|access_code|auth", re.IGNORECASE)


def display_value(value, limit: int = 120, *, key: str = ""):
    """Return a safe, compact value for a user-facing conversion summary.

    Project settings can contain printer credentials and arbitrary G-code (which
    commonly embeds usernames, host paths, and tokens).  Neither belongs in an
    API response or UI summary, even when it would fit the normal truncation.
    """
    if _SENSITIVE_SUMMARY_KEY.search(key):
        return "[redacted]"
    if "gcode" in key.lower():
        chars = len(value) if isinstance(value, str) else len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        return f"machine G-code replaced with U1 machine G-code ({chars} chars)"
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > limit:
        return encoded[:limit - 1] + "…"
    return copy.deepcopy(value)
