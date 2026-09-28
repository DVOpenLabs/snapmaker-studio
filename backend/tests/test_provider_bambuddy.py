"""What a real Bambuddy actually does, and what it hands Studio that cannot be true.

The second implementation of the material-provider seam, and the reason it is
Bambuddy rather than something Spoolman-shaped: it agrees with Spoolman about
almost nothing at the wire, so a normalisation that works for both is evidence
that the seam is a seam. Where Spoolman states a remaining weight inside a nested
filament object, Bambuddy has **no remaining-weight field at all** and keeps the
material, the variant and the brand as three flat fields.

A real Bambuddy 1.2.5.3 was run locally in Docker (session-owned, removed
afterwards) and seeded through its own documented REST API with ten controlled
spools. Four things it did were not what its documentation implies:

1. **Archived spools are omitted from the default listing** — ten spools with
   `include_archived=true` and nine without. Exactly the trap Spoolman set, in a
   differently-spelled parameter, and a slot mapped to an archived spool would
   otherwise read as deleted.
2. **`remaining` is not a field.** The wiki describes remaining weight as
   `label_weight − weight_used`; that subtraction happens in Bambuddy's own
   interface, and over the API Studio has to do it. So the figure is arithmetic,
   and it can never be presented as something Bambuddy is keeping.
3. **`last_used` is null on every spool**, including one whose weight had just
   been set through the scale endpoint. It is written by print consumption only —
   so an undated figure is the common case, which is what Spoolman turned out to
   be too, reached through a completely different schema.
4. **It accepts weights that cannot be true**: a negative used weight, a used
   weight far above the label weight, and a 99,000,000 g spool, all stored and
   returned without complaint.

The fixture beside this file is the captured response with its own provenance
block, so these findings stay pinned without needing Docker on every run.
"""
from __future__ import annotations

import datetime
import json
import urllib.error
from pathlib import Path

import pytest

from snapstudio_core import (freshness, material_plan,
                             material_providers as providers, send_check)

FIXTURE = Path(__file__).parent / "fixtures" / "providers" / "bambuddy_1_2_5_3.json"


@pytest.fixture(scope="module")
def captured() -> dict:
    return json.loads(FIXTURE.read_text("utf-8"))


@pytest.fixture
def real_bambuddy(monkeypatch, captured):
    """Replay the captured response through the real adapter, asserting the URL."""
    seen: dict = {}

    def fake_get(url, timeout=4.0):
        seen["url"] = url
        return captured["spools"]

    monkeypatch.setattr(providers, "_get_json", fake_get)
    return seen


def by_id(state: dict, spool_id: int) -> dict:
    return next(s for s in state["spools"] if s["id"] == spool_id)


def test_the_fixture_says_plainly_what_it_is(captured):
    provenance = captured["_provenance"]
    assert provenance["kind"] == "captured_from_real_software"
    assert provenance["bambuddy_version"] == "1.2.5.3"
    assert "not about any printer" in provenance["statement"]


# --- the four things the real instance contradicted --------------------------

def test_studio_asks_for_archived_spools(real_bambuddy):
    providers.bambuddy("http://b")
    assert "include_archived=true" in real_bambuddy["url"]
    assert real_bambuddy["url"].endswith("/api/v1/inventory/spools?include_archived=true")


def test_the_default_listing_really_does_hide_an_archived_spool(captured):
    """Measured, not assumed: this is why the parameter above is not optional."""
    listed = set(captured["spools_default_listing_ids"])
    everything = {s["id"] for s in captured["spools"]}
    hidden = everything - listed
    assert hidden, "the fixture no longer demonstrates the archived-spool trap"
    assert all(captured_spool["archived_at"] for captured_spool in captured["spools"]
               if captured_spool["id"] in hidden)


def test_an_archived_spool_is_found_and_flagged_rather_than_missing(real_bambuddy, captured):
    archived = next(s for s in captured["spools"] if s["archived_at"])
    state = providers.bambuddy("http://b", slot_map={"0": archived["id"]})
    slot = state["slots"][0]
    assert slot["present"] is True
    assert slot["spool_id"] == archived["id"]
    assert any("archived in Bambuddy" in note for note in slot["notes"])
    assert not any("no spool with id" in note for note in slot["notes"])


