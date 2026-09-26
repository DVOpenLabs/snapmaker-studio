# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-09-26

**Two platforms, one release.**

### New in 1.0.0
(everything below shipped on `main` between v0.9.0 and this tag — nothing else did)

#### Added
- **Linux, as a `.deb`.** Ubuntu 22.04 / 24.04 x86_64. Self-contained: the engine
  ships as a frozen sidecar; `apt` only needs `libwebkit2gtk-4.1-0` and
  `libgtk-3-0`. Installed with `apt install ./<file>.deb`, removed with
  `apt remove`. Reinstall and package-replacement (`apt install --reinstall`)
  verified on genuinely clean containers by an installed-build acceptance
  harness that launches the real app under a real display and closes its
  real window; a real cross-version upgrade has no prior Linux release to
  upgrade FROM yet, so it stays unverified until v1.0.1. Guide:
  [docs/linux-install.md](docs/linux-install.md).
- **Data lives where Linux expects it.** `$XDG_DATA_HOME/SnapmakerStudio`,
  falling back to `~/.local/share/SnapmakerStudio`, created `0700`;
  `SNAPSTUDIO_DATA_DIR` still overrides. Windows is unchanged
  (`%LOCALAPPDATA%\SnapmakerStudio`).

#### Fixed
- **Closing the window now actually quits Studio and its engine (Windows and
  Linux).** Since beta.13, closing the main window left the process and its
  sidecar running silently in the background — confirmed against a real
  built release binary, not inferred. Every previous "zero orphan" proof only
  covered a process being killed outright, never a normal window close.
- **No orphaned engine on Linux**, closing, crashing, or killing the app stops
  its sidecar every time (parent-death signal, a stdin lifeline, and a
  graceful `/shutdown`, with the sidecar's own process group killed as the
  last resort).

#### Changed
- **The project's home is `github.com/DVOpenLabs/snapmaker-studio`.** The
  in-app update check and the public docs now say so. Old links redirect.
