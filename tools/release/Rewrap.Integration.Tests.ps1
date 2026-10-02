#requires -Version 7.0
# Pester 5. ENV-GATED integration test: runs the real rewrap (pinned portable 7-Zip + makensis) on a REAL released
# installer. Skipped unless SNAPSTUDIO_REWRAP_INSTALLER points at the installer and a SHA256SUMS file sits next to it
# (or SNAPSTUDIO_REWRAP_SHA256SUMS points at one). Optional: SNAPSTUDIO_RELEASE_TOOLS_DIR (a directory inside TEMP) to
# reuse already-unpacked pinned tools.
#
# Nothing here installs, runs or launches any installer or extracted binary. The only process launches are the pinned
# 7-Zip (list / extract) and makensis (compile), through Invoke-PinnedTool.

BeforeDiscovery {
    $script:Enabled = [bool]$env:SNAPSTUDIO_REWRAP_INSTALLER -and (Test-Path -LiteralPath $env:SNAPSTUDIO_REWRAP_INSTALLER)
}

BeforeAll {
    $script:Enabled = [bool]$env:SNAPSTUDIO_REWRAP_INSTALLER -and (Test-Path -LiteralPath $env:SNAPSTUDIO_REWRAP_INSTALLER)
    if ($script:Enabled) {
        Import-Module (Join-Path $PSScriptRoot '..\lib\InstallGuard.psm1') -Force -DisableNameChecking
        Import-Module (Join-Path $PSScriptRoot 'lib\ReleaseTools.psm1') -Force -DisableNameChecking
        Import-Module (Join-Path $PSScriptRoot 'lib\Rewrap.psm1') -Force -DisableNameChecking
        $script:Id = Get-HarnessIdentity
        $script:Installer = (Resolve-Path -LiteralPath $env:SNAPSTUDIO_REWRAP_INSTALLER).Path
        $sums = if ($env:SNAPSTUDIO_REWRAP_SHA256SUMS) { $env:SNAPSTUDIO_REWRAP_SHA256SUMS } else { Join-Path (Split-Path $script:Installer) 'SHA256SUMS' }
        if (-not (Test-Path -LiteralPath $sums)) { throw 'integration test needs a SHA256SUMS file next to the installer' }
        $leaf = [IO.Path]::GetFileName($script:Installer)
        $line = Get-Content -LiteralPath $sums | Where-Object { $_ -match '^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$' -and $Matches[2] -ceq $leaf } | Select-Object -First 1
        if (-not $line) { throw "SHA256SUMS has no entry for $leaf" }
        $expected = ($line -split '\s+')[0].ToLowerInvariant()
        if ($leaf -notmatch '_(\d+\.\d+\.\d+)_') { throw "cannot derive the version from '$leaf'" }
        $script:Version = $Matches[1]
        $script:Root = Join-Path ([IO.Path]::GetTempPath()) "ssh-rewrap-int-$([guid]::NewGuid().ToString('N'))"
        New-Item -ItemType Directory -Force -Path $script:Root | Out-Null
        $script:Hr = Join-Path $script:Root 'SnapmakerStudio-Harness'
        $tools = if ($env:SNAPSTUDIO_RELEASE_TOOLS_DIR) { $env:SNAPSTUDIO_RELEASE_TOOLS_DIR } else { Join-Path $script:Root 'tools' }
        $script:ToolPaths = Install-PinnedTools -ToolsDir $tools
        $script:Result = Invoke-AcceptanceRewrap -InstallerPath $script:Installer -ExpectedSha256 $expected -Sha256SumsPath $sums `
            -SourceVersion $script:Version -HarnessRoot $script:Hr -ToolsDir $tools -RunId 'integration'
        $script:Extraction = Get-Content -LiteralPath (Join-Path $script:Hr 'extract\integration\extraction.json') -Raw | ConvertFrom-Json -AsHashtable
    }
}

AfterAll {
    if ($script:Enabled -and $script:Root -and (Test-Path -LiteralPath $script:Root)) {
        # remove our own run tree only (the tools dir is inside it unless SNAPSTUDIO_RELEASE_TOOLS_DIR was given)
        Remove-Item -LiteralPath $script:Root -Recurse -Force
    }
}

Describe 'real rewrap of the released installer' -Skip:(-not $script:Enabled) {
    It 'the compiled installer carries the acceptance ProductName' {
        (Get-Item -LiteralPath $script:Result.InstallerPath).VersionInfo.ProductName | Should -BeExactly $script:Id.Acceptance.ProductName
        $script:Result.ProductName | Should -BeExactly 'Snapmaker Studio Acceptance'
    }
    It 'lists the renamed main binary and the sidecar, and not the production main binary' {
        $list = Get-ArchiveListing -SevenZip $script:ToolPaths.SevenZip -ArchivePath $script:Result.InstallerPath
        $names = @($list | ForEach-Object { $_.Path })
        $names | Should -Contain $script:Id.Acceptance.MainBinaryName
        $names | Should -Contain $script:Id.Acceptance.SidecarName
        $names | Should -Not -Contain $script:Id.Production.MainBinaryName
    }
    It 'no uninstall.exe from the source installer is carried into the build or work trees' {
        $script:Extraction.extractionEmittedUninstaller | Should -BeTrue    # 7-Zip DID synthesize one (C1) ...
        $src = $script:Extraction.strippedUninstallerSha256
        $src | Should -Match '^[0-9a-f]{64}$'
        $all = Get-ChildItem -LiteralPath $script:Hr -Recurse -Force -File -ErrorAction SilentlyContinue
        # ... it was stripped: no uninstall.exe anywhere under extract\ or the build dir, and no file with its hash
        @($all | Where-Object { $_.FullName -match '\\(extract|rewrap)\\' -and $_.Name -ieq 'uninstall.exe' }).Count | Should -Be 0
        @($all | Where-Object { (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -eq $src }).Count | Should -Be 0
    }
    It 'the compiled installer contains byte-identical payload (renamed main) and a DIFFERENT uninstaller' {
        $out = Join-Path $script:Root 'verify-extract'
        [void](Invoke-PinnedTool -Exe $script:ToolPaths.SevenZip -Arguments @('x', '-y', '-bd', '-aoa', "-o$out", $script:Result.InstallerPath))
        $acc = $script:Id.Acceptance
        foreach ($f in $script:Extraction.files) {
            $name = if ($f.path -ceq $script:Id.Production.MainBinaryName) { $acc.MainBinaryName } else { $f.path }
            (Get-FileHash (Join-Path $out $name) -Algorithm SHA256).Hash.ToLowerInvariant() | Should -Be $f.sha256
        }
        $newUninst = (Get-FileHash (Join-Path $out 'uninstall.exe') -Algorithm SHA256).Hash.ToLowerInvariant()
        $newUninst | Should -Not -Be $script:Extraction.strippedUninstallerSha256
        Remove-Item -LiteralPath $out -Recurse -Force   # never executed; our own scratch tree
    }
    It 'the attestation is valid per InstallGuard, binds this installer hash, and a tampered copy is refused' {
        $r = Test-RewrapAttestation -Attestation $script:Result.AttestationPath -InstallerSha256 $script:Result.InstallerSha256
        $r.Errors | Should -BeNullOrEmpty
        $r.Valid | Should -BeTrue
        $r.Attestation.template.sha256 | Should -Be $script:Id.Attestation.PinnedTemplateSha256
        @($r.Attestation.deleteTargets).Count | Should -BeGreaterThan 0
        $t = Get-Content -LiteralPath $script:Result.AttestationPath -Raw | ConvertFrom-Json -AsHashtable
        $t.deleteTargets = @($t.deleteTargets) + @{ op = 'RmDir'; target = '$APPDATA\com.snapmakerstudio.desktop' }
        (Test-RewrapAttestation -Attestation $t -InstallerSha256 $script:Result.InstallerSha256).Valid | Should -BeFalse
    }
    It 'the guard accepts the rewrapped installer (staged copy, identity, attestation) without running it' {
        $g = Assert-InstallerAllowed -Path $script:Result.InstallerPath -AttestationPath $script:Result.AttestationPath -HarnessRoot $script:Hr
        $g.Sha256 | Should -Be $script:Result.InstallerSha256
        $g.ProductName | Should -BeExactly $script:Id.Acceptance.ProductName
        Test-PathContained -Path $g.Path -Root (Join-Path $script:Hr 'staging') | Should -BeTrue
    }
    It 'REAL compile from the private snapshot succeeds while the ORIGINAL NSIS tree is unavailable and the ambient config is hostile' {
        $lock = Get-ToolsLock
        # own copy of the cache, so the shared tools dir is never touched
        $srcRoot = Join-Path $script:Root 'tools-src'
        Copy-Item -LiteralPath $script:ToolPaths.Root -Destination $srcRoot -Recurse
        $srcPaths = Get-ReleaseToolPaths -ToolsDir $srcRoot -Lock $lock
        $snap = New-ToolSnapshot -Source $srcPaths -Destination (Join-Path $script:Root 'snap-real') -Lock $lock -Kinds @('nsis')
        Rename-Item -LiteralPath $srcRoot -NewName 'tools-src.gone'                       # the original tree is now unavailable

        $b = Join-Path $script:Root 'tiny-build'; $priv = Join-Path $b 'private-appdata'
        New-Item -ItemType Directory -Force -Path $b, $priv | Out-Null
        [IO.File]::WriteAllText((Join-Path $b 'tiny.nsi'), "Unicode true`n!include MUI2.nsh`nOutFile `"tiny.exe`"`nSection`n  System::Call 'kernel32::GetTickCount()i.r0'`nSectionEnd`n")
        # hostile ambient config: a user nsisconf.nsh that fails the compile if it is loaded, and NSISDIR / NSISCONFDIR pointing at a bad dir
        $hostile = Join-Path $script:Root 'hostile-appdata'; $bad = Join-Path $script:Root 'bad-nsis-dir'
        New-Item -ItemType Directory -Force -Path $hostile, $bad | Out-Null
        [IO.File]::WriteAllText((Join-Path $hostile 'nsisconf.nsh'), '!error "HOSTILE CONFIG LOADED"')
        $e0 = @{ A = $env:APPDATA; L = $env:LOCALAPPDATA; N = $env:NSISDIR; C = $env:NSISCONFDIR }
        try {
            $env:APPDATA = $hostile; $env:LOCALAPPDATA = $hostile; $env:NSISDIR = $bad; $env:NSISCONFDIR = $bad
            # negative control: WITHOUT -NOCONFIG and with the hostile ambient config the same snapshot compiler must fail (the hostility is real)
            $threw = $false
            try { [void](Start-PinnedTool -Exe $snap.Makensis -WorkingDirectory $b -Arguments @('-V2', 'tiny.nsi')) } catch { $threw = $true }
            $threw | Should -BeTrue -Because 'the hostile nsisconf.nsh / NSISDIR must break a compile that does not use the production isolation'
            Remove-Item -LiteralPath (Join-Path $b 'tiny.exe') -ErrorAction SilentlyContinue
            # production isolation (-NOCONFIG, scrubbed env, private APPDATA, snapshot exe): succeeds
            $r = Invoke-IsolatedMakensis -Makensis $snap.Makensis -BuildDir $b -PrivateDir $priv -ScriptName 'tiny.nsi'
            $r.ExitCode | Should -Be 0
        } finally { $env:APPDATA = $e0.A; $env:LOCALAPPDATA = $e0.L; $env:NSISDIR = $e0.N; $env:NSISCONFDIR = $e0.C }
        Test-Path -LiteralPath (Join-Path $b 'tiny.exe') | Should -BeTrue
        # includes, stubs and plugins came from the copy: the snapshot is intact and the original is gone
        Assert-TreePinned -Path $snap.NsisDir -ExpectedSha256 $lock.nsis.treeSha256 -ExpectedCount ([int]$lock.nsis.treeFileCount) -What 'NSIS snapshot'
        Test-Path -LiteralPath $srcPaths.NsisDir | Should -BeFalse
    }
}
