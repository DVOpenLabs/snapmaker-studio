"""Guards against documents that describe a state the project has left behind.

This file exists because of a specific failure. Snapmaker Studio was submitted to
the Innovation Fund on 24 June 2026, confirmed on 29 June, and listed publicly
among the fund's 41 entries. Two months later a sprint read a stale document,
concluded the project had not been submitted, and reported "submit the form" as a
remaining human action. The stale document was believed over the live world.

Documents that describe the *current* state must not contain phrases that assert
a superseded one. Historical documents may — they just have to say so.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Documents that speak in the present tense about where the project is now.
CURRENT_STATE_DOCS = [
    ROOT / "README.md",
    ROOT / "docs" / "INNOVATION_FUND.md",
    ROOT / "docs" / "SUBMISSION_STATUS.md",
    ROOT / "docs" / "innovation-fund" / "JUDGE_OVERVIEW.md",
    ROOT / "docs" / "innovation-fund" / "NEXT_MOVES.md",
    ROOT / "docs" / "innovation-fund" / "PHASE1_POSITION.md",
]

# A document may carry any of these if it declares itself historical.
HISTORICAL_MARKERS = ("historical record", "historical document", "superseded",
                      "corrected 2026", "an earlier version")

# Each entry is (regex, why it is wrong now). The negative look-behinds matter:
# "do not submit the form again" is the correct instruction and must be allowed,
# while "submit the form" as a task must not be.
_NEG = r"(?<!do not )(?<!don't )(?<!never )(?<!not )(?<!re-)"

STALE_STATE_PHRASES = [
    (r"not yet submitted", "the Phase 1 entry was submitted on 24 June 2026"),
    (r"has not been submitted", "the Phase 1 entry was submitted on 24 June 2026"),
    (_NEG + r"submit the form", "the form has already been submitted; a second entry is a duplicate"),
    (_NEG + r"submit the entry", "the entry has already been submitted"),
    (r"future printer hub", "Printer Hub shipped"),
    (r"printer hub is planned", "Printer Hub shipped"),
    (r"sending is not shipped", "sending shipped"),
    (r"sending is \*\*not\*\* shipped", "sending shipped"),
    (r"pending acceptance", "beta.24 is ACCEPTED"),
]


def _read(path: Path) -> str:
    assert path.exists(), f"missing current-state document: {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("doc", CURRENT_STATE_DOCS, ids=lambda p: p.name)
def test_current_state_documents_carry_no_superseded_state(doc):
    text = _read(doc).lower()
    offenders = [
        f"{pattern!r} — {why}"
        for pattern, why in STALE_STATE_PHRASES
        if re.search(pattern, text)
    ]
    assert not offenders, (
        f"{doc.name} describes a state the project has left:\n  " + "\n  ".join(offenders))


def test_the_submission_is_recorded_as_complete():
    """The single fact this whole file protects."""
    text = _read(ROOT / "docs" / "INNOVATION_FUND.md")
    assert "Submitted" in text and "24 June 2026" in text, (
        "INNOVATION_FUND.md must record that the entry was submitted, and when")
    # The fund's own project count is contradictory and changes (41, then 66-67), so the
    # guard pins the fact that matters: the entry is publicly listed on the fund page.
    assert "publicly listed" in text and "snapmaker.com/innovation-fund" in text, (
        "INNOVATION_FUND.md must record that the project is publicly listed")


def test_the_submitted_entry_is_kept_and_marked_historical():
    doc = ROOT / "docs" / "innovation-fund" / "SUBMITTED_ENTRY.md"
    text = _read(doc)
    assert any(m in text.lower() for m in HISTORICAL_MARKERS), (
        "SUBMITTED_ENTRY.md holds the June text and must declare itself historical")


def test_no_document_claims_a_signed_installer():
    """Signing has not happened. It would be an easy claim to let slip in."""
    for doc in CURRENT_STATE_DOCS:
        text = _read(doc).lower()
        assert not re.search(r"(?<!un)signed installer|installer is signed|"
                             r"(?<!un)code-?signed build", text), (
            f"{doc.name} claims a signed installer; none has been produced")
