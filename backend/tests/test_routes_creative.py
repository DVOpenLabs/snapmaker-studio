"""Route level: /creative/inspect (read-only inspection of a local 3MF).

Evidence label: fixture-tested. Archives are synthetic, built in memory by the checked-in zip factory.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from snapstudio_api import ext_routes, routes_creative

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "creative"))
from zip_factory import make_3mf  # noqa: E402

ROW = "1,2,1,0,50,0,u7"


class FakeHandler:
    def __init__(self):
        self.sent = []

    def _send(self, code, obj):
        self.sent.append((code, obj))


def call(data):
    h = FakeHandler()
    assert ext_routes.dispatch(h, "/creative/inspect", data) is True
    assert len(h.sent) == 1
    return h.sent[0]


def write(tmp_path, blob, name="project.3mf"):
    p = tmp_path / name
    p.write_bytes(blob)
    return str(p)


def test_route_registered_under_creative_only():
    assert "/creative/inspect" in ext_routes.ROUTES
    assert all(p.startswith("/creative") for p, fn in ext_routes.ROUTES.items()
               if fn.__module__.endswith("routes_creative"))


def test_registered_in_a_fresh_interpreter():
    import subprocess
    code = ("from snapstudio_api import ext_routes; "
            "print('/creative/inspect' in ext_routes.ROUTES)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(Path(__file__).resolve().parents[1]), timeout=60)
    assert out.stdout.strip() == "True", out.stderr


def test_fullspectrum_happy_path_with_recipes_and_untouched_original(tmp_path):
    blob = make_3mf(settings={"mixed_filament_definitions": ROW, "layer_height": "0.2"},
                    members={"Metadata/plate_1.png": b"opaque-bytes"})
    path = write(tmp_path, blob)
    code, body = call({"path": path})
    assert code == 200
    assert body["origin"]["generator"] == "fullspectrum" and body["origin"]["status"] == "detected"
    assert "mixed_filament_definitions" in body["understood"]
    names = {i["name"] for i in body["passed_through"]}
    assert {"layer_height", "Metadata/plate_1.png"} <= names
    assert body["recipes"] and all(r["simulated"] is True and r["execution_supported"] is False
                                   for r in body["recipes"])
    assert body["physical_slots_needed"] == 2
    src = body["source"]
    assert src["sha256_before"] == src["sha256_after"] == hashlib.sha256(blob).hexdigest()
    assert src["unchanged"] is True and src["name"] == "project.3mf"
    assert str(tmp_path) not in json.dumps(body)
    assert Path(path).read_bytes() == blob


def test_forca_reports_missing_and_unknown_keys(tmp_path):
    blob = make_3mf(settings={"fos_mms_unit_count": 2, "fos_future_key": 1, "nozzle_diameter": ["0.4"]})
    code, body = call({"path": write(tmp_path, blob)})
    assert code == 200 and body["origin"]["generator"] == "forcaslicer"
    assert "fos_physical_nozzle_diameter" in body["missing"]
    assert "fos_future_key" in body["could_not_interpret"]
    assert "nozzle_diameter" in {i["name"] for i in body["passed_through"]}


def test_unknown_generator_is_origin_unknown(tmp_path):
    blob = make_3mf(settings={"layer_height": "0.2"}, members={"Metadata/x.bin": b"zz"})
    code, body = call({"path": write(tmp_path, blob)})
    assert code == 200
    assert body["origin"] == {"generator": "unknown", "status": "unknown", "candidates": []}
    assert "generator_not_recognized" in body["diagnostics"]
    assert body["recipes"] == []
    assert {"layer_height", "Metadata/x.bin"} <= {i["name"] for i in body["passed_through"]}
    assert body["source"]["unchanged"] is True


def test_ambiguous_generators_are_not_guessed(tmp_path):
    blob = make_3mf(settings={"fos_mms_unit_count": 2, "extruder_layer_height": [0.1]})
    code, body = call({"path": write(tmp_path, blob)})
    assert code == 200
    assert body["origin"]["generator"] == "unknown" and body["origin"]["status"] == "ambiguous"
    assert set(body["origin"]["candidates"]) == {"forcaslicer", "lixnix"}


def test_format_hint_is_honoured_and_validated(tmp_path):
    path = write(tmp_path, make_3mf(settings={"layer_height": "0.2"}))
    code, body = call({"path": path, "format": "lumina"})
    assert code == 200 and body["origin"]["generator"] == "lumina" and body["origin"]["status"] == "chosen"
    assert call({"path": path, "format": "nope"})[0] == 400


def test_missing_file_is_400(tmp_path):
    code, body = call({"path": str(tmp_path / "absent.3mf")})
    assert code == 400 and body["error"] == "invalid"


def test_directory_is_400(tmp_path):
    assert call({"path": str(tmp_path)})[0] == 400


def test_missing_or_bad_path_field_is_400():
    assert call({})[0] == 400
    assert call({"path": 5})[0] == 400
    assert call({"path": "a\x00b"})[0] == 400
    assert call({"path": "x" * 2000})[0] == 400


def test_oversized_file_is_refused_unread(tmp_path, monkeypatch):
    path = write(tmp_path, make_3mf(settings={"layer_height": "0.2"}))
    monkeypatch.setattr(routes_creative, "MAX_FILE_BYTES", 10)
    code, body = call({"path": path})
    assert code == 400 and "larger" in body["message"]


def test_non_zip_is_400_and_untouched(tmp_path):
    blob = b"this is not a zip archive"
    path = write(tmp_path, blob, "notes.3mf")
    code, body = call({"path": path})
    assert code == 400 and "not a readable 3MF" in body["message"]
    assert Path(path).read_bytes() == blob


def test_zip_without_model_is_400(tmp_path):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "hi")
    code, body = call({"path": write(tmp_path, buf.getvalue())})
    assert code == 400 and "no 3D model" in body["message"]


def test_original_bytes_and_mtime_unchanged_and_no_siblings(tmp_path):
    blob = make_3mf(settings={"mixed_filament_definitions": ROW})
    path = write(tmp_path, blob)
    before = Path(path).stat().st_mtime_ns
    call({"path": path})
    assert Path(path).read_bytes() == blob
    assert Path(path).stat().st_mtime_ns == before
    assert [p.name for p in tmp_path.iterdir()] == ["project.3mf"]


def test_copy_has_no_overclaims():
    text = (routes_creative.ADVISORY + routes_creative.EVIDENCE).lower()
    for banned in ("guarantee", "100%", "simultaneous", "ready", "coming soon"):
        assert banned not in text
