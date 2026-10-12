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
- This handoff is a separate documentation commit. Its exact SHA is available
  with `git log -1 --format=%H -- CODEX_HANDOFF.md`; it is also the delivered
  branch tip. Resolve it before integration and keep that SHA with the review.

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

Final coverage including this handoff: **1278 tracked filenames, 871 tracked text
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
can take the two Codex commits as an ordinary fast-forward:

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
