#requires -Version 7.0
# Pester 5. Fixtures and mocks only: NO real installer, app or product process is ever started, and nothing under
# the PRODUCTION identity is touched. Real registry writes happen ONLY in the scratch hive
# HKCU:\Software\SnapmakerStudioHarnessTest\<guid>; every file lives in a private temp dir. The product-name probe,
# the child-process seam, the process/port/CDP probes and the WebView2 probe are mocked. The one real child process
# is a harmless pwsh used to prove the launcher applies environment to the CHILD only.

BeforeAll {
    $script:LauncherPath = Join-Path $PSScriptRoot 'HarnessLauncher.psm1'
    Import-Module (Join-Path $PSScriptRoot '..\lib\InstallGuard.psm1') -Force -DisableNameChecking
    Import-Module (Join-Path $PSScriptRoot 'HarnessJournal.psm1') -Force -DisableNameChecking
    Import-Module $script:LauncherPath -Force -DisableNameChecking
    $script:Pin = ('c' * 64)
    InModuleScope InstallGuard -Parameters @{ Pin = $script:Pin } { $script:Identity.Attestation.PinnedTemplateSha256 = $Pin }
    $script:Id = Get-HarnessIdentity
    $script:Acc = $script:Id.Acceptance
    $script:Prod = $script:Id.Production
    $global:SshT = @{}

    function script:Get-FreePort {
        $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
        $l.Start(); $p = $l.LocalEndpoint.Port; $l.Stop(); $p
    }
    function script:New-Sandbox {
        $guid = [guid]::NewGuid().ToString('N')
        $dir = Join-Path ([IO.Path]::GetTempPath()) "ssh-launch-test-$guid"
        $hr = Join-Path $dir 'SnapmakerStudio-Harness'
        foreach ($d in $hr, (Join-Path $dir 'real\StartMenu'), (Join-Path $dir 'real\Desktop')) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
        [pscustomobject]@{
            Dir = $dir; Harness = $hr; Guid = $guid; RegRoot = "HKCU:\Software\SnapmakerStudioHarnessTest\$guid"
            Roaming = Join-Path $dir 'prod\Roaming\com.snapmakerstudio.desktop'; Local = Join-Path $dir 'prod\Local\com.snapmakerstudio.desktop'
            Engine = Join-Path $dir 'prod\Local\SnapmakerStudio'
            RealStartMenu = Join-Path $dir 'real\StartMenu'; RealDesktop = Join-Path $dir 'real\Desktop'
            SoftRoot = "HKCU:\Software\SnapmakerStudioHarnessTest\$guid\prodsoft"; RunKey = "HKCU:\Software\SnapmakerStudioHarnessTest\$guid\prodrun"
            InstallDirs = @((Join-Path $dir 'prod\install\local'), (Join-Path $dir 'prod\install\pf'), (Join-Path $dir 'prod\install\pf86'))
        }
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
        if ($s.Dir -like "$([IO.Path]::GetTempPath())ssh-launch-test-*" -and (Test-Path $s.Dir)) { Remove-Item $s.Dir -Recurse -Force }
        $parent = 'HKCU:\Software\SnapmakerStudioHarnessTest'
        if ((Test-Path $parent) -and @(Get-ChildItem $parent).Count -eq 0) { Remove-Item $parent -Force }
    }
    function script:Set-Hooks($s, [hashtable]$Extra = @{}) {
        $h = @{
            RoamingDir = $s.Roaming; LocalDir = $s.Local; EngineDir = $s.Engine
            RealStartMenuDir = $s.RealStartMenu; RealDesktopDir = $s.RealDesktop
            ProductionSoftwareRoots = @($s.SoftRoot, "$($s.SoftRoot)\WOW6432Node"); ProductionRunKeyPath = $s.RunKey; ProductionInstallDirs = $s.InstallDirs
            RegistryRoot = $s.RegRoot; MutexName = "Local\ssh-launch-test-$($s.Guid)"
            ProductionProcessProvider = { param($name) @() }
            WebViewWaitSeconds = 1; CdpWaitSeconds = 1; PortWaitSeconds = 0; ExitWaitSeconds = 1
        }
        foreach ($k in $Extra.Keys) { $h[$k] = $Extra[$k] }
        InModuleScope HarnessLauncher -Parameters @{ H = $h } { $script:TestHooks = $H }
    }
    function script:New-Attestation {
        param([string]$InstallerSha, [string]$Version = '1.2.0')
        $sha = ('a' * 64)
        [ordered]@{
            kind = $script:Id.Attestation.Kind; schemaVersion = 1; createdUtc = '2026-09-30T00:00:00Z'
            identity = [ordered]@{ productName = $script:Acc.ProductName; manufacturer = $script:Acc.Manufacturer; bundleId = $script:Acc.BundleId; mainBinaryName = $script:Acc.MainBinaryName }
            source = [ordered]@{ version = $Version; installerSha256 = ('b' * 64) }
            template = [ordered]@{ name = 'tauri-bundler-nsis'; version = '2.9.3'; sha256 = $script:Pin }
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
    }
    function script:New-FakeInstallerAndAttestation($s, [string]$Version = '1.2.0') {
        $inst = Join-Path $s.Dir "fake-$([guid]::NewGuid().ToString('N')).exe"
        [IO.File]::WriteAllBytes($inst, [Text.Encoding]::UTF8.GetBytes("not a real installer $([guid]::NewGuid())"))
        $sha = (Get-FileHash -LiteralPath $inst -Algorithm SHA256).Hash.ToLowerInvariant()
        $d = Join-Path $s.Harness 'attestations'
        New-Item -ItemType Directory -Force -Path $d | Out-Null
        $ap = Join-Path $d "att-$([guid]::NewGuid().ToString('N')).json"
        New-Attestation -InstallerSha $sha -Version $Version | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ap -Encoding utf8
        [pscustomobject]@{ Installer = $inst; Attestation = $ap; Sha = $sha }
    }
    function script:New-TestLane($s, [switch]$KeepInstall, [string]$Installer, [string]$Attestation) {
        if (-not $Installer) { $f = New-FakeInstallerAndAttestation $s; $Installer = $f.Installer; $Attestation = $f.Attestation }
        Start-HarnessLane -Name 't' -Kind acceptance -InstallerPath $Installer -AttestationPath $Attestation -HarnessRoot $s.Harness -DebugPort (Get-FreePort) -KeepInstall:$KeepInstall
    }
    function script:New-FakeProc([int]$ProcId, [int]$ExitCode = 0) {
        $o = [pscustomobject]@{ Id = $ProcId; ExitCode = $ExitCode; HasExited = $false }
        $o | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value { param($ms) $true }
        $o | Add-Member -MemberType ScriptMethod -Name Refresh -Value { }
        $o | Add-Member -MemberType ScriptMethod -Name CloseMainWindow -Value { $true }
        $o
    }
    function script:Get-FunctionCommandNames([string]$Name) {
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($script:LauncherPath, [ref]$null, [ref]$null)
        $fn = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $Name }, $true)
        @($fn.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true) | ForEach-Object { $_.GetCommandName() } | Sort-Object -Unique)
    }
    function script:Set-DefaultMocks {
        Mock -ModuleName InstallGuard Get-ExeProductName { 'Snapmaker Studio Acceptance' }
        Mock -ModuleName HarnessLauncher Get-WebView2RuntimeVersion { '1.0.0.0' }
    }
}

AfterAll {
    Remove-Variable -Name SshT -Scope Global -ErrorAction SilentlyContinue
}

