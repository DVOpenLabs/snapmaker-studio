# Prepare-with-setup screenshots

Development build, not released software. Captured from the integ/phase2 branch of the pull request that adds the printer-setup flow. These features are not in the released v1.7.0; the footer in each image reads "v1.7.0" only because the version number has not been bumped on this branch.

Real UI (Vite dev server) against a real local backend process, with a synthetic loopback host (`tools/dev/phase2-prepare-mock.mjs`). Synthetic projects only. No printer, no real network host.

| Image | Shows | Captured at |
|---|---|---|
| `eight-slot-preserve.png` | eight logical slots bound directly to the four toolheads; Preserve creator settings; the engine reports it used the setup | a7633db |
| `recommended-setup-not-applied.png` | same setup with U1 starter settings; the engine reports the setup was read but not applied, and says why | a7633db |
| `stock-four-head.png` | a four-slot setup on four toolheads; Preserve; used | a7633db |
| `invalid-blocked.png` | a three-head setup: Prepare is blocked and nothing is written | a7633db |
| `failed-read.png` | the host read failed: Prepare and Review settings are paused | bcc43c3 |

Each image shows the selection line "Selected setup reported by ..." and the binding count "N of M slots are bound (X to feeder lanes, Y directly to toolheads)". `failed-read.png` has no selection line because no setup was read.

The eight-slot and three-head hosts are hypothetical variants served by the loopback mock, not captures of real hardware.
