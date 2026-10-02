"""release-publish.yml's post-publish verification, decided deterministically.

tools/release/publish_verify.py only ever reads. These tests drive it with
scripted observations and a recording sleep; nothing touches GitHub.
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
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
    """Every gh call is an explicit GET or a read-only download; nothing
    edits, creates, uploads or looks the release up with `gh release view`
    (S7: `gh` runs the published-release and draft lookups concurrently and
    reports "release not found" if either transiently errors, so `view`-based
    presence checks are unsafe -- `release_present`/`list_releases` replace
    it)."""
    src = (ROOT / "tools/release/publish_verify.py").read_text(encoding="utf-8")
    assert '["gh", "api", "--method", "GET", endpoint]' in src
    assert '"gh", "release", "download"' in src
    for verb in ("release create", "release edit", "release upload", "release delete",
                 "release view", '"POST"', '"PATCH"', '"DELETE"', "git push", "git tag"):
        assert verb not in src, verb


def test_only_two_gh_argv_prefixes_appear_as_subprocess_calls_ast():
    """AST-based (item 6): every `subprocess.run(...)` call's first
    positional argument must be a literal list whose leading string
    constants match one of exactly two allowed prefixes. Robust to
    formatting/whitespace changes a regex would be fragile against."""
    src = (ROOT / "tools/release/publish_verify.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    allowed_prefixes = [["gh", "api", "--method", "GET"], ["gh", "release", "download"]]
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_subprocess_run = (isinstance(func, ast.Attribute) and func.attr == "run"
                             and isinstance(func.value, ast.Name) and func.value.id == "subprocess")
        if not is_subprocess_run:
            continue
        checked += 1
        assert node.args, "subprocess.run call with no positional argv"
        first = node.args[0]
        assert isinstance(first, ast.List), f"argv must be a literal list, got {ast.dump(first)}"
        elts = [el.value if isinstance(el, ast.Constant) and isinstance(el.value, str) else None
                for el in first.elts]
        assert any(elts[:len(p)] == p for p in allowed_prefixes), f"argv does not start with an allowed prefix: {elts}"
    assert checked >= 2, "expected at least the two known subprocess.run call sites"


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


# --- SemVer 2.0 precedence -------------------------------------------------------

def test_semver_ordering_numeric():
    assert pv.semver_key("v1.10.0") > pv.semver_key("v1.9.9")
    assert pv.semver_key("v2.0.0") > pv.semver_key("v1.99.99")


def test_semver_prerelease_precedence_chain():
    chain = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta.2",
             "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]
    keys = [pv.semver_key(t) for t in chain]
    assert keys == sorted(keys)
    assert all(a < b for a, b in zip(keys, keys[1:]))


def test_semver_beta_dotted_numeric_prerelease_below_release():
    assert pv.semver_key("0.4.0-beta.20.4") < pv.semver_key("0.4.0")


def test_semver_build_metadata_is_ignored_for_precedence():
    assert pv.semver_key("1.2.3+build.5") == pv.semver_key("1.2.3")
    assert pv.semver_key("1.2.3-rc.1+build.5") == pv.semver_key("1.2.3-rc.1")


@pytest.mark.parametrize("tag", ["vv1.0.0", "1.2", "latest", "v01.2.3", "1.2.3-01", "1.02.3"])
def test_semver_invalid_tags_are_none(tag):
    assert pv.semver_key(tag) is None


# --- should_be_latest / list_releases / release_present --------------------------

def _rel(tag, draft=False, prerelease=False):
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease}


def test_should_be_latest_true_when_highest():
    releases = [_rel("v1.0.0"), _rel("v1.1.0")]
    assert pv.should_be_latest("v2.0.0", releases) is True


def test_should_be_latest_false_when_a_newer_release_exists():
    releases = [_rel("v2.0.0")]
    assert pv.should_be_latest("v1.0.0", releases) is False


def test_should_be_latest_ignores_drafts_prereleases_and_unparseable(capsys):
    releases = [_rel("v9.0.0", draft=True), _rel("v9.0.0", prerelease=True), _rel("not-semver")]
    assert pv.should_be_latest("v1.0.0", releases) is True
    assert "ignoring unparseable" in capsys.readouterr().err


def test_should_be_latest_excludes_the_candidate_itself():
    releases = [_rel("v1.0.0")]
    assert pv.should_be_latest("v1.0.0", releases) is True


def test_should_be_latest_rejects_a_prerelease_candidate():
    with pytest.raises(ValueError):
        pv.should_be_latest("v1.0.0-rc.1", [])


def test_should_be_latest_rejects_an_unparseable_candidate():
    with pytest.raises(ValueError):
        pv.should_be_latest("not-a-version", [])


def test_should_be_latest_rejects_an_equal_precedence_alias():
    releases = [_rel("1.2.0+buildxyz")]
    with pytest.raises(ValueError):
        pv.should_be_latest("v1.2.0", releases)


def test_list_releases_paginates_across_full_and_short_pages(monkeypatch):
    page1 = [_rel(f"v0.{i}.0") for i in range(100)]
    page2 = [_rel(f"v1.{i}.0") for i in range(100)]
    page3 = [_rel("v2.0.0")]
    calls = []

    def fake_get(endpoint, **kw):
        calls.append(endpoint)
        if endpoint.endswith("page=1"):
            return page1
        if endpoint.endswith("page=2"):
            return page2
        if endpoint.endswith("page=3"):
            return page3
        raise AssertionError(f"unexpected page: {endpoint}")

    monkeypatch.setattr(pv, "_gh_get", fake_get)
    result = pv.list_releases("owner/repo")
    assert len(result) == 201
    assert len(calls) == 3


def test_list_releases_propagates_an_api_error(monkeypatch):
    def fake_get(endpoint, **kw):
        raise RuntimeError("HTTP 500")

    monkeypatch.setattr(pv, "_gh_get", fake_get)
    with pytest.raises(RuntimeError, match="HTTP 500"):
        pv.list_releases("owner/repo")


def test_list_releases_a_full_page_10_raises(monkeypatch):
    def fake_get(endpoint, **kw):
        return [_rel(f"v0.{i}.0") for i in range(100)]

    monkeypatch.setattr(pv, "_gh_get", fake_get)
    with pytest.raises(RuntimeError, match="page 10"):
        pv.list_releases("owner/repo")


def test_release_present_matches_a_draft():
    assert pv.release_present("v1.0.0", [_rel("v1.0.0", draft=True)]) is True


def test_release_present_matches_a_published_release():
    assert pv.release_present("v1.0.0", [_rel("v1.0.0")]) is True


def test_release_present_false_when_absent_across_several_entries():
    releases = [_rel("v1.0.0"), _rel("v1.1.0"), _rel("v1.2.0")]
    assert pv.release_present("v2.0.0", releases) is False


def test_exists_cli_absent_present_and_error(monkeypatch):
    monkeypatch.setattr(pv, "list_releases", lambda repo: [_rel("v1.0.0")])
    assert pv.main(["exists", "--repo", "o/r", "--tag", "v2.0.0"]) == 0
    assert pv.main(["exists", "--repo", "o/r", "--tag", "v1.0.0"]) == 3

    def fake_list_raises(repo):
        raise RuntimeError("HTTP 500")

    monkeypatch.setattr(pv, "list_releases", fake_list_raises)
    assert pv.main(["exists", "--repo", "o/r", "--tag", "v1.0.0"]) == 1


def test_should_be_latest_cli_prints_true_or_false(monkeypatch, capsys):
    monkeypatch.setattr(pv, "list_releases", lambda repo: [_rel("v1.0.0")])
    assert pv.main(["should-be-latest", "--repo", "o/r", "--tag", "v2.0.0"]) == 0
    assert capsys.readouterr().out.strip() == "true"
    assert pv.main(["should-be-latest", "--repo", "o/r", "--tag", "v0.5.0"]) == 0
    assert capsys.readouterr().out.strip() == "false"


def test_should_be_latest_cli_errors_on_a_prerelease_candidate(monkeypatch, capsys):
    monkeypatch.setattr(pv, "list_releases", lambda repo: [])
    assert pv.main(["should-be-latest", "--repo", "o/r", "--tag", "v1.0.0-rc.1"]) == 1
    assert "could not decide" in capsys.readouterr().err


# --- assess(expect_latest=...) ----------------------------------------------------

def test_assess_expect_latest_false_when_something_newer_is_latest():
    kind, _ = pv.assess(release(), "v10.0.0", TAG, ASSETS, expect_latest=False)
    assert kind == "ok"


def test_assess_expect_latest_false_when_latest_equals_tag():
    kind, _ = pv.assess(release(), TAG, TAG, ASSETS, expect_latest=False)
    assert kind == "latest"


def test_assess_expect_latest_false_when_latest_is_lower():
    kind, _ = pv.assess(release(), "v0.1.0", TAG, ASSETS, expect_latest=False)
    assert kind == "latest"


def test_assess_expect_latest_false_when_latest_is_unparseable():
    kind, _ = pv.assess(release(), "not-a-version", TAG, ASSETS, expect_latest=False)
    assert kind == "latest"


def test_assess_expect_latest_false_when_latest_is_none():
    kind, _ = pv.assess(release(), None, TAG, ASSETS, expect_latest=False)
    assert kind == "latest"


def test_assess_expect_latest_none_skips_the_latest_check():
    kind, _ = pv.assess(release(), "whatever-garbage", TAG, ASSETS, expect_latest=None)
    assert kind == "ok"


def test_assess_default_keyword_keeps_old_behaviour():
    kind, _ = pv.assess(release(), TAG, TAG, ASSETS)
    assert kind == "ok"
    kind, _ = pv.assess(release(), "v9.9.8", TAG, ASSETS)
    assert kind == "latest"


# --- verify_state: a latest-read failure cannot mask a release problem -----------

def test_a_latest_read_failure_cannot_mask_a_release_problem():
    out, _, _ = run([release(draft=True)] * 5, [RuntimeError("boom")] * 5)
    assert out.kind == "release"
    assert "draft" in out.message


# --- docs/RELEASE_METADATA.md -----------------------------------------------------

DOCS_METADATA = ROOT / "docs" / "RELEASE_METADATA.md"


def test_metadata_on_the_real_release_metadata_file():
    fields = pv.parse_metadata(DOCS_METADATA.read_text(encoding="utf-8"))
    for key in pv.REQUIRED_METADATA_FIELDS:
        assert key in fields
    lines = pv.metadata_lines(fields)
    assert len(lines) == 8
    keys = [l.split("=", 1)[0] for l in lines]
    assert keys == ["version", "win_name", "win_size", "win_sha256",
                     "linux_name", "linux_size", "linux_sha256", "build_run"]


def test_metadata_missing_key_raises():
    with pytest.raises(ValueError, match="missing"):
        pv.parse_metadata("## Current release\n\n| Field | Value |\n|---|---|\n| Version | v1.0.0 |\n")


def test_metadata_cli_on_the_real_file(capsys):
    assert pv.main(["metadata", "--path", str(DOCS_METADATA)]) == 0
    out = capsys.readouterr().out
    assert out.count("=") >= 8


def test_metadata_cli_missing_key_exits_1(tmp_path):
    bad = tmp_path / "meta.md"
    bad.write_text("## Current release\n\n| Field | Value |\n|---|---|\n| Version | v1.0.0 |\n", encoding="utf-8")
    assert pv.main(["metadata", "--path", str(bad)]) == 1


# --- expected_sums -----------------------------------------------------------------

def test_expected_sums_bytes_match_real_sha256sum_format():
    win_sha = hashlib.sha256(b"windows").hexdigest()
    linux_sha = hashlib.sha256(b"linux").hexdigest()
    got = pv.expected_sums("Snapmaker.Studio_1.2.0_x64-setup.exe", win_sha,
                            "snapmaker-studio_1.2.0_amd64.deb", linux_sha)
    assert got == (f"{win_sha}  Snapmaker.Studio_1.2.0_x64-setup.exe\n"
                    f"{linux_sha}  snapmaker-studio_1.2.0_amd64.deb\n").encode("ascii")


def test_expected_sums_rejects_a_bad_name():
    with pytest.raises(ValueError):
        pv.expected_sums("bad name!.exe", "a" * 64, "ok.deb", "b" * 64)


def test_expected_sums_rejects_a_bad_hash():
    with pytest.raises(ValueError):
        pv.expected_sums("ok.exe", "not-hex", "ok.deb", "b" * 64)


def test_expected_sums_cli_writes_the_file(tmp_path):
    out = tmp_path / "SHA256SUMS"
    win_sha, linux_sha = "a" * 64, "b" * 64
    args = ["expected-sums", "--win-name", "win.exe", "--win-sha256", win_sha,
            "--linux-name", "lin.deb", "--linux-sha256", linux_sha, "--out", str(out)]
    assert pv.main(args) == 0
    assert out.read_text() == f"{win_sha}  win.exe\n{linux_sha}  lin.deb\n"


# --- combine -----------------------------------------------------------------------

def _outcome(ok, kind="ok", message="msg"):
    return pv.Outcome(ok, kind, 1, message)


def test_combine_pass_pass():
    ok, report = pv.combine(None, _outcome(True), [])
    assert ok
    assert "LATEST DECISION: PASS" in report and "STATE: PASS" in report and "HASHES: PASS" in report


def test_combine_state_fail_hashes_pass():
    ok, report = pv.combine(None, _outcome(False, kind="release"), [])
    assert not ok
    assert "STATE: FAIL" in report


def test_combine_state_pass_hashes_fail():
    ok, report = pv.combine(None, _outcome(True), ["a.exe: not downloaded"])
    assert not ok
    assert "HASHES: FAIL" in report and "a.exe: not downloaded" in report


def test_combine_state_fail_hashes_fail():
    ok, report = pv.combine(None, _outcome(False, kind="api"), ["x: bad"])
    assert not ok


def test_combine_latest_failure_alone_fails_even_if_state_and_hashes_pass():
    ok, report = pv.combine("could not enumerate releases", _outcome(True), [])
    assert not ok
    assert "LATEST DECISION: FAIL - could not enumerate releases" in report
    assert "STATE: PASS" in report and "HASHES: PASS" in report


# --- the `verify` CLI (main), everything monkeypatched ----------------------------

def test_verify_cli_reports_a_download_failure_but_still_runs_hashes(monkeypatch, tmp_path):
    two_assets = ASSETS[:2]
    monkeypatch.setattr(pv, "list_releases", lambda repo, **kw: [])
    monkeypatch.setattr(pv, "_read_release", lambda repo, tag, **kw: release(assets=two_assets))
    monkeypatch.setattr(pv, "_read_latest", lambda repo, **kw: TAG)

    def fake_download(repo, tag, name, dest_dir, **kw):
        if name == two_assets[0]:
            return f"{name}: gh release download failed: boom"
        (dest_dir / name).write_bytes(b"x")
        return None

    monkeypatch.setattr(pv, "_download_asset", fake_download)

    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{hashlib.sha256(b'x').hexdigest()}  {two_assets[1]}\n", encoding="utf-8")
    out_dir = tmp_path / "live"

    args = ["verify", "--repo", "o/r", "--tag", TAG, "--sums", str(sums), "--dir", str(out_dir)]
    for a in two_assets:
        args += ["--asset", a]
    rc = pv.main(args)
    assert rc == 1


def test_verify_cli_passes_when_everything_matches(monkeypatch, tmp_path):
    two_assets = ASSETS[:2]
    monkeypatch.setattr(pv, "list_releases", lambda repo, **kw: [])
    monkeypatch.setattr(pv, "_read_release", lambda repo, tag, **kw: release(assets=two_assets))
    monkeypatch.setattr(pv, "_read_latest", lambda repo, **kw: TAG)

    def fake_download(repo, tag, name, dest_dir, **kw):
        (dest_dir / name).write_bytes(b"x")
        return None

    monkeypatch.setattr(pv, "_download_asset", fake_download)

    sums = tmp_path / "SHA256SUMS"
    digest = hashlib.sha256(b"x").hexdigest()
    sums.write_text("".join(f"{digest}  {n}\n" for n in two_assets), encoding="utf-8")
    out_dir = tmp_path / "live"

    args = ["verify", "--repo", "o/r", "--tag", TAG, "--sums", str(sums), "--dir", str(out_dir)]
    for a in two_assets:
        args += ["--asset", a]
    assert pv.main(args) == 0


# --- Deadline / time budget (Sol HIGH) --------------------------------------------

def test_deadline_cap_shrinks_with_remaining_time():
    clock = {"t": 0.0}
    d = pv.Deadline(10, clock=lambda: clock["t"])
    assert d.cap(20) == 10  # capped by remaining, not the per-call ceiling
    clock["t"] = 7.0
    assert abs(d.cap(20) - 3) < 1e-9
    assert abs(d.cap(2) - 2) < 1e-9  # the smaller of the two caps still wins
    clock["t"] = 15.0
    assert d.cap(20) == 0
    assert d.expired


def test_list_releases_per_page_timeout_shrinks_with_remaining(monkeypatch):
    clock = {"t": 0.0}
    d = pv.Deadline(10, clock=lambda: clock["t"])
    timeouts = []

    def fake_get(endpoint, timeout=pv.GH_TIMEOUT):
        timeouts.append(timeout)
        return [_rel("v1.0.0")]  # a short page ends the loop after 1 call

    monkeypatch.setattr(pv, "_gh_get", fake_get)
    pv.list_releases("owner/repo", deadline=d)
    assert timeouts == [10]  # remaining (10s) is smaller than GH_TIMEOUT (20s)


def test_list_releases_deadline_exceeded_before_next_page_raises(monkeypatch):
    clock = {"t": 0.0}
    d = pv.Deadline(5, clock=lambda: clock["t"])

    def fake_get(endpoint, timeout=pv.GH_TIMEOUT):
        clock["t"] += 6  # blow the whole budget inside the first call
        return [_rel(f"v0.{i}.0") for i in range(100)]  # full page -> would continue

    monkeypatch.setattr(pv, "_gh_get", fake_get)
    with pytest.raises(RuntimeError, match="deadline exceeded"):
        pv.list_releases("owner/repo", deadline=d)


def test_verify_state_deadline_exceeded_stops_the_retry_loop():
    clock = {"t": 0.0}
    d = pv.Deadline(1, clock=lambda: clock["t"])

    def slow_sleep(seconds):
        clock["t"] += seconds

    out = pv.verify_state(scripted(release(draft=True)), scripted("v9.9.8"), TAG, ASSETS,
                          sleep=slow_sleep, log=lambda *a: None, deadline=d)
    assert out.ok is False
    assert out.kind == "deadline"
    assert out.attempts == 1
    assert "deadline" in out.message.lower()


def test_verify_state_without_a_deadline_is_unaffected():
    """No deadline given -> identical to the pre-deadline behaviour."""
    out, slept, _ = run([release()] * 5, ["v9.9.8"] * 5)
    assert not out.ok and out.kind == "latest"
    assert slept == [2, 4, 8, 12]
    assert out.attempts == 5


def test_verify_cli_deadline_exceeded_still_prints_a_combined_report(monkeypatch, tmp_path, capsys):
    """Requirement C: the combined report must always print, even when the
    end-to-end deadline is exhausted before every check could run."""
    two_assets = ASSETS[:2]
    monkeypatch.setattr(pv, "list_releases", lambda repo, **kw: [_rel("v1.0.0")])
    monkeypatch.setattr(pv, "_read_release", lambda repo, tag, **kw: release(assets=two_assets))
    monkeypatch.setattr(pv, "_read_latest", lambda repo, **kw: TAG)

    downloaded = []

    def fake_download(repo, tag, name, dest_dir, **kw):
        downloaded.append(name)
        (dest_dir / name).write_bytes(b"x")
        return None

    monkeypatch.setattr(pv, "_download_asset", fake_download)

    sums = tmp_path / "SHA256SUMS"
    sums.write_text("", encoding="utf-8")
    out_dir = tmp_path / "live"

    args = ["verify", "--repo", "o/r", "--tag", TAG, "--sums", str(sums), "--dir", str(out_dir),
            "--deadline-seconds", "0"]
    for a in two_assets:
        args += ["--asset", a]
    rc = pv.main(args)
    out = capsys.readouterr().out

    assert rc == 1
    assert "LATEST DECISION: FAIL" in out
    assert "STATE:" in out
    assert "HASHES: FAIL" in out
    assert downloaded == []  # every download skipped; the deadline was already gone
    for a in two_assets:
        assert f"{a}: not downloaded" in out


def test_download_asset_uses_the_given_timeout_not_the_module_default(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(pv.subprocess, "run", fake_run)
    err = pv._download_asset("o/r", TAG, "a.exe", Path("."), timeout=3.5)
    assert seen["timeout"] == 3.5
    assert "3.5s" in err


# --- encoding (Opus: UnicodeDecodeError on Windows) --------------------------------

def test_gh_get_and_download_asset_pass_explicit_utf8_encoding():
    src = (ROOT / "tools/release/publish_verify.py").read_text(encoding="utf-8")
    assert src.count('encoding="utf-8"') >= 2


# --- static checks on release-publish.yml (text-based; no PyYAML dependency) -----

WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release-publish.yml"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _job_blocks(text: str) -> dict[str, str]:
    """Split the `jobs:` section into per-job text blocks on a job-name line
    (two-space indent, `name:` alone) -- avoids requiring PyYAML, which is
    not a backend dependency (see ci.yml)."""
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == "jobs:")
    job_starts: list[tuple[str, int]] = []
    for i in range(start + 1, len(lines)):
        m = re.match(r"^  (\S+):$", lines[i])
        if m:
            job_starts.append((m.group(1), i))
    blocks: dict[str, str] = {}
    for idx, (name, line_no) in enumerate(job_starts):
        end = job_starts[idx + 1][1] if idx + 1 < len(job_starts) else len(lines)
        blocks[name] = "\n".join(lines[line_no:end])
    return blocks


def test_workflow_job_splitter_finds_the_three_jobs():
    blocks = _job_blocks(_workflow_text())
    assert set(blocks) == {"publish", "flip", "verify"}

def test_workflow_top_level_permissions_lack_contents_write():
    text = _workflow_text()
    top = text.split("\njobs:")[0]
    perms_block = top.split("\npermissions:")[1].split("\nconcurrency:")[0]
    assert "contents: write" not in perms_block
    assert "contents: read" in perms_block


def test_workflow_job_graph_is_publish_then_flip_then_verify():
    """#50: `publish` (gates + draft) has no `needs:`; the irreversible flip
    is its own job after it; `verify` needs both, so it waits for the flip but
    reads the ALREADY-DELIVERED output of the completed gating job."""
    blocks = _job_blocks(_workflow_text())
    assert "needs:" not in blocks["publish"]

    def _needs(job: str) -> str:
        return next(l.strip() for l in blocks[job].splitlines() if l.strip().startswith("needs:"))

    assert _needs("flip") == "needs: publish"
    assert _needs("verify") == "needs: [publish, flip]"

def test_workflow_verify_only_input_is_boolean_default_false():
    text = _workflow_text()
    block = text[text.index("verify_only:"):]
    block = block[:block.index("\npermissions:")]
    assert "type: boolean" in block
    assert "default: false" in block


def test_workflow_job_conditions_are_exactly_the_expected_expressions():
    """Item 4: exact string match, not just a substring check -- flipping
    `!= true` to `== true` (or any other mutation) must fail this test."""
    blocks = _job_blocks(_workflow_text())

    def _if(job: str) -> str:
        return next(l.strip() for l in blocks[job].splitlines() if l.strip().startswith("if:"))

    assert _if("publish") == "if: github.event_name == 'push' || inputs.verify_only != true"
    # #50: the flip fires only for a REAL publish that the gating job armed.
    assert _if("flip") == "if: needs.publish.outputs.attempted == 'true'"
    assert _if("verify") == (
        "if: ${{ !cancelled() && ((github.event_name == 'workflow_dispatch' && inputs.verify_only == true) "
        "|| needs.publish.outputs.attempted == 'true') }}"
    )

def test_workflow_concurrency_group_covers_both_paths():
    text = _workflow_text()
    concurrency = text[text.index("\nconcurrency:"):text.index("\njobs:")]
    assert "verify_only" in concurrency
    assert "release-publish" in concurrency


def test_workflow_verify_job_permissions_and_token():
    verify = _job_blocks(_workflow_text())["verify"]
    assert "contents: read" in verify
    assert "GH_TOKEN" in verify
    for banned in ("gh release create", "gh release edit", "gh release delete",
                   "gh release upload", "git tag", "git push", "--cleanup-tag",
                   "git checkout", "git reset", "git clean", "pv.py exists"):
        assert banned not in verify, banned


def test_workflow_verify_job_mkdir_precedes_every_tmp_verify_write():
    lines = _job_blocks(_workflow_text())["verify"].splitlines()
    mkdir_idx = next(i for i, l in enumerate(lines) if "mkdir -p /tmp/verify" in l)
    for i, l in enumerate(lines):
        if "/tmp/verify/" in l and "mkdir -p /tmp/verify" not in l:
            assert i > mkdir_idx, l


def test_workflow_verify_job_mkdir_step_precedes_every_other_tag_dependent_step():
    """Round 3: the tag is now resolved+validated in its own step before
    the scratch-directory mkdir (which itself must still precede every
    other /tmp/verify/ write -- see the mkdir-precedes test above). Assert
    the mkdir is among the first few steps, before any step that resolves
    the tag's commit or touches metadata."""
    steps = _job_blocks(_workflow_text())["verify"].split("      - ")
    mkdir_step_idx = next(i for i, s in enumerate(steps) if "mkdir -p /tmp/verify/expected /tmp/verify/live" in s)
    target_step_idx = next(i for i, s in enumerate(steps) if "Resolve the tag's own commit" in s)
    assert mkdir_step_idx < target_step_idx


