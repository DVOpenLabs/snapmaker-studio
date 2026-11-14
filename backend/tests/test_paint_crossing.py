"""Painting crosses into the target's dialect, or it is reported — never quietly.

Two things have to be true before Snapmaker Orca reads a facet's colour, and both
were measured against Orca 2.3.5 by handing it one file at a time and reading the
project it saved back:

* the attribute must be `paint_color`. The identical painting written as
  PrusaSlicer's `slic3rpe:mmu_segmentation` came back with nothing painted.
* the mesh must be in its own object file behind a component. The identical
  painting, in `paint_color`, left in the root model came back with nothing
  painted; moved behind a component it came back complete — eight facets, the
  same slots, the same areas.

The encoding itself is the same on both sides: the OrcaSlicer and PrusaSlicer
painted-cube fixtures carry byte-identical values for the same eight facets. So
crossing is a rename plus a move, and this file holds it to that — including the
control that shows Orca is reading the attribute rather than copying it: handed
a paint tree that cannot be decoded, Orca 2.3.5 rewrote it to an unpainted one.
"""
from __future__ import annotations

import json
import re
import tempfile
import zipfile
from pathlib import Path

import pytest

from snapstudio_core import multipart as MP, painted_color as PC
from snapstudio_core.container import ThreeMF
from snapstudio_core.convert import convert_to_u1
from snapstudio_core.errors import UnsoundOutput
from snapstudio_core.fidelity import audit

FIXTURES = Path(__file__).parent / "fixtures"
PAINTED_CUBE = FIXTURES / "painted" / "prusaslicer-2.9.6-painted-cube.3mf"
TWO_VOLUMES = FIXTURES / "prusa-semantics" / "H_two_volumes_different_slots_out.3mf"
MODIFIER = FIXTURES / "prusa-semantics" / "vt_ParameterModifier_out.3mf"
ORCA_AUTHORED = FIXTURES / "painted" / "snapmaker-orca-2.3.5-authored.3mf"
ROOT = "3D/3dmodel.model"
OBJECTS = "3D/Objects/object_1.model"
SETTINGS = "Metadata/model_settings.config"


def prepare(source: Path) -> str:
    return convert_to_u1(str(source), out_dir=tempfile.mkdtemp()).output_path


def read(path: str, member: str) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read(member).decode("utf-8")


def rewrite(source: str, target: Path, member: str, change) -> str:
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == member:
                data = change(data.decode("utf-8")).encode("utf-8")
            dst.writestr(item, data)
    return str(target)


def meaning(path: str) -> dict:
    result = PC.read_container(ThreeMF.open(path))
    return {"facets": result.get("painted_triangle_count"),
            "slots": result.get("slots_referenced"),
            "dialect": result.get("dialect")}


def row(path: str, prefix: str, source: Path = TWO_VOLUMES) -> dict:
    found = [r for r in audit(str(source), path)["rows"]
             if r["element"].startswith(prefix)]
    assert found, f"no row starting {prefix!r}"
    return found[0]


@pytest.fixture(scope="module")
def prepared() -> str:
    return prepare(TWO_VOLUMES)


# --- the crossing -------------------------------------------------------------

def test_the_copy_writes_the_targets_attribute(prepared):
    body = read(prepared, OBJECTS)
    assert body.count('paint_color="') == 8
    assert "mmu_segmentation" not in body, (
        "Snapmaker Orca reads `paint_color`; the source's name means nothing to it")


def test_the_values_themselves_are_unchanged(prepared):
    """A rename, not a re-encode. The two families share the encoding."""
    before = re.findall(r'slic3rpe:mmu_segmentation="([^"]*)"', read(str(TWO_VOLUMES), ROOT))
    after = re.findall(r'paint_color="([^"]*)"', read(prepared, OBJECTS))
    assert before == after


def test_the_painting_moves_out_of_the_root(prepared):
    """Measured: Orca does not read painting left in the project's root model."""
    assert read(prepared, ROOT).count("<mesh>") == 0
    assert 'paint_color="' not in read(prepared, ROOT)


def test_the_decoded_painting_is_the_same_painting(prepared):
    before, after = meaning(str(TWO_VOLUMES)), meaning(prepared)
    assert before["facets"] == after["facets"] == 8
    assert before["slots"] == after["slots"]
    assert before["dialect"] == "prusa" and after["dialect"] == "bambu"


