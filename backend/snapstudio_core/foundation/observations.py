"""Observations: a fact, where it came from, when it was true, and how long it holds.

`observed_at` is when the fact was true at the source; `received_at` is when Studio
received it. They are different clocks and are never merged. Freshness is computed
from `observed_at` and a mandatory finite positive `ttl_s`; whether a figure may be
leaned on for loadout conclusions (`usable_for_loadout`) is a separate answer.

Vocabulary and skew tolerance come from the legacy `freshness` module (read-only).
"""
from __future__ import annotations

import collections
import datetime
import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Any

from .. import freshness as _legacy
from .decode import Decoded, Diagnostic, ERROR, NOTE, WARNING, Reader, decode_document, diag, is_finite_number

SCHEMA_VERSION = "observation/1"

FRESH = _legacy.FRESH
AGEING = _legacy.AGEING
STALE = _legacy.STALE
UNKNOWN = _legacy.UNKNOWN
UNUSABLE = _legacy.UNUSABLE
SKEW_TOLERANCE_S = _legacy.SKEW_TOLERANCE_S

SUBJECT_KINDS = ("lane", "head", "slot", "spool", "host", "file")
SOURCE_KINDS = ("live_query", "cached_record")

_UTC = datetime.timezone.utc


# -- time helpers ---------------------------------------------------------------
def to_iso(epoch: float) -> str:
    """Epoch seconds -> ISO-8601 UTC ("...Z"). A non-finite or out-of-range value is a programming error."""
    if not is_finite_number(epoch):
        raise ValueError("epoch must be a finite number")
    try:
        stamp = datetime.datetime.fromtimestamp(float(epoch), _UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("epoch out of range") from exc
    return stamp.isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> datetime.datetime | None:
    """ISO-8601 string, datetime or finite epoch number -> aware UTC datetime, else None. Never raises."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not is_finite_number(value):
            return None
        try:
            return datetime.datetime.fromtimestamp(float(value), _UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, (str, datetime.datetime)):
        try:
            stamp = _legacy.parse(value)
        except (ValueError, OverflowError):
            return None
        return stamp.astimezone(_UTC) if stamp is not None else None
    return None


def _normalise_time_field(value: Any) -> str | None:
    """Store times as ISO text. A finite number becomes ISO; unparseable text is kept so
    freshness can report UNUSABLE rather than silently turning it into 'unknown'."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not is_finite_number(value):
            return "invalid"
        try:
            return to_iso(value)
        except ValueError:      # out-of-range epoch from outside: keep it unreadable, never raise
            return "invalid"
    if isinstance(value, datetime.datetime):
        stamp = parse_time(value)
        return stamp.isoformat().replace("+00:00", "Z") if stamp else "invalid"
    return value if isinstance(value, str) else "invalid"


def _now(now: Any) -> datetime.datetime:
    if now is None:
        return datetime.datetime.now(_UTC)
    stamp = parse_time(now)
    if stamp is None:
        raise ValueError("now must be a datetime, ISO string or epoch number")
    return stamp


# -- the document ---------------------------------------------------------------
@dataclass
class Observation:
    observation_id: str
    subject: dict          # {kind, id}
    field: str
    value: Any
    source: dict           # {provider_instance_id, kind, source_version|None, snapshot_id}
    observed_at: str | None
    received_at: str
    ttl_s: Any             # must be a finite number > 0; anything else makes the observation UNUSABLE
    ageing_ok: bool = False
    historical: bool = False
    source_kind: str = "live_query"
    history_uncertain: bool = False   # stamped after the tracker lost history: never loadout-eligible

    def __post_init__(self) -> None:
        self.observed_at = _normalise_time_field(self.observed_at)
        self.received_at = _normalise_time_field(self.received_at) or "invalid"

    def diagnostics(self) -> list[Diagnostic]:
        """Construction diagnostics. The observation is kept either way; freshness says UNUSABLE."""
        out: list[Diagnostic] = []
        if not is_finite_number(self.ttl_s) or self.ttl_s <= 0:
            out.append(diag("ttl_invalid", "ttl_s", ERROR))
        if self.source_kind not in SOURCE_KINDS:
            out.append(diag("source_kind_unknown", "source_kind", ERROR))
        if parse_time(self.received_at) is None:
            out.append(diag("received_at_unreadable", "received_at", WARNING))
        return out

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "observation_id": self.observation_id,
                "subject": dict(self.subject), "field": self.field, "value": self.value,
                "source": dict(self.source), "source_kind": self.source_kind,
                "observed_at": self.observed_at, "received_at": self.received_at,
                "ttl_s": self.ttl_s if is_finite_number(self.ttl_s) else None,
                "ageing_ok": self.ageing_ok, "historical": self.historical,
                **({"history_uncertain": True} if self.history_uncertain else {})}

    @classmethod
    def from_dict(cls, raw: Any) -> Decoded["Observation"]:
        return decode_document(raw, SCHEMA_VERSION, cls._build)

    @classmethod
    def _build(cls, r: Reader) -> "Observation":
        subject = r.mapping("subject", required=True)
        sr = r.child(subject, "subject")
        kind = sr.enum("kind", SUBJECT_KINDS)
        sid = sr.string("id")
        source = r.mapping("source", required=True)
        src = r.child(source, "source")
        provider = src.string("provider_instance_id")
        source_kind_inner = src.string("kind")
        version = src.string("source_version", required=False)
        snapshot = src.string("snapshot_id", required=False)
        observed_raw = r.raw.get("observed_at")
        if observed_raw is not None and (isinstance(observed_raw, bool)
                                         or not isinstance(observed_raw, (str, int, float))):
            r.error("wrong_type", "observed_at")
            observed_raw = None
        received_raw = r.raw.get("received_at")
        if received_raw is None:
            r.error("missing_field", "received_at")
        elif isinstance(received_raw, bool) or not isinstance(received_raw, (str, int, float)):
            r.error("wrong_type", "received_at")
        ttl = r.raw.get("ttl_s")
        if not is_finite_number(ttl) or ttl <= 0:
            r.error("ttl_invalid", "ttl_s")
        if "value" not in r.raw:
            r.error("missing_field", "value")
        return cls(
            observation_id=r.string("observation_id") or "",
            subject={"kind": kind, "id": sid},
            field=r.string("field") or "",
            value=r.raw.get("value"),
            source={"provider_instance_id": provider, "kind": source_kind_inner,
                    "source_version": version, "snapshot_id": snapshot},
            observed_at=observed_raw if observed_raw is not None else None,
            received_at=received_raw if received_raw is not None else "invalid",
            ttl_s=ttl,
            ageing_ok=bool(r.boolean("ageing_ok", default=False)),
            historical=bool(r.boolean("historical", default=False)),
            source_kind=r.enum("source_kind", SOURCE_KINDS) or "live_query",
            history_uncertain=bool(r.boolean("history_uncertain", default=False)),
        )


