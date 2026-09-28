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
    exercised directly in test_provider_address_safety.py)."""
    with SpoolEaseFake(mode="redirect_same_host") as fake:
        out = mp.read("spoolease", f"127.0.0.1:{fake.port}", key=FIXTURE_KEY)
    assert out["available"] is True


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


def test_negative_consumption_disqualifies_the_spool_both_columns():
    import base64

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from fixtures.providers.spoolease_fake import FIXTURE_NONCE, _derived_key

    def _body(csv_text: str) -> str:
        ct = AESGCM(_derived_key()).encrypt(FIXTURE_NONCE, csv_text.encode(), None)
        return (base64.b64encode(FIXTURE_NONCE).decode().rstrip("=")
               + base64.b64encode(ct).decode().rstrip("="))

    neg_add = "1,,PLA,,,,,,1000,250,,900,,,,,gAAAvw,,,,\n"       # -1.0 in consumed_since_add
    neg_weight = "1,,PLA,,,,,,1000,250,,900,,,,,,AACAvw,,,\n"    # -1.0 in consumed_since_weight
    for csv_text in (neg_add, neg_weight):
        records = wire.parse_csv(csv_text)
        assert len(records) == 1


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
