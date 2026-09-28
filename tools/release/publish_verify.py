"""release-publish.yml's release decisions and post-publish verification,
decided deterministically. Read-only, always.

Nothing here can publish, tag, edit or upload anything. The only subprocess
calls this module makes are `gh api --method GET ...` and
`gh release download ...` -- both reads. It only reads what GitHub already
reports and compares it with what the workflow gated.

Pieces:

  semver_key / should_be_latest
          SemVer 2.0 precedence, used to decide whether the tag being
          published should become /releases/latest -- a plain (non
          prerelease-identifier) tag is only "latest" if no other
          non-draft, non-prerelease release outranks it.

  release_present
          Whether ANY release (including a draft) already exists for a tag.
          See its docstring: this can only see drafts with a push-access
          token, i.e. only from the publish job, never the read-only verify
          job.

  verify_state / assess
          The release GitHub now reports is public (draft=false), not a
          prerelease, carries exactly the expected assets, and
          /releases/latest points at it (or, when this release is NOT
          expected to be latest, that something with higher SemVer
          precedence is). The latest pointer is read right after the draft
          is flipped public, and GitHub can take a moment to converge, so
          the reads are retried on a short bounded backoff: immediately,
          then after 2, 4, 8 and 12 seconds (26 s of waiting; each read also
          times out after GH_TIMEOUT seconds). A transient API error is
          retried the same way. On timeout the failure says which case it
          was:
            A. the release itself is missing or wrong;
            B. the release is public and correct, but /releases/latest
               has not moved as expected yet;
            C. GitHub's API could not be read at all.
          A release-read failure and a latest-read failure are tried in
          their own scopes so a transient latest-read error can never mask
          a genuine case A (see `_assess_release_only`).

  verify_hashes
          Every downloaded asset matches the SHA256SUMS the workflow gated
          before publishing. SHA256SUMS itself is compared byte for byte; a
          checksum file does not list itself, and the shell loop this
          replaced failed silently on exactly that (grep found no line, and
          set -e with pipefail ended the step with no message) on every
          real publish.

  metadata / expected_sums
          Re-derive the workflow's `GITHUB_OUTPUT` key=value lines and the
          expected SHA256SUMS bytes from docs/RELEASE_METADATA.md, so the
          publish job and the read-only verify job compute the identical
          values from the same source instead of duplicating shell/python.

  combine
          One pass/fail report covering the latest decision, release state,
          and hashes, for the `verify` subcommand used by both jobs.

Subcommands (see `main`): exists, metadata, expected-sums, should-be-latest,
verify, state, hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Delays before attempts 2..5. Attempt 1 is immediate.
DELAYS: tuple[float, ...] = (2, 4, 8, 12)
SUMS_NAME = "SHA256SUMS"
# Per read (upper bound; shrinks further under a Deadline -- see below).
GH_TIMEOUT = 20
# gh release download, per asset (upper bound; shrinks further under a Deadline).
DOWNLOAD_TIMEOUT = 120
# `verify`'s end-to-end wall-clock budget. Chosen well below the workflow's
# job/step timeout-minutes (see release-publish.yml) so the deadline always
# fires first and the combined report is always printed -- see `Deadline`.
DEFAULT_DEADLINE_SECONDS = 480.0


class NotFound(Exception):
    """GitHub answered 404 for the resource."""


class Deadline:
    """A wall-clock budget for the `verify` subcommand's whole run (listing
    releases, the state retry loop, and every asset download).

    `list_releases`/`_gh_get`/`_download_asset` each take `timeout=min(their
    own per-call cap, deadline.remaining())`, so a single hung `gh` call can
    never eat the whole budget, and the budget itself can never be exceeded
    by more than one in-flight call's cap. Once `expired`, callers stop
    attempting further network calls and let `combine()` still produce one
    report, with the skipped/incomplete pieces recorded as failures --
    never silence, never a hang past the job's own timeout-minutes.
    """

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._end = clock() + seconds

    def remaining(self) -> float:
        return max(0.0, self._end - self._clock())

    @property
    def expired(self) -> bool:
        return self.remaining() <= 0

    def cap(self, per_call: float) -> float:
        """`min(per_call, remaining())`, never negative."""
        return max(0.0, min(per_call, self.remaining()))


@dataclass(frozen=True)
class Outcome:
    ok: bool
    kind: str  # "ok" | "release" | "latest" | "api" | "deadline"
    attempts: int
    message: str


# --- SemVer 2.0 precedence --------------------------------------------------

# https://semver.org/#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
_SEMVER_RE = re.compile(
    r"^v?"
    r"(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?$"
)


def semver_key(tag: str) -> tuple | None:
    """SemVer 2.0 precedence key for `tag`, or None if it is not valid
    SemVer: one optional leading 'v', no leading zeros in any numeric
    identifier (major/minor/patch or a purely-numeric prerelease
    identifier), build metadata ignored for precedence.

    The key sorts correctly with plain tuple comparison: a release with no
    prerelease always outranks one with the same major.minor.patch that has
    one; numeric prerelease identifiers compare numerically and always rank
    below alphanumeric ones; equal-prefix prerelease identifier lists rank
    the shorter one lower -- exactly SemVer's precedence rules.
    """
    m = _SEMVER_RE.match(tag)
    if not m:
        return None
    major, minor, patch = int(m["major"]), int(m["minor"]), int(m["patch"])
    prerelease = m["prerelease"]
    if prerelease is None:
        return (major, minor, patch, 1, ())
    parts: list[tuple[int, int | str]] = []
    for ident in prerelease.split("."):
        if ident.isdigit():
            parts.append((0, int(ident)))
        else:
            parts.append((1, ident))
    return (major, minor, patch, 0, tuple(parts))


def list_releases(repo: str, deadline: "Deadline | None" = None) -> list[dict]:
    """All releases (published AND draft, if the token has push access),
    newest first as GitHub returns them. Shared by `should_be_latest`
    (which filters drafts/prereleases out) and `release_present` (which does
    not). Paginated at 100 per page, up to 10 pages; a full 10th page means
    the listing cannot be confirmed complete, so that raises rather than
    silently under-counting.

    `deadline`, if given, caps every page's `gh api` call at
    `deadline.remaining()` and refuses to start a further page once the
    budget is gone (raising, rather than a near-zero-timeout call that
    would almost certainly time out anyway).
    """
    releases: list[dict] = []
    for page in range(1, 11):
        if deadline is not None:
            if deadline.expired:
                raise RuntimeError(
                    f"releases listing for {repo}: verification deadline exceeded after {page - 1} page(s)"
                )
            timeout = deadline.cap(GH_TIMEOUT)
        else:
            timeout = GH_TIMEOUT
        batch = _gh_get(f"repos/{repo}/releases?per_page=100&page={page}", timeout=timeout)
        if not isinstance(batch, list):
            raise RuntimeError(f"releases listing for {repo} page {page}: expected a list, got {type(batch)!r}")
        releases.extend(batch)
        if len(batch) < 100:
            return releases
    raise RuntimeError(
        f"releases listing for {repo}: page 10 was completely full (100 entries); "
        "cannot confirm the listing is complete, refusing to guess"
    )


def should_be_latest(candidate: str, releases: list[dict]) -> bool:
    """True iff `candidate` is the highest-SemVer-precedence release among
    the non-draft, non-prerelease-flagged, parseable entries in `releases`
    (candidate's own entry, if present, is excluded from the comparison).

    Entries that are drafts, prerelease-flagged, or not parseable as SemVer
    are logged and ignored rather than failing the whole check -- an
    unrelated stray tag must not block every future publish.

    `candidate` itself must be a plain (non prerelease-identifier),
    parseable SemVer tag, or this raises ValueError: a tag with a
    prerelease identifier can never be /releases/latest, so asking is a
    caller bug and must fail closed. Two entries (candidate vs. another)
    tying at equal SemVer precedence (e.g. `v1.2.0` vs `1.2.0+build`, which
    differ only in the ignored build-metadata) also raises ValueError --
    there is no correct answer to "which is latest" between them.
    """
    cand_key = semver_key(candidate)
    if cand_key is None or cand_key[3] != 1:
        raise ValueError(
            f"{candidate!r} is not a plain (non-prerelease) SemVer tag; it can never be /releases/latest"
        )
    others: list[tuple[tuple, str]] = []
    for r in releases:
        tag = r.get("tag_name")
        if tag == candidate or r.get("draft") or r.get("prerelease"):
            continue
        key = semver_key(tag)
        if key is None:
            print(f"should_be_latest: ignoring unparseable release tag {tag!r}", file=sys.stderr)
            continue
        others.append((key, tag))
    for key, tag in others:
        if key == cand_key:
            raise ValueError(
                f"{candidate!r} and {tag!r} have equal SemVer precedence; cannot decide which should be latest"
            )
    return all(cand_key > key for key, _ in others)


def release_present(tag: str, releases: list[dict]) -> bool:
    """True iff any entry in `releases` (the full listing from
    `list_releases`, published AND draft) has `tag_name == tag`.

    GitHub's "List releases" REST endpoint
    (`GET /repos/{owner}/{repo}/releases`) documents: "Draft releases are
    only returned to users who have push access to the repository." So
    `release_present` only sees a draft when called with a token that has
    push access -- exactly the `contents: write` token the publish job's
    refuse-if-exists step uses, which is the only place this runs. The
    read-only verify job (`contents: read`) never calls this; a draft is
    invisible to it by design, per the same GitHub documentation sentence.
    """
    return any(r.get("tag_name") == tag for r in releases)


# --- release state --------------------------------------------------------------

def _assess_release_only(release: dict | None, tag: str, expected_assets: list[str]) -> tuple[str, str] | None:
    """The parts of `assess` that need only `release`, not the latest
    pointer. None means the release itself checks out; a ("release", ...)
    tuple means case A. Kept separate so a transient failure reading
    /releases/latest can never mask a genuine case A (see `verify_state`).
    """
    if release is None:
        return "release", f"no release exists for tag {tag}"
    if release.get("tag_name") != tag:
        return "release", f"the release found is for tag {release.get('tag_name')!r}, not {tag!r}"
    if release.get("draft") is not False:
        return "release", f"release {tag} is still a draft"
    if release.get("prerelease") is not False:
        return "release", f"release {tag} is marked as a prerelease"
    names = sorted(a.get("name", "") for a in release.get("assets", []))
    if names != sorted(expected_assets):
        return "release", f"release {tag} has assets {names}, expected {sorted(expected_assets)}"
    return None


def assess(release: dict | None, latest_tag: str | None, tag: str,
           expected_assets: list[str], expect_latest: bool | None = True) -> tuple[str, str]:
    """One observation -> ("ok" | "release" | "latest", detail).

    `expect_latest`:
      True  (default) -- `latest_tag` must equal `tag`. Unchanged behaviour.
      False -- `latest_tag` must NOT equal `tag`, and must have strictly
               higher SemVer precedence than `tag` (this release is
               correctly not latest because something newer exists).
               An equal, lower, unparseable, or missing `latest_tag` is a
               "latest" problem.
      None  -- the latest pointer is not checked at all (used when whether
               this release *should* be latest could not itself be
               determined, e.g. the releases listing could not be read).
    """
    problem = _assess_release_only(release, tag, expected_assets)
    if problem is not None:
        return problem
    if expect_latest is None:
        return "ok", f"release {tag} is public with the expected assets (latest status not checked)"
    if expect_latest:
        if latest_tag != tag:
            return "latest", f"/releases/latest is {latest_tag!r}, expected {tag!r}"
        return "ok", f"release {tag} is public with the expected assets and is /releases/latest"
    latest_key = semver_key(latest_tag) if latest_tag else None
    tag_key = semver_key(tag)
    if latest_tag == tag or latest_key is None or tag_key is None or not (latest_key > tag_key):
        return ("latest",
                f"/releases/latest is {latest_tag!r}; expected a release with higher SemVer "
                f"precedence than {tag!r} (this release is not meant to be latest)")
    return "ok", f"release {tag} is public with the expected assets and /releases/latest ({latest_tag}) outranks it, as expected"


def verify_state(read_release: Callable[[], dict | None],
                 read_latest: Callable[[], str | None],
                 tag: str,
                 expected_assets: list[str],
                 expect_latest: bool | None = True,
                 delays: tuple[float, ...] = DELAYS,
                 sleep: Callable[[float], None] = time.sleep,
                 log: Callable[[str], None] = print,
                 deadline: "Deadline | None" = None) -> Outcome:
    """`deadline`, if given, is checked before every attempt (including
    the first) and again after each inter-attempt sleep; once expired the
    retry loop stops -- read_release/read_latest are expected to already
    honour the SAME deadline for their own per-call timeouts (the CLI wires
    this up; see `main`'s `verify` branch), so a stop here never leaves a
    call running past the budget. A deadline that cuts the loop short is
    reported as kind "deadline", distinct from "api", so the combined
    report can say plainly that not every planned check ran.
    """
    kind, detail = "api", "not attempted"
    schedule = (0.0, *delays)
    ran_attempts = 0
    for attempt, delay in enumerate(schedule, start=1):
        if deadline is not None and deadline.expired:
            detail = f"stopped before attempt {attempt}/{len(schedule)}: verification deadline exceeded"
            break
        if delay:
            wait = delay if deadline is None else min(delay, deadline.remaining())
            if wait > 0:
                sleep(wait)
            if deadline is not None and deadline.expired:
                detail = f"stopped before attempt {attempt}/{len(schedule)}: verification deadline exceeded while waiting"
                break
        ran_attempts = attempt
        try:
            release = read_release()
        except Exception as exc:  # noqa: BLE001 - any read failure is retried
            kind, detail = "api", f"GitHub API read failed: {exc}"
        else:
            release_problem = _assess_release_only(release, tag, expected_assets)
            try:
                latest = read_latest()
            except Exception as exc:  # noqa: BLE001
                if release_problem is not None:
                    # A latest-read failure must never mask a genuine case A.
                    kind, detail = release_problem
                else:
                    kind, detail = "api", f"GitHub API read failed: {exc}"
            else:
                kind, detail = assess(release, latest, tag, expected_assets, expect_latest)
                if kind == "ok":
                    return Outcome(True, "ok", attempt, f"Post-publish state OK after {attempt} attempt(s): {detail}.")
        log(f"attempt {attempt}/{len(schedule)}: {detail}")

    if ran_attempts < len(schedule):
        return Outcome(False, "deadline", ran_attempts,
                       f"D. VERIFICATION DEADLINE EXCEEDED after {ran_attempts}/{len(schedule)} planned attempt(s): "
                       f"{detail}. Not every planned check ran within the time budget; treat this as inconclusive "
                       "and check the release by hand -- do not republish.")

    waited = sum(delays)
    prefix = {
        "release": "A. RELEASE MISSING OR WRONG",
        "latest": "B. RELEASE IS PUBLIC, LATEST POINTER NOT PROPAGATED",
        "api": "C. GITHUB API UNREADABLE",
    }[kind]
    advice = {
        "release": "The release itself does not match what was gated. Inspect it before doing anything else.",
        "latest": "The release exists, is public and has the right assets; only /releases/latest did not "
                  "match what was expected. Either GitHub had not caught up yet, or another release became "
                  "latest in the meantime. Re-check by hand; do not republish.",
        "api": "The release state could not be read. Check it by hand; do not republish.",
    }[kind]
    return Outcome(False, kind, len(schedule),
                   f"{prefix} after {len(schedule)} attempts over {waited:g}s: {detail}. {advice}")


def parse_sums(text: str) -> dict[str, str]:
    sums: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, name = line.partition(" ")
        sums[name.strip().lstrip("*")] = digest.lower()
    return sums


def verify_hashes(sums_path: Path, asset_dir: Path, asset_names: list[str]) -> list[str]:
    """Problems found; an empty list means every asset matches."""
    expected = parse_sums(sums_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    for name in asset_names:
        path = asset_dir / name
        if not path.is_file():
            problems.append(f"{name}: not downloaded")
            continue
        if name == SUMS_NAME:
            if path.read_bytes() != sums_path.read_bytes():
                problems.append(f"{name}: the live file differs from the gated {sums_path}")
            continue
        if name not in expected:
            problems.append(f"{name}: no expected hash in {sums_path}")
            continue
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != expected[name]:
            problems.append(f"{name}: re-hashed to {got}, expected {expected[name]}")
    return problems


# --- docs/RELEASE_METADATA.md ------------------------------------------------

REQUIRED_METADATA_FIELDS = ["version", "installer", "size (bytes)", "sha256",
                            "linux installer", "linux size (bytes)", "linux sha256",
                            "build run"]


def parse_metadata(text: str) -> dict[str, str]:
    """The "## Current release" table's fields, lower-cased keys."""
    start = text.index("## Current release")
    end = text.find("## Previous release", start)
    block = text[start:end if end != -1 else len(text)]
    fields: dict[str, str] = {}
    for m in re.finditer(r"^\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*$", block, re.M):
        key, value = m.group(1).strip(), m.group(2).strip()
        if key.lower() in ("field", "---"):
            continue
        fields[key.lower()] = value.strip("`")
    missing = [k for k in REQUIRED_METADATA_FIELDS if k not in fields]
    if missing:
        raise ValueError(f"RELEASE_METADATA.md's Current release table is missing: {missing}")
    return fields


def metadata_lines(fields: dict[str, str]) -> list[str]:
    """The 8 key=value lines the workflow writes to GITHUB_OUTPUT."""
    return [
        f"version={fields['version']}",
        f"win_name={fields['installer']}",
        f"win_size={fields['size (bytes)'].replace(',', '')}",
        f"win_sha256={fields['sha256']}",
        f"linux_name={fields['linux installer']}",
        f"linux_size={fields['linux size (bytes)'].replace(',', '')}",
        f"linux_sha256={fields['linux sha256']}",
        f"build_run={fields['build run']}",
    ]


_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def expected_sums(win_name: str, win_sha256: str, linux_name: str, linux_sha256: str) -> bytes:
    """The SHA256SUMS bytes Gate 3 produces, from already-verified values."""
    for name in (win_name, linux_name):
        if not _NAME_RE.match(name):
            raise ValueError(f"asset name {name!r} contains characters outside [A-Za-z0-9._-]")
    for sha in (win_sha256, linux_sha256):
        if not _HASH_RE.match(sha):
            raise ValueError(f"hash {sha!r} is not 64 lowercase hex characters")
    return f"{win_sha256}  {win_name}\n{linux_sha256}  {linux_name}\n".encode("ascii")


# --- combined report -------------------------------------------------------------

def combine(expect_latest_problem: str | None, state: Outcome, hash_problems: list[str]) -> tuple[bool, str]:
    """Pure. One pass/fail report covering the latest decision, the release
    state, and the hashes. `ok` is True only if all three passed.
    """
    lines: list[str] = []
    ok = True
    if expect_latest_problem is not None:
        ok = False
        lines.append(f"LATEST DECISION: FAIL - {expect_latest_problem}")
    else:
        lines.append("LATEST DECISION: PASS")
    if not state.ok:
        ok = False
    lines.append(f"STATE: {'PASS' if state.ok else 'FAIL'} - {state.message}")
    if hash_problems:
        ok = False
        lines.append("HASHES: FAIL")
        for p in hash_problems:
            lines.append(f"  {p}")
    else:
        lines.append("HASHES: PASS")
    return ok, "\n".join(lines)


# --- GitHub reads (gh CLI, GET only) -------------------------------------------

def _gh_get(endpoint: str, timeout: float = GH_TIMEOUT):
    # encoding="utf-8" explicitly: `text=True` alone decodes with the
    # platform's default locale encoding, which on Windows runners is not
    # always UTF-8 and can raise UnicodeDecodeError on `gh`'s own UTF-8
    # output. No errors="replace" here -- the output is parsed as JSON, so a
    # genuine encoding problem should raise loudly rather than silently
    # corrupt the bytes json.loads then tries to parse.
    try:
        proc = subprocess.run(["gh", "api", "--method", "GET", endpoint],
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"gh api {endpoint}: no answer within {timeout:g}s") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip()
        if "HTTP 404" in err or "Not Found" in err:
            raise NotFound(endpoint)
        raise RuntimeError(f"gh api {endpoint}: {err[:300]}")
    return json.loads(proc.stdout)


def _read_release(repo: str, tag: str, timeout: float = GH_TIMEOUT) -> dict | None:
    """`releases/tags/{tag}` never returns a draft (it only matches
    published releases) -- a leftover draft for `tag` therefore reads as
    "no release", which is exactly the case A this feeds into `assess`.
    """
    try:
        return _gh_get(f"repos/{repo}/releases/tags/{tag}", timeout=timeout)
    except NotFound:
        return None


def _read_latest(repo: str, timeout: float = GH_TIMEOUT) -> str | None:
    try:
        return _gh_get(f"repos/{repo}/releases/latest", timeout=timeout).get("tag_name")
    except NotFound:
        return None


def _download_asset(repo: str, tag: str, name: str, dest_dir: Path,
                    timeout: float = DOWNLOAD_TIMEOUT) -> str | None:
    """Attempt `gh release download` for one asset. Returns an error string
    on failure, None on success -- callers continue regardless so a single
    missing asset does not abort the rest of the report; `verify_hashes`
    already reports a not-downloaded asset by name.

    encoding="utf-8", errors="replace": the captured output here is only
    ever used to build an error message for display, never parsed, so a
    decoding hiccup should degrade to replacement characters rather than
    raise and hide the real (gh command) failure.
    """
    try:
        proc = subprocess.run(
            ["gh", "release", "download", tag, "--repo", repo, "--pattern", name,
             "--dir", str(dest_dir), "--clobber"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"{name}: gh release download did not finish within {timeout:g}s"
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip()
        return f"{name}: gh release download failed: {err[:300]}"
    return None


# --- CLI -----------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    st = sub.add_parser("state")
    st.add_argument("--repo", required=True)
    st.add_argument("--tag", required=True)
    st.add_argument("--asset", action="append", required=True)

    hs = sub.add_parser("hashes")
    hs.add_argument("--sums", required=True, type=Path)
    hs.add_argument("--dir", required=True, type=Path)
    hs.add_argument("--asset", action="append", required=True)

    ex = sub.add_parser("exists")
    ex.add_argument("--repo", required=True)
    ex.add_argument("--tag", required=True)

    sbl = sub.add_parser("should-be-latest")
    sbl.add_argument("--repo", required=True)
    sbl.add_argument("--tag", required=True)

    md = sub.add_parser("metadata")
    md.add_argument("--path", required=True, type=Path)

    es = sub.add_parser("expected-sums")
    es.add_argument("--win-name", required=True)
    es.add_argument("--win-sha256", required=True)
    es.add_argument("--linux-name", required=True)
    es.add_argument("--linux-sha256", required=True)
    es.add_argument("--out", required=True, type=Path)

    vf = sub.add_parser("verify")
    vf.add_argument("--repo", required=True)
    vf.add_argument("--tag", required=True)
    vf.add_argument("--asset", action="append", required=True)
    vf.add_argument("--sums", required=True, type=Path)
    vf.add_argument("--dir", required=True, type=Path)
    vf.add_argument("--deadline-seconds", type=float, default=DEFAULT_DEADLINE_SECONDS,
                    help="End-to-end wall-clock budget for this whole subcommand "
                         "(listing releases, state retries, downloads). Must stay "
                         "well under the workflow step/job timeout-minutes.")

    args = parser.parse_args(argv)

    if args.cmd == "state":
        outcome = verify_state(lambda: _read_release(args.repo, args.tag),
                               lambda: _read_latest(args.repo),
                               args.tag, args.asset)
        print(outcome.message, file=sys.stdout if outcome.ok else sys.stderr)
        return 0 if outcome.ok else 1

    if args.cmd == "hashes":
        problems = verify_hashes(args.sums, args.dir, args.asset)
        if problems:
            print("Live assets do not match what was gated. The release IS public; this needs operator "
                  "attention, not a republish:", file=sys.stderr)
            for p in problems:
                print(f"  {p}", file=sys.stderr)
            return 1
        print(f"Post-publish hashes OK: all {len(args.asset)} live assets match {args.sums}.")
        return 0

    if args.cmd == "exists":
        try:
            releases = list_releases(args.repo)
        except Exception as exc:  # noqa: BLE001
            print(f"could not enumerate releases for {args.repo}: {exc}", file=sys.stderr)
            return 1
        if release_present(args.tag, releases):
            print(f"a release or draft already exists for {args.tag}")
            return 3
        print(f"no release or draft exists for {args.tag}")
        return 0

    if args.cmd == "should-be-latest":
        try:
            releases = list_releases(args.repo)
            result = should_be_latest(args.tag, releases)
        except Exception as exc:  # noqa: BLE001
            print(f"could not decide whether {args.tag} should be latest: {exc}", file=sys.stderr)
            return 1
        print("true" if result else "false")
        return 0

    if args.cmd == "metadata":
        try:
            fields = parse_metadata(args.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(str(exc), file=sys.stderr)
            return 1
        for line in metadata_lines(fields):
            print(line)
        return 0

    if args.cmd == "expected-sums":
        try:
            data = expected_sums(args.win_name, args.win_sha256, args.linux_name, args.linux_sha256)
        except Exception as exc:  # noqa: BLE001
            print(str(exc), file=sys.stderr)
            return 1
        args.out.write_bytes(data)
        return 0

    # verify -- everything below shares one Deadline so the combined report
    # (requirement: it must ALWAYS print) can never be starved by the
    # workflow's own job/step timeout-minutes killing the process first.
    args.dir.mkdir(parents=True, exist_ok=True)
    deadline = Deadline(args.deadline_seconds)
    expect_latest_problem: str | None = None
    expect_latest: bool | None = True
    try:
        if deadline.expired:
            raise RuntimeError("verification deadline exceeded before the releases listing could be read")
        releases = list_releases(args.repo, deadline=deadline)
        expect_latest = should_be_latest(args.tag, releases)
    except Exception as exc:  # noqa: BLE001
        expect_latest_problem = str(exc)
        expect_latest = None

    state = verify_state(
        lambda: _read_release(args.repo, args.tag, timeout=deadline.cap(GH_TIMEOUT)),
        lambda: _read_latest(args.repo, timeout=deadline.cap(GH_TIMEOUT)),
        args.tag, args.asset, expect_latest=expect_latest, deadline=deadline)

    for name in args.asset:
        if deadline.expired:
            print(f"{name}: not attempted -- verification deadline exceeded", file=sys.stderr)
            continue
        err = _download_asset(args.repo, args.tag, name, args.dir, timeout=deadline.cap(DOWNLOAD_TIMEOUT))
        if err:
            print(err, file=sys.stderr)

    # A skipped/timed-out download simply leaves the file missing;
    # verify_hashes already reports that by name -- no separate bookkeeping
    # needed, and this call is local file I/O only, never blocked by the
    # deadline.
    hash_problems = verify_hashes(args.sums, args.dir, args.asset)

    ok, report = combine(expect_latest_problem, state, hash_problems)
    print(report)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
