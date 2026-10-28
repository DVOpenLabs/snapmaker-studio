"""Real HTTP boundary: /setups/evaluate and /convert through the actual server, then the saved archive.

Evidence label: mock-service-tested. The host is an in-process 127.0.0.1 mock serving a hand-written
upstream-shaped bundle (the 8-slot case is a hypothetical variant, not a capture). No real printer.
"""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

from snapstudio_api.server import build_server
from snapstudio_core.config_io import load_project_settings
from tests.integration.setup_helpers import FILAMENT_SCOPE, HEAD_SCOPE, project_cfg
from tests.integration.test_setup_to_prepare_journey import bundle, eight_slot_bundle
from tests.mocks.hosts.host_mocks import make_moonraker
from tests.test_project_materials import _project


@pytest.fixture
def api():
    httpd, token = build_server(port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]

    def post(path, body=None, raw=None):
        data = raw if raw is not None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method="POST",
                                     headers={"X-Auth-Token": token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    yield post
    httpd.shutdown()
    httpd.server_close()


def read_setup(post, b):
    host = make_moonraker(b)
    try:
        return post("/setups/evaluate", {"host": "127.0.0.1", "port": host.server_address[1]})
    finally:
        host.stop()


def settings_of(result):
    return load_project_settings(zipfile.ZipFile(result["output_path"]).read("Metadata/project_settings.config"))


def vec(key, n):
    return [f"{key}-{i}" for i in range(n)]


def convert(post, tmp_path, n, name, **extra):
    src = _project(tmp_path, project_cfg(n), name=f"{name}.3mf")
    body = {"path": str(src), "out_dir": str(tmp_path / name), "prepare_mode": "preserve", **extra}
    return src, post("/convert", body)


def test_evaluate_returns_the_topology_over_http(api):
    code, body = read_setup(api, eight_slot_bundle())
    assert code == 200 and len(body["topology"]["heads"]) == 4 and len(body["topology"]["slots"]) == 8
    assert "api_key" not in json.dumps(body)


def test_stock_u1_over_http_unchanged_with_or_without_the_setup(api, tmp_path):
    _, topo = read_setup(api, bundle("four_heads_loaded"))
    _, a = convert(api, tmp_path, 4, "a", topology=topo["topology"])
    _, b = convert(api, tmp_path, 4, "b")
    sa, sb = settings_of(a[1]), settings_of(b[1])
    assert a[0] == b[0] == 200
    assert {k: sa[k] for k in FILAMENT_SCOPE + HEAD_SCOPE} == {k: sb[k] for k in FILAMENT_SCOPE + HEAD_SCOPE}


def test_omitted_setup_cuts_an_eight_filament_project_to_four_as_before(api, tmp_path):
    _, (code, res) = convert(api, tmp_path, 8, "o")
    assert code == 200
    out = settings_of(res)
    assert all(out[k] == vec(k, 8)[:4] for k in FILAMENT_SCOPE + HEAD_SCOPE)


def test_valid_eight_slot_setup_over_http_keeps_each_vector_at_its_scope(api, tmp_path):
    _, topo = read_setup(api, eight_slot_bundle())
    _, (code, res) = convert(api, tmp_path, 8, "v", topology=topo["topology"])
    assert code == 200 and not res.get("blocked")
    out = settings_of(res)
    assert all(out[k] == vec(k, 8) for k in FILAMENT_SCOPE)
    assert all(out[k] == vec(k, 4) for k in HEAD_SCOPE)
    assert res["settings_summary"]["setup"]["slots"] == 8


@pytest.mark.parametrize("topology", ["a string", ["a", "list"], 7, {"padding": "x" * 450_000}])
def test_a_malformed_or_oversize_topology_is_a_400(api, tmp_path, topology):
    src, (code, res) = convert(api, tmp_path, 8, "m", topology=topology)
    assert code == 400 and "topology" in res["error"]
    assert not (tmp_path / "m").exists()


def test_invalid_mapping_over_http_is_blocked_with_nothing_written(api, tmp_path):
    b = eight_slot_bundle()
    b["print_task_config"]["result"]["status"]["print_task_config"]["extruder_map_table"] = [0, 1, 2, 3, 9, 1, 2, 3]
    _, topo = read_setup(api, b)
    topology = topo["topology"]
    topology["bindings"].append({"slot_id": "slot:0", "target": "head:3", "evidence": []})   # contradicts slot 0 -> head 0
    src = _project(tmp_path, project_cfg(8), name="i.3mf")
    digest = hashlib.sha256(Path(src).read_bytes()).hexdigest()
    code, res = api("/convert", {"path": str(src), "out_dir": str(tmp_path / "i"), "prepare_mode": "preserve",
                                 "topology": topology})
    assert code == 200 and res["blocked"] is True and not res.get("output_path")
    assert "cannot be used" in " ".join(res["errors"]) and "Nothing was prepared" in " ".join(res["errors"])
    assert not (tmp_path / "i").exists()
    assert hashlib.sha256(Path(src).read_bytes()).hexdigest() == digest


def test_unbound_slot_over_http_is_reported_not_guessed(api, tmp_path):
    b = eight_slot_bundle()
    b["print_task_config"]["result"]["status"]["print_task_config"]["extruder_map_table"] = [0, 1, 2, 3, 9, 1, 2, 3]
    _, topo = read_setup(api, b)
    assert "bindings" in topo["report"]["entries"][0]["unknowns"]
    _, (code, res) = convert(api, tmp_path, 8, "n", topology=topo["topology"])
    assert code == 200
    assert res["settings_summary"]["setup"]["unbound"] == ["slot:4"]
    assert "1 of 8 material slots" in " ".join(res["settings_summary"]["warnings"])
