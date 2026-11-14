"""The only network transport for the Studio+ tracks.

Every outbound call from new code goes through `local_request`; no other foundation or track module
imports `socket`, `ssl`, `http.client` or `urllib.request`. The guarantees, all enforced here:

- The destination is on the user's own network. Every address the resolver returns is checked at
  connect time (loopback, private, 100.64/10 and IPv6 site-local are local; public, link-local
  169.254/16 and fe80::/10, 6to4, Teredo and NAT64 are not) and only a vetted address is dialled, so
  a name that changes its answer between check and connect (DNS rebinding) gains nothing.
- Name resolution runs in a bounded pool (4 threads, no queue). A stuck resolver cannot outlive the
  call's deadline; a saturated pool fails fast with `unavailable`.
- No proxy is ever consulted (`*_PROXY` is not read). TLS is verified with the default context.
- Redirects are refused. Credentials are attached only to the configured origin and never appear in
  an error, a log line or a returned response.
- Size caps apply to request body, response headers and response body; the whole call, including slow
  headers and slow bodies, runs under one deadline that closes the live socket.
- GET and HEAD by default. Any other method needs the write flag and an origin registered through
  `confirm_write_origin`. A path denylist applies to every host and method.

Errors are `NetguardRefused` with a fixed text per `code`; they never carry a URL, a header value or
a response body.
"""
from __future__ import annotations

import io
import ipaddress
import logging
import math
import os
import re
import socket
import ssl
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from http import client as _http
from typing import Any, Callable, Iterable, Mapping

_LOG = logging.getLogger("snapstudio.netguard")

DEFAULT_MAX_BYTES = 4 * 1024 * 1024
MAX_TIMEOUT_S = 300.0
RESOLVER_THREADS = 4
_HEADER_CAP_LIMIT = 64 * 1024
_URL_MAX = 2048
_ORIGIN_MAX = 255
_READ_CHUNK = 8192

_MESSAGES = {
    "syntax": "That is not an address Studio will use.",
    "off_network": "That address is not on your own network.",
    "public_address": "That address is not on your own network.",
    "unresolvable": "That address could not be resolved.",
    "unavailable": "Address lookup is busy; try again.",
    "deadline": "The request took too long.",
    "redirect": "The server tried to redirect the request; Studio does not follow redirects.",
    "too_large": "The request or response is larger than allowed.",
    "method": "That request method is not allowed.",
    "path": "That request path is not allowed.",
    "write_origin": "That server has not been confirmed for writing.",
    "tls": "The secure connection could not be verified.",
    "network": "The connection failed.",
    "protocol": "The server sent an invalid reply.",
    "bad_args": "The request arguments are not valid.",
}


class NetguardRefused(Exception):
    """A request Studio refuses or could not complete. The text is fixed per `code`; no request data."""

    def __init__(self, code: str) -> None:
        self.code = code if code in _MESSAGES else "network"
        super().__init__(_MESSAGES[self.code])

    def __repr__(self) -> str:
        return f"NetguardRefused({self.code!r})"


# ---------------------------------------------------------------- addresses

_6TO4 = ipaddress.ip_network("2002::/16")
_TEREDO = ipaddress.ip_network("2001::/32")
_NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_LOCAL_SUFFIXES = (".local", ".lan", ".home", ".internal", ".home.arpa")
_HOSTNAME_RE = re.compile(
    r"\A(?!-)[A-Za-z0-9_-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9_-]{1,63}(?<!-))*\.?\Z")


def _parse_ip(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(str(text).strip().strip("[]").split("%", 1)[0])
    except ValueError:
        return None


def is_local_address(text: str) -> bool:
    """True when `text` is an IP address on the user's own network."""
    address = _parse_ip(text)
    if address is None:
        return False
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_unspecified or address.is_multicast or address.is_link_local:
        return False
    if address.version == 6 and (address in _6TO4 or address in _TEREDO or any(address in n for n in _NAT64)):
        return False
    return bool(address.is_loopback or address.is_private or address in _CGNAT
                or (address.version == 6 and address.is_site_local))


# ---------------------------------------------------------------- bounded resolver

Resolver = Callable[[str], Iterable[str]]


def _system_resolver(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)]


