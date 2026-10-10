"""Plate placement checking and the move-onto-the-plate fix.

Built on real 3MF archives with real transforms, because the fix rewrites a
transform matrix and the only way to trust that is to write a file and read it
back. The behaviours that matter: catch the object that is off the plate even
though it is small enough, move the whole arrangement without disturbing
rotation or scale, never touch the original, and refuse when a single move
cannot honestly fix the project.
"""
from __future__ import annotations

import json
import zipfile

from snapstudio_core import plate_placement as pp

# A 10 mm cube at the origin. The build item transform is what places it.
CUBE_VERTS = [
    (0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
    (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10),
]
CUBE_TRIS = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7),
             (0, 1, 5), (0, 5, 4), (2, 3, 7), (2, 7, 6),
             (1, 2, 6), (1, 6, 5), (0, 3, 7), (0, 7, 4)]


def _object_xml(oid: int) -> str:
    verts = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in CUBE_VERTS)
    tris = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in CUBE_TRIS)
    return (f'<object id="{oid}" type="model"><mesh>'
            f"<vertices>{verts}</vertices><triangles>{tris}</triangles>"
            f"</mesh></object>")


def _model(items: list[tuple[int, str | None]], objects: list[int] | None = None) -> bytes:
    objects = objects or [oid for oid, _ in items]
    res = "".join(_object_xml(oid) for oid in objects)
    build = "".join(
        f'<item objectid="{oid}"'
        + (f' transform="{tf}"' if tf else "")
        + "/>"
        for oid, tf in items
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US"'
        ' xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        f"<resources>{res}</resources><build>{build}</build></model>"
    ).encode()


def _translate(x: float, y: float, z: float = 0.0) -> str:
    return f"1 0 0 0 1 0 0 0 1 {x} {y} {z}"


def _write(tmp_path, name, items, *, printable_area=None, plates=1,
           printer="Bambu Lab X1 Carbon", objects=None):
    settings = {"printer_model": printer}
    if printable_area:
        settings["printable_area"] = printable_area
    plate_xml = "".join(
        f'<plate><metadata key="plater_id" value="{i + 1}"/></plate>' for i in range(plates))
    p = tmp_path / name
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("3D/3dmodel.model", _model(items, objects))
        z.writestr("Metadata/project_settings.config", json.dumps(settings))
        z.writestr("Metadata/model_settings.config", f"<config>{plate_xml}</config>")
    return str(p)


# --- reading the bed --------------------------------------------------------

def test_parses_a_rectangular_printable_area():
    rect = pp.parse_printable_area(["0x0", "256x0", "256x256", "0x256"])
    assert rect == {"min_x": 0.0, "min_y": 0.0, "max_x": 256.0, "max_y": 256.0}


def test_refuses_a_shape_it_cannot_treat_as_a_rectangle():
    assert pp.parse_printable_area(["0x0", "10x0"]) is None       # too few corners
    assert pp.parse_printable_area("256x256") is None             # not a list
    assert pp.parse_printable_area(["0x0", "axb", "1x1"]) is None  # unparseable


def test_u1_bed_is_read_from_the_shipped_profile():
    bed = pp.u1_bed_rect()
    assert 260 <= bed["max_x"] - bed["min_x"] <= 280
    assert 260 <= bed["max_y"] - bed["min_y"] <= 280


# --- assessment -------------------------------------------------------------

def test_object_on_the_plate_is_reported_clean(tmp_path):
    p = _write(tmp_path, "ok.3mf", [(1, _translate(100, 100))])
    out = pp.assess(p)
    assert out["available"] is True
    assert out["off_plate"] == []
    assert "inside the Snapmaker U1's printable area" in out["summary"]


def test_small_object_placed_off_the_plate_is_caught(tmp_path):
    """The whole point: it is small enough, and still not on the bed."""
    p = _write(tmp_path, "far.3mf", [(1, _translate(300, 100))],
               printable_area=["0x0", "350x0", "350x350", "0x350"])
    out = pp.assess(p)
    assert len(out["off_plate"]) == 1
    assert out["off_plate"][0]["overhang_mm"]["right"] > 0
    assert out["off_plate"][0]["edges"] == "right"


