"""release-publish.yml's post-publish verification, decided deterministically.

tools/release/publish_verify.py only ever reads. These tests drive it with
scripted observations and a recording sleep; nothing touches GitHub.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release"))

import publish_verify as pv  # noqa: E402

TAG = "v9.9.9"
ASSETS = ["Snapmaker.Studio_9.9.9_x64-setup.exe",
          "snapmaker-studio_9.9.9_amd64_abc.deb", "SHA256SUMS"]


def release(tag=TAG, draft=False, prerelease=False, assets=ASSETS):
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease,
            "assets": [{"name": n} for n in assets]}


def scripted(*values):
    """A reader returning each value in turn; an Exception instance is raised."""
    it = iter(values)

    def read():
        v = next(it)
        if isinstance(v, Exception):
            raise v
        return v
    return read


def run(releases, latests):
    slept: list[float] = []
    logs: list[str] = []
    out = pv.verify_state(scripted(*releases), scripted(*latests), TAG, ASSETS,
                          sleep=slept.append, log=logs.append)
    return out, slept, logs


# --- the retry decision ---------------------------------------------------------

def test_latest_correct_immediately():
    out, slept, _ = run([release()], [TAG])
    assert out.ok and out.kind == "ok" and out.attempts == 1
    assert slept == []


def test_latest_stale_then_correct():
    out, slept, logs = run([release()] * 3, ["v9.9.8", "v9.9.8", TAG])
    assert out.ok and out.attempts == 3
    assert slept == [2, 4]
    assert "'v9.9.8'" in logs[0]


def test_release_public_but_latest_never_converges_is_case_b():
    out, slept, logs = run([release()] * 5, ["v9.9.8"] * 5)
    assert not out.ok and out.kind == "latest"
    assert out.message.startswith("B. RELEASE IS PUBLIC, LATEST POINTER NOT PROPAGATED")
    assert "do not republish" in out.message
    assert slept == [2, 4, 8, 12]            # bounded: five attempts, 26 s in total
    assert out.attempts == 5 and len(logs) == 5


def test_release_missing_is_case_a():
    out, slept, _ = run([None] * 5, ["v9.9.8"] * 5)
    assert not out.ok and out.kind == "release"
    assert out.message.startswith("A. RELEASE MISSING OR WRONG")
    assert "no release exists for tag v9.9.9" in out.message
    assert slept == [2, 4, 8, 12]


def test_wrong_tag_is_case_a():
    out, _, _ = run([release(tag="v9.9.8")] * 5, [TAG] * 5)
    assert out.kind == "release" and "'v9.9.8'" in out.message


def test_api_transient_failure_then_success():
    out, slept, logs = run([RuntimeError("HTTP 502"), release()], [TAG])
    assert out.ok and out.attempts == 2
    assert slept == [2]
    assert "GitHub API read failed: HTTP 502" in logs[0]


def test_api_never_readable_is_case_c():
    out, slept, _ = run([RuntimeError("HTTP 503")] * 5, [])
    assert not out.ok and out.kind == "api"
    assert out.message.startswith("C. GITHUB API UNREADABLE")
    assert slept == [2, 4, 8, 12]


def test_a_release_that_turns_up_during_the_retries_is_accepted():
    out, _, _ = run([None, release()], [None, TAG])
    assert out.ok and out.attempts == 2


def test_the_final_observation_decides_the_failure_case():
    """A release seen correctly, then a later API failure: the last reading wins,
    so the message never claims more than was last observed."""
    out, _, _ = run([release()] + [RuntimeError("boom")] * 4, ["v9.9.8"])
    assert out.kind == "api"


@pytest.mark.parametrize("rel, expect", [
    (release(draft=True), "still a draft"),
    (release(prerelease=True), "prerelease"),
    (release(assets=ASSETS[:2]), "has assets"),
    (release(assets=ASSETS + ["extra.zip"]), "has assets"),
])
def test_a_release_that_is_not_public_stable_and_complete_is_case_a(rel, expect):
    kind, detail = pv.assess(rel, TAG, TAG, ASSETS)
    assert kind == "release" and expect in detail


def test_the_release_is_checked_before_the_latest_pointer():
    """A draft is never reported as merely 'not propagated'."""
    kind, _ = pv.assess(release(draft=True), "v9.9.8", TAG, ASSETS)
    assert kind == "release"


def test_the_helper_cannot_write_to_github():
    """Every gh call is an explicit GET; nothing edits, creates or uploads."""
    src = (ROOT / "tools/release/publish_verify.py").read_text(encoding="utf-8")
    assert '["gh", "api", "--method", "GET", endpoint]' in src
    for verb in ("release create", "release edit", "release upload", "release delete",
                 '"POST"', '"PATCH"', '"DELETE"', "git push", "git tag"):
        assert verb not in src, verb


# --- the hash check ---------------------------------------------------------------

@pytest.fixture
def gated(tmp_path: Path):
    blobs = {ASSETS[0]: b"windows", ASSETS[1]: b"linux"}
    sums = "".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in blobs.items())
    dist = tmp_path / "dist"
    live = tmp_path / "live"
    dist.mkdir()
    live.mkdir()
    (dist / "SHA256SUMS").write_text(sums, encoding="utf-8")
    for n, b in blobs.items():
        (live / n).write_bytes(b)
    (live / "SHA256SUMS").write_text(sums, encoding="utf-8")
    return dist / "SHA256SUMS", live


def test_matching_assets_including_sha256sums_itself_pass(gated):
    """The v1.0.0-v1.2.0 step died here: SHA256SUMS has no line for itself."""
    sums, live = gated
    assert pv.verify_hashes(sums, live, ASSETS) == []


def test_a_changed_binary_is_named(gated):
    sums, live = gated
    (live / ASSETS[1]).write_bytes(b"tampered")
    [problem] = pv.verify_hashes(sums, live, ASSETS)
    assert problem.startswith(f"{ASSETS[1]}: re-hashed to")


def test_a_changed_sha256sums_is_named(gated):
    sums, live = gated
    (live / "SHA256SUMS").write_text("0" * 64 + "  other\n", encoding="utf-8")
    [problem] = pv.verify_hashes(sums, live, ASSETS)
    assert problem.startswith("SHA256SUMS: the live file differs")


def test_an_asset_with_no_expected_hash_fails_loudly(gated):
    sums, live = gated
    (live / "extra.bin").write_bytes(b"x")
    [problem] = pv.verify_hashes(sums, live, ASSETS + ["extra.bin"])
    assert "no expected hash" in problem


def test_a_missing_download_fails_loudly(gated):
    sums, live = gated
    (live / ASSETS[0]).unlink()
    [problem] = pv.verify_hashes(sums, live, ASSETS)
    assert problem == f"{ASSETS[0]}: not downloaded"


def test_star_prefixed_binary_mode_names_are_parsed():
    assert pv.parse_sums("ab" * 32 + " *a.exe\n") == {"a.exe": "ab" * 32}


def test_the_hashes_command_line_exits_nonzero_with_a_message(gated, capsys):
    sums, live = gated
    (live / ASSETS[0]).write_bytes(b"tampered")
    args = ["hashes", "--sums", str(sums), "--dir", str(live)]
    for a in ASSETS:
        args += ["--asset", a]
    assert pv.main(args) == 1
    assert "needs operator attention, not a republish" in capsys.readouterr().err


def test_a_hung_gh_call_becomes_a_retryable_api_error(monkeypatch):
    """A gh call that never answers must not stretch the bounded retry."""
    import subprocess

    def hang(*args, **kwargs):
        assert kwargs.get("timeout") == pv.GH_TIMEOUT
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(pv.subprocess, "run", hang)
    with pytest.raises(RuntimeError, match="no answer within"):
        pv._read_latest("owner/repo")
