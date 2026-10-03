"""SpoolEase 0.7 line (issue #39): 25-column spool list, list/escape encodings, and
the two credentials people mix up — the security key and the 0.7 API key.

Fixture row layout is from SpoolEase branch `0.7` (49a8e83) `spool_record.rs`:
the 21 columns Studio already knew plus assigned_location, actual_location,
spools_count and td.
"""
from __future__ import annotations

import json
import sys
import urllib.error

import pytest

sys.path.insert(0, __file__.rsplit("tests", 1)[0] + "tests")

from fixtures.providers.spoolease_fake import FIXTURE_KEY, SpoolEaseFake  # noqa: E402
from snapstudio_core import material_providers as mp  # noqa: E402
from snapstudio_core import spoolease_wire as wire  # noqa: E402

# id, tag_id, type, subtype, color_name, color_code, note, brand, adv, core, new, cur,
# slicer, added, encoded, added_full, c_add, c_wt, ext_has_k, origin, tag_type,
# assigned_location, actual_location, spools_count, td
ROW_07 = ("S1,TAGAAAA;TAGBBBB,PLA,Basic,Red,FF0000FF;00FF00FF,line one\\nline two\\\\end,"
          "Acme,1000,200,1200,900,GFSA00,1700000000,1700000100,y,,,n,SpoolEaseV1,"
          "Bambu,Shelf A,AMS A1,2,3.5\n")


def test_25_column_row_parses():
    (rec,) = wire.parse_csv(ROW_07)
    assert rec["id"] == "S1"
    assert rec["tag_ids"] == ["TAGAAAA", "TAGBBBB"]
    assert rec["color_codes"] == ["FF0000FF", "00FF00FF"]
    assert rec["color_code"] == "FF0000FF"          # primary colour
    assert rec["note"] == "line one\nline two\\end"  # escapes decoded
    assert rec["spools_count"] == 2
    assert rec["td"] == 3.5
    assert rec["assigned_location"] == "Shelf A"
    assert rec["actual_location"] == "AMS A1"
    assert rec["weight_current"] == 900


def test_legacy_rows_still_parse_with_defaults():
    legacy = "7,TAG1,PETG,,Blue,0000FFFF,,Acme,1000,200,1200,900\n"
    (rec,) = wire.parse_csv(legacy)
    assert rec["tag_ids"] == ["TAG1"]
    assert rec["color_code"] == "0000FFFF"
    assert rec["spools_count"] == 1
    assert rec["td"] is None
    assert rec["note"] == ""


def test_empty_list_columns_are_empty():
    (rec,) = wire.parse_csv("8,,PLA,,,,,,,,,\n")
    assert rec["tag_ids"] == [] and rec["color_codes"] == [] and rec["color_code"] == ""


def test_more_than_25_columns_is_still_refused():
    row = ",".join(["x"] * 26)
    with pytest.raises(wire.SpoolEaseWireError) as ei:
        wire.parse_csv(f"1{row}\n")
    assert ei.value.code == "csv"


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "1.5"])
def test_bad_spools_count_is_csv_error(bad):
    cols = ROW_07.rstrip("\n").split(",")
    cols[-2] = bad
    with pytest.raises(wire.SpoolEaseWireError) as ei:
        wire.parse_csv(",".join(cols) + "\n")
    assert ei.value.code == "csv"


@pytest.mark.parametrize("bad", ["nan", "inf", "x"])
def test_bad_td_is_csv_error(bad):
    cols = ROW_07.rstrip("\n").split(",")
    cols[-1] = bad
    with pytest.raises(wire.SpoolEaseWireError):
        wire.parse_csv(",".join(cols) + "\n")


def test_line_safe_decode_matches_upstream():
    assert wire.decode_line_safe("a\\nb\\rc\\\\d") == "a\nb\rc\\d"
    assert wire.decode_line_safe("keep\\q") == "keep\\q"   # unknown pair kept
    assert wire.decode_line_safe("trail\\") == "trail\\"   # lone trailing backslash


def test_real_reader_reads_a_07_row_end_to_end():
    with SpoolEaseFake(mode="custom", plaintext=ROW_07.encode()) as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["available"] is True, out.get("error")
    (spool,) = out["spools"]
    assert spool["id"] == "S1"
    assert spool["color"] == "#FF0000"
    assert spool["vendor"] == "Acme"


def test_api_key_in_the_security_key_box_gets_a_precise_message(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("no network call may be made for an API key")
    monkeypatch.setattr(mp, "_get_text", explode)
    secret = "spe_api_v1.abcd1234.SUPERSECRETVALUE"
    out = mp.read("spoolease", "http://192.168.0.10", key=secret)
    assert out["available"] is False
    assert out["error_code"] == "key_is_api_key"
    dumped = json.dumps(out)
    assert "SUPERSECRETVALUE" not in dumped and "abcd1234" not in dumped
    assert "security key" in out["error"]


@pytest.mark.parametrize("status", [401, 404])
def test_https_port_without_a_spool_list_says_use_http(monkeypatch, status):
    def fake_get(url, timeout=None, **kw):
        raise urllib.error.HTTPError(url, status, "x", None, None)
    monkeypatch.setattr(mp, "_get_text", fake_get)
    out = mp.read("spoolease", "https://192.168.0.10", key=FIXTURE_KEY)
    assert out["available"] is False
    assert out["error_code"] == "http_status"
    assert "http" in out["error"] and "security key" in out["error"]


def test_plain_http_404_keeps_the_generic_status_message(monkeypatch):
    def fake_get(url, timeout=None, **kw):
        raise urllib.error.HTTPError(url, 404, "x", None, None)
    monkeypatch.setattr(mp, "_get_text", fake_get)
    out = mp.read("spoolease", "http://192.168.0.10", key=FIXTURE_KEY)
    assert out["error"] == "SpoolEase did not answer: HTTP 404"


def test_wrong_key_sentence_names_security_key_not_api_key():
    with SpoolEaseFake(mode="wrong_key") as fake:
        out = mp.read("spoolease", fake.url, key=FIXTURE_KEY)
    assert out["error_code"] == "authentication_failed"
    assert "not an API key" in out["error"]