def test_negative_coordinates_are_caught_on_the_correct_edges(tmp_path):
    p = _write(tmp_path, "neg.3mf", [(1, _translate(-40, -40))])
    over = pp.assess(p)["off_plate"][0]["overhang_mm"]
    assert over["left"] > 0 and over["front"] > 0
    assert over["right"] == 0 and over["back"] == 0


def test_source_bed_and_printer_are_reported(tmp_path):
    p = _write(tmp_path, "src.3mf", [(1, _translate(100, 100))],
               printable_area=["0x0", "256x0", "256x256", "0x256"])
    out = pp.assess(p)
    assert out["source_bed"]["max_x"] == 256.0
    assert out["source_printer"] == "Bambu Lab X1 Carbon"


def test_arrangement_too_wide_is_not_called_fixable(tmp_path):
    p = _write(tmp_path, "wide.3mf",
               [(1, _translate(0, 100)), (2, _translate(400, 100))])
    out = pp.assess(p)
    assert out["fixable"] is False
    assert out["suggested_offset"] is None
    assert "wider than the plate" in out["summary"]


def test_unreadable_file_is_unavailable_not_an_exception(tmp_path):
    p = tmp_path / "junk.3mf"
    p.write_bytes(b"not a zip")
    out = pp.assess(str(p))
    assert out["available"] is False


# --- the transform maths ----------------------------------------------------

def test_shift_moves_only_the_translation_row():
    out = pp._shift_transform("2 0 0 0 2 0 0 0 2 10 20 30", 5, -5)
    assert out.split() == ["2", "0", "0", "0", "2", "0", "0", "0", "2", "15", "15", "30"]


def test_shift_rejects_a_matrix_it_does_not_understand():
    assert pp._shift_transform("1 0 0", 1, 1) is None
    assert pp._shift_transform("1 0 0 0 1 0 0 0 1 0 0 x", 1, 1) is None


# --- the fix ----------------------------------------------------------------

def test_fix_moves_the_arrangement_onto_the_plate(tmp_path):
    p = _write(tmp_path, "fixme.3mf", [(1, _translate(320, 100))],
               printable_area=["0x0", "350x0", "350x350", "0x350"])
    res = pp.prepare_placed_copy(p, out_dir=str(tmp_path / "out"))
    assert res["ok"] is True
    assert res["objects_moved"] == 1
    assert res["after"]["off_plate"] == []
    assert "not changed" in res["summary"]


def test_fix_never_modifies_the_original(tmp_path):
    p = _write(tmp_path, "orig.3mf", [(1, _translate(320, 100))],
               printable_area=["0x0", "350x0", "350x350", "0x350"])
    before = open(p, "rb").read()
    pp.prepare_placed_copy(p, out_dir=str(tmp_path / "out"))
    assert open(p, "rb").read() == before


def test_fix_preserves_rotation_and_scale(tmp_path):
    """A creator's rotated, scaled object must come back rotated and scaled."""
    rotated_scaled = "0 2 0 -2 0 0 0 0 2 320 100 0"
    p = _write(tmp_path, "rot.3mf", [(1, rotated_scaled)],
               printable_area=["0x0", "350x0", "350x350", "0x350"])
    res = pp.prepare_placed_copy(p, out_dir=str(tmp_path / "out"))
    assert res["ok"] is True
    with zipfile.ZipFile(res["output_path"]) as z:
        model = z.read("3D/3dmodel.model").decode()
    matrix = model.split('transform="')[1].split('"')[0].split()
    assert matrix[:9] == ["0", "2", "0", "-2", "0", "0", "0", "0", "2"]


def test_fix_preserves_relative_layout_between_objects(tmp_path):
    p = _write(tmp_path, "pair.3mf",
               [(1, _translate(300, 100)), (2, _translate(340, 100))],
               printable_area=["0x0", "400x0", "400x400", "0x400"])
    res = pp.prepare_placed_copy(p, out_dir=str(tmp_path / "out"))
    assert res["ok"] is True
    positions = {i["object_id"]: i["position"]["x"] for i in res["after"]["items"]}
    assert round(positions["2"] - positions["1"], 2) == 40.0


def test_fix_only_touches_the_model_part(tmp_path):
    p = _write(tmp_path, "surgical.3mf", [(1, _translate(320, 100))],
               printable_area=["0x0", "350x0", "350x350", "0x350"])
    res = pp.prepare_placed_copy(p, out_dir=str(tmp_path / "out"))
    with zipfile.ZipFile(p) as a, zipfile.ZipFile(res["output_path"]) as b:
        differing = [n for n in a.namelist() if a.read(n) != b.read(n)]
    assert differing == ["3D/3dmodel.model"]