Describe 'Isolation paths must resolve strictly inside the harness directory' {
    BeforeEach { $script:sb = New-Sandbox; Set-Hooks $script:sb }
    AfterEach { Remove-Sandbox $script:sb }

    It 'accepts a path strictly inside the root' {
        $p = Join-Path $script:sb.Harness 'run\x1\webview-profile'
        Assert-HarnessPathInside -Path $p -Root $script:sb.Harness | Should -Be $p
    }
    It 'refuses the root itself' {
        { Assert-HarnessPathInside -Path $script:sb.Harness -Root $script:sb.Harness } | Should -Throw '*strictly inside*'
    }
    It 'refuses a sibling directory outside the harness root' {
        { Assert-HarnessPathInside -Path (Join-Path $script:sb.Dir 'elsewhere\profile') -Root $script:sb.Harness } | Should -Throw '*strictly inside*'
    }
    It 'refuses a prefix-neighbour of the root' {
        $n = "$($script:sb.Harness)-evil"
        { Assert-HarnessPathInside -Path (Join-Path $n 'profile') -Root $script:sb.Harness } | Should -Throw '*strictly inside*'
    }
    It 'refuses a UNC path' { { Assert-HarnessPathInside -Path '\\server\share\run\x' -Root $script:sb.Harness } | Should -Throw '*not an allowed location*' }
    It 'refuses a relative path' { { Assert-HarnessPathInside -Path 'run\x\profile' -Root $script:sb.Harness } | Should -Throw '*not an allowed location*' }
    It 'refuses a dot-dot traversal' {
        { Assert-HarnessPathInside -Path (Join-Path $script:sb.Harness 'run\..\..\x') -Root $script:sb.Harness } | Should -Throw '*not an allowed location*'
    }
    It 'refuses a path that reaches outside through a junction' {
        $outside = Join-Path $script:sb.Dir 'outside'; New-Item -ItemType Directory -Path $outside | Out-Null
        $runDir = Join-Path $script:sb.Harness 'run'; New-Item -ItemType Directory -Path $runDir | Out-Null
        New-Item -ItemType Junction -Path (Join-Path $runDir 'j') -Target $outside | Out-Null
        { Assert-HarnessPathInside -Path (Join-Path $runDir 'j\profile') -Root $script:sb.Harness } | Should -Throw '*reparse*'
    }
    It 'Assert-LaneIsolation refuses a tampered profile dir, a production exe name and an exe outside the install dir' {
        Set-DefaultMocks
        $lane = New-TestLane $script:sb
        try {
            New-Item -ItemType Directory -Force -Path $lane.InstallDir | Out-Null
            [IO.File]::WriteAllText($lane.AppExe, 'x')
            { Assert-LaneIsolation -Lane $lane } | Should -Not -Throw
            $orig = $lane.ProfileDir
            $lane.ProfileDir = Join-Path $script:sb.Dir 'outside-profile'
            { Assert-LaneIsolation -Lane $lane } | Should -Throw '*strictly inside*'
            $lane.ProfileDir = $orig
            $lane.AppExe = Join-Path $lane.InstallDir $script:Prod.MainBinaryName
            { Assert-LaneIsolation -Lane $lane } | Should -Throw '*acceptance binary*'
            $lane.AppExe = Join-Path $script:sb.Dir 'x\snapmaker-studio-acceptance-desktop.exe'
            { Assert-LaneIsolation -Lane $lane } | Should -Throw '*not inside the harness install dir*'
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }
}

Describe 'update_check.json preflight (S1/N3): read-only, fail closed' {
    BeforeEach { $script:sb = New-Sandbox; Set-Hooks $script:sb; New-Item -ItemType Directory -Force -Path $script:sb.Roaming | Out-Null; $script:uc = Join-Path $script:sb.Roaming 'update_check.json' }
    AfterEach { Remove-Sandbox $script:sb }

    It 'accepts an absent file' { Remove-Item $script:uc -ErrorAction SilentlyContinue; Assert-UpdateCheckPreflight | Should -Be 'absent' }
    It 'accepts auto_check false' { '{"auto_check":false,"last_checked_at_unix":5}' | Set-Content $script:uc; Assert-UpdateCheckPreflight | Should -Be 'auto_check=false' }
    It 'refuses auto_check true' { '{"auto_check":true}' | Set-Content $script:uc; { Assert-UpdateCheckPreflight } | Should -Throw '*auto-check ON*' }
    It 'refuses a file without the auto_check key' { '{"last_checked_at_unix":5}' | Set-Content $script:uc; { Assert-UpdateCheckPreflight } | Should -Throw '*no explicit boolean*' }
    It 'refuses a non-boolean auto_check' { '{"auto_check":"false"}' | Set-Content $script:uc; { Assert-UpdateCheckPreflight } | Should -Throw '*no explicit boolean*' }
    It 'refuses a corrupt file' { '{not json' | Set-Content $script:uc; { Assert-UpdateCheckPreflight } | Should -Throw '*not valid JSON*' }
    It 'refuses a JSON array' { '[false]' | Set-Content $script:uc; { Assert-UpdateCheckPreflight } | Should -Throw '*no explicit boolean*' }
    It 'refuses an unreadable file (held open exclusively)' {
        '{"auto_check":false}' | Set-Content $script:uc
        $fs = [IO.File]::Open($script:uc, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        try { { Assert-UpdateCheckPreflight } | Should -Throw '*unreadable*' } finally { $fs.Dispose() }
    }
    It 'refuses when update_check.json is a directory (ambiguous)' {
        New-Item -ItemType Directory -Path $script:uc | Out-Null
        { Assert-UpdateCheckPreflight } | Should -Throw '*not a plain file*'
    }
    It 'never modifies the file and never prints its content' {
        '{"auto_check":true,"secret":"sentinel-value"}' | Set-Content $script:uc
        $before = (Get-FileHash $script:uc).Hash; $mt = (Get-Item $script:uc).LastWriteTimeUtc
        $msg = try { Assert-UpdateCheckPreflight; '' } catch { $_.Exception.Message }
        $msg | Should -Not -Match 'sentinel-value'
        (Get-FileHash $script:uc).Hash | Should -Be $before
        (Get-Item $script:uc).LastWriteTimeUtc | Should -Be $mt
    }
}

Describe 'Production process and WebView2 preflight' {
    BeforeEach { $script:sb = New-Sandbox; Set-Hooks $script:sb; Set-DefaultMocks }
    AfterEach { Remove-Sandbox $script:sb }

    It 'refuses when the production exe is running, accepts when it is not' {
        Set-Hooks $script:sb @{ ProductionProcessProvider = { param($name) @([pscustomobject]@{ Id = 4242 }) } }
        { Assert-ProductionIdle } | Should -Throw '*production Snapmaker Studio process is running*'
        Set-Hooks $script:sb
        { Assert-ProductionIdle } | Should -Not -Throw
    }
    It 'queries the production process name from HarnessIdentity (not the acceptance name)' {
        $seen = $null
        Set-Hooks $script:sb @{ ProductionProcessProvider = { param($name) $global:SshT.Name = $name; @() } }
        Assert-ProductionIdle
        $global:SshT.Name | Should -Be $script:Prod.ProcessName
        $global:SshT.Name | Should -Not -Be ([IO.Path]::GetFileNameWithoutExtension($script:Acc.MainBinaryName))
    }
    It 'a running production exe stops lane start (nothing installed, lock free for the next run)' {
        Set-Hooks $script:sb @{ ProductionProcessProvider = { param($name) @([pscustomobject]@{ Id = 1 }) } }
        { New-TestLane $script:sb } | Should -Throw '*production Snapmaker Studio process is running*'
        Set-Hooks $script:sb
        $lane = New-TestLane $script:sb
        try { $lane.Completed | Should -BeFalse } finally { [void](Complete-HarnessLane -Lane $lane) }
    }
    It 'aborts when the WebView2 runtime is missing and never runs a bootstrapper' {
        Mock -ModuleName HarnessLauncher Get-WebView2RuntimeVersion { $null }
        Mock -ModuleName HarnessLauncher Start-HarnessChildProcess { throw 'must not start anything' }
        { Assert-WebView2Runtime } | Should -Throw '*WebView2 runtime is not installed*'
        { New-TestLane $script:sb } | Should -Throw '*WebView2 runtime is not installed*'
        Should -Invoke -ModuleName HarnessLauncher Start-HarnessChildProcess -Times 0 -Exactly
        $t = Get-Content -LiteralPath $script:LauncherPath -Raw
        $t | Should -Not -Match '(?i)bootstrapper\.exe|MicrosoftEdgeWebview2Setup|go\.microsoft\.com/fwlink'
    }
    It 'the WebView2 probe is a read-only registry lookup (no write or run command)' {
        $names = Get-FunctionCommandNames 'Get-WebView2RuntimeVersion'
        @($names | Where-Object { $_ -notin 'Test-Path', 'Get-ItemProperty' }) | Should -BeNullOrEmpty
        $names | Should -Contain 'Test-Path'
    }
}

Describe 'Debug port' {
    BeforeEach { $script:sb = New-Sandbox; Set-Hooks $script:sb; Set-DefaultMocks }
    AfterEach { Remove-Sandbox $script:sb }

    It 'refuses a port that is in use, accepts a free one, rejects out-of-range ports' {
        $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0); $l.Start()
        try {
            $port = $l.LocalEndpoint.Port
            { Assert-DebugPortFree -Port $port } | Should -Throw '*already in use*'
        } finally { $l.Stop() }
        { Assert-DebugPortFree -Port (Get-FreePort) } | Should -Not -Throw
        { Assert-DebugPortFree -Port 80 } | Should -Throw '*out of range*'
    }
    It 'a launch whose port got occupied is refused before any child process starts' {
        $lane = New-TestLane $script:sb
        try {
            New-Item -ItemType Directory -Force -Path $lane.InstallDir | Out-Null; [IO.File]::WriteAllText($lane.AppExe, 'x')
            Mock -ModuleName HarnessLauncher Start-HarnessChildProcess { throw 'must not start' }
            $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $lane.DebugPort); $l.Start()
            try { { Start-HarnessApp -Lane $lane } | Should -Throw '*already in use*' } finally { $l.Stop() }
            Should -Invoke -ModuleName HarnessLauncher Start-HarnessChildProcess -Times 0 -Exactly
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }
}

Describe 'Start-HarnessApp: the fail-closed launcher' {
    BeforeEach {
        $script:sb = New-Sandbox; Set-Hooks $script:sb; Set-DefaultMocks
        $script:lane = New-TestLane $script:sb
        New-Item -ItemType Directory -Force -Path $script:lane.InstallDir | Out-Null
        [IO.File]::WriteAllText($script:lane.AppExe, 'x')
        $global:SshT.Exe = $script:lane.AppExe
        $global:SshT.Proc = New-FakeProc 4242
        $global:SshT.Alive = $true
        $global:SshT.Owner = 4242
        $global:SshT.Start = 111
        $global:SshT.ProfilePath = $script:lane.ProfileDir
        $global:SshT.CdpOk = $true
        Mock -ModuleName HarnessLauncher Start-HarnessChildProcess {
            New-Item -ItemType Directory -Force -Path (Join-Path $global:SshT.ProfilePath 'EBWebView') | Out-Null
            $global:SshT.Proc
        }
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo {
            if ($global:SshT.Alive) { [pscustomobject]@{ Id = $ProcessId; StartTicks = [int64]$global:SshT.Start; Path = $global:SshT.Exe } }
        }
        Mock -ModuleName HarnessLauncher Get-Win32ProcessList { @([pscustomobject]@{ ProcessId = 4242; ParentProcessId = 1; Name = 'app.exe'; ExecutablePath = $global:SshT.Exe }) }
        Mock -ModuleName HarnessLauncher Get-PortOwnerPid { $global:SshT.Owner }
        Mock -ModuleName HarnessLauncher Test-CdpEndpoint { $global:SshT.CdpOk }
        Mock -ModuleName HarnessLauncher Stop-ProcessById { }
        $global:SshT.CmdLines = @()
        Mock -ModuleName HarnessLauncher Get-Win32CommandLines { $global:SshT.CmdLines }
    }
    AfterEach { try { if ($script:lane) { [void](Complete-HarnessLane -Lane $script:lane) } } finally { $script:lane = $null; Remove-Sandbox $script:sb } }

    It 'passes the isolation variables ONLY to the child and leaves this session environment unchanged' {
        $names = 'WEBVIEW2_USER_DATA_FOLDER', 'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', 'SNAPSTUDIO_DATA_DIR'
        $before = $names | ForEach-Object { [Environment]::GetEnvironmentVariable($_) }
        $h = Start-HarnessApp -Lane $script:lane -Arguments @('model.3mf')
        $h.Pid | Should -Be 4242
        Should -Invoke -ModuleName HarnessLauncher Start-HarnessChildProcess -Times 1 -Exactly -ParameterFilter {
            $FilePath -eq $global:SshT.Exe -and
            $Environment['WEBVIEW2_USER_DATA_FOLDER'] -eq $global:SshT.ProfilePath -and
            $Environment['SNAPSTUDIO_DATA_DIR'] -like '*engine-data' -and
            $Environment['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] -like '--remote-debugging-port=* --remote-allow-origins=*' -and
            $ArgumentList -contains 'model.3mf'
        }
        $after = $names | ForEach-Object { [Environment]::GetEnvironmentVariable($_) }
        $after | Should -Be $before
        foreach ($n in $names) { [Environment]::GetEnvironmentVariable($n) | Should -BeNullOrEmpty }
    }
    It 'refuses to launch the production exe name or an exe outside the install dir' {
        $script:lane.AppExe = Join-Path $script:lane.InstallDir $script:Prod.MainBinaryName
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*acceptance binary*'
        $script:lane.AppExe = Join-Path $script:sb.Dir 'x\snapmaker-studio-acceptance-desktop.exe'
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*not inside the harness install dir*'
        Should -Invoke -ModuleName HarnessLauncher Start-HarnessChildProcess -Times 0 -Exactly
    }
    It 'refuses when an isolation path is outside the harness directory' {
        $script:lane.DataDir = Join-Path $script:sb.Dir 'outside-data'
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*strictly inside*'
        Should -Invoke -ModuleName HarnessLauncher Start-HarnessChildProcess -Times 0 -Exactly
    }
    It 'runs the update_check preflight before EVERY launch' {
        [void](Start-HarnessApp -Lane $script:lane)
        New-Item -ItemType Directory -Force -Path $script:sb.Roaming | Out-Null
        '{"auto_check":true}' | Set-Content (Join-Path $script:sb.Roaming 'update_check.json')
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*auto-check ON*'
        Should -Invoke -ModuleName HarnessLauncher Start-HarnessChildProcess -Times 1 -Exactly
    }
    It 'refuses to launch while the production exe is running' {
        Set-Hooks $script:sb @{ ProductionProcessProvider = { param($name) @([pscustomobject]@{ Id = 9 }) } }
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*production Snapmaker Studio process is running*'
        Should -Invoke -ModuleName HarnessLauncher Start-HarnessChildProcess -Times 0 -Exactly
    }
    It 'fails hard (and stops the tracked app) when the isolated WebView2 profile is not created' {
        Mock -ModuleName HarnessLauncher Start-HarnessChildProcess { $global:SshT.Proc }
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*EBWebView was not created*'
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 1 -Exactly -ParameterFilter { $ProcessId -eq 4242 }
    }
    It 'accepts the profile once EBWebView exists' {
        { Start-HarnessApp -Lane $script:lane } | Should -Not -Throw
    }
    It 'S1: a profile holding only Default, or only Local State, is REFUSED and the app is stopped' {
        foreach ($alt in 'Default', 'Local State') {
            $global:SshT.Alt = $alt
            if (Test-Path -LiteralPath $script:lane.ProfileDir) { Remove-Item -LiteralPath $script:lane.ProfileDir -Recurse -Force }
            Mock -ModuleName HarnessLauncher Start-HarnessChildProcess {
                New-Item -ItemType Directory -Force -Path $global:SshT.ProfilePath | Out-Null
                if ($global:SshT.Alt -eq 'Default') { New-Item -ItemType Directory -Force -Path (Join-Path $global:SshT.ProfilePath 'Default') | Out-Null }
                else { [IO.File]::WriteAllText((Join-Path $global:SshT.ProfilePath 'Local State'), '{}') }
                $global:SshT.Proc
            }
            { Start-HarnessApp -Lane $script:lane } | Should -Throw '*EBWebView was not created*'
        }
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 2 -Exactly -ParameterFilter { $ProcessId -eq 4242 }
        ($script:lane.Errors -join '|') | Should -Match 'launch postflight'
    }
    It 'S4: a sidecar registered right after launch is stopped with the app when the postflight fails' {
        $global:SshT.Calls = 0
        $global:SshT.Sidecar = Join-Path $script:lane.InstallDir 'snapstudio-api.exe'
        Mock -ModuleName HarnessLauncher Start-HarnessChildProcess { $global:SshT.Proc }     # no EBWebView => failure
        Mock -ModuleName HarnessLauncher Get-Win32ProcessList {
            $global:SshT.Calls++
            $rows = @([pscustomobject]@{ ProcessId = 4242; ParentProcessId = 1; Name = 'app.exe'; ExecutablePath = $global:SshT.Exe })
            if ($global:SshT.Calls -eq 1) { $rows += [pscustomobject]@{ ProcessId = 4343; ParentProcessId = 4242; Name = 'snapstudio-api.exe'; ExecutablePath = $global:SshT.Sidecar } }
            $rows
        }
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*EBWebView was not created*'
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 1 -Exactly -ParameterFilter { $ProcessId -eq 4242 }
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 1 -Exactly -ParameterFilter { $ProcessId -eq 4343 }
        @($script:lane.Tracked).Count | Should -Be 0
    }
    It 'B3: the app exits right after spawning a sidecar (parent already gone at the first query): the sidecar is still stopped and the launch fails closed' {
        $global:SshT.Sidecar = Join-Path $script:lane.InstallDir 'snapstudio-api.exe'
        Mock -ModuleName HarnessLauncher Start-HarnessChildProcess { $global:SshT.Proc }
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo {
            if ($ProcessId -eq 4242) { return $null }
            [pscustomobject]@{ Id = $ProcessId; StartTicks = [int64]5; Path = $global:SshT.Sidecar }
        }
        Mock -ModuleName HarnessLauncher Get-Win32ProcessList { @([pscustomobject]@{ ProcessId = 4343; ParentProcessId = 4242; Name = 'snapstudio-api.exe'; ExecutablePath = $global:SshT.Sidecar }) }
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*cannot be tracked*'
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 1 -Exactly -ParameterFilter { $ProcessId -eq 4343 }
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 0 -Exactly -ParameterFilter { $ProcessId -eq 4242 }
        ($script:lane.Errors -join '|') | Should -Match 'launch postflight'
    }
    It 'B3: the app entry is null and only a command-line match proves the process belongs to this launch: it is stopped (image still verified)' {
        Mock -ModuleName HarnessLauncher Start-HarnessChildProcess { $global:SshT.Proc }
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo {
            if ($ProcessId -eq 4242) { return $null }
            [pscustomobject]@{ Id = $ProcessId; StartTicks = [int64]5; Path = $global:SshT.Exe }
        }
        Mock -ModuleName HarnessLauncher Get-Win32ProcessList { @() }
        $global:SshT.CmdLines = @([pscustomobject]@{ ProcessId = 5555; CommandLine = "something --user-data-dir=$($script:lane.ProfileDir)\EBWebView" })
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*cannot be tracked*'
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 1 -Exactly -ParameterFilter { $ProcessId -eq 5555 }
    }
    It 'B3: a command-line match whose image is OUTSIDE the harness tree is never stopped' {
        Mock -ModuleName HarnessLauncher Start-HarnessChildProcess { $global:SshT.Proc }
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo {
            if ($ProcessId -eq 4242) { return $null }
            [pscustomobject]@{ Id = $ProcessId; StartTicks = [int64]5; Path = 'C:\user-gui\other.exe' }
        }
        Mock -ModuleName HarnessLauncher Get-Win32ProcessList { @() }
        $global:SshT.CmdLines = @([pscustomobject]@{ ProcessId = 5555; CommandLine = "x $($script:lane.InstallDir)" })
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*cannot be tracked*'
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 0 -Exactly
    }
    It 'B3: registering the app throws, and descendant registration throws: the failure path still sweeps and stops the sidecar' {
        $global:SshT.Calls = 0
        $global:SshT.Sidecar = Join-Path $script:lane.InstallDir 'snapstudio-api.exe'
        Mock -ModuleName HarnessLauncher Start-HarnessChildProcess { $global:SshT.Proc }
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo {
            if ($ProcessId -eq 4242) { throw 'process query failed' }
            [pscustomobject]@{ Id = $ProcessId; StartTicks = [int64]5; Path = $global:SshT.Sidecar }
        }
        Mock -ModuleName HarnessLauncher Get-Win32ProcessList {
            $global:SshT.Calls++
            if ($global:SshT.Calls -eq 1) { throw 'CIM enumeration failed' }
            @([pscustomobject]@{ ProcessId = 4343; ParentProcessId = 4242; Name = 'snapstudio-api.exe'; ExecutablePath = $global:SshT.Sidecar })
        }
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*cannot be tracked*'
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 1 -Exactly -ParameterFilter { $ProcessId -eq 4343 }
        ($script:lane.Warnings -join '|') | Should -Match 'could not be registered'
        ($script:lane.Warnings -join '|') | Should -Match 'descendant registration failed'
    }
    It 'S4: a sidecar that spawns AFTER the launch is found again at failure time and stopped too' {
        $global:SshT.Calls = 0
        $global:SshT.Sidecar = Join-Path $script:lane.InstallDir 'snapstudio-api.exe'
        Mock -ModuleName HarnessLauncher Start-HarnessChildProcess { $global:SshT.Proc }
        Mock -ModuleName HarnessLauncher Get-Win32ProcessList {
            $global:SshT.Calls++
            $rows = @([pscustomobject]@{ ProcessId = 4242; ParentProcessId = 1; Name = 'app.exe'; ExecutablePath = $global:SshT.Exe })
            if ($global:SshT.Calls -ge 2) { $rows += [pscustomobject]@{ ProcessId = 4343; ParentProcessId = 4242; Name = 'snapstudio-api.exe'; ExecutablePath = $global:SshT.Sidecar } }
            $rows
        }
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*EBWebView was not created*'
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 1 -Exactly -ParameterFilter { $ProcessId -eq 4343 }
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 1 -Exactly -ParameterFilter { $ProcessId -eq 4242 }
    }
    It 'aborts and stops the tracked app when the CDP endpoint belongs to a foreign process (M4)' {
        $global:SshT.Owner = 777
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*not part of the tracked app*'
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 1 -Exactly -ParameterFilter { $ProcessId -eq 4242 }
    }
    It 'aborts when the CDP endpoint never answers' {
        $global:SshT.CdpOk = $false
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*never answered*'
    }
    It 'refuses when the launched image is not inside the harness install dir' {
        $global:SshT.Exe = Join-Path $script:sb.Dir 'elsewhere\app.exe'
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*not inside the harness install dir*'
    }
    It 'waits briefly for an image path that is unavailable right after the start, then accepts it inside the install dir' {
        # Regression (third real lane run): Get-Process returned no image path for a moment after Process.Start, the null path
        # was stored, and the relaunch was refused as "not inside the harness install dir".
        Set-Hooks $script:sb @{ ProcessPathWaitSeconds = 5 }
        $global:SshT.PathCalls = 0
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo {
            $global:SshT.PathCalls++
            [pscustomobject]@{ Id = $ProcessId; StartTicks = [int64]$global:SshT.Start; Path = $(if ($global:SshT.PathCalls -ge 4) { $global:SshT.Exe } else { $null }) }
        }
        $h = Start-HarnessApp -Lane $script:lane
        $h.Pid | Should -Be 4242
        $global:SshT.PathCalls | Should -BeGreaterOrEqual 4
    }
    It 'still refuses when the image path never becomes available, and does not wait longer than the bound' {
        Set-Hooks $script:sb @{ ProcessPathWaitSeconds = 0.6 }
        $global:SshT.PathCalls = 0
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo {
            $global:SshT.PathCalls++
            [pscustomobject]@{ Id = $ProcessId; StartTicks = [int64]$global:SshT.Start; Path = $null }
        }
        $sw = [Diagnostics.Stopwatch]::StartNew()
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*not inside the harness install dir*'
        $sw.Elapsed.TotalSeconds | Should -BeLessThan 5
        $global:SshT.PathCalls | Should -BeGreaterThan 2
    }
    It 'still refuses a path that resolves late but lies outside the install dir' {
        Set-Hooks $script:sb @{ ProcessPathWaitSeconds = 5 }
        $global:SshT.PathCalls = 0
        $outside = Join-Path $script:sb.Dir 'elsewhere\app.exe'
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo {
            $global:SshT.PathCalls++
            [pscustomobject]@{ Id = $ProcessId; StartTicks = [int64]$global:SshT.Start; Path = $(if ($global:SshT.PathCalls -ge 3) { $outside } else { $null }) }
        }
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*not inside the harness install dir*'
        # a process whose image is outside the harness tree is refused AND never killed (the kill logic only stops harness-owned images)
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 0 -Exactly
    }
    It 'refuses a retry that reports a different start time (pid reuse) and never kills it' {
        Set-Hooks $script:sb @{ ProcessPathWaitSeconds = 5 }
        $global:SshT.PathCalls = 0
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo {
            $global:SshT.PathCalls++
            if ($global:SshT.PathCalls -le 2) { [pscustomobject]@{ Id = $ProcessId; StartTicks = [int64]100; Path = $null } }
            else { [pscustomobject]@{ Id = $ProcessId; StartTicks = [int64]200; Path = $global:SshT.Exe } }
        }
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*not found alive*'
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 0 -Exactly
    }
    It 'refuses when the process disappears during the retry' {
        Set-Hooks $script:sb @{ ProcessPathWaitSeconds = 5 }
        $global:SshT.PathCalls = 0
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo {
            $global:SshT.PathCalls++
            if ($global:SshT.PathCalls -le 2) { [pscustomobject]@{ Id = $ProcessId; StartTicks = [int64]$global:SshT.Start; Path = $null } }
        }
        { Start-HarnessApp -Lane $script:lane } | Should -Throw '*not found alive*'
    }
    It 'does not wait at all when the path is available immediately' {
        Set-Hooks $script:sb @{ ProcessPathWaitSeconds = 30 }
        $sw = [Diagnostics.Stopwatch]::StartNew()
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo {
            $global:SshT.PathCalls++
            [pscustomobject]@{ Id = $ProcessId; StartTicks = [int64]$global:SshT.Start; Path = $global:SshT.Exe }
        }
        $global:SshT.PathCalls = 0
        $h = Start-HarnessApp -Lane $script:lane
        $h.Pid | Should -Be 4242
        # no retry at all: Register-HarnessProcess read the live info exactly once (the postflight/children do not use it for this pid)
        $sw.Elapsed.TotalSeconds | Should -BeLessThan 20
    }}

Describe 'The child-process seam' {
    It 'the real child-process seam applies environment to the CHILD only' {
        $pw = (Get-Process -Id $PID).Path
        $txt = InModuleScope HarnessLauncher -Parameters @{ Pw = $pw } {
            $p = Start-HarnessChildProcess -FilePath $Pw -ArgumentList @('-NoProfile', '-Command', 'Write-Output $env:SSH_LAUNCH_TEST_VAR') -Environment @{ SSH_LAUNCH_TEST_VAR = 'child-only' } -RedirectOutput
            $o = $p.StandardOutput.ReadToEnd(); [void]$p.WaitForExit(30000); $o.Trim()
        }
        $txt | Should -Be 'child-only'
        [Environment]::GetEnvironmentVariable('SSH_LAUNCH_TEST_VAR') | Should -BeNullOrEmpty
    }
}

Describe 'Assert-CdpOwnedByTrackedApp (M4)' {
    It 'accepts the app itself and a descendant, refuses a foreign owner or no owner' {
        $all = @(
            [pscustomobject]@{ ProcessId = 10; ParentProcessId = 1; Name = 'a'; ExecutablePath = '' }
            [pscustomobject]@{ ProcessId = 11; ParentProcessId = 10; Name = 'b'; ExecutablePath = '' }
            [pscustomobject]@{ ProcessId = 12; ParentProcessId = 11; Name = 'c'; ExecutablePath = '' }
            [pscustomobject]@{ ProcessId = 99; ParentProcessId = 1; Name = 'z'; ExecutablePath = '' })
        $global:SshT.All = $all
        Mock -ModuleName HarnessLauncher Get-Win32ProcessList { $global:SshT.All }
        $global:SshT.Owner = 10; Mock -ModuleName HarnessLauncher Get-PortOwnerPid { $global:SshT.Owner }
        { Assert-CdpOwnedByTrackedApp -Port 9999 -AppPid 10 } | Should -Not -Throw
        $global:SshT.Owner = 12
        { Assert-CdpOwnedByTrackedApp -Port 9999 -AppPid 10 } | Should -Not -Throw
        $global:SshT.Owner = 99
        { Assert-CdpOwnedByTrackedApp -Port 9999 -AppPid 10 } | Should -Throw '*not part of the tracked app*'
        $global:SshT.Owner = $null
        { Assert-CdpOwnedByTrackedApp -Port 9999 -AppPid 10 } | Should -Throw '*nothing owns debug port*'
    }
}

Describe 'Process hygiene: kill only tracked pids, never by name' {
    BeforeEach { $script:sb = New-Sandbox; Set-Hooks $script:sb; Set-DefaultMocks; $script:lane = New-TestLane $script:sb; Mock -ModuleName HarnessLauncher Stop-ProcessById { } }
    AfterEach { try { if ($script:lane) { [void](Complete-HarnessLane -Lane $script:lane) } } finally { $script:lane = $null; Remove-Sandbox $script:sb } }

    It 'kills a tracked app whose start time and in-harness image still match' {
        $img = Join-Path $script:lane.InstallDir 'a.exe'
        $global:SshT.Live = [pscustomobject]@{ Id = 50; StartTicks = [int64]500; Path = $img }
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo { $global:SshT.Live }
        $e = [ordered]@{ Pid = 50; StartTicks = [int64]500; Path = $img; Kind = 'App'; Label = 'app'; Process = $null }
        Stop-HarnessTrackedProcess -Lane $script:lane -Entry $e | Should -Be 'killed'
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 1 -Exactly -ParameterFilter { $ProcessId -eq 50 }
    }
    It 'does NOT kill when the start time changed (pid reuse)' {
        $img = Join-Path $script:lane.InstallDir 'a.exe'
        $global:SshT.Live = [pscustomobject]@{ Id = 50; StartTicks = [int64]501; Path = $img }
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo { $global:SshT.Live }
        $e = [ordered]@{ Pid = 50; StartTicks = [int64]500; Path = $img; Kind = 'App'; Label = 'app'; Process = $null }
        Stop-HarnessTrackedProcess -Lane $script:lane -Entry $e | Should -Be 'start-time-mismatch'
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 0 -Exactly
    }
    It 'does NOT kill an App entry whose image is outside the harness directory' {
        $global:SshT.Live = [pscustomobject]@{ Id = 50; StartTicks = [int64]500; Path = (Join-Path $script:sb.Dir 'user-gui\orca.exe') }
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo { $global:SshT.Live }
        $e = [ordered]@{ Pid = 50; StartTicks = [int64]500; Path = $global:SshT.Live.Path; Kind = 'App'; Label = 'app'; Process = $null }
        Stop-HarnessTrackedProcess -Lane $script:lane -Entry $e | Should -Be 'image-outside-harness'
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 0 -Exactly
    }
    It 'does NOT kill a Tool entry whose image differs from the recorded one; kills when identical' {
        $global:SshT.Live = [pscustomobject]@{ Id = 51; StartTicks = [int64]7; Path = 'C:\tools\node.exe' }
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo { $global:SshT.Live }
        $bad = [ordered]@{ Pid = 51; StartTicks = [int64]7; Path = 'C:\tools\other.exe'; Kind = 'Tool'; Label = 'node'; Process = $null }
        Stop-HarnessTrackedProcess -Lane $script:lane -Entry $bad | Should -Be 'image-mismatch'
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 0 -Exactly
        $good = [ordered]@{ Pid = 51; StartTicks = [int64]7; Path = 'C:\tools\node.exe'; Kind = 'Tool'; Label = 'node'; Process = $null }
        Stop-HarnessTrackedProcess -Lane $script:lane -Entry $good | Should -Be 'killed'
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 1 -Exactly -ParameterFilter { $ProcessId -eq 51 }
    }
    It 'reports gone for a dead pid without killing' {
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo { $null }
        $e = [ordered]@{ Pid = 52; StartTicks = [int64]1; Path = 'x'; Kind = 'App'; Label = 'a'; Process = $null }
        Stop-HarnessTrackedProcess -Lane $script:lane -Entry $e | Should -Be 'gone'
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 0 -Exactly
    }
    It 'Stop-ProcessById is the only kill primitive and always targets -Id (no name-based stop anywhere in the module)' {
        $t = Get-Content -LiteralPath $script:LauncherPath -Raw
        $ast = [System.Management.Automation.Language.Parser]::ParseInput($t, [ref]$null, [ref]$null)
        $stops = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -in 'Stop-Process', 'taskkill', 'kill', 'spps' }, $true))
        $stops.Count | Should -Be 1
        $stops[0].Extent.Text | Should -Match '^Stop-Process -Id '
        $t | Should -Not -Match '(?i)Stop-Process\s+-Name|\|\s*Stop-Process|taskkill|\.Kill\('
    }
    It 'tools are restricted to node and ffmpeg' {
        foreach ($n in 'cmd', 'powershell', 'taskkill.exe', 'snapmaker-studio-desktop.exe', 'orca.exe') { { Resolve-HarnessToolPath -Name $n } | Should -Throw '*not an allowed tool*' }
    }
}

Describe 'Install arguments (never /P, /D= last and unquoted)' {
    It 'is exactly /S /NCRC /NS /D=<dir> with the directory last and unquoted' {
        $a = Get-InstallerArguments -InstallDir 'C:\h\SnapmakerStudio-Harness\install\run one'
        $a | Should -BeExactly '/S /NCRC /NS /D=C:\h\SnapmakerStudio-Harness\install\run one'
        $a | Should -Not -Match '"'
        $a | Should -Not -Match '(^|\s)/P(\s|$)'
        $a.EndsWith('run one') | Should -BeTrue    # the path (with its space) is the tail
        $a.IndexOf('/D=') | Should -BeGreaterThan $a.IndexOf('/NS')
    }
    It 'refuses a quote in the install dir' { { Get-InstallerArguments -InstallDir 'C:\a"b' } | Should -Throw '*quote*' }
    It 'the uninstaller is silent only' { InModuleScope HarnessLauncher { Get-UninstallerArguments } | Should -BeExactly '/S' }
}

