#requires -Version 7.0
# Pester 5. Everything runs against a scratch hive HKCU:\Software\SnapmakerStudioHarnessTest\<guid>
# and private temp dirs. Nothing here touches real production/acceptance keys, the real Start Menu or
# Desktop, and no installer is ever run.
#
# Fault-injection note (S7): the -Barrier hook throws at named points inside Invoke-HarnessRecovery.
# That validates the recovery STATE MACHINE (compare-and-swap, resumability) ONLY. It is NOT evidence of
# OS-crash or power-loss safety, which this suite does not claim.

BeforeAll {
    Import-Module (Join-Path $PSScriptRoot '..\lib\InstallGuard.psm1') -Force -DisableNameChecking
    Import-Module (Join-Path $PSScriptRoot 'HarnessJournal.psm1') -Force -DisableNameChecking
    $script:Id = Get-HarnessIdentity
    $script:Acc = $script:Id.Acceptance
    $script:Prod = $script:Id.Production
    $script:RepairScript = Join-Path $PSScriptRoot 'Repair-Harness.ps1'

    function script:New-Env {
        $guid = [guid]::NewGuid().ToString('N')
        $dir = Join-Path ([IO.Path]::GetTempPath()) "ssh-journal-test-$guid"
        $e = [pscustomobject]@{
            Guid = $guid; Dir = $dir
            Harness = (Join-Path $dir 'SnapmakerStudio-Harness')
            Journal = (Join-Path $dir 'journal')
            Shortcuts = (Join-Path $dir 'sc')
            Reg = "HKCU:\Software\SnapmakerStudioHarnessTest\$guid"
            InstallDir = (Join-Path $dir 'SnapmakerStudio-Harness\install\run1')
            RunId = "run-$guid".Substring(0, 20)
        }
        New-Item -ItemType Directory -Force -Path $e.Harness, $e.Journal, (Join-Path $e.Shortcuts 'StartMenu'), (Join-Path $e.Shortcuts 'Desktop'), $e.InstallDir | Out-Null
        New-Item -ItemType Directory -Force -Path $e.Reg | Out-Null
        $e
    }
    function script:Clear-Junctions([string]$dir) {
        if (-not (Test-Path -LiteralPath $dir)) { return }
        foreach ($d in [IO.Directory]::EnumerateDirectories($dir)) {
            if ([IO.File]::GetAttributes($d) -band [IO.FileAttributes]::ReparsePoint) { [IO.Directory]::Delete($d) } else { Clear-Junctions $d }
        }
    }
    function script:Remove-Env($e) {
        Clear-Junctions $e.Dir
        if ($e.Reg -like 'HKCU:\Software\SnapmakerStudioHarnessTest\*' -and (Test-Path $e.Reg)) { Remove-Item $e.Reg -Recurse -Force }
        if ($e.Dir -like "$([IO.Path]::GetTempPath())ssh-journal-test-*" -and (Test-Path $e.Dir)) { Remove-Item $e.Dir -Recurse -Force }
        $parent = 'HKCU:\Software\SnapmakerStudioHarnessTest'
        if ((Test-Path $parent) -and @(Get-ChildItem $parent).Count -eq 0) { Remove-Item $parent -Force }
    }
    function script:Key($e, [string]$rel) { "$($e.Reg)\$rel" }
    function script:UninstKey($e) { Key $e "Microsoft\Windows\CurrentVersion\Uninstall\$($script:Acc.ProductName)" }
    function script:MfrKey($e) { Key $e "$($script:Acc.Manufacturer)\$($script:Acc.ProductName)" }
    function script:RunKey($e) { Key $e 'Microsoft\Windows\CurrentVersion\Run' }
    function script:StartLnk($e) { Join-Path $e.Shortcuts "StartMenu\$($script:Acc.ProductName).lnk" }
    function script:DeskLnk($e) { Join-Path $e.Shortcuts "Desktop\$($script:Acc.ProductName).lnk" }

    # Write a full acceptance "installed" state pointing at $where (install dir) with $version.
    function script:Set-InstalledState($e, [string]$where, [string]$version) {
        $u = UninstKey $e
        New-Item -Path $u -Force | Out-Null
        Set-ItemProperty -LiteralPath $u -Name DisplayName -Value $script:Acc.ProductName
        Set-ItemProperty -LiteralPath $u -Name DisplayVersion -Value $version
        Set-ItemProperty -LiteralPath $u -Name InstallLocation -Value $where
        Set-ItemProperty -LiteralPath $u -Name UninstallString -Value ('"' + (Join-Path $where 'uninstall.exe') + '"')
        Set-ItemProperty -LiteralPath $u -Name DisplayIcon -Value ('"' + (Join-Path $where $script:Acc.MainBinaryName) + '",0')
        Set-ItemProperty -LiteralPath $u -Name NoModify -Value 1 -Type DWord
        $m = MfrKey $e
        New-Item -Path $m -Force | Out-Null
        Set-ItemProperty -LiteralPath $m -Name '(default)' -Value $where
        New-Item -Path (RunKey $e) -Force | Out-Null
        Set-ItemProperty -LiteralPath (RunKey $e) -Name $script:Acc.ProductName -Value ('"' + (Join-Path $where $script:Acc.MainBinaryName) + '"')
        foreach ($l in (StartLnk $e), (DeskLnk $e)) {
            $bytes = [Text.Encoding]::Unicode.GetBytes("LNK-FAKE|" + (Join-Path $where $script:Acc.MainBinaryName))
            [IO.File]::WriteAllBytes($l, $bytes)
        }
    }
    function script:Snap($e) {
        $defs = Get-HarnessSurfaceDefinition -RegistryRoot $e.Reg -ShortcutDir $e.Shortcuts
        $h = [ordered]@{}
        foreach ($d in $defs) { $h[$d.Id] = Get-SurfaceSnapshot -Surface $d }
        $h
    }
    function script:New-J($e, [string]$version = '1.2.0') {
        New-HarnessJournal -RunId $e.RunId -InstallDir $e.InstallDir -InstallVersion $version -RegistryRoot $e.Reg -ShortcutDir $e.Shortcuts -JournalDir $e.Journal -HarnessRoot $e.Harness
    }
    function script:Recover($e, [scriptblock]$Barrier) {
        $p = @{ RunId = $e.RunId; RegistryRoot = $e.Reg; ShortcutDir = $e.Shortcuts; JournalDir = $e.Journal; HarnessRoot = $e.Harness; SkipProcessKill = $true }
        if ($Barrier) { $p.Barrier = $Barrier }
        Invoke-HarnessRecovery @p
    }
    function script:Actions($r) { ($r.Surfaces | ForEach-Object { "$($_.Id)=$($_.Action)" }) -join ',' }
    function script:Add-Exe($e, [string]$where) { New-Item -ItemType Directory -Force -Path $where | Out-Null; Set-Content -LiteralPath (Join-Path $where $script:Acc.MainBinaryName) -Value 'x' }
}

Describe 'Identity allow-list and surface definitions' {
    It 'derives only acceptance-identity surfaces (never production names)' {
        $defs = Get-HarnessSurfaceDefinition -RegistryRoot 'HKCU:\Software\SnapmakerStudioHarnessTest\x' -ShortcutDir (Join-Path ([IO.Path]::GetTempPath()) 'ssh-defs-only')
        $defs.Count | Should -Be 5
        foreach ($d in $defs) {
            $text = "$($d.KeyPath)|$($d.ValueName)|$($d.FilePath)"
            $text | Should -Not -Match 'DeadlyVirusIn'
            $text | Should -Not -Match 'Snapmaker Studio(?! Acceptance)'
        }
        ($defs | Where-Object Id -eq 'RememberedLocationKey').KeyPath | Should -Be "HKCU:\Software\SnapmakerStudioHarnessTest\x\$($script:Acc.Manufacturer)\$($script:Acc.ProductName)"
    }
}

