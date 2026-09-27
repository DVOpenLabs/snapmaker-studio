# What to Test First

> First written during the beta; every screen named below still exists in v1.1.0, the current release. For what is new in v1.1.0 see the [README](../README.md#whats-new-in-v110). Current release + checksums: [`RELEASE_METADATA.md`](RELEASE_METADATA.md).

**Quick tour — try these first:**
1. **Compatibility** (sidebar) → **Source Check** tab → pick any STL/3MF → see the detected slicer, what Studio
   can read, and the safe next step.
2. **Find Models** → click an approved site → it opens in the locked Studio Model Browser;
   download a file, then **Open downloaded file** → Project Doctor.
3. **Colors & Materials** (sidebar) → **Plate Color Remap** → a multicolor 3MF → pick a plate + a from/to colour → the **2D
   plate preview** shows what changes and what stays protected.
4. **Print Quality** (sidebar) → pick a symptom → **Add your file** → the "What Studio found
   in your file" evidence panel.
5. **Printer Hub** → connect a U1 (or see the clear offline state) → monitor, then the
   confirmed control card (pause/cancel/start, upload gcode, emergency stop).

---


Three short beginner paths through Snapmaker Studio. Everything runs locally;
nothing is uploaded. Originals are never modified, and findings are advisory
readiness estimates, not guarantees of print success.

> Independent open-source project — not affiliated with or endorsed by Snapmaker.

## Path 1 — Beginner U1 owner

You have a U1 and a 3MF file and want to know if it's ready before slicing.

Steps:

1. Open Snapmaker Studio.
2. Open your U1 3MF file from the Dashboard.
3. Let Studio read the real geometry and show the design-health summary.
4. Run the Compatibility Doctor for a readiness estimate against the U1.
5. Read each finding — what was found, why it matters, what to try.

Expected outcome: a plain-language readiness estimate with a short list of likely
risks and concrete next steps, so you know what (if anything) to fix before
opening the slicer.

## Path 2 — Multicolor file user

You have a multicolor or multi-plate file and want the colors/plates to come out
clean.

Steps:

1. Open Snapmaker Studio and open your multicolor 3MF.
2. Review the detected materials, colors, and plate counts.
3. Open Plate Color Remap.
4. Apply the suggested remap and review the before/after.
5. Prepare a U1 profile copy (your original stays untouched).
6. Click **Open in Snapmaker Orca** to hand the prepared copy to the slicer (or
   **Copy path** and open it yourself). If Orca isn't installed, use **Install
   Snapmaker Orca**.

Expected outcome: a tidied color/plate mapping and a prepared U1 profile copy —
review in Orca before slicing — with the original file unchanged, handed off to
Snapmaker Orca to slice. Studio never slices or controls Orca.

## Path 3 — Failed print user

A print failed and you want to figure out why before trying again.

Steps:

1. Open Snapmaker Studio and open the file that failed.
2. Open the Print Quality Doctor.
3. Follow the "Fails even with supports" path if supports didn't help.
4. Switch to known-good troubleshooting mode and compare against a print that
   worked.
5. Change one thing at a time based on the guidance, then re-check.

Expected outcome: a narrowed-down list of likely causes and a clear next change to
try — instead of guessing and wasting more filament.

See also: [JUDGE_OVERVIEW.md](JUDGE_OVERVIEW.md),
[JUDGE_DEMO.md](JUDGE_DEMO.md),
[windows-install.md](windows-install.md).
