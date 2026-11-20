import hashlib
import io
import json
import zipfile

import pytest

from snapstudio_core.assemblies.importer import import_file
from snapstudio_core.assemblies.model import AssemblyInputError
from snapstudio_api import routes_assemblies


def archive(tmp_path, xml=None, count=2):
    path = tmp_path / "synthetic.3mf"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Metadata/project_settings.config", json.dumps({"filament_colour": ["#FF0000"] * count}))
        if xml is not None:
            z.writestr("Metadata/slice_info.config", xml)
    return path


def test_multiplate_import_keeps_slot_ids_and_unknown_values(tmp_path):
    path = archive(tmp_path, '<config><plate><filament id="1" used_g="12.5"/><filament id="2"/></plate><plate><filament id="2" used_g="2"/></plate></config>')
    before = path.read_bytes()
    report = import_file(str(path))
    tiles = report["assembly"]["tiles"]
    assert len(tiles) == 2
    assert tiles[0]["usage"] == {"slot:0": 12.5, "slot:1": None}
    assert tiles[1]["usage"] == {"slot:0": None, "slot:1": 2}
    assert tiles[0]["roles"] == {"Filament 1": "slot:0", "Filament 2": "slot:1"}
    assert report["sha256"] == hashlib.sha256(before).hexdigest()
    assert path.read_bytes() == before
    assert str(tmp_path) not in json.dumps(report)


def test_unsliced_project_does_not_invent_grams(tmp_path):
    report = import_file(str(archive(tmp_path)))
    assert all(g is None for g in report["assembly"]["tiles"][0]["usage"].values())
    assert "unknown" in " ".join(report["notes"])


def test_gcode_footer_uses_existing_reader(tmp_path):
    path = tmp_path / "synthetic.gcode"
    path.write_text("G28\nG1 X1\n; filament used [g] = 12, 3\n", encoding="utf-8")
    report = import_file(str(path))
    assert report["assembly"]["tiles"][0]["usage"] == {"slot:0": 12.0, "slot:1": 3.0}


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16-le", "utf-16-be"])
def test_entity_documents_are_refused_in_every_encoding(tmp_path, encoding):
    raw = '<!DOCTYPE config [<!ENTITY grams "99">]><config><plate><filament id="1" used_g="&grams;"/></plate></config>'.encode(encoding)
    with pytest.raises(AssemblyInputError):
        import_file(str(archive(tmp_path, raw)))


@pytest.mark.parametrize("usage", ['<filament id="1" used_g="1"/><filament id="1" used_g="2"/>', '<filament id="0" used_g="2"/>'])
def test_invalid_or_duplicate_filament_ids_are_refused(tmp_path, usage):
    with pytest.raises(AssemblyInputError):
        import_file(str(archive(tmp_path, f"<config><plate>{usage}</plate></config>")))


def test_routes_import_evaluate_save_reopen(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    path = archive(tmp_path, '<config><plate><filament id="1" used_g="3"/></plate></config>', count=1)
    document = routes_assemblies.import_file({"path": str(path)})[1]["assembly"]
    document["bindings"] = {"Filament 1": {"provider_instance_id": "synthetic", "provider_spool_id": "one"}}
    code, response = routes_assemblies.evaluate({"assembly": document, "supply": []})
    assert code == 200 and response["report"]["verdict"] == "unknown"
    saved = routes_assemblies.save({"assembly": document})[1]
    reopened = routes_assemblies.get({"id": saved["id"]})[1]
    assert reopened["assembly"]["tiles"][0]["usage"]["slot:0"] == 3


def test_model_reference_has_unknown_usage(tmp_path):
    path = tmp_path / "synthetic.stl"
    path.write_bytes(b"solid synthetic\nendsolid synthetic\n")
    assert import_file(str(path))["assembly"]["tiles"][0]["usage"] == {"slot:0": None}


def test_large_metadata_refused_before_decompression(tmp_path):
    path = tmp_path / "large.3mf"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Metadata/slice_info.config", b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(AssemblyInputError):
        import_file(str(path))

def test_import_keeps_source_plate_identifier(tmp_path):
    path = archive(tmp_path, '<config><plate><metadata key="index" value="17"/><filament id="1" used_g="1"/></plate></config>', count=1)
    assert import_file(str(path))["assembly"]["tiles"][0]["plate"] == "17"

def test_advanced_json_normalizes_existing_gcode_fact_contract_without_saving(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path))
    code, body = routes_assemblies.normalize({"assembly": {"name": "Synthetic legacy", "tiles": [{"tile_id": "one", "name": "One", "gcode_facts": {"available": True, "slots": [{"tool": 0, "grams": 2}]}}]}})
    assert code == 200 and body["assembly"]["tiles"][0]["usage"] == {"slot:0": 2}
    assert not list(tmp_path.rglob("*.db"))


@pytest.mark.parametrize('vector, expected', [('bad, 3', {'slot:0':None,'slot:1':3.0}), (', 3', {'slot:0':None,'slot:1':3.0}), ('3,', {'slot:0':3.0,'slot:1':None}), ('', {'slot:0':None}), ('NaN, 3', {'slot:0':None,'slot:1':3.0})])
def test_gcode_gram_vector_never_compacts_bad_or_blank_positions(tmp_path,vector,expected):
    path=tmp_path/'synthetic.gcode';path.write_text('G1 X1\n; filament used [g] = '+vector+'\n',encoding='utf-8')
    assert import_file(str(path))['assembly']['tiles'][0]['usage']==expected

def test_duplicate_plate_identity_is_refused(tmp_path):
    path=archive(tmp_path,'<config><plate><metadata key="index" value="7"/></plate><plate><metadata key="index" value="7"/></plate></config>')
    with pytest.raises(AssemblyInputError):import_file(str(path))

def test_declared_archive_and_role_caps_are_refusals(tmp_path):
    with pytest.raises(AssemblyInputError):import_file(str(archive(tmp_path,count=33)))
    p=tmp_path/'many.3mf'
    with zipfile.ZipFile(p,'w') as z:
        for n in range(2049):z.writestr(f'part{n}',b'')
    with pytest.raises(AssemblyInputError):import_file(str(p))
