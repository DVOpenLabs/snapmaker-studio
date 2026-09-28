"""Two providers, one set of decisions.

Studio has had a material-provider *seam* for several releases and exactly one
implementation behind it, which proves nothing: a seam with one implementation
is a function with an unusual name. This file is the second implementation's
reason for existing.

The claim under test is narrow and it is the whole point:

    Given two providers stating the same physical thing about a spool, in their
    own wire formats, everything downstream must reach the same decision — the
    same sufficiency verdict, the same blockers and warnings, the same
    confidence, the same conflict behaviour, the same send-check answer.

The only difference allowed anywhere in the result is the provider's *name*,
appearing as provenance on a fact. So the comparison scrubs the two names to one
token and then demands the results be equal — not similar, equal.

Each scenario is built from the **raw payload each provider actually returns**
and pushed through that provider's real adapter, because the seam is only proved
if the normalisation is part of what is being tested. Spoolman states a remaining
weight and hides the material and vendor inside a nested filament object;
Bambuddy has no remaining-weight field at all and Studio must subtract two
numbers to get one. If those two roads meet, the seam is real.

The wire formats here are not invented. They are the shapes captured from a real
Spoolman 0.26.1 and a real Bambuddy 1.2.5.3 — see the fixtures beside this file.
"""
from __future__ import annotations

import ast
import datetime
import json
import urllib.error
from pathlib import Path

import pytest

from snapstudio_core import (material_plan, material_providers as providers,
                             send_check)

FIXTURES = Path(__file__).parent / "fixtures" / "providers"


def _ago(**kw) -> str:
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(**kw)).isoformat()


# --- the same spool, said two different ways ---------------------------------
#
# Each builder returns the raw JSON its provider would return for one spool.
# `label` is the physical size, `used` what has come off it, `when` the moment
# that was last true, or None when nothing records it.

def spoolman_spool(spool_id: int, *, material="PLA", subtype="Basic",
                   vendor="Polymaker", color="FF3B30", label=1000.0, used=100.0,
                   when=None, archived=False, quantity=True) -> dict:
    """Spoolman's shape: a stated remaining weight, and a nested filament."""
    spool = {
        "id": spool_id,
        "registered": "2026-01-01T00:00:00Z",
        "archived": archived,
        "filament": {
            "name": f"{vendor} {material}",
            "material": " ".join(x for x in (material, subtype) if x),
            "weight": label,
            "color_hex": color,
            "vendor": {"name": vendor},
        },
    }
    if used is not None:
        spool["used_weight"] = used
    if when is not None:
        spool["last_used"] = when
    if quantity and label is not None and used is not None:
        spool["remaining_weight"] = round(label - used, 1)
    return spool


def bambuddy_spool(spool_id: int, *, material="PLA", subtype="Basic",
                   vendor="Polymaker", color="FF3B30", label=1000, used=100.0,
                   when=None, archived=False, quantity=True) -> dict:
    """Bambuddy's shape: no remaining weight at all, and flat fields."""
    return {
        "id": spool_id,
        "material": material,
        "subtype": subtype,
        "brand": vendor,
        "color_name": None,
        # Eight hex digits, no hash: RRGGBBAA.
        "rgba": (color + "FF") if color else None,
        "label_weight": int(label) if (quantity and label is not None) else 0,
        "core_weight": 250,
        "weight_used": used if used is not None else 0.0,
        "last_used": when,
        "last_scale_weight": None,
        "last_weighed_at": None,
        "archived_at": "2026-08-01T00:00:00" if archived else None,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }


BUILDERS = {providers.SPOOLMAN: spoolman_spool, providers.BAMBUDDY: bambuddy_spool}


def read_one(kind: str, monkeypatch, spools, slot_map, unavailable=False) -> dict:
    """Run a provider's real adapter over a payload it would really have sent."""
    def fake_get(url, timeout=4.0):
        if unavailable:
            raise urllib.error.URLError("connection refused")
        return spools

    monkeypatch.setattr(providers, "_get_json", fake_get)
    return providers.read(kind, "http://provider.local:1234", slot_map, slot_base=0)


# --- scrubbing provenance ----------------------------------------------------

