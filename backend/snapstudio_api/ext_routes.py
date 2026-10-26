"""Route seam for the Studio+ tracks.

`server.py` knows exactly one thing about the tracks: it asks `dispatch()` before
answering 404. Every track registers its POST handlers here, under its own prefix.

A handler is `fn(data: dict) -> (status: int, body: dict)`. It must return within
a short bound (HANDLER_BUDGET_S); long work goes through `foundation.jobs`.
Handlers raise to refuse; `dispatch` owns the error mapping so no track invents its
own shapes:

    request_validation.ValidationError                 -> 400 {"error":"invalid", "message"}
    SnapStudioError                                    -> 422 {"error":"refusal", "message"}
    NetguardRefused / RevisionConflict / StoreVersionError
                                                       -> 422 {"error":"refusal", "message": <fixed text>}
    anything else (including a plain ValueError)       -> 500 {"error":"internal", "message":"Internal error."}

The body shape matches what `api.ts` `post()` reads (`message`).
"""
from __future__ import annotations

import importlib.util
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable

from snapstudio_core.errors import SnapStudioError
from snapstudio_core.foundation.netguard import NetguardRefused
from snapstudio_core.foundation.store import RevisionConflict, StoreVersionError

from .request_validation import ValidationError

_LOG = logging.getLogger("snapstudio.ext_routes")

#: The only path prefixes a track may own.
PREFIXES = ("/setups", "/creative", "/engines", "/calibration", "/assemblies",
            "/variants", "/passport", "/monitoring", "/recovery")

#: Route module -> the prefixes it may register under.
TRACK_MODULES: dict[str, tuple[str, ...]] = {
    "routes_setups": ("/setups",),
    "routes_creative": ("/creative",),
    "routes_engines": ("/engines",),
    "routes_calibration": ("/calibration",),
    "routes_assemblies": ("/assemblies",),
    "routes_variants": ("/variants",),
    "routes_passport": ("/passport",),
    "routes_recovery": ("/monitoring", "/recovery"),
}

#: A handler that takes longer than this is logged (by route, never by content).
HANDLER_BUDGET_S = 5.0

Handler = Callable[[dict], "tuple[int, dict]"]
ROUTES: dict[str, Handler] = {}

REFUSAL_TEXTS = {
    "NetguardRefused": "That address was refused. Studio only talks to devices on your local network.",
    "RevisionConflict": "The saved data changed since it was loaded. Reload it and try again.",
    "StoreVersionError": "That saved data was written by a newer version of Studio and was left untouched.",
}
INTERNAL_MESSAGE = "Internal error."

_PATH_RE = re.compile(r"^/[a-z0-9_]+(?:/[a-z0-9_\-]+)*$")


class RegistrationError(ValueError):
    """A route was registered outside its track prefix, twice, or over a built-in path."""


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _is_test_module(name: str) -> bool:
    """Handlers defined in the test suite (pytest imports them as `test_*`, `tests.*` or `conftest`)."""
    parts = name.split(".")
    return parts[0] in ("tests", "conftest") or parts[0].startswith("test_") or "tests" in parts[:-1]


def builtin_paths() -> frozenset[str]:
    """Literal request paths `server.py` answers itself, read from its source.

    Empty when the source is not on disk (frozen build): the prefix rule already keeps
    every registration away from them, and a test pins that none of them is in a prefix.
    """
    try:
        text = (Path(__file__).with_name("server.py")).read_text(encoding="utf-8")
    except OSError:
        return frozenset()
    found: set[str] = set()
    for m in re.finditer(r"self\.path\s*==\s*([\"'])(/[^\"']*)\1", text):
        found.add(m.group(2))
    for m in re.finditer(r"self\.path\s+in\s*\(([^)]*)\)", text):
        found.update(re.findall(r"[\"'](/[^\"']*)[\"']", m.group(1)))
    return frozenset(found)


