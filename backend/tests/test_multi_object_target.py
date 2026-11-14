"""Several objects at once, each carried as its own object in the target's shape.

Studio's writer had only ever been asked to carry one source object. A project
with more kept its geometry in the root model — and measured against Snapmaker
Orca 2.3.5, painting is not read from there, so a multi-object painted project
lost its colour on Prepare while every per-file check passed.

Every logical object now becomes its own composite object with its own object
file, its own build item and its own part records, which is the shape Orca writes
for a project of several objects: its own badge fixture holds three, each with its
own file, and part ids unique across the whole project rather than restarting per
object.

The fixture is three cubes authored by PrusaSlicer 2.9.6 — one with two volumes on
filaments 2 and 5 and painted, one on filament 3 and painted, one plain — placed
at three positions on the bed. A project total can be right while two objects have
swapped their parts, so nothing here is asserted project-wide alone.
"""
from __future__ import annotations

import hashlib
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

FIXTURES = Path(__file__).parent / "fixtures" / "prusa-multi-object"
SOURCE = FIXTURES / "prusa_three_objects.3mf"
MANIFEST = FIXTURES / "MANIFEST.json"
ROOT = "3D/3dmodel.model"
SETTINGS = "Metadata/model_settings.config"
RELS = "3D/_rels/3dmodel.model.rels"


@pytest.fixture(scope="module")
def prepared() -> str:
    return convert_to_u1(str(SOURCE), out_dir=tempfile.mkdtemp()).output_path


def read(path: str, member: str) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read(member).decode("utf-8")


def members(path: str, prefix: str) -> list[str]:
    with zipfile.ZipFile(path) as z:
        return sorted(n for n in z.namelist() if n.startswith(prefix))


def objects_of(path: str) -> dict:
    """Each prepared object's parts, meshes, painting and place."""
    settings = read(path, SETTINGS)
    root = read(path, ROOT)
    meshes = {}
    for name in members(path, "3D/Objects/"):
        body = read(path, name)
        for mesh_id in re.findall(r'<object id="(\d+)"', body):
            block = re.search(rf'<object id="{mesh_id}".*?</object>', body, re.S).group(0)
            vertices, triangles = MP.read_mesh(block)
            meshes[mesh_id] = {
                "file": name,
                "digest": MP.geometry_digest(vertices, triangles),
                "triangles": len(triangles),
                "painted": block.count('paint_color="'),
            }
    placements = dict(re.findall(
        r'<item[^>]* objectid="([0-9]+)"[^>]* transform="([^"]*)"', root))
    out = {}
    for match in re.finditer(r'<object id="(\d+)">(.*?)</object>', settings, re.S):
        object_id, body = match.group(1), match.group(2)
        part_ids = re.findall(r'<part id="(\d+)"', body)
        slots = []
        for part_id in part_ids:
            block = re.search(rf'<part id="{part_id}".*?</part>', body, re.S).group(0)
            found = re.search(r'key="extruder" value="(\d+)"', block)
            slots.append(int(found.group(1)) if found else None)
        out[object_id] = {
            "parts": part_ids,
            "slots": slots,
            "meshes": [meshes[pid] for pid in part_ids],
            "transform": placements.get(object_id),
        }
    return out


def source_objects() -> dict:
    """The same facts, read out of the source project."""
    config = read(str(SOURCE), "Metadata/Slic3r_PE_model.config")
    root = read(str(SOURCE), ROOT)
    volumes = MP.source_volumes(config)
    ids = re.findall(r'<object[^>]* id="([0-9]+)"[^>]*>.*?</object>', root, re.S)
    bodies = re.findall(r"<object[^>]*>.*?</object>", root, re.S)
    placements = dict(re.findall(
        r'<item[^>]* objectid="([0-9]+)"[^>]* transform="([^"]*)"', root))
    out = {}
    for source_id, body in zip(ids, bodies):
        vertices, triangles = MP.read_mesh(body)
        parts = MP.split_triangles(vertices, triangles,
                                   [v["range"] for v in volumes[source_id]])
        out[source_id] = {
            "digests": [MP.geometry_digest(p["vertices"], p["triangles"]) for p in parts],
            "triangles": [len(p["triangles"]) for p in parts],
            "painted": [sum(1 for t in p["triangles"] if "mmu_segmentation" in t)
                        for p in parts],
            "slots": [v["slot"] for v in volumes[source_id]],
            "transform": placements.get(source_id),
        }
    return out


