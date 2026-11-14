"""The p:path file scan reads objects the way the root scan does, and references resolve by (file, id).

Evidence label: fixture-tested. Every archive here is SYNTHETIC, built in this file; no genuine export was
used and Snapmaker Orca was not run. These close the gaps Sol R6-N1 and Opus O-R6-F1 left open on the
validator: nested and unclosed objects in a p:path file, an empty <triangles> container, a comment that
contains tag text, and ids that repeat across files.
"""
from __future__ import annotations

from snapstudio_core import multipart

NS = 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'
PNS = 'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"'
MESH = ('<mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/><vertex x="0" y="1" z="0"/>'
        '<vertex x="0" y="0" z="1"/></vertices><triangles><triangle v1="0" v2="2" v3="1"/>'
        '<triangle v1="0" v2="1" v3="3"/></triangles></mesh>')
EMPTY_MESH = '<mesh><vertices><vertex x="0" y="0" z="0"/></vertices><triangles></triangles></mesh>'


class Archive:
    def __init__(self, parts):
        self.parts = parts

    def has_part(self, name):
        return name in self.parts

    def read_part(self, name):
        return self.parts[name]


def obj(object_id, kind="model", body=MESH):
    return f'<object id="{object_id}" type="{kind}">{body}</object>'


def model(*objects):
    return f'<model {NS}><resources>{"".join(objects)}</resources></model>'


def build(files, components, *, parts=None, root_objects=(), assembly=10):
    """files: {"/3D/Objects/a.model": model-xml}; components: [(path-or-None, id)];
    parts: [(part id, subtype)] under the assembly, defaulting to one normal_part per component."""
    refs = "".join(
        f'<component p:path="{p}" objectid="{i}"/>' if p else f'<component objectid="{i}"/>'
        for p, i in components)
    root = (f'<model {NS} {PNS}><resources>{"".join(root_objects)}'
            f'<object id="{assembly}" type="model"><components>{refs}</components></object>'
            f'</resources><build><item objectid="{assembly}"/></build></model>')
    rels = "".join(f'<Relationship Target="{p}"/>' for p in files)
    if parts is None:
        parts = [(i, "normal_part") for _p, i in components]
    part_xml = "".join(f'<part id="{i}" subtype="{s}"></part>' for i, s in parts)
    out = {"3D/3dmodel.model": root.encode(),
           "3D/_rels/3dmodel.model.rels": f"<Relationships>{rels}</Relationships>".encode(),
           "Metadata/model_settings.config": f'<config><object id="{assembly}">{part_xml}</object></config>'.encode()}
    for path, xml in files.items():
        out[path.lstrip("/")] = xml.encode()
    return Archive(out)


A = "/3D/Objects/a.model"
B = "/3D/Objects/b.model"


def problems_of(archive):
    return multipart.validate_archive(archive)["problems"]


# -- valid shapes still pass ---------------------------------------------------------------------------------

def test_a_plain_file_assembly_is_valid():
    result = multipart.validate_archive(build({A: model(obj(1))}, [(A, 1)]))
    assert result["ok"] is True, result["problems"]


def test_a_root_object_and_a_file_object_sharing_an_id_are_valid_when_the_assembly_names_the_file():
    """Root object 1 and file object 1 are different objects; two assemblies may each use their own."""
    archive = build({A: model(obj(1))}, [(A, 1)], root_objects=[obj(1)])
    assert multipart.validate_archive(archive)["ok"] is True


def test_an_unreferenced_file_with_the_same_id_does_not_disturb_the_assembly():
    """Cross-file id reuse is ordinary: ids are scoped to their file."""
    archive = build({A: model(obj(1)), B: model(obj(1, "other"))}, [(A, 1)])
    # B is never referenced, so it is not read and cannot disturb the assembly that uses A
    assert multipart.validate_archive(archive)["ok"] is True


def test_one_assembly_may_instance_the_same_file_object_twice():
    archive = build({A: model(obj(1))}, [(A, 1), (A, 1)])
    assert multipart.validate_archive(archive)["ok"] is True


def test_a_comment_that_contains_object_tag_text_does_not_refuse_a_valid_file():
    commented = f'<model {NS}><!-- <object id="9"> --><resources>{obj(1)}</resources></model>'
    result = multipart.validate_archive(build({A: commented}, [(A, 1)]))
    assert result["ok"] is True, result["problems"]


def test_a_comment_in_the_root_model_does_not_refuse_a_valid_root_mesh():
    archive = build({A: model(obj(1))}, [(None, 2), (A, 1)], root_objects=[
        f'<object id="2" type="model"><!-- <object --> {MESH}</object>'], parts=[(2, "normal_part"), (1, "normal_part")])
    assert multipart.validate_archive(archive)["ok"] is True


# -- the p:path scan now has the nested / unclosed handling the root scan has ---------------------------------