def test_rewrite_gives_a_transformless_item_the_shift_too():
    """An item at the identity still has to travel with the rest of the plate,
    so the rewrite adds the transform it was missing rather than skipping it."""
    model = _model([(1, _translate(300, 100)), (2, None)])
    out, moved = pp._rewrite_items(model, pp._uniform_offset(5.0, -5.0))
    assert moved == 2
    text = out.decode()
    transforms = [t.split('"')[0] for t in text.split('transform="')[1:]]
    assert transforms[0].split()[9:11] == ["305", "95"]
    assert transforms[1].split()[9:11] == ["5", "-5"]
    # The tag stays well-formed after the attribute is inserted.
    assert "<item objectid=\"2\" transform=" in text
    assert "/>" in text.split('objectid="2"')[1][:80]


def test_fix_refuses_when_nothing_is_off_the_plate(tmp_path):
    p = _write(tmp_path, "fine.3mf", [(1, _translate(100, 100))])
    res = pp.prepare_placed_copy(p, out_dir=str(tmp_path / "out"))
    assert res["ok"] is False
    assert "already on the plate" in res["reason"]


def test_fix_refuses_a_multi_plate_project_and_writes_nothing(tmp_path):
    out_dir = tmp_path / "out"
    p = _write(tmp_path, "multi2.3mf", [(1, _translate(400, 100))], plates=2)
    res = pp.prepare_placed_copy(p, out_dir=str(out_dir))
    assert res["ok"] is False
    assert not out_dir.exists() or list(out_dir.iterdir()) == []


def test_fix_refuses_an_arrangement_that_cannot_fit(tmp_path):
    out_dir = tmp_path / "out"
    p = _write(tmp_path, "toobig.3mf",
               [(1, _translate(0, 100)), (2, _translate(400, 100))])
    res = pp.prepare_placed_copy(p, out_dir=str(out_dir))
    assert res["ok"] is False
    assert not out_dir.exists() or list(out_dir.iterdir()) == []


def test_fix_result_explains_what_was_kept(tmp_path):
    p = _write(tmp_path, "explain.3mf", [(1, _translate(320, 100))],
               printable_area=["0x0", "350x0", "350x350", "0x350"])
    res = pp.prepare_placed_copy(p, out_dir=str(tmp_path / "out"))
    assert res["changes"][0]["kept"].startswith("Layout, rotation, scale")


# --- multi-plate projects ---------------------------------------------------
#
# Studio does not reposition these. An independent review reproduced a case where
# the derived plate stride was 690 mm against a true 370 mm and the second plate
# was placed entirely off the bed while the result reported success. The spacing
# between plates is not in the file, so the feature was withdrawn rather than
# patched. What remains is the part that does not depend on the grid: whether
# each plate's own contents fit a U1 plate.

def _multi_plate_project(tmp_path, name, plates: dict, *, printable_area=None,
                         printer="Bambu Lab X1 Carbon"):
    """plates: {ui_plate_number: [(object_id, x, y), ...]}"""
    items, plate_xml = [], []
    for number in sorted(plates):
        instances = ""
        for oid, x, y in plates[number]:
            items.append((oid, _translate(x, y)))
            instances += (f'<model_instance><metadata key="object_id" value="{oid}"/>'
                          f'<metadata key="instance_id" value="0"/></model_instance>')
        plate_xml.append(f'<plate><metadata key="plater_id" value="{number}"/>'
                         f'{instances}</plate>')
    settings = {"printer_model": printer}
    if printable_area:
        settings["printable_area"] = printable_area
    p = tmp_path / name
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("3D/3dmodel.model", _model(items))
        z.writestr("Metadata/project_settings.config", json.dumps(settings))
        z.writestr("Metadata/model_settings.config",
                   "<config>" + "".join(plate_xml) + "</config>")
    return str(p)


SOURCE_350 = ["0x0", "350x0", "350x350", "0x350"]


