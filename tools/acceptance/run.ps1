#requires -Version 7.0
# Installed-build acceptance for Snapmaker Studio - REWRAPPED ACCEPTANCE-IDENTITY lane.
#
# Installs a REWRAPPED acceptance-identity installer (tools/release/rewrap_installer.ps1) into a
# harness-owned directory, launches the installed application with its WebView2 opened for remote
# debugging, drives the real UI over CDP, then uninstalls and proves the harness left nothing behind.
#
# WHAT THIS PROVES, AND WHAT IT DOES NOT (issue #55): these checks prove the shipped payload (exe + frozen
# sidecar, renamed main binary) under the ACCEPTANCE identity. They do NOT prove the production installer:
# production registration, shortcut creation, default-path install/upgrade/uninstall are proven only by the
# disposable CI lanes. Every plumbing step (install, launch, uninstall, cleanup) is the shared fail-closed
# lane in tools/harness/HarnessLauncher.psm1; this script keeps only the acceptance checks themselves.
#
# Why this exists: every capability check before this ran against the dev server.
# That proves the feature works; it does not prove the installer ships it. This
# runs the shipped exe and the frozen sidecar.
#
# SAFETY, and these are not negotiable:
#  * Every process this script starts is tracked by PID and start time. Close is graceful first; a
#    force-kill only ever targets a tracked pid whose start time and image path still match. Never by
#    name. A Snapmaker Orca or other user process is never touched.
#  * The app runs with an isolated WebView2 profile and an isolated engine data directory, passed ONLY
#    to the child process (never through this session's environment), so the maintainer's own library,
#    recent files and settings are neither read nor modified.
#  * The production app must not be running and its update auto-check must be off (or its state file
#    absent); otherwise the lane refuses to start. Production state is read-only here: a tripwire reports
#    any change and fails the run, it never restores or deletes anything.
#  * The installer is /S /NCRC /NS only (no shortcuts, never /P, no app-data flag) into
#    <harness root>\install\<runId>. Nothing needs administrator.
#
# Usage (the installer is always a REWRAPPED acceptance installer; there is no auto-discovery):
#   pwsh -File tools/acceptance/run.ps1 -InstallerPath <rewrapped installer> -AttestationPath <its attestation>
#        [-UpgradeFromInstallerPath <rewrapped OLD installer> -UpgradeFromAttestationPath <its attestation>]
#        [-KeepInstall] [-SpoolmanUrl host:port] [-BambuddyUrl host:port] [-SpoolEasePort 9403]
#   or let the lane rewrap a verified real installer first:
#        -RealInstaller <path> -ExpectedSha256 <sha256> -SourceVersion <semver> [-Sha256SumsPath <path>]
#   (upgrade-from real installer: -UpgradeFromRealInstaller/-UpgradeFromExpectedSha256/-UpgradeFromSourceVersion and its own
#    -UpgradeFromSha256SumsPath; the primary SUMS file is never reused for it)
#   An upgrade here is rewrapped OLD -> rewrapped NEW under the acceptance identity; it is NOT a
#   production upgrade claim.
#
# v1.2: this run now also drives the spool-note and nozzle-confirmation phases
# in checks.mjs (W1-W9), no extra parameter needed - they run against the U1's
# stock placeholder host, with no printer present. A3.7: the acceptance.json
# report is now also swept for bare/bracketed IPv6 and IPv4 addresses, and the
# run fails outright if a supplied provider address survives redaction.