def test_an_object_nested_in_a_file_object_is_not_credited_to_the_outer_object():
    nested = model(f'<object id="1" type="model"><object id="9" type="model">{MESH}</object></object>')
    result = multipart.validate_archive(build({A: nested}, [(A, 1)]))
    assert result["ok"] is False
    assert any("object 1 in /3D/Objects/a.model contains another object" in p for p in result["problems"])
    assert any("no file defines" in p and "'1'" in p for p in result["problems"])


def test_an_unclosed_file_object_is_refused_not_ignored():
    unclosed = f'<model {NS}><resources><object id="1" type="model">{MESH}</resources></model>'
    result = multipart.validate_archive(build({A: unclosed}, [(A, 1)]))
    assert result["ok"] is False
    assert any("object 1 in /3D/Objects/a.model is not closed" in p for p in result["problems"])
    assert any("no file defines" in p for p in result["problems"])


def test_an_unclosed_file_object_does_not_borrow_the_next_objects_geometry():
    """Object 1 has no mesh and no close tag; object 2's closing tag must not make it look like geometry."""
    xml = f'<model {NS}><resources><object id="1" type="model"><components/><object id="2" type="model">{MESH}</object></resources></model>'
    result = multipart.validate_archive(build({A: xml}, [(A, 1)]))
    assert result["ok"] is False
    assert any("contains another object" in p for p in result["problems"])


def test_an_empty_triangles_container_in_a_file_is_not_geometry():
    result = multipart.validate_archive(build({A: model(obj(1, body=EMPTY_MESH))}, [(A, 1)]))
    assert result["ok"] is False
    assert any("object 1 in /3D/Objects/a.model carries no geometry" in p for p in result["problems"])


def test_an_empty_triangles_container_in_the_root_is_not_geometry():
    archive = build({A: model(obj(1))}, [(None, 2), (A, 1)], root_objects=[obj(2, body=EMPTY_MESH)],
                    parts=[(2, "normal_part"), (1, "normal_part")])
    assert any("object 2 in the root model carries no geometry" in p for p in problems_of(archive))


def test_a_self_closing_file_object_carries_no_geometry():
    result = multipart.validate_archive(build({A: model('<object id="1" type="model"/>')}, [(A, 1)]))
    assert result["ok"] is False
    assert any("object 1 in /3D/Objects/a.model carries no geometry" in p for p in result["problems"])


# -- ids: duplicates, cross-file reuse, missing references ----------------------------------------------------

def test_a_duplicate_id_inside_one_file_is_refused():
    result = multipart.validate_archive(build({A: model(obj(1), obj(1))}, [(A, 1)]))
    assert result["ok"] is False
    assert any("object 1 is defined more than once in /3D/Objects/a.model" in p for p in result["problems"])


def test_a_duplicate_id_in_the_root_model_is_refused():
    archive = build({A: model(obj(1))}, [(None, 2), (A, 1)], root_objects=[obj(2), obj(2)],
                    parts=[(2, "normal_part"), (1, "normal_part")])
    assert any("object 2 is defined more than once in the root model" in p for p in problems_of(archive))


def test_a_reference_resolves_in_its_own_file_not_in_another_file_with_that_id():
    """Component names file A object 2, which only file B defines: it is missing, not satisfied by B."""
    archive = build({A: model(obj(1)), B: model(obj(2))}, [(A, 2), (B, 2)])
    result = multipart.validate_archive(archive)
    assert result["ok"] is False
    assert any("no file defines" in p and "'2'" in p for p in result["problems"])


def test_a_pathed_reference_is_not_satisfied_by_a_root_object_with_that_id():
    archive = build({A: model(obj(5))}, [(A, 1)], root_objects=[obj(1)])
    assert any("no file defines" in p and "'1'" in p for p in problems_of(archive))


def test_a_missing_file_object_is_reported_when_the_file_exists_but_lacks_the_id():
    assert any("no file defines" in p and "'7'" in p
               for p in problems_of(build({A: model(obj(1))}, [(A, 7)])))


def test_type_is_checked_against_the_named_file_object_when_another_file_reuses_the_id():
    """Both files define object 1; the one the component names is typed 'other' under a normal_part."""
    archive = build({A: model(obj(1, "other")), B: model(obj(1, "model"))}, [(A, 1)])
    assert any("is a normal_part and the geometry under it is typed 'other'" in p for p in problems_of(archive))


def test_type_in_an_unreferenced_file_does_not_cause_a_false_mismatch():
    archive = build({A: model(obj(1, "model")), B: model(obj(1, "other"))}, [(A, 1)])
    assert multipart.validate_archive(archive)["ok"] is True


def test_two_files_that_disagree_on_an_ids_type_in_one_assembly_are_refused():
    archive = build({A: model(obj(1, "model")), B: model(obj(1, "other"))}, [(A, 1), (B, 1)],
                    parts=[(1, "normal_part"), (1, "normal_part")])
    assert any("several files that disagree" in p for p in problems_of(archive))