def test_a_spool_nobody_has_printed_from_is_not_called_tracked(real_bambuddy, captured):
    """A full declared kilogram is a label, not a record. It must not block a print."""
    untouched = next(s for s in captured["spools"]
                     if s["label_weight"] == 1000 and s["weight_used"] == 0
                     and not s["last_weighed_at"])
    spool = by_id(providers.bambuddy("http://b"), untouched["id"])
    assert spool["remaining_g"] == 1000.0
    assert spool["remaining_quality"] == providers.DERIVED
    assert spool["remaining_as_of"] is None


def test_a_weighed_spool_carries_the_moment_it_was_weighed(real_bambuddy, captured):
    """The scale endpoint writes the used figure *and* stamps when it was true."""
    weighed = next(s for s in captured["spools"] if s["last_weighed_at"])
    spool = by_id(providers.bambuddy("http://b"), weighed["id"])
    assert spool["remaining_quality"] == providers.TRACKED
    assert spool["remaining_as_of"] == weighed["last_weighed_at"]
    assert spool["remaining_g"] == weighed["label_weight"] - weighed["weight_used"]


def test_creation_time_is_not_treated_as_a_freshness_date(real_bambuddy, captured):
    """`created_at` is when the row was written, and says nothing about filament."""
    for spool in providers.bambuddy("http://b")["spools"]:
        assert spool["remaining_as_of"] != spool["registered"]
    assert all(s["created_at"] for s in captured["spools"]), "the fixture lost created_at"


def test_most_real_spools_have_no_freshness_date_at_all(real_bambuddy):
    spools = providers.bambuddy("http://b")["spools"]
    undated = [s for s in spools if s["remaining_as_of"] is None]
    assert len(undated) > len(spools) / 2


# --- what it hands over that cannot be true ----------------------------------

@pytest.mark.parametrize("what", ["negative used", "used above label", "absurd label"])
def test_an_impossible_weight_becomes_unknown_rather_than_enough(real_bambuddy, captured,
                                                                 what):
    """Fail open to unknown. Never to "you have plenty"."""
    picks = {
        "negative used": lambda s: s["weight_used"] < 0,
        "used above label": lambda s: s["weight_used"] > s["label_weight"] > 0,
        "absurd label": lambda s: s["label_weight"] > providers.IMPLAUSIBLE_GRAMS,
    }
    raw = next(s for s in captured["spools"] if picks[what](s))
    spool = by_id(providers.bambuddy("http://b"), raw["id"])
    assert spool["remaining_g"] is None
    assert spool["remaining_quality"] == providers.UNTRACKED
    assert spool["notes"], "an impossible figure was dropped without saying why"


def test_a_spool_with_no_label_weight_is_unknown_and_says_so(real_bambuddy, captured):
    raw = next(s for s in captured["spools"] if s["label_weight"] == 0)
    spool = by_id(providers.bambuddy("http://b"), raw["id"])
    assert spool["remaining_g"] is None
    assert any("does not record enough" in note for note in spool["notes"])


@pytest.mark.parametrize("payload", [
    None, {}, "a string", 42, [1, 2, 3], [None], ["not a dict"],
])
def test_a_response_that_is_not_a_list_of_spools_is_refused(monkeypatch, payload):
    monkeypatch.setattr(providers, "_get_json", lambda url, timeout=4.0: payload)
    out = providers.bambuddy("http://b", slot_map={"0": 1})
    if isinstance(payload, list):
        # A list of nothing usable is an empty inventory, which is a real state.
        assert all(s["remaining_g"] is None for s in out["spools"])
    else:
        assert out["available"] is False
        assert out["error"]


@pytest.mark.parametrize("value", [
    "lots", None, float("nan"), float("inf"), float("-inf"), True, "１０００", [], {},
])
def test_a_weight_that_is_not_a_number_never_becomes_one(monkeypatch, value):
    """Including a Unicode digit string, which `float()` would happily accept."""
    monkeypatch.setattr(providers, "_get_json", lambda url, timeout=4.0: [
        {"id": 1, "material": "PLA", "label_weight": value, "weight_used": 0.0}])
    spool = providers.bambuddy("http://b")["spools"][0]
    assert spool["remaining_g"] is None
    assert spool["remaining_quality"] == providers.UNTRACKED


