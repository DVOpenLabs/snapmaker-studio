#requires -Version 7.0
# Pester 5. No installer is ever run; no real registry key is written outside the scratch hive
# HKCU:\Software\SnapmakerStudioHarnessTest\<guid>; all files live in a private temp dir.
# Product-name probing is mocked (Get-ExeProductName) so no installer binaries are needed.

BeforeAll {
    $script:ModulePath = Join-Path $PSScriptRoot 'InstallGuard.psm1'
    Import-Module $script:ModulePath -Force -DisableNameChecking
    Import-Module (Join-Path $PSScriptRoot '..\harness\HarnessJournal.psm1') -Force -DisableNameChecking
    # Task B fills PinnedTemplateSha256 in HarnessIdentity.psd1; tests pin a synthetic value inside the module scope.
    $script:Pin = ('c' * 64)
    InModuleScope InstallGuard -Parameters @{ Pin = $script:Pin } { $script:Identity.Attestation.PinnedTemplateSha256 = $Pin }
    $script:Id = Get-HarnessIdentity
    $script:Acc = $script:Id.Acceptance
    $script:Prod = $script:Id.Production

    function script:New-Sandbox {
        $guid = [guid]::NewGuid().ToString('N')
        $dir = Join-Path ([IO.Path]::GetTempPath()) "ssh-guard-test-$guid"
        $hr = Join-Path $dir 'SnapmakerStudio-Harness'
        New-Item -ItemType Directory -Force -Path $hr | Out-Null
        [pscustomobject]@{ Dir = $dir; Harness = $hr; RegRoot = "HKCU:\Software\SnapmakerStudioHarnessTest\$guid"; Guid = $guid }
    }
    function script:Clear-Junctions([string]$dir) {
        if (-not (Test-Path -LiteralPath $dir)) { return }
        foreach ($d in [IO.Directory]::EnumerateDirectories($dir)) {
            if ([IO.File]::GetAttributes($d) -band [IO.FileAttributes]::ReparsePoint) { [IO.Directory]::Delete($d) } else { Clear-Junctions $d }
        }
    }
    function script:Remove-Sandbox($s) {
        Clear-Junctions $s.Dir
        if ($s.RegRoot -like 'HKCU:\Software\SnapmakerStudioHarnessTest\*' -and (Test-Path $s.RegRoot)) { Remove-Item $s.RegRoot -Recurse -Force }
        if ($s.Dir -like "$([IO.Path]::GetTempPath())ssh-guard-test-*" -and (Test-Path $s.Dir)) { Remove-Item $s.Dir -Recurse -Force }
        $parent = 'HKCU:\Software\SnapmakerStudioHarnessTest'
        if ((Test-Path $parent) -and @(Get-ChildItem $parent).Count -eq 0) { Remove-Item $parent -Force }
    }
    function script:New-Attestation {
        param([string]$InstallerSha, [hashtable]$Patch = @{})
        $sha = ('a' * 64)
        $att = [ordered]@{
            kind = $script:Id.Attestation.Kind; schemaVersion = 1; createdUtc = '2026-09-30T00:00:00Z'
            identity = [ordered]@{ productName = $script:Acc.ProductName; manufacturer = $script:Acc.Manufacturer; bundleId = $script:Acc.BundleId; mainBinaryName = $script:Acc.MainBinaryName }
            source = [ordered]@{ version = '1.2.0'; installerSha256 = ('b' * 64) }
            template = [ordered]@{ name = 'tauri-bundler-nsis'; version = '2.11.3'; sha256 = ('c' * 64) }
            installer = [ordered]@{ fileName = 'rewrapped.exe'; sha256 = $InstallerSha }
            manifest = [ordered]@{
                files = @(
                    [ordered]@{ path = $script:Acc.MainBinaryName; sha256 = $sha; size = 10; role = 'renamed-main'; sourcePath = $script:Prod.MainBinaryName; sourceSha256 = $sha }
                    [ordered]@{ path = 'snapstudio-api.exe'; sha256 = ('d' * 64); size = 11; role = 'payload'; sourcePath = 'snapstudio-api.exe'; sourceSha256 = ('d' * 64) }
                )
                renames = @([ordered]@{ from = $script:Prod.MainBinaryName; to = $script:Acc.MainBinaryName })
                excluded = @('uninstall.exe')
            }
            deleteTargets = @(
                [ordered]@{ op = 'Delete'; target = '$INSTDIR\uninstall.exe' }
                [ordered]@{ op = 'DeleteRegKey'; target = 'Software\SnapmakerStudio-Acceptance\Snapmaker Studio Acceptance' }
                [ordered]@{ op = 'Delete'; target = '$SMPROGRAMS\Snapmaker Studio Acceptance.lnk' }
            )
        }
        foreach ($k in $Patch.Keys) { $att[$k] = $Patch[$k] }
        $att
    }
    function script:Save-Attestation($s, $att) {
        $d = Join-Path $s.Harness 'attestations'
        New-Item -ItemType Directory -Force -Path $d | Out-Null
        $p = Join-Path $d "att-$([guid]::NewGuid().ToString('N')).json"
        $att | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $p -Encoding utf8
        $p
    }
    function script:New-FakeInstaller($s) {
        $p = Join-Path $s.Dir "fake-$([guid]::NewGuid().ToString('N')).exe"
        [IO.File]::WriteAllBytes($p, [Text.Encoding]::UTF8.GetBytes("not a real installer $([guid]::NewGuid())"))
        $p
    }
}

Describe 'Test-PathContained' {
    It 'accepts a child' { Test-PathContained -Path 'C:\a\Harness\x\y' -Root 'C:\a\Harness' | Should -BeTrue }
    It 'rejects the root itself unless AllowEqual' {
        Test-PathContained -Path 'C:\a\Harness' -Root 'C:\a\Harness' | Should -BeFalse
        Test-PathContained -Path 'C:\a\Harness\' -Root 'C:\a\Harness' -AllowEqual | Should -BeTrue
    }
    It 'rejects the prefix-neighbour attack (SnapmakerStudio vs SnapmakerStudio-Harness)' {
        Test-PathContained -Path 'C:\L\SnapmakerStudio-Harness\x' -Root 'C:\L\SnapmakerStudio' | Should -BeFalse
        Test-PathContained -Path 'C:\L\SnapmakerStudio\x' -Root 'C:\L\SnapmakerStudio-Harness' | Should -BeFalse
        Test-PathContained -Path 'C:\L\SnapmakerStudio-HarnessEvil\x' -Root 'C:\L\SnapmakerStudio-Harness' | Should -BeFalse
    }
    It 'rejects dot-dot traversal out of the root' { Test-PathContained -Path 'C:\a\Harness\..\Other\x' -Root 'C:\a\Harness' | Should -BeFalse }
    It 'is case-insensitive' { Test-PathContained -Path 'c:\A\HARNESS\x' -Root 'C:\a\Harness' | Should -BeTrue }
    It 'rejects UNC and alternate data streams' {
        Test-PathContained -Path '\\host\share\x' -Root 'C:\a' | Should -BeFalse
        Test-PathContained -Path 'C:\a\Harness\x:stream' -Root 'C:\a\Harness' | Should -BeFalse
    }
}

Describe 'Test-ContainsReparsePoint / Assert-HarnessOwnedPath' {
    BeforeEach { $script:sb = New-Sandbox }
    AfterEach { Remove-Sandbox $script:sb }
    It 'rejects a path that goes through a junction' {
        $outside = Join-Path $script:sb.Dir 'outside'; New-Item -ItemType Directory -Path $outside | Out-Null
        $j = Join-Path $script:sb.Harness 'install'
        New-Item -ItemType Junction -Path $j -Target $outside | Out-Null
        $p = Join-Path $j 'app'
        Test-ContainsReparsePoint -Path $p -Root $script:sb.Harness | Should -BeTrue
        { Assert-HarnessOwnedPath -Path $p -Root $script:sb.Harness } | Should -Throw '*reparse*'
    }
    It 'accepts a plain directory chain' {
        $p = Join-Path $script:sb.Harness 'install\app'; New-Item -ItemType Directory -Path $p | Out-Null
        Test-ContainsReparsePoint -Path $p -Root $script:sb.Harness | Should -BeFalse
    }
}