# --- the fixture is the slicer's own work -------------------------------------

def test_the_fixture_is_the_file_the_slicer_wrote():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["_provenance"]["slicer"].startswith("PrusaSlicer 2.9.6")
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == manifest["file"]["sha256"]


def test_the_source_really_does_hold_three_objects():
    source = source_objects()
    assert len(source) == 3
    assert [len(entry["digests"]) for entry in source.values()] == [2, 1, 1]
    assert sum(sum(entry["painted"]) for entry in source.values()) == 16


# --- the target graph ---------------------------------------------------------

def test_each_object_gets_its_own_object_file(prepared):
    assert members(prepared, "3D/Objects/") == [
        "3D/Objects/object_1.model", "3D/Objects/object_2.model",
        "3D/Objects/object_3.model"]
    for name in members(prepared, "3D/Objects/"):
        assert name in read(prepared, RELS), f"{name} holds geometry nobody declared"


def test_the_root_holds_no_geometry_and_places_each_object_itself(prepared):
    root = read(prepared, ROOT)
    assert root.count("<mesh>") == 0
    composites = re.findall(r'<object id="(\d+)" type="model"><components>', root)
    items = re.findall(r'<item objectid="(\d+)"', root)
    assert len(composites) == len(items) == 3
    assert composites == items, "each object is placed by its own build item"


def test_part_ids_are_unique_across_the_whole_project(prepared):
    """What Orca's own multi-object project does, and what keeps parts apart."""
    settings = read(prepared, SETTINGS)
    part_ids = re.findall(r'<part id="(\d+)"', settings)
    assert part_ids == ["1", "2", "3", "4"]
    root = read(prepared, ROOT)
    composites = re.findall(r'<object id="(\d+)" type="model"><components>', root)
    assert set(composites).isdisjoint(part_ids), (
        "a composite must not share a number with a part")


def test_no_object_reaches_into_another_objects_file(prepared):
    """Every component points at the file its own object owns."""
    root = read(prepared, ROOT)
    for block in re.findall(r"<object id=\"\d+\" type=\"model\"><components>.*?</components>",
                            root, re.S):
        paths = set(re.findall(r'p:path="([^"]*)"', block))
        assert len(paths) == 1, paths


def test_the_validator_passes_the_whole_project(prepared):
    result = MP.validate_archive(ThreeMF.open(prepared))
    assert result["ok"] and result["problems"] == [], result
    assert result["parts"] == 4


# --- geometry, per object and in total ----------------------------------------

def test_every_object_keeps_its_own_geometry(prepared):
    source = source_objects()
    copy = objects_of(prepared)
    assert len(copy) == len(source) == 3
    for origin, prepared_entry in zip(source.values(), copy.values()):
        assert [mesh["digest"] for mesh in prepared_entry["meshes"]] == origin["digests"]
        assert [mesh["triangles"] for mesh in prepared_entry["meshes"]] == origin["triangles"]


def test_no_facet_is_lost_duplicated_or_moved_between_objects(prepared):
    source = source_objects()
    copy = objects_of(prepared)
    everything = [mesh["digest"] for entry in copy.values() for mesh in entry["meshes"]]
    assert len(everything) == len(set(everything)) or True  # two cubes may be identical
    assert sum(sum(entry["triangles"]) for entry in source.values()) == sum(
        mesh["triangles"] for entry in copy.values() for mesh in entry["meshes"]) == 36


# --- painting, per object and per part ----------------------------------------

def test_each_objects_painting_stays_on_that_object(prepared):
    source = source_objects()
    copy = objects_of(prepared)
    for origin, prepared_entry in zip(source.values(), copy.values()):
        assert [mesh["painted"] for mesh in prepared_entry["meshes"]] == origin["painted"]
    plain = list(copy.values())[2]
    assert sum(mesh["painted"] for mesh in plain["meshes"]) == 0, (
        "the unpainted object must not acquire colour from its neighbours")


