# Snapmaker Studio — Demo Video (60–90s)

Launch/teaser cut. One screen-recording of the real app + a closing roadmap
card. Plain, confident VO; no music bed louder than the voice. Target 75s.

## Logline
"3D printing workflows are fragmented. Snapmaker Studio prepares any design
for the U1 — and flags likely print risks before slicing."

## Shot list

| Time | On screen | Voiceover | Capture |
|---|---|---|---|
| **0–10s** | A Bambu/Orca file opened in Snapmaker Orca showing the "Customized Preset" / "newer version" warnings (the failure). | "3D printing workflows are fragmented. Your files get trapped between slicers and printers." | Screen-record Orca loading a foreign file with warnings (the before-state). |
| **10–25s** | Open Snapmaker Studio. Drag **example.3mf** onto the drop zone. Doctor auto-runs; shows verdict + issues. | "Open Snapmaker Studio. Drop in any file. The Doctor checks it instantly — and tells you exactly what's wrong." | Studio: Dashboard -> drag-drop -> LiveWorkspace Doctor result. |
| **25–45s** | Click **Prepare U1 copy**. Loading -> green "U1 profile copy saved" with output path + "Structure validated". | "One click. Studio prepares a U1 profile copy — then shows exactly what stayed the same, what it changed, and what it could not check." | Studio: convert action -> success state. |
| **45–60s** | Open the prepared `example_SnapmakerU1.3mf` in Snapmaker Orca; review layout, supports & colours. | "Open the prepared copy in Snapmaker Orca — review layout, supports and colours before slicing." | Screen-record Orca loading the prepared copy (the after-state). |
| **60–90s** | Slow pan over roadmap cards: Understand . Validate . Prepare . Monitor -> "more ecosystems, more printers, plugins." End on logo + tagline. | "This is the start. We're building the workflow platform for modern 3D printing — understand, validate, and prepare any design for slicing." | Title cards from ROADMAP.md pillars + logo. |

## beta.3 additions (optional beats)
For a judge/Innovation-Fund cut, add two short beats after the convert success:
- **Navigation (≈5s):** pan the sidebar — every Doctor directly reachable; "Why
  Studio?" now in the secondary/help group. VO: "Every Doctor, one click away."
- **Plate Color Remap (≈8s):** open a generic multicolor 3MF (`example.3mf` / a
  real-world multicolor fixture — never a paid model name), pick a plate and a
  from→to colour, show the "What will change / What will stay the same" cards and
  the "Create safe copy — original stays unchanged" button, then the "Verified
  safe copy created" proof. VO: "Change one plate's colour — gold details and
  other plates stay exactly as they are, and your original file is never touched."

## End card
- Project brand assets: `docs/brand/` (mark `logo.svg`, banner `hero.svg`,
  share `social-preview.svg`). Dark background (`#0B0F19`).
- Show the flow once on screen: **Understand → Validate → Prepare → Monitor**
  (Validate highlighted — it's always on).
- Tagline: **"The workflow platform for modern 3D printing."**
- Sub: _Understand any design, catch risks before slicing, prepare it for the U1._ ·
  "Local-first · Open source · github.com/DVOpenLabs/snapmaker-studio"

## Capture notes
- Use real files (example.3mf -> example_SnapmakerU1.3mf) — the before/after is
  the whole pitch; do not fake it.
- Record at 1440p, light theme for the app (high contrast for screen capture).
- Keep cursor movements deliberate; pause ~1s on the green success state and on
  the Orca review beat.
- No narration over the Orca review beat — let it land silently for ~1.5s.

## Final narration (read for ~75s; ~150 wpm)
1. (0–10) "3D printing workflows are fragmented. Your files get trapped between
   slicers and printers."
2. (10–25) "Open Snapmaker Studio. Drop in any file. The Doctor checks it
   instantly — and tells you exactly what's wrong."
3. (25–45) "One click. Studio prepares a U1 profile copy — then shows you exactly
   what stayed the same, what it changed, and what it couldn't check."
4. (45–60) "Open it in Snapmaker Orca — review layout, supports and colours before slicing."
5. (60–90) "This is the start. We're building the unified platform for 3D
   printing workflows — the operating system for multi-material printing."

## Storyboard (frames)
| # | Frame | Duration | Transition |
|---|---|---|---|
| A | Orca with warning dialog over a Bambu file (the pain) | 0:00–0:10 | hard cut |
| B | Studio Dashboard; file dragged onto hero drop zone | 0:10–0:18 | cut on drop |
| C | LiveWorkspace: Doctor result (verdict + issues) | 0:18–0:25 | quick push-in |
| D | Cursor clicks **Prepare U1 copy**; progress | 0:25–0:35 | cut |
| E | Green "U1 profile copy saved" + path + Structure validated | 0:35–0:45 | hold 1s |
| F | Snapmaker Orca opens the prepared copy — review before slicing | 0:45–0:60 | silent 1.5s beat |
| G | Roadmap pillar cards animate in | 0:60–0:78 | slow pan |
| H | Logo + tagline end card | 0:78–0:90 | fade |

## Recording guide
- **Tools:** OBS (or built-in recorder) at 1920×1080/60; cursor highlight on.
- **App:** installed `0.4.0-beta.5`, light theme, 1280×800 client area, no
  personal paths visible.
- **Takes:** record each beat separately (B–E in Studio, A+F in Orca) for clean
  edits; do 2–3 takes of the drag and the click.
- **Audio:** VO recorded separately, denoised; soft music bed −18 dB under VO;
  duck to −24 dB during the Orca review beat.
- **Edit:** assemble per storyboard; total 75s target (trim G if over 90s).
- **Export:** 1080p H.264 MP4 + a captioned variant (autoplay-muted social).

## Production checklist
- [ ] Real `example.3mf` ready; output deleted beforehand so the save is live.
- [ ] Orca pre-opened twice (before-file and after-file) for clean A/F takes.
- [ ] Brand end card built from `docs/brand/` + tagline.
- [ ] Captions written from the narration block.
- [ ] No personal/identifying info in any frame.
- [ ] Final length 60–90s; Orca review beat lands silent.
