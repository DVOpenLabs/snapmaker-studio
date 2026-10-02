#requires -Version 7.0
# Verify the installed Snapmaker Studio against a real Snapmaker U1 - read-only - REWRAPPED ACCEPTANCE-IDENTITY lane.
#
# Installs a REWRAPPED acceptance-identity installer (tools/release/rewrap_installer.ps1) into a harness-owned
# directory, launches it with an isolated WebView2 profile and engine data directory, asks the real printer a
# fixed set of read-only questions through the app's own engine, and uninstalls. The plumbing (install, launch,
# uninstall, cleanup, tripwire) is the shared fail-closed lane in tools/harness/HarnessLauncher.psm1.
#
# WHAT THIS PROVES: the shipped payload under the ACCEPTANCE identity talking to a real printer. It does NOT prove
# the production installer (registration, shortcuts, default-path install/upgrade/uninstall = disposable CI only).
#
# SAFETY, and these are not negotiable:
#  * Read-only. No print is started, nothing is uploaded or queued, and no
#    temperature, motion, homing, pause, resume, cancel, emergency-stop or
#    configuration call is made. The route allow-list lives in checks.mjs and is
#    asserted there before the first request.
#  * Only processes this script starts are ever stopped, tracked by PID and start time (never by name).
#  * The production app must not be running and its update auto-check must be off (or its state file absent);
#    production state is only read, and a tripwire reports any change.
#  * The printer's address is replaced with a placeholder before anything is
#    written to the evidence file.
#
# Usage (the installer is always a REWRAPPED acceptance installer; there is no auto-discovery):
#   pwsh -File tools/hardware/verify.ps1 -PrinterHost <ip-or-hostname>
#        -InstallerPath <rewrapped installer> -AttestationPath <its attestation> [-KeepInstall]
#   or: -RealInstaller <path> -ExpectedSha256 <sha256> -SourceVersion <semver> [-Sha256SumsPath <path>]
#   (or set SNAPSTUDIO_ACCEPT_PRINTER instead of -PrinterHost)
#
# v1.2: also runs the nozzle-confirmation checks (R1/R2) against this same
# real printer - see the header of checks.mjs for what they prove.
#
# F6: THE EXIT CODE THIS SCRIPT RETURNS IS AUTHORITATIVE (it is checks.mjs's
# own exit code, passed through as $code below, raised to 1 if the harness lane itself reports a problem)
# - not hardware.json's own `passed`/`total` fields. checks.mjs writes hardware.json once, before its
# final evidence-directory leak scan (H8: nothing is written again after that
# scan runs), so the JSON can legitimately say "every check passed" on a run
# whose exit code is still non-zero because the leak scan found something.
# (lane-evidence.json is written LATER, by this script, after that scan: it is a closed-schema object with fixed codes and
# counts only, written with the printer address as a -Redact value that makes the write fail closed if it ever appears.)

[CmdletBinding()]
param(
    # v1.2: falls back to SNAPSTUDIO_ACCEPT_PRINTER so this real-U1 phase can
    # be wired into a CI-style invocation the same way tools/acceptance/run.ps1
    # is, without hardcoding an address in any script.
    [string]$PrinterHost = $env:SNAPSTUDIO_ACCEPT_PRINTER,
    [string]$InstallerPath,
    [string]$AttestationPath,
    [string]$RealInstaller,
    [string]$ExpectedSha256,
    [string]$Sha256SumsPath,
    [string]$SourceVersion,
    [int]$DebugPort = 9377,
    [switch]$KeepInstall
)

$ErrorActionPreference = "Stop"
if (-not $PrinterHost) {
    throw "Supply -PrinterHost or set SNAPSTUDIO_ACCEPT_PRINTER - this script only runs against a real, reachable printer."
}
if (-not (Test-Path (Join-Path $PSScriptRoot "node_modules"))) {
    throw "run 'npm install' in tools/hardware first"
}
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Import-Module (Join-Path $PSScriptRoot "..\harness\HarnessLauncher.psm1") -Force -DisableNameChecking

$laneArgs = @{
    InstallerPath = $InstallerPath; AttestationPath = $AttestationPath
    RealInstaller = $RealInstaller; ExpectedSha256 = $ExpectedSha256; Sha256SumsPath = $Sha256SumsPath; SourceVersion = $SourceVersion
}
$lane = Start-HarnessLane -Name "hardware" -Kind hardware @laneArgs -DebugPort $DebugPort -KeepInstall:$KeepInstall
$outDir = $lane.EvidenceDir
$sample = Join-Path $repo "examples\demo_u1_showcase.3mf"
$sampleWork = Join-Path $lane.RunDir "demo_u1_showcase.3mf"

Write-Host "Lane:      rewrapped acceptance-identity installer"
Write-Host "Printer:   <redacted in evidence>"
$code = 1
$result = $null
try {
    Copy-Item $sample $sampleWork -Force
    $proc = Install-HarnessBuild -Lane $lane -Which Primary
    if ($proc.ExitCode -ne 0) { throw "install failed with exit code $($proc.ExitCode)" }

    # Isolation variables reach ONLY the app child process, inside Start-HarnessApp.
    $appHandle = Start-HarnessApp -Lane $lane -SettleSeconds 12 -Label "app"

    $r = Invoke-HarnessNode -Lane $lane -ArgumentList @((Join-Path $PSScriptRoot "checks.mjs"), $appHandle.CdpUrl, $outDir, $PrinterHost, $sampleWork)
    $r.Output | ForEach-Object { Write-Host $_ }
    $code = $r.ExitCode
}
catch {
    Write-Host "FAIL  harness lane step aborted: $(Protect-LaneText -Text $_.Exception.Message -Lane $lane)"
    $code = 1
}
finally {
    # Always runs, including with -KeepInstall (which skips the uninstall and the recovery): processes, uninstall, journal
    # recovery, production tripwire, lock release.
    $result = Complete-HarnessLane -Lane $lane
}

# The lane evidence is a CLOSED SCHEMA (fixed codes and counts, no free text), so it cannot carry the printer address; the
# writer additionally fails closed if -Redact (the printer address) appears in its output. A writer failure FAILS the lane.
$rc = Publish-HarnessLaneReport -Lane $lane -Result $result -EvidencePath (Join-Path $outDir "lane-evidence.json") -Redact @($PrinterHost) -Failed:($code -ne 0)
if ($rc -ne 0 -and $code -eq 0) { $code = 1 }
if ($KeepInstall) { Write-Host "NOTE  -KeepInstall: the acceptance install and its journal(s) were KEPT (not uninstalled, not recovered). Uninstall it yourself, then for EACH journal run: tools/harness/Repair-Harness.ps1 -RunId <id> -ShortcutDir $($lane.ShortcutDir)   (journal ids: $((@($lane.Phases | ForEach-Object { $_.RunId })) -join ', '))" }

Write-Host "Evidence: $outDir"
Write-Host "EXIT CODE IS AUTHORITATIVE (F6): $code - see hardware.json's own passed/total for detail, but treat this code, not that file, as the pass/fail verdict."
exit $code