def test_workflow_publish_refuse_step_uses_exists_not_release_view():
    """N1: the `gh release view` ban is scoped to ONLY the refuse-if-exists
    step; draft creation and Gate 4 legitimately keep calling it."""
    publish = _job_blocks(_workflow_text())["publish"]
    steps = publish.split("      - name:")
    refuse = next(s for s in steps if s.strip().startswith("Refuse if"))
    assert "pv.py exists" in refuse
    assert "release view" not in refuse


def test_workflow_publish_refuse_step_captures_rc_safely_under_set_e():
    """N2: `python3 ... || rc=$?` then `case "$rc"`, never a bare `rc=$?`
    that `set -e` would already have aborted on."""
    publish = _job_blocks(_workflow_text())["publish"]
    steps = publish.split("      - name:")
    refuse = next(s for s in steps if s.strip().startswith("Refuse if"))
    assert "rc=0" in refuse
    assert "|| rc=$?" in refuse
    assert re.search(r"(?<!\|\| )rc=\$\?", refuse) is None
    assert 'case "$rc"' in refuse


def test_workflow_publish_latest_step_captures_rc_safely_under_set_e():
    publish = _job_blocks(_workflow_text())["publish"]
    steps = publish.split("      - name:")
    latest_step = next(s for s in steps if s.strip().startswith("Decide whether"))
    assert "rc=0" in latest_step
    assert "|| rc=$?" in latest_step
    assert re.search(r"(?<!\|\| )rc=\$\?", latest_step) is None


