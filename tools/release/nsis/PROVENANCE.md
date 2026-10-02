# Vendored NSIS template: provenance (issue #55)

This directory holds the Tauri NSIS installer template used to build the **acceptance-identity** installer
("rewrap"). It is derived from the stock Tauri template that produced the released Snapmaker Studio installers.

## Upstream source

| Item | Value |
|---|---|
| Crate | `tauri-bundler` **2.9.3** (not "2.11.3": no `tauri-bundler` 2.11.3 exists; the number 2.11.3 is the `tauri-cli` version, see below) |
| Why 2.9.3 | `desktop/package-lock.json` pins `@tauri-apps/cli` 2.11.3. The `tauri-cli` 2.11.3 crate's own `Cargo.lock` locks `tauri-bundler` **2.9.3** (`checksum = 216a33c0...c195c43` in that lock file). The npm CLI is a prebuilt binary of that crate, so 2.9.3 is the bundler that generated the released installers. This mapping is derived from the published crate, not from the npm binary itself. |
| Source URL | `https://static.crates.io/crates/tauri-bundler/tauri-bundler-2.9.3.crate` |
| Crate sha256 | `216a33c05235194af3afc49cecccc2416e7651af7514cda35d7b2509a91400f3` |
| Checksum source | crates.io sparse index (`https://index.crates.io/ta/ur/tauri-bundler`, line for `vers` 2.9.3, field `cksum`) and the `tauri-cli` 2.11.3 `Cargo.lock`; the downloaded crate was hashed locally and matches both. |
| `tauri-cli` 2.11.3 crate sha256 (for the mapping above) | `efa0d07c7dc71b7c8ae5ba1b536080c379230934dcfe54d784772a5f3bd8c61b` (index `cksum`, matches the local hash) |
| Template path inside the crate | `src/bundle/windows/nsis/installer.nsi`, `src/bundle/windows/nsis/utils.nsh`, `src/bundle/windows/nsis/languages/English.nsh` |

The local copy of `installer.nsi` that older docs referenced (0.9.0, with local paths) is **not** used.

Upstream file hashes (sha256 of the bytes in the crate):

| File | sha256 |
|---|---|
| `installer.nsi` | `20f4ecc730defb71f1342eaeaec4021df13be3d843abba0effe88ea5835fa079` |
| `utils.nsh` | `b27b407f886cca738e44e774f15e6b556b43ce52557a7c8891ee4eca7dd8013d` (shipped unchanged) |
| `languages/English.nsh` | `1dad40b023707a61f828db1e184d9c1b029cb530c2dbbc4790db265872ef7b5e` |

## Shipped files and what is hashed

`template/` contains exactly `English.nsh`, `installer.nsi`, `utils.nsh` (any other file makes the tooling refuse).
`.gitattributes` in this directory sets `-text`, so Git never rewrites their bytes.

| Shipped file | sha256 |
|---|---|
| `template/English.nsh` | `1925525cdf5aa64ca48146179cf90821353b87a705f261fc1562d0fe4a8b8e0e` |
| `template/installer.nsi` | `2af0c4e457f2b8fc11e1cf7c625f7518d613412153196a570fcde2334a9d8097` |
| `template/utils.nsh` | `b27b407f886cca738e44e774f15e6b556b43ce52557a7c8891ee4eca7dd8013d` |

**`Attestation.PinnedTemplateSha256`** (in `tools/lib/HarnessIdentity.psd1`) is the sha256 of this exact UTF-8 text
(no BOM, LF line endings, trailing LF), one line per file, sorted by ordinal name comparison:

```
English.nsh:<sha256 of the file bytes>
installer.nsi:<sha256 of the file bytes>
utils.nsh:<sha256 of the file bytes>
```

Pinned value: `d30f5f9d4bc40902addbc895e4211498612c6f0c567a54738c47fe3403ce1028`.
Computed by `Get-TemplateBundle` in `tools/release/lib/Rewrap.psm1`. `template.patch`, this file and the rendered
`installer.final.nsi` are **not** part of the pinned hash. The rendered script (placeholders replaced with acceptance
values, run-specific paths) is not pinned; instead its sha256 is recorded in `build-inputs.json`, it is scanned on every
build (delete-target enumeration plus forbidden-construct scan) and re-hashed before and after the compile (see the build
sequence below).

