#requires -Version 7.0
# HarnessJournal - recovery journal + compare-and-swap recovery for issue #55.
#
# Defense in depth, NOT a guarantee: the journal lets a crashed/aborted
# acceptance run put the FIXED acceptance-identity surfaces back the way it
# found them. It never touches production keys, the shared publisher subtree,
# or anything outside the allow-list in HarnessIdentity.psd1.
#
# Surface paths are always derived from the identity constants, never from
# journal content, so a tampered journal cannot redirect a write.
#
# Every function accepts -RegistryRoot / -ShortcutDir / -HarnessRoot so tests
# run against a scratch hive and private temp dirs. NSIS and the Shell COM
# are not redirected by those overrides; they only affect this module.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot '..\lib\InstallGuard.psm1') -DisableNameChecking

$script:Identity = Get-HarnessIdentity
$script:JournalSchema = 1

# ---------------------------------------------------------------------------
# Registry primitives (.NET, so value kinds and absence are preserved)
# ---------------------------------------------------------------------------

function Split-RegPath {
    param([string]$Path)
    # HKCU only: this module never reads or writes HKLM.
    $m = [regex]::Match($Path, '^HKCU:\\([^\\].*[^\\]|[^\\])\z')
    if (-not $m.Success -or $Path.Contains('\\')) { throw "Unsupported registry path: $Path" }
    [pscustomobject]@{ Hive = [Microsoft.Win32.Registry]::CurrentUser; Sub = $m.Groups[1].Value }
}

function Convert-RegValueToSnap {
    param([Microsoft.Win32.RegistryKey]$Key, [string]$Name)
    $kind = $Key.GetValueKind($Name)
    $raw = $Key.GetValue($Name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    $data = switch ($kind) {
        'Binary'      { [Convert]::ToBase64String([byte[]]$raw) }
        'MultiString' { , @([string[]]$raw) }
        'DWord'       { ([uint32]([int]$raw -band 0xFFFFFFFFL)).ToString() }
        'QWord'       { ([int64]$raw).ToString() }
        default       { [string]$raw }
    }
    [ordered]@{ name = $Name; kind = [string]$kind; data = $data }
}

function Set-RegValueFromSnap {
    param([Microsoft.Win32.RegistryKey]$Key, $Snap)
    $kind = [Microsoft.Win32.RegistryValueKind]$Snap['kind']
    $data = $Snap['data']
    $val = switch ($kind) {
        'Binary'      { , [Convert]::FromBase64String([string]$data) }
        'MultiString' { , [string[]]@($data) }
        'DWord'       { [BitConverter]::ToInt32([BitConverter]::GetBytes([uint32]$data), 0) }
        'QWord'       { [int64]$data }
        default       { [string]$data }
    }
    $Key.SetValue([string]$Snap['name'], $val, $kind)
}

# ---------------------------------------------------------------------------
# Surface definitions (the fixed allow-list)
# ---------------------------------------------------------------------------

function Get-HarnessSurfaceDefinition {
    [CmdletBinding()]
    param([string]$RegistryRoot = 'HKCU:\Software', [string]$ShortcutDir, [string]$StartMenuDir, [string]$DesktopDir)
    # Single choke point for New-HarnessJournal, Set-JournalOwnedAfter, Invoke-HarnessRecovery and Repair-Harness.ps1.
    # Overrides must pass the POSITIVE allowlist (Assert-AllowedOverridePath); the registry root must match the exact
    # allowlist. Values this module resolves itself (GetFolderPath) skip only the temp-container rule, never the
    # structural / reparse / production checks. Each File surface is stamped with its validated Container, which
    # mutation sites re-assert immediately before acting (narrows, does not eliminate, check-then-use).
    Assert-SafeRegistryRoot -RegistryRoot $RegistryRoot
    $acc = $script:Identity.Acceptance
    $reg = $script:Identity.Registry
    if ($ShortcutDir) { [void](Assert-AllowedOverridePath -Path $ShortcutDir -What 'ShortcutDir override') }
    $resolve = {
        param([string]$Explicit, [string]$SubName, [string]$Special, [string]$Label)
        if ($Explicit) { return (Assert-AllowedOverridePath -Path $Explicit -What "$Label override") }
        if ($ShortcutDir) { return (Assert-AllowedOverridePath -Path (Join-Path $ShortcutDir $SubName) -What "ShortcutDir\$SubName") }
        $d = [Environment]::GetFolderPath($Special)
        if ([string]::IsNullOrWhiteSpace($d)) { throw "Could not resolve the $Label folder." }
        Assert-AllowedOverridePath -Path $d -What "default $Label" -DefaultLocation
    }
    $StartMenuDir = & $resolve $StartMenuDir 'StartMenu' 'Programs' 'StartMenuDir'
    $DesktopDir = & $resolve $DesktopDir 'Desktop' 'DesktopDirectory' 'DesktopDir'
    $tokens = @{
        '{ProductName}' = $acc.ProductName; '{Manufacturer}' = $acc.Manufacturer
        '{UninstallKeyParent}' = $reg.UninstallKeyParent; '{RunKey}' = $reg.RunKey
    }
    $expand = { param($s) if ($null -eq $s) { return $null }; foreach ($k in $tokens.Keys) { $s = $s.Replace($k, $tokens[$k]) }; $s }
    foreach ($e in $script:Identity.RecoveryAllowList) {
        $def = [ordered]@{ Id = $e.Id; Type = $e.Type; KeyPath = $null; ValueName = $null; FilePath = $null; Container = $null; RegistryRoot = $RegistryRoot }
        if ($e.Type -eq 'File') {
            $dir = if ($e.Folder -eq 'StartMenu') { $StartMenuDir } else { $DesktopDir }
            $def.Container = $dir
            $def.FilePath = Join-Path $dir (& $expand $e.FileTemplate)
        } else {
            $def.KeyPath = $RegistryRoot.TrimEnd('\') + '\' + (& $expand $e.KeyTemplate)
            $def.ValueName = & $expand $e.ValueName
        }
        [pscustomobject]$def
    }
}

function Get-SurfaceSnapshot {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Surface)
    switch ($Surface.Type) {
        'RegKey' {
            $p = Split-RegPath $Surface.KeyPath
            $k = $p.Hive.OpenSubKey($p.Sub, $false)
            if (-not $k) { return [ordered]@{ type = 'RegKey'; exists = $false } }
            try {
                $vals = @($k.GetValueNames() | Sort-Object -CaseSensitive | ForEach-Object { Convert-RegValueToSnap -Key $k -Name $_ })
                [ordered]@{ type = 'RegKey'; exists = $true; values = $vals; subkeys = @($k.GetSubKeyNames() | Sort-Object) }
            } finally { $k.Dispose() }
        }
        'RegValue' {
            $p = Split-RegPath $Surface.KeyPath
            $k = $p.Hive.OpenSubKey($p.Sub, $false)
            if (-not $k) { return [ordered]@{ type = 'RegValue'; exists = $false } }
            try {
                if ($k.GetValueNames() -cnotcontains $Surface.ValueName) { return [ordered]@{ type = 'RegValue'; exists = $false } }
                $v = Convert-RegValueToSnap -Key $k -Name $Surface.ValueName
                [ordered]@{ type = 'RegValue'; exists = $true; kind = $v.kind; data = $v.data }
            } finally { $k.Dispose() }
        }
        'File' {
            if (-not (Test-Path -LiteralPath $Surface.FilePath -PathType Leaf)) { return [ordered]@{ type = 'File'; exists = $false } }
            $bytes = [IO.File]::ReadAllBytes($Surface.FilePath)
            [ordered]@{ type = 'File'; exists = $true; size = $bytes.Length; sha256 = (Get-FileSha256 -Path $Surface.FilePath); bytesB64 = [Convert]::ToBase64String($bytes) }
        }
        default { throw "Unknown surface type $($Surface.Type)" }
    }
}

function ConvertTo-Canonical {
    # Deterministic form for comparison: sorted dictionary keys, arrays kept in order.
    param($Value)
    if ($null -eq $Value) { return $null }
    if ($Value -is [System.Collections.IDictionary]) {
        $o = [ordered]@{}
        foreach ($k in ($Value.Keys | Sort-Object { [string]$_ } -CaseSensitive)) { $o[[string]$k] = ConvertTo-Canonical $Value[$k] }
        return $o
    }
    if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
        return , @(foreach ($i in $Value) { ConvertTo-Canonical $i })
    }
    if ($Value -is [bool] -or $Value -is [string]) { return $Value }
    if ($Value -is [ValueType]) { return [string]$Value }
    $Value
}