def test_workflow_publish_still_legitimately_uses_release_view_elsewhere():
    """N1: draft creation and Gate 4 (release-publish.yml) still use it."""
    publish = _job_blocks(_workflow_text())["publish"]
    assert publish.count("gh release view") >= 2


def test_workflow_publish_decides_latest_before_the_draft_and_guards_it():
    publish = _job_blocks(_workflow_text())["publish"]
    latest_idx = publish.index("should-be-latest")
    create_idx = publish.index('gh release create "')  # the invocation, not the earlier comment mention
    assert latest_idx < create_idx
    assert 'case "$latest" in' in publish
    assert 'true|false' in publish


def test_workflow_flip_has_no_bare_latest_flag():
    """The `--latest` value always comes with an explicit `=<true|false>`; the
    flip (the only place `gh release edit` runs) and the gating job both
    stay free of a bare `--latest`."""
    blocks = _job_blocks(_workflow_text())
    for name in ("publish", "flip"):
        assert re.search(r"--latest(?!=)", blocks[name]) is None, name
    assert "--latest=" in blocks["flip"]

def test_workflow_no_rc_capture_anywhere_is_bare_after_set_e():
    """Applies the N2 rc-capture pattern check to the whole file, not just
    the two steps that need it -- if a future step captures $? it must also
    use the safe `|| rc=$?` form."""
    text = _workflow_text()
    assert re.search(r"(?<!\|\| )\brc=\$\?", text) is None


