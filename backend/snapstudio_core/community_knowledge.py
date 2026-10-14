"""Community Knowledge Doctor — MVP + architecture.

WHY: the U1 community has already diagnosed and fixed most recurring friction, but
that knowledge is scattered across Facebook groups, r/snapmaker, the Snapmaker
forums, and GitHub issues. A first-time user hits "out of bounds" and has to go
ask. This brings the known answer in-app.

ARCHITECTURE (staged):
  MVP (this file): a curated, offline knowledge base of the top recurring U1
    issues, each with symptom keywords, plain-language cause, the community's
    fix, and its source themes. `match()` maps a free-text symptom (or the
    Report's risk texts via `match_risks()`) to the relevant entries. The Report
    can then attach "the community's fix" to any risk it raises — evidence, not a
    new Doctor surface.
  Phase 2 (planned, not in MVP): periodic ingestion — pull + cluster public
    threads (Reddit API, GitHub issues API, forum RSS) into candidate entries,
    human-reviewed before they enter the curated set (never auto-published, to
    keep quality and avoid bad advice). Per-entry "helped / didn't help" feedback
    to rank fixes. All read-only, attributed, licence-respecting (link out, never
    rehost copyrighted posts).

HONEST: the MVP set is curated by theme, not scraped; entries cite where the
pattern is discussed, not individual users' words.
"""
from __future__ import annotations

SCHEMA_VERSION = "communityknowledge/1"

KNOWN_ISSUES = [
    {
        "id": "out-of-bounds",
        "title": "“Out of bounds” with no reason",
        "symptoms": ["out of bounds", "outside", "won't slice", "wont slice", "too big",
                     "exceeds", "off the plate", "doesn't fit", "bed size"],
        "cause": "The model (or its skirt/brim/prime tower) extends past the U1's "
                 "270×270×270 mm printable area; Orca refuses to slice but doesn't say which axis.",
        "community_fix": "Scale to fit (Studio's Project Doctor gives the exact %), rotate ~45° "
                         "if only one axis is over, or split the model. Check in Snapmaker Orca that every object is on the plate.",
        "sources": ["r/snapmaker", "Snapmaker forum", "Facebook Snapmaker U1 group"],
    },
    {
        "id": "prime-tower",
        "title": "Prime / wipe tower collisions or tipping",
        "symptoms": ["prime tower", "wipe tower", "tower collision", "tower falling",
                     "tower tipping", "purge tower"],
        "cause": "Multi-material prints need clearance for the prime/wipe tower; if the model "
                 "fills the plate the tower gets pushed off the bed or printed too thin and topples.",
        "community_fix": "Leave room beside the model (shrink it slightly), reduce the tower size/brim "
                         "in Orca, or enable a tower brim for adhesion. Studio's Project Doctor flags low tower room.",
        "sources": ["r/snapmaker", "GitHub: OrcaSlicer issues", "Facebook Snapmaker U1 group"],
    },
    {
        "id": "multi-material-limit",
        "title": "More colours than toolheads",
        "symptoms": ["multi material", "multi-material", "colours", "colors", "toolhead",
                     "5 colours", "too many colours", "colour bleed", "color bleed", "wrong colour"],
        "cause": "The U1 has 4 toolheads; a design with more colours can't load them all at once, "
                 "so colours print wrong or the job fails.",
        "community_fix": "Remap to 4 colours in Orca, or pause-and-swap filament mid-print. "
                         "Studio's Multi-Material Doctor checks this and keeps all original colours in the file.",
        "sources": ["r/snapmaker", "Snapmaker forum"],
    },
    {
        "id": "first-layer-adhesion",
        "title": "First layer won't stick",
        "symptoms": ["first layer", "adhesion", "not sticking", "warping", "lifting",
                     "bed mesh", "z offset", "z-offset"],
        "cause": "Uneven bed, Z-offset, or a small/narrow contact patch; common on tall or "
                 "small-footprint parts.",
        "community_fix": "Re-run bed mesh, tune Z-offset, add a brim, slow the first layer. "
                         "Studio's First Layer Doctor flags adhesion risk from the footprint + the printer's real mesh.",
        "sources": ["r/snapmaker", "Snapmaker forum", "Facebook Snapmaker U1 group"],
    },
    {
        "id": "cryptic-error",
        "title": "Cryptic Klipper / firmware error mid-print",
        "symptoms": ["klippy", "shutdown", "mcu", "error mid-print", "lost connection",
                     "thermal", "endstop", "firmware error"],
        "cause": "Klipper halts on a hardware fault (thermal runaway, endstop, lost MCU link) "
                 "and shows a low-level message most users can't parse.",
        "community_fix": "Read the printer's own diagnostics (Studio's Printer Doctor surfaces state + "
                         "failed components in plain language), check wiring/temps, then restart firmware.",
        "sources": ["GitHub: Snapmaker U1 firmware", "r/snapmaker", "Snapmaker forum"],
    },
    {
        "id": "snorca-customized-preset",
        "title": "Snapmaker Orca “Customized Preset” / converted-project issues",
        "symptoms": ["customized preset", "customised preset", "converted", "bambu",
                     "import", "filament mismatch", "preset", "project won't open", "compatibility"],
        "cause": "A converted or foreign project has filament arrays / purge volumes that don't match "
                 "the filament count, so Orca flags a Customized Preset and may misprint.",
        "community_fix": "Conform the filament arrays to the colour count (Studio's repair does this), "
                         "or reselect the U1 presets. Studio validates this on import.",
        "sources": ["GitHub: OrcaSlicer issues", "Snapmaker forum"],
    },
]

_STOP = {"the", "a", "an", "and", "or", "is", "it", "to", "of", "my", "with", "for", "on", "in"}


def _tokens(text: str) -> set:
    import re
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in _STOP}


def match(query: str, limit: int = 3) -> list:
    """Return curated community entries relevant to a free-text symptom, ranked."""
    q = (query or "").lower()
    if not q.strip():
        return []
    qtok = _tokens(q)
    scored = []
    for e in KNOWN_ISSUES:
        score = 0
        for sym in e["symptoms"]:
            if sym in q:                       # phrase hit (strong)
                score += 3
            elif _tokens(sym) & qtok:          # token overlap (weak)
                score += 1
        if score:
            scored.append((score, e))
    scored.sort(key=lambda s: s[0], reverse=True)
    return [e for _, e in scored[:limit]]


def match_risks(risk_texts, limit_per: int = 1) -> list:
    """Map a list of Report risk texts to community guidance (deduped)."""
    seen = set()
    out = []
    for t in (risk_texts or []):
        for e in match(t, limit=limit_per):
            if e["id"] not in seen:
                seen.add(e["id"])
                out.append(e)
    return out
