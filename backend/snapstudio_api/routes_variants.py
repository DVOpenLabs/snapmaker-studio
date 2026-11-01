"""Read-only routes for comparing two sliced outputs."""
from __future__ import annotations

from snapstudio_core.variants import compare_outputs

from . import ext_routes
from . import request_validation as rv


@ext_routes.route("/variants/compare")
def compare(data: dict) -> tuple[int, dict]:
    """Compare exactly two user-selected local outputs."""
    try:
        return 200, compare_outputs(data)
    except ValueError as exc:
        # Unusable input is the caller's to fix: a plain sentence, never the internal-error response.
        raise rv.ValidationError(str(exc)) from exc
