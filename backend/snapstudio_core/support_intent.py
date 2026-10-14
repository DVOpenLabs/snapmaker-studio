"""Whether the source expresses explicit support intent, which Recommended must not silently discard.

Recommended is the "U1 starter settings" mode: speed, temperature, retraction, supports and cooling are the
starter's, and the support policy of a creator's print profile is rightly reset. Two things are not policy
but the model's own statement of where it needs support:

* painted supports (``paint_supports`` facets) and support-enforcer volumes, which mark the places;
* a per-object ``enable_support`` switched on.

If the support settings were reset while those remain, Snapmaker Orca would warn that enforcers exist and
support is off, and the model would print without the supports it was marked for. In those cases (only) the
creator's ``enable_support`` / ``support_type`` / ``support_filament`` / ``support_interface_filament`` are
declared as the project's own and kept; every other support setting still takes the starter's value.
"""
from __future__ import annotations

import re

from .container import ThreeMF

SUPPORT_KEYS = ("enable_support", "support_type", "support_filament", "support_interface_filament")

_PAINT = re.compile(rb'paint_supports="[^"]+"')
_OBJECT_ENABLE = re.compile(r'key="enable_support"\s+value="(?:1|true)"', re.I)
MODEL_SETTINGS = "Metadata/model_settings.config"


def detect(tm: ThreeMF, source_cfg: dict) -> dict:
    """``{"explicit": bool, "evidence": [...], "keys": [the support keys the source states]}``."""
    from . import roles
    from .assignments import SUPPORT_ENFORCER, role_of

    evidence: list[str] = []
    try:
        if any(_PAINT.search(tm.read_part(p)) for p in tm.list_parts() if p.endswith(".model")):
            evidence.append("painted supports (support facets painted on the model)")
    except Exception:  # noqa: BLE001
        pass
    try:
        if tm.has_part(MODEL_SETTINGS):
            text = tm.read_part(MODEL_SETTINGS).decode("utf-8", "ignore")
            records = roles.read_records(text)
            if any(role_of(sub) == SUPPORT_ENFORCER
                   for subs in records.part_subtypes.values() for sub in subs.values()):
                evidence.append("support-enforcer volumes")
            if _OBJECT_ENABLE.search(text):
                evidence.append("support switched on for an individual object")
    except Exception:  # noqa: BLE001
        pass
    keys = [k for k in SUPPORT_KEYS if k in (source_cfg or {})]
    return {"explicit": bool(evidence) and bool(keys), "evidence": evidence, "keys": keys}
