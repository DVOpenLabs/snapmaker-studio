# Codex handoff — preparation reliability #108

Selected task: finish the existing preparation eligibility/action contract on
[PR #108](https://github.com/DVOpenLabs/snapmaker-studio/pull/108). No redesign,
release, merge, push or duplicate PR was performed.

## Branch and exact commits

- Managed worktree: sibling `ss-codex108`, branch `codex/108-prepare-contract`.
- Exact starting SHA: `32c6fbc5d166ea0be120923cc1d0e6bf2d93a266`, the verified
  head of `fix/prepare-reliability` / PR #108. This is an unmerged task base,
  not a fresh branch from main.
- Completed implementation/tests/CI commit:
  `6e35fe607123ad371c29b187c55f560edc13d694`.
- Original handoff commit, preserved unchanged in history:
  `906b7ec6e56c5894fa5953cba5dc44995124b119`.
- Subsequent validation documentation is a new commit, not an amendment. Resolve
  its SHA with `git log -1 --format=%H -- CODEX_HANDOFF.md` before integration.

Claude's `wip/108-contracts` checkpoint
`77d777086fb82258cc4d2f405536fdf66802b84b` has an identical tree to
`b0c2e2e62c12f120de7c005d4bb19f900f7a1e1f`, already in PR #108's ancestry.
Do not cherry-pick that checkpoint again. Both refs were preserved.

## Changed files and behavior

| Path | Reason |
|---|---|
| `backend/snapstudio_core/multipart.py` | Validate retained object and part metadata before the direct-mesh early return. Unverified object settings and non-nullable part `nil` values cannot bypass eligibility. Keep existing option provenance. |
| `backend/tests/test_eligibility_contracts.py` | Generate a direct-mesh fixture from a committed base copy; drive the shared record, service/HTTP Doctor, Model Connect, validation, intelligence, compatibility, Ready Now, CLI and Prepare. Check clean direct meshes still prepare, refusal reasons stay separate, originals stay unchanged and refusals write no copy/backup. |
| `desktop/src/store/session.ts` | Reject known blocked conversion and preview calls before sending a request, including both preparation modes. |
| `desktop/src/store/session.test.ts` | Assert no request or state transition for known blocked Prepare/preview calls. |
| `desktop/src/routes/DesignInsights.tsx` | Disable both primary actions, suppress stale preview/recommended actions, and give a consistent review instruction. |
| `desktop/src/routes/LiveWorkspace.tsx` | Gate primary action, refusal retry and preview/recommended callbacks. |
| `desktop/src/components/PrepareModeChooser.tsx` | Disable settings preview for a blocked project and explain the next step. |
| `desktop/src/components/FixPlan.tsx` | Replace the blocked project's Prepare recommendation with review of the original in Orca, even when other risks fill the plan. |
| `desktop/src/routes/PrepareEligibility.test.tsx` | Exercise actual routes for disabled actions, stale previews, eligible-project controls, retry and the saturated fix plan. |
| `tools/check-source-independence.py` | Standard-library guard over tracked text and filenames, with narrow exceptions and exact coverage output. |
| `.github/workflows/ci.yml` | Run the guard before backend installation/tests in both Windows and Linux CI lanes. |
| `CODEX_HANDOFF.md` | Integration and evidence record; no product behavior. |

The refusal-test review finding did **not** reproduce as a failing baseline:
all 36 original contract tests passed because the exception prefixes its details
with common wording. The assertion was strengthened to check each actual reason.
The direct-mesh regressions did reproduce: 12 failures before the implementation,
with the clean direct-mesh positive control passing. Existing plate-count and
backup-copy review fixes were reused, not duplicated.

## Validation and evidence correspondence

All checks used this worktree's own `.venv` and `desktop/node_modules`.
These are ordinary independent directories, not shared environments/junctions.
Python 3.13, Node 24.11.0; npm reported engine-version warnings during installation,
but the actual test/build checks below passed. No dependency manifests changed.

| Check | Result | Local session evidence |
|---|---|---|
| Original eligibility baseline | 36 passed | `.codex-run/evidence/baseline-contracts.log` |
| Direct-mesh regression before repair | 12 failed, 37 passed | `.codex-run/evidence/regression-before.log` |
| Targeted preparation/backend regressions | 198 passed | `.codex-run/evidence/backend-targeted.log` |
| Full backend suite | **3047 passed, 49 skipped** | `.codex-run/evidence/backend-full.log` |
| Full desktop suite, including final fix-plan behavior | **831 passed, 72 files** | `.codex-run/evidence/desktop-full.log` |
| Final route/session regressions | **14 passed** | `.codex-run/evidence/desktop-targeted.log` |
| TypeScript and production build (`npm run build`) | **Passed**; existing chunk-size/static-dynamic-import warnings | `.codex-run/evidence/desktop-build.log` |
| End-to-end generated-fixture selfcheck | **27/27** | `.codex-run/evidence/selfcheck.log` |
| Isolated Edge route captures | **4 passed**, zero conversion requests | `.codex-run/evidence/browser-checks.json`, `prepare-blocked-{simple,advanced}-{dark,light}.png` in the same directory |
| Guard mutation/control checks | **19 passed**; real worktree mutation failed and was restored byte-for-byte | `.codex-run/evidence/guard-mutations.json` |

The full backend run includes all final executable backend/test changes. Only
explanatory comments changed afterwards. The full desktop run includes the final
runtime behavior and fix-plan regression. Its last test-only array access was
changed to match the existing TypeScript target; the subsequent 14-test run and
production build cover that exact final fixture. No full suite rerun is needed
for this documentation-only handoff.

Screenshots were generated and visually inspected in development Edge with
synthetic anonymous data. They prove the route actions/copy, **not** packaged
Tauri behavior or Orca loading. The private browser profile and Vite server used
only this session's directories and port 5188; API port 43881 was intercepted,
not a live server. Non-owned network origins were blocked. Browser and Vite were
closed by the runner; Vite's PID/command identity was verified before stopping.
Backend HTTP tests used ephemeral ports. No existing GUI/review session was used.

All test data/output and application state were under `.codex-run`, with
`SNAPSTUDIO_DATA_DIR`, `TEMP` and `TMP` set for backend runs and test-wide Orca
preset isolation retained. Existing benchmark inputs were not used or modified;
new fixtures were generated from read-only committed fixture inputs. Private
raw logs, mutation probe repo, dependencies and browser profiles remain local
and are deliberately absent from the commits.

## Source independence

Pre-edit text/filename scan: one historical research match at
`docs/innovation-fund/COMPETITOR_MATRIX.md:28`; preserved unchanged. No product
code, tests, dependency or filename matches required correction.

Run the actual CI check from the repository root:

```powershell
.\.venv\Scripts\python.exe tools/check-source-independence.py --manifest .codex-run/evidence/source-coverage.json
```

Initial delivery coverage including this handoff: **1278 tracked filenames, 871 tracked text
files, zero violations**. The exact enumerated paths are in
[source-coverage.json](.codex-run/evidence/source-coverage.json): `filenames`
contains every tracked path, `text_files` contains every scanned content path,
and `binary_content_skipped` lists known binary formats whose contents are not
text. Binary filenames are still checked. There is no source/tests directory
exception and no text size cap. A NUL byte in source cannot bypass the guard.

The only content exceptions are these exact paths:

- `docs/innovation-fund/COMPETITOR_MATRIX.md` — preserve historical research.
- `THIRD_PARTY_NOTICES.md` — preserve required attribution.

In the guard itself only the exact pattern-definition lines are allowed; other
lines and its filename are checked. Rules cover the reference name including
spacing/hyphen and case variants, both known conversion hosts, and the scoped
package/repository references. No external conversion implementation/package/API
was copied, installed or called. The mutation verification covered content,
filenames, source, tests, manifests, multiline/case variants, NUL bypass and
research-exception boundaries. All temporary prohibited mutations were removed.

## Protected worktrees and remaining Claude tasks

Paths below are sibling basenames, except the original repository. Every existing
worktree and pre-existing branch is protected; none was edited, stashed,
committed, reset, removed or rewritten by this work.

| Protected checkout | Starting HEAD |
|---|---|
| `snapmaker-studio` | `b01f7d049dc04c32df36489cf6ad5bd27d5c6b7e` |
| `ss-i39-fixes` | `96f83abec394b112f5437496ea2f4a64abe075cd` |
| `ss-i92-readiness` | `bc51aea3b982e577a7fc581fdafb394929f90478` |
| `ss-i93-i91` | `af7be233b63aca527e7a4a0058d118e185ed40c4` |
| `ss-i94-fonts` | `6de182487fa0a5ed90378a33521780bfcfeddf93` |
| `ss-i95-harness` | `1bddb802e580764744853bdc62e8d53eecac92b8` |
| `ss-p1-tabs` | `562defe2ab2bf497908039a0a03e069f18a418f2` |
| `ss-p2-guidance` | `c83ec81a6c492569247ab795e7002168ce0ab1f6` |
| `ss-p3a-scene` | `46589959d5c9f9b3accd16b8b50eba322caf48f9` |
| `ss-p3b-viewer` | `59f1a7af06519c70f4359d912137ca65b4efc6bd` |
| `ss-rel151` | `74208d7331f7c465ae41021ea9b8e6e36d947265` |
| `ss-rel151-fix` | `5d0649912b1d534d32e4d97fc4e5b8ab783a7366` |
| `ss-reliability` | `32c6fbc5d166ea0be120923cc1d0e6bf2d93a266` |
| `ss-viewer-webkit` | `6e7d8cdbc0bbac53cc572ef67e6731f09dbe6c71` |

`ss-i92-readiness` had **10 unstaged modified files** at audit time: service,
conditions, intelligence report, toolhead fit, condition-contract tests, desktop
API, printer badge and its tests, DesignInsights and Printers. They were
fingerprinted and preserved. Its pending #103 work remains Claude's work.
The original stash and all 20 pre-existing local branch heads were also recorded.

Final read-only comparison against `.codex-run/protected-before.json` passed:
**14 worktrees, 20 protected branch heads and the original stash unchanged**,
including all ten saved readiness-file hashes and its staged/unstaged diff hashes.
The result is retained as `.codex-run/evidence/protected-recheck.json`; no
unexpected changes were found. No Claude checkpoints, memory or existing evidence were changed.
Other task PRs and release gates remain pending; they were not integrated here.

## Integration into the existing PR — maintainer/Claude only

No integration or push was performed. After the remaining reviews, use the
existing PR #108 and its head branch; do not open a duplicate PR. From this
checkout, with its sibling layout:

```powershell
# Verify exact source and target before changing the PR checkout.
git rev-parse codex/108-prepare-contract
git log --reverse --format='%H %s' 32c6fbc5d166ea0be120923cc1d0e6bf2d93a266..codex/108-prepare-contract
git -C ../ss-reliability status --porcelain=v1 --untracked-files=all
git -C ../ss-reliability branch --show-current
git -C ../ss-reliability rev-parse HEAD
gh api repos/DVOpenLabs/snapmaker-studio/pulls/108 --jq '.head.sha'
```

Require a clean target checkout, branch `fix/prepare-reliability`, and both local
and PR heads equal to `32c6fbc5d166ea0be120923cc1d0e6bf2d93a266`. If any differ,
stop and reconcile that newer work read-only before integration; never overwrite
it or repeat a patch already present. If the checks match, the existing branch
can take the Codex commit chain, including validation documentation, as an ordinary fast-forward:

```powershell
git -C ../ss-reliability merge --ff-only codex/108-prepare-contract
```

Update the existing PR only through its owner's separately authorized normal
push/review workflow. No force push, history rewrite, main merge, tag or publish.
Fresh remote CI is required after that integration. Keep #108's existing plate,
backup, option-list and eligibility fixes; do not add changes from the release,
readiness, placement or viewer PRs to this preparation repair.

## Reviews and work Claude must not repeat

Outstanding: **Opus review** (already outstanding on the original #108 head),
**Fable review of the final code/copy**, **Orca GUI opening/loading of generated
copies**, and **fresh GitHub CI/review on the integrated PR head**. None is claimed
as run here. Packaged Tauri acceptance was not performed. These are review and
integration gates, not evidence that the independent local tests failed.

Do not repeat the metadata-before-early-return repair, route/session action
gates, fix-plan correction, refusal-detail assertion, generated direct-mesh
regressions, CI guard or its mutation checks. Reuse the valid test and screenshot
evidence above. Preserve #103's dirty checkout and all pending Claude tasks.

## Exact-engine Orca validation follow-up — 2026-10-12

**GUI checks remain blocked, not passed.** The supported Windows GUI runtime
could not start: first `windows sandbox failed: helper_unknown_error: setup
refresh had errors`, then `trusted Node process exited unexpectedly; kernel
reset, rerun your request`, including a no-op after reset. No Orca process was
started and no file-opening result, import-dialog observation or GUI setting
was asserted. A question requesting permission to use the existing native
isolated harness instead remains pending; elapsed time is not permission.

The `computer-use` skill's `docs/guidance.md`
requires: “Use only the Computer Use JS APIs for Windows app automation.” This
is the procedural blocker for executing the prepared fallback. The harness copy
is syntax-checked, uses private `--datadir` and TEMP/TMP, adds PID/start-time/path
verification and a byte-hash tripwire for the production profile, and retains
private evidence rather than recursively deleting it. It was **not executed**.

Evidence independent of that blocker is in
[orca-6e35fe6-results.json](docs/testing/prepare-contract/orca-6e35fe6-results.json).
Raw generation, comparison records, outputs and unexecuted harness are in the
new private lane `.codex-run/orca-gui-6e35fe6-20261012/`. Existing benchmark and
creator-pair folders were read-only; none of their code/evidence was edited.
One earlier local protection-summary artifact was inadvertently refreshed during
the initial check; its previous result was restored from the prior recorded tool
output, and this run's checks now use only the new lane's evidence paths.

The installed binary is **Snapmaker Orca 2.4.0**, executable SHA-256
`d85b864427135fe98903bdddd999e8259e4f96d1f7c012e19c0a80d3e252d1b87`.
The exact implementation commit
`6e35fe607123ad371c29b187c55f560edc13d694` was exported with `git archive`;
**all 327 exported backend files were verified against their Git blobs**. The
existing worktree's independent `.venv` supplies dependencies, while `-I` plus
the explicit exported-backend path selects this committed engine. No source
changes or unrelated placement/readiness/viewer work were made.

### Generated-file results; these are not GUI results

Both Preserve and Recommended were generated for every successful case below.
Objects are settings objects; instances are root build items; plates are retained
plate metadata records. These counts do not establish Orca's rebuilt membership.

| Case | Objects / instances / plate records | Painting retained in the archive | Result in each mode |
|---|---|---|---|
| C02 | 2 / 2 / 1 | 196 support-paint attributes | Generated; GUI pending |
| C03 | 1 / 1 / 1 | 92,087 colour-paint and 2,306 support-paint attributes; repeated part records kept | Generated; GUI pending |
| C04 | 6 / 6 / 5 | 354 seam-paint attributes | Generated; GUI pending |
| C06 | 2 / 2 / 2 | No paint attributes in the source | Generated; GUI pending |
| D01 clean direct mesh | 1 / 1 / 0 | No paint on the built tetrahedron; exact test fixture also retains unused inherited mesh members | Generated; GUI pending |
| C11a / C11b creator pair | 2 / 2 / 2 each | 472,906 colour-paint and 12,330 support-paint attributes each | Generated; GUI pending |

The whole bounded fixture run produced **24 outputs and 6 refusals** (15 inputs,
two modes). C09 was refused for unreadable non-nullable part values. Synthetic
D02 (direct-mesh `nil`) and D03 (direct-mesh unverified object setting) were also
refused. **Every refusal produced no output; all 30 calls produced no backup.**
All twelve benchmark/creator originals and every input copy remain byte-identical.
Original hashes and individual output hashes are in the new JSON evidence.

For successful outputs, object count, build-item transforms, plate records,
per-object settings, all mesh vertex/triangle values and painting attributes were
checked independently. Non-root mesh members are byte-identical. These checks
establish what the files contain, not the runtime interpretation of every value.

### Regression distinction and limitations

The 22 benchmark/creator outputs were compared with fresh outputs from the
verified pre-Codex task base `32c6fbc5d166ea0be120923cc1d0e6bf2d93a266`.
Every archive member has identical contents in that comparison. Thus **no new
file-output regression from the Codex implementation was found**. This is not
a comparison requiring byte identity to the creator's U1 project. The synthetic
direct-mesh controls are covered by the earlier behavior regressions and the
new generation/refusal checks; their GUI loading is not established.

C11's inherited placement and support limitations remain visible in the files:
source-grid build transforms are kept instead of the creator U1 file's positions;
Recommended omits support keys from the process declaration while the raw
`enable_support` value can still be `1`. The existing creator-pair GUI/source
evidence explains why that can resolve to supports off in Orca. Current GUI
support state, plate membership, out-of-bounds notices, customized-preset prompts
and import errors were **not observed in this run**. No placement, support-policy,
flush-matrix or prime-tower correction was attempted here.

Paint bytes retained does not prove supports will be generated. Opening alone
would not establish slicing correctness, collision freedom, correct filament
mapping or a successful print. No uploads, printer calls or physical printing
were performed. No GUI interaction with the user's Orca profile occurred.

Remaining gates: runtime repair or explicit fallback authorization, actual Orca
GUI checks on these exact outputs, **Opus/Fable reviews**, and fresh existing-PR
CI after separately authorized owner integration. The earlier local unit/build
evidence remains valid; only documentation was added, so those suites were not
rerun. The final source scan and protected-checkout comparison for this follow-up
are recorded under the new lane's `evidence/` directory.


## Authorized native Orca preflight — 2026-10-13

The maintainer explicitly authorized native PowerShell/.NET UI Automation for
this isolated loading lane. This authorization remains valid; it does not grant
permission to touch unrelated processes or override approval-review rejections.

**GUI validation is still not run.** The preflight found an existing unrelated
Snapmaker Orca process without this lane's private `--datadir`. The maintainer's
instruction requires refusing to start in that state. The process was left
untouched: no Orca launch, GUI input, loading assertion or prompt acknowledgement
was performed. Close the existing instance normally before resuming the control.

The active private harness file was absent. It was restored from the preserved
pre-authorization copy; both old copies and existing evidence remain intact.
The runner now scopes acknowledgements to known import modals and their OK/Close
buttons, removes generic Yes handling, checks the owned PID/start time/path and
foreground before input, and stops on unknown/authentication/legal/security
prompts. The native seed leaves privacy agreement false. Arbitrary post-load
hooks are disabled. PowerShell parsing passed; native runtime behavior remains
untested until the control is actually run.

New private evidence is under `.codex-run/orca-gui-6e35fe6-20261013/`.
The anonymized preflight is
[orca-native-6e35fe6-preflight.json](docs/testing/prepare-contract/orca-native-6e35fe6-preflight.json).
Its harness hash binds this preparation state. The preflight source guard
reported 1279 tracked filenames / 872 text files / zero violations; final guard
coverage may increase with this new documentation. Protected-state preflight
confirmed 14 worktrees, 20 branch heads and the original stash unchanged.

Resume with D01 Preserve, using a fresh output directory and private data/TEMP.
Continue the existing bounded outputs only after that control demonstrates
isolation and capture. Do not regenerate or rerun passed file-level checks
without a relevant change. Earlier engine and evidence commits remain intact.

Remaining gates: existing Orca closure, actual control and GUI checks,
Opus/Fable reviews, and owner integration into #108 followed by fresh PR CI.
No runtime source, integration, push, main merge, tag or publication occurred.


## Native Orca GUI results — 2026-10-13

This supersedes the earlier **not run** preflight status above. After the
maintainer closed the unrelated Orca instance, the authorized native harness
ran using copied exact-commit outputs, private data/TEMP directories and owned
PID/path/start-time/foreground checks. The fallback runtime now works.

**Partial result: two unique outputs loaded, one stopped at a security prompt,
and 21 were not run.** Preserve and Recommended D01 both reached the loaded
project, with matching titles, valid captures and object-list observations.
Orca showed Snapmaker U1, 0.4 mm nozzle, 0.2 mm layer height and 0.25 mm first
layer height. The object list showed `Plate 1`, `Outside`, `Sample`, and Orca
reported an out-of-bounds/height warning. This direct-mesh fixture's built
tetrahedron has no placement transform and stays at its source origin. Loading
is proven; printable placement is not. No repositioning or source fix was made.
Supports and filament mapping were not inspected.

C02 Preserve showed the newer-configuration/value-replacement information
notice naming `nozzle_volume_type`. Only that identified notice's modal OK was
acknowledged. It then showed **Customized Preset**, asking for confirmation that
embedded G-code is safe. The maintainer's explicit stop-on-security-prompt rule
applied: this dialog was left untouched, its `Don't show again` checkbox stayed
unchecked, and the batch stopped. C02 completed loading, effective settings and
plate membership remain unverified. No safety judgement about that preset is
claimed. A scoped permission question is pending; no approval is inferred.

Three harness versions and the separate attempts remain in the private lane.
The first bounded run loaded D01 Recommended but aborted on the following C02
startup identity assertion; its final profile comparison did not run. That is
an incomplete technical attempt, not an acceptance pass. The next attempt
stopped because native text omitted the body of a known information notice;
combining captured OCR with native text fixed detection. The final attempt
then reached the real security confirmation and correctly stopped. No
previous failed attempt is presented as a successful candidate check.

Completed control-01/control-02 and bounded-02/bounded-03 reports each say the
whole production-profile hash was unchanged. A final preservation-only hash
check found all **12 originals, 15 input copies and 24 generated outputs
unchanged**; the passed generation/file checks were not rerun. Closure used
normal close/Discard when possible, otherwise only the independently verified
task-owned PID. No Orca process remained after cleanup. No slicing, uploads,
printer connections, saves over originals or source edits were performed.
Private profile seeding does not itself establish a network-isolation test.

Anonymized tracked evidence:
[orca-native-6e35fe6-results.json](docs/testing/prepare-contract/orca-native-6e35fe6-results.json).
Raw captures, OCR, identities, harness snapshots and integrity hashes remain
under `.codex-run/orca-gui-6e35fe6-20261013/`, untracked. Earlier commits remain
intact. The protected-state and source-guard final checks are recorded in that
lane's `evidence/` folder. Final checks: all 14 protected worktrees, 20 branch
heads and the original stash unchanged; source guard 1281 filenames / 874 text
files / zero violations. No push, integration, merge, tag or publication.

Remaining gates: a decision on this specific security confirmation, the
remaining bounded GUI checks, Opus/Fable reviews, and separately authorized
owner integration into existing PR #108 followed by fresh CI. Opening files
does not establish slicing correctness or a successful physical print.

## Isolated Orca GUI continuation — 2026-10-13

The maintainer explicitly authorized acknowledging only the already observed
`Customized Preset` embedded-G-code warning for copied test outputs. The
permission does not certify that the embedded G-code is safe. The suppression
checkbox must remain unchecked. The earlier raw prompt capture is preserved.

A fresh private runner copy was prepared with a narrow match for that exact
dialog title and message, a verified unchecked checkbox, and exactly one visible
modal-owned OK button. Authentication, legal prompts and every other security
confirmation remain stop conditions. The runner parsed successfully. Its hash
and implementation evidence are in
[orca-native-6e35fe6-focus-block.json](docs/testing/prepare-contract/orca-native-6e35fe6-focus-block.json).

**The resumed GUI run stopped before input.** It launched only the private C02
Preserve copy, verified the owned executable, PID and start time, then detected
that the foreground belonged to another window. The foreground guard stopped
all GUI input; no dialog or project capture occurred, no prompt was
acknowledged, and the owned Orca process closed normally. The copied input hash
and production-profile signature matched before and after. The process was gone
at the final check. No unrelated process was stopped.

This attempt establishes no loading, plate membership, import prompt or
settings result. It does not complete or replace the earlier two D01 loads. Of
the 24 planned unique outputs, those two D01 variants are the only completed
loads; the fresh C02 Preserve attempt did not complete, and the other 21
outputs remain unrun. The earlier C02 security dialog observation remains valid
as a prompt observation only; it was not acknowledged in this continuation.

The foreground stop is the current GUI blocker. Do not bypass it with input to
another window. Resume only when the owned Orca window can pass the foreground
identity check. On a successful run, record loading, dialogs, plate membership
and visible settings as separate observations. C11 source-grid placement and
Recommended support-setting behavior remain the already known limitations; no
new evidence or correction for them was produced here. No new product
regression was established. This GUI lane does not test slicing correctness,
G-code execution or print success.

Private raw runner output and identities are under
`.codex-run/orca-gui-6e35fe6-20261013/bounded-04/`; earlier prompt captures
remain under `bounded-03/` and were not changed. The tracked source-independence
check passed with **1281 filenames, 874 text files and zero violations**.
The final protected-state recheck found **14 worktrees, 20 pre-existing branch
heads and the original stash unchanged**, with no unexpected changes. Only the
anonymized evidence and this handoff were added to the tracked tree; prior
implementation and documentation commits remain intact.

Remaining gates are actual completion of the bounded Orca GUI set when the
foreground guard can pass, Opus/Fable reviews, and owner integration into the
existing PR #108 followed by fresh CI. No integration, push, merge, tag or
publication occurred.
