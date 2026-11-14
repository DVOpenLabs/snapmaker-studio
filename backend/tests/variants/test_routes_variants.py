"""Route level: /variants/compare answers bad input with a plain 400, never the internal-error 500.

Evidence label: fixture-tested.
"""
from __future__ import annotations

from pathlib import Path

from snapstudio_api import ext_routes, routes_variants  # noqa: F401  (import registers the route)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "variants"


class FakeHandler:
    def __init__(self):
        self.sent = []

    def _send(self, code, obj):
        self.sent.append((code, obj))


def call(data):
    h = FakeHandler()
    assert ext_routes.dispatch(h, "/variants/compare", data) is True
    assert len(h.sent) == 1
    return h.sent[0]


def test_empty_body_is_a_400_with_a_plain_sentence():
    code, body = call({})
    assert code == 400
    assert body["error"] == "invalid"
    assert "exactly two" in body["message"]


def test_missing_file_is_a_400_not_a_500():
    code, body = call({"outputs": [{"path": str(FIXTURES / "nope.gcode")}, {"path": str(FIXTURES / "right.gcode")}]})
    assert code == 400 and body["error"] == "invalid"


def test_two_fixture_outputs_compare():
    code, body = call({"outputs": [{"path": str(FIXTURES / "left.gcode")}, {"path": str(FIXTURES / "right.gcode")}]})
    assert code == 200 and len(body["outputs"]) == 2


def test_garbage_3mf_is_a_400_not_a_500(tmp_path):
    bad = tmp_path / "broken.3mf"
    bad.write_bytes(b"this is not a zip archive")
    code, body = call({"outputs": [{"path": str(bad)}, {"path": str(FIXTURES / "right.gcode")}]})
    assert code == 400 and body["error"] == "invalid"
