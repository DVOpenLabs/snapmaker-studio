"""When the printer and the provider disagree, and when only one of them speaks.

Two sources can describe the same slot and they answer different questions. The
printer is *looking* at what is loaded. The provider holds what a person wrote
down, plus the one thing the machine cannot know — how much is left on the spool.

That asymmetry is the whole design, and it is easy to lose. The tempting
simplification is to merge the two into one answer and pick a winner, which
produces a confident sentence about what will come out of the nozzle built partly
on somebody's bookkeeping.

The second half of this file is the payoff from the second-printer work. On a
machine that reports no filament state at all — most Klipper printers, including
the VORON profile Studio ships — a provider is the *only* source. Studio must
still not say the printer confirmed anything, because it did not.
"""
from __future__ import annotations

import datetime

import pytest

from snapstudio_core import (material_plan, material_providers as providers,
                             printer_profiles, send_check)


def fresh() -> str:
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=2)).isoformat()


def printer_slot(**kw) -> dict:
    kw.setdefault("confirmed_by", providers.BY_PRINTER)
    return {"schema_version": providers.SCHEMA_VERSION, "source": providers.STOCK,
            "available": True, "remaining_known": False,
            "slots": [providers._slot(0, **kw)]}


def provider_slot(**kw) -> dict:
    kw.setdefault("source", providers.SPOOLMAN)
    kw.setdefault("confirmed_by", providers.BY_PROVIDER)
    return {"schema_version": providers.SCHEMA_VERSION, "source": providers.SPOOLMAN,
            "available": True, "remaining_known": True,
            "slots": [providers._slot(0, **kw)]}


# --- the printer stays authoritative about what is physically there ----------

def test_the_printer_wins_on_material_and_the_disagreement_is_shown():
    """Printer says PLA Black; the mapping says PETG Red."""
    merged = providers.combine(
        printer_slot(material="PLA", color="#000000"),
        provider_slot(material="PETG", color="#FF0000", spool_id=7,
                      remaining_g=800.0, remaining_quality=providers.TRACKED,
                      remaining_as_of=fresh()))
    slot = merged["slots"][0]

    assert slot["material"] == "PLA"
    assert slot["color"] == "#000000"
    assert slot["disagreed"]["material"] == {"printer": "PLA", "spoolman": "PETG"}
    assert slot["disagreed"]["colour"] == {"printer": "#000000", "spoolman": "#FF0000"}
    assert slot["confidence"] == providers.UNKNOWN
    assert any("using what the printer can see" in note for note in slot["conflicts"])


def test_a_disagreement_does_not_stop_the_remaining_weight_being_useful():
    """The provider was wrong about the material and may still be right about the weight.

    Both facts are about the same slot, but they are not the same claim, and
    throwing the weight away because the material disagreed would lose the only
    thing the provider was there to supply.
    """
    merged = providers.combine(
        printer_slot(material="PLA", color="#000000"),
        provider_slot(material="PETG", spool_id=7, remaining_g=431.0,
                      remaining_quality=providers.TRACKED, remaining_as_of=fresh()))
    slot = merged["slots"][0]
    assert slot["remaining_g"] == 431.0
    assert slot["spool_id"] == 7
    assert slot["conflicts"]


def test_a_colour_only_disagreement_is_still_reported():
    merged = providers.combine(
        printer_slot(material="PLA", color="#000000"),
        provider_slot(material="PLA", color="#FFFFFF", spool_id=7))
    slot = merged["slots"][0]
    assert slot["color"] == "#000000"
    assert "colour" in slot["disagreed"]
    assert "material" not in slot.get("disagreed", {})


def test_a_vendor_the_printer_did_not_state_is_filled_not_contested():
    merged = providers.combine(
        printer_slot(material="PLA", color="#000000"),
        provider_slot(material="PLA", color="#000000", vendor="Prusament", spool_id=7))
    slot = merged["slots"][0]
    assert slot["vendor"] == "Prusament"
    assert not slot.get("conflicts")
    assert slot["added_by"]["vendor"] == providers.SPOOLMAN


