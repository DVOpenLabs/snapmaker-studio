"""P4 calibration acceptance tests; evidence label: fixture-tested."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from snapstudio_api import ext_routes
from snapstudio_api import routes_calibration  # noqa: F401 (registers routes)
from snapstudio_core.calibration import palette, service
from snapstudio_core.foundation.store import StoreVersionError, open_store

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "calibration"


def test_1_ditherforge_rows_parse_both_td_forms_and_derive_missing_td():
    decoded = palette.parse_ditherforge((FIXTURES / "ditherforge-sample.txt").read_text())
    assert decoded.valid_for_evaluation
    assert [entry.label for entry in decoded.value.entries] == ["Vermilion", "Blue", "Ochre"]
    assert decoded.value.entries[0].td == 0.8 and decoded.value.entries[0].td_provenance == "provided"
    assert decoded.value.entries[1].td == 1.0 and decoded.value.entries[1].td_provenance == "derived"


def test_2_kromacut_v2_is_decoded_and_other_versions_remain_unknown():
    accepted = palette.parse_kromacut((FIXTURES / "kromacut-v2.json").read_text())
    unknown_raw = json.loads((FIXTURES / "kromacut-v3-unknown.json").read_text())
    rejected = palette.parse_kromacut(unknown_raw)
    assert accepted.valid_for_evaluation and accepted.value.source == "kromacut_json_v2"
    assert accepted.value.entries[1].td_provenance == "derived"
    assert rejected.value is None and not rejected.valid_for_evaluation
    assert rejected.raw == unknown_raw


def test_3_frontlit_basis_identity_never_merges_with_another_family():
    front = service.basis_document("frontlit", 0.2, 0.4, "PLA")
    back = service.basis_document("backlit", 0.2, 0.4, "PLA")
    assert front["calibration_basis_id"] != back["calibration_basis_id"]
    with pytest.raises(ValueError):
        service.basis_document("other", 0.2, 0.4, "PLA")


def test_4_layer_height_change_gets_new_basis_and_keeps_prior_run(tmp_path):
    parsed = palette.parse_ditherforge("#112233 td Ink").value.to_dict()
    first_basis = service.basis_document("frontlit", 0.2, 0.4, "PLA")
    second_basis = service.basis_document("frontlit", 0.16, 0.4, "PLA")
    first = service.save_run(first_basis, parsed, service.evaluate(parsed, first_basis, {}, []), str(tmp_path))
    second = service.save_run(second_basis, parsed, service.evaluate(parsed, second_basis, {}, []), str(tmp_path))
    history = service.history(str(tmp_path))
    assert first["calibration_basis"]["calibration_basis_id"] != second["calibration_basis"]["calibration_basis_id"]
    assert first["inputs_revision"]["revision"] != second["inputs_revision"]["revision"]
    assert {row["calibration_basis"]["calibration_basis_id"] for row in history} == {
        first_basis["calibration_basis_id"], second_basis["calibration_basis_id"]}


def test_5_simulated_palette_and_physical_reading_stay_distinct():
    parsed = palette.parse_ditherforge("#112233 td Ink").value.to_dict()
    basis = service.basis_document("frontlit", 0.2, 0.4, "PLA")
    result = service.evaluate(parsed, basis, {"0": "#102030"}, [])
    row = result["entries"][0]
    assert row["simulated_color"] == "#112233" and row["physical_color"] == "#102030"
    assert row["physical_distance"] is not None


def test_6_owned_filament_alternatives_use_advisory_colour_distance():
    parsed = palette.parse_ditherforge("#112233 td Ink").value.to_dict()
    basis = service.basis_document("frontlit", 0.2, 0.4, "PLA")
    result = service.evaluate(parsed, basis, {}, [{"label": "Near", "color": "#112234"},
                                                   {"label": "Far", "color": "#FFFFFF"}])
    alternatives = result["entries"][0]["alternatives"]
    assert alternatives[0]["label"] == "Near" and alternatives[0]["distance"] < alternatives[1]["distance"]
    assert all(item["advisory"] for item in alternatives)


def test_7_calibration_store_refuses_newer_schema_without_replacing_rows(tmp_path):
    (tmp_path / "store").mkdir()
    conn = sqlite3.connect(tmp_path / "store" / "calibration.db")
    if conn.execute("PRAGMA user_version").fetchone()[0] < 2:
        conn.execute("CREATE TABLE IF NOT EXISTS preserved (value TEXT)")
        conn.execute("DELETE FROM preserved")
        conn.execute("INSERT INTO preserved VALUES ('synthetic')")
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
    conn.close()
    with pytest.raises(StoreVersionError):
        with open_store("calibration", "CREATE TABLE replacement (value TEXT);", 1, str(tmp_path)):
            pass
    conn = sqlite3.connect(tmp_path / "store" / "calibration.db")
    try:
        assert conn.execute("SELECT value FROM preserved").fetchone()[0] == "synthetic"
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='replacement'").fetchone() is None
    finally:
        conn.close()


def test_7b_failed_store_migration_rolls_back_schema_and_rows(tmp_path):
    data_dir = tmp_path
    with open_store("calibration", "CREATE TABLE preserved (value TEXT);", 1, str(data_dir)) as conn:
        if conn.execute("SELECT COUNT(*) FROM preserved").fetchone()[0] == 0:
            conn.execute("INSERT INTO preserved VALUES ('synthetic')")
    with pytest.raises(sqlite3.OperationalError):
        with open_store("calibration", [
            (1, "CREATE TABLE IF NOT EXISTS preserved (value TEXT);"),
            (2, "ALTER TABLE preserved ADD COLUMN added TEXT; SELECT * FROM missing_table;"),
        ], 2, str(data_dir)):
            pass
    conn = sqlite3.connect(data_dir / "store" / "calibration.db")
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute("SELECT value FROM preserved").fetchone()[0] == "synthetic"
        assert "added" not in {row[1] for row in conn.execute("PRAGMA table_info(preserved)")}
    finally:
        conn.close()


def test_8_basis_id_is_returned_and_included_in_derivation_revision():
    parsed = palette.parse_ditherforge("#112233 td Ink").value.to_dict()
    basis = service.basis_document("frontlit", 0.2, 0.4, "PLA")
    saved = service.save_run(basis, parsed, service.evaluate(parsed, basis, {}, []))
    assert saved["calibration_basis"]["calibration_basis_id"] == basis["calibration_basis_id"]
    assert saved["inputs_revision"]["calibration_basis_id"] == basis["calibration_basis_id"]


def test_route_evaluates_palette_and_saves_local_revision(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path))
    handler = type("Handler", (), {"_send": lambda self, code, body: self.sent.append((code, body))})()
    handler.sent = []
    assert ext_routes.dispatch(handler, "/calibration/evaluate", {
        "source": "ditherforge_txt", "content": "#112233 Ink", "family": "frontlit", "layer_height_mm": 0.2,
        "physical_colors": {"0": "#102030"}, "owned_filaments": [{"label": "Owned red", "color": "#112234"}],
    })
    code, body = handler.sent[0]
    assert code == 200 and body["status"] == "evaluated"
    assert body["result"]["entries"][0]["physical_color"] == "#102030"
    assert body["result"]["entries"][0]["alternatives"][0]["label"] == "Owned red"
    assert service.history(str(tmp_path))


def test_routes_do_not_echo_or_persist_a_sentinel_credential(tmp_path, monkeypatch, caplog):
    sentinel = "SENTINEL-KEY-9f3a"
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path))
    request = {"source": "ditherforge_txt", "content": "#112233 Ink", "family": "frontlit",
               "layer_height_mm": 0.2, "api_key": sentinel}
    for path, body in (("/calibration/evaluate", request), ("/calibration/history", {"api_key": sentinel})):
        handler = type("Handler", (), {"_send": lambda self, code, response: self.sent.append((code, response))})()
        handler.sent = []
        ext_routes.dispatch(handler, path, body)
        assert sentinel not in json.dumps(handler.sent)
    assert sentinel not in caplog.text
    assert all(sentinel not in item.read_bytes().decode("utf-8", "ignore")
               for item in tmp_path.rglob("*") if item.is_file())


def test_route_returns_unknown_for_unsupported_kromacut_version():
    handler = type("Handler", (), {"_send": lambda self, code, body: self.sent.append((code, body))})()
    handler.sent = []
    ext_routes.dispatch(handler, "/calibration/evaluate", {"source": "kromacut_json", "content": '{"version":9}'})
    code, body = handler.sent[0]
    assert code == 200 and body["status"] == "unknown" and body["result"] is None
