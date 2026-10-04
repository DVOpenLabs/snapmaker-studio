# The public listing is two months out of date — what was done

> **Status note, 2026-10-04.** Written 2026-08-23 for a different evaluation timeline. The listing also still links
> the project by its old handle; see [LISTING_URL_REQUEST.md](LISTING_URL_REQUEST.md).

**Investigated and acted on 2026-08-23.**

## The problem

Snapmaker Studio's card on <https://www.snapmaker.com/innovation-fund> shows:

> **snapmaker-studio** — by Kunal Khurana
> *"Free local pre-print checker for U1. Flags model defects and risky settings up
> front, before you waste filament."*
> Category: Workflow · View on GitHub →

Both the text **and the cover image** come from the entry submitted on 24 June.
The image is the old banner reading *"The workflow platform for modern 3D
printing — Understand · Validate · Prepare · Monitor"*.

Nothing there is false. It is simply two months behind: it predates the
project-to-printer preflight, the fidelity audit, the fix ledger, colour planning
beyond four toolheads, the ecosystem recommender, the installed-build acceptance
harness, and the read-only verification against a real U1. A committee scoring the
card scores the June product.

## Can an entry be updated?

Investigated in this order:

| Route | Result |
|---|---|
| Project editing UI on the fund page | **Does not exist.** The page offers only the submission form. Its own text says a browsing-and-voting system "will be updated in the next month", so even the public project pages are not built yet. |
| Logged-in account / dashboard | **None.** The entry was taken by a Formspree form, not an account system. There is nothing to log into. |
| Re-submitting the form with new text | **Rejected.** That creates a duplicate entry, which is worse than a stale one. |
| The submission confirmation email | **This is the route.** The confirmation from community@snapmaker.com on 29 June says: *"Please feel free to contact us if you have any questions in the meantime."* That is a documented, invited channel to the people who own the listing. |
| Snapmaker forum / Discord / Lark | Real channels, but not the owners of the fund listing. Wrong door for this specific request. |

## What was done

A concise, factual reply was prepared on the original confirmation thread to
community@snapmaker.com. It:

- asks the one question — can a listing be refreshed before evaluation closes;
- gives a drop-in replacement description of the same length;
- links a replacement 640×360 card at
  [`docs/brand/innovation-fund-card.png`](../brand/innovation-fund-card.png);
- lists what shipped after 24 June, factually and without adjectives;
- links the current release and the judge overview;
- states explicitly that the form has **not** been re-submitted, to avoid a
  duplicate entry.

It asks for nothing else. No votes, no stars, no consideration, no favours.

**Status: drafted in the maintainer's mailbox, not sent.** Sending mail on the
maintainer's behalf was refused by this environment's safety policy, which is
working as intended — the message goes out under their name and their address, to
the people judging their entry. The draft sits in the thread ready to send.

## Why this is worth doing at all

Of the five risks in [PHASE1_POSITION.md](PHASE1_POSITION.md), this is the only
one that is pure signal loss rather than a real gap. The work exists; the
committee's own page describes something else. Correcting it costs one email.
