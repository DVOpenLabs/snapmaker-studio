"""SpoolEase, read-only: the wire protocol, the error map, and honesty.

Covers the frozen §5.4 vectors, the fake-server error modes named in the
implementation handoff (correct/wrong/missing key, malformed, truncated,
oversized, unreachable, local redirect, public redirect blocked, cross-host
credential redirect blocked, valid parse, missing weight, derived weight,
duplicate spool IDs, slot mapping, IPv4, IPv6, .local handling), and the
diagnostics pin (no key, ever).
"""
from __future__ import annotations

import json
import socket
import sys

import pytest

sys.path.insert(0, __file__.rsplit("tests", 1)[0] + "tests")

from fixtures.providers.spoolease_fake import (FIXTURE_CSV_SHA256, FIXTURE_KEY,
                                               EMPTY_CSV_BODY, FIXED_NONCE_BODY,
                                               SpoolEaseFake)

from snapstudio_core import material_providers as mp
from snapstudio_core import spoolease_wire as wire

pytestmark = pytest.mark.filterwarnings("ignore")


# --- AC-0: the frozen vectors, reproduced -------------------------------------

def test_kdf_known_answer():
    derived = wire.derive_key(FIXTURE_KEY.encode("utf-8"))
    assert derived.hex() == ("1d46d10010514ebab8baa38bb66a45de4b29af058ad7d93ab97"
                             "089355dedc9b6")


def test_f32_known_vectors():
    assert wire.decode_f32("AABIQQ") == 12.5
    assert wire.decode_f32("AACAvw") == -1.0
    assert wire.decode_f32("zczMPQ") == pytest.approx(0.1, abs=1e-6)
    assert wire.decode_f32("") == 0.0
    with pytest.raises(wire.F32DecodeError):
        wire.decode_f32("AADAfw")  # NaN
    with pytest.raises(wire.F32DecodeError):
        wire.decode_f32("AACAfw")  # +inf


def test_fixture_csv_sha256_is_frozen():
    assert FIXTURE_CSV_SHA256 == "26c7ffdeec3d3a484a9361f642487cb87134ce61df14934366d2fa38b184ec4d"


def test_fixed_nonce_vector_is_frozen():
    assert len(FIXED_NONCE_BODY) == 479
    assert FIXED_NONCE_BODY.startswith("AAECAwQFBgcICQoL")


def test_empty_csv_vector_is_frozen():
    assert EMPTY_CSV_BODY == "AAECAwQFBgcICQoLvBh7NF8/N1h8EeQoKmJOTg"
    assert len(EMPTY_CSV_BODY) == 38


def test_fixed_nonce_vector_decrypts_to_the_fixture_csv():
    nonce, ct = wire.decode_frame(FIXED_NONCE_BODY)
    plaintext = wire.decrypt(FIXTURE_KEY.encode("utf-8"), nonce, ct)
    import hashlib
    assert hashlib.sha256(plaintext).hexdigest() == FIXTURE_CSV_SHA256


# --- correct / wrong / missing key --------------------------------------------

def test_correct_key_reads_the_fixture_spools():
    with SpoolEaseFake(mode="ok") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["available"] is True
    assert out["error_code"] is None
    assert out["weight_source"] == "scale"
    assert [s["id"] for s in out["spools"]] == ["1", "2", "3"]


def test_wrong_key_is_authentication_failed_and_leaks_nothing():
    with SpoolEaseFake(mode="wrong_key") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["available"] is False
    assert out["error_code"] == "authentication_failed"
    dumped = json.dumps(out)
    assert FIXTURE_KEY not in dumped
    assert wire.derive_key(FIXTURE_KEY.encode()).hex() not in dumped


