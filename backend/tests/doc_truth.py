"""Reading a public document the way a reader does, so a stale claim is caught.

Studio's counts and links are checked against `docs/internal/evidence.json`, and
until v0.7.0 that checking was line-by-line: a claim only counted if the words
identifying it and the number itself landed on the same line. Three false claims
shipped in v0.7.0 through that gap, all of them obvious to a human:

* the README's top call to action still linked v0.6.2;
* "`u1convert selfcheck` … prints a 25-check pass/fail table" — the sentence wraps,
  so the word and the number were on different lines;
* "verified against the published v0.6.2 installer" sat directly above a table of
  v0.7.0's numbers.

So this module reads *blocks* — a paragraph, a list item, a table row — together
with the headings above them, which is the unit a claim actually lives in. A block
is exempt only when it or one of its headings says it is talking about the past.

Nothing here reads the immutable per-release snapshots; those are history and are
guarded separately in test_evidence_integrity.py. This is only about documents
written in the present tense.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Words that mark a block, or the section holding it, as describing the past.
HISTORICAL_MARKERS = (
    "historical", "superseded", "was accepted", "an earlier version",
    "corrected 2026", "at the time", "previous release", "shipped with",
    "used to", "before this release", "this release fixed",
)

#: Which words identify which check, so a number is only read as that check's.
SUBJECTS = {
    "acceptance": ("installed-application acceptance", "installed application acceptance",
                   "acceptance harness", "installed-build acceptance", "acceptance run",
                   "drives the installed application", "installed application,",
                   "acceptance"),
    "hardware": ("real snapmaker u1", "real u1", "hardware verification",
                 "read-only verification"),
    "selfcheck": ("selfcheck", "self-check"),
}

_RATIO = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")
_PROSE_COUNT = re.compile(r"(\d{1,3})[‐-―\- ]check(?:s)?\b", re.I)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
#: A heading is *about* a version when it opens with one — `## v0.6.2 — ACCEPTED`,
#: `## [0.6.2] - 2026-08-24`. A heading that merely links a release is not a
#: history section, which is how v0.7.0's download call to action escaped: it
#: mentioned v0.6.2, so a looser rule read the whole line as history.
_HEADING_VERSION = re.compile(r"^\[?v?(\d+\.\d+\.\d+(?:-[\w.]+)?)\]?(?![\w.])")
_RELEASE_LINK = re.compile(
    r"releases/(?:tag|download)/v(\d+\.\d+\.\d+(?:-[\w.]+)?)")
_PUBLISHED_INSTALLER = re.compile(
    r"published\s+\**v(\d+\.\d+\.\d+(?:-[\w.]+)?)\**\s+installer", re.I)
_SCREENSHOT = re.compile(r"docs/screenshots/v(\d+\.\d+\.\d+(?:-[\w.]+)?)/")
_SECONDS = re.compile(r"\b(\d{1,4})[‐-―\- ]second(?:s)?\b", re.I)
_COMBINED_ROW = re.compile(
    r"^\|\s*Backend\s*/\s*desktop[^|]*\|\s*([^|]+)\|\s*$", re.I)


@dataclass
class Block:
    """One claim-sized piece of a document, with the headings above it."""
    line: int
    text: str
    headings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def lowered(self) -> str:
        return self.text.lower()

    def mentions(self, words) -> bool:
        return any(word in self.lowered for word in words)


def blocks(text: str) -> list[Block]:
    """Split a Markdown document into blocks, each carrying its heading trail.

    A paragraph is one block, so a sentence that wraps across three lines is read
    as the one claim it is. Table rows and list items are their own blocks,
    because two rows of a table are two separate claims.
    """
    out: list[Block] = []
    stack: list[tuple[int, str]] = []
    buffer: list[str] = []
    start = 0
    pending: Block | None = None

    def flush() -> None:
        nonlocal buffer, start
        if buffer:
            joined = " ".join(line.strip() for line in buffer).strip()
            if joined:
                out.append(Block(start, joined, tuple(h for _, h in stack)))
        buffer = []

    for number, line in enumerate(text.splitlines(), start=1):
        heading = _HEADING.match(line)
        if heading:
            flush()
            pending = None
            depth = len(heading.group(1))
            while stack and stack[-1][0] >= depth:
                stack.pop()
            stack.append((depth, heading.group(2).strip()))
            out.append(Block(number, line.strip(), tuple(h for _, h in stack)))
            continue
        stripped = line.strip()
        if not stripped:
            flush()
            pending = None
            continue
        # A table row or a list item is a claim of its own; a wrapped sentence is
        # not, so only the first two split eagerly.
        if stripped.startswith("|") or re.match(r"^([-*+]|\d+\.)\s", stripped):
            flush()
            out.append(Block(number, stripped, tuple(h for _, h in stack)))
            pending = out[-1]
            continue
        if pending is not None and line[:1].isspace() and not buffer:
            # An indented continuation belongs to the list item above it. The
            # sentence "prints a 25-check pass/fail table" wrapped exactly here,
            # which is why the number and the word naming it were never read
            # together.
            pending.text = f"{pending.text} {stripped}"
            continue
        if not buffer:
            start = number
            pending = None
        buffer.append(line)
    flush()
    return out


def is_historical(block: Block, current_version: str) -> bool:
    """Whether this block is describing a release other than the current one.

    Three ways to be historical, and all three are used in this repository: the
    block says so, a heading above it says so, or a heading above it names a
    different version — which is how TRUST_STATUS keeps every past release's
    numbers without them being read as claims about today.
    """
    haystack = " ".join((block.lowered, *(h.lower() for h in block.headings)))
    if any(marker in haystack for marker in HISTORICAL_MARKERS):
        return True
    for heading in block.headings:
        found = _HEADING_VERSION.match(heading.strip())
        if found and found.group(1) != current_version:
            return True
    return False


def _live(text: str, current_version: str):
    for block in blocks(text):
        if not is_historical(block, current_version):
            yield block


def count_offenders(text: str, evidence: dict, *, name: str = "document") -> list[str]:
    """Ratios and "n-check" prose that disagree with the canonical evidence."""
    version = evidence["version"]
    offenders = []
    for block in _live(text, version):
        for key, words in SUBJECTS.items():
            if not block.mentions(words):
                continue
            expected = f"{evidence[key]['passed']}/{evidence[key]['total']}"
            total = evidence[key]["total"]
            for found in _RATIO.finditer(block.text):
                ratio = f"{int(found.group(1))}/{int(found.group(2))}"
                if ratio != expected:
                    offenders.append(f"{name}:{block.line} says {ratio} for {key}, "
                                     f"canonical is {expected}")
            for found in _PROSE_COUNT.finditer(block.text):
                if int(found.group(1)) != total:
                    offenders.append(f"{name}:{block.line} says {found.group(0)!r} "
                                     f"for {key}, canonical total is {total}")
    return offenders


def suite_offenders(text: str, evidence: dict, *, name: str = "document") -> list[str]:
    """Backend and desktop counts, including a combined row."""
    backend = str(evidence["backend"]["passed"])
    desktop = str(evidence["desktop"]["passed"])
    offenders = []
    for block in _live(text, evidence["version"]):
        combined = _COMBINED_ROW.match(block.text)
        if combined:
            fields = [cell.strip() for cell in combined.group(1).split("·")]
            if len(fields) >= 2:
                if fields[0] != backend:
                    offenders.append(f"{name}:{block.line} combined row says backend "
                                     f"{fields[0]}, canonical is {backend}")
                if fields[1] != desktop:
                    offenders.append(f"{name}:{block.line} combined row says desktop "
                                     f"{fields[1]}, canonical is {desktop}")
            continue
        if "backend" in block.lowered and "passed" in block.lowered:
            if backend not in block.text:
                offenders.append(f"{name}:{block.line} quotes a backend count that is "
                                 f"not {backend}")
        if "desktop" in block.lowered and "passed" in block.lowered:
            if desktop not in block.text:
                offenders.append(f"{name}:{block.line} quotes a desktop count that is "
                                 f"not {desktop}")
    return offenders


def release_offenders(text: str, evidence: dict, *, name: str = "document") -> list[str]:
    """Links and version names in present-tense prose.

    Covers the download call to action wherever it appears — not only inside a
    section called Download — and the "published vX installer" sentence that made
    v0.7.0's numbers look like they came from v0.6.2's build.
    """
    version = evidence["version"]
    offenders = []
    for block in _live(text, version):
        for found in _RELEASE_LINK.finditer(block.text):
            if found.group(1) != version:
                offenders.append(f"{name}:{block.line} links release v{found.group(1)}, "
                                 f"current is v{version}")
        for found in _PUBLISHED_INSTALLER.finditer(block.text):
            if found.group(1) != version:
                offenders.append(f"{name}:{block.line} credits the published "
                                 f"v{found.group(1)} installer, current is v{version}")
        for found in _SCREENSHOT.finditer(block.text):
            if found.group(1) != version:
                offenders.append(f"{name}:{block.line} shows screenshots from "
                                 f"v{found.group(1)}, current is v{version}")
    return offenders


#: Length of the separate real-user rescue example recording (65.17 s, rounded as the docs quote it).
RESCUE_DEMO_SECONDS = 65


def demo_offenders(text: str, evidence: dict, *, name: str = "document") -> list[str]:
    """The demo's length, wherever it is quoted."""
    seconds = (evidence.get("demo") or {}).get("seconds")
    if not seconds:
        return []
    offenders = []
    for block in _live(text, evidence["version"]):
        if "demo" not in block.lowered and "watch it work" not in block.lowered:
            continue
        # The real-user rescue example (docs/media/snapmaker-studio-rescue-demo.mp4) is a second,
        # separate recording with its own length; its blocks are held to that length instead.
        expected = RESCUE_DEMO_SECONDS if "rescue" in block.lowered else seconds
        for found in _SECONDS.finditer(block.text):
            if int(found.group(1)) != expected:
                offenders.append(f"{name}:{block.line} says the demo is "
                                 f"{found.group(1)} seconds, canonical is {expected}")
    return offenders


ALL_CHECKS = (count_offenders, suite_offenders, release_offenders, demo_offenders)