function Test-SnapshotEqual {
    [CmdletBinding()]
    param($A, $B)
    if ($null -eq $A -or $null -eq $B) { return ($null -eq $A -and $null -eq $B) }
    $ja = (ConvertTo-Canonical $A) | ConvertTo-Json -Depth 12 -Compress
    $jb = (ConvertTo-Canonical $B) | ConvertTo-Json -Depth 12 -Compress
    $ja -ceq $jb
}

function Get-SnapshotFingerprint {
    param($Snap)
    $json = (ConvertTo-Canonical $Snap) | ConvertTo-Json -Depth 12 -Compress
    $h = [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($json))
    ([BitConverter]::ToString($h) -replace '-', '').ToLowerInvariant()
}

function Restore-SurfaceSnapshot {
    <# Applies a snapshot to a surface. Missing => delete only that surface (never a parent key). #>
    param([Parameter(Mandatory)]$Surface, [Parameter(Mandatory)]$Snap)
    switch ($Surface.Type) {
        'RegKey' {
            $p = Split-RegPath $Surface.KeyPath
            if (-not $Snap['exists']) { $p.Hive.DeleteSubKeyTree($p.Sub, $false); return }
            $k = $p.Hive.CreateSubKey($p.Sub)
            try {
                $want = @{}
                foreach ($v in @($Snap['values'])) { $want[[string]$v['name']] = $v }
                foreach ($n in @($k.GetValueNames())) { if (-not $want.ContainsKey($n)) { $k.DeleteValue($n, $false) } }
                foreach ($v in $want.Values) { Set-RegValueFromSnap -Key $k -Snap $v }
            } finally { $k.Dispose() }
        }
        'RegValue' {
            $p = Split-RegPath $Surface.KeyPath
            if (-not $Snap['exists']) {
                $k = $p.Hive.OpenSubKey($p.Sub, $true)
                if ($k) { try { $k.DeleteValue($Surface.ValueName, $false) } finally { $k.Dispose() } }
                return
            }
            $k = $p.Hive.CreateSubKey($p.Sub)
            try { Set-RegValueFromSnap -Key $k -Snap ([ordered]@{ name = $Surface.ValueName; kind = $Snap['kind']; data = $Snap['data'] }) } finally { $k.Dispose() }
        }
        'File' {
            # Re-validate the container chain IMMEDIATELY before mutating (narrows, does not eliminate, the TOCTOU window).
            Assert-HarnessOwnedPath -Path $Surface.FilePath -Root $Surface.Container -What "surface $($Surface.Id)"
            if (-not $Snap['exists']) { if (Test-Path -LiteralPath $Surface.FilePath) { Remove-Item -LiteralPath $Surface.FilePath -Force }; return }
            Write-AtomicBytes -Path $Surface.FilePath -Bytes ([Convert]::FromBase64String([string]$Snap['bytesB64'])) -Container $Surface.Container
        }
    }
}

