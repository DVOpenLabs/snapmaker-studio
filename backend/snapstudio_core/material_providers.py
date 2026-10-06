"""Where Studio learns what filament is actually loaded.

Until now there was one answer: whatever the U1 reports over Moonraker. That is
the right default and it will stay the default, but it cannot answer the question
people keep asking — *do I have enough filament for this print?* — because a
printer knows which spool is in a slot and nothing about how much is left on it.

Other tools do know. Spoolman tracks spools and their remaining weight, U1Hub
keeps a loadout, and some firmware builds expose more than stock does. So this is
a seam, not an integration: each provider is read-only, optional, and normalises
to one shape that `material_plan` consumes without caring where it came from.

Three rules, and they are the reason this is a seam rather than a feature:

* **Nothing is required.** A stock U1 with no other software is a first-class
  setup and always will be.
* **Nothing is written.** Studio does not create, update, consume or delete
  anyone else's records. Reading someone's spool database and then quietly
  decrementing it is how two tools end up disagreeing about reality.
* **Nothing is invented.** A provider that cannot say how much filament is left
  reports `None`, and everything downstream treats that as unknown rather than
  as plenty.

Every service here lives on the local network at an address the user supplies,
exactly like the printer. Studio still makes no outbound internet requests.
"""
from __future__ import annotations

import contextvars
import datetime
import errno
import http.client
import ipaddress
import json
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import spoolease_wire

SCHEMA_VERSION = "materials/2"

#: One deadline per provider read, shared by every connect attempt of every
#: candidate address of every hop (initial request + redirects). Set by
#: `_fetch()` for the whole `_OPENER.open(...)` + body read and reset in a
#: `finally`; read by `_LocalOnlyHTTPConnection._left()`. `None` outside a
#: `_fetch()` call — production code never leaves it set.
_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar("_DEADLINE", default=None)

#: #53: the live sockets of the provider read in progress (every hop, every
#: candidate that connected), so a watchdog timer can shut them down at the
#: overall deadline. That is what bounds the parts of a read that no per-read
#: timeout can: dripped status lines and headers, the body of a redirect that
#: urllib drains for itself, and chunk-size lines / trailers inside one
#: `read1()`. `None` outside a `_fetch()` call.
_LIVE_SOCKETS: contextvars.ContextVar["_Watchdog | None"] = contextvars.ContextVar(
    "_LIVE_SOCKETS", default=None)


def _register_live_socket(sock) -> None:
    watchdog = _LIVE_SOCKETS.get()
    if watchdog is not None and sock is not None:
        watchdog.register(sock)


class InvalidProviderAddress(ValueError):
    """A provider address Studio will not turn into a request."""


class OffNetworkAddress(InvalidProviderAddress):
    """An `InvalidProviderAddress` raised specifically because the address is
    not on the user's own network — the typed host is not local, it resolves
    only to a public address, or a redirect walked off-network. Unlike a pure
    format refusal (bad scheme, credentials, a path, a bad port, ...), this is
    the one class of refusal `service._with_providers` replaces with a fixed
    host-free sentence for `provider_status.error` (S-2/M1, #39 r4) — kept as
    an `InvalidProviderAddress` subclass so every existing `except
    InvalidProviderAddress` and `isinstance` check still catches it."""


#: Name suffixes that mean "a machine on this network". A bare single-label name
#: (`spoolman`) is a LAN name too. Anything else with a dot in it is a public DNS
#: name, and Studio does not make requests to those.
_LOCAL_SUFFIXES = (".local", ".lan", ".home", ".internal", ".home.arpa")

_HOSTNAME_RE = re.compile(
    r"\A(?!-)[A-Za-z0-9_-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9_-]{1,63}(?<!-))*\.?\Z")


#: 6to4 (RFC 3056), Teredo (RFC 4380) and NAT64 (RFC 6052 well-known prefix,
#: RFC 8215 local-use prefix) all tunnel or synthesise traffic that actually
#: crosses the public internet — a 6to4 or Teredo packet is relayed by a
#: third-party host neither Studio nor the user controls, and a NAT64 address
#: exists specifically to reach an IPv4 host that may be anywhere. Python's
#: `ipaddress` module nonetheless marks every one of these prefixes
#: `is_private` (it follows the IANA special-purpose registry's "not globally
#: unique" wording, not "does not leave this network"), so `is_private` alone
#: is not the right test here and these ranges must be excluded explicitly.
_6TO4_NET = ipaddress.ip_network("2002::/16")
_TEREDO_NET = ipaddress.ip_network("2001::/32")
_NAT64_WELL_KNOWN_NET = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL_NET = ipaddress.ip_network("64:ff9b:1::/48")


