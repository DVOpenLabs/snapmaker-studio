"""Decoding of external data into foundation documents.

Foundation documents are pure data. Anything that arrives from outside Studio -- a
provider reply, a stored file, an imported passport -- is decoded here and never
raises on malformed input: the caller gets a `Decoded` that says what was wrong.
`value` is None whenever an error-severity diagnostic exists; an unknown
`schema_version` keeps the original content opaquely in `raw` and is never evaluated.

Programming errors (our own code passing the wrong Python types) still raise.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Iterable, TypeVar

T = TypeVar("T")

ERROR = "error"
WARNING = "warning"
NOTE = "note"
SEVERITIES = (ERROR, WARNING, NOTE)


@dataclass(frozen=True)
class Diagnostic:
    code: str
    field: str = ""
    severity: str = WARNING

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity!r}")

    def to_dict(self) -> dict:
        return {"code": self.code, "field": self.field, "severity": self.severity}


def diag(code: str, field: str = "", severity: str = WARNING) -> Diagnostic:
    return Diagnostic(code, field, severity)


def has_error(diagnostics: Iterable[Diagnostic]) -> bool:
    return any(d.severity == ERROR for d in diagnostics)


def is_finite_number(value: Any) -> bool:
    """True for a finite int or float. bool, NaN, inf and non-numbers are rejected."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:               # a valid JSON integer too large for a float
        return False


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=repr)


def content_hash(value: Any) -> str:
    """`sha256:<hex>` of the canonical JSON form of `value`."""
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def revision_envelope(parts: dict, extra: dict | None = None) -> dict:
    """The `inputs_revision` carried by every evaluation result.

    `parts` are the inputs the result depends on (snapshot id/hash, mapping revision, artifact
    hashes, observation and calibration revisions ... whatever is available; absent ones are
    simply not listed). `revision` is the hash of everything listed, so a changed dependency
    changes it. `extra` entries are listed too."""
    extra = extra or {}
    collisions = set(parts).intersection(extra) | ({"revision"} & (set(parts) | set(extra)))
    if collisions:
        names = ", ".join(sorted(collisions))
        raise ValueError(f"revision fields cannot be replaced: {names}")
    body = {**parts, **extra}
    return {**body, "revision": content_hash(body)}


@dataclass
class Decoded(Generic[T]):
    schema_version: str | None
    value: T | None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    valid_for_evaluation: bool = False
    raw: Any = None

    def to_dict(self) -> dict:
        out = {"schema_version": self.schema_version,
               "value": self.value.to_dict() if hasattr(self.value, "to_dict") else self.value,
               "diagnostics": [d.to_dict() for d in self.diagnostics],
               "valid_for_evaluation": self.valid_for_evaluation}
        if self.raw is not None:
            out["raw"] = self.raw
        return out