# --- expression injection (Sol MEDIUM + Opus LOW) -----------------------------------

# `env:` and `with:` mappings, and `if:` conditions, are evaluated by the
# Actions runner itself and are the SAFE place for a `${{ }}` expression;
# only its appearance inside a `run:` script body (where it is substituted
# as literal text into a shell command before the shell ever runs) is an
# injection risk. This allowlist is intentionally empty: every value a
# script needs is threaded through `env:` or a `$GITHUB_ENV` export instead.
RUN_BLOCK_EXPRESSION_ALLOWLIST: tuple[str, ...] = ()


def _run_block_bodies(text: str) -> list[tuple[int, str]]:
    """(start_line, body_text) for every multi-line `run: |` block in the
    file, found the same indentation-based way GitHub Actions itself
    delimits a block scalar -- no PyYAML dependency (see `_job_blocks`)."""
    lines = text.splitlines()
    blocks: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)run:\s*\|\s*$", lines[i])
        if not m:
            i += 1
            continue
        indent = len(m.group(1))
        start = i + 1
        j = start
        body_lines = []
        while j < len(lines):
            line = lines[j]
            if line.strip() == "":
                body_lines.append(line)
                j += 1
                continue
            this_indent = len(line) - len(line.lstrip())
            if this_indent <= indent:
                break
            body_lines.append(line)
            j += 1
        blocks.append((start + 1, "\n".join(body_lines)))
        i = j
    return blocks


