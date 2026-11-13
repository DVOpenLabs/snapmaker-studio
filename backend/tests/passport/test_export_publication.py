"""R4-F1: `passport export -o` must publish into the directory it validated, even if that directory
(or an ancestor) is swapped between the check and the write. Evidence label: fixture-tested.

The swap is simulated deterministically. Both the old write path (`tempfile.mkstemp` in the validated
directory) and the new one (`safe_publish._after_pin`, after the directory is pinned) trigger it exactly
once, immediately before the first file is created. The directory swap is a rename of the validated
directory plus a rename of a decoy into its place; on Windows the new code's pinned handle makes the
first rename fail, which is the protection under test.
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest
from click.testing import CliRunner

from snapstudio_core import passport_cli

try:
    from snapstudio_core import safe_publish
except ImportError:                                  # the pre-fix tree: let the behavioural assertion fail instead
    safe_publish = None


def _run(*args):
    return CliRunner().invoke(passport_cli.passport, list(args))


@pytest.fixture
def layout(tmp_path):
    victim = tmp_path / "victim"
    decoy = tmp_path / "decoy"
    victim.mkdir()
    decoy.mkdir()
    (victim / "orig.marker").write_text("victim")
    (decoy / "decoy.marker").write_text("decoy")
    source = tmp_path / "part.3mf"
    source.write_bytes(b"synthetic original")
    return tmp_path, victim, decoy, source


def _install_swap(monkeypatch, victim, decoy):
    moved = victim.with_name("victim_moved")
    state = {"armed": True, "swapped": False}

    def swap():
        if not state["armed"]:
            return
        state["armed"] = False
        try:
            os.rename(victim, moved)
            os.rename(decoy, victim)
            state["swapped"] = True
        except OSError:
            pass                                      # a pinned directory refuses to be renamed (Windows)

    real_mkstemp = tempfile.mkstemp

    def mkstemp(*args, **kwargs):
        swap()
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(tempfile, "mkstemp", mkstemp)
    if safe_publish is not None:
        monkeypatch.setattr(safe_publish, "_after_pin", swap)
    return state, moved


def test_a_directory_swapped_after_validation_does_not_redirect_the_passport(layout, monkeypatch):
    tmp_path, victim, decoy, source = layout
    state, moved = _install_swap(monkeypatch, victim, decoy)
    out = victim / "job.passport.json"

    result = _run("export", "--original", str(source), "-o", str(out))

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["written"] == "job.passport.json"
    holders = [d for d in (victim, moved) if (d / "job.passport.json").exists()]
    assert len(holders) == 1
    assert (holders[0] / "orig.marker").exists(), "the passport landed in the swapped-in directory"
    assert not [p for p in (victim, moved) if (p / "decoy.marker").exists() and (p / "job.passport.json").exists()]
    assert not list(holders[0].glob("*.tmp")) and not list(holders[0].glob(".*.tmp"))


def test_export_writes_a_new_file_and_refuses_an_existing_one(tmp_path):
    source = tmp_path / "part.3mf"
    source.write_bytes(b"x")
    out = tmp_path / "p.json"
    first = _run("export", "--original", str(source), "-o", str(out))
    assert first.exit_code == 0 and json.loads(out.read_text(encoding="utf-8"))["passport_id"]
    before = out.read_bytes()
    second = _run("export", "--original", str(source), "-o", str(out))
    assert second.exit_code == 1 and json.loads(second.output)["error"]["code"] == "output_exists"
    assert out.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["p.json", "part.3mf"]


@pytest.mark.skipif(safe_publish is None, reason="needs safe_publish")
def test_publish_new_file_never_replaces_and_leaves_no_temporary(tmp_path):
    target = tmp_path / "a.json"
    safe_publish.publish_new_file(str(target), b"one")
    with pytest.raises(FileExistsError):
        safe_publish.publish_new_file(str(target), b"two")
    assert target.read_bytes() == b"one"
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


@pytest.mark.skipif(safe_publish is None, reason="needs safe_publish")
@pytest.mark.parametrize("name", ["", "..", "a/b", "a\\b"])
def test_publish_refuses_a_name_that_is_not_a_plain_file_name(tmp_path, name):
    with pytest.raises(safe_publish.UnsafeOutput):
        safe_publish._check_name(name)


@pytest.mark.skipif(safe_publish is None, reason="needs safe_publish")
def test_a_directory_that_resolves_to_a_network_location_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(safe_publish.localpath, "_reaches_network", lambda path, depth=0: True)
    with pytest.raises(safe_publish.UnsafeOutput):
        safe_publish.publish_new_file(str(tmp_path / "a.json"), b"x")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(safe_publish is None, reason="needs safe_publish")
def test_a_missing_output_directory_is_refused_not_created(tmp_path):
    with pytest.raises(safe_publish.UnsafeOutput):
        safe_publish.publish_new_file(str(tmp_path / "nope" / "a.json"), b"x")
    assert not (tmp_path / "nope").exists()


# ------------------------------------------------------------ in-place link on an empty directory

def _make_junction_in_place(directory, target) -> bool:
    """Turn the EMPTY `directory` into a junction to `target` without renaming it (Windows only)."""
    import ctypes
    import struct
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                         wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                         wintypes.LPVOID]
    kernel32.DeviceIoControl.restype = wintypes.BOOL
    h = kernel32.CreateFileW(str(directory), 0x40000000, 0x7, None, 3, 0x02000000 | 0x00200000, None)
    if h in (None, wintypes.HANDLE(-1).value):
        return False
    try:
        substitute = ("\\??\\" + str(target)).encode("utf-16-le")
        printable = str(target).encode("utf-16-le")
        path_buffer = substitute + b"\0\0" + printable + b"\0\0"
        header = struct.pack("<HHHH", 0, len(substitute), len(substitute) + 2, len(printable))
        body = header + path_buffer
        data = struct.pack("<IHH", 0xA0000003, len(body), 0) + body
        returned = wintypes.DWORD(0)
        return bool(kernel32.DeviceIoControl(h, 0x000900A4, data, len(data), None, 0, ctypes.byref(returned), None))
    finally:
        kernel32.CloseHandle(h)


@pytest.mark.skipif(os.name != "nt", reason="an in-place junction on an empty directory is a Windows case")
def test_an_empty_directory_turned_into_a_junction_after_validation_does_not_redirect_the_passport(tmp_path, monkeypatch):
    victim = tmp_path / "victim"
    decoy = tmp_path / "decoy"
    victim.mkdir()
    decoy.mkdir()
    source = tmp_path / "part.3mf"
    source.write_bytes(b"synthetic original")
    state = {"armed": True, "linked": None}

    def link():
        if state["armed"]:
            state["armed"] = False
            state["linked"] = _make_junction_in_place(victim, decoy)

    real_mkstemp = tempfile.mkstemp

    def mkstemp(*args, **kwargs):
        link()
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(tempfile, "mkstemp", mkstemp)
    if safe_publish is not None:
        monkeypatch.setattr(safe_publish, "_after_pin", link)

    result = _run("export", "--original", str(source), "-o", str(victim / "job.passport.json"))

    assert state["linked"], "the test could not create the in-place junction"
    assert not list(decoy.iterdir()), "the passport (or a temporary) was written through the junction"
    assert result.exit_code == 1 and json.loads(result.output)["error"]["code"] in ("bad_output", "write_failed")


def test_an_ancestor_swapped_after_validation_does_not_redirect_the_passport(tmp_path, monkeypatch):
    ancestor = tmp_path / "a"
    victim = ancestor / "b"
    victim.mkdir(parents=True)
    (victim / "orig.marker").write_text("victim")
    decoy_tree = tmp_path / "decoy_a"
    (decoy_tree / "b").mkdir(parents=True)
    source = tmp_path / "part.3mf"
    source.write_bytes(b"synthetic original")
    moved = tmp_path / "a_moved"
    state = {"armed": True}

    def swap():
        if not state["armed"]:
            return
        state["armed"] = False
        try:
            os.rename(ancestor, moved)
            os.rename(decoy_tree, ancestor)
        except OSError:
            pass                                      # Windows: an open descendant handle blocks the rename

    real_mkstemp = tempfile.mkstemp

    def mkstemp(*args, **kwargs):
        swap()
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(tempfile, "mkstemp", mkstemp)
    if safe_publish is not None:
        monkeypatch.setattr(safe_publish, "_after_pin", swap)

    result = _run("export", "--original", str(source), "-o", str(victim / "job.passport.json"))

    assert result.exit_code == 0, result.output
    holders = [d for d in (victim, moved / "b") if (d / "job.passport.json").exists()]
    assert len(holders) == 1 and (holders[0] / "orig.marker").exists()
    assert not (ancestor / "b" / "job.passport.json").exists() or (ancestor / "b" / "orig.marker").exists()
