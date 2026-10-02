#requires -Version 7.0
<#
.SYNOPSIS
    Builds the ACCEPTANCE-identity installer from a real released installer ("rewrap", issue #55). The result is
    compiled but NEVER run, installed or launched here.
.DESCRIPTION
    extract (pinned 7-Zip) -> render the vendored Tauri NSIS template with the acceptance identity from
    tools/lib/HarnessIdentity.psd1 -> enumerate every RmDir/Delete/DeleteRegKey/DeleteRegValue target and fail the build
    on anything InstallGuard's Test-DeleteTargetAllowed refuses -> compile with pinned makensis -> verify (ProductName,
    7-Zip listing) -> write <harness root>\attestations\<runId>.json and require InstallGuard's Test-RewrapAttestation
    to accept it. Output: <harness root>\rewrap\<runId>\<installer>.exe.
    -HarnessRoot / -ToolsDir are test overrides that must pass InstallGuard's positive path allowlist.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$InstallerPath,
    [Parameter(Mandatory)][string]$ExpectedSha256,
    [string]$Sha256SumsPath,
    [Parameter(Mandatory)][string]$SourceVersion,
    [string]$HarnessRoot,
    [string]$ToolsDir,
    [string]$RunId
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'lib\Rewrap.psm1') -Force -DisableNameChecking
$p = @{ InstallerPath = $InstallerPath; ExpectedSha256 = $ExpectedSha256; SourceVersion = $SourceVersion }
foreach ($k in 'Sha256SumsPath', 'HarnessRoot', 'ToolsDir', 'RunId') { if ((Get-Variable $k).Value) { $p[$k] = (Get-Variable $k).Value } }
Invoke-AcceptanceRewrap @p
