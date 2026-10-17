"""Whether the source expresses explicit support intent, which Recommended must not silently discard.

Recommended is the "U1 starter settings" mode: speed, temperature, retraction, supports and cooling are the
starter's, and the support policy of a creator's print profile is rightly reset. The one exception is a
model's own, positive statement of where it needs support. The rule, in order of precedence (the first that
applies decides):

1. **Explicit disable wins.** ``enable_support`` = 0 in the project's settings, or ``enable_support`` = 0 on any
   object, means supports are off and stay off. The model's painting or enforcers are then disclosed as
   unused; nothing is declared.
2. **Positive intent is kept.** Painted support *enforcers* (``paint_supports`` facets whose paint has the
   enforcer state), ``support_enforcer`` volumes, or ``enable_support`` = 1 on an object. The creator's
   ``enable_support`` / ``support_type`` / ``support_filament`` / ``support_interface_filament`` are declared
   as the project's own and kept.
3. **Otherwise the starter reset stands** (this is what the mode says it does): no support data at all, or
   blocker-only data. Blockers (``support_blocker`` volumes, blocker paint) say where NOT to support, which
   is not a request for supports, so they never keep anything.
4. Whatever is not decided above takes the creator's value (Preserve mode never reaches this module).

Paint states are the codec's: leaf state 1 is "enforcer", 2 is "blocker" (Orca's ``EnforcerBlockerType``).
"""
from __future__ import annotations

import re

from .container import ThreeMF

SUPPORT_KEYS = ("enable_support", "support_type", "support_filament", "support_interface_filament")

ENFORCER_STATE = 1
BLOCKER_STATE = 2

_PAINT = re.compile(rb'paint_supports="([^"]+)"')
_OBJECT_ENABLE = re.compile(r'<metadata\s+key="enable_support"\s+value="([^"]*)"', re.I)
MODEL_SETTINGS = "Metadata/model_settings.config"
#: A defensive bound on how many distinct paint strings are decoded.
_MAX_DISTINCT_PAINT = 20000

KEPT = "kept"
DISABLED = "disabled"
STARTER_RESET = "starter_reset"


def _off(value) -> bool:
    return str(value).strip().lower() in ("0", "false", "off", "no")


def _on(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "on", "yes")


def _paint_states(tm: ThreeMF) -> set[int]:
    from . import paint_codec

    states: set[int] = set()
    seen: set[bytes] = set()
    for part in tm.list_parts():
        if not part.endswith(".model"):
            continue
        for match in _PAINT.finditer(tm.read_part(part)):
            attribute = match.group(1)
            if attribute in seen or len(seen) >= _MAX_DISTINCT_PAINT:
                continue
            seen.add(attribute)
            try:
                states |= set(paint_codec.states(attribute.decode("ascii", "ignore")))
            except Exception:  # noqa: BLE001 - paint Studio cannot decode is not evidence of intent
                continue
            if ENFORCER_STATE in states and BLOCKER_STATE in states:
                return states
    return states


def detect(tm: ThreeMF, source_cfg: dict) -> dict:
    """The decision (``kept`` / ``disabled`` / ``starter_reset``) and the evidence for it."""
    from . import roles
    from .assignments import SUPPORT_BLOCKER, SUPPORT_ENFORCER, role_of

    positive: list[str] = []
    blockers: list[str] = []
    disabled: list[str] = []

    try:
        states = _paint_states(tm)
        if ENFORCER_STATE in states:
            positive.append("painted support enforcers")
        if BLOCKER_STATE in states:
            blockers.append("painted support blockers")
    except Exception:  # noqa: BLE001
        pass
    try:
        if tm.has_part(MODEL_SETTINGS):
            text = tm.read_part(MODEL_SETTINGS).decode("utf-8", "ignore")
            subtypes = [role_of(sub) for subs in roles.read_records(text).part_subtypes.values()
                        for sub in subs.values()]
            if SUPPORT_ENFORCER in subtypes:
                positive.append("support-enforcer volumes")
            if SUPPORT_BLOCKER in subtypes:
                blockers.append("support-blocker volumes")
            values = _OBJECT_ENABLE.findall(text)
            if any(_on(v) for v in values):
                positive.append("support switched on for an individual object")
            if any(_off(v) for v in values):
                disabled.append("support switched off for an individual object (enable_support = 0)")
    except Exception:  # noqa: BLE001
        pass
    if "enable_support" in (source_cfg or {}) and _off(source_cfg["enable_support"]):
        disabled.append("support switched off in the project's settings (enable_support = 0)")

    keys = [k for k in SUPPORT_KEYS if k in (source_cfg or {})]
    if disabled:
        decision = DISABLED
    elif positive and keys:
        decision = KEPT
    else:
        decision = STARTER_RESET
    return {"decision": decision, "explicit": decision == KEPT, "evidence": positive,
            "blocker_evidence": blockers, "disable_evidence": disabled, "keys": keys}


def statement(intent: dict) -> str:
    """One plain sentence for the summary."""
    decision = intent["decision"]
    if decision == KEPT:
        return ("This model marks where it needs support (" + ", ".join(intent["evidence"]) + "), so its "
                "support settings (" + ", ".join(intent["keys"]) + ") were kept as the creator set them "
                "rather than reset to the U1 starter's.")
    if decision == DISABLED:
        extra = (f" The model also has {', '.join(intent['evidence'])}, which are not used while supports "
                 "are off." if intent["evidence"] else "")
        return ("Supports stay off: " + "; ".join(intent["disable_evidence"]) + "." + extra)
    if intent["blocker_evidence"]:
        return ("Supports use the U1 starter settings. The model's " + ", ".join(intent["blocker_evidence"])
                + " only say where not to support, so they do not turn supports on.")
    return "Supports use the U1 starter settings, as this mode states."
