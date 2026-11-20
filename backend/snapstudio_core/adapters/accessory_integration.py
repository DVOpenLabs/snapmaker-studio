"""Explicit accessory input integration. No discovery probes or device-control requests."""
from __future__ import annotations
import copy
import json

from . import accessory  # noqa: F401
from . import registry
from ..foundation.topology import LogicalSlot, SlotBinding, slot_id

LIVE_PATHS = {'multiace': '/multiace/api/preflight/livedata', 'afc': '/printer/afc/status'}
VERSIONS = {'multiace': '1', 'afc': '1', 'bmcu': '1', 'sidecar': 'beta-preview'}
MAX_PAYLOAD_BYTES = 256 * 1024


def specification(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('adapter_id'), str) or raw.get('adapter_id') not in VERSIONS:
        raise ValueError('Choose a supported accessory adapter.')
    name = raw['adapter_id']
    if raw.get('source_version') != VERSIONS[name]:
        raise ValueError('Choose the supported accessory contract version explicitly.')
    mode = raw.get('mode')
    if mode not in ('live', 'snapshot') or (mode == 'live' and name not in LIVE_PATHS):
        raise ValueError('This adapter requires an imported published-contract snapshot.')
    if mode == 'snapshot':
        payload = raw.get('payload')
        if not isinstance(payload, dict):
            raise ValueError('Accessory snapshot must be a JSON object.')
        try:
            encoded = json.dumps(payload, allow_nan=False).encode('utf-8')
        except (ValueError, TypeError, RecursionError):
            raise ValueError('Accessory snapshot is not finite JSON.') from None
        if len(encoded) > MAX_PAYLOAD_BYTES:
            raise ValueError('Accessory snapshot is too large.')
    mapping = raw.get('slot_map')
    if mapping is not None and (not isinstance(mapping, list) or not 1 <= len(mapping) <= 64
                                or not all(isinstance(x, str) and len(x) <= 160 for x in mapping)):
        raise ValueError('Slot mapping must contain 1 to 64 explicit lane IDs in T0 order.')
    return name, mode, mapping


def compose(parsed, host, mapping=None, *, historical=False):
    """Use physical inventory from a separately read host only when evidence agrees.

    Never enumerate slots from lane count. An optional list is the user's explicit
    T0..Tn binding declaration, not an upstream report. Imported observations remain
    historical, even when a host was read in this request.
    """
    result = copy.deepcopy(parsed)
    if not result.ok or result.topology is None:
        if mapping is not None:
            raise ValueError("A logical map cannot be applied without a readable accessory topology.")
        return result
    t = result.topology
    if host is not None and host.ok and host.topology is not None and host.topology.complete:
        physical = host.topology
        heads = {h.id: h for h in physical.heads}
        if t.complete and set(h.id for h in t.heads) != set(heads):
            raise ValueError('Accessory and printer host disagree about physical heads.')
        for h in t.heads:
            if h.id not in heads or (h.nozzle_mm is not None and heads[h.id].nozzle_mm is not None
                                    and h.nozzle_mm != heads[h.id].nozzle_mm):
                raise ValueError('Accessory and printer host disagree about physical heads or nozzles.')
        t.heads = copy.deepcopy(physical.heads)
        t.complete = True
        t.evidence.append('physical-heads-from-separately-read-host')
    heads = {h.id for h in t.heads}
    lanes = {lane.id: lane for unit in t.units for lane in unit.lanes}
    if any(lane.reachable_heads is not None and any(h not in heads for h in lane.reachable_heads)
           for lane in lanes.values()):
        raise ValueError('Accessory references a physical head that was not observed.')
    if mapping is not None:
        if t.slots or t.bindings:
            raise ValueError('The accessory already reports a logical slot mapping. Remove the declared slot map; device-reported mappings cannot be overridden.')
        if any(target not in lanes for target in mapping):
            raise ValueError('A declared logical slot names a lane that was not reported.')
        t.slots = [LogicalSlot(slot_id(i), i, target) for i, target in enumerate(mapping)]
        t.bindings = [SlotBinding(slot_id(i), target, ['user-declared-slot-map']) for i, target in enumerate(mapping)]
        t.evidence.append('user-declared-slot-map')
    if historical:
        for obs in result.observations:
            obs.historical = True
        t.evidence.append('imported-snapshot-not-live')
    return result