def freshness(obs: Observation, now: Any = None) -> dict:
    """How old is this observation, and may it be used for loadout conclusions?

    Order: invalid ttl -> UNUSABLE; observed_at missing -> UNKNOWN; unparseable -> UNUSABLE;
    future beyond SKEW_TOLERANCE_S -> UNUSABLE (within skew the age is clamped to 0);
    age <= ttl/2 FRESH; <= ttl AGEING; else STALE. `historical` forces
    usable_for_loadout False regardless of age; so does `history_uncertain` (the display state is
    unchanged, only loadout eligibility is withheld).
    """
    def result(state: str, age: float | None, reason: str) -> dict:
        usable = (
            (state == FRESH or (state == AGEING and bool(obs.ageing_ok)))
            and not obs.historical
            and not obs.history_uncertain
        )
        return {"state": state, "age_s": age, "usable_for_loadout": usable, "reason": reason}

    ttl = obs.ttl_s
    if not is_finite_number(ttl) or ttl <= 0:
        return result(UNUSABLE, None, "The lifetime of this figure is missing or not a positive number.")
    if obs.observed_at is None:
        return result(UNKNOWN, None, "Nothing records when this figure was last true.")
    stamp = parse_time(obs.observed_at)
    if stamp is None:
        return result(UNUSABLE, None, "Studio could not read the date on this figure.")
    age = (_now(now) - stamp).total_seconds()
    if age < -SKEW_TOLERANCE_S:
        return result(UNUSABLE, None, "This figure is dated in the future beyond clock tolerance.")
    age = max(age, 0.0)
    if age <= ttl / 2:
        state = FRESH
    elif age <= ttl:
        state = AGEING
    else:
        state = STALE
    if obs.historical:
        reason = "Restored from an earlier session."
    elif obs.history_uncertain:
        reason = "History is uncertain; no new source evidence yet."
    else:
        reason = f"Aged {age:g} s of {ttl:g} s."
    return result(state, age, reason)