class Reader:
    """Typed, non-raising access to one JSON object. Collects diagnostics.

    A required field that is missing or of the wrong type is an error; an optional
    one of the wrong type is an error too (the value is untrustworthy), but an
    absent optional field is simply None. Nested readers share the diagnostics.
    """

    def __init__(self, raw: Any, path: str = "", diagnostics: list[Diagnostic] | None = None):
        self.diagnostics: list[Diagnostic] = diagnostics if diagnostics is not None else []
        self.path = path
        if isinstance(raw, dict):
            self.raw: dict = raw
        else:
            self.raw = {}
            self.error("not_an_object", "")

    # -- diagnostics -------------------------------------------------------
    def _where(self, name: str) -> str:
        if self.path and name:
            return f"{self.path}.{name}"
        return self.path or name

    def error(self, code: str, name: str = "") -> None:
        self.diagnostics.append(diag(code, self._where(name), ERROR))

    def warn(self, code: str, name: str = "") -> None:
        self.diagnostics.append(diag(code, self._where(name), WARNING))

    def note(self, code: str, name: str = "") -> None:
        self.diagnostics.append(diag(code, self._where(name), NOTE))

    def child(self, raw: Any, name: str) -> "Reader":
        return Reader(raw, self._where(name), self.diagnostics)

    # -- typed access ------------------------------------------------------
    def _present(self, name: str, required: bool) -> bool:
        if name in self.raw and self.raw[name] is not None:
            return True
        if required:
            self.error("missing_field", name)
        return False

    def string(self, name: str, *, required: bool = True, default: str | None = None) -> str | None:
        if not self._present(name, required):
            return default
        value = self.raw[name]
        if not isinstance(value, str) or not value.strip():
            self.error("wrong_type", name)
            return default
        return value

    def integer(self, name: str, *, required: bool = True, default: int | None = None,
                minimum: int | None = None) -> int | None:
        if not self._present(name, required):
            return default
        value = self.raw[name]
        if isinstance(value, bool) or not isinstance(value, int):
            self.error("wrong_type", name)
            return default
        if minimum is not None and value < minimum:
            self.error("out_of_range", name)
            return default
        return value

    def number(self, name: str, *, required: bool = False, default: float | None = None) -> float | None:
        if not self._present(name, required):
            return default
        value = self.raw[name]
        if not is_finite_number(value):
            self.error("wrong_type", name)
            return default
        try:
            return float(value)
        except OverflowError:
            self.error("wrong_type", name)
            return default

    def boolean(self, name: str, *, required: bool = False, default: bool | None = None) -> bool | None:
        if not self._present(name, required):
            return default
        value = self.raw[name]
        if not isinstance(value, bool):
            self.error("wrong_type", name)
            return default
        return value

    def enum(self, name: str, allowed: Iterable[str], *, required: bool = True,
             default: str | None = None) -> str | None:
        if not self._present(name, required):
            return default
        value = self.raw[name]
        if not isinstance(value, str) or value not in tuple(allowed):
            self.error("bad_enum", name)
            return default
        return value

    def items(self, name: str, *, required: bool = False) -> list:
        """A list field. Missing optional -> []; a non-list is an error and yields []."""
        if not self._present(name, required):
            return []
        value = self.raw[name]
        if not isinstance(value, list):
            self.error("wrong_type", name)
            return []
        return value

    def mapping(self, name: str, *, required: bool = False) -> dict:
        if not self._present(name, required):
            return {}
        value = self.raw[name]
        if not isinstance(value, dict):
            self.error("wrong_type", name)
            return {}
        return value

    def string_list(self, name: str, *, required: bool = False) -> list[str]:
        out = []
        for i, item in enumerate(self.items(name, required=required)):
            if isinstance(item, str) and item.strip():
                out.append(item)
            else:
                self.error("wrong_type", f"{name}[{i}]")
        return out

    def optional_string_list(self, name: str) -> list[str] | None:
        """None = unknown (field absent or null); [] = known empty."""
        if name not in self.raw or self.raw[name] is None:
            return None
        return self.string_list(name)


def parse_json(data: str | bytes) -> Decoded[Any]:
    """Parse JSON text. Never raises; the parsed object is returned as `value`."""
    try:
        text = data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data
        parsed = json.loads(text)
    except (ValueError, UnicodeDecodeError, TypeError, RecursionError):
        return Decoded(None, None, [diag("malformed_json", "", ERROR)], False)
    return Decoded(None, parsed, [], False)


def decode_document(raw: Any, schema_version: str, build: Callable[[Reader], T]) -> Decoded[T]:
    """Decode one versioned document. `raw` may be a dict or JSON text/bytes.

    Unknown or missing `schema_version` -> value None, raw preserved, never evaluated.
    `build` reads fields through the Reader and returns the document.
    """
    if isinstance(raw, (str, bytes, bytearray)):
        parsed = parse_json(raw)
        if parsed.value is None:
            return Decoded(None, None, parsed.diagnostics or [diag("not_an_object", "", ERROR)],
                           False, raw=_opaque(raw))
        raw = parsed.value
    if not isinstance(raw, dict):
        return Decoded(None, None, [diag("not_an_object", "", ERROR)], False, raw=raw)
    found = raw.get("schema_version")
    if found != schema_version:
        code = "missing_schema_version" if found is None else "unknown_schema_version"
        found_text = found if isinstance(found, str) else None
        return Decoded(found_text, None, [diag(code, "schema_version", ERROR)], False, raw=raw)
    reader = Reader(raw)
    try:
        value = build(reader)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, ArithmeticError, RecursionError):
        # A builder defect must not escape as an exception from external data.
        reader.error("decode_failed", "")
        value = None
    if has_error(reader.diagnostics):
        value = None
    return Decoded(schema_version, value, reader.diagnostics, value is not None,
                   raw=None if value is not None else raw)


def _opaque(raw: Any) -> Any:
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw).decode("utf-8", "replace")
    return raw
