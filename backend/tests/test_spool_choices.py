"""The spool picker's list: identity fields, a colour in words, one deterministic order."""
import random

import pytest

from snapstudio_core import spool_choices as sc


def spool(i, vendor="Acme", material="PLA", subtype=None, color="#FF0000", **kw):
    return {"id": i, "vendor": vendor, "material": material, "subtype": subtype, "color": color,
            "remaining_g": kw.pop("remaining_g", None), "remaining_quality": kw.pop("remaining_quality", None),
            "archived": kw.pop("archived", False), **kw}


def test_colour_names_follow_the_apps_bands():
    assert sc.color_name("#FF0000") == "red"
    assert sc.color_name("#000000") == "black"
    assert sc.color_name("#FFFFFF") == "white"
    assert sc.color_name("#008000") == "green"
    assert sc.color_name("#F7D959") == "gold/yellow"
    assert sc.color_name("#A3D8E1") == "light blue"
    assert sc.color_name("not a colour") is None
    assert sc.color_name(None) is None
    assert sc.color_name("#FF0000FF") == "red"      # RGBA


def test_choices_expose_every_identity_field():
    c = sc.build([spool(124, vendor="Yoopai", material="PLA", subtype="Matte", remaining_g=250.0,
                        remaining_quality="estimated")], "spoolease")[0]
    assert c == {"id": 124, "label": "Yoopai PLA Matte", "vendor": "Yoopai", "material": "PLA",
                 "subtype": "Matte", "color": "#FF0000", "color_name": "red", "source": "spoolease",
                 "slicer_filament": None,
                 "remaining_g": 250.0, "remaining_quality": "estimated", "archived": False}


def test_a_name_the_provider_gives_the_colour_wins_over_the_computed_one():
    c = sc.build([spool(1, color="#FF0000", color_name="Cherry")], "bambuddy")[0]
    assert c["color_name"] == "Cherry"


def test_sorted_vendor_then_material_then_subtype_then_colour_then_id():
    spools = [
        spool(9, vendor="Sunlu", material="ABS", color="#000000"),
        spool(3, vendor="Acme", material="PLA", subtype="Silk", color="#FF0000"),
        spool(2, vendor="Acme", material="PLA", subtype="Matte", color="#FF0000"),
        spool(1, vendor="Acme", material="PETG", color="#FF0000"),
        spool(7, vendor="acme", material="PLA", subtype="Matte", color="#0000FF"),
        spool(10, vendor="Acme", material="PLA", subtype="Matte", color="#FF0000"),
    ]
    order = [c["id"] for c in sc.build(spools, "spoolman")]
    assert order == [1, 7, 2, 10, 3, 9]   # PETG, then PLA Matte: blue before red, then ids, then Silk, then Sunlu


def test_numeric_ids_sort_as_numbers_and_text_ids_after_them():
    spools = [spool("A1"), spool(1000), spool(124), spool("b2"), spool(5)]
    assert [c["id"] for c in sc.build(spools, "x")] == [5, 124, 1000, "A1", "b2"]


def test_a_spool_that_says_nothing_sorts_after_one_that_does():
    spools = [spool(1, vendor=None), spool(2, vendor="Zeta")]
    assert [c["id"] for c in sc.build(spools, "x")] == [2, 1]


def test_order_does_not_depend_on_the_providers_order():
    base = [spool(i, vendor=("A", "B", "C")[i % 3], material=("PLA", "ABS")[i % 2],
                  color=("#FF0000", "#00FF00", "#0000FF")[i % 3]) for i in range(1, 130)]
    expected = [c["id"] for c in sc.build(base, "x")]
    for seed in range(5):
        shuffled = base[:]
        random.Random(seed).shuffle(shuffled)
        assert [c["id"] for c in sc.build(shuffled, "x")] == expected


def test_two_identical_looking_spools_stay_distinguishable_by_id():
    twins = sc.build([spool(133, vendor="Sunlu", material="ABS", color="#000000"),
                      spool(134, vendor="Sunlu", material="ABS", color="#000000")], "spoolease")
    assert twins[0]["label"] == twins[1]["label"]
    assert [c["id"] for c in twins] == [133, 134]


@pytest.mark.parametrize("name", ["Bambuddy-ish name", None])
def test_label_prefers_the_providers_own_name(name):
    c = sc.build([spool(1, vendor="V", name=name)], "x")[0]
    assert c["label"] == ("V Bambuddy-ish name" if name else "V PLA")


def test_provider_test_returns_the_sorted_identity_choices(monkeypatch):
    from snapstudio_api import service
    from snapstudio_core import material_providers as providers

    monkeypatch.setattr(providers, "validate_provider_url", lambda u: "http://192.168.1.50")
    state = {"available": True, "weight_source": "scale", "spools": [
        {"id": "2", "vendor": "Sunlu", "material": "ABS", "subtype": None, "color": "#000000",
         "color_name": "Black", "remaining_g": None, "remaining_quality": None, "archived": False},
        {"id": "1", "vendor": "Acme", "material": "PLA", "subtype": "Matte", "color": "#FF0000",
         "remaining_g": 250.0, "remaining_quality": "estimated", "remaining_as_of": None,
         "archived": False}]}
    monkeypatch.setattr(providers, "read", lambda kind, url, key=None, **k: state)
    out = service.provider_test("192.168.1.50", "spoolease", "key")
    assert out["ok"] is True
    assert [c["id"] for c in out["choices"]] == ["1", "2"]          # Acme before Sunlu
    first, second = out["choices"]
    assert (first["vendor"], first["material"], first["subtype"], first["color_name"]) == ("Acme", "PLA", "Matte", "red")
    assert second["color_name"] == "Black" and second["source"] == "spoolease"
    assert "192.168" not in repr(out)


def test_the_providers_slicer_filament_name_is_passed_through_as_an_input():
    c = sc.build([spool(1, slicer_filament="  Generic PLA ")], "spoolease")[0]
    assert c["slicer_filament"] == "Generic PLA"
