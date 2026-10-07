#requires -Version 7.0
<#
.SYNOPSIS
  Captures the guide screenshots that need the INSTALLED Snapmaker Studio (currently: handoff.png).

.DESCRIPTION
  Uses the repository's own isolated test harness (tools/harness): it installs a REWRAPPED acceptance-identity copy of
  the release installer into a harness-owned folder, starts it with an isolated WebView2 profile and data folder,
  attaches tools/capture-installed.mjs over the remote-debugging port, then uninstalls. It never touches your real
  Snapmaker Studio, its data, a printer, or Snapmaker Orca, and it never presses "Open in Snapmaker Orca".

  Read tools/acceptance/run.ps1 for how the harness lane works. The production Studio must not be running.

.EXAMPLE
  pwsh -File site/guide/tools/capture-installed.ps1 -Installer C:\path\Snapmaker.Studio_1.5.0_x64-setup.exe `
       -Sha <sha256 from docs/RELEASE_METADATA.md> -SourceVersion 1.5.0
#>
param(
    [Parameter(Mandatory)][string]$Installer,
    [Parameter(Mandatory)][string]$Sha,
    [Parameter(Mandatory)][string]$SourceVersion,
    [int]$DebugPort = 9333
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = (Resolve-Path (Join-Path $here "..\..\..")).Path
Import-Module (Join-Path $repo "tools\harness\HarnessLauncher.psm1") -Force -DisableNameChecking

$lane = Start-HarnessLane -Name "acceptance" -Kind acceptance -RealInstaller $Installer -ExpectedSha256 $Sha -SourceVersion $SourceVersion -DebugPort $DebugPort
try {
    $p = Install-HarnessBuild -Lane $lane -Which Primary
    if ($p.ExitCode -ne 0) { throw "install failed: exit code $($p.ExitCode)" }
    # the example project the screenshot is taken with, copied inside the harness folder
    $work = Join-Path $lane.RunDir "guide-input"
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    $example = Join-Path $work "demo_offplate_foreign.3mf"
    Copy-Item (Join-Path $repo "examples\demo_offplate_foreign.3mf") $example -Force
    $app = Start-HarnessApp -Lane $lane -Arguments @($example) -SettleSeconds 12 -Label "guide-capture"
    $r = Invoke-HarnessNode -Lane $lane -Environment @{} -ArgumentList @((Join-Path $here "capture-installed.mjs"), $app.CdpUrl)
    $r.Output | ForEach-Object { Write-Host $_ }
    if ($r.ExitCode -ne 0) { Write-Host "capture reported failures (exit $($r.ExitCode))" }
    Stop-HarnessApp -Lane $lane | Out-Null
    Start-Sleep -Seconds 3
}
finally {
    Complete-HarnessLane -Lane $lane | Out-Null
}
