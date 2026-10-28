"""Moonraker host running the Paxx extended firmware.

Same as stock, plus a per-entry `filament_spool_id` array inside `print_task_config`. When
that array is missing, or an entry is not a usable id, the spool identity of that entry is
UNKNOWN: no spool fact is emitted and nothing is cleared or invented. A usable id becomes a
`SpoolRef` owned by this adapter's provider instance id (it is a provider id, not a Spoolman
or SpoolEase id, unless a declared `SpoolAlias` says so).
"""
from __future__ import annotations

from ...foundation import topology as topo
from ...foundation.decode import WARNING, diag
from ...foundation.materials import MaterialFact, SpoolRef
from ..base import AdapterInfo
from .moonraker_base import MoonrakerBundleAdapter, _Ctx
from .moonraker_parse import BUNDLE_VERSION, at


def _usable_spool_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    if isinstance(value, str) and value.strip() and len(value.strip()) <= 64:
        return value.strip()
    return None


class MoonrakerPaxxAdapter(MoonrakerBundleAdapter):
    info = AdapterInfo(id="host.moonraker_paxx", kind="host",
                       versions_supported=(BUNDLE_VERSION,), ttl_s=30.0)

    def _spool_pass(self, cfg: dict, count: int, ctx: _Ctx) -> None:
        result = ctx.result
        column = cfg.get("filament_spool_id")
        if not isinstance(column, list):
            # Missing is not "no spool": identity stays unknown.
            if count:
                result.unknowns.append("spool")
                result.diagnostics.append(diag("spool_id_missing", "filament_spool_id", WARNING))
            return
        unknown = False
        for i in range(count):
            spool = _usable_spool_id(at(column, i))
            if spool is None:
                unknown = True
                result.diagnostics.append(diag("spool_id_unusable", f"filament_spool_id[{i}]", WARNING))
                continue
            if not ctx.head_known(i):
                unknown = True
                continue
            ref = SpoolRef(self.info.id, spool)
            # filament_spool_id is a per-physical-extruder column like the other filament arrays.
            obs = ctx.observe({"kind": "head", "id": topo.head_id(i)}, "spool", ref.to_dict())
            result.material_facts.append(MaterialFact("spool", ref, "provider", obs.observation_id))
        if unknown:
            result.unknowns.append("spool")


INSTANCE = MoonrakerPaxxAdapter()