Describe 'Installer lane: rewrapped acceptance installers only' {
    BeforeEach { $script:sb = New-Sandbox; Set-Hooks $script:sb; Set-DefaultMocks }
    AfterEach { Remove-Sandbox $script:sb }

    It 'refuses a wildcard / glob installer path (no discovery)' {
        { Resolve-HarnessBuild -InstallerPath 'C:\dl\*_x64-setup.exe' -AttestationPath 'C:\a\x.json' } | Should -Throw '*no wildcard*'
        { Resolve-HarnessBuild -RealInstaller 'C:\dl\?.exe' -ExpectedSha256 ('a' * 64) -SourceVersion '1.2.0' } | Should -Throw '*no wildcard*'
    }
    It 'refuses when no installer is given (there is no auto-discovery) and when both modes are mixed' {
        { Resolve-HarnessBuild } | Should -Throw '*auto-discovery*'
        { Resolve-HarnessBuild -InstallerPath 'C:\a.exe' -AttestationPath 'C:\a.json' -RealInstaller 'C:\b.exe' } | Should -Throw '*not both*'
    }
    It 'refuses the real production installer with a clear message and releases the lock' {
        Mock -ModuleName InstallGuard Get-ExeProductName { 'Snapmaker Studio' }
        $f = New-FakeInstallerAndAttestation $script:sb
        { New-TestLane $script:sb -Installer $f.Installer -Attestation $f.Attestation } | Should -Throw '*PRODUCTION identity*'
        Set-DefaultMocks
        $l = New-TestLane $script:sb -Installer $f.Installer -Attestation $f.Attestation
        try { $l.Completed | Should -BeFalse } finally { [void](Complete-HarnessLane -Lane $l) }
    }
    It 'refuses an installer that is not bound to a valid attestation' {
        $f = New-FakeInstallerAndAttestation $script:sb
        $a = Get-Content -LiteralPath $f.Attestation -Raw | ConvertFrom-Json -AsHashtable
        $a.installer.sha256 = ('9' * 64)
        $a | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $f.Attestation -Encoding utf8
        { New-TestLane $script:sb -Installer $f.Installer -Attestation $f.Attestation } | Should -Throw '*only a REWRAPPED acceptance-identity installer*'
    }
    It 'rewrap on demand goes through tools/release/rewrap_installer.ps1 with the verified inputs only' {
        $f = New-FakeInstallerAndAttestation $script:sb
        $global:SshT.Rewrap = [pscustomobject]@{ InstallerPath = $f.Installer; AttestationPath = $f.Attestation }
        Mock -ModuleName HarnessLauncher Invoke-RewrapScript { $global:SshT.Rewrap }
        $r = Resolve-HarnessBuild -RealInstaller 'C:\dl\real-setup.exe' -ExpectedSha256 ('A' * 64) -SourceVersion '1.2.0' -Sha256SumsPath 'C:\dl\SHA256SUMS' -HarnessRoot $script:sb.Harness
        $r.Rewrapped | Should -BeTrue
        $r.InstallerPath | Should -Be $f.Installer
        Should -Invoke -ModuleName HarnessLauncher Invoke-RewrapScript -Times 1 -Exactly -ParameterFilter {
            $Parameters.InstallerPath -eq 'C:\dl\real-setup.exe' -and $Parameters.ExpectedSha256 -eq ('A' * 64) -and $Parameters.SourceVersion -eq '1.2.0' -and
            $Parameters.Sha256SumsPath -eq 'C:\dl\SHA256SUMS' -and $Parameters.HarnessRoot -eq $script:sb.Harness
        }
        { Resolve-HarnessBuild -RealInstaller 'C:\dl\real.exe' -ExpectedSha256 'nothex' -SourceVersion '1.2.0' } | Should -Throw '*64-hex*'
        { Resolve-HarnessBuild -RealInstaller 'C:\dl\real.exe' -ExpectedSha256 ('a' * 64) } | Should -Throw '*SourceVersion*'
    }
    It 'passing ONLY -UpgradeFromSha256SumsPath activates upgrade validation and fails closed (never silently ignored), releasing the lock' {
        $f = New-FakeInstallerAndAttestation $script:sb
        { Start-HarnessLane -Name 't' -Kind acceptance -InstallerPath $f.Installer -AttestationPath $f.Attestation -UpgradeFromSha256SumsPath 'C:\dl\OLD-SHA256SUMS' `
                -HarnessRoot $script:sb.Harness -DebugPort (Get-FreePort) } | Should -Throw '*upgrade-from installer*'
        $l = New-TestLane $script:sb
        try { $l.Upgrade | Should -BeFalse } finally { [void](Complete-HarnessLane -Lane $l) }
    }
    It 'upgrade-from rewrap uses its OWN -UpgradeFromSha256SumsPath, and never silently reuses the primary SUMS file' -ForEach @(
        @{ Case = 'both'; UpSums = 'C:\dl\OLD-SHA256SUMS' }
        @{ Case = 'primary only'; UpSums = $null }
    ) {
        $new = New-FakeInstallerAndAttestation $script:sb
        $old = New-FakeInstallerAndAttestation $script:sb
        $global:SshT.RewrapNew = [pscustomobject]@{ InstallerPath = $new.Installer; AttestationPath = $new.Attestation }
        $global:SshT.RewrapOld = [pscustomobject]@{ InstallerPath = $old.Installer; AttestationPath = $old.Attestation }
        Mock -ModuleName HarnessLauncher Invoke-RewrapScript { if ($Parameters.InstallerPath -eq 'C:\dl\new-setup.exe') { $global:SshT.RewrapNew } else { $global:SshT.RewrapOld } }
        $extra = @{}
        if ($UpSums) { $extra.UpgradeFromSha256SumsPath = $UpSums }
        $lane = Start-HarnessLane -Name 't' -Kind acceptance -RealInstaller 'C:\dl\new-setup.exe' -ExpectedSha256 ('a' * 64) -SourceVersion '1.2.0' -Sha256SumsPath 'C:\dl\NEW-SHA256SUMS' `
            -UpgradeFromRealInstaller 'C:\dl\old-setup.exe' -UpgradeFromExpectedSha256 ('b' * 64) -UpgradeFromSourceVersion '1.1.0' @extra `
            -HarnessRoot $script:sb.Harness -DebugPort (Get-FreePort)
        try {
            $lane.Upgrade | Should -BeTrue
            Should -Invoke -ModuleName HarnessLauncher Invoke-RewrapScript -Times 1 -Exactly -ParameterFilter {
                $Parameters.InstallerPath -eq 'C:\dl\new-setup.exe' -and $Parameters.Sha256SumsPath -eq 'C:\dl\NEW-SHA256SUMS' }
            if ($UpSums) {
                Should -Invoke -ModuleName HarnessLauncher Invoke-RewrapScript -Times 1 -Exactly -ParameterFilter {
                    $Parameters.InstallerPath -eq 'C:\dl\old-setup.exe' -and $Parameters.Sha256SumsPath -eq 'C:\dl\OLD-SHA256SUMS' }
            } else {
                Should -Invoke -ModuleName HarnessLauncher Invoke-RewrapScript -Times 1 -Exactly -ParameterFilter {
                    $Parameters.InstallerPath -eq 'C:\dl\old-setup.exe' -and -not $Parameters.ContainsKey('Sha256SumsPath') }
            }
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }
    It 'a second concurrent run is refused by the machine-wide lock; the first keeps working' {
        $l1 = New-TestLane $script:sb
        try {
            { New-TestLane $script:sb } | Should -Throw '*Refused*'
            $l1.Completed | Should -BeFalse
        } finally { [void](Complete-HarnessLane -Lane $l1) }
        $l3 = New-TestLane $script:sb
        [void](Complete-HarnessLane -Lane $l3)
    }
}

Describe 'Production-state tripwire (detect and report only)' {
    BeforeEach { $script:sb = New-Sandbox; Set-Hooks $script:sb }
    AfterEach { Remove-Sandbox $script:sb }

    It 'is clean when nothing changed (all absent)' {
        $a = Get-ProductionStateSnapshot; $b = Get-ProductionStateSnapshot
        @(Compare-ProductionStateSnapshot -Before $a -After $b) | Should -BeNullOrEmpty
    }
    It 'Roaming bundle-id folder must stay ABSENT: any appearance (even an empty folder) is a violation' {
        $a = Get-ProductionStateSnapshot
        New-Item -ItemType Directory -Path $script:sb.Roaming -Force | Out-Null
        (@(Compare-ProductionStateSnapshot -Before $a -After (Get-ProductionStateSnapshot)) -join '|') | Should -Match 'Roaming.*APPEARED'
    }
    It 'Local bundle-id folder may go absent -> EMPTY only' {
        $a = Get-ProductionStateSnapshot
        New-Item -ItemType Directory -Path $script:sb.Local -Force | Out-Null
        @(Compare-ProductionStateSnapshot -Before $a -After (Get-ProductionStateSnapshot)) | Should -BeNullOrEmpty
        [IO.File]::WriteAllText((Join-Path $script:sb.Local 'x.txt'), 'x')
        (@(Compare-ProductionStateSnapshot -Before $a -After (Get-ProductionStateSnapshot)) -join '|') | Should -Match 'Local.*appeared with 1'
    }
    It 'the production engine folder is detect-only: appearing is a violation' {
        $a = Get-ProductionStateSnapshot
        New-Item -ItemType Directory -Path $script:sb.Engine -Force | Out-Null
        (@(Compare-ProductionStateSnapshot -Before $a -After (Get-ProductionStateSnapshot)) -join '|') | Should -Match 'engine data folder APPEARED'
    }
    It 'detects an ADD, a CHANGE and a DELETE inside pre-existing fixture production dirs' {
        foreach ($d in $script:sb.Roaming, $script:sb.Local, $script:sb.Engine) { New-Item -ItemType Directory -Path $d -Force | Out-Null; [IO.File]::WriteAllText((Join-Path $d 'keep.txt'), 'one'); [IO.File]::WriteAllText((Join-Path $d 'gone.txt'), 'g') }
        $a = Get-ProductionStateSnapshot
        [IO.File]::WriteAllText((Join-Path $script:sb.Roaming 'new.txt'), 'n')
        [IO.File]::WriteAllText((Join-Path $script:sb.Local 'keep.txt'), 'twotwo')
        Remove-Item (Join-Path $script:sb.Engine 'gone.txt')
        $v = @(Compare-ProductionStateSnapshot -Before $a -After (Get-ProductionStateSnapshot)) -join '|'
        $v | Should -Match 'Roaming.*ADDED'
        $v | Should -Match 'Local.*CHANGED'
        $v | Should -Match 'engine data.*REMOVED'
    }
    It 'detects a Local Storage leveldb byte change that keeps size and mtime (hash, read-only)' {
        $ldb = Join-Path $script:sb.Local 'EBWebView\Default\Local Storage\leveldb'
        New-Item -ItemType Directory -Path $ldb -Force | Out-Null
        $f = Join-Path $ldb '000003.log'
        [IO.File]::WriteAllBytes($f, [byte[]](1..20)); $mt = (Get-Item $f).LastWriteTimeUtc
        $a = Get-ProductionStateSnapshot
        [IO.File]::WriteAllBytes($f, [byte[]](2..21)); (Get-Item $f).LastWriteTimeUtc = $mt
        (@(Compare-ProductionStateSnapshot -Before $a -After (Get-ProductionStateSnapshot)) -join '|') | Should -Match 'Local.*CHANGED'
    }
    It 'reads leveldb files with share-read: an open writer does not stop the snapshot' {
        $ldb = Join-Path $script:sb.Local 'EBWebView\Default\Local Storage\leveldb'
        New-Item -ItemType Directory -Path $ldb -Force | Out-Null
        $fs = [IO.File]::Open((Join-Path $ldb 'LOCK'), [IO.FileMode]::Create, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
        try { $s = Get-ProductionStateSnapshot; $s.Local.Entries['EBWebView\Default\Local Storage\leveldb\LOCK'] | Should -Match '^file\|0\|\d+\|[0-9a-f]{64}$' } finally { $fs.Dispose() }
    }
    It 'NEVER restores or deletes: the changed fixture stays changed after the comparison' {
        New-Item -ItemType Directory -Path $script:sb.Roaming -Force | Out-Null
        $f = Join-Path $script:sb.Roaming 'p.txt'; [IO.File]::WriteAllText($f, 'before')
        $a = Get-ProductionStateSnapshot
        [IO.File]::WriteAllText($f, 'after-change'); [IO.File]::WriteAllText((Join-Path $script:sb.Roaming 'added.txt'), 'a')
        [void](Compare-ProductionStateSnapshot -Before $a -After (Get-ProductionStateSnapshot))
        Get-Content $f -Raw | Should -Match 'after-change'
        Test-Path (Join-Path $script:sb.Roaming 'added.txt') | Should -BeTrue
    }
    It 'the tripwire and preflight functions contain no mutating command' {
        $bad = InModuleScope HarnessLauncher {
            $mut = 'Remove-Item', 'Set-Content', 'Add-Content', 'Copy-Item', 'Move-Item', 'New-Item', 'Out-File', 'Set-ItemProperty', 'Clear-Content', 'Rename-Item', 'Stop-Process', 'Set-Item'
            $out = @()
            foreach ($fn in 'Get-DirectoryStateSnapshot', 'Get-ProductionStateSnapshot', 'Compare-DirectorySnapshot', 'Compare-ProductionStateSnapshot', 'Test-ProductionTripwire', 'Assert-UpdateCheckPreflight', 'Get-AcceptanceShortcutFindings', 'Assert-NoAcceptanceShortcutInRealFolders') {
                $ast = (Get-Command $fn).ScriptBlock.Ast
                foreach ($c in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true)) { if ($c.GetCommandName() -in $mut) { $out += "$fn : $($c.GetCommandName())" } }
                # No .NET mutators either.
                if ($ast.Extent.Text -match '\[IO\.(File|Directory)\]::(Delete|Move|Copy|WriteAll|Create|Replace)|\.Delete\(|\.MoveTo\(') { $out += "$fn : .NET mutator" }
            }
            $out
        }
        $bad | Should -BeNullOrEmpty
    }
    It 'Test-ProductionTripwire records findings on the lane and does not touch the disk' {
        Set-DefaultMocks
        $lane = New-TestLane $script:sb
        try {
            New-Item -ItemType Directory -Path $script:sb.Roaming -Force | Out-Null
            $v = @(Test-ProductionTripwire -Lane $lane -Stage 'mid')
            $v.Count | Should -BeGreaterThan 0
            ($lane.Findings -join '|') | Should -Match '\[tripwire:mid\].*Roaming'
            Test-Path $script:sb.Roaming | Should -BeTrue
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }
}

Describe 'Real Start Menu / Desktop: read-only absence assertion' {
    BeforeEach { $script:sb = New-Sandbox; Set-Hooks $script:sb; Set-DefaultMocks }
    AfterEach { Remove-Sandbox $script:sb }

    It 'passes when no acceptance shortcut exists' { { Assert-NoAcceptanceShortcutInRealFolders } | Should -Not -Throw }
    It 'refuses (and changes nothing) when an acceptance shortcut exists in either real folder' {
        foreach ($dir in $script:sb.RealStartMenu, $script:sb.RealDesktop) {
            $lnk = Join-Path $dir "$($script:Acc.ProductName).lnk"
            [IO.File]::WriteAllBytes($lnk, [byte[]](1, 2, 3)); $mt = (Get-Item $lnk).LastWriteTimeUtc
            { Assert-NoAcceptanceShortcutInRealFolders } | Should -Throw '*acceptance-identity shortcut exists*'
            [IO.File]::ReadAllBytes($lnk) | Should -Be ([byte[]](1, 2, 3))
            (Get-Item $lnk).LastWriteTimeUtc | Should -Be $mt
            Remove-Item $lnk
        }
    }
    It 'lane start refuses while an acceptance shortcut sits in a real folder' {
        [IO.File]::WriteAllBytes((Join-Path $script:sb.RealDesktop "$($script:Acc.ProductName).lnk"), [byte[]](1))
        { New-TestLane $script:sb } | Should -Throw '*acceptance-identity shortcut exists*'
    }
    It 'uses Test-Path only (no other filesystem command) on the real folders' {
        $names = InModuleScope HarnessLauncher {
            $ast = (Get-Command Get-AcceptanceShortcutFindings).ScriptBlock.Ast
            @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true) | ForEach-Object { $_.GetCommandName() } | Sort-Object -Unique)
        }
        @($names | Where-Object { $_ -notin 'Test-Path', 'Join-Path', 'Get-Hook', 'Split-Path', 'throw' }) | Should -BeNullOrEmpty
        $names | Should -Contain 'Test-Path'
    }
    It 'journal destinations are harness-owned EMPTY dirs, not the real known folders' {
        $lane = New-TestLane $script:sb
        try {
            foreach ($d in 'StartMenu', 'Desktop') {
                $p = Join-Path $lane.ShortcutDir $d
                Test-Path $p -PathType Container | Should -BeTrue
                @(Get-ChildItem -LiteralPath $p -Force).Count | Should -Be 0
                Test-PathContained -Path $p -Root $script:sb.Harness | Should -BeTrue
            }
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }
}

Describe 'Install / uninstall / journal ordering and the always-run finally path' {
    BeforeEach {
        $script:sb = New-Sandbox; Set-Hooks $script:sb; Set-DefaultMocks
        $global:SshT = @{ Launches = [System.Collections.Generic.List[string]]::new(); Sb = $script:sb; ProdPath = $script:sb.Roaming; InstallerExit = 0 }
        Mock -ModuleName HarnessLauncher Get-LiveProcessInfo { [pscustomobject]@{ Id = $ProcessId; StartTicks = [int64]1; Path = 'C:\x\y.exe' } }
        Mock -ModuleName HarnessLauncher Stop-ProcessById { }
        Mock -ModuleName HarnessLauncher Get-Win32CommandLines {
            if ($global:SshT.CimThrow) { throw $global:SshT.CimThrow }
            if ($global:SshT.HandoffGoneAfter) { $global:SshT.CimCalls++; if ($global:SshT.CimCalls -le $global:SshT.HandoffGoneAfter) { return @([pscustomobject]@{ ProcessId = 999999; CommandLine = $global:SshT.HandoffCmd }) } else { return @() } }
            if ($global:SshT.HandoffCmd) { @([pscustomobject]@{ ProcessId = 999999; CommandLine = $global:SshT.HandoffCmd }) } else { @() }
        }
        Mock -ModuleName HarnessLauncher Start-HarnessChildProcess {
            $t = $global:SshT
            $t.Launches.Add("$FilePath|$ArgumentString")
            $regRoot = $t.Sb.RegRoot
            $key = "$regRoot\Microsoft\Windows\CurrentVersion\Uninstall\Snapmaker Studio Acceptance"
            if ($ArgumentString -like '/S /NCRC*') {
                # The journal MUST already exist when the installer starts.
                $t.JournalExistedAtInstall = @(Get-ChildItem -LiteralPath (Join-Path $t.Sb.Harness 'journal') -Filter '*.json' -ErrorAction SilentlyContinue).Count -gt 0
                $t.InstallArgs = $ArgumentString; $t.InstallFile = $FilePath
                $dir = $ArgumentString.Substring($ArgumentString.IndexOf('/D=') + 3)
                New-Item -ItemType Directory -Force -Path $dir | Out-Null
                if ($t.Partial) {
                    # killed / partial install: the exe is copied first; no uninstaller and no registration yet
                    [IO.File]::WriteAllText((Join-Path $dir 'snapmaker-studio-acceptance-desktop.exe'), 'partial')
                } else {
                    [IO.File]::WriteAllText((Join-Path $dir 'uninstall.exe'), 'fake uninstaller')
                    if ($t.InstallerExit -eq 0) {
                        New-Item -Path $key -Force | Out-Null
                        Set-ItemProperty -LiteralPath $key -Name UninstallString -Value ('"' + (Join-Path $dir 'uninstall.exe') + '"')
                    }
                }
                $p = [pscustomobject]@{ Id = 7001; ExitCode = $t.InstallerExit; TimesOut = [bool]$t.Timeout }
            } else {
                $t.UninstallArgs = $ArgumentString
                if ($t.UninstallThrow) { throw $t.UninstallThrow }
                $dir = Split-Path -Parent $FilePath
                Remove-Item -LiteralPath $key -Recurse -Force -ErrorAction SilentlyContinue
                if (-not $t.KeepFiles) { Get-ChildItem -LiteralPath $dir -Force | Remove-Item -Recurse -Force }
                $p = [pscustomobject]@{ Id = 7002; ExitCode = [int]$t.UninstallExit; TimesOut = [bool]$t.UninstallTimeout }
            }
            $p | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value { param($ms) -not $this.TimesOut }
            $p
        }
    }
    AfterEach { Remove-Sandbox $script:sb; $global:SshT = @{} }

    It 'writes the journal BEFORE the installer starts and launches the staged copy with the exact arguments' {
        $lane = New-TestLane $script:sb
        try {
            $r = Install-HarnessBuild -Lane $lane -Which Primary
            $r.ExitCode | Should -Be 0
            $global:SshT.JournalExistedAtInstall | Should -BeTrue
            $global:SshT.InstallArgs | Should -BeExactly "/S /NCRC /NS /D=$($lane.InstallDir)"
            $global:SshT.InstallArgs | Should -Not -Match '(^|\s)/P(\s|$)'
            $global:SshT.InstallFile | Should -BeLike (Join-Path $script:sb.Harness 'staging\*')
            $lane.InstallDir | Should -BeLike (Join-Path $script:sb.Harness 'install\*')
            (Read-HarnessJournal -RunId $lane.RunId -HarnessRoot $script:sb.Harness)['state'] | Should -Be 'installed'
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }
    It 'Confirm-InstallerUnchanged runs immediately before the launch: a swapped staged copy is refused and nothing starts' {
        $lane = New-TestLane $script:sb
        try {
            $staged = $lane.Builds['Primary'].Staged.Path
            [IO.File]::WriteAllText($staged, 'tampered after authorization')
            { Install-HarnessBuild -Lane $lane -Which Primary } | Should -Throw '*changed between authorization and exec*'
            @($global:SshT.Launches | Where-Object { $_ -like '*/S /NCRC*' }).Count | Should -Be 0
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }
    It 'uninstall is silent /S only, after the uninstaller guard, and the journal is finalised' {
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $res = Complete-HarnessLane -Lane $lane
        $global:SshT.UninstallArgs | Should -BeExactly '/S'
        $res.Uninstall.Attempted | Should -BeTrue
        $res.Uninstall.ExitCode | Should -Be 0
        $res.ExitCode | Should -Be 0
        $lane.Phases[0].Finalized | Should -BeTrue
        Test-Path (Join-Path $script:sb.Harness "journal\$($lane.RunId).recovered.json") | Should -BeTrue
    }
    It 'the finally path runs uninstall + tripwire + lock release even when a lane step throws' {
        $lane = New-TestLane $script:sb
        $res = $null
        try {
            [void](Install-HarnessBuild -Lane $lane -Which Primary)
            New-Item -ItemType Directory -Path $script:sb.Roaming -Force | Out-Null      # production state changes mid-lane
            throw 'a lane step failed'
        } catch { $caught = $_.Exception.Message } finally { $res = Complete-HarnessLane -Lane $lane }
        $caught | Should -Be 'a lane step failed'
        $global:SshT.UninstallArgs | Should -BeExactly '/S'
        $res.ExitCode | Should -Be 1
        ($res.Findings -join '|') | Should -Match 'tripwire.*Roaming'
        Test-Path $script:sb.Roaming | Should -BeTrue            # reported, never removed
        $l2 = New-TestLane $script:sb                              # lock was released
        [void](Complete-HarnessLane -Lane $l2)
    }
    It '-KeepInstall does not uninstall but STILL reports the tripwire, keeps the journal, says so in the evidence, and frees the lock' {
        $lane = New-TestLane $script:sb -KeepInstall
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        New-Item -ItemType Directory -Path $script:sb.Roaming -Force | Out-Null
        $res = Complete-HarnessLane -Lane $lane
        $global:SshT.ContainsKey('UninstallArgs') | Should -BeFalse
        $res.Uninstall | Should -BeNullOrEmpty
        $res.ExitCode | Should -Be 1
        ($res.Findings -join '|') | Should -Match 'tripwire.*Roaming'
        $res.Evidence.keptInstall | Should -BeTrue
        $res.Evidence.keptInstall | Should -BeTrue
        Test-Path (Join-Path $script:sb.Harness "journal\$($lane.RunId).json") | Should -BeTrue
        $res.Evidence.repair.shortcutDir | Should -Be "run\$($lane.RunId)\shortcuts"
        @($res.Evidence.repair.journalIds) | Should -Contain $lane.RunId
        # The pending journal blocks the next run (and the refusal is the journal rule, not a stuck lock).
        { New-TestLane $script:sb } | Should -Throw '*unfinished harness journal*'
    }
    It 'an installer that dies before the journal is finalised: uninstall is refused, the error and tripwire are still reported' {
        $lane = New-TestLane $script:sb
        $j = New-HarnessJournal -RunId $lane.RunId -InstallDir $lane.InstallDir -InstallVersion '1.2.0' -RegistryRoot $script:sb.RegRoot -ShortcutDir $lane.ShortcutDir -HarnessRoot $script:sb.Harness
        $lane.Phases.Add([ordered]@{ RunId = $lane.RunId; Which = 'Primary'; Journal = $j; InstallerSha256 = 'x'; Version = '1.2.0'; InstallExitCode = $null; Finalized = $null })
        New-Item -ItemType Directory -Path $script:sb.Roaming -Force | Out-Null
        $res = Complete-HarnessLane -Lane $lane
        $global:SshT.ContainsKey('UninstallArgs') | Should -BeFalse
        ($res.Errors -join '|') | Should -Match "uninstall:.*not 'installed'"
        ($res.Findings -join '|') | Should -Match 'tripwire.*Roaming'
        $res.ExitCode | Should -Be 1
        # NotLaunched is on the recovery allow-list (nothing ran, install dir empty): the journal IS finalised.
        $res.Evidence.uninstallOutcome | Should -Be 'NotLaunched'
        Test-Path (Join-Path $script:sb.Harness "journal\$($lane.RunId).recovered.json") | Should -BeTrue
    }
    It 'X1: Protect-LaneText never leaks the tail of a path containing spaces (quoted, unquoted, UNC, double-quoted)' {
        $lane = New-TestLane $script:sb
        try {
            $cases = @(
                @{ t = "Could not find file 'C:\Users\Someone Else\My Models\PRIVATE-benchy-zq91.stl'."; bad = 'Someone', 'My Models', 'PRIVATE', 'zq91', 'benchy' }
                @{ t = 'failed to read D:\Private Models\customer alpha.3mf'; bad = 'Private', 'customer', 'alpha', '3mf' }
                @{ t = 'denied \\file server\share name\Secret Dir\plan v2.txt; next step ok'; bad = 'file server', 'share name', 'Secret', 'plan v2'; keep = 'next step ok' }
                @{ t = 'open C:\My Docs\a b.stl : access denied'; bad = 'My Docs', 'a b'; keep = 'access denied' }
                @{ t = 'load "E:\Cust Alpha\Job Two\part.3mf" now'; bad = 'Cust Alpha', 'Job Two', 'part'; keep = 'now' }
            )
            foreach ($c in $cases) {
                $out = Protect-LaneText -Text $c.t -Lane $lane
                foreach ($b in $c.bad) { $out | Should -Not -Match ([regex]::Escape($b)) -Because "input: $($c.t)" }
                if ($c.keep) { $out | Should -Match ([regex]::Escape($c.keep)) }
                $out | Should -Match '<path>'
            }
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }
    It 'X2: a failing evidence write FAILS the report (non-zero), prints scrubbed findings/errors and a scrubbed message' {
        Mock -ModuleName HarnessLauncher Write-HarnessLaneEvidence { throw "locked: C:\Users\Some One\Priv Dir\x.json" }
        $lane = New-TestLane $script:sb
        $res = Complete-HarnessLane -Lane $lane
        $lane.Errors.Add('seeded cleanup error') | Out-Null
        $iv = $null
        $rc = Publish-HarnessLaneReport -Lane $lane -Result $res -EvidencePath (Join-Path $script:sb.Dir 'e.json') -InformationAction Continue -InformationVariable iv 6>$null
        $rc | Should -Be 1
        $txt = ($iv | ForEach-Object { "$_" }) -join '|'
        $txt | Should -Match 'lane evidence could not be written'
        $txt | Should -Match 'seeded cleanup error'
        $txt | Should -Not -Match 'Some One|Priv Dir'
    }
    It 'X2: a successful report returns 0, a -Failed lane or a missing result returns 1' {
        $lane = New-TestLane $script:sb
        $res = Complete-HarnessLane -Lane $lane
        Publish-HarnessLaneReport -Lane $lane -Result $res -EvidencePath (Join-Path $script:sb.Dir 'ok.json') 6>$null | Should -Be 0
        Publish-HarnessLaneReport -Lane $lane -Result $res -EvidencePath (Join-Path $script:sb.Dir 'ok2.json') -Failed 6>$null | Should -Be 1
        Publish-HarnessLaneReport -Lane $lane -Result $null -EvidencePath (Join-Path $script:sb.Dir 'ok3.json') 6>$null | Should -Be 1
    }
    It 'a: an ambiguous (null) directory state labels the outcome Unknown, not Failed' {
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        Mock -ModuleName HarnessLauncher Get-InstallDirFileList { throw 'access denied' }
        $res = Complete-HarnessLane -Lane $lane
        $res.Evidence.uninstallOutcome | Should -Be 'Unknown'
    }
    It 'a: a definite failure (non-zero uninstaller exit, state known) is labelled Failed' {
        $global:SshT.UninstallExit = 3
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $res = Complete-HarnessLane -Lane $lane
        $res.Evidence.uninstallOutcome | Should -Be 'Failed'
        $lane.Phases[0].Finalized | Should -BeFalse
    }
    It 'CLOSED SCHEMA: hostile exception text <t> fed through the real lane and evidence path never reaches the persisted file' -ForEach @(
        @{ t = 'apostrophe in a folder name'; text = "Could not find 'D:\Private O'Brien\customer alpha.3mf'"; segs = @('Private', 'Brien', 'customer', 'alpha', '3mf') }
        @{ t = 'spaced relative path'; text = 'Private Models\customer alpha.3mf'; segs = @('Private', 'Models', 'customer', 'alpha', '3mf') }
        @{ t = 'forward-slash path'; text = 'C:/Users/Someone Else/Private Models/customer alpha.3mf'; segs = @('Someone', 'Private', 'customer', 'alpha') }
        @{ t = 'literal doubled backslashes'; text = 'C:\\Users\\Someone Else\\Private Models\\customer alpha.3mf'; segs = @('Someone', 'Private', 'customer', 'alpha') }
        @{ t = 'trailing spaces'; text = 'D:\Private Models\customer alpha.3mf     '; segs = @('Private', 'customer', 'alpha') }
        @{ t = 'UNC path'; text = '\\fileserver\Private Share\customer alpha.3mf'; segs = @('fileserver', 'Private', 'customer', 'alpha') }
        @{ t = 'absolute drive path'; text = 'E:\Cust Alpha\job zq91\part.3mf'; segs = @('Cust', 'Alpha', 'zq91', 'part') }
        @{ t = 'arbitrary text with private local data'; text = 'state dump: model customer-alpha-zq91 at /home/zq91/private/customer.stl (owner Zq91Person)'; segs = @('customer', 'alpha', 'zq91', 'Zq91Person', 'private') }
    ) {
        Mock -ModuleName HarnessLauncher Invoke-HarnessRecovery { throw 'recovery must not run (UNKNOWN_OUTCOME keeps the journal pending)' }
        $global:SshT.UninstallThrow = $text
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $res = Complete-HarnessLane -Lane $lane
        $res.ExitCode | Should -Be 1
        Should -Invoke -ModuleName HarnessLauncher Invoke-HarnessRecovery -Times 0 -Exactly
        Test-Path (Join-Path $script:sb.Harness "journal\$($lane.RunId).json") | Should -BeTrue
        $res.Evidence.uninstallOutcome | Should -Be 'Unknown'
        $f = Join-Path $script:sb.Dir 'closed.json'
        [void](Write-HarnessLaneEvidence -Lane $lane -Evidence $res.Evidence -Path $f)
        $raw = Get-Content -LiteralPath $f -Raw
        $raw | Should -Not -Match ([regex]::Escape($text.Trim()))
        $raw | Should -Not -Match ([regex]::Escape($text.Trim().Substring([Math]::Max(0, $text.Trim().Length - 12))))
        foreach ($seg in $segs) { $raw | Should -Not -Match ([regex]::Escape($seg)) -Because "segment '$seg' of: $text" }
        $raw | Should -Not -Match ([regex]::Escape([Environment]::UserName))
        $parsed = $raw | ConvertFrom-Json -AsHashtable
        Test-HarnessLaneEvidenceSchema -Evidence $parsed | Should -BeNullOrEmpty
        @($parsed.reasonCodes | ForEach-Object { $_.code }) | Should -Contain 'UNKNOWN_OUTCOME'
    }
    It 'CLOSED SCHEMA: the user name in any casing never reaches the persisted file or the closed object' {
        $user = [Environment]::UserName
        $global:SshT.UninstallThrow = "boom for $($user.ToUpper()) and $($user.ToLower()) in $user"
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $res = Complete-HarnessLane -Lane $lane
        $f = Join-Path $script:sb.Dir 'closed-user.json'
        [void](Write-HarnessLaneEvidence -Lane $lane -Evidence $res.Evidence -Path $f)
        (Get-Content -LiteralPath $f -Raw) | Should -Not -Match ([regex]::Escape($user))
        ($res.Evidence | ConvertTo-Json -Depth 8) | Should -Not -Match ([regex]::Escape($user))
    }
    It 'CLOSED SCHEMA: console reporting still prints scrubbed detail independently of the evidence, while the file holds none of it' {
        $global:SshT.UninstallThrow = "Could not find file 'C:\Users\Someone Else\My Models\PRIVATE-benchy-zq91.stl'"
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $res = Complete-HarnessLane -Lane $lane
        $f = Join-Path $script:sb.Dir 'console.json'
        $iv = $null
        $rc = Publish-HarnessLaneReport -Lane $lane -Result $res -EvidencePath $f -InformationAction Continue -InformationVariable iv 6>$null
        $rc | Should -Be 1
        $console = ($iv | ForEach-Object { "$_" }) -join '|'
        $console | Should -Match 'uninstall outcome unknown'
        $console | Should -Not -Match 'Someone|My Models|PRIVATE|zq91'
        $raw = Get-Content -LiteralPath $f -Raw
        $raw | Should -Not -Match 'outcome unknown \(error'
        $raw | Should -Not -Match 'Someone|My Models|PRIVATE|zq91|benchy'
    }
    It 'CLOSED SCHEMA: the persisted property set is a subset of the whitelist; an unknown property, free text or a bad code is rejected and nothing is written' {
        $lane = New-TestLane $script:sb
        $res = Complete-HarnessLane -Lane $lane
        $good = $res.Evidence
        Test-HarnessLaneEvidenceSchema -Evidence $good | Should -BeNullOrEmpty
        $variants = @{
            'unknown property'          = { param($e) $e['detail'] = 'free text' }
            'raw errors array'          = { param($e) $e['errors'] = @('boom') }
            'unknown code'              = { param($e) $e['reasonCodes'] = @([ordered]@{ code = 'MADE_UP_CODE'; count = 1 }) }
            'free text in a version'    = { param($e) $e['sourceVersion'] = 'C:\x\y' }
            'path in installDir'        = { param($e) $e['installDir'] = 'C:\x\y' }
            'unknown nested property'   = { param($e) $e['tripwire']['name'] = 'x' }
            'string where int expected' = { param($e) $e['errorCount'] = 'many' }
            'free-text lane label'      = { param($e) $e['lane'] = 'my own text' }
        }
        foreach ($name in $variants.Keys) {
            $copy = $good | ConvertTo-Json -Depth 8 | ConvertFrom-Json -AsHashtable
            & $variants[$name] $copy
            Test-HarnessLaneEvidenceSchema -Evidence $copy | Should -Not -BeNullOrEmpty -Because $name
            $f = Join-Path $script:sb.Dir ("reject-$([guid]::NewGuid().ToString('N')).json")
            { Write-HarnessLaneEvidence -Lane $lane -Evidence $copy -Path $f } | Should -Throw '*REPORT_WRITE_FAILED*'
            Test-Path -LiteralPath $f | Should -BeFalse
        }
        { Write-HarnessLaneEvidence -Lane $lane -Evidence $null -Path (Join-Path $script:sb.Dir 'null.json') } | Should -Throw '*REPORT_WRITE_FAILED*'
    }
    It 'CLOSED SCHEMA: every code is from the fixed list; an unmapped error is UNCLASSIFIED_ERROR (even one added without a code)' {
        $lane = New-TestLane $script:sb
        InModuleScope HarnessLauncher -Parameters @{ L = $lane } { Add-LaneError -Lane $L -Text 'x' -Code 'MADE_UP'; Add-LaneWarning -Lane $L -Text 'y' }
        [void]$lane.Errors.Add('added without any code')
        $res = Complete-HarnessLane -Lane $lane
        $list = InModuleScope HarnessLauncher { $script:ReasonCodes }
        $res.Evidence.reasonCodes.Count | Should -BeGreaterThan 0
        foreach ($c in @($res.Evidence.reasonCodes) + @($res.Evidence.warningCodes)) { $list | Should -Contain $c.code }
        (@($res.Evidence.reasonCodes | Where-Object { $_.code -eq 'UNCLASSIFIED_ERROR' }) | ForEach-Object { $_.count } | Measure-Object -Sum).Sum | Should -Be 2
        @($res.Evidence.warningCodes | ForEach-Object { $_.code }) | Should -Contain 'UNCLASSIFIED_ERROR'
        $list | Should -Contain 'UNCLASSIFIED_ERROR'
        foreach ($required in 'INSTALLER_PREFLIGHT_FAILED', 'INSTALL_FAILED', 'INSTALL_TIMEOUT', 'ORPHANED_INSTALL', 'UNINSTALL_FAILED', 'UNINSTALL_HANDOFF_INCOMPLETE', 'UNKNOWN_OUTCOME', 'RECOVERY_PENDING', 'APP_LAUNCH_FAILED', 'WEBVIEW_PREFLIGHT_FAILED', 'PROFILE_CHECK_FAILED', 'CDP_CHECK_FAILED', 'PORT_IN_USE', 'PRODUCTION_RUNNING', 'UPDATE_CHECK_PREFLIGHT_FAILED', 'TRIPWIRE_VIOLATION', 'SHORTCUT_ASSERTION_FAILED', 'PENDING_JOURNAL_BLOCKS_LANE', 'TOOL_NOT_ALLOWED', 'REPORT_WRITE_FAILED', 'LANE_STEP_FAILED', 'LOCK_RELEASE_FAILED', 'SOURCE_VERSION_UNRECOGNISED') { $list | Should -Contain $required }
    }
    It 'CLOSED SCHEMA: real failures map to their codes (orphan, timeout, handoff, tripwire, lock)' {
        $global:SshT.Partial = $true
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        New-Item -ItemType Directory -Path $script:sb.Roaming -Force | Out-Null
        $res = Complete-HarnessLane -Lane $lane
        $codes = @($res.Evidence.reasonCodes | ForEach-Object { $_.code })
        $codes | Should -Contain 'ORPHANED_INSTALL'
        $codes | Should -Contain 'TRIPWIRE_VIOLATION'
        $res.Evidence.tripwire.structural | Should -BeGreaterThan 0
        $res.Evidence.orphanedInstall.files | Should -BeGreaterThan 0
        $res.Evidence.status | Should -Be 'fail'
    }
    It 'CLOSED SCHEMA: a lock-release failure is in the persisted evidence as a code and a count' {
        Mock -ModuleName HarnessLauncher Exit-HarnessLock { throw 'release failed' }
        $lane = New-TestLane $script:sb
        $res = Complete-HarnessLane -Lane $lane
        $res.ExitCode | Should -Be 1
        $res.Evidence.errorCount | Should -BeGreaterThan 0
        @($res.Evidence.reasonCodes | ForEach-Object { $_.code }) | Should -Contain 'LOCK_RELEASE_FAILED'
    }
    It 'CLOSED SCHEMA: the secondary check fails the write closed (nothing persisted) when a redacted value is present in the output' {
        $lane = New-TestLane $script:sb
        $res = Complete-HarnessLane -Lane $lane
        $f = Join-Path $script:sb.Dir 'secondary.json'
        { Write-HarnessLaneEvidence -Lane $lane -Evidence $res.Evidence -Path $f -Redact @('acceptance') } | Should -Throw '*REPORT_WRITE_FAILED*'
        Test-Path -LiteralPath $f | Should -BeFalse
    }
    It 'evidence names the lane honestly, uses harness-relative names only and states what is not proven' {
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $res = Complete-HarnessLane -Lane $lane
        $ev = $res.Evidence
        $ev.schema | Should -Be 'harness-lane-evidence/3'
        $ev.lane | Should -Be 'rewrapped acceptance-identity installer'
        $ev.identity | Should -Be 'acceptance'
        $ev.status | Should -Be 'pass'
        $ev.installArguments | Should -Be '/S /NCRC /NS /D=<install dir>'
        $ev.notProven | Should -Match 'NOT proven'
        $ev.installDir | Should -Be "install\$($lane.RunId)"
        $ev.journals[0].runId | Should -Be $lane.RunId
        ($ev | ConvertTo-Json -Depth 8) | Should -Not -Match 'ssh-launch-test'
    }
    It 'B1a: a human-chosen run id is refused, never reaches the evidence, and the schema rejects an in-pattern-looking word' {
        $f = New-FakeInstallerAndAttestation $script:sb
        { Start-HarnessLane -Name 't' -Kind acceptance -InstallerPath $f.Installer -AttestationPath $f.Attestation -HarnessRoot $script:sb.Harness -RunId 'Private-Customer-Alpha' -DebugPort (Get-FreePort) } | Should -Throw '*opaque and generated*'
        { Start-HarnessLane -Name 't' -Kind acceptance -InstallerPath $f.Installer -AttestationPath $f.Attestation -HarnessRoot $script:sb.Harness -RunId ('h' + ('a' * 31) + 'Z') -DebugPort (Get-FreePort) } | Should -Throw '*opaque and generated*'
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $res = Complete-HarnessLane -Lane $lane
        $lane.RunId | Should -Match '^h[0-9a-f]{32}$'
        $copy = $res.Evidence | ConvertTo-Json -Depth 8 | ConvertFrom-Json -AsHashtable
        Test-HarnessLaneEvidenceSchema -Evidence $copy | Should -BeNullOrEmpty
        foreach ($mut in @(
                { param($e) $e['journals'][0]['runId'] = 'Private-Customer-Alpha' },
                { param($e) $e['installDir'] = 'install\Private-Customer-Alpha' },
                { param($e) $e['installDir'] = 'install\hprivatecustomeralphaprivatecustomer' },
                { param($e) $e['orphanedInstall'] = [ordered]@{ files = 1; dir = 'install\Customer-Alpha-Private' } },
                { param($e) $e['repair'] = [ordered]@{ journalIds = @('Customer-Alpha-Private'); shortcutDir = 'run\Customer-Alpha-Private\shortcuts' } })) {
            $c = $res.Evidence | ConvertTo-Json -Depth 8 | ConvertFrom-Json -AsHashtable
            & $mut $c
            Test-HarnessLaneEvidenceSchema -Evidence $c | Should -Not -BeNullOrEmpty
        }
    }
    It 'B1b: the source version is strictly numeric in the schema: real tag shapes pass, words do not' {
        $lane = New-TestLane $script:sb
        $ev = (Complete-HarnessLane -Lane $lane).Evidence
        foreach ($v in '1.2.0', '0.4.0-beta.20.2', '1.0.0-rc.1', '0.9.0-beta.24', '1.0.0-alpha.1.2.3') {
            $c = $ev | ConvertTo-Json -Depth 8 | ConvertFrom-Json -AsHashtable; $c['sourceVersion'] = $v
            Test-HarnessLaneEvidenceSchema -Evidence $c | Should -BeNullOrEmpty -Because $v
        }
        foreach ($v in 'customer-alpha-private', 'customer-alpha-1.2.3', '1.2.3-customer', '1.2.3-beta', 'v1.2.3', '1.2', '1.2.3-beta.x', '1.2.3-beta.1.2.3.4') {
            $c = $ev | ConvertTo-Json -Depth 8 | ConvertFrom-Json -AsHashtable; $c['sourceVersion'] = $v
            Test-HarnessLaneEvidenceSchema -Evidence $c | Should -Not -BeNullOrEmpty -Because $v
        }
    }
    It 'B1b: an attestation source version that is not strictly numeric (<v>) is warned about at the boundary and never reaches the persisted file' -ForEach @(@{ v = 'customer-alpha-private' }, @{ v = 'customer-alpha-1.2.3' }) {
        $f = New-FakeInstallerAndAttestation $script:sb -Version $v
        $lane = New-TestLane $script:sb -Installer $f.Installer -Attestation $f.Attestation
        ($lane.Warnings -join '|') | Should -Match 'not a strict numeric release version'
        ($lane.Warnings -join '|') | Should -Not -Match 'customer|alpha'
        $res = Complete-HarnessLane -Lane $lane
        $res.Evidence.sourceVersion | Should -BeNullOrEmpty
        $file = Join-Path $script:sb.Dir 'ver.json'
        [void](Write-HarnessLaneEvidence -Lane $lane -Evidence $res.Evidence -Path $file)
        (Get-Content -LiteralPath $file -Raw) | Should -Not -Match 'customer|alpha|private'
    }
    It '#57-2: a non-numeric source version is a SOURCE_VERSION_UNRECOGNISED warning, not a preflight failure, and the evidence stays schema-valid' {
        $f = New-FakeInstallerAndAttestation $script:sb -Version 'customer-alpha-private'
        $lane = New-TestLane $script:sb -Installer $f.Installer -Attestation $f.Attestation
        @($lane.WarningCodes) | Should -Contain 'SOURCE_VERSION_UNRECOGNISED'
        @($lane.WarningCodes) | Should -Not -Contain 'INSTALLER_PREFLIGHT_FAILED'
        $res = Complete-HarnessLane -Lane $lane
        @($res.Evidence.warningCodes | ForEach-Object { $_.code }) | Should -Contain 'SOURCE_VERSION_UNRECOGNISED'
        @($res.Evidence.warningCodes | ForEach-Object { $_.code }) | Should -Not -Contain 'INSTALLER_PREFLIGHT_FAILED'
        @($res.Evidence.reasonCodes | ForEach-Object { $_.code }) | Should -Not -Contain 'INSTALLER_PREFLIGHT_FAILED'
        Test-HarnessLaneEvidenceSchema -Evidence $res.Evidence | Should -BeNullOrEmpty
        $res.Evidence.schema | Should -Be 'harness-lane-evidence/3'
    }
    It '#57-3: -Sha256SumsPath / -UpgradeFromSha256SumsPath with an already-rewrapped installer is refused, never silently ignored' {
        $new = New-FakeInstallerAndAttestation $script:sb
        $old = New-FakeInstallerAndAttestation $script:sb
        { Resolve-HarnessBuild -InstallerPath $new.Installer -AttestationPath $new.Attestation -Sha256SumsPath 'C:\dl\SHA256SUMS' } | Should -Throw '*-Sha256SumsPath applies only to -RealInstaller*'
        { Start-HarnessLane -Name 't' -Kind acceptance -InstallerPath $new.Installer -AttestationPath $new.Attestation -Sha256SumsPath 'C:\dl\SHA256SUMS' -HarnessRoot $script:sb.Harness -DebugPort (Get-FreePort) } | Should -Throw '*installer -Sha256SumsPath applies only to -RealInstaller*'
        { Start-HarnessLane -Name 't' -Kind acceptance -InstallerPath $new.Installer -AttestationPath $new.Attestation -UpgradeFromInstallerPath $old.Installer -UpgradeFromAttestationPath $old.Attestation `
                -UpgradeFromSha256SumsPath 'C:\dl\OLD-SHA256SUMS' -HarnessRoot $script:sb.Harness -DebugPort (Get-FreePort) } | Should -Throw '*upgrade-from installer -Sha256SumsPath applies only to -RealInstaller*'
        # the lock was released by the refusals: a plain lane still starts
        $l = New-TestLane $script:sb
        [void](Complete-HarnessLane -Lane $l)
    }
    It 'B1b: a strictly numeric attestation version is recorded' {
        $f = New-FakeInstallerAndAttestation $script:sb -Version '0.4.0-beta.20.2'
        $lane = New-TestLane $script:sb -Installer $f.Installer -Attestation $f.Attestation
        $res = Complete-HarnessLane -Lane $lane
        $res.Evidence.sourceVersion | Should -Be '0.4.0-beta.20.2'
        @($lane.Warnings).Count | Should -Be 0
    }
    It 'B2: acceptance.json is assembled from closed parts, validated as the FINAL on-disk file, and a user name never rewrites a key or enum (<u>)' -ForEach @(@{ u = 'lane' }, @{ u = 'pass' }, @{ u = 'ok' }, @{ u = 'Kind' }, @{ u = 'Window' }, @{ u = 'name' }, @{ u = 'acceptance' }) {
        $lane = New-TestLane $script:sb
        $res = Complete-HarnessLane -Lane $lane
        $checks = @([pscustomobject]@{ name = 'Window title'; ok = $true; detail = 'raw detail must never persist' }, [pscustomobject]@{ name = 'Kind of lane pass ok'; ok = $false; detail = 'x' })
        $f = Join-Path $script:sb.Dir 'acceptance.json'
        $user = $u
        $laneBlock = Get-HarnessAcceptanceLaneEvidence -Lane $lane -Result $res -Checks $checks   # one check is deliberately failed => lane block says fail
        [void](Write-HarnessAcceptanceReport -Path $f -Checks $checks -LaneEvidence $laneBlock -ScrubName { param($n) $n -replace [regex]::Escape($user), '<user>' })
        Test-HarnessAcceptanceReportFile -Path $f | Should -BeNullOrEmpty
        $raw = Get-Content -LiteralPath $f -Raw
        $raw | Should -Not -Match 'raw detail'
        $j = $raw | ConvertFrom-Json -AsHashtable
        @($j.Keys | Sort-Object) | Should -Be @('checks', 'evidence', 'lane', 'passed', 'schema_version', 'total')
        $j.schema_version | Should -BeExactly 'acceptance/3'
        $j.lane.laneKind | Should -BeExactly 'acceptance'
        $j.lane.status | Should -BeExactly 'fail'
        $j.lane.lane | Should -BeExactly 'rewrapped acceptance-identity installer'
        $j.total | Should -Be 2
        $j.passed | Should -Be 1
        foreach ($c in $j.checks) { @($c.Keys | Sort-Object) | Should -Be @('name', 'ok') }
        Test-HarnessLaneEvidenceSchema -Evidence $j.lane | Should -BeNullOrEmpty
    }
    It 'acceptance lane block: <Case> persists status fail with at least one fixed reason code, still passes the report validator' -ForEach @(
        @{ Case = 'an aborted lane step (recorded as a failed check)'; Name = 'Harness lane step aborted'; Ok = $false }
        @{ Case = 'a failed check'; Name = 'Some acceptance check'; Ok = $false }
    ) {
        $lane = New-TestLane $script:sb
        $res = Complete-HarnessLane -Lane $lane
        $res.Evidence.status | Should -Be 'pass'   # the lane itself had nothing wrong; only the run verdict differs
        $checks = @([pscustomobject]@{ name = 'A passing check'; ok = $true }, [pscustomobject]@{ name = $Name; ok = $Ok })
        $block = Get-HarnessAcceptanceLaneEvidence -Lane $lane -Result $res -Checks $checks
        $f = Join-Path $script:sb.Dir 'acc-fail.json'
        [void](Write-HarnessAcceptanceReport -Path $f -Checks $checks -LaneEvidence $block)
        Test-HarnessAcceptanceReportFile -Path $f | Should -BeNullOrEmpty
        $j = Get-Content -LiteralPath $f -Raw | ConvertFrom-Json -AsHashtable
        $j.lane.status | Should -Be 'fail'
        @($j.lane.reasonCodes).Count | Should -BeGreaterThan 0
        @($j.lane.reasonCodes | ForEach-Object { $_.code }) | Should -Contain 'LANE_STEP_FAILED'
    }
    It 'acceptance lane block: a non-zero lane result fails it, and an all-pass run still persists pass' {
        $lane = New-TestLane $script:sb
        $res = Complete-HarnessLane -Lane $lane
        $ok = @([pscustomobject]@{ name = 'A passing check'; ok = $true })
        (Get-HarnessAcceptanceLaneEvidence -Lane $lane -Result $res -Checks $ok).status | Should -Be 'pass'
        @((Get-HarnessAcceptanceLaneEvidence -Lane $lane -Result $res -Checks $ok).reasonCodes).Count | Should -Be 0
        $bad = [pscustomobject]@{ ExitCode = 1; Evidence = $res.Evidence }
        $b = Get-HarnessAcceptanceLaneEvidence -Lane $lane -Result $bad -Checks $ok
        $b.status | Should -Be 'fail'
        @($b.reasonCodes).Count | Should -BeGreaterThan 0
        Get-HarnessAcceptanceLaneEvidence -Lane $lane -Result $null -Checks $ok | Should -BeNullOrEmpty
        $f = Join-Path $script:sb.Dir 'acc-pass.json'
        [void](Write-HarnessAcceptanceReport -Path $f -Checks $ok -LaneEvidence (Get-HarnessAcceptanceLaneEvidence -Lane $lane -Result $res -Checks $ok))
        ((Get-Content -LiteralPath $f -Raw | ConvertFrom-Json -AsHashtable).lane.status) | Should -Be 'pass'
    }
    It 'B2 verdict invariant: a failed check with a pass lane block is rejected (file deleted); with a fail lane block + reason it is accepted; all-pass + pass is accepted' {
        $lane = New-TestLane $script:sb
        $res = Complete-HarnessLane -Lane $lane
        $good = @([pscustomobject]@{ name = 'A passing check'; ok = $true })
        $bad = @([pscustomobject]@{ name = 'A passing check'; ok = $true }, [pscustomobject]@{ name = 'A failing check'; ok = $false })
        $f = Join-Path $script:sb.Dir 'verdict.json'
        $passLane = Get-HarnessAcceptanceLaneEvidence -Lane $lane -Result $res -Checks $good
        $passLane.status | Should -Be 'pass'
        { Write-HarnessAcceptanceReport -Path $f -Checks $bad -LaneEvidence $passLane } | Should -Throw '*REPORT_WRITE_FAILED*'
        Test-Path -LiteralPath $f | Should -BeFalse
        $failLane = Get-HarnessAcceptanceLaneEvidence -Lane $lane -Result $res -Checks $bad
        [void](Write-HarnessAcceptanceReport -Path $f -Checks $bad -LaneEvidence $failLane)
        Test-HarnessAcceptanceReportFile -Path $f | Should -BeNullOrEmpty
        [void](Write-HarnessAcceptanceReport -Path $f -Checks $good -LaneEvidence $passLane)
        Test-HarnessAcceptanceReportFile -Path $f | Should -BeNullOrEmpty
        # a fail lane block with NO reason code is also rejected when a check failed
        $noReason = [ordered]@{}; foreach ($k in $failLane.Keys) { $noReason[$k] = $failLane[$k] }; $noReason['reasonCodes'] = @()
        { Write-HarnessAcceptanceReport -Path $f -Checks $bad -LaneEvidence $noReason } | Should -Throw '*REPORT_WRITE_FAILED*'
        Test-Path -LiteralPath $f | Should -BeFalse
        # a lane that says fail must carry a reason code even when every check passed ...
        $noReasonAllPass = [ordered]@{}; foreach ($k in $failLane.Keys) { $noReasonAllPass[$k] = $failLane[$k] }; $noReasonAllPass['reasonCodes'] = @()
        $noReasonAllPass['status'] | Should -Be 'fail'
        { Write-HarnessAcceptanceReport -Path $f -Checks $good -LaneEvidence $noReasonAllPass } | Should -Throw '*REPORT_WRITE_FAILED*'
        Test-Path -LiteralPath $f | Should -BeFalse
        # ... and a lane-level failure with a fixed reason code and all checks passing is accepted
        $laneOnly = Get-HarnessLaneEvidence -Lane $lane -Failed
        $laneOnly.status | Should -Be 'fail'
        @($laneOnly.reasonCodes).Count | Should -BeGreaterThan 0
        [void](Write-HarnessAcceptanceReport -Path $f -Checks $good -LaneEvidence $laneOnly)
        Test-HarnessAcceptanceReportFile -Path $f | Should -BeNullOrEmpty
    }
    It 'B2: a deliberately corrupted acceptance.json fails closed (file deleted, REPORT_WRITE_FAILED), and every tamper of the final file is detected' {
        $lane = New-TestLane $script:sb
        $res = Complete-HarnessLane -Lane $lane
        $checks = @([pscustomobject]@{ name = 'Window title'; ok = $true })
        $f = Join-Path $script:sb.Dir 'acceptance2.json'
        { Write-HarnessAcceptanceReport -Path $f -Checks $checks -LaneEvidence $res.Evidence -ScrubName { param($n) "x`ny" } } | Should -Throw '*REPORT_WRITE_FAILED*'
        Test-Path -LiteralPath $f | Should -BeFalse
        { Write-HarnessAcceptanceReport -Path $f -Checks $checks -LaneEvidence ([ordered]@{ detail = 'free text' }) } | Should -Throw '*REPORT_WRITE_FAILED*'
        Test-Path -LiteralPath $f | Should -BeFalse
        [void](Write-HarnessAcceptanceReport -Path $f -Checks $checks -LaneEvidence $res.Evidence)
        $good = Get-Content -LiteralPath $f -Raw
        foreach ($t in @(
                @('"acceptance/3"', '"acceptance/9"'), @('"status": "pass"', '"status": "p<user>ss"'), @('"passed": 1', '"passed": 5'),
                @('"ok": true', '"ok": "yes"'), @('"total": 1', '"total": 2'), @('"evidence": "<harness-root>', '"evidence": "x<harness-root>'),
                @('"checks"', ('"extra": 1,' + "`n" + '  "checks"')), @('"laneKind"', '"lane<user>Kind"'))) {
            if (-not $good.Contains($t[0])) { throw "tamper pattern missing: $($t[0])" }
            Set-Content -LiteralPath $f -Value $good.Replace($t[0], $t[1]) -Encoding utf8
            Test-HarnessAcceptanceReportFile -Path $f | Should -Not -BeNullOrEmpty -Because $t[0]
        }
        Set-Content -LiteralPath $f -Value '{ not json' -Encoding utf8
        Test-HarnessAcceptanceReportFile -Path $f | Should -Not -BeNullOrEmpty
    }
    It 'note1: the secondary user-name check looks only at pattern-typed VALUES, so common short user names do not fail every lane (<u>)' -ForEach @(@{ u = 'Ali' }, @{ u = 'Liz' }, @{ u = 'Pat' }, @{ u = 'Ina' }, @{ u = 'Fin' }, @{ u = 'Lane' }, @{ u = 'Kind' }) {
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $res = Complete-HarnessLane -Lane $lane
        $global:SshT.User = $u
        Mock -ModuleName HarnessLauncher Get-CurrentUserName { $global:SshT.User }
        $f = Join-Path $script:sb.Dir 'short-user.json'
        { Write-HarnessLaneEvidence -Lane $lane -Evidence $res.Evidence -Path $f } | Should -Not -Throw
        Test-Path -LiteralPath $f | Should -BeTrue
    }
    It 'note1: a user name that appears inside a pattern-typed VALUE still fails the write closed' {
        $f0 = New-FakeInstallerAndAttestation $script:sb -Version '1.0.0-beta.1'
        $lane = New-TestLane $script:sb -Installer $f0.Installer -Attestation $f0.Attestation
        $res = Complete-HarnessLane -Lane $lane
        $global:SshT.User = 'beta'
        Mock -ModuleName HarnessLauncher Get-CurrentUserName { $global:SshT.User }
        $f = Join-Path $script:sb.Dir 'beta-user.json'
        { Write-HarnessLaneEvidence -Lane $lane -Evidence $res.Evidence -Path $f } | Should -Throw '*REPORT_WRITE_FAILED*'
        Test-Path -LiteralPath $f | Should -BeFalse
    }
    It 'note2: a failed run persists status fail with at least one reason code (-Failed), a clean run persists pass' {
        $lane = New-TestLane $script:sb
        $res = Complete-HarnessLane -Lane $lane
        $ok = Join-Path $script:sb.Dir 'ok-run.json'; $bad = Join-Path $script:sb.Dir 'bad-run.json'
        Publish-HarnessLaneReport -Lane $lane -Result $res -EvidencePath $ok 6>$null | Should -Be 0
        Publish-HarnessLaneReport -Lane $lane -Result $res -EvidencePath $bad -Failed 6>$null | Should -Be 1
        ((Get-Content -LiteralPath $ok -Raw) | ConvertFrom-Json).status | Should -Be 'pass'
        $j = (Get-Content -LiteralPath $bad -Raw) | ConvertFrom-Json -AsHashtable
        $j.status | Should -Be 'fail'
        @($j.reasonCodes | ForEach-Object { $_.code }) | Should -Contain 'LANE_STEP_FAILED'
        Test-HarnessLaneEvidenceSchema -Evidence $j | Should -BeNullOrEmpty
    }
    It 'note3: tripwire.violations counts only tripwire findings; a shortcut finding is its own count and code' {
        $lane = New-TestLane $script:sb
        [IO.File]::WriteAllBytes((Join-Path $script:sb.RealDesktop "$($script:Acc.ProductName).lnk"), [byte[]](1))
        $res = Complete-HarnessLane -Lane $lane
        $res.Evidence.tripwire.violations | Should -Be 0
        $res.Evidence.shortcutFindings | Should -Be 1
        @($res.Evidence.reasonCodes | ForEach-Object { $_.code }) | Should -Contain 'SHORTCUT_ASSERTION_FAILED'
        $res.Evidence.status | Should -Be 'fail'
    }
    It 'note3: a guard refusal after the phase was added is counted ONCE (no extra INSTALL_FAILED from Complete)' {
        $lane = New-TestLane $script:sb
        [IO.File]::WriteAllText($lane.Builds['Primary'].Staged.Path, 'tampered after authorization')
        { Install-HarnessBuild -Lane $lane -Which Primary } | Should -Throw
        $res = Complete-HarnessLane -Lane $lane
        $codes = @($res.Evidence.reasonCodes | ForEach-Object { $_.code })
        $codes | Should -Contain 'INSTALLER_PREFLIGHT_FAILED'
        $codes | Should -Not -Contain 'INSTALL_FAILED'
        (@($res.Evidence.reasonCodes | Where-Object { $_.code -eq 'INSTALLER_PREFLIGHT_FAILED' }) | ForEach-Object { $_.count } | Measure-Object -Sum).Sum | Should -Be 1
    }
    It 'note3: a Set-JournalOwnedAfter failure is JOURNAL_RECORD_FAILED once, not INSTALLER_PREFLIGHT_FAILED' {
        Mock -ModuleName HarnessLauncher Set-JournalOwnedAfter { throw 'journal write failed' }
        $lane = New-TestLane $script:sb
        { Install-HarnessBuild -Lane $lane -Which Primary } | Should -Throw '*journal write failed*'
        $res = Complete-HarnessLane -Lane $lane
        $codes = @($res.Evidence.reasonCodes | ForEach-Object { $_.code })
        $codes | Should -Contain 'JOURNAL_RECORD_FAILED'
        $codes | Should -Not -Contain 'INSTALLER_PREFLIGHT_FAILED'
        (@($res.Evidence.reasonCodes | Where-Object { $_.code -eq 'JOURNAL_RECORD_FAILED' }) | ForEach-Object { $_.count } | Measure-Object -Sum).Sum | Should -Be 1
    }
    It 'S2: a non-zero installer exit is returned, fails the lane, and the orphaned install keeps its journal pending (recovery never called)' {
        Mock -ModuleName HarnessLauncher Invoke-HarnessRecovery { throw 'recovery must not run over a populated install dir' }
        $global:SshT.InstallerExit = 5
        $lane = New-TestLane $script:sb
        $r = Install-HarnessBuild -Lane $lane -Which Primary
        $r.ExitCode | Should -Be 5
        $res = Complete-HarnessLane -Lane $lane
        $res.ExitCode | Should -Be 1
        ($res.Errors -join '|') | Should -Match 'installer phase .* exited with code 5'
        ($res.Errors -join '|') | Should -Match 'orphaned acceptance install: \d+ files under install\\'
        $res.Evidence.orphanedInstall.files | Should -BeGreaterThan 0
        $res.Evidence.orphanedInstall.dir | Should -Be "install\$($lane.RunId)"
        @(Get-ChildItem -LiteralPath $lane.InstallDir -Recurse -File).Count | Should -BeGreaterThan 0     # untouched
        Test-Path (Join-Path $script:sb.Harness "journal\$($lane.RunId).json") | Should -BeTrue
        Test-Path (Join-Path $script:sb.Harness "journal\$($lane.RunId).recovered.json") | Should -BeFalse
        $lane.Phases[0].Finalized | Should -BeFalse
        Should -Invoke -ModuleName HarnessLauncher Invoke-HarnessRecovery -Times 0 -Exactly
        $res.Evidence.lane | Should -Be 'rewrapped acceptance-identity installer'
    }
    It 'S2: a partial install (exe copied, no uninstaller, no registration) is never finalised and fails the lane' {
        Mock -ModuleName HarnessLauncher Invoke-HarnessRecovery { throw 'recovery must not run over a populated install dir' }
        $global:SshT.Partial = $true
        $lane = New-TestLane $script:sb
        $r = Install-HarnessBuild -Lane $lane -Which Primary
        $r.ExitCode | Should -Be 0
        $res = Complete-HarnessLane -Lane $lane
        $res.ExitCode | Should -Be 1
        $global:SshT.ContainsKey('UninstallArgs') | Should -BeFalse
        ($res.Errors -join '|') | Should -Match 'orphaned acceptance install: 1 files under install\\'
        Test-Path (Join-Path $lane.InstallDir 'snapmaker-studio-acceptance-desktop.exe') | Should -BeTrue
        Test-Path (Join-Path $script:sb.Harness "journal\$($lane.RunId).json") | Should -BeTrue
        Test-Path (Join-Path $script:sb.Harness "journal\$($lane.RunId).recovered.json") | Should -BeFalse
        Should -Invoke -ModuleName HarnessLauncher Invoke-HarnessRecovery -Times 0 -Exactly
    }
    It 'S2: an installer timeout fails the lane, leaves the journal pending and the install dir untouched' {
        Mock -ModuleName HarnessLauncher Invoke-HarnessRecovery { throw 'recovery must not run over a populated install dir' }
        $global:SshT.Timeout = $true
        $lane = New-TestLane $script:sb
        { Install-HarnessBuild -Lane $lane -Which Primary -TimeoutSeconds 1 } | Should -Throw '*timed out*'
        $res = Complete-HarnessLane -Lane $lane
        $res.ExitCode | Should -Be 1
        ($res.Errors -join '|') | Should -Match 'timed out'
        ($res.Errors -join '|') | Should -Match 'orphaned acceptance install'
        @(Get-ChildItem -LiteralPath $lane.InstallDir -Recurse -File).Count | Should -BeGreaterThan 0
        Test-Path (Join-Path $script:sb.Harness "journal\$($lane.RunId).recovered.json") | Should -BeFalse
        Should -Invoke -ModuleName HarnessLauncher Invoke-HarnessRecovery -Times 0 -Exactly
    }
    It 'S2: a clean install + uninstall leaves the install dir empty and finalises (guards against the gate being over-broad)' {
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $res = Complete-HarnessLane -Lane $lane
        @(Get-ChildItem -LiteralPath $lane.InstallDir -Recurse -File -ErrorAction SilentlyContinue).Count | Should -Be 0
        $res.ExitCode | Should -Be 0
        $res.Evidence.orphanedInstall | Should -BeNullOrEmpty
    }
    It 'S3: an uninstall hand-off process still running at the timeout is a failure (waited for, never killed), journal pending' {
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $global:SshT.HandoffCmd = "Un_A.exe _?=$($lane.InstallDir)"
        $res = Complete-HarnessLane -Lane $lane
        $res.Uninstall.HandoffComplete | Should -BeFalse
        $res.Uninstall.HandoffProcesses | Should -Be 1
        $res.Uninstall.Reason | Should -Match 'hand-off did not complete'
        $res.ExitCode | Should -Be 1
        ($res.Errors -join '|') | Should -Match 'uninstall hand-off did not complete'
        $lane.Phases[0].Finalized | Should -BeFalse
        Test-Path (Join-Path $script:sb.Harness "journal\$($lane.RunId).recovered.json") | Should -BeFalse
        Should -Invoke -ModuleName HarnessLauncher Stop-ProcessById -Times 0 -Exactly -ParameterFilter { $ProcessId -eq 999999 }
    }
    It 'S3: an install dir that is still non-empty at the timeout is a failure' {
        $global:SshT.KeepFiles = $true
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $res = Complete-HarnessLane -Lane $lane
        $res.Uninstall.HandoffComplete | Should -BeFalse
        $res.Uninstall.DirFiles | Should -BeGreaterThan 0
        $res.ExitCode | Should -Be 1
        ($res.Errors -join '|') | Should -Match 'hand-off did not complete'
        $lane.Phases[0].Finalized | Should -BeFalse
    }
    It 'S2: a non-zero uninstaller exit code fails the lane even when the install dir ended up empty' {
        $global:SshT.UninstallExit = 2
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $res = Complete-HarnessLane -Lane $lane
        $res.ExitCode | Should -Be 1
        ($res.Errors -join '|') | Should -Match 'uninstaller exited with code 2'
    }
    It 'B1: Get-InstallDirFileCount is strict: absent = 0, files = count, any enumeration error or reparse point = $null (ambiguous), never 0' {
        $d = Join-Path $script:sb.Dir 'cnt'
        InModuleScope HarnessLauncher -Parameters @{ D = $d } { Get-InstallDirFileCount -Dir $D } | Should -Be 0
        New-Item -ItemType Directory -Path (Join-Path $d 'sub') -Force | Out-Null
        [IO.File]::WriteAllText((Join-Path $d 'sub\a.txt'), 'x'); [IO.File]::WriteAllText((Join-Path $d 'b.txt'), 'x')
        InModuleScope HarnessLauncher -Parameters @{ D = $d } { Get-InstallDirFileCount -Dir $D } | Should -Be 2
        $out = Join-Path $script:sb.Dir 'cnt-target'; New-Item -ItemType Directory -Path $out | Out-Null
        New-Item -ItemType Junction -Path (Join-Path $d 'junc') -Target $out | Out-Null
        $r = InModuleScope HarnessLauncher -Parameters @{ D = $d } { Get-InstallDirFileCount -Dir $D }
        $null -eq $r | Should -BeTrue
        [IO.Directory]::Delete((Join-Path $d 'junc'))
        Mock -ModuleName HarnessLauncher Get-InstallDirFileList { throw 'access denied' }
        $r2 = InModuleScope HarnessLauncher -Parameters @{ D = $d } { Get-InstallDirFileCount -Dir $D }
        $null -eq $r2 | Should -BeTrue
    }
    It 'B1: an unenumerable install dir (error on a subtree) after a clean-looking uninstall: no recovery, journal pending, exit 1' {
        Mock -ModuleName HarnessLauncher Invoke-HarnessRecovery { throw 'recovery must not run' }
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        Mock -ModuleName HarnessLauncher Get-InstallDirFileList { throw 'access denied on a subtree' }
        $res = Complete-HarnessLane -Lane $lane
        $res.ExitCode | Should -Be 1
        Should -Invoke -ModuleName HarnessLauncher Invoke-HarnessRecovery -Times 0 -Exactly
        Test-Path (Join-Path $script:sb.Harness "journal\$($lane.RunId).json") | Should -BeTrue
        Test-Path (Join-Path $script:sb.Harness "journal\$($lane.RunId).recovered.json") | Should -BeFalse
        $lane.Phases[0].Finalized | Should -BeFalse
        $res.Uninstall.HandoffComplete | Should -BeFalse
    }
    It 'B1: the recovery gate itself treats an ambiguous directory state as not clean (uninstall itself reported success)' {
        Mock -ModuleName HarnessLauncher Invoke-HarnessRecovery { throw 'recovery must not run' }
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $global:SshT.CountCalls = 0
        Mock -ModuleName HarnessLauncher Get-InstallDirFileCount { $global:SshT.CountCalls++; if ($global:SshT.CountCalls -le 2) { 0 } else { $null } }
        $res = Complete-HarnessLane -Lane $lane
        $res.Uninstall.HandoffComplete | Should -BeTrue
        $res.ExitCode | Should -Be 1
        ($res.Errors -join '|') | Should -Match 'install directory state could not be determined'
        Should -Invoke -ModuleName HarnessLauncher Invoke-HarnessRecovery -Times 0 -Exactly
        $lane.Phases[0].Finalized | Should -BeFalse
    }
    It 'B2a: the uninstaller parent timing out leaves the outcome UNKNOWN: recovery never called, journal pending, exit 1' {
        Mock -ModuleName HarnessLauncher Invoke-HarnessRecovery { throw 'recovery must not run' }
        $global:SshT.UninstallTimeout = $true
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $res = Complete-HarnessLane -Lane $lane
        $res.ExitCode | Should -Be 1
        $res.Evidence.uninstallOutcome | Should -Be 'Unknown'
        ($res.Errors -join '|') | Should -Match 'uninstall outcome unknown \(error: .*timed out.*hand-off child may still be running'
        ($res.Errors -join '|') | Should -Match '-RunId <id> -ShortcutDir <harness-root>\\run\\'
        Should -Invoke -ModuleName HarnessLauncher Invoke-HarnessRecovery -Times 0 -Exactly
        Test-Path (Join-Path $script:sb.Harness "journal\$($lane.RunId).recovered.json") | Should -BeFalse
    }
    It 'B2b: a process-query (CIM) failure with ZERO files left is UNKNOWN, never "no hand-off process": no recovery, journal pending, exit 1' {
        Mock -ModuleName HarnessLauncher Invoke-HarnessRecovery { throw 'recovery must not run' }
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $global:SshT.CimThrow = 'CIM query failed'
        $res = Complete-HarnessLane -Lane $lane
        $res.Uninstall.DirFiles | Should -Be 0
        $res.Uninstall.HandoffComplete | Should -BeFalse
        $res.Uninstall.Reason | Should -Match 'unknown'
        $res.ExitCode | Should -Be 1
        Should -Invoke -ModuleName HarnessLauncher Invoke-HarnessRecovery -Times 0 -Exactly
        $lane.Phases[0].Finalized | Should -BeFalse
    }
    It 'B2b: an exception escaping the hand-off wait after the uninstaller launched is UNKNOWN' {
        Mock -ModuleName HarnessLauncher Invoke-HarnessRecovery { throw 'recovery must not run' }
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        Mock -ModuleName HarnessLauncher Get-InstallDirFileCount { throw 'wait failed' }
        $res = Complete-HarnessLane -Lane $lane
        $res.Evidence.uninstallOutcome | Should -Be 'Unknown'
        $res.ExitCode | Should -Be 1
        Should -Invoke -ModuleName HarnessLauncher Invoke-HarnessRecovery -Times 0 -Exactly
    }
    It 'B2c: a hand-off process that exits during the wait (files already gone) is success' {
        $global:SshT.CimCalls = 0
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $global:SshT.HandoffCmd = "Un_A.exe _?=$($lane.InstallDir)"
        $global:SshT.HandoffGoneAfter = 1
        $res = Complete-HarnessLane -Lane $lane
        $res.Uninstall.HandoffComplete | Should -BeTrue
        $res.Uninstall.HandoffProcesses | Should -Be 0
        $res.ExitCode | Should -Be 0
        $lane.Phases[0].Finalized | Should -BeTrue
    }
    It 'messages: orphan / hand-off / recovery holds carry the exact -RunId and -ShortcutDir hint' {
        $global:SshT.Partial = $true
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $res = Complete-HarnessLane -Lane $lane
        $orphan = @($res.Errors | Where-Object { $_ -match 'orphaned acceptance install' })[0]
        $orphan | Should -Match '-RunId <id> -ShortcutDir <harness-root>\\run\\'
        $orphan | Should -Match $lane.RunId
    }
    It 'S3: success path: install dir empty and no hand-off process => HandoffComplete, exit 0' {
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $res = Complete-HarnessLane -Lane $lane
        $res.Uninstall.HandoffComplete | Should -BeTrue
        $res.Uninstall.DirFiles | Should -Be 0
        $res.Uninstall.HandoffProcesses | Should -Be 0
        $res.ExitCode | Should -Be 0
    }
    It 'S5: a production engine filename that changes during the lane never appears in any evidence output' {
        New-Item -ItemType Directory -Path $script:sb.Engine -Force | Out-Null
        [IO.File]::WriteAllText((Join-Path $script:sb.Engine 'PRIVATE-model-name-zq91.3mf'), 'one')
        $ldb = Join-Path $script:sb.Local 'EBWebView\Default\Local Storage\leveldb'
        New-Item -ItemType Directory -Path $ldb -Force | Out-Null
        [IO.File]::WriteAllText((Join-Path $ldb 'PRIVATE-ldb-name-zq91.log'), 'aaaa')
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        [IO.File]::WriteAllText((Join-Path $script:sb.Engine 'PRIVATE-model-name-zq91.3mf'), 'two-changed')
        [IO.File]::WriteAllText((Join-Path $script:sb.Engine 'PRIVATE-added-zq91.3mf'), 'new')
        [IO.File]::WriteAllText((Join-Path $ldb 'PRIVATE-ldb-name-zq91.log'), 'bbbb')
        $res = Complete-HarnessLane -Lane $lane
        $res.ExitCode | Should -Be 1
        ($res.Findings -join '|') | Should -Match 'production engine data : 1 entry ADDED'
        ($res.Findings -join '|') | Should -Match 'production engine data : 1 entry CHANGED'
        ($res.Findings -join '|') | Should -Match 'leveldb file\(s\) hash-CHANGED'
        $all = (($res | ConvertTo-Json -Depth 10) + '|' + ($lane.Findings -join '|') + '|' + ($lane.Errors -join '|') + '|' + ($lane.Warnings -join '|') + '|' + ($res.Evidence | ConvertTo-Json -Depth 10))
        $all | Should -Not -Match 'zq91'
        $all | Should -Not -Match 'PRIVATE'
    }
    It 'M2: a pending journal (left by a failed run) blocks the next lane with a pointer to Repair-Harness.ps1; clearing it frees the lane' {
        $global:SshT.Partial = $true
        $lane = New-TestLane $script:sb
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        [void](Complete-HarnessLane -Lane $lane)
        { New-TestLane $script:sb } | Should -Throw '*unfinished harness journal*Repair-Harness.ps1*'
        $msg = try { New-TestLane $script:sb; '' } catch { $_.Exception.Message }
        $msg | Should -Match '-RunId <id> -ShortcutDir <harness-root>\\run\\<id>\\shortcuts'
        $msg | Should -Match ([regex]::Escape($lane.RunId))
        Rename-Item -LiteralPath (Join-Path $script:sb.Harness "journal\$($lane.RunId).json") -NewName "$($lane.RunId).recovered.json"
        $l2 = New-TestLane $script:sb
        [void](Complete-HarnessLane -Lane $l2)
    }
    It 'M2: an existing acceptance uninstall key blocks the next lane' {
        $k = "$($script:sb.RegRoot)\Microsoft\Windows\CurrentVersion\Uninstall\$($script:Acc.ProductName)"
        New-Item -Path $k -Force | Out-Null
        { New-TestLane $script:sb } | Should -Throw '*uninstall key already exists*'
        Remove-Item -LiteralPath $k -Recurse -Force
        $l = New-TestLane $script:sb
        [void](Complete-HarnessLane -Lane $l)
    }
    It 'M4: upgrade lane: OLD then NEW, phase run ids, one /S uninstall, both journals finalised, evidence labelled OLD -> NEW' {
        $old = New-FakeInstallerAndAttestation $script:sb
        $new = New-FakeInstallerAndAttestation $script:sb
        $lane = Start-HarnessLane -Name 't' -Kind acceptance -InstallerPath $new.Installer -AttestationPath $new.Attestation `
            -UpgradeFromInstallerPath $old.Installer -UpgradeFromAttestationPath $old.Attestation -HarnessRoot $script:sb.Harness -DebugPort (Get-FreePort)
        $lane.Upgrade | Should -BeTrue
        [void](Install-HarnessBuild -Lane $lane -Which UpgradeFrom)
        [void](Install-HarnessBuild -Lane $lane -Which Primary)
        $lane.Phases[0].RunId | Should -Be $lane.RunId
        $lane.Phases[1].RunId | Should -Be "$($lane.RunId)-u2"
        $res = Complete-HarnessLane -Lane $lane
        @($global:SshT.Launches | Where-Object { $_ -like '*|/S' }).Count | Should -Be 1
        @($global:SshT.Launches | Where-Object { $_ -like '*|/S /NCRC*' }).Count | Should -Be 2
        $lane.Phases[0].Finalized | Should -BeTrue
        $lane.Phases[1].Finalized | Should -BeTrue
        Test-Path (Join-Path $script:sb.Harness "journal\$($lane.RunId).recovered.json") | Should -BeTrue
        Test-Path (Join-Path $script:sb.Harness "journal\$($lane.RunId)-u2.recovered.json") | Should -BeTrue
        $res.ExitCode | Should -Be 0
        $res.Evidence.lane | Should -Match 'OLD -> NEW'
        $res.Evidence.lane | Should -Match 'not a production upgrade'
    }
}

Describe 'Production install-surface tripwire (detection only; scratch roots and temp dirs ONLY)' {
    BeforeAll {
        function script:Assert-ScratchReg([string]$p) { if ($p -notlike 'HKCU:\Software\SnapmakerStudioHarnessTest\*') { throw "test refuses a non-scratch registry path: $p" } }
        function script:Get-HkcuSub([string]$p) { Assert-ScratchReg $p; $p -replace '^HKCU:\\', '' }
        function script:Set-RegVal([string]$path, [string]$name, $value) {
            $k = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey((Get-HkcuSub $path)); try { $k.SetValue($name, $value) } finally { $k.Dispose() }
        }
        function script:New-RegKeyOnly([string]$path) { [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey((Get-HkcuSub $path)).Dispose() }
        function script:Remove-RegTree([string]$path) { [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree((Get-HkcuSub $path), $false) }
        function script:Remove-RegVal([string]$path, [string]$name) {
            $k = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey((Get-HkcuSub $path), $true); try { $k.DeleteValue($name) } finally { $k.Dispose() }
        }
        function script:Get-SurfacePaths($s) {
            [pscustomobject]@{
                Uninstall = "$($s.SoftRoot)\$($script:Id.Registry.UninstallKeyParent)\$($script:Prod.ProductName)"
                UninstallWow = "$($s.SoftRoot)\WOW6432Node\$($script:Id.Registry.UninstallKeyParent)\$($script:Prod.ProductName)"
                Remembered = "$($s.SoftRoot)\$($script:Prod.Manufacturer)\$($script:Prod.ProductName)"
                Manufacturer = "$($s.SoftRoot)\$($script:Prod.Manufacturer)"
                RunKey = $s.RunKey; RunName = $script:Prod.ProductName
                StartMenu = Join-Path $s.RealStartMenu "$($script:Prod.ProductName).lnk"
                Desktop = Join-Path $s.RealDesktop "$($script:Prod.ProductName).lnk"
                Install = $s.InstallDirs[0]
            }
        }
        function script:Set-RegValK([string]$path, [string]$name, $value, [Microsoft.Win32.RegistryValueKind]$kind) {
            $k = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey((Get-HkcuSub $path)); try { $k.SetValue($name, $value, $kind) } finally { $k.Dispose() }
        }
        function script:Assert-InSandbox([string]$path) {
            # Equivalent of Assert-ScratchReg for files: the path must resolve strictly inside THIS test's own temp sandbox, with no
            # wildcard, no stream suffix and no reparse point on the existing part of the chain.
            if ($path -match '[\*\?\[\]]') { throw "test helper refuses a wildcard path: $path" }
            if ($path.Length -gt 2 -and $path.Substring(2).Contains(':')) { throw "test helper refuses a stream-suffixed path: $path" }
            $full = [IO.Path]::GetFullPath($path)
            $root = [IO.Path]::GetFullPath($script:sb.Dir).TrimEnd('\') + '\'
            if (-not $full.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { throw "test helper refuses a path outside the test sandbox: $path" }
            $cur = $full
            while ($cur -and $cur.Length -ge $root.Length) {
                if (Test-Path -LiteralPath $cur) { if ((Get-Item -LiteralPath $cur -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "test helper refuses a path through a reparse point: $path" } }
                $cur = Split-Path -Parent $cur
            }
        }
        function script:Set-AdsBytes([string]$path, [string]$name, [byte[]]$bytes) {
            Assert-InSandbox $path
            Set-Content -LiteralPath $path -Stream $name -Value $bytes -AsByteStream
            if (@(Get-Item -LiteralPath $path -Stream * -Force | Where-Object { $_.Stream -eq $name }).Count -ne 1) { throw "alternate data streams could not be created in this environment ($name)" }
        }
        function script:Set-Ads([string]$path, [string]$name, [string]$value) {
            Assert-InSandbox $path
            Set-Content -LiteralPath $path -Stream $name -Value $value
            # an environment that cannot create alternate data streams must FAIL these tests, never skip them silently
            if (@(Get-Item -LiteralPath $path -Stream * -Force | Where-Object { $_.Stream -eq $name }).Count -ne 1) { throw "alternate data streams could not be created in this environment ($name)" }
        }
        function script:Remove-Ads([string]$path, [string]$name) { Assert-InSandbox $path; Remove-Item -LiteralPath $path -Stream $name }
        function script:Write-Bytes([string]$path, [string]$text) { Assert-InSandbox $path; New-Item -ItemType Directory -Force -Path (Split-Path -Parent $path) | Out-Null; [IO.File]::WriteAllBytes($path, [Text.Encoding]::UTF8.GetBytes($text)) }
    }
    BeforeEach { $script:sb = New-Sandbox; Set-Hooks $script:sb; Set-DefaultMocks }
    AfterEach { Remove-Sandbox $script:sb }

    It 'detects a mutation to <Cat> (<Name>) as a tripwire finding with a closed per-category count, completed = true, nothing restored' -ForEach @(
        @{ Name = 'added'; Cat = 'uninstallKey'; Setup = { param($s, $p) }; Mutate = { param($s, $p) Set-RegVal $p.Uninstall 'DisplayName' 'x' } }
        @{ Name = 'value changed'; Cat = 'uninstallKey'; Setup = { param($s, $p) Set-RegVal $p.Uninstall 'DisplayName' 'a' }; Mutate = { param($s, $p) Set-RegVal $p.Uninstall 'DisplayName' 'b' } }
        @{ Name = 'removed'; Cat = 'uninstallKey'; Setup = { param($s, $p) Set-RegVal $p.Uninstall 'DisplayName' 'a' }; Mutate = { param($s, $p) Remove-RegTree $p.Uninstall } }
        @{ Name = 'added in the WOW6432Node view'; Cat = 'uninstallKey'; Setup = { param($s, $p) }; Mutate = { param($s, $p) Set-RegVal $p.UninstallWow 'DisplayName' 'x' } }
        @{ Name = 'added'; Cat = 'rememberedKey'; Also = 'manufacturerKey'; Setup = { param($s, $p) }; Mutate = { param($s, $p) Set-RegVal $p.Remembered '' 'C:\x' } }
        @{ Name = 'value changed'; Cat = 'rememberedKey'; Also = 'manufacturerKey'; Setup = { param($s, $p) Set-RegVal $p.Remembered '' 'C:\a' }; Mutate = { param($s, $p) Set-RegVal $p.Remembered '' 'C:\b' } }
        @{ Name = 'removed'; Cat = 'rememberedKey'; Also = 'manufacturerKey'; Setup = { param($s, $p) Set-RegVal $p.Remembered '' 'C:\a' }; Mutate = { param($s, $p) Remove-RegTree $p.Remembered } }
        @{ Name = 'parent appears'; Cat = 'manufacturerKey'; Setup = { param($s, $p) }; Mutate = { param($s, $p) New-RegKeyOnly $p.Manufacturer } }
        @{ Name = 'parent removed'; Cat = 'manufacturerKey'; Setup = { param($s, $p) New-RegKeyOnly $p.Manufacturer }; Mutate = { param($s, $p) Remove-RegTree $p.Manufacturer } }
        @{ Name = 'added'; Cat = 'runValue'; Setup = { param($s, $p) }; Mutate = { param($s, $p) Set-RegVal $p.RunKey $p.RunName 'C:\x.exe' } }
        @{ Name = 'changed'; Cat = 'runValue'; Setup = { param($s, $p) Set-RegVal $p.RunKey $p.RunName 'C:\a.exe' }; Mutate = { param($s, $p) Set-RegVal $p.RunKey $p.RunName 'C:\b.exe' } }
        @{ Name = 'removed'; Cat = 'runValue'; Setup = { param($s, $p) Set-RegVal $p.RunKey $p.RunName 'C:\a.exe' }; Mutate = { param($s, $p) Remove-RegVal $p.RunKey $p.RunName } }
        @{ Name = 'added'; Cat = 'startMenuShortcut'; Setup = { param($s, $p) }; Mutate = { param($s, $p) Write-Bytes $p.StartMenu 'lnk1' } }
        @{ Name = 'changed'; Cat = 'startMenuShortcut'; Setup = { param($s, $p) Write-Bytes $p.StartMenu 'lnk1' }; Mutate = { param($s, $p) Write-Bytes $p.StartMenu 'lnk2' } }
        @{ Name = 'removed'; Cat = 'startMenuShortcut'; Setup = { param($s, $p) Write-Bytes $p.StartMenu 'lnk1' }; Mutate = { param($s, $p) [IO.File]::Delete($p.StartMenu) } }
        @{ Name = 'added'; Cat = 'desktopShortcut'; Setup = { param($s, $p) }; Mutate = { param($s, $p) Write-Bytes $p.Desktop 'lnk1' } }
        @{ Name = 'changed'; Cat = 'desktopShortcut'; Setup = { param($s, $p) Write-Bytes $p.Desktop 'lnk1' }; Mutate = { param($s, $p) Write-Bytes $p.Desktop 'lnk2' } }
        @{ Name = 'removed'; Cat = 'desktopShortcut'; Setup = { param($s, $p) Write-Bytes $p.Desktop 'lnk1' }; Mutate = { param($s, $p) [IO.File]::Delete($p.Desktop) } }
        @{ Name = 'file added'; Cat = 'installDir'; Setup = { param($s, $p) Write-Bytes (Join-Path $p.Install 'a.bin') 'a' }; Mutate = { param($s, $p) Write-Bytes (Join-Path $p.Install 'sub\b.bin') 'b' } }
        @{ Name = 'file changed (same size)'; Cat = 'installDir'; Setup = { param($s, $p) Write-Bytes (Join-Path $p.Install 'a.bin') 'a' }; Mutate = { param($s, $p) Write-Bytes (Join-Path $p.Install 'a.bin') 'b' } }
        @{ Name = 'file removed'; Cat = 'installDir'; Setup = { param($s, $p) Write-Bytes (Join-Path $p.Install 'a.bin') 'a' }; Mutate = { param($s, $p) [IO.File]::Delete((Join-Path $p.Install 'a.bin')) } }
        @{ Name = 'dir appears (empty)'; Cat = 'installDir'; Setup = { param($s, $p) }; Mutate = { param($s, $p) New-Item -ItemType Directory -Force -Path $p.Install | Out-Null } }
        @{ Name = 'dir disappears'; Cat = 'installDir'; Setup = { param($s, $p) Write-Bytes (Join-Path $p.Install 'a.bin') 'a' }; Mutate = { param($s, $p) [IO.Directory]::Delete($p.Install, $true) } }
        @{ Name = 'file added in a second default dir'; Cat = 'installDir'; Setup = { param($s, $p) New-Item -ItemType Directory -Force -Path $s.InstallDirs[1] | Out-Null }; Mutate = { param($s, $p) Write-Bytes (Join-Path $s.InstallDirs[1] 'x.bin') 'x' } }
        @{ Name = 'empty nested dir added'; Cat = 'installDir'; Setup = { param($s, $p) Write-Bytes (Join-Path $p.Install 'a.bin') 'a' }; Mutate = { param($s, $p) New-Item -ItemType Directory -Force -Path (Join-Path $p.Install 'sub\empty') | Out-Null } }
        @{ Name = 'empty nested dir removed'; Cat = 'installDir'; Setup = { param($s, $p) Write-Bytes (Join-Path $p.Install 'a.bin') 'a'; New-Item -ItemType Directory -Force -Path (Join-Path $p.Install 'sub\empty') | Out-Null }; Mutate = { param($s, $p) [IO.Directory]::Delete((Join-Path $p.Install 'sub\empty')) } }
        @{ Name = 'ADS added on a file'; Cat = 'installDir'; Setup = { param($s, $p) Write-Bytes (Join-Path $p.Install 'a.bin') 'a' }; Mutate = { param($s, $p) Set-Ads (Join-Path $p.Install 'a.bin') 'zone' 'x' } }
        @{ Name = 'ADS changed on a file (same size)'; Cat = 'installDir'; Setup = { param($s, $p) Write-Bytes (Join-Path $p.Install 'a.bin') 'a'; Set-Ads (Join-Path $p.Install 'a.bin') 'zone' 'x' }; Mutate = { param($s, $p) Set-Ads (Join-Path $p.Install 'a.bin') 'zone' 'y' } }
        @{ Name = 'ADS removed from a file'; Cat = 'installDir'; Setup = { param($s, $p) Write-Bytes (Join-Path $p.Install 'a.bin') 'a'; Set-Ads (Join-Path $p.Install 'a.bin') 'zone' 'x' }; Mutate = { param($s, $p) Remove-Ads (Join-Path $p.Install 'a.bin') 'zone' } }
        @{ Name = 'ADS added on a nested directory'; Cat = 'installDir'; Setup = { param($s, $p) New-Item -ItemType Directory -Force -Path (Join-Path $p.Install 'sub') | Out-Null }; Mutate = { param($s, $p) Set-Ads (Join-Path $p.Install 'sub') 'dz' 'x' } }
        @{ Name = 'ADS changed on a nested directory'; Cat = 'installDir'; Setup = { param($s, $p) New-Item -ItemType Directory -Force -Path (Join-Path $p.Install 'sub') | Out-Null; Set-Ads (Join-Path $p.Install 'sub') 'dz' 'x' }; Mutate = { param($s, $p) Set-Ads (Join-Path $p.Install 'sub') 'dz' 'y' } }
        @{ Name = 'ADS removed from a nested directory'; Cat = 'installDir'; Setup = { param($s, $p) New-Item -ItemType Directory -Force -Path (Join-Path $p.Install 'sub') | Out-Null; Set-Ads (Join-Path $p.Install 'sub') 'dz' 'x' }; Mutate = { param($s, $p) Remove-Ads (Join-Path $p.Install 'sub') 'dz' } }
        @{ Name = 'ADS added on the install dir itself'; Cat = 'installDir'; Setup = { param($s, $p) New-Item -ItemType Directory -Force -Path $p.Install | Out-Null }; Mutate = { param($s, $p) Set-Ads $p.Install 'rootz' 'x' } }
        @{ Name = 'nested subkey value added'; Cat = 'uninstallKey'; Setup = { param($s, $p) Set-RegVal $p.Uninstall 'DisplayName' 'a'; New-RegKeyOnly "$($p.Uninstall)\Sub" }; Mutate = { param($s, $p) Set-RegVal "$($p.Uninstall)\Sub" 'v' 'x' } }
        @{ Name = 'nested subkey value changed'; Cat = 'uninstallKey'; Setup = { param($s, $p) Set-RegVal "$($p.Uninstall)\Sub\Deeper" 'v' 'a' }; Mutate = { param($s, $p) Set-RegVal "$($p.Uninstall)\Sub\Deeper" 'v' 'b' } }
        @{ Name = 'nested subkey value removed'; Cat = 'uninstallKey'; Setup = { param($s, $p) Set-RegVal "$($p.Uninstall)\Sub" 'v' 'a' }; Mutate = { param($s, $p) Remove-RegVal "$($p.Uninstall)\Sub" 'v' } }
        @{ Name = 'a subkey name appears under it'; Cat = 'uninstallKey'; Setup = { param($s, $p) Set-RegVal $p.Uninstall 'DisplayName' 'a' }; Mutate = { param($s, $p) New-RegKeyOnly "$($p.Uninstall)\NewSub" } }
        @{ Name = 'value KIND only (same data, REG_SZ to REG_EXPAND_SZ)'; Cat = 'uninstallKey'; Setup = { param($s, $p) Set-RegValK $p.Uninstall 'V' 'same' ([Microsoft.Win32.RegistryValueKind]::String) }; Mutate = { param($s, $p) Set-RegValK $p.Uninstall 'V' 'same' ([Microsoft.Win32.RegistryValueKind]::ExpandString) } }
        @{ Name = 'REG_BINARY value changed'; Cat = 'uninstallKey'; Setup = { param($s, $p) Set-RegValK $p.Uninstall 'V' ([byte[]](1, 2, 3)) ([Microsoft.Win32.RegistryValueKind]::Binary) }; Mutate = { param($s, $p) Set-RegValK $p.Uninstall 'V' ([byte[]](1, 2, 4)) ([Microsoft.Win32.RegistryValueKind]::Binary) } }
        @{ Name = 'REG_MULTI_SZ value changed'; Cat = 'uninstallKey'; Setup = { param($s, $p) Set-RegValK $p.Uninstall 'V' ([string[]]('a', 'b')) ([Microsoft.Win32.RegistryValueKind]::MultiString) }; Mutate = { param($s, $p) Set-RegValK $p.Uninstall 'V' ([string[]]('a', 'c')) ([Microsoft.Win32.RegistryValueKind]::MultiString) } }
        @{ Name = 'REG_DWORD value changed'; Cat = 'uninstallKey'; Setup = { param($s, $p) Set-RegValK $p.Uninstall 'V' 1 ([Microsoft.Win32.RegistryValueKind]::DWord) }; Mutate = { param($s, $p) Set-RegValK $p.Uninstall 'V' 2 ([Microsoft.Win32.RegistryValueKind]::DWord) } }
        @{ Name = 'case-only rename of a file'; Cat = 'installDir'; Setup = { param($s, $p) Write-Bytes (Join-Path $p.Install 'Foo.dll') 'a' }; Mutate = { param($s, $p) [IO.File]::Move((Join-Path $p.Install 'Foo.dll'), (Join-Path $p.Install 'foo.dll')) } }
        @{ Name = 'case-only rename of a directory (with a file inside)'; Cat = 'installDir'; Setup = { param($s, $p) Write-Bytes (Join-Path $p.Install 'Sub\a.bin') 'a' }; Mutate = { param($s, $p) [IO.Directory]::Move((Join-Path $p.Install 'Sub'), (Join-Path $p.Install 'sub')) } }
        @{ Name = 'case-only rename of a nested file'; Cat = 'installDir'; Setup = { param($s, $p) Write-Bytes (Join-Path $p.Install 'sub\Inner.dll') 'a' }; Mutate = { param($s, $p) [IO.File]::Move((Join-Path $p.Install 'sub\Inner.dll'), (Join-Path $p.Install 'sub\inner.dll')) } }
        @{ Name = 'an unrelated subkey appears under the manufacturer parent (subkey names hashed independently of the remembered key)'; Cat = 'manufacturerKey'; Setup = { param($s, $p) New-RegKeyOnly $p.Manufacturer }; Mutate = { param($s, $p) New-RegKeyOnly "$($p.Manufacturer)\SomethingElse" } }
    ) {
        $p = Get-SurfacePaths $script:sb
        & $Setup $script:sb $p
        $lane = New-TestLane $script:sb
        try {
            & $Mutate $script:sb $p
            [void](Test-ProductionTripwire -Lane $lane -Stage 'final')
            $lane.SurfaceCounts[$Cat] | Should -BeGreaterThan 0
            # the manufacturer key's subkey list also changes when the remembered key is added or removed (parent fingerprint)
            foreach ($other in @($lane.SurfaceCounts.Keys | Where-Object { $_ -ne $Cat -and $_ -ne $Also })) { $lane.SurfaceCounts[$other] | Should -Be 0 -Because "only $Cat changed ($other)" }
            @($lane.Findings).Count | Should -BeGreaterThan 0
            @($lane.FindingCodes) | Should -Contain 'TRIPWIRE_VIOLATION'
            $lane.TripwireCompleted | Should -BeTrue
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }

    It 'negative controls: all surfaces absent stays clean; all surfaces present and unchanged stays clean (both complete)' -ForEach @(@{ Present = $false }, @{ Present = $true }) {
        $p = Get-SurfacePaths $script:sb
        if ($Present) {
            Set-RegVal $p.Uninstall 'DisplayName' 'a'; Set-RegVal $p.UninstallWow 'DisplayName' 'a'; Set-RegVal $p.Remembered '' 'C:\a'
            Set-RegVal $p.RunKey $p.RunName 'C:\a.exe'; Write-Bytes $p.StartMenu 'l1'; Write-Bytes $p.Desktop 'l2'
            Write-Bytes (Join-Path $p.Install 'a.bin') 'a'; Write-Bytes (Join-Path $p.Install 'sub\b.bin') 'b'
            Write-Bytes (Join-Path $p.Install 'Sub2\Mixed.DLL') 'm'
        }
        $lane = New-TestLane $script:sb
        try {
            @(Test-ProductionTripwire -Lane $lane -Stage 'final').Count | Should -Be 0
            @($lane.Findings).Count | Should -Be 0
            @($lane.SurfaceCounts.Values | Where-Object { $_ -ne 0 }).Count | Should -Be 0
            $lane.TripwireCompleted | Should -BeTrue
        } finally { $res = Complete-HarnessLane -Lane $lane }
        $res.Evidence.tripwire.completed | Should -BeTrue
        $res.Evidence.status | Should -Be 'pass'
    }

    It 'a reparse point under a production install dir at the BASELINE refuses the lane (unknown state is never empty)' {
        $p = Get-SurfacePaths $script:sb
        $target = Join-Path $script:sb.Dir 'junction-target'; New-Item -ItemType Directory -Force -Path $target | Out-Null
        New-Item -ItemType Directory -Force -Path $p.Install | Out-Null
        New-Item -ItemType Junction -Path (Join-Path $p.Install 'link') -Target $target | Out-Null
        { New-TestLane $script:sb } | Should -Throw '*could not be fingerprinted safely*'
        # the lock was released: once the junction is gone a lane starts again
        [IO.Directory]::Delete((Join-Path $p.Install 'link'))
        $l = New-TestLane $script:sb
        [void](Complete-HarnessLane -Lane $l)
    }

    It 'an unreadable / reparse state at the FINAL fingerprint is an Error (TRIPWIRE_INCOMPLETE), completed = false, never a pass' -ForEach @(
        @{ Name = 'a reparse point appears'; Arm = { param($s, $p) $t = Join-Path $s.Dir 'jt'; New-Item -ItemType Directory -Force -Path $t | Out-Null; New-Item -ItemType Directory -Force -Path $p.Install | Out-Null; New-Item -ItemType Junction -Path (Join-Path $p.Install 'link') -Target $t | Out-Null; $null } }
        @{ Name = 'a file is locked exclusively'; Arm = { param($s, $p) Write-Bytes (Join-Path $p.Install 'a.bin') 'a'; $null } ; Lock = $true }
        @{ Name = 'a shortcut path is a directory'; Arm = { param($s, $p) New-Item -ItemType Directory -Force -Path $p.StartMenu | Out-Null; $null } }
    ) {
        $p = Get-SurfacePaths $script:sb
        if ($Lock) { Write-Bytes (Join-Path $p.Install 'a.bin') 'a' }
        $lane = New-TestLane $script:sb
        $stream = $null
        try {
            if ($Lock) { $stream = [IO.File]::Open((Join-Path $p.Install 'a.bin'), [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
            else { [void](& $Arm $script:sb $p) }
            { Test-ProductionTripwire -Lane $lane -Stage 'final' } | Should -Throw '*unknown state*'
            $lane.TripwireCompleted | Should -BeFalse
            # through the always-run cleanup the same condition becomes a recorded Error, not a silent pass
            $res = Complete-HarnessLane -Lane $lane
            $res.ExitCode | Should -Be 1
            $lane.TripwireCompleted | Should -BeFalse
            @($lane.ErrorCodes) | Should -Contain 'TRIPWIRE_INCOMPLETE'
            $res.Evidence.tripwire.completed | Should -BeFalse
            $res.Evidence.status | Should -Be 'fail'
        } finally {
            if ($stream) { $stream.Dispose() }
            if (-not $lane.Completed) { [void](Complete-HarnessLane -Lane $lane) }
        }
    }

    It 'a lane without a surface baseline cannot complete the tripwire' {
        $lane = New-TestLane $script:sb
        try {
            $lane.SurfaceBaseline = $null
            { Test-ProductionTripwire -Lane $lane -Stage 'final' } | Should -Throw '*baseline is missing*'
            $lane.TripwireCompleted | Should -BeFalse
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }

    It 'persisted evidence carries only integer counts and a bool for the surfaces: no value, path, name or hash (closed schema)' {
        $p = Get-SurfacePaths $script:sb
        $secretName = 'zz-private-model-name.bin'; $secretValue = 'C:\zz-private-user-path\app.exe'
        Write-Bytes (Join-Path $p.Install $secretName) 'a'
        Set-RegVal $p.RunKey $p.RunName $secretValue
        $lane = New-TestLane $script:sb
        try {
            Write-Bytes (Join-Path $p.Install $secretName) 'changed'
            Set-RegVal $p.RunKey $p.RunName 'C:\zz-private-user-path\other.exe'
            [void](Test-ProductionTripwire -Lane $lane -Stage 'final')
        } finally { $res = Complete-HarnessLane -Lane $lane }
        $json = $res.Evidence | ConvertTo-Json -Depth 10
        $json | Should -Not -Match 'zz-private|Snapmaker Studio|DeadlyVirusIn|HKCU|ssh-launch-test|prodsoft|prodrun'
        foreach ($c in 'uninstallKey', 'rememberedKey', 'manufacturerKey', 'runValue', 'startMenuShortcut', 'desktopShortcut', 'installDir') { $res.Evidence.tripwire.surfaces[$c] | Should -BeOfType [int] }
        # counts accumulate over the stages (the always-run final check repeats the compare), so assert presence, not an exact number
        $res.Evidence.tripwire.surfaces.runValue | Should -BeGreaterThan 0
        $res.Evidence.tripwire.surfaces.installDir | Should -BeGreaterThan 0
        $res.Evidence.tripwire.completed | Should -BeTrue
        $res.Evidence.status | Should -Be 'fail'
        Test-HarnessLaneEvidenceSchema -Evidence $res.Evidence | Should -BeNullOrEmpty
        # closed-schema negatives: a missing field, an extra field and a non-integer count are all rejected
        $bad = $res.Evidence | ConvertTo-Json -Depth 10 | ConvertFrom-Json -AsHashtable
        $bad.tripwire.Remove('completed'); Test-HarnessLaneEvidenceSchema -Evidence $bad | Should -Not -BeNullOrEmpty
        $bad = $res.Evidence | ConvertTo-Json -Depth 10 | ConvertFrom-Json -AsHashtable
        $bad.tripwire.surfaces['runValueName'] = 'x'; Test-HarnessLaneEvidenceSchema -Evidence $bad | Should -Not -BeNullOrEmpty
        $bad = $res.Evidence | ConvertTo-Json -Depth 10 | ConvertFrom-Json -AsHashtable
        $bad.tripwire.surfaces.installDir = 'C:\x'; Test-HarnessLaneEvidenceSchema -Evidence $bad | Should -Not -BeNullOrEmpty
    }

    It 'the three production data-folder tripwires still behave as before (absent stays absent; a new Roaming folder is a violation)' {
        $lane = New-TestLane $script:sb
        try {
            New-Item -ItemType Directory -Force -Path $script:sb.Roaming | Out-Null
            @(Test-ProductionTripwire -Lane $lane -Stage 'final').Count | Should -BeGreaterThan 0
            $lane.TripwireCompleted | Should -BeTrue
            $lane.SurfaceCounts.installDir | Should -Be 0
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }

    It 'negative control: an install dir with an empty nested dir, files and alternate data streams (file, dir, root) stays clean when unchanged' {
        $p = Get-SurfacePaths $script:sb
        Write-Bytes (Join-Path $p.Install 'a.bin') 'a'; Set-Ads (Join-Path $p.Install 'a.bin') 'zone' 'x'
        New-Item -ItemType Directory -Force -Path (Join-Path $p.Install 'sub\empty') | Out-Null; Set-Ads (Join-Path $p.Install 'sub') 'dz' 'y'; Set-Ads $p.Install 'rootz' 'z'
        $lane = New-TestLane $script:sb
        try {
            @(Test-ProductionTripwire -Lane $lane -Stage 'final').Count | Should -Be 0
            @($lane.Findings).Count | Should -Be 0
            $lane.SurfaceCounts.installDir | Should -Be 0
            $lane.TripwireCompleted | Should -BeTrue
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }

    It 'B2: TripwireCompleted is reset at the ENTRY of every call: a successful call followed by a failing final call is never completed (Error TRIPWIRE_INCOMPLETE, evidence false, the acceptance check condition fails)' {
        $p = Get-SurfacePaths $script:sb
        $lane = New-TestLane $script:sb
        try {
            [void](Test-ProductionTripwire -Lane $lane -Stage 'mid')
            $lane.TripwireCompleted | Should -BeTrue
            $t = Join-Path $script:sb.Dir 'jt'; New-Item -ItemType Directory -Force -Path $t | Out-Null
            New-Item -ItemType Directory -Force -Path $p.Install | Out-Null
            New-Item -ItemType Junction -Path (Join-Path $p.Install 'link') -Target $t | Out-Null
            { Test-ProductionTripwire -Lane $lane -Stage 'final' } | Should -Throw '*unknown state*'
            $lane.TripwireCompleted | Should -BeFalse -Because 'a stale true from the earlier call must not survive'
            $res = Complete-HarnessLane -Lane $lane
            $lane.TripwireCompleted | Should -BeFalse
            @($lane.ErrorCodes) | Should -Contain 'TRIPWIRE_INCOMPLETE'
            $res.Evidence.tripwire.completed | Should -BeFalse
            $res.ExitCode | Should -Be 1
            (($lane.Findings.Count -eq 0) -and $lane.TripwireCompleted) | Should -BeFalse -Because 'this is the run.ps1 tripwire check condition'
        } finally { if (-not $lane.Completed) { [void](Complete-HarnessLane -Lane $lane) } }
    }

    It 'O-F2: Test-DirectorySnapshotUnknown flags every sentinel the data-folder snapshot can record, and nothing else' {
        InModuleScope HarnessLauncher {
            $mk = { param($k, $v) [ordered]@{ Exists = $true; Entries = [ordered]@{ $k = $v } } }
            Test-DirectorySnapshotUnknown -Snapshot (& $mk '<uninspectable>' 'inspect-error') | Should -BeTrue
            Test-DirectorySnapshotUnknown -Snapshot (& $mk '<unlistable>:sub' 'enum-error') | Should -BeTrue
            Test-DirectorySnapshotUnknown -Snapshot (& $mk 'a.bin' 'file|unreadable') | Should -BeTrue
            Test-DirectorySnapshotUnknown -Snapshot (& $mk 'a.bin' 'gone-or-uninspectable') | Should -BeTrue
            Test-DirectorySnapshotUnknown -Snapshot (& $mk 'a.bin' 'file|3|123') | Should -BeFalse
            Test-DirectorySnapshotUnknown -Snapshot (& $mk 'sub' 'dir') | Should -BeFalse
            Test-DirectorySnapshotUnknown -Snapshot ([ordered]@{ Exists = $false; Entries = [ordered]@{} }) | Should -BeFalse
        }
    }

    It 'O-F2: a data-folder sentinel in the BASELINE or in the FINAL snapshot makes the tripwire incomplete (Error TRIPWIRE_INCOMPLETE), never "no change"' -ForEach @(@{ Where = 'baseline' }, @{ Where = 'final' }) {
        # a regular FILE where a data folder is expected cannot be listed: the snapshot records an enum-error sentinel
        $notDir = Join-Path $script:sb.Dir 'not-a-dir.txt'; [IO.File]::WriteAllText($notDir, 'x')
        if ($Where -eq 'baseline') { Set-Hooks $script:sb @{ RoamingDir = $notDir } }
        $lane = New-TestLane $script:sb
        try {
            if ($Where -eq 'final') { Set-Hooks $script:sb @{ RoamingDir = $notDir } }
            [void](Test-ProductionTripwire -Lane $lane -Stage 'final')
            $lane.TripwireCompleted | Should -BeFalse
            @($lane.ErrorCodes) | Should -Contain 'TRIPWIRE_INCOMPLETE'
        } finally { $res = Complete-HarnessLane -Lane $lane }
        $res.Evidence.tripwire.completed | Should -BeFalse
        $res.Evidence.status | Should -Be 'fail'
        $res.ExitCode | Should -Be 1
    }

    It 'the REAL default surface locations are pinned without reading them: four Software roots, the HKCU Run key and the three default install dirs' {
        $loc = InModuleScope HarnessLauncher { Get-DefaultProductionSurfaceLocations }
        @($loc.SoftwareRoots) | Should -Be @('HKCU:\Software', 'HKLM:\Software', 'HKLM:\Software\WOW6432Node', 'HKCU:\Software\WOW6432Node')
        $loc.RunKeyPath | Should -Be ('HKCU:\Software\' + $script:Id.Registry.RunKey)
        $expected = @(foreach ($sf in 'LocalApplicationData', 'ProgramFiles', 'ProgramFilesX86') { Join-Path ([Environment]::GetFolderPath($sf)) $script:Prod.DefaultInstallDirName })
        @($loc.InstallDirs) | Should -Be $expected
        @($loc.InstallDirs).Count | Should -Be 3
        # the snapshot builder takes its defaults from that function and carries no registry-root literal of its own
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($script:LauncherPath, [ref]$null, [ref]$null)
        $fn = $ast.Find({ param($x) $x -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $x.Name -eq 'Get-ProductionSurfaceSnapshot' }, $true)
        @($fn.FindAll({ param($x) $x -is [System.Management.Automation.Language.CommandAst] }, $true) | ForEach-Object { $_.GetCommandName() }) | Should -Contain 'Get-DefaultProductionSurfaceLocations'
        @($fn.FindAll({ param($x) $x -is [System.Management.Automation.Language.StringConstantExpressionAst] }, $true) | Where-Object { $_.Value -match '^HK(CU|LM):' }) | Should -BeNullOrEmpty
    }

    It 'ProductionInstallDirs = @() means NONE (it does not fall back to the real default directories)' {
        Set-Hooks $script:sb @{ ProductionInstallDirs = @() }
        $snap = InModuleScope HarnessLauncher { Get-ProductionSurfaceSnapshot }
        @($snap.installDir).Count | Should -Be 0
        Write-Bytes (Join-Path $script:sb.InstallDirs[0] 'a.bin') 'a'
        $lane = New-TestLane $script:sb
        try {
            Write-Bytes (Join-Path $script:sb.InstallDirs[0] 'a.bin') 'changed'
            [void](Test-ProductionTripwire -Lane $lane -Stage 'final')
            $lane.SurfaceCounts.installDir | Should -Be 0
            $lane.TripwireCompleted | Should -BeTrue
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }
    It 'the file helpers refuse a path outside the test sandbox, a wildcard path and a path through a reparse point (<Name>)' -ForEach @(
        @{ Name = 'Write-Bytes'; Call = { param($p) Write-Bytes $p 'x' } }
        @{ Name = 'Set-Ads'; Call = { param($p) Set-Ads $p 'z' 'x' } }
        @{ Name = 'Set-AdsBytes'; Call = { param($p) Set-AdsBytes $p 'z' ([byte[]](65)) } }
        @{ Name = 'Remove-Ads'; Call = { param($p) Remove-Ads $p 'z' } }
    ) {
        $outsideDir = Join-Path (Split-Path -Parent $script:sb.Dir) "outside-$([guid]::NewGuid().ToString('N'))"
        { & $Call (Join-Path $outsideDir 'x.bin') } | Should -Throw '*outside the test sandbox*'
        Test-Path -LiteralPath $outsideDir | Should -BeFalse -Because 'nothing may be created outside the sandbox'
        { & $Call (Join-Path $script:sb.Dir '*.bin') } | Should -Throw '*wildcard*'
        { & $Call (Join-Path $script:sb.Dir 'a.bin:zone') } | Should -Throw '*stream-suffixed*'
        $target = Join-Path $script:sb.Dir 'jt'; New-Item -ItemType Directory -Force -Path $target | Out-Null
        New-Item -ItemType Junction -Path (Join-Path $script:sb.Dir 'jl') -Target $target | Out-Null
        { & $Call (Join-Path $script:sb.Dir 'jl\x.bin') } | Should -Throw '*reparse point*'
        Test-Path -LiteralPath (Join-Path $target 'x.bin') | Should -BeFalse
    }

    It 'tiny ADS (<Size> byte(s)) on a <Target>: the baseline does not false-refuse, the fingerprint is stable, and a change in the tiny stream is detected' -ForEach @(
        @{ Target = 'file'; Size = 0; Before = [byte[]]@(); After = [byte[]](65) }
        @{ Target = 'file'; Size = 1; Before = [byte[]](65); After = [byte[]](66) }
        @{ Target = 'file'; Size = 2; Before = [byte[]](65, 66); After = [byte[]](66, 65) }
        @{ Target = 'nested dir'; Size = 0; Before = [byte[]]@(); After = [byte[]](65) }
        @{ Target = 'nested dir'; Size = 1; Before = [byte[]](65); After = [byte[]](66) }
        @{ Target = 'nested dir'; Size = 2; Before = [byte[]](65, 66); After = [byte[]](66, 65) }
        @{ Target = 'install dir root'; Size = 0; Before = [byte[]]@(); After = [byte[]](65) }
        @{ Target = 'install dir root'; Size = 1; Before = [byte[]](65); After = [byte[]](66) }
        @{ Target = 'install dir root'; Size = 2; Before = [byte[]](65, 66); After = [byte[]](66, 65) }
    ) {
        $p = Get-SurfacePaths $script:sb
        Write-Bytes (Join-Path $p.Install 'a.bin') 'a'
        New-Item -ItemType Directory -Force -Path (Join-Path $p.Install 'sub') | Out-Null
        $path = switch ($Target) { 'file' { Join-Path $p.Install 'a.bin' } 'nested dir' { Join-Path $p.Install 'sub' } default { $p.Install } }
        Set-AdsBytes $path 'tiny' $Before
        $lane = New-TestLane $script:sb
        try {
            [void](Test-ProductionTripwire -Lane $lane -Stage 'stable')
            @($lane.Findings).Count | Should -Be 0
            $lane.SurfaceCounts.installDir | Should -Be 0
            $lane.TripwireCompleted | Should -BeTrue
            Set-AdsBytes $path 'tiny' $After
            [void](Test-ProductionTripwire -Lane $lane -Stage 'changed')
            $lane.SurfaceCounts.installDir | Should -BeGreaterThan 0
            $lane.TripwireCompleted | Should -BeTrue
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }

    It 'strictness: an error while enumerating the install dir (<Where>) makes the fingerprint THROW (unknown state), never a silent skip' -ForEach @(
        @{ Where = 'recursive listing'; Fn = 'Get-ChildItem'; Params = '[string]$LiteralPath, [switch]$Recurse, [switch]$Force'; Cond = '$Recurse' }
        @{ Where = 'alternate data stream listing'; Fn = 'Get-Item'; Params = '[string]$LiteralPath, [string[]]$Stream, [switch]$Force'; Cond = '$Stream' }
    ) {
        $p = Get-SurfacePaths $script:sb
        Write-Bytes (Join-Path $p.Install 'a.bin') 'a'
        # a real advanced function shadows the cmdlet inside the module: it emits a NON-terminating error, so only an explicit
        # -ErrorAction Stop in the production code turns it into a throw (a SilentlyContinue there would swallow it)
        $shadow = @"
function $Fn { [CmdletBinding()] param($Params)
    if ($Cond) { `$PSCmdlet.WriteError([System.Management.Automation.ErrorRecord]::new([System.UnauthorizedAccessException]::new('simulated access denied'), 'sim', [System.Management.Automation.ErrorCategory]::PermissionDenied, `$null)); return }
    Microsoft.PowerShell.Management\$Fn @PSBoundParameters }
"@
        InModuleScope HarnessLauncher -Parameters @{ D = $p.Install; Shadow = $shadow; Fn = $Fn } {
            . ([scriptblock]::Create($Shadow))
            try { { Get-InstallDirFingerprint -Dir $D } | Should -Throw '*unknown state*' } finally { Remove-Item -LiteralPath "function:\$Fn" }
            (Get-InstallDirFingerprint -Dir $D).Exists | Should -BeTrue
        }
    }

    It 'strictness (real access error): a scratch subdirectory the user may not list makes the install-dir fingerprint THROW, and the lane baseline refuses' {
        $p = Get-SurfacePaths $script:sb
        $locked = Join-Path $p.Install 'locked'
        Write-Bytes (Join-Path $locked 'f.bin') 'a'
        $me = [Security.Principal.WindowsIdentity]::GetCurrent().User
        $rule = [Security.AccessControl.FileSystemAccessRule]::new($me, [Security.AccessControl.FileSystemRights]::ListDirectory, [Security.AccessControl.AccessControlType]::Deny)
        $acl = Get-Acl -LiteralPath $locked; $acl.AddAccessRule($rule); Set-Acl -LiteralPath $locked -AclObject $acl
        try {
            InModuleScope HarnessLauncher -Parameters @{ D = $p.Install } { { Get-InstallDirFingerprint -Dir $D } | Should -Throw '*unknown state*' }
            { New-TestLane $script:sb } | Should -Throw '*could not be fingerprinted safely*'
        } finally {
            $acl = Get-Acl -LiteralPath $locked; [void]$acl.RemoveAccessRule($rule); Set-Acl -LiteralPath $locked -AclObject $acl
        }
        # once readable again the lane starts normally
        $l = New-TestLane $script:sb
        [void](Complete-HarnessLane -Lane $l)
    }
    It 'the new surface code never calls a mutating cmdlet or method on production surfaces (AST of the new functions)' {
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($script:LauncherPath, [ref]$null, [ref]$null)
        $names = 'Get-Sha256HexOfText', 'Get-Sha256HexOfFileShared', 'ConvertTo-RegistryValueText', 'Get-RegistryKeyFingerprint', 'Get-RegistryValueFingerprint',
            'Get-FileFingerprint', 'Get-InstallDirFingerprint', 'Get-InstallDirEntryList', 'Get-StreamFingerprints', 'Get-DefaultProductionSurfaceLocations', 'Test-DirectorySnapshotUnknown', 'Get-ProductionSurfaceSnapshot', 'Compare-ProductionSurfaceSnapshot', 'Test-ProductionTripwire'
        $badCmd = 'Set-Item', 'Set-ItemProperty', 'New-Item', 'New-ItemProperty', 'Remove-Item', 'Remove-ItemProperty', 'Copy-Item', 'Copy-ItemProperty', 'Move-Item', 'Move-ItemProperty',
            'Rename-Item', 'Rename-ItemProperty', 'Clear-Item', 'Clear-ItemProperty', 'Set-Content', 'Add-Content', 'Clear-Content', 'Out-File', 'Start-Process', 'Stop-Process', 'Invoke-Expression', 'Set-Acl'
        $badMember = 'SetValue', 'DeleteValue', 'DeleteSubKey', 'DeleteSubKeyTree', 'CreateSubKey', 'WriteAllText', 'WriteAllBytes', 'Delete', 'Move', 'Copy', 'Create', 'CreateDirectory', 'Kill', 'Replace', 'SetAttributes', 'Write'
        foreach ($n in $names) {
            $fn = $ast.Find({ param($x) $x -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $x.Name -eq $n }, $true)
            $fn | Should -Not -BeNullOrEmpty -Because $n
            $cmds = @($fn.FindAll({ param($x) $x -is [System.Management.Automation.Language.CommandAst] }, $true) | ForEach-Object { $_.GetCommandName() })
            $cmds | Where-Object { $_ -in $badCmd } | Should -BeNullOrEmpty -Because "$n must not mutate"
            $members = @($fn.FindAll({ param($x) $x -is [System.Management.Automation.Language.InvokeMemberExpressionAst] }, $true) | ForEach-Object { $_.Member.Extent.Text })
            $members | Where-Object { $_ -in $badMember } | Should -BeNullOrEmpty -Because "$n must not mutate"
        }
    }
}

Describe 'Static checks on the module and the four converted scripts' {
    BeforeAll {
        $root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
        $script:Files = [ordered]@{
            module   = Join-Path $PSScriptRoot 'HarnessLauncher.psm1'
            run      = Join-Path $root 'tools\acceptance\run.ps1'
            verify   = Join-Path $root 'tools\hardware\verify.ps1'
            record   = Join-Path $root 'tools\demo\record.ps1'
            capture  = Join-Path $root 'scripts\capture_embedded.ps1'
        }
    }
    It 'has zero parse errors in <_>' -ForEach 'module', 'run', 'verify', 'record', 'capture' {
        $errs = $null; $tok = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile($script:Files[$_], [ref]$tok, [ref]$errs)
        @($errs).Count | Should -Be 0
    }
    It 'no wildcard registration discovery in <_>' -ForEach 'run', 'verify', 'record', 'capture' {
        (Get-Content -LiteralPath $script:Files[$_] -Raw) | Should -Not -Match "-like\s+'\*Snapmaker Studio\*'"
    }
    It 'no installer globbing in <_>' -ForEach 'run', 'verify', 'record', 'capture' {
        (Get-Content -LiteralPath $script:Files[$_] -Raw) | Should -Not -Match '(?i)Get-ChildItem[^\r\n]*_x64-setup|\*_x64-setup'
    }
    It 'no session-environment mutation for the isolation variables in <_>' -ForEach 'run', 'verify', 'record', 'capture' {
        $t = Get-Content -LiteralPath $script:Files[$_] -Raw
        $t | Should -Not -Match '\$env:SNAPSTUDIO_DATA_DIR\s*='
        $t | Should -Not -Match '\$env:WEBVIEW2_\w+\s*='
        $t | Should -Not -Match '\$env:SNAPSTUDIO_\w+\s*='
        $t | Should -Not -Match '(?i)Remove-Item\s+["'']?Env:'
        $t | Should -Not -Match '(?i)\[Environment\]::SetEnvironmentVariable'
    }
    It 'no name-based process stop and no raw Start-Process in <_>' -ForEach 'module', 'run', 'verify', 'record', 'capture' {
        $t = Get-Content -LiteralPath $script:Files[$_] -Raw
        $t | Should -Not -Match '(?i)Stop-Process\s+-Name'
        $t | Should -Not -Match '(?i)Get-Process[^\r\n|]*\|\s*Stop-Process'
        $t | Should -Not -Match '(?i)taskkill|\bpkill\b|\.Kill\('
        $t | Should -Not -Match '(?i)\bStart-Process\b'
    }
    It 'no production uninstall-key backup/restore (reg export / import) in <_>' -ForEach 'run', 'verify', 'record', 'capture' {
        (Get-Content -LiteralPath $script:Files[$_] -Raw) | Should -Not -Match '(?i)\breg\s+(export|import)\b|backup-uninstall'
    }
    It 'no absolute local path or username literal in <_>' -ForEach 'module', 'run', 'verify', 'record', 'capture' {
        $t = Get-Content -LiteralPath $script:Files[$_] -Raw
        $t | Should -Not -Match '(?i)\b[A-Z]:\\(Users|STL Files|Program Files|Windows|OneDrive)'
        $t | Should -Not -Match '(?i)/home/|C:/Users'
    }
    It 'every converted script routes the lane through the shared launcher (no per-script copies)' -ForEach 'run', 'verify', 'record', 'capture' {
        $t = Get-Content -LiteralPath $script:Files[$_] -Raw
        $t | Should -Match 'HarnessLauncher\.psm1'
        $t | Should -Match 'Start-HarnessLane'
        $t | Should -Match 'Complete-HarnessLane'
        $t | Should -Match 'Install-HarnessBuild'
        $t | Should -Match 'Start-HarnessApp'
    }
    It 'every converted script runs Complete-HarnessLane inside a finally block' -ForEach 'run', 'verify', 'record', 'capture' {
        $errs = $null; $tok = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($script:Files[$_], [ref]$tok, [ref]$errs)
        $tries = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.TryStatementAst] -and $n.Finally -and $n.Finally.Extent.Text -match 'Complete-HarnessLane' }, $true))
        $tries.Count | Should -BeGreaterOrEqual 1
    }
    It 'every converted script takes -InstallerPath/-AttestationPath or -RealInstaller/-ExpectedSha256 and no production installer discovery' -ForEach 'run', 'verify', 'record', 'capture' {
        $errs = $null; $tok = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($script:Files[$_], [ref]$tok, [ref]$errs)
        $names = @($ast.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath })
        foreach ($n in 'InstallerPath', 'AttestationPath', 'RealInstaller', 'ExpectedSha256', 'SourceVersion', 'KeepInstall') { $names | Should -Contain $n }
        $names | Should -Not -Contain 'Installer'
        # L2: no script-level harness root override (the install dir must stay under the per-user harness root, never %TEMP%).
        $names | Should -Not -Contain 'HarnessRoot'
    }
    It 'lane evidence is persisted only through the closed-schema report function in <_>' -ForEach 'verify', 'record', 'capture' {
        $t = Get-Content -LiteralPath $script:Files[$_] -Raw
        $t | Should -Match 'Publish-HarnessLaneReport'
        $t | Should -Not -Match 'Evidence\s*\|\s*ConvertTo-Json'
        $t | Should -Not -Match '(?m)^\s*\[void\]\(Write-HarnessLaneEvidence'    # the report function owns the writer and its failure handling
    }
    It 'verify.ps1 redacts the printer address in the lane evidence it writes' {
        (Get-Content -LiteralPath $script:Files['verify'] -Raw) | Should -Match 'Publish-HarnessLaneReport[^\r\n]*-Redact @\(\$PrinterHost\)'
    }
    It 'X2: <_> exits non-zero when the report (evidence write) fails, and capture prints no success line before that check' -ForEach 'verify', 'record', 'capture' {
        $t = Get-Content -LiteralPath $script:Files[$_] -Raw
        if ($_ -eq 'verify') { $t | Should -Match 'if \(\$rc -ne 0 -and \$code -eq 0\) \{ \$code = 1 \}' }
        else { $t | Should -Match 'if \(\$rc -ne 0\) \{ exit 1 \}' }
        if ($_ -eq 'capture') { $t.IndexOf('if ($rc -ne 0) { exit 1 }') | Should -BeLessThan $t.IndexOf('Write-Host "done"') }
    }
    It 'run.ps1 takes -UpgradeFromSha256SumsPath and hands it to the lane (not the primary SUMS path)' {
        $t = Get-Content -LiteralPath $script:Files['run'] -Raw
        $t | Should -Match '\[string\]\$UpgradeFromSha256SumsPath'
        $t | Should -Match 'UpgradeFromSha256SumsPath = \$UpgradeFromSha256SumsPath'
    }
    It 'run.ps1: the tripwire check requires the tripwire to have COMPLETED and states exactly what is checked' {
        $t = Get-Content -LiteralPath $script:Files['run'] -Raw
        $t | Should -Match 'Add-Check "Production state unchanged \(tripwire\)" \(\(\$lane\.Findings\.Count -eq 0\) -and \$lane\.TripwireCompleted\)'
        $t | Should -Match 'the tripwire did not complete'
        foreach ($phrase in 'uninstall, remembered-location and manufacturer registry keys', 'Run value', 'production Start Menu and Desktop shortcuts', 'production install directories', 'no acceptance shortcut in the real Start Menu/Desktop') { $t | Should -Match ([regex]::Escape($phrase)) }
        $t | Should -Not -Match 'no change in the production data folders or real Start Menu/Desktop"'
        $t | Should -Match 'Add-Check "Harness cleanup reported no errors"'
    }
    It 'verify, record and capture get the install-surface tripwire through the shared lane (Start-HarnessLane + Complete-HarnessLane), with no tripwire of their own' -ForEach 'verify', 'record', 'capture' {
        $t = Get-Content -LiteralPath $script:Files[$_] -Raw
        $t | Should -Match 'Start-HarnessLane'
        $t | Should -Match 'Complete-HarnessLane -Lane \$lane'
        $t | Should -Not -Match 'Get-ProductionStateSnapshot|Get-ProductionSurfaceSnapshot|Test-ProductionTripwire'
    }
    It '#57-5: run.ps1 records a FAILED check when building the acceptance lane block throws (never an all-pass report with no lane block)' {
        $errs = $null; $tok = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($script:Files['run'], [ref]$tok, [ref]$errs)
        $catches = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CatchClauseAst] -and $n.Body.Extent.Text -match 'could not be built' }, $true))
        $catches.Count | Should -Be 1
        $adds = @($catches[0].Body.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Check' }, $true))
        $adds.Count | Should -Be 1
        $adds[0].CommandElements[1].Value | Should -Be 'Lane evidence block could be built'
        $adds[0].CommandElements[2].Extent.Text | Should -Be '$false'
        $catches[0].Body.Extent.Text | Should -Match '\$reportWriteFailed = \$true'
        (Get-Content -LiteralPath $script:Files['run'] -Raw) | Should -Match 'reportWriteFailed\) \{ exit 1 \}'
    }
    It 'run.ps1 builds the persisted lane block through Get-HarnessAcceptanceLaneEvidence and never passes $result.Evidence through' {
        $t = Get-Content -LiteralPath $script:Files['run'] -Raw
        $t | Should -Match 'Get-HarnessAcceptanceLaneEvidence -Lane \$lane -Result \$result -Checks \$checks'
        $t | Should -Match '-LaneEvidence \$laneBlock'
        $t | Should -Not -Match 'LaneEvidence \$\(if \(\$result'
        $t | Should -Not -Match '-LaneEvidence \$result\.Evidence'
    }
    It 'CLOSED SCHEMA: run.ps1 persists only fixed check names + pass/fail (no detail), and every check name is a string literal' {
        $t = Get-Content -LiteralPath $script:Files['run'] -Raw
        $t | Should -Match 'Write-HarnessAcceptanceReport -Path \$reportPath -Checks \$checks'
        $t | Should -Not -Match 'Scrub-EvidenceText \(\$report'
        $t | Should -Not -Match '\$json \| Set-Content \$reportPath'
        $t | Should -Match 'Protect-LaneText -Text \$_\.Exception\.Message -Lane \$lane\)" }'
        $t | Should -Match 'reportWriteFailed\) \{ exit 1 \}'
        $t | Should -Match 'Test-HarnessLaneEvidenceSchema'
        $errs = $null; $tok = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($script:Files['run'], [ref]$tok, [ref]$errs)
        $calls = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Check' }, $true))
        $calls.Count | Should -BeGreaterThan 50
        foreach ($c in $calls) {
            $first = $c.CommandElements[1]
            ($first -is [System.Management.Automation.Language.StringConstantExpressionAst]) | Should -BeTrue -Because "Add-Check name must be a literal: $($c.Extent.Text.Substring(0, [Math]::Min(60, $c.Extent.Text.Length)))"
        }
    }
    It 'c: run.ps1 judges "Install directory removed" with the strict count and fails on an ambiguous ($null) state' {
        $t = Get-Content -LiteralPath $script:Files['run'] -Raw
        $t | Should -Match 'Get-InstallDirFileCount -Dir \$installDir'
        $t | Should -Match '\$null -ne \$leftN -and \$leftN -eq 0'
        $t | Should -Not -Match 'Get-ChildItem \$installDir -Recurse -File -ErrorAction SilentlyContinue'
    }
    It 'B3: the docs state plainly what is closed-schema, what is not, and what the secondary check does not cover' {
        $d = (Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\..\docs\internal\HARNESS_ISOLATION.md') -Raw) -replace '\s+', ' '
        $d | Should -Match '`lane` block INSIDE `acceptance.json`'
        $d | Should -Match 'there is no separate `lane-evidence.json` there'
        $d | Should -Match 'node-written `results-\*.json` and logs .* and `hardware.json`, are NOT closed-schema'
        $d | Should -Match 'secondary check does NOT cover the `acceptance.json` lane block'
        $d | Should -Match 'human privacy glance'
        $d | Should -Match 'Most exception and detail text'
        $d | Should -Match 'fixed enums .* strict patterns .* integers'
        $d | Should -Not -Match 'any free text is rejected|unknown property or any free text'
        $d | Should -Not -Match 'scrubber guarantees'
        $c = (Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\..\docs\RELEASE_CHECKLIST.md') -Raw) -replace '\s+', ' '
        $c | Should -Match 'carries the closed-schema lane block inside it'
        $c | Should -Match 'for the hardware and demo harnesses, `lane-evidence.json`'
        $c | Should -Match 'capture harness .* writes its lane evidence beside the screenshot output path'
        $c | Should -Match 'NOT closed-schema .* human privacy glance'
        $c | Should -Not -Match 'copy what the release record needs from there'
        $v = (Get-Content -LiteralPath $script:Files['verify'] -Raw) -replace '\s+', ' '
        $v | Should -Match 'lane-evidence.json is written LATER, by this script, after that scan: it is a closed-schema object'
    }
    It 'the release checklist points evidence at the harness run folder, not docs/internal result files' {
        $t = Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\..\docs\RELEASE_CHECKLIST.md') -Raw
        $t | Should -Not -Match 'acceptance-X\.Y\.Z\.json'
        $t | Should -Not -Match 'hardware-X\.Y\.Z\.json'
        $t | Should -Match 'harness root>\\run\\<id>\\evidence'
    }
    It 'the release checklist no longer prescribes the old -Installer/-UpgradeFrom invocation or the false registry-restore claim (M1)' {
        $t = Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\..\docs\RELEASE_CHECKLIST.md') -Raw
        $t | Should -Not -Match '-Installer <RC exe>'
        $t | Should -Not -Match '-UpgradeFrom <previous'
        $t | Should -Not -Match '(?i)backs up and restores its registry entry'
        $t | Should -Match 'HARNESS_ISOLATION\.md'
        $t | Should -Match '-InstallerPath <rewrapped'
    }
}

Describe 'Empty-string argv elements (the check-phase helpers)' {
    BeforeEach { $script:sb = New-Sandbox; Set-Hooks $script:sb }
    AfterEach { Remove-Sandbox $script:sb }

    It 'Invoke-HarnessNode accepts empty-string elements in ArgumentList and they reach node' {
        # Regression (second real lane run): run.ps1's Invoke-Phase passes @($node, $phase, $cdp, $outDir, $arg, $arg2, $arg3, $url)
        # where most optional arguments are '', and a Mandatory [string[]] rejects an empty element without [AllowEmptyString()]:
        # "Cannot bind argument to parameter 'ArgumentList' because it is an empty string".
        Set-DefaultMocks
        $lane = New-TestLane $script:sb
        try {
            $r = Invoke-HarnessNode -Lane $lane -ArgumentList @('-e', 'process.stdout.write(JSON.stringify(process.argv.slice(1)))', '', 'x', '', '')
            $r.ExitCode | Should -Be 0
            ($r.Output -join '') | Should -Be '["","x","",""]'
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }
    It 'Invoke-HarnessTool accepts empty-string elements too' {
        Set-DefaultMocks
        $lane = New-TestLane $script:sb
        try {
            $r = Invoke-HarnessTool -Lane $lane -Tool 'node' -ArgumentList @('-e', 'process.stdout.write(String(process.argv.length - 1))', '', '')
            $r.ExitCode | Should -Be 0
            ($r.Output -join '') | Should -Be '2'
        } finally { [void](Complete-HarnessLane -Lane $lane) }
    }
}