# User evidence

**Measured 2026-10-04** from the GitHub API against the repository itself
(`DVOpenLabs/snapmaker-studio`). Every number is a measurement, not an estimate. Nothing
on this page is a testimonial: it separates *interest* (people looked), *external
reports* (people told us something) and *real-device or real-file outcomes* (a check on
hardware or a file Studio did not control).

The earlier version of this page was dated 2026-08-23 and said: 43 downloads, 1 star,
no issues ever opened, no outcome evidence. Those figures are superseded below.

## Interest

| Signal | Value (2026-10-04) | Source |
|---|---|---|
| Installer downloads, all releases | **155** (Windows 144, Linux `.deb` 11) | `repos/…/releases` asset counts, installer assets only |
| All release-asset downloads (incl. checksum files) | 179 across 54 releases | same |
| Unique cloners, last 14 days | **484** (2,003 clones) | `repos/…/traffic/clones` |
| Unique visitors, last 14 days | **180** (642 views) | `repos/…/traffic/views` |
| Stars / forks / watchers | 20 / 1 / 1 | repository metadata |
| Repository created | 2026-06-17 | repository metadata |

Clones include automated systems and our own CI; downloads include re-downloads and
testers. None of these numbers says anyone succeeded with Studio.

## External reports

| Report | Opened | What it was |
|---|---|---|
| #39 | 2026-09-27 | A community member asked for a SpoolEase integration, later tested it |
| #67 | 2026-10-03 | The same external user reported a failing prepare on a public model |

Two issues from one outside user. The other open and closed issues are maintainer work
items or automated notices.

Two further outside interactions concern how Studio *describes other projects*, which
is the ecosystem-registry part of the product:

| Interaction | What happened |
|---|---|
| Pull request #9 (merged 2026-09-23) | The maintainer of another Phase 1 project corrected their own entry in Studio's ecosystem registry, after Studio had invited a correction on their repository. |
| Issue #2 on the U1 Print Hub repository (closed) | Studio asked its maintainer to check how Studio describes that project; the maintainer replied that the entry was accurate. |

There are 44 pull requests: 43 from the maintainer and one (#9) from an outside
contributor.

## External validation since submission

Two checks against things Studio did not control have happened since the entry was
submitted, both prompted by the same outside user. They are bug reports and test results, not testimonials, and each records
what failed as well as what worked.

**#39 — SpoolEase (a community-requested integration)**

- A community member asked for the SpoolEase integration (issue #39); it shipped
  read-only in v1.3.0.
- Testing v1.3.0 on a real SpoolEase exposed two real defects: an address that is a
  private name (an FQDN on the user's own network) was refused as off-network, and the
  SpoolEase 0.7 firmware sends a longer spool list than Studio could read.
- The v1.3.1 release candidate connected to that user's physical SpoolEase: the
  security key was accepted, the SpoolEase 0.7 response parsed, **115 spools** were
  read and **35** had usable remaining weights.
- Status: **Initial real-device validation passed; detailed value spot-check
  pending.** Issue #39 stays open until the reporter confirms material, vendor, colour
  and remaining weight on a few known spools.

**#67 — a public MakerWorld model**

- An external user supplied a public model (the 10 mm "Universal Filament Snag
  Cutter" on MakerWorld) that Studio could not prepare.
- v1.3.0 showed only a generic "internal error". The real refusal was identified: the
  file carries per-object wall and support settings that Studio had not proved
  Snapmaker Orca acts on.
- Four native per-object settings — `wall_generator`, `wall_loops`, `support_type`,
  `support_style` — were verified against Snapmaker Orca's v2.4.0 source and are now
  kept, each only with a value Orca understands. Every other per-object setting is
  still refused rather than guessed at.
- The exact model now prepares through the frozen v1.3.1 release-candidate engine,
  validation passes, and the original file is byte-identical.
- This was an **older validator limitation, present since v0.9.0 — not a regression
  introduced by v1.3.** v1.3.0 made it harder to see; it did not cause it.

What this shows: one outside user found real defects in two separate reports, the
defects were reproduced and fixed, and the fixes were checked on that user's own device
or file. What it does not show: how often Studio works for people in general. One
reporter is not a rate, one SpoolEase is one device, and the SpoolEase value check
is not finished.

## How to re-measure

```bash
gh api repos/DVOpenLabs/snapmaker-studio
gh api repos/DVOpenLabs/snapmaker-studio/traffic/clones
gh api repos/DVOpenLabs/snapmaker-studio/traffic/views
gh api repos/DVOpenLabs/snapmaker-studio/releases --paginate
```

Traffic figures cover a rolling 14 days and need push access to read.
