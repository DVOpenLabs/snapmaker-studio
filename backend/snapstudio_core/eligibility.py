"""One answer to "can Studio prepare this file?", shared by every consumer.

Two separate questions, never merged:

* **readable** - Studio can open the file as a usable project (required parts are there).
  This is what the Doctor's HIGH_RISK verdict means, and nothing else does.
* **preparable** - Prepare would produce a copy rather than refuse. A readable file can
  be unpreparable: it carries per-object settings Studio has not verified Snapmaker Orca
  reads, a part-level value Orca 2.4.0 cannot load, or a structure that disagrees with itself.

Prepare (`convert.check_structure`), the Doctor, Model Connect, the Validation Center,
Ready Now, the Compatibility Doctor and the CLI all read this one record, so they cannot
disagree. A file that is not preparable is never "ready".
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import multipart
from .errors import plain_refusal

SETTINGS = "Metadata/project_settings.config"


@dataclass(frozen=True)
class Eligibility:
    readable: bool
    preparable: bool
    #: Raw engine wording, for a collapsed technical area only.
    problems: list = field(default_factory=list)
    #: One plain sentence for people ("" when preparable).
    summary: str = ""


def structure_problems(tm) -> list[str]:
    """Everything Prepare's structure gate refuses on; empty when sound. Read-only."""
    result = multipart.validate_archive(tm)
    if result.get("ok", True):
        return []
    return list(result.get("problems") or ["the structure is unsound"])


def assess(tm, readable: bool = True) -> Eligibility:
    """Eligibility of an opened source project.

    The gate only applies to a project that has `project_settings.config`: a geometry-only
    3MF is wrapped into a fresh project rather than repaired, so its own metadata is not
    what Prepare would write.
    """
    problems: list[str] = []
    if readable and tm.has_part(SETTINGS):
        try:
            problems = structure_problems(tm)
        except Exception:  # noqa: BLE001 - an assessment never fails on an odd corner
            problems = []
    return Eligibility(readable=readable, preparable=readable and not problems,
                       problems=problems,
                       summary=plain_refusal(problems, prepared_note=False) if problems else "")