[CmdletBinding()]
param(
    # A REWRAPPED acceptance-identity installer and its attestation (both required together).
    [string]$InstallerPath,
    [string]$AttestationPath,
    # Or: a verified real installer to rewrap first (tools/release/rewrap_installer.ps1 is the only thing that touches it).
    [string]$RealInstaller,
    [string]$ExpectedSha256,
    [string]$Sha256SumsPath,
    [string]$SourceVersion,
    [int]$DebugPort = 9333,
    [switch]$KeepInstall,
    # A previous REWRAPPED installer (acceptance identity). When given, it is installed first and its settings and
    # library are checked for survival across the upgrade. This proves rewrapped-OLD -> rewrapped-NEW only.
    [string]$UpgradeFromInstallerPath,
    [string]$UpgradeFromAttestationPath,
    [string]$UpgradeFromRealInstaller,
    [string]$UpgradeFromExpectedSha256,
    [string]$UpgradeFromSourceVersion,
    # SHA256SUMS that lists the OLD installer. Separate from -Sha256SumsPath: the primary SUMS is never reused for upgrade-from.
    [string]$UpgradeFromSha256SumsPath,
    # A material provider on this network, when one is available to test against.
    # Optional: without it the provider checks still prove the frozen build carries
    # the route, refuses an address that is not local, and claims nothing about
    # remaining filament. With it they prove the whole path inside the installed app.
    [string]$SpoolmanUrl,
    # A second provider. Studio normalises both into one contract, so with both
    # supplied the run also proves that equivalent facts produce equal decisions
    # in the installed build rather than only in the test suite.
    [string]$BambuddyUrl,
    [int]$SpoolEasePort = 9403,
    # Ports for the two throwaway probe servers this script owns. One counts the
    # requests it receives, which is how "no provider is configured" becomes a
    # measurement; the other answers every request with a redirect to a public
    # host, which is the only way to prove the shipped build refuses to follow
    # one off the local network.
    [int]$ProbePort = 9401,
    [int]$RedirectPort = 9402
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Import-Module (Join-Path $PSScriptRoot "..\harness\HarnessLauncher.psm1") -Force -DisableNameChecking
$checks = @()

function Add-Check($name, $ok, $detail = "") {
    $script:checks += [pscustomobject]@{ name = $name; ok = [bool]$ok; detail = $detail }
    $tag = if ($ok) { "PASS" } else { "FAIL" }
    Write-Host ("{0}  {1}{2}" -f $tag, $name, $(if ($detail) { "  - $detail" } else { "" }))
}

# Lane start: lock, preflights (production idle, update auto-check off/absent, WebView2 present, port free),
# tripwire baseline, and authorisation of every installer. Installs nothing. Throws (lock released) on any refusal.
$laneArgs = @{
    InstallerPath = $InstallerPath; AttestationPath = $AttestationPath
    RealInstaller = $RealInstaller; ExpectedSha256 = $ExpectedSha256; Sha256SumsPath = $Sha256SumsPath; SourceVersion = $SourceVersion
    UpgradeFromInstallerPath = $UpgradeFromInstallerPath; UpgradeFromAttestationPath = $UpgradeFromAttestationPath
    UpgradeFromRealInstaller = $UpgradeFromRealInstaller; UpgradeFromExpectedSha256 = $UpgradeFromExpectedSha256; UpgradeFromSourceVersion = $UpgradeFromSourceVersion; UpgradeFromSha256SumsPath = $UpgradeFromSha256SumsPath
}
$lane = Start-HarnessLane -Name "acceptance" -Kind acceptance @laneArgs -DebugPort $DebugPort -KeepInstall:$KeepInstall
$laneLabel = if ($lane.Upgrade) { "rewrapped OLD -> rewrapped NEW acceptance-identity installers (not a production upgrade)" } else { "rewrapped acceptance-identity installer" }
Write-Host "Lane: $laneLabel"

# --- prepare -----------------------------------------------------------------
# From here on the harness lane owns an install and a lock: everything runs inside try/finally so the
# uninstall / recovery / tripwire cleanup ALWAYS runs (including with -KeepInstall, which skips the uninstall and the recovery).

$WorkDir    = $lane.RunDir
$installDir = $lane.InstallDir
$profileDir = $lane.ProfileDir
$dataDir    = $lane.DataDir
$outDir     = $lane.EvidenceDir
$appExe     = $lane.AppExe
$sidecarExe = Join-Path $installDir "snapstudio-api.exe"
$sample     = Join-Path $repo "examples\demo_u1_showcase.3mf"
$sampleWork = Join-Path $WorkDir "demo_u1_showcase.3mf"
$result     = $null
$probeHandle = $null

function Stop-Tracked {
    # Graceful close first, then a VERIFIED force-kill of tracked pids only (never by name).
    Stop-HarnessApp -Lane $script:lane | Out-Null
    Start-Sleep -Seconds 3
}

function Start-App([string[]]$AppArgs = @(), [double]$Settle = 0, [string]$Label = "app") {
    # The one launch path: warm-up, relaunches and every phase use it (fail-closed launcher).
    return Start-HarnessApp -Lane $script:lane -Arguments $AppArgs -SettleSeconds $Settle -Label $Label
}

try {
# Work on a copy so the repository fixture is provably never written to.
Copy-Item $sample $sampleWork -Force
$sampleHashBefore = (Get-FileHash $sampleWork -Algorithm SHA256).Hash

# A sliced job. Studio does not slice, so the one input the installed build
# cannot make for itself is written here - shaped exactly like real Snapmaker
# Orca output from a physical U1.
# A painted project. Painting is the one thing a beginner cannot see in a file and
# Studio now reads before slicing, so the installed build is asked to read it from
# the frozen engine it actually ships.
#
# Two objects that cannot meet on a layer: one at the bottom painted with filament
# 2 and printing in filament 2, one thirty millimetres up painted with filament 3
# and printing in filament 3. The answers are therefore known before the app is
# asked - two painted slots, and a separation the geometry proves, which is the
# case that turns "cannot classify" into "possible with a planned swap". The
# attribute values are the format's own: "8" is filament 2, "0C" is filament 3.
$paintedWork = Join-Path $WorkDir "acceptance_painted.3mf"
$paintedModel = @'
<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><metadata name="BambuStudio:MmPaintingVersion">1</metadata><resources><object id="1" type="model"><mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/><vertex x="0" y="10" z="10"/></vertices><triangles><triangle v1="0" v2="1" v3="2" paint_color="8"/></triangles></mesh></object><object id="2" type="model"><mesh><vertices><vertex x="0" y="0" z="30"/><vertex x="10" y="0" z="30"/><vertex x="0" y="10" z="40"/></vertices><triangles><triangle v1="0" v2="1" v3="2" paint_color="0C"/></triangles></mesh></object></resources><build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/><item objectid="2" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></build></model>
'@
$paintedSettings = @'
{"printer_model":"Snapmaker U1","filament_colour":["#FF0000","#00FF00","#0000FF","#FFFFFF"],"filament_type":["PLA","PLA","PLA","PLA"],"layer_height":"0.2","initial_layer_print_height":"0.2","nozzle_diameter":["0.4","0.4","0.4","0.4"]}
'@
$paintedParts = @'
<config><object id="1"><part id="1" subtype="normal_part"><metadata key="extruder" value="2"/></part></object><object id="2"><part id="2" subtype="normal_part"><metadata key="extruder" value="3"/></part></object><plate><metadata key="plater_id" value="1"/></plate></config>
'@
if (Test-Path $paintedWork) { Remove-Item $paintedWork -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null
$zip = [System.IO.Compression.ZipFile]::Open($paintedWork, "Create")
foreach ($entry in @(
    @{ name = "3D/3dmodel.model"; body = $paintedModel },
    @{ name = "Metadata/project_settings.config"; body = $paintedSettings },
    @{ name = "Metadata/model_settings.config"; body = $paintedParts })) {
    $item = $zip.CreateEntry($entry.name)
    $writer = New-Object System.IO.StreamWriter($item.Open())
    $writer.Write($entry.body.Trim())
    $writer.Dispose()
}
$zip.Dispose()

$gcodeWork = Join-Path $WorkDir "acceptance_job.gcode"
@'
; HEADER_BLOCK_START
; generated by Snapmaker Orca 2.3.4 on 2026-08-23 at 10:00:00
; total layer number: 12
; max_z_height: 2.40
; HEADER_BLOCK_END
; EXECUTABLE_BLOCK_START
PRINT_START
M140 S60
M104 T1 S220
SET_PRINT_STATS_INFO TOTAL_LAYER=12 CURRENT_LAYER=0
T1
;LAYER_CHANGE
;Z:0.2
G1 X10 Y10 Z0.2 F1200
;LAYER_CHANGE
;Z:0.4
G1 X20 Y20 E1.0
;LAYER_CHANGE
;Z:0.6
G1 X30 Y30 E1.0
PRINT_END
; EXECUTABLE_BLOCK_END

; filament used [mm] = 0.00, 120.00, 0.00, 0.00
; filament used [g] = 0.00, 0.36, 0.00, 0.00
; total filament used [g] = 0.36
; total layers count = 12
; estimated printing time (normal mode) = 4m 10s

; CONFIG_BLOCK_START
; filament_type = PLA;PLA;PLA;PLA
; layer_height = 0.2
; nozzle_diameter = 0.4,0.4,0.4,0.4
; printable_area = 0.5x1,270.5x1,270.5x271,0.5x271
; printer_model = Snapmaker U1
; CONFIG_BLOCK_END
'@ | Set-Content $gcodeWork -Encoding utf8
$gcodeHashBefore = (Get-FileHash $gcodeWork -Algorithm SHA256).Hash

# Two throwaway servers this run owns. Started before the app so the provider
# checks can reach them, tracked by pid + start time like everything else here.
# The repository path contains a space; the launcher passes each argument as its
# own element, so the path reaches node intact. (The first run of an earlier
# version of this failed with a connection refused that looked like a product
# defect and was an unquoted path.)
$probeUrl = "127.0.0.1:$ProbePort"
$redirectUrl = "127.0.0.1:$RedirectPort"
$spooleaseKey = "Fx7-tEsT"
# These go to the node child processes ONLY (probes and check phases); this session's environment is never changed.
$probeEnv = @{
    SNAPSTUDIO_PROBE_URL     = $probeUrl
    SNAPSTUDIO_REDIRECT_URL  = $redirectUrl
    SNAPSTUDIO_SPOOLEASE_URL = "127.0.0.1:$SpoolEasePort"
    SNAPSTUDIO_SPOOLEASE_KEY = $spooleaseKey
}
if ($BambuddyUrl) { $probeEnv.SNAPSTUDIO_BAMBUDDY_URL = $BambuddyUrl }
# Deliberately not stopped when the app is restarted with a different project (Stop-HarnessApp only stops
# the app and its children): the probes are instruments for the whole run. They are stopped in the finally
# block, and only ever by their own tracked pid.
$probeHandle = Start-HarnessTool -Lane $lane -Tool node -Hidden -Label "probes" `
    -ArgumentList @((Join-Path $PSScriptRoot "probes.mjs"), "$ProbePort", "$RedirectPort", "$SpoolEasePort") `
    -Environment $probeEnv
Start-Sleep -Seconds 2
try {
    $probeAlive = (Invoke-WebRequest "http://$probeUrl/__hits" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200
} catch { $probeAlive = $false }
Add-Check "Probe servers this run owns are up" $probeAlive "count $ProbePort, redirect $RedirectPort"

    $acceptanceIdentity = (Import-PowerShellDataFile (Join-Path $PSScriptRoot "..\lib\HarnessIdentity.psd1")).Acceptance
    $acceptanceUninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$($acceptanceIdentity.ProductName)"

    # --- upgrade path --------------------------------------------------------
    # Rewrapped OLD -> rewrapped NEW (acceptance identity). Real production upgrade proof lives only in the disposable CI lane.
    if ($lane.Upgrade) {
        Write-Host "Upgrading from the previous rewrapped acceptance installer"
        $prev = Install-HarnessBuild -Lane $lane -Which UpgradeFrom
        Add-Check "Previous version installs" ($prev.ExitCode -eq 0) "exit code $($prev.ExitCode)"

        # Give the old build a run so it creates the state a real user would have.
        $warm = Start-App -Settle 12 -Label "warm-up-previous"
        Stop-HarnessApp -Lane $lane -App $warm | Out-Null
        Start-Sleep -Seconds 4

        Add-Check "Previous version left state to migrate" (Test-Path $dataDir) "engine-data under the harness run directory"
        $script:stateBefore = @(Get-ChildItem $dataDir -Recurse -File -ErrorAction SilentlyContinue).Count
    }

    # --- install -------------------------------------------------------------
    $proc = Install-HarnessBuild -Lane $lane -Which Primary
    Add-Check "Scripted install completes" ($proc.ExitCode -eq 0) "exit code $($proc.ExitCode)"

    if ($lane.Upgrade) {
        $stateAfter = @(Get-ChildItem $dataDir -Recurse -File -ErrorAction SilentlyContinue).Count
        Add-Check "Upgrade keeps the user's data" ($stateAfter -ge $script:stateBefore) `
            "$script:stateBefore file(s) before, $stateAfter after"
        # Exact acceptance uninstall key only: no display-name wildcard discovery. (The old "not two installations"
        # count could never fail against one exact key, so it is gone; these checks can.)
        $regPresent = Test-Path -LiteralPath $acceptanceUninstallKey
        Add-Check "Upgrade leaves the acceptance registration in place" $regPresent "exact acceptance uninstall key"

        # v1.0.0 release-prep: proves the registration was REPLACED, not
        # merely left alone (a broken upgrade that silently no-ops would still
        # leave the registration, but with the OLD version still recorded).
        $newVersion = $lane.Builds["Primary"].Staged.Version
        $regVersion = if ($regPresent) { (Get-ItemProperty -LiteralPath $acceptanceUninstallKey -ErrorAction SilentlyContinue).DisplayVersion } else { $null }
        Add-Check "Upgrade registration reports the new version" `
            ($null -ne $newVersion -and $regVersion -eq $newVersion) `
            "registry says $regVersion, attestation source version says $newVersion"
    }

    Add-Check "Application installed" (Test-Path $appExe)
    Add-Check "Frozen engine sidecar installed" (Test-Path $sidecarExe) `
        ("{0:N1} MB" -f ((Get-Item $sidecarExe -ErrorAction SilentlyContinue).Length / 1MB))
    Add-Check "Uninstaller installed" (Test-Path (Join-Path $installDir "uninstall.exe"))

    # --- launch --------------------------------------------------------------
    # Hand the project to the app the same way a file association would. Isolation variables
    # (WebView2 profile, debug port, engine data dir) reach ONLY the child, inside Start-HarnessApp.
    $appHandle = Start-App -AppArgs @($sampleWork) -Settle 10 -Label "app"
    $app = $appHandle.Process

    $alive = $null -ne (Get-Process -Id $app.Id -ErrorAction SilentlyContinue)
    Add-Check "Application launches" $alive "pid $($app.Id)"
    Add-Check "Window title" (( Get-Process -Id $app.Id).MainWindowTitle -eq "Snapmaker Studio")

    $sidecars = @(Get-HarnessSidecarProcesses -Lane $lane)
    Add-Check "Sidecar boots from the install directory" ($sidecars.Count -ge 1) `
        "$($sidecars.Count) process(es)"

    $cdp = $appHandle.CdpUrl
    $node = Join-Path $PSScriptRoot "checks.mjs"

    function Invoke-Phase($phase, $arg = "", $arg2 = "", $arg3 = "") {
        $r = Invoke-HarnessNode -Lane $script:lane -Environment $script:probeEnv `
            -ArgumentList @($node, $phase, $cdp, $outDir, $arg, $arg2, $arg3, $SpoolmanUrl)
        $r.Output | ForEach-Object { Write-Host "    $_" }
        return $r.ExitCode
    }

    Add-Check "CDP reachable on the installed webview" `
        ((Invoke-WebRequest "$cdp/json/version" -UseBasicParsing -TimeoutSec 10).StatusCode -eq 200)

    $code = Invoke-Phase "startup"
    Add-Check "Startup checks" ($code -eq 0)

    $code = Invoke-Phase "routes" $sampleWork $gcodeWork $paintedWork
    Add-Check "Engine routes answer from the installed sidecar" ($code -eq 0)

    # --- the project the app was launched with --------------------------------
    #
    # The native picker is deliberately not used here. It is a Win32 common
    # dialog with no DOM, and on this stack invoking it without real user input
    # blocks without ever creating a window - verified by enumerating every
    # top-level window while the call was pending. No UI-automation client can
    # reach a window that does not exist, so the app instead accepts a model on
    # its command line, which a file association needs anyway.
    $code = Invoke-Phase "launch-file"
    Add-Check "Model passed on the command line is open" ($code -eq 0)

    Invoke-Phase "goto-compatibility" | Out-Null
    Start-Sleep -Seconds 4

    $code = Invoke-Phase "ui"
    Add-Check "Project opens and its findings render" ($code -eq 0)

    # --- prepare a copy -------------------------------------------------------
    Invoke-Phase "prepare" | Out-Null
    Start-Sleep -Seconds 3
    $code = Invoke-Phase "prepared"
    Add-Check "Prepare, fidelity, ledger and best-tool render" ($code -eq 0)

    $code = Invoke-Phase "colours"
    Add-Check "Colour plan renders on its own page" ($code -eq 0)

    # --- the post-slice half of the workflow ---------------------------------
    $code = Invoke-Phase "post-slice" $sampleWork $gcodeWork
    Add-Check "Post-Slice Doctor reads a sliced job in the installed app" ($code -eq 0)

    $code = Invoke-Phase "cockpit" $sampleWork $gcodeWork
    Add-Check "One surface shows the whole job" ($code -eq 0)

    # Whether a job belongs to the open project decides whether every other
    # answer on the page is about the right file.
    $code = Invoke-Phase "provenance" $sampleWork $gcodeWork
    Add-Check "Studio explains how sure it is about a job" ($code -eq 0)

    # The states a first-time owner hits, driven through the shipped UI.
    $code = Invoke-Phase "novice" $sampleWork $gcodeWork
    Add-Check "First-evening mistakes are answered, not ignored" ($code -eq 0)

    # --- v1.2: local spool notes and per-printer nozzle confirmation ---------
    #
    # No printer is present for this half of the run (host stays the U1's
    # stock mDNS placeholder), which is deliberate: these checks prove the
    # local-only note path end to end in the installed build without needing
    # real hardware. The real-U1 half of the same feature (a live nozzle
    # reading and a conflict against it) is tools/hardware/checks.mjs +
    # verify.ps1, run separately against an actual printer.
    $code = Invoke-Phase "spool-nozzle-empty"
    Add-Check "Spool notes and nozzle empty states render (W1/W6/W9)" ($code -eq 0)

    $code = Invoke-Phase "spool-notes-create"
    Add-Check "Spool notes are created through the installed UI (W2)" ($code -eq 0)

    $code = Invoke-Phase "spool-edit-validate"
    Add-Check "Editing, clearing and validating a spool note behave as specified (W3/W5/W9)" ($code -eq 0)

    $code = Invoke-Phase "spool-record-used"
    Add-Check "Recording filament used shows an estimate, not a measurement (W4)" ($code -eq 0)

    $code = Invoke-Phase "nozzle-confirm"
    Add-Check "Nozzle sizes are confirmed through the installed UI (W6)" ($code -eq 0)

    $gcodeHashAfter = (Get-FileHash $gcodeWork -Algorithm SHA256).Hash
    Add-Check "Sliced job is byte-identical afterwards" ($gcodeHashBefore -eq $gcodeHashAfter)

    $sampleHashAfter = (Get-FileHash $sampleWork -Algorithm SHA256).Hash
    Add-Check "Original file is byte-identical afterwards" `
        ($sampleHashBefore -eq $sampleHashAfter)

    # --- the painted project, in the installed UI -----------------------------
    #
    # The colours card is where this release's work becomes visible, so it is
    # driven with a project that is actually painted rather than only asserted
    # through the engine. The app is restarted with that project because a model
    # is opened from the command line, which is the same path a file association
    # takes.
    Stop-Tracked
    $paintedHandle = Start-App -AppArgs @($paintedWork) -Settle 12 -Label "painted"
    $paintedApp = $paintedHandle.Process
    $code = Invoke-Phase "painted"
    Add-Check "Painted colour is shown in the installed build" ($code -eq 0)
    # --- v1.2: the same relaunch proves persistence, then destructive removal -
    #
    # The app was just closed (Stop-Tracked above) and started again with a
    # different project - a genuine process relaunch, the same mechanism W7
    # asks for. What was created before that relaunch must still be there.
    $code = Invoke-Phase "spool-nozzle-restored"
    Add-Check "Spool notes and nozzle confirmations survive a relaunch (W7)" ($code -eq 0)

    # Destructive, so run last among the v1.2 checks: nothing after this
    # depends on the notes or nozzle confirmations it removes.
    $code = Invoke-Phase "spool-nozzle-remove"
    Add-Check "Removing nozzles, deleting a note and switching provider kind behave as specified (W8)" ($code -eq 0)

    # --- the material provider, through the installed UI ----------------------
    #
    # Only when an address was supplied. The default and the restart are what
    # matter most: an upgrading v0.7.2 user never had a provider setting, so the
    # app must open with none and contact nothing, and a setting a person typed
    # has to survive closing the app.
    if ($SpoolmanUrl) {
        $code = Invoke-Phase "provider-default"
        Add-Check "A new install offers the provider setting and configures none" ($code -eq 0)

        $code = Invoke-Phase "provider-configure" $sampleWork $gcodeWork
        Add-Check "The provider can be configured in the installed app" ($code -eq 0)
    }

    # --- the provider wire, the safety rules and the second provider ----------
    #
    # These run against the frozen sidecar from inside the app's own origin. The
    # unit suites prove the engine; these prove the binary that was installed
    # actually carries it.
    try {
        $probeStillUp = (Invoke-WebRequest "http://$probeUrl/__hits" `
            -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200
    } catch { $probeStillUp = $false }
    Add-Check "Probe servers survived the app restarts" $probeStillUp

    $code = Invoke-Phase "provider-wire" $sampleWork $gcodeWork
    Add-Check "Both provider wire shapes work in the installed build" ($code -eq 0)

    $code = Invoke-Phase "provider-zero-request" $sampleWork $gcodeWork
    Add-Check "No provider configured means no provider request" ($code -eq 0)

    $code = Invoke-Phase "provider-safety" $sampleWork $gcodeWork
    Add-Check "Provider addresses are validated in the installed build" ($code -eq 0)

    $code = Invoke-Phase "provider-redirect" $sampleWork $gcodeWork
    Add-Check "A redirect off the local network is refused in the installed build" ($code -eq 0)

    if ($BambuddyUrl) {
        $code = Invoke-Phase "provider-adversarial" $sampleWork $gcodeWork
        Add-Check "Impossible provider weights become unknown, never enough" ($code -eq 0)
    }

    if ($SpoolmanUrl -and $BambuddyUrl) {
        $code = Invoke-Phase "provider-equivalence" $sampleWork $gcodeWork
        Add-Check "Equivalent facts from two providers decide the same" ($code -eq 0)

        $code = Invoke-Phase "provider-conflict" $sampleWork $gcodeWork
        Add-Check "A printer/provider disagreement is shown, not resolved" ($code -eq 0)

        $code = Invoke-Phase "provider-upload-contract" $sampleWork $gcodeWork
        Add-Check "The upload route accepts both wire shapes" ($code -eq 0)

    }

    # --- close the real window, prove that alone exits the app cleanly -------
    # Every orphan check below this point (and previously, every "close"
    # check in this script's history) used a forced kill - a kill, not
    # a close. That measures a different, easier path: Windows' Job Object
    # binding and the app's plain kill()+wait() both fire on any process
    # death, killed or not. It never proved that clicking the X button (or
    # Alt+F4, or any other real close) exits the app at all. It did not,
    # from beta.13 through v0.9.0: closing the main window left the process
    # and its sidecar running in the background - confirmed empirically
    # against the real v0.9.0 release binary before this check existed, then
    # fixed by requesting app exit when the main window is destroyed (the
    # app also owns a second, permanently-hidden window that prevents its
    # own close, which meant Tauri's window-map-empties-so-exit default
    # never fired for the main window either). This check is what actually
    # exercises that fix, and what the "No orphan sidecar after close" check
    # below should have been testing all along.
    $sidecarBeforeClose = @(Get-HarnessSidecarProcesses -Lane $lane -ParentPid $paintedApp.Id |
        Select-Object -ExpandProperty ProcessId)
    $paintedApp.Refresh()
    $realCloseWorked = $false
    if ($paintedApp.MainWindowHandle -ne [IntPtr]::Zero -and $sidecarBeforeClose.Count -gt 0) {
        $paintedApp.CloseMainWindow() | Out-Null
        $appExited = $paintedApp.WaitForExit(15000)
        $sidecarDeadline = (Get-Date).AddSeconds(10)
        $stillAlive = $sidecarBeforeClose
        while ((Get-Date) -lt $sidecarDeadline -and $stillAlive) {
            $stillAlive = $stillAlive | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }
            if ($stillAlive) { Start-Sleep -Milliseconds 250 }
        }
        $realCloseWorked = $appExited -and (-not $stillAlive)
        Add-Check "Closing the real window exits the app and its sidecar (not just a kill)" $realCloseWorked `
            "app exited=$appExited, sidecar PID(s) still alive=$($stillAlive -join ',')"
    } else {
        Add-Check "Closing the real window exits the app and its sidecar (not just a kill)" $false `
            "could not locate the main window or its sidecar PID before attempting the close"
    }
    if (-not $realCloseWorked) {
        # Don't let a failed close leave the rest of the script blocked on a
        # process that should already be gone - stop whatever remains (tracked
        # pids only, start time and image verified) so later phases still run,
        # but the FAIL above already recorded it.
        Stop-HarnessApp -Lane $lane -App $paintedHandle -GraceSeconds 1 | Out-Null
    }

    # --- close (the pre-existing check) and prove no orphan ------------------
    Stop-Tracked
    $orphans = @(Get-HarnessSidecarProcesses -Lane $lane)
    Add-Check "No orphan sidecar after close" ($orphans.Count -eq 0) `
        "$($orphans.Count) left running"

    # --- reopen ---------------------------------------------------------------
    $againHandle = Start-App -Settle 8 -Label "reopen"
    Add-Check "Reopens cleanly" ($null -ne (Get-Process -Id $againHandle.Pid -ErrorAction SilentlyContinue))

    if ($SpoolmanUrl) {
        $code = Invoke-Phase "provider-restored" $sampleWork $gcodeWork
        Add-Check "Provider settings survive a restart and reach the send decision" ($code -eq 0)
    }

    # Only now, with the first provider's persistence proved, is it safe to
    # switch. Doing it earlier cleared the Spoolman configuration that the
    # restart check above exists to find - which is what the first run of this
    # did, and it read as five product failures.
    if ($SpoolmanUrl -and $BambuddyUrl) {
        $code = Invoke-Phase "provider-switch" $sampleWork $gcodeWork
        Add-Check "Switching provider in the installed app clears the old one" ($code -eq 0)

        # A second restart, so the second provider's persistence is measured the
        # same way the first one's was rather than assumed from it.
        Stop-Tracked
        $thirdHandle = Start-App -Settle 8 -Label "reopen-after-switch"
        Add-Check "Reopens again after switching provider" `
            ($null -ne (Get-Process -Id $thirdHandle.Pid -ErrorAction SilentlyContinue))

        $code = Invoke-Phase "provider-switch-restored" $sampleWork $gcodeWork
        Add-Check "The second provider survives a restart and can then be turned off" ($code -eq 0)
    }

    # SpoolEase runs last so the provider-switch phases above still measure a
    # clean Spoolman -> Bambuddy switch, not a switch away from SpoolEase.
    if ($spooleaseKey) {
        $code = Invoke-Phase "provider-spoolease" $sampleWork $gcodeWork
        Add-Check "SpoolEase can be configured and read in the installed build" ($code -eq 0)

        Stop-Tracked
        $spooleaseAgainHandle = Start-App -Settle 8 -Label "reopen-spoolease"
        $code = Invoke-Phase "provider-spoolease-restored" $sampleWork $gcodeWork
        Add-Check "SpoolEase settings restore without the session key" ($code -eq 0)
    }

    Stop-Tracked
}
catch {
    # A lane step threw. Record it as a failed check so the report still gets written; the finally block
    # below runs the uninstall / recovery / tripwire cleanup regardless.
    Add-Check "Harness lane step aborted" $false (Protect-LaneText -Text $_.Exception.Message -Lane $lane)
}
finally {
    # Always runs: stop tracked processes (graceful, then verified), uninstall unless -KeepInstall,
    # journal recovery, production tripwire, lock release. The probe servers are stopped only by their own tracked pid.
    try { if ($probeHandle) { [void](Stop-HarnessTool -Lane $lane -Handle $probeHandle) } } catch { Write-Host "NOTE  probe stop failed: $(Protect-LaneText -Text $_.Exception.Message -Lane $lane)" }
    $result = Complete-HarnessLane -Lane $lane
}

# --- uninstall and cleanup verdicts (the work itself ran in Complete-HarnessLane) -----------
if (-not $KeepInstall) {
    if ($lane.Phases.Count -gt 0) {
        $u = $result.Uninstall
        $uExit = if ($u -and $u.Attempted) { $u.ExitCode } else { $null }
        # Based on the install dir state and the hand-off wait (the NSIS parent exit code alone proves nothing).
        $uDone = [bool]($u -and $u.Attempted -and $u.HandoffComplete -and $u.DirFiles -eq 0 -and $uExit -eq 0)
        Add-Check "Uninstall completes" $uDone $(if ($u -and $u.Attempted) { "exit code $uExit; $($u.DirFiles) file(s) left; $($u.HandoffProcesses) hand-off process(es) still running" } else { "uninstall was not run (see harness errors)" })
        # Strict enumeration: an ambiguous directory state ($null) is a FAIL, never "zero files".
        $leftN = Get-InstallDirFileCount -Dir $installDir
        Add-Check "Install directory removed" ($null -ne $leftN -and $leftN -eq 0) $(if ($null -eq $leftN) { "install dir state could not be determined" } else { "$leftN file(s) left" })
        $stillRunning = @(Get-HarnessSidecarProcesses -Lane $lane)
        Add-Check "No sidecar survives uninstall" ($stillRunning.Count -eq 0)
    }
    $unfinalised = @($lane.Phases | Where-Object { -not $_.Finalized })
    Add-Check "Harness journal finalised (nothing left to recover)" ($unfinalised.Count -eq 0) "$($lane.Phases.Count) journal(s)"
} else {
    Write-Host "NOTE  -KeepInstall: the acceptance install and its journal(s) were KEPT (not uninstalled, not recovered). Uninstall it yourself, then for EACH journal run: tools/harness/Repair-Harness.ps1 -RunId <id> -ShortcutDir $($lane.ShortcutDir)   (journal ids: $((@($lane.Phases | ForEach-Object { $_.RunId })) -join ', '))"
}
Add-Check "Production state unchanged (tripwire)" ($lane.Findings.Count -eq 0) $(if ($lane.Findings.Count) { ($lane.Findings -join " | ") } else { "no change in the production data folders or real Start Menu/Desktop" })
Add-Check "Harness cleanup reported no errors" ($lane.Errors.Count -eq 0) $(if ($lane.Errors.Count) { ($lane.Errors -join " | ") } else { "" })

# --- report -------------------------------------------------------------------
# PERSISTED report = CLOSED STRUCTURE: fixed check names (string literals in this script) + pass/fail, integer totals, fixed
# literals, and the closed-schema lane block (fixed codes and counts only). The free-text check DETAILS stay on the console
# only (most of it best-effort scrubbed); they are never written to acceptance.json. Write-HarnessAcceptanceReport assembles
# the file from those closed parts (scrubbing touches ONLY the check-name values, before the lane block is inserted), then
# re-reads the FINAL on-disk file and validates it; a mismatch deletes it and fails the run. The scrubbing and the leak scan
# below are secondary checks, not the privacy boundary.
$laneSchemaError = if ($result) { Test-HarnessLaneEvidenceSchema -Evidence $result.Evidence } else { "no result" }
if ($laneSchemaError) { Add-Check "Lane evidence conforms to the closed schema" $false "REPORT_WRITE_FAILED" }
$passed = @($checks | Where-Object ok).Count
$total = $checks.Count
$reportPath = Join-Path $outDir "acceptance.json"

# The repository's own rules forbid local paths and usernames in tracked files,
# and this report (and every per-phase results-*.json checks.mjs writes
# straight into $outDir) is meant to be committed as release evidence.
#
# A1 (harness-fix round 1, Opus 5/Sol 4): this used to scrub only the
# in-memory acceptance.json string - every results-<phase>.json and log file
# checks.mjs writes directly to $outDir was never touched at all. It also
# leak-checked that SAME already-replaced string, which can never fail (a
# vacuous pass Sol flagged as BLOCK). Fixed: every text file actually in
# $outDir is scrubbed in place, and the final leak check re-reads every file
# fresh off disk afterward, independent of any in-memory string this script
# built along the way.
function Scrub-EvidenceText([string]$text) {
    foreach ($pair in $literalRedactionPairs) {
        $text = $text.Replace($pair.from.Replace('\', '\\'), $pair.to)
        $text = $text.Replace($pair.from, $pair.to)
    }
    # IPv4.
    $text = [regex]::Replace($text, '\b(?:\d{1,3}\.){3}\d{1,3}\b', '<ip>')
    # Bracketed IPv6 (A7-2, Opus): requires either a literal "::" or at least
    # 3 colons inside the brackets - a short bracketed list like a log's
    # "[22:14:05]" (2 colons) or "[1]"/"[2]" (no colon at all) used to match
    # the old, looser "any hex/colon chars in brackets" pattern and get
    # wrongly redacted; neither shape is a real IPv6 address.
    $text = [regex]::Replace($text,
        '\[(?:[0-9a-fA-F]*::[0-9a-fA-F:]*|(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{0,4})(?:%[0-9a-zA-Z]+)?\]',
        '<ip>')
    # Bare compressed IPv6 (fe80::1, 2001:db8::1, ::1, fd00::abcd:1234, ...),
    # with an optional zone id. Requires the literal "::" - a plain clock
    # time like 22:14:05 has no double colon and can never match this, unlike
    # a broader hex-run regex.
    #
    # F7 (Opus polish): also requires a REAL hex group immediately touching
    # the "::" on at least one side - bare "::" with nothing hex-shaped on
    # either side (e.g. "[System.IO.File]::Read(...)", a plain PowerShell/.NET
    # member-access token, not an address) used to match the old, looser
    # "{0,4} on both sides" pattern, since both sides being zero-width was
    # still allowed. The two alternatives below require the LEADING group
    # non-empty (covers "fe80::", "fd00::abcd:1234") or the TRAILING group
    # non-empty (covers "::1") - never both empty at once.
    $text = [regex]::Replace($text,
        '(?<![0-9a-fA-F:])(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{0,4}){0,7}::(?:[0-9a-fA-F]{0,4}:){0,7}[0-9a-fA-F]{0,4}|[0-9a-fA-F]{0,4}(?::[0-9a-fA-F]{0,4}){0,7}::(?:[0-9a-fA-F]{0,4}:){0,7}[0-9a-fA-F]{1,4})(?:%[0-9a-zA-Z]+)?(?![0-9a-fA-F:])',
        '<ip>')
    # A7-4 (Opus): bare, FULLY EXPANDED IPv6 (8 groups, exactly 7 colons, no
    # "::" at all) - the round-1 pattern only matched a compressed form. A
    # plain clock time has only 2 colons and can never satisfy "exactly 7", so
    # this is still never a false positive on one.
    $text = [regex]::Replace($text,
        '(?<![0-9a-fA-F:])(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}(?:%[0-9a-zA-Z]+)?(?![0-9a-fA-F:])',
        '<ip>')
    return $text
}

$literalRedactionPairs = @(
    @{ from = $repo;         to = "<repo>" },
    @{ from = $WorkDir;      to = "<workdir>" },
    @{ from = $lane.Root;    to = "<harness-root>" },
    @{ from = $env:TEMP;     to = "<temp>" },
    @{ from = $env:USERNAME; to = "<user>" },
    @{ from = $SpoolmanUrl;  to = "<provider-on-lan>" },
    @{ from = $BambuddyUrl;  to = "<provider-on-lan>" }
    @{ from = "Fx7-tEsT";    to = "<fixture-key>" }
) | Where-Object { $_.from }

$reportWriteFailed = $false
# The lane block carries the RUN verdict (any failed check, an aborted lane step, or a non-zero lane result => status fail
# with a fixed reason code), built through the same closed-schema path as the other harnesses; never edited afterwards.
$laneBlock = $null
if ($result -and -not $laneSchemaError) {
    try { $laneBlock = Get-HarnessAcceptanceLaneEvidence -Lane $lane -Result $result -Checks $checks }
    catch {
        $reportWriteFailed = $true
        Write-Host "FAIL  REPORT_WRITE_FAILED: lane evidence could not be built: $(Protect-LaneText -Text $_.Exception.Message -Lane $lane)"
    }
}
try {
    [void](Write-HarnessAcceptanceReport -Path $reportPath -Checks $checks `
        -LaneEvidence $laneBlock `
        -ScrubName { param($n) Scrub-EvidenceText $n })
} catch {
    $reportWriteFailed = $true
    Write-Host "FAIL  REPORT_WRITE_FAILED: acceptance.json was not written or failed validation: $(Protect-LaneText -Text $_.Exception.Message -Lane $lane)"
}

$textExtensions = @(".json", ".log", ".txt")
foreach ($file in @(Get-ChildItem $outDir -File -Recurse -ErrorAction SilentlyContinue)) {
    if ($file.FullName -eq $reportPath) { continue } # already scrubbed and written above
    if ($textExtensions -notcontains $file.Extension.ToLowerInvariant()) { continue }
    $raw = $null
    try { $raw = Get-Content -Raw -Path $file.FullName -ErrorAction Stop } catch { continue }
    if ($null -eq $raw) { continue }
    $scrubbed = Scrub-EvidenceText $raw
    if ($scrubbed -ne $raw) {
        $scrubbed | Set-Content -Path $file.FullName -Encoding utf8 -NoNewline
    }
}

# Final scan: re-read every file fresh off disk (byte-safe, so a binary
# screenshot is scanned too, not just text) and fail the run if the RAW
# supplied provider address is still found anywhere in the evidence
# directory - independent of the $json variable above, which would trivially
# "pass" having just been replaced in it.
#
# A7-3 (Opus): matched case-INsensitively, and both WITH and WITHOUT the
# address's own port - a log line that dropped the ":port" suffix, or wrote
# the hostname in a different case, used to slip past a case-sensitive,
# exact-string Contains() check.
# F7 (Opus polish): also strips any "http(s)://" prefix, in addition to the
# port, so a candidate supplied as a full URL still produces the bare-host
# form to match against.
function Get-LeakCandidates([string]$addr) {
    if (-not $addr) { return @() }
    $out = New-Object System.Collections.Generic.List[string]
    $out.Add($addr)
    $noScheme = $addr -replace '^[a-zA-Z][a-zA-Z0-9+.-]*://', ''
    if ($noScheme -ne $addr) { $out.Add($noScheme) }
    foreach ($candidate in @($addr, $noScheme)) {
        if ($candidate -match '^(.*):(\d+)$') { $out.Add($matches[1]) }
    }
    return @($out | Select-Object -Unique)
}
$leakCandidates = @(
    (Get-LeakCandidates $SpoolmanUrl) + (Get-LeakCandidates $BambuddyUrl)
) | Select-Object -Unique
# F4 (fix-round-3, Sol 4 BLOCKING): records/prints the FILENAME only on a hit
# - never the candidate string itself. The round-2 code embedded the raw
# address into `$leaked` (`"$($file.Name): $candidate"`) and then printed
# that straight to the console via Write-Host, which is exactly the "write
# the raw address somewhere" mistake H8 exists to prevent elsewhere in this
# same round - it just hadn't been fixed here yet.
$leaked = New-Object System.Collections.Generic.List[string]
if ($leakCandidates.Count -gt 0) {
    $latin1 = [System.Text.Encoding]::GetEncoding(28591)
    foreach ($file in @(Get-ChildItem $outDir -File -Recurse -ErrorAction SilentlyContinue)) {
        $text = $null
        try {
            $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
            $text = $latin1.GetString($bytes)
        } catch { continue }
        foreach ($candidate in $leakCandidates) {
            if ($text.IndexOf($candidate, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                if (-not $leaked.Contains($file.Name)) { $leaked.Add($file.Name) }
                break
            }
        }
    }
}
if ($leaked.Count -gt 0) {
    Write-Host "FAIL  A supplied provider address survived redaction in the evidence directory (F4/A3.7/A1) - found in: $($leaked -join ', ')"
}

Write-Host ""
Write-Host "$passed/$total checks passed"
Write-Host "Evidence and screenshots: $outDir"
if ($passed -ne $total -or $leaked.Count -gt 0 -or ($result -and $result.ExitCode -ne 0) -or $reportWriteFailed) { exit 1 }
