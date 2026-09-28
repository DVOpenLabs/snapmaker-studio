"""Post-publish verification for release-publish.yml. Read-only, always.

Nothing here can publish, tag, edit or upload anything. It only reads the
release GitHub now reports and compares it with what the workflow gated.

Two checks:

  state   The release exists, is public (draft=false), is not a prerelease,
          carries exactly the expected assets, and /releases/latest points at
          it. The latest pointer is read right after the draft is flipped
          public, and GitHub can take a moment to converge, so the reads are
          retried on a short bounded backoff: immediately, then after 2, 4, 8
          and 12 seconds (26 s of waiting; each read also times out after
          GH_TIMEOUT seconds). A transient API error is retried the same way.
          On timeout the failure says which case it was:
            A. the release itself is missing or wrong;
            B. the release is public and correct, but /releases/latest has
               not moved to it yet;
            C. GitHub's API could not be read at all.

  hashes  Every downloaded asset matches the SHA256SUMS the workflow gated
          before publishing. SHA256SUMS itself is compared byte for byte; a
          checksum file does not list itself, and the shell loop this replaces
          failed silently on exactly that (grep found no line, and set -e with
          pipefail ended the step with no message) on every real publish.

Usage (in the workflow):
  python3 publish_verify.py state  --repo OWNER/NAME --tag vX.Y.Z --asset A --asset B --asset SHA256SUMS
  python3 publish_verify.py hashes --sums dist/SHA256SUMS --dir DIR --asset A --asset B --asset SHA256SUMS
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Delays before attempts 2..5. Attempt 1 is immediate.
DELAYS: tuple[float, ...] = (2, 4, 8, 12)
SUMS_NAME = "SHA256SUMS"
# Per read. With five attempts the whole check stays bounded even if gh hangs.
GH_TIMEOUT = 20


class NotFound(Exception):
    """GitHub answered 404 for the resource."""


@dataclass(frozen=True)
class Outcome:
    ok: bool
    kind: str  # "ok" | "release" | "latest" | "api"
    attempts: int
    message: str


def assess(release: dict | None, latest_tag: str | None, tag: str,
           expected_assets: list[str]) -> tuple[str, str]:
    """One observation -> ("ok" | "release" | "latest", detail)."""
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
    if latest_tag != tag:
        return "latest", f"/releases/latest is {latest_tag!r}, expected {tag!r}"
    return "ok", f"release {tag} is public with the expected assets and is /releases/latest"


def verify_state(read_release: Callable[[], dict | None],
                 read_latest: Callable[[], str | None],
                 tag: str,
                 expected_assets: list[str],
                 delays: tuple[float, ...] = DELAYS,
                 sleep: Callable[[float], None] = time.sleep,
                 log: Callable[[str], None] = print) -> Outcome:
    kind, detail = "api", "not attempted"
    schedule = (0.0, *delays)
    for attempt, delay in enumerate(schedule, start=1):
        if delay:
            sleep(delay)
        try:
            release = read_release()
            latest = read_latest()
        except Exception as exc:  # noqa: BLE001 - any read failure is retried
            kind, detail = "api", f"GitHub API read failed: {exc}"
        else:
            kind, detail = assess(release, latest, tag, expected_assets)
            if kind == "ok":
                return Outcome(True, "ok", attempt, f"Post-publish state OK after {attempt} attempt(s): {detail}.")
        log(f"attempt {attempt}/{len(schedule)}: {detail}")

    waited = sum(delays)
    prefix = {
        "release": "A. RELEASE MISSING OR WRONG",
        "latest": "B. RELEASE IS PUBLIC, LATEST POINTER NOT PROPAGATED",
        "api": "C. GITHUB API UNREADABLE",
    }[kind]
    advice = {
        "release": "The release itself does not match what was gated. Inspect it before doing anything else.",
        "latest": "The release exists, is public and has the right assets; only /releases/latest had not moved "
                  "to it. Either GitHub had not caught up yet, or another release became latest in the "
                  "meantime. Re-check by hand; do not republish.",
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


# --- GitHub reads (gh CLI, GET only) -------------------------------------------

def _gh_get(endpoint: str) -> dict:
    try:
        proc = subprocess.run(["gh", "api", "--method", "GET", endpoint],
                              capture_output=True, text=True, timeout=GH_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"gh api {endpoint}: no answer within {GH_TIMEOUT}s") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip()
        if "HTTP 404" in err or "Not Found" in err:
            raise NotFound(endpoint)
        raise RuntimeError(f"gh api {endpoint}: {err[:300]}")
    return json.loads(proc.stdout)


def _read_release(repo: str, tag: str) -> dict | None:
    try:
        return _gh_get(f"repos/{repo}/releases/tags/{tag}")
    except NotFound:
        return None


def _read_latest(repo: str) -> str | None:
    try:
        return _gh_get(f"repos/{repo}/releases/latest").get("tag_name")
    except NotFound:
        return None


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
    args = parser.parse_args(argv)

    if args.cmd == "state":
        outcome = verify_state(lambda: _read_release(args.repo, args.tag),
                               lambda: _read_latest(args.repo),
                               args.tag, args.asset)
        print(outcome.message, file=sys.stdout if outcome.ok else sys.stderr)
        return 0 if outcome.ok else 1

    problems = verify_hashes(args.sums, args.dir, args.asset)
    if problems:
        print("Live assets do not match what was gated. The release IS public; this needs operator "
              "attention, not a republish:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(f"Post-publish hashes OK: all {len(args.asset)} live assets match {args.sums}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