class ResolverPool:
    """At most `max_threads` resolutions in flight; a stuck one keeps its slot until it returns."""

    def __init__(self, max_threads: int = RESOLVER_THREADS) -> None:
        self._slots = threading.BoundedSemaphore(max_threads)

    def resolve(self, resolver: Resolver, host: str, timeout: float) -> list[str]:
        if not self._slots.acquire(blocking=False):
            raise NetguardRefused("unavailable")
        box: dict[str, Any] = {}
        done = threading.Event()

        def run() -> None:
            try:
                box["answers"] = [str(a) for a in resolver(host)]
            except BaseException:  # noqa: BLE001 - nothing from the resolver is surfaced
                box["failed"] = True
            finally:
                self._slots.release()
                done.set()

        try:
            threading.Thread(target=run, name="netguard-resolve", daemon=True).start()
        except RuntimeError:
            self._slots.release()
            raise NetguardRefused("unavailable") from None
        if not done.wait(max(timeout, 0.0)):
            raise NetguardRefused("deadline")
        if box.get("failed") or not box.get("answers"):
            raise NetguardRefused("unresolvable")
        return box["answers"]


_DEFAULT_POOL = ResolverPool()


# ---------------------------------------------------------------- origin syntax

@dataclass(frozen=True)
class _Origin:
    scheme: str
    host: str          # lower-case, no brackets, no trailing dot
    port: int          # explicit or scheme default
    explicit_port: int | None
    rest: str          # raw path + query as typed ('' when none)

    @property
    def is_ip(self) -> bool:
        return _parse_ip(self.host) is not None

    @property
    def canonical(self) -> str:
        return _canonical(self.scheme, self.host, self.port)


def _canonical(scheme: str, host: str, port: int) -> str:
    ip = _parse_ip(host)
    shown = f"[{ip.compressed}]" if ip is not None and ip.version == 6 else (ip.compressed if ip else host)
    return f"{scheme}://{shown}:{port}"


def _split(url: Any) -> _Origin:
    text = url.strip() if isinstance(url, str) else ""
    if not text or len(text) > _URL_MAX or any(ord(c) < 33 or ord(c) == 127 for c in text):
        raise NetguardRefused("syntax")
    if "://" not in text:
        text = "http://" + text
    try:
        parts = urllib.parse.urlsplit(text)
        port = parts.port
    except ValueError:
        raise NetguardRefused("syntax") from None
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        raise NetguardRefused("syntax")
    raw_host = parts.hostname
    if not raw_host or (port is not None and port == 0):
        raise NetguardRefused("syntax")
    host = raw_host.strip("[]").rstrip(".").lower()
    if ":" in raw_host:
        if _parse_ip(raw_host) is None or "%" in raw_host:
            raise NetguardRefused("syntax")
    elif not _HOSTNAME_RE.match(raw_host):
        raise NetguardRefused("syntax")
    if not host or len(parts.netloc) > _ORIGIN_MAX:
        raise NetguardRefused("syntax")
    rest = parts.path + (("?" + parts.query) if parts.query else "")
    return _Origin(parts.scheme, host, port or (443 if parts.scheme == "https" else 80), port, rest)


def _typed_name_is_local(origin: _Origin, resolver: Resolver | None, pool: ResolverPool | None,
                         timeout: float) -> bool:
    host = origin.host
    ip = _parse_ip(host)
    if ip is not None:
        return is_local_address(host)
    if host == "localhost" or "." not in host or host.endswith(_LOCAL_SUFFIXES):
        return True
    try:
        answers = (pool or _DEFAULT_POOL).resolve(resolver or _system_resolver, host, timeout)
    except NetguardRefused as exc:
        if exc.code in ("unavailable", "deadline"):
            raise
        return False
    return any(is_local_address(a) for a in answers)


