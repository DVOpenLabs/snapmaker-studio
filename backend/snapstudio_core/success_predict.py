"""Print Success Prediction — "will this actually print on my U1?", before you start.

Studio already knows, separately: whether the design is validation-ready, whether
its colours fit the toolheads, whether the first layer is risky, how healthy the
printer is, and whether this exact file has failed before. A novice has to read all
of those and judge. This synthesises them into one honest likelihood + the factors
behind it, so the answer to "should I hit print?" is a single read.

Pure read-only synthesis of signals Studio already has — no webcam, no AI vision,
no control, no new printer calls. Honest: it scores only the signals present, names
what's pulling the odds down, and stays calibrated (no false confidence).
"""
from __future__ import annotations

SCHEMA_VERSION = "successpredict/1"


def _band(likelihood: int) -> str:
    if likelihood >= 75:
        return "likely"
    if likelihood >= 50:
        return "uncertain"
    return "risky"


def predict(readiness=None, toolfit=None, first_layer=None, health=None,
            prior_failures: int = 0, geometry_basis: dict | None = None) -> dict:
    """Combine pre-print signals into a 0–100 success likelihood.

    readiness: validation_report.readiness_report() output (ready + warnings).
    toolfit:   toolhead_fit.assess() output (overall_level).
    first_layer: first_layer.assess() output (overall_level).
    health:    health_score.score() output (score 0–100).
    prior_failures: times this exact file has failed in the printer's history.
    """
    have_any = any([readiness, toolfit, first_layer,
                    health and health.get("available"), prior_failures])
    if not have_any:
        return {"schema_version": SCHEMA_VERSION, "available": False,
                "reason": "no design or printer signals available to predict from"}

    if geometry_basis is not None and not geometry_basis.get("established", True):
        return _not_estimated(geometry_basis, toolfit, health, prior_failures)

    factors: list[tuple[int, str]] = []

    if readiness and readiness.get("ready") is False:
        w = len(readiness.get("warnings") or [])
        factors.append((min(40, 20 + 5 * w),
                        f"design isn't validation-ready ({w} issue{'s' if w != 1 else ''} to fix)"))

    if toolfit and toolfit.get("available"):
        lvl = toolfit.get("overall_level")
        if lvl == "risk":
            factors.append((25, "more colours than toolheads — needs a swap or remap"))
        elif lvl == "warn":
            factors.append((10, "colour layout needs a filament swap or remap"))

    if first_layer:
        lvl = first_layer.get("overall_level")
        if lvl == "risk":
            factors.append((20, "first-layer adhesion looks risky on this printer"))
        elif lvl == "warn":
            factors.append((10, "first layer is marginal — watch adhesion"))

    if health and health.get("available"):
        hs = int(health.get("score") or 100)
        if hs < 60:
            factors.append((round((60 - hs) * 0.5), f"printer health is low ({hs}/100)"))

    if prior_failures and prior_failures > 0:
        factors.append((min(30, 15 * min(prior_failures, 2)),
                        f"this exact file failed {prior_failures}× before"))

    likelihood = max(0, min(100, 100 - sum(p for p, _ in factors)))
    band = _band(likelihood)

    factors.sort(key=lambda f: f[0], reverse=True)
    factor_text = [t for _, t in factors] or ["No risk signals in the design, printer, or history."]

    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "likelihood": likelihood,
        "band": band,
        "factors": factor_text,
        "verdict": _verdict(likelihood, band),
    }


def _not_estimated(basis: dict, toolfit, health, prior_failures: int) -> dict:
    """The model's physical size is not established, so the design signals that rest on it
    (readiness, first layer) are not usable and neither is a probability built from the
    rest: say so, and keep only the independent signals as plain facts, not as a score."""
    from . import geometry_basis as gb
    facts: list[str] = []
    if toolfit and toolfit.get("available"):
        lvl = toolfit.get("overall_level")
        if lvl == "risk":
            facts.append("more colours than toolheads — needs a swap or remap")
        elif lvl == "warn":
            facts.append("colour layout needs a filament swap or remap")
    if health and health.get("available") and int(health.get("score") or 100) < 60:
        facts.append(f"printer health is low ({int(health.get('score') or 100)}/100)")
    if prior_failures and prior_failures > 0:
        facts.append(f"this exact file failed {prior_failures}× before")
    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "likelihood": None,
        "band": "unknown",
        "factors": facts,
        "verdict": "Not estimated — Studio could not establish this model's physical size, "
                   "so it makes no print-success estimate.",
        **gb.not_checked(basis, "the print-success estimate"),
    }


def _verdict(likelihood: int, band: str) -> str:
    if band == "likely":
        return f"Likely to print ({likelihood}%) — review settings before printing."
    if band == "uncertain":
        return f"Could go either way ({likelihood}%) — clear the points below first."
    return f"Risky ({likelihood}%) — fix the points below before starting a long print."