def _is_internet_transit_tunnel(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """S-1: is this a 6to4/Teredo/NAT64 address, despite `is_private` saying
    "local"? Checked before `is_private` is trusted for anything, by both
    `_host_is_local` (the string the user typed) and `_ip_is_local` (what the
    resolver actually returned)."""
    if address.version != 6:
        return False
    return bool(
        address in _6TO4_NET or address in _TEREDO_NET
        or address in _NAT64_WELL_KNOWN_NET or address in _NAT64_LOCAL_NET)


def _name_resolves_locally(name: str) -> bool:
    """True when at least one address the resolver returns for `name` is on the user's own network (`_ip_is_local`).
    A resolution failure or an answer with only public addresses is not local."""
    try:
        answers = _resolve(name, None, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return False
    for answer in answers:
        try:
            if _ip_is_local(answer[4][0]):
                return True
        except (ValueError, IndexError, TypeError):
            continue
    return False

def _host_is_local(host: str) -> bool:
    """Is this address on the user's own network?

    Studio is local-first, and that is a promise about where requests go rather
    than a description of its architecture. A provider address is typed by the
    user into a settings box, so without this check that box is a way to make
    Studio fetch an arbitrary URL on the public internet — which is exactly what
    it says it never does.
    """
    name = host.strip().strip("[]").rstrip(".").lower()
    if not name:
        return False
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        if name == "localhost" or "." not in name:
            return True
        if name.endswith(_LOCAL_SUFFIXES):
            return True
        # v1.3.1 (#39): a private name that is NOT one of the conventional suffixes (a home or office domain such as
        # `spoolease.example.net` served by the user's own router) is local when what it RESOLVES to is local -- the
        # same test the connect layer applies to every address it dials. Judging it by a guessed suffix list refused
        # legitimate private FQDNs. A name that resolves only publicly, or not at all, is still refused here, and the
        # connect layer still only ever dials the local answers of a mixed result.
        return _name_resolves_locally(name)
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    if _is_internet_transit_tunnel(address):
        return False
    # 100.64/10 is carrier-grade NAT, which is also what Tailscale hands out; a
    # tailnet is the user's own network by any reasonable reading.
    return bool(
        address.is_loopback or address.is_private or address.is_link_local
        or address in ipaddress.ip_network("100.64.0.0/10")
        or (address.version == 6 and address.is_site_local))


def _address_error(out: dict, exc: InvalidProviderAddress) -> dict:
    """Fill a reader's error result from a caught `InvalidProviderAddress`,
    the same way in every reader.

    `error_code` stays `"invalid_address"` for every case, format refusals
    included — unchanged from before, and every existing caller keys on that
    string. `off_network` additionally records whether this was specifically
    an `OffNetworkAddress` (not local / resolves only publicly / a redirect
    left the network) as opposed to a pure format refusal (bad scheme,
    credentials, a path, a bad port, ...) — `service._with_providers` (S-2/M1)
    replaces `provider_status.error` with a fixed host-free sentence only for
    the former; a format refusal's own message is already host-free and must
    reach the user unchanged (#39 r4)."""
    out["error"] = str(exc)
    out["error_code"] = "invalid_address"
    out["off_network"] = isinstance(exc, OffNetworkAddress)
    return out


def validate_provider_url(value: str) -> str:
    """Return a normalised provider base URL, or raise InvalidProviderAddress.

    Accepts `http://spoolman.local:7912`, `http://192.168.1.9:7912`, a bare
    `spoolman:7912`. Refuses another scheme, credentials in the URL, a path,
    query or fragment, and any host that is not on the local network.

    The refusals are not paranoia about the user. `file://` made Studio read a
    local file, `ftp://` made it open an FTP connection, and a public hostname
    made it fetch a page from the internet — all three demonstrated against this
    function's predecessor, which passed the string straight to urllib.
    """
    text = (value or "").strip()
    if not text:
        raise InvalidProviderAddress("Enter the address of your material provider's server.")
    if len(text) > 255:
        raise InvalidProviderAddress("That address is too long to be a server address.")
    if "://" not in text:
        text = "http://" + text
    parts = urllib.parse.urlsplit(text)
    if parts.scheme not in ("http", "https"):
        raise InvalidProviderAddress(
            "Studio only reads providers over http or https on your own network.")
    if parts.username or parts.password:
        raise InvalidProviderAddress(
            "Put the server's address here on its own — Studio does not send a "
            "username or password in a URL.")
    if parts.query or parts.fragment or parts.path.strip("/"):
        raise InvalidProviderAddress(
            "Enter just the server's address and port, without a path.")
    host = parts.hostname
    if not host:
        raise InvalidProviderAddress("That doesn't look like a server address.")
    if not _HOSTNAME_RE.match(host) and ":" not in host:
        raise InvalidProviderAddress("That doesn't look like a server address.")
    # #54: parse the port BEFORE classifying locality, so a malformed port on a
    # public address gets the more specific bad-port message.
    try:
        port = parts.port
    except ValueError as exc:
        raise InvalidProviderAddress("That port is not a number.") from exc
    if not _host_is_local(host):
        raise OffNetworkAddress(
            f"{host} is not an address on your own network. Studio reads material "
            "providers running on your network only — it makes no requests to the "
            "internet.")
    authority = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{authority}" + (f":{port}" if port else "")

STOCK = "stock-u1"
SPOOLMAN = "spoolman"
BAMBUDDY = "bambuddy"
SPOOLEASE = "spoolease"
LOCAL = "local"

#: The network providers a user can choose, and what to call them on screen —
#: the ones reachable through `read()`/`READERS` below. LOCAL is deliberately
#: not here: it has no address to read, no `READERS` entry, and its own
#: dedicated functions (`local_spools`, and the library-backed writes in
#: `snapstudio_api.service`) rather than the network seam this table serves.
PROVIDER_NAMES = {SPOOLMAN: "Spoolman", BAMBUDDY: "Bambuddy", SPOOLEASE: "SpoolEase"}

CONFIRMED = "confirmed"
LIKELY = "likely"
UNKNOWN = "unknown"

#: How a remaining weight came to be known. Nothing here is ever a measurement:
#: no spool holder on a U1 weighs filament, so the best available is a figure some
#: other tool — or the person themselves — has been keeping track of.
TRACKED = "tracked"                # an external provider states a remaining weight
USER_CONFIRMED = "user_confirmed"  # the person weighed or looked and typed a figure just now
DERIVED = "derived"                # computed from a net/last-confirmed weight minus what was used
UNTRACKED = "unknown"              # nothing knows

#: More than this on one spool is not filament, it is a units mistake or a typo.
#: A 5 kg spool is a real product; 25 kg on one U1 slot is not.
IMPLAUSIBLE_GRAMS = 25_000


#: Who established that something is in this slot. The distinction the whole
#: multi-printer story turns on: a printer that reports its own filament state has
#: *looked*, while a provider mapping is a person writing down what they believe
#: they loaded. On a machine that reports no filament state at all — most Klipper
#: printers — a provider is the only source, and it must not be dressed up as the
#: machine having confirmed anything.
BY_PRINTER = "printer"
BY_PROVIDER = "provider"


def _slot(index: int, *, material=None, subtype=None, color=None, vendor=None,
          spool_id=None, remaining_g=None, source=STOCK, confidence=CONFIRMED,
          present=True, remaining_quality=UNTRACKED, remaining_as_of=None,
          notes=None, confirmed_by=None) -> dict:
    """One normalised slot. Absent facts stay absent."""
    return {
        "slot": index,
        "present": present,
        "confirmed_by": confirmed_by,
        "material": material,          # family, e.g. "PLA"
        "subtype": subtype,            # e.g. "Matte", when the source says so
        "color": color,
        "vendor": vendor,
        "spool_id": spool_id,
        "remaining_g": remaining_g,
        # How much to trust that number, and when it was last touched. A blocker
        # ("this print will run out") may only be built on a figure that says
        # where it came from.
        "remaining_quality": remaining_quality if remaining_g is not None else UNTRACKED,
        "remaining_as_of": remaining_as_of,
        "source": source,
        "confidence": confidence,
        "notes": list(notes or ()),
    }


def _family_and_subtype(value: str | None) -> tuple[str | None, str | None]:
    """"PLA Matte" -> ("PLA", "Matte")."""
    if not value:
        return None, None
    parts = str(value).strip().split(None, 1)
    if not parts:
        return None, None
    return parts[0].upper(), (parts[1] if len(parts) > 1 else None)


# --- stock U1 ----------------------------------------------------------------

def _source_phrase(source_id: str) -> str:
    """A plain-language name for a provenance source id — B4 (Opus M5/Sol 5):
    a conflict sentence must never echo a raw internal id ("local",
    "spoolman", "stock-u1") to a person reading it."""
    if source_id == STOCK:
        return "the printer"
    name = PROVIDER_NAMES.get(source_id)
    if name:
        return f"your provider ({name})"
    if source_id == LOCAL:
        return "your note"
    return "another source"


def _says(source_id: str) -> str:
    """"the printer reports" / "your provider (Spoolman) says" / "your note
    says" — the verb the printer gets is "reports" (it looked); everything
    else "says" (someone's record of what they believe)."""
    phrase = _source_phrase(source_id)
    return f"{phrase} reports" if source_id == STOCK else f"{phrase} says"


def _describe_disagreement(mine_source: str, mine_value, theirs_source: str, theirs_value) -> str:
    """B4: names the real source on BOTH sides, and only credits the printer
    with 'Studio is using what the printer can see' when the value Studio
    actually kept came from the printer — never for a provider/note value
    that merely happened to arrive first."""
    mine_txt = f"{_says(mine_source)} {mine_value}"
    theirs_txt = f"{_says(theirs_source)} {theirs_value}"
    if mine_source == STOCK:
        return f"{mine_txt} in this slot and {theirs_txt} — Studio is using what the printer can see"
    return f"{mine_txt} in this slot and {theirs_txt} — Studio kept {mine_value}"


def add_note_conflicts(state: dict, conflicts: list[dict]) -> dict:
    """A3.4/A2.8: fold a local-spool alias collision into the LOCAL provider
    state — a ``note_conflicts`` field for the UI, plus a synthetic slot entry
    per collided slot that carries NO material/colour/weight facts at all,
    only the conflict note. It is deliberately ``present=True`` with no
    material: `material_plan.plan()` reads an index with a `have` dict but no
    family on either side as state ``unknown`` (never the ``have is None``
    branch that produces ``empty``) — A4.1's regression is exactly this: two
    colliding notes and no printer reading must never read as a BLOCKER.
    """
    if not conflicts:
        return state
    out = dict(state)
    out["note_conflicts"] = list(conflicts)
    out["available"] = True
    slots = list(out.get("slots") or [])
    covered = {s["slot"] for s in slots}
    for c in conflicts:
        if c["slot"] in covered:
            continue
        slots.append(_slot(
            c["slot"], present=True, material=None, subtype=None, color=None, vendor=None,
            remaining_g=None, source=LOCAL, confidence=UNKNOWN, confirmed_by=None,
            notes=[f"two notes exist for slot {c['slot'] + 1} — remove one in Settings"]))
    out["slots"] = slots
    return out


def stock_from_facts(printer: dict) -> dict:
    """The STOCK provider shape, built from a printer read `service.py`
    already did (``printer["loaded_filaments"]``) rather than a second,
    independent read of the printer.

    A1.11 (Opus D-10): the previous version of `service._with_providers`
    called `stock_u1(host, port)` itself — a SECOND live read, after
    `printer_facts()` had already read the same thing once. If that second
    read failed or answered differently (a printer that changed state between
    the two calls, or simply flaked once), `combine()` would treat the STOCK
    source as entirely unavailable and let a local note or provider fill in
    material the printer had, moments earlier, already confirmed — silently
    replacing live evidence with a guess. Building STOCK from the facts
    already in hand makes that impossible: there is only ever one printer
    read per request, and this is a pure reshaping of it.
    """
    loaded = printer.get("loaded_filaments") if printer else None
    out = {"schema_version": SCHEMA_VERSION, "source": STOCK, "available": False,
          "slots": [], "remaining_known": False}
    if loaded is None:
        return out
    out["available"] = True
    for index, entry in enumerate(loaded):
        if not entry:
            out["slots"].append(_slot(index, present=False, confirmed_by=BY_PRINTER))
            continue
        family, subtype = _family_and_subtype(entry.get("material"))
        out["slots"].append(_slot(
            index, material=family, subtype=subtype, color=entry.get("color"),
            vendor=entry.get("vendor"), source=STOCK, confidence=CONFIRMED,
            confirmed_by=BY_PRINTER))
    return out


def stock_u1(host: str, port: int = 7125) -> dict:
    """What the printer itself reports. The default, and the only one always available."""
    from . import moonraker

    out = {"schema_version": SCHEMA_VERSION, "source": STOCK, "available": False, "slots": []}
    if not host:
        out["error"] = "no printer address configured"
        return out
    try:
        loaded = moonraker.loaded_filaments(host, port)
    except moonraker.PrinterUnavailable as exc:
        out["error"] = f"Studio could not reach the printer just now: {exc}"
        return out
    except Exception as exc:  # noqa: BLE001 — a printer that will not answer is an answer
        out["error"] = f"the printer did not answer: {type(exc).__name__}"
        return out
    if loaded is None:
        out["error"] = "this printer does not report which filaments are loaded"
        return out

    out["available"] = True
    for index, entry in enumerate(loaded):
        if not entry:
            out["slots"].append(_slot(index, present=False, confirmed_by=BY_PRINTER))
            continue
        family, subtype = _family_and_subtype(entry.get("material"))
        out["slots"].append(_slot(
            index, material=family, subtype=subtype, color=entry.get("color"),
            vendor=entry.get("vendor"), source=STOCK, confidence=CONFIRMED,
            confirmed_by=BY_PRINTER))
    # A printer knows what is loaded and nothing about how much is left on it.
    out["remaining_known"] = False
    return out


# --- Spoolman ----------------------------------------------------------------

def _is_timeout(exc: BaseException) -> bool:
    """A plain `TimeoutError`, or a `URLError` wrapping one — `_fetch`'s shared
    deadline can raise either shape depending on where the time ran out
    (connect vs. a later read), and both mean the same thing to the reader."""
    if isinstance(exc, TimeoutError):
        return True
    return isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, TimeoutError)


def _timeout_sentence(name: str, timeout: float) -> str:
    """plan-39 v3.2 N-4: the same pattern for every provider's timeout, in
    `provider_status.error` and in a reader's own `error` field alike."""
    return (f"{name} did not answer in time (Studio waited about {timeout:g} "
            "seconds), so Studio carried on without it.")


class _LocalOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse a redirect that walks off the user's own network.

    `validate_provider_url` checks the address the user typed, and that was not
    enough. A service on the LAN answering 302 with a `Location` on the public
    internet made Studio follow it, and the request genuinely left the machine —
    demonstrated against this module, not imagined: a local server that answered
    every request with `302 → http://example.com` produced example.com's 404 in
    Studio's own error message.

    That is the same defect as the one the address check was written for, one
    hop later, and it is fixed in the same place for every provider rather than
    in whichever adapter happened to notice.

    It also refuses a redirect that STAYS local but changes *host* while an
    Authorization header is on the request. No provider reader sends one today
    — none of them supports a credential yet — but `urllib`'s own redirect
    handling forwards every header, Authorization included, to whatever new
    host a `Location` names. That is the confused-deputy problem most HTTP
    clients have had to patch at some point, and the fix belongs here, once,
    before any provider is allowed to hold a credential — not added later as a
    follow-up once something has already had the chance to leak.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if parts.scheme not in ("http", "https") or not _host_is_local(parts.hostname or ""):
            raise OffNetworkAddress(
                f"That provider redirected Studio to {parts.hostname or newurl}, which is "
                "not on your own network. Studio makes no requests to the internet, so it "
                "stopped rather than following it.")
        original_host = (urllib.parse.urlsplit(req.full_url).hostname or "").lower()
        new_host = (parts.hostname or "").lower()
        if new_host != original_host and any(name.lower() == "authorization" for name in req.headers):
            raise InvalidProviderAddress(
                "That provider redirected Studio to a different host on a "
                "request that carried credentials. Studio does not forward credentials to a "
                "host that never received them directly, so it stopped rather than following "
                "the redirect.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _ip_is_local(text: str) -> bool:
    """Is this resolved address on the user's own network? (plan-39 O-1)

    Unlike `_host_is_local`, this checks an address the *resolver* returned,
    not the string the user typed — so a name Studio accepted (a bare LAN
    name, or one ending `.local`/`.lan`/...) is still refused at connect time
    if DNS answers with something off-network, and a name that resolves to
    both a LAN and a public address is only ever dialled on the LAN one.
    """
    address = ipaddress.ip_address(text)
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    if _is_internet_transit_tunnel(address):
        return False
    return bool(
        address.is_loopback or address.is_private or address.is_link_local
        or address in ipaddress.ip_network("100.64.0.0/10")
        or (address.version == 6 and address.is_site_local))


#: `socket.getaddrinfo`, called through a module attribute so tests can stub
#: it without touching the real resolver. Production code never reassigns it.
_resolve = socket.getaddrinfo


class _FatalConnect(Exception):
    """Wraps a `setsockopt` failure that is not `ENOPROTOOPT` (plan-39 addendum
    §1/§3): it must surface as the underlying `OSError`, not be treated as a
    failed candidate to try the next address for."""

    def __init__(self, exc: OSError):
        super().__init__(str(exc))
        self.exc = exc


class _LocalOnlyHTTPConnection(http.client.HTTPConnection):
    """An `HTTPConnection` that only ever dials an address on the user's own
    network — checked against what the resolver actually returned, not the
    name that was typed (plan-39 §3.1, amended by the addendum §1 for the
    per-candidate connect deadline).
    """

    def connect(self):
        sys.audit("http.client.connect", self, self.host, self.port)
        # A resolver failure (e.g. `socket.gaierror`) is left to propagate as
        # the raw `OSError` here, exactly as stdlib's own `HTTPConnection.connect`
        # does — `urllib.request.AbstractHTTPHandler.do_open()` catches OSError
        # and wraps it into a URLError exactly once. `URLError` is itself an
        # `OSError` subclass, so wrapping it here as well would let do_open's
        # except-clause catch it a second time and produce a URLError whose
        # `.reason` is another URLError instead of the resolver's own
        # exception — the double-wrap plan-39 B-1 named (it showed up as
        # "<urlopen error ...>" for Spoolman/Bambuddy and the bare class name
        # "URLError" for SpoolEase, instead of the resolver's own reason).
        answers = _resolve(self.host, self.port, type=socket.SOCK_STREAM)
        local = [a for a in answers if _ip_is_local(a[4][0])]
        if not local:
            raise OffNetworkAddress(
                f"{self.host} has no address on your own network, so Studio did "
                "not connect. Enter the provider's local network address "
                "instead (for example its 192.168.x.x address).")
        last: OSError | None = None
        for index, (family, kind, proto, _canon, sockaddr) in enumerate(local):
            slice_seconds = self._slice(len(local) - index)
            sock = None
            try:
                sock = socket.socket(family, kind, proto)
                sock.settimeout(slice_seconds)
                sock.connect(sockaddr)
                if not _ip_is_local(sock.getpeername()[0]):
                    # Belt-and-braces: the resolver answered with something
                    # local and the socket ended up connected to something
                    # that is not. Should be unreachable; refused anyway.
                    raise OffNetworkAddress(
                        f"{self.host} connected to an address that is not on "
                        "your own network, so Studio stopped.")
                try:
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError as exc:
                    # Exactly what stdlib's own HTTPConnection.connect does:
                    # a platform that has no TCP_NODELAY option is fine; any
                    # other failure is real and must not be swallowed as
                    # though this candidate merely failed to connect.
                    if exc.errno != errno.ENOPROTOOPT:
                        raise _FatalConnect(exc) from exc
                # Bounds every later read op (status line, headers, body) by
                # the base per-operation timeout — not by what is left of the
                # shared connect deadline, so a slow-but-connected provider
                # gets the same per-recv budget it always did.
                sock.settimeout(self.timeout if self.timeout is not
                                socket._GLOBAL_DEFAULT_TIMEOUT else None)
            except InvalidProviderAddress:
                if sock is not None:
                    sock.close()
                raise
            except _FatalConnect as wrapped:
                if sock is not None:
                    sock.close()
                raise wrapped.exc
            except OSError as exc:  # incl. a TimeoutError from this slice
                if sock is not None:
                    sock.close()
                last = exc
                continue
            self.sock = sock
            _register_live_socket(sock)
            return
        raise last or OSError(f"could not connect to {self.host}")

    def _left(self) -> float | None:
        """Time left on the shared per-read deadline, or the connection's own
        base timeout when there is no deadline (a direct call outside
        `_fetch()`, e.g. a test)."""
        base = None if self.timeout is socket._GLOBAL_DEFAULT_TIMEOUT else self.timeout
        deadline = _DEADLINE.get()
        if deadline is None:
            return base
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("the provider read ran out of time")
        return left if base is None else min(base, left)

    def _slice(self, remaining_candidates: int) -> float | None:
        """This candidate's even share of the time left (addendum §1): a
        black-holed candidate can consume only its own slice, never the whole
        deadline, so the candidates after it still get a real chance."""
        left = self._left()
        if left is None:
            return None
        return left / max(1, remaining_candidates)


class _LocalOnlyHTTPSConnection(_LocalOnlyHTTPConnection, http.client.HTTPSConnection):
    def connect(self):
        super().connect()
        try:
            # #53: wrap WITHOUT the implicit handshake, register the TLS socket
            # (wrapping detaches the plain one `super().connect()` registered),
            # and only then handshake -- so a peer that stalls the handshake can
            # still be cut off by the overall-deadline watchdog.
            self.sock = self._context.wrap_socket(
                self.sock, server_hostname=self.host, do_handshake_on_connect=False)
            _register_live_socket(self.sock)
            self.sock.do_handshake()
        except Exception:
            self.sock.close()
            self.sock = None
            raise


class _LocalOnlyHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_LocalOnlyHTTPConnection, req)


class _LocalOnlyHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_LocalOnlyHTTPSConnection, req, context=self._context)