def test_workflow_no_expressions_inside_any_run_block():
    """Item 2 (Sol MEDIUM + Opus LOW): no `${{ ... }}` may appear inside any
    `run:` script body anywhere in the file -- every tag/input/step-output
    value a script needs must come from `env:` or a `$GITHUB_ENV` export and
    be referenced as a plain shell variable instead."""
    text = _workflow_text()
    blocks = _run_block_bodies(text)
    assert len(blocks) >= 15, "expected many multi-line run: blocks in this workflow"
    offenders = []
    for start_line, body in blocks:
        for offset, line in enumerate(body.splitlines()):
            if "${{" in line and not any(allowed in line for allowed in RUN_BLOCK_EXPRESSION_ALLOWLIST):
                offenders.append(f"line {start_line + offset}: {line.strip()}")
    assert offenders == []


def test_workflow_single_line_run_steps_have_no_expressions_either():
    text = _workflow_text()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("run:") and "|" not in stripped.split("run:", 1)[1][:2]:
            assert "${{" not in stripped, stripped


def test_workflow_github_token_lives_in_env_not_a_run_block():
    """github.token is the one context value that legitimately needs a
    `${{ }}` expression at all -- confirm it only ever appears in `env:`."""
    text = _workflow_text()
    for line in text.splitlines():
        if "github.token" in line:
            assert re.match(r"^\s*GH_TOKEN:\s*\$\{\{\s*github\.token\s*\}\}\s*$", line), line


