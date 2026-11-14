"""Loss reports for creative projects; reports are advisory and read-only."""
from __future__ import annotations

from .readers import CreativeProject


def document(project: CreativeProject) -> dict:
    """Return per-format understood, passed-through and unknown fields."""
    report = project.loss_report()
    report["evidence"] = "fixture-tested; fixtures are hand-written to published shapes, not captures"
    return report
