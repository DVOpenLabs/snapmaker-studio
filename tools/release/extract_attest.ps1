#requires -Version 7.0
<#
.SYNOPSIS
    Extracts a REAL released Snapmaker Studio installer with the pinned portable 7-Zip and builds the payload manifest
    (issue #55). Nothing extracted is ever executed.
.DESCRIPTION
    - verifies the installer sha256 (-ExpectedSha256, and SHA256SUMS when given);
    - lists the archive first and fails on traversal, duplicate, missing or unexpected entries;
    - extracts into <harness root>\extract\<runId>\ (a subtree separate from any install dir), then strips
      uninstall.exe and $PLUGINSDIR (keeping only the one pinned nsis_tauri_utils.dll as compile input);
    - writes <run dir>\extraction.json (per-file {path, sha256, size}) and returns the same data.
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
Invoke-InstallerExtraction @p