# ---------------------------------------------------------------------------
# Journal persistence
# ---------------------------------------------------------------------------

function Get-JournalDir {
    param([string]$JournalDir, [string]$HarnessRoot)
    if ($JournalDir) { return (Assert-AllowedOverridePath -Path $JournalDir -What 'journal dir override') }
    Get-HarnessSubdir -Name Journal -HarnessRoot $HarnessRoot
}

function Write-AtomicBytes {
    # Private (not exported): a generic "write anywhere" primitive must not be reachable from outside.
    # tmp file in the same directory -> flush to disk -> rename. Directory-entry durability is not claimed.
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][byte[]]$Bytes, [Parameter(Mandatory)][string]$Container)
    Assert-HarnessOwnedPath -Path $Path -Root $Container -What 'write target'
    $dir = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($Path))
    if (-not (Test-Path -LiteralPath $dir)) { [void][IO.Directory]::CreateDirectory($dir) }
    $tmp = "$Path.tmp-$PID-$([guid]::NewGuid().ToString('N'))"
    Assert-HarnessOwnedPath -Path $tmp -Root $Container -What 'write temp file'
    $fs = [IO.File]::Open($tmp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $fs.Write($Bytes, 0, $Bytes.Length); $fs.Flush($true) } finally { $fs.Dispose() }
    try {
        Assert-HarnessOwnedPath -Path $Path -Root $Container -What 'write target'
        if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($tmp, $Path, [NullString]::Value) } else { [IO.File]::Move($tmp, $Path) }
    } catch {
        if (Test-PathContainedNoReparse -Path $tmp -Root $Container) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
        throw
    }
}

function Test-RegData {
    # $null when valid, else a reason. Mirrors what Convert-RegValueToSnap produces.
    param([string]$Kind, $Data)
    switch ($Kind) {
        { $_ -in 'String', 'ExpandString' } { if ($Data -isnot [string]) { return 'string data expected' } }
        'MultiString' { if ($Data -is [string] -or $Data -isnot [System.Collections.IEnumerable]) { return 'string[] expected' }; foreach ($x in $Data) { if ($x -isnot [string]) { return 'string[] expected' } } }
        'DWord' { $u = [uint32]0; if ($Data -isnot [string] -or -not [uint32]::TryParse($Data, [ref]$u)) { return 'uint32 string expected' } }
        'QWord' { $q = [int64]0; if ($Data -isnot [string] -or -not [int64]::TryParse($Data, [ref]$q)) { return 'int64 string expected' } }
        'Binary' { if ($Data -isnot [string]) { return 'base64 expected' }; try { [void][Convert]::FromBase64String($Data) } catch { return 'base64 not decodable' } }
        default { return "unsupported kind '$Kind'" }
    }
    $null
}

function Test-SnapshotShape {
    # $null when the snapshot is well-formed for the surface type, else a reason. Validates EVERYTHING recovery would later apply.
    param($Snap, [string]$Type)
    if ($Snap -isnot [System.Collections.IDictionary]) { return 'snapshot is not an object' }
    if (-not $Snap.Contains('type') -or $Snap['type'] -cne $Type) { return 'snapshot type mismatch' }
    if (-not $Snap.Contains('exists') -or $Snap['exists'] -isnot [bool]) { return 'snapshot exists flag invalid' }
    if (-not $Snap['exists']) { return $null }
    switch ($Type) {
        'RegKey' {
            if (-not $Snap.Contains('values') -or $Snap['values'] -isnot [System.Collections.IList]) { return 'values missing' }
            if (-not $Snap.Contains('subkeys') -or $Snap['subkeys'] -isnot [System.Collections.IList]) { return 'subkeys missing' }
            $names = @{}
            foreach ($v in $Snap['values']) {
                if ($v -isnot [System.Collections.IDictionary] -or -not $v.Contains('name') -or $v['name'] -isnot [string] -or -not $v.Contains('kind') -or -not $v.Contains('data')) { return 'value entry malformed' }
                if ($names.ContainsKey($v['name'])) { return 'duplicate value name' }
                $names[$v['name']] = $true
                $r = Test-RegData -Kind ([string]$v['kind']) -Data $v['data']
                if ($r) { return "value '$($v['name'])': $r" }
            }
            foreach ($s in $Snap['subkeys']) { if ($s -isnot [string]) { return 'subkey name invalid' } }
        }
        'RegValue' {
            if (-not $Snap.Contains('kind') -or -not $Snap.Contains('data')) { return 'kind/data missing' }
            $r = Test-RegData -Kind ([string]$Snap['kind']) -Data $Snap['data']
            if ($r) { return $r }
        }
        'File' {
            foreach ($f in 'bytesB64', 'sha256', 'size') { if (-not $Snap.Contains($f)) { return "file field $f missing" } }
            if ($Snap['bytesB64'] -isnot [string] -or $Snap['sha256'] -isnot [string]) { return 'file fields invalid' }
            $bytes = $null
            try { $bytes = [Convert]::FromBase64String($Snap['bytesB64']) } catch { return 'file bytes not base64' }
            if ($Snap['size'] -isnot [int] -and $Snap['size'] -isnot [long]) { return 'file size invalid' }
            if ([int64]$Snap['size'] -ne $bytes.Length) { return 'file size does not match bytes' }
            $h = ([BitConverter]::ToString([Security.Cryptography.SHA256]::HashData($bytes)) -replace '-', '').ToLowerInvariant()
            if ($h -cne $Snap['sha256'].ToLowerInvariant()) { return 'file sha256 does not match bytes' }
        }
    }
    $null
}

