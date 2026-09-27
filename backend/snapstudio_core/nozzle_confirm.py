"""Per-printer, per-toolhead nozzle diameter the user confirms themselves.

Stock U1 firmware publishes the fitted nozzle diameter over Moonraker
(``printer_facts()`` reads it); plenty of other firmware genuinely does not.
When it does not, and only then, a person can tell Studio which nozzle is
fitted — once, here — rather than repeating it into every dialog that used to
carry its own `confirmed_nozzle_diameters` request field.

Precedence, always: LIVE printer reading > USER-CONFIRMED (this module) >
UNKNOWN. A live reading is whole-list-or-nothing (a firmware that answers for
some toolheads and not others is not something Moonraker's own API
distinguishes, so Studio does not invent that distinction either) and a
user's confirmation is never blended into it — only used when the printer
answered nothing at all.

Storage is keyed by ``canonical_host(host)`` and ``port`` (default 7125),
never the string exactly as a person typed it — "U1.local " and "u1.local"
must be the same printer's confirmation, and an IPv6 address written with or
without brackets must be too.
"""
from __future__ import annotations

import ipaddress

from . import library, moonraker

#: Moonraker's own default, and the port a stored confirmation is keyed to
#: when the caller does not say otherwise.
DEFAULT_PORT = 7125

#: Same ceiling as the toolhead-diameters list everywhere else in Studio.
MAX_TOOLHEADS = 8

#: A nozzle bigger than this is not a real FDM nozzle; a request that says
#: otherwise is malformed, not a big printer.
MAX_DIAMETER_MM = 2.0


class InvalidHost(ValueError):
    """The submitted host is not a storage key Studio can use."""


# Re-exported so callers only need one name for "the confirmation changed
# under you" regardless of whether it came from this module or `library`.
StaleRevision = library.StaleRevision


def canonical_host(host: str) -> str:
    """The storage key for a printer address.

    Wraps `moonraker.validate_host` — a nozzle confirmation is only ever keyed
    by exactly what the printer layer itself accepts — with the normalisation
    rules the plan fixes: trim; reject embedded whitespace, a URL scheme, a
    path or an ``@``; lowercase a DNS name; strip exactly one trailing dot
    (``u1.local.`` and ``u1.local`` are the same printer); an IPv6 address,
    bracketed or not as submitted, is stored bracketed, compressed and
    lowercase. An embedded port outside of IPv6 brackets is rejected — the
    port is its own field, never smuggled into the host string.
    """
    raw = host if isinstance(host, str) else ""
    h = raw.strip()
    if not h or any(ch.isspace() for ch in h):
        raise InvalidHost("That printer address isn't valid.")
    if "://" in h or "/" in h or "@" in h:
        raise InvalidHost("That printer address isn't valid.")

    ipv6_candidate: str | None = None
    if h.startswith("[") and h.endswith("]"):
        ipv6_candidate = h[1:-1]
    elif h.count(":") >= 2:
        ipv6_candidate = h

    if ipv6_candidate is not None:
        try:
            addr = ipaddress.ip_address(ipv6_candidate)
        except ValueError:
            raise InvalidHost("That printer address isn't valid.")
        if addr.version != 6:
            raise InvalidHost("That printer address isn't valid.")
        candidate = f"[{addr.compressed.lower()}]"
        try:
            return moonraker.validate_host(candidate)
        except moonraker.InvalidHost as exc:
            raise InvalidHost("That printer address isn't valid.") from exc

    if h.count(":") >= 1:
        # A single bare colon that is not IPv6 is an embedded port — reject it
        # rather than guess which part was the host.
        raise InvalidHost("That printer address isn't valid.")

    lowered = h.lower()
    if lowered.endswith(".") and not lowered.endswith(".."):
        lowered = lowered[:-1]
    try:
        return moonraker.validate_host(lowered)
    except moonraker.InvalidHost as exc:
        raise InvalidHost("That printer address isn't valid.") from exc