def test_missing_key_never_opens_a_socket(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("Studio dialled the network with no key")
    monkeypatch.setattr(mp, "_resolve", explode)
    out = mp.read("spoolease", "http://192.168.1.50", key="")
    assert out["error_code"] == "key_missing"
    out2 = mp.read("spoolease", "http://192.168.1.50", key="   \t  ")
    assert out2["error_code"] == "key_missing"


def test_unencodable_key_never_opens_a_socket(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("Studio dialled the network with a bad key")
    monkeypatch.setattr(mp, "_resolve", explode)
    out = mp.read("spoolease", "http://192.168.1.50", key="\ud800")
    assert out["error_code"] == "key_invalid"


def test_the_reference_clients_own_trim_semantics():
    with SpoolEaseFake(mode="ok") as fake:
        out = mp.read("spoolease", fake.url, key=f"  {FIXTURE_KEY} ")
    assert out["available"] is True  # trimmed like the reference config page


# --- malformed / truncated / oversized / unreachable --------------------------

def test_malformed_csv_is_a_whole_read_failure():
    with SpoolEaseFake(mode="malformed_csv") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["error_code"] == "csv"
    assert out["available"] is False


def test_truncated_frame_is_framing():
    with SpoolEaseFake(mode="short_frame") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["error_code"] == "framing"


def test_garbage_body_is_framing():
    with SpoolEaseFake(mode="garbage_b64") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["error_code"] == "framing"


def test_oversized_body_is_refused():
    with SpoolEaseFake(mode="oversized") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["error_code"] == "oversized"


def test_unreachable_port_is_transport():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # nothing listening now
    out = mp.read("spoolease", f"http://127.0.0.1:{port}", key=FIXTURE_KEY, timeout=1.0)
    assert out["error_code"] == "transport"
    assert out["available"] is False


def test_early_close_after_status_is_transport_not_empty_body():
    with SpoolEaseFake(mode="close_before_status") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["error_code"] == "transport"
    assert "RemoteDisconnected" in out["error"]


def test_partial_body_with_content_length_mismatch_is_transport():
    with SpoolEaseFake(mode="truncated_after_headers") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY, timeout=1.0)
    assert out["error_code"] == "transport"


def test_genuinely_empty_body_is_empty_body_not_framing():
    with SpoolEaseFake(mode="empty_body") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["error_code"] == "empty_body"


def test_encrypted_empty_csv_is_a_successful_read_with_zero_spools():
    with SpoolEaseFake(mode="empty_csv") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["available"] is True
    assert out["spools"] == []


def test_http_error_status_is_http_status_not_transport():
    with SpoolEaseFake(mode="http_500") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["error_code"] == "http_status"
    assert out["error_code"] != "transport"


# --- redirects: local ok, public refused, cross-host credential refused ------

def test_local_redirect_is_followed():
    with SpoolEaseFake(mode="redirect_same_host") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["available"] is True
    assert fake.hits[0] == "/api/spools"
    assert fake.hits[-1] == "/moved"


def test_public_redirect_is_refused():
    with SpoolEaseFake(mode="redirect_public", redirect_target="http://example.com/") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["error_code"] == "invalid_address"
    assert "not on your own network" in out["error"]
    assert fake.hits, "the local server was never reached, so nothing was proved"


def test_cross_host_local_redirect_is_followed_with_no_credential_header():
    """No SpoolEase reader sends a credential header today, so this pins the
    shared `_LocalOnlyRedirects` behaviour on the actual read path: a
    same-network cross-host redirect is followed (only a *credentialed*
    request refusing a *cross-host* hop is the rule the class enforces —
    exercised directly in test_provider_address_safety.py). A genuine
    cross-host redirect: the initial request goes to the literal "127.0.0.1"
    and the 302 sends it to the literal "localhost" — a different host
    string, same loopback port — not merely a different path on the same
    host as the earlier `redirect_same_host` mode exercises."""
    with SpoolEaseFake(mode="redirect_cross_host_local") as fake:
        fake.redirect_target = f"http://localhost:{fake.port}/moved"
        out = mp.read("spoolease", f"127.0.0.1:{fake.port}", key=FIXTURE_KEY)
    assert out["available"] is True
    assert fake.hits[0] != "/moved"
    assert fake.hits[-1] == "/moved"


# --- valid parse / missing weight / derived weight / duplicate ids -----------

def test_valid_parse_matches_the_frozen_expectations():
    with SpoolEaseFake(mode="ok") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    by_id = {s["id"]: s for s in out["spools"]}
    assert by_id["1"]["remaining_g"] == 549.5
    assert by_id["1"]["remaining_quality"] == "derived"
    assert by_id["1"]["remaining_as_of"] is None
    assert any("estimate" in n for n in by_id["1"]["notes"])
    assert by_id["2"]["remaining_g"] == 400.0
    assert by_id["2"]["remaining_quality"] == "derived"
    assert by_id["3"]["remaining_g"] is None
    assert by_id["3"]["remaining_quality"] == "unknown"
    assert out["remaining_known"] is True


def test_missing_weight_spool_is_unknown_not_zero():
    with SpoolEaseFake(mode="ok") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    spool3 = next(s for s in out["spools"] if s["id"] == "3")
    assert spool3["remaining_g"] is None
    assert spool3["remaining_quality"] == "unknown"


def test_duplicate_spool_ids_are_a_whole_read_failure():
    with SpoolEaseFake(mode="duplicate_ids") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["error_code"] == "csv"
    assert out["available"] is False


def test_a_single_trailing_newline_is_allowed():
    """The frozen contract: one trailing newline is not a blank record —
    `csv.reader` never emits a phantom empty row for it, and `parse_csv`
    must not either."""
    one_row = "1,,PLA,,,,,,1000,250,,900,,,,,,,,,\n"
    records = wire.parse_csv(one_row)
    assert len(records) == 1
    assert records[0]["id"] == "1"


def test_a_blank_record_elsewhere_is_a_whole_read_failure():
    """A genuinely blank CSV record (a blank line between two real rows, not
    a single trailing newline) must fail the whole read like any other
    malformed row — not be silently dropped (Sol r3 item 2)."""
    two_rows_with_blank_between = (
        "1,,PLA,,,,,,1000,250,,900,,,,,,,,,\n"
        "\n"
        "2,,PLA,,,,,,1000,250,,900,,,,,,,,,\n")
    with pytest.raises(wire.SpoolEaseWireError) as excinfo:
        wire.parse_csv(two_rows_with_blank_between)
    assert excinfo.value.code == "csv"


def test_fixture_csv_still_parses_after_the_blank_record_fix():
    """The real captured fixture (a single trailing newline, no blank
    records) must still parse cleanly with the stricter blank-record
    handling above."""
    with SpoolEaseFake(mode="ok") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["available"] is True
    assert len(out["spools"]) >= 1


def test_negative_consumption_disqualifies_the_spool_both_columns():
    """S-N1, through the real `spoolease()` reader against the fake — not
    just `parse_csv`: a negative figure in *either* consumption column must
    leave `remaining_g` None and carry the bad-consumption note, and a NaN
    (which `decode_f32` itself refuses) must do the same."""
    neg_add_csv = "1,,PLA,,,,,,1000,250,,900,,,,,gAAAvw,,,,\n"      # ~-0.5 in consumed_since_add
    neg_weight_csv = "1,,PLA,,,,,,1000,250,,900,,,,,,AACAvw,,,\n"   # -1.0 in consumed_since_weight
    nan_add_csv = "1,,PLA,,,,,,1000,250,,900,,,,,AADAfw,,,,\n"      # NaN in consumed_since_add

    for csv_text in (neg_add_csv, neg_weight_csv, nan_add_csv):
        with SpoolEaseFake(mode="custom", plaintext=csv_text.encode()) as fake:
            out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
        assert out["available"] is True, csv_text
        spool = out["spools"][0]
        assert spool["remaining_g"] is None, csv_text
        assert spool["remaining_quality"] == "unknown", csv_text
        assert any("consumption figure" in n for n in spool["notes"]), (csv_text, spool["notes"])


# --- slot mapping, IPv4, IPv6, .local -----------------------------------------

def test_slot_mapping_by_string_id():
    with SpoolEaseFake(mode="ok") as fake:
        out = mp.read("spoolease", fake.url, slot_map={"1": "1", "2": "2"}, key=FIXTURE_KEY)
    slots = {s["slot"]: s for s in out["slots"]}
    assert slots[1]["spool_id"] == "1"
    assert slots[1]["remaining_g"] == 549.5
    assert slots[2]["spool_id"] == "2"
    assert slots[2]["remaining_g"] == 400.0


def test_ipv4_loopback_is_reachable():
    with SpoolEaseFake(mode="ok") as fake:
        out = mp.read("spoolease", f"http://127.0.0.1:{fake.port}", key=FIXTURE_KEY)
    assert out["available"] is True


def test_ipv6_loopback_is_reachable():
    import http.server
    import threading

    class Srv6(http.server.HTTPServer):
        address_family = socket.AF_INET6

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = FIXED_NONCE_BODY.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = Srv6(("::1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        out = mp.read("spoolease", f"http://[::1]:{port}", key=FIXTURE_KEY)
    finally:
        server.shutdown()
        server.server_close()
    assert out["available"] is True


def test_local_name_resolving_only_to_a_public_address_is_refused(monkeypatch):
    def fake_resolve(host, port, type=None):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]
    monkeypatch.setattr(mp, "_resolve", fake_resolve)
    out = mp.read("spoolease", "http://spoolease.local:80", key=FIXTURE_KEY)
    assert out["error_code"] == "invalid_address"
    assert "own network" in out["error"]


# --- diagnostics: no key, ever -------------------------------------------------

def test_diagnostics_never_contain_the_key_or_derived_key():
    from snapstudio_core import diagnostics as diag

    with SpoolEaseFake(mode="ok") as fake:
        mp.read("spoolease", fake.url, key=FIXTURE_KEY)  # exercised; result discarded
        preview = diag.preview(host=None, port=7125)
    dumped = json.dumps(preview)
    assert FIXTURE_KEY not in dumped
    assert wire.derive_key(FIXTURE_KEY.encode()).hex() not in dumped


def test_provider_status_never_contains_the_key():
    from snapstudio_api import service

    with SpoolEaseFake(mode="ok") as fake:
        out = service.provider_test(fake.url, provider="spoolease", provider_key=FIXTURE_KEY)
    dumped = json.dumps(out)
    assert FIXTURE_KEY not in dumped
    assert out["with_weight"] == 2
    assert out["error_code"] is None
    assert "estimate" in out["detail"] or "scale" in out["detail"]


# --- D-suite: key semantics, in full (plan-39 v3 §7, D-1..D-8) ---------------

def test_d2_a_fixed_key_never_trimmed_on_the_device_mismatches_a_trimmed_typed_key():
    """O-3: the reference client's fixed-key SETTER sends `.value` untrimmed,
    so a device whose fixed key was set with surrounding whitespace has a real
    key that includes it. Studio always trims what the person types before
    deriving, so it can never reproduce that key — this documents the
    consequence rather than treating it as a Studio bug."""
    device_key = "  padded-secret  "  # never trimmed when set on the device
    with SpoolEaseFake(mode="ok", key=device_key) as fake:
        out = mp.read("spoolease", fake.url, key=device_key)  # Studio trims first
    assert out["error_code"] == "authentication_failed"


def test_d3_inner_whitespace_is_preserved_not_stripped():
    key = "sch luss el-7"  # internal space must survive the JS-trim
    with SpoolEaseFake(mode="ok", key=key) as fake:
        out = mp.read("spoolease", fake.url, key=f"  {key}  ")  # only outer padding
    assert out["available"] is True


def test_d4_unicode_key_round_trips():
    key = "Schlüssel-7"
    with SpoolEaseFake(mode="ok", key=key) as fake:
        out = mp.read("spoolease", fake.url, key=key)
    assert out["available"] is True


def test_d5_a_200_char_key_is_accepted_no_length_cap():
    """plan-39 §2 item 3: 'Crypto' decision states no length cap; PBKDF2
    pre-hashes long keys so the cost is flat regardless of key length."""
    key = "x" * 200
    with SpoolEaseFake(mode="ok", key=key) as fake:
        out = mp.read("spoolease", fake.url, key=key)
    assert out["available"] is True


# --- A-8: Windows numeric-scope resolution (this machine is Windows) --------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only: numeric scope resolution")
def test_a8_windows_resolves_a_numeric_ipv6_scope_and_keeps_it_local():
    """plan-39 §1 O-4: on Windows, `getaddrinfo('fe80::1%<ifindex>')` resolves
    to a sockaddr whose scope survives, and that address still passes
    `_ip_is_local` (link-local). Resolve-only — no connect, since there is no
    real interface with index 1 guaranteed to answer on this host; the point
    is that the *resolver* accepts the numeric form and the scope is not lost
    or mangled on the way to `_ip_is_local`."""
    try:
        answers = socket.getaddrinfo("fe80::1%1", 80, type=socket.SOCK_STREAM)
    except OSError:
        pytest.skip("this host has no interface with numeric index 1")
    sockaddr = answers[0][4]
    ip, _port, _flow, scope = sockaddr
    assert scope == 1
    assert mp._ip_is_local(ip) is True


# --- A-9: real TLS (S-N2 adopted the real test; the scoped-IPv6 HTTPS claim
# was dropped, the TLS test itself was not) -----------------------------------

def _make_test_cert(tmp_path, *, common_name: str = "localhost", include_ip_san: bool = True):
    """A short-lived self-signed CA-less leaf, written under pytest's own
    `tmp_path` so the PEM/key files are cleaned up with the rest of the test's
    temp directory rather than leaking into the OS temp folder forever.
    ``include_ip_san=False`` builds a leaf that is valid for ``common_name``
    only, so a request to the IP literal ``127.0.0.1`` fails verification —
    used by the negative case below."""
    import datetime
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    san = [x509.DNSName(common_name)]
    if include_ip_san:
        san.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .sign(key, hashes.SHA256()))

    key_pem = key.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.TraditionalOpenSSL,
                                serialization.NoEncryption())
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_path = tmp_path / f"{common_name}-key.pem"
    cert_path = tmp_path / f"{common_name}-cert.pem"
    key_path.write_bytes(key_pem)
    cert_path.write_bytes(cert_pem)
    return str(key_path), str(cert_path)


