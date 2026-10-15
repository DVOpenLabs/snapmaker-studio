"""The tracked-file guard catches tool output and local absolute paths (prof.out class)."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

GUARD = Path(__file__).parents[2] / "tools" / "check-source-independence.py"
BS = chr(92)
NL = chr(10)
NLB = NL.encode()
USERS = "Us" + "ers"


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


def _win(*parts: str, sep: str = BS) -> str:
    return "C:" + sep + sep.join(parts)


def _baselined(mod) -> tuple[str, str]:
    """A real approved (file, line) baseline entry whose line holds a Windows-style path."""
    return next(e for e in sorted(mod.LEAK_BASELINE)
                if "c:/" + "users/" in e[1] and "#" not in e[1] and len(e[1]) < 150)


def _leaks(problems: list[str], name: str) -> list[str]:
    return [p for p in problems if p.startswith(name + ":") and "local absolute path" in p]


def test_tracked_tool_output_is_a_violation(tmp_path):
    repo = _repo(tmp_path, {"backend/prof.out": bytes([0, 1]) + b"binary"})
    problems, _ = _guard().scan(repo)
    assert any("prof.out" in p and "tool output" in p for p in problems)


def test_a_local_absolute_path_in_a_new_file_is_a_violation(tmp_path):
    leak = _win("Users", "someone", "proj", "x.py").encode()
    repo = _repo(tmp_path, {"docs/new-note.md": b"see " + leak + b"\n"})
    problems, _ = _guard().scan(repo)
    assert any("docs/new-note.md" in p and "local absolute path" in p for p in problems)


def test_a_clean_tree_and_the_public_sample_path_pass(tmp_path):
    ok = _win("Users", "Public", "samples", "a.3mf").encode()
    repo = _repo(tmp_path, {"docs/ok.md": b"plain text\n" + ok})
    problems, _ = _guard().scan(repo)
    assert problems == []


def test_a_known_baseline_line_passes(tmp_path):
    mod = _guard()
    name, line = _baselined(mod)
    repo = _repo(tmp_path, {name: line.encode() + NLB})
    problems, _ = mod.scan(repo)
    assert _leaks(problems, name) == []


def test_a_baseline_entry_does_not_hide_a_different_path_in_the_same_file(tmp_path):
    mod = _guard()
    name, line = _baselined(mod)
    other = _win("Users", "intruder", "secret", "x.3mf")
    repo = _repo(tmp_path, {name: (line + NL + other + NL).encode()})
    problems, _ = mod.scan(repo)
    found = _leaks(problems, name)
    assert len(found) == 1 and "intruder" in found[0]


def test_a_longer_path_sharing_an_approved_prefix_fails(tmp_path):
    mod = _guard()
    name, line = _baselined(mod)
    for extension in (" OtherClient/model.3mf", "/more", "-sibling"):
        repo = _repo(tmp_path / ("e" + str(abs(hash(extension)))), {name: (line + extension).encode() + NLB})             if (tmp_path / ("e" + str(abs(hash(extension))))).mkdir() is None else None
        problems, _ = mod.scan(repo)
        assert _leaks(problems, name), extension


def test_unc_file_host_and_url_encoded_paths_are_found(tmp_path):
    forms = {
        "unc.md": BS + BS + "workstation" + BS + "Users" + BS + "Alice" + BS + "private" + BS + "model.3mf",
        "filehost.md": "file://workstation/" + USERS + "/Alice/private/model.3mf",
        "encoded.md": "C%3A%5C" + USERS + "%5CAlice%5Cprivate",
        "encoded2.md": "C%253A%255C" + USERS + "%255CAlice",
        "encodedfile.md": "file:///C%3A/" + USERS + "/Alice/x.3mf",
        "admin.md": BS + BS + "workstation" + BS + "C$" + BS + "Users" + BS + "Alice" + BS + "private" + BS + "model.3mf",
        "adminfile.md": "file://workstation/C$/" + USERS + "/Alice/private/model.3mf",
        "adminencoded.md": "file://workstation/C%24/" + USERS + "/Alice/x.3mf",
        "adminencodedunc.md": "%5C%5Cworkstation%5CC%24%5C" + USERS + "%5CAlice%5Cx",
        "adminlower.md": BS + BS + "WORKSTATION" + BS + "d$" + BS + "users" + BS + "alice" + BS + "x",
        "namedshare.md": BS + BS + "nas" + BS + "home" + BS + "STL Files" + BS + "private",
    }
    repo = _repo(tmp_path, {n: v.encode() + NLB for n, v in forms.items()})
    problems, _ = _guard().scan(repo)
    for name in forms:
        assert _leaks(problems, name), name


def test_an_https_url_naming_a_users_path_is_not_a_leak(tmp_path):
    repo = _repo(tmp_path, {"docs/link.md": ("see https://example.com/" + USERS + "/guide for details").encode() + NLB})
    problems, _ = _guard().scan(repo)
    assert _leaks(problems, "docs/link.md") == []


def test_case_and_separator_variants_of_a_leak_are_all_found(tmp_path):
    variants = {
        "a.md": _win("USERS", "Someone", "x"),
        "b.md": _win("users", "someone", "x", sep="/"),
        "c.md": _win("Users", "someone", "x", sep=BS + BS),
        "d.md": "d:" + BS + "stl files" + BS + "private",
        "e.md": "/HO" + "ME/someone/x",
    }
    repo = _repo(tmp_path, {n: v.encode() + b"\n" for n, v in variants.items()})
    problems, _ = _guard().scan(repo)
    for name in variants:
        assert _leaks(problems, name), name


def test_every_leak_on_a_line_is_reported_not_only_the_first(tmp_path):
    first = _win("Users", "one", "a").encode()
    second = _win("Users", "two", "b").encode()
    repo = _repo(tmp_path, {"docs/two.md": first + b" and " + second + b"\n"})
    problems, _ = _guard().scan(repo)
    assert len(_leaks(problems, "docs/two.md")) == 2


def test_a_content_exception_does_not_waive_the_leak_scan(tmp_path):
    mod = _guard()
    name = next(iter(mod.CONTENT_EXCEPTIONS))
    leak = _win("Users", "someone", "x").encode()
    repo = _repo(tmp_path, {name: b"credit line\n" + leak + b"\n"})
    problems, manifest = mod.scan(repo)
    assert _leaks(problems, name)
    assert name in manifest["content_exceptions"]


def test_a_content_exception_still_waives_the_reference_patterns(tmp_path):
    mod = _guard()
    name = next(iter(mod.CONTENT_EXCEPTIONS))
    ref = ("bambu" + "2" + "orca").encode()
    repo = _repo(tmp_path, {name: b"attribution: " + ref + b"\n"})
    problems, _ = mod.scan(repo)
    assert problems == []


def test_a_reference_pattern_in_an_ordinary_file_is_a_violation(tmp_path):
    ref = ("bambu" + "2" + "orca").encode()
    repo = _repo(tmp_path, {"docs/notes.md": b"see " + ref + b"\n"})
    problems, _ = _guard().scan(repo)
    assert any("docs/notes.md" in p and "prohibited reference" in p for p in problems)


def test_a_path_inside_a_nul_bearing_binary_suffix_file_is_found(tmp_path):
    leak = _win("Users", "someone", "x").encode()
    repo = _repo(tmp_path, {"assets/pic.png": bytes([0, 1, 2]) + leak + bytes([0])})
    problems, _ = _guard().scan(repo)
    assert _leaks(problems, "assets/pic.png")


def test_the_guard_passes_on_this_repository():
    root = GUARD.parents[1]
    problems, _ = _guard().scan(root)
    assert problems == []


# --- mutation checks: each weakening of the guard must be caught by the canary scenarios --------
def _mutant(tmp_path: Path, old: str, new: str):
    src = GUARD.read_text(encoding="utf-8")
    assert old in src, f"mutation anchor missing: {old!r}"
    path = tmp_path / "mutant_guard.py"
    path.write_text(src.replace(old, new), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("mutant_guard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _canaries_all_caught(mod, tmp_path: Path) -> bool:
    """True only when every canary scenario still produces its leak problem."""
    name, line = _baselined(mod)
    exc = next(iter(mod.CONTENT_EXCEPTIONS))
    scenarios = {
        name: (line + NL + _win("Users", "intruder", "x") + NL + line + " OtherClient/model.3mf").encode(),
        "case.md": _win("USERS", "Someone", "x").encode(),
        "two.md": (_win("Users", "one", "a") + " " + _win("Users", "two", "b")).encode(),
        exc: b"credit" + NLB + _win("Users", "someone", "x").encode(),
        "pic.png": bytes([0, 1]) + _win("Users", "someone", "x").encode() + bytes([0]),
        "unc.md": (BS + BS + "host" + BS + "Users" + BS + "a" + BS + "b").encode(),
        "url.md": ("C%3A%5C" + USERS + "%5CAlice%5Cprivate").encode(),
        "admin.md": (BS + BS + "host" + BS + "C$" + BS + "Users" + BS + "a" + BS + "b").encode(),
        "adminurl.md": ("file://host/C$/" + USERS + "/a/b").encode(),
    }
    (tmp_path / "canary").mkdir(exist_ok=True)
    repo = _repo(tmp_path / "canary", scenarios)
    problems, _ = mod.scan(repo)
    if len(_leaks(problems, "two.md")) != 2 or len(_leaks(problems, name)) != 2:
        return False
    return all(_leaks(problems, n) for n in scenarios)


def test_the_unmutated_guard_catches_every_canary(tmp_path):
    assert _canaries_all_caught(_guard(), tmp_path)


import pytest  # noqa: E402

MUTATIONS = {
    "case-sensitive leak rules": ("_TAIL, re.IGNORECASE)", "_TAIL)"),
    "baseline keyed by file name only": ("if (name, key) not in LEAK_BASELINE:",
                                         "if name not in {f for f, _ in LEAK_BASELINE}:"),
    "baseline matched by prefix": ("if (name, key) not in LEAK_BASELINE:",
                                   "if not any(f == name and key.startswith(k) for f, k in LEAK_BASELINE):"),
    "content exception skips the leak scan": ("for line, token, key in leak_hits(leak_text):",
                                              "for line, token, key in ([] if name in CONTENT_EXCEPTIONS else leak_hits(leak_text)):"),
    "binary-suffix files skip the leak scan": ("for line, token, key in leak_hits(leak_text):",
                                               "for line, token, key in (leak_hits(leak_text) if is_text else []):"),
    "only the first hit per rule is reported": ("for m in rule.finditer(line):",
                                                "for m in list(rule.finditer(line))[:1]:"),
    "url-encoded paths are not decoded": ("decoded = unquote(line)", "decoded = line"),
    "administrative-share segments not allowed": ("){0,2}?", "){0}?"),
    "UNC and file-host rule removed": ("    re.compile(_UNC + _USERS + _TAIL, re.IGNORECASE)," + NL, ""),
}


@pytest.mark.parametrize("label", sorted(MUTATIONS))
def test_a_weakened_guard_is_detected(tmp_path, label):
    old, new = MUTATIONS[label]
    assert not _canaries_all_caught(_mutant(tmp_path, old, new), tmp_path), label


def test_https_and_plain_unc_negatives_stay_clean(tmp_path):
    lines = {
        "https.md": "see https://host/C$/" + USERS + "/guide and //cdn.example/assets/a.js",
        "bare.md": BS + BS + "host" + BS + "share" + BS + "docs" + BS + "readme.txt",
    }
    repo = _repo(tmp_path, {n: v.encode() + NLB for n, v in lines.items()})
    problems, _ = _guard().scan(repo)
    for name in lines:
        assert _leaks(problems, name) == [], name
