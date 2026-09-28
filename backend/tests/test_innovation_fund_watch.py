"""tools/watch/innovation_fund.py — the Innovation Fund page watcher.

This script's job was to notice the community vote going live. It did (the
committed snapshot records it). These tests pin: the terminal guard (no
fetch once ``voting_live`` is recorded, unless ``--force``/``--update``),
the atomic ``--update`` write, and that a corrupt snapshot fails closed
without ever reaching the network.

Fixture signal dicts are derived by calling the real ``signals()`` on small
HTML fixtures rather than hand-written, so a fixture can never silently drift
from what the regexes actually do.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "watch"))

import innovation_fund as ifw  # noqa: E402


PRE_VOTE_HTML = "<html><body><p>The voting system is coming next month.</p></body></html>"
PRE_VOTE_HTML_TRIVIA = (
    "<html><body><p>The voting system is coming next month.</p>"
    "<p>Some trivia not matched by any pattern, added today.</p></body></html>"
)
LIVE_HTML = (
    '<html><body><p>Voting is open. Open the ballot to cast your vote.</p>'
    '<p>See /innovation-fund/vote for details.</p>'
    '<p>View on GitHub</p><p>View on GitHub</p></body></html>'
)

PRE_VOTE_SIGNALS = ifw.signals(PRE_VOTE_HTML)
LIVE_SIGNALS = ifw.signals(LIVE_HTML)

# Sanity on the fixtures themselves: they must actually exercise a
# voting_promised -> voting_live transition, or the tests below prove nothing.
assert PRE_VOTE_SIGNALS["voting_promised"] is True
assert PRE_VOTE_SIGNALS["voting_live"] is False
assert LIVE_SIGNALS["voting_promised"] is False
assert LIVE_SIGNALS["voting_live"] is True
assert LIVE_SIGNALS["project_pages"] is True
assert LIVE_SIGNALS["project_count_hint"] == 2

PRE_VOTE = dict(PRE_VOTE_SIGNALS, recorded_at="2026-09-01")
TERMINAL = dict(LIVE_SIGNALS, recorded_at="2026-09-23")


def write(tmp_path, monkeypatch, data: dict | None, name: str = "snap.json"):
    snap = tmp_path / name
    if data is not None:
        snap.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(ifw, "SNAPSHOT", snap)
    return snap


def no_fetch(monkeypatch):
    def fail(*a, **kw):
        raise AssertionError("fetch must not be called")
    monkeypatch.setattr(ifw, "fetch", fail)


def stub_fetch(monkeypatch, html=None, error=None):
    def fake(*a, **kw):
        if error is not None:
            raise error
        return html
    monkeypatch.setattr(ifw, "fetch", fake)


# --- terminal guard -----------------------------------------------------

def test_terminal_snapshot_exits_zero_without_fetching(tmp_path, monkeypatch):
    write(tmp_path, monkeypatch, TERMINAL)
    no_fetch(monkeypatch)
    code = ifw.main([])
    assert code == 0


def test_terminal_with_force_fetches_and_reports_no_change(tmp_path, monkeypatch):
    snap = write(tmp_path, monkeypatch, TERMINAL)
    before = snap.read_bytes()
    stub_fetch(monkeypatch, html=LIVE_HTML)  # same content as recorded -> no watched change
    code = ifw.main(["--force"])
    assert code == 0
    assert snap.read_bytes() == before  # --force never writes


def test_terminal_with_update_fetches_and_refreshes(tmp_path, monkeypatch):
    snap = write(tmp_path, monkeypatch, TERMINAL)
    stub_fetch(monkeypatch, html=LIVE_HTML)
    code = ifw.main(["--update"])
    assert code == 0
    data = json.loads(snap.read_text(encoding="utf-8"))
    assert data["voting_live"] is True
    assert data["recorded_at"] == ifw._utc_today_iso()


# --- ordinary comparisons -------------------------------------------------

def test_pre_voting_snapshot_vs_live_page_reports_changes(tmp_path, monkeypatch, capsys):
    write(tmp_path, monkeypatch, PRE_VOTE)
    stub_fetch(monkeypatch, html=LIVE_HTML)
    code = ifw.main([])
    assert code == 2
    out = capsys.readouterr().out
    assert "voting_promised" in out
    assert "voting_live" in out
    assert "project_count_hint" in out


def test_unchanged_signals_exit_zero_and_file_untouched(tmp_path, monkeypatch):
    snap = write(tmp_path, monkeypatch, PRE_VOTE)
    before = snap.read_bytes()
    stub_fetch(monkeypatch, html=PRE_VOTE_HTML)  # identical content -> identical signals
    code = ifw.main([])
    assert code == 0
    assert snap.read_bytes() == before  # comparison branch never writes


def test_fetch_error_exits_one(tmp_path, monkeypatch):
    write(tmp_path, monkeypatch, PRE_VOTE)
    stub_fetch(monkeypatch, error=OSError("network down"))
    code = ifw.main([])
    assert code == 1


# --- --update ---------------------------------------------------------

def test_update_writes_recorded_at_and_signals(tmp_path, monkeypatch):
    snap = write(tmp_path, monkeypatch, PRE_VOTE)
    stub_fetch(monkeypatch, html=LIVE_HTML)
    code = ifw.main(["--update"])
    assert code == 0
    data = json.loads(snap.read_text(encoding="utf-8"))
    assert data["voting_live"] is True
    assert data["recorded_at"] == ifw._utc_today_iso()


def test_update_fetch_error_leaves_file_untouched(tmp_path, monkeypatch):
    snap = write(tmp_path, monkeypatch, PRE_VOTE)
    before = snap.read_bytes()
    stub_fetch(monkeypatch, error=OSError("network down"))
    code = ifw.main(["--update"])
    assert code == 1
    assert snap.read_bytes() == before


# --- ignored keys (recorded_at / text_sha256) ------------------------------

def test_only_recorded_at_and_text_sha256_differ_is_no_change(tmp_path, monkeypatch):
    snap = write(tmp_path, monkeypatch, PRE_VOTE)
    before = snap.read_bytes()
    # Different HTML text (different text_sha256) but identical watched signals.
    stub_fetch(monkeypatch, html=PRE_VOTE_HTML_TRIVIA)
    assert ifw.signals(PRE_VOTE_HTML_TRIVIA)["text_sha256"] != PRE_VOTE_SIGNALS["text_sha256"]
    code = ifw.main([])
    assert code == 0
    assert snap.read_bytes() == before


# --- --force with no snapshot yet ------------------------------------------

def test_force_without_update_and_missing_snapshot_exits_one_no_fetch(tmp_path, monkeypatch):
    snap = write(tmp_path, monkeypatch, None)  # no file at all
    no_fetch(monkeypatch)
    code = ifw.main(["--force"])
    assert code == 1
    assert not snap.exists()


def test_update_force_with_missing_snapshot_still_writes(tmp_path, monkeypatch):
    snap = write(tmp_path, monkeypatch, None)
    stub_fetch(monkeypatch, html=LIVE_HTML)
    code = ifw.main(["--update", "--force"])
    assert code == 0
    assert snap.exists()
    data = json.loads(snap.read_text(encoding="utf-8"))
    assert data["voting_live"] is True


# --- write_snapshot: line endings and temp-file uniqueness -----------------

def test_snapshot_bytes_have_no_crlf(tmp_path, monkeypatch):
    snap = write(tmp_path, monkeypatch, None)
    stub_fetch(monkeypatch, html=LIVE_HTML)
    ifw.main(["--update"])
    assert b"\r\n" not in snap.read_bytes()


def test_write_snapshot_leaves_no_temp_file_behind(tmp_path, monkeypatch):
    snap = write(tmp_path, monkeypatch, None)
    ifw.write_snapshot({"a": 1})
    ifw.write_snapshot({"a": 2})  # a second write must not collide with a leftover temp
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []
    assert json.loads(snap.read_text(encoding="utf-8")) == {"a": 2}


# --- is_terminal / missing keys -----------------------------------------

def test_missing_watched_key_is_not_terminal_and_fetches(tmp_path, monkeypatch):
    incomplete = {"voting_live": True}  # missing every other WATCHED key
    write(tmp_path, monkeypatch, incomplete)
    stub_fetch(monkeypatch, html=LIVE_HTML)
    code = ifw.main([])
    assert code == 2  # fetch was reached (no AssertionError) and other keys differ


def test_invalid_json_snapshot_exits_one_without_fetch(tmp_path, monkeypatch):
    snap = tmp_path / "snap.json"
    snap.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(ifw, "SNAPSHOT", snap)
    no_fetch(monkeypatch)
    code = ifw.main([])
    assert code == 1


def test_snapshot_not_a_dict_exits_one_without_fetch(tmp_path, monkeypatch):
    snap = tmp_path / "snap.json"
    snap.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setattr(ifw, "SNAPSHOT", snap)
    no_fetch(monkeypatch)
    code = ifw.main([])
    assert code == 1


# --- signals() itself -----------------------------------------------------

def test_signals_detects_live_voting_text():
    found = ifw.signals("<p>Voting is open. Open the ballot to cast your vote.</p>")
    assert found["voting_live"] is True
    assert found["voting_promised"] is False


def test_signals_detects_promised_not_live_text():
    found = ifw.signals(PRE_VOTE_HTML)
    assert found["voting_promised"] is True
    assert found["voting_live"] is False


# --- is_terminal helper directly -----------------------------------------

@pytest.mark.parametrize("snapshot, expected", [
    (None, False),
    ({}, False),
    ({"voting_live": True}, False),  # missing other WATCHED keys
    (dict(TERMINAL, voting_live=False), False),
    (TERMINAL, True),
])
def test_is_terminal(snapshot, expected):
    assert ifw.is_terminal(snapshot) is expected


def test_committed_snapshot_is_terminal():
    """The snapshot actually committed to the repo records the vote as live."""
    committed = json.loads(ifw.SNAPSHOT.read_text(encoding="utf-8"))
    assert ifw.is_terminal(committed) is True


# --- static workflow checks -----------------------------------------------

WORKFLOW = (ROOT / ".github" / "workflows" / "watch-innovation-fund.yml").read_text(encoding="utf-8")


def test_workflow_has_no_schedule():
    assert "schedule:" not in WORKFLOW
    assert "cron:" not in WORKFLOW


def test_workflow_keeps_workflow_dispatch():
    assert "workflow_dispatch:" in WORKFLOW


def test_workflow_issue_list_precedes_issue_create():
    list_idx = WORKFLOW.index("gh issue list")
    create_idx = WORKFLOW.index("gh issue create")
    assert list_idx < create_idx


def test_workflow_body_says_manual_run():
    assert "A manual run of the page watcher saw" in WORKFLOW


def test_workflow_invokes_the_script_with_no_flags():
    # The scheduled/manual check must be a plain comparison run, never
    # --force or --update (those are for a maintainer's own terminal).
    assert "python tools/watch/innovation_fund.py 2>&1" in WORKFLOW
    assert "innovation_fund.py --force" not in WORKFLOW
    assert "innovation_fund.py --update" not in WORKFLOW.split("Refresh the snapshot")[0]


def test_workflow_check_step_fails_the_job_on_code_one():
    assert 'if [ "$code" = "0" ] || [ "$code" = "2" ]; then' in WORKFLOW
    assert "exit 0" in WORKFLOW
    assert "exit 1" in WORKFLOW


def test_workflow_restores_set_e_after_capturing_exit_code():
    check_block = WORKFLOW.split("Compare the page against")[1].split("Open or update an issue")[0]
    lines = [line.strip() for line in check_block.splitlines() if line.strip()]
    code_idx = lines.index("code=$?")
    assert lines[code_idx + 1] == "set -e"


def test_workflow_selects_issue_by_exact_title():
    assert "jq -r --arg t \"$TITLE\"" in WORKFLOW
    assert 'select(.title == $t)' in WORKFLOW


def test_workflow_has_both_comment_and_create_branches():
    issue_block = WORKFLOW.split("Open or update an issue")[1]
    assert "gh issue comment" in issue_block
    assert "gh issue create" in issue_block
    assert "if [ -n \"$existing\" ]; then" in issue_block
