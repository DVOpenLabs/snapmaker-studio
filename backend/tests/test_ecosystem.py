"""Ecosystem tool recommendation.

The value of this feature is entirely in its honesty: a suggestion is only worth
something if it was earned by a fact Studio actually read out of the file, and if
"installed" means the executable is really there. These tests hold that line —
including the boring default case, where the right answer is the official slicer
and nothing clever.
"""
from __future__ import annotations

import json

import pytest

from snapstudio_core import ecosystem


@pytest.fixture()
def registry():
    return {
        "schema_version": "ecosystem/1",
        "updated": "2026-08-22",
        "tools": [
            {"id": "orca", "name": "Snapmaker Orca", "kind": "slicer", "official": True,
             "base_score": 50, "handoff": "file", "url": "https://example.invalid/orca",
             "license": "AGPL-3.0",
             "recommend_when": [{"trait": "is_u1_project", "op": "is_true", "weight": 25,
                                 "reason": "Already a U1 project."}]},
            {"id": "fork", "name": "Nozzle Fork", "kind": "slicer", "official": False,
             "base_score": 0, "handoff": "file", "url": "https://example.invalid/fork",
             "license": "AGPL-3.0", "caution": "Community fork.",
             "recommend_when": [{"trait": "mixed_nozzle_sizes", "op": "is_true", "weight": 40,
                                 "reason": "Mixed nozzle sizes are its whole point."}]},
            {"id": "hub", "name": "Print Hub", "kind": "printer-dashboard", "official": False,
             "base_score": 0, "handoff": "link", "stage": "after-slicing",
             "url": "https://example.invalid/hub", "license": "MIT",
             "recommend_when": [{"trait": "is_sliced", "op": "is_true", "weight": 20,
                                 "reason": "Already sliced."}]},
            {"id": "many", "name": "Many Colours", "kind": "utility", "official": False,
             "base_score": 0, "handoff": "link", "url": "https://example.invalid/many",
             "license": "MIT",
             "recommend_when": [{"trait": "filament_count", "op": "at_least", "value": 4,
                                 "weight": 10, "reason": "Four or more filaments."}]},
        ],
    }


def _traits(**values):
    return {k: {"value": v, "confidence": "confirmed", "evidence": "test"}
            for k, v in values.items()}


def test_default_is_the_official_slicer(registry):
    out = ecosystem.recommend(_traits(is_u1_project=True, mixed_nozzle_sizes=False),
                              registry=registry)
    assert out["primary"]["id"] == "orca"
    assert out["primary"]["why"] == ["Already a U1 project."]
    assert out["alternatives"] == []


def test_a_fork_only_wins_when_its_trigger_is_present(registry):
    plain = ecosystem.recommend(_traits(is_u1_project=True, mixed_nozzle_sizes=False),
                                registry=registry)
    assert all(a["id"] != "fork" for a in plain["alternatives"])

    mixed = ecosystem.recommend(_traits(is_u1_project=True, mixed_nozzle_sizes=True),
                                registry=registry)
    ids = [mixed["primary"]["id"]] + [a["id"] for a in mixed["alternatives"]]
    assert "fork" in ids


def test_every_recommendation_carries_its_reason(registry):
    out = ecosystem.recommend(_traits(is_u1_project=True, mixed_nozzle_sizes=True,
                                      is_sliced=True), registry=registry)
    for entry in [out["primary"], *out["alternatives"]]:
        assert entry["why"], f"{entry['id']} was recommended with no reason"


def test_unmeasured_traits_never_fire_a_rule(registry):
    """An unknown trait is not a false — it must simply not trigger anything."""
    out = ecosystem.recommend(_traits(is_u1_project=None, mixed_nozzle_sizes=None,
                                      is_sliced=None), registry=registry)
    assert out["primary"]["id"] == "orca"      # base score only
    assert out["primary"]["why"] == []
    assert out["alternatives"] == []


def test_installed_is_only_claimed_when_a_path_was_found(registry):
    out = ecosystem.recommend(_traits(is_u1_project=True), registry=registry)
    assert out["primary"]["installed"] is False
    assert out["primary"]["path"] is None

    out2 = ecosystem.recommend(_traits(is_u1_project=True),
                               installed={"orca": r"C:\Apps\orca.exe"}, registry=registry)
    assert out2["primary"]["installed"] is True
    assert out2["primary"]["path"] == r"C:\Apps\orca.exe"


def test_empty_install_path_is_not_installed(registry):
    out = ecosystem.recommend(_traits(is_u1_project=True),
                              installed={"orca": ""}, registry=registry)
    assert out["primary"]["installed"] is False


def test_installed_breaks_a_score_tie(registry):
    """Between equals, recommend the one the user can actually click right now."""
    reg = {"schema_version": "ecosystem/1", "tools": [
        {"id": "a", "name": "A", "base_score": 10, "recommend_when": []},
        {"id": "b", "name": "B", "base_score": 10, "recommend_when": []},
    ]}
    out = ecosystem.recommend({}, installed={"b": "/usr/bin/b"}, registry=reg)
    assert out["primary"]["id"] == "b"


def test_at_least_operator_rejects_booleans(registry):
    """True must not sneak through a numeric comparison as 1."""
    out = ecosystem.recommend(_traits(filament_count=True), registry=registry)
    assert all(e["id"] != "many" for e in [out["primary"], *out["alternatives"]] if e)


def test_at_least_operator_works_on_numbers(registry):
    out = ecosystem.recommend(_traits(filament_count=5), registry=registry)
    assert any(e["id"] == "many" for e in [out["primary"], *out["alternatives"]] if e)
    out2 = ecosystem.recommend(_traits(filament_count=3), registry=registry)
    assert all(e["id"] != "many" for e in [out2["primary"], *out2["alternatives"]] if e)