Describe 'Test-RewrapAttestation' {
    It 'accepts a well-formed attestation' {
        $r = Test-RewrapAttestation -Attestation (New-Attestation -InstallerSha ('e' * 64) | ConvertTo-Json -Depth 12 | ConvertFrom-Json -AsHashtable)
        $r.Errors | Should -BeNullOrEmpty
        $r.Valid | Should -BeTrue
    }
    It 'rejects production identity fields' {
        $a = New-Attestation -InstallerSha ('e' * 64)
        $a.identity.productName = $script:Prod.ProductName
        (Test-RewrapAttestation -Attestation $a).Valid | Should -BeFalse
    }
    It 'rejects a manifest that still carries the production main binary' {
        $a = New-Attestation -InstallerSha ('e' * 64)
        $a.manifest.files += [ordered]@{ path = $script:Prod.MainBinaryName; sha256 = ('a' * 64); size = 1; role = 'payload'; sourcePath = 'x'; sourceSha256 = ('a' * 64) }
        (Test-RewrapAttestation -Attestation $a).Errors -join ';' | Should -Match 'production main binary'
    }
    It 'rejects uninstall.exe in the manifest, traversal paths, and altered payload bytes' {
        $a = New-Attestation -InstallerSha ('e' * 64)
        $a.manifest.files += [ordered]@{ path = 'uninstall.exe'; sha256 = ('a' * 64); size = 1; role = 'payload'; sourcePath = 'u'; sourceSha256 = ('a' * 64) }
        $a.manifest.files += [ordered]@{ path = '..\evil.dll'; sha256 = ('a' * 64); size = 1; role = 'payload'; sourcePath = 'x'; sourceSha256 = ('a' * 64) }
        $a.manifest.files[1].sourceSha256 = ('9' * 64)
        $e = (Test-RewrapAttestation -Attestation $a).Errors -join ';'
        $e | Should -Match 'uninstall.exe'
        $e | Should -Match 'unsafe'
        $e | Should -Match 'differ'
    }
    It 'rejects a delete target derived from a production identifier' {
        foreach ($t in '$APPDATA\com.snapmakerstudio.desktop', '$LOCALAPPDATA\SnapmakerStudio', 'Software\DeadlyVirusIn / Snapmaker Studio\Snapmaker Studio', '$INSTDIR\snapmaker-studio-desktop.exe', 'Software\Microsoft\Windows\CurrentVersion\Uninstall\Snapmaker Studio') {
            $a = New-Attestation -InstallerSha ('e' * 64)
            $a.deleteTargets += [ordered]@{ op = 'RmDir'; target = $t }
            (Test-RewrapAttestation -Attestation $a).Valid | Should -BeFalse -Because $t
        }
    }
    # B1 probes: each is applied alone to an otherwise VALID attestation, so removing the matching check makes the test fail.
    It 'B1: accepts the baseline (guards the probes below against vacuous failure)' {
        (Test-RewrapAttestation -Attestation (New-Attestation -InstallerSha ('e' * 64))).Valid | Should -BeTrue
    }
    It 'B1: rejects an empty deleteTargets enumeration' {
        $a = New-Attestation -InstallerSha ('e' * 64); $a.deleteTargets = @()
        (Test-RewrapAttestation -Attestation $a).Errors -join ';' | Should -Match 'missing or empty'
    }
    It 'B1: rejects <op> <target> (positive allowlist)' -ForEach @(
        @{ op = 'RmDir'; target = '$APPDATA\Unrelated-App-Data' }
        @{ op = 'RmDir'; target = '$APPDATA\${BUNDLEID}' }
        @{ op = 'RmDir'; target = '$INSTDIR\$0\x' }
        @{ op = 'DeleteRegKey'; target = 'Software\Microsoft\Windows\CurrentVersion\Uninstall' }
        @{ op = 'DeleteRegKey'; target = 'Software' }
        @{ op = 'DeleteRegValue'; target = 'Software\Microsoft\Windows\CurrentVersion\Run' }
        @{ op = 'RmDir'; target = '$LOCALAPPDATA' }
        @{ op = 'RmDir'; target = '$INSTDIR\..\..' }
        @{ op = 'RmDir'; target = 'C:\Windows' }
        @{ op = 'Delete'; target = '$DESKTOP\Other App.lnk' }
    ) {
        $a = New-Attestation -InstallerSha ('e' * 64)
        $a.deleteTargets += [ordered]@{ op = $op; target = $target }
        $r = Test-RewrapAttestation -Attestation $a
        $r.Valid | Should -BeFalse
        $r.Errors -join ';' | Should -Match 'deleteTargets entry refused'
    }
    It 'B1: allows exactly the acceptance-derived targets' -ForEach @(
        @{ op = 'RmDir'; target = '$INSTDIR' }
        @{ op = 'RmDir'; target = '$INSTDIR\resources' }
        @{ op = 'DeleteRegKey'; target = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\Snapmaker Studio Acceptance' }
        @{ op = 'DeleteRegKey'; target = 'HKCU\Software\SnapmakerStudio-Acceptance' }
        @{ op = 'DeleteRegValue'; target = 'Software\Microsoft\Windows\CurrentVersion\Run\Snapmaker Studio Acceptance' }
        @{ op = 'Delete'; target = '$DESKTOP\Snapmaker Studio Acceptance.lnk' }
    ) {
        $a = New-Attestation -InstallerSha ('e' * 64)
        $a.deleteTargets += [ordered]@{ op = $op; target = $target }
        (Test-RewrapAttestation -Attestation $a).Valid | Should -BeTrue
    }
    It 'M8: rejects an extra file (evil.dll) and a missing sidecar in the installed file set' {
        $a = New-Attestation -InstallerSha ('e' * 64)
        $a.manifest.files += [ordered]@{ path = 'evil.dll'; sha256 = ('a' * 64); size = 1; role = 'payload'; sourcePath = 'evil.dll'; sourceSha256 = ('a' * 64) }
        (Test-RewrapAttestation -Attestation $a).Errors -join ';' | Should -Match 'unexpected file in installed file set: evil.dll'
        $b = New-Attestation -InstallerSha ('e' * 64)
        $b.manifest.files = @($b.manifest.files[0])
        (Test-RewrapAttestation -Attestation $b).Errors -join ';' | Should -Match 'exactly one snapstudio-api.exe'
    }
    It 'rejects a template hash that differs from the pinned value, and fails closed when no pin is configured' {
        $a = New-Attestation -InstallerSha ('e' * 64); $a.template.sha256 = ('9' * 64)
        (Test-RewrapAttestation -Attestation $a).Errors -join ';' | Should -Match 'pinned template hash'
        InModuleScope InstallGuard { $script:Identity.Attestation.PinnedTemplateSha256 = '' }
        try { (Test-RewrapAttestation -Attestation (New-Attestation -InstallerSha ('e' * 64))).Errors -join ';' | Should -Match 'no pinned template' }
        finally { InModuleScope InstallGuard -Parameters @{ Pin = $script:Pin } { $script:Identity.Attestation.PinnedTemplateSha256 = $Pin } }
    }
    It 'rejects a missing deleteTargets enumeration and an installer hash equal to the real installer' {
        $a = New-Attestation -InstallerSha ('b' * 64)
        $a.Remove('deleteTargets')
        $e = (Test-RewrapAttestation -Attestation $a).Errors -join ';'
        $e | Should -Match 'deleteTargets'
        $e | Should -Match 'not rewrapped'
    }
    It 'rejects a hash that does not match the installer under test, and garbage input' {
        $a = New-Attestation -InstallerSha ('e' * 64)
        (Test-RewrapAttestation -Attestation $a -InstallerSha256 ('f' * 64)).Valid | Should -BeFalse
        (Test-RewrapAttestation -Attestation 'C:\does\not\exist.json').Valid | Should -BeFalse
        (Test-RewrapAttestation -Attestation @{}).Valid | Should -BeFalse
    }
}

Describe 'Assert-InstallerAllowed' {
    BeforeEach { $script:sb = New-Sandbox }
    AfterEach { Remove-Sandbox $script:sb }

    It 'allows an acceptance-identity installer whose hash is attested, and returns a harness-owned copy' {
        Mock -ModuleName InstallGuard Get-ExeProductName { 'Snapmaker Studio Acceptance' }
        $inst = New-FakeInstaller $script:sb
        $sha = (Get-FileHash $inst -Algorithm SHA256).Hash.ToLowerInvariant()
        $att = Save-Attestation $script:sb (New-Attestation -InstallerSha $sha)
        $r = Assert-InstallerAllowed -Path $inst -AttestationPath $att -HarnessRoot $script:sb.Harness
        $r.Sha256 | Should -Be $sha
        $r.Path | Should -Not -Be $inst
        Test-PathContained -Path $r.Path -Root $script:sb.Harness | Should -BeTrue
        (Get-FileHash $r.Path -Algorithm SHA256).Hash.ToLowerInvariant() | Should -Be $sha
    }
    It 'ALWAYS refuses the production-identity installer, even with a matching attestation' {
        Mock -ModuleName InstallGuard Get-ExeProductName { 'Snapmaker Studio' }
        $inst = New-FakeInstaller $script:sb
        $sha = (Get-FileHash $inst -Algorithm SHA256).Hash.ToLowerInvariant()
        $att = Save-Attestation $script:sb (New-Attestation -InstallerSha $sha)
        { Assert-InstallerAllowed -Path $inst -AttestationPath $att -HarnessRoot $script:sb.Harness } | Should -Throw '*PRODUCTION identity*'
    }
    It 'refuses an unknown ProductName' {
        Mock -ModuleName InstallGuard Get-ExeProductName { 'Something Else' }
        $inst = New-FakeInstaller $script:sb
        $sha = (Get-FileHash $inst -Algorithm SHA256).Hash.ToLowerInvariant()
        $att = Save-Attestation $script:sb (New-Attestation -InstallerSha $sha)
        { Assert-InstallerAllowed -Path $inst -AttestationPath $att -HarnessRoot $script:sb.Harness } | Should -Throw '*not the acceptance identity*'
    }
    It 'refuses an acceptance-named installer whose hash is not attested' {
        Mock -ModuleName InstallGuard Get-ExeProductName { 'Snapmaker Studio Acceptance' }
        $inst = New-FakeInstaller $script:sb
        $att = Save-Attestation $script:sb (New-Attestation -InstallerSha ('0' * 64))
        { Assert-InstallerAllowed -Path $inst -AttestationPath $att -HarnessRoot $script:sb.Harness } | Should -Throw '*not bound*'
    }
    It 'refuses an attestation that lives outside the harness attestations dir' {
        Mock -ModuleName InstallGuard Get-ExeProductName { 'Snapmaker Studio Acceptance' }
        $inst = New-FakeInstaller $script:sb
        $sha = (Get-FileHash $inst -Algorithm SHA256).Hash.ToLowerInvariant()
        $elsewhere = Join-Path $script:sb.Dir 'att.json'
        New-Attestation -InstallerSha $sha | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $elsewhere
        { Assert-InstallerAllowed -Path $inst -AttestationPath $elsewhere -HarnessRoot $script:sb.Harness } | Should -Throw '*attestations dir*'
    }
    It 'refuses when the staging dir is a junction out of the harness tree' {
        Mock -ModuleName InstallGuard Get-ExeProductName { 'Snapmaker Studio Acceptance' }
        $outside = Join-Path $script:sb.Dir 'outside'; New-Item -ItemType Directory -Path $outside | Out-Null
        New-Item -ItemType Junction -Path (Join-Path $script:sb.Harness 'staging') -Target $outside | Out-Null
        $inst = New-FakeInstaller $script:sb
        $sha = (Get-FileHash $inst -Algorithm SHA256).Hash.ToLowerInvariant()
        $att = Save-Attestation $script:sb (New-Attestation -InstallerSha $sha)
        { Assert-InstallerAllowed -Path $inst -AttestationPath $att -HarnessRoot $script:sb.Harness } | Should -Throw '*reparse*'
        (Get-ChildItem $outside).Count | Should -Be 0
    }
    It 'hashes the copy, not the original (original swapped after copy cannot matter)' {
        Mock -ModuleName InstallGuard Get-ExeProductName { 'Snapmaker Studio Acceptance' }
        $inst = New-FakeInstaller $script:sb
        $sha = (Get-FileHash $inst -Algorithm SHA256).Hash.ToLowerInvariant()
        $att = Save-Attestation $script:sb (New-Attestation -InstallerSha $sha)
        $r = Assert-InstallerAllowed -Path $inst -AttestationPath $att -HarnessRoot $script:sb.Harness
        [IO.File]::WriteAllBytes($inst, [byte[]](1, 2, 3))
        (Get-FileHash $r.Path -Algorithm SHA256).Hash.ToLowerInvariant() | Should -Be $sha
    }
}

Describe 'Confirm-InstallerUnchanged (B2 TOCTOU)' {
    BeforeEach {
        $script:sb = New-Sandbox
        Mock -ModuleName InstallGuard Get-ExeProductName { 'Snapmaker Studio Acceptance' }
        $inst = New-FakeInstaller $script:sb
        $script:sha = (Get-FileHash $inst -Algorithm SHA256).Hash.ToLowerInvariant()
        $att = Save-Attestation $script:sb (New-Attestation -InstallerSha $script:sha)
        $script:r = Assert-InstallerAllowed -Path $inst -AttestationPath $att -HarnessRoot $script:sb.Harness
    }
    AfterEach { Remove-Sandbox $script:sb }
    It 'passes for the untouched staged copy' {
        Confirm-InstallerUnchanged -Path $script:r.Path -ExpectedSha256 $script:sha -HarnessRoot $script:sb.Harness | Should -BeTrue
    }
    It 'refuses when the STAGED copy is replaced after Assert returned (source untouched)' {
        [IO.File]::WriteAllBytes($script:r.Path, [byte[]](6, 6, 6))
        { Confirm-InstallerUnchanged -Path $script:r.Path -ExpectedSha256 $script:sha -HarnessRoot $script:sb.Harness } | Should -Throw '*changed*'
    }
    It 'refuses when the staging dir is swapped for a junction holding a same-hash file' {
        $stage = Split-Path $script:r.Path -Parent
        $moved = "$stage-moved"
        Move-Item -LiteralPath $stage -Destination $moved
        New-Item -ItemType Junction -Path $stage -Target $moved | Out-Null
        (Get-FileHash $script:r.Path -Algorithm SHA256).Hash.ToLowerInvariant() | Should -Be $script:sha
        { Confirm-InstallerUnchanged -Path $script:r.Path -ExpectedSha256 $script:sha -HarnessRoot $script:sb.Harness } | Should -Throw '*reparse*'
    }
    It 'refuses a path that is not a staged copy (e.g. the original source)' {
        $src = New-FakeInstaller $script:sb
        $h = (Get-FileHash $src -Algorithm SHA256).Hash.ToLowerInvariant()
        { Confirm-InstallerUnchanged -Path $src -ExpectedSha256 $h -HarnessRoot $script:sb.Harness } | Should -Throw '*staged copy*'
    }
    It 'refuses when the staged file now reports a production identity' {
        Mock -ModuleName InstallGuard Get-ExeProductName { 'Snapmaker Studio' }
        { Confirm-InstallerUnchanged -Path $script:r.Path -ExpectedSha256 $script:sha -HarnessRoot $script:sb.Harness } | Should -Throw '*PRODUCTION*'
    }
}

Describe 'Assert-UninstallerAllowed / Confirm-UninstallerUnchanged (C1, F2, B2)' {
    BeforeEach {
        $script:sb = New-Sandbox
        $script:jd = Join-Path $script:sb.Dir 'journal'
        $script:sc = Join-Path $script:sb.Dir 'sc'
        $script:installDir = Join-Path $script:sb.Harness 'install\run1'
        New-Item -ItemType Directory -Force -Path $script:installDir, $script:jd, $script:sc | Out-Null
        New-Item -ItemType Directory -Force -Path $script:sb.RegRoot | Out-Null
        $script:runId = "run-$($script:sb.Guid)".Substring(0, 20)
        $script:j = New-HarnessJournal -RunId $script:runId -InstallDir $script:installDir -InstallVersion '1.2.0' -RegistryRoot $script:sb.RegRoot -ShortcutDir $script:sc -JournalDir $script:jd -HarnessRoot $script:sb.Harness
        $script:un = Join-Path $script:installDir 'uninstall.exe'
        [IO.File]::WriteAllBytes($script:un, [Text.Encoding]::UTF8.GetBytes('uninstaller-bytes'))
        $script:usha = (Get-FileHash $script:un -Algorithm SHA256).Hash.ToLowerInvariant()
        $k = "$($script:sb.RegRoot)\Microsoft\Windows\CurrentVersion\Uninstall\$($script:Acc.ProductName)"
        New-Item -Path $k -Force | Out-Null
        Set-ItemProperty -LiteralPath $k -Name UninstallString -Value ('"' + $script:un + '"')
        $script:key = $k
        Mock -ModuleName InstallGuard Get-ExeProductName { 'Snapmaker Studio Acceptance' }
        function script:Install-Done {
            [void](Set-JournalOwnedAfter -Journal $script:j -RegistryRoot $script:sb.RegRoot -ShortcutDir $script:sc -JournalDir $script:jd -HarnessRoot $script:sb.Harness)
        }
        function script:Assert-U([string]$Path = $script:un, [string[]]$Extra = @()) {
            Assert-UninstallerAllowed -Path $Path -RunId $script:runId -JournalDir $script:jd -HarnessRoot $script:sb.Harness -RegistryRoot $script:sb.RegRoot -ExtraWorkDirs $Extra
        }
    }
    AfterEach { Remove-Sandbox $script:sb }

    It 'F2: Set-JournalOwnedAfter computes the uninstaller hash itself' {
        Install-Done
        (Read-HarnessJournal -RunId $script:runId -JournalDir $script:jd -HarnessRoot $script:sb.Harness)['uninstallerSha256'] | Should -Be $script:usha
    }
    It 'F2: Set-JournalOwnedAfter has no caller-supplied uninstaller hash parameter' {
        (Get-Command Set-JournalOwnedAfter).Parameters.Keys | Should -Not -Contain 'UninstallerSha256'
    }
    It 'allows the journaled uninstaller when every condition holds, and Confirm passes' {
        Install-Done
        $a = Assert-U
        $a.Sha256 | Should -Be $script:usha
        Confirm-UninstallerUnchanged -Allowed $a | Should -BeTrue
    }
    It 'F2: refuses while the journal state is armed (install not yet recorded)' {
        { Assert-U } | Should -Throw '*not ''installed''*'
    }
    It 'F2: refuses a missing journal' {
        Install-Done
        { Assert-UninstallerAllowed -Path $script:un -RunId 'run-nonexistent-01' -JournalDir $script:jd -HarnessRoot $script:sb.Harness -RegistryRoot $script:sb.RegRoot } | Should -Throw 'JournalMissing*'
    }
    It 'Confirm detects a swap of the uninstaller between authorization and exec' {
        Install-Done
        $a = Assert-U
        [IO.File]::WriteAllBytes($script:un, [byte[]](9, 9))
        { Confirm-UninstallerUnchanged -Allowed $a } | Should -Throw '*differs*'
    }
    It 'B2: Confirm re-runs the UninstallString agreement check (key repointed after Assert)' {
        Install-Done
        $a = Assert-U
        Set-ItemProperty -LiteralPath $script:key -Name UninstallString -Value '"C:\elsewhere\uninstall.exe"'
        { Confirm-UninstallerUnchanged -Allowed $a } | Should -Throw '*does not resolve*'
    }
    It 'B2: Confirm refuses a junction swap of the install dir even though the file hash is identical' {
        Install-Done
        $a = Assert-U
        $moved = "$($script:installDir)-moved"
        Move-Item -LiteralPath $script:installDir -Destination $moved
        New-Item -ItemType Junction -Path $script:installDir -Target $moved | Out-Null
        (Get-FileHash $script:un -Algorithm SHA256).Hash.ToLowerInvariant() | Should -Be $script:usha
        { Confirm-UninstallerUnchanged -Allowed $a } | Should -Throw '*reparse*'
    }
    It 'B2: Confirm refuses when the uninstaller reports a production identity after Assert' {
        Install-Done
        $a = Assert-U
        Mock -ModuleName InstallGuard Get-ExeProductName { 'Snapmaker Studio' }
        { Confirm-UninstallerUnchanged -Allowed $a } | Should -Throw '*production identity*'
    }
    It 'Assert refuses an install dir that is a junction at authorization time' {
        Install-Done
        $moved = "$($script:installDir)-moved"
        Move-Item -LiteralPath $script:installDir -Destination $moved
        New-Item -ItemType Junction -Path $script:installDir -Target $moved | Out-Null
        { Assert-U } | Should -Throw '*reparse*'
    }
    It 'refuses a different path than <installDir>\uninstall.exe' {
        Install-Done
        $other = Join-Path $script:sb.Harness 'install\run2'; New-Item -ItemType Directory -Path $other | Out-Null
        $o = Join-Path $other 'uninstall.exe'; Copy-Item $script:un $o
        { Assert-U -Path $o } | Should -Throw '*not <journaled*'
    }
    It 'refuses when the uninstall key UninstallString points elsewhere, or is absent' {
        Install-Done
        Set-ItemProperty -LiteralPath $script:key -Name UninstallString -Value '"C:\elsewhere\uninstall.exe"'
        { Assert-U } | Should -Throw '*does not resolve*'
        Remove-Item -LiteralPath $script:key
        { Assert-U } | Should -Throw '*no UninstallString*'
    }
    It 'refuses a journal whose install dir was tampered to sit outside the harness install tree or under a work dir' {
        Install-Done
        $path = Get-JournalPath -RunId $script:runId -JournalDir $script:jd
        $good = Get-Content $path -Raw
        $enc = { param($p) ($p | ConvertTo-Json).Trim('"') }
        foreach ($bad in (Join-Path $script:sb.Dir 'SnapmakerStudio-HarnessEvil\install\run1'), (Join-Path $script:sb.Harness 'extract\x'), (Join-Path $script:sb.Harness 'rewrap\x')) {
            Set-Content -LiteralPath $path -Value ($good -replace [regex]::Escape((& $enc $script:installDir)), (& $enc $bad)) -NoNewline
            { Assert-U } | Should -Throw 'JournalCorrupt*' -Because $bad
        }
    }
    It 'honours ExtraWorkDirs' {
        Install-Done
        { Assert-U -Extra @((Join-Path $script:sb.Harness 'install')) } | Should -Throw '*work dir*'
    }
    It 'refuses a production-identity uninstaller (VersionInfo)' {
        Install-Done
        Mock -ModuleName InstallGuard Get-ExeProductName { 'Snapmaker Studio' }
        { Assert-U } | Should -Throw '*production identity*'
    }
    It 'refuses when the hash differs from the recorded one, or none was recorded' {
        Install-Done
        [IO.File]::WriteAllBytes($script:un, [byte[]](1, 2, 3))
        { Assert-U } | Should -Throw '*differs*'
    }
    It 'refuses when no uninstaller existed when the install was recorded' {
        Remove-Item -LiteralPath $script:un
        Install-Done
        [IO.File]::WriteAllBytes($script:un, [byte[]](1, 2, 3))
        { Assert-U } | Should -Throw '*recorded*'
    }
}

Describe 'F3: overrides may not overlap production locations' {
    It 'refuses harness roots that equal / sit inside / contain production locations' {
        $lad = $env:LOCALAPPDATA; $apd = $env:APPDATA
        foreach ($p in @(
                (Join-Path $lad $script:Prod.EngineDataDirName), (Join-Path $lad "$($script:Prod.EngineDataDirName)\sub"),
                (Join-Path $lad $script:Prod.DefaultInstallDirName), (Join-Path $lad $script:Prod.BundleId),
                (Join-Path $apd $script:Prod.BundleId), (Join-Path $apd "$($script:Prod.BundleId)\x"), $lad)) {
            { Get-HarnessRoot -HarnessRoot $p } | Should -Throw '*Refused*' -Because $p
        }
    }
    It 'accepts the real default harness root (prefix-neighbour of the engine dir) and a temp dir' {
        { Get-HarnessRoot } | Should -Not -Throw
        { Get-HarnessRoot -HarnessRoot (Join-Path ([IO.Path]::GetTempPath()) 'x-harness') } | Should -Not -Throw
    }
    It 'refuses registry roots other than HKCU:\Software or a non-overlapping scratch key' {
        foreach ($r in 'HKLM:\Software', 'HKCU:\Software\DeadlyVirusIn / Snapmaker Studio', 'HKCU:\Software\Microsoft', 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
            'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Snapmaker Studio', 'HKCU:\Other') {
            { Assert-SafeRegistryRoot -RegistryRoot $r } | Should -Throw '*Refused*' -Because $r
        }
        { Assert-SafeRegistryRoot -RegistryRoot 'HKCU:\Software' } | Should -Not -Throw
        { Assert-SafeRegistryRoot -RegistryRoot 'HKCU:\Software\SnapmakerStudioHarnessTest\abc' } | Should -Not -Throw
    }
    It 'Get-HarnessSurfaceDefinition and journal-dir overrides apply the same refusal' {
        { Get-HarnessSurfaceDefinition -RegistryRoot 'HKLM:\Software' -ShortcutDir 'x' } | Should -Throw '*Refused*'
        { Get-JournalDir -JournalDir (Join-Path $env:APPDATA $script:Prod.BundleId) } | Should -Throw '*Refused*'
    }
    It 'does not export raw write/restore primitives' {
        Get-Command Write-AtomicFile -Module InstallGuard -ErrorAction SilentlyContinue | Should -BeNullOrEmpty
        Get-Command Restore-SurfaceSnapshot -Module HarnessJournal -ErrorAction SilentlyContinue | Should -BeNullOrEmpty
    }
}

Describe 'Get-ProductionRegistration (read-only)' {
    BeforeEach { $script:sb = New-Sandbox }
    AfterEach { Remove-Sandbox $script:sb }
    It 'finds nothing on a clean scratch root' {
        $f = Get-ProductionRegistration -SoftwareRoots @($script:sb.RegRoot) -DefaultInstallDirs @() -ProcessProvider { @() }
        @($f).Count | Should -Be 0
    }
    It 'detects exact uninstall / remembered-location / manufacturer keys, default-path exe and a running process' {
        New-Item -Force -Path "$($script:sb.RegRoot)\Microsoft\Windows\CurrentVersion\Uninstall\$($script:Prod.ProductName)" | Out-Null
        New-Item -Force -Path "$($script:sb.RegRoot)\$($script:Prod.Manufacturer)\$($script:Prod.ProductName)" | Out-Null
        $d = Join-Path $script:sb.Dir 'Snapmaker Studio'; New-Item -ItemType Directory -Path $d | Out-Null
        New-Item -ItemType File -Path (Join-Path $d $script:Prod.MainBinaryName) | Out-Null
        $f = Get-ProductionRegistration -SoftwareRoots @($script:sb.RegRoot) -DefaultInstallDirs @($d) -ProcessProvider { [pscustomobject]@{ Id = 4242 } }
        ($f -join "`n") | Should -Match 'uninstall key'
        ($f -join "`n") | Should -Match 'remembered-location'
        ($f -join "`n") | Should -Match 'manufacturer key'
        ($f -join "`n") | Should -Match 'default path'
        ($f -join "`n") | Should -Match 'process running'
        { Assert-NoProductionRegistration -SoftwareRoots @($script:sb.RegRoot) -DefaultInstallDirs @($d) -ProcessProvider { @() } } | Should -Throw '*registration present*'
        { Assert-ProductionNotRunning -ProcessProvider { [pscustomobject]@{ Id = 1 } } } | Should -Throw '*running*'
    }
    It 'does not treat the acceptance identity as production' {
        New-Item -Force -Path "$($script:sb.RegRoot)\Microsoft\Windows\CurrentVersion\Uninstall\$($script:Acc.ProductName)" | Out-Null
        New-Item -Force -Path "$($script:sb.RegRoot)\$($script:Acc.Manufacturer)\$($script:Acc.ProductName)" | Out-Null
        @(Get-ProductionRegistration -SoftwareRoots @($script:sb.RegRoot) -DefaultInstallDirs @() -ProcessProvider { @() }).Count | Should -Be 0
    }
}

Describe 'Harness lock (M5)' {
    BeforeEach { $script:sb = New-Sandbox; $script:mx = "Local\SnapmakerStudio-Harness-Test-$($script:sb.Guid)" }
    AfterEach { Remove-Sandbox $script:sb }
    It 'acquires, refuses a second holder, and releases' {
        $l = Enter-HarnessLock -HarnessRoot $script:sb.Harness -MutexName $script:mx
        try { { Enter-HarnessLock -HarnessRoot $script:sb.Harness -MutexName $script:mx } | Should -Throw '*Refused*' }
        finally { Exit-HarnessLock -Lock $l }
        Test-Path $l.LockFile | Should -BeFalse
        $l2 = Enter-HarnessLock -HarnessRoot $script:sb.Harness -MutexName $script:mx
        Exit-HarnessLock -Lock $l2
    }
    It 'takes over a stale lock (dead pid) and refuses an unreadable lock file' {
        $dir = Join-Path $script:sb.Harness 'lock'; New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $lf = Join-Path $dir 'harness.lock.json'
        @{ pid = 2147483000; startTicks = 1; acquiredUtc = 'x' } | ConvertTo-Json | Set-Content $lf
        $l = Enter-HarnessLock -HarnessRoot $script:sb.Harness -MutexName $script:mx
        $l.TookOverStale | Should -BeTrue
        Exit-HarnessLock -Lock $l
        'not json {' | Set-Content $lf
        { Enter-HarnessLock -HarnessRoot $script:sb.Harness -MutexName $script:mx } | Should -Throw '*unreadable*'
    }
    It 'treats a recycled pid (same pid, different start time) as stale' {
        $dir = Join-Path $script:sb.Harness 'lock'; New-Item -ItemType Directory -Force -Path $dir | Out-Null
        @{ pid = $PID; startTicks = 1; acquiredUtc = 'x' } | ConvertTo-Json | Set-Content (Join-Path $dir 'harness.lock.json')
        $l = Enter-HarnessLock -HarnessRoot $script:sb.Harness -MutexName $script:mx
        $l.TookOverStale | Should -BeTrue
        Exit-HarnessLock -Lock $l
    }
}

Describe 'Identity constants' {
    It 'keeps acceptance and production identities disjoint' {
        $script:Acc.ProductName | Should -Not -Be $script:Prod.ProductName
        $script:Acc.MainBinaryName | Should -Not -Be $script:Prod.MainBinaryName
        $script:Acc.BundleId | Should -Not -Be $script:Prod.BundleId
        $script:Acc.Manufacturer | Should -Not -Be $script:Prod.Manufacturer
    }
    It 'contains no absolute local paths or user names' {
        $raw = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'HarnessIdentity.psd1') -Raw
        $raw | Should -Not -Match '[A-Za-z]:\\'
        $raw | Should -Not -Match '(?i)\\users\\'
    }
    It 'has a recovery allow-list limited to acceptance surfaces' {
        @($script:Id.RecoveryAllowList | ForEach-Object Id) | Should -Be @('UninstallKey', 'RememberedLocationKey', 'RunValue', 'StartMenuShortcut', 'DesktopShortcut')
    }
}

