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
import hashlib
import re
import subprocess
import sys
from urllib.parse import unquote


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
_DRIVE = r"[A-Za-z]:[\x5c/]+"
_TAIL = r"[^\s\"'`<>|*?,;)\]}]*"
# A UNC share or a file URL with a host names the machine before the user directory.
# Up to two share segments (an administrative share such as a drive share, or a named share)
# may sit between the host and the protected directory. The leading separators may be
# doubled (an escaped string literal), so two or more are accepted.
_UNC = (r"(?:file:[\x5c/]{2,}|(?<![\w:.\x5c/])[\x5c/]{2,})[^\x5c/\s:]+[\x5c/]+"
        r"(?:[^\x5c/\s:]+[\x5c/]+){0,2}?")
_USERS = r"(?:Users|STL Files)[\x5c/]+(?!Public\b)"
LEAK_RULES = (
    re.compile(_DRIVE + _USERS + _TAIL, re.IGNORECASE),
    re.compile(_UNC + _USERS + _TAIL, re.IGNORECASE),
    re.compile("/ho" + r"me/+(?!runner\b)[A-Za-z0-9_.-]+/" + _TAIL, re.IGNORECASE),
)
# Known synthetic test paths and historical handoff notes, as (file, line key): the whole
# normalized line (see line_key). A longer or different path on an approved line, or a path
# that only shares an approved prefix, is a violation. The set is closed; nothing is exempt
# by file name, and a matched path is never compared as a prefix.
LEAK_BASELINE: frozenset[tuple[str, str]] = frozenset({
    ('backend/tests/fixtures/providers/spoolman_0_26_1.json', '"backups_dir": "/home/app/spoolman/c:/program files/git/home/app/.local/share/spoolman/backups",'),
    ('backend/tests/fixtures/providers/spoolman_0_26_1.json', '"data_dir": "/home/app/spoolman/c:/program files/git/home/app/.local/share/spoolman",'),
    ('backend/tests/fixtures/providers/spoolman_0_26_1.json', '"logs_dir": "/home/app/spoolman/c:/program files/git/home/app/.local/share/spoolman",'),
    ('backend/tests/test_diagnostics.py', '"nested": [{"home": "/home/alexmorgan/models"}],'),
    ('backend/tests/test_diagnostics.py', '"path": r"c:/users/alexmorgan/documents/secret model.3mf",'),
    ('backend/tests/test_diagnostics.py', 'original = {"path": r"c:/users/someone/thing.3mf"}'),
    ('backend/tests/test_fix_ledger.py', 'assert "c:/users/someone" not in blob'),
    ('backend/tests/test_fix_ledger.py', 'def entry(tmp_path, *, operation=fix_ledger.prepare, source="c:/users/someone/models/a.3mf",'),
    ('backend/tests/test_fix_ledger.py', 'output = "c:/users/someone/documents/secret project/model_snapmakeru1.3mf"'),
    ('backend/tests/test_fix_ledger.py', 'output="c:/users/someone/models/a_snapmakeru1.3mf", **kw):'),
    ('backend/tests/test_fix_ledger.py', 'source = "c:/users/someone/documents/secret project/model.3mf"'),
    ('backend/tests/test_paths.py', 'assert result == os.path.join(r"c:/users/someone/appdata/local", "snapmakerstudio")'),
    ('backend/tests/test_paths.py', 'monkeypatch.setenv("localappdata", r"c:/users/someone/appdata/local")'),
    ('backend/tests/test_privacy_adversarial.py', 'scrubbed = diagnostics.redact({"folder": r"c:/users/someone/documents/orca/exports"})'),
    ('backend/tests/test_user_presets.py', '[path(r"c:/users/p/appdata/roaming") / "snapmaker_orca" / "user"]'),
    ('backend/tests/test_user_presets.py', 'assert pc.default_user_roots({"appdata": r"c:/users/p/appdata/roaming"}, "win32") == /'),
    ('backend/tests/test_user_presets.py', 'assert pc.default_user_roots({"home": "/home/p"}, "linux") == [path("/home/p/.config") / "snapmaker_orca" / "user"]'),
    ('desktop/src-tauri/src/main.rs', 'let text = "[desktop entry]/nname=orcaslicer/nexec=/"/home/u/my apps/orca-slicer.appimage/" %u/n";'),
    ('desktop/src-tauri/src/main.rs', 'let text = "[desktop entry]/nname=snapmaker orca/nexec=/home/u/apps/snapmaker-orca.appimage %f/ntype=application/n";'),
    ('desktop/src-tauri/src/main.rs', 'some(pathbuf::from("/home/u/apps/snapmaker-orca.appimage"))'),
    ('desktop/src-tauri/src/main.rs', 'some(pathbuf::from("/home/u/my apps/orca-slicer.appimage"))'),
    ('desktop/src/components/OrcaRoundTrip.tsx', 'placeholder="c:/users/you/documents/snapmaker orca/output"'),
    ('desktop/src/lib/ecosystem.test.ts', 'const msg = toolerrormessage(new error("launch-failed: c:/users/someone/secret/x.exe"), "x");'),
    ('desktop/src/lib/orca.test.ts', 'const m = orcaerrormessage("c:/users/secret/path.3mf blew up");'),
    ('desktop/src/routes/AfterSlicing.tsx', 'placeholder="c:/users/you/downloads/something_pla_2h13m.gcode"'),
    ('desktop/src/store/sliced.test.ts', '/ "c:/users/someone/downloads/job.gcode" where the file name belonged —'),
    ('desktop/src/store/sliced.test.ts', 'const full = string.raw`c:/users/someone/job.gcode`;'),
    ('desktop/src/store/sliced.test.ts', 'usesliced.getstate().setsliced("/home/someone/prints/job.gcode");'),
    ('desktop/src/store/sliced.test.ts', 'usesliced.getstate().setsliced(string.raw`c:/users/someone/downloads/job_pla_2h13m.gcode`);'),
    ('docs/archive/2026-06-16-m1.1e-rebase-stl-template-on-stock.md', '- [ ] regenerate the 4 validation outputs into `d:/stl files/validation-out/`.'),
    ('docs/archive/2026-06-16-m1.1e-rebase-stl-template-on-stock.md', "cfg=json.loads(zipfile.zipfile(r'd:/stl files/sample/stock_u1_blank.3mf').read('metadata/project_settings.config').decode('utf-8'))"),
    ('docs/internal/FABLE_PUBLIC_RELEASE_AUDIT.md', '| no real local user paths | — | only hit is synthetic test data (`orca.test.ts`: "c:/users/secret/path.3mf") — clearly fake | public but harmless | none |'),
    ('docs/internal/HANDOFF_main_contract.md', 'cd "d:/stl files/snapmaker-studio"'),
    ('docs/internal/HANDOFF_main_ff1aef2.md', 'cd "d:/stl files/snapmaker-studio"'),
    ('docs/internal/HANDOFF_main_overrides.md', 'cd "d:/stl files/snapmaker-studio"'),
    ('docs/internal/HANDOFF_main_reachability.md', 'cd "d:/stl files/snapmaker-studio"'),
    ('docs/internal/HANDOFF_main_session_restart.md', 'cd "d:/stl files/snapmaker-studio"'),
    ('tools/harness/HarnessLauncher.Tests.ps1', '$global:ssht.uninstallthrow = "could not find file \'c:/users/someone else/my models/private-benchy-zq91.stl\'"'),
    ('tools/harness/HarnessLauncher.Tests.ps1', '@{ t = "could not find file \'c:/users/someone else/my models/private-benchy-zq91.stl\'."; bad = \'someone\', \'my models\', \'private\', \'zq91\', \'benchy\' }'),
    ('tools/harness/HarnessLauncher.Tests.ps1', "@{ t = 'arbitrary text with private local data'; text = 'state dump: model customer-alpha-zq91 at /home/zq91/private/customer.stl (owner zq91person)'; segs = @('customer', 'alpha', 'zq91', 'zq91person#329f6adaec67"),
    ('tools/harness/HarnessLauncher.Tests.ps1', "@{ t = 'forward-slash path'; text = 'c:/users/someone else/private models/customer alpha.3mf'; segs = @('someone', 'private', 'customer', 'alpha') }"),
    ('tools/harness/HarnessLauncher.Tests.ps1', "@{ t = 'literal doubled backslashes'; text = 'c:/users/someone else/private models/customer alpha.3mf'; segs = @('someone', 'private', 'customer', 'alpha') }"),
    ('tools/harness/HarnessLauncher.Tests.ps1', 'mock -modulename harnesslauncher write-harnesslaneevidence { throw "locked: c:/users/some one/priv dir/x.json" }'),
})


