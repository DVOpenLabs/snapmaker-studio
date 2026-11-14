"""A helper volume crosses as a helper volume, and the ways that can go wrong.

PrusaSlicer gives a volume one of five roles. Four of them describe something the
slicer uses but never prints: a parameter modifier, a negative volume, a support
enforcer and a support blocker. Studio used to carry none of them — the object
crossed whole, so a modifier's facets arrived inside the printable mesh and were
printed as solid plastic.

Each of the four now crosses as its own part with the word Snapmaker Orca uses.
Those four words were measured, not matched by name: Orca was handed a project
claiming each one, and the project Orca saved back was read. A made-up word came
back rewritten to `normal_part`, so surviving means Orca recognises the word.
Sliced, each of the four contributed nothing to the plate while a `normal_part`
in the same position contributed a second cube.

The second half of this file damages a carried modifier eight ways and requires
the validator or the audit to catch each one. A `<part subtype="modifier_part">`
over geometry the file describes as a model is not a modifier; it is a claim.
"""
from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path

import pytest

from snapstudio_core import assignments as A, multipart as MP
from snapstudio_core.container import ThreeMF
from snapstudio_core.convert import convert_to_u1
from snapstudio_core.fidelity import audit

FIXTURES = Path(__file__).parent / "fixtures" / "prusa-semantics"
MODIFIER_SOURCE = FIXTURES / "vt_ParameterModifier_out.3mf"
PRUSA_CONFIG = "Metadata/Slic3r_PE_model.config"
ROOT = "3D/3dmodel.model"
OBJECTS = "3D/Objects/object_1.model"
SETTINGS = "Metadata/model_settings.config"

#: PrusaSlicer's word for each role, and Studio's own name for it. Every one of
#: these five round-trips through PrusaSlicer 2.9.6 unchanged.
PRUSA_WORDS = {
    "ParameterModifier": "modifier",
    "NegativeVolume": "negative",
    "SupportEnforcer": "support_enforcer",
    "SupportBlocker": "support_blocker",
}


def rewrite(source: Path, target: Path, member: str, change) -> Path:
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == member:
                data = change(data.decode("utf-8")).encode("utf-8")
            dst.writestr(item, data)
    return target


def source_with_role(word: str, tmp_path: Path) -> Path:
    """The genuine two-volume modifier fixture, with the role word swapped."""
    return rewrite(MODIFIER_SOURCE, tmp_path / f"prusa_{word}.3mf", PRUSA_CONFIG,
                   lambda text: text.replace('value="ParameterModifier"',
                                             f'value="{word}"'))


def prepare(source: Path) -> str:
    return convert_to_u1(str(source), out_dir=tempfile.mkdtemp()).output_path


def read(path: str, member: str) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read(member).decode("utf-8")


@pytest.fixture(scope="module")
def prepared_modifier() -> str:
    return prepare(MODIFIER_SOURCE)


# --- the role crosses ---------------------------------------------------------

@pytest.mark.parametrize("word,role", sorted(PRUSA_WORDS.items()))
def test_every_proven_role_crosses_as_its_own_part(word, role, tmp_path):
    out = prepare(source_with_role(word, tmp_path))
    settings = read(out, SETTINGS)
    assert re.findall(r'<part id="\d+" subtype="([^"]+)"', settings) == [
        "normal_part", MP.TARGET_ROLES[role]]


@pytest.mark.parametrize("word,role", sorted(PRUSA_WORDS.items()))
def test_a_helper_volumes_geometry_is_not_a_model(word, role, tmp_path):
    """The geometry says what it is for, not only the metadata over it."""
    out = prepare(source_with_role(word, tmp_path))
    objects = read(out, OBJECTS)
    assert re.findall(r'<object id="(\d+)"[^>]*type="([^"]*)"', objects) == [
        ("1", "model"), ("2", "other")]