def test_an_empty_printer_slot_against_a_mapped_spool_stays_empty():
    """Nothing loaded — and the printer LOOKED. A provider's mapping is
    somebody's note about what they believe is in a slot, never a second
    look at it, so it cannot turn a printer-confirmed empty slot into a
    "maybe" the way two provider-supplied facts can disagree with each
    other. This changed from an earlier "neither is assumed" (present=True,
    confidence=unknown) design once that turned out to mean the real
    send-check BLOCKER for an empty slot a job prints from could be made to
    disappear by nothing more than a stale mapping — see
    test_local_spools.py's H1 regression tests for the reproduction."""
    merged = providers.combine(
        printer_slot(present=False),
        provider_slot(material="PLA", spool_id=7, remaining_g=400.0))
    slot = merged["slots"][0]
    assert slot["present"] is False
    assert any("printer looked and found it empty" in note for note in slot["conflicts"])


def test_a_loaded_printer_slot_with_no_mapping_is_unchanged():
    merged = providers.combine(printer_slot(material="PLA", color="#000000"),
                               {"source": providers.SPOOLMAN, "available": True,
                                "remaining_known": True, "slots": []})
    slot = merged["slots"][0]
    assert slot["material"] == "PLA"
    assert not slot.get("conflicts")
    assert slot["remaining_g"] is None


def test_a_provider_that_cannot_say_the_material_contests_nothing():
    merged = providers.combine(
        printer_slot(material="PLA", color="#000000"),
        provider_slot(spool_id=7, remaining_g=400.0))
    assert not merged["slots"][0].get("conflicts")


def test_a_stale_provider_weight_beside_a_live_printer_material_stays_a_warning():
    old = (datetime.datetime.now(datetime.timezone.utc)
           - datetime.timedelta(days=20)).isoformat()
    merged = providers.combine(
        printer_slot(material="PLA", color="#000000"),
        provider_slot(material="PLA", spool_id=7, remaining_g=43.0,
                      remaining_quality=providers.TRACKED, remaining_as_of=old))
    loaded = providers.as_loaded_filaments(merged)
    plan = material_plan.plan(
        [{"tool": 0, "used": True, "grams": 87.0, "type": "PLA"}], loaded, [0])
    assert plan["slots"][0]["sufficiency"]["verdict"] == "probably_short"
    assert not [i for i in send_check.evaluate(
        {"available": True, "tools_used": [0],
         "slots": [{"tool": 0, "used": True, "grams": 87.0, "type": "PLA"}]},
        {"reachable": True, "loaded_filaments": loaded})["items"]
        if i["kind"] == send_check.BLOCKER]


@pytest.mark.parametrize("base, key", [(0, "0"), (1, "1")])
def test_the_stated_slot_numbering_is_honoured_over_any_inference(base, key, monkeypatch):
    """One mapping cannot be inferred; it has to be stated, and stating it wins."""
    monkeypatch.setattr(providers, "_get_json", lambda url, timeout=4.0: [
        {"id": 7, "remaining_weight": 400.0, "used_weight": 600.0,
         "last_used": fresh(), "archived": False,
         "filament": {"material": "PLA", "color_hex": "000000", "weight": 1000}}])
    state = providers.spoolman("http://spoolman.local", slot_map={key: 7}, slot_base=base)
    assert state["slot_base"] == base
    assert state["slots"][0]["slot"] == 0


# --- the multi-printer payoff -----------------------------------------------

VORON = {
    "reachable": True, "toolhead_count": 1,
    "bed_mm": {"x": 250.0, "y": 250.0, "z": 252.0},
    "klipper_objects": ["extruder", "toolhead", "probe", "quad_gantry_level"],
    "print_state": "standby",
}


def test_a_printer_that_reports_no_filament_state_confirms_nothing():
    """The VORON profile records that nothing on the machine reports filament."""
    profile = printer_profiles.load("voron_2_4_250")
    assert (profile["material_state"]["source"]) == "none"
    resolved = printer_profiles.resolve(VORON, profile)
    assert resolved["material_state"]["known"] is False


