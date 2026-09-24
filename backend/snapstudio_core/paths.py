"""Local-first data directory resolution, shared by the API layer and the core.

Lives in the core (not the API) so both `snapstudio_api.service` and
`snapstudio_core.diagnostics` can call the same resolver without diagnostics
importing the API layer.
"""
from __future__ import annotations
import os
import sys


def data_dir(explicit: str | None = None, *, create: bool = True) -> str:
    """Resolve, and by default create, the local data directory.

    Windows: unchanged from prior behaviour — ``%LOCALAPPDATA%\\SnapmakerStudio``,
    falling back to ``~`` if LOCALAPPDATA is unset.
    Linux: XDG Base Directory spec — ``$XDG_DATA_HOME/SnapmakerStudio``, falling
    back to ``~/.local/share/SnapmakerStudio`` (the XDG spec requires an absolute
    path; a relative ``XDG_DATA_HOME`` is treated as unset rather than resolved
    against the current working directory).
    Other platforms (e.g. macOS): unchanged from prior behaviour — ``~/SnapmakerStudio``.
    All platforms: ``SNAPSTUDIO_DATA_DIR`` overrides everything, for tests and
    power users.

    ``create=False`` only resolves the path — no directory is created and no
    permissions are touched. Diagnostics (previously a read-only path lookup,
    matching prior behaviour where a missing directory just meant an empty
    ledger) uses this; every other caller keeps the previous create-on-resolve
    behaviour.

    Locked-down permissions (0700) are applied only to Studio's own default
    Linux directory, and only atomically at creation (``os.makedirs(...,
    mode=0o700)`` — never a separate check-then-chmod step, which under this
    codebase's threaded server would either race between concurrent first-run
    callers or, if the process died between the check and the chmod, leave the
    directory permanently under-permissioned with no later call able to notice
    and correct it). A caller-supplied ``explicit`` path or ``SNAPSTUDIO_DATA_DIR``
    override is never touched (it may point at a folder the caller doesn't own).
    A directory that already exists is left exactly as it is either way — Python's
    ``os.makedirs(mode=...)`` does not change the mode of an already-existing
    target directory.
    """
    override = explicit or os.environ.get("SNAPSTUDIO_DATA_DIR")
    if override:
        base = override
        mode = None
    elif sys.platform == "win32":
        base = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "SnapmakerStudio")
        mode = None
    elif sys.platform.startswith("linux"):
        xdg = os.environ.get("XDG_DATA_HOME")
        xdg_home = xdg if xdg and os.path.isabs(xdg) else os.path.join(os.path.expanduser("~"), ".local", "share")
        base = os.path.join(xdg_home, "SnapmakerStudio")
        mode = 0o700
    else:
        base = os.path.join(os.path.expanduser("~"), "SnapmakerStudio")
        mode = None

    if create:
        os.makedirs(base, mode=mode or 0o777, exist_ok=True)
    return base
