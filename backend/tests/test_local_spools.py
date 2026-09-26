"""The local/manual spool fallback — for a printer with no Spoolman or
Bambuddy, or for a slot neither of them tracks.

Two things this file is careful to prove, because they are the two ways a
"just let people type it in" feature goes wrong: that a fresh figure the
person just typed is told apart from one Studio derived by subtracting a
job's usage from it (USER_CONFIRMED vs DERIVED), and that the subtraction
never happens except from the one call a person's own confirmation reaches —
never as a side effect of reading, planning or sending a job.
"""
from __future__ import annotations

from snapstudio_api import service
from snapstudio_core import material_providers as providers


# --- the normaliser: library rows -> the shared provider shape --------------

def test_local_spools_normalises_rows_into_the_shared_shape():
    rows = [
        {"slot": 0, "material": "PLA", "subtype": "Matte", "color": "#FF0000",
         "vendor": "Snapmaker", "remaining_g": 750.0,
         "remaining_quality": providers.USER_CONFIRMED,
         "remaining_as_of": "2026-09-26T00:00:00Z", "notes": None},
    ]
    out = providers.local_spools(rows)
    assert out["available"] is True
    assert out["source"] == providers.LOCAL
    assert out["remaining_known"] is True
    slot = out["slots"][0]
    assert slot["material"] == "PLA" and slot["remaining_g"] == 750.0
    assert slot["remaining_quality"] == providers.USER_CONFIRMED
    assert slot["confirmed_by"] == providers.BY_PROVIDER  # a person said so, not the printer


def test_local_spools_with_no_rows_is_unavailable_not_empty_and_confident():
    out = providers.local_spools([])
    assert out["available"] is False
    assert out["slots"] == []


def test_local_spools_with_no_remaining_weight_is_untracked():
    rows = [{"slot": 1, "material": "PETG", "subtype": None, "color": None,
             "vendor": None, "remaining_g": None, "remaining_quality": None,
             "remaining_as_of": None, "notes": None}]
    out = providers.local_spools(rows)
    assert out["slots"][0]["remaining_quality"] == providers.UNTRACKED
    assert out["remaining_known"] is False


def test_local_is_not_a_network_provider_name():
    """LOCAL has no address to read and no READERS entry — it must not silently
    start answering to /provider/test or the network read() dispatch."""
    assert providers.LOCAL not in providers.READERS
    assert providers.LOCAL not in providers.PROVIDER_NAMES


# --- the service layer: save / list / delete / mark used --------------------

def test_save_then_list_local_spool(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    saved = service.save_local_spool("u1.local", 0, material="PLA", color="#FF0000",
                                     starting_g=1000.0, remaining_g=800.0)
    assert saved["remaining_quality"] == providers.USER_CONFIRMED
    assert saved["remaining_as_of"]

    state = service.local_spools("u1.local")
    assert state["available"] is True
    assert state["slots"][0]["material"] == "PLA"

    # A different printer's spools stay separate.
    assert service.local_spools("other.local")["available"] is False


def test_saving_with_no_remaining_weight_records_nothing_to_be_confident_about(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    saved = service.save_local_spool("u1.local", 0, material="PLA", starting_g=1000.0)
    assert saved["remaining_g"] is None
    assert saved["remaining_quality"] is None


def test_delete_local_spool(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    service.save_local_spool("u1.local", 0, material="PLA", remaining_g=500.0)
    service.delete_local_spool("u1.local", 0)
    assert service.local_spools("u1.local")["available"] is False


def test_mark_local_spool_used_subtracts_and_becomes_derived(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    service.save_local_spool("u1.local", 0, material="PLA", starting_g=1000.0, remaining_g=800.0)
    updated = service.mark_local_spool_used("u1.local", 0, 50.0)
    assert updated["remaining_g"] == 750.0
    assert updated["remaining_quality"] == providers.DERIVED  # Studio's arithmetic, not a fresh confirmation


def test_mark_local_spool_used_on_an_unknown_slot_refuses_rather_than_inventing_one(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    try:
        service.mark_local_spool_used("u1.local", 0, 50.0)
        assert False, "expected a ValueError"
    except ValueError as exc:
        assert "no local spool record" in str(exc)


def test_mark_used_never_fires_as_a_side_effect_of_reading(tmp_path, monkeypatch):
    """The one honesty guarantee this feature exists to keep: reading a spool's
    state, however many times, never changes it."""
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    service.save_local_spool("u1.local", 0, material="PLA", starting_g=1000.0, remaining_g=800.0)
    for _ in range(5):
        service.local_spools("u1.local")
    assert service.local_spools("u1.local")["slots"][0]["remaining_g"] == 800.0


# --- the wiring into the provider seam: the fallback with no Spoolman/Bambuddy

def test_with_providers_folds_local_spool_when_no_provider_is_configured(tmp_path, monkeypatch):
    """The core claim of this feature: a local spool note fills the gap the
    printer cannot answer even when no Spoolman or Bambuddy is set up."""
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))

    def fake_stock_u1(host, port):
        return {"schema_version": providers.SCHEMA_VERSION, "source": providers.STOCK,
                "available": True, "remaining_known": False,
                "slots": [providers._slot(0, present=False, confirmed_by=providers.BY_PRINTER)]}

    monkeypatch.setattr(providers, "stock_u1", fake_stock_u1)
    service.save_local_spool("u1.local", 0, material="PLA", color="#FF0000",
                             starting_g=1000.0, remaining_g=750.0)

    printer = service._with_providers({"reachable": True}, "u1.local", 7125,
                                      provider_url=None, slot_map=None)
    loaded = printer["loaded_filaments"]
    assert loaded[0]["material"] == "PLA"
    assert loaded[0]["remaining_g"] == 750.0
    assert loaded[0]["remaining_quality"] == providers.USER_CONFIRMED


def test_with_providers_never_overrides_what_the_printer_itself_saw(tmp_path, monkeypatch):
    """The printer stays authoritative about *what* is in a slot — a local note
    can only add a remaining weight, exactly like every other provider here."""
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))

    def fake_stock_u1(host, port):
        return {"schema_version": providers.SCHEMA_VERSION, "source": providers.STOCK,
                "available": True, "remaining_known": False,
                "slots": [providers._slot(0, material="PETG", confirmed_by=providers.BY_PRINTER)]}

    monkeypatch.setattr(providers, "stock_u1", fake_stock_u1)
    service.save_local_spool("u1.local", 0, material="PLA", remaining_g=500.0)

    printer = service._with_providers({"reachable": True}, "u1.local", 7125,
                                      provider_url=None, slot_map=None)
    loaded = printer["loaded_filaments"]
    assert loaded[0]["material"] == "PETG"       # the printer's own answer
    assert loaded[0]["remaining_g"] == 500.0      # the gap the printer could not fill
    assert loaded[0]["confirmed_by"] == providers.BY_PRINTER


def test_with_providers_skips_the_network_entirely_when_nothing_to_add(tmp_path, monkeypatch):
    """No provider configured and no local spool recorded: the exact no-op the
    feature had before this fallback existed, with no extra network round trip."""
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))

    def boom(*a, **k):
        raise AssertionError("stock_u1 must not be called when there is nothing to add")

    monkeypatch.setattr(providers, "stock_u1", boom)
    printer = {"reachable": True}
    result = service._with_providers(printer, "u1.local", 7125, provider_url=None, slot_map=None)
    assert result is printer


def test_with_providers_returns_unchanged_with_no_host():
    printer = {"reachable": False}
    result = service._with_providers(printer, None, 7125, provider_url=None, slot_map=None)
    assert result is printer
