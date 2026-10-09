"""Guard: guide statements that depend on engine behavior are checked against the engine.

The user guide (site/guide) is hand-written. Its own tests check structure and
interaction, and cannot know what the engine does. These tests run the engine on
the example project and read the values from it, then require the guide to agree.
They do not copy the guide's answers: the expected facts come from the engine.

What they establish: the placement example's distance and output name match what
the engine really produces, the original stays byte-identical, and the guide's
printer-name explanation matches the confidence the engine actually assigns.
What they cannot establish: that the prose around those facts is well explained,
that a source is the right source, honest review dates, paraphrased overclaims,
screen-reader behavior, or anything about a physical printer or Snapmaker Orca.
"""
import hashlib
import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

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


ENGINE_FACTS = {
    "setting-why": ("engine-reason", "backend:rules.apply_clamps"),
    "size-or-placement": ("placement-move", "backend:plate_placement.EDGE_MARGIN_MM"),
    "unknown-compatible": ("unknown-gap", "backend:post_slice._machine_match"),
    "sliced-for-u1": ("sliced-header", "backend:post_slice._machine_match"),
    "original-unchanged": ("copy-only", "test:backend/tests/test_guide_claims.py::test_original_unchanged_answer_uses_real_convert_path"),
    "print-success": ("readiness-estimate", "backend:success_predict.predict"),
}


def check_answers(manifest, pages, tmp_path):
    """Check code-derived tokens and ownership; this cannot judge prose clarity, source fitness, dates, paraphrased overclaims, physical behavior, Orca behavior, or screen readers."""
    from snapstudio_core import success_predict
    from snapstudio_core.convert import convert_to_u1
    from snapstudio_core.rules import apply_clamps, load_rules
    by_id = {answer["id"]: answer for answer in manifest["answers"]}
    table = {
        "setting-why": lambda: ("engine-reason", "backend:rules.apply_clamps", {"valid range", "U1 default"}),
        "size-or-placement": lambda: ("placement-move", "backend:plate_placement.EDGE_MARGIN_MM", {"one move cannot fix the layout", "multi-plate"}),
        "unknown-compatible": lambda: ("unknown-gap", "backend:post_slice._machine_match", {"does not guess", "no printer is connected"}),
        "sliced-for-u1": lambda: ("sliced-header", "backend:post_slice._machine_match", {"Studio reads the header", "not simulated"}),
        "original-unchanged": lambda: ("copy-only", "test:backend/tests/test_guide_claims.py::test_original_unchanged_answer_uses_real_convert_path", {"SnapmakerU1", "original file is not modified"}),
        "print-success": lambda: ("readiness-estimate", "backend:success_predict.predict", {"takes points off for each risk signal", "not a probability of print success", "at least 75"}),
    }
    assert set(table) == set(ENGINE_FACTS)
    assert set(ENGINE_FACTS) | {"kept-orca"} == set(by_id)
    asserted = set()
    for answer_id, (expected_id, expected_derive, expected_tokens) in ((a, table[a]()) for a in table):
        answer = by_id[answer_id]
        assert len(answer["requiredFacts"]) == 1
        fact = answer["requiredFacts"][0]
        assert (fact["id"], fact["derive"]) == (expected_id, expected_derive)
        assert set(fact["tokens"]) == expected_tokens
        assert all(token in json.dumps(pages) for token in expected_tokens)
        asserted.add(fact["id"])
    # Exercise real behavior for the facts whose tokens summarize it.
    clamp = apply_clamps({"prime_tower_brim_width": "-1"}, load_rules())
    assert "valid range" in clamp[0]["explanation"] and "U1 default" in clamp[0]["explanation"]
    assert clamp[0]["kind"] == "engine"
    assert post_slice._machine_match({"printer_model": "Snapmaker U1"}, {})["confidence"] == post_slice.CONFIRMED
    assert post_slice._machine_match({"printer_model": "not a known printer"}, {})["confidence"] == post_slice.LIKELY
    assert success_predict.predict(readiness={"ready": True})["likelihood"] == 100
    src = tmp_path / "answer-source.3mf"
    shutil.copy(ROOT / "examples" / "demo_offplate_foreign.3mf", src)
    before = _sha(src)
    out = convert_to_u1(str(src), out_dir=str(tmp_path), dry_run=False)
    assert out.output_name.endswith("_SnapmakerU1.3mf") and _sha(src) == before
    assert asserted == {fact["id"] for answer in manifest["answers"] for fact in answer["requiredFacts"] if fact["derive"].startswith(("backend:", "test:"))}
    return True


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


