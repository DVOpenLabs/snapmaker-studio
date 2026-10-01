<#
SHORTCUT POLICY EVIDENCE (production v1.1.0/v1.2.0 NSIS, per-user /S):
- template/installer.nsi:254-262 calls the Start Menu creator for every install and the Desktop
  creator when ${Silent} is true; /S therefore creates both links.
- template/installer.nsi:354-373 names both links "Snapmaker Studio.lnk", targets
  $INSTDIR\snapmaker-studio-desktop.exe, sets the AUMID on each, and skips both for /NS.
- desktop/src-tauri/tauri.conf.json:3, 8 and 27-29 establish the product name, identifier
  com.snapmakerstudio.desktop, and currentUser NSIS mode; template/installer.nsi:76-77 sets user level.
- tools/release/nsis/PROVENANCE.md:92 and 96-97 record retained /NS semantics and matching
  shortcut/AUMID behavior; template.patch:107-108 is the per-user acceptance change.
Assert hard-fails missing/wrong-target/AUMID-less links for /S. Report remains available for
invocation-dependent observations (including desktop absent under /NS). AssertAbsent requires
both links gone after uninstall; the remembered install-location key is intentionally retained.
#>
[CmdletBinding()]
param(
    [ValidateSet('Assert', 'AssertAbsent', 'Report')]
    [string] $Action = 'Assert',
    [string] $StartMenuDir = [Environment]::GetFolderPath('Programs'),
    [string] $DesktopDir = [Environment]::GetFolderPath('Desktop'),
    [string] $InstallDir = (Join-Path $env:LOCALAPPDATA 'Snapmaker Studio'),
    [string] $ExpectedAumid,
    [string] $OutFile
)

function Write-CiAssertOutput {
    param(
        [Parameter(Mandatory)] [object] $Value,
        [string] $Path,
        [string] $Root
    )

    $text = $Value | ConvertTo-Json -Depth 8
    if ([string]::IsNullOrWhiteSpace($Path)) {
        $text
        return
    }

    $full = [IO.Path]::GetFullPath($Path)
    if (-not [IO.Path]::IsPathRooted($full) -or $full -notmatch '^[A-Za-z]:\\' -or $full -match '^(?i)(\\\\|\\\\\.\\)') { throw 'OutFile must be an absolute drive-letter path.' }
    $allowed = @($env:RUNNER_TEMP, [IO.Path]::GetTempPath()) | Where-Object { $_ }
    $approved = $allowed | Where-Object { $rootFull = [IO.Path]::GetFullPath($_).TrimEnd('\'); $full -eq $rootFull -or $full.StartsWith($rootFull + '\', [StringComparison]::OrdinalIgnoreCase) }
    if (-not $approved) { throw 'OutFile must be under RUNNER_TEMP or the system temp directory.' }
    if ($full.IndexOf(':', 2) -ge 0) { throw 'OutFile may not use an alternate data stream.' }
    $leaf = [IO.FileInfo]::new($full)
    if ($leaf.Exists -and ($leaf.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'OutFile leaf may not be a reparse point.' }
    $cursor = $leaf.Directory
    if (-not $cursor -or -not $cursor.Exists) { throw 'OutFile parent must already exist.' }
    while ($cursor) { if ($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'OutFile path may not traverse a reparse point.' }; $cursor = $cursor.Parent }

    [IO.File]::WriteAllText($full, $text)
}

function Read-CiShortcut {
    param([string] $Path, [string] $ExpectedTarget, [string] $Aumid)
    if (-not (Test-Path -LiteralPath $Path)) {
        return [pscustomobject]@{ Path = $Path; Present = $false; TargetPath = $null; Aumid = $null; TargetMatches = $false; AumidVerified = $false }
    }
    $shell = [Activator]::CreateInstance([Type]::GetTypeFromProgID('WScript.Shell'))
    $link = $shell.CreateShortcut($Path)
    # This is a UTF-16LE byte-substring check, not a full ShellLink property-store parse.
    $aumidVerified = $false
    if ($Aumid) {
        $bytes = [IO.File]::ReadAllBytes($Path)
        $needle = [Text.Encoding]::Unicode.GetBytes($Aumid)
        $aumidVerified = $false
        for ($i = 0; $i -le $bytes.Length - $needle.Length; $i++) {
            $match = $true
            for ($j = 0; $j -lt $needle.Length; $j++) {
                if ($bytes[$i + $j] -ne $needle[$j]) { $match = $false; break }
            }
            if ($match) { $aumidVerified = $true; break }
        }
    }
    [pscustomobject]@{
        Path = $Path
        Present = $true
        TargetPath = [string] $link.TargetPath
        Aumid = $null
        TargetMatches = (-not [string]::IsNullOrWhiteSpace([string] $link.TargetPath)) -and [IO.Path]::GetFullPath([string] $link.TargetPath) -eq [IO.Path]::GetFullPath($ExpectedTarget)
        AumidVerified = $aumidVerified
    }
}

function Test-CiShortcutAumid {
    param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][string]$Expected)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $bytes=[IO.File]::ReadAllBytes($Path);$needle=[Text.Encoding]::Unicode.GetBytes($Expected)
    for($i=0;$i -le $bytes.Length-$needle.Length;$i++){ $match=$true;for($j=0;$j -lt $needle.Length;$j++){if($bytes[$i+$j]-ne $needle[$j]){$match=$false;break}};if($match){return $true} }
    $false
}

function Assert-CiShortcuts {
    param([string] $StartMenu, [string] $Desktop, [string] $Dir, [string] $Aumid)
    $target = Join-Path $Dir 'snapmaker-studio-desktop.exe'
    $results = @(
        Read-CiShortcut (Join-Path $StartMenu 'Snapmaker Studio.lnk') $target $Aumid
        Read-CiShortcut (Join-Path $Desktop 'Snapmaker Studio.lnk') $target $Aumid
    )
    if ($results | Where-Object { -not $_.TargetMatches }) {
        throw 'A required shortcut is absent or targets a different executable.'
    }
    if ($Aumid -and ($results | Where-Object { -not $_.AumidVerified })) { throw "A required shortcut lacks AUMID '$Aumid'." }
    $results
}

function Assert-CiShortcutsAbsent {
    param([string] $StartMenu, [string] $Desktop)
    $paths = @((Join-Path $StartMenu 'Snapmaker Studio.lnk'), (Join-Path $Desktop 'Snapmaker Studio.lnk'))
    if ($paths | Where-Object { Test-Path -LiteralPath $_ }) { throw 'An installed shortcut remains after uninstall.' }
    @($paths | ForEach-Object { [pscustomobject]@{ Path = $_; Present = $false } })
}

if ($MyInvocation.InvocationName -ne '.') {
    $result = if ($Action -eq 'Assert') {
        Assert-CiShortcuts -StartMenu $StartMenuDir -Desktop $DesktopDir -Dir $InstallDir -Aumid $ExpectedAumid
    } elseif ($Action -eq 'AssertAbsent') {
        Assert-CiShortcutsAbsent -StartMenu $StartMenuDir -Desktop $DesktopDir
    } else {
        @(
            Read-CiShortcut (Join-Path $StartMenuDir 'Snapmaker Studio.lnk') (Join-Path $InstallDir 'snapmaker-studio-desktop.exe') $ExpectedAumid
            Read-CiShortcut (Join-Path $DesktopDir 'Snapmaker Studio.lnk') (Join-Path $InstallDir 'snapmaker-studio-desktop.exe') $ExpectedAumid
        )
    }
    Write-CiAssertOutput $result $OutFile
}
