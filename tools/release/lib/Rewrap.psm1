#requires -Version 7.0
# Rewrap - acceptance-identity "rewrap" of a real released Snapmaker Studio installer (issue #55, task B).
#
# Pipeline: verify installer hash -> list + extract with pinned 7-Zip (never executed) -> strip installer machinery
# (uninstall.exe, $PLUGINSDIR) -> per-file manifest -> render the vendored Tauri NSIS template with the ACCEPTANCE
# identity -> statically enumerate every RmDir/Delete/DeleteRegKey/DeleteRegValue target and refuse anything the
# guard's Test-DeleteTargetAllowed rejects -> compile with pinned makensis -> verify (VersionInfo, 7-Zip listing)
# -> write the attestation that InstallGuard's Test-RewrapAttestation accepts.
#
# NOTHING produced here is ever run, installed or launched. Process launches are limited to Invoke-PinnedTool
# (pinned portable 7-Zip and makensis, by explicit verified path).

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot '..\..\lib\InstallGuard.psm1') -DisableNameChecking
Import-Module (Join-Path $PSScriptRoot 'ReleaseTools.psm1') -DisableNameChecking

$script:TemplateFiles = @('English.nsh', 'installer.nsi', 'utils.nsh')   # EXACT set, hashed as the template bundle
$script:TemplateName = 'tauri-bundler-nsis-acceptance'
$script:TemplateVersion = '2.9.3'                                          # tauri-bundler crate the template derives from
$script:Copyright = 'Copyright (c) 2026 Snapmaker Studio contributors'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Test-RunId { param([string]$RunId) ($RunId -is [string]) -and ($RunId -cmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') }

function New-RunId { [guid]::NewGuid().ToString('N') }

function ConvertTo-HexSha256 { param([byte[]]$Bytes) ([BitConverter]::ToString([Security.Cryptography.SHA256]::HashData($Bytes)).Replace('-', '').ToLowerInvariant()) }

function Get-RunDirectory {
    <# <harness root>\<extract|rewrap>\<runId>, validated; must not exist yet (-MustNotExist). Creates nothing. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][ValidateSet('extract', 'rewrap')][string]$Kind, [Parameter(Mandatory)][string]$RunId, [string]$HarnessRoot, [switch]$MustNotExist)
    if (-not (Test-RunId $RunId)) { throw "Refused: invalid run id '$RunId'." }
    $root = Get-HarnessRoot -HarnessRoot $HarnessRoot
    $dir = Join-Path (Join-Path $root $Kind) $RunId
    Assert-HarnessOwnedPath -Path $dir -Root $root -What "$Kind directory"
    # C1: extraction / rewrap trees are SEPARATE subtrees from any install dir.
    $inst = Join-Path $root (Get-HarnessIdentity).HarnessSubdirs.Install
    if (Test-PathContained -Path $dir -Root $inst -AllowEqual) { throw 'Refused: work directory inside the install subtree.' }
    if ($MustNotExist -and (Test-Path -LiteralPath $dir)) { throw "Refused: run directory already exists: $RunId" }
    $dir
}

function Remove-LinkSafeTree {
    # Deletes $Path recursively WITHOUT ever following a reparse point: a link (junction / symlink) is removed itself, never its target.
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)
    $attr = [IO.File]::GetAttributes($Path)
    if ($attr -band [IO.FileAttributes]::ReparsePoint) {
        if ($attr -band [IO.FileAttributes]::Directory) { [IO.Directory]::Delete($Path) } else { [IO.File]::Delete($Path) }
        return
    }
    if ($attr -band [IO.FileAttributes]::Directory) {
        foreach ($e in @([IO.Directory]::EnumerateFileSystemEntries($Path))) { Remove-LinkSafeTree -Path $e }
        [IO.Directory]::Delete($Path)
    } else {
        if ($attr -band [IO.FileAttributes]::ReadOnly) { [IO.File]::SetAttributes($Path, [IO.FileAttributes]::Normal) }
        [IO.File]::Delete($Path)
    }
}

function Remove-OwnedTree {
    # Deletes a directory this module created, only when strictly inside $Container and its PARENT chain is reparse-free.
    # Reparse points found INSIDE the tree are removed as links (never followed).
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Container)
    try { [void][IO.File]::GetAttributes($Path) } catch [System.IO.FileNotFoundException], [System.IO.DirectoryNotFoundException] { return }
    if (-not (Test-PathContained -Path $Path -Root $Container)) { throw "Refused: $Path is not strictly inside $Container." }
    if (Test-ContainsReparsePoint -Path ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($Path)))) { throw "Refused: the parent of $Path traverses a reparse point." }
    Remove-LinkSafeTree -Path $Path
}

function Write-JsonAtomic {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Object, [Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Container)
    Assert-HarnessOwnedPath -Path $Path -Root $Container -What 'json output'
    $dir = [IO.Path]::GetDirectoryName($Path)
    [void][IO.Directory]::CreateDirectory($dir)
    Assert-HarnessOwnedPath -Path $dir -Root $Container -What 'json output directory'
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($Object | ConvertTo-Json -Depth 12))
    $tmp = "$Path.tmp-$PID"
    $fs = [IO.File]::Open($tmp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $fs.Write($bytes, 0, $bytes.Length); $fs.Flush($true) } finally { $fs.Dispose() }
    Assert-HarnessOwnedPath -Path $Path -Root $Container -What 'json output'
    if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($tmp, $Path, [NullString]::Value) } else { [IO.File]::Move($tmp, $Path) }
}

# ---------------------------------------------------------------------------
# Template bundle (what PinnedTemplateSha256 pins)
# ---------------------------------------------------------------------------

function Get-TemplateBundle {
    <# The pinned template hash is sha256 over UTF-8 text made of one line per template file, sorted ordinally by name:
         "<name>:<sha256 of the file's bytes>\n"
       for EXACTLY the files English.nsh, installer.nsi, utils.nsh in the template directory (any missing/extra file
       is an error). template.patch / PROVENANCE.md are documentation and are not part of the hash. #>
    [CmdletBinding()]
    param([string]$TemplateDir = (Join-Path $PSScriptRoot '..\nsis\template'))
    $dir = [IO.Path]::GetFullPath($TemplateDir)
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) { throw "Template directory not found: $dir" }
    [string[]]$have = @(Get-ChildItem -LiteralPath $dir -Force | ForEach-Object { $_.Name })
    [Array]::Sort($have, [StringComparer]::Ordinal)
    if (($have -join '|') -cne ($script:TemplateFiles -join '|')) { throw "Refused: template directory must contain exactly $($script:TemplateFiles -join ', ') (found: $($have -join ', '))." }
    $files = foreach ($n in $script:TemplateFiles) {
        $p = Join-Path $dir $n
        if ((Get-Item -LiteralPath $p).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refused: template file is a reparse point: $n" }
        [pscustomobject]@{ Name = $n; Sha256 = (Get-FileSha256 -Path $p); Path = $p }
    }
    [pscustomobject]@{ Sha256 = (Get-BundleSha256 -Entries $files); Files = @($files); Dir = $dir }
}

function Get-BundleSha256 {
    # sha256 over "<name>:<sha256>\n" lines (entries in the given order, which is ordinal by name). Shared by Get-TemplateBundle and
    # the staged-copy verification so both compute the pinned value identically.
    [CmdletBinding()]
    param([Parameter(Mandatory)][object[]]$Entries)
    $text = (($Entries | ForEach-Object { "$($_.Name):$($_.Sha256)" }) -join "`n") + "`n"
    ConvertTo-HexSha256 ([Text.UTF8Encoding]::new($false).GetBytes($text))
}