def _build_opener(context=None) -> urllib.request.OpenerDirector:
    """One opener builder for every provider (and for tests that need a
    fresh one with a specific TLS context), so the local-only rule and the
    redirect rule cannot be true of one and not another.

    `ProxyHandler({})` disables environment- and system-configured proxies
    for provider reads: a proxy is a third host that would resolve the name
    on Studio's behalf and could defeat the local-only check entirely.
    """
    return urllib.request.build_opener(
        _LocalOnlyRedirects, _LocalOnlyHTTPHandler,
        _LocalOnlyHTTPSHandler(context=context), urllib.request.ProxyHandler({}))


#: One opener for every provider, so the redirect rule cannot be true of one and
#: not another. Deliberately not the module-level default: replacing the global
#: opener would change behaviour for code that has nothing to do with providers.
_OPENER = _build_opener()

#: What a single provider read will take from the network, at most. Every
#: reader shares this cap; a provider that tries to send more is refused, not
#: read in pieces.
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class _ProviderTransportError(Exception):
    """An I/O-shaped failure a reader maps to its own error vocabulary.

    Deliberately not `SpoolEaseWireError` (that is a wire-decode failure, not
    a network one) and not a subclass of `OSError`/`HTTPException` (so it
    cannot be mistaken for one by an except-clause that catches those).
    `code` is `"oversized"` or `"transport"` (an early close after a partial,
    under-length body — plan-39 v3.3 C-4b) — never anything a caller has to
    string-match to tell the two apart.
    """

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _transport_error_sentence(name: str, exc: "_ProviderTransportError") -> str:
    """POLISH: Spoolman/Bambuddy must never show this private class's own
    name (`_ProviderTransportError answered with something unexpected: ...`)
    for an oversized or short-and-truncated body — the same two plain
    sentences SpoolEase's own §4.2 rows 7/9 use, with the provider's name in
    place of "SpoolEase"."""
    if exc.code == "oversized":
        return (f"{name} sent more than Studio will read from a provider "
                "(4 MB), so Studio stopped.")
    return f"{name} did not answer: the response ended before it said it would"