def validate_diameters(diameters: list) -> list[float | None]:
    """1..8 entries, each ``None`` ("not sure") or a finite 0 < d <= 2.0 mm."""
    if not isinstance(diameters, list) or not (1 <= len(diameters) <= MAX_TOOLHEADS):
        raise ValueError("invalid_diameters")
    out: list[float | None] = []
    for item in diameters:
        if item is None:
            out.append(None)
            continue
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError("invalid_diameters")
        value = float(item)
        if not (value == value) or value in (float("inf"), float("-inf")):
            raise ValueError("invalid_diameters")
        if not (0 < value <= MAX_DIAMETER_MM):
            raise ValueError("invalid_diameters")
        out.append(value)
    return out


def _num(value) -> str:
    try:
        return f"{round(float(value), 2):g}"
    except (TypeError, ValueError):
        return str(value)


OK = "ok"
ATTENTION = "attention"
UNKNOWN = "unknown"


def match_verdict(required: list[int], ordered: list | None, wanted_set: set,
                  reported: list) -> str:
    """The one frozen result matrix (plan A1.8 + A3.2 vacuous-truth + A4.4
    mixed-size override), shared by `preflight._nozzle` and
    `post_slice._nozzle` so the two halves of the same check can never drift.

    ``required`` is the list of positions (0-based) this comparison must
    settle for this project/job. ``ordered`` is the project/job's own
    per-toolhead list when one genuinely exists (a positional comparison);
    when it is ``None``, only ``wanted_set`` (the deduplicated sizes) is
    available, and the comparison is necessarily about set membership, never
    toolhead assignment.
    """
    wanted_nums = {_num(w) for w in wanted_set}

    if ordered or len(wanted_nums) == 1:
        # A genuine per-toolhead order, OR a single project size — which is
        # trivially "the same value expected at every required position", the
        # exact rule the ordered comparison already implements. B1 fix (Opus
        # H1/Sol 3): a single size is compared POSITION BY POSITION over every
        # required index, never by set membership — a printer that reports
        # the wanted size on ONE required position and something else on
        # another must never read as OK just because the wanted size exists
        # SOMEWHERE in what it reported.
        single = next(iter(wanted_nums)) if not ordered else None
        # R2-B2 (Opus N2) + F6 (round 3, Sol d): a required position beyond
        # `ordered`'s own length, OR one `ordered` genuinely has a value for
        # but that value is itself None ("not sure" / not stated), has no
        # expected size AT ALL — the job/project simply never stated one for
        # it (v1.1.0 parity: a shorter G-code nozzle list against a printer
        # that answers for more toolheads than the job's own list covers; or
        # a slicer/confirmation that recorded "not sure" for one toolhead).
        # That is not "unknown" and never "a mismatch" — it is irrelevant to
        # this comparison, and dropped from `required` entirely, BEFORE
        # counting known/relevant, rather than counted against it either way.
        # An empty `relevant` (nothing left to compare) is UNKNOWN, same as
        # the existing known==0 vacuous-truth rule below.
        relevant = [i for i in required
                   if not ordered or (i < len(ordered) and ordered[i] is not None)]
        mismatch = False
        known = 0
        for i in relevant:
            reported_i = reported[i] if i < len(reported) else None
            if reported_i is None:
                continue
            known += 1
            wanted_i = ordered[i] if ordered else single
            if wanted_i is None or _num(wanted_i) != _num(reported_i):
                mismatch = True
        if mismatch:
            return ATTENTION
        if known == 0:
            return UNKNOWN
        if known < len(relevant):
            return UNKNOWN
        return OK

    # Mixed sizes with no genuine per-toolhead order: only known which SIZES
    # exist somewhere on the printer, never which toolhead a project's
    # filament assignment would land on — so the best this can ever prove is
    # set membership, and A4.4 forbids OK for an unproven assignment
    # regardless. ATTENTION only once every required position is known; any
    # required position still unknown -> UNKNOWN, never a premature ATTENTION
    # on a printer that has not fully answered.
    known_sizes = {_num(reported[i]) for i in required if i < len(reported) and reported[i] is not None}
    known_count = sum(1 for i in required if i < len(reported) and reported[i] is not None)
    all_known = known_count == len(required) and len(required) > 0
    if not all_known:
        return UNKNOWN
    if any(size not in known_sizes for size in wanted_nums):
        return ATTENTION
    return UNKNOWN  # assignment unproven — never OK for a mixed set