# --- round 3: structural timeout fix (Sol HIGH) + tag/metadata validation ---------

def test_workflow_publish_job_outputs_tag_attempted_and_latest():
    publish = _job_blocks(_workflow_text())["publish"]
    outputs_block = publish.split("\n    outputs:")[1].split("\n    env:")[0]
    assert "tag: ${{ steps.input.outputs.tag }}" in outputs_block
    assert "attempted: ${{ steps.arm.outputs.attempted }}" in outputs_block
    assert "latest: ${{ steps.latest.outputs.latest }}" in outputs_block
    assert "published" not in outputs_block


def test_workflow_the_flip_lives_only_in_the_flip_job():
    """#50: `gh release edit` (the irreversible flip-to-public) runs exactly
    once in the whole file, inside the dedicated `flip` job -- never in the
    gating job, whose outputs must already be delivered before it happens."""
    text = _workflow_text()
    blocks = _job_blocks(text)
    def code(s: str) -> str:
        return "\n".join(l for l in s.splitlines() if not l.lstrip().startswith("#"))

    assert code(text).count("gh release edit") == 1
    assert "gh release edit" in code(blocks["flip"])
    assert "gh release edit" not in code(blocks["publish"])
    assert "--draft=false" in code(blocks["flip"])
    assert "--draft=false" not in code(blocks["publish"])
    assert "published=true" not in text