Describe 'Journal persistence' {
    BeforeEach { $script:e = New-Env }
    AfterEach { Remove-Env $script:e }
    It 'writes before-snapshots with absence markers, atomically, leaving no temp files' {
        $j = New-J $script:e
        foreach ($id in 'UninstallKey', 'RememberedLocationKey', 'RunValue', 'StartMenuShortcut', 'DesktopShortcut') { $j['surfaces'][$id]['before']['exists'] | Should -BeFalse }
        @(Get-ChildItem $script:e.Journal).Name | Should -Be @("$($script:e.RunId).json")
        $j['generation'] | Should -Match '^[0-9a-f-]{36}$'
    }
    It 'refuses to overwrite an existing journal and an install dir outside the harness install tree' {
        [void](New-J $script:e)
        { New-J $script:e } | Should -Throw '*already exists*'
        { New-HarnessJournal -RunId 'run-other-0001' -InstallDir (Join-Path $script:e.Dir 'SnapmakerStudio-Harness\work\x') -InstallVersion '1.2.0' -RegistryRoot $script:e.Reg -ShortcutDir $script:e.Shortcuts -JournalDir $script:e.Journal -HarnessRoot $script:e.Harness } | Should -Throw '*install dir is not inside the harness-owned tree*'
    }
    It 'Set-JournalOwnedAfter records owned-after fingerprints and hashes' {
        $j = New-J $script:e
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        [IO.File]::WriteAllBytes((Join-Path $script:e.InstallDir 'uninstall.exe'), [byte[]](1, 2, 3))
        $j2 = Set-JournalOwnedAfter -Journal $j -InstallerSha256 ('AB' * 32) -RegistryRoot $script:e.Reg -ShortcutDir $script:e.Shortcuts -JournalDir $script:e.Journal -HarnessRoot $script:e.Harness
        $j2['surfaces']['UninstallKey']['ownedAfter']['exists'] | Should -BeTrue
        $j2['surfaces']['UninstallKey']['ownedAfterFingerprint'] | Should -Match '^[0-9a-f]{64}$'
        $j2['uninstallerSha256'] | Should -Be (Get-FileSha256 -Path (Join-Path $script:e.InstallDir 'uninstall.exe'))
        $j2['state'] | Should -Be 'installed'
        $j2['generation'] | Should -Be $j['generation']
    }
    It 'Update-HarnessJournal refuses when the generation token changed underneath' {
        $j = New-J $script:e
        $raw = Get-Content (Get-JournalPath -RunId $script:e.RunId -JournalDir $script:e.Journal) -Raw | ConvertFrom-Json -AsHashtable
        $raw['generation'] = [guid]::NewGuid().ToString()
        [void](Save-HarnessJournal -Journal $raw -JournalDir $script:e.Journal)
        { Update-HarnessJournal -Journal $j -JournalDir $script:e.Journal -HarnessRoot $script:e.Harness -Mutate { param($x) $x['state'] = 'x' } } | Should -Throw '*generation*'
    }
}

Describe 'Recovery decision table' {
    BeforeEach { $script:e = New-Env }
    AfterEach { Remove-Env $script:e }

    It 'equals-before: no-op, finalises the journal, touches nothing' {
        [void](New-J $script:e)
        $before = Snap $script:e | ConvertTo-Json -Depth 12
        $r = Recover $script:e
        (Actions $r) | Should -Be 'UninstallKey=noop,RememberedLocationKey=noop,RunValue=noop,StartMenuShortcut=noop,DesktopShortcut=noop'
        $r.Finalized | Should -BeTrue
        $r.ExitCode | Should -Be 0
        Test-Path $r.FinalPath | Should -BeTrue
        Test-Path (Get-JournalPath -RunId $script:e.RunId -JournalDir $script:e.Journal) | Should -BeFalse
        (Snap $script:e | ConvertTo-Json -Depth 12) | Should -Be $before
    }

    It 'points into harness and exe missing, nothing existed before: deletes every owned surface, never the publisher key' {
        [void](New-J $script:e)
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        $r = Recover $script:e
        (Actions $r) | Should -Be 'UninstallKey=restored,RememberedLocationKey=restored,RunValue=restored,StartMenuShortcut=restored,DesktopShortcut=restored'
        $r.Finalized | Should -BeTrue
        Test-Path (UninstKey $script:e) | Should -BeFalse
        Test-Path (MfrKey $script:e) | Should -BeFalse
        Test-Path (StartLnk $script:e) | Should -BeFalse
        Test-Path (DeskLnk $script:e) | Should -BeFalse
        (Get-ItemProperty (RunKey $script:e)).PSObject.Properties.Name | Should -Not -Contain $script:Acc.ProductName
        # parent (publisher) key is shared: recovery must not delete it
        Test-Path (Key $script:e $script:Acc.Manufacturer) | Should -BeTrue
    }

    It 'restores a prior state exactly, preserving value kinds (DWord high bit, QWord, Binary, MultiString, ExpandString) and lnk bytes' {
        $u = UninstKey $script:e
        New-Item -Path $u -Force | Out-Null
        Set-ItemProperty -LiteralPath $u -Name Expand -Value '%TEMP%\x' -Type ExpandString
        Set-ItemProperty -LiteralPath $u -Name Multi -Value @('a', 'b') -Type MultiString
        Set-ItemProperty -LiteralPath $u -Name Bin -Value ([byte[]](0, 1, 255)) -Type Binary
        Set-ItemProperty -LiteralPath $u -Name Big -Value ([int]-1) -Type DWord
        Set-ItemProperty -LiteralPath $u -Name Q -Value ([int64]5000000000) -Type QWord
        Set-ItemProperty -LiteralPath $u -Name DisplayVersion -Value '0.9.0'
        Set-ItemProperty -LiteralPath $u -Name InstallLocation -Value 'D:\some\other\real\place'
        [IO.File]::WriteAllBytes((StartLnk $script:e), [byte[]](1, 2, 3, 4))
        $orig = Snap $script:e | ConvertTo-Json -Depth 12
        [void](New-J $script:e)
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        $r = Recover $script:e
        $r.Finalized | Should -BeTrue -Because (Actions $r)
        (Snap $script:e | ConvertTo-Json -Depth 12) | Should -Be $orig
        (Get-Item -LiteralPath $u).GetValueKind('Big') | Should -Be 'DWord'
        (Get-Item -LiteralPath $u).GetValueKind('Q') | Should -Be 'QWord'
        (Get-Item -LiteralPath $u).GetValueKind('Expand') | Should -Be 'ExpandString'
        (Get-Item -LiteralPath $u).GetValue('Expand', $null, 'DoNotExpandEnvironmentNames') | Should -Be '%TEMP%\x'
    }

    It 'completed install (exe present in harness dir): needs-uninstall, nothing modified, journal kept, exit 3' {
        [void](New-J $script:e)
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        Add-Exe $script:e $script:e.InstallDir
        $state = Snap $script:e | ConvertTo-Json -Depth 12
        $r = Recover $script:e
        (Actions $r) | Should -Match 'UninstallKey=needs-uninstall'
        $r.Finalized | Should -BeFalse
        $r.ExitCode | Should -Be 3
        (Snap $script:e | ConvertTo-Json -Depth 12) | Should -Be $state
        Test-Path (Get-JournalPath -RunId $script:e.RunId -JournalDir $script:e.Journal) | Should -BeTrue
    }

    It 'a real install dir WITH an exe (outside harness) is never touched: superseded' {
        [void](New-J $script:e)
        $real = Join-Path $script:e.Dir 'real-install'
        Add-Exe $script:e $real
        Set-InstalledState $script:e $real '1.2.0'
        $state = Snap $script:e | ConvertTo-Json -Depth 12
        $r = Recover $script:e
        (Actions $r) | Should -Match 'UninstallKey=superseded'
        (Snap $script:e | ConvertTo-Json -Depth 12) | Should -Be $state
    }

    It 'a semver-NEWER registration is never touched, even if it points into the harness dir with exe missing' {
        [void](New-J $script:e '1.2.0')
        Set-InstalledState $script:e $script:e.InstallDir '9.9.9'
        $state = Snap $script:e | ConvertTo-Json -Depth 12
        $r = Recover $script:e
        (Actions $r) | Should -Match 'UninstallKey=superseded'
        (Snap $script:e | ConvertTo-Json -Depth 12) | Should -Be $state
    }

    It 'an unparseable version is treated as newer (fail closed)' {
        [void](New-J $script:e '1.2.0')
        Set-InstalledState $script:e $script:e.InstallDir 'banana'
        (Actions (Recover $script:e)) | Should -Match 'UninstallKey=superseded'
    }

    It 'same version but a DIFFERENT real path is never touched' {
        [void](New-J $script:e '1.2.0')
        Set-InstalledState $script:e (Join-Path $script:e.Dir 'elsewhere') '1.2.0'
        $state = Snap $script:e | ConvertTo-Json -Depth 12
        $r = Recover $script:e
        (Actions $r) | Should -Match 'UninstallKey=superseded'
        (Snap $script:e | ConvertTo-Json -Depth 12) | Should -Be $state
    }

    It 'prefix-neighbour install dir is not "inside" the journaled dir' {
        [void](New-J $script:e)
        Set-InstalledState $script:e ($script:e.InstallDir + '-evil') '1.2.0'
        (Actions (Recover $script:e)) | Should -Match 'UninstallKey=superseded'
    }

    It 'same-version / same-path reuse: before already equals the earlier install, so recovery is a no-op even with exe present' {
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        Add-Exe $script:e $script:e.InstallDir
        [void](New-J $script:e)
        $j = Get-Content (Get-JournalPath -RunId $script:e.RunId -JournalDir $script:e.Journal) -Raw | ConvertFrom-Json -AsHashtable
        $r = Recover $script:e
        (Actions $r) | Should -Not -Match 'restored|needs-uninstall'
        $r.Finalized | Should -BeTrue
        Test-Path (UninstKey $script:e) | Should -BeTrue
    }

    It 'never touches production registrations or the shared publisher subtree' {
        $pu = Key $script:e "Microsoft\Windows\CurrentVersion\Uninstall\$($script:Prod.ProductName)"
        $pm = Key $script:e "$($script:Prod.Manufacturer)\$($script:Prod.ProductName)"
        New-Item -Path $pu -Force | Out-Null; Set-ItemProperty -LiteralPath $pu -Name InstallLocation -Value 'D:\prod'
        New-Item -Path $pm -Force | Out-Null; Set-ItemProperty -LiteralPath $pm -Name '(default)' -Value 'D:\prod'
        $prodLnk = Join-Path $script:e.Shortcuts "StartMenu\$($script:Prod.ProductName).lnk"
        [IO.File]::WriteAllBytes($prodLnk, [byte[]](7, 7))
        [void](New-J $script:e)
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        Set-ItemProperty -LiteralPath (RunKey $script:e) -Name $script:Prod.ProductName -Value 'D:\prod\app.exe'
        $r = Recover $script:e
        $r.Finalized | Should -BeTrue
        (Get-ItemProperty -LiteralPath $pu).InstallLocation | Should -Be 'D:\prod'
        (Get-ItemProperty -LiteralPath $pm).'(default)' | Should -Be 'D:\prod'
        (Get-ItemProperty (RunKey $script:e)).($script:Prod.ProductName) | Should -Be 'D:\prod\app.exe'
        [IO.File]::ReadAllBytes($prodLnk) | Should -Be ([byte[]](7, 7))
    }

    It 'restores from owned-after (journal A) when current still equals what this run installed and exe is gone' {
        $j = New-J $script:e
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        [void](Set-JournalOwnedAfter -Journal $j -RegistryRoot $script:e.Reg -ShortcutDir $script:e.Shortcuts -JournalDir $script:e.Journal -HarnessRoot $script:e.Harness)
        $r = Recover $script:e
        $r.Finalized | Should -BeTrue
        Test-Path (UninstKey $script:e) | Should -BeFalse
    }
}

