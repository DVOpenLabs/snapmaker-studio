"""Static guards for the Studio+ modules (FOUNDATION.md section 8).

`scan_source` is the whole checker: it takes source text plus the module's path relative to
`backend/` and returns the violations. The real-tree test runs it over every scanned module;
each rule also has a negative self-test proving it fails on a synthetic violating source, so a
guard that silently stops matching cannot go unnoticed.

Rules
- G1   only snapstudio_core/foundation/netguard.py imports socket, ssl, http.client,
       urllib.request, urllib3 or requests (including importlib.import_module / __import__
       with a literal name).
- G1b  new modules use only an allowlisted set of names from snapstudio_core.moonraker.
- G1c  `write_ok=True` appears only under snapstudio_core/engines/.
- G3   no module reads `slot_count` or `len(nozzles)` (a head count must come from topology).
- G5   subprocess, os.system, os.startfile, os.popen, os.spawn*/exec*/posix_spawn*/fork*, pty.spawn,
       multiprocessing, loop.subprocess_exec/subprocess_shell, getattr(os, "system") and Popen appear
       only in snapstudio_core/engines/cli_runner.py, including aliases and asyncio subprocess/socket calls.
"""
from __future__ import annotations

import ast
import os

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PACKAGES = ("adapters", "engines", "creative", "calibration", "assemblies", "variants", "passport",
            "monitoring_context", "workspace_recovery", "foundation")
API_FILES = ("ext_routes.py", "setup_view.py")
EXTRA_FILES = ("u1convert/passport_cli.py",)

NETGUARD = "snapstudio_core/foundation/netguard.py"
CLI_RUNNER = "snapstudio_core/engines/cli_runner.py"
ENGINES_PREFIX = "snapstudio_core/engines/"

TRANSPORT_MODULES = ("socket", "ssl", "http.client", "urllib.request", "urllib3", "requests")
MOONRAKER_ALLOWED = frozenset({"toolhead_objects", "validate_host", "InvalidHost", "DEFAULT_PORT",
                               "SCHEMA_VERSION", "EXTENDED_MARKERS", "CONTROL_PATH"})
PROCESS_ATTRS = frozenset({"system", "startfile", "popen", "Popen"})
OS_EXTRA = frozenset({"posix_spawn", "posix_spawnp", "fork", "forkpty"})
LOOP_SPAWN = frozenset({"subprocess_exec", "subprocess_shell"})


# ------------------------------------------------------------------ the checker
def _is_transport(name: str) -> bool:
    return any(name == m or name.startswith(m + ".") for m in TRANSPORT_MODULES)


def _is_moonraker(module: str) -> bool:
    return module == "moonraker" or module.endswith(".moonraker")


def _os_process(name: str) -> bool:
    return name in PROCESS_ATTRS or name in OS_EXTRA or name.startswith(("spawn", "exec"))


def _is_process_module(name: str) -> bool:
    return name.split(".")[0] in ("subprocess", "multiprocessing")