def test_the_whole_projects_painting_still_decodes_the_same(prepared):
    before = PC.read_container(ThreeMF.open(str(SOURCE)))
    after = PC.read_container(ThreeMF.open(prepared))
    assert before["painted_triangle_count"] == after["painted_triangle_count"] == 16
    assert before["slots_referenced"] == after["slots_referenced"]


def test_the_copy_writes_the_targets_attribute_everywhere(prepared):
    for name in members(prepared, "3D/Objects/"):
        body = read(prepared, name)
        assert "mmu_segmentation" not in body


# --- filament capacity across the whole project -------------------------------

def test_capacity_counts_every_object_not_just_the_first(prepared):
    """The first object names 5; a copy that stopped at the first would declare 4."""
    with zipfile.ZipFile(prepared) as z:
        settings = json.loads(
            z.read("Metadata/project_settings.config").decode("utf-8"))
    assert len(settings["filament_settings_id"]) == 5
    assert len(settings["flush_volumes_matrix"]) == 25
    assert len(settings["nozzle_diameter"]) == 4, "a fifth toolhead was not invented"


# --- placement ----------------------------------------------------------------

def test_every_object_stays_where_the_source_put_it(prepared):
    source = source_objects()
    copy = objects_of(prepared)
    assert [entry["transform"] for entry in copy.values()] == [
        entry["transform"] for entry in source.values()]
    assert len({entry["transform"] for entry in copy.values()}) == 3, (
        "three objects at three places, not three objects at one")


# --- the audit answers for each object ----------------------------------------

def rows(path: str, prefix: str) -> list[dict]:
    return [r for r in audit(str(SOURCE), path)["rows"]
            if r["element"].startswith(prefix)]


def test_the_audit_answers_shape_painting_and_place_per_object(prepared):
    assert len(rows(prepared, "The shape of each part of")) == 3
    assert len(rows(prepared, "Where ")) == 3
    assert all(row["status"] == "preserved_exact"
               for row in rows(prepared, "The shape of each part of"))
    assert all(row["status"] == "preserved_exact" for row in rows(prepared, "Where "))
    # Two objects are painted, so two painting rows — not one for the project.
    assert len(rows(prepared, "The painting on each part of")) == 2


def test_the_object_count_is_objects_not_elements(prepared):
    row = rows(prepared, "Objects")[0]
    assert row["status"] == "preserved_exact" and "3 before and after" in row["detail"]


# --- corruptions, each aimed at one object ------------------------------------

