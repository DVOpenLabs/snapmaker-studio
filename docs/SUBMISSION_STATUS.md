# Innovation Fund — submission status

> Independent open-source project — not affiliated with or endorsed by Snapmaker.
> "Snapmaker" is a trademark of its respective owner.

**Phase 1 entry is submitted and listed.** The current description of the project
is [INNOVATION_FUND.md](INNOVATION_FUND.md); the competitive position and what is
worth doing before evaluation closes is
[innovation-fund/PHASE1_POSITION.md](innovation-fund/PHASE1_POSITION.md). This
page is the status record only.

## Current build

| | |
|---|---|
| Version | **v1.0.0** — the current stable release |
| Installer, size, SHA256 | [RELEASE_METADATA.md](RELEASE_METADATA.md) — canonical |
| Verification state | [TRUST_STATUS.md](TRUST_STATUS.md) — **ACCEPTED** |
| Release | <https://github.com/DVOpenLabs/snapmaker-studio/releases/tag/v1.0.0> |

The installer is not code-signed — verify the SHA256 before installing. See
[windows-install.md](windows-install.md) and
[CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md).

## Submission state — settled

**Submitted, confirmed, and publicly listed.** This is not an open question and
must not be reopened.

| | |
|---|---|
| Submitted | 24 June 2026, 20:53, via the fund's form |
| Confirmed | 29 June 2026 by community@snapmaker.com |
| Listed as | "snapmaker-studio — by Kunal Khurana", category *Workflow* |
| Where | <https://www.snapmaker.com/innovation-fund>, among 41 projects in the running |
| Evaluation closes | 22 September 2026 |
| Winners announced | 30 September 2026 — 20 of the 41 |

The exact text submitted is preserved in
[innovation-fund/SUBMITTED_ENTRY.md](innovation-fund/SUBMITTED_ENTRY.md).

**Do not submit the form again.** A second entry would be a duplicate.

An earlier version of this page speculated that v0.4.0-beta.16.2 might have been a
"frozen submission record" and that nothing recorded whether a form was ever sent.
That is now answered: the entry was sent on 24 June, which is beta.16-era, so
beta.16.2 was indeed roughly the build the committee was told about.

The listing — its description *and* its cover image — still describes that June
build. What was done about that is in
[innovation-fund/LISTING_UPDATE.md](innovation-fund/LISTING_UPDATE.md).

## Hardware verification

**v0.7.0, 2026-08-24 — read-only, 39/39.** Printer discovered, 196 Klipper
objects enumerated, the printer's own 271 × 335 × 281 mm bed used, four loaded
filaments read with colour and sub-type, the fitted nozzle correctly reported as
unknown rather than unsupported, the project's materials compared both against
toolhead count and against what is loaded, and a sliced job joined to the live
machine: the tool it needs exists, the slot it prints from is loaded, and the
material matches. Nothing was started, uploaded or queued; no temperature, motion,
homing, pause, resume, cancel, emergency-stop or configuration call was made.
Record: [TRUST_STATUS.md](TRUST_STATUS.md) · raw evidence
[internal/hardware-0.7.0.json](internal/hardware-0.7.0.json).

**v0.6.2, 2026-08-24 — read-only, 39/39**: the same checks a release earlier, and
the run that found a community-firmware probe reporting a stock printer as running
Extended Firmware — fixed in that release. Recorded in
[internal/hardware-0.6.2.json](internal/hardware-0.6.2.json).

**v0.6.0, 2026-08-23 — read-only, 20/20**, and **v0.4.0, 2026-08-23 — read-only,
20/20**: the same read-only checks against the same machine, recorded per release
in [internal/hardware-0.6.0.json](internal/hardware-0.6.0.json) and
[internal/hardware-0.4.0.json](internal/hardware-0.4.0.json). Each release's
numbers stay with that release; none of them is restated when a later one ships.

**Earlier, 2026-06-24, firmware 1.4.1.6 —** Printer Hub's confirmed actions were
exercised on hardware under supervision: connect, monitor, upload without starting
a print, start, pause, resume and cancel. Emergency stop is code-verified only
(`M112` via `/printer/gcode/script`; the `/printer/emergency_stop` endpoint 404s on
the U1's Moonraker). It has deliberately never been fired, because firing it forces
a Klipper shutdown and firmware restart. Record:
[PRINTER_HUB_VERIFICATION.md](PRINTER_HUB_VERIFICATION.md).

## Known limitations

- The Windows installer is **unsigned**; SmartScreen will warn. Verify the SHA256.
- Emergency stop has never been fired on hardware.
- Studio **does not slice** — it hands a prepared copy to Snapmaker Orca.
- Studio **never takes autonomous control**. Printer Hub actions are local and
  each requires an explicit confirmation; Studio never auto-starts a print.
- Studio is advisory. It does not guarantee a successful print.

## Judge-facing documents

- [innovation-fund/JUDGE_OVERVIEW.md](innovation-fund/JUDGE_OVERVIEW.md) — five
  minutes, from a standing start
- [innovation-fund/JUDGE_WALKTHROUGH.md](innovation-fund/JUDGE_WALKTHROUGH.md) —
  reproduce every claim yourself
- [innovation-fund/DEMO_SCRIPT_90_SECONDS.md](innovation-fund/DEMO_SCRIPT_90_SECONDS.md)
  — the recorded demo, beat by beat
- [media/snapmaker-studio-demo.mp4](media/snapmaker-studio-demo.mp4) — 66 seconds
  of the running application