Describe 'Journal missing / corrupt => no destructive action' {
    BeforeEach { $script:e = New-Env }
    AfterEach { Remove-Env $script:e }
    It 'missing journal throws JournalMissing and mutates nothing' {
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        $state = Snap $script:e | ConvertTo-Json -Depth 12
        { Recover $script:e } | Should -Throw 'JournalMissing*'
        (Snap $script:e | ConvertTo-Json -Depth 12) | Should -Be $state
    }
    It 'corrupt journals (garbage, truncated, wrong schema, unknown surface id, install dir outside harness) throw JournalCorrupt and mutate nothing' {
        [void](New-J $script:e)
        $path = Get-JournalPath -RunId $script:e.RunId -JournalDir $script:e.Journal
        $good = Get-Content $path -Raw
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        $state = Snap $script:e | ConvertTo-Json -Depth 12
        $variants = @{
            garbage   = 'not json {{{'
            truncated = $good.Substring(0, [int]($good.Length / 2))
            schema    = ($good -replace '"schema":\s*1', '"schema": 99')
            unknownId = ($good -replace '"UninstallKey"', '"HKLM_Something"')
            outside   = ($good -replace [regex]::Escape(($script:e.InstallDir | ConvertTo-Json).Trim('"')), (Join-Path $script:e.Dir 'elsewhere' | ConvertTo-Json).Trim('"'))
            emptyFile = ''
        }
        foreach ($k in $variants.Keys) {
            Set-Content -LiteralPath $path -Value $variants[$k] -NoNewline
            { Recover $script:e } | Should -Throw 'JournalCorrupt*' -Because $k
            (Snap $script:e | ConvertTo-Json -Depth 12) | Should -Be $state -Because $k
        }
    }
    It 'Repair-Harness.ps1 exits 2 on a corrupt journal, 2 on a missing explicit RunId, 0 when there are no journals' {
        $lockName = "Local\ssh-repair-test-$($script:e.Guid)"
        $common = @('-NoProfile', '-File', $script:RepairScript, '-RegistryRoot', $script:e.Reg, '-ShortcutDir', $script:e.Shortcuts, '-JournalDir', $script:e.Journal, '-HarnessRoot', $script:e.Harness, '-LockMutexName', $lockName, '-SkipProcessKill')
        & pwsh @common | Out-Null
        $LASTEXITCODE | Should -Be 0
        & pwsh @common -RunId 'run-missing-0001' | Out-Null
        $LASTEXITCODE | Should -Be 2
        [void](New-J $script:e)
        Set-Content -LiteralPath (Get-JournalPath -RunId $script:e.RunId -JournalDir $script:e.Journal) -Value 'garbage'
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        & pwsh @common | Out-Null
        $LASTEXITCODE | Should -Be 2
        Test-Path (UninstKey $script:e) | Should -BeTrue
    }
    It 'Repair-Harness.ps1 recovers a healthy journal (exit 0) and reports needs-uninstall as exit 3' {
        $lockName = "Local\ssh-repair-test-$($script:e.Guid)"
        $common = @('-NoProfile', '-File', $script:RepairScript, '-RegistryRoot', $script:e.Reg, '-ShortcutDir', $script:e.Shortcuts, '-JournalDir', $script:e.Journal, '-HarnessRoot', $script:e.Harness, '-LockMutexName', $lockName, '-SkipProcessKill')
        [void](New-J $script:e)
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        Add-Exe $script:e $script:e.InstallDir
        & pwsh @common | Out-Null
        $LASTEXITCODE | Should -Be 3
        Remove-Item (Join-Path $script:e.InstallDir $script:Acc.MainBinaryName)
        & pwsh @common | Out-Null
        $LASTEXITCODE | Should -Be 0
        Test-Path (UninstKey $script:e) | Should -BeFalse
    }
}