BASELINE_LINES = frozenset(f"    ({f!r}, {k!r})," for f, k in LEAK_BASELINE)


def decode_line(line: str) -> str:
    """Undo URL encoding (also when applied twice) so encoded separators and colons match."""
    for _ in range(3):
        decoded = unquote(line)
        if decoded == line:
            break
        line = decoded
    return line


def normalize_leak(token: str) -> str:
    """Fold case, separator style and doubled or escaped separators into one key."""
    return re.sub(r"/+", "/", token.replace("\\", "/")).lower()


def line_key(decoded_line: str) -> str:
    """The approved context: the whole normalized line, hashed past 200 characters."""
    key = normalize_leak(decoded_line).strip()
    if len(key) > 200:
        key = key[:200] + "#" + hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:12]
    return key


def leak_hits(text: str) -> list[tuple[int, str, str]]:
    """Every local-path match as (line number, normalized path, line key), not just the first."""
    hits = set()
    for number, raw in enumerate(text.split("\n"), start=1):
        line = decode_line(raw)
        for rule in LEAK_RULES:
            for m in rule.finditer(line):
                hits.add((number, normalize_leak(m.group(0)), line_key(line)))
    return sorted(hits)


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
        for line, token, key in leak_hits(leak_text):
            if (name, key) not in LEAK_BASELINE:
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
