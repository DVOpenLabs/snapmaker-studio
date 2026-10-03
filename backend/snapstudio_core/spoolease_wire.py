"""SpoolEase's wire protocol, and nothing else.

Pure codec: no sockets, no files, no clock. Everything here turns bytes SpoolEase
sent into Python values, or raises :class:`SpoolEaseWireError` with one of the
frozen ``error_code`` values from the protocol contract — never a raw exception
message that might carry a fragment of ciphertext or a key.

Status: **PROTOCOL VERIFIED** (SpoolEase `0.7` line, branch `0.7`
`49a8e830a7ada916f2da4b5731f2645b06f3287b`, source-read; encryption framing
unchanged from `3532f8d962dd1a95c7d4ebb37beddca5bbefd39a` + esp-hal-app-framework
`0.6.1`) / **REAL SPOOLEASE USER TEST PENDING.**

The key never leaves process memory and is never written to a log: every
function here takes it as an argument and returns without keeping a reference
to it (Python's GC will collect the derived-key bytes with everything else once
the caller's local goes out of scope — nothing here caches one).
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import math
import re
import struct

#: The exact set `String.prototype.trim()` strips in every JS engine that ships
#: SpoolEase's own config page — not Python's `str.strip()`, which differs on
#: U+FEFF, U+001C-U+001F and U+0085. See plan-39 O-3: the only shipping decrypt
#: client (the reference config page) trims outer whitespace before sending a
#: fixed key, so a Studio that does not trim cannot use a key that page can.
_JS_WS = ("\t\n\v\f\r          "
          "        　﻿")

#: `framework.rs:15-16` — the hard-coded salt every SpoolEase build derives its
#: web-app key with. Upstream's, not Studio's; Studio only reads.
KDF_SALT = b"example_salt"
KDF_ITERATIONS = 10_000
KDF_KEY_LEN = 32

#: `store.rs` / `spool_record.rs` — one CSV row per spool, no header,
#: LF-terminated. Columns 1-12 are always present; 13-25 default to "" on an
#: older (shorter) row. Columns 22-25 were added in the 0.7 line.
FIELD_COLUMNS = (
    "id", "tag_id", "material_type", "material_subtype", "color_name",
    "color_code", "note", "brand", "weight_advertised", "weight_core",
    "weight_new", "weight_current", "slicer_filament", "added_time",
    "encode_time", "added_full", "consumed_since_add", "consumed_since_weight",
    "ext_has_k", "data_origin", "tag_type",
    "assigned_location", "actual_location", "spools_count", "td",
)
REQUIRED_COLUMNS = 12
TOTAL_COLUMNS = len(FIELD_COLUMNS)

_B64_ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")

_I32_RE = re.compile(r"\A-?[0-9]{1,10}\Z")
_I32_MIN, _I32_MAX = -2_147_483_648, 2_147_483_647


class SpoolEaseWireError(Exception):
    """A protocol-level failure with a frozen `error_code` (plan-39 §4.2).

    Deliberately NOT an `OSError`/`http.client.HTTPException` subclass (plan-39
    v3.4 M-2): the reader's except-clause order relies on that distinction to
    keep a wire failure from being mistaken for a transport failure.
    """

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


class F32DecodeError(ValueError):
    """A malformed `consumed_since_*` field. Deliberately per-spool, never a
    whole-read failure (plan-39 §4.2, last paragraph) — the caller decides."""


def trim_key(raw: str) -> str:
    """The exact `String.prototype.trim()` semantics, never `str.strip()`."""
    return raw.strip(_JS_WS)


def derive_key(key_utf8: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256(key, `example_salt`, 10 000, 32) — `settings.rs:15-16`."""
    return hashlib.pbkdf2_hmac("sha256", key_utf8, KDF_SALT, KDF_ITERATIONS, KDF_KEY_LEN)


def _b64_canonical_decode(text: str) -> bytes:
    """Standard-alphabet, no-padding base64. Refuses padding characters and any
    input whose re-encoding does not reproduce the input byte-for-byte (a
    non-canonical encoding is not a decode error stdlib would catch on its
    own, and a wire that accepts one silently accepts more inputs than the
    protocol defines)."""
    if not text or any(c not in _B64_ALPHABET for c in text):
        raise ValueError("not canonical base64")
    if len(text) % 4 == 1:
        # No unpadded base64 encoding ever produces a length congruent to 1
        # mod 4 (each trailing group of 6/12/18 encoded bits produces 2, 3 or
        # 4 characters, never 1) — this length cannot be a real encoding.
        raise ValueError("bad base64 length")
    pad = (-len(text)) % 4
    data = base64.b64decode(text + "=" * pad, validate=True)
    if base64.b64encode(data).decode().rstrip("=") != text:
        raise ValueError("non-canonical base64")
    return data