def test_duplicate_spool_ids_do_not_silently_pick_the_wrong_one(monkeypatch):
    """Two spools with one id is Bambuddy's problem; guessing would be Studio's."""
    monkeypatch.setattr(providers, "_get_json", lambda url, timeout=4.0: [
        {"id": 1, "material": "PLA", "label_weight": 1000, "weight_used": 0.0},
        {"id": 1, "material": "PETG", "label_weight": 1000, "weight_used": 900.0}])
    state = providers.bambuddy("http://b", slot_map={"0": 1})
    assert len(state["slots"]) == 1
    # Whichever wins, the slot describes exactly one spool and nothing is merged.
    slot = state["slots"][0]
    assert slot["material"] in ("PLA", "PETG")
    assert slot["remaining_g"] in (1000.0, 100.0)


def test_a_spool_with_no_id_cannot_be_mapped_to_a_slot(monkeypatch):
    monkeypatch.setattr(providers, "_get_json", lambda url, timeout=4.0: [
        {"material": "PLA", "label_weight": 1000, "weight_used": 0.0}])
    state = providers.bambuddy("http://b", slot_map={"0": 1})
    assert state["slots"][0]["present"] is False
    assert any("no spool with id 1" in n for n in state["slots"][0]["notes"])


def test_a_malformed_colour_is_no_colour(monkeypatch):
    monkeypatch.setattr(providers, "_get_json", lambda url, timeout=4.0: [
        {"id": 1, "material": "PLA", "rgba": "not-a-colour", "label_weight": 1000,
         "weight_used": 0.0}])
    assert providers.bambuddy("http://b")["spools"][0]["color"] is None


def test_the_eight_digit_colour_becomes_the_six_studio_uses(monkeypatch):
    """Bambuddy writes RRGGBBAA; every other colour in Studio is RRGGBB."""
    monkeypatch.setattr(providers, "_get_json", lambda url, timeout=4.0: [
        {"id": 1, "material": "PLA", "rgba": "ff3b3080", "label_weight": 1000,
         "weight_used": 0.0}])
    assert providers.bambuddy("http://b")["spools"][0]["color"] == "#FF3B30"


def test_enormous_strings_do_not_become_a_material_or_a_vendor(monkeypatch):
    monkeypatch.setattr(providers, "_get_json", lambda url, timeout=4.0: [
        {"id": 1, "material": "P" * 100_000, "brand": "V" * 100_000,
         "label_weight": 1000, "weight_used": 0.0}])
    spool = providers.bambuddy("http://b")["spools"][0]
    # Not truncated here — but it must not crash, and it must stay a plain string
    # that the comparison downstream treats as "not PLA".
    assert isinstance(spool["material"], str)
    plan = material_plan.plan(
        [{"tool": 0, "used": True, "grams": 10.0, "type": "PLA"}],
        providers.as_loaded_filaments(providers.combine(
            providers.bambuddy("http://b", slot_map={"0": 1}))), [0])
    slot = plan["slots"][0]
    assert slot["has_material"] != slot["wants_material"]
    assert slot["action"], "a slot loaded with something else must say what to do"


# --- being unreachable, and being asked for credentials ----------------------

def test_an_unreachable_bambuddy_is_unknown_not_empty(monkeypatch):
    monkeypatch.setattr(providers, "_get_json", lambda url, timeout=4.0: (
        _ for _ in ()).throw(urllib.error.URLError("connection refused")))
    out = providers.bambuddy("http://192.168.1.50:8000", slot_map={"0": 1})
    assert out["available"] is False
    assert out["slots"] == []
    assert "192.168.1.50" not in json.dumps(out)


def test_a_timeout_is_an_answer_rather_than_a_crash(monkeypatch):
    monkeypatch.setattr(providers, "_get_json", lambda url, timeout=4.0: (
        _ for _ in ()).throw(TimeoutError()))
    out = providers.bambuddy("http://b")
    assert out["available"] is False
    # plan-39 v3.2 N-4: the same timeout-sentence pattern as every provider.
    assert "did not answer in time" in out["error"]
    assert "Studio waited about 4 seconds" in out["error"]


