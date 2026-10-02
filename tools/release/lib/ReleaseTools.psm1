#requires -Version 7.0
# ReleaseTools - pinned, portable acquisition and verification of 7-Zip and NSIS (issue #55, task B).
#
# Nothing is installed globally and nothing is added to PATH. Every tool lives under a harness-owned tools
# directory (default <harness root>\tools, or an explicit -ToolsDir that passes Assert-AllowedOverridePath).
# Pins live in tools/release/tools.lock.json. Every download is verified against its pinned sha256 before it is unpacked.
# Each run then works from a PRIVATE AND VERIFIED SNAPSHOT of the tools (New-ToolSnapshot): the whole 7-Zip folder and the whole NSIS tree
# are copied into a fresh per-run directory, the COPY is hashed once against the lock, and the tools are launched from that copy
# (Start-PinnedTool re-checks the exact registered path and the exe hash). Assert-ToolVerified re-hashes the snapshot tree around a compile.
# "Private and verified" is NOT "immutable". Exact residual: a principal with write access to the harness root who races the run with
# change-and-restore, and compile-time side effects of a hostile include, are not prevented or undone. This is an accident control,
# not an adversary control.
#
# Honest limits: the lock file is the trust anchor. Where an upstream checksum exists it is named in the
# lock's `checksumSource`; otherwise the value is trust-on-first-use (TOFU) and the lock says so.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot '..\..\lib\InstallGuard.psm1') -DisableNameChecking

$script:ToolContexts = [System.Collections.Generic.List[object]]::new()   # registered tool-layout roots (cache dir, per-run snapshots): @{ Dir; Lock }
$script:ToolsDirName = 'tools'   # <harness root>\tools (not one of HarnessSubdirs; no uninstaller may ever live here either)

function Get-ToolsLock {
    [CmdletBinding()]
    param([string]$Path = (Join-Path $PSScriptRoot '..\tools.lock.json'))
    $lock = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -AsHashtable
    if ($lock.schemaVersion -ne 1) { throw "tools.lock.json: unsupported schemaVersion '$($lock.schemaVersion)'." }
    foreach ($k in 'sevenZip', 'nsis', 'tauriUtilsDll') { if (-not $lock.ContainsKey($k)) { throw "tools.lock.json: missing '$k'." } }
    $hex = '^[0-9a-f]{64}$'
    $all = @($lock.sevenZip.downloads.Values) + @($lock.nsis.download)
    foreach ($d in $all) {
        if ($d.sha256 -cnotmatch $hex) { throw "tools.lock.json: bad sha256 for $($d.fileName)." }
        if ($d.url -cnotmatch '^https://') { throw "tools.lock.json: non-https url for $($d.fileName)." }
    }
    foreach ($h in @($lock.sevenZip.binaries.Values) + @($lock.sevenZip.bootstrapBinaries.Values) + @($lock.sevenZip.treeSha256, $lock.nsis.treeSha256, $lock.nsis.makensisSha256, $lock.tauriUtilsDll.sha256)) {
        if ($h -cnotmatch $hex) { throw 'tools.lock.json: malformed pinned hash.' }
    }
    $lock
}

function Get-ReleaseToolsDir {
    <# Resolves and validates the tools directory. Creates nothing. An explicit -ToolsDir must pass the
       positive override allowlist (strictly inside temp or the default harness root, no reparse points). #>
    [CmdletBinding()]
    param([string]$ToolsDir, [string]$HarnessRoot)
    if ($ToolsDir) { return (Assert-AllowedOverridePath -Path $ToolsDir -What 'tools directory override') }
    $root = Get-HarnessRoot -HarnessRoot $HarnessRoot
    $dir = Join-Path $root $script:ToolsDirName
    Assert-HarnessOwnedPath -Path $dir -Root $root -What 'tools directory'
    $dir
}

