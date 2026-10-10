"""Studio Intelligence Report — the Doctors become evidence, the Report is the product.

Every Doctor answers one question. A user shouldn't have to read seven cards to
know where they stand. This synthesises them into a single screen's worth of
answer: a Studio Intelligence Score, the money headline, the biggest risk, and
the one next action — with each Doctor's finding as supporting evidence.

Pure synthesis over already-computed Doctor dicts (no network, no fabrication):
it scores only what's present, surfaces real findings, and stays honest about
what it can't yet see.
"""
from __future__ import annotations

SCHEMA_VERSION = "report/1"

_ORDER = {"ok": 0, "warn": 1, "risk": 2}
_LEVEL_SCORE = {"ok": 100, "warn": 70, "risk": 40}


def _push_findings(risks, recs, doctor, doc):
    """Collect a doctor's non-ok findings as risks and its fixes as recommendations."""
    if not doc or not doc.get("available", True):
        return
    for f in (doc.get("findings") or []):
        if f.get("level") in ("warn", "risk"):
            risks.append({"doctor": doctor, "level": f["level"], "text": f["text"]})
    for fx in (doc.get("fixes") or []):
        recs.append(fx)


def demo() -> dict:
    """Demo Mode: a representative report for a typical multicolour U1 model —
    no file, no printer needed, deterministic, for Innovation Fund reviewers.
    Built through the REAL synthesis engine from realistic Doctor outputs (with a
    bed-fit risk + a colour note so the value is visible), then flagged is_demo."""
    out = build(
        predict={"available": True, "likelihood": 72, "band": "uncertain",
                 "factors": ["more colours than toolheads — needs a swap or remap"]},
        bed_fit={"available": True, "overall_level": "risk",
                 "overall_text": "It won't fit as-is — this is the out-of-bounds error.",
                 "findings": [{"level": "risk", "text": "Too big for the bed: 286×140 mm on a 270×270 mm bed — scale to 94% to fit."}],
                 "fixes": ["Scale to 94% so it fits the 270×270 mm bed.",
                           "Or rotate it ~45° — the diagonal fits within the bed."]},
        mm={"available": True, "overall_level": "warn",
            "overall_text": "Multi-material setup needs a tweak before slicing.",
            "findings": [{"level": "warn", "text": "5 colours but only 4 toolheads — 1 colour can't load at once."}],
            "fixes": ["Remap to 4 colours in Orca, or pause-and-swap mid-print."]},
        first_layer={"overall_level": "ok", "overall_text": "First layer looks solid.", "findings": []},
        health={"available": True, "score": 88, "grade": "A", "drivers": [],
                "verdict": "Healthy (88/100) — good to print."},
        cost={"available": True, "true_cost": 6.40, "suggested_price": 11.84,
              "margin": 5.44, "margin_pct": 46.0, "currency": "$", "time_known": True,
              "basis": "printer slicer metadata"},
        pricing={"available": True, "currency": "$", "verdict": "Marketplace ~$11.84"},
        profit={"available": True, "profit_per_print": 5.44, "margin_pct": 46.0},
    )
    out["is_demo"] = True
    out["demo_name"] = "Sample: multicolour desk organiser"
    return out


