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
                             ".exe", ".dll", ".mp4", ".gz"})
# Tool output must never be tracked (a profiler dump once carried absolute local paths).
ARTIFACT_SUFFIXES = frozenset({".out", ".prof", ".pstats", ".dmp", ".tee"})
# Local absolute paths and user names, built from pieces so this file does not match itself.
# Matching is case-insensitive, accepts either separator and repeated separators, and the
# whole path is captured so a baseline entry covers one known path, not a whole file.
_DRIVE = r"[A-Za-z]:[\\/]+"
_TAIL = r"[^\s\"'`<>|*?,;)\]}]*"
LEAK_RULES = (
    re.compile(_DRIVE + r"(?:Users|STL Files)[\\/]+(?!Public\b)" + _TAIL, re.IGNORECASE),
    re.compile("/ho" + r"me/+(?!runner\b)[A-Za-z0-9_.-]+/" + _TAIL, re.IGNORECASE),
)
# Known synthetic test paths and historical handoff notes, as (file, normalized path).
# The set is closed: any other local path in ANY tracked file, including a different path
# in a file listed here, fails. Nothing is exempt by file name alone.
LEAK_BASELINE: frozenset[tuple[str, str]] = frozenset({
    ('backend/tests/fixtures/providers/spoolman_0_26_1.json', '/home/app/.local/share/spoolman'),
    ('backend/tests/fixtures/providers/spoolman_0_26_1.json', '/home/app/.local/share/spoolman/backups'),
    ('backend/tests/fixtures/providers/spoolman_0_26_1.json', '/home/app/spoolman/c:/program'),
    ('backend/tests/test_diagnostics.py', '/home/alexmorgan/models'),
    ('backend/tests/test_diagnostics.py', 'c:/users/alexmorgan/documents/secret'),
    ('backend/tests/test_diagnostics.py', 'c:/users/someone/thing.3mf'),
    ('backend/tests/test_fix_ledger.py', 'c:/users/someone'),
    ('backend/tests/test_fix_ledger.py', 'c:/users/someone/documents/secret'),
    ('backend/tests/test_fix_ledger.py', 'c:/users/someone/models/a.3mf'),
    ('backend/tests/test_fix_ledger.py', 'c:/users/someone/models/a_snapmakeru1.3mf'),
    ('backend/tests/test_paths.py', 'c:/users/someone/appdata/local'),
    ('backend/tests/test_privacy_adversarial.py', 'c:/users/someone/documents/orca/exports'),
    ('backend/tests/test_user_presets.py', '/home/p/.config'),
    ('backend/tests/test_user_presets.py', 'c:/users/p/appdata/roaming'),
    ('desktop/src-tauri/src/main.rs', '/home/u/apps/snapmaker-orca.appimage'),
    ('desktop/src-tauri/src/main.rs', '/home/u/my'),
    ('desktop/src/components/OrcaRoundTrip.tsx', 'c:/users/you/documents/snapmaker'),
    ('desktop/src/lib/ecosystem.test.ts', 'c:/users/someone/secret/x.exe'),
    ('desktop/src/lib/orca.test.ts', 'c:/users/secret/path.3mf'),
    ('desktop/src/routes/AfterSlicing.tsx', 'c:/users/you/downloads/something_pla_2h13m.gcode'),
    ('desktop/src/store/sliced.test.ts', '/home/someone/prints/job.gcode'),
    ('desktop/src/store/sliced.test.ts', 'c:/users/someone/downloads/job.gcode'),
    ('desktop/src/store/sliced.test.ts', 'c:/users/someone/downloads/job_pla_2h13m.gcode'),
    ('desktop/src/store/sliced.test.ts', 'c:/users/someone/job.gcode'),
    ('docs/archive/2026-06-16-m1.1e-rebase-stl-template-on-stock.md', 'd:/stl files/sample/stock_u1_blank.3mf'),
    ('docs/archive/2026-06-16-m1.1e-rebase-stl-template-on-stock.md', 'd:/stl files/validation-out/'),
    ('docs/internal/FABLE_PUBLIC_RELEASE_AUDIT.md', 'c:/users/secret/path.3mf'),
    ('docs/internal/HANDOFF_main_contract.md', 'd:/stl files/snapmaker-studio'),
    ('docs/internal/HANDOFF_main_ff1aef2.md', 'd:/stl files/snapmaker-studio'),
    ('docs/internal/HANDOFF_main_overrides.md', 'd:/stl files/snapmaker-studio'),
    ('docs/internal/HANDOFF_main_reachability.md', 'd:/stl files/snapmaker-studio'),
    ('docs/internal/HANDOFF_main_session_restart.md', 'd:/stl files/snapmaker-studio'),
    ('tools/harness/HarnessLauncher.Tests.ps1', '/home/zq91/private/customer.stl'),
    ('tools/harness/HarnessLauncher.Tests.ps1', 'c:/users/some'),
    ('tools/harness/HarnessLauncher.Tests.ps1', 'c:/users/someone'),
})


BASELINE_LINES = frozenset(f"    ({f!r}, {t!r})," for f, t in LEAK_BASELINE)


def normalize_leak(token: str) -> str:
    """Fold case, separator style and doubled or escaped separators into one key."""
    return re.sub(r"/+", "/", token.replace("\\", "/")).lower()


def leak_hits(text: str) -> list[tuple[int, str]]:
    """Every local-path match in ``text`` as (line, normalized path), not just the first."""
    return sorted((text.count("\n", 0, m.start()) + 1, normalize_leak(m.group(0)))
                  for rule in LEAK_RULES for m in rule.finditer(text))


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
        if Path(name).suffix.lower() in ARTIFACT_SUFFIXES:
            problems.append(f"{name}: tool output must not be tracked")
        raw = (root / name).read_bytes()
        is_text = True
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            content = raw.decode("utf-16")
        elif b"\0" in raw and Path(name).suffix.lower() in BINARY_SUFFIXES:
            # Known binary formats are still searched for path bytes, as latin-1 text.
            content = raw.decode("latin-1")
            is_text = False
        else:
            # Replacement characters do not hide ASCII references in legacy text.
            content = raw.decode("utf-8-sig", errors="replace")
        # A content exception waives the reference patterns only; a local path is never waived.
        # This file's own baseline entries are the one exact-line exemption, as RULE_LINES is.
        leak_text = content
        if name == SELF:
            leak_text = "\n".join("" if line in BASELINE_LINES else line
                                  for line in content.splitlines())
        for line, token in leak_hits(leak_text):
            if (name, token) not in LEAK_BASELINE:
                problems.append(f"{name}:{line}: local absolute path or user name ({token!r})")
        if not is_text:
            binary_files.append(name)
            continue
        text_files.append(name)
        if name in CONTENT_EXCEPTIONS:
            exempt_files[name] = CONTENT_EXCEPTIONS[name]
            continue
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
