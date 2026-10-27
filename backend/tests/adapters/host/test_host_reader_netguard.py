"""Host layer: kind decided from reply bodies, auth failures are `unavailable`, every read via netguard.

Mocks are in-process 127.0.0.1 servers that count connections. Evidence label: fixture-tested.
"""
from __future__ import annotations

import ast
import inspect
import json
import pathlib

import pytest

from snapstudio_core.adapters import registry
from snapstudio_core.adapters.host import classify, reader
from snapstudio_core.foundation.netguard import NetguardRefused
from tests.mocks.hosts.host_mocks import SECRET_KEY, MockHost, make_moonraker, make_octoprint

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "adapters" / "host"
HOST_SRC = pathlib.Path(reader.__file__).parent
ALLOWED_PATHS = {"/api/version", "/server/info", "/printer/objects/list", "/printer/objects/query",
                 "/machine/system_info"}


def bundle(system: str, version: str, case: str) -> dict:
    return json.loads((FIXTURES / system / version / f"{case}.json").read_text(encoding="utf-8"))["bundle"]


@pytest.fixture
def mocks():
    made: list[MockHost] = []

    def add(server: MockHost) -> MockHost:
        made.append(server)
        return server

    yield add
    for server in made:
        server.stop()


def _parse_with_registry(res: reader.HostRead):
    adapter = registry.get(res.adapter_id)
    assert adapter is not None
    return adapter.parse(res.bundle, received_at="2026-10-26T12:00:00Z", source_version="host_bundle/1")


# plan test 3
def test_octoprint_is_identified_by_api_version_body_not_a_preset(mocks):
    assert "host_type" not in inspect.signature(reader.read_host).parameters
    server = mocks(make_octoprint())
    res = reader.read_host(server.origin, api_key=SECRET_KEY)
    assert (res.status, res.kind, res.adapter_id) == ("ok", "octoprint", "host.octoprint")
    assert _parse_with_registry(res).ok


def test_classify_uses_bodies_only():
    octo = {"api": "0.1", "server": "1.9.3", "text": "OctoPrint 1.9.3"}
    assert classify.classify(octo, None) == "octoprint"
    assert classify.classify({"hello": "world"}, None) == "unknown"
    assert classify.classify("OctoPrint", None) == "unknown"
    assert classify.classify(None, None) == "unknown"


# plan test 4
def test_moonraker_octoprint_compat_is_classified_moonraker_from_server_info(mocks):
    data = bundle("moonraker_stock", "moonraker-0.9", "four_heads_loaded")
    server = mocks(make_moonraker(data, octoprint_compat=True))
    res = reader.read_host(server.origin)
    assert res.kind == "moonraker" and res.adapter_id == "host.moonraker_stock"
    assert "/server/info" in server.paths() and "/api/version" in server.paths()
    # an OctoPrint-shaped /api/version body alone does not beat the /server/info payload
    octo_shaped = {"api": "0.1", "server": "0.9.3", "text": "OctoPrint 0.9.3"}
    assert classify.classify(octo_shaped, data["server_info"]) == "moonraker"
    assert _parse_with_registry(res).topology.complete


def test_moonraker_without_compat_is_still_moonraker(mocks):
    server = mocks(make_moonraker(bundle("moonraker_stock", "moonraker-0.9", "four_heads_loaded"),
                                  octoprint_compat=False))
    assert reader.read_host(server.origin).kind == "moonraker"


def test_paxx_variant_is_detected_from_the_spool_id_array_or_a_hint(mocks):
    paxx = mocks(make_moonraker(bundle("moonraker_paxx", "paxx-synthetic-1", "spool_ids_present")))
    assert reader.read_host(paxx.origin).adapter_id == "host.moonraker_paxx"
    quiet = mocks(make_moonraker(bundle("moonraker_paxx", "paxx-synthetic-1", "spool_id_missing")))
    assert reader.read_host(quiet.origin).adapter_id == "host.moonraker_stock"        # nothing says paxx
    hinted = reader.read_host(quiet.origin, variant_hint="paxx")
    assert hinted.adapter_id == "host.moonraker_paxx"
    res = _parse_with_registry(hinted)
    assert "spool" in res.unknowns and not [f for f in res.material_facts if f.field == "spool"]


def test_unrecognised_host_is_reported_not_guessed(mocks):
    server = mocks(MockHost({"/api/version": (200, {"hello": "world"})}).start())
    res = reader.read_host(server.origin)
    assert (res.status, res.kind, res.bundle) == ("unrecognised", "unknown", None)


# plan test 5
def test_missing_api_key_is_unavailable_with_no_retry(mocks):
    server = mocks(make_octoprint())
    res = reader.read_host(server.origin)
    assert (res.status, res.reason, res.retries, res.bundle) == ("unavailable", "api_key_missing", 0, None)
    assert server.paths() == ["/api/version"] and server.connections == 1