function Get-JournalPath {
    param([string]$RunId, [string]$JournalDir, [string]$HarnessRoot)
    if ($RunId -notmatch '^[A-Za-z0-9][A-Za-z0-9-]{5,63}$') { throw "Invalid runId '$RunId'." }
    Join-Path (Get-JournalDir -JournalDir $JournalDir -HarnessRoot $HarnessRoot) "$RunId.json"
}

function Save-HarnessJournal {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Journal, [string]$JournalDir, [string]$HarnessRoot)
    $path = Get-JournalPath -RunId $Journal['runId'] -JournalDir $JournalDir -HarnessRoot $HarnessRoot
    $json = $Journal | ConvertTo-Json -Depth 16
    Write-AtomicBytes -Path $path -Bytes ([Text.Encoding]::UTF8.GetBytes($json)) -Container (Get-JournalDir -JournalDir $JournalDir -HarnessRoot $HarnessRoot)
    $path
}

function Read-HarnessJournal {
    <# Throws with message starting 'JournalMissing' or 'JournalCorrupt' - callers must treat both as
       "no destructive action". Validates schema, ids against the allow-list, and install dir containment. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$RunId, [string]$JournalDir, [string]$HarnessRoot)
    $path = Get-JournalPath -RunId $RunId -JournalDir $JournalDir -HarnessRoot $HarnessRoot
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "JournalMissing: $RunId" }
    $j = $null
    try { $j = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json -AsHashtable -DateKind String -Depth 32 }
    catch { throw "JournalCorrupt: $RunId not parseable" }
    $bad = { param($why) throw "JournalCorrupt: $RunId $why" }
    if ($j -isnot [System.Collections.IDictionary]) { & $bad 'not an object' }
    foreach ($f in 'schema', 'runId', 'generation', 'installDir', 'surfaces', 'restored') { if (-not $j.Contains($f)) { & $bad "missing $f" } }
    if ($j['schema'] -ne $script:JournalSchema) { & $bad 'schema version' }
    if ($j['runId'] -cne $RunId) { & $bad 'runId does not match file' }
    $g = [guid]::Empty
    if (-not [guid]::TryParse([string]$j['generation'], [ref]$g)) { & $bad 'generation token' }
    if ($j['surfaces'] -isnot [System.Collections.IDictionary] -or $j['restored'] -isnot [System.Collections.IDictionary]) { & $bad 'surfaces/restored shape' }
    $allowed = @($script:Identity.RecoveryAllowList | ForEach-Object { $_.Id })
    # Everything below is validated up front, for EVERY surface, so recovery never mutates on a half-valid journal.
    foreach ($f in 'state', 'installVersion', 'installerSha256', 'uninstallerSha256', 'processes') { if (-not $j.Contains($f)) { & $bad "missing $f" } }
    if ($j['state'] -cnotin @('armed', 'installed')) { & $bad 'state invalid' }
    if ($j['installVersion'] -isnot [string] -or -not (ConvertTo-SemVerParts $j['installVersion'])) { & $bad 'installVersion missing or not strict semver' }
    foreach ($h in 'installerSha256', 'uninstallerSha256') {
        if ($null -ne $j[$h] -and ($j[$h] -isnot [string] -or $j[$h] -notmatch '^[0-9a-f]{64}$')) { & $bad "$h malformed" }
    }
    if ($j['processes'] -isnot [System.Collections.IList]) { & $bad 'processes malformed' }
    foreach ($p in $j['processes']) {
        if ($p -isnot [System.Collections.IDictionary] -or -not $p.Contains('pid') -or -not $p.Contains('startTicks') -or -not $p.Contains('path') -or
            ($p['pid'] -isnot [int] -and $p['pid'] -isnot [long]) -or ($p['startTicks'] -isnot [long] -and $p['startTicks'] -isnot [int]) -or $p['path'] -isnot [string]) { & $bad 'process record malformed' }
    }
    if ($j['restored'].Count -ne $allowed.Count) { & $bad 'restored flags do not match allow-list' }
    foreach ($id in $j['surfaces'].Keys) { if ($allowed -cnotcontains $id) { & $bad "surface $id is not in the allow-list" } }
    foreach ($e in $script:Identity.RecoveryAllowList) {
        $id = $e.Id
        if (-not $j['surfaces'].Contains($id)) { & $bad "surface $id missing" }
        if (-not $j['restored'].Contains($id) -or $j['restored'][$id] -isnot [bool]) { & $bad "restored flag $id invalid" }
        $s = $j['surfaces'][$id]
        if ($s -isnot [System.Collections.IDictionary] -or -not $s.Contains('before')) { & $bad "surface $id malformed" }
        $why = Test-SnapshotShape -Snap $s['before'] -Type $e.Type
        if ($why) { & $bad "surface $id before-snapshot: $why" }
        $oa = if ($s.Contains('ownedAfter')) { $s['ownedAfter'] } else { $null }
        if ($null -ne $oa) {
            $why = Test-SnapshotShape -Snap $oa -Type $e.Type
            if ($why) { & $bad "surface $id ownedAfter: $why" }
            if (-not $s.Contains('ownedAfterFingerprint') -or $s['ownedAfterFingerprint'] -isnot [string]) { & $bad "surface $id ownedAfter fingerprint missing" }
            if ((Get-SnapshotFingerprint $oa) -cne $s['ownedAfterFingerprint']) { & $bad "surface $id ownedAfter does not match its recorded fingerprint" }
        } elseif ($j['state'] -ceq 'installed') { & $bad "surface $id has no ownedAfter although state is installed" }
    }
    # Destination binding: the validated destination set this journal was created for.
    if (-not $j.Contains('destinations') -or $j['destinations'] -isnot [System.Collections.IDictionary]) { & $bad 'destinations missing' }
    foreach ($k in 'registryRoot', 'startMenuDir', 'desktopDir', 'harnessRoot') {
        if (-not $j['destinations'].Contains($k) -or $j['destinations'][$k] -isnot [string] -or [string]::IsNullOrWhiteSpace($j['destinations'][$k])) { & $bad "destination $k invalid" }
    }
    $root = Get-HarnessRoot -HarnessRoot $HarnessRoot
    $installRoot = Join-Path $root $script:Identity.HarnessSubdirs.Install
    # real-path style containment (lexical AND reparse-free), not lexical only
    if (-not (Test-PathContainedNoReparse -Path ([string]$j['installDir']) -Root $installRoot)) { & $bad 'installDir outside harness install tree or behind a reparse point' }
    $j
}

