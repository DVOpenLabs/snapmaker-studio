import os
import sys
import tempfile
import threading
import types

import pytest

from snapstudio_api import _lifeline


def _forbid_thread(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("lifeline should not have started a watcher thread")
    monkeypatch.setattr(_lifeline.threading, "Thread", _boom)


def test_noop_without_env_var(monkeypatch):
    monkeypatch.delenv("SNAPSTUDIO_PARENT_LIFELINE", raising=False)
    _forbid_thread(monkeypatch)
    _lifeline.start_parent_lifeline()


def test_noop_wrong_env_value(monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_PARENT_LIFELINE", "not-the-right-value")
    _forbid_thread(monkeypatch)
    _lifeline.start_parent_lifeline()


def _os_as(monkeypatch, name, **overrides):
    """Give _lifeline its own view of `os` that reports `name`.

    Replaces the module's reference only, so os.name and os.fstat stay real for
    pytest and everything else running in the process."""
    attrs = {k: getattr(os, k) for k in ("environ", "fstat", "read", "_exit")}
    attrs["name"] = name
    attrs.update(overrides)
    shim = types.SimpleNamespace(**attrs)
    monkeypatch.setattr(_lifeline, "os", shim)


def test_noop_on_non_posix(monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_PARENT_LIFELINE", "stdin-v1")
    _os_as(monkeypatch, "nt")
    _forbid_thread(monkeypatch)
    read_fd, write_fd = os.pipe()  # a real pipe, so only the os.name check can stop the watcher
    try:
        _lifeline.start_parent_lifeline(fd=read_fd)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_noop_when_stdin_is_not_a_pipe(monkeypatch):
    # A dev-mode launch (or pytest itself) has a real terminal or a regular
    # file on stdin, never a pipe — the lifeline must never block on that.
    # Uses a real regular-file descriptor, so nothing global is patched.
    monkeypatch.setenv("SNAPSTUDIO_PARENT_LIFELINE", "stdin-v1")
    _os_as(monkeypatch, "posix")
    _forbid_thread(monkeypatch)
    with tempfile.TemporaryFile() as regular:
        _lifeline.start_parent_lifeline(fd=regular.fileno())


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pipe/fd semantics only")
def test_watcher_exits_when_stdin_pipe_reaches_eof(monkeypatch):
    # Simulates the real contract: the desktop shell holds a pipe's write end
    # open as this process's stdin and never writes to it. Closing that write
    # end (standing in for the parent process dying, which closes it exactly
    # the same way via exit_files()) must trigger the exit path.
    #
    # Passes a real pipe fd via the `fd` parameter rather than monkeypatching
    # os.fstat/os.read themselves: those are the exact names
    # start_parent_lifeline calls internally, so a lambda that calls the real
    # os.fstat/os.read to implement the patch would recurse into itself.
    monkeypatch.setenv("SNAPSTUDIO_PARENT_LIFELINE", "stdin-v1")
    read_fd, write_fd = os.pipe()
    exited = threading.Event()
    started_threads = []
    real_thread_cls = _lifeline.threading.Thread

    def fake_exit(_code):
        exited.set()

    def capturing_thread(*args, **kwargs):
        # Capture the watcher thread so this test can join() it before
        # closing read_fd — otherwise a slow-scheduled watcher could still be
        # inside its os.read() call on read_fd after this test moves on,
        # racing the fd's reuse by a later test, or (if it fires very late)
        # calling the REAL os._exit after monkeypatch has already restored it.
        t = real_thread_cls(*args, **kwargs)
        started_threads.append(t)
        return t

    _os_as(monkeypatch, os.name, _exit=fake_exit)
    monkeypatch.setattr(_lifeline.threading, "Thread", capturing_thread)
    try:
        _lifeline.start_parent_lifeline(fd=read_fd)
        os.close(write_fd)  # last write-end copy closes -> EOF on the read end
        assert exited.wait(timeout=3), "watcher thread did not exit on stdin EOF"
        assert started_threads, "lifeline did not start a watcher thread"
        started_threads[0].join(timeout=3)
        assert not started_threads[0].is_alive(), "watcher thread did not finish after firing"
    finally:
        os.close(read_fd)
