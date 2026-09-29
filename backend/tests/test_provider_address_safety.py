"""A settings box is not permission to fetch anything, anywhere.

Studio's first hard rule is that it is local-first: no cloud, nothing uploaded, no
outbound internet requests. A provider address is typed by the user, and before
this was written it went straight to `urllib.request.urlopen`. Three things were
demonstrated against that code, not imagined:

* `file:///…` made Studio open a local path;
* `ftp://…` made it open an FTP connection;
* `http://example.com` made it resolve and fetch a page on the public internet,
  which returned a 404 — meaning the request genuinely left the machine.

None of it was reachable from the shipped app, because nothing in the desktop ever
sent a provider address. It was about to become reachable, which is why this exists
before the settings page does rather than after it.
"""
from __future__ import annotations

import pytest

from snapstudio_core.material_providers import (InvalidProviderAddress, spoolman,
                                                validate_provider_url)

LOCAL = [
    "http://127.0.0.1:7912",
    "http://localhost:7912",
    "localhost:7912",
    "http://192.168.1.9:7912",
    "http://10.0.0.4",
    "http://172.16.5.5:7912",
    "http://169.254.10.10:7912",
    "http://100.101.102.103:7912",     # tailnet / CGNAT
    "http://spoolman.local:7912",
    "http://spoolman.lan",
    "http://spoolman",                  # a bare LAN name
    "http://nas.home.arpa:7912",
    "https://spoolman.local:7912",
    "http://[::1]:7912",
    "http://[fd00::1]:7912",
]

REFUSED = [
    "http://example.com",
    "http://spoolman.example.com:7912",
    "https://api.spoolman.io",
    "http://8.8.8.8:7912",
    "http://[2606:4700:4700::1111]",
    "file:///c:/windows/win.ini",
    "ftp://192.168.1.9",
    "gopher://192.168.1.9",
    "http://user:secret@192.168.1.9:7912",
    "http://192.168.1.9:7912/api/v1/spool",
    "http://192.168.1.9:7912/?x=1",
    "http://192.168.1.9:7912/#frag",
    "",
    "   ",
    "http://192.168.1.9:notaport",
    "x" * 300,
]


@pytest.mark.parametrize("address", LOCAL)
def test_an_address_on_your_own_network_is_accepted(address):
    assert validate_provider_url(address).startswith(("http://", "https://"))


@pytest.mark.parametrize("address", REFUSED)
def test_anything_else_is_refused(address):
    with pytest.raises(InvalidProviderAddress):
        validate_provider_url(address)


def test_the_refusal_explains_itself_without_jargon():
    with pytest.raises(InvalidProviderAddress) as raised:
        validate_provider_url("http://example.com")
    message = str(raised.value)
    assert "your own network" in message
    assert "no requests to the internet" in message


def test_a_public_address_never_reaches_the_network(monkeypatch):
    """The refusal happens before anything is opened, not after."""
    def explode(url, timeout=4.0):
        raise AssertionError(f"Studio tried to fetch {url}")

    monkeypatch.setattr("snapstudio_core.material_providers._get_json", explode)
    out = spoolman("http://example.com")
    assert out["available"] is False
    assert "your own network" in out["error"]


def test_a_file_url_never_reaches_the_filesystem(monkeypatch):
    def explode(url, timeout=4.0):
        raise AssertionError(f"Studio tried to open {url}")

    monkeypatch.setattr("snapstudio_core.material_providers._get_json", explode)
    out = spoolman("file:///c:/windows/win.ini")
    assert out["available"] is False
    assert out["error"]


def test_a_bare_address_gains_the_scheme_rather_than_being_refused():
    assert validate_provider_url("192.168.1.9:7912") == "http://192.168.1.9:7912"


def test_a_trailing_slash_and_stray_space_are_tolerated():
    assert validate_provider_url("  http://spoolman.local:7912/  ") == \
        "http://spoolman.local:7912"


def test_the_normalised_url_is_what_gets_requested(monkeypatch):
    seen = {}
    monkeypatch.setattr("snapstudio_core.material_providers._get_json",
                        lambda url, timeout=4.0: seen.setdefault("url", url) and [])
    spoolman("spoolman.local:7912/")
    assert seen["url"].startswith("http://spoolman.local:7912/api/v1/spool")


def test_a_huge_response_is_bounded():
    """The reader caps what it will take from a provider, like every other
    reader — the size cap lives in the shared `_fetch()` every reader routes
    through (plan-39 v3.4 M-1/L-7: it moved out of `_get_json` when
    `_get_text` needed the same cap for SpoolEase's plaintext body)."""
    import inspect

    from snapstudio_core import material_providers

    source = inspect.getsource(material_providers._fetch)
    assert "limit" in source and "read(" in source
    assert "1024" in inspect.getsource(material_providers)


