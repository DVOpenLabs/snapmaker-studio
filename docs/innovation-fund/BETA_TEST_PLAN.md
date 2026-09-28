# Beta test plan — asking for the smallest useful thing

> **Current state, recorded 2026-09-28.** Everything below was written on 2026-08-23 and is kept as written. Since then, Snapmaker's Innovation Fund community vote was observed live on 23 September 2026 (issue #18, opened by the page watcher and closed by the maintainer that day); the fund page says voting runs 22–30 September 2026. The ballot is Snapmaker's official ballot, linked from the fund page (`snapmaker.com/innovation-fund`) and hosted externally: email-verified, five votes per voter, with provisional results due 30 September and the confirmed list on 15 October. The rule below stands: this project does not ask for votes, in any channel; naming the fund page once, factually, remains the limit. The page watcher (`tools/watch/innovation_fund.py`) has done its job and no longer runs on a schedule.

**Written 2026-08-23.** Studio has been downloaded 43 times and has never received
a single report from anyone but its author. That is the project's largest gap, and
it is not a gap in the software.

The correction this plan makes to earlier thinking: engagement was never
*attempted*. It was assumed to be unwinnable in the time available, which confused
buying attention — which is off the table — with earning it, which nobody had
tried. There has never been a post about the project, never an issue template
inviting a report, and Discussions were switched off until today.

## The ask, in full

> Download beta.24. Open one model you were going to print anyway.
> Tell us what Studio got wrong.

That is the entire request. Not "please evaluate my application". Not "please try
every feature". One model, one answer, two minutes.

**It is deliberately easier to report a failure than a success.** Praise is
pleasant and useless; a wrong analysis is a bug report against the one claim the
whole project rests on.

## What counts as a useful report

In descending order of value:

1. **Studio said something untrue** — a false alarm, a missed problem, an "I can't
   tell" that it should have been able to tell, or a confident answer that was
   wrong.
2. **Studio changed something in the prepared copy it should not have** — the fix
   ledger records every change, so this is checkable.
3. **Studio could not read a real file** at all.
4. **A message that made no sense to you.** If a beginner cannot act on it, it has
   failed even when it is technically correct.
5. Crashes and install problems.

Notably absent: feature requests. They are welcome, but they are not what this
plan is asking for.

## What is now in place

| Channel | State |
|---|---|
| **"Studio got this wrong" issue form** | Added — `.github/ISSUE_TEMPLATE/studio-got-this-wrong.yml`. Two required fields: what Studio said, what was actually true. Everything else optional. |
| **Bug report template** | Rewritten for a desktop-app user. The old one asked for `pip show` output and a Python version, which no installer user has. |
| **GitHub Discussions** | **Enabled today.** Previously off, which meant a person with a one-line observation had no low-commitment place to put it. |
| **Issue template chooser** | Links Discussions and this plan, so the low-effort route is visible before the high-effort one. |
| **Community post** | Written — [COMMUNITY_POST.md](COMMUNITY_POST.md). Leads with a firmware finding useful to any U1 developer, not with the project. |
| **Ecosystem threads** | Four notes posted 2026-08-23 to FOrcaSlicer, u1hub, makerworld-to-snapmaker-u1 and snapmaker-u1-toolkit. Any maintainer correction is recorded in [USER_EVIDENCE.md](USER_EVIDENCE.md) as ecosystem feedback, explicitly not as customer testimony. |

## Where the people are

Assessed for fit, not for reach. A post in the wrong place is worse than no post.

| Venue | Fit | Note |
|---|---|---|
| **Snapmaker forum** (`forum.snapmaker.com`) | **Best.** U1 owners, active, project threads are normal there | Verified today that Studio has never been mentioned on it |
| **The four ecosystem issue threads** | Already open, and the audience is other maintainers — the people most likely to find a wrong analysis | Do not turn them into marketing; answer questions only |
| **Snapmaker Discord / Lark groups** | Good, but conversational — a link drop reads as spam without a person behind it | Only alongside participation |
| **Reddit (r/3Dprinting, U1 threads)** | Mixed. Self-promotion rules vary and are enforced | Only if the post is genuinely a technical finding |
| **MakerWorld / model sites** | Poor fit — audiences want models, not tools | Skip |

## Rules

- **No asking for stars.** Not once, not by implication.
- **No asking for votes**, now or when the fund's voting system launches.
- **No mass messaging.** No DMs to strangers, no mailing lists.
- **No posting the same text twice.** Each venue gets something written for it.
- **Lead with something useful to the reader**, not with the product.
- **State the beta status and the unsigned installer up front**, every time.
- **Answer every report**, including the ones that are user error — especially
  those, because a message a user could misread is a real defect.

## What success looks like before 22 September

Deliberately small, because inflated targets produce dishonest behaviour:

- **One external issue of any kind.** The project has never had one.
- **One "Studio got this wrong"** report. That would be the first external
  evidence in the project's history, and worth more than a hundred stars.
- **One maintainer reply** on an ecosystem thread.

If none of that arrives, the honest conclusion is that the project is not yet
discoverable, and that is what [USER_EVIDENCE.md](USER_EVIDENCE.md) will say.