Describe 'Crash-during-recovery (compare-and-swap, state machine only)' {
    BeforeEach { $script:e = New-Env }
    AfterEach { Remove-Env $script:e }

    It 'crash after a mutation but before the journal update: re-run completes (surface now equals before)' {
        [void](New-J $script:e)
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        { Recover $script:e { param($p) if ($p -eq 'after-mutate:UninstallKey') { throw 'SIMULATED-CRASH' } } } | Should -Throw '*SIMULATED-CRASH*'
        Test-Path (UninstKey $script:e) | Should -BeFalse
        $r = Recover $script:e
        $r.Finalized | Should -BeTrue
        (Actions $r) | Should -Match 'UninstallKey=noop'
        (Actions $r) | Should -Match 'RunValue=restored'
    }
    It 'double crash at different barriers still converges' {
        [void](New-J $script:e)
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        { Recover $script:e { param($p) if ($p -eq 'before-mutate:RememberedLocationKey') { throw 'SIMULATED-CRASH-1' } } } | Should -Throw '*CRASH-1*'
        { Recover $script:e { param($p) if ($p -eq 'after-journal:RunValue') { throw 'SIMULATED-CRASH-2' } } } | Should -Throw '*CRASH-2*'
        $r = Recover $script:e
        $r.Finalized | Should -BeTrue
        Test-Path (UninstKey $script:e) | Should -BeFalse
        Test-Path (MfrKey $script:e) | Should -BeFalse
        Test-Path (StartLnk $script:e) | Should -BeFalse
    }
    It 'CAS: a surface changed by someone else between decision and mutation is NOT overwritten' {
        [void](New-J $script:e)
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        $e2 = $script:e
        $r = Recover $script:e { param($p) if ($p -eq 'before-mutate:RunValue') { Set-ItemProperty -LiteralPath (RunKey $e2) -Name $script:Acc.ProductName -Value 'CHANGED-BY-SOMEONE' } }
        (Actions $r) | Should -Match 'RunValue=cas-failed'
        $r.Finalized | Should -BeFalse
        (Get-ItemProperty (RunKey $script:e)).($script:Acc.ProductName) | Should -Be 'CHANGED-BY-SOMEONE'
        (Actions $r) | Should -Match 'UninstallKey=restored'
    }
    It 'CAS: a journal whose generation token changed mid-recovery is not acted on' {
        [void](New-J $script:e)
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        $e2 = $script:e
        $r = Recover $script:e {
            param($p)
            if ($p -eq 'before-mutate:UninstallKey') {
                $path = Get-JournalPath -RunId $e2.RunId -JournalDir $e2.Journal
                $raw = Get-Content $path -Raw | ConvertFrom-Json -AsHashtable
                $raw['generation'] = [guid]::NewGuid().ToString()
                [void](Save-HarnessJournal -Journal $raw -JournalDir $e2.Journal)
            }
        }
        (Actions $r) | Should -Match 'UninstallKey=cas-failed'
        Test-Path (UninstKey $script:e) | Should -BeTrue
    }
    It 'an already-restored surface is not touched again' {
        [void](New-J $script:e)
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        { Recover $script:e { param($p) if ($p -eq 'after-journal:UninstallKey') { throw 'SIMULATED-CRASH' } } } | Should -Throw
        # someone reinstalls the uninstall key (same content) after it was recovered and journaled
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        $r = Recover $script:e
        (Actions $r) | Should -Match 'UninstallKey=already-restored'
        Test-Path (UninstKey $script:e) | Should -BeTrue
    }
}

Describe 'Tracked process matching' {
    BeforeEach { $script:e = New-Env }
    AfterEach { Remove-Env $script:e }
    It 'never matches a dead pid, a wrong start time, or an image outside the harness dir' {
        $ticks = Get-ProcessStartTicks -ProcessId $PID
        Test-TrackedProcessMatch -Tracked @{ pid = 2147483000; startTicks = 1 } -HarnessRoot $script:e.Harness | Should -BeFalse
        Test-TrackedProcessMatch -Tracked @{ pid = $PID; startTicks = 1 } -HarnessRoot $script:e.Harness | Should -BeFalse
        # right pid + start time, but pwsh lives outside the (scratch) harness dir
        Test-TrackedProcessMatch -Tracked @{ pid = $PID; startTicks = $ticks } -HarnessRoot $script:e.Harness | Should -BeFalse
    }
}

Describe 'Compare-SemVerStrict' {
    It 'orders versions and pre-releases, null on garbage' {
        Compare-SemVerStrict '1.2.0' '1.2.0' | Should -Be 0
        Compare-SemVerStrict '1.2.1' '1.2.0' | Should -Be 1
        Compare-SemVerStrict '1.2.0-beta.3' '1.2.0' | Should -Be -1
        Compare-SemVerStrict '1.2.0-beta.10' '1.2.0-beta.9' | Should -Be 1
        Compare-SemVerStrict '0.4.0-beta.20.2' '1.0.0' | Should -Be -1
        Compare-SemVerStrict 'x' '1.0.0' | Should -BeNullOrEmpty
    }
}

Describe 'B3: journal is fully validated before any mutation' {
    BeforeEach {
        $script:e = New-Env
        function script:Tamper($e, [scriptblock]$Mutate) {
            $p = Get-JournalPath -RunId $e.RunId -JournalDir $e.Journal
            $h = Get-Content $p -Raw | ConvertFrom-Json -AsHashtable -DateKind String -Depth 32
            & $Mutate $h
            [void](Save-HarnessJournal -Journal $h -JournalDir $e.Journal)
        }
    }
    AfterEach { Remove-Env $script:e }

    It 'tampered ownedAfter with a stale fingerprint + same-version different-path registration + exe missing is NOT restored or deleted' {
        $j = New-J $script:e
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        [void](Set-JournalOwnedAfter -Journal $j -RegistryRoot $script:e.Reg -ShortcutDir $script:e.Shortcuts -JournalDir $script:e.Journal -HarnessRoot $script:e.Harness)
        # someone else's registration: same version, different real path (exe for the journaled dir is missing)
        Set-InstalledState $script:e (Join-Path $script:e.Dir 'someone-elses-install') '1.2.0'
        $state = Snap $script:e | ConvertTo-Json -Depth 12
        $cur = Snap $script:e
        Tamper $script:e { param($h) $h['surfaces']['UninstallKey']['ownedAfter'] = $cur['UninstallKey'] }   # fingerprint left stale
        { Recover $script:e } | Should -Throw 'JournalCorrupt*fingerprint*'
        (Snap $script:e | ConvertTo-Json -Depth 12) | Should -Be $state
    }
    It 'control: the same forgery WITH a recomputed fingerprint is what the fingerprint check exists to catch (it would restore)' {
        $j = New-J $script:e
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        [void](Set-JournalOwnedAfter -Journal $j -RegistryRoot $script:e.Reg -ShortcutDir $script:e.Shortcuts -JournalDir $script:e.Journal -HarnessRoot $script:e.Harness)
        Set-InstalledState $script:e (Join-Path $script:e.Dir 'someone-elses-install') '1.2.0'
        $cur = Snap $script:e
        Tamper $script:e { param($h) $h['surfaces']['UninstallKey']['ownedAfter'] = $cur['UninstallKey']; $h['surfaces']['UninstallKey']['ownedAfterFingerprint'] = Get-SnapshotFingerprint $cur['UninstallKey'] }
        (Actions (Recover $script:e)) | Should -Match 'UninstallKey=restored'
    }
    It 'malformed base64 in a LATE surface yields zero mutations to earlier surfaces' {
        [IO.File]::WriteAllBytes((DeskLnk $script:e), [byte[]](1, 2, 3))
        [void](New-J $script:e)
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'      # exe missing => every earlier surface would be restored
        $state = Snap $script:e | ConvertTo-Json -Depth 12
        Tamper $script:e { param($h) $h['surfaces']['DesktopShortcut']['before']['bytesB64'] = '***not-base64***' }
        { Recover $script:e } | Should -Throw 'JournalCorrupt*DesktopShortcut*'
        (Snap $script:e | ConvertTo-Json -Depth 12) | Should -Be $state
    }
    It 'every malformed field is JournalCorrupt and mutates nothing: <name>' -ForEach @(
        @{ name = 'DWord data not numeric'; m = { param($h) $h['surfaces']['UninstallKey']['before'] = [ordered]@{ type = 'RegKey'; exists = $true; subkeys = @(); values = @([ordered]@{ name = 'x'; kind = 'DWord'; data = 'abc' }) } } }
        @{ name = 'unknown value kind'; m = { param($h) $h['surfaces']['UninstallKey']['before'] = [ordered]@{ type = 'RegKey'; exists = $true; subkeys = @(); values = @([ordered]@{ name = 'x'; kind = 'Unknown'; data = 'a' }) } } }
        @{ name = 'snapshot type mismatch'; m = { param($h) $h['surfaces']['RunValue']['before'] = [ordered]@{ type = 'File'; exists = $false } } }
        @{ name = 'restored flag not bool'; m = { param($h) $h['restored']['RunValue'] = 'yes' } }
        @{ name = 'restored flag missing'; m = { param($h) $h['restored'].Remove('RunValue') } }
        @{ name = 'sha256 malformed'; m = { param($h) $h['installerSha256'] = 'zz' } }
        @{ name = 'process record malformed'; m = { param($h) $h['processes'] = @([ordered]@{ pid = 'x' }) } }
        @{ name = 'state invalid'; m = { param($h) $h['state'] = 'bogus' } }
        @{ name = 'file size lies'; m = { param($h) $h['surfaces']['StartMenuShortcut']['before'] = [ordered]@{ type = 'File'; exists = $true; size = 99; sha256 = ('0' * 64); bytesB64 = 'AQID' } } }
        @{ name = 'installed state without ownedAfter'; m = { param($h) $h['state'] = 'installed' } }
    ) {
        [void](New-J $script:e)
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        $state = Snap $script:e | ConvertTo-Json -Depth 12
        Tamper $script:e $m
        { Recover $script:e } | Should -Throw 'JournalCorrupt*'
        (Snap $script:e | ConvertTo-Json -Depth 12) | Should -Be $state
    }
}

