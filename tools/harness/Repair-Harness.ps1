#requires -Version 7.0
<#
.SYNOPSIS
  Recover acceptance-identity install surfaces left behind by a crashed/aborted harness run (issue #55).
.DESCRIPTION
  Reads journals from <harness root>\journal and restores ONLY the fixed acceptance-identity allow-list
  (uninstall key, remembered-location key, Run value, Start Menu + Desktop shortcuts), per value, with
  compare-and-swap. Never touches production keys or the shared publisher subtree. A missing or corrupt
  journal means NO destructive action: the problem is reported and the script exits 2.
  Defense in depth, not a guarantee.

  Exit codes: 0 all journals finalised / nothing to do, 1 unexpected error, 2 journal missing or corrupt,
              3 a surface needs a manual step (completed install needs uninstall, or CAS/verify failed).
.PARAMETER RunId   Recover one run. Omit to process every unfinished journal.
.NOTES
  -RegistryRoot / -ShortcutDir / -JournalDir / -HarnessRoot exist for tests (scratch hive + private dirs).
#>
[CmdletBinding()]
param(
    [string]$RunId,
    [string]$RegistryRoot = 'HKCU:\Software',
    [string]$ShortcutDir,
    [string]$JournalDir,
    [string]$HarnessRoot,
    [string]$LockMutexName,
    [switch]$SkipProcessKill
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '..\lib\InstallGuard.psm1') -DisableNameChecking
Import-Module (Join-Path $PSScriptRoot 'HarnessJournal.psm1') -DisableNameChecking

$lock = $null
$exit = 0
try {
    $lockArgs = @{ HarnessRoot = $HarnessRoot }
    if ($LockMutexName) { $lockArgs.MutexName = $LockMutexName }
    $lock = Enter-HarnessLock @lockArgs

    $jdir = Get-JournalDir -JournalDir $JournalDir -HarnessRoot $HarnessRoot
    if ($RunId) { $ids = @($RunId) }
    elseif (Test-Path -LiteralPath $jdir) {
        $ids = @(Get-ChildItem -LiteralPath $jdir -Filter '*.json' -File |
            Where-Object { $_.Name -notlike '*.recovered.json' } | ForEach-Object { $_.BaseName })
    } else { $ids = @() }
    if ($ids.Count -eq 0) { Write-Host 'No unfinished harness journals found. Nothing to do.'; return }

    foreach ($id in $ids) {
        try {
            $r = Invoke-HarnessRecovery -RunId $id -RegistryRoot $RegistryRoot -ShortcutDir $ShortcutDir -JournalDir $JournalDir -HarnessRoot $HarnessRoot -SkipProcessKill:$SkipProcessKill
            Write-Host "run $id : finalized=$($r.Finalized)"
            foreach ($s in $r.Surfaces) { Write-Host ("  {0,-22} {1}" -f $s.Id, $s.Action) }
            if ($r.ExitCode -ne 0) { $exit = [Math]::Max($exit, 3); Write-Host '  A surface needs a manual step (uninstall the acceptance install, or investigate). Journal kept.' }
        } catch {
            if ($_.Exception.Message -match '^(JournalMissing|JournalCorrupt)') {
                Write-Host "run ${id}: $($_.Exception.Message). No destructive action taken. Inspect the harness state manually."
                $exit = 2
            } else { throw }
        }
    }
} catch {
    Write-Host "Repair-Harness failed: $($_.Exception.Message)"
    $exit = 1
} finally {
    if ($lock) { Exit-HarnessLock -Lock $lock }
}
exit $exit
