[CmdletBinding()]
param(
    [string] $InstallDir = (Join-Path $env:LOCALAPPDATA 'Snapmaker Studio'),
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
    if ($full.IndexOf(':', 2) -ge 0) { throw 'OutFile may not use an alternate data stream.' }
    $roots = @($env:RUNNER_TEMP, [IO.Path]::GetTempPath()) | Where-Object { $_ }
    $approved = $roots | Where-Object {
        $rootFull = [IO.Path]::GetFullPath($_).TrimEnd('\')
        $full -eq $rootFull -or $full.StartsWith($rootFull + '\', [StringComparison]::OrdinalIgnoreCase)
    }
    if (-not $approved) { throw 'OutFile must be under RUNNER_TEMP or the system temp directory.' }
    $leaf = [IO.FileInfo]::new($full)
    if ($leaf.Exists -and ($leaf.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'OutFile leaf may not be a reparse point.' }
    $cursor = $leaf.Directory
    if (-not $cursor -or -not $cursor.Exists) { throw 'OutFile parent must already exist.' }
    while ($cursor) { if ($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'OutFile path may not traverse a reparse point.' }; $cursor = $cursor.Parent }

    [IO.File]::WriteAllText($full, $text)
}

function Get-CiInstalledTreeManifest {
    param([Parameter(Mandatory)] [string] $Dir)
    if (-not (Test-Path -LiteralPath $Dir)) { throw "Install directory not found: $Dir" }
    $prefix = [IO.Path]::GetFullPath($Dir).TrimEnd('\') + '\'
    foreach ($file in Get-ChildItem -LiteralPath $Dir -File -Recurse | Sort-Object FullName) {
        $relative = $file.FullName.Substring($prefix.Length)
        [pscustomobject]@{
            Path = $relative.Replace('\', '/')
            Size = [int64] $file.Length
            Sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
}

Write-CiAssertOutput (Get-CiInstalledTreeManifest $InstallDir) $OutFile