function Assert-JournalDestinations {
    <# Recovery/owned-after may only act on the destination set the journal was created for. A mismatch is
       JournalCorrupt-class (Repair-Harness exit 2) and happens before any mutation. #>
    param([Parameter(Mandatory)]$Journal, [Parameter(Mandatory)]$Defs, [Parameter(Mandatory)][string]$HarnessRoot)
    $same = { param($a, $b) ([IO.Path]::GetFullPath($a).TrimEnd('\')).Equals(([IO.Path]::GetFullPath($b).TrimEnd('\')), [StringComparison]::OrdinalIgnoreCase) }
    $want = $Journal['destinations']
    $sm = ($Defs | Where-Object Id -eq 'StartMenuShortcut').Container
    $dk = ($Defs | Where-Object Id -eq 'DesktopShortcut').Container
    $rr = ($Defs | Select-Object -First 1).RegistryRoot
    $mismatch = $null
    if ($want['registryRoot'] -cne $rr) { $mismatch = 'registryRoot' }
    elseif (-not (& $same $want['startMenuDir'] $sm)) { $mismatch = 'startMenuDir' }
    elseif (-not (& $same $want['desktopDir'] $dk)) { $mismatch = 'desktopDir' }
    elseif (-not (& $same $want['harnessRoot'] $HarnessRoot)) { $mismatch = 'harnessRoot' }
    if ($mismatch) { throw "JournalCorrupt: $($Journal['runId']) destination '$mismatch' differs from the validated destination set" }
}

function New-HarnessJournal {
    <# Snapshots every surface ('before') and writes the journal atomically. Call BEFORE any installer starts. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RunId,
        [Parameter(Mandatory)][string]$InstallDir,
        [string]$InstallVersion,
        [string]$RegistryRoot = 'HKCU:\Software', [string]$ShortcutDir, [string]$StartMenuDir, [string]$DesktopDir,
        [string]$JournalDir, [string]$HarnessRoot
    )
    # F4: the version this run installs is mandatory (recovery's "newer install took over" guard needs it).
    # Two-phase upgrade (O1: old rewrap installs, then new rewrap upgrades) = ONE JOURNAL PER PHASE, each with
    # its own runId and installVersion. Phase 2's journal is created after phase 1 finished, so its 'before'
    # snapshot is phase 1's installed state; recovering phase 2 returns to phase 1, never further back.
    if ([string]::IsNullOrWhiteSpace($InstallVersion) -or -not (ConvertTo-SemVerParts $InstallVersion)) { throw 'Refused: InstallVersion is mandatory and must be strict semver.' }
    $root = Get-HarnessRoot -HarnessRoot $HarnessRoot
    Assert-HarnessOwnedPath -Path $InstallDir -Root (Join-Path $root $script:Identity.HarnessSubdirs.Install) -What 'install dir'
    if (-not (Test-PathContained -Path $InstallDir -Root (Join-Path $root $script:Identity.HarnessSubdirs.Install))) { throw 'Refused: install dir must be below the harness install tree.' }
    $jpath = Get-JournalPath -RunId $RunId -JournalDir $JournalDir -HarnessRoot $HarnessRoot
    if (Test-Path -LiteralPath $jpath) { throw "Journal for run $RunId already exists." }
    $defs = Get-HarnessSurfaceDefinition -RegistryRoot $RegistryRoot -ShortcutDir $ShortcutDir -StartMenuDir $StartMenuDir -DesktopDir $DesktopDir
    $surfaces = [ordered]@{}
    foreach ($d in $defs) { $surfaces[$d.Id] = [ordered]@{ before = (Get-SurfaceSnapshot -Surface $d); ownedAfter = $null } }
    $destinations = [ordered]@{
        registryRoot = $RegistryRoot
        startMenuDir = [string]($defs | Where-Object Id -eq 'StartMenuShortcut').Container
        desktopDir   = [string]($defs | Where-Object Id -eq 'DesktopShortcut').Container
        harnessRoot  = $root
    }
    $j = [ordered]@{
        schema = $script:JournalSchema; runId = $RunId; generation = [guid]::NewGuid().ToString()
        createdUtc = [DateTime]::UtcNow.ToString('o'); state = 'armed'
        harnessPid = $PID; harnessStartTicks = (Get-ProcessStartTicks -ProcessId $PID)
        installDir = [IO.Path]::GetFullPath($InstallDir); installVersion = $InstallVersion
        installerSha256 = $null; uninstallerSha256 = $null
        processes = @(); surfaces = $surfaces; destinations = $destinations
        restored = [ordered]@{}
    }
    foreach ($d in $defs) { $j['restored'][$d.Id] = $false }
    [void](Save-HarnessJournal -Journal $j -JournalDir $JournalDir -HarnessRoot $HarnessRoot)
    Read-HarnessJournal -RunId $RunId -JournalDir $JournalDir -HarnessRoot $HarnessRoot
}

function Update-HarnessJournal {
    <# Re-read -> verify generation -> mutate -> atomic save. Guards against a stale in-memory copy. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Journal, [Parameter(Mandatory)][scriptblock]$Mutate, [string]$JournalDir, [string]$HarnessRoot)
    $fresh = Read-HarnessJournal -RunId $Journal['runId'] -JournalDir $JournalDir -HarnessRoot $HarnessRoot
    if ($fresh['generation'] -cne $Journal['generation']) { throw 'Journal generation token changed underneath this run; refusing to write.' }
    & $Mutate $fresh
    [void](Save-HarnessJournal -Journal $fresh -JournalDir $JournalDir -HarnessRoot $HarnessRoot)
    $fresh
}

function Set-JournalOwnedAfter {
    <# After the installer finished: record what THIS run created, per surface. The uninstaller sha256 is computed
       HERE from <installDir>\uninstall.exe (never caller-supplied); if the file is absent it stays null and the
       guard will refuse to run any uninstaller. Sets state = 'installed'. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]$Journal, [string]$InstallerSha256,
        [string]$RegistryRoot = 'HKCU:\Software', [string]$ShortcutDir, [string]$StartMenuDir, [string]$DesktopDir,
        [string]$JournalDir, [string]$HarnessRoot
    )
    # Derive, don't trust: only the run id is taken from the caller's object; installDir etc. come from the journal on disk.
    $uninstallerSha = $null
    $rootForCheck = Get-HarnessRoot -HarnessRoot $HarnessRoot
    $journalNow = Read-HarnessJournal -RunId $Journal['runId'] -JournalDir $JournalDir -HarnessRoot $HarnessRoot
    $uPath = Join-Path ([string]$journalNow['installDir']) $script:Identity.Acceptance.UninstallerName
    Assert-HarnessOwnedPath -Path $uPath -Root $rootForCheck -What 'uninstaller'
    if (Test-Path -LiteralPath $uPath -PathType Leaf) { $uninstallerSha = Get-FileSha256 -Path $uPath }
    $defs = Get-HarnessSurfaceDefinition -RegistryRoot $RegistryRoot -ShortcutDir $ShortcutDir -StartMenuDir $StartMenuDir -DesktopDir $DesktopDir
    Assert-JournalDestinations -Journal $journalNow -Defs $defs -HarnessRoot $rootForCheck
    $snaps = @{}
    foreach ($d in $defs) { $snaps[$d.Id] = Get-SurfaceSnapshot -Surface $d }
    # The fingerprints are computed HERE, not inside the closure below: a `GetNewClosure()` scriptblock does not see this
    # module's own functions when the module is imported inside another module (the launcher's import model), so a
    # call to `Get-SnapshotFingerprint` from within it fails with "term not recognized" in a real lane run.
    $fingerprints = @{}
    foreach ($id in $snaps.Keys) { $fingerprints[$id] = Get-SnapshotFingerprint $snaps[$id] }
    Update-HarnessJournal -Journal $Journal -JournalDir $JournalDir -HarnessRoot $HarnessRoot -Mutate {
        param($j)
        foreach ($id in $snaps.Keys) {
            $j['surfaces'][$id]['ownedAfter'] = $snaps[$id]
            $j['surfaces'][$id]['ownedAfterFingerprint'] = $fingerprints[$id]
        }
        if ($InstallerSha256) { $j['installerSha256'] = $InstallerSha256.ToLowerInvariant() }
        if ($uninstallerSha) { $j['uninstallerSha256'] = $uninstallerSha }
        $j['state'] = 'installed'
    }.GetNewClosure()
}