function Assert-TemplatePinned {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Bundle, [string]$ExpectedSha256)
    if ($ExpectedSha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Refused: no valid pinned template sha256 is configured (fail closed).' }
    if ($Bundle.Sha256 -cne $ExpectedSha256) { throw "Refused: template bundle sha256 $($Bundle.Sha256) does not equal the pinned value $ExpectedSha256." }
}

# ---------------------------------------------------------------------------
# 7-Zip listing (no execution) and extraction
# ---------------------------------------------------------------------------

function Get-ArchiveListing {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$SevenZip, [Parameter(Mandatory)][string]$ArchivePath)
    $r = Invoke-PinnedTool -Exe $SevenZip -Arguments @('l', '-slt', '-bd', '-sccUTF-8', $ArchivePath)
    $entries = New-Object System.Collections.Generic.List[object]
    $inEntries = $false; $cur = $null
    foreach ($line in $r.Output) {
        if ($line -eq '----------') { $inEntries = $true; continue }
        if (-not $inEntries) { continue }
        if ($line -eq '') { if ($cur -and $cur.ContainsKey('Path')) { $entries.Add([pscustomobject]@{ Path = $cur['Path']; Size = $cur['Size']; IsFolder = ($cur['Folder'] -eq '+') }) }; $cur = $null; continue }
        if ($null -eq $cur) { $cur = @{} }
        $i = $line.IndexOf(' = ')
        if ($i -gt 0) { $cur[$line.Substring(0, $i)] = $line.Substring($i + 3) }
    }
    if ($cur -and $cur.ContainsKey('Path')) { $entries.Add([pscustomobject]@{ Path = $cur['Path']; Size = $cur['Size']; IsFolder = ($cur['Folder'] -eq '+') }) }
    , $entries.ToArray()
}

