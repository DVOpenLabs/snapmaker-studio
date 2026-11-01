"""Route level (/passport/build, /passport/import, /passport/verify) and package guards.

Plan common tests C3, C7 and guards G1, G2, G3 as they apply to this package.
Evidence label: fixture-tested.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from snapstudio_api import ext_routes, routes_passport  # noqa: F401  (registers the routes)

ROOT = pathlib.Path(__file__).resolve().parents[2]
PACKAGE_FILES = (sorted((ROOT / "snapstudio_core" / "passport").glob("*.py"))
                 + [ROOT / "snapstudio_core" / "passport_cli.py", ROOT / "snapstudio_api" / "routes_passport.py"])


class FakeHandler:
    def __init__(self):
        self.sent = []

    def _send(self, code, obj):
        self.sent.append((code, obj))


def call(path, data):
    h = FakeHandler()
    assert ext_routes.dispatch(h, path, data) is True
    assert len(h.sent) == 1
    return h.sent[0]


@pytest.fixture
def files(tmp_path):
    out = {}
    for name, body in (("a.3mf", b"synthetic a"), ("b.3mf", b"synthetic b"), ("c.gcode", b"synthetic c")):
        (tmp_path / name).write_bytes(body)
        out[name] = str(tmp_path / name)
    return out


def entries(files):
    return [{"path": files["a.3mf"], "role": "original"}, {"path": files["b.3mf"], "role": "prepared"},
            {"path": files["c.gcode"], "role": "sliced"}]


def test_routes_are_registered_under_passport_only():
    names = {"/passport/build", "/passport/import", "/passport/verify"}
    assert names <= set(ext_routes.ROUTES)
    assert all(p.startswith("/passport") for p, fn in ext_routes.ROUTES.items() if fn.__module__.endswith("routes_passport"))


def test_build_then_verify_then_a_change_invalidates(files):
    code, built = call("/passport/build", {"entries": entries(files)})
    assert code == 200 and built["passport"]["schema_version"] == "passport/1"
    assert set(built["paths"].values()) == set(files.values())
    assert files["a.3mf"] not in json.dumps(built["passport"])             # paths stay out of the document
    code, ok = call("/passport/verify", {"passport": built["passport"], "paths": built["paths"]})
    assert code == 200 and ok["verification"]["summary"]["all_intact"] is True
    pathlib.Path(files["a.3mf"]).write_bytes(b"synthetic A")
    code, bad = call("/passport/verify", {"passport": built["passport"], "paths": built["paths"]})
    summary = bad["verification"]["summary"]
    assert summary["all_intact"] is False and summary["invalidated"] == ["a.3mf", "b.3mf", "c.gcode"]


def test_build_reports_a_missing_file_as_a_diagnostic_not_a_crash(files):
    body = entries(files)
    body[1]["path"] = body[1]["path"] + ".missing"
    code, out = call("/passport/build", {"entries": body})
    assert code == 200 and out["passport"] is None and out["diagnostics"][0]["code"] == "file_missing"


def test_import_marks_everything_declared_and_flags_a_false_parent(files, tmp_path):
    _c, built = call("/passport/build", {"entries": entries(files)})
    doc = json.loads(json.dumps(built["passport"]))
    for d in doc["derivations"]:
        d["witness"] = "local"
        d["declared_by"] = None
    other = tmp_path / "other"
    other.mkdir()
    (other / "a.3mf").write_bytes(b"not the same")
    (other / "b.3mf").write_bytes(pathlib.Path(files["b.3mf"]).read_bytes())
    code, res = call("/passport/import", {"passport": doc, "base_dir": str(other)})
    assert code == 200
    assert {p["witness"] for p in res["parentage"]} == {"declared"}
    assert [p["output"] for p in res["parentage"] if p["declared_mismatch"]] == ["b.3mf"]


@pytest.mark.parametrize("path, body", [
    ("/passport/build", {}), ("/passport/build", {"entries": []}), ("/passport/build", {"entries": [1]}),
    ("/passport/build", {"entries": [{"path": 5, "role": "original"}]}),
    ("/passport/verify", {}), ("/passport/verify", {"passport": []}),
    ("/passport/verify", {"passport": {}, "paths": {"a": 1}}),
    ("/passport/verify", {"passport": {}, "base_dir": "no-such-folder-here"}),
    ("/passport/import", {"passport": "text"}),
])
def test_bad_requests_are_400(path, body):
    code, out = call(path, body)
    assert code == 400 and out["error"] == "invalid"


def test_an_unusable_passport_is_a_200_with_no_verification():
    code, out = call("/passport/verify", {"passport": {"schema_version": "passport/9"}})
    assert code == 200 and out["verification"] is None and out["diagnostics"][0]["code"] == "unknown_schema_version"


def test_a_credential_in_the_request_is_not_echoed_anywhere(files):
    code, out = call("/passport/build", {"entries": entries(files), "api_key": "SENTINEL-KEY-9f3a"})
    assert code == 200 and "SENTINEL-KEY-9f3a" not in json.dumps(out)


# -- package guards ----------------------------------------------------------------------
def test_c3_every_fixture_dir_has_provenance():
    assert (ROOT / "tests" / "fixtures" / "passport" / "PROVENANCE.md").is_file()


def test_g1_no_network_or_printer_control_in_package_sources():
    banned = re.compile(r"urlopen|\brequests\b|http\.client|socket\.create_connection|moonraker\._get|"
                        r"moonraker\.(status|history|pause|resume|cancel|start)|netguard|import socket")
    for path in PACKAGE_FILES:
        text = path.read_text(encoding="utf-8")
        assert not banned.search(text), path.name


def test_g3_no_head_count_from_slot_count():
    for path in PACKAGE_FILES:
        text = path.read_text(encoding="utf-8")
        assert "slot_count" not in text and "len(nozzles)" not in text, path.name


def test_c7_no_banned_claim_words_in_package_files():
    paths = PACKAGE_FILES + [ROOT.parent / "docs" / "internal" / "PASSPORT.md"]
    paths += list((ROOT / "tests" / "fixtures" / "passport").iterdir())
    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        for word in ("simultaneous", "guaranteed", "100%"):
            assert word not in text, (path.name, word)