class _Watchdog:
    """#53: at the overall deadline, shut down every live socket of the read in
    progress. A per-read socket timeout is an inactivity timeout, so a peer
    that keeps dripping bytes (status line, headers, a redirect body urllib
    drains for itself, chunk framing) can outlive it; shutting the socket down
    makes whatever read is blocked return at once, and `_fetch` then reports a
    plain timeout. Needs no private stdlib attribute."""

    def __init__(self, seconds: float):
        self.fired = threading.Event()
        self.sockets: list = []
        self._lock = threading.Lock()
        self._timer = threading.Timer(max(seconds, 0.0), self._trip)
        self._timer.daemon = True

    @staticmethod
    def _shutdown(sock) -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except (OSError, ValueError):
            pass

    def register(self, sock) -> None:
        """Track a live socket. Registration and the trip are serialised by
        one lock, so a socket that connects just as the deadline passes is
        shut down at once instead of being missed by the one-shot timer."""
        with self._lock:
            self.sockets.append(sock)
            already_fired = self.fired.is_set()
        if already_fired:
            self._shutdown(sock)

    def _trip(self) -> None:
        with self._lock:
            self.fired.set()
            sockets = list(self.sockets)
        for sock in sockets:
            self._shutdown(sock)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.cancel()


def _fetch(url: str, *, timeout: float = 4.0, accept: str = "application/json",
          limit: int = _MAX_RESPONSE_BYTES) -> bytes:
    """GET `url`, bounded by one deadline shared across every connect attempt
    of every candidate of every hop, and by `limit` bytes of body. Raises
    stdlib's own `urllib.error.URLError`/`HTTPError`, `TimeoutError`, or
    `_ProviderTransportError` (oversized / truncated body) — callers translate
    those into their own error vocabulary.
    """
    request = urllib.request.Request(url, headers={"Accept": accept})
    deadline = time.monotonic() + timeout
    token = _DEADLINE.set(deadline)
    watchdog = _Watchdog(timeout)
    live_token = _LIVE_SOCKETS.set(watchdog)
    watchdog.start()
    try:
        try:
            return _read_bounded(request, timeout, deadline, watchdog, limit)
        except Exception:
            # #53: once the deadline has passed and the watchdog has shut a
            # socket down, whatever error that caused (EOF, a reset, a short
            # chunk) is a timeout, not a transport fault.
            if watchdog.fired.is_set():
                raise TimeoutError("the provider read ran out of time") from None
            raise
    finally:
        watchdog.stop()
        _LIVE_SOCKETS.reset(live_token)
        _DEADLINE.reset(token)


def _read_bounded(request, timeout: float, deadline: float, watchdog: "_Watchdog",
                  limit: int) -> bytes:
    """The body of `_fetch`. #53: the overall deadline (`time.monotonic()`) is
    checked between every body read, and the watchdog shuts the sockets down
    at the deadline so a read blocked inside the stdlib — headers, a redirect
    body, chunk framing — cannot outlive it either."""
    with _OPENER.open(request, timeout=timeout) as response:
        chunks: list[bytes] = []
        received = 0
        while received <= limit:
            if deadline - time.monotonic() <= 0:
                raise TimeoutError("the provider read ran out of time")
            chunk = response.read1(min(65536, limit + 1 - received))
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
        if watchdog.fired.is_set():
            raise TimeoutError("the provider read ran out of time")
        body = b"".join(chunks)
        if len(body) > limit:
            raise _ProviderTransportError(
                "oversized", "response exceeded the size Studio will read")
        declared = response.getheader("Content-Length")
        if declared is not None:
            try:
                declared_n = int(declared)
            except ValueError:
                raise _ProviderTransportError(
                    "transport", "the response's Content-Length was not a number")
            if declared_n != len(body):
                # `resp.read(limit + 1)` can return a short body at EOF
                # without raising (plan-39 v3.3 C-4b) — an early close
                # after a partial body must be caught explicitly, not
                # treated as a complete-but-short answer.
                raise _ProviderTransportError(
                    "transport", "the response ended before it said it would")
        return body


def _get_json(url: str, timeout: float = 4.0):
    return json.loads(_fetch(url, timeout=timeout, accept="application/json")
                      .decode("utf-8", "replace"))


def _get_text(url: str, timeout: float = 4.0) -> str:
    return _fetch(url, timeout=timeout, accept="text/plain").decode("utf-8", "replace")


def spoolman(base_url: str, slot_map: dict | None = None, timeout: float = 4.0,
             slot_base: int | None = None) -> dict:
    """Read spools from a Spoolman instance on the local network.

    Read-only, and deliberately so: Studio does not create spools and does not
    decrement anyone's remaining weight. Consumption tracking belongs to the tool
    that owns the data.

    ``slot_map`` maps a printer slot to a Spoolman spool id, because Spoolman
    does not know which slot a spool is in — the user does. Without it, Studio
    reports the spools it can see and does not pretend to know where they are.
    """
    out = {"schema_version": SCHEMA_VERSION, "source": SPOOLMAN, "available": False,
           "slots": [], "spools": []}
    if not base_url:
        out["error"] = "no Spoolman address configured"
        return out

    try:
        root = validate_provider_url(base_url)
    except InvalidProviderAddress as exc:
        return _address_error(out, exc)
    try:
        # Spoolman leaves archived spools out of this list unless asked. Studio
        # asks for them: a slot mapped to a spool somebody archived last week
        # should read as "that spool is archived", not as "there is no such
        # spool", which is what it said while this parameter was missing — and
        # which every mocked test agreed with, because a mock returns whatever
        # it was handed.
        spools = _get_json(f"{root}/api/v1/spool?allow_archived=true", timeout=timeout)
    except InvalidProviderAddress as exc:
        # A redirect that led off the local network. Refused mid-request, and
        # said plainly, because it is the user's network that just behaved oddly.
        return _address_error(out, exc)
    except _ProviderTransportError as exc:
        out["error"] = _transport_error_sentence("Spoolman", exc)
        return out
    except Exception as exc:  # noqa: BLE001
        if _is_timeout(exc):
            out["error"] = _timeout_sentence("Spoolman", timeout)
        elif isinstance(exc, urllib.error.URLError):
            out["error"] = f"Spoolman did not answer: {_host_free_reason(exc)}"
        else:
            out["error"] = f"Spoolman answered with something unexpected: {type(exc).__name__}"
        return out

    if not isinstance(spools, list):
        out["error"] = "Spoolman answered with something unexpected"
        return out

    out["available"] = True
    for spool in spools:
        if not isinstance(spool, dict):
            continue
        filament = spool.get("filament") or {}
        vendor = (filament.get("vendor") or {}).get("name")
        family, subtype = _family_and_subtype(filament.get("material"))
        remaining, quality, notes = _remaining(spool, filament)
        out["spools"].append({
            "id": spool.get("id"),
            "material": family,
            "subtype": subtype,
            "color": _colour(filament.get("color_hex")),
            "vendor": vendor,
            "remaining_g": remaining,
            "remaining_quality": quality,
            # When this figure was last true. `last_used` is the only field a
            # real Spoolman has that means that; `registered` is when the spool
            # was added, which is not the same thing and must not stand in for
            # it. A spool nothing has printed from has no such date, and that is
            # the common case rather than the odd one.
            "remaining_as_of": spool.get("last_used") or None,
            "registered": spool.get("registered") or None,
            "notes": notes,
            "name": filament.get("name"),
            "archived": bool(spool.get("archived")),
        })
    out["remaining_known"] = any(s["remaining_g"] is not None for s in out["spools"])

    _attach_slots(out, SPOOLMAN, slot_map, slot_base)
    return out


