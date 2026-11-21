import json, zipfile
from snapstudio_core.variants.comparison import _read_3mf, _read_gcode, MAX_GCODE_SCAN

def archive(tmp_path, text):
    p=tmp_path/"sliced.3mf"
    with zipfile.ZipFile(p,"w") as z:
        z.writestr("Metadata/project_settings.config",json.dumps({"layer_height":"0.2"}))
        z.writestr("Metadata/slice_info.config",text)
    return p

def test_xml_slice_info_aggregates_plates_by_filament_id(tmp_path):
    p=archive(tmp_path,'<config><plate><metadata key="prediction" value="60"/><filament id="1" used_g="12.5"/><filament id="2" used_g="1.5"/></plate><plate><metadata key="prediction" value="120"/><filament id="1" used_g="2.5"/></plate></config>')
    r=_read_3mf(p)
    assert r["grams_by_tool"] == [15.0,1.5]
    assert r["time_seconds"] == 180

def test_unknown_plate_usage_does_not_become_a_complete_total(tmp_path):
    p=archive(tmp_path,'<config><plate><filament id="1" used_g="2"/></plate><plate><filament id="1"/></plate></config>')
    assert _read_3mf(p)["grams_by_tool"] is None

def test_bad_xml_does_not_crash_or_expand_entities(tmp_path):
    for text in ['<config><plate>', '<!DOCTYPE x [<!ENTITY a "boom">]><config>&a;</config>']:
        r=_read_3mf(archive(tmp_path,text))
        assert r["grams_by_tool"] is None and r["time_seconds"] is None

def test_metadata_at_end_of_gcode_is_read(tmp_path):
    p=tmp_path/"sliced.gcode"
    p.write_text("G28\nT0\nG1 X1\n; filament used [g] = 12.5, 1.5\n; estimated printing time (normal mode) = 1h 1m\n",encoding="utf-8")
    r=_read_gcode(p)
    assert r["grams_by_tool"] == [12.5,1.5]
    assert r["time_seconds"] == 3660

def test_tail_summary_does_not_make_truncated_body_tool_counts_known(tmp_path):
    p=tmp_path/"large.gcode"
    with p.open("wb") as f:
        f.write(b"T0\n")
        f.write(b"; filler\n"*(MAX_GCODE_SCAN//8+1))
        f.write(b"; filament used [g] = 4.5\n; estimated printing time (normal mode) = 2m\n")
    r=_read_gcode(p)
    assert r["grams_by_tool"] == [4.5]
    assert r["time_seconds"] == 120
    assert r["scan"]["tool_changes"] is None

def test_utf16_entity_document_is_not_evaluated(tmp_path):
    raw = '<!DOCTYPE config [<!ENTITY a "expanded">]><config><plate><metadata key="prediction" value="1"/></plate></config>'.encode("utf-16")
    result = _read_3mf(archive(tmp_path, raw))
    assert result["time_seconds"] is None

def test_incomplete_time_and_duplicate_filaments_stay_unknown(tmp_path):
    result = _read_3mf(archive(tmp_path, '<config><plate><metadata key="prediction" value="60"/><filament id="1" used_g="1"/><filament id="1" used_g="2"/></plate><plate><filament id="1" used_g="2"/></plate></config>'))
    assert result["grams_by_tool"] is None
    assert result["time_seconds"] is None

def test_bomless_utf16_entity_documents_are_not_evaluated(tmp_path):
    xml = '<!DOCTYPE config [<!ENTITY seconds "100">]><config><plate><metadata key="prediction" value="&seconds;"/></plate></config>'
    for encoding in ("utf-16-le", "utf-16-be"):
        assert _read_3mf(archive(tmp_path, xml.encode(encoding)))["time_seconds"] is None

def test_large_footer_keeps_settings_and_prefers_normal_time(tmp_path):
    p = tmp_path / "large-footer.gcode"
    with p.open("wb") as f:
        f.write(b"; filament used [g] = 2\n; estimated printing time (normal mode) = 1m\nT0\n")
        f.write(b"; filler\n" * (MAX_GCODE_SCAN // 8 + 1))
        f.write(b"; layer_height = 0.16\n; filament used [g] = bad\n; estimated printing time (silent mode) = 9m\n")
    result = _read_gcode(p)
    assert result["settings"]["layer_height"] == "0.16"
    assert result["grams_by_tool"] == [2]
    assert result["time_seconds"] == 60
