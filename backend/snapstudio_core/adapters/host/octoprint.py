"""OctoPrint host adapter. Identity comes from the `/api/version` body (see `classify`).

OctoPrint reports no toolhead or filament data on the read-only paths Studio allows, so the
topology is empty and incomplete: heads, slots and materials are UNKNOWN, not zero. The API
key is held by the caller for the request only and never reaches this module.
"""
from __future__ import annotations

from typing import Any

from ...foundation import topology as topo
from ...foundation.decode import ERROR, diag
from ...foundation.observations import parse_time, to_iso
from ..base import Adapter, AdapterInfo, AdapterResult
from . import classify as cl
from . import moonraker_parse as mp
from .moonraker_parse import BUNDLE_VERSION

HOST_SUBJECT = {"kind": "host", "id": "host:octoprint"}


class OctoPrintAdapter(Adapter):
    info = AdapterInfo(id="host.octoprint", kind="host", versions_supported=(BUNDLE_VERSION,), ttl_s=60.0)

    def _parse(self, data: Any, received_at: Any, result: AdapterResult) -> None:
        if not isinstance(data, dict):
            result.errors.append(diag("bundle_not_object", "", ERROR))
            return
        api = data.get("api_version")
        kind = cl.classify(api, data.get("server_info"))
        if kind == cl.MOONRAKER:
            result.errors.append(diag("host_is_moonraker", "api_version", ERROR))
            return
        if kind != cl.OCTOPRINT:
            result.errors.append(diag("host_not_octoprint", "api_version", ERROR))
            return
        stamp = parse_time(received_at)
        received_iso = to_iso(stamp.timestamp()) if stamp is not None else "invalid"
        snapshot = mp.snapshot_id_of(data)

        def obs(field: str, value: Any) -> None:
            self.observe(result, observation_id=f"{self.info.id}:{snapshot}:{HOST_SUBJECT['id']}:{field}",
                         subject=HOST_SUBJECT, field=field, value=value, snapshot_id=snapshot,
                         received_at=received_at)

        obs("service", "octoprint")
        version = api.get("server")
        if isinstance(version, str) and version.strip():
            obs("octoprint_version", version.strip()[:64])
        else:
            result.unknowns.append("octoprint_version")
        result.unknowns.extend(["heads", "slots", "materials"])
        result.topology = topo.Topology(snapshot_id=snapshot, received_at=received_iso, complete=False,
                                        evidence=["api_version"])


INSTANCE = OctoPrintAdapter()