function Add-JournalProcess {
    <# Record a process this run started (pid + start time) so recovery can kill only that one. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Journal, [Parameter(Mandatory)][int]$ProcessId, [string]$JournalDir, [string]$HarnessRoot)
    $ticks = Get-ProcessStartTicks -ProcessId $ProcessId
    if ($null -eq $ticks) { throw "Process $ProcessId not found; cannot track it." }
    $path = (Get-Process -Id $ProcessId).Path
    Update-HarnessJournal -Journal $Journal -JournalDir $JournalDir -HarnessRoot $HarnessRoot -Mutate {
        param($j)
        $j['processes'] = @($j['processes']) + , ([ordered]@{ pid = $ProcessId; startTicks = $ticks; path = $path })
    }.GetNewClosure()
}

# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

function Test-TrackedProcessMatch {
    <# True only if pid is alive, start time equals the recorded one, and its image lives inside the harness root. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Tracked, [string]$HarnessRoot)
    $root = Get-HarnessRoot -HarnessRoot $HarnessRoot
    try { $p = Get-Process -Id ([int]$Tracked['pid']) -ErrorAction Stop } catch { return $false }
    if ($p.StartTime.ToUniversalTime().Ticks -ne [int64]$Tracked['startTicks']) { return $false }
    $img = $null; try { $img = $p.Path } catch { }
    if (-not $img) { return $false }
    Test-PathContainedNoReparse -Path $img -Root $root
}

