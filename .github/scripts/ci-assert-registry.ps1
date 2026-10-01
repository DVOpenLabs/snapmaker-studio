[CmdletBinding()]
param(
    [ValidateSet('Assert', 'Report')]
    [string] $Action = 'Report',
    [string] $RegistryRoot = 'HKCU:\Software',
    [string] $InstallDir,
    [string] $OutFile,
    [switch] $AfterUninstall
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

function ConvertTo-RegistryRelativePath {
    param([Parameter(Mandatory)] [string] $Root)

    if ($Root -notmatch '^HKCU:\\Software(?:\\(.*))?$') {
        throw "RegistryRoot must be under HKCU:\Software: $Root"
    }
    if ($matches[1]) {
        return "Software\$($matches[1])"
    }
    return 'Software'
}

function Open-CiRegistryKey {
    param(
        [Parameter(Mandatory)] [string] $Root,
        [Parameter(Mandatory)] [string[]] $ChildNames
    )

    $relative = ConvertTo-RegistryRelativePath $Root
    foreach ($child in $ChildNames) {
        $relative = "$relative\$child"
    }
    [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($relative, $false)
}

function Get-CiRegistrySnapshot {
    param(
        [string] $Root = 'HKCU:\Software',
        [string] $Dir
    )
    $uninstall = Open-CiRegistryKey $Root @('Microsoft', 'Windows', 'CurrentVersion', 'Uninstall', 'Snapmaker Studio')
    $remembered = Open-CiRegistryKey $Root @('DeadlyVirusIn / Snapmaker Studio', 'Snapmaker Studio')
    $manufacturer = Open-CiRegistryKey $Root @('DeadlyVirusIn / Snapmaker Studio')
    $run = Open-CiRegistryKey $Root @('Microsoft', 'Windows', 'CurrentVersion', 'Run')

    $snapshot = [ordered]@{
        UninstallKey = 'Microsoft\Windows\CurrentVersion\Uninstall\Snapmaker Studio'
        UninstallKeyPresent = $null -ne $uninstall
        DisplayName = if ($uninstall) { [string] $uninstall.GetValue('DisplayName', $null) } else { $null }
        DisplayVersion = if ($uninstall) { [string] $uninstall.GetValue('DisplayVersion', $null) } else { $null }
        InstallLocation = if ($uninstall) { ([string] $uninstall.GetValue('InstallLocation', $null)).Trim('"') } else { $null }
        UninstallString = if ($uninstall) { [string] $uninstall.GetValue('UninstallString', $null) } else { $null }
        RememberedKeyPresent = $null -ne $remembered
        RememberedLocation = if ($remembered) { [string] $remembered.GetValue('', $null) } else { $null }
        ManufacturerKeyPresent = $null -ne $manufacturer
        RunValuePresent = $null -ne $run -and $null -ne $run.GetValue('Snapmaker Studio', $null)
        InstallDirPresent = if ($Dir) { Test-Path -LiteralPath $Dir } else { $null }
    }

    foreach ($key in @($uninstall, $remembered, $manufacturer, $run)) {
        if ($key) { $key.Dispose() }
    }
    [pscustomobject] $snapshot
}

function Assert-CiRegistryState {
    param(
        [string] $Root = 'HKCU:\Software',
        [Parameter(Mandatory)] [string] $Dir,
        [switch] $AfterUninstall
    )

    $state = Get-CiRegistrySnapshot -Root $Root -Dir $Dir
    if ($AfterUninstall) {
        if ($state.UninstallKeyPresent -or $state.InstallDirPresent -or $state.RunValuePresent) {
            throw 'Post-uninstall exact registration or install directory remains.'
        }
        if (-not $state.RememberedKeyPresent -or $state.RememberedLocation -ne $Dir) {
            throw 'Post-uninstall remembered-location state was not retained.'
        }
        return $state
    }
    if (-not $state.UninstallKeyPresent) { throw 'Exact Snapmaker Studio uninstall key is absent.' }
    if ($state.InstallLocation -ne $Dir) { throw "InstallLocation '$($state.InstallLocation)' is not '$Dir'." }
    if (-not $state.RememberedKeyPresent -or $state.RememberedLocation -ne $Dir) { throw 'Remembered-location default does not equal the install directory.' }
    if (-not $state.ManufacturerKeyPresent) { throw 'Manufacturer registry key is absent.' }
    if ($state.RunValuePresent) { throw 'Snapmaker Studio Run value must be absent.' }
    $state
}

if ($Action -eq 'Assert') {
        Write-CiAssertOutput (Assert-CiRegistryState -Root $RegistryRoot -Dir $InstallDir -AfterUninstall:$AfterUninstall) $OutFile
} elseif ($Action -eq 'Report') {
    Write-CiAssertOutput (Get-CiRegistrySnapshot -Root $RegistryRoot -Dir $InstallDir) $OutFile
}