def test_original_unchanged_answer_uses_real_convert_path(tmp_path):
    """The conversion path preserves the input; this does not establish prose clarity, source choice, dates, physical behavior, paraphrased overclaims, or screen-reader behavior."""
    from snapstudio_core.convert import convert_to_u1
    src = tmp_path / "source.3mf"
    shutil.copy(ROOT / "examples" / "demo_offplate_foreign.3mf", src)
    before = _sha(src)
    result = convert_to_u1(str(src), out_dir=str(tmp_path), dry_run=False)
    assert result.output_name.endswith("_SnapmakerU1.3mf")
    assert (tmp_path / result.output_name).exists()
    assert _sha(src) == before


def _resolve_engine_derive(derive, package="snapstudio_core"):
    """Resolve a backend: or test: derive for real. Raises AttributeError or returns None when it does not resolve."""
    if derive.startswith("backend:"):
        module_name, symbol = derive[8:].rsplit(".", 1)
        return getattr(importlib.import_module(f"{package}.{module_name}"), symbol)
    if derive.startswith("test:"):
        file_name, test_name = derive[5:].split("::", 1)
        path = (ROOT / file_name) if not Path(file_name).is_absolute() else Path(file_name)
        if not path.is_file():
            return None
        if path.resolve() == Path(__file__).resolve():
            module = sys.modules[__name__]  # this module is already loaded; never execute it twice
        else:
            module_name = "_derive_" + hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:12]
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        member = getattr(module, test_name, None)
        return member if callable(member) else None


def test_every_manifest_derive_resolves_to_code():
    """Resolution is mechanical; it cannot establish prose clarity, source fitness, honest dates, physical printer or Snapmaker Orca behavior, paraphrased overclaims, or screen-reader behavior. App derives are resolved in guideClaims.test.ts."""
    seen = 0
    for answer in _guide("answers")["answers"]:
        for fact in answer["requiredFacts"]:
            if fact["derive"].startswith(("backend:", "test:")):
                assert _resolve_engine_derive(fact["derive"]) is not None, fact["derive"]
                seen += 1
            else:
                assert fact["derive"].startswith("app:"), fact["derive"]
    assert seen >= 5