def require_local_url(url: str, *, resolver: Resolver | None = None,
                      resolver_pool: ResolverPool | None = None, timeout: float = 3.0) -> str:
    """Return the normalised URL, or raise `NetguardRefused`.

    Same syntax rules as the provider-address check (http/https, no userinfo, hostname pattern,
    length) applied to the origin only: a path is allowed here. A name that is not obviously local is
    resolved in the bounded pool, never with the unbounded system call.
    """
    origin = _split(url)
    if not _typed_name_is_local(origin, resolver, resolver_pool, _timeout(timeout)):
        raise NetguardRefused("off_network")
    authority = f"[{origin.host}]" if ":" in origin.host else origin.host
    return (f"{origin.scheme}://{authority}"
            + (f":{origin.explicit_port}" if origin.explicit_port else "") + origin.rest)


# ---------------------------------------------------------------- method and path policy

_DENIED_PREFIXES = (
    ("printer", "print"), ("printer", "gcode", "script"), ("printer", "emergency_stop"),
    ("printer", "firmware_restart"), ("printer", "restart"), ("machine",),
    ("server", "files", "upload"), ("api", "printer"), ("api", "job"),
)
_ALLOWED_EXACT_GET = (("machine", "system_info"),)
_GET_ONLY_PREFIXES = (
    ("api", "files", "local"), ("api", "files", "sdcard"), ("server", "jsonrpc"), ("server", "job_queue"),
)
_METHODS_READ = frozenset({"GET", "HEAD"})
_METHODS_WRITE = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_ENCODED_DANGER = re.compile(r"%(2e|2f|5c|00)", re.IGNORECASE)


def _normalise_path(rest: str) -> tuple[str, tuple[str, ...]]:
    """(path to send, lower-cased segments to match). Raises on residual encoded traversal."""
    path = rest.split("?", 1)[0].split("#", 1)[0]
    decoded = urllib.parse.unquote(path)
    if "\\" in decoded or any(ord(c) < 32 or ord(c) == 127 for c in decoded):
        raise NetguardRefused("path")
    stack: list[str] = []
    for segment in decoded.split("/"):
        segment = segment.split(";", 1)[0]
        if _ENCODED_DANGER.search(segment):
            raise NetguardRefused("path")
        if segment in ("", "."):
            continue
        if segment == "..":
            if stack:
                stack.pop()
            continue
        stack.append(segment)
    send = "/" + "/".join(urllib.parse.quote(s, safe="@:!$&'()*+,=~-._") for s in stack)
    return send, tuple(s.lower() for s in stack)


def _has_prefix(segments: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    return segments[:len(prefix)] == prefix


def _check_method_and_path(method: str, segments: tuple[str, ...], write_ok: bool) -> None:
    if method not in _METHODS_READ and method not in _METHODS_WRITE:
        raise NetguardRefused("method")
    if method in _METHODS_WRITE and not write_ok:
        raise NetguardRefused("method")
    if method == "GET" and segments in _ALLOWED_EXACT_GET:
        return
    if any(_has_prefix(segments, p) for p in _DENIED_PREFIXES):
        raise NetguardRefused("path")
    if method != "GET" and any(_has_prefix(segments, p) for p in _GET_ONLY_PREFIXES):
        raise NetguardRefused("path")


# ---------------------------------------------------------------- write-origin registry

_WRITE_ORIGINS: set[str] = set()
_WRITE_LOCK = threading.Lock()


def confirm_write_origin(origin: str) -> str:
    """Register an origin as confirmed for writes (the caller proves identity; netguard stays generic)."""
    canonical = _split(origin).canonical
    with _WRITE_LOCK:
        _WRITE_ORIGINS.add(canonical)
    return canonical


def revoke_write_origin(origin: str) -> None:
    canonical = _split(origin).canonical
    with _WRITE_LOCK:
        _WRITE_ORIGINS.discard(canonical)


def clear_write_origins() -> None:
    with _WRITE_LOCK:
        _WRITE_ORIGINS.clear()


def _write_origin_confirmed(canonical: str) -> bool:
    with _WRITE_LOCK:
        return canonical in _WRITE_ORIGINS


# ---------------------------------------------------------------- transport

@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes | None
    path: str | None
    bytes_read: int
    reason: str = field(default="", repr=False)

    def __repr__(self) -> str:
        return f"Response(status={self.status}, bytes_read={self.bytes_read})"


class _TooLarge(Exception):
    pass


class _CountingRaw(io.RawIOBase):
    def __init__(self, raw: Any) -> None:
        self._raw = raw
        self.count = 0
        self.limit: int | None = None

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int | None:
        n = self._raw.readinto(buffer)
        if n:
            self.count += n
            if self.limit is not None and self.count > self.limit:
                raise _TooLarge()
        return n

    def close(self) -> None:
        try:
            self._raw.close()
        finally:
            super().close()


class _GuardedSocket:
    """Delegates to the vetted socket; `makefile` counts the bytes read so header size can be capped."""

    def __init__(self, sock: Any) -> None:
        self._sock = sock
        self.counter: _CountingRaw | None = None
        self.header_limit: int | None = None

    def makefile(self, mode: str = "rb", buffering: int | None = None, **_: Any) -> Any:
        self.counter = _CountingRaw(self._sock.makefile("rb", buffering=0))
        self.counter.limit = self.header_limit
        return io.BufferedReader(self.counter, buffer_size=1024)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._sock, name)