Describe 'F4: installVersion is mandatory and strict semver; one journal per upgrade phase' {
    BeforeEach { $script:e = New-Env }
    AfterEach { Remove-Env $script:e }
    It 'New-HarnessJournal refuses a missing or invalid version: <v>' -ForEach @(@{ v = $null }, @{ v = '' }, @{ v = 'banana' }, @{ v = '1.2' }) {
        { New-HarnessJournal -RunId $script:e.RunId -InstallDir $script:e.InstallDir -InstallVersion $v -RegistryRoot $script:e.Reg -ShortcutDir $script:e.Shortcuts -JournalDir $script:e.Journal -HarnessRoot $script:e.Harness } | Should -Throw '*InstallVersion*'
        Test-Path (Get-JournalPath -RunId $script:e.RunId -JournalDir $script:e.Journal) | Should -BeFalse
    }
    It 'Read-HarnessJournal treats a null or invalid stored version as corrupt' {
        [void](New-J $script:e)
        foreach ($bad in $null, 'banana') {
            $p = Get-JournalPath -RunId $script:e.RunId -JournalDir $script:e.Journal
            $h = Get-Content $p -Raw | ConvertFrom-Json -AsHashtable -DateKind String -Depth 32
            $h['installVersion'] = $bad
            [void](Save-HarnessJournal -Journal $h -JournalDir $script:e.Journal)
            { Read-HarnessJournal -RunId $script:e.RunId -JournalDir $script:e.Journal -HarnessRoot $script:e.Harness } | Should -Throw 'JournalCorrupt*installVersion*'
        }
    }
    It 'two-phase upgrade (O1): phase 2 recovery returns to the phase-1 installed state, not further back' {
        # phase 1: old rewrap installs 1.0.0 (its own journal)
        $e1 = $script:e
        [void](New-HarnessJournal -RunId "$($e1.RunId)-p1" -InstallDir $e1.InstallDir -InstallVersion '1.0.0' -RegistryRoot $e1.Reg -ShortcutDir $e1.Shortcuts -JournalDir $e1.Journal -HarnessRoot $e1.Harness)
        Set-InstalledState $e1 $e1.InstallDir '1.0.0'
        $phase1State = Snap $e1 | ConvertTo-Json -Depth 12
        # phase 2: new rewrap upgrades to 2.0.0 in another dir; its own journal's 'before' is phase 1's state
        $dir2 = Join-Path $e1.Dir 'SnapmakerStudio-Harness\install\run2'
        New-Item -ItemType Directory -Force -Path $dir2 | Out-Null
        [void](New-HarnessJournal -RunId "$($e1.RunId)-p2" -InstallDir $dir2 -InstallVersion '2.0.0' -RegistryRoot $e1.Reg -ShortcutDir $e1.Shortcuts -JournalDir $e1.Journal -HarnessRoot $e1.Harness)
        Set-InstalledState $e1 $dir2 '2.0.0'
        $p = @{ RunId = "$($e1.RunId)-p2"; RegistryRoot = $e1.Reg; ShortcutDir = $e1.Shortcuts; JournalDir = $e1.Journal; HarnessRoot = $e1.Harness; SkipProcessKill = $true }
        $r = Invoke-HarnessRecovery @p
        $r.Finalized | Should -BeTrue
        (Snap $e1 | ConvertTo-Json -Depth 12) | Should -Be $phase1State
    }
}

BeforeDiscovery {
    $prodName = (Import-PowerShellDataFile -LiteralPath (Join-Path $PSScriptRoot '..\lib\HarnessIdentity.psd1')).Production
    $targets = @(
        @{ kind = 'engine dir'; path = (Join-Path $env:LOCALAPPDATA $prodName.EngineDataDirName) }
        @{ kind = 'default install dir'; path = (Join-Path $env:LOCALAPPDATA $prodName.DefaultInstallDirName) }
        @{ kind = 'app-data dir'; path = (Join-Path $env:APPDATA $prodName.BundleId) }
        @{ kind = 'bare parent (LOCALAPPDATA)'; path = $env:LOCALAPPDATA }
    )
    $script:ShortcutCases = foreach ($p in 'ShortcutDir', 'StartMenuDir', 'DesktopDir') { foreach ($t in $targets) { @{ param = $p; kind = $t.kind; path = $t.path } } }
}

Describe 'Shortcut-dir overrides may not overlap production locations (entry points: definition, New-, Recovery)' {
    BeforeEach { $script:e = New-Env }
    AfterEach { Remove-Env $script:e }

    It '<param> -> <kind> is refused everywhere and mutates nothing' -ForEach $script:ShortcutCases {
        $ov = @{ $param = $path }
        # 1. the definition builder
        { Get-HarnessSurfaceDefinition -RegistryRoot $script:e.Reg @ov } | Should -Throw '*Refused*'
        # 2. journal creation captures nothing and writes no journal
        { New-HarnessJournal -RunId $script:e.RunId -InstallDir $script:e.InstallDir -InstallVersion '1.2.0' -RegistryRoot $script:e.Reg -JournalDir $script:e.Journal -HarnessRoot $script:e.Harness @ov } | Should -Throw '*Refused*'
        Test-Path (Get-JournalPath -RunId $script:e.RunId -JournalDir $script:e.Journal) | Should -BeFalse
        # 3. recovery of a healthy journal (created with safe dirs) refuses an unsafe override and changes nothing
        [void](New-J $script:e)
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'       # exe missing => would be restored/deleted
        $state = Snap $script:e | ConvertTo-Json -Depth 12
        $jpath = Get-JournalPath -RunId $script:e.RunId -JournalDir $script:e.Journal
        $jbytes = [IO.File]::ReadAllBytes($jpath)
        $p = @{ RunId = $script:e.RunId; RegistryRoot = $script:e.Reg; JournalDir = $script:e.Journal; HarnessRoot = $script:e.Harness; SkipProcessKill = $true }
        if ($param -ne 'ShortcutDir') { $p.ShortcutDir = $script:e.Shortcuts }
        { Invoke-HarnessRecovery @p @ov } | Should -Throw '*Refused*'
        (Snap $script:e | ConvertTo-Json -Depth 12) | Should -Be $state
        [IO.File]::ReadAllBytes($jpath) | Should -Be $jbytes
        # 4. owned-after capture
        $j = Read-HarnessJournal -RunId $script:e.RunId -JournalDir $script:e.Journal -HarnessRoot $script:e.Harness
        { Set-JournalOwnedAfter -Journal $j -RegistryRoot $script:e.Reg -JournalDir $script:e.Journal -HarnessRoot $script:e.Harness @ov } | Should -Throw '*Refused*'
    }
    It 'a legitimate temp-dir override still works' {
        $tmp = Join-Path $script:e.Dir 'legit'
        { Get-HarnessSurfaceDefinition -RegistryRoot $script:e.Reg -StartMenuDir $tmp -DesktopDir $tmp } | Should -Not -Throw
        { Get-HarnessSurfaceDefinition -RegistryRoot $script:e.Reg -ShortcutDir $tmp } | Should -Not -Throw
    }
}