- The Ecosystem entry for the Snapmaker U1 Toolkit now says what it is: driven
  from a terminal or a phone over Telegram, and needs a Linux or WSL host
  (corrections from that project's own maintainer).

#### Known limitations (Linux)
- Snapmaker Orca is not auto-detected on Linux: after Prepare, the handoff
  button always offers Orca's download page — open the prepared `.3mf` in
  Orca yourself.
- No automatic update check on either platform — Studio doesn't notify you of
  a new release on its own. Use Help → Check GitHub now, or watch the
  Releases page.
- Not yet verified from Linux: Printer Hub against a real Snapmaker U1; no
  external-user report yet.

#### Not changed
- Windows install identity is unchanged, so v1.0.0 installs over v0.9.0 in
  place and keeps your data — verified, including that the upgraded
  installation reports the new version and nothing is left duplicated. The
  Windows installer is still unsigned; verify the SHA256.

### The v1.0 product includes
(already shipped in 0.4.0–0.9.0 — listed so 1.0 reads as a whole, not as new work)
- Project Doctor / Printer Doctor / Cost Doctor — read-only, plain-language,
  "unknown" stays unknown.
- Prepare a U1 copy for Snapmaker Orca without touching the original; painted
  colour, parts, modifiers, multi-object layout and three per-object settings
  cross (0.7–0.9).
- Read the sliced G-code back and check it against the printer as it is right
  now (0.4).
- Printer Hub: monitor, and user-confirmed send/pause/resume/cancel — never
  autonomous.
- Materials providers: Spoolman and Bambuddy, read-only, local-network only
  (0.8–0.9).
- Batch, Design Library, Ecosystem directory, the engine and the `u1convert` CLI.
- Local-first: no cloud, no account, no telemetry; the one transfer is a
  sliced job to your own printer after you confirm it.

## [0.9.0] - 2026-08-28

**The project that crosses whole.**

### Added
- **Painted colour survives the crossing.** A prepared copy carried painting
  exactly as the source wrote it and Snapmaker Orca opened it with nothing
  painted. Painting is only read when the mesh sits in its own object file, so
  that is where a painted object goes now. Eight painted facets in, eight out, in
  the same slots; the encoding is unchanged.
- **An object's parts cross as real parts.** A project whose object has volumes on
  different filaments is split along its real volume boundaries instead of
  arriving as one undifferentiated mesh. The parts recombine to the source
  geometry facet for facet, nothing is duplicated, and a filament in slot 5 is not
  clamped to four.
- **A modifier crosses as a modifier.** The four non-printing volume roles cross
  with the word Orca uses, over geometry typed as not-printable, instead of
  arriving as solid plastic. Measured on Orca's own plate footprint: 500 mm² for a
  solid second cube, 400 mm² for every non-printing role.
- **Multi-object projects cross in the target's layout.** Every logical object
  becomes its own object with its own object file, build item and part records. If
  any one object cannot be carried the whole project declines and crosses
  verbatim.
- **Three per-object settings cross** — layer height, infill density and supports
  — written in the target's vocabulary rather than the source's, chosen by handing
  Orca one candidate at a time with an invented key as the control. Every value is
  validated before it is written, because a value the slicer cannot read costs the
  object rather than the setting. A per-object layer height is withheld on a
  multi-filament plate, where Orca refuses to slice a prime-tower plate whose
  objects disagree.
- **Bambuddy as a second materials provider.** Settings offers None, Spoolman or
  Bambuddy on the existing page. Read-only, optional, local-network only.
  Everything downstream of the adapter is identical whichever is chosen, proved by
  a table of equivalent facts rather than asserted.
- **The fidelity report answers each fact twice** — what the file states, and what
  the slicer will do with it.

### Fixed
- **Print settings carried from a source project reached the file and not the
  slicer.** The five translated process values were written but never declared, and
  an undeclared value is replaced by the preset on load — so the whole promise was
  correct in the file and invisible in Orca. Declared now, each in the entry it
  belongs to.
- **An unpainted patch on a painted object** printed in the wrong filament; it now
  prints in its own volume's filament.
- **A provider address that redirected off the local network was followed**, and
  the request left the machine. Refused now at the one transport every provider
  shares. A redirect that stays on the local network is still followed.
- **A slot with a stale provider mapping claimed the printer had looked at it.**
  With no printer configured and none contacted, a mapping pointing at a deleted
  spool produced "the printer reports it empty". The three reasons a slot can be
  absent now read differently from each other.
- **Malformed provider numbers could become a weight.** A full-width Unicode digit
  string parsed as a number; a plain ASCII number is now required.
- **A modifier off the plate** was reported as an object off the plate.
- **A per-object layer height and a prime tower** could both be written into a
  project Orca then refused to slice.

### Changed
- The provider wire names are `provider` and `provider_url`; the older `spoolman`
  field still works and means what it did.
- Switching materials provider clears the address and slot mapping, because a
  spool id only means something to the provider that issued it.
- **Eight values were removed from the U1 template.** Restated preset defaults
  that the slicer overwrote on load and that had never reached a print, including
  a nozzle type and start and end code older than the presets they competed with.


## [0.8.0] - 2026-08-25

**The spool, the printer, and the evidence.**

### Added
- **Spoolman as a materials provider, configurable in the app.** Settings gains a
  Materials provider section: choose Spoolman, give the address of the machine on
  your network that runs it, test the connection, and map a spool to each slot.
  Studio then answers whether a job has enough filament to finish. Read-only —
  Studio never creates a spool and never decrements anyone's remaining weight.
- **Slot numbering is stated, not guessed.** A person counts printer slots 1–4 and
  the G-code counts them 0–3; the app asks which you mean.
- **Remaining-filament sufficiency with provenance and freshness.** A short,
  tracked, recent figure blocks a send. A stale one, a figure derived from a
  spool's declared size, and a figure with no date all warn instead. Nothing
  tracking the spool stays unknown.
- **Printer profiles.** Build volume, tool count, what a machine reports about its
  own materials and what it is known not to report, each with a source and a
  verification level. Live evidence from a connected printer always wins over a
  profile, and a disagreement is reported rather than resolved.
- **A second printer profile — VORON 2.4 250 — profile verified, hardware not
  tested by this project.** Derived from the configuration Klipper publishes for
  that machine. The Snapmaker U1 remains the only printer verified on physical
  hardware.
- Printer Hub shows which machine Studio identified and on what evidence.

### Changed
- Printer intelligence reads the printer instead of assuming a U1: the bed and
  toolhead fallbacks, the sliced-job machine comparison, the firmware summary, the
  discovery hint and the placement wording are all driven by profile data or by
  what the machine reported.
- Design and placement answers name the printer they were measured against, so a
  profile figure never reads as a reading from your machine.
- Preparing a copy is unchanged: Studio still prepares Snapmaker U1 projects for
  Snapmaker Orca.

### Fixed
These were found while making provider support reachable. None of them could
affect v0.7.2, which had no way to configure a provider at all.
- A provider address was passed straight to the network layer, so a `file://`
  address opened a local file and a public web address was fetched. Addresses are
  now validated as being on the user's own network before anything is opened.
- A stale tracked weight, and a weight derived from a spool's declared size, could
  each refuse a send. Both now warn.
- Archived Spoolman spools were invisible, so a slot mapped to one reported "no
  such spool" instead of "that spool is archived".
- A spool's remaining weight was labelled as tracked whenever Spoolman reported
  one, including for spools nothing had ever printed from.
- On a printer that reports its own filament, the slot is now recorded as
  confirmed by the machine rather than carrying no provenance.

## [0.7.2] - 2026-08-25

**A Prusa object's filament survives the crossing.**

### Fixed

- **Every PrusaSlicer project Studio prepared came out with all of its objects on
  filament 1.** An object the user had assigned to filament 3 was written as
  filament 1 in the U1 copy — a different print of the same shape — while the
  geometry was reported byte-identical and nothing was reported removed. Prepare
  now carries what the source says each object prints in, including a slot above
  four, which is never renumbered to fit the machine's toolheads. An object with
  no assignment of its own takes its volumes' slot when they agree, and the
  object's own name comes across with it.

- **The fidelity audit could not see it.** It compared per-object assignments only
  when both files spoke the same dialect, and a PrusaSlicer source never does. It
  reads the assignment from either dialect now and reports one row per object:
  preserved, changed with "slot 3 → slot 1", lost, or — for volumes on different
  filaments, which a single-part U1 object cannot represent — not representable,
  with the slots named.


## [0.7.1] - 2026-08-25

**What a real brush writes, and what an overlap really means.** A patch
release: one defect found by painting in the slicers themselves, and one
overclaim found by reading Studio's own copy.

### Fixed

- **A genuine painted project could be reported as partly undecodable.** Studio
  capped a paint attribute at 4,096 characters — a number chosen before any
  slicer-authored file had been seen. Snapmaker Orca's own round brush writes
  35,460 characters for a single facet of a large surface, so two facets of a
  real project came back as malformed and lost their slot, area and height. The
  cap is now a million characters, the reader walks the string instead of
  building a list of bits, and the bound that matters — the total work one
  project may ask for — is unchanged.

- **The colours card said two colours "share the same layers".** Studio cannot
  prove that: overlapping heights show two colours *can* meet on a layer, and
  only the slice shows whether one really does. The plan is unchanged and still
  conservative — a toolhead is reserved either way — but the claim now matches
  the evidence: "not proven separable — reserve a toolhead each".

- **Four public claims about the current release were false.** The README's top
  download button pointed at v0.6.2; the self-check was described as a 25-check
  table and the acceptance harness as 30 checks; and the evidence section
  credited "the published v0.6.2 installer" above v0.7.0's numbers. The guard
  that should have caught them read one line at a time, so a wrapped sentence or
  a link outside the Download section was invisible to it. It reads whole blocks
  now, and each of those four claims is a regression test against the guard
  itself.

### Verified

Painting was authored in **Snapmaker Orca 2.3.5** and **Bambu Studio
02.08.02.61** through their own gizmos and saved by them; both files are
fixtures, and reading them is what found the attribute-length defect.


## [0.7.0] - 2026-08-24

**The painting, read.**

Multi-material painting is the part of a project most tools treat as opaque, and
Studio was one of them: it could prove a project *had* painted regions and then
said painted colour "cannot be classified without slicing". The paint was in the
file the whole time.

### Added

- **Painted colour is read before anything is sliced.** Which filament slots the
  painting uses, how many facets carry each, how much surface each covers, and
  the height band each occupies once the object is placed. Facet counts and areas
  are reported as the two different facts they are — a mesh's triangles are not
  equal in size, so 40% of the facets is not 40% of the surface.
- **Colour planning answers instead of shrugging.** A painted colour whose height
  band overlaps another's needs a toolhead, because the two can meet on a layer.
  One painted only between, say, 38.2 mm and 61.0 mm, with every other colour
  ending below it or starting above, is offered as a planned swap. One that
  cannot be compared stays unclassified and says why. A separation is only
  claimed when it is proven.
- **The colours card leads with a sentence a beginner can act on** — "Parts of
  this model are painted with 3 filament colours." — and keeps every number
  behind it one click away: the attribute it was read from, the painting format
  version the project declares or fails to, per-mesh facet counts, and which slot
  the unpainted area falls back to.
- **A project that paints with a filament it never lists is reported**, rather
  than renumbered onto a filament that happens to exist.
- **Two self-checks**, so the capability is provable from a frozen install: paint
  decoded from a project built at runtime, and a prepared copy audited to show the
  painting survived. 25 checks became 27.

### Fixed

- **Every painted project in the field was reported as unpainted.** The trait
  looked for painting in `Metadata/model_settings.config`, where no slicer has
  ever written it. It reads the mesh parts now, in both dialects.
- **Fidelity compared painting by counting markers in the bytes**, which cannot
  tell painting that survived from painting that was rewritten: remap every
  painted facet to another filament, or shrink a painted region to a quarter of
  its area, and the count is identical. It compares the painting itself now —
  byte-identical, or the same meaning written differently, or changed with what
  changed, or removed.

### Verified

Studio's decoding was checked against files two real slicers wrote: paint was
handed to PrusaSlicer 2.9.6 and OrcaSlicer 2.4.2, and both wrote every attribute
back byte for byte, including a subdivided facet. The painted fixture was then
sliced for a five-extruder printer, and the G-code used tools T0-T4 and no
others — which is what proves a paint state names filament N counting from one,
rather than that being asserted.


## [0.6.2] - 2026-08-24

**Evidence that stays true, and a service that answers on a busy machine.**

### Fixed

- **A release's evidence changed when a later release shipped.** There was one
  canonical evidence file, rewritten every time, so publishing restated the numbers
  every document quoted — including the sections describing releases that had
  already shipped. TRUST_STATUS said v0.6.0 was verified with 967 backend tests,
  290 desktop tests, a 30-check acceptance run and 26 hardware checks; it shipped
  with 822, 284, 28 and 20, and the larger figures come from a suite and a harness
  that did not exist yet. v0.5.0 and v0.4.0 had their hardware counts overwritten
  the same way, and SUBMISSION_STATUS attached this week's hardware run to v0.4.0's
  name while still calling v0.4.0 the current build.

  Evidence is now one immutable snapshot per release in `docs/internal/evidence/`,
  reconstructed for past releases from what each release's own tag recorded and
  saying "not recorded" where a release recorded nothing. Publishing adds a file
  and never edits one. The historical sections are restored from their own tags.

- **Studio could fail to start on a machine that is short of ports.** The loopback
  service spoke HTTP/1.0, closing the connection after every call, and drawing one
  page makes a dozen calls. On a machine with 14,000 connections held open by
  something else, the service could not be reached and sometimes could not bind at
  all. It speaks HTTP/1.1 so a client keeps one connection, retries the bind, and
  falls back to fixed ports below the dynamic range.

- **"This printer does not report which filaments are loaded" could be untrue.** A
  dropped connection and a printer that genuinely reports nothing both came back as
  `None`, so a momentary network failure was reported as a statement about the
  user's machine. They are distinct now; printer reads retry; and the firmware
  route degrades to "Studio could not ask" instead of returning an error.

- **A re-slice could pass as the file that was checked.** The send fingerprint
  identified a job by size and modification time, and a re-slice that lands on the
  same byte count within the same timestamp tick matched both. It now also
  fingerprints the file's contents at three bounded windows — start, middle and
  end — which is where a slicer writes what distinguishes one job from another.

- **The "Extended firmware" badge appeared on stock printers**, and the acceptance
  and release-doc guards missed the README's combined row, which said
  `822 · 284 · clean · clean` through an entire release.

### Added

- Every item in the send confirmation can now show what it was read from, one
  level down: the beginner never opens it, and an expert who doubts a verdict
  should not have to ask.
- The send card says when the printer was last actually read. The send path
  already re-reads before uploading; this is so a page drawn four minutes ago
  cannot be mistaken for what the machine is doing now.
- An evidence-integrity guard: current documents against the current snapshot,
  every historical section against *that release's* snapshot, and a regression test
  that re-derives each published release's evidence from its own tag.

### Verified

pytest 1004 passed / 3 skipped · vitest 293 · self-check 25/25 · installed-build
acceptance 30/30 including the v0.6.1 upgrade · real Snapmaker U1 read-only 26/26.

## [0.6.1] - 2026-08-24

**The answers, attacked.** A release spent trying to make v0.6.0 lie — mismatch
files, lose provenance, misread materials, mishandle uploads — and fixing what
worked. Every item below is a defect that was in the published v0.6.0.

### Fixed

- **Object names in real Snapmaker Orca jobs were not read at all.** Studio looked
  only for `EXCLUDE_OBJECT_DEFINE`, which Orca writes only when object exclusion is
  switched on, and it is off by default. Three jobs pulled off a real U1 carry 90,
  52 and 3,476 `; printing object` labels between them and not one exclusion
  define, so the strongest provenance evidence was missing from exactly the files
  it was written for. Both dialects are read now, along with PrusaSlicer's `M486`,
  and names are normalised so `Left_bracket.stl_id_0_copy_0` and `Left bracket` are
  recognised as the same object.
- **PrusaSlicer's object labels never parsed on Windows.** The pattern was anchored
  with `$`, which in multiline mode matches before a newline and never before a
  carriage return, so every CRLF file — which is most of them — read as having no
  objects.
- **A matching setup was read as a matching project.** Evidence is now identity
  (which objects the job prints) or profile (the setup it was sliced with), and
  profile evidence alone can never do better than "cannot tell". Identity decides
  first, so a project re-sliced in a different material is still that project;
  object names compare as a set of hashes, so one plate of a four-plate project is
  part of it rather than a stranger.
- **The folder watcher could offer a file that stopped part-way.** Completion was a
  two-second pause plus any of five markers in the last 4 KB, and Snapmaker Orca
  writes three of those markers inside the first few hundred kilobytes. It now
  needs the terminator its own dialect ends with. That check also slept two seconds
  per candidate inside a request the app repeats every five seconds; it remembers
  sizes between polls instead and never sleeps.
- **A provider could contradict the printer in silence.** A tracker reporting PETG
  where the printer reports PLA now shows the disagreement against the slot it is
  about, with the printer's answer standing. A one-based slot map — the way a
  person counts the slots on a U1 — was read as zero-based.
- **"It will run out" was built on whatever number came back.** A remaining weight
  now carries where it came from: tracked, worked out from what was used, or
  unknown. Only a tracked figure, short by more than the tracking can drift, blocks
  a send. Negative weights, weights larger than the spool holds, and weights that
  are not weights are refused.
- **Nothing re-read the world between the check and the send.** The check records a
  fingerprint of what it looked at; sending re-reads the same things and refuses,
  naming what moved, rather than uploading against an answer that no longer holds.
- **"Upload failed" was four different situations.** A refusal by the printer, a
  dropped connection, bytes accepted but never listed, and a file the printer has
  not finished reading are now told apart — including a printer still describing
  the file this one replaced.
- **A model name could reach a support bundle.** The bundle drops the project's
  filename on purpose; the sliced-job section was carrying it through.
- **A badge told people they had firmware they do not have.** "Extended firmware"
  appeared whenever a printer reported fifteen or more macros. Detection is
  positive only now — the firmware has to answer for itself, distinguishably from
  what the printer serves for a path nobody claims — and not finding it never means
  the printer is stock. Verified against a real U1 with 115 macros and stock
  firmware, which the old rule would have badged.
- **Studio reported "no nozzle" for every PrusaSlicer project.** A project does not
  carry `nozzle_diameter`; it keeps the printer variant and the profile name, both
  of which are now read and labelled with where they came from. PrusaSlicer's
  record of where an object was imported from was also being counted as per-object
  setting overrides.

### Added

- **A prepared Prusa copy now prints the way the project did.** Layer height, first
  layer height, infill density, wall count, brim, support on or off, and the
  filament type and colour per slot are carried into the U1 copy, each recorded
  with where it came from. Temperatures are deliberately not carried: they belong
  to a Prusa hotend and a Prusa filament profile.
- **Sending from where the checks are.** The send confirmation now offers the
  upload it describes, passing the fingerprint of what was checked.
- **The reasoning behind a provenance verdict**, grouped into what identifies the
  model and what describes the setup, wherever the verdict is shown — and never
  the object names themselves.
- **An interoperability proposal for U1Hub** ([docs/interop](docs/interop/U1HUB_INTEROP_PROPOSAL.md)):
  a two-route read-only contract for spool state. U1Hub exposes no interface it
  means to offer, so Studio reads none of its files and depends on nothing.

### Verified

pytest 967 passed / 3 skipped · vitest 290 · self-check 25/25 · installed-build
acceptance 30/30 including the v0.6.0 upgrade · real Snapmaker U1 read-only 26/26.
Bounds measured on files built for the purpose: a 525 MB job reads in 0.20 s
holding 40 MB, and its timeline scans in 3.0 s holding 9 MB.

## [0.6.0] - 2026-08-23

**The workflow becomes one thing.** v0.5.0 could read a sliced job, plan the
materials and decide whether to send. It still needed the user to carry the file
back from Snapmaker Orca by hand, and it still could not tell whether that file
was the slice of the project they had just checked. Both are fixed.

### Added
- **The sliced job comes back on its own.** Point Studio at the folder Snapmaker
  Orca exports to — once — and it notices finished jobs appearing there while the
  page is open. It offers a file only when it can see the slicer has stopped
  writing it: the size has settled *and* the file ends the way a finished job
  ends. One folder, chosen by the user; no background daemon, no whole-disk
  watcher, nothing uploaded.
- **Provenance: is this actually the slice of my project?** Every conclusion in
  the post-slice half depends on the answer, and there is no identifier linking a
  3MF to its G-code. So Studio weighs the evidence that exists — the set of object
  names, filament colours and materials per slot, slot count, the target machine,
  object count — and reports `confirmed`, `likely`, `ambiguous`, `no_match` or
  `unknown`. **A filename is never proof**, and a folder with two equally good
  candidates produces a question rather than a guess. Object names are compared as
  a digest, so a model's name never leaves the file.
- **A material provider seam.** What is loaded no longer has to come from the
  printer alone. `material_providers` normalises any read-only source to one
  shape, and **Spoolman** is supported optionally over the local network. The
  printer stays authoritative about *what* is in a slot; another source may only
  add what the machine cannot know — a spool identity, a remaining weight. Nothing
  is required, nothing is written back, and a disagreement between two sources is
  reported as a disagreement.
- **Do I have enough filament?** With a source that tracks remaining weight,
  Studio compares grams needed against grams left, per slot: enough, probably
  enough (with a stated margin, because tracked weights are not exact),
  insufficient, or — on a stock U1, which cannot know — unknown. A short spool is
  a blocker on the send check, because it stops the print part-way.
- **One surface for the whole job.** *This print* shows the stages in the order
  they happen: before slicing, prepared, after slicing. Every individual page
  still exists and still works; the cockpit exists so a beginner does not have to
  know the order to follow it. In Simple mode it replaces "Check my model", which
  moves to More tools.

### Fixed
- **Studio called an upload finished when the printer had not read it.**
  Moonraker accepts the bytes and parses metadata afterwards, so a job could be
  "uploaded" and not yet startable — the failure the U1 Toolkit documented.
  Uploads are now confirmed against the printer's own metadata, with one polite
  `metascan` request if it has not appeared, and `ok` means the printer has the
  file *and* has finished reading it. A same-named file of a different size is
  caught, which is what happens when a slicer re-exports over an old job.
- **A project file handed in where G-code was expected** produced a report that
  looked empty for no stated reason: a 3MF is a ZIP, and its compressed bytes
  decode into enough noise to contain `G1 `. Studio now names the mistake.
- The public evidence counts had drifted again — the Innovation Fund page still
  described a 15-check self-check and a 21-check acceptance harness. The guard now
  reads prose as well as tables, and also checks the demo's length against the
  recording's own header, the screenshot folder against the released version, and
  that the README's "What's new" names the current release.

### Traced, and deliberately still unknown
- **Free storage on the printer.** Checked properly this time rather than assumed:
  `/machine/system_info` reports `total_bytes: 0`, `/server/files/roots` reports no
  sizes, and nothing else on stock firmware exposes disk usage. Studio says it
  cannot tell, and now says exactly what it looked at.

## [0.5.0] - 2026-08-23

**The loop gets intelligent.** v0.4.0 could read a sliced job and check it against
the printer. This release answers the three questions that follow: what actually
happens during the print, what should be loaded before it starts, and whether to
press send.

### Added
- **The print, in order.** *What happens during this print* reads the whole job in
  one streaming pass and gives a plain-language timeline: which slot it starts on,
  when each other slot joins in, when one is finished with and its spool can come
  out, where it pauses and waits for you, and what the bed and nozzle targets are.
  Every line carries the G-code that proves it. Verified on a real 89 MB
  four-colour job with 764 tool changes — read in 0.53 s using 8 MB of memory.
- **What to load.** Slot by slot: what the job needs, what is in there now, and
  what to do about the difference. An empty slot the job prints from is a change;
  a slot the job never touches is left alone and says so; a right-material,
  wrong-colour slot is advisory rather than alarming; and a material family match
  means "PLA Matte" is not reported as wrong against "PLA". This is an
  intelligence layer over whatever spool state exists — Studio does not track
  filament and does not want to. U1Hub, Spoolman and OpenSpool do that.
- **Ready to send?** Blockers, warnings and unknowns kept strictly apart. A
  blocker is a provable mismatch — an empty slot the job uses, a tool the printer
  does not have. A warning is a real concern that is not proof. An unknown is
  something Studio cannot verify, and it is never promoted to look thorough or
  demoted to look clean. Studio still never sends anything on its own, and it does
  not disable the button: it is your printer.
- **PrusaSlicer projects are read, not merely recognised.** A Prusa `.3mf` carries
  its whole configuration in `Metadata/Slic3r_PE.config` and its per-object data in
  `Metadata/Slic3r_PE_model.config`. Studio now reads both: printer model, bed
  size, every filament slot with its type, colour, vendor and diameter, layer and
  first-layer heights, supports, temperatures, per-object extruder assignments,
  per-object overrides and variable layer-height profiles. What a U1 copy cannot
  keep — variable layer height, per-object overrides, support styling — is named
  in the fidelity report rather than quietly lost. Verified against a genuine
  PrusaSlicer 2.8 project.
- Six new engine routes — `/print_plan`, `/material_plan`, `/send_check`, plus the
  0.4.0 additions — all covered by the self-check, which is now 21 checks over 13
  documented routes.
- **Check for a newer version**, in Help. This is the only thing in Studio that
  talks to the internet: one request to GitHub's releases API, made only when
  somebody presses the button, sending nothing but the request — no identifiers,
  no usage, no telemetry. Studio never downloads or installs anything on its own.
  It is implemented in the desktop shell rather than the web view so the page's
  content-security-policy keeps its lock-down, and `test_local_first.py` fails the
  build if the shell ever reaches another host, if the check is wired to run
  automatically, or if the engine requests a remote address at all.

### Fixed
- **The timeline scanner missed everything in a job written on Windows.** Lines
  end with CR LF there, and the stray CR sat between the marker and the end of the
  line, so every anchored pattern missed. Found by its own test.
- **A quoted filament name containing a comma silently invented an extra
  extruder.** PrusaSlicer separates per-extruder values with semicolons for
  strings and commas for numbers, and quotes any value containing either.
- The public evidence counts in the README, the judge walkthrough and the
  submission status had drifted from what the harnesses actually produce — 21/21
  where it is now 27, 15/15 where it is 18, 495 backend tests where there are 766.
  `docs/internal/evidence.json` is now the single source and
  `test_evidence_consistency.py` fails the build when a current-state document
  disagrees with it.
- The Innovation Fund description still said Studio is "the step before the
  slicer", which stopped being true in 0.4.0.

### Changed
- The README's compatibility table no longer calls PrusaSlicer "detected", and
  names sliced G-code as an input.
- The change-freeze policy is replaced by a convergence policy: v0.4.0 stays the
  public stable baseline while development continues, and a new stable ships when
  it is clearly better rather than when a milestone arrives.

## [0.4.0] - 2026-08-23

**The first stable release, and the second half of the workflow.**

Studio has always stopped at the slicer. It read a project, explained the risks,
compared the project against the printer, prepared a corrected copy, and handed
that copy to Snapmaker Orca. What happened after Orca sliced it was somebody
else's problem — which meant the most consequential failures were invisible: the
job prints from slot 3 and slot 3 is empty; the job was sliced for PETG and PLA
is loaded; the job was sliced for another machine entirely. None of those can be
seen in the project file, and none can be seen on the printer alone.

This release closes the loop. Studio still does not slice.

### Added
- **Post-Slice Doctor.** Open the `.gcode` your slicer produced and Studio reads
  what the printer will actually execute: which machine it was sliced for, how
  many layers, the estimated time, which tools it prints from, the filament per
  slot, the nozzle it expects, and whether it defines excludable objects. Every
  figure comes from the file; nothing is inferred.
- **The sliced job, joined to the live printer.** Tools the job needs against
  toolheads the printer reports; the slots it prints from against the spools
  actually loaded; the job's materials against the loaded materials, compared by
  family so "PLA Matte" is not a false alarm against "PLA"; the sliced bed against
  the printer's own reported bed; object exclusion against the firmware's own
  object list; and whether the printer is busy right now.
- **Cost from what the slicer measured.** Filament by slot and print time come
  from the file rather than an estimate. Where the file states nothing, the line
  reads unknown rather than zero. **Purge is never split out of a total the
  slicer did not split** — Snapmaker Orca reports one figure per slot, so Studio
  reports that and says why it will not divide it.
- **`.gcode` opens Studio.** A sliced job passed on the command line, dropped on
  the window, or opened from a shell goes straight to the Post-Slice Doctor. It
  is deliberately not treated as a project.
- **A support bundle worth sending.** Studio asks people to report when it gets an
  analysis wrong; this gathers the facts behind that report — project traits,
  Doctor findings, the sliced job, the printer's capabilities, the fix ledger.
  Usernames, home directories, file paths, machine names and addresses are
  replaced **before the bundle is assembled**, and the whole thing can be read
  before it is written. Studio never sends it anywhere.
- Three new engine routes — `/gcode_facts`, `/post_slice`, `/sliced_cost` — plus
  `/diagnostics_preview` and `/diagnostics_build`, all documented and covered by
  the self-check.

### Fixed
- **`u1convert selfcheck` crashed at the end on a default Windows console.** The
  results table contained a character `cp1252` cannot encode, so the one command
  Studio tells strangers to run failed while printing its own success. It now
  prints on a stock console.
- **The support bundle leaked a model's file name.** Replacing a username inside
  a path inserted angle brackets that stopped the path pattern dead, leaving the
  rest of the path — file name included — in the bundle. Paths are now redacted
  before anything else. Found by its own test, before the feature shipped.
- A slicer that reports filament per slot without a total, PrusaSlicer among
  them, now has the total added up rather than left missing.

### Changed
- **Version is `0.4.0`, not `beta.25`.** The workflow is complete end to end and
  the release is no longer a prerelease, so GitHub's "latest release" finally
  points at the build people should actually download.
- The development freeze that was in force before this release is cancelled and
  replaced with a convergence policy — see
  `docs/innovation-fund/CHANGE_FREEZE.md`.
- The self-check grew from 15 checks to 18, covering the sliced-job reader, the
  post-slice join, and the refusal to invent a purge split.

## [0.4.0-beta.24] - 2026-08-23

The first build verified against a real Snapmaker U1. Hardware found a bug no
synthetic test could: Studio was telling owners their printer does not report
which filaments are loaded, while the printer was reporting all four.

### Fixed
- **Loaded filament is now read the way a real U1 actually reports it.** Stock U1
  firmware publishes loaded filament as parallel arrays — one array of types, one
  of colours, one of sub-types, one of vendors, and `filament_exist` as the
  printer's own answer to "is a spool in this slot". Studio was looking for a list
  of objects, found nothing, and reported "this printer does not report which
  filaments are loaded". Against a real machine it now reads all four slots,
  including colour and sub-type, and the project-to-printer preflight compares a
  project's materials against what is actually loaded.
- **Every message that names a problem now says what to do about it.** The
  fidelity report's "could not account for" headline tells you to open the
  prepared copy in Snapmaker Orca, compare it with the original, and report it as
  a bug. An element Studio cannot read is labelled "Not checked — Studio can't
  read it" rather than left ambiguous. The preflight's printer action names
  Printer Hub instead of a field that does not exist. "Toolhead" — the word the
  colour planning rests on — is explained before it is used.
- The preflight summary no longer lowercases "Studio" mid-sentence.

### Added
- **Open a project by handing it to the app.** Studio accepts an `.stl` or `.3mf`
  path on its command line and opens it on launch, so a file can be sent to Studio
  from a shell, a script, or a shortcut. Only paths that exist and carry those
  extensions are accepted; anything else is ignored.
- **An acceptance harness that drives the installed application.**
  `tools/acceptance/run.ps1` installs the built installer into an isolated
  directory, launches it with an isolated WebView2 profile and engine data
  directory, drives the real window over the Chrome DevTools Protocol, and asserts
  21 checks against the shipped build — including that the input file is
  byte-identical afterwards and that uninstalling leaves nothing behind. It stops
  only the processes it started, and restores any pre-existing installation it
  displaced.
- **A recorded demo of the running application** at
  `docs/media/snapmaker-studio-demo.mp4` — 71 seconds, every frame the installed
  app, nothing reconstructed.
- **Regression tests against files real slicers wrote.** OrcaSlicer, BambuStudio
  and PrusaSlicer project 3MFs are fetched from their upstream repositories and
  the reader is tested against them. They are AGPL-3.0 and one embeds an upstream
  developer's username, so they are fetched rather than committed; the suite skips
  cleanly without them. See `backend/tests/fixtures/REAL_WORLD_PROVENANCE.md`.
- `docs/CODE_SIGNING_POLICY.md` — the signing story, prepared to the point where
  only a form submission remains.

### Changed
- The Rust crate version had drifted to `0.4.0-beta.21.3` while the app manifests
  moved on. It now matches, and `test_release_docs.py` fails the build if it drifts
  again.
- `tools/demo/node_modules/` was committed by accident in beta.23. It is now
  untracked and ignored, as the acceptance harness's dependencies already were.

## [0.4.0-beta.23] - 2026-08-23

### Added
- **Before you slice** — a project↔printer preflight. Materials against toolheads,
  the project's nozzle against the printer's, the objects against the printer's
  real bed, the capabilities a prepared project relies on against the firmware's
  own list, and whether the machine is busy. Every check carries its evidence, a
  confidence and what to do. Unknowns stay unknown: stock firmware does not report
  the fitted nozzle, so Studio says "check this yourself" and never "unsupported".
- **What survived preparing this copy** — a fidelity audit classifying every
  element as preserved exactly or semantically, deliberately changed or removed,
  added, unsupported, or unverified. The last two exist because a report that can
  only say preserved-or-changed has to lie about the parts it does not understand.
  Studio may only claim nothing was lost when the audit proves it for that file.
- **Changes Studio made** — a fix ledger recording every file Studio produced with
  its changes, old values and reasons, plus "return to the original". The original
  was never written to, so going back points the workflow at an untouched file.
  A shared export strips file locations.
- **Colours and toolheads** — a >4-colour project is classified into colours that
  share layers, colours introduced at a height (with that height, and a layer
  number only ever as a labelled estimate), and colours Studio cannot classify.
  Painted colour cannot be read without slicing and is never put in the optimistic
  bucket.
- `u1convert selfcheck` — runs the real pipeline end to end over a generated
  project and prints a pass/fail table. Exits non-zero on failure and runs in CI.
- CLI: `preflight`, `fidelity`, `colors`, `history`. API: `/preflight`,
  `/fidelity`, `/color_plan`, `/fix_history`, `/fix_original`,
  `/fix_history_export`.
- Current screenshots from the running build, and `examples/demo_u1_showcase.3mf`.
- `THIRD_PARTY_NOTICES.md`; "Run from source" in CONTRIBUTING.md.

### Changed
- A prepared copy is now labelled with the U1 process preset that matches its
  actual layer height. A 0.12 mm project was being stamped "0.20 Standard" —
  correct settings under a wrong label, which Snapmaker Orca then reported as a
  customised preset with no explanation.
- Placement, colour planning and preflight appear on "Check my model", the route a
  beginner actually lands on, instead of only under More tools.
- The prepare-mode choice marks Preserve as Recommended and describes both options
  by outcome rather than by setting name.
- Colours & Materials answers its own page-title question instead of linking away,
  and shares the model-path hook every other tool page uses.

### Removed
- **Multi-plate repositioning.** An independent review reproduced a derived plate
  stride wrong by 79%, placing a plate entirely off the bed while reporting
  success; the guard meant to catch it was a tautology for two-plate projects. The
  plate spacing is not recorded in the file, so the feature was withdrawn rather
  than patched. Multi-plate projects are still checked — each plate on whether its
  own contents fit a U1 plate — and Studio points at Snapmaker Orca's Arrange.

### Fixed
- **`snapstudio_api` was excluded from the installed package**, so on a clean
  install the loopback service could not be imported and `selfcheck` failed. Tests
  masked it because pytest puts `backend/` on the path.
- Two ecosystem registry entries could never be recommended while the docs said
  they were listed; a test now asserts every entry is reachable.
- `color_plan` read object `extruder` values as 0-based while `plate_remap` — the
  module validated against a real nine-plate U1 project — reads them 1-based.
- The colour card defaulted to four toolheads and implied it had read the printer.
- Moonraker responses are read through a byte cap, like the 3MF reader.
- A model part that is not valid UTF-8 no longer raises out of a function
  documented as always returning a result.
- `docs/INNOVATION_FUND.md` claimed a signed installer. It is unsigned.

### Security
- CI runs `cargo check`; the Rust shell owns the security boundary and nothing was
  verifying it.

## [0.4.0-beta.22] - 2026-08-22

### Added
- **Object placement check and fix.** Reports which objects sit outside the U1's
  printable area, on which edge and by how many millimetres, and can write a new
  copy with the whole arrangement moved onto the plate. Multi-plate projects are
  checked but never repositioned — the plate spacing is not in the file — and each
  plate is judged on whether its own contents fit a U1 plate. Originals are never
  modified and only build-item translations are rewritten.
- **Best tool for this project.** A data-driven registry of the open U1 ecosystem
  matched against facts read from the file, with the reason, licence and a
  caution for experimental community projects. A tool is only marked installed
  when the shell found its executable on disk.
- **Project traits with graded confidence.** Origin slicer, target printer,
  plates, objects, filament slots, nozzle sizes, painted colour, textures,
  per-layer custom g-code, model unit, required 3MF extensions and sliced state —
  each with its evidence and one of confirmed / likely / informational / unknown.
- **Material cost from the project's own slicing result**, per material, stating
  its basis — or an explanation when the file carries no real figures.
- CLI: `u1convert traits`, `ecosystem`, `cost`, `placement` (with `--fix`).
- API: `/project_traits`, `/ecosystem_advice`, `/project_cost`,
  `/placement_check`, `/prepare_placed`.
- Docs: `docs/EXTENDING.md` and the `docs/innovation-fund/` package.

### Changed
- Preparing a U1 copy now also applies Snapmaker Orca import compatibility in
  every mode: Exclude Object enabled; an *automatic* brim suppressed while an
  explicitly chosen brim is kept; tree support with variable layer height
  switched to hybrid; filament array validity repaired; a negative raft
  first-layer expansion restored from the U1 profile; and the authoring slicer's
  `plate_N.gcode` / `.json` removed so Orca re-slices. Plate images are kept.
  Every change is reported with its old value and reason.
- Printer discovery probes both ports a U1 answers Moonraker on, and explains
  Advanced Mode when nothing responds.

### Security
- 3MF reads are bounded by a hard byte budget (total, per part and entry count)
  so a decompression bomb is refused rather than exhausting memory.
- Printer addresses are validated before becoming request URLs; control POSTs use
  the same gate.
- The loopback API refuses oversized request bodies before allocating.

### Fixed
- `u1convert` commands defined after the module's `__main__` guard were never
  registered; the guard now sits at the end of the module.
- The sidecar build script resolves a Python interpreter that can actually import
  its build dependencies instead of assuming a bare `python` on PATH.

## [0.4.0-beta.21.3] - 2026-07-18

### Fixed
- **Preserved settings are no longer listed as "Changed".** Creator temperature,
  retraction and other per-toolhead values that Studio only maps onto the U1's
  four-toolhead layout (values preserved) now appear under "Kept from the original
  file" with the note that they were mapped — never under "Changed for U1
  compatibility". Genuine value changes (including type changes) still appear as
  changed.
- **No more doubled output name.** Preparing a file whose name already ends in
  `_SnapmakerU1` (any letter case) no longer produces `..._SnapmakerU1_SnapmakerU1.3mf`;
  Studio now appends a numeric copy suffix instead.
- **Simpler summary by default.** The prepare summary now leads with plain
  language (printer identity, U1 machine G-code, toolhead layout); raw setting
  keys moved behind a "Technical detail" disclosure. Real print-affecting changes
  stay visible in the default view. "Could not carry over" remains always visible.
- **Copy accuracy.** Removed an overclaiming "safe" wording from the Dashboard
  prepare step and the Design Insights page; the wording guard test now scans more
  surfaces and stricter patterns.

### Internal
- Desktop test runner now collects `.test.tsx` files (previously eight UI tests,
  including the prepare-summary tests, were never executed by `npm run test`).

## [0.4.0-beta.21.2] - 2026-07-17

### Fixed
- **Preserve creator settings by default (P0 trust fix).** Preparing a U1 profile
  copy previously replaced creator-tuned slicer settings silently (nozzle
  temperatures, Z-hop, prime/wipe tower position and shape, print order) via a full
  U1 profile swap — a reported cause of stringing/webbing and poor print quality.
  Preparing now defaults to **Preserve creator settings**: only the minimum machine /
  project-wrapper fields required for Snapmaker Orca U1 compatibility change, and a
  runtime preservation invariant fails the conversion if any setting changes without
  being reported.

### Added
- **Preparation mode choice** before preparing: Preserve creator settings (default),
  Apply Studio recommended U1 settings (opt-in; the previous swap behavior), Custom
  (dry-run preview of the settings summary before preparing).
- **Settings summary** on every prepared copy: kept count, changed-for-U1-compatibility
  list (with reasons), could-not-carry list, warnings, and a preview of what the
  recommended mode would change. Sensitive values (print-host keys, tokens) are
  redacted; machine G-code is summarized, never included verbatim.
- **STL / geometry-only clarity**: such inputs are labeled as having no creator
  slicer settings; Studio uses a U1 starter profile unless the user chooses another
  profile in Orca.
- Regression tests: creator-tuned, multi-material and support-heavy 3MF fixtures
  proving preservation of temperatures, retraction, speed/acceleration, cooling,
  supports, layer height, flow, prime/wipe tower and print order; a non-tautological
  invariant test that fails on any unaccounted mutation; UI tests for default mode,
  dry-run preview, stale-response safety and banned-overclaim copy.

## [0.4.0-beta.1] - 2026-06 (internal milestone — never tagged)

> Positioning: **the workflow platform for modern 3D printing** — understand any
> design, validate it, get it ready, and monitor your U1 (read-only). Snapmaker Orca
> still slices; Studio does not slice, send prints, or control printers. Independent
> open-source project, not affiliated with Snapmaker. Snapmaker U1 is the first
> printer target.

### Added
- **Project Intelligence** (`/insights`) — real, read-only design data: model dimensions (bounding box, mm), triangle count + complexity tier, detected materials (color + type), object/plate/color counts, source ecosystem, verdict and readiness score. No fake data — every value is derived from the file or the existing engine.
- **Validation Center** (`/report`) — a first-class readiness report: pass/warn/fail checks (incl. bed-fit vs the U1 270×270×270 build volume) plus a preservation answer to *What will be preserved? / What will change? / What might be lost?*
- **U1 Printer Hub** (read-only) — discover a networked Snapmaker U1 over its stock LAN-trusted Moonraker API and watch live status: print state, progress, bed + per-toolhead temperatures. **Monitoring only** — GET requests exclusively; no upload, no print start/stop, no printer modification. New `Printers` tab in the desktop app.
- **Canonical project representation** (`/canonical`) — the smallest source-neutral view of a design, the seam where multi-ecosystem support begins. A thin read-only layer over Project Intelligence that normalizes any source into one shape, including a Prusa INI (`Slic3r_PE.config`) reader so Prusa materials + printer model surface like Bambu's. Honest about limits: Prusa multi-material is *detected*, not yet preserved through conversion.
- **Adaptive Print Strategies** (`/strategies`, `/strategy/recommend`) — five research-backed, intent-based U1 print profiles (Fastest, Balanced (default), Best Quality, Maximum Reliability, Advanced). **Recommendation-only — Snapmaker Orca still slices.** Recommendation uses real design signals (color count, source, dimensions, complexity) and never fabricates duration, tool-change count, or purge volume. Print Strategy selector in the conversion flow: Simple Mode shows plain-language names + a *Recommended* badge; Advanced Mode shows the raw settings. Grounded in `docs/research/U1_PRINT_PROFILE_RESEARCH.md`.

### Changed
- **Product positioning rework** across app, README, docs, brand, and landing — from "U1 converter" to a workflow platform (Understand → Validate → Prepare → Monitor). Nav/labels reworded (e.g. "Batch prepare"); "U1 Control Center" → "Workflow Platform"; live engine status in the footer; global search wired to My Designs.
- **Honesty pass:** dropped "any printer / any file / Operating System / Perfect prints" overclaims; PrusaSlicer is shown as *detected* (full conversion = roadmap); added the "independent open-source project, not affiliated with Snapmaker" disclaimer to README, landing, app About, and brand docs.

### Fixed
- **Clean import in Snapmaker Orca.** Converting a customized Bambu/Orca project no longer triggers Orca's "Customized Preset" popup or the "Print By Object" collision warning:
  - clears `different_settings_to_system` (the "differs from system preset" marker carried from the source) during U1 normalization;
  - resets `print_sequence` to `by layer` (the U1 default; "by object" caused the collision warning).
  - The customized setting *values* are preserved — only the markers/sequence are normalized.
- **Validator hardened:** `is_u1_clean` (and the corpus gate) now fail if `different_settings_to_system` is non-empty or `print_sequence != "by layer"`, so these warning triggers can't regress silently. Regression tests added (real-world `KidsCrocsWithSupport` finding).
- **Legacy optimization safety reconciliation:** the bundled `u1_fast_prime_tower` optimization no longer carries `wipe_tower_max_purge_speed: 200` (now 90, the U1-documented safe cap) and its description matches its data. Tests now scan all bundled optimizations/profiles to enforce ≤90 mm/s tower speed, no auto-enabled no-sparse-layers, and no touching of protected per-design data. (Opt-in optimize mode only; default conversion unchanged.)

## [0.3.0-beta.1] - 2026-06-18

### Added
- **Desktop app** (Tauri + React + TypeScript): live Workspace (Doctor → Convert → Compare), Project Library, Batch convert, Settings, and a real-data Dashboard.
- **Project Library** — SQLite index of diagnosed/converted files; `/library` endpoints with name search and tag filter; auto-recorded on doctor/convert.
- **Batch conversion** — background job queue with live per-file progress; `/batch` + `/batch/status` endpoints.
- **Compare** in the desktop workspace — wires the existing `/diff` engine into a side-by-side panel (geometry, counts, normalized settings); STL inputs skip diff with a clear note.
- Bundled engine **sidecar** (PyInstaller-frozen, loopback + token), spawned by the desktop shell with zero orphan processes on exit.
- One-click **Windows installer** (NSIS) with the Studio Hub app icon.
- Official **Brand Identity Asset Pack** alignment across logo/icon/favicon/app-icon/hero/social SVGs, README, and landing page (7-stream spectrum, Primary Dark `#0A101C`, Inter).

### Changed
- README: product value proposition, Studio Hub hero, Input → Diagnose → Transform → Validate → Output workflow, real app screenshots, Architecture section, corrected roadmap.
- Landing page repaletted to the official palette.

### Fixed
- Clean Bambu/Orca 3MF → Snapmaker U1 conversion for a real-world corpus (112 files → 100% passed the internal structural validation gate — structurally valid U1 profile copies, not a print-success measure), incl. identity normalization, foreign-token scrub, and filament-array conform.

## [0.2.0] - 2026-06-17

### Added
- `doctor` — read-only compatibility check: will a file load cleanly on the U1, and if not, why (verdicts READY / REPAIRABLE / CONVERTIBLE / HIGH_RISK; `--json`)
- `diff` — read-only comparison of two projects (structure, geometry, settings, counts; `--json`)

### Changed
- README: badges, compatibility matrix, 30-second quick start, doctor & diff sections
- Added CONTRIBUTING guide and issue templates
- Public packaging metadata for the `snapmaker-studio` distribution

## [0.1.0] - 2026-06-17

### Added
- Repair incompatible 3MF projects into U1-ready projects (`u1convert repair --mode u1`)
- Convert STL files directly into native Snapmaker U1 projects (`u1convert repair part.stl`)
- Project integrity validation (`u1convert validate`)
- Preservation of painted and multi-colour models during repair
- Optional, reversible print-optimization profiles (`--mode optimize --opt-profile`)

### Notes
- Output is intended for Snapmaker Orca.
- OBJ/GLB input, batch processing, and a desktop GUI are planned (see the roadmap in the README).
