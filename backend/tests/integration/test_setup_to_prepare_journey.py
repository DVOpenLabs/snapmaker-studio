"""Journey: read a host (mock Moonraker) -> /setups/evaluate -> topology -> service.convert -> saved project.

Evidence label: mock-service-tested. The host is an in-process 127.0.0.1 mock serving a hand-written
upstream-shaped bundle; the 8-slot case is a hypothetical variant of the four-head fixture, not a capture.
No real printer. service.convert is the function the /convert route calls.
"""
from __future__ import annotations

import json
import pathlib

from snapstudio_api import ext_routes, service
from tests.mocks.hosts.host_mocks import make_moonraker
from tests.integration.setup_helpers import FILAMENT_SCOPE, HEAD_SCOPE, project_cfg
from tests.test_project_materials import _prepared, _project

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "adapters" / "host"


class _H:
    def __init__(self):
        self.sent = []

    def _send(self, code, obj):
        self.sent.append((code, obj))


def bundle(name):
    return json.loads((FIXTURES / "moonraker_stock" / "moonraker-0.9" / f"{name}.json").read_text("utf-8"))["bundle"]


def eight_slot_bundle():
    b = bundle("four_heads_loaded")
    cfg = b["print_task_config"]["result"]["status"]["print_task_config"]
    for key, value in list(cfg.items()):
        if isinstance(value, list) and len(value) == 4:
            cfg[key] = value + value             # eight logical entries on the same four heads
    cfg["extruder_map_table"] = [0, 1, 2, 3, 0, 1, 2, 3]
    return b


def read_setup(b):
    server = make_moonraker(b)
    try:
        h = _H()
        assert ext_routes.dispatch(h, "/setups/evaluate", {"host": "127.0.0.1", "port": server.server_address[1]})
        code, body = h.sent[0]
        assert code == 200
        return body
    finally:
        server.stop()


def prepare(tmp_path, n, topology, name):
    src = _project(tmp_path, project_cfg(n), name=f"{name}.3mf")
    result = service.convert(str(src), str(tmp_path / name), "preserve", False, None, topology=topology)
    return result, _prepared(type("R", (), {"output_path": result["output_path"]}))


def vec(key, n):
    return [f"{key}-{i}" for i in range(n)]


def stock_cut(out):
    return all(out[k] == vec(k, 8)[:4] for k in FILAMENT_SCOPE + HEAD_SCOPE)


def at_scope(out, filaments, heads=4):
    return all(out[k] == vec(k, filaments) for k in FILAMENT_SCOPE) and all(out[k] == vec(k, heads) for k in HEAD_SCOPE)


def test_stock_u1_four_heads_is_unchanged_with_or_without_the_setup(tmp_path):
    body = read_setup(bundle("four_heads_loaded"))
    assert body["topology"] is not None and len(body["topology"]["heads"]) == 4
    _, with_setup = prepare(tmp_path, 4, body["topology"], "a")
    _, without = prepare(tmp_path, 4, None, "b")
    assert at_scope(with_setup, 4) and at_scope(without, 4)
    assert {k: with_setup[k] for k in FILAMENT_SCOPE + HEAD_SCOPE} == {k: without[k] for k in FILAMENT_SCOPE + HEAD_SCOPE}


def test_an_eight_slot_setup_keeps_every_mapping_through_preparation(tmp_path):
    body = read_setup(eight_slot_bundle())
    topo = body["topology"]
    assert len(topo["heads"]) == 4 and len(topo["slots"]) == 8
    assert body["report"]["entries"][0]["counts"]["physical_heads"] == 4
    result, out = prepare(tmp_path, 8, topo, "c")
    assert at_scope(out, 8)                           # filament settings 8 long, head settings 4 long
    assert result["settings_summary"]["setup"]["slots"] == 8
    # the same project without the setup shows the stock cut to four
    _, stock = prepare(tmp_path, 8, None, "d")
    assert stock_cut(stock)


def test_a_map_entry_naming_an_unseen_head_leaves_that_slot_unbound_and_is_not_guessed(tmp_path):
    b = eight_slot_bundle()
    b["print_task_config"]["result"]["status"]["print_task_config"]["extruder_map_table"] = [0, 1, 2, 3, 9, 1, 2, 3]
    body = read_setup(b)
    topo = body["topology"]
    assert len(topo["slots"]) == 8 and len(topo["bindings"]) == 7
    assert "bindings" in body["report"]["entries"][0]["unknowns"]
    bound = {x["slot_id"] for x in topo["bindings"]}
    assert "slot:4" not in bound                       # slot 4 is unknown, not defaulted to head 0 or 1
    result, out = prepare(tmp_path, 8, topo, "e")
    assert at_scope(out, 8)                            # an unknown binding is not a contradiction: nothing is dropped
    assert result["settings_summary"]["setup"]["unbound"] == ["slot:4"]