def _dotted(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def scan_source(source: str, rel: str) -> list[tuple[str, int, str]]:
    """Violations of the guard rules in `source`, which lives at `rel` (posix, relative to backend/)."""
    tree = ast.parse(source)
    out: list[tuple[str, int, str]] = []
    transport_ok = rel == NETGUARD
    process_ok = rel == CLI_RUNNER
    write_ok_ok = rel.startswith(ENGINES_PREFIX)
    moon_aliases: set[str] = set()
    module_aliases: dict[str, str] = {}
    function_aliases: dict[str, tuple[str, str]] = {}

    def add(rule: str, node: ast.AST, message: str) -> None:
        out.append((rule, getattr(node, "lineno", 0), message))

    local_request_names: set[str] = set()
    for node in ast.walk(tree):                       # aliases first, so import order never hides a call
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_aliases[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if node.module:
                    function_aliases[alias.asname or alias.name] = (node.module, alias.name)
                if alias.name == "local_request":
                    local_request_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = _dotted(node.value) or ""
            if value.rsplit(".", 1)[-1] == "local_request" or value in local_request_names:
                local_request_names.add(node.targets[0].id)

    def calls_local_request(func: ast.AST) -> bool:
        if isinstance(func, ast.Name):
            return func.id == "local_request" or func.id in local_request_names
        return isinstance(func, ast.Attribute) and func.attr == "local_request"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                module_aliases[local] = alias.name
                if _is_transport(alias.name) and not transport_ok:
                    add("G1", node, f"imports {alias.name}")
                if _is_process_module(alias.name) and not process_ok:
                    add("G5", node, f"imports {alias.name}")
                if _is_moonraker(alias.name):
                    moon_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if module:
                    function_aliases[alias.asname or alias.name] = (module, alias.name)
                full = f"{module}.{alias.name}" if module else alias.name
                if (_is_transport(module) or _is_transport(full)) and not transport_ok:
                    add("G1", node, f"imports {full}")
                if _is_process_module(module) and not process_ok:
                    add("G5", node, f"imports from {module}")
                if alias.name == "subprocess" and not process_ok:
                    add("G5", node, "imports subprocess")
                if module == "os" and _os_process(alias.name) and not process_ok:
                    add("G5", node, f"imports {full}")
                if module == "subprocess" and alias.name in PROCESS_ATTRS and not process_ok:
                    add("G5", node, f"imports {full}")
                if module == "pty" and alias.name in ("spawn", "fork") and not process_ok:
                    add("G5", node, f"imports {full}")
                if _is_moonraker(module):
                    if alias.name == "*":
                        add("G1b", node, "wildcard import from moonraker")
                    elif alias.name not in MOONRAKER_ALLOWED:
                        add("G1b", node, f"imports {alias.name} from moonraker")
                elif alias.name == "moonraker":
                    moon_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Call):
            callee = _dotted(node.func) or ""
            literal = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str) else None
            if callee.rsplit(".", 1)[-1] in ("import_module", "__import__") and literal is not None:
                if _is_transport(literal) and not transport_ok:
                    add("G1", node, f"dynamic import of {literal}")
                if _is_process_module(literal) and not process_ok:
                    add("G5", node, f"dynamic import of {literal}")
                if _is_moonraker(literal):
                    add("G1b", node, "dynamic import of moonraker")
            if not write_ok_ok and calls_local_request(node.func) \
                    and any(kw.arg is None for kw in node.keywords):
                add("G1c", node, "expanded keyword arguments may pass write_ok outside engines/")
            for kw in node.keywords:
                if kw.arg == "write_ok" and not write_ok_ok:
                    if not isinstance(kw.value, ast.Constant) or kw.value.value is True:
                        add("G1c", node, "write_ok may enable writes outside engines/")
            if isinstance(node.func, ast.Name) and node.func.id in function_aliases:
                module, name = function_aliases[node.func.id]
                if not process_ok and (
                        _is_process_module(module)
                        or (module == "os" and _os_process(name))
                        or (module == "pty" and name in ("spawn", "fork"))
                        or (module == "asyncio" and (name.startswith("create_subprocess_") or name == "open_connection"))):
                    add("G5", node, f"calls imported {module}.{name}")
            if callee == "getattr" and len(node.args) >= 2 and not process_ok:
                target = _dotted(node.args[0])
                name_arg = node.args[1].value if isinstance(node.args[1], ast.Constant) \
                    and isinstance(node.args[1].value, str) else None
                if target is not None and name_arg is not None:
                    root = module_aliases.get(target.split(".")[0], target.split(".")[0])
                    if (root == "os" and _os_process(name_arg)) or _is_process_module(root) \
                            or (root == "pty" and name_arg in ("spawn", "fork")):
                        add("G5", node, f"getattr({target}, {name_arg!r})")
            if callee == "len" and len(node.args) == 1:
                target = _dotted(node.args[0]) or ""
                if target.rsplit(".", 1)[-1] == "nozzles":
                    add("G3", node, "len(nozzles) used as a head count")
            if callee.rsplit(".", 1)[-1] == "get" and literal == "slot_count":
                add("G3", node, "reads slot_count")
        elif isinstance(node, ast.Subscript):
            index = node.slice
            if isinstance(index, ast.Constant) and index.value == "slot_count":
                add("G3", node, "reads slot_count")
        if isinstance(node, ast.Attribute):
            if node.attr == "slot_count":
                add("G3", node, "reads slot_count")
            if node.attr in PROCESS_ATTRS and not process_ok:
                owner = _dotted(node.value) or ""
                if node.attr in ("Popen", "startfile") or owner in ("os", "subprocess"):
                    add("G5", node, f"uses {owner}.{node.attr}")
            if node.attr in LOOP_SPAWN and not process_ok:
                add("G5", node, f"uses {node.attr}")
            owner = _dotted(node.value)
            if owner:
                root, dot, suffix = owner.partition(".")
                resolved_owner = module_aliases.get(root, root) + (dot + suffix if dot else "")
                effective = resolved_owner + "." + node.attr
                if _is_transport(effective) and not transport_ok:
                    add("G1", node, f"uses {effective}")
                root_module = resolved_owner.split(".")[0]
                if not process_ok and (_is_process_module(root_module)
                        or (root_module == "os" and _os_process(node.attr))
                        or (root_module == "pty" and node.attr in ("spawn", "fork"))
                        or (root_module == "asyncio" and (node.attr.startswith("create_subprocess_")
                                                           or node.attr == "open_connection"))):
                    add("G5", node, f"uses {effective}")
            if owner in moon_aliases and node.attr not in MOONRAKER_ALLOWED:
                add("G1b", node, f"uses moonraker.{node.attr}")
            if owner is not None and _is_moonraker(owner) and node.attr not in MOONRAKER_ALLOWED:
                add("G1b", node, f"uses {owner}.{node.attr}")
        elif isinstance(node, ast.Name):
            if node.id == "slot_count":
                add("G3", node, "reads slot_count")
            if node.id == "Popen" and not process_ok:
                add("G5", node, "uses Popen")
    return out


