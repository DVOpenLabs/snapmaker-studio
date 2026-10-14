# Snapmaker Studio — External Validation Kit

> **Historical — written before the Innovation Fund entry was submitted on 24 June 2026.** Kept for the reasoning, not as a description of the project's current state. Current state: [docs/SUBMISSION_STATUS.md](../SUBMISSION_STATUS.md) and [docs/innovation-fund/PHASE1_POSITION.md](../innovation-fund/PHASE1_POSITION.md).

> **HISTORICAL — describes the v0.4.0-beta.1 RC era; not the current release.** In particular, 'read-only printer access / no printer control' was true then; the current Printer Hub provides monitoring plus user-confirmed controls (never auto-start). Current state: [`../TRUST_STATUS.md`](../TRUST_STATUS.md) · [`../RELEASE_METADATA.md`](../RELEASE_METADATA.md).

## 1. Lightweight tester feedback form
Keep it to 7 questions — under 3 minutes. (Host on a Google Form / Tally; questions
below are the source of truth.)

1. What U1 experience do you have? *(New · Some · Experienced)*
2. After the demo / first use, could you answer "what is at risk, what it costs, what
   to sell it for"? *(Yes, instantly · Yes, with a look · No)*
3. Did the **Studio Intelligence Report** make sense at a glance? *(1–5)*
4. Was a flagged **risk + community fix** something you'd actually trust/act on? *(1–5)*
5. Did anything feel broken, confusing, or fake? *(free text)*
6. Would you use Studio before opening Orca? *(Yes · No · Maybe — why?)*
7. One thing to add or change before you'd rely on it? *(free text)*

Optional: NPS — "How likely to recommend Studio to another U1 owner?" *(0–10)*.

## 2. Where to capture feedback in-app (capture points)
Lowest-effort, highest-signal moments — all surface the existing toast/store, no
new major capability:
- **After the Demo Report renders** (Dashboard) — the "aha" moment; a small
  "Was this useful? 👍/👎 + comment" affordance under the report.
- **After a real model's Intelligence Report** (Design Insights) — same affordance.
- **Settings → About** — a persistent "Send feedback" link to the form.
- **First-run / onboarding end** — one-tap "How was setup?".
> Implementation note (post-freeze): a single `<FeedbackButton>` posting to the
> form URL covers all four; no backend needed. Not built during feature freeze.

## 3. User Validation Report — template
Fill this once tester responses are in.

```
# User Validation Report — <date>
Testers: <n>  (New <n> · Some <n> · Experienced <n>)

## Headline
- Could answer the 3 questions unaided: <x>/<n> (<%>)
- Report-clarity (Q3) mean: <x.x>/5
- Community-fix trust (Q4) mean: <x.x>/5
- Would use before Orca (Q6): <x>/<n>
- NPS: <score>

## What worked (verbatim quotes)
- "<quote>" — <tester role>

## Friction / confusion (verbatim)
- "<quote>" — <tester role>   -> action: <fix or backlog>

## Demo-breaking issues found
- <none / list>

## Top requested change
- <item>  (frequency <n>)

## Conclusion
<1–2 lines: does it validate the value prop? submit-ready?>
```

## 4. Real user testimonials
> Add verbatim, attributed quotes here as testers respond. Keep only **real**
> quotes — never fabricate. Format: quote — name/handle, U1 experience level, date.

- _(pending tester round)_

---
This kit is process + templates only — no fabricated data, no new app features.