function Get-DirectoryTreeSha256 {
    <# Deterministic tree hash: sha256 over UTF-8 lines "<lowercase relative path with />:<file sha256>\n" sorted ordinally.
       Refuses reparse points anywhere in the tree. Returns @{ Sha256; FileCount }. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)
    $root = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw "Tree not found: $root" }
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($item in (Get-ChildItem -LiteralPath $root -Recurse -Force)) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refused: reparse point inside tool tree: $($item.FullName)" }
        if ($item.PSIsContainer) { continue }
        $rel = $item.FullName.Substring($root.Length + 1).Replace('\', '/').ToLowerInvariant()
        $lines.Add("${rel}:$((Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant())")
    }
    $lines.Sort([StringComparer]::Ordinal)
    $text = ($lines -join "`n") + "`n"
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($text)
    $sha = [Security.Cryptography.SHA256]::HashData($bytes)
    @{ Sha256 = ([BitConverter]::ToString($sha).Replace('-', '').ToLowerInvariant()); FileCount = $lines.Count }
}

function Get-ReleaseToolPaths {
    # Layout under the tools dir; one place so install and verify cannot disagree.
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ToolsDir, [Parameter(Mandatory)]$Lock)
    $sz = Join-Path $ToolsDir "7zip-$($Lock.sevenZip.version)"
    $ns = Join-Path $ToolsDir "nsis-$($Lock.nsis.version)"
    @{
        Root = $ToolsDir; Downloads = Join-Path $ToolsDir 'downloads'
        SevenZipDir = $sz; SevenZr = Join-Path $sz '7zr.exe'; SevenZa = Join-Path $sz '7za.exe'
        SevenZip = Join-Path $sz '7z.exe'; SevenZipDll = Join-Path $sz '7z.dll'
        NsisDir = $ns; Makensis = Join-Path $ns 'Bin\makensis.exe'
    }
}

function Assert-FileSha256 {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Expected, [string]$What = $Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Refused: $What is missing." }
    $have = Get-FileSha256 -Path $Path
    if ($have -cne $Expected.ToLowerInvariant()) { throw "Refused: $What sha256 mismatch (expected $Expected, got $have)." }
}

function Assert-PinnedTools {
    <# Verifies the unpacked portable tools against the lock. Called after install and by callers that want a full check;
       Assert-ToolVerified / Invoke-PinnedTool re-verify again at execution time. Returns the tool paths.
       7-Zip: the WHOLE 7-Zip folder (tree hash + file count; covers any planted Codecs\ / Formats\ / extra dll), 7z.exe and 7z.dll.
       NSIS: the whole tree hash and file count. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ToolsDir, $Lock = (Get-ToolsLock), [switch]$SevenZipOnly, [switch]$NsisOnly)
    $p = Get-ReleaseToolPaths -ToolsDir $ToolsDir -Lock $Lock
    Assert-HarnessOwnedPath -Path $ToolsDir -Root $ToolsDir -What 'tools directory'   # reparse walk from the volume root
    Register-ToolContext -Dir $ToolsDir -Lock $Lock
    if (-not $NsisOnly) {
        Assert-FileSha256 -Path $p.SevenZip -Expected $Lock.sevenZip.binaries['7z.exe'] -What '7z.exe'
        Assert-FileSha256 -Path $p.SevenZipDll -Expected $Lock.sevenZip.binaries['7z.dll'] -What '7z.dll'
        Assert-TreePinned -Path $p.SevenZipDir -ExpectedSha256 $Lock.sevenZip.treeSha256 -ExpectedCount ([int]$Lock.sevenZip.treeFileCount) -What '7-Zip folder'
    }
    if (-not $SevenZipOnly) {
        if (-not (Test-Path -LiteralPath $p.NsisDir -PathType Container)) { throw 'Refused: NSIS tree is missing.' }
        Assert-TreePinned -Path $p.NsisDir -ExpectedSha256 $Lock.nsis.treeSha256 -ExpectedCount ([int]$Lock.nsis.treeFileCount) -What 'NSIS tree'
        if (-not (Test-Path -LiteralPath $p.Makensis -PathType Leaf)) { throw 'Refused: makensis.exe is missing from the NSIS tree.' }
    }
    $p
}