def _attach_slots(out: dict, source: str, slot_map: dict | None,
                  slot_base: int | None) -> None:
    """Turn the user's slot-to-spool map into normalised slots, for any provider.

    Shared deliberately. A filament inventory knows what spools exist and not
    which one a person pushed into slot 2, so every provider Studio can read
    needs exactly this step — and every provider must reach the same verdict for
    a mapping that points nowhere, or at something archived. Writing it once is
    what makes that true rather than hoped for.
    """
    name = PROVIDER_NAMES.get(source, source)
    # str() on both sides: SpoolEase spool ids are decimal strings while
    # Spoolman/Bambuddy ids are numbers, and a persisted slot map may hold
    # either shape depending on when it was saved — comparing as text means
    # neither provider needs the map to have been written in its own idiom.
    by_id = {str(s["id"]): s for s in out["spools"]}
    mapped, base = _mapped_slots(slot_map, slot_base)
    out["slot_base"] = base
    for slot_index, spool_id in mapped:
        spool = by_id.get(str(spool_id))
        if not spool:
            out["slots"].append(_slot(slot_index, present=False, source=source,
                                      confidence=UNKNOWN, confirmed_by=BY_PROVIDER,
                                      notes=[f"no spool with id {spool_id} in {name}"]))
            continue
        notes = list(spool["notes"])
        if spool["archived"]:
            notes.append(f"this spool is archived in {name}")
        out["slots"].append(_slot(
            slot_index, material=spool["material"], subtype=spool["subtype"],
            color=spool["color"], vendor=spool["vendor"], spool_id=spool["id"],
            remaining_g=spool["remaining_g"], source=source,
            remaining_quality=spool["remaining_quality"],
            remaining_as_of=spool["remaining_as_of"], notes=notes,
            # The user told Studio which spool is in which slot. That is a
            # statement of intent, not a measurement the printer confirmed.
            confidence=LIKELY, confirmed_by=BY_PROVIDER))


# --- Bambuddy ----------------------------------------------------------------

def bambuddy(base_url: str, slot_map: dict | None = None, timeout: float = 4.0,
             slot_base: int | None = None) -> dict:
    """Read spools from a Bambuddy instance on the local network.

    The second implementation of this seam, and chosen partly because it agrees
    with Spoolman about almost nothing at the wire: a versioned FastAPI service
    on `/api/v1/inventory/spools`, `brand` rather than a nested vendor object,
    `rgba` rather than `color_hex`, `material` and `subtype` as separate fields
    rather than one string to split, `include_archived` rather than
    `allow_archived` — and, decisively, **no remaining-weight field at all**.

    Read-only like every provider here. Bambuddy has routes that would create,
    archive and reweigh spools; Studio calls none of them.
    """
    out = {"schema_version": SCHEMA_VERSION, "source": BAMBUDDY, "available": False,
           "slots": [], "spools": []}
    if not base_url:
        out["error"] = "no Bambuddy address configured"
        return out

    try:
        root = validate_provider_url(base_url)
    except InvalidProviderAddress as exc:
        return _address_error(out, exc)
    try:
        # Archived spools are left out of the default listing, exactly as
        # Spoolman leaves them out of its own — measured against a real instance,
        # 10 spools with this parameter and 9 without. A slot mapped to a spool
        # somebody archived last week should read as archived, not as missing.
        spools = _get_json(f"{root}/api/v1/inventory/spools?include_archived=true",
                           timeout=timeout)
    except InvalidProviderAddress as exc:
        return _address_error(out, exc)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            # Bambuddy can be run with authentication on, and then every route
            # wants an `X-API-Key`. Studio has nowhere safe to keep one, so it
            # says so instead of asking for a secret it would store in the clear.
            out["error"] = ("Bambuddy is asking Studio to sign in. Studio reads providers "
                            "without credentials, so use a Bambuddy that does not require "
                            "an API key.")
            return out
        out["error"] = f"Bambuddy did not answer: HTTP {exc.code}"
        return out
    except _ProviderTransportError as exc:
        out["error"] = _transport_error_sentence("Bambuddy", exc)
        return out
    except Exception as exc:  # noqa: BLE001
        if _is_timeout(exc):
            out["error"] = _timeout_sentence("Bambuddy", timeout)
        elif isinstance(exc, urllib.error.URLError):
            out["error"] = f"Bambuddy did not answer: {_host_free_reason(exc)}"
        else:
            out["error"] = f"Bambuddy answered with something unexpected: {type(exc).__name__}"
        return out

    if not isinstance(spools, list):
        out["error"] = "Bambuddy answered with something unexpected"
        return out

    out["available"] = True
    for spool in spools:
        if not isinstance(spool, dict):
            continue
        remaining, quality, as_of, notes = _bambuddy_remaining(spool)
        family, subtype = _bambuddy_material(spool)
        out["spools"].append({
            "id": spool.get("id"),
            "material": family,
            "subtype": subtype,
            "color": _colour(spool.get("rgba")),
            "vendor": _text(spool.get("brand")),
            "color_name": _text(spool.get("color_name")),
            "remaining_g": remaining,
            "remaining_quality": quality,
            "remaining_as_of": as_of,
            # `created_at` is when the row was written. It is not when anything
            # about the filament was last true, and it is not offered as one.
            "registered": spool.get("created_at") or None,
            "notes": notes,
            "name": _text(spool.get("color_name")),
            "archived": bool(spool.get("archived_at")),
        })
    out["remaining_known"] = any(s["remaining_g"] is not None for s in out["spools"])

    _attach_slots(out, BAMBUDDY, slot_map, slot_base)
    return out


def _bambuddy_material(spool: dict) -> tuple[str | None, str | None]:
    """Bambuddy keeps the family and the variant apart, so there is nothing to split."""
    family = _text(spool.get("material"))
    return (family.upper() if family else None), _text(spool.get("subtype"))


def _bambuddy_remaining(spool: dict) -> tuple[float | None, str, object, list[str]]:
    """How much is left on a Bambuddy spool, how that is known, and when it was true.

    Bambuddy has no remaining-weight field. It stores what the label claimed and
    what has been used, and its own interface subtracts one from the other — so
    the figure is arithmetic Studio performs, and it is never dressed up as
    something Bambuddy is keeping.

    The same evidence test as everywhere else decides the label. A weighing wrote
    both the used figure and the moment it was taken, so that is a record with a
    date. A used figure that print consumption has been moving is a record too,
    dated by `last_used`. What is left — a label weight minus a number nothing has
    touched since the spool was added — is arithmetic, and says so.
    """
    notes: list[str] = []
    label = _number(spool.get("label_weight"))
    used = _number(spool.get("weight_used"))
    if label is None or label <= 0 or used is None:
        # Nothing to subtract from. Unknown, which is what a person needs to hear
        # to go and look at the spool — and said out loud, because a silent
        # unknown reads as though Studio never asked.
        notes.append(_no_quantity_note(BAMBUDDY))
        return None, UNTRACKED, None, notes

    if used < 0:
        notes.append("Bambuddy reports a negative used weight for this spool, so Studio "
                     "cannot work out what is left")
        return None, UNTRACKED, None, notes
    if label > IMPLAUSIBLE_GRAMS:
        notes.append(f"Bambuddy reports a {label:g} g spool, which is not a weight of "
                     "filament — check the spool in Bambuddy")
        return None, UNTRACKED, None, notes

    value = round(label - used, 1)
    if value < 0:
        notes.append(f"Bambuddy records more used ({used:g} g) than this spool ever held "
                     f"({label:g} g), so Studio cannot use it")
        return None, UNTRACKED, None, notes

    weighed_at = spool.get("last_weighed_at")
    if weighed_at and _number(spool.get("last_scale_weight")) is not None:
        return value, TRACKED, weighed_at, notes
    last_used = spool.get("last_used")
    if last_used and used:
        return value, TRACKED, last_used, notes
    return value, DERIVED, last_used or None, notes