def scanned_modules() -> list[str]:
    """Posix paths relative to backend/ of every existing module the guards cover."""
    found: list[str] = []
    for package in PACKAGES:
        base = os.path.join(BACKEND, "snapstudio_core", package)
        for root, _dirs, files in os.walk(base):
            for name in files:
                if name.endswith(".py"):
                    found.append(os.path.relpath(os.path.join(root, name), BACKEND).replace(os.sep, "/"))
    api = os.path.join(BACKEND, "snapstudio_api")
    if os.path.isdir(api):
        for name in os.listdir(api):
            if name in API_FILES or (name.startswith("routes_") and name.endswith(".py")):
                found.append("snapstudio_api/" + name)
    for extra in EXTRA_FILES:
        if os.path.exists(os.path.join(BACKEND, extra)):
            found.append(extra)
    return sorted(found)


# ------------------------------------------------------------------ the real tree
def test_scan_covers_the_known_modules():
    mods = scanned_modules()
    for expected in (NETGUARD, "snapstudio_core/foundation/jobs.py", "snapstudio_core/adapters/base.py",
                     "snapstudio_api/ext_routes.py"):
        assert expected in mods
    assert len(mods) >= 15


def test_no_module_breaks_a_guard():
    problems = []
    for rel in scanned_modules():
        with open(os.path.join(BACKEND, rel), encoding="utf-8") as fh:
            for rule, line, message in scan_source(fh.read(), rel):
                problems.append(f"{rule} {rel}:{line} {message}")
    assert not problems, "\n".join(problems)


