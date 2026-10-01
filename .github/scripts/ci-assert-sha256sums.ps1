[CmdletBinding()]
param(
    [string] $Tag,
    [string] $InstallerPath,
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

$ErrorActionPreference = 'Stop'

function Compare-CiSha256Sums {
    param(
        [Parameter(Mandatory)] [string] $SumsContent,
        [Parameter(Mandatory)] [string] $FilePath
    )
    $name = [IO.Path]::GetFileName($FilePath)
    $line = $SumsContent -split "`r?`n" |
        Where-Object { $_ -match "(?i)\s\*?$([regex]::Escape($name))\s*$" } |
        Select-Object -First 1
    if (-not $line) { throw "SHA256SUMS has no entry for $name" }
    $expected = ([regex]::Match($line, '(?i)^[0-9a-f]{64}')).Value.ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $FilePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw "SHA256 mismatch for ${name}: $actual != $expected" }
    [pscustomobject] @{ Installer = $name; Sha256 = $actual }
}

if ($MyInvocation.InvocationName -ne '.') {
    if ([string]::IsNullOrWhiteSpace($Tag) -or [string]::IsNullOrWhiteSpace($InstallerPath)) {
        throw 'Tag and InstallerPath are required.'
    }
    if ($Tag -notmatch '^v?\d+\.\d+\.\d+([-.][0-9A-Za-z.]+)?$') { throw "Invalid release tag: $Tag" }
    $uri = "https://github.com/DVOpenLabs/snapmaker-studio/releases/download/$Tag/SHA256SUMS"
    $request = [Net.WebRequest]::Create($uri)
    $response = $request.GetResponse()
    $reader = [IO.StreamReader]::new($response.GetResponseStream())
    $sumsContent = $reader.ReadToEnd()
    $reader.Dispose()
    $response.Dispose()
    $result = Compare-CiSha256Sums -SumsContent $sumsContent -FilePath $InstallerPath
    $name = $result.Installer
    $actual = $result.Sha256
    Write-CiAssertOutput ([pscustomobject] @{ Tag = $Tag; Installer = $name; Sha256 = $actual; Source = $uri }) $OutFile
}
