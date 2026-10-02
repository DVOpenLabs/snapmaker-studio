#requires -Version 7.0
# Pester 5. Hermetic unit tests for tools/release/lib/Rewrap.psm1:
#  - no network, no real 7-Zip or NSIS, nothing extracted or compiled is ever executed;
#  - Install-PinnedTools, Invoke-PinnedTool, Assert-ToolVerified and Start-PinnedTool are mocked inside the Rewrap module (an emulated "7z" writes
#    synthetic payload files; the makensis stub runs hooks that mutate the build dir / the private snapshot); the snapshot copy and the
#    build-namespace checks are REAL and run against a synthetic tool tree;
#  - all files live in a private temp dir removed in AfterAll.
# The real compile + 7-Zip listing run only in Rewrap.Integration.Tests.ps1 (env-gated).

BeforeAll {
    Import-Module (Join-Path $PSScriptRoot '..\lib\InstallGuard.psm1') -Force -DisableNameChecking
    Import-Module (Join-Path $PSScriptRoot 'lib\ReleaseTools.psm1') -Force -DisableNameChecking
    Import-Module (Join-Path $PSScriptRoot 'lib\Rewrap.psm1') -Force -DisableNameChecking

    $script:Id = Get-HarnessIdentity
    $script:Acc = $script:Id.Acceptance
    $script:Prod = $script:Id.Production
    $script:TemplateDir = Join-Path $PSScriptRoot 'nsis\template'
    $script:Root = Join-Path ([IO.Path]::GetTempPath()) "ssh-rewrap-test-$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Force -Path $script:Root | Out-Null

    function script:Sha([byte[]]$b) { ([BitConverter]::ToString([Security.Cryptography.SHA256]::HashData($b)).Replace('-', '').ToLowerInvariant()) }
    function script:Bytes([string]$s) { [Text.Encoding]::UTF8.GetBytes($s) }
    function script:New-HarnessRoot { $h = Join-Path $script:Root ("hr-" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $h | Out-Null; $h }

    $script:DllBytes = Bytes 'fake-nsis-tauri-utils'
    $script:MainBytes = Bytes 'fake-main-exe'
    $script:ApiBytes = Bytes 'fake-sidecar-exe'
    $script:UninstBytes = Bytes 'fake-uninstall-exe'
    # A synthetic tool cache (7-Zip folder + NSIS tree) and a lock that pins it; the REAL snapshot code copies and verifies it.
    $script:ToolsSrc = Join-Path $script:Root 'cache-tools'
    $lock0 = @{ sevenZip = @{ version = '9.99' }; nsis = @{ version = '9.99' } }
    $tp0 = Get-ReleaseToolPaths -ToolsDir $script:ToolsSrc -Lock $lock0
    New-Item -ItemType Directory -Force -Path $tp0.SevenZipDir, (Join-Path $tp0.NsisDir 'Bin'), (Join-Path $tp0.NsisDir 'Include'), (Join-Path $tp0.NsisDir 'Plugins\x86-unicode') | Out-Null
    foreach ($n in '7zr.exe', '7za.exe', '7z.exe', '7z.dll') { [IO.File]::WriteAllBytes((Join-Path $tp0.SevenZipDir $n), (Bytes "fake-$n")) }
    [IO.File]::WriteAllBytes($tp0.Makensis, (Bytes 'fake-makensis'))
    [IO.File]::WriteAllBytes((Join-Path $tp0.NsisDir 'Include\MUI2.nsh'), (Bytes 'fake-mui2'))
    [IO.File]::WriteAllBytes((Join-Path $tp0.NsisDir 'Plugins\x86-unicode\System.dll'), (Bytes 'fake-system-plugin'))
    $z0 = Get-DirectoryTreeSha256 -Path $tp0.SevenZipDir; $n0 = Get-DirectoryTreeSha256 -Path $tp0.NsisDir
    $script:Lock = @{
        schemaVersion = 1
        sevenZip = @{ version = '9.99'; treeSha256 = $z0.Sha256; treeFileCount = $z0.FileCount
            binaries = @{ '7z.exe' = (Sha (Bytes 'fake-7z.exe')); '7z.dll' = (Sha (Bytes 'fake-7z.dll')) }
            bootstrapBinaries = @{ '7zr.exe' = (Sha (Bytes 'fake-7zr.exe')); '7za.exe' = (Sha (Bytes 'fake-7za.exe')) } }
        nsis = @{ version = '9.99'; treeSha256 = $n0.Sha256; treeFileCount = $n0.FileCount; makensisSha256 = (Sha (Bytes 'fake-makensis')) }
        tauriUtilsDll = @{ fileName = 'nsis_tauri_utils.dll'; sha256 = (Sha $script:DllBytes) }
    }
    $global:SshRewrapTestToolPaths = $tp0

    # Spec of the emulated installer archive. Entries: @{ Path; Bytes; IsFolder }.
    function script:New-GoodSpec {
        @{
            Entries = @(
                @{ Path = '$PLUGINSDIR\System.dll'; Bytes = (Bytes 'sys') }
                @{ Path = '$PLUGINSDIR\nsis_tauri_utils.dll'; Bytes = $script:DllBytes }
                @{ Path = $script:Prod.MainBinaryName; Bytes = $script:MainBytes }
                @{ Path = $script:Acc.SidecarName; Bytes = $script:ApiBytes }
                @{ Path = 'uninstall.exe'; Bytes = $script:UninstBytes }
            )
            OmitOnExtract = @(); ExtraOnExtract = @(); Junction = $null
        }
    }
    function script:Set-Emulation($spec) { $global:SshRewrapTestEmul = $spec }

    $script:InstallerPath = Join-Path $script:Root 'Snapmaker.Studio_1.2.0_x64-setup.exe'
    [IO.File]::WriteAllBytes($script:InstallerPath, (Bytes 'fake-real-installer'))
    $script:InstallerSha = Sha (Bytes 'fake-real-installer')

    # Install the emulation mocks (bound to the Rewrap module so its internal calls hit them).
    Mock -ModuleName Rewrap Install-PinnedTools {
        if ($global:SshRewrapTestHook) { & $global:SshRewrapTestHook 'tools' @() }
        $global:SshRewrapTestToolPaths
    }
    Mock -ModuleName Rewrap Invoke-PinnedTool {
        if ($Exe -like '*makensis*') { throw 'makensis must go through Assert-ToolVerified / Start-PinnedTool' }
        $spec = $global:SshRewrapTestEmul
        if ($Arguments[0] -eq 'l') {
            if ($global:SshRewrapTestHook) { & $global:SshRewrapTestHook 'list' $Arguments }
            $lines = @('', '7-Zip emulation', '', '--', 'Path = installer', 'Type = Nsis', '', '----------')
            foreach ($e in $spec.Entries) {
                $lines += "Path = $($e.Path)"
                $lines += "Size = $(if ($e.IsFolder) { '' } else { $e.Bytes.Length })"
                if ($e.IsFolder) { $lines += 'Folder = +' }
                $lines += ''
            }
            return [pscustomobject]@{ ExitCode = 0; Output = $lines }
        }
        if ($Arguments[0] -eq 'x') {
            if ($global:SshRewrapTestHook) { & $global:SshRewrapTestHook 'extract' $Arguments }
            $out = ($Arguments | Where-Object { $_ -like '-o*' } | Select-Object -First 1).Substring(2)
            foreach ($e in $spec.Entries) {
                if ($e.IsFolder -or ($spec.OmitOnExtract -contains $e.Path)) { continue }
                $p = Join-Path $out $e.Path
                [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($p))
                [IO.File]::WriteAllBytes($p, $e.Bytes)
            }
            foreach ($x in $spec.ExtraOnExtract) { [IO.File]::WriteAllBytes((Join-Path $out $x), [byte[]](1, 2, 3)) }
            if ($spec.Junction) { New-Item -ItemType Junction -Path (Join-Path $out 'evil-junction') -Target $spec.Junction | Out-Null }
            return [pscustomobject]@{ ExitCode = 0; Output = @() }
        }
        throw "unexpected tool call: $Arguments"
    }
    # makensis is verified and launched through the split pair (Assert-ToolVerified, then Start-PinnedTool).
    Mock -ModuleName Rewrap Assert-ToolVerified { if ($global:SshRewrapTestHook) { & $global:SshRewrapTestHook 'toolverify' @() } }
    Mock -ModuleName Rewrap Start-PinnedTool {
        $global:SshRewrapTestMakensisArgs = $Arguments
        if ($global:SshRewrapTestHook) { & $global:SshRewrapTestHook 'launch' @() }
        if (-not $global:SshRewrapTestMakensisOk) { throw 'makensis stub reached' }
        [pscustomobject]@{ ExitCode = 0; Output = @() }
    }

    function script:Invoke-Extract([hashtable]$Spec, [string]$HarnessRoot, [string]$RunId = ([guid]::NewGuid().ToString('N')), [string]$Sums, [string]$Installer = $script:InstallerPath) {
        Set-Emulation $Spec
        $p = @{ InstallerPath = $Installer; ExpectedSha256 = $script:InstallerSha; SourceVersion = '1.2.0'; HarnessRoot = $HarnessRoot; RunId = $RunId; Lock = $script:Lock }
        if ($Sums) { $p.Sha256SumsPath = $Sums }
        Invoke-InstallerExtraction @p
    }

    # Renders the real (or a mutated) template exactly as New-AcceptanceInstaller does, for the static scan tests.
    function script:Get-RenderValues {
        @{
            compression = 'lzma'; manufacturer = $script:Acc.Manufacturer; product_name = $script:Acc.ProductName; version = '1.2.0'; version_with_build = '1.2.0.0'
            homepage = ''; install_mode = 'currentUser'; license = ''; installer_icon = ''; sidebar_image = ''; header_image = ''; uninstaller_icon = ''
            uninstaller_header_image = ''; main_binary_name = [IO.Path]::GetFileNameWithoutExtension($script:Acc.MainBinaryName)
            main_binary_path = 'X:\b\payload\main.exe'; sidecar_name = $script:Acc.SidecarName; sidecar_path = 'X:\b\payload\api.exe'
            bundle_id = $script:Acc.BundleId; copyright = (InModuleScope Rewrap { $script:Copyright }); out_file = 'X:\b\out.exe'; arch = 'x64'; additional_plugins_path = 'X:\b\plugins'
            allow_downgrades = 'true'; display_language_selector = 'false'; estimated_size = '1'; language = 'English'; language_file = 'English.nsh'
        }
    }
    function script:Get-Scripts([scriptblock]$Mutate) {
        $inst = [IO.File]::ReadAllText((Join-Path $script:TemplateDir 'installer.nsi'))
        if ($Mutate) { $inst = & $Mutate $inst }
        @{
            'installer.final.nsi' = (Expand-InstallerTemplate -TemplateText $inst -Values (Get-RenderValues))
            'utils.nsh' = [IO.File]::ReadAllText((Join-Path $script:TemplateDir 'utils.nsh'))
            'English.nsh' = [IO.File]::ReadAllText((Join-Path $script:TemplateDir 'English.nsh'))
        }
    }
    function script:New-MutatedTemplateDir([scriptblock]$Mutate) {
        $d = Join-Path $script:Root ("tpl-" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path $d | Out-Null
        Copy-Item (Join-Path $script:TemplateDir '*') $d
        $f = Join-Path $d 'installer.nsi'
        [IO.File]::WriteAllText($f, (& $Mutate ([IO.File]::ReadAllText($f))))
        $d
    }
}

AfterAll {
    foreach ($v in 'SshRewrapTestEmul', 'SshRewrapTestHook', 'SshRewrapTestMakensisArgs', 'SshRewrapTestTamper', 'SshRewrapTestCaptured', 'SshRewrapTestMakensisOk', 'SshRewrapTestSequence', 'SshRewrapTestRun', 'SshRewrapTestToolPaths', 'SshRewrapTestSource') { Remove-Variable -Name $v -Scope Global -ErrorAction SilentlyContinue }
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) {
        foreach ($d in Get-ChildItem -LiteralPath $script:Root -Recurse -Force -Directory -ErrorAction SilentlyContinue) {
            if ($d.Attributes -band [IO.FileAttributes]::ReparsePoint) { [IO.Directory]::Delete($d.FullName) }
        }
        Remove-Item -LiteralPath $script:Root -Recurse -Force
    }
}

Describe 'vendored template bundle and pin' {
    It 'the shipped template hashes to PinnedTemplateSha256 in HarnessIdentity.psd1 (any template edit breaks this)' {
        $b = Get-TemplateBundle
        $b.Sha256 | Should -Be $script:Id.Attestation.PinnedTemplateSha256
        $b.Sha256 | Should -Match '^[0-9a-f]{64}$'
    }
    It 'hashes exactly English.nsh, installer.nsi and utils.nsh' {
        (Get-TemplateBundle).Files.Name | Should -Be @('English.nsh', 'installer.nsi', 'utils.nsh')
    }
    It 'refuses a template directory with an extra file' {
        $d = New-MutatedTemplateDir { param($t) $t }
        [IO.File]::WriteAllText((Join-Path $d 'extra.nsh'), '!system "calc"')
        { Get-TemplateBundle -TemplateDir $d } | Should -Throw '*must contain exactly*'
    }
    It 'refuses a template directory with a missing file' {
        $d = New-MutatedTemplateDir { param($t) $t }
        Remove-Item (Join-Path $d 'utils.nsh')
        { Get-TemplateBundle -TemplateDir $d } | Should -Throw '*must contain exactly*'
    }
    It 'Assert-TemplatePinned refuses a different hash and a blank pin' {
        $b = Get-TemplateBundle
        { Assert-TemplatePinned -Bundle $b -ExpectedSha256 ('0' * 64) } | Should -Throw '*does not equal the pinned*'
        { Assert-TemplatePinned -Bundle $b -ExpectedSha256 '' } | Should -Throw '*no valid pinned*'
        { Assert-TemplatePinned -Bundle $b -ExpectedSha256 $b.Sha256 } | Should -Not -Throw
    }
    It 'a one-byte template change changes the bundle hash' {
        $d = New-MutatedTemplateDir { param($t) $t + "`n; x" }
        (Get-TemplateBundle -TemplateDir $d).Sha256 | Should -Not -Be (Get-TemplateBundle).Sha256
    }
    It 'documents its upstream provenance in PROVENANCE.md and keeps template.patch' {
        $prov = Get-Content (Join-Path $PSScriptRoot 'nsis\PROVENANCE.md') -Raw
        $prov | Should -Match '216a33c05235194af3afc49cecccc2416e7651af7514cda35d7b2509a91400f3'
        $prov | Should -Match ([regex]::Escape((Get-TemplateBundle).Sha256))
        (Get-Item (Join-Path $PSScriptRoot 'nsis\template.patch')).Length | Should -BeGreaterThan 1000
    }
}

Describe 'template rendering' {
    It 'renders the real template with the acceptance identity and leaves no placeholder' {
        $s = (Get-Scripts)['installer.final.nsi']
        $s | Should -Not -Match '\{\{'
        $s | Should -Match ([regex]::Escape('!define PRODUCTNAME "Snapmaker Studio Acceptance"'))
        $s | Should -Match ([regex]::Escape('!define MANUFACTURER "SnapmakerStudio-Acceptance"'))
        $s | Should -Match ([regex]::Escape('!define BUNDLEID "com.snapmakerstudio.acceptance"'))
        $s | Should -Match ([regex]::Escape('!define MAINBINARYNAME "snapmaker-studio-acceptance-desktop"'))
    }
    It 'rendered with the REAL copyright string, contains no production identifier outside that copyright text (case-sensitive patterns)' {
        $s = (Get-Scripts)['installer.final.nsi']
        $copyright = InModuleScope Rewrap { $script:Copyright }
        $s.Contains($copyright) | Should -BeTrue                     # the real copyright (which legitimately names the project) is present ...
        $rest = $s.Replace($copyright, '')                           # ... and is the ONLY place a production-looking name may occur
        foreach ($pat in $script:Prod.ForbiddenTargetPatterns) { ($rest -cmatch $pat) | Should -BeFalse -Because $pat }
    }
    It 'refuses an unresolved placeholder' {
        { Expand-InstallerTemplate -TemplateText 'x {{nope}}' -Values @{} } | Should -Throw '*no value*'
    }
    It 'refuses a value NSIS would interpret ($, quote, newline)' {
        $v = Get-RenderValues
        foreach ($bad in '$APPDATA', 'a"b', "a`nb", "a'b") {
            $v.product_name = $bad
            { Expand-InstallerTemplate -TemplateText '!define PRODUCTNAME "{{product_name}}"' -Values $v } | Should -Throw '*NSIS would interpret*'
        }
    }
    It 'compiles out the app-data deletion feature, WebView2 install, WiX migration, app launches and subfolder removal (B1/S6/N1)' {
        $s = (Get-Scripts)['installer.final.nsi']
        foreach ($gone in 'deleteAppData', 'DeleteAppDataCheckbox', '$APPDATA', 'RmDir /r', 'RMDir /r', 'AppStartMenuFolder', 'WebView2', 'NSISdl::download',
            'RunAsUser', 'WixMode', 'OldMainBinaryName', 'HKLM', 'MUI_STARTMENU', 'ExecWait', 'PageReinstall', 'ReinstallPageCheck', 'ExecShell') { $s | Should -Not -BeLike "*$gone*" }
        (Get-Scripts)['English.nsh'] | Should -Not -BeLike '*deleteAppData*'
    }
}

Describe 'static enumeration of delete targets (B1)' {
    It 'the real template enumerates exactly the 8 acceptance-derived targets, post-expansion' {
        $t = Assert-NsisScriptSafe -Scripts (Get-Scripts)
        $got = @($t | ForEach-Object { "$($_.op)|$($_.target)" })
        $want = @(
            'Delete|$INSTDIR\snapmaker-studio-acceptance-desktop.exe'
            'Delete|$INSTDIR\snapstudio-api.exe'
            'Delete|$INSTDIR\uninstall.exe'
            'RmDir|$INSTDIR'
            'Delete|$SMPROGRAMS\Snapmaker Studio Acceptance.lnk'
            'Delete|$DESKTOP\Snapmaker Studio Acceptance.lnk'
            'DeleteRegKey|HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\Snapmaker Studio Acceptance'
            'DeleteRegValue|HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Snapmaker Studio Acceptance'
        )
        $got | Should -Be $want
    }
    It 'every enumerated target is allowed by the guard (Test-DeleteTargetAllowed is the single authority)' {
        foreach ($t in (Assert-NsisScriptSafe -Scripts (Get-Scripts))) { Test-DeleteTargetAllowed -Op $t.op -Target $t.target | Should -BeNullOrEmpty }
    }
    It 'refuses <Name>' -ForEach @(
        @{ Name = 'RmDir /r of the production APPDATA identifier dir'; Line = 'RmDir /r "$APPDATA\com.snapmakerstudio.desktop"' }
        @{ Name = 'unquoted RmDir of the production APPDATA dir'; Line = 'RmDir $APPDATA\com.snapmakerstudio.desktop' }
        @{ Name = 'lower-case rmdir /r of LOCALAPPDATA identifier dir'; Line = 'rmdir /r "$LOCALAPPDATA\com.snapmakerstudio.desktop"' }
        @{ Name = 'RmDir /r of the acceptance identifier under APPDATA (only INSTDIR is allowed)'; Line = 'RmDir /r "$APPDATA\${BUNDLEID}"' }
        @{ Name = 'inline ${IfThen} form'; Line = '${IfThen} $0 = 1 ${|} RmDir /r "$APPDATA\x" ${|}' }
        @{ Name = 'Delete under TEMP'; Line = 'Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"' }
        @{ Name = 'Delete of an INSTDIR child through a variable'; Line = 'Delete "$INSTDIR\$OldMainBinaryName"' }
        @{ Name = 'RmDir of a variable'; Line = 'RmDir $R0' }
        @{ Name = 'Start Menu subfolder removal'; Line = 'RMDir "$SMPROGRAMS\$AppStartMenuFolder"' }
        @{ Name = 'DeleteRegKey of the production publisher key'; Line = 'DeleteRegKey HKCU "Software\DeadlyVirusIn / Snapmaker Studio"' }
        @{ Name = 'DeleteRegKey of the production uninstall key'; Line = 'DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Snapmaker Studio"' }
        @{ Name = 'DeleteRegKey under HKLM'; Line = 'DeleteRegKey HKLM "Software\${MANUFACTURER}"' }
        @{ Name = 'DeleteRegKey with SHCTX'; Line = 'DeleteRegKey SHCTX "${UNINSTKEY}"' }
        @{ Name = 'DeleteRegValue of a foreign Run value'; Line = 'DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Other"' }
        @{ Name = 'a continued line'; Line = "RmDir /r `"`$APPDATA\com.snapmakerstudio.desktop`" `\`n   " }
    ) {
        $mut = { param($t) $t.Replace('  ; Auto close if passive mode or updating', "  $Line`n  ; Auto close if passive mode or updating") }.GetNewClosure()
        { Assert-NsisScriptSafe -Scripts (Get-Scripts $mut) } | Should -Throw '*not safe*'
    }
    It 'refuses a delete hidden in an included script file (utils.nsh is scanned too)' {
        $s = Get-Scripts
        $s['utils.nsh'] += "`nDelete `"`$APPDATA\evil.txt`"`n"
        { Assert-NsisScriptSafe -Scripts $s } | Should -Throw '*not safe*'
    }
    It 'allows a delete of an acceptance-defined key (positive control: the allow-list is not a blanket refusal)' {
        $mut = { param($t) $t.Replace('  ; Auto close if passive mode or updating', "  DeleteRegKey /ifempty HKCU `"`${MANUKEY}`"`n  ; Auto close if passive mode or updating") }
        $t = Assert-NsisScriptSafe -Scripts (Get-Scripts $mut)
        @($t | Where-Object { $_.op -eq 'DeleteRegKey' -and $_.target -eq 'HKCU\Software\SnapmakerStudio-Acceptance' }).Count | Should -Be 1
    }
    It 'refuses <Name> (compile-time exec / launch constructs)' -ForEach @(
        @{ Name = '!system'; Line = '!system "calc.exe"' }
        @{ Name = '!execute'; Line = '!execute "calc.exe"' }
        @{ Name = '!finalize'; Line = '!finalize "calc.exe"' }
        @{ Name = '!packhdr'; Line = '!packhdr "x" "calc.exe"' }
        @{ Name = '!define /redef'; Line = '!define /redef PRODUCTNAME "Snapmaker Studio"' }
        @{ Name = 'a foreign include'; Line = '!include "C:\evil.nsh"' }
        @{ Name = 'ExecShell'; Line = 'ExecShell "open" "calc.exe"' }
        @{ Name = 'Exec'; Line = 'Exec "calc.exe"' }
        @{ Name = 'ExecWait of anything'; Line = 'ExecWait "calc.exe"' }
        @{ Name = 'the upstream ExecWait of the registry-sourced UninstallString (reinstall page)'; Line = 'ExecWait ''$R1'' $0' }
        @{ Name = 'nsExec'; Line = 'nsExec::Exec "calc.exe"' }
        @{ Name = 'RunAsUser (app launch)'; Line = 'nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""' }
    ) {
        $mut = { param($t) $t.Replace('  ; Auto close if passive mode or updating', "  $Line`n  ; Auto close if passive mode or updating") }.GetNewClosure()
        { Assert-NsisScriptSafe -Scripts (Get-Scripts $mut) } | Should -Throw '*not safe*'
    }
    It 'refuses an enumeration that finds nothing' {
        { Assert-NsisScriptSafe -Scripts @{ 'a.nsi' = '; nothing here' } } | Should -Throw '*must not be empty*'
    }
    It 'a mutated template that adds RmDir $APPDATA\com.snapmakerstudio.desktop FAILS THE BUILD even when its hash is pinned, before makensis runs' {
        $hr = New-HarnessRoot
        $ex = Invoke-Extract (New-GoodSpec) $hr 'b1'
        $d = New-MutatedTemplateDir { param($t) $t.Replace('  RMDir "$INSTDIR"', "  RMDir `"`$INSTDIR`"`n  RmDir `$APPDATA\com.snapmakerstudio.desktop") }
        $pin = (Get-TemplateBundle -TemplateDir $d).Sha256   # the mutation is "pinned": only the enumeration can stop it
        { New-AcceptanceInstaller -Extraction $ex -HarnessRoot $hr -TemplateDir $d -ExpectedTemplateSha256 $pin -Lock $script:Lock } | Should -Throw '*not safe*APPDATA*'
        Should -Invoke -ModuleName Rewrap Start-PinnedTool -Times 0
        Test-Path (Join-Path $hr 'attestations') | Should -BeFalse
    }
    It 'the same mutation with the REAL pin fails on the pin (second, independent layer)' {
        $hr = New-HarnessRoot
        $ex = Invoke-Extract (New-GoodSpec) $hr 'b2'
        $d = New-MutatedTemplateDir { param($t) $t + "`nRmDir /r `"`$APPDATA\x`"`n" }
        { New-AcceptanceInstaller -Extraction $ex -HarnessRoot $hr -TemplateDir $d -Lock $script:Lock } | Should -Throw '*does not equal the pinned*'
    }
}

Describe 'archive classification (Assert-ExtractionListing)' {
    It 'accepts the real shape and classifies uninstall.exe and $PLUGINSDIR as machinery' {
        $entries = (New-GoodSpec).Entries | ForEach-Object { [pscustomobject]@{ Path = $_.Path; Size = 1; IsFolder = $false } }
        $c = Assert-ExtractionListing -Entries $entries -Lock $script:Lock
        $c.HasUninstaller | Should -BeTrue
        $c.Payload | Should -Be @($script:Prod.MainBinaryName, $script:Acc.SidecarName)
        $c.Machinery | Should -Contain 'uninstall.exe'
    }
    It 'refuses <Name>' -ForEach @(
        @{ Name = 'path traversal'; Add = @('..\evil.exe'); Remove = @() }
        @{ Name = 'an absolute path'; Add = @('C:\evil.exe'); Remove = @() }
        @{ Name = 'a rooted path'; Add = @('\evil.exe'); Remove = @() }
        @{ Name = 'an alternate data stream'; Add = @('snapstudio-api.exe:evil'); Remove = @() }
        @{ Name = 'a duplicate entry (case-insensitive)'; Add = @('SNAPSTUDIO-API.EXE'); Remove = @() }
        @{ Name = 'an unexpected extra file'; Add = @('evil.exe'); Remove = @() }
        @{ Name = 'a nested extra file'; Add = @('sub\evil.exe'); Remove = @() }
        @{ Name = 'a missing sidecar'; Add = @(); Remove = @('snapstudio-api.exe') }
        @{ Name = 'a missing main binary'; Add = @(); Remove = @('snapmaker-studio-desktop.exe') }
        @{ Name = 'a missing pinned plugin dll'; Add = @(); Remove = @('$PLUGINSDIR\nsis_tauri_utils.dll') }
    ) {
        $paths = @((New-GoodSpec).Entries | ForEach-Object { $_.Path } | Where-Object { $Remove -cnotcontains $_ }) + $Add
        $entries = $paths | ForEach-Object { [pscustomobject]@{ Path = $_; Size = 1; IsFolder = $false } }
        { Assert-ExtractionListing -Entries $entries -Lock $script:Lock } | Should -Throw '*Refused*'
    }
}

Describe 'installer hash verification' {
    It 'refuses a wrong expected sha256' {
        { Assert-InstallerHash -InstallerPath $script:InstallerPath -ExpectedSha256 ('0' * 64) } | Should -Throw '*does not equal the expected*'
    }
    It 'refuses a non-hex expected value' {
        { Assert-InstallerHash -InstallerPath $script:InstallerPath -ExpectedSha256 'ABC' } | Should -Throw '*64 lowercase hex*'
    }
    It 'verifies against SHA256SUMS, and refuses a mismatch, a missing name and a duplicated name' {
        $leaf = [IO.Path]::GetFileName($script:InstallerPath)
        $ok = Join-Path $script:Root 'SUMS-ok'; "$($script:InstallerSha)  $leaf" | Set-Content $ok
        Assert-InstallerHash -InstallerPath $script:InstallerPath -ExpectedSha256 $script:InstallerSha -Sha256SumsPath $ok | Should -Be $script:InstallerSha
        $bad = Join-Path $script:Root 'SUMS-bad'; "$('1' * 64)  $leaf" | Set-Content $bad
        { Assert-InstallerHash -InstallerPath $script:InstallerPath -ExpectedSha256 $script:InstallerSha -Sha256SumsPath $bad } | Should -Throw '*SHA256SUMS lists*'
        $none = Join-Path $script:Root 'SUMS-none'; "$($script:InstallerSha)  other.exe" | Set-Content $none
        { Assert-InstallerHash -InstallerPath $script:InstallerPath -ExpectedSha256 $script:InstallerSha -Sha256SumsPath $none } | Should -Throw '*exactly once*'
        $dup = Join-Path $script:Root 'SUMS-dup'; @("$($script:InstallerSha)  $leaf", "$($script:InstallerSha)  $leaf") | Set-Content $dup
        { Assert-InstallerHash -InstallerPath $script:InstallerPath -ExpectedSha256 $script:InstallerSha -Sha256SumsPath $dup } | Should -Throw '*exactly once*'
    }
}

Describe 'extraction, manifest and stripping (emulated 7-Zip)' {
    It 'builds the per-file manifest and strips uninstall.exe and $PLUGINSDIR (keeping only the pinned dll)' {
        $hr = New-HarnessRoot
        $r = Invoke-Extract (New-GoodSpec) $hr 'ok1'
        $r.ExtractionEmittedUninstaller | Should -BeTrue
        $r.StrippedUninstallerSha256 | Should -Be (Sha $script:UninstBytes)
        $r.Files.Count | Should -Be 2
        ($r.Files | Where-Object { $_.path -eq $script:Prod.MainBinaryName }).sha256 | Should -Be (Sha $script:MainBytes)
        ($r.Files | Where-Object { $_.path -eq $script:Acc.SidecarName }).size | Should -Be $script:ApiBytes.Length
        # nothing but payload + one dll survives, and no uninstall.exe anywhere in the run dir
        @(Get-ChildItem $r.RunDir -Recurse -Force -File | Where-Object { $_.Name -ieq 'uninstall.exe' }).Count | Should -Be 0
        Test-Path (Join-Path $r.RunDir 'raw') | Should -BeFalse
        @(Get-ChildItem $r.PayloadDir -File).Name | Sort-Object | Should -Be @($script:Acc.SidecarName, $script:Prod.MainBinaryName | Sort-Object)
        @(Get-ChildItem (Join-Path $r.RunDir 'plugins') -File).Name | Should -Be @('nsis_tauri_utils.dll')
        (Get-FileHash $r.PluginDll -Algorithm SHA256).Hash.ToLowerInvariant() | Should -Be $script:Lock.tauriUtilsDll.sha256
        Test-Path (Join-Path $r.RunDir 'extraction.json') | Should -BeTrue
    }
    It 'the extraction tree is a separate subtree from the install dir (C1)' {
        $hr = New-HarnessRoot
        $r = Invoke-Extract (New-GoodSpec) $hr 'sep1'
        Test-PathContained -Path $r.RunDir -Root (Join-Path $hr $script:Id.HarnessSubdirs.Install) -AllowEqual | Should -BeFalse
        Test-UnderWorkDir -Path $r.PayloadDir -HarnessRoot $hr | Should -BeTrue
    }
    It 'works without an uninstall.exe in the archive and records that' {
        $hr = New-HarnessRoot; $spec = New-GoodSpec
        $spec.Entries = @($spec.Entries | Where-Object { $_.Path -ne 'uninstall.exe' })
        (Invoke-Extract $spec $hr 'nu1').ExtractionEmittedUninstaller | Should -BeFalse
    }
    It 'refuses a file that was extracted but is not in the listing (extra)' {
        $hr = New-HarnessRoot; $spec = New-GoodSpec; $spec.ExtraOnExtract = @('smuggled.exe')
        { Invoke-Extract $spec $hr 'ex1' } | Should -Throw '*not in the archive listing*'
    }
    It 'refuses a listed file that was not extracted (missing)' {
        $hr = New-HarnessRoot; $spec = New-GoodSpec; $spec.OmitOnExtract = @($script:Acc.SidecarName)
        { Invoke-Extract $spec $hr 'ms1' } | Should -Throw '*was not extracted*'
    }
    It 'refuses a reparse point (junction) in the extracted tree' {
        $hr = New-HarnessRoot; $spec = New-GoodSpec
        $spec.Junction = Join-Path $script:Root ('junction-target-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $spec.Junction | Out-Null
        [IO.File]::WriteAllBytes((Join-Path $spec.Junction 'precious.txt'), (Bytes 'keep me'))
        { Invoke-Extract $spec $hr 'jn1' } | Should -Throw '*reparse point*'     # the ORIGINAL exception is preserved
        Test-Path (Join-Path $hr 'extract\jn1\raw') | Should -BeFalse           # raw is gone ...
        @(Get-ChildItem (Join-Path $hr 'extract') -Recurse -Force -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -ieq 'uninstall.exe' }).Count | Should -Be 0
        Test-Path (Join-Path $spec.Junction 'precious.txt') | Should -BeTrue    # ... and the link was removed, NEVER followed
    }
    It 'refuses a plugin dll whose hash is not the pinned one' {
        $hr = New-HarnessRoot; $spec = New-GoodSpec
        ($spec.Entries | Where-Object { $_.Path -like '*nsis_tauri_utils.dll' }).Bytes = Bytes 'tampered-dll'
        { Invoke-Extract $spec $hr 'dl1' } | Should -Throw '*sha256 mismatch*'
    }
    It 'refuses traversal and duplicates in the listing before extracting anything' {
        $hr = New-HarnessRoot; $spec = New-GoodSpec
        $spec.Entries += @{ Path = '..\evil.exe'; Bytes = (Bytes 'x') }
        { Invoke-Extract $spec $hr 'tr1' } | Should -Throw '*unsafe archive path*'
        Test-Path (Join-Path $hr 'extract\tr1\raw') | Should -BeFalse
        $spec2 = New-GoodSpec; $spec2.Entries += @{ Path = $script:Prod.MainBinaryName.ToUpper(); Bytes = (Bytes 'x') }
        { Invoke-Extract $spec2 $hr 'du1' } | Should -Throw '*duplicate archive entry*'
    }
    It 'refuses a wrong installer hash before touching the tools' {
        $hr = New-HarnessRoot
        { Invoke-InstallerExtraction -InstallerPath $script:InstallerPath -ExpectedSha256 ('0' * 64) -SourceVersion 1.2.0 -HarnessRoot $hr -Lock $script:Lock } | Should -Throw '*does not equal the expected*'
        Should -Invoke -ModuleName Rewrap Install-PinnedTools -Times 0 -ParameterFilter { $true } -Scope It
    }
    It 'refuses an invalid run id and an existing run directory' {
        $hr = New-HarnessRoot
        { Invoke-Extract (New-GoodSpec) $hr '..\x' } | Should -Throw '*invalid run id*'
        Invoke-Extract (New-GoodSpec) $hr 'twice' | Out-Null
        { Invoke-Extract (New-GoodSpec) $hr 'twice' } | Should -Throw '*already exists*'
    }
    It 'refuses a harness-root override outside temp' {
        { Invoke-InstallerExtraction -InstallerPath $script:InstallerPath -ExpectedSha256 $script:InstallerSha -SourceVersion 1.2.0 -HarnessRoot 'C:\Windows\x' -Lock $script:Lock } | Should -Throw '*not an allowed location*'
    }
    It 'refuses a malformed source version' {
        { Invoke-InstallerExtraction -InstallerPath $script:InstallerPath -ExpectedSha256 $script:InstallerSha -SourceVersion '1.2' -HarnessRoot (New-HarnessRoot) -Lock $script:Lock } | Should -Throw '*SourceVersion*'
    }
}

Describe 'source installer binding (copy, hash the copy, read only the copy)' {
    AfterEach { $global:SshRewrapTestHook = $null }
    BeforeAll {
        function script:New-SourceFile { $p = Join-Path $script:Root ("src-" + [guid]::NewGuid().ToString('N') + '.exe'); [IO.File]::WriteAllBytes($p, (Bytes 'fake-real-installer')); $p }
        function script:Get-CopyPath($hr, $runId, $src) { Join-Path $hr "extract\$runId\source\$([IO.Path]::GetFileName($src))" }
    }
    It 'copies the installer into the harness-owned run dir, hashes the COPY, and records it' {
        $hr = New-HarnessRoot; $src = New-SourceFile
        $r = Invoke-Extract (New-GoodSpec) $hr 'cp1' -Installer $src
        $r.InstallerCopy | Should -Be (Get-CopyPath $hr 'cp1' $src)
        (Get-FileHash $r.InstallerCopy -Algorithm SHA256).Hash.ToLowerInvariant() | Should -Be $script:InstallerSha
        $r.InstallerSha256 | Should -Be $script:InstallerSha
        (Get-Content (Join-Path $r.RunDir 'extraction.json') -Raw | ConvertFrom-Json).installerSha256 | Should -Be $script:InstallerSha
    }
    It 'lists and extracts the COPY, and swapping the original path after the copy has no effect' {
        $hr = New-HarnessRoot; $src = New-SourceFile
        $global:SshRewrapTestCaptured = @()
        $global:SshRewrapTestSource = $src
        $global:SshRewrapTestHook = {
            param($stage, $a)
            if ($stage -eq 'tools') { [IO.File]::WriteAllBytes($global:SshRewrapTestSource, [byte[]](9, 9, 9)) }   # attacker swaps the original
            if ($stage -in 'list', 'extract') { $global:SshRewrapTestCaptured += $a[-1] }
        }
        $r = Invoke-Extract (New-GoodSpec) $hr 'cp2' -Installer $src
        $r.InstallerSha256 | Should -Be $script:InstallerSha
        $global:SshRewrapTestCaptured | Should -Be @($r.InstallerCopy, $r.InstallerCopy)
        Remove-Variable SshRewrapTestSource -Scope Global
    }
    It 'detects the copy being swapped between hashing and listing' {
        $hr = New-HarnessRoot; $src = New-SourceFile; $global:SshRewrapTestSource = Get-CopyPath $hr 'cp3' $src
        $global:SshRewrapTestHook = { param($stage, $a) if ($stage -eq 'tools') { [IO.File]::WriteAllBytes($global:SshRewrapTestSource, [byte[]](9, 9, 9)) } }
        { Invoke-Extract (New-GoodSpec) $hr 'cp3' -Installer $src } | Should -Throw '*installer copy (before listing)*sha256 mismatch*'
        Remove-Variable SshRewrapTestSource -Scope Global
    }
    It 'detects the copy being swapped between listing and extraction' {
        $hr = New-HarnessRoot; $src = New-SourceFile; $global:SshRewrapTestSource = Get-CopyPath $hr 'cp4' $src
        $global:SshRewrapTestHook = { param($stage, $a) if ($stage -eq 'list') { [IO.File]::WriteAllBytes($global:SshRewrapTestSource, [byte[]](9, 9, 9)) } }
        { Invoke-Extract (New-GoodSpec) $hr 'cp4' -Installer $src } | Should -Throw '*installer copy (before extraction)*sha256 mismatch*'
        Remove-Variable SshRewrapTestSource -Scope Global
    }
    It 'a copy that differs from the original (corrupted while copying) is refused at the hash of the COPY' {
        $hr = New-HarnessRoot; $src = New-SourceFile
        Mock -ModuleName Rewrap Copy-Item { [IO.File]::WriteAllBytes($Destination, [byte[]](7, 7, 7)) }
        { Invoke-Extract (New-GoodSpec) $hr 'cp6' -Installer $src } | Should -Throw 'Refused: installer sha256 * does not equal the expected*'
    }
    It 'a swapped ORIGINAL (different bytes at the source path) is refused at the copy hash' {
        $hr = New-HarnessRoot; $src = New-SourceFile; [IO.File]::WriteAllBytes($src, [byte[]](1, 2, 3))
        { Invoke-Extract (New-GoodSpec) $hr 'cp5' -Installer $src } | Should -Throw '*does not equal the expected*'
    }
}

Describe 'raw extraction tree (holds the synthesized production uninstall.exe) is removed on EVERY failure path' {
    It 'leaves no uninstall.exe and no raw dir under the harness extract dir after a failure that happens AFTER extraction' {
        $hr = New-HarnessRoot; $spec = New-GoodSpec
        ($spec.Entries | Where-Object { $_.Path -like '*nsis_tauri_utils.dll' }).Bytes = Bytes 'tampered-dll'   # fails after files were extracted
        { Invoke-Extract $spec $hr 'fail1' } | Should -Throw '*sha256 mismatch*'
        @(Get-ChildItem (Join-Path $hr 'extract') -Recurse -Force -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -ieq 'uninstall.exe' }).Count | Should -Be 0
        Test-Path (Join-Path $hr 'extract\fail1\raw') | Should -BeFalse
    }
    It 'a cleanup failure never masks the ORIGINAL exception' {
        $hr = New-HarnessRoot; $spec = New-GoodSpec
        ($spec.Entries | Where-Object { $_.Path -like '*nsis_tauri_utils.dll' }).Bytes = Bytes 'tampered-dll'
        Mock -ModuleName Rewrap Remove-OwnedTree { throw 'cleanup boom' }
        { Invoke-Extract $spec $hr 'fail3' } | Should -Throw '*sha256 mismatch*'
    }
    It 'also after an extracted-vs-listing mismatch' {
        $hr = New-HarnessRoot; $spec = New-GoodSpec; $spec.ExtraOnExtract = @('smuggled.exe')
        { Invoke-Extract $spec $hr 'fail2' } | Should -Throw '*not in the archive listing*'
        @(Get-ChildItem (Join-Path $hr 'extract') -Recurse -Force -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -ieq 'uninstall.exe' }).Count | Should -Be 0
    }
}