def test_a_spoolman_timeout_reads_the_same_whether_bare_or_wrapped(monkeypatch):
    """plan-39 v3.2 N-4 / v3.4 L-2: the same timeout sentence, and a
    `URLError(reason=TimeoutError())` — the shape the real transport raises
    when the shared read deadline expires — is recognised exactly like a bare
    `TimeoutError`."""
    import urllib.error

    from snapstudio_core import material_providers as mp

    monkeypatch.setattr(mp, "_get_json", lambda url, timeout=4.0: (
        _ for _ in ()).throw(TimeoutError()))
    bare = mp.spoolman("http://192.168.1.9:7912")
    assert "did not answer in time" in bare["error"]
    assert "192.168.1.9" not in bare["error"]

    monkeypatch.setattr(mp, "_get_json", lambda url, timeout=4.0: (
        _ for _ in ()).throw(urllib.error.URLError(TimeoutError())))
    wrapped = mp.spoolman("http://192.168.1.9:7912")
    assert "did not answer in time" in wrapped["error"]


def test_a_provider_error_never_carries_the_address_into_the_result(monkeypatch):
    """A support bundle must not gain a LAN address through an error string."""
    import urllib.error

    monkeypatch.setattr(
        "snapstudio_core.material_providers._get_json",
        lambda url, timeout=4.0: (_ for _ in ()).throw(
            urllib.error.URLError("connection refused")))
    out = spoolman("http://192.168.1.44:7912")
    assert "192.168.1.44" not in json_text(out)


def json_text(value) -> str:
    import json

    return json.dumps(value)


# --- the hop the address check could not see ---------------------------------
#
# `validate_provider_url` checks the string the user typed. That turned out not
# to be the whole journey: a service on the LAN answering `302 Location:
# http://example.com` made Studio follow it, and the request left the machine —
# demonstrated against this module by standing up a local server that redirected
# every request to the public internet and watching example.com's 404 come back
# in Studio's own error message.
#
# The same defect as `file://` and a public hostname, one hop later, and fixed in
# the same place for every provider rather than in whichever adapter noticed.

class _Redirector:
    """A local server that always redirects somewhere it should not be followed."""

    def __init__(self, target: str):
        self.target = target
        self.hits: list[str] = []

    def __enter__(self):
        import http.server
        import threading

        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 — the stdlib's spelling
                owner.hits.append(self.path)
                self.send_response(302)
                self.send_header("Location", owner.target)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def _read_kwargs(provider_kind: str) -> dict:
    """SpoolEase needs a key before it will make any request at all; the
    other two providers take none."""
    return {"key": "Fx7-tEsT"} if provider_kind == "spoolease" else {}


@pytest.mark.parametrize("provider_kind", ["spoolman", "bambuddy", "spoolease"])
@pytest.mark.parametrize("target", [
    "http://example.com/api/v1/spool",
    "https://example.com/",
    "http://8.8.8.8/",
])
def test_a_redirect_off_the_local_network_is_refused(provider_kind, target):
    """A local address is not a promise about where the second request goes."""
    from snapstudio_core import material_providers as mp

    with _Redirector(target) as server:
        out = mp.read(provider_kind, f"127.0.0.1:{server.port}", **_read_kwargs(provider_kind))

    assert out["available"] is False
    assert "not on your own network" in out["error"]
    assert server.hits, "the local server was never reached, so nothing was proved"


@pytest.mark.parametrize("provider_kind", ["spoolman", "bambuddy", "spoolease"])
def test_a_redirect_that_stays_local_is_still_followed(provider_kind):
    """The rule is about leaving the network, not about redirects."""
    import json as _json

    from snapstudio_core import material_providers as mp

    import http.server
    import threading

    if provider_kind == "spoolease":
        import sys as _sys
        _sys.path.insert(0, __file__.rsplit("tests", 1)[0] + "tests")
        from fixtures.providers.spoolease_fake import FIXED_NONCE_BODY

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if "moved" not in self.path:
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{port}/moved")
                self.end_headers()
                return
            if provider_kind == "spoolease":
                body = FIXED_NONCE_BODY.encode()
                content_type = "text/plain"
            else:
                body = _json.dumps([]).encode()
                content_type = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        out = mp.read(provider_kind, f"127.0.0.1:{port}", **_read_kwargs(provider_kind))
    finally:
        server.shutdown()
        server.server_close()

    assert out["available"] is True
    if provider_kind == "spoolease":
        assert len(out["spools"]) == 3
    else:
        assert out["spools"] == []


