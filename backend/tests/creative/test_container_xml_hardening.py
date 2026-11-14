"""The 3MF model XML guard refuses entity/DTD content in every encoding, not only plain UTF-8.

Regression for the UTF-16 bypass found in the #140 aggregate review: a byte-substring check misses NUL-interleaved
DOCTYPE/ENTITY, and expat auto-detects UTF-16 and expands the entities.
"""
from __future__ import annotations

import pytest

from snapstudio_core.creative.container import ContainerError, read_3mf
from fixtures.creative.zip_factory import make_3mf, model_xml

BOMB = (
    '<?xml version="1.0"?><!DOCTYPE model [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
    '<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" unit="millimeter"><resources/>&b;<build/></model>'
)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16-le", "utf-16-be", "utf-16", "utf-32-le", "utf-32-be", "utf-32"])
def test_entity_documents_are_refused_in_every_encoding(encoding):
    with pytest.raises(ContainerError) as info:
        read_3mf(make_3mf(model=BOMB.encode(encoding)))
    assert info.value.args[0] in ("unsafe_xml", "bad_xml")


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be", "utf-32-le"])
def test_a_bom_less_wide_encoding_is_unsafe_not_parsed(encoding):
    plain = model_xml().decode("utf-8") if isinstance(model_xml(), bytes) else model_xml()
    with pytest.raises(ContainerError) as info:
        read_3mf(make_3mf(model=plain.encode(encoding)))
    assert info.value.args[0] == "unsafe_xml"


def test_lowercase_doctype_is_refused():
    lowered = BOMB.replace("DOCTYPE", "doctype").replace("ENTITY", "entity")
    with pytest.raises(ContainerError) as info:
        read_3mf(make_3mf(model=lowered.encode("utf-8")))
    assert info.value.args[0] == "unsafe_xml"


def test_a_plain_utf8_model_with_a_bom_is_still_read():
    plain = model_xml()
    raw = plain if isinstance(plain, bytes) else plain.encode("utf-8")
    assert read_3mf(make_3mf(model=bytes([0xEF, 0xBB, 0xBF]) + raw)) is not None


# ---- every other part of the archive goes through the same guard (OP144-1) -------------------------------

from pathlib import Path

from snapstudio_core.creative import generators


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16-le", "utf-16-be", "utf-16", "utf-32-le", "utf-32-be", "utf-32"])
def test_generator_part_parser_refuses_entity_documents_in_every_encoding(encoding):
    with pytest.raises(ContainerError) as info:
        generators._xml(BOMB.encode(encoding))
    assert info.value.args[0] in ("unsafe_xml", "bad_xml")


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_generator_part_parser_refuses_bom_less_wide_text(encoding):
    with pytest.raises(ContainerError) as info:
        generators._xml("<a xmlns='x'/>".encode(encoding))
    assert info.value.args[0] == "unsafe_xml"


def test_no_creative_module_parses_xml_outside_the_guarded_helper():
    folder = Path(generators.__file__).parent
    offenders = []
    for path in sorted(folder.glob("*.py")):
        if path.name == "container.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "ElementTree.fromstring" in text or "ET.fromstring" in text or "minidom" in text or "iterparse" in text:
            offenders.append(path.name)
    assert not offenders, f"parse XML through container.parse_xml: {offenders}"