function Test-SafeArchivePath {
    param([string]$Path)
    $n = $Path.Replace('/', '\')
    -not ([string]::IsNullOrWhiteSpace($n) -or $n -match '^([A-Za-z]:|\\)' -or $n -match '(^|\\)\.\.(\\|$)' -or $n.Contains(':') -or $n -match '[*?<>|"]' -or $n -match '(^|\\)\.(\\|$)')
}

function Assert-ExtractionListing {
    <# Classifies the installer's archive entries. Returns @{ Payload = <names>; Machinery = <names>; HasUninstaller }.
       Fails on traversal / absolute / ADS paths, duplicates (case-insensitive), a missing payload file, the missing
       pinned plugin dll, and ANY entry that is neither expected payload nor known installer machinery. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][object[]]$Entries, [Parameter(Mandatory)]$Lock)
    $id = Get-HarnessIdentity
    $payloadNames = @($id.Production.MainBinaryName, $id.Acceptance.SidecarName)
    $seen = @{}; $payload = @(); $machinery = @(); $hasUninst = $false; $hasDll = $false
    foreach ($e in $Entries) {
        $p = [string]$e.Path
        if (-not (Test-SafeArchivePath $p)) { throw "Refused: unsafe archive path '$p'." }
        $n = $p.Replace('/', '\')
        $k = $n.ToLowerInvariant()
        if ($seen.ContainsKey($k)) { throw "Refused: duplicate archive entry '$n'." }
        $seen[$k] = $true
        if ($e.IsFolder) { continue }
        if ($n -ieq $id.Acceptance.UninstallerName) { $hasUninst = $true; $machinery += $n; continue }
        if ($n -match '^\$PLUGINSDIR\\[^\\]+$') { $machinery += $n; if ($n -ieq ('$PLUGINSDIR\' + $Lock.tauriUtilsDll.fileName)) { $hasDll = $true }; continue }
        if ($n -ceq '[NSIS].nsi') { $machinery += $n; continue }
        if ($payloadNames -ccontains $n) { $payload += $n; continue }
        throw "Refused: unexpected entry '$n' in the installer (installed file set must be exactly $($payloadNames -join ', '))."
    }
    foreach ($w in $payloadNames) { if ($payload -cnotcontains $w) { throw "Refused: installer is missing payload file '$w'." } }
    if (-not $hasDll) { throw "Refused: installer does not contain `$PLUGINSDIR\$($Lock.tauriUtilsDll.fileName) (needed as the compile-time plugin input)." }
    @{ Payload = $payload; Machinery = $machinery; HasUninstaller = $hasUninst }
}

function Assert-InstallerHash {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$InstallerPath, [Parameter(Mandatory)][string]$ExpectedSha256, [string]$Sha256SumsPath)
    if ($ExpectedSha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Refused: -ExpectedSha256 must be 64 lowercase hex characters.' }
    if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) { throw "Refused: installer not found: $InstallerPath" }
    $sha = Get-FileSha256 -Path $InstallerPath
    if ($sha -cne $ExpectedSha256) { throw "Refused: installer sha256 $sha does not equal the expected $ExpectedSha256." }
    if ($Sha256SumsPath) {
        if (-not (Test-Path -LiteralPath $Sha256SumsPath -PathType Leaf)) { throw "Refused: SHA256SUMS not found: $Sha256SumsPath" }
        $leaf = [IO.Path]::GetFileName($InstallerPath)
        $hits = @(Get-Content -LiteralPath $Sha256SumsPath | Where-Object { $_ -match '^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$' } | ForEach-Object { [pscustomobject]@{ Sha = $Matches[1].ToLowerInvariant(); Name = $Matches[2] } } | Where-Object { $_.Name -ceq $leaf })
        if ($hits.Count -ne 1) { throw "Refused: SHA256SUMS must list '$leaf' exactly once (found $($hits.Count))." }
        if ($hits[0].Sha -cne $sha) { throw "Refused: SHA256SUMS lists $($hits[0].Sha) for '$leaf', installer is $sha." }
    }
    $sha
}

function Invoke-InstallerExtraction {
    <# Extracts a REAL released installer with the pinned 7-Zip into <harness>\extract\<runId>\raw, builds the manifest,
       moves the payload to ...\payload and the single pinned plugin dll to ...\plugins, then DELETES ...\raw (which
       contains the synthesized uninstall.exe and $PLUGINSDIR). Nothing extracted is ever executed. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$InstallerPath, [Parameter(Mandatory)][string]$ExpectedSha256, [string]$Sha256SumsPath,
        [Parameter(Mandatory)][string]$SourceVersion, [string]$HarnessRoot, [string]$ToolsDir, [string]$RunId, $Lock = (Get-ToolsLock)
    )
    if ($SourceVersion -cnotmatch '^\d+\.\d+\.\d+$') { throw "Refused: -SourceVersion must look like 1.2.3 (got '$SourceVersion')." }
    if (-not $RunId) { $RunId = New-RunId }
    $root = Get-HarnessRoot -HarnessRoot $HarnessRoot
    $runDir = Get-RunDirectory -Kind extract -RunId $RunId -HarnessRoot $HarnessRoot -MustNotExist
    $extractRoot = Join-Path $root 'extract'

    # Bind the source: copy the installer into the harness-owned run dir FIRST, hash the COPY, and list/extract the COPY only.
    # The caller's path is never read again, so swapping it afterwards has no effect.
    if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) { throw "Refused: installer not found: $InstallerPath" }
    [void][IO.Directory]::CreateDirectory($runDir)
    Assert-HarnessOwnedPath -Path $runDir -Root $root -What 'extraction run directory'
    $srcDir = Join-Path $runDir 'source'
    [void][IO.Directory]::CreateDirectory($srcDir)
    $copy = Join-Path $srcDir ([IO.Path]::GetFileName($InstallerPath))
    Assert-HarnessOwnedPath -Path $copy -Root $root -What 'installer copy'
    Copy-Item -LiteralPath $InstallerPath -Destination $copy
    Assert-HarnessOwnedPath -Path $copy -Root $root -What 'installer copy'
    $installerSha = Assert-InstallerHash -InstallerPath $copy -ExpectedSha256 $ExpectedSha256 -Sha256SumsPath $Sha256SumsPath
    $cache = Install-PinnedTools -ToolsDir $ToolsDir -HarnessRoot $HarnessRoot -Lock $Lock
    # 7-Zip runs FROM a private and verified snapshot of its whole folder (the COPY is hashed once against the lock), so a dll swapped in the
    # shared cache after the snapshot cannot alter the extracted payload.
    $tools = New-ToolSnapshot -Source $cache -Destination (Join-Path $runDir 'tools') -Lock $Lock -Kinds @('7zip')

    $raw = Join-Path $runDir 'raw'
    $originalError = $null
    try {
    # Re-hash the copy before each read of it (listing, extraction).
    Assert-FileSha256 -Path $copy -Expected $installerSha -What 'installer copy (before listing)'
    $entries = Get-ArchiveListing -SevenZip $tools.SevenZip -ArchivePath $copy
    $cls = Assert-ExtractionListing -Entries $entries -Lock $Lock

    [void][IO.Directory]::CreateDirectory($raw)
    Assert-HarnessOwnedPath -Path $raw -Root $root -What 'extraction directory'
    Assert-FileSha256 -Path $copy -Expected $installerSha -What 'installer copy (before extraction)'
    [void](Invoke-PinnedTool -Exe $tools.SevenZip -Arguments @('x', '-y', '-bd', '-aoa', "-o$raw", $copy))

    # The extracted tree must equal the listing exactly (no traversal, no reparse points, nothing extra, nothing missing).
    $listed = @($entries | Where-Object { -not $_.IsFolder } | ForEach-Object { $_.Path.Replace('/', '\').ToLowerInvariant() })
    $found = New-Object System.Collections.Generic.List[string]
    foreach ($i in (Get-ChildItem -LiteralPath $raw -Recurse -Force)) {
        if ($i.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refused: reparse point in extracted tree: $($i.FullName)" }
        $full = [IO.Path]::GetFullPath($i.FullName)
        if (-not (Test-PathContained -Path $full -Root $raw)) { throw "Refused: extracted item escapes the extraction directory: $full" }
        if (-not $i.PSIsContainer) { $found.Add($full.Substring($raw.Length + 1).ToLowerInvariant()) }
    }
    foreach ($f in $found) { if ($listed -cnotcontains $f) { throw "Refused: extracted file not in the archive listing: $f" } }
    foreach ($l in $listed) { if ($found -cnotcontains $l) { throw "Refused: listed file was not extracted: $l" } }

    # Manifest of the real payload.
    $id = Get-HarnessIdentity
    $files = foreach ($n in @($id.Production.MainBinaryName, $id.Acceptance.SidecarName)) {
        $p = Join-Path $raw $n
        [ordered]@{ path = $n; sha256 = (Get-FileSha256 -Path $p); size = (Get-Item -LiteralPath $p).Length }
    }
    $dllRaw = Join-Path $raw ('$PLUGINSDIR\' + $Lock.tauriUtilsDll.fileName)
    Assert-FileSha256 -Path $dllRaw -Expected $Lock.tauriUtilsDll.sha256 -What $Lock.tauriUtilsDll.fileName
    $uninstallerSha = $null
    $up = Join-Path $raw $id.Acceptance.UninstallerName
    if (Test-Path -LiteralPath $up) { $uninstallerSha = Get-FileSha256 -Path $up }

    # Strip: keep only payload + the one pinned plugin dll; delete everything else (uninstall.exe included) now.
    $payloadDir = Join-Path $runDir 'payload'; $pluginDir = Join-Path $runDir 'plugins'
    [void][IO.Directory]::CreateDirectory($payloadDir); [void][IO.Directory]::CreateDirectory($pluginDir)
    foreach ($f in $files) { Move-Item -LiteralPath (Join-Path $raw $f.path) -Destination (Join-Path $payloadDir $f.path) }
    Move-Item -LiteralPath $dllRaw -Destination (Join-Path $pluginDir $Lock.tauriUtilsDll.fileName)
    Remove-OwnedTree -Path $raw -Container $extractRoot
    foreach ($f in $files) { Assert-FileSha256 -Path (Join-Path $payloadDir $f.path) -Expected $f.sha256 -What "payload $($f.path)" }
    if (@(Get-ChildItem -LiteralPath $runDir -Recurse -Force -File | Where-Object { $_.Name -ieq $id.Acceptance.UninstallerName }).Count -ne 0) { throw 'Internal error: uninstall.exe survived stripping.' }
    } catch {
        $originalError = $_
        throw
    } finally {
        # raw holds the 7-Zip-synthesized PRODUCTION uninstall.exe: remove it on EVERY exit path once it may exist. Links inside it are
        # removed (never followed). A cleanup failure never masks the ORIGINAL exception.
        try { Remove-OwnedTree -Path $raw -Container $extractRoot }
        catch { if ($null -eq $originalError) { throw } else { Write-Warning "cleanup of the raw extraction tree failed: $($_.Exception.Message)" } }
    }

    $result = [pscustomobject]@{
        RunId = $RunId; RunDir = $runDir; PayloadDir = $payloadDir; PluginDll = (Join-Path $pluginDir $Lock.tauriUtilsDll.fileName)
        InstallerSha256 = $installerSha; InstallerCopy = $copy; SourceVersion = $SourceVersion; Files = @($files)
        ExtractionEmittedUninstaller = [bool]$cls.HasUninstaller; StrippedUninstallerSha256 = $uninstallerSha
        StrippedMachinery = @($cls.Machinery)
    }
    Write-JsonAtomic -Object ([ordered]@{
            kind = 'snapmaker-studio-extraction'; schemaVersion = 1; runId = $RunId; sourceVersion = $SourceVersion; installerSha256 = $installerSha; installerCopy = 'source/' + [IO.Path]::GetFileName($copy)
            files = @($files); extractionEmittedUninstaller = [bool]$cls.HasUninstaller; strippedUninstallerSha256 = $uninstallerSha
            strippedMachinery = @($cls.Machinery); pluginDllSha256 = $Lock.tauriUtilsDll.sha256
        }) -Path (Join-Path $runDir 'extraction.json') -Container $root
    $result
}

# ---------------------------------------------------------------------------
# NSIS script: rendering and static enumeration
# ---------------------------------------------------------------------------

function ConvertTo-NsisValue {
    # Values are placed inside "..." in the NSIS script: refuse anything NSIS would interpret.
    param([string]$Name, [string]$Value)
    if ($Value -match '["`$\r\n]' -or $Value.Contains("'")) { throw "Refused: template value '$Name' contains a character NSIS would interpret." }
    $Value
}

function Expand-InstallerTemplate {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$TemplateText, [Parameter(Mandatory)][hashtable]$Values)
    $out = [regex]::Replace($TemplateText, '\{\{([a-z_]+)\}\}', {
            param($m)
            $k = $m.Groups[1].Value
            if (-not $Values.ContainsKey($k)) { throw "Refused: template placeholder '{{$k}}' has no value." }
            ConvertTo-NsisValue -Name $k -Value ([string]$Values[$k])
        })
    if ($out.Contains('{{')) { throw 'Refused: unresolved template placeholder remains after rendering.' }
    $out
}

function Get-NsisTokens {
    # Splits NSIS arguments honouring "..." '...' `...` (with $\" escapes). Stops at an inline ${|}.
    param([string]$Text)
    $tokens = New-Object System.Collections.Generic.List[string]
    $i = 0; $n = $Text.Length
    while ($i -lt $n) {
        while ($i -lt $n -and [char]::IsWhiteSpace($Text[$i])) { $i++ }
        if ($i -ge $n) { break }
        $c = $Text[$i]
        if ($c -eq '"' -or $c -eq "'" -or $c -eq '`') {
            $q = $c; $i++; $sb = New-Object System.Text.StringBuilder
            while ($i -lt $n -and $Text[$i] -ne $q) {
                if ($Text[$i] -eq '$' -and $i + 2 -lt $n -and $Text[$i + 1] -eq '\') { [void]$sb.Append($Text, $i, 3); $i += 3; continue }
                [void]$sb.Append($Text[$i]); $i++
            }
            $i++
            $tokens.Add($sb.ToString())
        } else {
            $s = $i
            while ($i -lt $n -and -not [char]::IsWhiteSpace($Text[$i])) { $i++ }
            $t = $Text.Substring($s, $i - $s)
            if ($t -ceq '${|}') { break }
            $tokens.Add($t)
        }
    }
    @($tokens)
}

function Get-NsisLogicalLines {
    # Joins backslash-continued lines and splits; strips comments (; or # outside quotes at token start).
    param([string]$Text)
    $joined = [regex]::Replace($Text, '\\\r?\n', ' ')
    foreach ($raw in ($joined -split "\r?\n")) {
        $mask = [regex]::Replace($raw, '"[^"]*"|''[^'']*''|`[^`]*`', { param($m) '_' * $m.Value.Length })
        $cut = [regex]::Match($mask, '(^|\s)[;#]')
        if ($cut.Success) { $pos = $cut.Index + $cut.Length - 1; $raw = $raw.Substring(0, $pos); $mask = $mask.Substring(0, $pos) }
        if ($raw.Trim() -ne '') { [pscustomobject]@{ Text = $raw; Mask = $mask } }
    }
}

function Get-NsisDefines {
    param([object[]]$Lines)
    $defs = [ordered]@{}
    foreach ($l in $Lines) {
        if ($l.Text -match '^\s*!define\s+(?:/ifndef\s+)?([A-Za-z0-9_.]+)\s+(?:"([^"]*)"|''([^'']*)''|`([^`]*)`|(\S+))\s*$') {
            $name = $Matches[1]
            if ($defs.Contains($name)) { continue }   # NSIS: first definition wins for /ifndef; a plain redefinition is an NSIS error
            $val = @($Matches[2], $Matches[3], $Matches[4], $Matches[5] | Where-Object { $null -ne $_ -and $_ -ne '' })
            $defs[$name] = if ($val.Count) { [string]$val[0] } else { '' }
        }
    }
    $defs
}

function Expand-NsisDefines {
    param([string]$Text, $Defines)
    for ($pass = 0; $pass -lt 10; $pass++) {
        $new = [regex]::Replace($Text, '\$\{([A-Za-z0-9_.]+)\}', { param($m) if ($Defines.Contains($m.Groups[1].Value)) { [string]$Defines[$m.Groups[1].Value] } else { $m.Value } })
        if ($new -ceq $Text) { break }
        $Text = $new
    }
    $Text
}

function Get-NsisDeleteTargets {
    <# Static enumeration of every RmDir / Delete / DeleteRegKey / DeleteRegValue in the script text(s), AFTER define
       expansion. Case-insensitive instruction match (NSIS is case-insensitive); a conservative superset (dead !if
       branches are included). Registry targets are 'ROOT\key[\value]'. Returns objects { Op; Target; Source }. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][hashtable]$Scripts)   # name -> text; defines are taken from ALL scripts (first wins)
    $all = @{}; $defs = [ordered]@{}
    foreach ($name in $Scripts.Keys) { $all[$name] = @(Get-NsisLogicalLines -Text $Scripts[$name]) }
    foreach ($name in ($Scripts.Keys | Sort-Object { if ($_ -like '*.nsi') { 0 } else { 1 } }, { $_ })) { foreach ($kv in (Get-NsisDefines -Lines $all[$name]).GetEnumerator()) { if (-not $defs.Contains($kv.Key)) { $defs[$kv.Key] = $kv.Value } } }
    $ops = @{ 'rmdir' = 'RmDir'; 'delete' = 'Delete'; 'deleteregkey' = 'DeleteRegKey'; 'deleteregvalue' = 'DeleteRegValue' }
    $targets = New-Object System.Collections.Generic.List[object]
    foreach ($name in ($Scripts.Keys | Sort-Object)) {
        foreach ($l in $all[$name]) {
            foreach ($m in [regex]::Matches($l.Mask, '(?i)(?<![\w${.\\])(RmDir|DeleteRegKey|DeleteRegValue|Delete)(?![\w}])')) {
                $op = $ops[$m.Groups[1].Value.ToLowerInvariant()]
                $rest = Get-NsisTokens -Text $l.Text.Substring($m.Index + $m.Length)
                $args2 = @($rest | ForEach-Object { $_ })
                # leading flags (unquoted tokens beginning with '/')
                $k = 0
                while ($k -lt $args2.Count -and $args2[$k] -match '^/[A-Za-z]+$') { $k++ }
                $pos = @($args2 | Select-Object -Skip $k)
                $target = $null
                switch ($op) {
                    { $_ -in 'RmDir', 'Delete' } { $target = if ($pos.Count -ge 1) { $pos[0] } else { '${missing-operand}' } }
                    'DeleteRegKey' { $target = if ($pos.Count -ge 2) { "$($pos[0])\$($pos[1])" } else { '${missing-operand}' } }
                    'DeleteRegValue' { $target = if ($pos.Count -ge 3) { "$($pos[0])\$($pos[1])\$($pos[2])" } else { '${missing-operand}' } }
                }
                $targets.Add([pscustomobject]@{ Op = $op; Target = (Expand-NsisDefines -Text $target -Defines $defs); Source = $name })
            }
        }
    }
    , $targets.ToArray()
}

function Get-NsisForbiddenFindings {
    <# Compile-time execution and app-launch constructs that must never appear (defence in depth; the template is also
       hash-pinned). Returns a list of human-readable findings. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][hashtable]$Scripts)
    $findings = New-Object System.Collections.Generic.List[string]
    $includeOk = @('MUI2.nsh', 'FileFunc.nsh', 'x64.nsh', 'WordFunc.nsh', 'utils.nsh', 'Win\COM.nsh', 'Win\Propkey.nsh', 'StrFunc.nsh', 'English.nsh')
    $bad = '(?i)^\s*!(system|execute|packhdr|finalize|uninstfinalize|delfile|appendfile|tempfile|cd|makensis|searchparse|searchreplace|addincludedir)\b'
    $procApi = '(?i)\b(CreateProcess\w*|ShellExecute\w*|WinExec|CreateRemoteThread\w*|LoadLibrary\w*|WriteProcessMemory|NtCreateUserProcess)\b'
    # The ONLY plugin calls the template (and its utils.nsh) make. A new plugin call fails the build.
    $pluginOk = @('System::Call', 'System::Alloc', 'System::Free', 'nsis_tauri_utils::FindProcess', 'nsis_tauri_utils::FindProcessCurrentUser',
        'nsis_tauri_utils::KillProcess', 'nsis_tauri_utils::KillProcessCurrentUser', 'nsis_tauri_utils::StrReplace')
    foreach ($name in ($Scripts.Keys | Sort-Object)) {
        foreach ($l in (Get-NsisLogicalLines -Text $Scripts[$name])) {
            if ($l.Mask -match $bad) { $findings.Add("${name}: forbidden directive: $($l.Text.Trim())") }
            if ($l.Mask -match '(?i)^\s*!define\s+/(redef|math|file|date|utcdate)\b') { $findings.Add("${name}: forbidden define form: $($l.Text.Trim())") }
            if ($l.Text -match '^\s*!include\s+(.+)$') {
                $t = @(Get-NsisTokens -Text $Matches[1])
                $inc = if ($t.Count) { $t[0] } else { '' }
                if ($inc -notmatch '^[A-Za-z0-9_.\\]+$' -or ($includeOk -inotcontains $inc)) { $findings.Add("${name}: include not on the allow-list: $inc") }
            }
            if ($l.Text -match $procApi) { $findings.Add("${name}: process / library-loading API reference is not allowed: $($l.Text.Trim())") }
            if ($l.Mask -match '(?i)(?<![\w${.\\])(CallInstDLL|RegDLL|UnRegDLL)(?![\w}])') { $findings.Add("${name}: DLL registration / call instruction is not allowed: $($l.Text.Trim())") }
            if ($l.Text -match '(?i)^\s*!addplugindir\b(.*)$') {
                $pt = @(Get-NsisTokens -Text $Matches[1])
                if ($pt.Count -ne 1 -or $pt[0] -cne '${ADDITIONALPLUGINSPATH}') { $findings.Add("${name}: !addplugindir other than `${ADDITIONALPLUGINSPATH} is not allowed: $($l.Text.Trim())") }
            }
            foreach ($pm in [regex]::Matches($l.Mask, '(?<![\w${:.])([A-Za-z_]\w*)::([A-Za-z_]\w*)')) {
                $call = "$($pm.Groups[1].Value)::$($pm.Groups[2].Value)"
                if (@($pluginOk | Where-Object { $_ -ieq $call }).Count -eq 0) { $findings.Add("${name}: plugin call is not on the allow-list: $call") }
            }
            if ($l.Mask -match '(?i)nsis_tauri_utils::RunAsUser') { $findings.Add("${name}: app launch (RunAsUser) is not allowed in the acceptance installer") }
            if ($l.Mask -match '(?i)(nsExec|ExecDos|ExecCmd)::') { $findings.Add("${name}: process-exec plugin is not allowed: $($l.Text.Trim())") }
            foreach ($m in [regex]::Matches($l.Mask, '(?i)(?<![\w${.\\])(ExecShellWait|ExecShell|ExecWait|Exec)(?![\w}])')) {
                # NO process-execution instruction of any kind is allowed (the reinstall-page ExecWait of a registry-sourced
                # UninstallString is compiled out; see PROVENANCE.md).
                $findings.Add("${name}: process launch instruction is not allowed: $($l.Text.Trim())")
            }
        }
    }
    @($findings)
}

