"""Linux parent-death lifeline: exit the sidecar the instant its parent dies.

`_watch_parent_then_exit` in `server.py` already covers Windows: it waits on
a HANDLE to the parent process, and any exit path (close, crash, kill)
satisfies that wait. Linux has no single primitive with the same guarantee
available to a plain child process. The desktop shell separately arms
PR_SET_PDEATHSIG on this process before it execs (see
`desktop/src-tauri/src/sidecar.rs::configure_linux_lifecycle`), but signal
delivery is not the only thing that can go wrong in the fork()-to-exec()
window before that is armed.

The one guarantee that never fails: on ANY exit path a process takes —
normal, crash, or SIGKILL — the kernel closes every file descriptor it held,
unconditionally (`exit_files()`). The desktop shell keeps a pipe's write end
open as this process's stdin for the app's entire lifetime and never writes
to it. Reading stdin here blocks until that write end closes, which is EOF,
which is parent death, by construction — no delivery step to miss.

No-op unless SNAPSTUDIO_PARENT_LIFELINE=stdin-v1 is set (only the Linux prod
sidecar launch sets it) and stdin is actually a pipe — so this never blocks
on a real terminal in dev mode or under pytest.
"""
from __future__ import annotations
import os
import stat
import threading


def start_parent_lifeline(fd: int = 0) -> None:
    """`fd` defaults to real stdin; tests pass a real pipe fd instead so they
    exercise the actual blocking-read/EOF behavior without patching `os`
    itself (patching `os.fstat`/`os.read` here would recurse: those exact
    names are what this function calls internally)."""
    if os.environ.get("SNAPSTUDIO_PARENT_LIFELINE") != "stdin-v1":
        return
    if os.name != "posix":
        return
    try:
        mode = os.fstat(fd).st_mode
    except OSError:
        return
    if not stat.S_ISFIFO(mode):
        return

    def _watch() -> None:
        try:
            os.read(fd, 1)  # blocks; any read at all — including EOF (b"") — means exit
        except OSError:
            pass
        os._exit(0)

    threading.Thread(target=_watch, name="parent-lifeline", daemon=True).start()
