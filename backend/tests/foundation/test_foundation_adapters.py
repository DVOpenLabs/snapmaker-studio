"""P0a acceptance 17: adapter base (never raises) and registry (literal discovery)."""
from __future__ import annotations

import importlib.util
import json
import sys

import pytest

from snapstudio_core.adapters import registry
from snapstudio_core.adapters.base import Adapter, AdapterInfo, AdapterResult
from snapstudio_core.foundation.materials import MaterialFact
from snapstudio_core.foundation.observations import freshness
from snapstudio_core.foundation.topology import (Lane, FeederUnit, PhysicalToolhead, Topology,
                                                 head_id, lane_id, unit_id)

NOW = "2026-10-25T12:00:00Z"


class FakeAdapter(Adapter):
    info = AdapterInfo(id="fake_host", kind="host", versions_supported=("1.0",), ttl_s=30.0)

    def _parse(self, data, received_at, result):
        unit = unit_id("stock", "a")
        lanes = [Lane(id=lane_id(unit, 0), unit_id=unit, index=0, reachable_heads=[head_id(0)],
                      state="loaded")]
        result.topology = Topology(snapshot_id="snap-1", received_at=str(received_at),
                                   heads=[PhysicalToolhead(id=head_id(0), index=0, nozzle_mm=0.4)],
                                   units=[FeederUnit(id=unit, kind="stock", lanes=lanes)], complete=True)
        self.observe(result, observation_id="o1", subject={"kind": "lane", "id": lanes[0].id},
                     field="state", value="loaded", snapshot_id="snap-1", received_at=received_at,
                     provider_time=data.get("stamp"))
        result.material_facts.append(MaterialFact("material", data["material"], "provider", "o1"))
        result.unknowns.append("remaining_g")


class ExplodingAdapter(FakeAdapter):
    info = AdapterInfo(id="boom", kind="host", versions_supported=("1.0",), ttl_s=5)

    def _parse(self, data, received_at, result):
        raise KeyError("SENTINEL-KEY-9f3a")


GOOD = {"material": "PLA", "stamp": "2026-10-25T11:59:50Z"}


def test_good_payload_yields_normalised_documents():
    r = FakeAdapter().parse(GOOD, received_at=NOW, source_version="1.0")
    assert isinstance(r, AdapterResult) and r.ok and r.errors == []
    assert r.source_version == "1.0" and r.adapter_id == "fake_host"
    assert r.topology.snapshot_id == "snap-1" and r.topology.complete is True
    assert [f.value for f in r.material_facts] == ["PLA"]
    assert r.unknowns == ["remaining_g"]
    json.dumps(r.to_dict())
    assert r.to_decoded().valid_for_evaluation is True and r.to_decoded().value is r


def test_observations_carry_the_declared_ttl_and_provider_time():
    r = FakeAdapter().parse(GOOD, received_at=NOW, source_version="1.0")
    obs = r.observations[0]
    assert obs.ttl_s == 30.0 and obs.observed_at == "2026-10-25T11:59:50Z"
    assert obs.source["source_version"] == "1.0" and obs.source["provider_instance_id"] == "fake_host"
    assert freshness(obs, NOW)["state"] == "fresh"
    assert not any(d.code == "observed_at_is_receipt_time" for d in r.diagnostics)


def test_without_provider_time_the_receipt_time_diagnostic_is_recorded():
    r = FakeAdapter().parse({"material": "PETG"}, received_at=NOW, source_version="1.0")
    assert any(d.code == "observed_at_is_receipt_time" for d in r.diagnostics)


@pytest.mark.parametrize("bad_ttl", [0, -1, float("nan"), float("inf"), True, None, "30"])
def test_adapter_must_declare_a_finite_positive_ttl(bad_ttl):
    class Bad(Adapter):
        info = AdapterInfo(id="bad", kind="host", versions_supported=("1",), ttl_s=bad_ttl)
    with pytest.raises(ValueError, match="ttl_s"):
        Bad()


def test_adapter_without_info_or_with_bad_kind_is_refused():
    class NoInfo(Adapter):
        pass
    with pytest.raises(ValueError):
        NoInfo()

    class BadKind(Adapter):
        info = AdapterInfo(id="x", kind="cloud", versions_supported=("1",), ttl_s=5)
    with pytest.raises(ValueError, match="kind"):
        BadKind()


