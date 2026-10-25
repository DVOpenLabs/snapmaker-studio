# 90-second demo script

**Recorded from the installed beta.24 build on 2026-08-23.** The recording is
[`docs/media/snapmaker-studio-demo.mp4`](../media/snapmaker-studio-demo.mp4) — 71
seconds, 1578×944, every frame the running application. It was produced by driving
the beats below through the real window (`tools/demo/record.ps1`), on the sample
project committed at
[`examples/demo_u1_showcase.3mf`](../../examples/demo_u1_showcase.3mf). Nothing
here is staged, and nothing is a mock-up.

**The single idea:** *Snapmaker Orca says "out of bounds". Studio says which
object, which edge, how many millimetres, why — fixes it in a new copy, proves
what survived, and checks it against your actual printer.*

**Known limitation (v1.7.0 release candidate).** The sample project is a minimal synthetic file written by
Studio's self-check: its `[Content_Types].xml` and `_rels/.rels` parts are present but empty stubs
(`<Types/>` and `<Relationships/>`), so nothing points a standard 3MF reader at `3D/3dmodel.model`, and its
`model_settings.config` lists objects 2 to 4 that the model does not contain. In an isolated test, Snapmaker Orca
2.4.1 answered "Loading of model file failed" for the unprepared sample; it loaded a differently built painted
project that has a real relationship file. Which of these differences Orca rejects was **not isolated**, and the
cause is not confirmed. Studio itself reads the sample fine. The line "Orca says out of bounds" is the story of a
real downloaded project, not something this sample shows in Orca.

---

## 1. The beats

### 0:00 – 0:10 · The problem, in the user's words
**On screen:** Studio's own first frame (the recording starts in Studio and does not show Snapmaker Orca).
This beat is narration only. Do not open `examples/demo_u1_showcase.3mf` in Orca on camera: Snapmaker Orca 2.4.1
refuses that file, with a load failure rather than an out-of-bounds message (see the known limitation above).

> I downloaded a model. I don't know if it's right for my U1 — and my slicer just
> says out of bounds.

### 0:10 – 0:25 · Studio reads the file
**On screen:** Studio → Compatibility, project open, the Object placement card.

**Real output:**
> **Object placement** — 1 object is outside the U1's printable area.
> Object 1 · 10 × 10 × 10 mm — Hangs 45.0 mm past the right edge.

> The part is tiny. It isn't too big — it's in the wrong place, because this
> project was made for a 350 millimetre bed and still carries that printer's
> coordinates.

### 0:25 – 0:40 · The fix, and what it protects
**On screen:** click **Move onto the plate (saves a copy)**.

**Real output:**
> 1 object(s) moved onto the U1 plate in a new copy — `demo_u1_showcase_placed_U1.3mf`.
> Your original file was not changed.
> Every object shifted by X −174.5 mm, Y −44.0 mm. Layout, rotation, scale and
> height are unchanged.

### 0:40 – 0:52 · Prepare, and every change accounted for
**On screen:** **Prepare U1 copy** → the change list.

> Studio corrects only what stops Snapmaker Orca behaving properly on a U1 — and
> shows every change with its old value.

**Real output, visible in the list:**
> `brim_type: auto_brim → no_brim` · `exclude_object: 0 → 1` ·
> `default_print_profile: → 0.12 Standard @Snapmaker U1 (0.4 nozzle)`

### 0:52 – 1:05 · Proof, not a promise
**On screen:** the **What survived preparing this copy** card.

**Real output:**
> 13 kept · 2 changed · 1 not carried over
> **What Studio could not carry over (1)** — Sliced output from the original
> printer. Why: these toolpaths were generated for the original printer, so
> Snapmaker Orca must slice again for the U1.

> Every other converter says "converted". This says what that cost — and lists
> anything it could not check, instead of assuming it was fine.

### 1:05 – 1:15 · The way back
**On screen:** **Changes Studio made**, both entries, and the return control.

**Real output:**
> 1. Prepared a U1 copy — 63 changes · structure validated
> 2. Moved the objects onto the plate — 1 change · structure validated
> **Return to the original** — your original was never modified. Going back to it
> just points Studio at the untouched file; the copy stays on disk.

### 1:15 – 1:25 · This project, on this printer
**On screen:** the **Before you slice** card, scrolled to the nozzle check.

**Real output:**
> **Nozzle size — check this yourself** · STUDIO CAN'T TELL
> Printing with a different nozzle than the project was made for changes line
> width and can ruin fine detail — and Studio has no way to see which one is
> installed.
> *"Studio can't tell" means Studio has no way to read that from your printer —
> not that your printer can't do it.*

> That last line is the whole product in one sentence.

### 1:25 – 1:30 · The close
**On screen:** the **Best tool for this project** panel, then the terminal.

```
$ u1convert selfcheck
21/21 checks passed
```

> **Snapmaker Studio**
> The Intelligence Layer for Open 3D Printing
> Understand → Diagnose → Fix → Validate → Print
>
> Studio doesn't slice. Snapmaker Orca does.

---

## 2. The exact click path

Recorded and verified. Total: one file open, three clicks, two scrolls.

1. Launch Studio. Sidebar → **More tools** → **Compatibility**.
2. **Open a 3MF project** → choose `examples/demo_u1_showcase.3mf`.
   *Frame: `placement_and_preflight.jpg`.*
3. Click **Move onto the plate (saves a copy)**.
   *Frame: `placement_fixed.jpg`.*
4. Scroll down to the preparation panel (about 10 wheel ticks).
   *Frame: `preflight_unknowns.jpg` — the nozzle unknown and the footnote.*
5. Leave **Preserve creator settings** selected. Click **Prepare U1 copy**.
6. Scroll down about 20 ticks to the fidelity and ledger cards.
   *Frame: `fidelity_and_ledger.jpg`.*
7. Sidebar → **Colors & Materials** for the colour beat.
   *Frame: `colour_plan.jpg`.*
8. Terminal: `cd backend && u1convert selfcheck`.

**Reset between takes:** delete `examples/demo_u1_showcase_placed_U1.3mf`,
`examples/demo_u1_showcase_SnapmakerU1.3mf` and `examples/demo_u1_showcase.orig.3mf`.
The sample itself is never modified, so nothing else needs restoring.

---

## 3. Recording setup

- **Display:** 1920 × 1200, 100% scaling, single monitor.
- **Theme:** either. Dark is Studio's default and matches the brand; light reads
  better on a projector. Do not switch mid-take.
- **Window:** maximised. The sidebar must be visible — it carries the product's
  information architecture.
- **Privacy, per the project's own rules:** the app shows file *names*, not paths,
  so a clean recording needs only that no other window, no real printer IP and no
  personal folder appears. Clear the Recent list if it holds private model names.
- **Capture:** OBS Studio, Display Capture, 1920 × 1200 at 60 fps, MP4. No cursor
  highlighting effects.

## 4. Rules for the edit

- **Do not cut inside a claim.** The viewer has to see the result follow the
  click, or the demo is just assertions with pictures.
- **Do not speed up the fix.** It is genuinely fast; real time is the point.
- **Silence over the 1:15 beat.** The refusal is the strongest moment in the
  video and should land without music.
- **Never add a frame the app cannot produce.** If a beat does not exist on
  screen, cut the beat, not the honesty.

---

## 5. Final caption card

```
Snapmaker Studio
The Intelligence Layer for Open 3D Printing

Understand → Diagnose → Fix → Validate → Print

Local-first · MIT · Studio doesn't slice — Snapmaker Orca does
github.com/DeadlyVirusIn/snapmaker-studio
```