def test_rejected_key_is_unavailable_with_no_retry_and_the_key_is_not_echoed(mocks):
    server = mocks(make_octoprint())
    res = reader.read_host(server.origin, api_key="wrong-key-value-0002")
    assert (res.status, res.reason, res.retries) == ("unavailable", "auth_required", 0)
    assert server.paths() == ["/api/version"]
    assert "wrong-key-value-0002" not in json.dumps(res.to_dict())
    assert server.requests[0]["headers"].get("x-api-key") == "wrong-key-value-0002"   # sent to its own origin only


def test_key_never_appears_in_the_result_or_the_bundle(mocks):
    server = mocks(make_octoprint())
    res = reader.read_host(server.origin, api_key=SECRET_KEY)
    assert SECRET_KEY not in json.dumps(res.to_dict()) and SECRET_KEY not in json.dumps(res.bundle)


def test_unreachable_host_is_unavailable_not_an_exception(mocks):
    server = make_octoprint()
    origin = server.origin
    server.stop()
    res = reader.read_host(origin, api_key=SECRET_KEY)
    assert (res.status, res.reason, res.retries) == ("unavailable", "unreachable", 0)


# plan test 10
def test_only_documented_read_only_get_endpoints_are_used(mocks):
    server = mocks(make_moonraker(bundle("moonraker_paxx", "paxx-synthetic-1", "spool_ids_present")))
    reader.read_host(server.origin)
    assert {r["method"] for r in server.requests} == {"GET"}
    assert set(server.paths()) <= ALLOWED_PATHS


def test_redirect_to_another_local_server_is_refused_and_it_gets_zero_connections(mocks):
    forbidden = mocks(make_octoprint(require_key=None))
    redirector = mocks(MockHost(redirect_to=forbidden.origin + "/api/version").start())
    with pytest.raises(NetguardRefused) as caught:
        reader.read_host(redirector.origin, api_key=SECRET_KEY)
    assert caught.value.code == "redirect"
    assert forbidden.connections == 0 and forbidden.requests == []
    assert redirector.connections >= 1
    assert all("x-api-key" in r["headers"] for r in redirector.requests)   # only the configured origin saw it


def test_redirect_to_a_public_address_is_refused(mocks):
    redirector = mocks(MockHost(redirect_to="http://203.0.113.9:7125/server/info").start())
    with pytest.raises(NetguardRefused) as caught:
        reader.read_host(redirector.origin)
    assert caught.value.code == "redirect"


@pytest.mark.parametrize("url", ["http://8.8.8.8:7125", "http://1.1.1.1", "ftp://127.0.0.1", "http://user@127.0.0.1"])
def test_public_or_malformed_addresses_are_refused_before_any_connection(url):
    with pytest.raises(NetguardRefused) as caught:
        reader.read_host(url)
    assert caught.value.code in ("off_network", "public_address", "syntax")


def test_a_second_local_host_sees_zero_connections(mocks):
    configured = mocks(make_moonraker(bundle("moonraker_stock", "moonraker-0.9", "four_heads_loaded")))
    other = mocks(make_octoprint(require_key=None))
    reader.read_host(configured.origin)
    assert other.connections == 0 and other.requests == []


# plan test 14 + G1/G3/G5 adjacency
def _tree(name: str) -> ast.AST:
    return ast.parse((HOST_SRC / name).read_text(encoding="utf-8"))


def _imports(tree: ast.AST) -> set:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.add(("." * node.level) + (node.module or ""))
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def test_parsers_are_network_free_and_never_import_legacy_moonraker_or_netguard():
    for name in ("moonraker_parse.py", "moonraker_base.py", "moonraker_stock.py", "moonraker_paxx.py",
                 "octoprint.py", "classify.py"):
        imported = _imports(_tree(name))
        for bad in ("socket", "ssl", "http.client", "urllib.request", "requests", "urllib3",
                    "snapstudio_core.moonraker", "....moonraker", "...moonraker"):
            assert not any(i == bad or i.startswith(bad + ".") for i in imported), (name, bad)
        assert not any("netguard" in i for i in imported), name


def test_reader_is_the_only_host_module_that_uses_netguard_and_it_calls_local_request_only():
    uses = [p.name for p in HOST_SRC.glob("*.py")
            if any("netguard" in i for i in _imports(_tree(p.name)))]
    assert uses == ["reader.py"]
    src = (HOST_SRC / "reader.py").read_text(encoding="utf-8")
    assert "netguard.local_request(" in src and "write_ok" not in src
    assert "socket" not in _imports(_tree("reader.py"))


# plan test 13
def test_readme_says_what_ships_without_p1a_and_fixtures_are_honest():
    readme = (HOST_SRC / "README.md").read_text(encoding="utf-8")
    assert "stock Moonraker, Paxx Moonraker and OctoPrint only" in readme
    assert "P1a" in readme and "fixture-tested" in readme
    provenance = (FIXTURES / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "none of these files is a capture" in provenance.lower()
    import re
    for path in FIXTURES.rglob("*.json"):
        for ip in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", path.read_text(encoding="utf-8")):
            assert ip.startswith("192.0.2."), (path.name, ip)
