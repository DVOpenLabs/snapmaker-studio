"""Request-input validation helpers for the loopback API.

Goal: turn bad *user* input into a clean HTTP 400 with a short, sanitized message
(e.g. "Invalid scale_percent") instead of a 500 with a raw Python traceback.
Each helper raises ``ValidationError`` (carrying a safe message) on bad input;
the server maps that to 400. Genuine internal failures still raise normally and
the server maps those to a generic 500 (no raw exception text).

These helpers never leak the offending value or a stack trace in the message.
"""
from __future__ import annotations

import math


class ValidationError(ValueError):
    """Bad user input. The message is safe to return to the client verbatim."""


def require_str(data: dict, key: str) -> str:
    v = data.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ValidationError(f"Missing or invalid '{key}'")
    return v


def optional_str(data: dict, key: str, default: str = "") -> str:
    v = data.get(key, default)
    if v is None:
        return default
    if not isinstance(v, str):
        raise ValidationError(f"Invalid '{key}'")
    return v


def require_path_string(data: dict, key: str = "path") -> str:
    """A non-empty string path. (Existence/safety is the engine's concern; this
    only guarantees the field is a usable string, not a number/null/object.)"""
    return require_str(data, key)


def _as_number(data: dict, key: str, required: bool, default: float | None) -> float | None:
    if key not in data or data.get(key) is None:
        if required:
            raise ValidationError(f"Missing '{key}'")
        return default
    v = data.get(key)
    # Reject bools (bool is an int subclass) and non-numeric strings/objects.
    if isinstance(v, bool):
        raise ValidationError(f"Invalid {key}")
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        try:
            f = float(v.strip())
        except (TypeError, ValueError):
            raise ValidationError(f"Invalid {key}")
    else:
        raise ValidationError(f"Invalid {key}")
    if not math.isfinite(f):
        raise ValidationError(f"Invalid {key}")
    return f


def require_float(data: dict, key: str) -> float:
    return _as_number(data, key, required=True, default=None)  # type: ignore[return-value]


def optional_float(data: dict, key: str, default: float) -> float:
    return _as_number(data, key, required=False, default=default)  # type: ignore[return-value]


def require_finite_float(data: dict, key: str) -> float:
    # _as_number already rejects NaN/Inf; alias kept for call-site clarity.
    return require_float(data, key)


def require_positive_float(data: dict, key: str) -> float:
    f = require_float(data, key)
    if f <= 0:
        raise ValidationError(f"Invalid {key}")
    return f


def optional_positive_float(data: dict, key: str, default: float) -> float:
    f = optional_float(data, key, default)
    if f <= 0:
        raise ValidationError(f"Invalid {key}")
    return f


def require_int(data: dict, key: str) -> int:
    f = require_float(data, key)
    if f != int(f):
        raise ValidationError(f"Invalid {key}")
    return int(f)


def optional_int(data: dict, key: str, default: int) -> int:
    if key not in data or data.get(key) is None:
        return default
    f = _as_number(data, key, required=True, default=None)
    if f != int(f):
        raise ValidationError(f"Invalid {key}")
    return int(f)


def require_port(data: dict, key: str = "port", default: int = 7125) -> int:
    p = optional_int(data, key, default)
    if not (1 <= p <= 65535):
        raise ValidationError(f"Invalid {key}")
    return p


def optional_non_negative_float(data: dict, key: str, default: float | None) -> float | None:
    """Zero is a real answer here (a spool tracked down to empty), unlike
    optional_positive_float — only negative and non-numeric values are refused."""
    if key not in data or data.get(key) is None:
        return default
    f = _as_number(data, key, required=True, default=None)
    if f < 0:
        raise ValidationError(f"Invalid {key}")
    return f


def require_slot_index(data: dict, key: str = "slot") -> int:
    """A printer slot index: a small non-negative integer, never a guess at
    what the caller meant by a float or a negative number."""
    n = require_int(data, key)
    if not (0 <= n <= 31):
        raise ValidationError(f"Invalid {key}")
    return n
