"""Routes for guarded monitoring context and local workspace recovery."""
from __future__ import annotations

import time

from snapstudio_core import monitoring_context, workspace_recovery
from snapstudio_core import moonraker
from snapstudio_core.errors import SnapStudioError
from snapstudio_core.foundation import store
from snapstudio_core.foundation.observations import to_iso

from . import ext_routes, request_validation as rv


@ext_routes.route("/monitoring/read")
def monitoring_read(data: dict) -> tuple[int, dict]:
    host = rv.require_bounded_str(data, "host", 255)
    port = rv.require_port(data, "port", 7125)
    previous = data.get("previous_state")
    if previous is not None and (not isinstance(previous, str) or len(previous) > 64):
        raise rv.ValidationError("Invalid 'previous_state'")
    try:
        result = monitoring_context.read(host, port)
    except moonraker.InvalidHost as exc:
        raise rv.ValidationError(str(exc)) from exc
    if previous is not None:
        result["reconciliation"] = monitoring_context.reconcile(previous, result)
    return 200, result


@ext_routes.route("/monitoring/history")
def monitoring_history(data: dict) -> tuple[int, dict]:
    host = rv.require_bounded_str(data, "host", 255)
    port = rv.require_port(data, "port", 7125)
    try:
        return 200, monitoring_context.read_history(host, port)
    except moonraker.InvalidHost as exc:
        raise rv.ValidationError(str(exc)) from exc


@ext_routes.route("/recovery/checkpoint")
def recovery_checkpoint(data: dict) -> tuple[int, dict]:
    raw = data.get("workspace", {})
    if not isinstance(raw, dict):
        raise rv.ValidationError("Invalid 'workspace'")
    observations = data.get("observations", [])
    files = data.get("files", [])
    jobs = data.get("jobs", [])
    if any(not isinstance(value, list) or len(value) > 1000 for value in (observations, files, jobs)):
        raise rv.ValidationError("Invalid checkpoint content")
    expected = data.get("expected_revision")
    if expected is not None and (isinstance(expected, bool) or not isinstance(expected, int)):
        raise rv.ValidationError("Invalid 'expected_revision'")
    try:
        result = workspace_recovery.checkpoint({"workspace": raw, "observations": observations,
                                                "files": files, "jobs": jobs,
                                                "checkpointed_at": to_iso(time.time())},
                                               expected_revision=expected)
    except store.StoreLockError:
        raise SnapStudioError("Another Studio process is saving a checkpoint. Try again shortly.") from None
    except (store.RevisionConflict, store.StoreVersionError):
        raise                                               # dispatch owns these refusal texts
    except store.StoreError:
        raise SnapStudioError("The checkpoint could not be saved.") from None
    return 200, result


@ext_routes.route("/recovery/restore")
def recovery_restore(data: dict) -> tuple[int, dict]:
    try:
        return 200, workspace_recovery.restore()
    except store.StoreVersionError:
        raise
    except store.StoreError:
        raise SnapStudioError("The saved checkpoint could not be read.") from None
