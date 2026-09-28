"""Watch the Innovation Fund page for the project-voting system going live.

The fund's page said the community-vote system was still being built. Twenty
per cent of the Phase 1 score depends on it, and there is no announcement
channel that reliably reaches an entrant — so this checks the page itself.

It is deliberately minimal about what it does to the site: at most one GET per
run, a normal User-Agent, and nothing that resembles interacting with a vote.

This script's job was to notice voting go live. It did (recorded_at in the
committed snapshot). It is kept for manual checks — a maintainer can still run
it — but once the snapshot records ``voting_live: true`` it refuses to fetch
again and reports the terminal state instead, so a stale page fingerprint
cannot cause a repeated alert.

    python tools/watch/innovation_fund.py            # compare against the snapshot
    python tools/watch/innovation_fund.py --update   # accept the current page as the snapshot
    python tools/watch/innovation_fund.py --force    # compare even if terminal; never writes

Exit codes: 0 = no meaningful change (or terminal, or snapshot written), 2 =
signals changed (the workflow opens an issue), 1 = the page could not be
read, or the snapshot could not be read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://www.snapmaker.com/innovation-fund"
SNAPSHOT = Path(__file__).resolve().parents[2] / "docs" / "internal" / "innovation-fund-signals.json"

# Phrases that would mean the voting system has appeared, or that the rules moved.
SIGNALS = {
    "voting_promised": r"voting system[^.]{0,80}(next month|coming|being built|will be updated)",
    "voting_live": r"\b(upvote|vote now|cast your vote|voting is (now )?open)\b",
    "project_pages": r"/innovation-fund/(projects?|vote)",
    "phase1_deadline": r"Sep\s*7,?\s*2026|September\s*7,?\s*2026",
    "evaluation_close": r"Sep\s*22,?\s*2026|September\s*22,?\s*2026",
    "winners_date": r"Sep\s*30|September\s*30",
    "weighting": r"\b80\s*%|\b20\s*%",
}

# The explicit compare allowlist. `text_sha256` (the page's full text changes
# for trivial reasons) and `recorded_at` (metadata, not a signal) are never
# compared.
WATCHED = tuple(SIGNALS) + ("project_count_hint",)


def fetch(url: str = URL) -> str:
    request = urllib.request.Request(
        url, headers={"User-Agent": "snapmaker-studio-fund-watch (+https://github.com/DVOpenLabs/snapmaker-studio)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def signals(html: str) -> dict:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    found = {name: bool(re.search(pattern, text, re.I)) for name, pattern in SIGNALS.items()}
    # A count of listed projects is a cheap proxy for the wall changing.
    found["project_count_hint"] = len(re.findall(r"View on GitHub", text, re.I))
    found["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return found


def load() -> tuple[dict | None, str | None]:
    """Read the snapshot. Returns (snapshot, problem).

    Missing file -> (None, None): a first run, handled the same as before
    (fetch and write). Unreadable / invalid JSON / not a JSON object ->
    (None, "snapshot unreadable: ..."); the caller must not fetch in that case.
    """
    if not SNAPSHOT.exists():
        return None, None
    try:
        data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"snapshot unreadable: {type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return None, "snapshot unreadable: not a JSON object"
    return data, None


def is_terminal(snapshot: dict | None) -> bool:
    """True once the snapshot is a dict with every watched key and a live vote."""
    if not isinstance(snapshot, dict):
        return False
    if not all(key in snapshot for key in WATCHED):
        return False
    return snapshot.get("voting_live") is True


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def write_snapshot(data: dict) -> None:
    """Write the snapshot atomically: a temp file in the same directory, then replace."""
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    tmp = SNAPSHOT.with_name(SNAPSHOT.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, SNAPSHOT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true",
                        help="write the current page's signals as the new snapshot")
    parser.add_argument("--force", action="store_true",
                        help="compare against the page even if the snapshot is terminal; never writes")
    args = parser.parse_args(argv)

    previous, problem = load()
    if problem:
        print(problem)
        return 1

    if previous is not None and not args.update and not args.force and is_terminal(previous):
        recorded = previous.get("recorded_at") or "unknown date"
        print(f"terminal: voting_live recorded on {recorded} — the vote is open; "
              "nothing left to watch (--force compares anyway, --update refreshes)")
        return 0

    try:
        current = signals(fetch())
    except Exception as exc:  # noqa: BLE001 — the message is the whole point
        print(f"could not read {URL}: {type(exc).__name__}: {exc}")
        return 1

    if args.update or previous is None:
        to_write = dict(current)
        to_write["recorded_at"] = _utc_today_iso()
        write_snapshot(to_write)
        print(f"snapshot written to {SNAPSHOT.name}")
        return 0

    # previous is not None here, so watched keys are read with .get() for safety
    # against an older snapshot missing a newer signal.
    changes = [(key, previous.get(key), current.get(key))
               for key in WATCHED if previous.get(key) != current.get(key)]

    if not changes:
        print("no change in the watched signals")
        return 0

    print("CHANGED:")
    for name, was, now in changes:
        print(f"  {name}: {was!r} -> {now!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