Describe 'Strict semver (no leading zeros, no empty prerelease identifiers)' {
    It 'Compare-SemVerStrict returns null (unparseable) for <v>' -ForEach @(
        @{ v = '01.2.3' }, @{ v = '1.02.3' }, @{ v = '1.2.03' }, @{ v = '1.2.3-01' }, @{ v = '1.2.3-alpha..1' }, @{ v = '1.2.3-' }, @{ v = '1.2.3-alpha.' }, @{ v = '1.2.3-.x' }
    ) {
        Compare-SemVerStrict $v '1.0.0' | Should -BeNullOrEmpty
    }
    It 'still parses valid versions, including 0 cores and numeric/alphanumeric prerelease ids' -ForEach @(
        @{ v = '0.0.0' }, @{ v = '1.2.3' }, @{ v = '1.2.3-0' }, @{ v = '1.2.3-alpha.1' }, @{ v = '1.2.3-beta.20.2' }, @{ v = '1.2.3-0a' }, @{ v = '1.2.3-x-y.7+build.5' }
    ) {
        Compare-SemVerStrict $v $v | Should -Be 0
    }
    It 'New-HarnessJournal refuses a leading-zero version' {
        $e = New-Env
        try {
            { New-HarnessJournal -RunId $e.RunId -InstallDir $e.InstallDir -InstallVersion '01.2.3' -RegistryRoot $e.Reg -ShortcutDir $e.Shortcuts -JournalDir $e.Journal -HarnessRoot $e.Harness } | Should -Throw '*InstallVersion*'
        } finally { Remove-Env $e }
    }
}

Describe 'Repair-Harness.ps1 refuses production-overlapping shortcut dirs' {
    BeforeEach { $script:e = New-Env }
    AfterEach { Remove-Env $script:e }
    It 'exits non-zero and leaves the journal and surfaces untouched' {
        [void](New-J $script:e)
        Set-InstalledState $script:e $script:e.InstallDir '1.2.0'
        $state = Snap $script:e | ConvertTo-Json -Depth 12
        $jp = Get-JournalPath -RunId $script:e.RunId -JournalDir $script:e.Journal
        $bad = Join-Path $env:LOCALAPPDATA $script:Prod.EngineDataDirName
        & pwsh -NoProfile -File $script:RepairScript -RegistryRoot $script:e.Reg -ShortcutDir $bad -JournalDir $script:e.Journal -HarnessRoot $script:e.Harness -LockMutexName "Local\ssh-repair-test-$($script:e.Guid)" -SkipProcessKill | Out-Null
        $LASTEXITCODE | Should -Be 1
        Test-Path $jp | Should -BeTrue
        (Snap $script:e | ConvertTo-Json -Depth 12) | Should -Be $state
    }
}