def test_unknown_operator_is_ignored_not_crashing():
    reg = {"schema_version": "ecosystem/1", "tools": [
        {"id": "x", "name": "X", "base_score": 1,
         "recommend_when": [{"trait": "a", "op": "sorcery", "weight": 99, "reason": "no"}]},
    ]}
    out = ecosystem.recommend({"a": True}, registry=reg)
    assert out["primary"]["score"] == 1


def test_discover_lists_matched_but_uninstalled_tools(registry):
    out = ecosystem.recommend(_traits(is_u1_project=True, mixed_nozzle_sizes=True),
                              installed={"orca": "/orca"}, registry=registry)
    discover_ids = [d["id"] for d in out["discover"]]
    assert "fork" in discover_ids
    assert "orca" not in discover_ids


def test_flat_trait_map_is_accepted(registry):
    out = ecosystem.recommend({"is_u1_project": True}, registry=registry)
    assert out["primary"]["id"] == "orca"


def test_summary_mentions_the_primary_tool(registry):
    out = ecosystem.recommend(_traits(is_u1_project=True), registry=registry)
    assert "Snapmaker Orca" in out["summary"]


def test_unreadable_project_gets_an_honest_summary():
    reg = {"schema_version": "ecosystem/1", "tools": []}
    out = ecosystem.recommend({}, registry=reg)
    assert out["primary"] is None
    assert "could not read" in out["summary"]


# --- the shipped registry itself -------------------------------------------

def test_shipped_registry_is_wellformed():
    reg = ecosystem.load_registry()
    assert reg["schema_version"] == ecosystem.SCHEMA_VERSION
    ids = [t["id"] for t in reg["tools"]]
    assert len(ids) == len(set(ids)), "duplicate tool ids"
    for tool in reg["tools"]:
        for field in ("id", "name", "kind", "role", "url", "license", "install_hint"):
            assert tool.get(field), f"{tool.get('id')} missing {field}"
        assert str(tool["url"]).startswith("https://")
        for rule in tool.get("recommend_when") or []:
            assert rule["op"] in ecosystem._OPS, f"{tool['id']} uses unknown op {rule['op']}"
            assert rule.get("reason"), f"{tool['id']} has a rule with no reason"
            assert isinstance(rule.get("weight"), int)


def test_shipped_registry_rules_reference_real_traits():
    """A rule keyed on a trait Studio never measures would silently never fire."""
    from snapstudio_core import project_traits as pt

    known = set(pt.TRAIT_KEYS)
    for tool in ecosystem.load_registry()["tools"]:
        for rule in tool.get("recommend_when") or []:
            assert rule["trait"] in known, \
                f"{tool['id']} matches on unknown trait {rule['trait']}"


def test_every_shipped_tool_can_actually_be_recommended():
    """A registry entry with no base score and no rules can never be returned, so
    listing it advertises something the code cannot surface. Every entry has to be
    reachable for at least one project."""
    from snapstudio_core import project_traits as pt

    unreachable = []
    for tool in ecosystem.load_registry()["tools"]:
        if tool.get("base_score"):
            continue
        rules = tool.get("recommend_when") or []
        if not rules:
            unreachable.append(tool["id"])
            continue
        # Build the trait vector this tool's own rules ask for and check it fires.
        traits = {}
        for rule in rules:
            op, value = rule["op"], rule.get("value")
            traits[rule["trait"]] = {
                "is_true": True, "is_false": False,
                "equals": value, "at_least": value,
            }[op]
        out = ecosystem.recommend(traits)
        found = [e["id"] for e in [out["primary"], *out["alternatives"]] if e]
        if tool["id"] not in found:
            unreachable.append(tool["id"])
    assert not unreachable, f"these tools can never be recommended: {unreachable}"


def test_licences_are_bare_identifiers_not_commentary():
    """Every entry gets the same treatment: an SPDX-style string. Nuance about a
    project's provenance belongs in `notes`, not in a licence field shown to users
    inside a competing product."""
    for tool in ecosystem.load_registry()["tools"]:
        licence = tool["license"]
        assert len(licence) <= 40, f"{tool['id']} has commentary in its licence field"
        assert "(" not in licence, f"{tool['id']} has a parenthetical in its licence field"


def test_shipped_registry_declares_a_license_for_every_tool():
    """Licence is shown in the UI so nobody installs an AGPL fork unaware."""
    for tool in ecosystem.load_registry()["tools"]:
        assert tool["license"], tool["id"]


def test_every_tool_declares_its_maturity():
    for tool in ecosystem.load_registry()["tools"]:
        assert tool.get("maturity") in ("stable", "preview"), tool["id"]


def test_preview_tools_carry_a_caution():
    """A young or experimental project must never be suggested without its warning."""
    for tool in ecosystem.load_registry()["tools"]:
        if tool.get("maturity") == "preview":
            assert tool.get("caution"), f"{tool['id']} is a preview tool with no caution"


def test_registry_loads_from_an_explicit_path(tmp_path, registry):
    p = tmp_path / "reg.json"
    p.write_text(json.dumps(registry), encoding="utf-8")
    assert ecosystem.load_registry(p)["tools"][0]["id"] == "orca"


def test_advise_reads_a_real_file(tmp_path):
    import zipfile

    p = tmp_path / "u1.3mf"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("_rels/.rels", "<Relationships/>")
        z.writestr("3D/3dmodel.model", '<model unit="millimeter"><build/></model>')
        z.writestr("Metadata/project_settings.config",
                   json.dumps({"printer_model": "Snapmaker U1"}))
    out = ecosystem.advise(str(p))
    assert out["traits"]["is_u1_project"]["value"] is True
    assert out["primary"]["id"] == "snapmaker-orca"