## Modifications relative to upstream (complete list)

`template.patch` is the unified diff of `template/` against the upstream files (`utils.nsh` is unchanged and has no hunk).

1. **Identity parameterization (a).** The identity defines (`PRODUCTNAME`, `MANUFACTURER`, `BUNDLEID`,
   `MAINBINARYNAME`, `VERSION`, ...) stay `{{placeholder}}`s exactly as upstream. `rewrap_installer.ps1` renders them
   from `tools/lib/HarnessIdentity.psd1` (Acceptance block): product `Snapmaker Studio Acceptance`, manufacturer
   `SnapmakerStudio-Acceptance`, bundle id `com.snapmakerstudio.acceptance`, main binary
   `snapmaker-studio-acceptance-desktop.exe`. Two placeholders are new (`sidecar_name`, `sidecar_path`, replacing the
   `{{#each binaries}}` blocks) plus `language` / `language_file` (replacing `{{#each languages}}`).
2. **Template-engine blocks resolved for the one fixed configuration** (no Handlebars engine is used): file
   associations, deep links, resources, installer hooks, signed plugins and the multi-language loops are removed
   because the released product configures none of them (`desktop/src-tauri/tauri.conf.json`: `installMode`
   `currentUser`, one external binary, English).
3. **B1: app-data deletion compiled out entirely.** Removed: the "Delete the application data" checkbox
   (`un.ConfirmShow`, `un.ConfirmLeave`, the `deleteAppData` LangString), `RmDir /r` of `$APPDATA\<bundle id>` and
   `$LOCALAPPDATA\<bundle id>`, the `DeleteRegKey` of the remembered-location keys and of the `Installer Language`
   value, the Start Menu **subfolder** variants (the Start Menu page, `$AppStartMenuFolder`, `RMDir "$SMPROGRAMS\..."`),
   all `HKLM` / `SHCTX` / `perMachine` / `both` deletes. What remains deletes only: the acceptance main exe,
   `snapstudio-api.exe`, `uninstall.exe`, `$INSTDIR`, the exact acceptance `.lnk` files in `$SMPROGRAMS` and `$DESKTOP`,
   `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\Snapmaker Studio Acceptance`, and the acceptance Run value.
   Behavioural note: as in the released product (checkbox unselected), the remembered-install-location key is left in
   place after an uninstall.
4. **S6: WebView2 installation compiled out** (the WebView2 section, bootstrapper download, `NSISdl::download`).
   Workstation lanes require the WebView2 runtime to be present (read-only preflight elsewhere).
5. **N1: no app launches from the installer.** The finish-page "Run" action and the `/R` silent relaunch
   (`nsis_tauri_utils::RunAsUser`) are removed so the installer cannot start the app outside the fail-closed launcher.
6. **Reinstall page compiled out entirely.** The upstream page (and its WiX-migration loop) ran a registry-sourced
   `UninstallString` through `ExecWait`, outside the guard's uninstaller authorization. The script now contains **no
   process-execution instruction of any kind** (`Exec`, `ExecWait`, `ExecShell`, `nsExec`, `RunAsUser`); the build
   fails if one appears. Reinstalling over an existing acceptance install just overwrites files; the harness
   uninstalls through the guarded path first. The old-main-binary rename logic is removed too (fresh identity).
7. Dead code removed so the build has no warnings (`StrFunc.nsh`/`${StrCase}`/`${StrLoc}` used only by the WiX loop,
   the unused `Skip` function, an unused label), and unused defines removed (WebView2 mode/paths, signing command,
   hooks).
8. `English.nsh`: only the `deleteAppData` LangString is removed.

Retained on purpose: per-user execution level, shortcuts (`/NS` skips them), `/P` `/S` `/UPDATE` handling.

Known fidelity gap: the released installers carry the product icon and Tauri's header/sidebar defaults; the rewrapped
installer uses NSIS defaults for installer/uninstaller icon (the icon is not recoverable from the extracted payload).
The installed files, registry layout, shortcut names and AUMID behaviour match the stock template for the acceptance
identity.