Describe 'Override allowlist end-to-end (definition, New-, Recovery, Set-JournalOwnedAfter, Repair-Harness.ps1)' {
    BeforeEach { $script:e = New-Env }
    AfterEach { Remove-Env $script:e }

    It 'every bad override form x every override parameter is refused with zero mutation and an unchanged journal' {
        $e = $script:e
        $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
        # Fixtures: a production-like dir holding a decoy acceptance-named shortcut, reached through junctions.
        $prodLike = Join-Path $e.Dir 'prodlike'
        New-Item -ItemType Directory -Force -Path (Join-Path $prodLike 'sm') | Out-Null
        $decoy = Join-Path $prodLike "sm\$($script:Acc.ProductName).lnk"
        [IO.File]::WriteAllBytes($decoy, [Text.Encoding]::Unicode.GetBytes("LNK-FAKE|$($e.InstallDir)\x"))
        $decoyBytes = [IO.File]::ReadAllBytes($decoy)
        $alias = Join-Path $e.Dir 'alias'; New-Item -ItemType Junction -Path $alias -Target $prodLike | Out-Null          # (i) alias -> production-like dir
        New-Item -ItemType Directory -Force -Path (Join-Path $e.Dir 'real\x') | Out-Null
        $link = Join-Path $e.Dir 'link'; New-Item -ItemType Junction -Path $link -Target (Join-Path $e.Dir 'real') | Out-Null   # (ii) ancestor junction
        $bad = [ordered]@{
            'junction alias'        = (Join-Path $alias 'sm')
            'ancestor junction'     = (Join-Path $link 'x\y')
            'extended-length'       = '\\?\C:\x\y'
            'UNC admin share'       = '\\localhost\C$\x\y'
            'device path'           = '\\.\C:\x\y'
            'dotdot relative'       = '..\x'
            'dot relative'          = '.\x'
            'drive relative'        = 'C:x'
            'alternate data stream' = (Join-Path $tempRoot "ssh-ads-$($e.Guid)\a:s")
            'temp root itself'      = $tempRoot
            'other drive'           = 'D:\x'
            'Documents outside'     = (Join-Path $env:USERPROFILE 'Documents\x')
        }
        # healthy journal made with SAFE dirs, then an installed-looking state that recovery would otherwise restore
        [void](New-J $e)
        Set-InstalledState $e $e.InstallDir '1.2.0'
        $state = Snap $e | ConvertTo-Json -Depth 12
        $jpath = Get-JournalPath -RunId $e.RunId -JournalDir $e.Journal
        $jbytes = [IO.File]::ReadAllBytes($jpath)
        $jRead = Read-HarnessJournal -RunId $e.RunId -JournalDir $e.Journal -HarnessRoot $e.Harness
        $n = 0
        foreach ($param in 'ShortcutDir', 'StartMenuDir', 'DesktopDir') {
            foreach ($name in $bad.Keys) {
                $n++; $ov = @{ $param = $bad[$name] }; $why = "$param <- $name"
                { Get-HarnessSurfaceDefinition -RegistryRoot $e.Reg @ov } | Should -Throw '*Refused*' -Because $why
                $rid = "rid-$($e.Guid.Substring(0, 8))-$n"
                { New-HarnessJournal -RunId $rid -InstallDir $e.InstallDir -InstallVersion '1.2.0' -RegistryRoot $e.Reg -JournalDir $e.Journal -HarnessRoot $e.Harness @ov } | Should -Throw '*Refused*' -Because $why
                Test-Path (Get-JournalPath -RunId $rid -JournalDir $e.Journal) | Should -BeFalse -Because $why
                $p = @{ RunId = $e.RunId; RegistryRoot = $e.Reg; JournalDir = $e.Journal; HarnessRoot = $e.Harness; SkipProcessKill = $true }
                if ($param -ne 'ShortcutDir') { $p.ShortcutDir = $e.Shortcuts }
                { Invoke-HarnessRecovery @p @ov } | Should -Throw '*Refused*' -Because $why
                { Set-JournalOwnedAfter -Journal $jRead -RegistryRoot $e.Reg -JournalDir $e.Journal -HarnessRoot $e.Harness @ov } | Should -Throw '*Refused*' -Because $why
            }
        }
        (Snap $e | ConvertTo-Json -Depth 12) | Should -Be $state
        [IO.File]::ReadAllBytes($jpath) | Should -Be $jbytes
        [IO.File]::ReadAllBytes($decoy) | Should -Be $decoyBytes
        # Repair-Harness.ps1 pass-through: nonzero exit, nothing changed
        # (Repair-Harness.ps1 exposes -ShortcutDir only; every bad form must be refused there with exit 1)
        foreach ($name in $bad.Keys) {
            & pwsh -NoProfile -File $script:RepairScript -RegistryRoot $e.Reg -JournalDir $e.Journal -HarnessRoot $e.Harness -LockMutexName "Local\ssh-repair-test-$($e.Guid)" -SkipProcessKill -ShortcutDir $bad[$name] | Out-Null
            $LASTEXITCODE | Should -Be 1 -Because $name
        }
        (Snap $e | ConvertTo-Json -Depth 12) | Should -Be $state
        [IO.File]::ReadAllBytes($jpath) | Should -Be $jbytes
        [IO.File]::ReadAllBytes($decoy) | Should -Be $decoyBytes
    }

    It 'accepts subdirs of temp, creates nothing by itself, and leaves the default harness root override usable' {
        $tmp = Join-Path $script:e.Dir 'legit-none'
        { Get-HarnessSurfaceDefinition -RegistryRoot $script:e.Reg -StartMenuDir "$tmp\sm" -DesktopDir "$tmp\dk" } | Should -Not -Throw
        Test-Path $tmp | Should -BeFalse
        { Get-HarnessSurfaceDefinition -RegistryRoot $script:e.Reg -ShortcutDir "$tmp\sc" } | Should -Not -Throw
        Test-Path $tmp | Should -BeFalse
        $defaultSub = Join-Path (Get-DefaultHarnessRoot) 'sub-none'
        { Get-JournalDir -JournalDir $defaultSub } | Should -Not -Throw
        Test-Path $defaultSub | Should -BeFalse
    }
    It 'default-resolved Start Menu / Desktop skip only the container rule (reparse rule still applies)' {
        $tmp = Join-Path $script:e.Dir 'legit'
        { Get-HarnessSurfaceDefinition -RegistryRoot $script:e.Reg -DesktopDir "$tmp\dk" } | Should -Not -Throw   # default Start Menu
        $desk = [Environment]::GetFolderPath('DesktopDirectory')
        if (Test-ContainsReparsePoint -Path $desk) {
            # e.g. a OneDrive-redirected Desktop: refused fail-closed by design
            { Get-HarnessSurfaceDefinition -RegistryRoot $script:e.Reg -StartMenuDir "$tmp\sm" } | Should -Throw '*reparse*'
        } else {
            { Get-HarnessSurfaceDefinition -RegistryRoot $script:e.Reg -StartMenuDir "$tmp\sm" } | Should -Not -Throw
        }
    }

    It 'registry roots: bad forms are refused by definition and New-HarnessJournal and create no keys' {
        $e = $script:e
        $g = $e.Guid
        foreach ($r in "HKCU:\Software\ssh-bad-$g", 'HKLM:\Software', "Registry::HKEY_CURRENT_USER\Software\ssh-bad-$g", "HKCU:\\Software", "HKCU:\Software\SnapmakerStudioHarnessTest\..\ssh-bad-$g", "$($e.Reg)\child") {
            { Get-HarnessSurfaceDefinition -RegistryRoot $r -ShortcutDir $e.Shortcuts } | Should -Throw '*Refused*' -Because $r
            { New-HarnessJournal -RunId "rid-$($g.Substring(0, 8))-r" -InstallDir $e.InstallDir -InstallVersion '1.2.0' -RegistryRoot $r -ShortcutDir $e.Shortcuts -JournalDir $e.Journal -HarnessRoot $e.Harness } | Should -Throw '*Refused*' -Because $r
        }
        Test-Path "HKCU:\Software\ssh-bad-$g" | Should -BeFalse
        { Get-HarnessSurfaceDefinition -RegistryRoot $e.Reg -ShortcutDir $e.Shortcuts } | Should -Not -Throw
    }

    It 'post-validation junction swap during recovery: the decoy shortcut is untouched and the surface is not marked restored' {
        $e = $script:e
        [void](New-J $e)
        Set-InstalledState $e $e.InstallDir '1.2.0'                        # before: absent => recovery would DELETE the shortcut
        $decoyDir = Join-Path $e.Dir 'decoy'; New-Item -ItemType Directory -Path $decoyDir | Out-Null
        $decoy = Join-Path $decoyDir "$($script:Acc.ProductName).lnk"
        Copy-Item -LiteralPath (StartLnk $e) -Destination $decoy
        $decoyBytes = [IO.File]::ReadAllBytes($decoy)
        $sm = Join-Path $e.Shortcuts 'StartMenu'
        $barrier = {
            param($p)
            if ($p -eq 'before-mutate:StartMenuShortcut') {
                Move-Item -LiteralPath $sm -Destination "$sm-moved"
                New-Item -ItemType Junction -Path $sm -Target $decoyDir | Out-Null
            }
        }
        { Recover $e $barrier } | Should -Throw '*reparse*'
        [IO.File]::ReadAllBytes($decoy) | Should -Be $decoyBytes
        (Read-HarnessJournal -RunId $e.RunId -JournalDir $e.Journal -HarnessRoot $e.Harness)['restored']['StartMenuShortcut'] | Should -BeFalse
        Test-Path (Get-JournalPath -RunId $e.RunId -JournalDir $e.Journal) | Should -BeTrue
    }

    It 'journal destination binding: <name> mismatch is JournalCorrupt, exit 2, zero mutation' -ForEach @(
        @{ name = 'startMenuDir'; key = 'startMenuDir' }
        @{ name = 'desktopDir'; key = 'desktopDir' }
        @{ name = 'registryRoot'; key = 'registryRoot' }
        @{ name = 'harnessRoot'; key = 'harnessRoot' }
    ) {
        $e = $script:e
        [void](New-J $e)
        Set-InstalledState $e $e.InstallDir '1.2.0'
        $state = Snap $e | ConvertTo-Json -Depth 12
        $jp = Get-JournalPath -RunId $e.RunId -JournalDir $e.Journal
        $h = Get-Content $jp -Raw | ConvertFrom-Json -AsHashtable -DateKind String -Depth 32
        $h['destinations'][$key] = if ($key -eq 'registryRoot') { 'HKCU:\Software' } else { Join-Path $e.Dir 'some-other-legit-dir' }
        [void](Save-HarnessJournal -Journal $h -JournalDir $e.Journal)
        $jbytes = [IO.File]::ReadAllBytes($jp)
        { Recover $e } | Should -Throw 'JournalCorrupt*destination*'
        (Snap $e | ConvertTo-Json -Depth 12) | Should -Be $state
        [IO.File]::ReadAllBytes($jp) | Should -Be $jbytes
        & pwsh -NoProfile -File $script:RepairScript -RegistryRoot $e.Reg -ShortcutDir $e.Shortcuts -JournalDir $e.Journal -HarnessRoot $e.Harness -LockMutexName "Local\ssh-repair-test-$($e.Guid)" -SkipProcessKill | Out-Null
        $LASTEXITCODE | Should -Be 2
        (Snap $e | ConvertTo-Json -Depth 12) | Should -Be $state
    }
    It 'recovering with a different (but legitimate) shortcut dir than the journal recorded is refused' {
        $e = $script:e
        [void](New-J $e)
        Set-InstalledState $e $e.InstallDir '1.2.0'
        $state = Snap $e | ConvertTo-Json -Depth 12
        $p = @{ RunId = $e.RunId; RegistryRoot = $e.Reg; ShortcutDir = (Join-Path $e.Dir 'other-sc'); JournalDir = $e.Journal; HarnessRoot = $e.Harness; SkipProcessKill = $true }
        { Invoke-HarnessRecovery @p } | Should -Throw 'JournalCorrupt*destination*'
        (Snap $e | ConvertTo-Json -Depth 12) | Should -Be $state
    }
    It 'Set-JournalOwnedAfter refuses a destination set that differs from the journal, and leaves the journal unchanged' {
        $e = $script:e
        $j = New-J $e
        Set-InstalledState $e $e.InstallDir '1.2.0'
        $jp = Get-JournalPath -RunId $e.RunId -JournalDir $e.Journal
        $jbytes = [IO.File]::ReadAllBytes($jp)
        { Set-JournalOwnedAfter -Journal $j -RegistryRoot $e.Reg -ShortcutDir (Join-Path $e.Dir 'other-sc') -JournalDir $e.Journal -HarnessRoot $e.Harness } | Should -Throw 'JournalCorrupt*destination*'
        [IO.File]::ReadAllBytes($jp) | Should -Be $jbytes
    }
    It 'Set-JournalOwnedAfter ignores a forged installDir on the caller object (derives it from the journal on disk)' {
        $e = $script:e
        $j = New-J $e
        Set-InstalledState $e $e.InstallDir '1.2.0'
        [IO.File]::WriteAllBytes((Join-Path $e.InstallDir 'uninstall.exe'), [byte[]](1, 1, 1))
        $other = Join-Path $e.Harness 'install\forged'; New-Item -ItemType Directory -Path $other | Out-Null
        [IO.File]::WriteAllBytes((Join-Path $other 'uninstall.exe'), [byte[]](9, 9, 9))
        $forged = @{ runId = $j['runId']; generation = $j['generation']; installDir = $other }
        [void](Set-JournalOwnedAfter -Journal $forged -RegistryRoot $e.Reg -ShortcutDir $e.Shortcuts -JournalDir $e.Journal -HarnessRoot $e.Harness)
        $after = Read-HarnessJournal -RunId $e.RunId -JournalDir $e.Journal -HarnessRoot $e.Harness
        $after['uninstallerSha256'] | Should -Be (Get-FileSha256 -Path (Join-Path $e.InstallDir 'uninstall.exe'))
        $after['uninstallerSha256'] | Should -Not -Be (Get-FileSha256 -Path (Join-Path $other 'uninstall.exe'))
    }
    It 'New-HarnessJournal records the validated destination set' {
        $j = New-J $script:e
        $j['destinations']['registryRoot'] | Should -Be $script:e.Reg
        $j['destinations']['startMenuDir'] | Should -Be (Join-Path $script:e.Shortcuts 'StartMenu')
        $j['destinations']['desktopDir'] | Should -Be (Join-Path $script:e.Shortcuts 'Desktop')
    }

    It 'Repair-Harness.ps1 refuses a LockMutexName that is not Local\<name>' {
        $e = $script:e
        & pwsh -NoProfile -File $script:RepairScript -RegistryRoot $e.Reg -ShortcutDir $e.Shortcuts -JournalDir $e.Journal -HarnessRoot $e.Harness -LockMutexName 'Global\ssh-x' -SkipProcessKill | Out-Null
        $LASTEXITCODE | Should -Be 1
    }

    It 'Read-HarnessJournal refuses an install dir that became a junction (real-path containment)' {
        $e = $script:e
        [void](New-J $e)
        $moved = "$($e.InstallDir)-moved"
        Move-Item -LiteralPath $e.InstallDir -Destination $moved
        New-Item -ItemType Junction -Path $e.InstallDir -Target $moved | Out-Null
        { Read-HarnessJournal -RunId $e.RunId -JournalDir $e.Journal -HarnessRoot $e.Harness } | Should -Throw 'JournalCorrupt*installDir*'
    }
    It 'Test-PointsIntoHarness is false for a target under a junction inside the install dir' {
        $e = $script:e
        $outside = Join-Path $e.Dir 'outside'; New-Item -ItemType Directory -Path $outside | Out-Null
        $jn = Join-Path $e.InstallDir 'jn'; New-Item -ItemType Junction -Path $jn -Target $outside | Out-Null
        $plain = Join-Path $e.InstallDir 'app.exe'
        InModuleScope HarnessJournal -Parameters @{ jn = $jn; plain = $plain; id = $e.InstallDir } {
            Test-PointsIntoHarness -Targets @($plain) -InstallDir $id | Should -BeTrue
            Test-PointsIntoHarness -Targets @((Join-Path $jn 'app.exe')) -InstallDir $id | Should -BeFalse
        }
    }
}