def test_the_redirect_rule_is_one_rule_for_every_provider():
    """One opener, so it cannot be true of one provider and not another."""
    from snapstudio_core import material_providers as mp

    assert any(isinstance(h, mp._LocalOnlyRedirects) for h in mp._OPENER.handlers)


# --- credentials must not follow a cross-host redirect (item E hardening) ---
#
# No provider reader sends an Authorization header today — none of them
# supports a credential yet. This is tested directly against the handler
# rather than through `read()`/`spoolman()`/`bambuddy()` because there is no
# public path to attach one yet; the point is to have the protection already
# in place, and already proven, before one exists.

def _request(url: str, *, authorization: str | None = None) -> object:
    import urllib.request as _ur
    headers = {"Accept": "application/json"}
    if authorization is not None:
        headers["Authorization"] = authorization
    return _ur.Request(url, headers=headers)


def test_a_credentialed_request_refuses_a_redirect_to_a_different_local_host():
    from snapstudio_core import material_providers as mp

    req = _request("http://127.0.0.1:1234/api", authorization="Bearer secret-token")
    with pytest.raises(mp.InvalidProviderAddress, match="carried credentials"):
        mp._LocalOnlyRedirects().redirect_request(
            req, None, 302, "Found", {}, "http://127.0.0.2:1234/api")


def test_a_credentialed_request_still_follows_a_same_host_redirect():
    """The rule is about the host changing, not about redirects generally —
    the same distinction the local-network rule already draws."""
    from snapstudio_core import material_providers as mp

    req = _request("http://127.0.0.1:1234/api", authorization="Bearer secret-token")
    new_req = mp._LocalOnlyRedirects().redirect_request(
        req, None, 302, "Found", {}, "http://127.0.0.1:1234/moved")
    assert new_req is not None


def test_a_request_with_no_credentials_still_follows_a_cross_host_local_redirect():
    """Nothing here restricts an ordinary redirect that carries nothing worth
    protecting — only a credentialed one is refused."""
    from snapstudio_core import material_providers as mp

    req = _request("http://127.0.0.1:1234/api")
    new_req = mp._LocalOnlyRedirects().redirect_request(
        req, None, 302, "Found", {}, "http://127.0.0.2:1234/api")
    assert new_req is not None


def test_authorization_header_check_is_case_insensitive():
    from snapstudio_core import material_providers as mp

    req = _request("http://127.0.0.1:1234/api")
    req.add_header("authorization", "Bearer secret-token")  # lowercase, as a real client might send
    with pytest.raises(mp.InvalidProviderAddress, match="carried credentials"):
        mp._LocalOnlyRedirects().redirect_request(
            req, None, 302, "Found", {}, "http://127.0.0.2:1234/api")


def test_off_network_refusal_still_wins_over_the_credential_check():
    """A redirect that leaves the network entirely is refused for that reason
    even when it also happens to carry credentials — the more serious defect
    is reported, not silently superseded by the newer check."""
    from snapstudio_core import material_providers as mp

    req = _request("http://127.0.0.1:1234/api", authorization="Bearer secret-token")
    with pytest.raises(mp.InvalidProviderAddress, match="not on your own network"):
        mp._LocalOnlyRedirects().redirect_request(
            req, None, 302, "Found", {}, "http://example.com/")


# --- #39 r4 M1: OffNetworkAddress marks locality/redirect refusals only, ----
# --- distinctly from a pure format refusal or the credential-redirect one ---

def test_off_network_address_is_an_invalid_provider_address():
    """`OffNetworkAddress` must be catchable by every existing
    `except InvalidProviderAddress` and `isinstance` check."""
    from snapstudio_core import material_providers as mp

    assert issubclass(mp.OffNetworkAddress, mp.InvalidProviderAddress)
    assert isinstance(mp.OffNetworkAddress("boom"), mp.InvalidProviderAddress)


def test_validate_provider_url_off_network_case_is_the_subclass():
    from snapstudio_core import material_providers as mp

    with pytest.raises(mp.OffNetworkAddress):
        mp.validate_provider_url("http://8.8.8.8:7912")


@pytest.mark.parametrize("address", [
    "",
    "http://192.168.1.9:7912/api/v1/spool",
    "ftp://192.168.1.9",
    "http://user:secret@192.168.1.9:7912",
    "http://192.168.1.9:notaport",
])
def test_validate_provider_url_format_refusals_are_not_the_off_network_subclass(address):
    """A format problem (a path, a bad scheme, credentials, a bad port, an
    empty address) must stay a base `InvalidProviderAddress`, never the
    `OffNetworkAddress` subclass — `service._with_providers` (M1) uses that
    distinction to decide whether to replace the message."""
    from snapstudio_core import material_providers as mp

    with pytest.raises(mp.InvalidProviderAddress) as raised:
        mp.validate_provider_url(address)
    assert not isinstance(raised.value, mp.OffNetworkAddress)


