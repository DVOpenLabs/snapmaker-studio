"""P0a acceptance 16: the Studio+ route seam (ext_routes) and the server.py seam."""
from __future__ import annotations

import ast
import difflib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from snapstudio_api import ext_routes
from snapstudio_api.request_validation import ValidationError
from snapstudio_core.errors import SnapStudioError, UnsafeArchive
from snapstudio_core.foundation.netguard import NetguardRefused
from snapstudio_core.foundation.store import RevisionConflict, StoreVersionError

API_DIR = Path(ext_routes.__file__).parent
SERVER_PY = API_DIR / "server.py"
BASELINE = "6d2e7f0485bfb7fa24caa9a58a4bd5fd37431222"


class FakeHandler:
    def __init__(self):
        self.sent = []

    def _send(self, code, obj):
        self.sent.append((code, obj))


@pytest.fixture
def routes():
    """Registry changes made by a test are undone afterwards."""
    before = dict(ext_routes.ROUTES)
    yield ext_routes.ROUTES
    ext_routes.ROUTES.clear()
    ext_routes.ROUTES.update(before)


def _call(path, data):
    h = FakeHandler()
    handled = ext_routes.dispatch(h, path, data)
    return handled, h.sent


# -- registration ----------------------------------------------------------------

@pytest.mark.parametrize("prefix", ext_routes.PREFIXES)
def test_registration_inside_each_prefix_is_accepted(routes, prefix):
    ext_routes.register(prefix + "/probe", lambda d: (200, {}))
    assert prefix + "/probe" in ext_routes.ROUTES


@pytest.mark.parametrize("path", [
    "/doctor", "/health", "/setup", "/setupsX", "/creativeness/x", "/other/setups",
    "setups/x", "/setups/../doctor", "/setups//x", "/setups/x?y=1", "/Setups/x", "", "/",
])
def test_registration_outside_the_nine_prefixes_is_refused(routes, path):
    with pytest.raises(ext_routes.RegistrationError):
        ext_routes.register(path, lambda d: (200, {}))


def test_registration_must_stay_inside_its_own_track(routes):
    def handler(data):
        return 200, {}
    handler.__module__ = "snapstudio_api.routes_creative"
    with pytest.raises(ext_routes.RegistrationError):
        ext_routes.register("/setups/x", handler)
    ext_routes.register("/creative/x", handler)
    recovery = lambda d: (200, {})  # noqa: E731
    recovery.__module__ = "snapstudio_api.routes_recovery"
    ext_routes.register("/monitoring/x", recovery)
    ext_routes.register("/recovery/x", recovery)
    with pytest.raises(ext_routes.RegistrationError):
        ext_routes.register("/passport/x", recovery)


def test_duplicate_registration_is_refused(routes):
    ext_routes.register("/setups/dup", lambda d: (200, {}))
    with pytest.raises(ext_routes.RegistrationError):
        ext_routes.register("/setups/dup", lambda d: (200, {}))