def _tls_server(key_path, cert_path, *, body: bytes = FIXED_NONCE_BODY.encode()):
    import ssl
    import threading as _threading
    import http.server

    seen_sni = []
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(cert_path, key_path)

    def sni_callback(sslsock, server_name, ctx):
        seen_sni.append(server_name)

    server_ctx.sni_callback = sni_callback

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    server.socket = server_ctx.wrap_socket(server.socket, server_side=True)
    port = server.server_address[1]
    thread = _threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, seen_sni


def test_a9_https_verifies_the_certificate_and_records_sni(tmp_path):
    import ssl

    key_path, cert_path = _make_test_cert(tmp_path)
    server, port, seen_sni = _tls_server(key_path, cert_path)
    try:
        client_ctx = ssl.create_default_context(cafile=cert_path)
        opener = mp._build_opener(context=client_ctx)
        real_opener = mp._OPENER
        mp._OPENER = opener
        try:
            out = mp.read("spoolease", f"https://127.0.0.1:{port}", key=FIXTURE_KEY, timeout=5.0)
        finally:
            mp._OPENER = real_opener
    finally:
        server.shutdown()
        server.server_close()

    assert out["available"] is True
    # RFC 6066 forbids sending an IP literal as the SNI extension, and
    # `_LocalOnlyHTTPSConnection` passes `self.host` (the literal
    # "127.0.0.1" used above) as `server_hostname` — Python's `ssl` omits
    # the extension for an IP `server_hostname` rather than sending it as
    # text, so the server's callback deterministically sees no server name.
    # The certificate still verifies, because of the IP SAN above.
    assert seen_sni == [None]


