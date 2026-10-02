#requires -Version 7.0
# InstallGuard - workstation (branch W) install-identity guard for issue #55.
#
# Scope (plan v2.3): the workstation may only ever run an installer that
#   (1) carries the ACCEPTANCE identity, and
#   (2) whose sha256 is bound to a trusted rewrap attestation, and
#   (3) is launched from a harness-owned copy (copy, hash, then launch that copy).
# The production-identity installer is ALWAYS refused. There is no
# "disposable environment" branch in this module or anywhere under tools/.
#
# This is an accident / agent-error control, not a defence against a
# maintainer who deliberately bypasses it. Everything fails closed: any
# error, ambiguity or missing evidence throws.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Identity = Import-PowerShellDataFile -LiteralPath (Join-Path $PSScriptRoot 'HarnessIdentity.psd1')
$script:ActiveLocks = @{}   # token -> @{ HarnessRoot; Mutex; Pid } (see Enter-/Exit-HarnessLock)

function Get-HarnessIdentity { $script:Identity }

# ---------------------------------------------------------------------------
# Paths and containment
# ---------------------------------------------------------------------------

function Get-HarnessRoot {
    [CmdletBinding()]
    param([string]$HarnessRoot)
    # Overrides pass the POSITIVE allowlist (strictly inside the temp container or the default harness root).
    if ($HarnessRoot) { return (Assert-AllowedOverridePath -Path $HarnessRoot -What 'harness root override') }
    $default = Get-DefaultHarnessRoot
    Assert-AllowedOverridePath -Path $default -What 'default harness root' -DefaultLocation
}

function Get-DefaultHarnessRoot {
    $lad = $env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($lad)) { throw 'LOCALAPPDATA is not set; refusing to guess a harness root.' }
    [IO.Path]::GetFullPath((Join-Path $lad $script:Identity.HarnessRootDirName))
}

function Assert-AllowedOverridePath {
    <# POSITIVE allowlist for every test-only / relocatable path (harness root, journal dir, shortcut dirs).
       Returns the canonical full path; creates nothing. Steps, on the RAW input, in order:
         a) fully-qualified local drive path only (X:\...): no relative, drive-relative, UNC, \\?\ , \\.\ , provider syntax
         b) no ':' beyond index 1, no wildcards/invalid chars, no '.'/'..' segments, no trailing dot/space in a segment,
            no doubled or forward slashes
         c) GetFullPath
         d) STRICTLY inside the temp container or the DEFAULT harness root (never equal to either)
            -- skipped only with -DefaultLocation, which is for values this module resolved itself
         e) reparse-point walk from the VOLUME ROOT through every existing component; an inspection error refuses
         f) layer 2: Assert-NotProductionLocation (guards a TEMP variable pointing at production)
       Honest limit: this narrows, but does not eliminate, the check-then-use window (no handle-based confinement).
       It is an accident control, not an adversary control. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [string]$What = 'path', [switch]$DefaultLocation)
    $bad = { param($why) throw "Refused: $What is not an allowed location ($why)." }
    if ($Path -notmatch '^[A-Za-z]:\\') { & $bad 'must be a fully-qualified local drive path' }
    if ($Path.IndexOf(':', 2) -ge 0) { & $bad 'colon / alternate data stream' }
    if ($Path -match '[*?<>|"]' -or $Path.IndexOfAny([IO.Path]::GetInvalidPathChars()) -ge 0) { & $bad 'invalid or wildcard character' }
    if ($Path.Contains('/') -or $Path.Substring(3).Contains('\\')) { & $bad 'doubled or forward separator' }
    foreach ($seg in $Path.Substring(3).TrimEnd('\').Split('\')) {
        if ($seg -eq '') { continue }
        if ($seg -eq '.' -or $seg -eq '..') { & $bad 'dot segment' }
        if ($seg.EndsWith('.') -or $seg.EndsWith(' ')) { & $bad 'trailing dot or space in a segment' }
    }
    $full = [IO.Path]::GetFullPath($Path)
    # A volume root is never acceptable (and must not be TrimEnd'ed: 'C:' is drive-RELATIVE and would resolve against the cwd).
    if ($full.Equals([IO.Path]::GetPathRoot($full), [StringComparison]::OrdinalIgnoreCase)) { & $bad 'a volume root is not allowed' }
    $full = $full.TrimEnd('\')
    if (-not $DefaultLocation) {
        $temp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
        $containers = @($temp)
        if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { $containers += (Get-DefaultHarnessRoot) }
        $ok = $false
        foreach ($c in $containers) { if (Test-PathContained -Path $full -Root $c) { $ok = $true } }
        if (-not $ok) { & $bad 'must be strictly inside the temp directory or the default harness root' }
    }
    if (Test-ContainsReparsePoint -Path $full) { & $bad 'a path component is a reparse point or could not be inspected' }
    Assert-NotProductionLocation -Path $full -What $What
    $full
}

function Get-ProductionLocation {
    # Production engine data dir, default install dirs and Tauri app-data dirs (names from HarnessIdentity.psd1).
    $p = $script:Identity.Production
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($pair in @(
            @($env:LOCALAPPDATA, $p.EngineDataDirName), @($env:LOCALAPPDATA, $p.DefaultInstallDirName), @($env:LOCALAPPDATA, $p.BundleId),
            @($env:APPDATA, $p.BundleId), @($env:ProgramFiles, $p.DefaultInstallDirName), @(${env:ProgramFiles(x86)}, $p.DefaultInstallDirName))) {
        if (-not [string]::IsNullOrWhiteSpace($pair[0])) { $out.Add([IO.Path]::GetFullPath((Join-Path $pair[0] $pair[1]))) }
    }
    $out.ToArray()
}

function Assert-NotProductionLocation {
    <# Refuses a path that equals, sits inside, or is an ANCESTOR of any production location. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [string]$What = 'path')
    $full = [IO.Path]::GetFullPath($Path)
    foreach ($loc in (Get-ProductionLocation)) {
        if ((Test-PathContained -Path $full -Root $loc -AllowEqual) -or (Test-PathContained -Path $loc -Root $full -AllowEqual)) {
            throw "Refused: $What overlaps a production location."
        }
    }
}

function Assert-SafeRegistryRoot {
    <# Only the real HKCU Software root, or a location under HKCU:\Software that does not overlap any
       production key (either direction). HKLM and anything else is refused. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$RegistryRoot)
    # Exact allowlist (no normalization, no trailing separator): the real HKCU software root, or
    # HKCU:\Software\<ScratchParent>\<name>. HKLM, Registry:: forms, doubled backslashes and '..' never match.
    $scratch = [regex]::Escape($script:Identity.Registry.ScratchParent)
    if ($RegistryRoot -match '^HKCU:\\Software\z') { return }
    if ($RegistryRoot -match "^HKCU:\\Software\\$scratch\\[A-Za-z0-9][A-Za-z0-9-]{0,63}\z") { return }
    throw 'Refused: registry root must be exactly HKCU:\Software or HKCU:\Software\<scratch parent>\<name>.'
}