def test_engine_derive_resolution_rejects_near_misses(tmp_path, monkeypatch):
    """Real getattr resolution: a name that only appears in a comment, a comparison or a docstring is not a symbol."""
    package = tmp_path / "fixturepkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mod.py").write_text(
        '"""Module docstring mentions docstring_only."""\n'
        "# comment_only is described here\n"
        "REAL = 1\n"
        "def real_fn():\n"
        '    """real_fn mentions inner_docstring."""\n'
        "    return REAL == 1\n"
        "async def real_async():\n"
        "    return 1\n"
        "value = REAL\n"
        "check = (missing_eq == 1) if False else None\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    assert _resolve_engine_derive("backend:mod.REAL", package="fixturepkg") == 1
    assert _resolve_engine_derive("backend:mod.real_async", package="fixturepkg")
    for name in ["REA", "real_f", "comment_only", "docstring_only", "inner_docstring", "missing_eq", "real_fn_"]:
        with pytest.raises(AttributeError):
            _resolve_engine_derive(f"backend:mod.{name}", package="fixturepkg")


def test_test_derive_resolution_imports_the_real_function(tmp_path):
    """A test: derive resolves by importing the file and calling getattr, so text that only looks like a definition fails."""
    ref = "test:backend/tests/test_guide_claims.py::"
    assert callable(_resolve_engine_derive(ref + "test_original_unchanged_answer_uses_real_convert_path"))
    assert _resolve_engine_derive(ref + "test_original_unchanged_answer_uses_real_convert_pat") is None
    assert _resolve_engine_derive("test:backend/tests/no_such_file.py::test_x") is None
    fixture = tmp_path / "fixture_tests.py"
    fixture.write_text(
        '"""def spoofed_in_docstring(): pass"""\n'
        "TEXT = \"\"\"\ndef spoofed_test():\n    pass\n\"\"\"\n"
        "ESCAPED = \"\\\"\\\"\\\" def spoofed_escaped(): pass\"\n"
        "# def spoofed_comment(): pass\n"
        "NOT_CALLABLE = 5\n"
        "def test_real():\n    return 1\n",
        encoding="utf-8",
    )
    ref = f"test:{fixture}::"
    assert _resolve_engine_derive(ref + "test_real")() == 1
    for name in ["spoofed_test", "spoofed_in_docstring", "spoofed_escaped", "spoofed_comment", "test_rea", "NOT_CALLABLE", "TEXT"]:
        assert _resolve_engine_derive(ref + name) is None, name


def test_golden_answer_engine_assertion_table_has_exact_manifest_coverage(tmp_path):
    """The table checks code facts only; it cannot establish prose clarity, source fitness, honest dates, physical printer or Snapmaker Orca behavior, paraphrased overclaims, or screen readers."""
    assert check_answers(_guide("answers"), {name: _guide(name) for name in ("path", "tasks", "problems")}, tmp_path)


def test_print_readiness_is_a_risk_signal_score_not_a_measured_chance():
    """The formula check cannot establish that the score predicts physical printer behavior, prose clarity, source fitness, honest dates, paraphrased overclaims, or screen-reader behavior."""
    from snapstudio_core import success_predict
    baseline = success_predict.predict(readiness={"ready": True})
    one_warning = success_predict.predict(readiness={"ready": False, "warnings": ["one"]})
    two_warnings = success_predict.predict(readiness={"ready": False, "warnings": ["one", "two"]})
    assert baseline["likelihood"] == 100
    assert one_warning["likelihood"] == 100 - (20 + 5 * 1) == 75
    assert two_warnings["likelihood"] == 100 - (20 + 5 * 2) == 70
    assert one_warning["band"] == "likely" and two_warnings["band"] == "uncertain"
    assert success_predict.predict(readiness={"ready": False, "warnings": []})["band"] == "likely"
    assert success_predict._band(75) == "likely" and success_predict._band(74) == "uncertain"
    assert "Likely to print" in success_predict._verdict(80, "likely")


def _run_guide_build(content, output):
    env = os.environ.copy()
    env["SNAPSTUDIO_GUIDE_CONTENT"] = str(content)
    env["SNAPSTUDIO_GUIDE_OUTPUT"] = str(output)
    return subprocess.run(["node", "tools/build.mjs"], cwd=ROOT / "site" / "guide", env=env, capture_output=True, text=True)


def test_build_rejects_invalid_answers_and_source_refs():
    """These negative cases test the validator; they cannot establish prose clarity, source fitness, honest dates, physical behavior, paraphrased overclaims, or screen readers."""
    with tempfile.TemporaryDirectory() as raw:
        content = Path(raw) / "content"
        shutil.copytree(GUIDE, content)
        output = Path(raw) / "index.html"
        answers_path = content / "answers.json"
        original = json.loads(answers_path.read_text(encoding="utf-8"))
        cases = []
        bad = json.loads(json.dumps(original)); bad["answers"][0]["requiredFacts"] = []; cases.append(bad)
        bad = json.loads(json.dumps(original)); bad["answers"][0]["unknown"] = True; cases.append(bad)
        bad = json.loads(json.dumps(original)); bad["answers"][1]["requiredFacts"][0]["id"] = bad["answers"][0]["requiredFacts"][0]["id"]; cases.append(bad)
        for bad in cases:
            answers_path.write_text(json.dumps(bad), encoding="utf-8")
            assert _run_guide_build(content, output).returncode != 0
        # the build checks shape and file existence only; symbol resolution is tested separately above
        for derive in ["bogus:thing", "backend:no_such_module.symbol", "backend:rules.not-an-identifier", "backend:rules", "app:desktop/src/lib/no_such_file.ts#X", "app:desktop/src/lib/fidelity.ts", "app:desktop/src/lib/fidelity.ts#not-an-id", "test:backend/tests/no_such_file.py::test_x", "test:backend/tests/test_guide_claims.py::"]:
            bad = json.loads(json.dumps(original)); bad["answers"][0]["requiredFacts"][0]["derive"] = derive
            answers_path.write_text(json.dumps(bad), encoding="utf-8")
            assert _run_guide_build(content, output).returncode != 0
        path_path = content / "path.json"
        path_data = json.loads(path_path.read_text(encoding="utf-8"))
        source_page_index = next(i for i, page in enumerate(path_data) if page.get("sources"))
        for ref in [
            "https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.5.0/backend/DOES_NOT_EXIST.py",
            "https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.5.0/desktop/src/lib/fidelity.ts#DOES_NOT_EXIST",
            "https://github.com/DVOpenLabs/snapmaker-studio/blob/main/backend/snapstudio_core/rules.py",
            "https://github.com/DVOpenLabs/snapmaker-studio/blob/v1.5.0/../backend/snapstudio_core/rules.py",
            "/absolute/backend/snapstudio_core/rules.py",
            "@does_not_exist",
        ]:
            bad_path = json.loads(json.dumps(path_data)); bad_path[source_page_index]["sources"][0]["ref"] = ref
            path_path.write_text(json.dumps(bad_path), encoding="utf-8")
            assert _run_guide_build(content, output).returncode != 0
        path_path.write_text(json.dumps(path_data), encoding="utf-8")


@pytest.mark.parametrize("answer_id,changed", [
    ("size-or-placement", "Studio shrinks the object to fit"),
    ("sliced-for-u1", "Studio simulates every command"),
    ("original-unchanged", "Studio edits your original in place"),
])
def test_mutated_manifest_and_page_fails_real_engine_checker(tmp_path, answer_id, changed):
    """Mutation checks call check_answers, the real engine-layer checker; they cannot judge general prose clarity or accessibility."""
    manifest = json.loads(json.dumps(_guide("answers")))
    pages = {name: _guide(name) for name in ("path", "tasks", "problems")}
    answer = next(a for a in manifest["answers"] if a["id"] == answer_id)
    answer["requiredFacts"][0]["tokens"] = [changed]
    move = next(t for t in pages["tasks"]["tasks"] if t["id"] == "move-onto-plate")
    prepare = next(t for t in pages["tasks"]["tasks"] if t["id"] == "prepare-u1-copy")
    if answer_id == "size-or-placement": move["differs"][0]["then"] = changed
    elif answer_id == "sliced-for-u1": pages["path"][5]["means"][1]["meaning"] = changed
    else: prepare["success"][0] = changed
    import pytest
    with pytest.raises(AssertionError):
        check_answers(manifest, pages, tmp_path)


def test_extra_contradictory_fact_fails_real_engine_checker(tmp_path):
    """An extra fact must fail the real checker; this cannot judge general prose clarity or accessibility."""
    manifest = json.loads(json.dumps(_guide("answers")))
    pages = {name: _guide(name) for name in ("path", "tasks", "problems")}
    manifest["answers"][0]["requiredFacts"].append({"id": "contradiction", "derive": "backend:rules.apply_clamps", "tokens": ["shrinks"]})
    import pytest
    with pytest.raises(AssertionError):
        check_answers(manifest, pages, tmp_path)


def test_renamed_fact_id_fails_real_engine_checker_from_fresh_manifest(tmp_path):
    """A fact-id mutation calls the real checker; it cannot establish prose clarity, source fitness, dates, physical behavior, Orca behavior, paraphrased overclaims, or screen readers."""
    manifest = json.loads(json.dumps(_guide("answers")))
    pages = {name: _guide(name) for name in ("path", "tasks", "problems")}
    manifest["answers"][0]["requiredFacts"][0]["id"] = "renamed-fact"
    with pytest.raises(AssertionError):
        check_answers(manifest, pages, tmp_path)


def test_dropped_token_fails_real_engine_checker_without_page_mutation(tmp_path):
    """A pure token deletion calls the real checker; it cannot establish prose clarity, source fitness, dates, physical behavior, Orca behavior, paraphrased overclaims, or screen readers."""
    manifest = json.loads(json.dumps(_guide("answers")))
    pages = {name: _guide(name) for name in ("path", "tasks", "problems")}
    manifest["answers"][5]["requiredFacts"][0]["tokens"] = ["SnapmakerU1"]
    with pytest.raises(AssertionError):
        check_answers(manifest, pages, tmp_path)