def test_a9_negative_wrong_certificate_name_is_refused_and_host_free(tmp_path):
    """A leaf that is valid for a different name must fail verification, and
    the failure text must not name the host Studio was connecting to (S-2)."""
    import ssl

    key_path, cert_path = _make_test_cert(tmp_path, common_name="other.example", include_ip_san=False)
    server, port, _seen_sni = _tls_server(key_path, cert_path)
    try:
        # Trust the leaf's own issuer (itself, self-signed) but do NOT
        # disable hostname checking — the point is that the *name* fails,
        # not that the chain is untrusted.
        client_ctx = ssl.create_default_context(cafile=cert_path)
        opener = mp._build_opener(context=client_ctx)
        real_opener = mp._OPENER
        mp._OPENER = opener
        try:
            out = mp.read("spoolease", f"https://127.0.0.1:{port}", key=FIXTURE_KEY, timeout=5.0)
        finally:
            mp._OPENER = real_opener
    finally:
        server.shutdown()
        server.server_close()

    assert out["available"] is False
    assert out["error_code"] == "transport"
    assert "127.0.0.1" not in out["error"]
    assert "other.example" not in out["error"]


# --- M-2 (v3.4): wire errors never masquerade as transport errors ------------

def test_wire_error_types_are_never_oserror_subclasses():
    import http.client

    assert not issubclass(wire.SpoolEaseWireError, OSError)
    assert not issubclass(wire.SpoolEaseWireError, http.client.HTTPException)
    assert not issubclass(wire.F32DecodeError, OSError)