function Assert-TreePinned {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$ExpectedSha256, [Parameter(Mandatory)][int]$ExpectedCount, [string]$What = 'tree')
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "Refused: $What is missing." }
    $t = Get-DirectoryTreeSha256 -Path $Path
    if ($t.Sha256 -cne $ExpectedSha256 -or $t.FileCount -ne $ExpectedCount) {
        throw "Refused: $What hash mismatch (expected $ExpectedSha256/$ExpectedCount, got $($t.Sha256)/$($t.FileCount))."
    }
}

function Resolve-PinnedToolPath {
    # Shared by Assert-ToolVerified and Start-PinnedTool: the exe must be EXACTLY a registered tool path (the cache tools dir or a per-run
    # snapshot), with no reparse point anywhere on its path. Returns @{ Full; Leaf; Paths; Lock }.
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Exe)
    if (-not [IO.Path]::IsPathRooted($Exe) -or -not (Test-Path -LiteralPath $Exe -PathType Leaf)) { throw "Refused: tool path is not an existing absolute file: $Exe" }
    $leaf = [IO.Path]::GetFileName($Exe).ToLowerInvariant()
    if ($leaf -notin @('7zr.exe', '7za.exe', '7z.exe', 'makensis.exe')) { throw "Refused: '$leaf' is not an allowed pinned tool." }
    if ($script:ToolContexts.Count -eq 0) { throw 'Refused: no verified tools directory is registered (call Install-PinnedTools / Assert-PinnedTools first).' }
    $full = [IO.Path]::GetFullPath($Exe)
    foreach ($ctx in @($script:ToolContexts)) {
        $tp = Get-ReleaseToolPaths -ToolsDir $ctx.Dir -Lock $ctx.Lock
        $expectedPath = switch ($leaf) { '7zr.exe' { $tp.SevenZr } '7za.exe' { $tp.SevenZa } '7z.exe' { $tp.SevenZip } 'makensis.exe' { $tp.Makensis } }
        if ($full.Equals([IO.Path]::GetFullPath($expectedPath), [StringComparison]::OrdinalIgnoreCase)) {
            if (-not (Test-PathContainedNoReparse -Path $full -Root $ctx.Dir)) { throw "Refused: $leaf is outside the verified tools directory or traverses a reparse point." }
            return @{ Full = $full; Leaf = $leaf; Paths = $tp; Lock = $ctx.Lock }
        }
    }
    throw "Refused: $leaf is not the tool inside the verified tools directory (or a registered snapshot)."
}

function Get-PinnedExeSha256 {
    param($R)
    $lk = $R.Lock
    switch ($R.Leaf) {
        '7zr.exe' { $lk.sevenZip.bootstrapBinaries['7zr.exe'] }
        '7za.exe' { $lk.sevenZip.bootstrapBinaries['7za.exe'] }
        '7z.exe' { $lk.sevenZip.binaries['7z.exe'] }
        'makensis.exe' { $lk.nsis.makensisSha256 }
    }
}

function Assert-ToolVerified {
    <# FULL verification of the tool about to be used: the exe hash, plus for 7z.exe the 7z.dll and the WHOLE 7-Zip folder tree,
       and for makensis.exe the full NSIS tree hash (the slow part). 7zr / 7za (bootstrap stage, before the folder is complete) are
       exe-hash only. Run this before the build-namespace check; Start-PinnedTool launches afterwards. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Exe)
    $r = Resolve-PinnedToolPath -Exe $Exe
    $lk = $r.Lock; $tp = $r.Paths
    Assert-FileSha256 -Path $r.Full -Expected (Get-PinnedExeSha256 $r) -What "$($r.Leaf) (at execution)"
    switch ($r.Leaf) {
        '7z.exe' {
            Assert-FileSha256 -Path $tp.SevenZipDll -Expected $lk.sevenZip.binaries['7z.dll'] -What '7z.dll (at execution)'
            Assert-TreePinned -Path $tp.SevenZipDir -ExpectedSha256 $lk.sevenZip.treeSha256 -ExpectedCount ([int]$lk.sevenZip.treeFileCount) -What '7-Zip folder (at execution)'
        }
        'makensis.exe' { Assert-TreePinned -Path $tp.NsisDir -ExpectedSha256 $lk.nsis.treeSha256 -ExpectedCount ([int]$lk.nsis.treeFileCount) -What 'NSIS tree (at execution)' }
    }
}