def test_the_modifier_leaves_the_printable_mesh(prepared_modifier):
    """The whole point. Its facets are no longer inside the solid.

    Before this, the object crossed whole: a modifier's twelve facets sat in the
    printable mesh and Snapmaker Orca printed them.
    """
    assert read(prepared_modifier, ROOT).count("<triangle ") == 0
    body = read(prepared_modifier, OBJECTS)
    assert body.count("<triangle ") == 12
    solid = re.search(r'<object id="1".*?</object>', body, re.S).group(0)
    helper = re.search(r'<object id="2".*?</object>', body, re.S).group(0)
    assert solid.count("<triangle ") == helper.count("<triangle ") == 6
    assert 'type="model"' in solid and 'type="other"' in helper


def test_a_helper_part_states_no_filament(prepared_modifier):
    """It prints nothing, so a material for it would be a choice about nothing.

    A genuine Snapmaker Orca project states none on any of its eight modifier
    parts either.
    """
    settings = read(prepared_modifier, SETTINGS)
    block = re.search(r'<part id="2".*?</part>', settings, re.S).group(0)
    assert "extruder" not in block
    assert '<metadata key="extruder" value="0"/>' in settings, "the object still states its own"


def test_the_parts_recombine_into_the_source_geometry(prepared_modifier):
    """Splitting off the modifier moved facets; it did not change any."""
    source_root = read(str(MODIFIER_SOURCE), ROOT)
    body = re.search(r"<object[^>]*>.*?</object>", source_root, re.S).group(0)
    vertices, triangles = MP.read_mesh(body)
    whole = MP.geometry_digest(vertices, triangles)

    objects = read(prepared_modifier, OBJECTS)
    combined_vertices: list[str] = []
    combined_triangles: list[str] = []
    for object_id in ("1", "2"):
        block = re.search(rf'<object id="{object_id}".*?</object>', objects, re.S).group(0)
        part_vertices, part_triangles = MP.read_mesh(block)
        offset = len(combined_vertices)
        combined_vertices.extend(part_vertices)
        combined_triangles.extend(
            re.sub(r'\bv([123])="(\d+)"',
                   lambda m: f'v{m.group(1)}="{int(m.group(2)) + offset}"', tag)
            for tag in part_triangles)
    assert MP.geometry_digest(combined_vertices, combined_triangles) == whole


def test_the_validator_passes_a_carried_modifier(prepared_modifier):
    result = MP.validate_archive(ThreeMF.open(prepared_modifier))
    assert result["multipart"] is True and result["parts"] == 2
    assert result["ok"] and result["problems"] == []


def test_the_audit_reports_the_role_as_kept(prepared_modifier):
    rows = audit(str(MODIFIER_SOURCE), prepared_modifier)["rows"]
    role = [r for r in rows if r["element"].startswith("Part roles")]
    assert role and role[0]["status"] == "preserved_exact"
    assert "modifier" in role[0]["detail"]


def test_the_audit_compares_each_parts_shape(prepared_modifier):
    rows = audit(str(MODIFIER_SOURCE), prepared_modifier)["rows"]
    shape = [r for r in rows if r["element"].startswith("The shape of each part")]
    assert shape and shape[0]["status"] == "preserved_exact"


def test_the_audit_no_longer_loses_sight_of_the_geometry(prepared_modifier):
    """The mesh moved into its own file. That is not the same as vanishing.

    Counting only the root model saw every facet disappear and called an intact
    copy unverified.
    """
    rows = audit(str(MODIFIER_SOURCE), prepared_modifier)["rows"]
    geometry = [r for r in rows if r["element"].startswith("Model geometry")]
    assert geometry and geometry[0]["status"] == "preserved_semantic"
    assert "one mesh per part" in geometry[0]["detail"]


# --- eight ways a carried modifier can be wrong -------------------------------

def problems(path: str) -> list[str]:
    return MP.validate_archive(ThreeMF.open(path))["problems"]


def damaged(prepared: str, tmp_path: Path, member: str, change) -> str:
    return str(rewrite(Path(prepared), tmp_path / "damaged.3mf", member, change))


def role_status(prepared: str) -> tuple[str, str]:
    result = A.compare(A.read(ThreeMF.open(str(MODIFIER_SOURCE))),
                       A.read(ThreeMF.open(prepared)))
    row = [r for r in result["semantics"] if r["kind"] == "volume_role"][0]
    return row["status"], row["detail"]