function Get-SnapTargets {
    <# Paths a snapshot refers to (for "points into harness" decisions). Files are scanned for the install dir in raw bytes. #>
    param($Def, $Snap, [string]$InstallDir)
    $unq = { param($s) if ($null -eq $s) { return $null }; $s = ([string]$s).Trim(); if ($s.StartsWith('"')) { $e = $s.IndexOf('"', 1); if ($e -gt 0) { return $s.Substring(1, $e - 1) } }; if ($s -match '^(.*?\.(exe|ico))(,-?\d+)?(\s|$)') { return $Matches[1] }; $s }
    $out = @()
    switch ($Def.Type) {
        'RegKey' {
            if ($Snap['exists']) {
                foreach ($v in @($Snap['values'])) {
                    if ($v['kind'] -in 'String', 'ExpandString' -and ($v['name'] -in '', 'InstallLocation', 'UninstallString', 'DisplayIcon', 'QuietUninstallString')) { $out += (& $unq $v['data']) }
                }
            }
        }
        'RegValue' { if ($Snap['exists'] -and $Snap['kind'] -in 'String', 'ExpandString') { $out += (& $unq $Snap['data']) } }
        'File' {
            if ($Snap['exists']) {
                $b = [Convert]::FromBase64String([string]$Snap['bytesB64'])
                $texts = @([Text.Encoding]::Latin1.GetString($b), [Text.Encoding]::Unicode.GetString($b))
                if ($b.Length -gt 1) { $texts += [Text.Encoding]::Unicode.GetString($b, 1, $b.Length - 1) }
                foreach ($t in $texts) { if ($t.IndexOf($InstallDir, [StringComparison]::OrdinalIgnoreCase) -ge 0) { $out += $InstallDir } }
            }
        }
    }
    , @($out | Where-Object { $_ })
}

function Test-PointsIntoHarness {
    # True only if there is at least one target and ALL targets are inside the journaled install dir.
    param($Targets, [string]$InstallDir)
    if (@($Targets).Count -eq 0) { return $false }
    foreach ($t in $Targets) { if (-not (Test-PathContainedNoReparse -Path $t -Root $InstallDir -AllowEqual)) { return $false } }
    $true
}

function ConvertTo-SemVerParts {
    param([string]$V)
    # Semver 2.0: no leading zeros in numeric identifiers, no empty prerelease identifiers.
    $num = '(0|[1-9]\d*)'
    $pre = '(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)'
    if ($V -notmatch "^\s*v?$num\.$num\.$num(?:-($pre(?:\.$pre)*))?(?:\+[0-9A-Za-z.-]+)?\s*$") { return $null }
    [pscustomobject]@{ Core = @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3]); Pre = $Matches[4] }
}

function Compare-SemVerStrict {
    # -1/0/1, or $null when either side is unparseable.
    param([string]$Left, [string]$Right)
    $x = ConvertTo-SemVerParts $Left; $y = ConvertTo-SemVerParts $Right
    if (-not $x -or -not $y) { return $null }
    for ($i = 0; $i -lt 3; $i++) { if ($x.Core[$i] -ne $y.Core[$i]) { return [Math]::Sign($x.Core[$i] - $y.Core[$i]) } }
    if ($x.Pre -eq $y.Pre) { return 0 }
    if (-not $x.Pre) { return 1 }
    if (-not $y.Pre) { return -1 }
    $pa = $x.Pre.Split('.'); $pb = $y.Pre.Split('.')
    for ($i = 0; $i -lt [Math]::Max($pa.Count, $pb.Count); $i++) {
        if ($i -ge $pa.Count) { return -1 }
        if ($i -ge $pb.Count) { return 1 }
        $na = $pa[$i] -match '^\d+$'; $nb = $pb[$i] -match '^\d+$'
        if ($na -and $nb) { $d = [int64]$pa[$i] - [int64]$pb[$i]; if ($d -ne 0) { return [Math]::Sign($d) } }
        elseif ($na) { return -1 } elseif ($nb) { return 1 }
        else { $c = [string]::CompareOrdinal($pa[$i], $pb[$i]); if ($c -ne 0) { return [Math]::Sign($c) } }
    }
    0
}

function Get-SurfaceVersion {
    param($Snap)
    if ($Snap['type'] -eq 'RegKey' -and $Snap['exists']) { foreach ($v in @($Snap['values'])) { if ($v['name'] -ceq 'DisplayVersion') { return [string]$v['data'] } } }
    $null
}