def _builtin_literals_from_ast() -> set:
    """Every path literal compared with `self.path` in server.py, found by AST (independent of ext_routes)."""
    tree = ast.parse(SERVER_PY.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        left = node.left
        if not (isinstance(left, ast.Attribute) and left.attr == "path"
                and isinstance(left.value, ast.Name) and left.value.id == "self"):
            continue
        for comp in node.comparators:
            if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                found.add(comp.value)
            elif isinstance(comp, (ast.Tuple, ast.List, ast.Set)):
                found.update(e.value for e in comp.elts
                             if isinstance(e, ast.Constant) and isinstance(e.value, str))
    return found


def test_no_server_literal_lies_in_a_studio_plus_prefix_and_registration_refuses_each():
    literals = _builtin_literals_from_ast()
    assert len(literals) >= 20 and "/doctor" in literals          # the extraction really found them
    assert ext_routes.builtin_paths() >= {p for p in literals if p.startswith("/")}
    for lit in literals:
        assert not any(ext_routes._under(lit, p) for p in ext_routes.PREFIXES), lit
        with pytest.raises(ext_routes.RegistrationError):
            ext_routes.register(lit, lambda d: (200, {}))


def test_collision_with_a_builtin_is_refused_even_inside_a_prefix(routes, monkeypatch):
    monkeypatch.setattr(ext_routes, "builtin_paths", lambda: frozenset({"/setups/taken"}))
    with pytest.raises(ext_routes.RegistrationError):
        ext_routes.register("/setups/taken", lambda d: (200, {}))


def test_no_registered_route_collides_with_a_server_literal():
    assert not (set(ext_routes.ROUTES) & _builtin_literals_from_ast())


# -- dispatch --------------------------------------------------------------------

def test_unknown_path_is_not_handled_and_sends_nothing(routes):
    handled, sent = _call("/setups/nothing-here", {})
    assert handled is False and sent == []


@pytest.mark.parametrize("body", [[], [1], "x", 3, None, True])
def test_non_object_body_is_400_invalid(routes, body):
    calls = []
    ext_routes.register("/setups/obj", lambda d: calls.append(d) or (200, {}))
    handled, sent = _call("/setups/obj", body)
    assert handled is True and calls == []
    assert sent[0][0] == 400 and sent[0][1]["error"] == "invalid" and sent[0][1]["message"]


def test_handler_result_is_sent_as_returned(routes):
    ext_routes.register("/setups/ok", lambda d: (200, {"echo": d["x"]}))
    assert _call("/setups/ok", {"x": 5}) == (True, [(200, {"echo": 5})])


@pytest.mark.parametrize("bad", [None, 200, (200,), ("200", {}), (200, []), (True, {}), (99, {}), (600, {})])
def test_malformed_handler_result_is_a_generic_500(routes, bad):
    ext_routes.register("/setups/bad", lambda d: bad)
    _, sent = _call("/setups/bad", {})
    assert sent == [(500, {"error": "internal", "message": "Internal error."})]


def test_validation_error_is_400_invalid_with_its_message(routes):
    def handler(d):
        raise ValidationError("Missing or invalid 'host'")
    ext_routes.register("/setups/v", handler)
    assert _call("/setups/v", {})[1] == [(400, {"error": "invalid", "message": "Missing or invalid 'host'"})]


def test_validation_error_is_checked_before_plain_value_error(routes):
    assert issubclass(ValidationError, ValueError)
    def plain(d):
        raise ValueError("secret-path SENTINEL-PATH-x")
    ext_routes.register("/setups/plain", plain)
    code, body = _call("/setups/plain", {})[1][0]
    assert code == 500 and body == {"error": "internal", "message": "Internal error."}


@pytest.mark.parametrize("exc", [
    NetguardRefused("public"), RevisionConflict("rev 3 != 4 SENTINEL-PATH-store.json"),
    StoreVersionError("user_version 9 SENTINEL-PATH-x.db")])
def test_foundation_errors_are_422_refusal_with_fixed_text(routes, exc):
    def handler(d):
        raise exc
    ext_routes.register("/setups/f", handler)
    code, body = _call("/setups/f", {})[1][0]
    assert code == 422 and body["error"] == "refusal"
    assert body["message"] == ext_routes.REFUSAL_TEXTS[type(exc).__name__]
    assert "someone" not in body["message"] and "rev 3" not in body["message"]


def test_snapstudio_error_is_422_refusal_with_its_own_message(routes):
    def handler(d):
        raise UnsafeArchive("That archive was not opened.")
    ext_routes.register("/setups/s", handler)
    code, body = _call("/setups/s", {})[1][0]
    assert code == 422 and body == {"error": "refusal", "message": "That archive was not opened."}
    assert isinstance(UnsafeArchive("x"), SnapStudioError)


def test_unexpected_exception_is_a_generic_500_and_leaks_nothing(routes):
    def handler(d):
        raise RuntimeError("SENTINEL-KEY-9f3a at SENTINEL-PATH-x")
    ext_routes.register("/setups/boom", handler)
    code, body = _call("/setups/boom", {})[1][0]
    assert (code, body) == (500, {"error": "internal", "message": "Internal error."})
    assert "SENTINEL" not in repr(body)


def test_error_body_has_the_message_key_api_ts_reads(routes):
    for exc in (ValidationError("m"), NetguardRefused("x"), RuntimeError("x")):
        code, body = ext_routes.error_response(exc)
        assert set(body) == {"error", "message"} and isinstance(body["message"], str)


# -- loading ---------------------------------------------------------------------

def test_load_all_has_literal_imports_for_all_eight_modules_and_the_registry():
    src = Path(ext_routes.__file__).read_text(encoding="utf-8")
    for name in ext_routes.TRACK_MODULES:
        assert f"from . import {name}  # noqa: F401" in src
    assert "registry.discover()" in src and len(ext_routes.TRACK_MODULES) == 8


def test_every_route_module_that_exists_registers_its_prefix():
    for module, prefixes in ext_routes.TRACK_MODULES.items():
        if importlib.util.find_spec(f"snapstudio_api.{module}") is None:
            continue   # until integration only modules that exist are checked; the integration PR asserts all eight
        assert any(any(ext_routes._under(p, pre) for pre in prefixes) for p in ext_routes.ROUTES), module


def test_missing_module_is_skipped(monkeypatch):
    monkeypatch.setitem(sys.modules, "snapstudio_api.routes_setups", None)   # import raises ImportError
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None)
    ext_routes.load_all()