Describe 'Assert-AllowedOverridePath (positive allowlist)' {
    BeforeAll {
        $script:TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
        $script:DefaultHarness = Get-DefaultHarnessRoot
    }
    BeforeEach { $script:sb = New-Sandbox }
    AfterEach { Remove-Sandbox $script:sb }

    It 'refuses <name> (raw input)' -ForEach @(
        @{ name = 'relative'; p = 'sub\x' }
        @{ name = 'dot-relative'; p = '.\x' }
        @{ name = 'dotdot-relative'; p = '..\x' }
        @{ name = 'drive-relative'; p = 'C:x' }
        @{ name = 'extended-length'; p = '\\?\C:\x\y' }
        @{ name = 'device'; p = '\\.\C:\x\y' }
        @{ name = 'UNC admin share'; p = '\\localhost\C$\x\y' }
        @{ name = 'provider syntax'; p = 'Registry::HKEY_CURRENT_USER\Software\x' }
        @{ name = 'forward slashes'; p = 'C:/x/y' }
        @{ name = 'wildcard'; p = 'C:\x\*' }
        @{ name = 'doubled separator'; p = 'C:\x\\y' }
    ) {
        { Assert-AllowedOverridePath -Path $p } | Should -Throw '*Refused*'
    }
    It 'refuses structural tricks inside the temp container (ADS, dot segments, trailing dot/space)' {
        foreach ($suffix in 'a:stream', 'a\..\b', 'a\.\b', 'a.', 'a ', 'dir.\x', 'dir \x') {
            { Assert-AllowedOverridePath -Path (Join-Path $script:TempRoot "ssh-allow-$($script:sb.Guid)\$suffix") } | Should -Throw '*Refused*' -Because $suffix
        }
    }
    It 'refuses the temp root and the default harness root themselves (strictly inside only)' {
        { Assert-AllowedOverridePath -Path $script:TempRoot } | Should -Throw '*strictly inside*'
        { Assert-AllowedOverridePath -Path ($script:TempRoot + '\') } | Should -Throw '*strictly inside*'
        { Assert-AllowedOverridePath -Path $script:DefaultHarness } | Should -Throw '*strictly inside*'
    }
    It 'refuses fully-qualified local paths outside the temp container / default harness root (proves an allowlist, not a denylist)' {
        { Assert-AllowedOverridePath -Path 'D:\x' } | Should -Throw '*strictly inside*'
        { Assert-AllowedOverridePath -Path (Join-Path $env:USERPROFILE 'Documents\x') } | Should -Throw '*strictly inside*'
        { Assert-AllowedOverridePath -Path (Join-Path (Split-Path $script:TempRoot -Parent) 'NotTemp\x') } | Should -Throw '*strictly inside*'
        { Assert-AllowedOverridePath -Path ($script:TempRoot + '-neighbour\x') } | Should -Throw '*strictly inside*'
    }
    It 'accepts a subdir of the temp dir and of the default harness root, returns the canonical path, and creates nothing' {
        $a = Join-Path $script:TempRoot "ssh-allow-$($script:sb.Guid)-none\sub"
        Assert-AllowedOverridePath -Path $a | Should -Be $a
        Test-Path -LiteralPath (Split-Path $a -Parent) | Should -BeFalse
        $b = Join-Path $script:DefaultHarness 'sub'
        Assert-AllowedOverridePath -Path $b | Should -Be $b
        Test-Path -LiteralPath $b | Should -BeFalse
    }
    It 'refuses a path whose ancestor is a junction (Sol repro shape: alias -> production-like dir)' {
        $prodLike = Join-Path $script:sb.Dir 'prodlike'; New-Item -ItemType Directory -Path $prodLike | Out-Null
        $alias = Join-Path $script:sb.Dir 'alias'; New-Item -ItemType Junction -Path $alias -Target $prodLike | Out-Null
        { Assert-AllowedOverridePath -Path (Join-Path $alias 'sub') } | Should -Throw '*reparse*'
        { Assert-AllowedOverridePath -Path $alias } | Should -Throw '*reparse*'
    }
    It 'refuses a junction at an ANCESTOR several levels above the override' {
        $real = Join-Path $script:sb.Dir 'real\x'; New-Item -ItemType Directory -Path $real | Out-Null
        $link = Join-Path $script:sb.Dir 'link'; New-Item -ItemType Junction -Path $link -Target (Join-Path $script:sb.Dir 'real') | Out-Null
        { Assert-AllowedOverridePath -Path (Join-Path $link 'x\y\z') } | Should -Throw '*reparse*'
    }
    It 'refuses a file symlink leaf' {
        $target = Join-Path $script:sb.Dir 'target.txt'; Set-Content $target 'x'
        $leaf = Join-Path $script:sb.Dir 'leaf.lnk'
        try { New-Item -ItemType SymbolicLink -Path $leaf -Target $target -ErrorAction Stop | Out-Null }
        catch { Set-ItResult -Skipped -Because 'creating a file symlink needs Developer Mode / privilege on this machine'; return }
        { Assert-AllowedOverridePath -Path $leaf } | Should -Throw '*reparse*'
    }
    It 'layer 2: still refuses production locations even when they would sit under an allowed container' {
        # Simulate TEMP pointing at production by pretending the production engine dir is the temp container child:
        # the lexical production check must fire independently of the container rule.
        $prodDir = Join-Path $env:LOCALAPPDATA $script:Prod.EngineDataDirName
        { Assert-NotProductionLocation -Path (Join-Path $prodDir 'x') } | Should -Throw '*production location*'
    }
    It 'layer 2 fires independently: TEMP pointing at production (container rule satisfied, no reparse) is still refused' {
        $prodDir = Join-Path $env:LOCALAPPDATA $script:Prod.EngineDataDirName
        $saved = @{ TMP = $env:TMP; TEMP = $env:TEMP }
        try {
            $env:TMP = $prodDir; $env:TEMP = $prodDir
            { Assert-AllowedOverridePath -Path (Join-Path $prodDir 'sub') } | Should -Throw '*production location*'
        } finally { $env:TMP = $saved.TMP; $env:TEMP = $saved.TEMP }
    }
    It 'default locations skip ONLY the container rule, not the reparse rule' {
        $prodLike = Join-Path $script:sb.Dir 'prodlike'; New-Item -ItemType Directory -Path $prodLike | Out-Null
        $alias = Join-Path $script:sb.Dir 'alias'; New-Item -ItemType Junction -Path $alias -Target $prodLike | Out-Null
        { Assert-AllowedOverridePath -Path (Join-Path $alias 'x') -DefaultLocation } | Should -Throw '*reparse*'
        { Assert-AllowedOverridePath -Path (Join-Path ($env:SystemDrive + [char]92) "ssh-not-in-temp-$($script:sb.Guid)") -DefaultLocation } | Should -Not -Throw
        { Assert-AllowedOverridePath -Path 'relative\x' -DefaultLocation } | Should -Throw '*Refused*'
    }
}

Describe 'Test-ContainsReparsePoint walks from the volume root' {
    BeforeEach { $script:sb = New-Sandbox }
    AfterEach { Remove-Sandbox $script:sb }
    It 'sees a junction ABOVE the old "root" (the stop-at-root weakness)' {
        $real = Join-Path $script:sb.Dir 'real\sub'; New-Item -ItemType Directory -Path $real | Out-Null
        $link = Join-Path $script:sb.Dir 'link'; New-Item -ItemType Junction -Path $link -Target (Join-Path $script:sb.Dir 'real') | Out-Null
        $p = Join-Path $link 'sub'
        Test-ContainsReparsePoint -Path $p -Root $p | Should -BeTrue
        { Assert-HarnessOwnedPath -Path $p -Root $p } | Should -Throw '*reparse*'
    }
    It 'treats genuine absence as clean and a plain chain as clean' {
        Test-ContainsReparsePoint -Path (Join-Path $script:sb.Dir 'nope\deeper') | Should -BeFalse
        New-Item -ItemType Directory -Path (Join-Path $script:sb.Dir 'plain\x') | Out-Null
        Test-ContainsReparsePoint -Path (Join-Path $script:sb.Dir 'plain\x') | Should -BeFalse
    }
    It 'refuses paths it cannot reason about (UNC, relative)' {
        Test-ContainsReparsePoint -Path '\\localhost\C$\x' | Should -BeTrue
    }
    It 'Test-PathContainedNoReparse is false through a junction even though it is lexically inside' {
        $real = Join-Path $script:sb.Dir 'real'; New-Item -ItemType Directory -Path $real | Out-Null
        $link = Join-Path $script:sb.Harness 'install'; New-Item -ItemType Junction -Path $link -Target $real | Out-Null
        Test-PathContained -Path (Join-Path $link 'a') -Root $script:sb.Harness | Should -BeTrue
        Test-PathContainedNoReparse -Path (Join-Path $link 'a') -Root $script:sb.Harness | Should -BeFalse
    }
}

Describe 'Registry root allowlist (exact)' {
    It 'refuses <r>' -ForEach @(
        @{ r = 'HKCU:\Software\Foo' }
        @{ r = 'HKLM:\Software' }
        @{ r = 'HKLM:\Software\SnapmakerStudioHarnessTest\abc' }
        @{ r = 'Registry::HKEY_CURRENT_USER\Software' }
        @{ r = 'HKCU:\\Software' }
        @{ r = 'HKCU:\Software\\SnapmakerStudioHarnessTest\abc' }
        @{ r = 'HKCU:\Software\SnapmakerStudioHarnessTest\..\Microsoft' }
        @{ r = 'HKCU:\Software\SnapmakerStudioHarnessTest\abc\child' }
        @{ r = 'HKCU:\Software\SnapmakerStudioHarnessTest' }
        @{ r = 'HKCU:\Software\' }
        @{ r = 'HKCU:\Software\SnapmakerStudioHarnessTest\abc\' }
        @{ r = 'HKCU:\Software\SnapmakerStudioHarnessTest\-bad' }
        @{ r = 'HKCU:\Software\DeadlyVirusIn / Snapmaker Studio' }
        @{ r = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' }
    ) { { Assert-SafeRegistryRoot -RegistryRoot $r } | Should -Throw '*Refused*' }
    It 'accepts HKCU:\Software and scratch-hive names' {
        { Assert-SafeRegistryRoot -RegistryRoot 'HKCU:\Software' } | Should -Not -Throw
        { Assert-SafeRegistryRoot -RegistryRoot "HKCU:\Software\SnapmakerStudioHarnessTest\$([guid]::NewGuid().ToString('N'))" } | Should -Not -Throw
    }
}

Describe 'Lock hardening (mutex override, deletion confinement)' {
    BeforeEach { $script:sb = New-Sandbox }
    AfterEach { Remove-Sandbox $script:sb }
    It 'refuses a MutexName override that is not Local\<name>' {
        foreach ($m in 'Global\SnapmakerStudio-Harness-Lock', 'plain-name', 'Local\', 'Local\..\x', 'Local\a b', '') {
            { Enter-HarnessLock -HarnessRoot $script:sb.Harness -MutexName $m } | Should -Throw '*MutexName*' -Because "'$m'"
        }
    }
    It 'Exit-HarnessLock refuses to delete a lock file reached through a swapped lock dir (junction)' {
        $l = Enter-HarnessLock -HarnessRoot $script:sb.Harness -MutexName "Local\ssh-lock-$($script:sb.Guid)"
        $decoy = Join-Path $script:sb.Dir 'decoy'; New-Item -ItemType Directory -Path $decoy | Out-Null
        Copy-Item $l.LockFile (Join-Path $decoy 'harness.lock.json')
        $lockDir = $l.LockDir
        Move-Item -LiteralPath $lockDir -Destination "$lockDir-moved"
        New-Item -ItemType Junction -Path $lockDir -Target $decoy | Out-Null
        { Exit-HarnessLock -Lock $l } | Should -Throw '*reparse*'
        Test-Path (Join-Path $decoy 'harness.lock.json') | Should -BeTrue
    }
}

Describe 'Exit-HarnessLock derives, never trusts, the lock object' {
    BeforeEach {
        $script:sb = New-Sandbox
        $script:mx = "Local\ssh-lock-$($script:sb.Guid)"
        $script:victimDir = Join-Path $script:sb.Dir 'outside'
        New-Item -ItemType Directory -Path $script:victimDir | Out-Null
        $script:victim = Join-Path $script:victimDir 'victim.json'
        $ticks = Get-ProcessStartTicks -ProcessId $PID
        (@{ pid = $PID; startTicks = $ticks } | ConvertTo-Json) | Set-Content -LiteralPath $script:victim
    }
    AfterEach {
        if ($script:held) { try { Exit-HarnessLock -Lock $script:held } catch { } ; $script:held = $null }
        Remove-Sandbox $script:sb
    }

    It 'a fully forged lock object (no valid handle) deletes nothing, even with a matching pid' {
        $forged = [pscustomobject]@{ LockFile = $script:victim; LockDir = $script:victimDir; Pid = $PID }
        { Exit-HarnessLock -Lock $forged } | Should -Throw '*forged*'
        $forged2 = [pscustomobject]@{ Token = 'deadbeef'; LockFile = $script:victim; LockDir = $script:victimDir; Pid = $PID; Mutex = $null }
        { Exit-HarnessLock -Lock $forged2 } | Should -Throw '*forged*'
        Test-Path $script:victim | Should -BeTrue
    }
    It 'a genuine handle with a mutated LockFile / LockDir / Pid / leaf name is refused, deletes nothing, and the real lock survives' {
        $script:held = Enter-HarnessLock -HarnessRoot $script:sb.Harness -MutexName $script:mx
        $real = $script:held
        $mutations = [ordered]@{
            'LockFile outside'            = @{ LockFile = $script:victim }
            'LockDir outside + LockFile'  = @{ LockFile = $script:victim; LockDir = $script:victimDir }
            'leaf name mismatch (inside)' = @{ LockFile = (Join-Path $real.LockDir 'other.json') }
            'Pid changed'                 = @{ Pid = ($PID + 1) }
        }
        Set-Content -LiteralPath (Join-Path $real.LockDir 'other.json') -Value '{}'
        foreach ($name in $mutations.Keys) {
            $copy = [pscustomobject]@{ Token = $real.Token; Mutex = $real.Mutex; LockFile = $real.LockFile; LockDir = $real.LockDir; Pid = $real.Pid }
            foreach ($k in $mutations[$name].Keys) { $copy.$k = $mutations[$name][$k] }
            { Exit-HarnessLock -Lock $copy } | Should -Throw '*does not match its handle*' -Because $name
        }
        Test-Path $script:victim | Should -BeTrue
        Test-Path (Join-Path $real.LockDir 'other.json') | Should -BeTrue
        Test-Path $real.LockFile | Should -BeTrue
    }
    It 'a lock dir swapped for a junction is refused and the decoy lock file survives' {
        $script:held = Enter-HarnessLock -HarnessRoot $script:sb.Harness -MutexName $script:mx
        $l = $script:held
        $decoy = Join-Path $script:sb.Dir 'decoy'; New-Item -ItemType Directory -Path $decoy | Out-Null
        Copy-Item $l.LockFile (Join-Path $decoy 'harness.lock.json')
        Move-Item -LiteralPath $l.LockDir -Destination "$($l.LockDir)-moved"
        New-Item -ItemType Junction -Path $l.LockDir -Target $decoy | Out-Null
        { Exit-HarnessLock -Lock $l } | Should -Throw '*reparse*'
        $script:held = $null
        Test-Path (Join-Path $decoy 'harness.lock.json') | Should -BeTrue
    }
    It 'a legitimate lock still acquires and releases (lock file removed, mutex free, handle single-use)' {
        $l = Enter-HarnessLock -HarnessRoot $script:sb.Harness -MutexName $script:mx
        Test-Path $l.LockFile | Should -BeTrue
        Exit-HarnessLock -Lock $l
        Test-Path $l.LockFile | Should -BeFalse
        { Exit-HarnessLock -Lock $l } | Should -Throw '*forged*'
        $l2 = Enter-HarnessLock -HarnessRoot $script:sb.Harness -MutexName $script:mx
        Exit-HarnessLock -Lock $l2
    }
}

Describe 'Volume roots are refused even when the cwd is inside the temp container' {
    BeforeEach {
        $script:sb = New-Sandbox
        $script:cwd = (Get-Location).Path
        Set-Location -LiteralPath $script:sb.Dir
        $script:root = $env:SystemDrive + [char]92
    }
    AfterEach { Set-Location -LiteralPath $script:cwd; Remove-Sandbox $script:sb }
    It 'Assert-AllowedOverridePath refuses a volume root (with and without -DefaultLocation)' {
        { Assert-AllowedOverridePath -Path $script:root } | Should -Throw '*volume root*'
        { Assert-AllowedOverridePath -Path $script:root -DefaultLocation } | Should -Throw '*volume root*'
    }
    It 'refuses the root as harness root, journal dir, start menu dir and desktop dir' {
        { Get-HarnessRoot -HarnessRoot $script:root } | Should -Throw '*volume root*'
        { Get-JournalDir -JournalDir $script:root } | Should -Throw '*volume root*'
        { Get-HarnessSurfaceDefinition -RegistryRoot 'HKCU:\Software' -StartMenuDir $script:root } | Should -Throw '*volume root*'
        { Get-HarnessSurfaceDefinition -RegistryRoot 'HKCU:\Software' -DesktopDir $script:root } | Should -Throw '*volume root*'
        { Get-HarnessSurfaceDefinition -RegistryRoot 'HKCU:\Software' -ShortcutDir $script:root } | Should -Throw '*volume root*'
    }
}

Describe 'Default harness root (no -HarnessRoot) with LOCALAPPDATA and TMP redirected into a sandbox: real-use shape' {
    BeforeAll {
        function script:Use-Redirect([string]$base) {
            $saved = @{ LOCALAPPDATA = $env:LOCALAPPDATA; APPDATA = $env:APPDATA; TMP = $env:TMP; TEMP = $env:TEMP }
            $local = Join-Path $base 'Local'; $tmp = Join-Path $local 'Temp'
            New-Item -ItemType Directory -Force -Path $tmp, (Join-Path $base 'Roaming') | Out-Null
            $env:LOCALAPPDATA = $local; $env:APPDATA = Join-Path $base 'Roaming'; $env:TMP = $tmp; $env:TEMP = $tmp
            $saved
        }
        function script:Restore-Redirect($saved) { foreach ($k in $saved.Keys) { Set-Item -LiteralPath "env:$k" -Value $saved[$k] } }
    }
    BeforeEach {
        $script:sb = New-Sandbox
        $script:saved = Use-Redirect $script:sb.Dir
        $script:mx = "Local\ssh-lock-$($script:sb.Guid)"
        Mock -ModuleName InstallGuard Get-ExeProductName { 'Snapmaker Studio Acceptance' }
    }
    AfterEach { Restore-Redirect $script:saved; Remove-Sandbox $script:sb }

    It 'lock: acquire / release / re-acquire / single-use handle with NO -HarnessRoot' {
        $l = Enter-HarnessLock -MutexName $script:mx
        $expectedDir = Join-Path (Join-Path $env:LOCALAPPDATA 'SnapmakerStudio-Harness') 'lock'
        $l.LockDir | Should -Be $expectedDir
        Test-Path $l.LockFile | Should -BeTrue
        { Enter-HarnessLock -MutexName $script:mx } | Should -Throw '*Refused*'        # still held: no silent double-acquire
        Exit-HarnessLock -Lock $l
        Test-Path $l.LockFile | Should -BeFalse
        { Exit-HarnessLock -Lock $l } | Should -Throw '*forged*'
        $l2 = Enter-HarnessLock -MutexName $script:mx                                 # re-acquire: no self-lockout
        Exit-HarnessLock -Lock $l2
    }
    It 'a release whose root later fails validation still frees the mutex and the token' {
        $l = Enter-HarnessLock -MutexName $script:mx
        $env:LOCALAPPDATA = ''                                                        # default root can no longer be derived
        { Exit-HarnessLock -Lock $l } | Should -Throw '*LOCALAPPDATA*'
        { Exit-HarnessLock -Lock $l } | Should -Throw '*forged*'                      # token entry was removed
        $ex = $null; try { [void]$l.Mutex.WaitOne(0) } catch { $ex = $_.Exception.GetBaseException() }
        $ex | Should -BeOfType ([System.ObjectDisposedException])                          # mutex was released and disposed
    }
    It 'a forged object cannot release someone elses lock even when the root would fail validation' {
        $l = Enter-HarnessLock -MutexName $script:mx
        $forged = [pscustomobject]@{ Token = $l.Token; Mutex = $l.Mutex; LockFile = (Join-Path $script:sb.Dir 'x.json'); LockDir = $script:sb.Dir; Pid = $l.Pid }
        { Exit-HarnessLock -Lock $forged } | Should -Throw '*does not match*'
        Test-Path $l.LockFile | Should -BeTrue                                        # the real lock was NOT released by the forger
        Exit-HarnessLock -Lock $l
    }

    Context 'uninstaller authorization on the DEFAULT harness root' {
        BeforeEach {
            $script:jd = $null
            $script:sc = Join-Path $env:TMP 'sc'
            $script:reg = "HKCU:\Software\SnapmakerStudioHarnessTest\$($script:sb.Guid)"
            New-Item -ItemType Directory -Force -Path $script:sc, $script:reg | Out-Null
            $script:root = Get-HarnessRoot
            $script:installDir = Join-Path $script:root 'install\run1'
            New-Item -ItemType Directory -Force -Path $script:installDir | Out-Null
            $script:runId = "run-$($script:sb.Guid)".Substring(0, 20)
            $script:j = New-HarnessJournal -RunId $script:runId -InstallDir $script:installDir -InstallVersion '1.2.0' -RegistryRoot $script:reg -ShortcutDir $script:sc
            $script:un = Join-Path $script:installDir 'uninstall.exe'
            [IO.File]::WriteAllBytes($script:un, [Text.Encoding]::UTF8.GetBytes('uninstaller-bytes'))
            $script:key = "$($script:reg)\Microsoft\Windows\CurrentVersion\Uninstall\$($script:Acc.ProductName)"
            New-Item -Path $script:key -Force | Out-Null
            Set-ItemProperty -LiteralPath $script:key -Name UninstallString -Value ('"' + $script:un + '"')
            [void](Set-JournalOwnedAfter -Journal $script:j -RegistryRoot $script:reg -ShortcutDir $script:sc)
            function script:Assert-D([string]$Path = $script:un) { Assert-UninstallerAllowed -Path $Path -RunId $script:runId -RegistryRoot $script:reg }
        }
        It 'Assert-UninstallerAllowed and Confirm-UninstallerUnchanged succeed on the default root' {
            $a = Assert-D
            $a.Path | Should -Be $script:un
            Confirm-UninstallerUnchanged -Allowed $a | Should -BeTrue
        }
        It 'still refuses every C1 negative on the default root' {
            $a = Assert-D
            $other = Join-Path $script:root 'install\run2'; New-Item -ItemType Directory -Path $other | Out-Null
            Copy-Item $script:un (Join-Path $other 'uninstall.exe')
            { Assert-D -Path (Join-Path $other 'uninstall.exe') } | Should -Throw '*not <journaled*'
            Set-ItemProperty -LiteralPath $script:key -Name UninstallString -Value '"C:\elsewhere\uninstall.exe"'
            { Assert-D } | Should -Throw '*does not resolve*'
            { Confirm-UninstallerUnchanged -Allowed $a } | Should -Throw '*does not resolve*'
            Set-ItemProperty -LiteralPath $script:key -Name UninstallString -Value ('"' + $script:un + '"')
            [IO.File]::WriteAllBytes($script:un, [byte[]](1, 2, 3))
            { Assert-D } | Should -Throw '*differs*'
        }
        It 'refuses an install dir swapped for a junction on the default root' {
            $moved = "$($script:installDir)-moved"
            Move-Item -LiteralPath $script:installDir -Destination $moved
            New-Item -ItemType Junction -Path $script:installDir -Target $moved | Out-Null
            { Assert-D } | Should -Throw '*reparse*'
        }
        It 'refuses an install dir under an extraction work dir via ExtraWorkDirs on the default root' {
            { Assert-UninstallerAllowed -Path $script:un -RunId $script:runId -RegistryRoot $script:reg -ExtraWorkDirs @((Join-Path $script:root 'install')) } | Should -Throw '*work dir*'
        }
    }
}