Describe 'Write-AtomicBytes re-validates its container immediately before writing' {
    BeforeEach { $script:e = New-Env }
    AfterEach { Remove-Env $script:e }
    It 'refuses when the container is a junction and writes nothing to the junction target' {
        $target = Join-Path $script:e.Dir 'target'; New-Item -ItemType Directory -Path $target | Out-Null
        $container = Join-Path $script:e.Dir 'cont'; New-Item -ItemType Junction -Path $container -Target $target | Out-Null
        InModuleScope HarnessJournal -Parameters @{ c = $container } {
            { Write-AtomicBytes -Path (Join-Path $c 'f.bin') -Bytes ([byte[]](1, 2, 3)) -Container $c } | Should -Throw '*reparse*'
        }
        @(Get-ChildItem -LiteralPath $target -Force).Count | Should -Be 0
    }
    It 'refuses a target outside the container and writes inside a plain container' {
        $container = Join-Path $script:e.Dir 'plain'; New-Item -ItemType Directory -Path $container | Out-Null
        InModuleScope HarnessJournal -Parameters @{ c = $container; outside = (Join-Path $script:e.Dir 'outside.bin') } {
            { Write-AtomicBytes -Path $outside -Bytes ([byte[]](1)) -Container $c } | Should -Throw '*not inside*'
            Write-AtomicBytes -Path (Join-Path $c 'ok.bin') -Bytes ([byte[]](1, 2)) -Container $c
            [IO.File]::ReadAllBytes((Join-Path $c 'ok.bin')) | Should -Be ([byte[]](1, 2))
        }
        Test-Path (Join-Path $script:e.Dir 'outside.bin') | Should -BeFalse
    }
}

Describe 'Repair-Harness.ps1 with NO -HarnessRoot and LOCALAPPDATA/TMP redirected into a sandbox (real-use shape)' {
    BeforeEach {
        $script:e = New-Env
        $script:saved = @{ LOCALAPPDATA = $env:LOCALAPPDATA; APPDATA = $env:APPDATA; TMP = $env:TMP; TEMP = $env:TEMP }
        $local = Join-Path $script:e.Dir 'RLocal'; $tmp = Join-Path $local 'Temp'
        New-Item -ItemType Directory -Force -Path $tmp, (Join-Path $script:e.Dir 'RRoaming') | Out-Null
        $env:LOCALAPPDATA = $local; $env:APPDATA = Join-Path $script:e.Dir 'RRoaming'; $env:TMP = $tmp; $env:TEMP = $tmp
        $root = Join-Path $local 'SnapmakerStudio-Harness'
        $sc = Join-Path $tmp 'sc'
        New-Item -ItemType Directory -Force -Path (Join-Path $sc 'StartMenu'), (Join-Path $sc 'Desktop'), (Join-Path $root 'install\run1') | Out-Null
        # an env-like object for the shared helpers, pointing at the DEFAULT root (no override anywhere)
        $script:r = [pscustomobject]@{ Guid = $script:e.Guid; Dir = $script:e.Dir; Reg = $script:e.Reg; Shortcuts = $sc; InstallDir = (Join-Path $root 'install\run1'); Root = $root; RunId = $script:e.RunId }
        $script:common = @('-NoProfile', '-File', $script:RepairScript, '-RegistryRoot', $script:r.Reg, '-ShortcutDir', $sc, '-LockMutexName', "Local\ssh-repair-test-$($script:e.Guid)", '-SkipProcessKill')
        function script:New-RJ([string]$runId) {
            New-HarnessJournal -RunId $runId -InstallDir $script:r.InstallDir -InstallVersion '1.2.0' -RegistryRoot $script:r.Reg -ShortcutDir $script:r.Shortcuts
        }
    }
    AfterEach {
        foreach ($k in $script:saved.Keys) { Set-Item -LiteralPath "env:$k" -Value $script:saved[$k] }
        Remove-Env $script:e
    }
    It 'exits 0 with no journals; 3 for a completed install; 0 after recovery; 2 for a corrupt journal; never 1' {
        & pwsh @script:common | Out-Null
        $LASTEXITCODE | Should -Be 0
        $id1 = "$($script:e.RunId)-a"
        [void](New-RJ $id1)
        Set-InstalledState $script:r $script:r.InstallDir '1.2.0'
        Set-Content -LiteralPath (Join-Path $script:r.InstallDir $script:Acc.MainBinaryName) -Value 'x'
        & pwsh @script:common | Out-Null
        $LASTEXITCODE | Should -Be 3
        Remove-Item (Join-Path $script:r.InstallDir $script:Acc.MainBinaryName)
        & pwsh @script:common | Out-Null
        $LASTEXITCODE | Should -Be 0
        Test-Path (UninstKey $script:r) | Should -BeFalse
        $id2 = "$($script:e.RunId)-b"
        [void](New-RJ $id2)
        Set-Content -LiteralPath (Get-JournalPath -RunId $id2) -Value 'garbage'
        & pwsh @script:common | Out-Null
        $LASTEXITCODE | Should -Be 2
    }
}