def _text(value) -> str | None:
    """A non-empty string, or nothing. A provider may send either."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# --- SpoolEase -----------------------------------------------------------------
#
# Status: PROTOCOL VERIFIED (SpoolEase 0.7 line, branch `0.7`
# 49a8e830a7ada916f2da4b5731f2645b06f3287b, source-read; encryption framing
# unchanged from 3532f8d962dd1a95c7d4ebb37beddca5bbefd39a + esp-hal-app-framework
# 0.6.1) / REAL SPOOLEASE USER TEST PENDING.
#
# Read-only, same as every other provider here: `/api/spools` is the only
# route this ever calls, and it is a GET. The wire itself is encrypted — a
# security key the person copies from the SpoolEase screen, never persisted
# anywhere Studio keeps state (library.db, settings, logs, diagnostics), only
# ever held in memory for the request that needs it.

#: The one sentence every SpoolEase-fed spool with a remaining weight carries.
#: SpoolEase weighs a spool once and subtracts what it has seen a *Bambu*
#: print consume since; it cannot see anything a U1 has used, so the figure is
#: always DERIVED, never TRACKED — the caveat says why in the person's own
#: terms rather than the internal word "derived" (plan-39 O-2/§3.4).
SPOOLEASE_WEIGHT_NOTE = (
    "SpoolEase does not record when this spool was weighed and cannot see what your "
    "U1 has used since, so treat this as an estimate.")

_SPOOLEASE_BAD_CONSUMPTION_NOTE = (
    "SpoolEase recorded a consumption figure Studio could not read for this spool")

#: §4.2 rows 9-12 — the sentence for each `SpoolEaseWireError.code`. Never
#: contains the key, the derived key, the response body or any address.
_SPOOLEASE_WIRE_SENTENCES = {
    "framing": ("Studio could not understand what SpoolEase sent back. Check the "
               "address points at a SpoolEase device."),
    "authentication_failed": (
        "Studio could not read what SpoolEase sent back — either the security key is "
        "wrong or the response was damaged. Use the security key shown on the SpoolEase "
        "screen — not an API key — and try again."),
    "not_text": "SpoolEase sent something Studio could not read as text.",
    "csv": ("SpoolEase answered, but its spool list is in a form Studio does not "
           "recognise. Studio may need an update for this SpoolEase version."),
}


#: SpoolEase 0.7 issues API keys (`spe_api_v1.<id>.<secret>`) for its https
#: port. They are a different credential from the security key and cannot
#: decrypt the plain-http spool list Studio reads. Never echoes the value.
SPOOLEASE_API_KEY_PREFIX = "spe_api_v1."
_SPOOLEASE_API_KEY_SENTENCE = (
    "That looks like a SpoolEase API key, which Studio does not use. Studio reads "
    "SpoolEase's spool list with its security key — the short key shown on the "
    "SpoolEase screen and in its web settings. Enter that instead.")
_SPOOLEASE_HTTPS_SENTENCE = (
    "SpoolEase's secure (https) port is its API-key interface and does not offer a "
    "spool list Studio can read. Use the plain http address of the SpoolEase "
    "(http://…) with its security key instead. Nothing about its secure setup needs "
    "to change.")


def _spoolease_material(record: dict) -> tuple[str | None, str | None]:
    family = _text(record.get("material_type"))
    return (family.upper() if family else None), _text(record.get("material_subtype"))


def _spoolease_weight(record: dict) -> tuple[float | None, str, list[str]]:
    """§2.6/§3.4: both computation paths are DERIVED, never TRACKED — a
    SpoolEase remaining weight is always arithmetic Studio performed from a
    scale reading and a consumption counter, never a figure SpoolEase itself
    calls settled. A negative value in *either* consumption column disqualifies
    the spool (plan-39 addendum S-N1), even though only one of them appears in
    the formula below — a device reporting a negative anywhere in its own
    bookkeeping is a device Studio should not trust the rest of the row from.
    """
    notes: list[str] = []
    try:
        consumed_add = spoolease_wire.decode_f32(record.get("consumed_since_add") or "")
        consumed_weight = spoolease_wire.decode_f32(record.get("consumed_since_weight") or "")
    except spoolease_wire.F32DecodeError:
        notes.append(_SPOOLEASE_BAD_CONSUMPTION_NOTE)
        return None, UNTRACKED, notes
    if consumed_add < 0 or consumed_weight < 0:
        notes.append(_SPOOLEASE_BAD_CONSUMPTION_NOTE)
        return None, UNTRACKED, notes

    weight_current = record.get("weight_current")
    weight_core = record.get("weight_core")
    if weight_core is not None and weight_current is not None:
        core = weight_core
    elif (weight_current is not None and record.get("weight_new") is not None
          and record.get("weight_advertised") is not None):
        core = record["weight_new"] - record["weight_advertised"]
    else:
        notes.append(_no_quantity_note(SPOOLEASE))
        return None, UNTRACKED, notes

    value = round(weight_current - core - consumed_weight, 1)
    if value < 0:
        notes.append("SpoolEase's figures for this spool do not add up to a usable "
                     "weight, so Studio cannot use it")
        return None, UNTRACKED, notes
    if value > IMPLAUSIBLE_GRAMS:
        notes.append(f"SpoolEase reports {value:g} g on this spool, which is not a "
                     "weight of filament — check the spool in SpoolEase")
        return None, UNTRACKED, notes
    notes.append(SPOOLEASE_WEIGHT_NOTE)
    return value, DERIVED, notes


def _spoolease_registered(record: dict) -> str | None:
    """`added_time` (epoch seconds) -> ISO-8601 UTC, or None when absent or
    out of the range a real clock can express."""
    added_time = record.get("added_time")
    if added_time is None:
        return None
    try:
        stamp = datetime.datetime.fromtimestamp(added_time, datetime.timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None
    return stamp.isoformat().replace("+00:00", "Z")


#: S-2 (Opus L5): stdlib's own TLS verification failure text names the host
#: the connection was for (`ssl.SSLCertVerificationError.strerror` reads
#: "...certificate is not valid for 'spoolease.local'...") — that must never
#: reach a sentence the module otherwise keeps host-free. Only a genuine
#: certificate-verification failure gets this sentence; every other
#: `ssl.SSLError` (handshake failure, protocol mismatch, a plaintext server
#: behind an https:// URL) gets `_TLS_GENERIC_FAILURE_TEXT` instead — both are
#: host-free, but conflating "the certificate is wrong" with "there was no
#: TLS to check a certificate on" would misdescribe the second case (Sol r3).
_TLS_VERIFY_FAILURE_TEXT = "its TLS certificate could not be verified"
_TLS_GENERIC_FAILURE_TEXT = "it could not set up a secure connection"


def _tls_failure_text(reason: BaseException) -> str:
    if isinstance(reason, ssl.SSLCertVerificationError):
        return _TLS_VERIFY_FAILURE_TEXT
    return _TLS_GENERIC_FAILURE_TEXT


def _transport_reason(exc: BaseException) -> str:
    """A short, address-free, key-free description of a transport failure —
    never `str(exc)` on an `HTTPException`, which can carry response bytes."""
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, ssl.SSLError):
            return _tls_failure_text(reason)
        if isinstance(reason, socket.gaierror):
            return "name not found"
        if isinstance(reason, OSError):
            return reason.strerror or type(reason).__name__
        return str(reason)
    if isinstance(exc, ssl.SSLError):
        return _tls_failure_text(exc)
    if isinstance(exc, http.client.HTTPException):
        return type(exc).__name__
    if isinstance(exc, OSError):
        return exc.strerror or type(exc).__name__
    return type(exc).__name__


def _host_free_reason(exc: BaseException):
    """What `spoolman()`/`bambuddy()` show for `exc.reason` (or `exc` itself)
    on a transport failure — unchanged from the base-95fd031 form for every
    case except a TLS failure (S-2), which stdlib's own message would
    otherwise name the host for."""
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLError):
        return _tls_failure_text(reason)
    return reason


def spoolease(base_url: str, slot_map: dict | None = None, timeout: float = 4.0,
             slot_base: int | None = None, key: str | None = None) -> dict:
    """Read spools from a SpoolEase device on the local network.

    ``key`` is the security key shown on the SpoolEase screen, trimmed exactly
    as its own reference config page trims one (plan-39 O-3) and never kept
    anywhere past this call — nothing here writes it to a file, a setting or a
    log, and the derived key exists only for the one `decrypt()` call that
    needs it.
    """
    out = {"schema_version": SCHEMA_VERSION, "source": SPOOLEASE, "available": False,
           "slots": [], "spools": [], "error_code": None, "weight_source": None}
    if not base_url:
        out["error"] = "no SpoolEase address configured"
        out["error_code"] = "invalid_address"
        return out

    # §4.2 rows 2-3: decided before any network call — no name is resolved and
    # no socket is opened for a key Studio already knows it cannot use.
    trimmed = spoolease_wire.trim_key(key or "")
    if trimmed.startswith(SPOOLEASE_API_KEY_PREFIX):
        out["error"] = _SPOOLEASE_API_KEY_SENTENCE
        out["error_code"] = "key_is_api_key"
        return out
    if not trimmed:
        out["error"] = ("SpoolEase needs its security key — enter it in Settings → "
                        "Materials provider. Studio keeps it in memory for this "
                        "session only.")
        out["error_code"] = "key_missing"
        return out
    try:
        key_utf8 = trimmed.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        out["error"] = ("That security key contains characters Studio cannot use. "
                        "Copy it exactly as SpoolEase shows it.")
        out["error_code"] = "key_invalid"
        return out

    try:
        root = validate_provider_url(base_url)
    except InvalidProviderAddress as exc:
        return _address_error(out, exc)

    try:
        body = _get_text(f"{root}/api/spools", timeout=timeout)
    except InvalidProviderAddress as exc:
        return _address_error(out, exc)
    except urllib.error.HTTPError as exc:
        if root.startswith("https://") and exc.code in (401, 404):
            out["error"] = _SPOOLEASE_HTTPS_SENTENCE
        else:
            out["error"] = f"SpoolEase did not answer: HTTP {exc.code}"
        out["error_code"] = "http_status"
        return out
    except _ProviderTransportError as exc:
        if exc.code == "oversized":
            out["error"] = ("SpoolEase sent more than Studio will read from a "
                            "provider (4 MB), so Studio stopped.")
        else:
            out["error"] = "SpoolEase did not answer: the response ended before it said it would"
        out["error_code"] = exc.code
        return out
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        if _is_timeout(exc):
            out["error"] = _timeout_sentence("SpoolEase", timeout)
        else:
            out["error"] = f"SpoolEase did not answer: {_transport_reason(exc)}"
        out["error_code"] = "transport"
        return out

    if body == "":
        out["error"] = ("SpoolEase answered with an empty reply — its spool list is "
                        "not ready or could not be listed. Give it a moment and try "
                        "again.")
        out["error_code"] = "empty_body"
        return out

    try:
        nonce, ciphertext = spoolease_wire.decode_frame(body)
        try:
            plaintext_bytes = spoolease_wire.decrypt(key_utf8, nonce, ciphertext)
        except ImportError:
            out["error"] = ("This build of Studio cannot read SpoolEase (its "
                            "encryption support is missing). Please report this.")
            out["error_code"] = "unsupported_build"
            return out
        plaintext = spoolease_wire.decode_text(plaintext_bytes)
        records = spoolease_wire.parse_csv(plaintext)
    except spoolease_wire.SpoolEaseWireError as exc:
        out["error"] = _SPOOLEASE_WIRE_SENTENCES.get(exc.code, str(exc))
        out["error_code"] = exc.code
        return out

    out["available"] = True
    out["weight_source"] = "scale"
    for record in records:
        family, subtype = _spoolease_material(record)
        remaining, quality, notes = _spoolease_weight(record)
        out["spools"].append({
            "id": record["id"],
            "material": family,
            "subtype": subtype,
            "color": _colour(record.get("color_code")),
            "vendor": _text(record.get("brand")),
            "color_name": _text(record.get("color_name")),
            "remaining_g": remaining,
            "remaining_quality": quality,
            # Always undated: a DERIVED SpoolEase figure never carries a
            # "this was true as of" moment (plan-39 O-2).
            "remaining_as_of": None,
            "registered": _spoolease_registered(record),
            "notes": notes,
            "name": None,
            "archived": False,
        })
    out["remaining_known"] = any(s["remaining_g"] is not None for s in out["spools"])

    _attach_slots(out, SPOOLEASE, slot_map, slot_base)
    return out


# --- local / manual spools ----------------------------------------------------
#
# For a printer with no Spoolman and no Bambuddy — or for a slot neither of them
# tracks — a person's own record of what is on the spool. This is the only
# provider here that is not a network read: the rows come from Studio's own
# local library database (`library.spools`), already keyed by slot, so there is
# no slot_map indirection to resolve the way there is for Spoolman or Bambuddy.
#
# Reading it never mutates it. The one thing that changes a remaining weight —
# subtracting what a job used — is `library.apply_spool_usage`, called only from
# the one place a person explicitly confirmed "mark this much used". Nothing in
# this module, and nothing that calls it to build a report, may call that path
# on its own; an inventory a tool quietly edits behind the numbers on screen is
# exactly the divergence the module docstring above promises never to cause.

def local_spools(rows: list[dict]) -> dict:
    """Normalise this printer's local spool rows into the shared provider shape.

    ``rows`` is whatever `library.list_spools` returned for this printer's
    host — already one row per slot, so unlike Spoolman/Bambuddy there is no
    separate spool inventory to map onto slots.
    """
    out = {"schema_version": SCHEMA_VERSION, "source": LOCAL, "available": bool(rows),
           "slots": [], "spools": []}
    for row in rows or []:
        slot_index = row.get("slot")
        if slot_index is None:
            continue
        remaining_g = row.get("remaining_g")
        quality = row.get("remaining_quality") or UNTRACKED
        notes = [n for n in [row.get("notes")] if n]
        out["slots"].append(_slot(
            int(slot_index), material=row.get("material"), subtype=row.get("subtype"),
            color=row.get("color"), vendor=row.get("vendor"), remaining_g=remaining_g,
            source=LOCAL, remaining_quality=quality if remaining_g is not None else UNTRACKED,
            remaining_as_of=row.get("remaining_as_of"), notes=notes,
            # A person telling Studio what is in a slot is the same kind of
            # statement Spoolman's slot map is — intent, not something the
            # printer looked at and confirmed.
            confidence=LIKELY, confirmed_by=BY_PROVIDER))
    out["remaining_known"] = any(s["remaining_g"] is not None for s in out["slots"])
    return out


# --- choosing one ------------------------------------------------------------

#: Every provider Studio can read, by the name the app sends. Adding one here is
#: the whole registration: nothing downstream looks the provider up again.
READERS = {SPOOLMAN: spoolman, BAMBUDDY: bambuddy, SPOOLEASE: spoolease}


def read(kind: str, base_url: str, slot_map: dict | None = None, timeout: float = 4.0,
         slot_base: int | None = None, key: str | None = None) -> dict:
    """Read whichever provider the user configured, in one shape.

    The only place in Studio that turns a provider's name into a decision. Past
    this call the name is provenance — a label on a fact — and nothing branches
    on it. ``error_code`` (string|None) and ``weight_source`` (``"scale"``|None)
    are normalised onto every return here, so every caller can rely on both
    keys existing whichever reader answered (plan-39 Astra-5/§5.1).

    ``key`` is passed through only to a reader that actually takes one
    (SpoolEase, today); Spoolman and Bambuddy are called exactly as before —
    neither of them has anywhere safe to keep a credential, and this seam does
    not invent one for them just because a sibling provider needed it.
    """
    normalised_kind = (kind or "").strip().lower()
    reader = READERS.get(normalised_kind)
    if reader is None:
        return {"schema_version": SCHEMA_VERSION, "source": kind or "unknown",
                "available": False, "slots": [], "spools": [],
                "error": f"Studio does not know how to read a provider called {kind!r}.",
                "error_code": "unknown_provider", "weight_source": None}
    try:
        if normalised_kind == SPOOLEASE:
            state = reader(base_url, slot_map, timeout=timeout, slot_base=slot_base, key=key)
        else:
            state = reader(base_url, slot_map, timeout=timeout, slot_base=slot_base)
    except Exception as exc:  # noqa: BLE001 — a reader must never raise past this seam
        return {"schema_version": SCHEMA_VERSION, "source": kind or "unknown",
                "available": False, "slots": [], "spools": [],
                "error": f"{PROVIDER_NAMES.get(normalised_kind, kind)} answered with "
                         f"something Studio could not handle: {type(exc).__name__}",
                "error_code": "internal", "weight_source": None}
    state.setdefault("error_code", None)
    state.setdefault("weight_source", None)
    return state


def _mapped_slots(slot_map: dict | None,
                  slot_base: int | None = None) -> tuple[list[tuple[int, object]], int]:
    """Read the user's slot-to-spool map, whichever way they numbered their slots.

    Spoolman does not know which slot a spool is in, so the map comes from the
    user — and a person looking at a U1 counts the slots 1, 2, 3, 4 while the
    G-code counts them 0, 1, 2, 3. Getting that wrong puts every spool one slot
    out, and would then report the wrong material for every slot with complete
    confidence, which is worse than not knowing at all.

    So: when the caller says which way it numbered them, that is used. Otherwise
    a map that cannot be zero-based — it names a slot beyond the last one — is
    read as one-based, and the interpretation is reported alongside the result so
    the user can see it rather than discover it.
    """
    pairs = []
    for key, value in (slot_map or {}).items():
        try:
            index = int(str(key).strip())
        except (TypeError, ValueError):
            continue
        if index < 0:
            continue
        pairs.append((index, value))
    if not pairs:
        return [], 0 if slot_base is None else slot_base

    indices = [index for index, _ in pairs]
    base = slot_base
    if base is None:
        base = 1 if (min(indices) >= 1 and max(indices) >= 4) else 0
    if base:
        pairs = [(index - base, value) for index, value in pairs if index - base >= 0]
    return sorted(pairs), base


def _colour(value) -> str | None:
    """A hex colour, or nothing. A malformed one is not a colour."""
    if value is None:
        return None
    text = str(value).strip().lstrip("#")
    if len(text) >= 6 and all(c in "0123456789abcdefABCDEF" for c in text[:6]):
        return "#" + text[:6].upper()
    return None


def _remaining(spool: dict, filament: dict) -> tuple[float | None, str, list[str]]:
    """How much filament is left, how that is known, and what is odd about it.

    Never invents a number: a spool with nothing recorded comes back as unknown,
    and a number that cannot be true — negative, or more than any spool holds — is
    treated as not knowing rather than as a fact worth blocking a print over.
    """
    notes: list[str] = []
    value = _number(spool.get("remaining_weight"))
    quality = _quality(spool)
    if value is None:
        # Spoolman does not always store a remaining weight; when it stores the
        # spool's net weight and what has been used, the difference is honest
        # arithmetic — but it is arithmetic, and it is labelled as such.
        net = _number(filament.get("weight")) or _number(spool.get("initial_weight"))
        used = _number(spool.get("used_weight"))
        if net is not None and used is not None:
            value = round(net - used, 1)
            quality = DERIVED
        else:
            notes.append(_no_quantity_note(SPOOLMAN))
            return None, UNTRACKED, notes

    if value < 0:
        notes.append("Spoolman reports a negative weight for this spool, so Studio "
                     "cannot use it")
        return None, UNTRACKED, notes
    if value > IMPLAUSIBLE_GRAMS:
        notes.append(f"Spoolman reports {value:g} g on this spool, which is not a "
                     "weight of filament — check the units in Spoolman")
        return None, UNTRACKED, notes

    net = _number(filament.get("weight"))
    if net and value > net * 1.5:
        notes.append(f"Spoolman reports more left ({value:g} g) than the spool holds "
                     f"({net:g} g), so Studio cannot use it")
        return None, UNTRACKED, notes
    return value, quality, notes


def _no_quantity_note(source: str) -> str:
    """One sentence, shared, for "there is nothing here to work a weight out from".

    Shared because the two providers reach it down completely different roads —
    Spoolman having neither a remaining weight nor the pair to derive one,
    Bambuddy having no label weight to subtract from — and a person reading the
    slot does not care which. An unknown that explains itself sends them to look
    at the spool; a silent one reads as though Studio never asked.
    """
    return (f"{PROVIDER_NAMES.get(source, source)} does not record enough about this "
            "spool for Studio to work out how much is left on it")


def _quality(spool: dict) -> str:
    """Is this remaining weight bookkeeping something has kept, or arithmetic?

    Spoolman always answers with a `remaining_weight`, because it computes one
    from the spool's initial weight minus what has been recorded used. That means
    the field being present proves nothing on its own — a spool registered five
    minutes ago and never printed from reports a full kilogram, and the previous
    version of this function called that `tracked`, the highest confidence Studio
    has, which is what a blocker is built on.

    So the distinction is drawn where the evidence actually is: a figure is
    tracked when something has been recording consumption against this spool, and
    derived when it is initial weight minus a used weight nothing has updated.
    """
    used = _number(spool.get("used_weight"))
    if spool.get("last_used") and used:
        return TRACKED
    return DERIVED


#: A plain ASCII number and nothing else. `float()` is more generous than that:
#: it accepts full-width Unicode digits, so `float("１０００")` is 1000.0
#: and a malformed field quietly becomes a weight Studio might reason from. This
#: codebase has been caught by Unicode digits twice already, both times through a
#: regex `\d`, and this is the same mistake wearing different clothes.
_PLAIN_NUMBER_RE = re.compile(r"\A[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z")


def _number(value):
    """A usable number, or nothing. Never a guess at what a string meant."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not _PLAIN_NUMBER_RE.match(value.strip()):
            return None
    elif not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return round(number, 1)


