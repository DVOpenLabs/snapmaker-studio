"""Local-first, enforced rather than promised.

Studio's headline claim is that everything happens on the user's machine: no
cloud, no account, no telemetry, nothing uploaded. v0.5.0 introduces exactly one
outbound request — an explicit "check GitHub for a newer release" button — and
that is precisely the moment a claim like this starts eroding.

So the rule is written down and checked. The shell may request one host. The
engine may request none: its only network calls go to a printer address the user
typed in, which is why they are built from a variable rather than a literal.

The test looks at what is actually *requested*. A namespace URI in a 3MF, a
project link in a comment, or another tool's homepage in the ecosystem registry
are text, not traffic, and must not be confused for it.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SHELL = ROOT / "desktop" / "src-tauri" / "src" / "main.rs"
ENGINE = ROOT / "backend" / "snapstudio_core"

#: The one host the desktop shell is allowed to reach, and only on a button press.
ALLOWED_SHELL_HOSTS = {"api.github.com"}

_SHELL_REQUEST = re.compile(r"ureq::\w+\(\s*\n?\s*\"https://([a-z0-9.\-]+)")
_ENGINE_REQUEST = re.compile(r"(?:urlopen|Request)\(\s*[\"']https?://([a-z0-9.\-]+)")


def test_the_shell_requests_exactly_one_host():
    requested = set(_SHELL_REQUEST.findall(SHELL.read_text(encoding="utf-8")))
    assert requested <= ALLOWED_SHELL_HOSTS, (
        f"the shell requests hosts it should not: {sorted(requested - ALLOWED_SHELL_HOSTS)}")


def test_the_manual_update_check_is_never_automatic():
    """The manual check runs only when a person presses the button — nothing
    may call it unconditionally. A separate, opt-in automatic path exists
    (test_the_automatic_update_check_gates_itself_before_any_request below);
    this test is only about the one that always fires a request."""
    shell = SHELL.read_text(encoding="utf-8")
    assert "fn check_for_update" in shell
    # The command is registered for the frontend to invoke; the shell itself must
    # not call it unconditionally during setup.
    setup = shell[shell.index(".setup("):] if ".setup(" in shell else ""
    assert "check_for_update(" not in setup, (
        "the shell calls the update check during startup — it must be user-initiated "
        "or gated behind the opt-in automatic path's own throttle")

    app = (ROOT / "desktop" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "checkForUpdate" not in app, (
        "App.tsx calls the unconditional manual update check on mount — it must "
        "be user-initiated (see maybeAutoCheckUpdate for the opt-in automatic path)")


def test_the_automatic_update_check_gates_itself_before_any_request():
    """The opt-in automatic path may run once per launch — see App.tsx's own
    startup effect — but only because the Rust side refuses to make the
    request at all unless the persisted preference is on and a day has
    passed. Checked here by requiring that gate to actually run inside the
    function, not merely trusted by name — and that it reuses the exact same
    request function the manual button uses, not a second implementation
    that could drift from the manual path's own privacy guarantees."""
    shell = SHELL.read_text(encoding="utf-8")
    assert "fn maybe_auto_check_update" in shell
    start = shell.index("fn maybe_auto_check_update")
    end = shell.index("\n}\n", start)
    auto_fn = shell[start:end]
    assert "should_check_now" in auto_fn, (
        "maybe_auto_check_update must consult the throttle/opt-in gate before "
        "ever making a request")
    assert "check_for_update()" in auto_fn, (
        "maybe_auto_check_update must reuse check_for_update's own request, "
        "not a second implementation of the same GET")

    app = (ROOT / "desktop" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "maybeAutoCheckUpdate" in app, (
        "the opt-in automatic check must run once per launch from App's own "
        "startup effect — calling it only from the Help page would mean it "
        "never runs unless someone happens to open Help")


def test_the_engine_never_requests_a_remote_host():
    offenders = []
    for module in ENGINE.glob("*.py"):
        for match in _ENGINE_REQUEST.finditer(module.read_text(encoding="utf-8")):
            offenders.append(f"{module.name} -> {match.group(1)}")
    assert not offenders, "engine modules requesting a remote host: " + ", ".join(offenders)


def test_the_printer_address_is_always_supplied_not_baked_in():
    """The engine talks to a printer, and only to the one it was given."""
    moonraker = (ENGINE / "moonraker.py").read_text(encoding="utf-8")
    literals = re.findall(r"\"https?://(?!\{)([a-z0-9.\-]+)", moonraker)
    assert not literals, f"moonraker.py contains a hard-coded host: {literals}"


def test_the_update_check_sends_nothing_about_the_user():
    """One GET, a User-Agent, and no body. No identifier, no usage, no file names.

    `check_for_update` itself is now only an async wrapper around
    `check_for_update_blocking` (M1: it hands the blocking ureq call to
    `spawn_blocking` so it never runs on the async runtime's own worker
    threads) — the request itself lives in the blocking function, so that
    is what this scans."""
    shell = SHELL.read_text(encoding="utf-8")
    block = shell[shell.index("fn check_for_update_blocking"):]
    block = block[:block.index("\n}\n")]
    for leak in ("hostname", "username", "machine_id", "uuid", "send_json",
                 ".send(", "os_info", "telemetry"):
        assert leak not in block, f"the update check sends {leak}"
