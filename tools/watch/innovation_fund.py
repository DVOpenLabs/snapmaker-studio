"""Watch the Innovation Fund page for the project-voting system going live.

The fund's page says the community-vote system is still being built. Twenty per
cent of the Phase 1 score depends on it, and there is no announcement channel that
reliably reaches an entrant — so this checks the page itself, once a day.

It is deliberately minimal about what it does to the site: one GET per run, a
normal User-Agent, and nothing that resembles interacting with a vote.

    python tools/watch/innovation_fund.py            # compare against the snapshot
    python tools/watch/innovation_fund.py --update   # accept the current page as the snapshot

Exit codes: 0 = no meaningful change, 2 = signals changed (the workflow opens an
issue), 1 = the page could not be read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
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


def load() -> dict:
    if not SNAPSHOT.exists():
        return {}
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true",
                        help="write the current page's signals as the new snapshot")
    args = parser.parse_args()

    try:
        current = signals(fetch())
    except Exception as exc:  # noqa: BLE001 — the message is the whole point
        print(f"could not read {URL}: {type(exc).__name__}: {exc}")
        return 1

    previous = load()

    if args.update or not previous:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"snapshot written to {SNAPSHOT.name}")
        return 0

    # The page's full text changes for trivial reasons; only the named signals
    # and the project count are treated as meaningful.
    watched = [k for k in current if k != "text_sha256"]
    changes = [(k, previous.get(k), current[k]) for k in watched if previous.get(k) != current[k]]

    if not changes:
        print("no change in the watched signals")
        return 0

    print("CHANGED:")
    for name, was, now in changes:
        print(f"  {name}: {was!r} -> {now!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