def _positions(confirmed: dict[int, dict], toolhead_count: int | None) -> list[dict]:
    count = toolhead_count if toolhead_count and toolhead_count > 0 else (
        (max(confirmed) + 1) if confirmed else 0)
    rows = []
    for toolhead in range(count):
        entry = confirmed.get(toolhead)
        if entry is None:
            rows.append({"toolhead": toolhead, "diameter": None, "source": "unknown",
                        "confirmed_at": None, "confirmed": None, "conflict": False,
                        "out_of_range": False})
        else:
            rows.append({"toolhead": toolhead, "diameter": entry["diameter"],
                        "source": "unknown" if entry["diameter"] is None else "user",
                        "confirmed_at": entry["confirmed_at"], "confirmed": entry["diameter"],
                        "conflict": False, "out_of_range": False})
    # Stored entries beyond the live/profile count are preserved, never
    # truncated, but flagged so the UI can offer to remove them rather than
    # silently acting on a toolhead this printer does not currently have.
    for toolhead in sorted(confirmed):
        if toolhead >= count:
            entry = confirmed[toolhead]
            rows.append({"toolhead": toolhead, "diameter": entry["diameter"],
                        "source": "unknown" if entry["diameter"] is None else "user",
                        "confirmed_at": entry["confirmed_at"], "confirmed": entry["diameter"],
                        "conflict": False, "out_of_range": True})
    return rows


def status(conn, host: str, port: int | None, *, live: list[float] | None = None,
          live_error: str | None = None, reachable: bool = False,
          toolhead_count: int | None = None,
          toolhead_count_source: str = "unknown", observed_at: str | None = None) -> dict:
    """The full snapshot the frozen `/nozzles/status` contract promises.

    ``live`` is the printer's own reading, when it has one — the caller
    (``service.py``) is the only thing that talks to Moonraker; this module
    only ever reads storage and joins it to whatever the caller already knows.

    ``live_error`` (plan A3.6's frozen set, round 3/Opus N7 documents the
    addition here): ``"unreachable"``, ``"timeout"``, ``"not_reported"``,
    ``"invalid_response"``, or ``"not_checked"`` — the last one only when the
    caller asked for ``probe=false`` (R2-B6) and never talked to the printer
    at all, as distinct from every other value, which means Studio DID try.
    """
    canon = canonical_host(host)
    p = int(port) if port else DEFAULT_PORT
    confirmed, revision = library.get_nozzle_confirmations(conn, canon, p)

    toolheads = _positions(confirmed, toolhead_count)
    count_mismatch = bool(live) and toolhead_count and len(live) != toolhead_count
    if live:
        for row in toolheads:
            if row["toolhead"] < len(live):
                row["diameter"] = live[row["toolhead"]]
                row["source"] = "printer"
                stored = confirmed.get(row["toolhead"])
                if (stored is not None and stored["diameter"] is not None
                        and abs(stored["diameter"] - live[row["toolhead"]]) > 1e-9):
                    row["conflict"] = True

    return {
        "host": canon, "port": p, "reachable": reachable, "live": live,
        "live_error": live_error, "toolhead_count": toolhead_count,
        "toolhead_count_source": toolhead_count_source, "revision": revision,
        "observed_at": observed_at, "count_mismatch": count_mismatch,
        "storage_error": None, "toolheads": toolheads,
    }


def confirm(conn, host: str, port: int | None, diameters: list, expected_revision: int,
           at: str) -> int:
    """Atomic replace. Raises `InvalidHost`, `ValueError("invalid_diameters")`
    or `StaleRevision`."""
    canon = canonical_host(host)
    p = int(port) if port else DEFAULT_PORT
    clean = validate_diameters(diameters)
    return library.replace_nozzle_confirmations(conn, canon, p, clean, at, int(expected_revision))