def test_netguard_really_is_the_transport_module():
    with open(os.path.join(BACKEND, NETGUARD), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert any(_is_transport(name) for name in imported)     # the allowlist is exercised, not vacuous


# ------------------------------------------------------------------ negative self-tests
OTHER = "snapstudio_core/creative/thing.py"


def rules(source: str, rel: str = OTHER) -> set[str]:
    return {rule for rule, _line, _msg in scan_source(source, rel)}


def test_clean_source_passes():
    clean = "import json\nfrom snapstudio_core.moonraker import toolhead_objects, validate_host\n" \
            "def f(t):\n    return len(t.heads)\n"
    assert scan_source(clean, OTHER) == []


@pytest.mark.parametrize("source", [
    "import socket\n",
    "import socket as sock\nsock.create_connection(('host', 1))\n",
    "import ssl\n",
    "import http.client\n",
    "import urllib.request\n",
    "import http\nhttp.client.HTTPConnection('host')\n",
    "import urllib\nurllib.request.urlopen('http://example.com')\n",
    "import urllib3\n",
    "import requests\n",
    "from http import client\n",
    "from http.client import HTTPConnection\n",
    "from urllib import request\n",
    "from urllib.request import urlopen\n",
    "from requests import get\n",
    "import importlib\nimportlib.import_module('socket')\n",
    "__import__('requests')\n",
])
def test_g1_fails_on_each_transport_import_outside_netguard(source):
    assert "G1" in rules(source)
    assert "G1" not in rules(source, NETGUARD)               # and netguard alone may


@pytest.mark.parametrize("source", [
    "from snapstudio_core.moonraker import emergency_stop\n",
    "from snapstudio_core.moonraker import validate_host, upload_gcode\n",
    "from ..moonraker import _post\n",
    "from snapstudio_core.moonraker import *\n",
    "from snapstudio_core import moonraker\nmoonraker.job_queue()\n",
    "from snapstudio_core import moonraker as mr\nmr.probe('x')\n",
    "import snapstudio_core.moonraker as mr\nmr.discover()\n",
    "import snapstudio_core.moonraker\nsnapstudio_core.moonraker.confirm_upload()\n",
    "import importlib\nimportlib.import_module('snapstudio_core.moonraker')\n",
])
def test_g1b_fails_on_a_forbidden_moonraker_use(source):
    assert "G1b" in rules(source)


def test_g1b_allows_exactly_the_listed_names():
    names = sorted(MOONRAKER_ALLOWED)
    assert len(names) == 7
    ok = "from snapstudio_core.moonraker import " + ", ".join(names) + "\n"
    assert scan_source(ok, OTHER) == []
    assert scan_source("from snapstudio_core import moonraker\nmoonraker.validate_host('x')\n", OTHER) == []


def test_g1c_write_ok_true_only_under_engines():
    source = "local_request('POST', url, write_ok=True)\n"
    assert "G1c" in rules(source)
    assert "G1c" in rules(source, "snapstudio_api/ext_routes.py")
    assert "G1c" not in rules(source, "snapstudio_core/engines/lumina.py")
    assert "G1c" not in rules("local_request('GET', url, write_ok=False)\n")


G1C_ALIASES = [
    "from snapstudio_core.foundation.netguard import local_request as request\n"
    "def f(opts):\n    request('POST', url, **opts)\n",
    "from snapstudio_core.foundation import netguard\n"
    "def f(opts):\n    netguard.local_request('POST', url, **opts)\n",
    "import snapstudio_core.foundation.netguard as ng\n"
    "def f(opts):\n    ng.local_request('POST', url, **opts)\n",
    "from snapstudio_core.foundation.netguard import local_request\nreq = local_request\n"
    "def f(opts):\n    req('POST', url, **opts)\n",
]


@pytest.mark.parametrize("source", G1C_ALIASES)
def test_g1c_resolves_aliases_of_local_request(source):
    assert "G1c" in rules(source)
    assert "G1c" not in rules(source, "snapstudio_core/engines/lumina.py")


@pytest.mark.parametrize("source", [
    "def f(write_ok):\n    local_request('POST', url, write_ok=write_ok)\n",
    "def f(kwargs):\n    local_request('POST', url, **kwargs)\n",
])
def test_g1c_fails_when_write_permission_is_indirect(source):
    assert "G1c" in rules(source)
    assert "G1c" not in rules(source, "snapstudio_core/engines/lumina.py")


@pytest.mark.parametrize("source", [
    "def f(p):\n    return p.slot_count\n",
    "def f(p):\n    return p['slot_count']\n",
    "def f(p):\n    return p.get('slot_count')\n",
    "def f(slot_count):\n    return slot_count * 2\n",
    "def f(p):\n    return len(p.nozzles)\n",
    "def f(nozzles):\n    return len(nozzles)\n",
])
def test_g3_fails_when_a_head_count_comes_from_slot_count_or_nozzles(source):
    assert "G3" in rules(source)


@pytest.mark.parametrize("source", [
    "import subprocess\n",
    "from subprocess import run\n",
    "import subprocess as sp\n",
    "import os\nos.system('x')\n",
    "import os\nos.startfile('x')\n",
    "import os\nos.popen('x')\n",
    "import os\nos.spawnv(os.P_WAIT, 'x', ['x'])\n",
    "import os\nos.execlp('x', 'x')\n",
    "from os import spawnv as s\ns(os.P_WAIT, 'x', ['x'])\n",
    "import os as operating\noperating.system('x')\n",
    "from os import system as s\ns('x')\n",
    "from os import system\n",
    "import subprocess\nsubprocess.Popen(['x'])\n",
    "import subprocess as sp\nsp.run(['x'])\n",
    "import asyncio as aio\nawait aio.create_subprocess_exec('x')\n",
    "import asyncio\nawait asyncio.create_subprocess_shell('x')\n",
    "import asyncio\nawait asyncio.open_connection('host', 1)\n",
    "from x import Popen\nPopen(['x'])\n",
    "import importlib\nimportlib.import_module('subprocess')\n",
    "import os\nos.posix_spawn('x', ['x'], {})\n",
    "import os\nos.posix_spawnp('x', ['x'], {})\n",
    "import os\nos.fork()\n",
    "import os\nos.forkpty()\n",
    "from os import fork\n",
    "import pty\npty.spawn(['x'])\n",
    "from pty import spawn\n",
    "import multiprocessing\n",
    "import multiprocessing as mp\nmp.Process(target=f).start()\n",
    "from multiprocessing import Pool\n",
    "import importlib\nimportlib.import_module('multiprocessing')\n",
    "def f(loop):\n    return loop.subprocess_exec(factory, 'x')\n",
    "def f(loop):\n    return loop.subprocess_shell(factory, 'x')\n",
    "import os\ngetattr(os, 'system')('x')\n",
    "import os as o\ngetattr(o, 'fork')()\n",
    "import subprocess\ngetattr(subprocess, 'run')(['x'])\n",
])
def test_g5_fails_on_process_execution_outside_cli_runner(source):
    assert "G5" in rules(source)
    assert "G5" not in rules(source, CLI_RUNNER)


def test_a_syntax_error_is_not_swallowed():
    with pytest.raises(SyntaxError):
        scan_source("def broken(:\n", OTHER)
