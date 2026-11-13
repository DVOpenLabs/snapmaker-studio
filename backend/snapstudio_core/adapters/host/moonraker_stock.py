"""Stock Moonraker host (Snapmaker U1 stock firmware and plain Klipper/Moonraker stacks).

Reads `print_task_config` (parallel arrays, one entry per LOGICAL filament entry) and
`/printer/objects/list` (toolhead objects = physical heads). Stock names no spool identity,
so spool facts are never emitted. Evidence label: fixture-tested (documentation-derived).
"""
from __future__ import annotations

from ..base import AdapterInfo
from .moonraker_base import MoonrakerBundleAdapter
from .moonraker_parse import BUNDLE_VERSION


class MoonrakerStockAdapter(MoonrakerBundleAdapter):
    info = AdapterInfo(id="host.moonraker_stock", kind="host",
                       versions_supported=(BUNDLE_VERSION,), ttl_s=30.0)


INSTANCE = MoonrakerStockAdapter()