def test_studio_invents_no_painting_version(prepared):
    """No project the Orca family wrote declares one, so neither does the copy.

    PrusaSlicer declares `slic3rpe:MmPaintingVersion`. Snapmaker Orca 2.3.5,
    OrcaSlicer 2.4.2 and BambuStudio all declare only `BambuStudio:3mfVersion`,
    and the copy opens correctly without a painting version of any kind.
    """
    for member in (ROOT, OBJECTS):
        assert "MmPaintingVersion" not in read(prepared, member)


def test_painting_already_in_the_targets_dialect_is_left_alone(tmp_path):
    # Preparing leaves a .orig backup beside its *source*, so the fixture is
    # copied out of the repository first. A test must not write into the tree it
    # is testing.
    import shutil

    source = tmp_path / ORCA_AUTHORED.name
    shutil.copy2(ORCA_AUTHORED, source)
    out = prepare(source)
    with zipfile.ZipFile(out) as z:
        body = "".join(z.read(n).decode("utf-8", "ignore")
                       for n in z.namelist() if n.endswith(".model"))
    assert 'paint_color="' in body
    assert "mmu_segmentation" not in body


# --- each part keeps its own -------------------------------------------------

def test_each_part_keeps_its_own_painting(prepared):
    body = read(prepared, OBJECTS)
    counts = []
    for object_id in ("1", "2"):
        block = re.search(rf'<object id="{object_id}".*?</object>', body, re.S).group(0)
        counts.append(block.count('paint_color="'))
    assert sum(counts) == 8 and all(counts), "colour must not pile onto one part"


def test_the_audit_compares_the_painting_part_by_part(prepared):
    assert row(prepared, "The painting on each part")["status"] == "preserved_exact"


# --- twelve ways painting can go wrong ---------------------------------------

def test_a_dropped_painted_facet_is_caught(prepared, tmp_path):
    broken = rewrite(prepared, tmp_path / "a.3mf", OBJECTS,
                     lambda t: t.replace(' paint_color="4"', "", 1))
    assert row(broken, "Painted colour")["status"] == "changed"


def test_a_changed_slot_is_caught(prepared, tmp_path):
    """Same facets, another filament on them."""
    broken = rewrite(prepared, tmp_path / "b.3mf", OBJECTS,
                     lambda t: t.replace('paint_color="4"', 'paint_color="8"'))
    assert row(broken, "Painted colour")["status"] == "changed"


def test_a_changed_patch_is_caught(prepared, tmp_path):
    """A subdivided facet repainted: the areas per slot move."""
    broken = rewrite(prepared, tmp_path / "c.3mf", OBJECTS,
                     lambda t: t.replace('paint_color="480C501C3"', 'paint_color="2C"'))
    assert row(broken, "Painted colour")["status"] == "changed"


def test_painting_moved_to_the_wrong_part_is_caught(prepared, tmp_path):
    """Every value still present, every one of them on the wrong facet.

    Comparing only the set of colours calls this preserved, which is why the
    audit compares each part's facets in order.
    """
    def move_the_colour(text: str) -> str:
        """Take the colour off the first part's facets and put it on the second.

        The geometry does not move and every colour value is still in the file;
        only the facets they sit on change.
        """
        first = re.search(r'<object id="1".*?</object>', text, re.S).group(0)
        second = re.search(r'<object id="2".*?</object>', text, re.S).group(0)
        values = re.findall(r'\s(?:paint_color)="[^"]*"', first)
        stripped = re.sub(r'\s(?:paint_color)="[^"]*"', "", first)
        painted = second
        for value in values:
            painted = painted.replace("/>", f"{value}/>", 1)
        return text.replace(first, stripped).replace(second, painted)

    broken = rewrite(prepared, tmp_path / "d.3mf", OBJECTS, move_the_colour)
    assert row(broken, "The painting on each part")["status"] == "changed"


def test_the_wrong_dialect_in_the_copy_is_named(prepared, tmp_path):
    """A copy carrying PrusaSlicer's name opens with nothing painted."""
    broken = rewrite(prepared, tmp_path / "e.3mf", OBJECTS,
                     lambda t: t.replace('paint_color="', 'slic3rpe:mmu_segmentation="'))
    reason = row(broken, "Painted colour")["reason"] or ""
    assert "no painting" in reason and "PrusaSlicer" in reason


def test_painting_left_in_the_root_is_named(tmp_path):
    """The attribute is right and the mesh is in the wrong place."""
    prepared_cube = prepare(PAINTED_CUBE)
    body = read(prepared_cube, OBJECTS)
    moved = tmp_path / "f.3mf"
    with zipfile.ZipFile(prepared_cube) as src, zipfile.ZipFile(moved, "w") as dst:
        for item in src.infolist():
            if item.filename == OBJECTS:
                continue
            data = src.read(item.filename)
            if item.filename == ROOT:
                mesh = re.search(r"<object id=\"1\".*?</object>", body, re.S).group(0)
                text = data.decode("utf-8").replace("<resources>",
                                                    "<resources>" + mesh, 1)
                data = text.encode("utf-8")
            dst.writestr(item, data)
    reason = row(str(moved), "Painted colour", source=PAINTED_CUBE)["reason"] or ""
    assert "root" in reason and "not read from there" in reason