def test_reset_mid_body_is_transport_never_framing_or_csv():
    with SpoolEaseFake(mode="reset_mid_body") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY, timeout=2.0)
    assert out["error_code"] == "transport"
    assert out["error_code"] not in ("framing", "csv")
    assert FIXTURE_KEY not in json.dumps(out)


# --- L-2 (v3.4): wrapped URLError(reason=TimeoutError) through the REAL
# transport, for Spoolman and Bambuddy, against a genuinely non-answering
# local socket (not a monkeypatched exception) -------------------------------

def _non_answering_socket():
    """A bound, listening socket that never accepts — every connect() to it
    succeeds at the TCP level and then simply gets no response, so a read
    against it times out for real."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)  # never call accept() -- backlog fills, further connects hang
    return s


def test_spoolman_wrapped_timeout_through_the_real_transport():
    blackhole = _non_answering_socket()
    port = blackhole.getsockname()[1]
    try:
        out = mp.spoolman(f"http://127.0.0.1:{port}", timeout=0.5)
    finally:
        blackhole.close()
    assert out["available"] is False
    assert "did not answer in time" in out["error"]


def test_bambuddy_wrapped_timeout_through_the_real_transport():
    blackhole = _non_answering_socket()
    port = blackhole.getsockname()[1]
    try:
        out = mp.bambuddy(f"http://127.0.0.1:{port}", timeout=0.5)
    finally:
        blackhole.close()
    assert out["available"] is False
    assert "did not answer in time" in out["error"]


def test_status_with_no_content_length_then_close_is_empty_body():
    """v3.4 M-3: a status line with no Content-Length, then a clean close
    with no body, reads as `empty_body` — the status line and headers did
    arrive, unlike `close_before_status`."""
    with SpoolEaseFake(mode="status_no_content_length_then_close") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY, timeout=2.0)
    assert out["error_code"] == "empty_body"


# --- Sol r3 item 3: a non-certificate SSLError must not read as a --------
# --- certificate-verification failure -------------------------------------

def _plaintext_ok_handler():
    import http.server
    import json as _json

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = _json.dumps([]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return Handler


def _plaintext_http_server():
    import http.server
    import threading

    server = http.server.HTTPServer(("127.0.0.1", 0), _plaintext_ok_handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.parametrize("kind,reader_name,make_out", [
    ("spoolman", "Spoolman", lambda url: mp.spoolman(url, timeout=2.0)),
    ("bambuddy", "Bambuddy", lambda url: mp.bambuddy(url, timeout=2.0)),
])
def test_plaintext_server_on_https_is_not_a_certificate_failure(kind, reader_name, make_out):
    """A plain HTTP server behind an `https://` URL fails the TLS handshake
    itself (`WRONG_VERSION_NUMBER` or similar) — a real `ssl.SSLError`, but
    never an `ssl.SSLCertVerificationError`, because no certificate was ever
    offered to verify. That must not be described as a certificate problem,
    and must stay host-free like every other transport sentence here."""
    server = _plaintext_http_server()
    port = server.server_address[1]
    try:
        out = make_out(f"https://127.0.0.1:{port}")
    finally:
        server.shutdown()
        server.server_close()
    assert out["available"] is False
    assert "certificate" not in out["error"].lower()
    assert "127.0.0.1" not in out["error"]
    assert "secure connection" in out["error"].lower()


def test_spoolease_plaintext_server_on_https_is_not_a_certificate_failure():
    server = _plaintext_http_server()
    port = server.server_address[1]
    try:
        out = mp.read("spoolease", f"https://127.0.0.1:{port}", key=FIXTURE_KEY, timeout=2.0)
    finally:
        server.shutdown()
        server.server_close()
    assert out["available"] is False
    assert out["error_code"] == "transport"
    assert "certificate" not in out["error"].lower()
    assert "127.0.0.1" not in out["error"]
    assert "secure connection" in out["error"].lower()