function Assert-NsisScriptSafe {
    <# Enumerates delete targets (post-expansion) and FAILS if any is refused by InstallGuard's Test-DeleteTargetAllowed
       (the guard's own function; not reimplemented), matches a production-identifier pattern, or any forbidden
       construct is present. Returns the targets as { op, target } hashtables for the attestation. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][hashtable]$Scripts)
    $prod = (Get-HarnessIdentity).Production
    $problems = New-Object System.Collections.Generic.List[string]
    foreach ($f in (Get-NsisForbiddenFindings -Scripts $Scripts)) { $problems.Add($f) }
    $targets = [object[]](Get-NsisDeleteTargets -Scripts $Scripts)
    if ($targets.Count -eq 0) { $problems.Add('no delete targets were found (the enumeration must not be empty)') }
    $out = New-Object System.Collections.Generic.List[object]
    foreach ($t in $targets) {
        $why = Test-DeleteTargetAllowed -Op $t.Op -Target $t.Target
        if ($why) { $problems.Add("$($t.Source): $($t.Op) target refused ($why): $($t.Target)"); continue }
        foreach ($pat in $prod.ForbiddenTargetPatterns) { if ($t.Target -match $pat) { $problems.Add("$($t.Source): $($t.Op) target derives from a production identifier: $($t.Target)"); break } }
        $out.Add([ordered]@{ op = $t.Op; target = $t.Target })
    }
    if ($problems.Count) { throw "Refused: the acceptance installer script is not safe:`n  - $($problems -join "`n  - ")" }
    # De-duplicate identical (op,target) pairs, keep order.
    $seen = @{}; $uniq = foreach ($o in $out) { $key = "$($o.op)|$($o.target)"; if (-not $seen.ContainsKey($key)) { $seen[$key] = $true; $o } }
    @($uniq)
}

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

function Get-VersionWithBuild {
    param([string]$Version)
    if ($Version -cnotmatch '^\d+\.\d+\.\d+$') { throw "Refused: version '$Version' is not x.y.z." }
    "$Version.0"
}

function New-RewrapAttestationObject {
    <# Builds the attestation exactly per the schema documented above Test-RewrapAttestation in InstallGuard.psm1.
       Identity fields come from HarnessIdentity.psd1 (read, never duplicated). Does not validate or write. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$SourceVersion, [Parameter(Mandatory)][string]$SourceInstallerSha256,
        [Parameter(Mandatory)][string]$TemplateSha256, [Parameter(Mandatory)][string]$InstallerFileName, [Parameter(Mandatory)][string]$InstallerSha256,
        [Parameter(Mandatory)][object[]]$Files, [Parameter(Mandatory)][object[]]$Renames, [Parameter(Mandatory)][object[]]$DeleteTargets,
        $Lock = (Get-ToolsLock), [bool]$ExtractionEmittedUninstaller
    )
    $id = Get-HarnessIdentity; $acc = $id.Acceptance
    [ordered]@{
        kind = $id.Attestation.Kind; schemaVersion = $id.Attestation.SchemaVersion
        createdUtc = [DateTime]::UtcNow.ToString('o')
        identity = [ordered]@{ productName = $acc.ProductName; manufacturer = $acc.Manufacturer; bundleId = $acc.BundleId; mainBinaryName = $acc.MainBinaryName }
        source = [ordered]@{ version = $SourceVersion; installerSha256 = $SourceInstallerSha256 }
        template = [ordered]@{ name = $script:TemplateName; version = $script:TemplateVersion; sha256 = $TemplateSha256 }
        installer = [ordered]@{ fileName = $InstallerFileName; sha256 = $InstallerSha256 }
        manifest = [ordered]@{ files = $Files; renames = @($Renames | ForEach-Object { [ordered]@{ from = $_.from; to = $_.to } }); excluded = @($acc.UninstallerName) }
        deleteTargets = $DeleteTargets
        tools = [ordered]@{
            sevenZip = $Lock.sevenZip.version; nsis = $Lock.nsis.version; nsisTreeSha256 = $Lock.nsis.treeSha256
            tauriUtilsDllSha256 = $Lock.tauriUtilsDll.sha256; extractionEmittedUninstaller = $ExtractionEmittedUninstaller
        }
    }
}

function Get-MakensisArguments {
    # -NOCONFIG: never load the user nsisconf.nsh (under the roaming app-data folder) or the tree nsisconf.nsh (unpinned/unscanned configuration).
    [CmdletBinding()]
    param([string]$ScriptName = 'installer.final.nsi')
    @('-NOCONFIG', '-INPUTCHARSET', 'UTF8', '-OUTPUTCHARSET', 'UTF8', '-V2', $ScriptName)
}

function New-BuildAllowlist {
    # The EXACT set of entries a build directory may contain (files AND directories).
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$PluginDllName, [Parameter(Mandatory)][string[]]$PayloadNames)
    @{
        Files = @('installer.final.nsi', 'installer.nsi', 'utils.nsh', 'English.nsh', "plugins\$PluginDllName") + @($PayloadNames | ForEach-Object { "payload\$_" })
        Dirs  = @('plugins', 'payload', 'private-appdata')
    }
}

function Get-BuildDirInventory {
    <# Walks the build directory (files AND directories, reparse points included) and returns { relative path -> sha256 } for every file.
       Throws on ANY entry that is not on the allow-list, on ANY reparse point (file or directory, e.g. a junction), and on a missing build dir.
       private-appdata\ is allowed as a directory but its contents are never listed (it is the compiler's private APPDATA); -PrivateMustBeEmpty
       additionally requires it to be empty (pre-launch). -Light records payload files by size instead of hashing them (cheap pre-launch check;
       the post-exit check uses the full inventory). #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$BuildDir, [Parameter(Mandatory)]$Allowlist, [switch]$Light, [switch]$PrivateMustBeEmpty)
    $root = [IO.Path]::GetFullPath($BuildDir).TrimEnd('\')
    try { $rootAttr = [IO.File]::GetAttributes($root) } catch { throw "Refused: the build directory is missing or cannot be inspected: $root" }
    if ($rootAttr -band [IO.FileAttributes]::ReparsePoint) { throw 'Refused: the build directory is a reparse point.' }
    $inv = @{}
    $stack = New-Object System.Collections.Generic.Stack[string]
    $stack.Push($root)
    while ($stack.Count -gt 0) {
        $dir = $stack.Pop()
        foreach ($e in @([IO.Directory]::EnumerateFileSystemEntries($dir))) {
            $rel = $e.Substring($root.Length + 1)
            $attr = [IO.File]::GetAttributes($e)
            if ($attr -band [IO.FileAttributes]::ReparsePoint) { throw "Refused: reparse point in the build directory: $rel" }
            if ($attr -band [IO.FileAttributes]::Directory) {
                if (@($Allowlist.Dirs | Where-Object { $_ -ieq $rel }).Count -eq 0) { throw "Refused: unexpected directory in the build directory (not on the allow-list): $rel" }
                if ($rel -ieq 'private-appdata') {
                    if ($PrivateMustBeEmpty -and @([IO.Directory]::EnumerateFileSystemEntries($e)).Count -gt 0) { throw 'Refused: private-appdata is not empty before launch.' }
                    continue
                }
                $stack.Push($e)
            } else {
                if (@($Allowlist.Files | Where-Object { $_ -ieq $rel }).Count -eq 0) { throw "Refused: unexpected file in the build directory (not on the allow-list): $rel" }
                $inv[$rel] = if ($Light -and $rel -like 'payload\*') { "size:$((Get-Item -LiteralPath $e).Length)" } else { Get-FileSha256 -Path $e }
            }
        }
    }
    $sorted = [ordered]@{}
    foreach ($k in ($inv.Keys | Sort-Object { $_.ToLowerInvariant() })) { $sorted[$k] = $inv[$k] }
    $sorted
}

function Assert-BuildInputsUnchanged {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$BuildDir, [Parameter(Mandatory)]$Recorded, [Parameter(Mandatory)]$Allowlist, [switch]$Light, [switch]$PrivateMustBeEmpty)
    $now = Get-BuildDirInventory -BuildDir $BuildDir -Allowlist $Allowlist -Light:$Light -PrivateMustBeEmpty:$PrivateMustBeEmpty
    $a = (@($Recorded.GetEnumerator() | Sort-Object { $_.Key.ToLowerInvariant() } | ForEach-Object { "$($_.Key):$($_.Value)" })) -join '|'
    $b = (@($now.GetEnumerator() | ForEach-Object { "$($_.Key):$($_.Value)" })) -join '|'
    if ($a -cne $b) { throw 'Refused: a makensis input changed since the scan (build directory contents or hashes differ from those recorded).' }
}

function Invoke-IsolatedMakensis {
    <# Runs the (snapshot) makensis against $ScriptName in $BuildDir with a scrubbed environment: NSISDIR / NSISCONFDIR cleared and APPDATA /
       LOCALAPPDATA pointed at a private directory (process-scoped, restored afterwards) on top of -NOCONFIG. Defence in depth; -NOCONFIG and
       the snapshot are the primary controls. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Makensis, [Parameter(Mandatory)][string]$BuildDir, [Parameter(Mandatory)][string]$PrivateDir, [string]$ScriptName = 'installer.final.nsi')
    $env0 = @{ NSISDIR = $env:NSISDIR; NSISCONFDIR = $env:NSISCONFDIR; APPDATA = $env:APPDATA; LOCALAPPDATA = $env:LOCALAPPDATA }
    try {
        $env:NSISDIR = $null; $env:NSISCONFDIR = $null; $env:APPDATA = $PrivateDir; $env:LOCALAPPDATA = $PrivateDir
        Start-PinnedTool -Exe $Makensis -WorkingDirectory $BuildDir -Arguments (Get-MakensisArguments -ScriptName $ScriptName)
    } finally { $env:NSISDIR = $env0.NSISDIR; $env:NSISCONFDIR = $env0.NSISCONFDIR; $env:APPDATA = $env0.APPDATA; $env:LOCALAPPDATA = $env0.LOCALAPPDATA }
}

function Remove-RunOutputs {
    # Deletes the compiled installer and any attestation of this run (only regular files inside the harness root).
    [CmdletBinding()]
    param([Parameter(Mandatory)][string[]]$Paths, [Parameter(Mandatory)][string]$Root)
    foreach ($o in $Paths) {
        if ((Test-Path -LiteralPath $o -PathType Leaf) -and (Test-PathContainedNoReparse -Path $o -Root $Root)) { Remove-Item -LiteralPath $o -Force }
    }
}

function New-AcceptanceInstaller {
    <# Compiles the acceptance installer from an extraction result. Writes <harness>\rewrap\<runId>\ and the
       attestation <harness>\attestations\<runId>.json. -TemplateDir / -ExpectedTemplateSha256 exist for tests; the
       defaults are the vendored template and the pin from HarnessIdentity.psd1.
       Consumed set == verified set: makensis runs FROM a private and verified snapshot of the NSIS tree (<run>\tools\nsis-*), reading only a
       build directory whose complete namespace (files and directories) is an exact allow-list. Residual: a principal with write access to the
       harness root who races the run with change-and-restore, and compile-time side effects of a hostile include, are not prevented or undone
       (accident control, not an adversary control). #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]$Extraction, [string]$HarnessRoot, [string]$ToolsDir, $Lock = (Get-ToolsLock),
        [string]$TemplateDir = (Join-Path $PSScriptRoot '..\nsis\template'),
        [string]$ExpectedTemplateSha256 = [string](Get-HarnessIdentity).Attestation.PinnedTemplateSha256,
        [string]$RunId
    )
    $id = Get-HarnessIdentity; $acc = $id.Acceptance
    if (-not $RunId) { $RunId = $Extraction.RunId }
    $root = Get-HarnessRoot -HarnessRoot $HarnessRoot
    $cache = Install-PinnedTools -ToolsDir $ToolsDir -HarnessRoot $HarnessRoot -Lock $Lock

    $bundle = Get-TemplateBundle -TemplateDir $TemplateDir
    Assert-TemplatePinned -Bundle $bundle -ExpectedSha256 $ExpectedTemplateSha256

    $runDir = Get-RunDirectory -Kind rewrap -RunId $RunId -HarnessRoot $HarnessRoot -MustNotExist
    $build = Join-Path $runDir 'build'
    foreach ($d in @($build, (Join-Path $build 'payload'), (Join-Path $build 'plugins'), (Join-Path $build 'private-appdata'))) { [void][IO.Directory]::CreateDirectory($d) }
    Assert-HarnessOwnedPath -Path $build -Root $root -What 'build directory'
    $private = Join-Path $build 'private-appdata'

    # Private and verified snapshot of the tools for THIS run (outside the build dir); the COPY is hashed once against the lock.
    $snap = New-ToolSnapshot -Source $cache -Destination (Join-Path $runDir 'tools') -Lock $Lock -Kinds @('7zip', 'nsis')

    # Template: copy to the build dir, read each staged file ONCE, verify those bytes (per file and as a bundle) against the pin. Everything
    # after this point (render, scan, hash, compile) uses these buffers / these staged files.
    $tplBytes = @{}
    $stagedEntries = foreach ($f in $bundle.Files) {
        $dest = Join-Path $build $f.Name
        Copy-Item -LiteralPath $f.Path -Destination $dest
        $bytes = [IO.File]::ReadAllBytes($dest)
        $h = ConvertTo-HexSha256 $bytes
        if ($h -cne $f.Sha256) { throw "Refused: staged template file $($f.Name) sha256 mismatch (expected $($f.Sha256), got $h)." }
        $tplBytes[$f.Name] = $bytes
        [pscustomobject]@{ Name = $f.Name; Sha256 = $h }
    }
    $staged = [pscustomobject]@{ Sha256 = (Get-BundleSha256 -Entries @($stagedEntries)) }
    Assert-TemplatePinned -Bundle $staged -ExpectedSha256 $ExpectedTemplateSha256

    # Payload (explicit rename map): assert on the COPY that its hash equals the manifest hash. Plugin dll: bytes == pinned hash.
    $renames = @(@{ from = $id.Production.MainBinaryName; to = $acc.MainBinaryName })
    $manifest = New-Object System.Collections.Generic.List[object]
    foreach ($f in $Extraction.Files) {
        $src = Join-Path $Extraction.PayloadDir $f.path
        Assert-FileSha256 -Path $src -Expected $f.sha256 -What "extracted $($f.path)"
        $isMain = ($f.path -ceq $id.Production.MainBinaryName)
        $destName = if ($isMain) { $acc.MainBinaryName } else { $f.path }
        $dest = Join-Path (Join-Path $build 'payload') $destName
        Copy-Item -LiteralPath $src -Destination $dest
        Assert-FileSha256 -Path $dest -Expected $f.sha256 -What "payload copy $destName"
        $manifest.Add([ordered]@{
                path = $destName; sha256 = $f.sha256; size = (Get-Item -LiteralPath $dest).Length
                role = $(if ($isMain) { 'renamed-main' } else { 'payload' }); sourcePath = $f.path; sourceSha256 = $f.sha256
            })
    }
    $pluginRel = 'plugins\' + $Lock.tauriUtilsDll.fileName
    Copy-Item -LiteralPath $Extraction.PluginDll -Destination (Join-Path $build $pluginRel)
    Assert-FileSha256 -Path (Join-Path $build $pluginRel) -Expected $Lock.tauriUtilsDll.sha256 -What 'plugin dll'

    $outName = "Snapmaker.Studio.Acceptance_$($Extraction.SourceVersion)_x64-setup.exe"
    $outPath = Join-Path $runDir $outName
    $attPath = Join-Path (Join-Path $root $id.HarnessSubdirs.Attestations) "$RunId.json"
    $values = @{
        compression = 'lzma'; manufacturer = $acc.Manufacturer; product_name = $acc.ProductName; version = $Extraction.SourceVersion
        version_with_build = (Get-VersionWithBuild $Extraction.SourceVersion); homepage = ''; install_mode = 'currentUser'; license = ''
        installer_icon = ''; sidebar_image = ''; header_image = ''; uninstaller_icon = ''; uninstaller_header_image = ''
        main_binary_name = [IO.Path]::GetFileNameWithoutExtension($acc.MainBinaryName)
        main_binary_path = (Join-Path $build ('payload\' + $acc.MainBinaryName)); sidecar_name = $acc.SidecarName
        sidecar_path = (Join-Path $build ('payload\' + $acc.SidecarName)); bundle_id = $acc.BundleId; copyright = $script:Copyright
        out_file = $outPath; arch = 'x64'; additional_plugins_path = (Join-Path $build 'plugins'); allow_downgrades = 'true'
        display_language_selector = 'false'
        estimated_size = [string][math]::Floor((($manifest | ForEach-Object { [int64]$_.size } | Measure-Object -Sum).Sum) / 1024)
        language = 'English'; language_file = 'English.nsh'
    }
    $utf8 = [Text.UTF8Encoding]::new($false)
    $final = Expand-InstallerTemplate -TemplateText $utf8.GetString($tplBytes['installer.nsi']) -Values $values
    $finalBytes = [byte[]]([Text.UTF8Encoding]::new($true).GetPreamble() + $utf8.GetBytes($final))
    [IO.File]::WriteAllBytes((Join-Path $build 'installer.final.nsi'), $finalBytes)
    $finalSha = ConvertTo-HexSha256 $finalBytes

    # Exact allow-list of the build namespace; the recorded inventories must agree with the buffers that were written.
    $allow = New-BuildAllowlist -PluginDllName $Lock.tauriUtilsDll.fileName -PayloadNames @($manifest | ForEach-Object { $_.path })
    $invFull = Get-BuildDirInventory -BuildDir $build -Allowlist $allow
    $invLight = Get-BuildDirInventory -BuildDir $build -Allowlist $allow -Light
    $expect = @{ 'installer.final.nsi' = $finalSha; 'installer.nsi' = (ConvertTo-HexSha256 $tplBytes['installer.nsi']); 'utils.nsh' = (ConvertTo-HexSha256 $tplBytes['utils.nsh'])
        'English.nsh' = (ConvertTo-HexSha256 $tplBytes['English.nsh']); $pluginRel = $Lock.tauriUtilsDll.sha256 }
    foreach ($m in $manifest) { $expect["payload\$($m.path)"] = $m.sha256 }
    foreach ($k in $expect.Keys) { if ($invFull[$k] -cne $expect[$k]) { throw "Refused: staged file $k differs from the verified buffer it was written from." } }
    if ($invFull.Count -ne $expect.Count) { throw 'Refused: the staged build directory does not contain exactly the expected files.' }
    Write-JsonAtomic -Object ([ordered]@{ kind = 'snapmaker-studio-build-inputs'; schemaVersion = 1; runId = $RunId; inputs = $invFull }) -Path (Join-Path $runDir 'build-inputs.json') -Container $root

    # B1: enumerate + validate the SAME buffers that were written and hashed (no second read).
    $deleteTargets = Assert-NsisScriptSafe -Scripts @{
        'installer.final.nsi' = $final
        'utils.nsh'           = $utf8.GetString($tplBytes['utils.nsh'])
        'English.nsh'         = $utf8.GetString($tplBytes['English.nsh'])
    }

    # Compile. Order: snapshot tool verification (exe + whole snapshot tree) -> cheap build-namespace check -> launch (exe-only hash).
    # After EVERY compiler exit, including failure: full build-namespace inventory and the snapshot tree are re-validated; on any mismatch the
    # output and any attestation are deleted and the build fails (integrity failure takes precedence over a compiler error).
    $launched = $false; $compileError = $null; $mk = $null
    try {
        Assert-ToolVerified -Exe $snap.Makensis
        Assert-BuildInputsUnchanged -BuildDir $build -Recorded $invLight -Allowlist $allow -Light -PrivateMustBeEmpty
        $launched = $true
        $mk = Invoke-IsolatedMakensis -Makensis $snap.Makensis -BuildDir $build -PrivateDir $private
    } catch { $compileError = $_ }
    if ($launched) {
        try {
            Assert-BuildInputsUnchanged -BuildDir $build -Recorded $invFull -Allowlist $allow
            Assert-TreePinned -Path $snap.NsisDir -ExpectedSha256 $Lock.nsis.treeSha256 -ExpectedCount ([int]$Lock.nsis.treeFileCount) -What 'NSIS snapshot (post-exit)'
            Assert-FileSha256 -Path $snap.Makensis -Expected $Lock.nsis.makensisSha256 -What 'makensis.exe snapshot (post-exit)'
        } catch {
            $integrity = $_.Exception.Message
            Remove-RunOutputs -Paths @($outPath, $attPath) -Root $root
            throw "Refused: the build namespace or the tool snapshot changed while makensis ran (post-exit check); the compiled output and any attestation were deleted. $integrity"
        }
    }
    if ($compileError) { throw $compileError }
    if (-not (Test-Path -LiteralPath $outPath -PathType Leaf)) { throw 'makensis reported success but produced no installer.' }

    # Verify the compiled installer WITHOUT executing it (7-Zip from its own snapshot).
    $installerSha = Get-FileSha256 -Path $outPath
    $pn = (Get-Item -LiteralPath $outPath).VersionInfo.ProductName
    if ($pn -cne $acc.ProductName) { throw "Refused: compiled installer ProductName is '$pn', expected '$($acc.ProductName)'." }
    $listing = [object[]](Get-ArchiveListing -SevenZip $snap.SevenZip -ArchivePath $outPath)
    $rootFiles = @($listing | Where-Object { -not $_.IsFolder -and $_.Path -notmatch '^\$PLUGINSDIR\\' -and $_.Path -ine '[NSIS].nsi' })
    $names = @($rootFiles | ForEach-Object { $_.Path })
    if ($names -icontains $id.Production.MainBinaryName) { throw 'Refused: compiled installer still contains the production main binary name.' }
    foreach ($m in $manifest) {
        $hit = @($rootFiles | Where-Object { $_.Path -ceq $m.path })
        if ($hit.Count -ne 1) { throw "Refused: compiled installer does not list exactly one '$($m.path)'." }
        if ([int64]$hit[0].Size -ne [int64]$m.size) { throw "Refused: compiled installer lists a different size for '$($m.path)'." }
    }
    foreach ($n in $names) { if (@($manifest | Where-Object { $_.path -ceq $n }).Count -eq 0 -and $n -ine $acc.UninstallerName) { throw "Refused: compiled installer lists unexpected file '$n'." } }

    # The attestation is written only after the post-exit validation above succeeded.
    $att = New-RewrapAttestationObject -SourceVersion $Extraction.SourceVersion -SourceInstallerSha256 $Extraction.InstallerSha256 `
        -TemplateSha256 $staged.Sha256 -InstallerFileName $outName -InstallerSha256 $installerSha -Files $manifest.ToArray() `
        -Renames $renames -DeleteTargets $deleteTargets -Lock $Lock -ExtractionEmittedUninstaller ([bool]$Extraction.ExtractionEmittedUninstaller)
    $v = Test-RewrapAttestation -Attestation $att -InstallerSha256 $installerSha
    if (-not $v.Valid) { throw "Refused: the produced attestation is not valid per InstallGuard: $($v.Errors -join '; ')" }
    Write-JsonAtomic -Object $att -Path $attPath -Container $root
    $v2 = Test-RewrapAttestation -Attestation $attPath -InstallerSha256 $installerSha
    if (-not $v2.Valid) { throw "Refused: the written attestation does not round-trip: $($v2.Errors -join '; ')" }

    [pscustomobject]@{
        RunId = $RunId; InstallerPath = $outPath; InstallerSha256 = $installerSha; AttestationPath = $attPath; ProductName = $pn
        TemplateSha256 = $staged.Sha256; DeleteTargets = @($deleteTargets); Files = $manifest.ToArray(); MakensisOutputTail = @($mk.Output | Select-Object -Last 8)
    }
}

function Invoke-AcceptanceRewrap {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$InstallerPath, [Parameter(Mandatory)][string]$ExpectedSha256, [string]$Sha256SumsPath,
        [Parameter(Mandatory)][string]$SourceVersion, [string]$HarnessRoot, [string]$ToolsDir, [string]$RunId
    )
    if (-not $RunId) { $RunId = New-RunId }
    $ex = Invoke-InstallerExtraction -InstallerPath $InstallerPath -ExpectedSha256 $ExpectedSha256 -Sha256SumsPath $Sha256SumsPath `
        -SourceVersion $SourceVersion -HarnessRoot $HarnessRoot -ToolsDir $ToolsDir -RunId $RunId
    New-AcceptanceInstaller -Extraction $ex -HarnessRoot $HarnessRoot -ToolsDir $ToolsDir -RunId $RunId
}

Export-ModuleMember -Function Test-RunId, Get-RunDirectory, Get-TemplateBundle, Assert-TemplatePinned, Get-ArchiveListing, Assert-ExtractionListing,
    Assert-InstallerHash, Invoke-InstallerExtraction, Expand-InstallerTemplate, Get-NsisTokens, Get-NsisDeleteTargets, Get-NsisForbiddenFindings,
    Assert-NsisScriptSafe, Get-BundleSha256, Remove-LinkSafeTree, Get-MakensisArguments, New-BuildAllowlist, Get-BuildDirInventory, Assert-BuildInputsUnchanged, Invoke-IsolatedMakensis, Remove-RunOutputs, New-RewrapAttestationObject, New-AcceptanceInstaller, Invoke-AcceptanceRewrap, Write-JsonAtomic, Remove-OwnedTree, ConvertTo-HexSha256