def decode_frame(body: str) -> tuple[bytes, bytes]:
    """Split the wire body into (12-byte nonce, ciphertext‖16-byte GCM tag).

    `framework_web_app.rs:641-700`: ASCII body, first 16 base64 chars are the
    nonce, the remainder is ciphertext+tag, standard alphabet, no padding.
    Raises ``SpoolEaseWireError('framing')`` (§4.2 row 9) for anything else.
    """
    if not isinstance(body, str) or not body.isascii():
        raise SpoolEaseWireError("framing", "body is not ASCII")
    if len(body) < 38:
        raise SpoolEaseWireError("framing", "body too short")
    try:
        nonce = _b64_canonical_decode(body[:16])
        ciphertext = _b64_canonical_decode(body[16:])
    except ValueError as exc:
        raise SpoolEaseWireError("framing", str(exc)) from exc
    if len(nonce) != 12:
        raise SpoolEaseWireError("framing", "nonce is not 12 bytes")
    if len(ciphertext) < 16:
        raise SpoolEaseWireError("framing", "ciphertext shorter than the GCM tag")
    return nonce, ciphertext


def decrypt(key_utf8: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    """AES-256-GCM decrypt with the derived key, no AAD.

    Raises ``SpoolEaseWireError('authentication_failed')`` on a bad key or a
    damaged/truncated response (`cryptography.exceptions.InvalidTag` covers
    both — GCM cannot tell them apart, and neither can the sentence in §4.2).
    `ImportError` (the `cryptography` package is missing from this build) is
    left to the caller, which maps it to `unsupported_build` — this module
    never assumes the dependency is present at import time, only when actually
    asked to decrypt.
    """
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    derived = derive_key(key_utf8)
    try:
        return AESGCM(derived).decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise SpoolEaseWireError("authentication_failed") from exc


def decode_text(plaintext: bytes) -> str:
    """UTF-8 strict. Raises ``SpoolEaseWireError('not_text')`` otherwise."""
    try:
        return plaintext.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SpoolEaseWireError("not_text") from exc


def decode_i32_opt(value: str) -> int | None:
    """`Option<i32>` (`""` -> None; else `\\A-?[0-9]{1,10}\\Z` within i32 range).

    `"-0"` is refused rather than read as zero: SpoolEase's own encoder never
    emits it, so an incoming `"-0"` is either a hand-crafted request or a
    firmware Studio does not yet understand — either way, guessing is worse
    than saying the response could not be read (§4.2 row 12).
    """
    if value == "":
        return None
    if value == "-0" or not _I32_RE.match(value):
        raise SpoolEaseWireError("csv", "not a plain integer")
    n = int(value)
    if not (_I32_MIN <= n <= _I32_MAX):
        raise SpoolEaseWireError("csv", "integer out of i32 range")
    return n


def decode_bool_opt(value: str) -> bool | None:
    """`y/Y` -> True, `n/N` -> False, `""` -> None. Anything else is `csv`."""
    if value in ("y", "Y"):
        return True
    if value in ("n", "N"):
        return False
    if value == "":
        return None
    raise SpoolEaseWireError("csv", "not a y/Y/n/N/'' flag")


def decode_f32(value: str) -> float:
    """`utils.rs:145-176`: `""` -> 0.0; else exactly 6 chars of canonical
    standard-alphabet base64 decoding to exactly 4 bytes, little-endian
    IEEE-754. Raises :class:`F32DecodeError` — deliberately NOT
    ``SpoolEaseWireError`` — for a bad length, non-canonical encoding,
    non-finite value (NaN/Inf) or anything else malformed. Negative values are
    returned, not rejected here: whether a negative consumption figure is
    acceptable is the caller's call (it never is, but the caller decides which
    spool that disqualifies and writes the note — this function only decodes).
    """
    if value == "":
        return 0.0
    if len(value) != 6:
        raise F32DecodeError("consumed_* is not 6 base64 characters")
    try:
        raw = _b64_canonical_decode(value)
    except ValueError as exc:
        raise F32DecodeError(str(exc)) from exc
    if len(raw) != 4:
        raise F32DecodeError("consumed_* did not decode to 4 bytes")
    number = struct.unpack("<f", raw)[0]
    if not math.isfinite(number):
        raise F32DecodeError("consumed_* is not a finite number")
    return number


def decode_list(value: str) -> list[str]:
    """`deserialize_string_array` (utils.rs): `;`-joined, empty items dropped."""
    return [item for item in value.split(";") if item]


def decode_line_safe(value: str) -> str:
    """`decode_line_safe_string` (utils.rs): the escapes backslash-n,
    backslash-r and double backslash; any other backslash pair is kept as
    written."""
    out: list[str] = []
    it = iter(value)
    for ch in it:
        if ch != "\\":
            out.append(ch)
            continue
        nxt = next(it, None)
        if nxt is None:
            out.append("\\")
        elif nxt == "n":
            out.append("\n")
        elif nxt == "r":
            out.append("\r")
        elif nxt == "\\":
            out.append("\\")
        else:
            out.append("\\" + nxt)
    return "".join(out)


def _count(value: str) -> int:
    n = decode_i32_opt(value)
    if n is None or n < 1:
        raise SpoolEaseWireError("csv", "spools_count is not a positive integer")
    return n


def decode_f32_plain_opt(value: str) -> float | None:
    """`td`: `Option<f32>` written as plain decimal text (`""` -> None)."""
    if value == "":
        return None
    try:
        number = float(value)
    except ValueError as exc:
        raise SpoolEaseWireError("csv", "td is not a number") from exc
    if not math.isfinite(number):
        raise SpoolEaseWireError("csv", "td is not finite")
    return number


def parse_csv(plaintext: str) -> list[dict]:
    """The decrypted plaintext -> one dict per spool, columns typed except the
    two `consumed_since_*` fields (left as raw strings — see :func:`decode_f32`).

    Whole-read failure (raises ``SpoolEaseWireError('csv')``) on: a row with
    fewer than 12 or more than 25 columns, an empty or duplicate spool id, a
    malformed integer or boolean field, or quoting `csv.reader` itself cannot
    parse. An empty plaintext is zero spools, not an error — the encrypted
    empty-CSV vector is a successful read with nothing in it (§4.2, after the
    error table).
    """
    if plaintext == "":
        return []
    try:
        rows = list(csv.reader(io.StringIO(plaintext), strict=True))
    except csv.Error as exc:
        raise SpoolEaseWireError("csv", f"malformed CSV: {exc}") from exc

    records: list[dict] = []
    seen_ids: set[str] = set()
    for row in rows:
        if not (REQUIRED_COLUMNS <= len(row) <= TOTAL_COLUMNS):
            raise SpoolEaseWireError("csv", "wrong column count")
        padded = row + [""] * (TOTAL_COLUMNS - len(row))
        record = dict(zip(FIELD_COLUMNS, padded))
        # 0.7 stores several tags and colours per spool as `;`-joined lists and
        # escapes line breaks in the note. `color_code` stays the PRIMARY colour
        # (first item) so every consumer keeps reading one string.
        record["tag_ids"] = decode_list(record["tag_id"])
        record["color_codes"] = decode_list(record["color_code"])
        record["color_code"] = record["color_codes"][0] if record["color_codes"] else ""
        record["note"] = decode_line_safe(record["note"])
        spool_id = record["id"]
        if not spool_id:
            raise SpoolEaseWireError("csv", "empty spool id")
        if spool_id in seen_ids:
            raise SpoolEaseWireError("csv", "duplicate spool id")
        seen_ids.add(spool_id)

        for key in ("weight_advertised", "weight_core", "weight_new",
                    "weight_current", "added_time", "encode_time"):
            record[key] = decode_i32_opt(record[key])
        record["added_full"] = decode_bool_opt(record["added_full"])
        record["ext_has_k"] = decode_bool_opt(record["ext_has_k"])
        record["spools_count"] = 1 if record["spools_count"] == "" else _count(record["spools_count"])
        record["td"] = decode_f32_plain_opt(record["td"])
        # consumed_since_add / consumed_since_weight stay raw strings here:
        # a bad one is a per-spool weight-unknown, never a whole-read failure.
        records.append(record)
    return records