# -- observed_at stamping -----------------------------------------------------
class ObservedAtTracker:
    """Decides `observed_at` and builds observations for adapters.

    live_query: observed_at is the provider's own timestamp when it supplies one, else the
    receipt time of every successful read (diagnostic `observed_at_is_receipt_time`).
    cached_record: re-polling an unchanged record never renews observed_at. The provider's
    timestamp is used when present; otherwise the first observed_at is kept for an unchanged
    (subject, field, value, revision) within this process. `received_at` always advances.

    Eviction never renews a figure: a key found in the eviction memory has an UNKNOWN
    `observed_at` (diagnostic `observed_at_lost_after_eviction`). The memory is an exact digest
    cache of the last `4 * max_entries` evictions, then two rotating digest-filter generations that
    each cover `4 * max_entries` more. The oldest generation is dropped on rotation, so filter false
    positives cannot accumulate without limit and a changed value or revision is eventually
    accepted as new. Limit: an unchanged key not seen for longer than that retention is treated as
    new, because Studio no longer holds any record of it.

    Once a rotation has dropped a generation that held evictions, the tracker has really lost history
    and cannot tell an unchanged forgotten record from one it never saw. From then on a cached record
    observed without a provider timestamp and not already known to the tracker (a first sighting, or a
    changed value or revision) gets `observed_at` = receipt time (so it still displays FRESH, and a
    change still becomes fresh) but is marked `history_uncertain` (diagnostic
    `observed_at_history_uncertain`) and is never `usable_for_loadout`. The mark is sticky: re-polling
    the same cached value is not new provider evidence, so every later sighting of that key within
    retention stays `history_uncertain`; it is cleared only when the key leaves the tracker (eviction).
    Only a provider timestamp establishes it. Records first seen before any loss are unaffected.
    """

    def __init__(self, max_entries: int = 4096):
        self._first: dict[str, str] = {}
        self._evicted: "collections.OrderedDict[str, None]" = collections.OrderedDict()
        self._gen_bits = max(32, max_entries * 8)
        self._gens = [bytearray(self._gen_bits), bytearray(self._gen_bits)]    # [current, previous]
        self._gen_count = 0
        self._rotations = 0
        self._history_lost = False               # a generation holding evictions has been dropped
        self._uncertain: set[str] = set()         # keys stamped while history_lost; sticky until evicted
        self._lock = threading.Lock()
        self._max = max_entries

    @staticmethod
    def _digest(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()[:32]

    def _remember_evicted(self, digest: str) -> None:
        raw = bytes.fromhex(digest)
        bit_count = len(self._gens[0]) * 8
        for offset in (0, 4, 8):
            bit = int.from_bytes(raw[offset:offset + 4], "big") % bit_count
            self._gens[0][bit // 8] |= 1 << (bit % 8)
        self._gen_count += 1
        if self._gen_count >= self._max * 4:                  # rotate: the oldest generation is dropped
            if self._rotations >= 1:
                self._history_lost = True                 # the dropped generation held real evictions
            self._rotations += 1
            self._gens = [bytearray(self._gen_bits), self._gens[0]]
            self._gen_count = 0

    def _was_evicted(self, digest: str) -> bool:
        raw = bytes.fromhex(digest)
        bit_count = len(self._gens[0]) * 8
        bits = [int.from_bytes(raw[offset:offset + 4], "big") % bit_count for offset in (0, 4, 8)]
        return any(all(gen[bit // 8] & (1 << (bit % 8)) for bit in bits) for gen in self._gens)

    @staticmethod
    def _key(subject: dict, field_name: str, value: Any, revision: Any) -> str:
        try:
            canon = json.dumps([subject, field_name, value, revision], sort_keys=True, default=repr)
        except (TypeError, ValueError):
            canon = repr([subject, field_name, value, revision])
        return canon

    def observe(self, *, observation_id: str, subject: dict, field: str, value: Any, source: dict,
                source_kind: str, received_at: Any, ttl_s: Any, revision: Any = None,
                provider_time: Any = None, ageing_ok: bool = False) -> tuple[Observation, list[Diagnostic]]:
        if source_kind not in SOURCE_KINDS:
            raise ValueError(f"unknown source_kind {source_kind!r}")
        received = _normalise_time_field(received_at)
        diagnostics: list[Diagnostic] = []
        observed: str | None
        uncertain = False
        if provider_time is not None:
            observed = _normalise_time_field(provider_time)
        elif source_kind == "live_query":
            observed = received
            diagnostics.append(diag("observed_at_is_receipt_time", "observed_at", NOTE))
        else:
            key = self._key(subject, field, value, revision)
            with self._lock:
                observed = self._first.get(key)
                lost = uncertain = False
                if observed is not None:
                    uncertain = key in self._uncertain    # sticky: a re-poll is not new evidence
                if observed is None:
                    digest = self._digest(key)
                    lost = digest in self._evicted or self._was_evicted(digest)   # maybe seen: never renew
                    if not lost:
                        observed = received
                        uncertain = self._history_lost
                        if len(self._first) >= self._max:
                            oldest = next(iter(self._first))
                            del self._first[oldest]
                            self._uncertain.discard(oldest)
                            self._evicted[self._digest(oldest)] = None
                            if len(self._evicted) > self._max * 4:
                                old_digest, _ = self._evicted.popitem(last=False)
                                self._remember_evicted(old_digest)
                        self._first[key] = observed
                        if uncertain:
                            self._uncertain.add(key)
            if lost:
                diagnostics.append(diag("observed_at_lost_after_eviction", "observed_at", WARNING))
            else:
                diagnostics.append(diag("observed_at_is_receipt_time", "observed_at", NOTE))
                if uncertain:
                    diagnostics.append(diag("observed_at_history_uncertain", "observed_at", WARNING))
        obs = Observation(observation_id=observation_id, subject=dict(subject), field=field, value=value,
                          source=dict(source), observed_at=observed, received_at=received or "invalid",
                          ttl_s=ttl_s, ageing_ok=ageing_ok, source_kind=source_kind,
                          history_uncertain=uncertain)
        diagnostics.extend(obs.diagnostics())
        return obs, diagnostics


def as_historical(obs: Observation) -> Observation:
    """A restored copy: never usable for loadout conclusions until freshly read."""
    return Observation(observation_id=obs.observation_id, subject=dict(obs.subject), field=obs.field,
                       value=obs.value, source=dict(obs.source), observed_at=obs.observed_at,
                       received_at=obs.received_at, ttl_s=obs.ttl_s, ageing_ok=obs.ageing_ok,
                       historical=True, source_kind=obs.source_kind,
                       history_uncertain=obs.history_uncertain)
