"""A local HTTP server that speaks SpoolEase's wire protocol, for tests only.

Provenance: ``synthesised_from_upstream_source`` — built by reading the
upstream Rust source (SpoolEase `3532f8d962dd1a95c7d4ebb37beddca5bbefd39a` +
esp-hal-app-framework `0.6.1` = `43daad9d1795b21a7f4ea3ef610b328cabbfeda1`),
never captured from a real device. The fixed-nonce vector this fake can also
produce is the same one frozen in plan-39 §5.4, so the Python test suite and
the Node acceptance fake can be compared byte-for-byte.

The fixture key is ``Fx7-tEsT`` — literal, deliberately, so any accidental
leak into evidence or a screenshot is easy to grep for and impossible to
mistake for a real device's key.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import os
import threading

from snapstudio_core import spoolease_wire as wire

FIXTURE_KEY = "Fx7-tEsT"
FIXTURE_NONCE = bytes(range(12))

_CSV_PATH = os.path.join(os.path.dirname(__file__), "spoolease_3532f8d.csv")
with open(_CSV_PATH, "rb") as _f:
    FIXTURE_CSV_BYTES = _f.read()
FIXTURE_CSV_SHA256 = hashlib.sha256(FIXTURE_CSV_BYTES).hexdigest()


def _derived_key(key: str = FIXTURE_KEY) -> bytes:
    return wire.derive_key(key.encode("utf-8"))


def _encrypt(plaintext: bytes, *, key: str = FIXTURE_KEY, nonce: bytes | None = None) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = FIXTURE_NONCE if nonce is None else nonce
    ciphertext = AESGCM(_derived_key(key)).encrypt(nonce, plaintext, None)
    return (base64.b64encode(nonce).decode().rstrip("=")
            + base64.b64encode(ciphertext).decode().rstrip("="))


#: The exact 479-char body frozen in plan-39 §5.4.
FIXED_NONCE_BODY = _encrypt(FIXTURE_CSV_BYTES)
#: The exact 38-char body frozen in plan-39 §5.4 — an encrypted empty CSV.
EMPTY_CSV_BODY = _encrypt(b"")


class SpoolEaseFake:
    """A local ``/api/spools`` server with one selectable failure mode.

    Every mode from plan-39 §2 item 8 is here except the ones better tested
    directly against ``spoolease_wire`` (``noncanonical_b64`` etc. — pure
    codec cases, not network-shaped ones).
    """

    def __init__(self, mode: str = "ok", *, key: str = FIXTURE_KEY,
                redirect_target: str | None = None):
        self.mode = mode
        self.key = key
        self.redirect_target = redirect_target
        self.hits: list[str] = []
        self.host_headers: list[str] = []
        self.accept_headers: list[str | None] = []
        self.accept_encoding_headers: list[str | None] = []

    def __enter__(self):
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):  # noqa: N802 — stdlib's spelling
                owner.hits.append(self.path)
                owner.host_headers.append(self.headers.get("Host"))
                owner.accept_headers.append(self.headers.get("Accept"))
                owner.accept_encoding_headers.append(self.headers.get("Accept-Encoding"))
                mode = owner.mode
                if mode == "redirect_public":
                    self.send_response(302)
                    self.send_header("Location", owner.redirect_target or "http://example.com/")
                    self.end_headers()
                    return
                if mode == "redirect_same_host":
                    if self.path != "/moved":
                        self.send_response(302)
                        self.send_header("Location", "/moved")
                        self.end_headers()
                        return
                    mode = "ok"
                if mode == "redirect_cross_host_local":
                    self.send_response(302)
                    self.send_header("Location", owner.redirect_target)
                    self.end_headers()
                    return
                if mode == "close_before_status":
                    self.close_connection = True
                    return  # nothing sent at all -> RemoteDisconnected
                if mode == "http_500":
                    self._send_text(500, "")
                    return
                if mode == "slow":
                    import time
                    time.sleep(10)
                    self._send_text(200, FIXED_NONCE_BODY)
                    return
                if mode == "truncated_after_headers":
                    # Status line + a Content-Length that promises more than
                    # is ever sent, then the connection drops.
                    self.send_response(200)
                    self.send_header("Content-Length", "100")
                    self.end_headers()
                    self.wfile.write(b"0123456789")
                    self.close_connection = True
                    return
                if mode == "oversized":
                    body = ("A" * (4 * 1024 * 1024 + 16)).encode()
                    self._send_text(200, body.decode())
                    return
                if mode == "empty_body":
                    self._send_text(200, "")
                    return
                if mode == "garbage_b64":
                    self._send_text(200, "not-base64-at-all!!" * 3)
                    return
                if mode == "short_frame":
                    self._send_text(200, FIXED_NONCE_BODY[:20])
                    return
                if mode == "wrong_key":
                    self._send_text(200, _encrypt(FIXTURE_CSV_BYTES, key="a-different-key!"))
                    return
                if mode == "fixed_nonce":
                    self._send_text(200, FIXED_NONCE_BODY)
                    return
                if mode == "empty_csv":
                    self._send_text(200, EMPTY_CSV_BODY)
                    return
                if mode == "not_utf8":
                    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                    ct = AESGCM(_derived_key(owner.key)).encrypt(FIXTURE_NONCE, b"\xff\xfe\xfd", None)
                    body = (base64.b64encode(FIXTURE_NONCE).decode().rstrip("=")
                           + base64.b64encode(ct).decode().rstrip("="))
                    self._send_text(200, body)
                    return
                if mode == "malformed_csv":
                    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                    ct = AESGCM(_derived_key(owner.key)).encrypt(
                        FIXTURE_NONCE, b"1,only,three\n", None)
                    body = (base64.b64encode(FIXTURE_NONCE).decode().rstrip("=")
                           + base64.b64encode(ct).decode().rstrip("="))
                    self._send_text(200, body)
                    return
                if mode == "duplicate_ids":
                    dup = ("1,,PLA,,,,,,,,,,,,,,,,,,\n" "1,,PETG,,,,,,,,,,,,,,,,,,\n").encode()
                    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                    ct = AESGCM(_derived_key(owner.key)).encrypt(FIXTURE_NONCE, dup, None)
                    body = (base64.b64encode(FIXTURE_NONCE).decode().rstrip("=")
                           + base64.b64encode(ct).decode().rstrip("="))
                    self._send_text(200, body)
                    return
                # default "ok": encrypted with a random nonce, as upstream.
                self._send_text(200, _encrypt(FIXTURE_CSV_BYTES, key=owner.key))

            def _send_text(self, code: int, text: str):
                body = text.encode("ascii", errors="replace")
                self.send_response(code)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"