function Invoke-HarnessRecovery {
    <# Per-surface decision table (before = B, owned-after = A, current = C):
         C == B                                   -> noop
         install exe present AND (C == A or C points into install dir)
                                                  -> needs-uninstall (completed acceptance install; uninstall, do not patch registry)
         C == A, or (C points only into install dir, exe missing, version not newer)
                                                  -> restore B (delete if B absent)   [compare-and-swap]
         anything else (real dir, newer version, unknown)
                                                  -> superseded, NEVER touched
       The journal is finalised (renamed *.recovered.json) only when every surface is verified noop/restored/
       superseded. -Barrier is a fault-injection hook (tests): it validates the recovery STATE MACHINE only,
       not OS-crash or power-loss safety. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RunId,
        [string]$RegistryRoot = 'HKCU:\Software', [string]$ShortcutDir, [string]$StartMenuDir, [string]$DesktopDir,
        [string]$JournalDir, [string]$HarnessRoot,
        [scriptblock]$Barrier,
        [switch]$SkipProcessKill
    )
    $root = Get-HarnessRoot -HarnessRoot $HarnessRoot
    $jr = @{ JournalDir = $JournalDir; HarnessRoot = $HarnessRoot }
    $journal = Read-HarnessJournal -RunId $RunId @jr     # JournalMissing / JournalCorrupt propagate: no destructive action
    $installDir = [string]$journal['installDir']
    $exe = Join-Path $installDir $script:Identity.Acceptance.MainBinaryName
    $defs = Get-HarnessSurfaceDefinition -RegistryRoot $RegistryRoot -ShortcutDir $ShortcutDir -StartMenuDir $StartMenuDir -DesktopDir $DesktopDir
    Assert-JournalDestinations -Journal $journal -Defs $defs -HarnessRoot $root      # before any mutation, including process kill
    $killed = @()
    if (-not $SkipProcessKill) {
        foreach ($t in @($journal['processes'])) {
            if (Test-TrackedProcessMatch -Tracked $t -HarnessRoot $HarnessRoot) { Stop-Process -Id ([int]$t['pid']) -Force; $killed += [int]$t['pid'] }
        }
    }
    # Run-level guard: if ANY surface carries a version that is newer than (or cannot be compared with) the
    # version this run installed, a different install has taken over; every surface is then left alone.
    $runSuperseded = $false
    foreach ($d in $defs) {
        $snapNow = Get-SurfaceSnapshot -Surface $d
        if (Test-SnapshotEqual $snapNow $journal['surfaces'][$d.Id]['before']) { continue }   # untouched: not evidence of a takeover
        $v = Get-SurfaceVersion $snapNow
        if ($v) {
            $cmp0 = Compare-SemVerStrict $v ([string]$journal['installVersion'])
            if ($null -eq $cmp0 -or $cmp0 -gt 0) { $runSuperseded = $true }
        }
    }
    $results = @()
    foreach ($d in $defs) {
        $id = $d.Id
        if ($journal['restored'][$id] -eq $true) { $results += [pscustomobject]@{ Id = $id; Action = 'already-restored' }; continue }
        $surf = $journal['surfaces'][$id]
        $before = $surf['before']; $after = $surf['ownedAfter']
        $cur = Get-SurfaceSnapshot -Surface $d
        $action = $null
        if (Test-SnapshotEqual $cur $before) { $action = 'noop' }
        else {
            $isOwned = ($null -ne $after) -and (Test-SnapshotEqual $cur $after)
            $targets = Get-SnapTargets -Def $d -Snap $cur -InstallDir $installDir
            $inside = Test-PointsIntoHarness -Targets $targets -InstallDir $installDir
            $exeThere = Test-Path -LiteralPath $exe -PathType Leaf
            if ($runSuperseded) { $action = 'superseded' }
            elseif ($exeThere -and ($isOwned -or $inside)) { $action = 'needs-uninstall' }
            elseif ($isOwned -or $inside) { $action = 'restore' }
            else { $action = 'superseded' }
        }
        if ($action -eq 'restore') {
            if ($Barrier) { & $Barrier "before-mutate:$id" }
            # Compare-and-swap: journal (generation, not-yet-restored) and surface state re-read immediately before mutation.
            $fresh = Read-HarnessJournal -RunId $RunId @jr
            if ($fresh['generation'] -cne $journal['generation'] -or $fresh['restored'][$id] -eq $true) { $action = 'cas-failed' }
            else {
                $cur2 = Get-SurfaceSnapshot -Surface $d
                if (-not (Test-SnapshotEqual $cur2 $cur)) { $action = 'cas-failed' }
                else {
                    Restore-SurfaceSnapshot -Surface $d -Snap $before
                    if ($Barrier) { & $Barrier "after-mutate:$id" }
                    $action = 'restored'
                }
            }
        }
        if ($action -in 'noop', 'restored') {
            $verify = Get-SurfaceSnapshot -Surface $d
            if (-not (Test-SnapshotEqual $verify $before)) { $action = 'verify-failed' }
        }
        if ($action -in 'noop', 'restored', 'superseded') {
            $journal = Update-HarnessJournal -Journal $journal @jr -Mutate { param($j) $j['restored'][$id] = $true }.GetNewClosure()
            if ($Barrier) { & $Barrier "after-journal:$id" }
        }
        $results += [pscustomobject]@{ Id = $id; Action = $action }
    }
    $done = -not (@($results | Where-Object { $_.Action -notin 'noop', 'restored', 'superseded', 'already-restored' }).Count)
    $finalPath = $null
    if ($done) {
        $jp = Get-JournalPath -RunId $RunId @jr
        $finalPath = [IO.Path]::ChangeExtension($jp, 'recovered.json')
        $jdir = Get-JournalDir @jr
        Assert-HarnessOwnedPath -Path $jp -Root $jdir -What 'journal'
        Assert-HarnessOwnedPath -Path $finalPath -Root $jdir -What 'finalized journal'
        if (Test-Path -LiteralPath $finalPath) { Remove-Item -LiteralPath $finalPath -Force }
        Move-Item -LiteralPath $jp -Destination $finalPath
    }
    [pscustomobject]@{ RunId = $RunId; Finalized = $done; FinalPath = $finalPath; KilledPids = $killed; Surfaces = $results; ExitCode = $(if ($done) { 0 } else { 3 }) }
}

Export-ModuleMember -Function Get-HarnessSurfaceDefinition, Get-SurfaceSnapshot, Test-SnapshotEqual, Get-SnapshotFingerprint,
    Save-HarnessJournal, Read-HarnessJournal, New-HarnessJournal, Update-HarnessJournal, Set-JournalOwnedAfter, Add-JournalProcess,
    Test-TrackedProcessMatch, Invoke-HarnessRecovery, Compare-SemVerStrict, Get-JournalPath, Get-JournalDir
