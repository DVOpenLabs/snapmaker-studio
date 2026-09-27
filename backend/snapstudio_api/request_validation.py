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


def _safe_float(v, error_message: str) -> float:
    """Convert to a finite float, or raise ``ValidationError(error_message)``.

    A JSON body has no length limit on an integer literal — ``10**400``
    parses to a perfectly ordinary (if enormous) Python ``int`` — but
    ``float()`` on one that big raises ``OverflowError``, not ``ValueError``.
    Every numeric validator that ever converts a raw JSON value to float goes
    through this one place, so none of them can let that leak past as an
    unhandled 500."""
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        raise ValidationError(error_message)
    if not math.isfinite(f):
        raise ValidationError(error_message)
    return f


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
        return _safe_float(v, f"Invalid {key}")
    if isinstance(v, str):
        return _safe_float(v.strip(), f"Invalid {key}")
    raise ValidationError(f"Invalid {key}")


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
    try:
        n = require_int(data, key)
    except ValidationError:
        raise ValidationError("invalid_slot")
    if not (0 <= n <= 31):
        raise ValidationError("invalid_slot")
    return n


#: A sentinel distinct from ``None``: "the key was not sent at all" vs
#: "the key was sent, and it was explicitly null". A spool text field needs
#: both answers, and they mean opposite things (A3.3): MISSING/None preserve
#: whatever is on record; "" clears it.
MISSING = object()


def optional_nullable_str(data: dict, key: str) -> object:
    """Presence-aware string: MISSING (key absent) preserves, None (explicit
    null) preserves, "" clears (caller stores NULL), any other string is
    stripped and set. Never raises on a missing/null key — only a non-string,
    non-null value is invalid."""
    if key not in data:
        return MISSING
    v = data[key]
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValidationError("invalid_request")
    return v.strip()


def optional_bounded_float(data: dict, key: str, lo: float, hi: float,
                           default: float | None = None) -> float | None:
    """A number in [lo, hi], or ``default`` if the key is absent/null."""
    if key not in data or data.get(key) is None:
        return default
    f = _as_number(data, key, required=True, default=None)
    if f < lo or f > hi:
        raise ValidationError("invalid_weight")
    return f


def optional_color(data: dict, key: str = "color") -> object:
    """A3.3/A1.4 for the one text field with a format: MISSING/None preserve,
    "" clears, a non-empty value must be #RRGGBB (normalised upper) or 400
    `invalid_color`. A legacy free-text colour is never re-validated here —
    only a value THIS call is trying to set goes through the hex check."""
    v = optional_nullable_str(data, key)
    if v is MISSING or v is None or v == "":
        return v
    s = v.lstrip("#")
    if len(s) == 6 and all(c in "0123456789abcdefABCDEF" for c in s):
        return "#" + s.upper()
    raise ValidationError("invalid_color")


def bounded_weight(data: dict, key: str) -> object:
    """A2.6 + tri-state (A3.3 parity, CodeRabbit PR #41): a spool weight
    field behaves exactly like the text fields — MISSING (key absent)
    returns the ``MISSING`` sentinel, an explicit ``null`` returns ``None``
    (both mean "preserve" to the caller); "" (or a whitespace-only string)
    returns ``""`` (the caller's "clear" marker, same as `optional_nullable_str`);
    a number in [0, 10000] is returned as a float. Only a value that is
    genuinely wrong — out of range, or a non-numeric, non-empty string —
    raises `invalid_weight`; a clear never does."""
    if key not in data:
        return MISSING
    v = data[key]
    if v is None:
        return None
    if isinstance(v, str) and v.strip() == "":
        return ""
    try:
        f = _as_number(data, key, required=True, default=None)
    except ValidationError:
        raise ValidationError("invalid_weight")
    if f < 0 or f > 10000:
        raise ValidationError("invalid_weight")
    return f


def bounded_used_weight(data: dict, key: str = "used_g") -> float:
    """A2.6: 0 < used_g <= 10000 g, required."""
    try:
        f = require_float(data, key)
    except ValidationError:
        # Missing, non-numeric, or too large to convert (10**400) all map to
        # the one code A4.3 promises for this route — never the generic
        # invalid_request just because the bad-value message wasn't already
        # shaped like a code.
        raise ValidationError("invalid_weight")
    if f <= 0 or f > 10000:
        raise ValidationError("invalid_weight")
    return f


def nullable_diameter_list(data: dict, key: str = "diameters", max_len: int = 8) -> list[float | None]:
    """1..8 entries, each ``None`` ("not sure") or a finite 0 < d <= 2.0 mm —
    the shape `/nozzles/confirm` takes. Distinct from
    `optional_positive_float_list`: this one is required, and null entries are
    a real, meaningful answer rather than a reason to reject the request."""
    v = data.get(key)
    if not isinstance(v, list) or not (1 <= len(v) <= max_len):
        raise ValidationError("invalid_diameters")
    out: list[float | None] = []
    for item in v:
        if item is None:
            out.append(None)
            continue
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValidationError("invalid_diameters")
        f = _safe_float(item, "invalid_diameters")
        if not (0 < f <= 2.0):
            raise ValidationError("invalid_diameters")
        out.append(f)
    return out


def optional_positive_float_list(data: dict, key: str, max_len: int = 8) -> list[float] | None:
    """A list of positive, finite numbers (e.g. user-confirmed nozzle diameters
    per toolhead), or None if the key is absent/null. Bounded length so a
    malformed/hostile body can't make Studio allocate an unbounded list."""
    v = data.get(key)
    if v is None:
        return None
    if not isinstance(v, list) or not v or len(v) > max_len:
        raise ValidationError(f"Invalid {key}")
    out: list[float] = []
    for item in v:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValidationError(f"Invalid {key}")
        f = _safe_float(item, f"Invalid {key}")
        if f <= 0:
            raise ValidationError(f"Invalid {key}")
        out.append(f)
    return out
