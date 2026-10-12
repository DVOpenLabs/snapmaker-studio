#!/usr/bin/env python3
"""Keep external conversion references out of Studio's tracked product files.

All tracked filenames are checked, including binary asset filenames. Contents
of every tracked text file are checked; source and tests have no directory-level
exceptions. Only the exact research and attribution paths below are exempt.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


# These definitions alone may contain the references they prohibit.
PATTERN_TEXT = (
    r"bambu[\s-]*2[\s-]*orca",
    r"(?:b2o|bambu2orca)\.kuzuriao\.com",
    r"@kuzuri\.ao\s*/\s*b2o",
    r"kuzuriao\s*/\s*b2o",
)
RULES = tuple(re.compile(pattern, re.IGNORECASE) for pattern in PATTERN_TEXT)
RULE_LINES = frozenset(f'    r"{pattern}",' for pattern in PATTERN_TEXT)
SELF = "tools/check-source-independence.py"
CONTENT_EXCEPTIONS = {
    "docs/innovation-fund/COMPETITOR_MATRIX.md": "Historical competitor research; preserve its evidence.",
    "THIRD_PARTY_NOTICES.md": "Required third-party attribution; do not remove or disguise credits.",
}
# Only known binary formats can skip content because of NUL bytes. A NUL in
# source, tests, configuration or an unfamiliar format must not hide references.
BINARY_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp",
                             ".pdf", ".3mf", ".zip", ".woff", ".woff2", ".ttf",
                             ".exe", ".dll", ".out", ".mp4", ".gz"})


def scan(root: Path) -> tuple[list[str], dict]:
    """Scan the checkout using Git's tracked-file inventory, with no size cap."""
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True)
    paths = sorted(set(result.stdout.decode("utf-8").rstrip("\0").split("\0")) - {""})
    problems: list[str] = []
    text_files: list[str] = []
    binary_files: list[str] = []
    exempt_files: dict[str, str] = {}
    for name in paths:
        if any(rule.search(name) for rule in RULES):
            problems.append(f"{name}: prohibited filename")
        if name in CONTENT_EXCEPTIONS:
            exempt_files[name] = CONTENT_EXCEPTIONS[name]
            continue
        raw = (root / name).read_bytes()
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            content = raw.decode("utf-16")
        elif b"\0" in raw and Path(name).suffix.lower() in BINARY_SUFFIXES:
            binary_files.append(name)
            continue
        else:
            # Replacement characters do not hide ASCII references in legacy text.
            content = raw.decode("utf-8-sig", errors="replace")
        text_files.append(name)
        # Match the whole text so a name split over lines cannot bypass the guard.
        checked = "\n".join("" if name == SELF and line in RULE_LINES else line
                            for line in content.splitlines())
        for rule in RULES:
            for match in rule.finditer(checked):
                line = checked.count("\n", 0, match.start()) + 1
                problems.append(f"{name}:{line}: prohibited reference")
    return problems, {"filenames": paths, "text_files": text_files,
                      "binary_content_skipped": binary_files, "content_exceptions": exempt_files}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="Write the exact coverage inventory as JSON.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    try:
        problems, manifest = scan(root)
        if args.manifest:
            args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except (OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        print(f"Source independence check could not complete: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"Source independence: {len(manifest['filenames'])} filenames, "
          f"{len(manifest['text_files'])} text files; {len(problems)} violations.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
