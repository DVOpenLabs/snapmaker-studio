"""Guard: guide statements that depend on engine behavior are checked against the engine.

The user guide (site/guide) is hand-written. Its own tests check structure and
interaction, and cannot know what the engine does. These tests run the engine on
the example project and read the values from it, then require the guide to agree.
They do not copy the guide's answers: the expected facts come from the engine.

What they establish: the placement example's distance and output name match what
the engine really produces, the original stays byte-identical, and the guide's
printer-name explanation matches the confidence the engine actually assigns.
What they cannot establish: that the prose around those facts is well explained,
or anything about a physical printer or Snapmaker Orca.
"""
import hashlib
import json
import re
import shutil
from pathlib import Path

from snapstudio_core import plate_placement as pp
from snapstudio_core import post_slice

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "site" / "guide" / "content"


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)


def _guide(name):
    return json.loads((GUIDE / f"{name}.json").read_text(encoding="utf-8"))


def _all_guide_text() -> str:
    return "\n".join(s for n in ("guide", "path", "tasks", "problems", "examples", "shots")
                     for s in _strings(_guide(n)))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_placement_example_matches_the_engine(tmp_path):
    src = tmp_path / "demo_offplate_foreign.3mf"
    shutil.copy(ROOT / "examples" / "demo_offplate_foreign.3mf", src)
    before = _sha(src)

    assessed = pp.assess(str(src))
    assert assessed["off_plate"], "the example project must still have an object off the plate"
    item = assessed["off_plate"][0]
    assert item["edges"] == "right"
    distance = item["overhang_mm"]["right"]

    moved = pp.prepare_placed_copy(str(src))
    assert moved["ok"] and moved["verification"]["passed"]
    assert moved["output_name"].endswith("_placed_U1.3mf")
    assert _sha(src) == before, "the original must stay byte-identical"

    text = _all_guide_text()
    # the exact sentence the app prints for this object, built from the engine's own numbers
    edge = item["edges"]
    assert f"Hangs {distance:.1f} mm past the {edge} edge" in text, "the guide quotes a distance the engine did not produce"
    assert "_placed_U1" in text, "the guide names the moved copy differently from the engine"


def test_printer_name_confidence_matches_the_guide():
    # An unrecognized printer name is only 'likely' a mismatch; the guide must not call it confirmed.
    # the printer name written into the guide's own example job (site/guide/tools/fixtures.py), not a copy of it here
    fixture = (ROOT / "site" / "guide" / "tools" / "fixtures.py").read_text(encoding="utf-8")
    other = re.search(r'example_other_printer\.gcode.*?"; printer_model = Snapmaker U1", "; printer_model = ([^"]+)"', fixture, re.S)
    assert other, "could not find the other-printer header in the guide fixture"
    unknown = post_slice._machine_match({"printer_model": other.group(1)}, {})
    assert unknown["title"] == "Sliced for a different printer"
    assert unknown["confidence"] == post_slice.LIKELY
    # A name for a printer Studio does know (and that is not the target) is confirmed.
    known = post_slice._machine_match({"printer_model": "Voron 2.4 250"}, {})
    assert known["title"] == "Sliced for a different printer"
    assert known["confidence"] == post_slice.CONFIRMED

    problems = {p["id"]: p for p in _guide("problems")}
    page = problems["sliced-for-different-printer"]
    assert page["certainty"] != "confirmed", "the page cannot be 'confirmed' while the example is only 'likely'"
    text = " ".join(_strings(page)).lower()
    assert "likely" in text and "recogni" in text
    # the exercise item built on this example names the same printer family the fixture writes
    items = _guide("examples")["unknown-vs-confirmed"]["items"]
    assert other.group(1).split()[0] in items[0]["text"]


def test_matching_header_is_confirmed_and_looks_right():
    ok = post_slice._machine_match({"printer_model": "Snapmaker U1"}, {})
    assert ok["result"] == "ok" and ok["confidence"] == post_slice.CONFIRMED
