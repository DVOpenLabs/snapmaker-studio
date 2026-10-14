"""The tracked-file guard catches tool output and local absolute paths (prof.out class)."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

GUARD = Path(__file__).parents[2] / "tools" / "check-source-independence.py"
BS = chr(92)


def _guard():
    spec = importlib.util.spec_from_file_location("check_source_independence", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _repo(tmp_path: Path, files: dict[str, bytes]) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for name, data in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def test_tracked_tool_output_is_a_violation(tmp_path):
    repo = _repo(tmp_path, {"backend/prof.out": bytes([0, 1]) + b"binary"})
    problems, _ = _guard().scan(repo)
    assert any("prof.out" in p and "tool output" in p for p in problems)


def test_a_local_absolute_path_in_a_new_file_is_a_violation(tmp_path):
    leak = ("C:" + BS + "Users" + BS + "someone" + BS + "proj" + BS + "x.py").encode()
    repo = _repo(tmp_path, {"docs/new-note.md": b"see " + leak + b"\n"})
    problems, _ = _guard().scan(repo)
    assert any("docs/new-note.md" in p and "local absolute path" in p for p in problems)


def test_a_clean_tree_and_the_public_sample_path_pass(tmp_path):
    ok = ("C:" + BS + "Users" + BS + "Public" + BS + "samples" + BS + "a.3mf").encode()
    repo = _repo(tmp_path, {"docs/ok.md": b"plain text\n" + ok})
    problems, _ = _guard().scan(repo)
    assert problems == []