def test_workflow_flip_job_is_minimal_and_validates_its_inputs():
    flip = _job_blocks(_workflow_text())["flip"]
    assert "contents: write" in flip
    assert "actions:" not in flip
    assert "actions/checkout" not in flip
    assert "secrets." not in flip
    assert "TAG: ${{ needs.publish.outputs.tag }}" in flip
    assert "LATEST: ${{ needs.publish.outputs.latest }}" in flip
    # re-validated right before the irreversible step
    assert r"^v[0-9A-Za-z.+-]+$" in flip
    assert "true|false" in flip
    assert flip.index("true|false") < flip.index("gh release edit")
    assert re.search(r"^\s*timeout-minutes:\s*\d+\s*$", flip, re.M)


# --- round 4: uncertain-result window (Sol HIGH) + concurrency deadlock (Opus HIGH) -

def test_workflow_arm_step_is_the_last_step_of_the_gating_job():
    """#50: `attempted=true` is the output of a COMPLETED job. The arm step
    must therefore be the last step of `publish` (nothing after it can fail the
    job's output delivery before the flip job starts), on the non-dry-run-only
    `if:`, and `attempted=true` is written nowhere else."""
    publish = _job_blocks(_workflow_text())["publish"]
    steps = publish.split("      - name:")
    arm_step = steps[-1]
    assert arm_step.strip().startswith("Arm post-publish verification")
    assert "id: arm" in arm_step
    ifs = [ln.strip() for ln in arm_step.splitlines() if ln.strip().startswith("if:")]
    assert ifs == ["if: steps.input.outputs.dry_run != 'true'"]
    assert 'echo "attempted=true" >> "$GITHUB_OUTPUT"' in arm_step
    assert _workflow_text().count('echo "attempted=true"') == 1

def test_workflow_verify_condition_uses_attempted_not_published_or_result():
    """Sol HIGH: `verify` must run whenever publication was ATTEMPTED, not
    only once it is known to have succeeded -- `needs.publish.result` and
    `needs.publish.outputs.published` must not appear in the condition."""
    verify_if = next(l.strip() for l in _job_blocks(_workflow_text())["verify"].splitlines()
                     if l.strip().startswith("if:"))
    assert "needs.publish.outputs.attempted" in verify_if
    assert "needs.publish.result" not in verify_if
    assert "needs.publish.outputs.published" not in verify_if
    assert "!cancelled()" in verify_if
    assert "always()" not in verify_if


def test_workflow_no_job_defines_its_own_concurrency_block():
    """Opus HIGH: the round-3 job-level `concurrency:` on `verify` was an
    identical-group deadlock against the workflow-level block (GitHub
    cancels the run). Only the workflow-level `concurrency:` may exist now."""
    text = _workflow_text()
    top = text.split("\njobs:")[0]
    assert "\nconcurrency:" in top
    blocks = _job_blocks(text)
    for name, block in blocks.items():
        assert "\n    concurrency:" not in block, name


def test_workflow_publish_job_no_longer_runs_pv_py_verify():
    """Round 3: post-publish verification moved entirely into the `verify`
    job; the `publish` job must not call `pv.py verify` at all."""
    publish = _job_blocks(_workflow_text())["publish"]
    assert "pv.py verify" not in publish


def test_workflow_verify_job_runs_pv_py_verify_exactly_once():
    verify = _job_blocks(_workflow_text())["verify"]
    assert verify.count("pv.py verify") == 1


def _verify_job_step_chunks(text: str) -> list[str]:
    """Every individual step body in the `verify` job (split the same way
    the mkdir/refuse tests above already do)."""
    verify = _job_blocks(text)["verify"]
    header, *steps = verify.split("\n      - ")
    return steps


def test_workflow_every_verify_job_step_has_its_own_timeout_minutes():
    steps = _verify_job_step_chunks(_workflow_text())
    assert len(steps) >= 9
    for step in steps:
        assert re.search(r"^\s*timeout-minutes:\s*\d+\s*$", step, re.M), step[:80]


