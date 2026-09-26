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
    """The reader caps what it will take from a provider, like every other reader."""
    import inspect

    from snapstudio_core import material_providers

    source = inspect.getsource(material_providers._get_json)
    assert "1024" in source and "read(" in source


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


@pytest.mark.parametrize("provider_kind", ["spoolman", "bambuddy"])
@pytest.mark.parametrize("target", [
    "http://example.com/api/v1/spool",
    "https://example.com/",
    "http://8.8.8.8/",
])
def test_a_redirect_off_the_local_network_is_refused(provider_kind, target):
    """A local address is not a promise about where the second request goes."""
    from snapstudio_core import material_providers as mp

    with _Redirector(target) as server:
        out = mp.read(provider_kind, f"127.0.0.1:{server.port}")

    assert out["available"] is False
    assert "not on your own network" in out["error"]
    assert server.hits, "the local server was never reached, so nothing was proved"


@pytest.mark.parametrize("provider_kind", ["spoolman", "bambuddy"])
def test_a_redirect_that_stays_local_is_still_followed(provider_kind):
    """The rule is about leaving the network, not about redirects."""
    import json as _json

    from snapstudio_core import material_providers as mp

    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if "moved" not in self.path:
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{port}/moved")
                self.end_headers()
                return
            body = _json.dumps([]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        out = mp.read(provider_kind, f"127.0.0.1:{port}")
    finally:
        server.shutdown()
        server.server_close()

    assert out["available"] is True
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