def test_two_files_that_agree_on_an_ids_type_in_one_assembly_stay_valid():
    archive = build({A: model(obj(1)), B: model(obj(1))}, [(A, 1), (B, 1)],
                    parts=[(1, "normal_part"), (1, "normal_part")])
    assert multipart.validate_archive(archive)["ok"] is True


# -- malformed objects and components ------------------------------------------------------------------------

def test_a_non_numeric_object_id_in_a_file_is_refused():
    xml = model(f'<object id="x1" type="model">{MESH}</object>', obj(1))
    assert any("has an id that is not a number" in p for p in problems_of(build({A: xml}, [(A, 1)])))


def test_a_truncated_object_tag_is_refused():
    xml = f'<model {NS}><resources>{obj(1)}<object id="2" type="model"'
    assert any("is not closed" in p for p in problems_of(build({A: xml}, [(A, 1)])))


def test_a_component_without_an_object_id_is_refused_even_beside_valid_ones():
    archive = build({A: model(obj(1))}, [(A, 1)])
    root = archive.parts["3D/3dmodel.model"].decode().replace(
        "</components>", f'<component p:path="{A}"/></components>', 1)
    archive.parts["3D/3dmodel.model"] = root.encode()
    assert any("has no object id" in p for p in problems_of(archive))


def test_component_attribute_order_does_not_matter():
    archive = build({A: model(obj(1))}, [(A, 1)])
    root = archive.parts["3D/3dmodel.model"].decode().replace(
        f'<component p:path="{A}" objectid="1"/>', f'<component objectid="1" p:path="{A}"/>')
    archive.parts["3D/3dmodel.model"] = root.encode()
    assert multipart.validate_archive(archive)["ok"] is True


def test_an_unclosed_root_mesh_object_is_refused():
    archive = build({A: model(obj(1))}, [(None, 2), (A, 1)], parts=[(2, "normal_part"), (1, "normal_part")],
                    root_objects=[f'<object id="2" type="model">{MESH}'])
    # no closing tag: the next </object> belongs to the assembly, so object 2 holds another object
    assert any("object 2 in the root model" in p for p in problems_of(archive))


# -- same-id root/file assembly stays refused (Sol R5-F1) ------------------------------------------------------

def test_one_assembly_still_may_not_mix_root_and_file_components_with_the_same_id():
    archive = build({A: model(obj(1, "other"))}, [(A, 1), (None, 1)], root_objects=[obj(1, "model")],
                    parts=[(1, "normal_part"), (1, "normal_part")])
    assert any("referenced both from the root model and from a file" in p for p in problems_of(archive))


# -- Sol R7-F1 / R7-F2 ---------------------------------------------------------------------------------------

def test_a_commented_out_component_in_the_root_model_does_not_refuse_a_valid_archive():
    archive = build({A: model(obj(1))}, [(A, 1)])
    root = archive.parts["3D/3dmodel.model"].decode().replace(
        "</components>", '</components><!-- <component/> -->', 1)
    archive.parts["3D/3dmodel.model"] = root.encode()
    assert multipart.validate_archive(archive)["ok"] is True


def test_a_commented_out_assembly_is_not_read_as_structure():
    archive = build({A: model(obj(1))}, [(A, 1)])
    root = archive.parts["3D/3dmodel.model"].decode().replace(
        "</resources>",
        '<!--<object id="77" type="model"><components><component objectid="5"/></components></object>--></resources>', 1)
    archive.parts["3D/3dmodel.model"] = root.encode()
    assert multipart.validate_archive(archive)["ok"] is True


def test_an_omitted_object_type_equals_an_explicit_model_across_files():
    untyped = f'<object id="1">{MESH}</object>'
    archive = build({A: model(untyped), B: model(obj(1, "model"))}, [(A, 1), (B, 1)],
                    parts=[(1, "normal_part"), (1, "normal_part")])
    assert multipart.validate_archive(archive)["ok"] is True


def test_an_omitted_object_type_still_disagrees_with_an_explicit_other_across_files():
    untyped = f'<object id="1">{MESH}</object>'
    archive = build({A: model(untyped), B: model(obj(1, "other"))}, [(A, 1), (B, 1)],
                    parts=[(1, "normal_part"), (1, "normal_part")])
    assert any("several files that disagree" in p for p in problems_of(archive))


def test_an_object_written_with_id_not_first_is_refused_not_skipped():
    """Opus O-R7-F1: an unreadable object spelling must not hide a nested object from the scan."""
    xml = model(f'<object type="model" id="1"><object id="9" type="model">{MESH}</object></object>')
    result = multipart.validate_archive(build({A: xml}, [(A, 9)]))
    assert result["ok"] is False
    assert any("object tag the scan cannot read" in p for p in result["problems"])