def test_a_painting_version_the_target_never_writes_is_not_invented(prepared):
    """`BambuStudio:MmPaintingVersion` appears in no target-authored fixture."""
    for fixture in (ORCA_AUTHORED,
                    FIXTURES / "painted" / "orcaslicer-2.4.2-painted-cube.3mf",
                    FIXTURES / "painted" / "bambustudio-2.08.02.61-authored.3mf"):
        with zipfile.ZipFile(fixture) as z:
            body = "".join(z.read(n).decode("utf-8", "ignore")
                           for n in z.namelist() if n.endswith(".model"))
        assert "MmPaintingVersion" not in body, fixture.name
    assert "MmPaintingVersion" not in read(prepared, OBJECTS)


def test_a_paint_tree_that_cannot_be_decoded_is_reported(prepared, tmp_path):
    """Studio reads it as malformed rather than as a colour."""
    broken = rewrite(prepared, tmp_path / "g.3mf", OBJECTS,
                     lambda t: t.replace('paint_color="480C501C3"',
                                         'paint_color="ZZZZZZZZ"'))
    result = PC.read_container(ThreeMF.open(broken))
    assert result["available"]
    assert (result.get("malformed_triangle_count") or 0) >= 1 or \
        result["painted_triangle_count"] < 8


def test_a_slot_the_copy_does_not_declare_is_named(prepared, tmp_path):
    """Painting names slot 5; the project must declare five filaments."""
    with zipfile.ZipFile(prepared) as z:
        settings = json.loads(
            z.read("Metadata/project_settings.config").decode("utf-8"))
    assert len(settings["filament_colour"]) >= max(
        PC.read_container(ThreeMF.open(prepared))["slots_referenced"])


# --- painting and helper volumes ---------------------------------------------

def test_painting_on_a_helper_volume_is_not_promoted(tmp_path):
    """A modifier's facets can carry colour. Nothing proves what that means.

    The modifier crosses as a modifier and its facets cross with it, so whatever
    the source painted stays on the volume it was painted on. What Studio does
    not do is move that colour onto printable geometry, and it does not claim the
    target honours painting on a volume that prints nothing.
    """
    out = prepare(MODIFIER)
    body = read(out, OBJECTS)
    helper = re.search(r'<object id="2".*?</object>', body, re.S).group(0)
    solid = re.search(r'<object id="1".*?</object>', body, re.S).group(0)
    settings = read(out, SETTINGS)
    assert 'subtype="modifier_part"' in settings
    assert 'type="other"' in helper and 'type="model"' in solid
    # Whatever painting the source put on each volume is still on that volume.
    source_root = read(str(MODIFIER), ROOT)
    source_body = re.search(r"<object[^>]*>.*?</object>", source_root, re.S).group(0)
    _vertices, triangles = MP.read_mesh(source_body)
    painted = [bool(re.search(r'(?:paint_color|slic3rpe:mmu_segmentation)=', t))
               for t in triangles]
    assert helper.count('paint_color="') == sum(painted[6:])
    assert solid.count('paint_color="') == sum(painted[:6])


# --- Prepare refuses its own bad output --------------------------------------

def test_prepare_refuses_to_save_a_structure_it_cannot_vouch_for(monkeypatch, tmp_path):
    """The validator runs in the pipeline now, not only in the tests.

    A writer bug used to reach the user as a project Snapmaker Orca opens
    wrongly. Damaged here at the writer, the way a bug would damage it.
    """
    from snapstudio_core import stl_wrap

    original = MP.part_records

    def wrong(parts, name, slots, roles=None, ids=None):
        return original(parts, name, slots, roles, ids).replace('<part id="2"',
                                                                '<part id="9"')

    monkeypatch.setattr(stl_wrap.multipart if hasattr(stl_wrap, "multipart") else MP,
                        "part_records", wrong)
    monkeypatch.setattr(MP, "part_records", wrong)

    out_dir = tmp_path / "out"
    with pytest.raises(UnsoundOutput) as caught:
        convert_to_u1(str(TWO_VOLUMES), out_dir=str(out_dir))
    assert "do not match its component ids" in caught.value.details
    assert not list(out_dir.glob("*.3mf")), "an unsound copy must not be left behind"