def test_a_provider_on_such_a_printer_is_the_only_source_and_says_so():
    merged = providers.combine(
        provider_slot(material="PLA", color="#2D9E59", spool_id=7, remaining_g=431.0,
                      remaining_quality=providers.TRACKED, remaining_as_of=fresh()))
    loaded = providers.as_loaded_filaments(merged)

    assert loaded[0]["confirmed_by"] == providers.BY_PROVIDER
    plan = material_plan.plan(
        [{"tool": 0, "used": True, "grams": 87.0, "type": "PLA", "color": "#2D9E59"}],
        loaded, [0])
    slot = plan["slots"][0]
    assert slot["state"] == "ready"
    assert slot["printer_confirmed"] is False
    assert "does not report its own filament" in slot["detail"]


def test_a_wrong_material_on_such_a_printer_is_phrased_as_your_mapping():
    merged = providers.combine(
        provider_slot(material="PETG", spool_id=7, remaining_g=431.0,
                      remaining_quality=providers.TRACKED, remaining_as_of=fresh()))
    loaded = providers.as_loaded_filaments(merged)
    plan = material_plan.plan(
        [{"tool": 0, "used": True, "grams": 87.0, "type": "PLA"}], loaded, [0])
    slot = plan["slots"][0]
    assert slot["state"] == "wrong_material"
    assert "your mapping puts" in slot["detail"]
    assert "the printer reports" not in slot["detail"]


def test_the_same_provider_on_a_u1_is_phrased_as_an_observation():
    """The identical spool, on a machine that does look, reads differently."""
    merged = providers.combine(
        printer_slot(material="PLA", color="#2D9E59"),
        provider_slot(material="PLA", color="#2D9E59", spool_id=7, remaining_g=431.0,
                      remaining_quality=providers.TRACKED, remaining_as_of=fresh()))
    loaded = providers.as_loaded_filaments(merged)

    assert loaded[0]["confirmed_by"] == providers.BY_PRINTER
    plan = material_plan.plan(
        [{"tool": 0, "used": True, "grams": 87.0, "type": "PLA", "color": "#2D9E59"}],
        loaded, [0])
    slot = plan["slots"][0]
    assert slot["printer_confirmed"] is True
    assert "does not report its own filament" not in slot["detail"]


def test_provider_bookkeeping_can_still_block_a_send_on_an_unconfirmed_slot():
    """Not knowing what is loaded does not make the weight meaningless.

    The provider says this spool has 43 g and something has been keeping that
    figure. The printer cannot confirm the spool is in the slot, but if it is,
    an 87 g job runs out — and that is worth stopping for, on the mapping the
    user themselves set up.
    """
    merged = providers.combine(
        provider_slot(material="PLA", spool_id=7, remaining_g=43.0,
                      remaining_quality=providers.TRACKED, remaining_as_of=fresh()))
    loaded = providers.as_loaded_filaments(merged)
    out = send_check.evaluate(
        {"available": True, "tools_used": [0],
         "slots": [{"tool": 0, "used": True, "grams": 87.0, "type": "PLA"}]},
        {"reachable": True, "loaded_filaments": loaded})
    assert any("Not enough filament" in i["title"]
               for i in out["items"] if i["kind"] == send_check.BLOCKER)


def test_no_provider_and_no_printer_filament_state_is_simply_unknown():
    """A VORON with nothing configured: useful preflight, honest silence."""
    out = send_check.evaluate(
        {"available": True, "printer_model": "Voron 2.4", "tools_used": [0],
         "slots": [{"tool": 0, "used": True, "grams": 87.0, "type": "PLA"}],
         "size_bytes": 1_000_000},
        dict(VORON, identity={"matched": False, "printer_id": None}))
    assert out["counts"][send_check.BLOCKER] == 0
    assert out["available"] is True
    titles = " ".join(i["title"] for i in out["items"])
    assert "empty" not in titles.lower()