def scrub(value):
    """Replace every trace of *which* provider with one token.

    Provenance is the one difference the seam is allowed to have: a fact may say
    where it came from. Anything else that differs is the abstraction leaking.
    """
    if isinstance(value, dict):
        return {scrub(k): scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        for name in ("Spoolman", "spoolman", "Bambuddy", "bambuddy"):
            value = value.replace(name, "PROVIDER")
        return value
    return value


# --- the scenarios -----------------------------------------------------------
#
# `needed` is what the job asks of slot 0. Everything else describes the spool.

SCENARIOS = {
    "enough tracked recent":  dict(needed=200.0, spool=dict(label=1000, used=100.0,
                                                            when=_ago(hours=3))),
    "clearly short tracked recent": dict(needed=400.0, spool=dict(label=1000, used=980.0,
                                                                  when=_ago(hours=3))),
    "stale short":            dict(needed=400.0, spool=dict(label=1000, used=980.0,
                                                            when=_ago(days=30))),
    "derived short":          dict(needed=400.0, spool=dict(label=1000, used=980.0,
                                                            when=None)),
    "undated short":          dict(needed=400.0, spool=dict(label=100, used=0.0, when=None)),
    "remaining unknown":      dict(needed=400.0, spool=dict(quantity=False, label=None,
                                                            used=None, when=None)),
    "archived":               dict(needed=200.0, spool=dict(label=1000, used=100.0,
                                                            when=_ago(hours=3),
                                                            archived=True)),
    "different material":     dict(needed=200.0, spool=dict(material="PETG", subtype="Matte",
                                                            vendor="Prusament",
                                                            color="1C1C1E",
                                                            label=1000, used=300.0,
                                                            when=_ago(hours=3))),
}

#: What the job asks for, in the shape a G-code read produces.
def job(needed, material="PLA") -> dict:
    return {"available": True, "tools_used": [0],
            "slots": [{"tool": 0, "used": True, "grams": needed, "type": material}]}


def run(kind, monkeypatch, *, needed, spool, slot_map=None, printer=None,
        unavailable=False) -> dict:
    """One provider, all the way to a send-check answer."""
    payload = [BUILDERS[kind](7, **spool)]
    state = read_one(kind, monkeypatch, payload, slot_map or {"0": 7},
                     unavailable=unavailable)
    states = ([printer] if printer else []) + [state]
    combined = providers.combine(*states)
    loaded = providers.as_loaded_filaments(combined)
    facts = job(needed)
    plan = material_plan.from_facts(facts, {"loaded_filaments": loaded})
    check = send_check.evaluate(facts, {"reachable": True, "loaded_filaments": loaded}, plan)
    return {
        "slots": combined["slots"],
        "remaining_known": combined["remaining_known"],
        "plan": plan["slots"],
        "verdict": check["verdict"],
        "counts": check["counts"],
        "items": [{k: i[k] for k in ("kind", "title", "detail")} for i in check["items"]],
    }


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_equivalent_facts_produce_identical_decisions(name, monkeypatch):
    """The central gate. If this fails, the seam is not generic — fix the seam."""
    case = SCENARIOS[name]
    results = {kind: scrub(run(kind, monkeypatch, **case)) for kind in BUILDERS}

    a, b = results[providers.SPOOLMAN], results[providers.BAMBUDDY]
    assert a == b, (
        f"{name}: the two providers stated the same thing and Studio decided "
        f"differently.\nSpoolman: {json.dumps(a, indent=1, default=str)}\n"
        f"Bambuddy: {json.dumps(b, indent=1, default=str)}")


def test_the_scenarios_actually_exercise_the_decisions_they_claim_to(monkeypatch):
    """A table of identical answers proves nothing if every answer is the same.

    Equivalence is only interesting when the scenarios genuinely reach different
    verdicts, so this asserts the spread rather than trusting it.
    """
    verdicts = {}
    for name, case in SCENARIOS.items():
        out = run(providers.SPOOLMAN, monkeypatch, **case)
        verdicts[name] = out["plan"][0]["sufficiency"]["verdict"]

    assert verdicts["enough tracked recent"] == "enough"
    assert verdicts["clearly short tracked recent"] == "insufficient"
    # Stale and derived may warn; neither may be the sole reason a send is refused.
    assert verdicts["stale short"] == "probably_short"
    assert verdicts["derived short"] == "probably_short"
    assert verdicts["undated short"] == "probably_short"
    assert verdicts["remaining unknown"] == "unknown"
    assert len(set(verdicts.values())) >= 4


def test_only_a_tracked_recent_shortfall_blocks_on_either_provider(monkeypatch):
    """The one sentence strong enough to stop a send, reached the same way twice."""
    for kind in BUILDERS:
        blocked = run(kind, monkeypatch, **SCENARIOS["clearly short tracked recent"])
        assert any("Not enough filament" in i["title"]
                   for i in blocked["items"] if i["kind"] == send_check.BLOCKER), kind

        for softer in ("stale short", "derived short", "undated short"):
            out = run(kind, monkeypatch, **SCENARIOS[softer])
            assert not [i for i in out["items"]
                        if i["kind"] == send_check.BLOCKER
                        and "filament" in i["title"].lower()], f"{kind}: {softer}"


# --- the cases that are not about one spool ----------------------------------

def test_a_provider_that_will_not_answer_is_unknown_on_either(monkeypatch):
    """Unreachable is unknown. Not empty, and certainly not enough."""
    results = {}
    for kind in BUILDERS:
        out = run(kind, monkeypatch, needed=400.0, spool=dict(), unavailable=True)
        assert out["slots"] == []
        assert out["remaining_known"] is False
        results[kind] = scrub(out)
    assert results[providers.SPOOLMAN] == results[providers.BAMBUDDY]


def test_a_mapping_pointing_at_nothing_reads_the_same_on_either(monkeypatch):
    """A slot mapped to a spool id the provider does not have."""
    results = {}
    when = _ago(hours=3)
    for kind in BUILDERS:
        out = run(kind, monkeypatch, needed=400.0,
                  spool=dict(label=1000, used=100.0, when=when),
                  slot_map={"0": 999})
        slot = out["slots"][0]
        assert slot["present"] is False
        assert slot["confidence"] == providers.UNKNOWN
        assert any("no spool with id 999" in n for n in slot["notes"])
        results[kind] = scrub(out)
    assert results[providers.SPOOLMAN] == results[providers.BAMBUDDY]


def printer_says(material: str, color: str | None = None) -> dict:
    return {"schema_version": providers.SCHEMA_VERSION, "source": providers.STOCK,
            "available": True, "remaining_known": False,
            "slots": [providers._slot(0, material=material, color=color,
                                      confirmed_by=providers.BY_PRINTER)]}


def test_a_printer_provider_conflict_behaves_the_same_on_either(monkeypatch):
    """Printer sees PLA; the mapping says PETG. Shown, not resolved — twice."""
    results = {}
    when = _ago(hours=3)
    for kind in BUILDERS:
        out = run(kind, monkeypatch, needed=200.0,
                  spool=dict(material="PETG", subtype="Matte", color="1C1C1E",
                             label=1000, used=100.0, when=when),
                  printer=printer_says("PLA", "#000000"))
        slot = out["slots"][0]
        assert slot["material"] == "PLA", kind          # the printer is looking
        assert slot["confidence"] == providers.UNKNOWN
        assert slot["confirmed_by"] == providers.BY_PRINTER
        assert slot["remaining_g"] == 900.0             # the weight still survives
        # `disagreed` names the real source — the merged row's value is
        # STOCK's here, not a hardcoded "printer" key.
        assert slot["disagreed"]["material"][providers.STOCK] == "PLA"
        results[kind] = scrub(out)
    assert results[providers.SPOOLMAN] == results[providers.BAMBUDDY]


def test_a_printer_that_agrees_behaves_the_same_on_either(monkeypatch):
    """No disagreement to report, and the provider still supplies the weight."""
    results = {}
    when = _ago(hours=3)
    for kind in BUILDERS:
        out = run(kind, monkeypatch, needed=200.0,
                  spool=dict(label=1000, used=100.0, when=when),
                  printer=printer_says("PLA"))
        slot = out["slots"][0]
        assert not slot.get("conflicts")
        assert slot["confirmed_by"] == providers.BY_PRINTER
        assert slot["remaining_g"] == 900.0
        results[kind] = scrub(out)
    assert results[providers.SPOOLMAN] == results[providers.BAMBUDDY]


def test_a_machine_that_reports_no_filament_reads_the_same_on_either(monkeypatch):
    """Most Klipper printers say nothing. Then the mapping is the only source —
    and it must not be dressed up as something the machine confirmed."""
    results = {}
    when = _ago(hours=3)
    for kind in BUILDERS:
        out = run(kind, monkeypatch, needed=200.0,
                  spool=dict(label=1000, used=100.0, when=when))
        slot = out["slots"][0]
        assert slot["confirmed_by"] == providers.BY_PROVIDER
        assert slot["confidence"] == providers.LIKELY
        results[kind] = scrub(out)
    assert results[providers.SPOOLMAN] == results[providers.BAMBUDDY]


# --- an empty slot is three different facts ----------------------------------
#
# Found by the installed-build acceptance run, not by this suite, and it was a
# defect of exactly the kind this project's honesty rules exist to prevent: a
# slot whose provider mapping named a spool that no longer existed was described
# to the user as
#
#     "This job prints from this slot and the printer reports it empty."
#
# with no printer configured, no printer contacted, and nothing having looked at
# the slot at all. `as_loaded_filaments` drops a slot that holds nothing, so by
# the time the plan was built the three causes of an absent slot were
# indistinguishable — and the sentence picked the one that sounded most certain.

def empty_slot_plan(monkeypatch, kind, *, spool_id, printer=None):
    """Map a slot to a spool the provider does not have, and read the plan."""
    payload = [BUILDERS[kind](7, label=1000, used=100.0, when=_ago(hours=3))]
    state = read_one(kind, monkeypatch, payload, {"0": spool_id})
    combined = providers.combine(*([printer] if printer else []) + [state])
    facts = job(200.0)
    return material_plan.from_facts(facts, {
        "loaded_filaments": providers.as_loaded_filaments(combined),
        "slot_facts": combined["slots"],
    })["slots"][0]


@pytest.mark.parametrize("kind", sorted(BUILDERS))
def test_a_stale_mapping_is_never_reported_as_a_printer_observation(monkeypatch, kind):
    slot = empty_slot_plan(monkeypatch, kind, spool_id=999)
    assert slot["state"] == "empty"
    assert slot["printer_confirmed"] is False
    assert "printer reports it empty" not in slot["detail"]
    # And the reason is carried through rather than dropped, because it sends the
    # person to the provider to fix a mapping instead of to the printer to look
    # at a slot that may well have a spool in it.
    assert any("no spool with id 999" in note for note in slot["notes"])
    assert "no spool with id 999" in slot["detail"]


def test_the_two_providers_still_say_the_same_thing_about_a_stale_mapping(monkeypatch):
    both = {kind: scrub(empty_slot_plan(monkeypatch, kind, spool_id=999))
            for kind in BUILDERS}
    assert both[providers.SPOOLMAN] == both[providers.BAMBUDDY]


@pytest.mark.parametrize("kind", sorted(BUILDERS))
def test_a_printer_that_looked_and_saw_nothing_still_says_so(monkeypatch, kind):
    """The sentence was not wrong, only unearned. Where it is earned it stays."""
    empty = {"schema_version": providers.SCHEMA_VERSION, "source": providers.STOCK,
             "available": True, "remaining_known": False,
             "slots": [providers._slot(0, present=False,
                                       confirmed_by=providers.BY_PRINTER)]}
    slot = empty_slot_plan(monkeypatch, kind, spool_id=999, printer=empty)
    assert slot["state"] == "empty"
    assert slot["printer_confirmed"] is True
    assert "printer reports it empty" in slot["detail"]


def test_with_nothing_configured_at_all_studio_says_exactly_that():
    """No provider, no printer slot facts: silence, described as silence."""
    facts = job(200.0)
    slot = material_plan.from_facts(facts, {"loaded_filaments": [None]})["slots"][0]
    assert slot["state"] == "empty"
    assert slot["printer_confirmed"] is False
    assert "nothing Studio can read says what is in it" in slot["detail"]


def test_the_older_call_shape_is_unchanged():
    """`plan()` without slot facts is what every caller predating this passes."""
    out = material_plan.plan(
        [{"tool": 0, "used": True, "grams": 200.0, "type": "PLA"}], [None], [0])
    assert out["slots"][0]["state"] == "empty"


# --- keeping the boundary where it is ----------------------------------------

#: Everything downstream of the adapters. None of it may name a provider.
GENERIC = ("material_plan.py", "send_check.py", "freshness.py", "post_slice.py",
           "print_plan.py", "preflight.py")

ENGINE = Path(__file__).resolve().parents[1] / "snapstudio_core"


@pytest.mark.parametrize("filename", GENERIC)
def test_no_generic_consumer_branches_on_a_provider_name(filename):
    """A source guard, because the table above cannot catch code nobody added yet.

    `material_providers.py` is where a provider's name is allowed to be a
    decision; that is what an adapter is. Anywhere past it, a comparison against
    a provider name is the seam failing quietly, and it is much easier to add
    such a line than to notice one.

    This reads the syntax tree rather than the text, so it flags what a provider
    name is *used for* instead of whether it is mentioned. These modules explain
    themselves in prose, and naming Spoolman in a comment as an example of a
    provider is documentation. `if source == "spoolman":` is the thing to catch.
    """
    tree = ast.parse((ENGINE / filename).read_text("utf-8"), filename)
    offenders = []

    def names_a_provider(node) -> bool:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return any(n in node.value.lower() for n in ("spoolman", "bambuddy", "spoolease"))
        if isinstance(node, ast.Attribute):
            return node.attr in ("SPOOLMAN", "BAMBUDDY", "SPOOLEASE")
        if isinstance(node, ast.Name):
            return node.id in ("SPOOLMAN", "BAMBUDDY", "SPOOLEASE")
        return False

    for node in ast.walk(tree):
        # `x == "spoolman"`, `x in ("spoolman", ...)`, `x is providers.SPOOLMAN`
        if isinstance(node, ast.Compare):
            parts = [node.left, *node.comparators]
            for part in parts:
                inner = part.elts if isinstance(part, (ast.Tuple, ast.List, ast.Set)) else [part]
                if any(names_a_provider(x) for x in inner):
                    offenders.append(f"{filename}:{node.lineno}: a comparison against "
                                     "a provider name")
        # `providers.SPOOLMAN` used as a value anywhere in this module at all.
        elif names_a_provider(node) and isinstance(node, (ast.Attribute, ast.Name)):
            offenders.append(f"{filename}:{node.lineno}: the constant "
                             f"{getattr(node, 'attr', getattr(node, 'id', '?'))}")

    assert not offenders, (
        "a generic consumer names a provider - the decision belongs in the "
        "adapter:\n" + "\n".join(sorted(set(offenders))))


def test_every_registered_provider_has_a_display_name():
    """A provider that can be read must have something to call it on screen."""
    assert set(providers.READERS) == set(providers.PROVIDER_NAMES)
    assert providers.READERS[providers.SPOOLMAN] is providers.spoolman
    assert providers.READERS[providers.BAMBUDDY] is providers.bambuddy
    assert providers.READERS[providers.SPOOLEASE] is providers.spoolease
    assert providers.PROVIDER_NAMES[providers.SPOOLEASE] == "SpoolEase"


def test_read_normalises_error_code_and_weight_source_on_every_kind(monkeypatch):
    """Astra-5: `error_code`/`weight_source` are always present, for every
    registered provider, not only for the one that can actually fail with a
    wire-level code."""
    def fake_get(url, timeout=4.0):
        return []
    monkeypatch.setattr(providers, "_get_json", fake_get)
    for kind in (providers.SPOOLMAN, providers.BAMBUDDY):
        out = providers.read(kind, "http://provider.local:1234")
        assert "error_code" in out and "weight_source" in out
        assert out["error_code"] is None
        assert out["weight_source"] is None


def test_an_unknown_provider_name_is_refused_rather_than_guessed():
    out = providers.read("filamentron-9000", "http://provider.local:1234")
    assert out["available"] is False
    assert "does not know how to read" in out["error"]
    assert out["slots"] == [] and out["spools"] == []