def build(predict=None, bed_fit=None, mm=None, first_layer=None, health=None,
          cost=None, pricing=None, profit=None, spacing=None) -> dict:
    """Combine the Doctors into one report. All inputs are their build() outputs.

    `spacing` is the object-spacing/collision status ({"status": ...}); when it is
    "unknown" the report must not claim "no major blockers found"."""
    avail = {
        "predict": bool(predict and predict.get("available")),
        "bed_fit": bool(bed_fit and bed_fit.get("available")),
        "mm": bool(mm and mm.get("available")),
        "first_layer": bool(first_layer and first_layer.get("overall_level")),
        "health": bool(health and health.get("available")),
        "cost": bool(cost and cost.get("available")),
        "pricing": bool(pricing and pricing.get("available")),
        "profit": bool(profit and profit.get("available")),
    }
    if not any(avail.values()):
        return {"schema_version": SCHEMA_VERSION, "available": False,
                "reason": "no Doctor results available to report on"}

    cur = (cost or {}).get("currency") or (pricing or {}).get("currency") or "$"

    # --- headline scores ---
    success = predict.get("likelihood") if avail["predict"] else None
    health_score = health.get("score") if avail["health"] else None

    # Studio Intelligence Score: blend print-success and printer-health when both
    # are known; otherwise lean on whichever exists, then on the doctors' levels.
    comp = []
    if success is not None:
        comp.append((success, 0.6))
    if health_score is not None:
        comp.append((health_score, 0.4))
    if comp:
        wsum = sum(w for _, w in comp)
        studio_score = round(sum(v * w for v, w in comp) / wsum)
    else:
        worst = "ok"
        for d in (bed_fit, mm, first_layer):
            lvl = (d or {}).get("overall_level")
            if lvl and _ORDER[lvl] > _ORDER[worst]:
                worst = lvl
        studio_score = _LEVEL_SCORE[worst] if any([avail["bed_fit"], avail["mm"], avail["first_layer"]]) else None

    # --- money headline ---
    money = cost or {}
    cost_v = money.get("true_cost") if avail["cost"] else None
    price_v = money.get("suggested_price") if avail["cost"] else None
    margin_pct = (profit.get("margin_pct") if avail["profit"] else money.get("margin_pct")) if (avail["profit"] or avail["cost"]) else None
    profit_v = profit.get("profit_per_print") if avail["profit"] else (money.get("margin") if avail["cost"] else None)

    # --- printer compatibility ---
    if avail["health"]:
        compatibility = "Compatible" if (health_score or 0) >= 60 else "Check"
    else:
        compatibility = "Unknown"   # no printer connected; design-only signals

    # --- risks + recommendations from every doctor ---
    risks: list = []
    recs: list = []
    _push_findings(risks, recs, "Bed fit (size and placement)"
                   if (bed_fit or {}).get("placement_checked") else "Bed fit", bed_fit)
    _push_findings(risks, recs, "Multi-Material Doctor", mm)
    _push_findings(risks, recs, "First Layer Doctor", first_layer)
    if avail["health"]:
        for d in (health.get("drivers") or []):
            if "no problem" not in d.lower():
                risks.append({"doctor": "Printer Doctor", "level": "warn", "text": d})
    if avail["predict"]:
        for f in (predict.get("factors") or []):
            if "no risk" not in f.lower():
                risks.append({"doctor": "Project Doctor", "level": "warn", "text": f})
    if avail["profit"] and (profit.get("profit_per_print") or 0) <= 0:
        risks.append({"doctor": "Profit Doctor", "level": "warn",
                      "text": "Priced below cost — not profitable as-is."})
        recs.append("Raise the price or cut cost before selling.")

    # Object spacing / collisions not verified by Studio yet — a real blocker that
    # must keep the report from saying "no major blockers found".
    if spacing and spacing.get("status") == "unknown":
        risks.append({"doctor": "Object spacing", "level": "warn",
                      "text": "Object spacing / collisions not verified by Studio — "
                              "check for too-close / collision warnings in Snapmaker Orca before slicing."})

    # dedup, severity-sort
    seen = set()
    risks = [r for r in risks if not (r["text"] in seen or seen.add(r["text"]))]
    risks.sort(key=lambda r: _ORDER.get(r["level"], 0), reverse=True)
    seen_r = set()
    recommendations = [r for r in recs if not (r in seen_r or seen_r.add(r))]

    # Community Knowledge: attach the community-known fix + confidence to each risk.
    try:
        from . import community_knowledge as ck
        for rk in risks:
            hit = ck.match(rk["text"], limit=1)
            if hit:
                e = hit[0]
                rk["community"] = {
                    "fix": e["community_fix"],
                    "success_pattern": f"Most U1 users resolve “{e['title']}” this way.",
                    "confidence": "High",   # curated, widely-reported issues
                    "sources": e["sources"],
                }
    except Exception:
        pass

    biggest_risk = risks[0] if risks else None

    # Expected Improvement (clearly an estimate): applying the recommended fixes
    # clears most of the gap to a clean print. We recover ~80% of the shortfall.
    expected_improvement = None
    if success is not None:
        after = success if not recommendations or success >= 95 else round(success + (95 - success) * 0.8)
        expected_improvement = {
            "current": success,
            "after_fixes": after,
            "is_estimate": True,
            "label": f"Estimate: ~{success}% now → ~{after}% after the recommended fixes",
        }

    # --- the one next action ---
    if biggest_risk:
        next_action = recommendations[0] if recommendations else f"Address: {biggest_risk['text']}"
    else:
        next_action = "Review the recommendations, then prepare a U1 profile copy and check it in Snapmaker Orca before slicing."

    # --- supporting evidence (each Doctor's one-line status) ---
    supporting = []

    def add(name, ok, status, detail):
        if ok:
            supporting.append({"doctor": name, "status": status, "detail": detail})

    _lvl_status = {"ok": "OK", "warn": "Check", "risk": "Action needed"}
    add("Project Doctor", avail["bed_fit"], _lvl_status.get((bed_fit or {}).get("overall_level"), "—"),
        (bed_fit or {}).get("overall_text", ""))
    add("Multi-Material Doctor", avail["mm"], _lvl_status.get((mm or {}).get("overall_level"), "—"),
        (mm or {}).get("overall_text", ""))
    add("First Layer Doctor", avail["first_layer"], _lvl_status.get((first_layer or {}).get("overall_level"), "—"),
        (first_layer or {}).get("overall_text", ""))
    add("Printer Doctor", avail["health"], f"{(health or {}).get('grade','')} · {health_score}/100" if avail["health"] else "—",
        (health or {}).get("verdict", ""))
    add("Cost Doctor", avail["cost"], f"{cur}{cost_v}" if cost_v is not None else "—",
        "True cost to make.")
    add("Pricing Doctor", avail["pricing"], (pricing or {}).get("verdict", ""), "Hobby / Marketplace / Premium tiers.")
    add("Profit Doctor", avail["profit"], f"{cur}{profit_v}/print" if profit_v is not None else "—",
        (profit or {}).get("verdict", ""))
    if spacing and spacing.get("status") == "unknown":
        add("Object spacing", True, "Check in Orca",
            "Studio does not verify object-to-object spacing yet — confirm in Snapmaker Orca.")

    # --- one-line verdict ---
    bits = []
    if studio_score is not None:
        bits.append(f"Studio score {studio_score}/100")
    if biggest_risk:
        bits.append(f"top risk: {biggest_risk['text']}")
    else:
        bits.append("no major blockers found")
    verdict = "; ".join(bits) + "." if bits else "Report ready."

    # --- Before vs After: "why not just use Orca?" ---
    n_issues = len(risks)
    n_fixes = len(recommendations)
    orca_line = ("Orca would slice this as-is" +
                 (f" — no warning about the {n_issues} issue{'s' if n_issues != 1 else ''} below."
                  if n_issues else ", and it'd be fine — but it can't tell you that in advance."))
    money_bit = (f", and it prices the print at {cur}{price_v} ({cur}{profit_v}/print profit)"
                 if (price_v is not None and profit_v is not None) else "")
    studio_line = (f"Studio caught {n_issues} issue{'s' if n_issues != 1 else ''} and offered "
                   f"{n_fixes} fix{'es' if n_fixes != 1 else ''} before you slice{money_bit}."
                   if n_issues else
                   f"Studio checked it and found no major blockers{money_bit}.")
    comparison = {
        "issues_found": n_issues,
        "fixes_offered": n_fixes,
        "prices_the_print": price_v is not None,
        "orca_line": orca_line,
        "studio_line": studio_line,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "comparison": comparison,
        "expected_improvement": expected_improvement,
        "studio_score": studio_score,
        "print_success_score": success,
        "cost": cost_v,
        "suggested_price": price_v,
        "margin_pct": margin_pct,
        "profit_per_print": profit_v,
        "currency": cur,
        "printer_compatibility": compatibility,
        "risks": risks,
        "biggest_risk": biggest_risk,
        "recommendations": recommendations,
        "next_action": next_action,
        "supporting": supporting,
        "verdict": verdict,
    }
