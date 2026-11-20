"""ASM-05: independent slot declarations must survive short/absent gram vectors.

Synthetic fixtures only. Tests use the real reader and import/evaluate routes;
no slicer, provider, device or printer control is involved.
"""
import hashlib
import pytest
from snapstudio_api import routes_assemblies
from snapstudio_core.assemblies.importer import import_file
from snapstudio_core.assemblies.model import AssemblyInputError

DECLARATIONS = [
    "; filament_type = PLA;PLA\n",
    "; filament used [mm] = 100, 200\n",
    "; nozzle_diameter = 0.4;0.4\n",
]

@pytest.mark.parametrize("declaration", DECLARATIONS)
@pytest.mark.parametrize("vector,expected", [("; filament used [g] = 3\n", {"slot:0": 3.0, "slot:1": None}), ("", {"slot:0": None, "slot:1": None})])
def test_independent_slots_remain_unknown_when_grams_are_short_or_absent(tmp_path, declaration, vector, expected):
    path = tmp_path / "synthetic-short.gcode"
    raw = ("G1 X1\n" + declaration + vector).encode()
    path.write_bytes(raw)
    report = import_file(str(path))
    assert report["assembly"]["tiles"][0]["usage"] == expected
    assert report["assembly"]["tiles"][0]["roles"] == {"Filament 1": "slot:0", "Filament 2": "slot:1"}
    assert report["sha256"] == hashlib.sha256(raw).hexdigest() and path.read_bytes() == raw

def test_malformed_grams_never_reuse_the_readers_compacted_values(tmp_path):
    path = tmp_path / "synthetic-positions.gcode"
    path.write_text("G1 X1\n; filament_type = PLA;PLA;PLA\n; filament used [g] = bad, 3\n", encoding="utf-8")
    assert import_file(str(path))["assembly"]["tiles"][0]["usage"] == {"slot:0": None, "slot:1": 3.0, "slot:2": None}

@pytest.mark.parametrize("vector,expected", [("3", "unknown"), ("", "unknown"), ("3, 2", "enough")])
def test_import_to_evaluate_cannot_claim_enough_for_an_omitted_requirement(tmp_path, vector, expected):
    path = tmp_path / "synthetic-plan.gcode"
    path.write_text("G1 X1\n; filament_type = PLA;PLA\n; filament used [mm] = 100, 200\n" + (f"; filament used [g] = {vector}\n" if vector else ""), encoding="utf-8")
    code, imported = routes_assemblies.import_file({"path": str(path)})
    assert code == 200
    document = imported["assembly"]
    spool = {"provider_instance_id": "synthetic", "provider_spool_id": "one"}
    document["bindings"] = {role: spool for role in document["tiles"][0]["roles"]}
    code, result = routes_assemblies.evaluate({"assembly": document, "now": 1_800_000_000,
        "supply": [{"spool": spool, "remaining_g": 100, "observed_at": 1_799_999_999, "ttl_s": 600}]})
    assert code == 200 and result["report"]["verdict"] == expected

def test_large_independent_slot_list_is_refused_instead_of_discarded(tmp_path):
    path = tmp_path / "synthetic-many.gcode"
    path.write_text("G1 X1\n; filament_type = " + ";".join(["PLA"] * 65) + "\n; filament used [g] = 1\n", encoding="utf-8")
    with pytest.raises(AssemblyInputError, match="64"):
        import_file(str(path))

@pytest.mark.parametrize("declaration", [
    "; filament used [mm] = bad, 200\n",
    "; nozzle_diameter = bad;0.4\n",
    "; filament_colour = #FF0000;#00FF00\n",
])
def test_raw_declaration_positions_also_survive_other_readers_compaction(tmp_path, declaration):
    path = tmp_path / "synthetic-declared-positions.gcode"
    path.write_text("G1 X1\n" + declaration + "; filament used [g] = 3\n", encoding="utf-8")
    assert import_file(str(path))["assembly"]["tiles"][0]["usage"] == {"slot:0": 3.0, "slot:1": None}
