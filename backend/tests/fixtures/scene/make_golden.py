"""Writes golden-scene-1.json by hand, independently of snapstudio_core.scene.

The golden scene is the frozen reference for scene/1: a 10 mm cube, authored in millimetres at
(50, 60, 0) in a plain 3MF with no slicer metadata. It is derived here from first principles (struct +
base64 + the U1 bed numbers), so a test can require the real builder to reproduce it exactly.

Run:  py -3.13 make_golden.py   (rewrites golden-scene-1.json next to this file)
"""
import base64
import json
import struct
from pathlib import Path

REVISION = "0123456789abcdef" * 4
VERTS = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0), (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10)]
TRIS = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
        (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
PART = "3D/3dmodel.model"


def b64(fmt, values):
    return base64.b64encode(struct.pack("<" + fmt * len(values), *values)).decode("ascii")


matrix = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 50.0, 60.0, 0.0, 1.0]
scene = {
    "schema": "scene/1", "revision": REVISION, "status": "complete", "units": "mm", "axes": "right-handed-z-up",
    "sources": [{"part": PART, "unit": "millimeter", "mm_per_unit": 1.0}],
    "bed": {"polygon_mm": [[0.5, 1.0], [270.5, 1.0], [270.5, 271.0], [0.5, 271.0]],
            "height_mm": 270.05, "edge_margin_mm": 0.5, "policy": "u1_template"},
    "meshes": [{
        "key": {"part": PART, "object_id": "1"}, "vertex_count": 8, "triangle_count": 12,
        "positions_f32le_base64": b64("f", [c for v in VERTS for c in v]),
        "indices_u32le_base64": b64("I", [i for t in TRIS for i in t]),
        "volumes": [{"id": "v0", "triangle_start": 0, "triangle_count": 12, "role": "part", "source": "object"}]}],
    "nodes": [{
        "id": "b0", "parent_id": None, "resource": {"part": PART, "object_id": "1"},
        "mesh_key": {"part": PART, "object_id": "1"}, "local_to_parent_mm": matrix, "world_mm": matrix,
        "mirrored": False, "role_context": None, "build_index": 0, "instance_ref": {"build_index": 0, "component_path": []},
        "plate": {"state": "unknown", "plate_id": None, "source": None}, "placement_state": "known",
        "printable": True, "has_non_part_volumes": False,
        "bounds_mm": {"min": [50.0, 60.0, 0.0], "max": [60.0, 70.0, 10.0]}, "finding_ids": []}],
    "plates": [], "findings": [],
    "limitations": [{"code": "PLATES_UNAVAILABLE", "target_ids": []}],
    "counts": {"nodes": 1, "meshes": 1, "vertices": 8, "triangles": 12, "rendered_triangles": 12,
               "plates": 0, "findings": 0, "limitations": 1},
    "limits": {"max_archive_bytes": 134217728, "max_model_xml_bytes": 33554432, "max_rendered_triangles": 250000,
               "max_vertices": 300000, "max_nodes": 2000, "max_depth": 64, "max_response_bytes": 8388608,
               "max_findings": 500, "max_limitations": 50, "max_id_length": 128}}
if __name__ == "__main__":
    out = Path(__file__).with_name("golden-scene-1.json")
    out.write_text(json.dumps(scene, indent=2) + "\n", encoding="utf-8")
    print("wrote", out)