def test_a_modifier_relabelled_as_a_normal_part_is_caught(prepared_modifier, tmp_path):
    """The corruption that matters most: it would be printed as solid."""
    broken = damaged(prepared_modifier, tmp_path, SETTINGS,
                     lambda t: t.replace('subtype="modifier_part"', 'subtype="normal_part"'))
    assert role_status(broken)[0] == A.UNSUPPORTED
    assert any("typed 'other'" in p for p in problems(broken))


def test_a_modifier_over_geometry_typed_as_a_model_is_caught(prepared_modifier, tmp_path):
    """Modifier metadata over printable geometry is a claim, not a modifier."""
    broken = damaged(prepared_modifier, tmp_path, OBJECTS,
                     lambda t: t.replace('<object id="2" type="other">',
                                         '<object id="2" type="model">'))
    assert any("modifier_part" in p and "typed 'model'" in p for p in problems(broken))


def test_changed_modifier_geometry_is_caught(prepared_modifier, tmp_path):
    broken = damaged(prepared_modifier, tmp_path, OBJECTS, lambda t: re.sub(
        r'(<object id="2".*?<vertex x=")10(")', r"\g<1>11\g<2>", t, count=1, flags=re.S))
    rows = audit(str(MODIFIER_SOURCE), broken)["rows"]
    shape = [r for r in rows if r["element"].startswith("The shape of each part")]
    assert shape and shape[0]["status"] == "changed"


def test_a_dropped_modifier_is_caught(prepared_modifier, tmp_path):
    broken = damaged(prepared_modifier, tmp_path, SETTINGS,
                     lambda t: re.sub(r'<part id="2".*?</part>\s*', "", t, flags=re.S))
    assert any("lists 1 part(s) and has 2 component(s)" in p for p in problems(broken))
    assert role_status(broken)[0] == A.UNSUPPORTED


def test_a_duplicated_modifier_is_caught(prepared_modifier, tmp_path):
    broken = damaged(prepared_modifier, tmp_path, SETTINGS, lambda t: t.replace(
        "</object>", re.search(r'<part id="2".*?</part>', t, re.S).group(0) + "</object>"))
    assert any("lists 3 part(s) and has 2 component(s)" in p for p in problems(broken))


def test_swapped_roles_are_caught(prepared_modifier, tmp_path):
    """Both roles are still in the file. They are on the wrong parts.

    Asking only whether the role appears somewhere passes this file — and this
    file prints the modifier and drops the solid.
    """
    broken = damaged(prepared_modifier, tmp_path, SETTINGS, lambda t: t.replace(
        '<part id="1" subtype="normal_part">', '<part id="1" subtype="modifier_part">'
    ).replace('<part id="2" subtype="modifier_part">', '<part id="2" subtype="normal_part">'))
    status, detail = role_status(broken)
    assert status == A.CHANGED and "different part" in detail


def test_a_part_belonging_to_no_object_is_caught(prepared_modifier, tmp_path):
    """A modifier attached to something the geometry does not describe."""
    broken = damaged(prepared_modifier, tmp_path, SETTINGS,
                     lambda t: t.replace('<part id="2"', '<part id="7"'))
    assert any("do not match its component ids" in p for p in problems(broken))


def test_a_role_word_the_target_does_not_know_is_caught(prepared_modifier, tmp_path):
    """Orca rewrites a word it does not know to `normal_part` and prints it."""
    broken = damaged(prepared_modifier, tmp_path, SETTINGS,
                     lambda t: t.replace('subtype="modifier_part"', 'subtype="helper_thing"'))
    assert any("not one Studio has proven" in p for p in problems(broken))


# --- the writer refuses rather than guesses -----------------------------------

def test_the_writer_will_not_invent_a_role():
    """No silent fallback to `normal_part`, anywhere in the writer."""
    parts = [{"index": 0, "vertices": [], "triangles": []}]
    with pytest.raises(MP.Unsplittable):
        MP.part_records(parts, "thing", [None], ["something_else"])
    with pytest.raises(MP.Unsplittable):
        MP.objects_model_xml(parts, roles=["something_else"])
    with pytest.raises(MP.Unsplittable):
        MP.object_type_for("something_else")