class _Deadline:
    def __init__(self, seconds: float) -> None:
        self.end = time.monotonic() + seconds
        self.expired = False
        self._sock: Any = None
        self._timer = threading.Timer(seconds, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def remaining(self) -> float:
        left = self.end - time.monotonic()
        if left <= 0:
            self.expired = True
            raise NetguardRefused("deadline")
        return left

    def attach(self, sock: Any) -> None:
        self._sock = sock
        if self.expired:
            self._fire()

    def _fire(self) -> None:
        self.expired = True
        sock = self._sock
        if sock is not None:
            for action in (lambda: sock.shutdown(socket.SHUT_RDWR), sock.close):
                try:
                    action()
                except Exception:  # noqa: BLE001
                    pass

    def cancel(self) -> None:
        self._timer.cancel()


def _timeout(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or value <= 0 or value > MAX_TIMEOUT_S:
        raise NetguardRefused("bad_args")
    return float(value)


def _positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise NetguardRefused("bad_args")
    return value


def _tls_context() -> ssl.SSLContext:
    """Default context: certificate required, hostname checked."""
    return ssl.create_default_context()


def _dial(address: str, port: int, timeout: float) -> socket.socket:
    ip = _parse_ip(address)
    family = socket.AF_INET6 if ip is not None and ip.version == 6 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect((str(ip), port))
        return sock
    except BaseException:
        sock.close()
        raise


_BAD_HEADER_NAMES = frozenset({"host", "content-length", "transfer-encoding", "connection"})
_TOKEN_RE = re.compile(r"\A[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")


def _clean_headers(headers: Mapping[str, str] | None, secret_headers: Iterable[str]) -> tuple[
        list[tuple[str, str]], frozenset[str]]:
    secret_names = frozenset({"authorization", "x-api-key"} | {str(s).lower() for s in secret_headers})
    items: list[tuple[str, str]] = []
    for name, value in (headers or {}).items():
        if not isinstance(name, str) or not isinstance(value, str) or not _TOKEN_RE.match(name) \
                or name.lower() in _BAD_HEADER_NAMES or any(c in value for c in "\r\n\x00"):
            raise NetguardRefused("bad_args")
        items.append((name, value))
    return items, secret_names


def _redact(text: str, secrets_: list[str]) -> str:
    for secret in secrets_:
        text = text.replace(secret, "[redacted]")
    return text


class _BodyRedactor:
    """Replace sent credential values in a body, including values split across read boundaries.

    Raw bytes that could still be the start of a secret are held back (`pending`, shorter than the
    longest secret) until the next block arrives or `finish` is called. Replacements are never rescanned.
    """

    def __init__(self, secrets_: list[str]) -> None:
        variants: set[bytes] = set()
        for secret in secrets_:
            if not secret:
                continue
            variants.add(secret.encode("utf-8"))
            try:
                variants.add(secret.encode("latin-1"))
            except UnicodeEncodeError:
                pass
        ordered = sorted(variants, key=len, reverse=True)
        self._pattern = re.compile(b"|".join(re.escape(v) for v in ordered)) if ordered else None
        self._hold = (max(len(v) for v in ordered) - 1) if ordered else 0
        self._pending = b""

    def _run(self, window: bytes, final: bool) -> bytes:
        if self._pattern is None:
            return window
        limit = len(window) if final else len(window) - self._hold
        out: list[bytes] = []
        pos = 0
        for match in self._pattern.finditer(window):
            if match.start() >= limit:
                break
            out.append(window[pos:match.start()])
            out.append(b"[redacted]")
            pos = match.end()
        consumed = max(pos, limit, 0)
        if consumed > pos:
            out.append(window[pos:consumed])
        self._pending = window[consumed:]
        return b"".join(out)

    def feed(self, block: bytes) -> bytes:
        return self._run(self._pending + block, False)

    def finish(self) -> bytes:
        return self._run(self._pending, True)


def local_request(method: str, url: str, *, headers: Mapping[str, str] | None = None,
                  body: bytes | None = None, timeout: float = 10.0, max_bytes: int = DEFAULT_MAX_BYTES,
                  max_request_bytes: int | None = None, stream_to: str | os.PathLike | None = None,
                  write_ok: bool = False, secret_headers: Iterable[str] = (), origin: str | None = None,
                  resolver: Resolver | None = None, resolver_pool: ResolverPool | None = None) -> Response:
    """One bounded request to a server on the user's own network. See the module docstring.

    `origin` is the configured origin; credential headers (authorization, x-api-key and any name in
    `secret_headers`) are sent only when the request URL has the same scheme, host and port, and are
    otherwise dropped. `stream_to` is an existing directory: the body is written to a new temporary
    file there (capped by `max_bytes`) and `Response.path` names it; partial files are removed.
    """
    method = method.upper() if isinstance(method, str) else ""
    seconds = _timeout(timeout)
    cap = _positive_int(max_bytes)
    request_cap = cap if max_request_bytes is None else _positive_int(max_request_bytes)
    if body is not None and (not isinstance(body, (bytes, bytearray)) or method in _METHODS_READ):
        raise NetguardRefused("bad_args")
    if body is not None and len(body) > request_cap:
        raise NetguardRefused("too_large")
    if stream_to is not None and not os.path.isdir(stream_to):
        raise NetguardRefused("bad_args")

    target = _split(url)
    send_path, segments = _normalise_path(target.rest)
    _check_method_and_path(method, segments, bool(write_ok))
    if write_ok and not _write_origin_confirmed(target.canonical):
        raise NetguardRefused("write_origin")
    header_items, secret_names = _clean_headers(headers, secret_headers)
    same_origin = origin is not None and _split(origin).canonical == target.canonical
    sent_secrets: list[str] = []
    final_headers: list[tuple[str, str]] = []
    for name, value in header_items:
        if name.lower() in secret_names:
            if not same_origin:
                continue
            sent_secrets.append(value)
            if name.lower() == "authorization":
                scheme, separator, credential = value.partition(" ")
                if separator and scheme.lower() in ("bearer", "basic") and credential.strip():
                    sent_secrets.append(credential.strip())
        final_headers.append((name, value))
    query = target.rest.split("?", 1)[1].split("#", 1)[0] if "?" in target.rest else ""
    request_target = send_path + (("?" + query) if query else "")

    deadline = _Deadline(seconds)
    sock: Any = None
    partial: str | None = None
    try:
        # resolve and vet: only local answers are ever dialled
        if target.is_ip:
            candidates = [target.host]
        else:
            candidates = (resolver_pool or _DEFAULT_POOL).resolve(
                resolver or _system_resolver, target.host, deadline.remaining())
        local = [a for a in candidates if is_local_address(a)]
        if not local:
            raise NetguardRefused("public_address" if target.is_ip else "off_network")
        for address in local:
            try:
                sock = _dial(address, target.port, deadline.remaining())
            except NetguardRefused:
                raise
            except OSError:
                continue
            peer = sock.getpeername()[0]
            if not is_local_address(peer):
                sock.close()
                raise NetguardRefused("public_address")
            break
        if sock is None:
            raise NetguardRefused("deadline" if deadline.expired else "network")
        deadline.attach(sock)
        if target.scheme == "https":
            sock.settimeout(deadline.remaining())
            sock = _tls_context().wrap_socket(sock, server_hostname=target.host)
            deadline.attach(sock)
        sock.settimeout(deadline.remaining())
        guarded = _GuardedSocket(sock)
        conn = _http.HTTPConnection(target.host, target.port)
        conn.sock = guarded  # type: ignore[assignment]
        header_cap = min(cap, _HEADER_CAP_LIMIT)
        guarded.header_limit = header_cap + 1024
        conn.putrequest(method, request_target, skip_accept_encoding=False)
        for name, value in final_headers:
            conn.putheader(name, value)
        if body is not None:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(bytes(body) if body is not None else None)
        sock.settimeout(deadline.remaining())
        try:
            response = conn.getresponse()
        except _TooLarge:
            raise NetguardRefused("too_large") from None
        if guarded.counter is not None:
            guarded.counter.limit = None
        raw_headers = response.getheaders()
        if sum(len(k) + len(v) + 4 for k, v in raw_headers) > header_cap:
            raise NetguardRefused("too_large")
        if 300 <= response.status < 400 and response.status != 304:
            raise NetguardRefused("redirect")
        length = response.getheader("Content-Length")
        if length is not None and length.strip().isdigit() and int(length) > cap and method != "HEAD":
            raise NetguardRefused("too_large")

        total = 0
        chunks: list[bytes] = []
        handle = None
        redactor = _BodyRedactor(sent_secrets)
        if stream_to is not None and method != "HEAD":
            fd, partial = tempfile.mkstemp(prefix="netguard-", suffix=".part", dir=os.fspath(stream_to))
            handle = os.fdopen(fd, "wb")
        try:
            while method != "HEAD":
                block = response.read(_READ_CHUNK)
                if not block:
                    break
                total += len(block)
                if total > cap:
                    raise NetguardRefused("too_large")
                if handle is not None:
                    handle.write(redactor.feed(block))
                else:
                    chunks.append(block)
                sock.settimeout(deadline.remaining())
            if handle is not None:
                handle.write(redactor.finish())
        finally:
            if handle is not None:
                handle.close()
        if deadline.expired:
            raise NetguardRefused("deadline")
        out_headers: dict[str, str] = {}
        for name, value in raw_headers:
            key = name.lower()
            safe = "[redacted]" if key in secret_names else _redact(value, sent_secrets)
            out_headers[key] = f"{out_headers[key]}, {safe}" if key in out_headers else safe
        data: bytes | None = None
        if handle is None and method != "HEAD":
            data = b"".join(chunks)
            if sent_secrets:
                scrub = _BodyRedactor(sent_secrets)
                data = scrub.feed(data) + scrub.finish()
        result = Response(response.status, out_headers, data, partial if handle is not None else None,
                          total, _redact(response.reason or "", sent_secrets))
        partial = None  # ownership passes to the caller
        return result
    except NetguardRefused as exc:
        code = "deadline" if deadline.expired and exc.code in ("network", "protocol") else exc.code
        _LOG.debug("netguard refused: %s", code)
        raise (exc if code == exc.code else NetguardRefused(code)) from None
    except ssl.SSLError:
        _LOG.debug("netguard refused: tls")
        raise NetguardRefused("deadline" if deadline.expired else "tls") from None
    except (OSError, _http.HTTPException, ValueError, UnicodeError):
        code = "deadline" if deadline.expired else "network"
        _LOG.debug("netguard refused: %s", code)
        raise NetguardRefused(code) from None
    except _TooLarge:
        raise NetguardRefused("too_large") from None
    finally:
        deadline.cancel()
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if partial is not None:
            try:
                os.unlink(partial)
            except OSError:
                pass