Describe 'makensis invocation and input binding' {
    It 'Get-MakensisArguments passes -NOCONFIG first and the script name last' {
        $a = Get-MakensisArguments
        $a[0] | Should -Be '-NOCONFIG'
        $a[-1] | Should -Be 'installer.final.nsi'
        $a | Should -Contain '-V2'
    }
    It 'the real build path hands makensis -NOCONFIG, and restores the environment afterwards' {
        $hr = New-HarnessRoot; $ex = Invoke-Extract (New-GoodSpec) $hr 'mk1'
        $before = @{ A = $env:APPDATA; L = $env:LOCALAPPDATA; N = $env:NSISDIR }
        $global:SshRewrapTestMakensisArgs = $null
        { New-AcceptanceInstaller -Extraction $ex -HarnessRoot $hr -Lock $script:Lock } | Should -Throw '*makensis stub reached*'
        $global:SshRewrapTestMakensisArgs | Should -Contain '-NOCONFIG'
        $global:SshRewrapTestMakensisArgs[0] | Should -Be '-NOCONFIG'
        $env:APPDATA | Should -Be $before.A
        $env:LOCALAPPDATA | Should -Be $before.L
        $env:NSISDIR | Should -Be $before.N
    }
    It 'records the bound inputs (script, includes, plugin dll, payload) in build-inputs.json' {
        $hr = New-HarnessRoot; $ex = Invoke-Extract (New-GoodSpec) $hr 'mk2'
        { New-AcceptanceInstaller -Extraction $ex -HarnessRoot $hr -Lock $script:Lock } | Should -Throw '*makensis stub reached*'
        $j = Get-Content (Join-Path $hr 'rewrap\mk2\build-inputs.json') -Raw | ConvertFrom-Json -AsHashtable
        $keys = @($j.inputs.Keys)
        $keys | Should -Contain 'installer.final.nsi'
        $keys | Should -Contain 'installer.nsi'
        $keys | Should -Contain 'utils.nsh'
        $keys | Should -Contain 'English.nsh'
        $keys | Should -Contain 'plugins\nsis_tauri_utils.dll'
        $keys | Should -Contain ('payload\' + $script:Acc.MainBinaryName)
        @($keys).Count | Should -Be 7
    }
    It 'a script swapped AFTER the scan is refused before makensis runs' {
        $hr = New-HarnessRoot; $ex = Invoke-Extract (New-GoodSpec) $hr 'mk3'
        $global:SshRewrapTestTamper = Join-Path $hr 'rewrap\mk3\build\installer.final.nsi'
        Mock -ModuleName Rewrap Assert-NsisScriptSafe { [IO.File]::AppendAllText($global:SshRewrapTestTamper, "`n; swapped after the scan`n"); , @() }
        { New-AcceptanceInstaller -Extraction $ex -HarnessRoot $hr -Lock $script:Lock } | Should -Throw '*changed since the scan*'
        Should -Invoke -ModuleName Rewrap Start-PinnedTool -Times 0
    }
    It 'the plugin dll swapped AFTER the scan is refused before makensis runs' {
        $hr = New-HarnessRoot; $ex = Invoke-Extract (New-GoodSpec) $hr 'mk4'
        $global:SshRewrapTestTamper = Join-Path $hr 'rewrap\mk4\build\plugins\nsis_tauri_utils.dll'
        Mock -ModuleName Rewrap Assert-NsisScriptSafe { [IO.File]::WriteAllBytes($global:SshRewrapTestTamper, [byte[]](6, 6, 6)); , @() }
        { New-AcceptanceInstaller -Extraction $ex -HarnessRoot $hr -Lock $script:Lock } | Should -Throw '*changed since the scan*'
        Should -Invoke -ModuleName Rewrap Start-PinnedTool -Times 0
    }
}

Describe 'makensis build sequence: verify -> input check -> launch -> post-exit check' {
    BeforeAll {
        function script:New-BuildFixture($id) {
            $hr = New-HarnessRoot; $ex = Invoke-Extract (New-GoodSpec) $hr $id
            @{ Hr = $hr; Ex = $ex; Build = (Join-Path $hr "rewrap\$id\build"); Out = (Join-Path $hr "rewrap\$id\Snapmaker.Studio.Acceptance_1.2.0_x64-setup.exe") }
        }
    }
    AfterEach { $global:SshRewrapTestHook = $null; $global:SshRewrapTestMakensisOk = $false }

    It 'runs Assert-ToolVerified, THEN the input check, THEN the launch, THEN the input check again' {
        $f = New-BuildFixture 'sq1'
        $global:SshRewrapTestSequence = @()
        Mock -ModuleName Rewrap Assert-ToolVerified { $global:SshRewrapTestSequence += 'verify' }
        Mock -ModuleName Rewrap Assert-BuildInputsUnchanged { $global:SshRewrapTestSequence += 'inputs' }
        Mock -ModuleName Rewrap Start-PinnedTool { $global:SshRewrapTestSequence += 'launch'; [pscustomobject]@{ ExitCode = 0; Output = @() } }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*produced no installer*'
        $global:SshRewrapTestSequence | Should -Be @('verify', 'inputs', 'launch', 'inputs')
    }
    It 'a build file changed DURING tool verification is refused before makensis is launched' {
        $f = New-BuildFixture 'sq2'
        $global:SshRewrapTestTamper = Join-Path $f.Build 'utils.nsh'
        $global:SshRewrapTestHook = { param($stage, $a) if ($stage -eq 'toolverify') { [IO.File]::AppendAllText($global:SshRewrapTestTamper, "`n; swapped during verification`n") } }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*changed since the scan*'
        Should -Invoke -ModuleName Rewrap Start-PinnedTool -Times 0
    }
    It 'a build file changed after the final comparison and before makensis exits is detected by the post-exit check, and the output is deleted' {
        $f = New-BuildFixture 'sq3'
        $global:SshRewrapTestMakensisOk = $true
        $global:SshRewrapTestTamper = Join-Path $f.Build 'English.nsh'
        $global:SshRewrapTestSource = $f.Out
        $global:SshRewrapTestHook = {
            param($stage, $a)
            if ($stage -eq 'launch') {
                [IO.File]::WriteAllBytes($global:SshRewrapTestSource, [byte[]](1, 2, 3))                       # makensis "produced" an output
                [IO.File]::AppendAllText($global:SshRewrapTestTamper, "`n; swapped while makensis ran`n")     # ... while an input changed
            }
        }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*changed while makensis ran*'
        Test-Path -LiteralPath $f.Out | Should -BeFalse
        Test-Path -LiteralPath (Join-Path $f.Hr 'attestations\sq3.json') | Should -BeFalse
        Remove-Variable SshRewrapTestSource -Scope Global
    }
    It 'a staged file swapped after the scan and before launch is detected by the final input check' {
        $f = New-BuildFixture 'sq4'
        $global:SshRewrapTestTamper = Join-Path $f.Build 'utils.nsh'
        Mock -ModuleName Rewrap Assert-NsisScriptSafe { [IO.File]::AppendAllText($global:SshRewrapTestTamper, "`n; swapped after the scan`n"); , @() }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*changed since the scan*'
        Should -Invoke -ModuleName Rewrap Start-PinnedTool -Times 0
    }
    It 'a SOURCE template file swapped between pin verification and staging is detected by the staged-copy hash' {
        $f = New-BuildFixture 'sq5'
        $d = Join-Path $script:Root ("tplsrc-" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $d | Out-Null
        Copy-Item (Join-Path $script:TemplateDir '*') $d
        $pin = (Get-TemplateBundle -TemplateDir $d).Sha256
        $global:SshRewrapTestTamper = Join-Path $d 'utils.nsh'
        $global:SshRewrapTestRun = Join-Path $f.Hr 'rewrap\sq5'
        # Get-RunDirectory runs after the source was hashed and pinned and before staging: swap the source there.
        Mock -ModuleName Rewrap Get-RunDirectory { [IO.File]::AppendAllText($global:SshRewrapTestTamper, "`n; swapped between pin and staging`n"); $global:SshRewrapTestRun }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -TemplateDir $d -ExpectedTemplateSha256 $pin -Lock $script:Lock } | Should -Throw '*staged template file utils.nsh*sha256 mismatch*'
        Should -Invoke -ModuleName Rewrap Start-PinnedTool -Times 0
        Remove-Variable SshRewrapTestRun -Scope Global
    }
}

Describe 'forbidden-construct scan: process APIs, DLL registration, plugin dirs, plugin allow-list' {
    It 'accepts the real template (positive control)' {
        Get-NsisForbiddenFindings -Scripts (Get-Scripts) | Should -BeNullOrEmpty
    }
    It 'refuses <Name>' -ForEach @(
        @{ Name = 'System::Call to CreateProcess'; Line = 'System::Call ''kernel32::CreateProcessW(w "calc.exe",i0,i0,i0,i0,i0,i0,i0,i0,i0)''' }
        @{ Name = 'System::Call to ShellExecute'; Line = 'System::Call ''shell32::ShellExecuteW(i0,w "open",w "calc.exe",i0,i0,i1)''' }
        @{ Name = 'System::Call to ShellExecuteEx'; Line = 'System::Call ''shell32::ShellExecuteExW(p r1)''' }
        @{ Name = 'System::Call to WinExec'; Line = 'System::Call ''kernel32::WinExec(m "calc.exe",i1)''' }
        @{ Name = 'System::Call to CreateRemoteThread'; Line = 'System::Call ''kernel32::CreateRemoteThread(p r1,i0,i0,p r2,i0,i0,i0)''' }
        @{ Name = 'System::Call to LoadLibrary'; Line = 'System::Call ''kernel32::LoadLibraryW(w "evil.dll")''' }
        @{ Name = 'CallInstDLL'; Line = 'CallInstDLL "$INSTDIR\evil.dll" func' }
        @{ Name = 'RegDLL'; Line = 'RegDLL "$INSTDIR\evil.dll"' }
        @{ Name = 'UnRegDLL'; Line = 'UnRegDLL "$INSTDIR\evil.dll"' }
        @{ Name = '!addplugindir to another directory'; Line = '!addplugindir "C:\evil"' }
        @{ Name = '!addplugindir with an arch switch'; Line = '!addplugindir /x86-unicode "${ADDITIONALPLUGINSPATH}"' }
        @{ Name = '!addplugindir with two directories'; Line = '!addplugindir "${ADDITIONALPLUGINSPATH}" "C:\evil"' }
        @{ Name = 'a plugin that is not on the allow-list (INetC)'; Line = 'INetC::get "http://x" "$TEMP\x"' }
        @{ Name = 'a plugin that is not on the allow-list (nsDialogs)'; Line = 'nsDialogs::Create 1018' }
        @{ Name = 'a System plugin function that is not on the allow-list'; Line = 'System::Int64Op 1 + 1' }
        @{ Name = 'an unlisted nsis_tauri_utils function'; Line = 'nsis_tauri_utils::SomethingNew "x"' }
    ) {
        $mut = { param($t) $t.Replace('  ; Auto close if passive mode or updating', "  $Line`n  ; Auto close if passive mode or updating") }.GetNewClosure()
        $f = Get-NsisForbiddenFindings -Scripts (Get-Scripts $mut)
        @($f).Count | Should -BeGreaterThan 0
        { Assert-NsisScriptSafe -Scripts (Get-Scripts $mut) } | Should -Throw '*not safe*'
    }
    It 'the exact !addplugindir "${ADDITIONALPLUGINSPATH}" is allowed (positive control)' {
        (Get-Scripts)['installer.final.nsi'] | Should -Match '!addplugindir "\$\{ADDITIONALPLUGINSPATH\}"'
        @(Get-NsisForbiddenFindings -Scripts (Get-Scripts)).Count | Should -Be 0
    }
}

Describe 'consumed set == verified set: exact build namespace, private snapshots, post-exit validation' {
    BeforeAll {
        function script:New-BuildFixture3($id) {
            $hr = New-HarnessRoot; $ex = Invoke-Extract (New-GoodSpec) $hr $id
            $run = Join-Path $hr "rewrap\$id"
            @{ Hr = $hr; Ex = $ex; Run = $run; Build = (Join-Path $run 'build'); Snap = (Join-Path $run 'tools\nsis-9.99'); Out = (Join-Path $run 'Snapmaker.Studio.Acceptance_1.2.0_x64-setup.exe')
               Att = (Join-Path $hr "attestations\$id.json") }
        }
    }
    AfterEach { $global:SshRewrapTestHook = $null; $global:SshRewrapTestMakensisOk = $false }

    It 'a planted build\MUI2.nsh (shadows the stock include) is refused before launch' {
        $f = New-BuildFixture3 'ns1'
        $global:SshRewrapTestTamper = Join-Path $f.Build 'MUI2.nsh'
        $global:SshRewrapTestHook = { param($stage, $a) if ($stage -eq 'toolverify') { [IO.File]::WriteAllText($global:SshRewrapTestTamper, '!system "calc.exe"') } }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*unexpected file in the build directory*MUI2.nsh*'
        Should -Invoke -ModuleName Rewrap Start-PinnedTool -Times 0
    }
    It 'an extra EMPTY directory in the build dir is refused before launch (no -File-only enumeration)' {
        $f = New-BuildFixture3 'ns2'
        $global:SshRewrapTestTamper = Join-Path $f.Build 'Include'
        $global:SshRewrapTestHook = { param($stage, $a) if ($stage -eq 'toolverify') { New-Item -ItemType Directory -Path $global:SshRewrapTestTamper | Out-Null } }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*unexpected directory in the build directory*'
        Should -Invoke -ModuleName Rewrap Start-PinnedTool -Times 0
    }
    It 'a junction in the build dir (invisible to -File enumeration) is refused before launch' {
        $f = New-BuildFixture3 'ns3'
        $target = Join-Path $script:Root ('jx-target-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $target | Out-Null
        $global:SshRewrapTestTamper = Join-Path $f.Build 'Include'; $global:SshRewrapTestSource = $target
        $global:SshRewrapTestHook = { param($stage, $a) if ($stage -eq 'toolverify') { New-Item -ItemType Junction -Path $global:SshRewrapTestTamper -Target $global:SshRewrapTestSource | Out-Null } }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*reparse point in the build directory*'
        Should -Invoke -ModuleName Rewrap Start-PinnedTool -Times 0
        Remove-Variable SshRewrapTestSource -Scope Global
    }
    It 'a junction inside plugins\ is refused before launch' {
        $f = New-BuildFixture3 'ns4'
        $target = Join-Path $script:Root ('jx-target-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $target | Out-Null
        $global:SshRewrapTestTamper = Join-Path $f.Build 'plugins\x86-unicode'; $global:SshRewrapTestSource = $target
        $global:SshRewrapTestHook = { param($stage, $a) if ($stage -eq 'toolverify') { New-Item -ItemType Junction -Path $global:SshRewrapTestTamper -Target $global:SshRewrapTestSource | Out-Null } }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*reparse point in the build directory*'
        Remove-Variable SshRewrapTestSource -Scope Global
    }
    It 'a file planted in private-appdata\ before launch is refused' {
        $f = New-BuildFixture3 'ns5'
        $global:SshRewrapTestTamper = Join-Path $f.Build 'private-appdata\nsisconf.nsh'
        $global:SshRewrapTestHook = { param($stage, $a) if ($stage -eq 'toolverify') { [IO.File]::WriteAllText($global:SshRewrapTestTamper, '!error "hostile"') } }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*private-appdata is not empty*'
        Should -Invoke -ModuleName Rewrap Start-PinnedTool -Times 0
    }
    It 'Get-BuildDirInventory accepts exactly the allow-listed set and refuses any other entry (direct)' {
        $d = Join-Path $script:Root ("inv-" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path (Join-Path $d 'plugins'), (Join-Path $d 'payload'), (Join-Path $d 'private-appdata') | Out-Null
        foreach ($n in 'installer.final.nsi', 'installer.nsi', 'utils.nsh', 'English.nsh', 'plugins\p.dll', 'payload\a.exe') { [IO.File]::WriteAllBytes((Join-Path $d $n), (Bytes $n)) }
        $allow = New-BuildAllowlist -PluginDllName 'p.dll' -PayloadNames @('a.exe')
        (Get-BuildDirInventory -BuildDir $d -Allowlist $allow).Count | Should -Be 6
        (Get-BuildDirInventory -BuildDir $d -Allowlist $allow -Light)['payload\a.exe'] | Should -Match '^size:'
        [IO.File]::WriteAllBytes((Join-Path $d 'payload\b.exe'), (Bytes 'b'))
        { Get-BuildDirInventory -BuildDir $d -Allowlist $allow } | Should -Throw '*unexpected file*payload\b.exe*'
        Remove-Item (Join-Path $d 'payload\b.exe')
        New-Item -ItemType Directory -Path (Join-Path $d 'payload\sub') | Out-Null
        { Get-BuildDirInventory -BuildDir $d -Allowlist $allow } | Should -Throw '*unexpected directory*'
    }
    It 'Assert-BuildInputsUnchanged refuses a modified, added or removed input; private-appdata contents are ignored post-exit' {
        $d = Join-Path $script:Root ("bi-" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path (Join-Path $d 'plugins'), (Join-Path $d 'payload'), (Join-Path $d 'private-appdata') | Out-Null
        foreach ($n in 'installer.final.nsi', 'installer.nsi', 'utils.nsh', 'English.nsh', 'plugins\p.dll', 'payload\a.exe') { [IO.File]::WriteAllBytes((Join-Path $d $n), (Bytes $n)) }
        $allow = New-BuildAllowlist -PluginDllName 'p.dll' -PayloadNames @('a.exe')
        $rec = Get-BuildDirInventory -BuildDir $d -Allowlist $allow
        { Assert-BuildInputsUnchanged -BuildDir $d -Recorded $rec -Allowlist $allow } | Should -Not -Throw
        [IO.File]::WriteAllBytes((Join-Path $d 'private-appdata\x'), (Bytes 'x'))
        { Assert-BuildInputsUnchanged -BuildDir $d -Recorded $rec -Allowlist $allow } | Should -Not -Throw
        { Assert-BuildInputsUnchanged -BuildDir $d -Recorded $rec -Allowlist $allow -PrivateMustBeEmpty } | Should -Throw '*private-appdata is not empty*'
        [IO.File]::WriteAllBytes((Join-Path $d 'utils.nsh'), (Bytes 'EVIL'))
        { Assert-BuildInputsUnchanged -BuildDir $d -Recorded $rec -Allowlist $allow } | Should -Throw '*changed since the scan*'
        [IO.File]::WriteAllBytes((Join-Path $d 'utils.nsh'), (Bytes 'utils.nsh'))
        Remove-Item (Join-Path $d 'plugins\p.dll')
        { Assert-BuildInputsUnchanged -BuildDir $d -Recorded $rec -Allowlist $allow } | Should -Throw '*changed since the scan*'
    }

    It 'a snapshot include (Include\MUI2.nsh) mutated while makensis ran is refused post-exit; output and attestation are deleted' {
        $f = New-BuildFixture3 'ps1'
        $global:SshRewrapTestMakensisOk = $true
        $global:SshRewrapTestTamper = Join-Path $f.Snap 'Include\MUI2.nsh'; $global:SshRewrapTestSource = $f.Out; $global:SshRewrapTestRun = $f.Att
        $global:SshRewrapTestHook = {
            param($stage, $a)
            if ($stage -eq 'launch') {
                [IO.File]::WriteAllBytes($global:SshRewrapTestSource, [byte[]](1, 2, 3))
                New-Item -ItemType Directory -Force -Path (Split-Path $global:SshRewrapTestRun) | Out-Null
                [IO.File]::WriteAllBytes($global:SshRewrapTestRun, [byte[]](1))
                [IO.File]::AppendAllText($global:SshRewrapTestTamper, "`n!system ""calc""`n")
            }
        }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*snapshot changed while makensis ran*'
        Test-Path -LiteralPath $f.Out | Should -BeFalse
        Test-Path -LiteralPath $f.Att | Should -BeFalse
        Remove-Variable SshRewrapTestSource, SshRewrapTestRun -Scope Global
    }
    It 'a snapshot PLUGIN (Plugins\x86-unicode\System.dll) mutated while makensis ran is refused post-exit' {
        $f = New-BuildFixture3 'ps2'
        $global:SshRewrapTestMakensisOk = $true
        $global:SshRewrapTestTamper = Join-Path $f.Snap 'Plugins\x86-unicode\System.dll'; $global:SshRewrapTestSource = $f.Out
        $global:SshRewrapTestHook = { param($stage, $a) if ($stage -eq 'launch') { [IO.File]::WriteAllBytes($global:SshRewrapTestSource, [byte[]](1)); [IO.File]::WriteAllBytes($global:SshRewrapTestTamper, [byte[]](6, 6, 6)) } }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*snapshot changed while makensis ran*'
        Test-Path -LiteralPath $f.Out | Should -BeFalse
        Remove-Variable SshRewrapTestSource -Scope Global
    }
    It 'the snapshot makensis.exe swapped while makensis ran is refused post-exit' {
        $f = New-BuildFixture3 'ps3'
        $global:SshRewrapTestMakensisOk = $true
        $global:SshRewrapTestTamper = Join-Path $f.Snap 'Bin\makensis.exe'; $global:SshRewrapTestSource = $f.Out
        $global:SshRewrapTestHook = { param($stage, $a) if ($stage -eq 'launch') { [IO.File]::WriteAllBytes($global:SshRewrapTestSource, [byte[]](1)); [IO.File]::WriteAllBytes($global:SshRewrapTestTamper, [byte[]](6, 6, 6)) } }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*snapshot changed while makensis ran*'
        Test-Path -LiteralPath $f.Out | Should -BeFalse
        Remove-Variable SshRewrapTestSource -Scope Global
    }
    It 'a FAILING compiler (non-zero exit) still gets the post-exit validation: tampering wins over the compiler error and cleanup happens' {
        $f = New-BuildFixture3 'ps4'
        $global:SshRewrapTestMakensisOk = $false     # the stub throws 'makensis stub reached' after the hook ran
        $global:SshRewrapTestTamper = Join-Path $f.Build 'English.nsh'; $global:SshRewrapTestSource = $f.Out
        $global:SshRewrapTestHook = { param($stage, $a) if ($stage -eq 'launch') { [IO.File]::WriteAllBytes($global:SshRewrapTestSource, [byte[]](1)); [IO.File]::AppendAllText($global:SshRewrapTestTamper, "`n; x`n") } }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*changed while makensis ran*'
        Test-Path -LiteralPath $f.Out | Should -BeFalse
        Remove-Variable SshRewrapTestSource -Scope Global
    }
    It 'a failing compiler with an intact namespace surfaces the ORIGINAL compiler error' {
        $f = New-BuildFixture3 'ps5'
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*makensis stub reached*'
    }
    It 'the build succeeds past the compile while the ORIGINAL tools dir is renamed away during the compile (the snapshot is what runs)' {
        $f = New-BuildFixture3 'ps6'
        $global:SshRewrapTestMakensisOk = $true
        $gone = "$($script:ToolsSrc).gone"
        $global:SshRewrapTestTamper = $script:ToolsSrc; $global:SshRewrapTestSource = $f.Out; $global:SshRewrapTestRun = $gone
        $global:SshRewrapTestHook = { param($stage, $a) if ($stage -eq 'launch') { [IO.File]::WriteAllBytes($global:SshRewrapTestSource, [byte[]](1)); Rename-Item -LiteralPath $global:SshRewrapTestTamper -NewName (Split-Path $global:SshRewrapTestRun -Leaf) } }
        try {
            # no integrity error: the first failure is the later ProductName check on the fake output
            { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*ProductName*'
        } finally { if (Test-Path -LiteralPath $gone) { Rename-Item -LiteralPath $gone -NewName (Split-Path $script:ToolsSrc -Leaf) } }
        Remove-Variable SshRewrapTestSource, SshRewrapTestRun -Scope Global
    }
    It 'a payload COPY that does not hash to the manifest value is refused' {
        $f = New-BuildFixture3 'ps7'
        Mock -ModuleName Rewrap Copy-Item -ParameterFilter { $Destination -like '*\build\payload\*' } { [IO.File]::WriteAllBytes($Destination, [byte[]](7, 7, 7)) }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*payload copy*sha256 mismatch*'
        Should -Invoke -ModuleName Rewrap Start-PinnedTool -Times 0
    }
    It 'a staged template file corrupted DURING the copy is refused (single-read byte check)' {
        $f = New-BuildFixture3 'ps8'
        Mock -ModuleName Rewrap Copy-Item -ParameterFilter { $Destination -like '*\build\utils.nsh' } { [IO.File]::WriteAllBytes($Destination, [byte[]](7, 7, 7)) }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*staged template file utils.nsh*sha256 mismatch*'
        Should -Invoke -ModuleName Rewrap Start-PinnedTool -Times 0
    }
    It 'the scanned text is byte-for-byte the text that was written and hashed (single read)' {
        $f = New-BuildFixture3 'ps9'
        $global:SshRewrapTestSequence = $null
        Mock -ModuleName Rewrap Assert-NsisScriptSafe { $global:SshRewrapTestSequence = $Scripts; throw 'scan sentinel' }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw '*scan sentinel*'
        foreach ($n in 'installer.final.nsi', 'utils.nsh', 'English.nsh') {
            $global:SshRewrapTestSequence[$n] | Should -BeExactly ([IO.File]::ReadAllText((Join-Path $f.Build $n)))
        }
        $global:SshRewrapTestSequence = $null
    }
    It 'the compiler runs from the snapshot path, never from the shared cache' {
        $f = New-BuildFixture3 'ps10'
        $global:SshRewrapTestSequence = @()
        Mock -ModuleName Rewrap Assert-ToolVerified { $global:SshRewrapTestSequence += $Exe }
        Mock -ModuleName Rewrap Start-PinnedTool { $global:SshRewrapTestSequence += $Exe; throw 'stop' }
        { New-AcceptanceInstaller -Extraction $f.Ex -HarnessRoot $f.Hr -Lock $script:Lock } | Should -Throw
        $global:SshRewrapTestSequence | Should -Be @((Join-Path $f.Snap 'Bin\makensis.exe'), (Join-Path $f.Snap 'Bin\makensis.exe'))
        $global:SshRewrapTestSequence[0].StartsWith($script:ToolsSrc, [StringComparison]::OrdinalIgnoreCase) | Should -BeFalse
    }
}

Describe '7-Zip runs from a private and verified snapshot during extraction' {
    AfterEach { $global:SshRewrapTestHook = $null }
    It 'lists and extracts with the SNAPSHOT 7z.exe, not the shared cache' {
        $hr = New-HarnessRoot
        $global:SshRewrapTestSequence = @()
        Mock -ModuleName Rewrap Invoke-PinnedTool {
            $global:SshRewrapTestSequence += $Exe
            if ($Arguments[0] -eq 'l') { return [pscustomobject]@{ ExitCode = 0; Output = @('----------', 'Path = snapmaker-studio-desktop.exe', 'Size = 1', '', 'Path = snapstudio-api.exe', 'Size = 1', '', 'Path = $PLUGINSDIR\nsis_tauri_utils.dll', 'Size = 1', '') } }
            throw 'stop after listing'
        }
        { Invoke-Extract (New-GoodSpec) $hr 'z1' } | Should -Throw '*stop after listing*'
        $snap7z = Join-Path $hr 'extract\z1\tools\7zip-9.99\7z.exe'
        @($global:SshRewrapTestSequence | Select-Object -Unique) | Should -Be @($snap7z)
        Test-Path -LiteralPath $snap7z | Should -BeTrue
        Remove-Variable SshRewrapTestSequence -Scope Global
    }
    It 'a 7z.dll swapped in the shared cache AFTER the snapshot does not affect the run (the snapshot copy is unchanged)' {
        $hr = New-HarnessRoot; $cacheDll = $global:SshRewrapTestToolPaths.SevenZipDll
        $orig = [IO.File]::ReadAllBytes($cacheDll)
        $global:SshRewrapTestSource = $cacheDll
        $global:SshRewrapTestHook = { param($stage, $a) if ($stage -eq 'list') { [IO.File]::WriteAllBytes($global:SshRewrapTestSource, [byte[]](6, 6, 6)) } }
        try {
            $r = Invoke-Extract (New-GoodSpec) $hr 'z2'
            (Get-FileHash (Join-Path $hr 'extract\z2\tools\7zip-9.99\7z.dll') -Algorithm SHA256).Hash.ToLowerInvariant() | Should -Be $script:Lock.sevenZip.binaries['7z.dll']
            $r.Files.Count | Should -Be 2
        } finally { [IO.File]::WriteAllBytes($cacheDll, $orig); Remove-Variable SshRewrapTestSource -Scope Global }
    }
    It 'a cache that no longer matches the lock cannot be snapshotted (the COPY is hashed against the lock)' {
        $hr = New-HarnessRoot; $cacheDll = $global:SshRewrapTestToolPaths.SevenZipDll
        $orig = [IO.File]::ReadAllBytes($cacheDll)
        try {
            [IO.File]::WriteAllBytes($cacheDll, [byte[]](6, 6, 6))
            { Invoke-Extract (New-GoodSpec) $hr 'z3' } | Should -Throw '*7-Zip snapshot hash mismatch*'
        } finally { [IO.File]::WriteAllBytes($cacheDll, $orig) }
    }
}

Describe 'attestation (must pass InstallGuard Test-RewrapAttestation unchanged)' {
    BeforeAll {
        function script:New-ValidAttestation {
            $targets = Assert-NsisScriptSafe -Scripts (Get-Scripts)
            $main = [ordered]@{ path = $script:Acc.MainBinaryName; sha256 = (Sha $script:MainBytes); size = $script:MainBytes.Length; role = 'renamed-main'; sourcePath = $script:Prod.MainBinaryName; sourceSha256 = (Sha $script:MainBytes) }
            $api = [ordered]@{ path = $script:Acc.SidecarName; sha256 = (Sha $script:ApiBytes); size = $script:ApiBytes.Length; role = 'payload'; sourcePath = $script:Acc.SidecarName; sourceSha256 = (Sha $script:ApiBytes) }
            $installerSha = Sha (Bytes 'rewrapped-installer')
            $att = New-RewrapAttestationObject -SourceVersion '1.2.0' -SourceInstallerSha256 $script:InstallerSha -TemplateSha256 (Get-TemplateBundle).Sha256 `
                -InstallerFileName 'x.exe' -InstallerSha256 $installerSha -Files @($main, $api) `
                -Renames @(@{ from = $script:Prod.MainBinaryName; to = $script:Acc.MainBinaryName }) -DeleteTargets $targets -Lock (Get-ToolsLock)
            @{ Att = $att; InstallerSha = $installerSha }
        }
    }
    It 'an attestation built from the real template output validates' {
        $v = New-ValidAttestation
        $r = Test-RewrapAttestation -Attestation $v.Att -InstallerSha256 $v.InstallerSha
        $r.Errors | Should -BeNullOrEmpty
        $r.Valid | Should -BeTrue
    }
    It 'survives a JSON round trip through a file (what the guard reads)' {
        $v = New-ValidAttestation
        $p = Join-Path $script:Root 'att.json'
        $v.Att | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $p -Encoding utf8
        (Test-RewrapAttestation -Attestation $p -InstallerSha256 $v.InstallerSha).Valid | Should -BeTrue
    }
    It 'a tampered attestation FAILS: <Name>' -ForEach @(
        @{ Name = 'production product name'; Mut = { param($a) $a.identity.productName = 'Snapmaker Studio' } }
        @{ Name = 'template hash differs from the pin'; Mut = { param($a) $a.template.sha256 = ('0' * 64) } }
        @{ Name = 'empty deleteTargets'; Mut = { param($a) $a.deleteTargets = @() } }
        @{ Name = 'extra APPDATA delete target'; Mut = { param($a) $a.deleteTargets = @($a.deleteTargets) + [ordered]@{ op = 'RmDir'; target = '$APPDATA\com.snapmakerstudio.desktop' } } }
        @{ Name = 'payload bytes differ from the real installer'; Mut = { param($a) $a.manifest.files[1].sha256 = ('9' * 64) } }
        @{ Name = 'an extra installed file'; Mut = { param($a) $a.manifest.files = @($a.manifest.files) + [ordered]@{ path = 'evil.exe'; sha256 = ('8' * 64); size = 1; role = 'payload'; sourcePath = 'evil.exe'; sourceSha256 = ('8' * 64) } } }
        @{ Name = 'rewrapped installer hash equals the real installer hash'; Mut = { param($a) $a.installer.sha256 = $a.source.installerSha256 } }
        @{ Name = 'uninstall.exe not excluded'; Mut = { param($a) $a.manifest.excluded = @() } }
        @{ Name = 'production main binary kept in the file list'; Mut = { param($a) $a.manifest.files[0].path = 'snapmaker-studio-desktop.exe' } }
    ) {
        $v = New-ValidAttestation
        & $Mut $v.Att
        (Test-RewrapAttestation -Attestation $v.Att -InstallerSha256 $v.InstallerSha).Valid | Should -BeFalse
    }
    It 'does not validate against a different installer sha256' {
        $v = New-ValidAttestation
        (Test-RewrapAttestation -Attestation $v.Att -InstallerSha256 ('7' * 64)).Valid | Should -BeFalse
    }
}

Describe 'repository hygiene of tools/release' {
    BeforeAll {
        $script:Files = Get-ChildItem -LiteralPath $PSScriptRoot -Recurse -File | Where-Object { $_.FullName -notmatch '\\__pycache__\\' -and $_.Extension -notin '.py', '.pyc' }
    }
    It 'contains no absolute local paths, user names or host names' {
        foreach ($f in $script:Files) {
            $text = [IO.File]::ReadAllText($f.FullName)
            $text | Should -Not -Match '[A-Za-z]:\\Users\\(?!Public\\)' -Because $f.Name
            if ($env:USERNAME) { $text | Should -Not -Match ('(?i)\b' + [regex]::Escape($env:USERNAME) + '\b') -Because $f.Name }   # pattern built at run time: no username literal in a tracked file
            $text | Should -Not -Match '(?i)DESKTOP-[A-Z0-9]{5,}' -Because $f.Name
        }
    }
    It 'has no launch primitive other than the single Invoke-PinnedTool call site' {
        $code = $script:Files | Where-Object { $_.Extension -in '.ps1', '.psm1' -and $_.Name -notlike '*.Tests.ps1' }
        foreach ($f in $code) {
            $text = [IO.File]::ReadAllText($f.FullName)
            $text | Should -Not -Match '(?i)Start-Process|Invoke-Expression|\biex\b|Invoke-Item|ProcessStartInfo|\[Diagnostics\.Process\]|cmd(\.exe)?\s+/c|schtasks|rundll32|Invoke-WmiMethod|Win32_Process' -Because $f.Name
        }
        $calls = foreach ($f in $code) { Select-String -LiteralPath $f.FullName -Pattern '^\s*(\$\w+\s*=\s*)?&\s+\$' | ForEach-Object { "$($f.Name): $($_.Line.Trim())" } }
        # one tool launch (& $Exe @Arguments) and the test-only injectable downloader (& $Downloader), nothing else
        @($calls | Where-Object { $_ -notmatch '& \$Exe @Arguments' -and $_ -notmatch '& \$Downloader' }) | Should -BeNullOrEmpty
        @($calls | Where-Object { $_ -match '& \$Exe @Arguments' }).Count | Should -Be 1
    }
}