def test_a_plate_far_along_the_grid_is_not_called_off_the_plate(tmp_path):
    """Plate 3 legitimately sits hundreds of millimetres along X. That is the
    authoring slicer's grid, not a fault in the project."""
    p = _multi_plate_project(tmp_path, "grid.3mf", {
        1: [(1, 170, 170)],
        2: [(2, 540, 170)],
        3: [(3, 910, 170)],
    }, printable_area=SOURCE_350)
    out = pp.assess(p)
    assert out["available"] is True
    assert out["off_plate"] == []
    assert len(out["plate_fit"]) == 3
    assert all(row["fits"] for row in out["plate_fit"])


def test_multi_plate_projects_are_never_repositioned(tmp_path):
    out_dir = tmp_path / "out"
    p = _multi_plate_project(tmp_path, "multi.3mf", {
        1: [(1, 170, 170)],
        2: [(2, 540, 170)],
    }, printable_area=SOURCE_350)
    out = pp.assess(p)
    assert out["fixable"] is False
    # Reworded: the old text claimed the plates "fit" the printable area and only said Studio
    # does not reposition them; it now says what Studio cannot check (see test_honest_claims).
    assert "cannot check where the plates sit" in out["summary"]
    res = pp.prepare_placed_copy(p, out_dir=str(out_dir))
    assert res["ok"] is False
    assert not out_dir.exists() or list(out_dir.iterdir()) == []


def test_the_refusal_explains_why_rather_than_just_declining(tmp_path):
    p = _multi_plate_project(tmp_path, "why.3mf", {
        1: [(1, 170, 170)], 2: [(2, 540, 170)],
    }, printable_area=SOURCE_350)
    summary = pp.assess(p)["summary"]
    assert "cannot check where the plates sit" in summary and "Arrange all plates" in summary


def test_a_plate_whose_contents_are_too_big_is_reported(tmp_path):
    """This check does not depend on the grid, so Studio can still make it."""
    p = _multi_plate_project(tmp_path, "big.3mf", {
        1: [(1, 170, 170)],
        2: [(2, 400, 170), (3, 900, 170)],   # spans 510 mm — wider than a U1 plate
    }, printable_area=SOURCE_350)
    out = pp.assess(p)
    oversized = out["oversized_plates"]
    assert [row["plate"] for row in oversized] == [2]
    assert "larger than the Snapmaker U1's" in oversized[0]["reason"]
    # The objects on that plate are flagged, the ones on plate 1 are not.
    flagged = {row["object_id"] for row in out["off_plate"]}
    assert flagged == {"2", "3"}
    assert out["fixable"] is False


def test_an_object_on_no_plate_is_reported(tmp_path):
    p = _multi_plate_project(tmp_path, "orphan.3mf", {
        1: [(1, 170, 170)], 2: [(2, 540, 170)],
    }, printable_area=SOURCE_350)
    with zipfile.ZipFile(p) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["3D/3dmodel.model"] = _model(
        [(1, _translate(170, 170)), (2, _translate(540, 170)), (3, _translate(900, 900))])
    p2 = tmp_path / "orphan2.3mf"
    with zipfile.ZipFile(p2, "w") as z:
        for n, d in parts.items():
            z.writestr(n, d)
    out = pp.assess(str(p2))
    assert [u["object_id"] for u in out["unresolved_objects"]] == ["3"]
    assert out["fixable"] is False


def test_single_plate_projects_are_unaffected(tmp_path):
    p = _write(tmp_path, "one.3mf", [(1, _translate(320, 100))],
               printable_area=["0x0", "350x0", "350x350", "0x350"])
    out = pp.assess(p)
    assert out["plate_fit"] == []
    assert out["suggested_offset"] is not None
    assert out["fixable"] is True


def test_a_model_part_that_is_not_text_does_not_raise(tmp_path):
    """prepare_placed_copy is documented as always returning a result dict."""
    p = _write(tmp_path, "bin.3mf", [(1, _translate(320, 100))],
               printable_area=["0x0", "350x0", "350x350", "0x350"])
    with zipfile.ZipFile(p) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    good = pp.assess(p)
    assert good["fixable"] is True
    parts["3D/3dmodel.model"] = bytes([0xff, 0xfe]) + b" not text at all"
    p2 = tmp_path / "bin2.3mf"
    with zipfile.ZipFile(p2, "w") as z:
        for n, d in parts.items():
            z.writestr(n, d)
    res = pp.prepare_placed_copy(str(p2), out_dir=str(tmp_path / "o"))
    assert res["ok"] is False