@pytest.mark.parametrize("payload", [
    "not json {", b"\xff\xfe\x00", "", b"", "null", "42", '"text"', 42, 3.5, None, True,
    float("nan"), object(), "[1, 2", '{"a": ' * 5000])
def test_malformed_payload_never_raises_and_returns_diagnostics(payload):
    r = FakeAdapter().parse(payload, received_at=NOW, source_version="1.0")
    assert not r.ok and r.errors
    assert r.topology is None and r.observations == [] and r.material_facts == []
    assert r.unknowns == ["all"]
    assert r.to_decoded().value is None and r.to_decoded().valid_for_evaluation is False


def test_payload_missing_a_required_field_is_reported_not_raised():
    r = FakeAdapter().parse({}, received_at=NOW, source_version="1.0")   # data["material"] -> KeyError inside _parse
    assert [e.code for e in r.errors] == ["adapter_failed"]
    assert r.topology is None and r.observations == [] and r.material_facts == []


def test_parser_defect_message_is_dropped():
    r = ExplodingAdapter().parse(GOOD, received_at=NOW, source_version="1.0")
    assert [e.code for e in r.errors] == ["adapter_failed"]
    assert "SENTINEL" not in json.dumps(r.to_dict())


@pytest.mark.parametrize("version", ["9.9", None, "", 1, "1.0.1"])
def test_unknown_source_version_is_all_unknown_with_errors(version):
    r = FakeAdapter().parse(GOOD, received_at=NOW, source_version=version)
    assert [e.code for e in r.errors] == ["unknown_source_version"]
    assert r.topology is None and r.observations == [] and r.material_facts == []
    assert r.unknowns == ["all"]
    assert r.source_version == (version if isinstance(version, str) else None)


def test_json_text_and_bytes_are_accepted():
    for payload in (json.dumps(GOOD), json.dumps(GOOD).encode()):
        assert FakeAdapter().parse(payload, received_at=NOW, source_version="1.0").ok


def test_adapter_modules_import_no_transport():
    for name in ("base", "registry"):
        spec = importlib.util.find_spec(f"snapstudio_core.adapters.{name}")
        text = open(spec.origin, encoding="utf-8").read()
        for banned in ("socket", "urllib", "http.client", "requests", "netguard", "subprocess"):
            assert f"import {banned}" not in text and f"from {banned}" not in text, (name, banned)


# -- registry --------------------------------------------------------------------

@pytest.fixture
def clean_registry():
    before = dict(registry.REGISTRY)
    yield registry.REGISTRY
    registry.REGISTRY.clear()
    registry.REGISTRY.update(before)


def test_register_get_and_filter_by_kind(clean_registry):
    a = FakeAdapter()
    registry.register(a)
    assert registry.get("fake_host") is a and a in registry.all_adapters("host")
    assert a not in registry.all_adapters("accessory")
    registry.register(a)                        # same instance again is harmless


def test_duplicate_id_and_non_adapter_are_refused(clean_registry):
    registry.register(FakeAdapter())
    with pytest.raises(registry.RegistryError):
        registry.register(FakeAdapter())
    with pytest.raises(registry.RegistryError):
        registry.register(object())


def test_discover_uses_literal_imports_for_accessory_and_host():
    text = open(registry.__file__, encoding="utf-8").read()
    assert "from . import accessory  # noqa: F401" in text and "from . import host  # noqa: F401" in text


def test_discover_skips_absent_packages(monkeypatch):
    monkeypatch.setitem(sys.modules, "snapstudio_core.adapters.accessory", None)
    monkeypatch.setitem(sys.modules, "snapstudio_core.adapters.host", None)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None)
    registry.discover()


def test_discover_re_raises_for_a_present_but_broken_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "snapstudio_core.adapters.host", None)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: object())
    with pytest.raises(ImportError):
        registry.discover()


def test_every_adapter_package_that_exists_registers_adapters():
    registry.discover()
    for kind in ("accessory", "host"):
        if importlib.util.find_spec(f"snapstudio_core.adapters.{kind}") is not None:
            assert registry.all_adapters(kind), kind   # until integration only existing packages are checked
    for adapter in registry.all_adapters():
        assert adapter.info.ttl_s > 0
