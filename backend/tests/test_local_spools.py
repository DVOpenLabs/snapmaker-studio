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

def test_with_providers_folds_local_spool_remaining_weight_when_no_provider_is_configured(tmp_path, monkeypatch):
    """The core claim of this feature: a local note fills in the one thing a
    stock U1 cannot know — how much is left on a spool it has confirmed is
    loaded — even when no Spoolman or Bambuddy is configured. This must never
    be confused with a provider claiming a slot is OCCUPIED when the printer
    itself says otherwise — see the H1 regression tests below for that."""
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))

    def fake_stock_u1(host, port):
        return {"schema_version": providers.SCHEMA_VERSION, "source": providers.STOCK,
                "available": True, "remaining_known": False,
                "slots": [providers._slot(0, material="PLA", color="#FF0000",
                                          confirmed_by=providers.BY_PRINTER)]}

    monkeypatch.setattr(providers, "stock_u1", fake_stock_u1)
    service.save_local_spool("u1.local", 0, material="PLA", color="#FF0000",
                             starting_g=1000.0, remaining_g=750.0)

    printer = service._with_providers({"reachable": True}, "u1.local", 7125,
                                      provider_url=None, slot_map=None)
    loaded = printer["loaded_filaments"]
    assert loaded[0]["material"] == "PLA"                          # confirmed by the printer
    assert loaded[0]["confirmed_by"] == providers.BY_PRINTER
    assert loaded[0]["remaining_g"] == 750.0                        # the gap only the note could fill
    assert loaded[0]["remaining_quality"] == providers.USER_CONFIRMED


# --- H1 regression: a local note must never override a printer-confirmed-empty slot

def test_a_local_note_never_overrides_a_printer_confirmed_empty_slot(tmp_path, monkeypatch):
    """A stale local note must never turn a slot the printer has physically
    looked at and found empty into one that reads as loaded — that is
    exactly how a real BLOCKER (this slot is empty) would silently
    disappear. Opus review of 7848824, finding H1."""
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))

    def fake_stock_u1(host, port):
        return {"schema_version": providers.SCHEMA_VERSION, "source": providers.STOCK,
                "available": True, "remaining_known": False,
                "slots": [providers._slot(0, present=False, confirmed_by=providers.BY_PRINTER)]}

    monkeypatch.setattr(providers, "stock_u1", fake_stock_u1)
    service.save_local_spool("u1.local", 0, material="PLA", color="#FF0000",
                             starting_g=1000.0, remaining_g=800.0)

    printer = service._with_providers({"reachable": True}, "u1.local", 7125,
                                      provider_url=None, slot_map=None)
    loaded = printer["loaded_filaments"]
    assert loaded[0] is None    # still reads as empty — the printer looked and saw nothing
    slot_facts = printer["slot_facts"][0]
    assert slot_facts["present"] is False
    assert any("printer looked and found it empty" in c for c in slot_facts.get("conflicts", []))


def test_send_check_still_blocks_on_a_printer_confirmed_empty_slot_despite_a_local_note(tmp_path, monkeypatch):
    """End-to-end proof: the local-spool fallback must never be able to
    silently remove the one BLOCKER that exists to stop a job printing into
    an empty slot."""
    from snapstudio_core import send_check

    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))

    def fake_stock_u1(host, port):
        return {"schema_version": providers.SCHEMA_VERSION, "source": providers.STOCK,
                "available": True, "remaining_known": False,
                "slots": [providers._slot(0, present=False, confirmed_by=providers.BY_PRINTER)]}

    monkeypatch.setattr(providers, "stock_u1", fake_stock_u1)
    service.save_local_spool("u1.local", 0, material="PLA", color="#FF0000",
                             starting_g=1000.0, remaining_g=800.0)

    printer = service._with_providers(
        {"reachable": True, "toolhead_count": 4, "bed_mm": {"x": 271, "y": 335},
         "print_state": "standby", "klipper_objects": ["gcode", "print_stats", "exclude_object"]},
        "u1.local", 7125, provider_url=None, slot_map=None)

    facts = {"available": True, "tools_used": [0],
            "slots": [{"tool": 0, "used": True, "grams": 20.0, "type": "PLA"}]}
    report = send_check.evaluate(facts, printer)
    assert report["verdict"] == send_check.BLOCKER
    assert any("empty" in i["title"].lower() for i in report["items"] if i["kind"] == send_check.BLOCKER)


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