def register(path: str, fn: Handler) -> Handler:
    if not isinstance(path, str) or not _PATH_RE.match(path):
        raise RegistrationError("route path is not a plain lowercase path")
    if not callable(fn):
        raise RegistrationError("route handler is not callable")
    if not any(_under(path, p) for p in PREFIXES):
        raise RegistrationError("route path is outside the Studio+ prefixes")
    full_module = str(getattr(fn, "__module__", "") or "")
    module = full_module.rsplit(".", 1)[-1]
    allowed = TRACK_MODULES.get(module)
    if allowed is None:
        if not _is_test_module(full_module):
            raise RegistrationError("route handler is not defined in a known track module")
    elif not any(_under(path, p) for p in allowed):
        raise RegistrationError("route path is outside its track prefix")
    if path in builtin_paths():
        raise RegistrationError("route path collides with a built-in path")
    existing = ROUTES.get(path)
    if existing is not None and existing is not fn:
        raise RegistrationError("route path is already registered")
    ROUTES[path] = fn
    return fn


def route(path: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        return register(path, fn)
    return deco


# -- dispatch -------------------------------------------------------------------

def _log_unexpected(exc: BaseException) -> None:
    """Server-side only, class and call sites only (server.py's own redacting logger)."""
    try:
        from . import server  # already imported when a request is being served
        server._log_unexpected(exc)
        return
    except Exception:  # logging must never be the reason a request fails
        pass
    try:
        _LOG.error("unexpected %s", type(exc).__name__)
    except Exception:
        pass


def error_response(exc: BaseException) -> tuple[int, dict]:
    """The one mapping from an exception to a response. ValidationError is checked before ValueError."""
    if isinstance(exc, ValidationError):
        return 400, {"error": "invalid", "message": str(exc)}
    if isinstance(exc, (NetguardRefused, RevisionConflict, StoreVersionError)):
        return 422, {"error": "refusal", "message": REFUSAL_TEXTS[_refusal_key(exc)]}
    if isinstance(exc, SnapStudioError):
        return 422, {"error": "refusal", "message": str(exc)}
    _log_unexpected(exc)
    return 500, {"error": "internal", "message": INTERNAL_MESSAGE}


def _refusal_key(exc: BaseException) -> str:
    if isinstance(exc, NetguardRefused):
        return "NetguardRefused"
    if isinstance(exc, RevisionConflict):
        return "RevisionConflict"
    return "StoreVersionError"


def dispatch(handler: Any, path: str, data: Any) -> bool:
    """Answer `path` if a track owns it. Returns False (nothing sent) for an unknown path."""
    fn = ROUTES.get(path)
    if fn is None:
        return False
    if not isinstance(data, dict):
        handler._send(400, {"error": "invalid", "message": "The request body must be a JSON object."})
        return True
    started = time.monotonic()
    try:
        result = fn(data)
        if (not isinstance(result, tuple) or len(result) != 2 or isinstance(result[0], bool)
                or not isinstance(result[0], int) or not 100 <= result[0] <= 599
                or not isinstance(result[1], dict)):
            raise TypeError("route handler returned a malformed result")
        status, body = result
    except Exception as exc:  # the mapping below is the whole policy
        status, body = error_response(exc)
    if time.monotonic() - started > HANDLER_BUDGET_S:
        _LOG.warning("route %s exceeded its %.0f s budget", path, HANDLER_BUDGET_S)
    handler._send(status, body)
    return True


# -- loading ---------------------------------------------------------------------

def _missing_ok(name: str) -> None:
    """Called from an `except ImportError`: skip a module that is absent, re-raise one that is present but broken."""
    if importlib.util.find_spec(f"{__package__}.{name}") is not None:
        raise


def load_all() -> None:
    """Import every track's route module (each registers its handlers on import)."""
    try:
        from . import routes_setups  # noqa: F401
    except ImportError:
        _missing_ok("routes_setups")
    try:
        from . import routes_creative  # noqa: F401
    except ImportError:
        _missing_ok("routes_creative")
    try:
        from . import routes_engines  # noqa: F401
    except ImportError:
        _missing_ok("routes_engines")
    try:
        from . import routes_calibration  # noqa: F401
    except ImportError:
        _missing_ok("routes_calibration")
    try:
        from . import routes_assemblies  # noqa: F401
    except ImportError:
        _missing_ok("routes_assemblies")
    try:
        from . import routes_variants  # noqa: F401
    except ImportError:
        _missing_ok("routes_variants")
    try:
        from . import routes_passport  # noqa: F401
    except ImportError:
        _missing_ok("routes_passport")
    try:
        from . import routes_recovery  # noqa: F401
    except ImportError:
        _missing_ok("routes_recovery")
    from snapstudio_core.adapters import registry
    registry.discover()


load_all()