function Start-PinnedTool {
    <# THE single process-launch site of tools/release (pinned portable 7-Zip / makensis only). Re-checks the exact registered
       path, containment / reparse points and the EXE hash only (cheap) and launches. Call Assert-ToolVerified first
       for the full verification. Arguments are passed as an array (no shell).
       Residual (no handle-based confinement): a principal with write access to the harness root who races the run with
       change-and-restore is not detected, and compile-time side effects of a hostile include are not undone. Accident control,
       not an adversary control. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Exe, [Parameter(Mandatory)][string[]]$Arguments, [string]$WorkingDirectory, [int[]]$OkExitCodes = @(0))
    $r = Resolve-PinnedToolPath -Exe $Exe
    Assert-FileSha256 -Path $r.Full -Expected (Get-PinnedExeSha256 $r) -What "$($r.Leaf) (at launch)"
    $leaf = $r.Leaf
    $old = $null
    if ($WorkingDirectory) { $old = Get-Location; Set-Location -LiteralPath $WorkingDirectory }
    try {
        $out = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } finally { if ($old) { Set-Location -LiteralPath $old.Path } }
    if ($code -notin $OkExitCodes) { throw "$leaf exited with code $code.`n$(($out | Select-Object -Last 40) -join "`n")" }
    [pscustomobject]@{ ExitCode = $code; Output = @($out) }
}

function Invoke-PinnedTool {
    # Convenience for the non-build tools (7-Zip): full verification, then launch.
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Exe, [Parameter(Mandatory)][string[]]$Arguments, [string]$WorkingDirectory, [int[]]$OkExitCodes = @(0))
    Assert-ToolVerified -Exe $Exe
    $p = @{ Exe = $Exe; Arguments = $Arguments; OkExitCodes = $OkExitCodes }
    if ($WorkingDirectory) { $p.WorkingDirectory = $WorkingDirectory }
    Start-PinnedTool @p
}

function Save-VerifiedDownload {
    <# Downloads $Entry.url to <downloads>\<fileName> if absent or wrong, verifying the pinned sha256 BEFORE the
       file is accepted. -Downloader (scriptblock: url, destination path) exists for tests. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Entry, [Parameter(Mandatory)][string]$DownloadsDir, [scriptblock]$Downloader)
    [void][IO.Directory]::CreateDirectory($DownloadsDir)
    $dest = Join-Path $DownloadsDir $Entry.fileName
    if ((Test-Path -LiteralPath $dest) -and ((Get-FileSha256 -Path $dest) -ceq $Entry.sha256)) { return $dest }
    $part = "$dest.part-$PID"
    try {
        if ($Downloader) { & $Downloader $Entry.url $part }
        else { Invoke-WebRequest -Uri $Entry.url -OutFile $part -UseBasicParsing -MaximumRedirection 5 -UserAgent 'curl/8 (release-tools)' }
        $have = Get-FileSha256 -Path $part
        if ($have -cne $Entry.sha256) { throw "Refused: download of $($Entry.fileName) has sha256 $have, pinned $($Entry.sha256)." }
        Move-Item -LiteralPath $part -Destination $dest -Force
    } finally { if (Test-Path -LiteralPath $part) { Remove-Item -LiteralPath $part -Force } }
    $dest
}

function Expand-ZipSafely {
    # Zip extraction with traversal / reparse refusal; strips an optional leading folder.
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ZipPath, [Parameter(Mandatory)][string]$Destination, [string]$StripPrefix)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $destFull = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
    $zip = [IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        foreach ($e in $zip.Entries) {
            $name = $e.FullName.Replace('\', '/')
            if ($StripPrefix) { if ($name.StartsWith("$StripPrefix/")) { $name = $name.Substring($StripPrefix.Length + 1) } else { throw "Refused: zip entry outside '$StripPrefix/': $name" } }
            if ($name -eq '') { continue }
            if ($name -match '(^|/)\.\.(/|$)' -or $name -match '^[A-Za-z]:' -or $name.StartsWith('/') -or $name.Contains(':')) { throw "Refused: unsafe zip entry: $name" }
            $target = [IO.Path]::GetFullPath((Join-Path $destFull $name.Replace('/', '\')))
            if (-not $target.StartsWith($destFull + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Refused: zip entry escapes destination: $name" }
            if ($name.EndsWith('/')) { [void][IO.Directory]::CreateDirectory($target); continue }
            [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
            [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $target, $false)
        }
    } finally { $zip.Dispose() }
}

function Register-ToolContext {
    # A "context" is a tool-layout root (the cache tools dir, or a per-run snapshot root) with the lock that pins it. Resolve-PinnedToolPath
    # accepts a tool only when its path is exactly a registered context's tool path.
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Dir, [Parameter(Mandatory)]$Lock)
    $full = [IO.Path]::GetFullPath($Dir)
    $keep = [System.Collections.Generic.List[object]]::new()
    foreach ($c in $script:ToolContexts) { if (-not $c.Dir.Equals($full, [StringComparison]::OrdinalIgnoreCase)) { $keep.Add($c) } }
    $keep.Add(@{ Dir = $full; Lock = $Lock })
    $script:ToolContexts = $keep
}

function Get-ToolCacheLockName {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Dir)
    $h = [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes([IO.Path]::GetFullPath($Dir).TrimEnd('\').ToLowerInvariant()))
    'Global\SnapmakerStudio-ToolCache-' + ([BitConverter]::ToString($h).Replace('-', '').Substring(0, 16))
}

function Enter-ToolCacheLock {
    # Serializes tool-cache population and snapshotting (named mutex, re-entrant for the owning thread).
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Dir, [int]$TimeoutSeconds = 300)
    $m = [Threading.Mutex]::new($false, (Get-ToolCacheLockName -Dir $Dir))
    $got = $false
    try { $got = $m.WaitOne([TimeSpan]::FromSeconds($TimeoutSeconds)) } catch [Threading.AbandonedMutexException] { $got = $true }
    if (-not $got) { $m.Dispose(); throw "Refused: could not acquire the tool-cache lock within $TimeoutSeconds s (another run is populating or snapshotting the cache)." }
    $m
}

function Exit-ToolCacheLock {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Mutex)
    try { $Mutex.ReleaseMutex() } finally { $Mutex.Dispose() }
}

function Copy-TreeNoLinks {
    # Copies a directory tree creating every destination directory exclusively. Refuses a reparse point (file OR directory) on the
    # source and on the destination; copies regular files only. -AfterFile (test hook) runs after each file copy.
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Source, [Parameter(Mandatory)][string]$Destination, [scriptblock]$AfterFile)
    $attr = [IO.File]::GetAttributes($Source)
    if ($attr -band [IO.FileAttributes]::ReparsePoint) { throw "Refused: reparse point in the tool source tree: $Source" }
    if ($attr -band [IO.FileAttributes]::Directory) {
        if (Test-Path -LiteralPath $Destination) { throw "Refused: snapshot destination already exists: $Destination" }
        [void][IO.Directory]::CreateDirectory($Destination)
        if ([IO.File]::GetAttributes($Destination) -band [IO.FileAttributes]::ReparsePoint) { throw "Refused: snapshot directory is a reparse point: $Destination" }
        foreach ($e in @([IO.Directory]::EnumerateFileSystemEntries($Source))) {
            Copy-TreeNoLinks -Source $e -Destination (Join-Path $Destination ([IO.Path]::GetFileName($e))) -AfterFile $AfterFile
        }
    } else {
        [IO.File]::Copy($Source, $Destination, $false)
        if ([IO.File]::GetAttributes($Destination) -band [IO.FileAttributes]::ReparsePoint) { throw "Refused: snapshot file is a reparse point: $Destination" }
        if ($AfterFile) { & $AfterFile $Source $Destination }
    }
}

function New-ToolSnapshot {
    <# PRIVATE AND VERIFIED snapshot of the pinned tools for ONE run: copies the whole 7-Zip folder and/or the whole NSIS tree (including
       Bin\makensis.exe) from the cache into a fresh, exclusively created directory ($Destination, outside any build dir), hashes the COPY once
       against the lock, and registers the snapshot so that Start-PinnedTool launches FROM THE COPY. The tools actually executed are therefore the
       bytes that were verified, in a directory no later run shares. Population/snapshotting of the shared cache is serialized.
       This is not immutable: a principal with write access to the harness root can still modify the snapshot (the caller re-validates the snapshot
       tree after every compiler exit). Accident control, not an adversary control. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]$Source,                      # the Get-ReleaseToolPaths hashtable of the cache (Install-PinnedTools output)
        [Parameter(Mandatory)][string]$Destination, [Parameter(Mandatory)]$Lock,
        [ValidateSet('7zip', 'nsis')][string[]]$Kinds = @('7zip', 'nsis'), [int]$LockTimeoutSeconds = 300, [scriptblock]$AfterFile
    )
    $dest = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
    if (Test-Path -LiteralPath $dest) { throw "Refused: snapshot destination already exists: $dest" }
    if (Test-ContainsReparsePoint -Path ([IO.Path]::GetDirectoryName($dest))) { throw 'Refused: the snapshot destination parent traverses a reparse point or could not be inspected.' }
    $mutex = Enter-ToolCacheLock -Dir $Source.Root -TimeoutSeconds $LockTimeoutSeconds
    try {
        [void][IO.Directory]::CreateDirectory($dest)
        if ([IO.File]::GetAttributes($dest) -band [IO.FileAttributes]::ReparsePoint) { throw 'Refused: snapshot root is a reparse point.' }
        $p = Get-ReleaseToolPaths -ToolsDir $dest -Lock $Lock
        if ($Kinds -contains '7zip') { Copy-TreeNoLinks -Source $Source.SevenZipDir -Destination $p.SevenZipDir -AfterFile $AfterFile }
        if ($Kinds -contains 'nsis') { Copy-TreeNoLinks -Source $Source.NsisDir -Destination $p.NsisDir -AfterFile $AfterFile }
    } finally { Exit-ToolCacheLock -Mutex $mutex }
    # Verify the COPY (once), not the source.
    if ($Kinds -contains '7zip') {
        Assert-TreePinned -Path $p.SevenZipDir -ExpectedSha256 $Lock.sevenZip.treeSha256 -ExpectedCount ([int]$Lock.sevenZip.treeFileCount) -What '7-Zip snapshot'
        Assert-FileSha256 -Path $p.SevenZip -Expected $Lock.sevenZip.binaries['7z.exe'] -What '7z.exe (snapshot)'
        Assert-FileSha256 -Path $p.SevenZipDll -Expected $Lock.sevenZip.binaries['7z.dll'] -What '7z.dll (snapshot)'
    }
    if ($Kinds -contains 'nsis') {
        Assert-TreePinned -Path $p.NsisDir -ExpectedSha256 $Lock.nsis.treeSha256 -ExpectedCount ([int]$Lock.nsis.treeFileCount) -What 'NSIS snapshot'
        Assert-FileSha256 -Path $p.Makensis -Expected $Lock.nsis.makensisSha256 -What 'makensis.exe (snapshot)'
    }
    Register-ToolContext -Dir $dest -Lock $Lock
    $p
}

function Install-PinnedTools {
    <# Idempotent. Ensures the pinned portable 7-Zip and NSIS exist under -ToolsDir (downloads only what is missing,
       verifying each pinned hash), then runs the full verification. Never touches PATH or the registry.
       7-Zip chain: 7zr.exe -> 7z2603-extra.7z (7za.exe) -> 7za.exe opens the MSI (NOT installed, only unpacked)
       -> _7z.exe/_7z.dll renamed 7z.exe/7z.dll (the full 7z.dll is what can open NSIS installers). #>
    [CmdletBinding()]
    param([string]$ToolsDir, [string]$HarnessRoot, $Lock = (Get-ToolsLock), [scriptblock]$Downloader, [int]$LockTimeoutSeconds = 300)
    $dir = Get-ReleaseToolsDir -ToolsDir $ToolsDir -HarnessRoot $HarnessRoot
    [void][IO.Directory]::CreateDirectory($dir)
    $p = Get-ReleaseToolPaths -ToolsDir $dir -Lock $Lock
    Register-ToolContext -Dir $dir -Lock $Lock
    $mutex = Enter-ToolCacheLock -Dir $dir -TimeoutSeconds $LockTimeoutSeconds
    try {
    $needSz = $true; $needNs = $true
    try { [void](Assert-PinnedTools -ToolsDir $dir -Lock $Lock -SevenZipOnly); $needSz = $false } catch { Write-Verbose "7-Zip not ready: $($_.Exception.Message)" }
    try { [void](Assert-PinnedTools -ToolsDir $dir -Lock $Lock -NsisOnly); $needNs = $false } catch { Write-Verbose "NSIS not ready: $($_.Exception.Message)" }

    if ($needSz) {
        $d = $Lock.sevenZip.downloads
        $zr = Save-VerifiedDownload -Entry $d.bootstrap -DownloadsDir $p.Downloads -Downloader $Downloader
        $extra = Save-VerifiedDownload -Entry $d.extra -DownloadsDir $p.Downloads -Downloader $Downloader
        $msi = Save-VerifiedDownload -Entry $d.msi -DownloadsDir $p.Downloads -Downloader $Downloader
        if (Test-Path -LiteralPath $p.SevenZipDir) { Remove-Item -LiteralPath $p.SevenZipDir -Recurse -Force }
        [void][IO.Directory]::CreateDirectory($p.SevenZipDir)
        Copy-Item -LiteralPath $zr -Destination $p.SevenZr
        Assert-FileSha256 -Path $p.SevenZr -Expected $Lock.sevenZip.bootstrapBinaries['7zr.exe'] -What '7zr.exe'
        [void](Invoke-PinnedTool -Exe $p.SevenZr -Arguments @('e', '-y', '-bd', "-o$($p.SevenZipDir)", $extra, '7za.exe'))
        Assert-FileSha256 -Path $p.SevenZa -Expected $Lock.sevenZip.bootstrapBinaries['7za.exe'] -What '7za.exe'
        $tmp = Join-Path $p.SevenZipDir 'msi-members'
        [void](Invoke-PinnedTool -Exe $p.SevenZa -Arguments @('e', '-y', '-bd', "-o$tmp", $msi, '_7z.exe', '_7z.dll'))
        Move-Item -LiteralPath (Join-Path $tmp '_7z.exe') -Destination $p.SevenZip
        Move-Item -LiteralPath (Join-Path $tmp '_7z.dll') -Destination $p.SevenZipDll
        Remove-Item -LiteralPath $tmp -Recurse -Force
        [void](Assert-PinnedTools -ToolsDir $dir -Lock $Lock -SevenZipOnly)
    }
    if ($needNs) {
        $zip = Save-VerifiedDownload -Entry $Lock.nsis.download -DownloadsDir $p.Downloads -Downloader $Downloader
        if (Test-Path -LiteralPath $p.NsisDir) { Remove-Item -LiteralPath $p.NsisDir -Recurse -Force }
        Expand-ZipSafely -ZipPath $zip -Destination $p.NsisDir -StripPrefix $Lock.nsis.innerDir
    }
    Assert-PinnedTools -ToolsDir $dir -Lock $Lock
    } finally { Exit-ToolCacheLock -Mutex $mutex }
}

Export-ModuleMember -Function Get-ToolsLock, Get-ReleaseToolsDir, Get-DirectoryTreeSha256, Get-ReleaseToolPaths, Assert-FileSha256,
    Assert-PinnedTools, Assert-TreePinned, Register-ToolContext, Get-ToolCacheLockName, Enter-ToolCacheLock, Exit-ToolCacheLock, New-ToolSnapshot, Assert-ToolVerified, Start-PinnedTool, Invoke-PinnedTool, Save-VerifiedDownload, Expand-ZipSafely, Install-PinnedTools