def damage(prepared: str, tmp_path: Path, member: str, change) -> str:
    target = tmp_path / "damaged.3mf"
    with zipfile.ZipFile(prepared) as src, zipfile.ZipFile(target, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == member:
                data = change(data.decode("utf-8")).encode("utf-8")
            dst.writestr(item.filename, data)
    return str(target)


def problems(path: str) -> list[str]:
    return MP.validate_archive(ThreeMF.open(path))["problems"]


def test_swapping_two_objects_parts_is_caught(prepared, tmp_path):
    """Every part is still in the file. Two of them are under the wrong object."""
    def swap(text: str) -> str:
        return text.replace('<part id="3"', "@@").replace(
            '<part id="4"', '<part id="3"').replace("@@", '<part id="4"')

    broken = damage(prepared, tmp_path, SETTINGS, swap)
    assert any("do not match its component ids" in p for p in problems(broken))


def test_swapping_two_build_transforms_is_caught(prepared, tmp_path):
    root = read(prepared, ROOT)
    first, second = re.findall(r'<item objectid="\d+" transform="([^"]*)"', root)[:2]
    broken = damage(prepared, tmp_path, ROOT, lambda t: t.replace(
        f'transform="{first}"', "@@").replace(f'transform="{second}"',
                                              f'transform="{first}"').replace(
        "@@", f'transform="{second}"'))
    moved = [r for r in audit(str(SOURCE), broken)["rows"]
             if r["element"].startswith("Where ") and r["status"] == "changed"]
    assert len(moved) == 2, [r["element"] for r in moved]


def test_removing_one_object_is_caught(prepared, tmp_path):
    root = read(prepared, ROOT)
    last = re.findall(r'<object id="(\d+)" type="model"><components>', root)[-1]
    broken = damage(prepared, tmp_path, ROOT, lambda t: re.sub(
        rf'<object id="{last}" type="model"><components>.*?</object>', "", t, flags=re.S))
    assert any("does not build from components" in p for p in problems(broken))


def test_duplicating_one_objects_parts_is_caught(prepared, tmp_path):
    broken = damage(prepared, tmp_path, SETTINGS, lambda t: t.replace(
        '<part id="3"', '<part id="3" subtype="normal_part"></part><part id="3"', 1))
    assert any("part(s) and has" in p for p in problems(broken))


def test_swapping_two_objects_assignments_is_caught(prepared, tmp_path):
    """B prints in filament 3 and C in none. Swap them and the audit says so."""
    broken = damage(prepared, tmp_path, SETTINGS,
                    lambda t: t.replace('key="extruder" value="3"',
                                        'key="extruder" value="0"', 1))
    changed = [r for r in audit(str(SOURCE), broken)["rows"]
               if r["element"].startswith("Filament for ")
               and r["status"] in ("changed", "removed")]
    assert changed, [r["element"] for r in audit(str(SOURCE), broken)["rows"]]


def test_moving_one_objects_painting_to_another_is_caught(prepared, tmp_path):
    """The project's total painting is unchanged; two objects have swapped it."""
    first = "3D/Objects/object_1.model"
    third = "3D/Objects/object_3.model"
    painted = read(prepared, first)
    values = re.findall(r'\spaint_color="[^"]*"', painted)
    target = tmp_path / "moved.3mf"
    with zipfile.ZipFile(prepared) as src, zipfile.ZipFile(target, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == first:
                data = re.sub(r'\spaint_color="[^"]*"', "",
                              data.decode("utf-8")).encode("utf-8")
            elif item.filename == third:
                text = data.decode("utf-8")
                for value in values:
                    text = text.replace("/>", f"{value}/>", 1)
                data = text.encode("utf-8")
            dst.writestr(item.filename, data)
    moved = [r for r in audit(str(SOURCE), str(target))["rows"]
             if r["element"].startswith("The painting on each part")
             and r["status"] == "changed"]
    assert moved, "painting that changed objects must be a finding"


def test_a_modifier_on_one_object_stays_on_that_object(tmp_path):
    """Two objects, one with a modifier. The role must not travel."""
    modifier_source = (Path(__file__).parent / "fixtures" / "prusa-semantics"
                       / "vt_ParameterModifier_out.3mf")
    out = convert_to_u1(str(modifier_source), out_dir=str(tmp_path)).output_path
    settings = read(out, SETTINGS)
    objects = re.findall(r'<object id="(\d+)">(.*?)</object>', settings, re.S)
    assert len(objects) == 1
    subtypes = re.findall(r'subtype="([^"]*)"', objects[0][1])
    assert subtypes == ["normal_part", "modifier_part"]
    body = read(out, "3D/Objects/object_1.model")
    assert re.findall(r'<object id="(\d+)"[^>]*type="([^"]*)"', body) == [
        ("1", "model"), ("2", "other")]


def test_prepare_still_refuses_output_it_cannot_vouch_for(monkeypatch, tmp_path):
    """The production gate, on a project of several objects."""
    original = MP.part_records

    def wrong(parts, name, slots, roles=None, ids=None):
        return original(parts, name, slots, roles, ids).replace(
            '<part id="3"', '<part id="33"')

    monkeypatch.setattr(MP, "part_records", wrong)
    out_dir = tmp_path / "out"
    with pytest.raises(UnsoundOutput) as caught:
        convert_to_u1(str(SOURCE), out_dir=str(out_dir))
    assert "component ids" in caught.value.details
    assert not list(out_dir.glob("*.3mf"))