# --- combining ---------------------------------------------------------------

def combine(*states: dict) -> dict:
    """Merge providers, best evidence first.

    The printer is authoritative about *what* is in a slot, because it is looking
    at it. Another provider may add what the printer cannot know — a spool
    identity, a remaining weight — but never overrides the material or colour the
    machine itself reported.
    """
    merged: dict[int, dict] = {}
    sources = []
    remaining_known = False
    note_conflicts: list[dict] = []

    for state in states:
        if not state or not state.get("available"):
            continue
        sources.append(state["source"])
        remaining_known = remaining_known or bool(state.get("remaining_known"))
        note_conflicts.extend(state.get("note_conflicts") or [])
        for slot in state.get("slots", []):
            index = slot["slot"]
            existing = merged.get(index)
            if existing is None:
                merged[index] = dict(slot)
                continue
            # Fill gaps only; never overwrite what the printer said it sees.
            for key in ("material", "subtype", "color", "vendor", "spool_id", "remaining_g"):
                if existing.get(key) in (None, "") and slot.get(key) not in (None, ""):
                    existing[key] = slot[key]
                    existing.setdefault("added_by", {})[key] = slot["source"]
                    if key == "remaining_g":
                        existing["remaining_quality"] = slot.get("remaining_quality", UNTRACKED)
                        existing["remaining_as_of"] = slot.get("remaining_as_of")
            existing["notes"] = list(existing.get("notes") or ()) + list(slot.get("notes") or ())

            # Two sources describing the same slot differently is not a detail to
            # smooth over: one of them is about to be wrong about what will come
            # out of the nozzle. The printer's answer stands, and the
            # disagreement is said out loud.
            for key, what in (("material", "material"), ("color", "colour")):
                mine, theirs = existing.get(key), slot.get(key)
                if mine and theirs and str(mine).upper() != str(theirs).upper():
                    # `mine`'s real source: whichever source's gap-fill actually
                    # supplied this field, or the merged row's own original
                    # source if nothing filled it — never assumed to be the
                    # printer just because STOCK is read first.
                    mine_source = existing.get("added_by", {}).get(key, existing.get("source"))
                    theirs_source = slot["source"]
                    existing.setdefault("conflicts", []).append(
                        _describe_disagreement(mine_source, mine, theirs_source, theirs))
                    existing["confidence"] = UNKNOWN
                    # `disagreed`'s keys now name the REAL source on both
                    # sides (matching `conflicts`'s sentence above) instead of
                    # hardcoding "printer" for `mine` regardless of where it
                    # actually came from. Two DIFFERENT sources always
                    # produce two distinct keys; the (believed impossible —
                    # every state passed to combine() has its own distinct
                    # `source`) case of the two sources being equal is still
                    # handled without losing either value or raising.
                    theirs_key = theirs_source if theirs_source != mine_source else f"{theirs_source}_2"
                    existing.setdefault("disagreed", {})[what] = {
                        mine_source: mine, theirs_key: theirs}

            # A provider filling gaps never changes who saw the slot. If the
            # printer reported it, the printer confirmed it; if only a provider
            # ever spoke, nothing confirmed it.
            if existing.get("confirmed_by") != BY_PRINTER and slot.get("confirmed_by") == BY_PRINTER:
                existing["confirmed_by"] = BY_PRINTER

            if slot.get("present") and not existing.get("present"):
                # One source says empty, another says a spool is there. When
                # the PRINTER is the one that looked and found nothing, that
                # stands: a provider's "present" is someone's record of what
                # they believe is loaded, never a second look at the slot —
                # letting it override a printer's own observation is how a
                # stale note turns a real BLOCKER (this slot is empty) into a
                # job that goes ahead believing a spool is there. Anything
                # other than a printer-confirmed empty is still a genuine
                # disagreement between two guesses, and reported as one.
                if existing.get("confirmed_by") == BY_PRINTER:
                    existing.setdefault("conflicts", []).append(
                        f"{_says(slot['source'])} this slot has material in it, but the printer "
                        "looked and found it empty — Studio is using what the printer can see")
                else:
                    existing["present"] = True
                    existing["confidence"] = UNKNOWN
                    existing.setdefault("conflicts", []).append(
                        f"{_says(existing['source'])} this slot is empty, but "
                        f"{_says(slot['source'])} it is not")

    return {
        "schema_version": SCHEMA_VERSION,
        "available": bool(merged),
        "sources": sources,
        "remaining_known": remaining_known,
        "slots": [merged[i] for i in sorted(merged)],
        "note_conflicts": note_conflicts,
    }


def as_loaded_filaments(state: dict) -> list | None:
    """Back into the shape the existing checks already understand.

    `material_plan` and the post-slice checks were written against the printer's
    own list, index-aligned with `None` for an empty slot. Keeping that shape means
    every provider works with code that predates the seam.
    """
    if not state or not state.get("available"):
        return None
    slots = state.get("slots") or []
    if not slots:
        return None
    highest = max(s["slot"] for s in slots)
    out: list = [None] * (highest + 1)
    for slot in slots:
        if not slot.get("present"):
            continue
        material = " ".join(x for x in (slot.get("material"), slot.get("subtype")) if x)
        out[slot["slot"]] = {
            "confirmed_by": slot.get("confirmed_by"),
            "color": slot.get("color"),
            "material": material or None,
            "vendor": slot.get("vendor"),
            "spool_id": slot.get("spool_id"),
            "remaining_g": slot.get("remaining_g"),
            # Carried through so the checks downstream can tell a figure something
            # is keeping track of from a figure nothing is.
            "remaining_quality": slot.get("remaining_quality", UNTRACKED),
            "remaining_as_of": slot.get("remaining_as_of"),
            "conflicts": list(slot.get("conflicts") or ()),
            "notes": list(slot.get("notes") or ()),
        }
    return out
