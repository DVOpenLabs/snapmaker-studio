"""Fixtures must match the published upstream key sets, so they cannot drift into invented shapes."""
import json
import re
from pathlib import Path

import pytest

from . import accessory_contracts as C

FIXTURES = Path(__file__).parents[2] / "fixtures" / "adapters" / "accessory"
ADAPTERS = Path(__file__).parents[3] / "snapstudio_core" / "adapters" / "accessory"
SKIP = {"unknown_source_version", "malformed", "auth_401", "auth_403"}
TOLERATED_VARIANTS = {"status_plain", "result_envelope"}


def cases(system):
    return list(_cases(system))


def _cases(system):
    for path in sorted((FIXTURES / system).glob("*/*.json")):
        if path.stem not in SKIP:
            yield pytest.param(path, id=f"{system}-{path.stem}")


def body_of(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == {"http_status", "body"}, "fixtures use only the Studio transport envelope"
    return payload["http_status"], payload["body"]


@pytest.mark.parametrize("path", cases("multiace"))
def test_accessory_contract_multiace_fixture_keys(path):
    status, body = body_of(path)
    if status == 409:
        assert set(body) == {"detail"}
        return
    assert set(body) == {"live_slots", "head_ctx"}
    for row in body["live_slots"]:
        assert set(row) == C.MULTIACE_LIVE_SLOT
    ctx = body["head_ctx"]
    assert set(ctx) <= C.MULTIACE_CTX_ALLOWED
    if path.stem != "disconnected":
        assert C.MULTIACE_CTX_REQUIRED <= set(ctx)
    for name in ("manual_heads", "feeders"):
        for row in ctx.get(name, []):
            assert set(row) == C.MULTIACE_MANUAL_OR_FEEDER
    for key in list(ctx.get("head_nozzles", {})) + list(ctx.get("head_ace", {})):
        assert isinstance(key, str) and key.isdigit(), "head objects are keyed by string index"


@pytest.mark.parametrize("path", cases("afc"))
def test_accessory_contract_afc_fixture_keys(path):
    _, body = body_of(path)
    if path.stem == "result_envelope":
        body = body["result"]
    wrapper = "status" if path.stem == "status_plain" else C.AFC_WRAPPER
    assert set(body) == {wrapper}
    afc = body[wrapper]["AFC"]
    assert set(afc["system"]) == C.AFC_SYSTEM_KEYS
    for unit_name, unit in afc.items():
        if unit_name == "system":
            continue
        assert set(unit["system"]) == C.AFC_UNIT_SYSTEM_KEYS
        for lane_name, lane in unit.items():
            if lane_name != "system":
                assert set(lane) <= C.AFC_LANE_KEYS     # {} = lane not yet connected (get_status line 2185)


@pytest.mark.parametrize("path", cases("bmcu"))
def test_accessory_contract_bmcu_fixture_keys(path):
    _, body = body_of(path)
    assert set(body) <= {"kind", "text", "body"}
    if body["kind"] == "transport_status":
        assert set(body["body"]) <= C.BMCU_PANEL_KEYS
        for device in body["body"]["devices"]:
            assert set(device) <= C.BMCU_PANEL_DEVICE_KEYS
        return
    for line in body["text"].splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        command = line.split()[0]
        assert command in C.BMCU_COMMANDS, command
        for name in re.findall(r"([A-Z_]+)=", line):
            assert name in C.BMCU_PARAMS, name


@pytest.mark.parametrize("path", cases("sidecar"))
def test_accessory_contract_sidecar_fixture_keys(path):
    _, body = body_of(path)
    if body["kind"] == "gcode":
        for marker in re.findall(r"^\s*;\s*(SIDECAR:[A-Z]+)=", body["text"], re.M):
            assert marker in C.SIDECAR_MARKERS
        return
    reply = body["body"]
    if body["kind"] == "loadcell" and reply.get("ok"):
        assert set(reply) == C.SIDECAR_LOADCELL_KEYS
        for cell in reply["lanes"].values():
            assert set(cell) == C.SIDECAR_LOADCELL_LANE_KEYS
    else:
        assert set(reply) <= C.SIDECAR_ERROR_KEYS | {"ok"}


def test_accessory_contract_every_key_a_parser_reads_is_listed():
    published = (C.MULTIACE_LIVE_SLOT | C.MULTIACE_CTX_ALLOWED | C.MULTIACE_MANUAL_OR_FEEDER | C.AFC_LANE_KEYS
                 | C.AFC_UNIT_SYSTEM_KEYS | C.AFC_SYSTEM_KEYS | {C.AFC_WRAPPER, "status", "AFC", "result", "system"}
                 | C.BMCU_PANEL_KEYS | C.BMCU_PANEL_DEVICE_KEYS | C.SIDECAR_LOADCELL_KEYS
                 | C.SIDECAR_LOADCELL_LANE_KEYS | C.SIDECAR_ERROR_KEYS | C.ENVELOPE_KEYS | {"live_slots", "head_ctx"})
    published |= {p.lower() for p in C.BMCU_PARAMS} | C.BMCU_PARAMS
    read = set()
    for path in ADAPTERS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        read |= set(re.findall(r'\.get\("([A-Za-z_:]+)"', text)) | set(re.findall(r'\["([A-Za-z_:]+)"\]', text))
    # Keys the parsers build themselves (row dicts, Studio fields) are not wire keys.
    # Studio-side evidence labels and local state, never read from a payload.
    internal = {"head", "ace", "slot", "bmcu_print_map", "sidecar_t_mapping", "committed"}
    unlisted = {k for k in read - published - internal if not k.isupper()}
    assert unlisted == set(), f"parser reads keys that no published contract lists: {sorted(unlisted)}"
