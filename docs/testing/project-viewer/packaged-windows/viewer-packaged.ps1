#requires -Version 7.0
# Packaged-app viewer probe on a clean local account: REWRAPPED ACCEPTANCE copy of a CI-built viewer candidate.
# Installer path, hash and version arrive as parameters.
param(
    [Parameter(Mandatory)][string]$Installer,
    [Parameter(Mandatory)][string]$Sha256,
    [Parameter(Mandatory)][string]$SourceVersion,
    [Parameter(Mandatory)][string]$Sums,
    [string]$OutName = 'viewer-packaged'
)
$ErrorActionPreference = 'Continue'
$g = $PSScriptRoot; $repo = Join-Path $g 'repo'; $out = Join-Path $g 'out-viewer'
New-Item -ItemType Directory -Force $out | Out-Null
Start-Transcript -Path (Join-Path $out "$OutName-transcript.txt") -Force | Out-Null
"started_utc: $((Get-Date).ToUniversalTime().ToString('o'))"
Import-Module (Join-Path $repo 'tools\harness\HarnessLauncher.psm1') -Force -DisableNameChecking
$lane = Start-HarnessLane -Name 'viewer' -Kind capture -RealInstaller $Installer -ExpectedSha256 $Sha256 -Sha256SumsPath $Sums -SourceVersion $SourceVersion -DebugPort 9352
$failure = $null; $probe = 99
try {
    $sample = Join-Path $lane.RunDir 'demo_u1_showcase.3mf'
    Copy-Item (Join-Path $repo 'examples\demo_u1_showcase.3mf') $sample -Force
    $inst = Install-HarnessBuild -Lane $lane -Which Primary
    if ($inst.ExitCode -ne 0) { throw "install failed with exit code $($inst.ExitCode)" }
    $null = Start-HarnessApp -Lane $lane -Arguments @($sample) -SettleSeconds 12 -Label 'app'
    & node (Join-Path $repo 'tools\acceptance\viewer-packaged.mjs') 'http://127.0.0.1:9352' $sample (Join-Path $out "$OutName-result.json") *>&1 | Tee-Object -FilePath (Join-Path $out "$OutName-console.txt")
    $probe = $LASTEXITCODE
} catch { $failure = $_; "FAIL  $($_.Exception.Message)" }
finally { $result = Complete-HarnessLane -Lane $lane }
$rc = Publish-HarnessLaneReport -Lane $lane -Result $result -EvidencePath (Join-Path $out "$OutName.lane-evidence.json") -Failed:([bool]$failure -or $probe -ne 0)
Set-Content (Join-Path $out "$OutName-exit.txt") "probe_exit=$probe`nlane_report_rc=$rc`nended_utc=$((Get-Date).ToUniversalTime().ToString('o'))"
Stop-Transcript | Out-Null
exit ([int](($probe -ne 0) -or ($rc -ne 0)))