def clear(conn, host: str, port: int | None, expected_revision: int) -> int:
    """Idempotent: clearing an already-empty record still bumps the revision
    (the tombstone rule), and a stale caller still gets 409."""
    canon = canonical_host(host)
    p = int(port) if port else DEFAULT_PORT
    return library.clear_nozzle_confirmations(conn, canon, p, int(expected_revision))


def resolve(conn, host: str | None, port: int | None, live: list[float] | None,
           request_diameters: list[float | None] | None) -> dict:
    """The one shared precedence resolver every route joins against: LIVE >
    USER-CONFIRMED (a request list, if supplied, REPLACES the stored one
    entirely for this call only — it is never persisted) > stored > UNKNOWN.

    Returns ``{"diameters": [...] | None, "confirmed_by": "printer"|"user"|None,
    "confirmed_at": str|None, "revision": int, "conflicts": [...],
    "stored": {toolhead: {"diameter": float|None, "confirmed_at": str|None}}}``.

    ``stored`` is the raw per-toolhead confirmation record (revision-backed,
    including an explicit "not sure" ``diameter: None`` row), independent of
    whether it currently WINS the precedence — R2-B3 (Sol 3): a send
    fingerprint needs to see the stored note change even on a printer whose
    live reading already matches and always wins.
    """
    if live:
        confirmed, revision = ({}, 0)
        if host:
            try:
                canon = canonical_host(host)
                confirmed, revision = library.get_nozzle_confirmations(
                    conn, canon, int(port) if port else DEFAULT_PORT)
            except InvalidHost:
                confirmed, revision = ({}, 0)
        conflicts = []
        source_lists = []
        if request_diameters:
            source_lists.append(("request", {i: d for i, d in enumerate(request_diameters)}))
        source_lists.append(("stored", {i: v["diameter"] for i, v in confirmed.items()
                                        if v["diameter"] is not None}))
        for source, values in source_lists:
            for toolhead, value in values.items():
                if toolhead < len(live) and value is not None and abs(value - live[toolhead]) > 1e-9:
                    at = confirmed.get(toolhead, {}).get("confirmed_at") if source == "stored" else None
                    conflicts.append({"toolhead": toolhead, "printer": live[toolhead],
                                      "confirmed": value, "source": source, "confirmed_at": at})
        return {"diameters": live, "confirmed_by": "printer", "confirmed_at": None,
                "revision": revision, "conflicts": conflicts, "stored": confirmed}

    if request_diameters:
        # B6 (Opus M2): the request replaces the VALUE, never the revision —
        # `printer.nozzle_revision` must still report the real stored
        # revision (0 only when nothing has ever been stored), so a client
        # comparing revisions across routes never sees a false "nothing
        # stored" just because this call happened to carry a request-level
        # override.
        revision = 0
        confirmed = {}
        if host:
            try:
                canon = canonical_host(host)
                confirmed, revision = library.get_nozzle_confirmations(
                    conn, canon, int(port) if port else DEFAULT_PORT)
            except InvalidHost:
                revision = 0
        return {"diameters": request_diameters, "confirmed_by": "user", "confirmed_at": None,
                "revision": revision, "conflicts": [], "stored": confirmed}

    if host:
        try:
            canon = canonical_host(host)
        except InvalidHost:
            return {"diameters": None, "confirmed_by": None, "confirmed_at": None,
                    "revision": 0, "conflicts": [], "stored": {}}
        confirmed, revision = library.get_nozzle_confirmations(
            conn, canon, int(port) if port else DEFAULT_PORT)
        values = {i: v["diameter"] for i, v in confirmed.items() if v["diameter"] is not None}
        if values:
            count = max(values) + 1
            diameters = [values.get(i) for i in range(count)]
            latest_at = max((v["confirmed_at"] for v in confirmed.values() if v["confirmed_at"]),
                           default=None)
            return {"diameters": diameters, "confirmed_by": "user", "confirmed_at": latest_at,
                    "revision": revision, "conflicts": [], "stored": confirmed}
        return {"diameters": None, "confirmed_by": None, "confirmed_at": None,
                "revision": revision, "conflicts": [], "stored": confirmed}

    return {"diameters": None, "confirmed_by": None, "confirmed_at": None,
            "revision": 0, "conflicts": [], "stored": {}}