function Get-HarnessSubdir {
    [CmdletBinding()]
    param([Parameter(Mandatory)][ValidateSet('Journal', 'Install', 'Staging', 'Attestations', 'Lock')][string]$Name, [string]$HarnessRoot)
    Join-Path (Get-HarnessRoot -HarnessRoot $HarnessRoot) $script:Identity.HarnessSubdirs[$Name]
}

function Test-PathContained {
    <# Separator-safe containment. The harness root is a prefix-neighbour of the
       production engine dir, so a bare StartsWith on the un-terminated root is
       wrong; both sides are normalised and the root gets a trailing separator.
       A path equal to the root is NOT contained (-AllowEqual to permit). #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Root, [switch]$AllowEqual)
    try {
        if ($Path -match '^\\\\' -or $Root -match '^\\\\') { return $false }   # UNC / device paths
        $p = [IO.Path]::GetFullPath($Path)
        $r = [IO.Path]::GetFullPath($Root)
    } catch { return $false }
    # Alternate data streams / odd colons after the drive letter.
    if ($p.Length -lt 3 -or $p.Substring(2).Contains(':')) { return $false }
    $p = $p.TrimEnd('\', '/')
    $r = $r.TrimEnd('\', '/')
    if ($p.Equals($r, [StringComparison]::OrdinalIgnoreCase)) { return [bool]$AllowEqual }
    $p.StartsWith($r + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

function Test-ContainsReparsePoint {
    <# True if ANY existing component of $Path, walking from the VOLUME ROOT down (so ancestors such as
       an alias junction above a container are covered), is a reparse point (junction / symlink), or if a
       component cannot be inspected (access denied etc. is refusal, distinct from genuine absence).
       Absent components end the walk (nothing deeper can exist). -Root is accepted for backward
       compatibility only; the walk never starts below the volume root. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [string]$Root)
    try { $full = [IO.Path]::GetFullPath($Path).TrimEnd('\') } catch { return $true }
    if ($full -match '^\\\\' -or $full -notmatch '^[A-Za-z]:') { return $true }
    $chain = New-Object System.Collections.Generic.List[string]
    $cur = $full
    while (-not [string]::IsNullOrEmpty($cur)) { $chain.Insert(0, $cur); $cur = [IO.Path]::GetDirectoryName($cur) }
    $volRoot = [IO.Path]::GetPathRoot($full)
    if ($chain.Count -eq 0 -or -not $chain[0].TrimEnd('\').Equals($volRoot.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) { return $true }
    foreach ($c in $chain) {
        $probe = if ($c.Length -eq 2) { "$c\" } else { $c }
        try { $attr = [IO.File]::GetAttributes($probe) }
        catch [System.IO.FileNotFoundException], [System.IO.DirectoryNotFoundException] { break }   # genuine absence
        catch { return $true }                                                                       # inspection error => refuse
        if ($attr -band [IO.FileAttributes]::ReparsePoint) { return $true }
    }
    $false
}

function Assert-HarnessOwnedPath {
    <# Lexical containment under $Root (equal allowed) AND a reparse-free chain from the volume root. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Root, [string]$What = 'path')
    if (-not (Test-PathContained -Path $Path -Root $Root -AllowEqual)) { throw "Refused: $What is not inside the harness-owned tree." }
    if (Test-ContainsReparsePoint -Path $Path) { throw "Refused: $What traverses a reparse point (junction/symlink) or could not be inspected." }
}

function Test-PathContainedNoReparse {
    # Real-path style containment: lexical AND reparse-free. Used where a lexical-only answer would be spoofable.
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Root, [switch]$AllowEqual)
    (Test-PathContained -Path $Path -Root $Root -AllowEqual:$AllowEqual) -and -not (Test-ContainsReparsePoint -Path $Path)
}

function Test-UnderWorkDir {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [string]$HarnessRoot, [string[]]$ExtraWorkDirs = @())
    $root = Get-HarnessRoot -HarnessRoot $HarnessRoot
    $dirs = @($script:Identity.HarnessSubdirs.WorkDirs | ForEach-Object { Join-Path $root $_ }) + $ExtraWorkDirs
    foreach ($d in $dirs) { if (Test-PathContained -Path $Path -Root $d -AllowEqual) { return $true } }
    $false
}

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

function Get-FileSha256 {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-ExeProductName {
    # Separate function so tests can Mock it (no installer binaries are needed).
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)
    $pn = (Get-Item -LiteralPath $Path).VersionInfo.ProductName
    if ($null -eq $pn) { return '' }
    $pn.Trim()
}

function Test-IsProductionProductName {
    param([string]$Name)
    [bool]($Name -and $Name.Trim().Equals($script:Identity.Production.ProductName, [StringComparison]::OrdinalIgnoreCase))
}

function Write-AtomicFile {
    <# tmp file in the same directory -> flush to disk -> rename. Directory entry
       durability is not claimed (no portable .NET API). #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][byte[]]$Bytes, [Parameter(Mandatory)][string]$Container)
    # The container/reparse assertion is repeated immediately before each mutation. This narrows, but does not
    # eliminate, the check-then-use window (no handle-based confinement): accident control, not adversary control.
    Assert-HarnessOwnedPath -Path $Path -Root $Container -What 'atomic write target'
    $dir = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($Path))
    if (-not (Test-Path -LiteralPath $dir)) { [void][IO.Directory]::CreateDirectory($dir) }
    $tmp = "$Path.tmp-$PID-$([guid]::NewGuid().ToString('N'))"
    Assert-HarnessOwnedPath -Path $tmp -Root $Container -What 'atomic write temp file'
    $fs = [IO.File]::Open($tmp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $fs.Write($Bytes, 0, $Bytes.Length)
        $fs.Flush($true)
    } finally { $fs.Dispose() }
    try {
        Assert-HarnessOwnedPath -Path $Path -Root $Container -What 'atomic write target'
        if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($tmp, $Path, [NullString]::Value) } else { [IO.File]::Move($tmp, $Path) }
    } catch {
        if (Test-PathContainedNoReparse -Path $tmp -Root $Container) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
        throw
    }
}

# ---------------------------------------------------------------------------
# Rewrap attestation: schema + verifier
# ---------------------------------------------------------------------------
# JSON schema (camelCase), produced by tools/release (task B), consumed here:
# {
#   "kind": "snapmaker-studio-acceptance-rewrap-attestation", "schemaVersion": 1,
#   "createdUtc": "<iso8601>",
#   "identity": { "productName", "manufacturer", "bundleId", "mainBinaryName" },   // must equal Acceptance constants
#   "source":   { "version": "<semver>", "installerSha256": "<64 hex>" },          // real released installer
#   "template": { "name", "version", "sha256": "<64 hex>" },                       // vendored NSIS template
#   "installer":{ "fileName", "sha256": "<64 hex>" },                              // the REWRAPPED installer (what may run)
#   "manifest": {
#     "files":   [ { "path", "sha256", "size", "role": "payload|renamed-main",
#                    "sourcePath", "sourceSha256" } ],                             // installed tree, NO uninstall.exe
#     "renames": [ { "from": "<production main exe>", "to": "<acceptance main exe>" } ],
#     "excluded":[ "uninstall.exe" ]
#   },
#   "deleteTargets": [ { "op": "RmDir|Delete|DeleteRegKey|DeleteRegValue", "target": "<string>" } ]  // B1 enumeration
# }

function Get-AttProp {
    param($Object, [string]$Name)
    if ($Object -is [System.Collections.IDictionary] -and $Object.Contains($Name)) { , $Object[$Name] } else { $null }
}

function Test-DeleteTargetAllowed {
    <# Positive allowlist for B1. Targets are POST-EXPANSION NSIS strings: only $INSTDIR, $SMPROGRAMS and $DESKTOP
       remain as tokens. Returns $null when allowed, else a short reason.
       Forms: RmDir|Delete  $INSTDIR[\<rel>] ; Delete $SMPROGRAMS\<Product>.lnk and $DESKTOP\<Product>.lnk ;
              DeleteRegKey  <uninstall key> | <manufacturer\product key> | <manufacturer key> (optional HKCU\ prefix) ;
              DeleteRegValue <Run key>\<Product>. Everything is derived from Acceptance constants. #>
    param([string]$Op, [string]$Target)
    $acc = $script:Identity.Acceptance; $reg = $script:Identity.Registry
    if ($Op -cnotin @('RmDir', 'Delete', 'DeleteRegKey', 'DeleteRegValue')) { return 'unknown op' }
    if ($Target -match '\$\{|\$\(|%') { return 'unresolved variable' }
    if ($Target -match '(^|[\\/])\.\.([\\/]|$)') { return 'traversal' }
    $t = $Target.Trim()
    switch ($Op) {
        { $_ -in 'RmDir', 'Delete' } {
            if ($t -ceq '$INSTDIR') { return $null }
            if ($t.StartsWith('$INSTDIR\', [StringComparison]::Ordinal)) {
                $rel = $t.Substring(9)
                if ($rel -match '\$' -or $rel -match ':' -or $rel -match '\\\\' -or $rel.Length -eq 0 -or $rel.EndsWith('\')) { return 'bad path under $INSTDIR' }
                return $null
            }
            if ($Op -eq 'Delete') {
                foreach ($dir in '$SMPROGRAMS', '$DESKTOP') { if ($t -ceq "$dir\$($acc.ProductName).lnk") { return $null } }
            }
            return 'not under $INSTDIR or an acceptance shortcut'
        }
        'DeleteRegKey' {
            $k = $t -replace '^HKCU\\', ''
            $ok = @("$($reg.UninstallKeyParent)\$($acc.ProductName)", "$($acc.Manufacturer)\$($acc.ProductName)", $acc.Manufacturer) | ForEach-Object { "Software\$_" }
            if (@($ok | Where-Object { $_ -ceq $k }).Count -eq 1) { return $null }
            return 'registry key is not an exact acceptance-identity key'
        }
        'DeleteRegValue' {
            $k = $t -replace '^HKCU\\', ''
            if ($k -ceq "Software\$($reg.RunKey)\$($acc.ProductName)") { return $null }
            return 'registry value is not the acceptance Run value'
        }
    }
    'unhandled'
}

function Test-RewrapAttestation {
    <# Returns an object { Valid; Errors[]; Attestation }. Never throws on bad content. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Attestation, [string]$InstallerSha256)
    $errs = New-Object System.Collections.Generic.List[string]
    $acc = $script:Identity.Acceptance
    $prod = $script:Identity.Production
    $att = $Attestation
    if ($att -is [string]) {
        try { $att = Get-Content -LiteralPath $att -Raw | ConvertFrom-Json -AsHashtable -DateKind String }
        catch { return [pscustomobject]@{ Valid = $false; Errors = @("attestation unreadable or not JSON: $($_.Exception.Message)"); Attestation = $null } }
    }
    if ($att -isnot [System.Collections.IDictionary]) {
        return [pscustomobject]@{ Valid = $false; Errors = @('attestation is not a JSON object'); Attestation = $null }
    }
    $hex = '^[0-9a-fA-F]{64}$'
    $safeRel = { param($p) ($p -is [string]) -and $p.Length -gt 0 -and $p -notmatch '^([A-Za-z]:|[\\/])' -and $p -notmatch '(^|[\\/])\.\.([\\/]|$)' -and $p -notmatch ':' }

    if ((Get-AttProp $att 'kind') -cne $script:Identity.Attestation.Kind) { $errs.Add('kind mismatch') }
    if ((Get-AttProp $att 'schemaVersion') -ne $script:Identity.Attestation.SchemaVersion) { $errs.Add('schemaVersion mismatch') }

    $idn = Get-AttProp $att 'identity'
    foreach ($pair in @(@('productName', $acc.ProductName), @('manufacturer', $acc.Manufacturer), @('bundleId', $acc.BundleId), @('mainBinaryName', $acc.MainBinaryName))) {
        if ((Get-AttProp $idn $pair[0]) -cne $pair[1]) { $errs.Add("identity.$($pair[0]) is not the acceptance value") }
    }

    $src = Get-AttProp $att 'source'
    $srcSha = Get-AttProp $src 'installerSha256'
    if (-not ($srcSha -is [string] -and $srcSha -match $hex)) { $errs.Add('source.installerSha256 missing/invalid') }
    if ([string]::IsNullOrWhiteSpace([string](Get-AttProp $src 'version'))) { $errs.Add('source.version missing') }
    $tpl = Get-AttProp $att 'template'
    $tplSha = Get-AttProp $tpl 'sha256'
    if (-not ($tplSha -is [string] -and $tplSha -match $hex)) { $errs.Add('template.sha256 missing/invalid') }
    if ([string]::IsNullOrWhiteSpace([string](Get-AttProp $tpl 'version'))) { $errs.Add('template.version missing') }

    $inst = Get-AttProp $att 'installer'
    $instSha = Get-AttProp $inst 'sha256'
    if (-not ($instSha -is [string] -and $instSha -match $hex)) { $errs.Add('installer.sha256 missing/invalid') }
    elseif ($InstallerSha256 -and ($instSha.ToLowerInvariant() -ne $InstallerSha256.ToLowerInvariant())) { $errs.Add('installer.sha256 does not match the installer under test') }
    if ($srcSha -is [string] -and $instSha -is [string] -and $srcSha.ToLowerInvariant() -eq $instSha.ToLowerInvariant()) {
        $errs.Add('rewrapped installer hash equals the real released installer hash (not rewrapped)')
    }

    $man = Get-AttProp $att 'manifest'
    $files = Get-AttProp $man 'files'
    $seen = @{}
    $mainCount = 0
    if ($files -isnot [System.Collections.IList] -or $files.Count -eq 0) { $errs.Add('manifest.files missing/empty') }
    else {
        foreach ($f in $files) {
            $fp = Get-AttProp $f 'path'
            if (-not (& $safeRel $fp)) { $errs.Add("manifest file path unsafe: $fp"); continue }
            $k = $fp.ToLowerInvariant()
            if ($seen.ContainsKey($k)) { $errs.Add("duplicate manifest path: $fp") }
            $seen[$k] = $true
            if ((Split-Path -Leaf $fp) -ieq $acc.UninstallerName) { $errs.Add('manifest must not list uninstall.exe (installer machinery is excluded)') }
            if ((Split-Path -Leaf $fp) -ieq $prod.MainBinaryName) { $errs.Add('manifest lists the production main binary name') }
            $sha = Get-AttProp $f 'sha256'; $ssha = Get-AttProp $f 'sourceSha256'
            if (-not ($sha -is [string] -and $sha -match $hex -and $ssha -is [string] -and $ssha -match $hex)) { $errs.Add("manifest hashes invalid for $fp") }
            elseif ($sha.ToLowerInvariant() -ne $ssha.ToLowerInvariant()) { $errs.Add("payload bytes differ from the real installer for $fp") }
            $role = Get-AttProp $f 'role'
            if ($role -eq 'renamed-main') {
                $mainCount++
                if ($fp -cne $acc.MainBinaryName) { $errs.Add('renamed-main path is not the acceptance main binary name') }
                if ((Get-AttProp $f 'sourcePath') -cne $prod.MainBinaryName) { $errs.Add('renamed-main sourcePath is not the production main binary name') }
            } elseif ($role -ne 'payload') { $errs.Add("manifest role invalid for $fp") }
        }
        if ($mainCount -ne 1) { $errs.Add("manifest must contain exactly one renamed-main entry (found $mainCount)") }
    }
    $ren = Get-AttProp $man 'renames'
    $okRen = $false
    if ($ren -is [System.Collections.IList]) {
        foreach ($r in $ren) { if ((Get-AttProp $r 'from') -ceq $prod.MainBinaryName -and (Get-AttProp $r 'to') -ceq $acc.MainBinaryName) { $okRen = $true } }
    }
    if (-not $okRen) { $errs.Add('manifest.renames lacks production->acceptance main binary rename') }
    $exc = Get-AttProp $man 'excluded'
    if ($exc -isnot [System.Collections.IList] -or -not (@($exc) -contains $acc.UninstallerName)) { $errs.Add('manifest.excluded must list uninstall.exe') }
    else { foreach ($e in $exc) { if ($e -cne $acc.UninstallerName) { $errs.Add("manifest.excluded lists unexpected entry: $e") } } }

    # M8: installed file set is EXACTLY {acceptance main exe, sidecar}; nothing else, nothing missing.
    if ($files -is [System.Collections.IList]) {
        $want = @($acc.MainBinaryName, $acc.SidecarName)
        $have = @($files | ForEach-Object { [string](Get-AttProp $_ 'path') })
        foreach ($w in $want) { if (@($have | Where-Object { $_ -ieq $w }).Count -ne 1) { $errs.Add("installed file set must contain exactly one $w") } }
        foreach ($h in $have) { if ($want -notcontains $h -and @($want | Where-Object { $_ -ieq $h }).Count -eq 0) { $errs.Add("unexpected file in installed file set: $h") } }
    }

    # Template must be the pinned vendored template (slot in HarnessIdentity.psd1, filled by task B).
    $pin = [string]$script:Identity.Attestation.PinnedTemplateSha256
    if ($pin -notmatch $hex) { $errs.Add('no pinned template sha256 configured (fail closed)') }
    elseif ($tplSha -is [string] -and $tplSha.ToLowerInvariant() -ne $pin.ToLowerInvariant()) { $errs.Add('template.sha256 does not equal the pinned template hash') }

    # B1: delete-target enumeration must be present, non-empty, fully expanded, and on a POSITIVE allowlist.
    $dt = Get-AttProp $att 'deleteTargets'
    if ($dt -isnot [System.Collections.IList] -or $dt.Count -eq 0) { $errs.Add('deleteTargets enumeration missing or empty (B1)') }
    else {
        foreach ($t in $dt) {
            $target = [string](Get-AttProp $t 'target')
            if ([string]::IsNullOrWhiteSpace($target)) { $errs.Add('deleteTargets entry without target'); continue }
            $why = Test-DeleteTargetAllowed -Op ([string](Get-AttProp $t 'op')) -Target $target
            if ($why) { $errs.Add("deleteTargets entry refused ($why): $target"); continue }
            foreach ($pat in $prod.ForbiddenTargetPatterns) {
                if ($target -match $pat) { $errs.Add("deleteTargets entry derives from a production identifier: $target"); break }
            }
        }
    }
    [pscustomobject]@{ Valid = ($errs.Count -eq 0); Errors = @($errs); Attestation = $att }
}

# ---------------------------------------------------------------------------
# Installer / uninstaller authorization (branch W only)
# ---------------------------------------------------------------------------

function Assert-InstallerAllowed {
    <# Copy-then-hash-then-launch (O3). Returns an object whose .Path is the harness-owned
       copy; the caller must launch THAT path and nothing else. Throws on any doubt. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$AttestationPath,
        [string]$HarnessRoot
    )
    $root = Get-HarnessRoot -HarnessRoot $HarnessRoot
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Refused: installer not found: $Path" }
    if (-not (Test-Path -LiteralPath $AttestationPath -PathType Leaf)) { throw 'Refused: attestation file not found.' }

    $attDir = Join-Path $root $script:Identity.HarnessSubdirs.Attestations
    if (-not (Test-PathContained -Path $AttestationPath -Root $attDir)) { throw 'Refused: attestation is not inside the harness attestations dir.' }
    Assert-HarnessOwnedPath -Path $AttestationPath -Root $root -What 'attestation file'

    $stagingRoot = Join-Path $root $script:Identity.HarnessSubdirs.Staging
    Assert-HarnessOwnedPath -Path $stagingRoot -Root $root -What 'staging dir'
    [void][IO.Directory]::CreateDirectory($stagingRoot)
    Assert-HarnessOwnedPath -Path $stagingRoot -Root $root -What 'staging dir'
    $stage = Join-Path $stagingRoot ([guid]::NewGuid().ToString('N'))
    Assert-HarnessOwnedPath -Path $stage -Root $root -What 'staging subdir'
    [void][IO.Directory]::CreateDirectory($stage)
    $copy = Join-Path $stage ('installer-' + [IO.Path]::GetFileName($Path))
    Assert-HarnessOwnedPath -Path $copy -Root $root -What 'installer copy target'
    Copy-Item -LiteralPath $Path -Destination $copy -Force
    Assert-HarnessOwnedPath -Path $copy -Root $root -What 'installer copy'

    # Everything below inspects the COPY, never the original (TOCTOU).
    $sha = Get-FileSha256 -Path $copy
    $pn = Get-ExeProductName -Path $copy
    if (Test-IsProductionProductName $pn) { throw "Refused: installer carries the PRODUCTION identity ('$pn'). Production installers never run on the workstation." }
    if ($pn -cne $script:Identity.Acceptance.ProductName) { throw "Refused: installer ProductName '$pn' is not the acceptance identity." }

    $v = Test-RewrapAttestation -Attestation $AttestationPath -InstallerSha256 $sha
    if (-not $v.Valid) { throw "Refused: installer hash $sha is not bound to a valid rewrap attestation: $($v.Errors -join '; ')" }

    [pscustomobject]@{ Path = $copy; Sha256 = $sha; ProductName = $pn; Attestation = $v.Attestation; Version = [string]$v.Attestation['source']['version'] }
}

function Get-UninstallStringPath {
    param([string]$UninstallString)
    if ([string]::IsNullOrWhiteSpace($UninstallString)) { return $null }
    $s = $UninstallString.Trim()
    if ($s.StartsWith('"')) { $end = $s.IndexOf('"', 1); if ($end -lt 0) { return $null }; return $s.Substring(1, $end - 1) }
    if ($s -match '^(.*?\.exe)(\s|$)') { return $Matches[1] }
    $null
}

function Confirm-InstallerUnchanged {
    <# B2 (TOCTOU). Call IMMEDIATELY before Start-Process on the staged copy returned by Assert-InstallerAllowed:
       re-checks containment under <harness>\staging, reparse points, sha256 and VersionInfo identity. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$ExpectedSha256, [string]$HarnessRoot)
    $root = Get-HarnessRoot -HarnessRoot $HarnessRoot
    $stagingRoot = Join-Path $root $script:Identity.HarnessSubdirs.Staging
    if (-not (Test-PathContained -Path $Path -Root $stagingRoot)) { throw 'Refused: installer is not a staged copy under the harness staging dir.' }
    Assert-HarnessOwnedPath -Path $Path -Root $root -What 'staged installer'
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw 'Refused: staged installer vanished before exec.' }
    if ((Get-FileSha256 -Path $Path) -ne $ExpectedSha256.ToLowerInvariant()) { throw 'Refused: staged installer changed between authorization and exec.' }
    $pn = Get-ExeProductName -Path $Path
    if (Test-IsProductionProductName $pn) { throw 'Refused: staged installer carries the PRODUCTION identity.' }
    if ($pn -cne $script:Identity.Acceptance.ProductName) { throw 'Refused: staged installer is not the acceptance identity.' }
    $true
}

function Assert-UninstallerAllowed {
    <# C1 + F2. The journal is read FROM DISK by run id (never passed in). An uninstaller may run only if ALL hold:
       - journal state == 'installed'
       - path == <journaled acceptance install dir>\uninstall.exe, install dir inside <harness>\install
       - acceptance uninstall key UninstallString resolves to the same path
       - not under any extraction/rewrap/staging work dir, no reparse points on any component
       - VersionInfo (when present) is not the production identity
       - sha256 equals the value Set-JournalOwnedAfter computed from the installed file
       Confirm-UninstallerUnchanged re-runs all of this immediately before exec. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$RunId,
        [string]$JournalDir,
        [string]$HarnessRoot,
        [string]$RegistryRoot = 'HKCU:\Software',
        [string[]]$ExtraWorkDirs = @()
    )
    $root = Get-HarnessRoot -HarnessRoot $HarnessRoot
    Assert-SafeRegistryRoot -RegistryRoot $RegistryRoot
    $acc = $script:Identity.Acceptance
    # Late import: HarnessJournal imports this module, so it cannot be imported at load time.
    $jm = Import-Module (Join-Path $PSScriptRoot '..\harness\HarnessJournal.psm1') -PassThru -DisableNameChecking
    $Journal = & $jm.ExportedCommands['Read-HarnessJournal'] -RunId $RunId -JournalDir $JournalDir -HarnessRoot $HarnessRoot
    if ($Journal['state'] -cne 'installed') { throw "Refused: journal state is '$($Journal['state'])', not 'installed'." }
    $installDir = [string]$Journal['installDir']
    $recorded = [string]$Journal['uninstallerSha256']
    if ([string]::IsNullOrWhiteSpace($installDir)) { throw 'Refused: journal has no install dir.' }
    if ($recorded -notmatch '^[0-9a-fA-F]{64}$') { throw 'Refused: no uninstaller sha256 was recorded at install.' }

    $installRoot = Join-Path $root $script:Identity.HarnessSubdirs.Install
    if (-not (Test-PathContained -Path $installDir -Root $installRoot)) { throw 'Refused: journaled install dir is not under the harness install tree.' }
    Assert-HarnessOwnedPath -Path $installDir -Root $root -What 'journaled install dir'
    if (Test-UnderWorkDir -Path $installDir -HarnessRoot $HarnessRoot -ExtraWorkDirs $ExtraWorkDirs) { throw 'Refused: install dir is inside an extraction/rewrap work dir.' }

    $expected = [IO.Path]::GetFullPath((Join-Path $installDir $acc.UninstallerName))
    $given = [IO.Path]::GetFullPath($Path)
    if (-not $given.Equals($expected, [StringComparison]::OrdinalIgnoreCase)) { throw 'Refused: uninstaller path is not <journaled install dir>\uninstall.exe.' }
    if (Test-UnderWorkDir -Path $given -HarnessRoot $HarnessRoot -ExtraWorkDirs $ExtraWorkDirs) { throw 'Refused: uninstaller is inside an extraction/rewrap work dir.' }
    Assert-HarnessOwnedPath -Path $given -Root $root -What 'uninstaller'
    if (-not (Test-Path -LiteralPath $given -PathType Leaf)) { throw 'Refused: uninstaller does not exist.' }

    # Uninstall key must agree.
    $keyPath = ($RegistryRoot.TrimEnd('\')) + '\' + $script:Identity.Registry.UninstallKeyParent + '\' + $acc.ProductName
    $us = $null
    if (Test-Path -LiteralPath $keyPath) { $us = (Get-ItemProperty -LiteralPath $keyPath -ErrorAction Stop).PSObject.Properties['UninstallString'] }
    if (-not $us) { throw 'Refused: acceptance uninstall key has no UninstallString.' }
    $usPath = Get-UninstallStringPath -UninstallString ([string]$us.Value)
    if (-not $usPath -or -not [IO.Path]::GetFullPath($usPath).Equals($given, [StringComparison]::OrdinalIgnoreCase)) { throw 'Refused: acceptance uninstall key UninstallString does not resolve to the same path.' }

    $pn = Get-ExeProductName -Path $given
    if (Test-IsProductionProductName $pn) { throw 'Refused: uninstaller VersionInfo is the production identity.' }

    $sha = Get-FileSha256 -Path $given
    if ($sha -ne $recorded.ToLowerInvariant()) { throw 'Refused: uninstaller sha256 differs from the value recorded at install.' }
    [pscustomobject]@{
        Path = $given; Sha256 = $sha
        Params = @{ Path = $Path; RunId = $RunId; JournalDir = $JournalDir; HarnessRoot = $HarnessRoot; RegistryRoot = $RegistryRoot; ExtraWorkDirs = $ExtraWorkDirs }
    }
}

function Confirm-UninstallerUnchanged {
    <# Call immediately before exec of an object returned by Assert-UninstallerAllowed. Re-runs the FULL C1 check
       (journal state, containment, reparse points, UninstallString agreement, VersionInfo, sha256). #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Allowed)
    $p = $Allowed.Params
    $again = Assert-UninstallerAllowed @p
    if ($again.Sha256 -ne $Allowed.Sha256 -or $again.Path -ne $Allowed.Path) { throw 'Refused: uninstaller changed between authorization and exec.' }
    $true
}

# ---------------------------------------------------------------------------
# Production registration detection (read-only)
# ---------------------------------------------------------------------------

function Get-ProductionRegistration {
    <# Read-only. Returns findings (string[]); empty = none seen. Exact keys only, no wildcards.
       -SoftwareRoots defaults to HKCU/HKLM/WOW6432 views; tests pass a scratch root. #>
    [CmdletBinding()]
    param(
        [string[]]$SoftwareRoots = @('HKCU:\Software', 'HKLM:\Software', 'HKLM:\Software\WOW6432Node', 'HKCU:\Software\WOW6432Node'),
        [string[]]$DefaultInstallDirs,
        [scriptblock]$ProcessProvider = { param($name) Get-Process -Name $name -ErrorAction SilentlyContinue }
    )
    $prod = $script:Identity.Production
    $found = New-Object System.Collections.Generic.List[string]
    foreach ($r in $SoftwareRoots) {
        $uk = $r.TrimEnd('\') + '\' + $script:Identity.Registry.UninstallKeyParent + '\' + $prod.ProductName
        if (Test-Path -LiteralPath $uk) { $found.Add("uninstall key present: $uk") }
        $mk = $r.TrimEnd('\') + '\' + $prod.Manufacturer + '\' + $prod.ProductName
        if (Test-Path -LiteralPath $mk) { $found.Add("remembered-location key present: $mk") }
        $pk = $r.TrimEnd('\') + '\' + $prod.Manufacturer
        if (Test-Path -LiteralPath $pk) { $found.Add("manufacturer key present: $pk") }
    }
    if (-not $PSBoundParameters.ContainsKey('DefaultInstallDirs')) {
        $DefaultInstallDirs = @()
        foreach ($b in @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
            if ($b) { $DefaultInstallDirs += (Join-Path $b $prod.DefaultInstallDirName) }
        }
    }
    foreach ($d in $DefaultInstallDirs) {
        $exe = Join-Path $d $prod.MainBinaryName
        if (Test-Path -LiteralPath $exe) { $found.Add("production exe present at default path: $exe") }
    }
    foreach ($p in @(& $ProcessProvider $prod.ProcessName)) {
        if ($p) { $found.Add("production process running (pid $($p.Id))") }
    }
    $found.ToArray()
}

function Test-ProductionRunning {
    [CmdletBinding()]
    param([scriptblock]$ProcessProvider = { param($name) Get-Process -Name $name -ErrorAction SilentlyContinue })
    @(& $ProcessProvider $script:Identity.Production.ProcessName | Where-Object { $_ }).Count -gt 0
}

function Assert-ProductionNotRunning {
    [CmdletBinding()]
    param([scriptblock]$ProcessProvider = { param($name) Get-Process -Name $name -ErrorAction SilentlyContinue })
    if (Test-ProductionRunning -ProcessProvider $ProcessProvider) { throw 'Refused: the production Snapmaker Studio process is running. Close it yourself; the harness will not.' }
}

function Assert-NoProductionRegistration {
    <# Strict preflight for callers that require a machine with no production footprint. #>
    [CmdletBinding()]
    param([string[]]$SoftwareRoots, [string[]]$DefaultInstallDirs, [scriptblock]$ProcessProvider)
    $fwd = @{}
    foreach ($k in 'SoftwareRoots', 'DefaultInstallDirs', 'ProcessProvider') { if ($PSBoundParameters.ContainsKey($k)) { $fwd[$k] = $PSBoundParameters[$k] } }
    $f = @(Get-ProductionRegistration @fwd)
    if ($f.Count -gt 0) { throw "Refused: production registration present: $($f -join '; ')" }
}

# ---------------------------------------------------------------------------
# Machine-wide single-run lock (M5)
# ---------------------------------------------------------------------------

function Get-ProcessStartTicks {
    param([int]$ProcessId)
    try { (Get-Process -Id $ProcessId -ErrorAction Stop).StartTime.ToUniversalTime().Ticks } catch { $null }
}

function Enter-HarnessLock {
    <# Named mutex + pid/start-time lock file. Stale lock (dead pid or pid reuse) is taken over;
       a live holder, or an unreadable lock file without proof of staleness, => throw. #>
    [CmdletBinding()]
    param([string]$HarnessRoot, [string]$MutexName = $script:Identity.LockMutexName)
    # The machine-wide default is Global\...; an override (tests) may only be a Local\ name, never a Global one.
    if ($PSBoundParameters.ContainsKey('MutexName') -and $MutexName -notmatch '^Local\\[A-Za-z0-9._-]{1,100}\z') {
        throw 'Refused: a MutexName override must match ^Local\<name>.'
    }
    $root = Get-HarnessRoot -HarnessRoot $HarnessRoot
    $lockDir = Join-Path $root $script:Identity.HarnessSubdirs.Lock
    Assert-HarnessOwnedPath -Path $lockDir -Root $root -What 'lock dir'
    [void][IO.Directory]::CreateDirectory($lockDir)
    $lockFile = Join-Path $lockDir $script:Identity.LockFileName

    $mutex = New-Object System.Threading.Mutex($false, $MutexName)
    $stale = $false
    $got = $false
    try {
        try { $got = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $got = $true; $stale = $true }
        if (-not $got) { throw 'Refused: another harness run holds the machine-wide lock.' }

        if (Test-Path -LiteralPath $lockFile) {
            $holder = $null
            try { $holder = Get-Content -LiteralPath $lockFile -Raw | ConvertFrom-Json -AsHashtable -DateKind String } catch { }
            if ($holder -isnot [System.Collections.IDictionary] -or -not $holder.Contains('pid') -or -not $holder.Contains('startTicks')) {
                if (-not $stale) { throw 'Refused: lock file is unreadable and the previous holder cannot be proven dead.' }
            } else {
                $ticks = Get-ProcessStartTicks -ProcessId ([int]$holder['pid'])
                if ($null -ne $ticks -and [int64]$holder['startTicks'] -eq $ticks) {
                    throw "Refused: lock file names a live holder (pid $($holder['pid']))."
                }
                $stale = $true
            }
        }
        $me = [ordered]@{ pid = $PID; startTicks = (Get-ProcessStartTicks -ProcessId $PID); acquiredUtc = [DateTime]::UtcNow.ToString('o') }
        Write-AtomicFile -Path $lockFile -Bytes ([Text.Encoding]::UTF8.GetBytes(($me | ConvertTo-Json))) -Container $lockDir
    } catch {
        if ($got) { try { $mutex.ReleaseMutex() } catch { } }
        $mutex.Dispose()
        throw
    }
    # The authoritative state (harness root, mutex, pid) lives in a module-private table keyed by an opaque token.
    # The returned object's path fields are DISPLAY-ONLY: Exit-HarnessLock never acts on them.
    $token = [guid]::NewGuid().ToString('N')
    # Record the caller's ORIGINAL -HarnessRoot argument (empty = default). A resolved default root must never be fed
    # back through the override gate (equal-to-default is refused there), so Exit re-derives from the original argument.
    $script:ActiveLocks[$token] = @{ OriginalHarnessRoot = $HarnessRoot; Mutex = $mutex; Pid = $PID; LockFile = $lockFile; LockDir = $lockDir }
    [pscustomobject]@{ Token = $token; Mutex = $mutex; LockFile = $lockFile; LockDir = $lockDir; TookOverStale = $stale; Pid = $PID }
}

function Exit-HarnessLock {
    <# Derive, don't trust: nothing path-like is read from $Lock. The handle token selects the module-private record;
       the lock file is re-derived as <harness root>\lock\<fixed LockFileName>, re-validated (positive allowlist +
       volume-root reparse walk), and deleted only if it still names THIS process (pid + start time). A forged or
       mutated lock object (different token, LockFile, LockDir or Pid) is refused with nothing deleted. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lock)
    $get = { param($n) $p = $Lock.PSObject.Properties[$n]; if ($p) { $p.Value } }
    $token = [string](& $get 'Token')
    if ([string]::IsNullOrEmpty($token) -or -not $script:ActiveLocks.ContainsKey($token)) { throw 'Refused: unknown or forged lock handle.' }
    $rec = $script:ActiveLocks[$token]
    # Object-vs-handle comparison is pure string comparison against what Enter recorded (no path derivation, no
    # validation that could throw), and stays OUTSIDE the try so a forged object cannot release someone else's lock.
    $same = { param($a, $b) (-not [string]::IsNullOrEmpty($a)) -and ([string]$a).Equals([string]$b, [StringComparison]::OrdinalIgnoreCase) }
    if (-not (& $same (& $get 'LockFile') $rec.LockFile) -or -not (& $same (& $get 'LockDir') $rec.LockDir) -or [int](& $get 'Pid') -ne [int]$rec.Pid -or
        [IO.Path]::GetFileName([string](& $get 'LockFile')) -cne $script:Identity.LockFileName) {
        throw 'Refused: lock object does not match its handle (forged or mutated).'
    }
    try {
        # Derivation and validation are INSIDE the try: a root that now fails validation still frees mutex + token.
        $rootD = Get-HarnessRoot -HarnessRoot $rec.OriginalHarnessRoot
        $lockDirD = Join-Path $rootD $script:Identity.HarnessSubdirs.Lock
        $lockFileD = Join-Path $lockDirD $script:Identity.LockFileName
        Assert-HarnessOwnedPath -Path $lockFileD -Root $lockDirD -What 'lock file'
        if ([IO.Path]::GetFileName($lockFileD) -cne $script:Identity.LockFileName) { throw 'Refused: lock file leaf name is not the fixed lock file name.' }
        if (Test-Path -LiteralPath $lockFileD -PathType Leaf) {
            $h = $null
            try { $h = Get-Content -LiteralPath $lockFileD -Raw | ConvertFrom-Json -AsHashtable -DateKind String } catch { }
            if ($h -is [System.Collections.IDictionary] -and $h.Contains('pid') -and $h.Contains('startTicks') -and
                [int]$h['pid'] -eq [int]$rec.Pid -and [int64]$h['startTicks'] -eq (Get-ProcessStartTicks -ProcessId $rec.Pid)) {
                Assert-HarnessOwnedPath -Path $lockFileD -Root $lockDirD -What 'lock file'   # again, immediately before deleting
                Remove-Item -LiteralPath $lockFileD -Force
            }
        }
    } finally {
        try { $rec.Mutex.ReleaseMutex() } catch { }
        $rec.Mutex.Dispose()
        $script:ActiveLocks.Remove($token)
    }
}

Export-ModuleMember -Function Get-HarnessIdentity, Get-HarnessRoot, Get-HarnessSubdir, Test-PathContained, Test-ContainsReparsePoint,
    Assert-HarnessOwnedPath, Test-UnderWorkDir, Get-FileSha256, Test-RewrapAttestation, Test-DeleteTargetAllowed,
    Assert-NotProductionLocation, Assert-SafeRegistryRoot, Assert-AllowedOverridePath, Test-PathContainedNoReparse, Get-DefaultHarnessRoot,
    Assert-InstallerAllowed, Confirm-InstallerUnchanged, Assert-UninstallerAllowed, Confirm-UninstallerUnchanged, Get-UninstallStringPath,
    Get-ProductionRegistration, Test-ProductionRunning, Assert-ProductionNotRunning, Assert-NoProductionRegistration,
    Enter-HarnessLock, Exit-HarnessLock, Get-ProcessStartTicks, Test-IsProductionProductName
