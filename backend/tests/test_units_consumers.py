"""The 3MF `unit` header table (snapstudio_core.units), as the scene contract reads it.

The scene contract (scene.py) normalises a part's declared unit to millimetres through this table. The size-dependent
verdicts elsewhere (bed fit, readiness, success estimate, first-layer footprint, placement) do NOT consume it: on main
they stay behind `geometry_basis`, which reports "not checked" for a non-millimetre project rather than converting. A
shared physical-geometry normaliser for those consumers is a separate, later change.
"""
from snapstudio_core import units


def test_table_has_the_six_units_and_reads_the_header():
    assert units.MM_PER_UNIT == {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4,
                                 "foot": 304.8, "meter": 1000.0}
    assert units.unit_of(b'<?xml version="1.0"?><model unit="inch" xmlns="x">') == ("inch", 25.4)
    assert units.unit_of(b"<model xmlns='x' unit='foot'/>") == ("foot", 304.8)
    assert units.unit_of(b"<model xmlns='x'/>") == ("millimeter", 1.0)          # absent attribute = default
    assert units.unit_of(b'<model unit="yard">') == ("yard", None)               # unknown is surfaced, not guessed
    assert units.mm_per_unit(b'<model unit="yard">') == 1.0                      # legacy readers keep treating it as mm
    info = units.read_unit(b'<model_settings unit="inch">')                       # not a <model> element
    assert (info.recognized, info.declared, info.factor) == (False, False, 1.0)   # unreadable is not "absent"
    assert units.read_unit(b"this is not xml").recognized is False
    assert units.read_unit(b"").recognized is False and units.read_unit(b"<model/>").recognized is True
    assert units.scale_translation([1, 0, 0, 0, 1, 0, 0, 0, 1, 2, 3, 4], 25.4)[9:] == [2 * 25.4, 3 * 25.4, 4 * 25.4]
    same = [1, 0, 0, 0, 1, 0, 0, 0, 1, 2, 3, 4]
    assert units.scale_translation(same, 1.0) is same