def test_a_credentialed_cross_host_redirect_is_not_off_network():
    """The credential/cross-host redirect refusal is a different defect from
    leaving the network — it must stay a base `InvalidProviderAddress`, not
    `OffNetworkAddress`, so the host-free replacement in
    `service._with_providers` never fires for it."""
    from snapstudio_core import material_providers as mp

    req = _request("http://127.0.0.1:1234/api", authorization="Bearer secret-token")
    with pytest.raises(mp.InvalidProviderAddress, match="carried credentials") as raised:
        mp._LocalOnlyRedirects().redirect_request(
            req, None, 302, "Found", {}, "http://127.0.0.2:1234/api")
    assert not isinstance(raised.value, mp.OffNetworkAddress)


def test_a_redirect_off_the_network_raises_the_off_network_subclass():
    from snapstudio_core import material_providers as mp

    with pytest.raises(mp.OffNetworkAddress):
        mp._LocalOnlyRedirects().redirect_request(
            _request("http://127.0.0.1:1234/api"), None, 302, "Found", {},
            "http://example.com/")


# --- S-1: 6to4 / Teredo / NAT64 route over the public internet ---------------
#
# Python's `ipaddress` module marks 2002::/16 (6to4), 2001::/32 (Teredo, a
# subset of the 2001::/23 range it lists) and 64:ff9b:1::/48 (the RFC 8215
# NAT64 local-use prefix) `is_private`, because that follows the IANA
# special-purpose registry's "not globally unique" wording rather than "does
# not leave this network" — but 6to4/Teredo packets are relayed by a
# third-party host on the public internet, and a NAT64 address exists to
# reach an arbitrary IPv4 destination. Each must be refused by both address
# predicates, and a redirect that lands on one must be refused too.

_6TO4_EXAMPLE = "2002:c0a8:101::"          # embeds 192.168.1.1
_TEREDO_EXAMPLE = "2001::c0a8:6407"        # a Teredo client address
_NAT64_WELL_KNOWN_EXAMPLE = "64:ff9b::c0a8:101"    # embeds 192.168.1.1, but is_global
_NAT64_LOCAL_EXAMPLE = "64:ff9b:1::c0a8:101"       # the RFC 8215 local-use prefix


@pytest.mark.parametrize("address", [
    _6TO4_EXAMPLE, _TEREDO_EXAMPLE, _NAT64_WELL_KNOWN_EXAMPLE, _NAT64_LOCAL_EXAMPLE])
def test_host_is_local_refuses_internet_transit_tunnels(address):
    from snapstudio_core.material_providers import _host_is_local

    assert _host_is_local(address) is False


@pytest.mark.parametrize("address", [
    _6TO4_EXAMPLE, _TEREDO_EXAMPLE, _NAT64_WELL_KNOWN_EXAMPLE, _NAT64_LOCAL_EXAMPLE])
def test_ip_is_local_refuses_internet_transit_tunnels(address):
    from snapstudio_core.material_providers import _ip_is_local

    assert _ip_is_local(address) is False


def test_host_is_local_still_accepts_an_ordinary_private_v6_address():
    """The tunnel exclusion must not swallow ordinary ULA/link-local traffic."""
    from snapstudio_core.material_providers import _host_is_local

    assert _host_is_local("fd00::1") is True
    assert _host_is_local("fe80::1") is True


def test_an_ipv4_mapped_address_is_judged_by_its_embedded_ipv4():
    from snapstudio_core.material_providers import _host_is_local, _ip_is_local

    assert _host_is_local("::ffff:192.168.1.1") is True
    assert _ip_is_local("::ffff:192.168.1.1") is True
    assert _host_is_local("::ffff:93.184.216.34") is False
    assert _ip_is_local("::ffff:93.184.216.34") is False


def test_a_redirect_to_a_6to4_address_is_refused():
    """A local server redirecting to a 6to4 literal is the same defect as
    redirecting to a public IPv4 address — routes over the public internet
    despite `ipaddress` calling the prefix "private"."""
    from snapstudio_core import material_providers as mp

    target = f"http://[{_6TO4_EXAMPLE}]/api/v1/spool"
    with _Redirector(target) as server:
        out = mp.read("spoolman", f"127.0.0.1:{server.port}")

    assert out["available"] is False
    assert "not on your own network" in out["error"]
    assert server.hits, "the local server was never reached, so nothing was proved"