def test_a_wrapped_timeout_reads_the_same_as_a_bare_one(monkeypatch):
    """plan-39 v3.4 L-2: `URLError(reason=TimeoutError())` — the shape the real
    transport actually raises when the shared read deadline expires — is
    recognised as a timeout exactly like a bare `TimeoutError`."""
    monkeypatch.setattr(providers, "_get_json", lambda url, timeout=4.0: (
        _ for _ in ()).throw(urllib.error.URLError(TimeoutError())))
    out = providers.bambuddy("http://b")
    assert out["available"] is False
    assert "did not answer in time" in out["error"]


@pytest.mark.parametrize("code", [401, 403])
def test_a_bambuddy_that_wants_an_api_key_is_told_it_cannot_have_one(monkeypatch, code):
    """Studio has nowhere safe to keep a secret, so it says so.

    Bambuddy can be run with authentication on, and then every route wants an
    `X-API-Key`. Storing one in the clear to make this work would trade a real
    security property for a convenience, so the honest answer is that this
    deployment is not one Studio can read.
    """
    def raise_http(url, timeout=4.0):
        raise urllib.error.HTTPError(url, code, "Forbidden", {}, None)

    monkeypatch.setattr(providers, "_get_json", raise_http)
    out = providers.bambuddy("http://b")
    assert out["available"] is False
    assert "API key" in out["error"]
    assert out["slots"] == []


def test_another_http_error_is_reported_as_itself(monkeypatch):
    def raise_http(url, timeout=4.0):
        raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)

    monkeypatch.setattr(providers, "_get_json", raise_http)
    assert "HTTP 500" in providers.bambuddy("http://b")["error"]


# --- the decision the whole thing exists for ---------------------------------

def test_a_real_full_spool_never_blocks_a_send(real_bambuddy, captured):
    """Bambuddy saying 1000 g must not become a Studio fact."""
    untouched = next(s for s in captured["spools"]
                     if s["label_weight"] == 1000 and s["weight_used"] == 0
                     and not s["last_weighed_at"])
    state = providers.bambuddy("http://b", slot_map={"0": untouched["id"]})
    loaded = providers.as_loaded_filaments(providers.combine(state))
    plan = material_plan.plan(
        [{"tool": 0, "used": True, "grams": 2000.0, "type": "PLA"}], loaded, [0])
    sufficiency = plan["slots"][0]["sufficiency"]
    assert sufficiency["verdict"] == "probably_short"
    assert sufficiency["trusted"] is False
    assert sufficiency["freshness"] == freshness.UNKNOWN


def test_a_real_tracked_shortfall_still_blocks(real_bambuddy, captured, monkeypatch):
    """The sentence worth saying, arrived at through Bambuddy's arithmetic."""
    weighed = next(s for s in captured["spools"] if s["last_weighed_at"])
    recent = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=3)).isoformat()
    payload = [dict(s, last_weighed_at=recent) if s["id"] == weighed["id"] else s
               for s in captured["spools"]]
    monkeypatch.setattr(providers, "_get_json", lambda url, timeout=4.0: payload)

    state = providers.bambuddy("http://b", slot_map={"0": weighed["id"]})
    grams = by_id(state, weighed["id"])["remaining_g"]
    loaded = providers.as_loaded_filaments(providers.combine(state))
    facts = {"available": True, "tools_used": [0],
             "slots": [{"tool": 0, "used": True, "grams": grams * 3, "type": "PLA"}]}
    plan = material_plan.from_facts(facts, {"loaded_filaments": loaded})
    assert plan["slots"][0]["sufficiency"]["verdict"] == "insufficient"
    assert plan["slots"][0]["sufficiency"]["trusted"] is True

    out = send_check.evaluate(facts, {"reachable": True, "loaded_filaments": loaded}, plan)
    assert any("Not enough filament" in i["title"]
               for i in out["items"] if i["kind"] == send_check.BLOCKER)


def test_studio_never_writes_to_bambuddy():
    """It has routes that would create, archive and reweigh spools. None is called."""
    import inspect

    source = inspect.getsource(providers)
    for verb in ('method="POST"', 'method="PATCH"', 'method="PUT"', 'method="DELETE"'):
        assert verb not in source
    assert "/archive" not in source
    assert "update-spool-weight" not in source
