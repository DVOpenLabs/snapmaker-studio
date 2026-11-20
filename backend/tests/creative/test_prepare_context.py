import io
import json
import zipfile

import pytest

from snapstudio_api import ext_routes, routes_creative, service
from tests.fixtures.creative.zip_factory import make_kromacut
from tests.integration.setup_helpers import project_cfg, topology
from tests.test_project_materials import profiles, _shared


def project(tmp_path, settings=None):
    path = tmp_path / "synthetic-kromacut.3mf"
    source = zipfile.ZipFile(io.BytesIO(make_kromacut()))
    with source, zipfile.ZipFile(path, "w") as target:
        for entry in source.infolist():
            if entry.filename != "Metadata/project_settings.config":
                target.writestr(entry, source.read(entry))
        target.writestr("Metadata/project_settings.config", json.dumps(settings or project_cfg(8)))
    return path


def call(body):
    handler = type("H", (), {"_send": lambda self, code, body: self.sent.append((code, body))})()
    handler.sent = []
    ext_routes.dispatch(handler, "/creative/prepare", body)
    return handler.sent[0]


def test_real_creative_route_preserves_eight_slots_with_setup_and_four_without(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    source = project(tmp_path)
    original = source.read_bytes()
    code, selected = call({"path": str(source), "topology": topology().to_dict()})
    assert code == 200 and selected["prepared"], selected
    with zipfile.ZipFile(selected["output"]["local_path"]) as z:
        settings = json.loads(z.read("Metadata/project_settings.config"))
    assert len(settings["nozzle_temperature"]) == 8
    assert selected["prepare"]["settings_summary"]["setup"]["applied"] is True
    _, stock = call({"path": str(source)})
    with zipfile.ZipFile(stock["output"]["local_path"]) as z:
        stock_settings = json.loads(z.read("Metadata/project_settings.config"))
    assert len(stock_settings["nozzle_temperature"]) == 4
    assert source.read_bytes() == original


def test_materials_and_topology_reach_the_existing_service_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    source = project(tmp_path)
    chosen = {"selections": [{"slot": 0, "colour": "#123456"}]}
    setup = topology().to_dict()
    real = service.convert
    seen = []
    def convert(*args, **kwargs):
        seen.append((args, kwargs))
        return real(*args, **kwargs)
    monkeypatch.setattr(service, "convert", convert)
    code, result = call({"path": str(source), "materials": chosen, "topology": setup})
    assert code == 200 and result["prepared"], result
    assert seen[0][0][4] == chosen and seen[0][1]["topology"] == setup
    with zipfile.ZipFile(result["output"]["local_path"]) as z:
        assert json.loads(z.read("Metadata/project_settings.config"))["filament_colour"][0] == "#123456"


def test_invalid_setup_is_refused_without_a_copy(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(data))
    source = project(tmp_path)
    code, result = call({"path": str(source), "topology": {"schema_version": "bad"}})
    assert code == 200 and result["prepared"] is False
    assert result["setup"]["state"] == "invalid"
    assert not list((data / "creative-prepared").glob("*.3mf"))


@pytest.mark.parametrize("context", [{"topology": []}, {"materials": []}, {"materials": {"selections": "bad"}}])
def test_malformed_context_is_400(tmp_path, monkeypatch, context):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    code, _ = call({"path": str(project(tmp_path)), **context})
    assert code == 400


def test_real_material_guard_refusal_has_no_invalid_setup_claim(tmp_path,monkeypatch,profiles):
    data=tmp_path/'data';monkeypatch.setenv('SNAPSTUDIO_DATA_DIR',str(data));monkeypatch.setenv('SNAPSTUDIO_ORCA_PROFILES_DIR',str(profiles))
    source=project(tmp_path,_shared());before=source.read_bytes()
    code,result=call({'path':str(source),'topology':topology(slots=3).to_dict(),'materials':{'selections':[{'slot':2,'preset':'Generic PETG @U1'}]}})
    assert code==200 and result['prepared'] is False
    assert result['refusal']['kind']=='prepare_blocked'
    assert result['setup'] is None
    assert not list((data/'creative-prepared').glob('*.3mf')) and source.read_bytes()==before

def test_real_material_value_error_does_not_blame_the_ready_setup(tmp_path,monkeypatch,profiles):
    monkeypatch.setenv('SNAPSTUDIO_DATA_DIR',str(tmp_path/'data'));monkeypatch.setenv('SNAPSTUDIO_ORCA_PROFILES_DIR',str(profiles))
    code,result=call({'path':str(project(tmp_path)),'topology':topology().to_dict(),'materials':{'selections':[{'slot':0,'preset':'Unproven synthetic preset'}]}})
    assert code==200 and result['prepared'] is False
    assert result['refusal']['kind']=='prepare_refused' and result.get('setup') is None
