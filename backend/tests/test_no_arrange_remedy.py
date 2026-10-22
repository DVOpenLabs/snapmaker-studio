"""Studio does not recommend Arrange as a remedy.

In Snapmaker Orca 2.4.0, on a two-plate project made for a larger-bed printer,
Arrange all plates did not fix an Outside object or an inherited prime tower; for a
single plate it was never tested. A text that tells people Arrange fixes placement is
therefore unsupported. The one sentence that may name it says it did not work.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = "Arrange all plates did not fix that in our test"
ARRANGE = re.compile(r"\barrange\b", re.IGNORECASE)   # not "arrangement"

SCAN = [
    (ROOT / "backend" / "snapstudio_core", "*.py"),
    (ROOT / "backend" / "snapstudio_api", "*.py"),
    (ROOT / "backend" / "u1convert", "*.py"),
    (ROOT / "desktop" / "src", "*.ts"),
    (ROOT / "desktop" / "src", "*.tsx"),
    # site/guide/content is deliberately not scanned here: the user guide is held and
    # reviewed on its own, so this guard covers the app and engine text only.
]


def _files():
    for base, pattern in SCAN:
        for path in sorted(base.rglob(pattern)):
            if ".test." in path.name or "node_modules" in path.parts:
                continue
            yield path


def test_no_text_recommends_arrange():
    offenders = []
    for path in _files():
        for number, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            if ARRANGE.search(line.replace(ALLOWED, "")):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:120]}")
    assert not offenders, "Arrange is not a tested remedy:\n" + "\n".join(offenders)


def test_the_guard_actually_scans_something():
    assert sum(1 for _ in _files()) > 100