## Pinned tools (`tools/release/tools.lock.json`)

| Tool | Pin | Checksum source (what it does and does not prove) |
|---|---|---|
| 7-Zip 26.03 `7zr.exe`, `7z2603-extra.7z`, `7z2603-x64.msi` | sha256 in the lock | GitHub release-asset digest reported by the GitHub API for `ip7z/7zip` tag `26.03`. This is a hash published through GitHub, **not** a publisher-signed checksum. |
| `7za.exe` (from the extra pack), `7z.exe` / `7z.dll` (the MSI's `_7z.exe` / `_7z.dll`, renamed; the MSI is only unpacked, never run), and the whole unpacked 7-Zip folder (tree hash over 7zr.exe, 7za.exe, 7z.exe, 7z.dll) | sha256 / `sevenZip.treeSha256` in the lock | **Trust-on-first-use** of the unpack step: recorded from the first unpack of the pinned archives. The archives themselves are pinned above. |
| NSIS 3.11 `nsis-3.11.zip` | sha256 in the lock | SourceForge file listing for `NSIS 3/3.11` (sha256 `c7d27f78...394fa1`); its sha1 `ef7ff767e5cbd9edd22add3a32c9b8f4500bb10d` equals `NSIS_SHA1` pinned in tauri-bundler 2.9.3 for the same zip. SourceForge-hosted metadata, not a publisher signature. |
| NSIS unpacked tree | `treeSha256` + file count in the lock | **Trust-on-first-use** of the unpack step (hash over every file of the unpacked tree, re-verified at execution time before each compile). |
| `nsis_tauri_utils.dll` | sha256 `5ba143b5db4a87d32d6e7802e033330aae56cbceabe0d1e3ba41948385ad4709` | Taken from the released v1.2.0 installer and cross-checked: the upstream release asset `nsis_tauri_utils-v0.5.3/nsis_tauri_utils.dll` has the same sha256, and its sha1 `75197fee3c6a814fe035788d1c34ead39349b860` equals `NSIS_TAURI_UTILS_SHA1` in tauri-bundler 2.9.3. |

Every download is hashed before it is unpacked. Each run then works from a **private and verified snapshot** of the tools:

- `Assert-PinnedTools` (after install into the shared cache): `7z.exe`, `7z.dll` and the **whole 7-Zip folder** (`sevenZip.treeSha256` + file
  count), plus the NSIS tree hash and file count.
- `New-ToolSnapshot` (once per run): copies the whole 7-Zip folder and/or the whole NSIS tree (including `Bin\makensis.exe`, layout preserved) from
  the cache into a fresh, exclusively created `<harness>\extract\<runId>\tools` (7-Zip, extraction) or `<harness>\rewrap\<runId>\tools`
  (7-Zip + NSIS, build), outside any build directory. Regular files only; a reparse point (file or directory) on the source or destination is
  refused. The **copy** is hashed once against the lock (tree hash + file count, `makensisSha256`, 7z.exe / 7z.dll). Population and snapshotting of the
  shared cache are serialized by a named mutex, so a concurrent run cannot rebuild the cache while another run snapshots it.
- `Assert-ToolVerified`: exe hash; for `7z.exe` also `7z.dll` and the whole 7-Zip folder tree; for `makensis.exe` also the full NSIS tree hash and file
  count (of the snapshot being used).
- `Start-PinnedTool` (the single launch site): accepts only the exact path of a registered tool (cache dir or snapshot, no reparse points) and re-checks
  the exe hash, then launches. 7-Zip (listing, extraction, final listing) and makensis are launched **from their snapshots**, never from the cache.

"Private and verified" is **not** "immutable". Exact residual (accident control, not adversary control): a principal with write access to the harness
root who races the run with change-and-restore (modify, let the tool run, put the bytes back before the next check) is not detected, and compile-time side
effects of a hostile include are not undone. Both are out of scope for an accident control.

Nothing is installed globally and nothing is added to `PATH`; tools live under `<harness root>\tools` (or an explicit `-ToolsDir` that passes the guard's
positive override allow-list).

## makensis build sequence and hardening

The consumed set is the verified set: makensis runs from the private snapshot and reads only a build directory whose complete namespace is an exact
allow-list. The order is fixed:

1. Snapshot the tools (see above). Copy the template files into the private build directory and read each staged file **once**; those bytes are
   verified per file and as a bundle against `PinnedTemplateSha256`. The attestation's `template.sha256` is that verified bundle hash.
2. Copy the payload (asserting on the **copy** that its sha256 equals the manifest value) and the plugin dll (bytes equal to the pinned hash). Render
   `installer.final.nsi` from the template buffer; the same rendered text is written, hashed and scanned (no second read).
3. Record the full inventory (`build-inputs.json`, run dir, side metadata; the attestation schema is unchanged). `Get-BuildDirInventory` enumerates **files
   and directories** and accepts exactly: `installer.final.nsi`, `installer.nsi`, `utils.nsh`, `English.nsh`, `plugins\<lock dll>`,
   `payload\<manifest names>` and an (empty before launch) `private-appdata\`. Any extra entry (for example a planted `MUI2.nsh` that would shadow the
   stock include, an empty directory) and any reparse point (including a junction) is refused.
4. Scan (delete-target enumeration and the forbidden-construct scan, see below).
5. `Assert-ToolVerified` for the snapshot makensis (exe + whole snapshot tree), a cheap build-namespace check (payload by size), then launch
   (`Start-PinnedTool`, exe-hash re-check).
6. After **every** compiler exit, including a failing one: the full build-namespace inventory (payload hashed) and the snapshot NSIS tree + makensis exe are
   re-validated. On any mismatch the compiled output and any attestation are deleted and the build fails (integrity failure takes precedence over the
   compiler error). The attestation is written only after this validation and the compiled-installer checks succeed.

The rendered `installer.final.nsi` is **not** part of `PinnedTemplateSha256` (it carries run-specific paths and values); its hash is recorded in
`build-inputs.json`, it is scanned, and it is validated by the post-exit inventory.

Other controls:

- `-NOCONFIG` is always passed (`Get-MakensisArguments`) and is the **primary** control: neither a user `nsisconf.nsh` nor the tree's own
  `nsisconf.nsh` (stock: only an empty `MUI_NSISCONF` macro) is loaded. Output is unchanged for the stock tree.
- makensis 3.11 reads the `APPDATA` environment variable, so pointing `APPDATA` and `LOCALAPPDATA` at a private build subdirectory for the
  child (process-scoped, restored afterwards) is a real **second** control. `NSISDIR` / `NSISCONFDIR` are cleared for the child as well
  (`Invoke-IsolatedMakensis`). The env-gated integration test compiles from a snapshot while the original tree is renamed away and with a hostile ambient
  `nsisconf.nsh` / `NSISDIR`, and shows (negative control) that the same hostile ambient config breaks a compile that does not use this isolation.
- The source installer is copied into `<harness>\extract\<runId>\source\`, hashed there against the expected value / SHA256SUMS, re-hashed
  before listing and again before extraction, and only the copy is read.
- `<harness>\extract\<runId>\raw` (which holds the 7-Zip-synthesized production `uninstall.exe`) is removed in a `finally`, i.e. on every
  failure path as well. Links found inside it are removed, never followed, and the original exception is preserved.
- Static scan of the final script and its includes (the build fails on any finding): no process-execution instruction of any kind; no
  `System::Call` to process APIs (`CreateProcess*`, `ShellExecute*`, `WinExec`, `CreateRemoteThread*`, `LoadLibrary*`,
  `WriteProcessMemory`, `NtCreateUserProcess`); no `CallInstDLL` / `RegDLL` / `UnRegDLL`; no `!addplugindir` other than
  `${ADDITIONALPLUGINSPATH}`; no `!system` / `!execute` / `!finalize` and similar; and only the plugin calls on an explicit allow-list
  (the plugins the template actually uses). A new plugin call fails the build.

Accepted, uncaught residuals (documented, not claimed closed): change-and-revert of any verified file between two checks; a redundant staged-bundle
pin check and the attestation's template-hash source cannot be distinguished by a test (the values are equal by construction); compile-time side effects of
a hostile include before the post-exit check detects it.