def test_workflow_verify_job_step_timeout_sum_fits_inside_the_job_timeout():
    """The structural fix itself: no earlier step in this job can eat into
    the last step's time, because every step's timeout is small, explicit,
    and their sum (plus the job's own margin) stays under the job-level
    timeout-minutes -- so the workflow's own kill can never fire before
    pv.py's combined report has had time to print."""
    text = _workflow_text()
    blocks = _job_blocks(text)
    verify = blocks["verify"]
    job_timeout = int(re.search(r"^\s*timeout-minutes:\s*(\d+)\s*$", verify.split("\n    permissions:")[0], re.M).group(1))
    steps = _verify_job_step_chunks(text)
    step_timeouts = [int(re.search(r"^\s*timeout-minutes:\s*(\d+)\s*$", s, re.M).group(1)) for s in steps]
    assert sum(step_timeouts) <= job_timeout
    # The last step (pv.py verify) must individually exceed the 480s (8 min)
    # end-to-end deadline pv.py enforces on itself, or the step could be
    # killed before the combined report finishes printing.
    assert step_timeouts[-1] > 8


def test_workflow_publish_job_tag_validation_precedes_its_first_tag_write():
    """Item 2: the tag must be validated before ANY $GITHUB_OUTPUT/
    $GITHUB_ENV write of it, in the publish job."""
    publish = _job_blocks(_workflow_text())["publish"]
    steps = publish.split("      - name:")
    resolve_step = next(s for s in steps if s.strip().startswith("Resolve the tag, target commit"))
    validate_idx = resolve_step.index('=~ ^v[0-9A-Za-z.+-]+$')
    first_output_write_idx = resolve_step.index('echo "tag=$tag" >> "$GITHUB_OUTPUT"')
    first_env_write_idx = resolve_step.index('echo "TAG=$tag"')
    assert validate_idx < first_output_write_idx
    assert validate_idx < first_env_write_idx


def test_workflow_verify_job_tag_validation_precedes_its_first_tag_write():
    verify = _job_blocks(_workflow_text())["verify"]
    steps = verify.split("      - name:")
    resolve_step = next(s for s in steps if s.strip().startswith("Resolve and validate the tag to verify"))
    validate_idx = resolve_step.index('=~ ^v[0-9A-Za-z.+-]+$')
    env_write_idx = resolve_step.index('echo "TAG=$tag" >> "$GITHUB_ENV"')
    assert validate_idx < env_write_idx


def test_workflow_tag_validation_rejects_crlf_and_enforces_the_format():
    text = _workflow_text()
    # Both jobs reject an embedded CR/LF before any write, and both require
    # the same ^v[0-9A-Za-z.+-]+$ shape.
    assert text.count("*$'\\n'*|*$'\\r'*)") == 2
    # the gating job, the verify job and (#50) the flip job's re-check of the tag it is handed\n    assert text.count('=~ ^v[0-9A-Za-z.+-]+$') == 3


def test_workflow_metadata_whole_blob_crlf_check_precedes_both_writes():
    """Round 4 item 3: the whole `out` blob is checked for an embedded
    carriage return BEFORE the FIRST write to either $GITHUB_OUTPUT or
    $GITHUB_ENV, in both jobs -- not just before the $GITHUB_ENV loop (round
    3's version left the $GITHUB_OUTPUT write unguarded)."""
    text = _workflow_text()
    assert text.count("Metadata output contains a carriage return") == 2
    for block_name in ("publish", "verify"):
        block = _job_blocks(text)[block_name]
        steps = block.split("      - name:")
        metadata_step = next(s for s in steps
                             if "metadata --path" in s and "id: metadata" in s)
        idx_out = metadata_step.index('out="$(python3 /tmp/pv.py metadata')
        idx_case = metadata_step.index('case "$out" in', idx_out)
        idx_cr = metadata_step.index("*$'\\r'*)", idx_case)
        idx_output_write = metadata_step.index('echo "$out" >> "$GITHUB_OUTPUT"')
        idx_env_write = metadata_step.index('echo "${upper}=${value}" >> "$GITHUB_ENV"')
        assert idx_out < idx_case < idx_cr < idx_output_write < idx_env_write


# --- round 5: docs/comments must not overclaim runner-death coverage (Sol HIGH) --

CHECKLIST_PATH = ROOT / "docs" / "RELEASE_CHECKLIST.md"


def _checklist_text() -> str:
    return CHECKLIST_PATH.read_text(encoding="utf-8")


def test_docs_do_not_claim_verify_survives_a_lost_runner():
    """Sol r4 HIGH: the arm step and the flip step run in the same job, so
    if the runner machine itself is lost after a server-side-successful
    flip but before the job finishes, its outputs are never delivered to
    GitHub and `verify` is skipped -- this is a real gap, not covered by
    `attempted`. Neither the workflow nor the checklist may claim
    otherwise."""
    workflow_text = _workflow_text()
    checklist_text = _checklist_text()
    assert "runner dies" not in workflow_text
    assert "runner dies" not in checklist_text


def test_checklist_documents_the_flip_job_and_verify_only_as_the_manual_recheck():
    """#50: the checklist describes the publish -> flip -> verify graph, says
    `attempted` is delivered before the flip starts (so a lost flip runner no
    longer skips `verify`), and keeps `verify_only` as the manual re-check."""
    checklist_text = _checklist_text()
    flat = " ".join(checklist_text.split())
    assert "`publish` (gates + the draft), `flip`" in flat
    assert "(`needs: [publish, flip]`)" in flat
    assert "that output is delivered **before** the `flip` job can start" in flat
    assert "its runner is lost after GitHub accepted the flip, `verify` still runs" in flat
    # the old single-job limitation is gone
    assert "GitHub never receives that job's outputs and `verify` is skipped" not in flat
    assert "`verify_only` dispatch" in flat
