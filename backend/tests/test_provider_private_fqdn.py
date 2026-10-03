"""v1.3.1 (#39): a private FQDN that is not one of the conventional local suffixes (a real user's `spoolease.casa.me`
-> 192.168.x.x) is local because of what it RESOLVES to, not because of a guessed suffix list. Public destinations
stay refused, a mixed answer is never dialled on its public address, and a redirect is held to the same rule."""
from __future__ import annotations

import socket
import threading
import http.server

import pytest

from snapstudio_core import material_providers as mp


def _ans(ip: str, port: int = 80):
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return (fam, socket.SOCK_STREAM, 6, "", (ip, port, 0, 0) if fam == socket.AF_INET6 else (ip, port))


def _resolver(mapping):
    def resolve(host, port, type=None):
        if host in mapping:
            return [_ans(ip, port or 80) for ip in mapping[host]]
        raise socket.gaierror(socket.EAI_NONAME, "no such host")
    return resolve


@pytest.mark.parametrize("name,ips", [
    ("spoolease.casa.me", ["192.168.0.120"]),
    ("printer-room.example.net", ["10.1.2.3"]),
    ("spoolease.example.org", ["fd12:3456:789a::1"]),
    ("spoolease.example.org", ["fe80::1"]),
    ("tailnet-host.example.com", ["100.64.1.9"]),
])
def test_an_arbitrary_fqdn_resolving_only_locally_is_accepted(monkeypatch, name, ips):
    monkeypatch.setattr(mp, "_resolve", _resolver({name: ips}))
    assert mp.validate_provider_url(f"https://{name}").startswith("https://" + name)
    assert mp.validate_provider_url(name).startswith("http://" + name)  # schemeless still normalises


def test_an_fqdn_resolving_only_publicly_is_refused(monkeypatch):
    monkeypatch.setattr(mp, "_resolve", _resolver({"spoolease.casa.me": ["93.184.216.34"]}))
    with pytest.raises(mp.OffNetworkAddress):
        mp.validate_provider_url("https://spoolease.casa.me")


def test_an_fqdn_that_does_not_resolve_is_refused(monkeypatch):
    monkeypatch.setattr(mp, "_resolve", _resolver({}))
    with pytest.raises(mp.OffNetworkAddress):
        mp.validate_provider_url("https://nothing.casa.me")


def test_a_public_ip_literal_is_still_refused(monkeypatch):
    monkeypatch.setattr(mp, "_resolve", _resolver({}))
    with pytest.raises(mp.OffNetworkAddress):
        mp.validate_provider_url("http://93.184.216.34")


class _Ok(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"[]"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_a_mixed_local_and_public_answer_never_dials_the_public_address(monkeypatch):
    server = http.server.HTTPServer(("127.0.0.1", 0), _Ok)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    dialled = []
    real_socket = socket.socket

    class Recording(real_socket):
        def connect(self, address):
            dialled.append(address[0])
            return super().connect(address)

    monkeypatch.setattr(mp, "_resolve", _resolver({"spoolease.casa.me": ["93.184.216.34", "127.0.0.1"]}))
    monkeypatch.setattr(mp.socket, "socket", Recording)
    try:
        body = mp._fetch(f"http://spoolease.casa.me:{port}/api/x", timeout=3.0)
    finally:
        server.shutdown()
    assert body == b"[]"
    assert dialled == ["127.0.0.1"]


def test_an_fqdn_with_only_public_answers_is_never_dialled_even_if_it_slips_past_validation(monkeypatch):
    dialled = []
    real_socket = socket.socket

    class Recording(real_socket):
        def connect(self, address):
            dialled.append(address[0])
            return super().connect(address)

    monkeypatch.setattr(mp, "_resolve", _resolver({"evil.example.net": ["93.184.216.34"]}))
    monkeypatch.setattr(mp.socket, "socket", Recording)
    with pytest.raises(Exception) as caught:
        mp._fetch("http://evil.example.net:80/", timeout=2.0)
    assert "own network" in str(caught.value)
    assert dialled == []


def test_a_redirect_to_a_public_fqdn_is_refused(monkeypatch):
    monkeypatch.setattr(mp, "_resolve", _resolver({"public.example.net": ["93.184.216.34"]}))
    import urllib.request as ur

    req = ur.Request("http://127.0.0.1:1234/api")
    with pytest.raises(mp.OffNetworkAddress):
        mp._LocalOnlyRedirects().redirect_request(req, None, 302, "Found", {}, "http://public.example.net/x")


def test_a_redirect_to_a_private_fqdn_is_allowed_and_still_checked_at_connect(monkeypatch):
    monkeypatch.setattr(mp, "_resolve", _resolver({"nas.casa.me": ["192.168.0.5"]}))
    import urllib.request as ur

    req = ur.Request("http://127.0.0.1:1234/api")
    assert mp._LocalOnlyRedirects().redirect_request(req, None, 302, "Found", {}, "http://nas.casa.me/x") is not None
