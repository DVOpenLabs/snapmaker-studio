# Community post — prepared, not posted

> **Superseded in part (v1.1.0):** the draft below says stock firmware does not
> report the fitted nozzle. That is wrong — it does, and Studio reads it since
> v1.1.0. Correct that paragraph before posting anything from this draft.

## What already exists, checked before writing anything

Searched the Snapmaker Discourse forum (`forum.snapmaker.com`) via its search API
on **2026-08-23** for `snapmaker-studio`, for the maintainer's handle, and for
"pre-print checker". **No results.** The maintainer's mailbox contains no
Discourse notifications about a topic of their own, only replies to threads they
watch.

So: the project has an accepted, listed Innovation Fund entry, but **has never
been posted about in the community**. That is a genuine gap, verified today — not
an old to-do resurrected. It is also the only lever on the fund's 20% community
component that does not involve asking anyone for anything.

Two related facts worth holding together:

- The fund's page says the project **voting system is not built yet**. There is
  nothing to vote on, so there is no urgency to "campaign", and no honest way to.
- The repository has 1 star and has never had an issue opened. A post that reads
  as marketing will do more harm than the silence it replaces.

The post below therefore leads with the hardware bug, because that is the only
part of this project's story that a U1 owner has a personal reason to care about.

## Where it should go

`forum.snapmaker.com` → the U1 software/community category, as a normal project
thread. Not in a fund thread; the fund is not the audience.

## Status

**Not posted.** Posting to a public forum under the maintainer's identity is
theirs to do — it is their name on it. The text needs no editing to be usable.

---

## The post

**Title:** Snapmaker Studio — a local pre-print checker for the U1, and a bug your printer told me about

> I have been building a small open-source desktop app called Snapmaker Studio.
> It is not a slicer and never will be — Snapmaker Orca slices. Studio is the step
> before: it reads a project file, tells you what is likely to go wrong, compares
> the project against your actual printer, and prepares a corrected copy without
> touching your original.
>
> I want to lead with the part that might matter to you even if you never install
> it.
>
> **Your U1 reports which filaments are loaded, and my app was getting it wrong.**
> Studio was telling owners *"this printer does not report which filaments are
> loaded"*. It does. Stock firmware publishes loaded filament as parallel lists —
> types in one, colours in another, sub-types and vendors in others, plus a
> per-slot flag for whether a spool is actually there. I had been looking for a
> list of objects, found nothing, and reported that as the printer's silence
> instead of my own bug. When I finally pointed it at a real U1 it took about a
> minute to find. Fixed in the current build. If you are writing
> anything against the U1's Moonraker API, that shape may save you the same hour.
>
> The same session confirmed something I had only assumed: **stock firmware
> genuinely does not report which nozzle is fitted.** So Studio says "check this
> yourself" and explains what a mismatch would do, rather than pretending it
> knows. That is the rule the whole app runs on — when it cannot tell, it says
> so, and "not detected" never becomes "not supported".
>
> What it does today:
>
> - **Before you slice** — compares your project against the printer it can see:
>   how many materials it needs against how many toolheads you have and which
>   spools are loaded, the objects against your printer's own reported bed, and
>   the features a prepared copy relies on against your firmware's own object
>   list.
> - **Names the actual problem** — not "out of bounds", but which object, which
>   edge, how many millimetres, and why; then offers to move it in a new copy.
> - **Shows what survived** — after preparing a copy it lists what stayed
>   byte-for-byte identical, what changed and why, what it could not carry over,
>   and separately what it could not check at all. It only claims nothing was lost
>   when it can prove that for your file.
> - **Six colours on four toolheads** — separates the colours that share layers
>   and each need a toolhead from the ones that appear higher up and could be
>   swaps, and says plainly when it cannot tell.
> - **Points at other people's tools** — if your file would be better served by
>   FOrcaSlicer, u1hub, the U1 toolkit or one of the converters, Studio says so
>   and links them. I would rather you use the right tool than mine.
>
> Everything is local. No account, no cloud, nothing uploaded off your own
> network, MIT licensed.
> Your original files are never modified. Studio never starts a print.
>
> A 66-second recording of it working, the Windows installer with its SHA256, and
> the full verification record (including the 21 checks that run against the
> installer itself, and the 13 read-only checks against a real U1) are here:
>
> https://github.com/DeadlyVirusIn/snapmaker-studio
>
> It is a beta and the installer is not code-signed yet, so Windows will warn you
> about an unknown publisher — the hash is published, please check it.
>
> **The one thing I actually want:** open one model you were going to print
> anyway, and tell me what Studio got wrong. There is an issue template called
> "Studio got this wrong" that asks exactly two things — what Studio said, and
> what was actually true. It has never had a bug report from anyone but me, and
> that is the least useful kind.

---

## Rules this post follows

- No request for stars, votes or Innovation Fund consideration. The fund is not
  mentioned at all.
- Leads with something useful to the reader (the firmware shape), not with the
  product.
- Names competing and complementary projects by name, positively.
- States the beta status and the unsigned installer up front rather than burying
  them.
- Asks for exactly one thing: bug reports.