def test_present_but_broken_module_re_raises_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "snapstudio_api.routes_passport", None)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: object())
    with pytest.raises(ImportError):
        ext_routes.load_all()


def test_a_real_broken_route_module_fails_loudly(tmp_path, monkeypatch):
    """End to end with a genuine file that raises ImportError on import (find_spec finds it)."""
    pkg = tmp_path / "fakeapi"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "routes_x.py").write_text("import module_that_does_not_exist_9f3a\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(ext_routes, "__package__", "fakeapi")
    with pytest.raises(ImportError):
        try:
            import fakeapi.routes_x  # noqa: F401
        except ImportError:
            ext_routes._missing_ok("routes_x")      # file exists -> re-raised
    try:
        raise ImportError("absent")
    except ImportError:
        ext_routes._missing_ok("routes_absent")     # no such file: skipped


# -- server.py seam --------------------------------------------------------------

def _baseline_server_lines():
    root = Path(__file__).resolve().parents[2]
    try:
        out = subprocess.run(["git", "-C", str(root), "show", f"{BASELINE}:backend/snapstudio_api/server.py"],
                             capture_output=True, check=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("baseline commit not available in this checkout")
    return out.stdout.decode("utf-8").splitlines()


def test_server_diff_is_exactly_the_authorised_seam():
    base = _baseline_server_lines()
    now = SERVER_PY.read_text(encoding="utf-8").splitlines()
    added, removed = [], []
    for line in difflib.unified_diff(base, now, lineterm="", n=0):
        if line.startswith(("+++", "---", "@@")):
            continue
        (added if line.startswith("+") else removed).append(line[1:])
    assert removed == []
    assert [a.strip() for a in added] == [
        "from . import ext_routes",
        "elif ext_routes.dispatch(self, self.path, data):",
        "pass",
    ]
    hunks = [ln for ln in difflib.unified_diff(base, now, lineterm="", n=0) if ln.startswith("@@")]
    assert len(hunks) == 2


def test_dispatch_branch_comes_before_the_final_404_in_do_post():
    tree = ast.parse(SERVER_PY.read_text(encoding="utf-8"))
    post = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "do_POST")
    chain = next(n for n in reversed(post.body) if isinstance(n, ast.If))
    node, tests = chain, []
    while True:
        tests.append(ast.unparse(node.test))
        if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            node = node.orelse[0]
        else:
            break
    assert tests[-1] == "ext_routes.dispatch(self, self.path, data)"
    final_else = ast.unparse(node.orelse[0])
    assert "404" in final_else and "not found" in final_else


def test_handler_from_an_unknown_module_is_refused_but_test_modules_and_track_modules_are_allowed(routes):
    def handler(d):
        return 200, {}

    for module in ("some_plugin", "snapstudio_api.service", "snapstudio_api.routes_unknown", "", "evil.tests_helper"):
        handler.__module__ = module
        with pytest.raises(ext_routes.RegistrationError):
            ext_routes.register("/setups/unknown-mod", handler)
    for module in ("snapstudio_api.routes_setups", "routes_setups", "test_ext_routes", "tests.test_ext_routes",
                   "backend.tests.helpers", "conftest"):
        handler.__module__ = module
        ext_routes.register("/setups/ok-mod", handler)
        ext_routes.ROUTES.pop("/setups/ok-mod", None)
