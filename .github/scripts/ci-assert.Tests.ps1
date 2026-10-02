<#
REGRESSION and ACCIDENT control, not a security boundary. Static checks catch
accidents and regressions; a determined author can obfuscate via COM,
reflection, encoded Invoke-Expression, or dynamic members. The YAML parser is
minimal. Runner-identity environment variables (runneradmin,
RUNNER_ENVIRONMENT, ImageOS) are verified at the first dry CI run. The real
boundary is tools/lib InstallGuard plus disposable GitHub-hosted runners. Task
C routes the workstation launch sites through the guard.
#>

BeforeAll {
    $scriptDir = $PSScriptRoot
    . (Join-Path $scriptDir 'ci-assert-shortcuts.ps1')
    $fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) "ci-assert-fixture-$([guid]::NewGuid())"
    New-Item -ItemType Directory -Force $fixtureRoot | Out-Null
    $writerPins = @{
        'ci-assert-manifest.ps1' = '8e10d60e1cb1fa0a6b5b3a233b697113623d05e333ab29aa7cf793212e754b32'
        'ci-assert-registry.ps1' = 'd739f0f1ecadcd987b0e79f788c5f4cb7c08460fabf5d7f3747dc980a0df5d66'
        'ci-assert-sha256sums.ps1' = 'd739f0f1ecadcd987b0e79f788c5f4cb7c08460fabf5d7f3747dc980a0df5d66'
        'ci-assert-shortcuts.ps1' = 'd739f0f1ecadcd987b0e79f788c5f4cb7c08460fabf5d7f3747dc980a0df5d66'
    }

    function Get-Ast([string] $Path) {
        $tokens = $null; $errors = $null
        $ast = [Management.Automation.Language.Parser]::ParseFile($Path, [ref] $tokens, [ref] $errors)
        if ($errors.Count) { throw "Parse errors in $Path" }
        $ast
    }

    function Get-WriterHash([string] $Path) {
        $ast = Get-Ast $Path
        $writer = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and
                $n.Name -eq 'Write-CiAssertOutput' }, $true))
        if ($writer.Count -ne 1) { throw 'Expected one output writer.' }
        ([Security.Cryptography.SHA256]::Create().ComputeHash(
            [Text.Encoding]::UTF8.GetBytes($writer[0].Extent.Text)) |
            ForEach-Object ToString x2) -join ''
    }

    $script:HelperStaticMemberAllowlist = @(
        @{ Type='System.String'; Member='IsNullOrWhiteSpace' }
        @{ Type='System.IO.Path'; Member='GetFullPath' }
        @{ Type='System.IO.Path'; Member='GetTempPath' }
        @{ Type='System.IO.Path'; Member='GetFileName' }
        @{ Type='System.IO.Path'; Member='IsPathRooted' }
        @{ Type='System.StringComparison'; Member='OrdinalIgnoreCase' }
        @{ Type='System.IO.FileInfo'; Member='new' }
        @{ Type='System.IO.File'; Member='WriteAllText' }
        @{ Type='System.IO.File'; Member='ReadAllBytes' }
        @{ Type='System.IO.FileAttributes'; Member='ReparsePoint' }
        @{ Type='Microsoft.Win32.Registry'; Member='CurrentUser' }
        @{ Type='System.Text.Encoding'; Member='Unicode' }
        @{ Type='System.Text.Encoding'; Member='GetBytes' }
        @{ Type='System.Environment'; Member='GetFolderPath' }
        @{ Type='System.Activator'; Member='CreateInstance' }
        @{ Type='System.Type'; Member='GetTypeFromProgID' }
        @{ Type='System.Net.WebRequest'; Member='Create' }
        @{ Type='System.IO.StreamReader'; Member='new' }
        @{ Type='System.Text.RegularExpressions.Regex'; Member='Escape' }
        @{ Type='System.Text.RegularExpressions.Regex'; Member='Match' }
    )
    $script:HelperInstanceMemberAllowlist = @{
        'full'=@('IndexOf','StartsWith')
        'rootFull'=@('TrimEnd')
        'leaf'=@('Exists','Attributes','Directory')
        'cursor'=@('Exists','Attributes','Parent')
        'file'=@('FullName','Length','Substring')
        'file.FullName'=@('Substring')
        'relative'=@('Replace')
        'uninstall'=@('GetValue','Dispose')
        'remembered'=@('GetValue','Dispose')
        'manufacturer'=@('Dispose')
        'run'=@('GetValue','Dispose')
        'key'=@('Dispose')
        'request'=@('GetResponse')
        'response'=@('GetResponseStream','Dispose')
        'reader'=@('ReadToEnd','Dispose')
        'shell'=@('CreateShortcut')
        'link'=@('TargetPath')
        'bytes'=@('Length')
        'needle'=@('Length')
        'result'=@('Installer','Sha256')
        'state'=@('UninstallKeyPresent','InstallDirPresent','RunValuePresent','RememberedKeyPresent','RememberedLocation','InstallLocation','ManufacturerKeyPresent')
        '_'=@('TargetMatches','AumidVerified')
        'MyInvocation'=@('InvocationName')
    }

    function Get-HelperTypeName($TypeExpression) {
        $name = $TypeExpression.TypeName.FullName
        $aliases = @{
            'string'='System.String'
            'IO.Path'='System.IO.Path'; 'IO.File'='System.IO.File'; 'IO.FileInfo'='System.IO.FileInfo'
            'IO.FileAttributes'='System.IO.FileAttributes'; 'Text.Encoding'='System.Text.Encoding'
            'StringComparison'='System.StringComparison'; 'Environment'='System.Environment'
            'Activator'='System.Activator'; 'Type'='System.Type'; 'Net.WebRequest'='System.Net.WebRequest'
            'IO.StreamReader'='System.IO.StreamReader'; 'regex'='System.Text.RegularExpressions.Regex'
        }
        if ($aliases.ContainsKey($name)) { return $aliases[$name] }
        $name
    }

    function Assert-PositiveHelperGrammar([string] $Path) {
        $ast = Get-Ast $Path
        $allowed = @('Get-ItemProperty','Get-Item','Get-ChildItem','Test-Path','Join-Path',
            'Split-Path','Get-FileHash','ConvertTo-Json','Where-Object','Sort-Object',
            'Select-Object','ForEach-Object','Write-Output')
        $defined = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] }, $true) | ForEach-Object Name)
        foreach ($command in @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] }, $true))) {
            $name = $command.GetCommandName()
            if ($command.InvocationOperator -ne [Management.Automation.Language.TokenKind]::Unknown) {
                throw "Invocation operator is not allowed: $($command.Extent.Text)"
            }
            if ($name -notin $allowed -and $name -notin $defined) { throw "Unknown helper command: $name" }
        }
        if (@($ast.FindAll({ param($n) $n -is [Management.Automation.Language.RedirectionAst] }, $true)).Count) {
            throw 'Redirection is not allowed.'
        }
        foreach ($member in @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.InvokeMemberExpressionAst] }, $true))) {
            $memberName = [string]$member.Member.Value
            if ($member.Expression -is [Management.Automation.Language.TypeExpressionAst]) {
                $typeName = Get-HelperTypeName $member.Expression
                if (-not @($script:HelperStaticMemberAllowlist | Where-Object { $_.Type -eq $typeName -and $_.Member -eq $memberName }).Count) {
                    throw "Unapproved static member: [$typeName]::$memberName"
                }
            } else {
                $receiver = $member.Expression.Extent.Text -replace '^\$', ''
                if ($member.Member.Value -in @('Trim','TrimEnd','ToLowerInvariant','Replace','OpenSubKey','GetBytes') -and
                    $member.Expression.Extent.Text -match '(?:::\w+|\)\.?\w+|\.Hash$|GetValue\(|GetFullPath\(|GetFileHash\(|Match\()') { continue }
                if (-not $script:HelperInstanceMemberAllowlist.ContainsKey($receiver) -or
                    $memberName -notin $script:HelperInstanceMemberAllowlist[$receiver]) {
                    throw "Unapproved instance member: $($member.Extent.Text)"
                }
            }
        }
        foreach ($member in @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.MemberExpressionAst] }, $true))) {
            if ($member.Parent -is [Management.Automation.Language.InvokeMemberExpressionAst]) { continue }
            if ($member.Expression -is [Management.Automation.Language.TypeExpressionAst]) {
                $typeName = Get-HelperTypeName $member.Expression
                if (-not @($script:HelperStaticMemberAllowlist | Where-Object { $_.Type -eq $typeName -and $_.Member -eq [string]$member.Member.Value }).Count) {
                    throw "Unapproved static member: [$typeName]::$($member.Member.Value)"
                }
            } else {
                $receiver = $member.Expression.Extent.Text -replace '^\$', ''
                if ($member.Member.Value -in @('Trim','TrimEnd','ToLowerInvariant','Replace','OpenSubKey','GetBytes') -and
                    $member.Expression.Extent.Text -match '(?:::\w+|\)\.?\w+|\.Hash$|GetValue\(|GetFullPath\(|GetFileHash\(|Match\()') { continue }
                if (-not $script:HelperInstanceMemberAllowlist.ContainsKey($receiver) -or
                    $member.Member.Value -notin $script:HelperInstanceMemberAllowlist[$receiver]) {
                    throw "Unapproved instance property: $($member.Extent.Text)"
                }
            }
        }
        foreach ($assignment in @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] }, $true))) {
            if ($assignment.Left -is [Management.Automation.Language.MemberExpressionAst]) { throw 'Member assignment is not allowed.' }
        }
        $source = Get-Content $Path -Raw
        if ($source -match '(?i)AllowedOutRoot|GITHUB_WORKSPACE|\.\s*\(\s*\$|::\s*\$') { throw 'Unapproved output root or dynamic member call.' }
        if (($source | Select-String -Pattern 'WriteAllText' -AllMatches).Matches.Count -ne 1) {
            throw 'Exactly one writer call is required.'
        }
        if ($source -notmatch 'RUNNER_TEMP' -or $source -notmatch 'GetTempPath') { throw 'Unsafe output roots.' }
        if ($source -notmatch 'leaf\.Exists.*ReparsePoint' -or $source -notmatch 'parent must already exist') {
            throw 'Fresh-leaf and parent hardening is required.'
        }
        $true
    }

    function Remove-ScratchHive([string] $Guid) {
        try {
            $parent = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\SnapmakerStudioCiAssertTest', $true)
            if ($parent) {
                try { $parent.DeleteSubKeyTree($Guid, $false) } catch { }
                $empty = $parent.SubKeyCount -eq 0 -and $parent.ValueCount -eq 0
                $parent.Dispose()
                if ($empty) {
                    $software = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software', $true)
                    if ($software) { try { $software.DeleteSubKey('SnapmakerStudioCiAssertTest', $false) } catch { }; $software.Dispose() }
                }
            }
        } catch { }
    }

    function Set-RegistryFixture([string] $Guid, [string] $Dir, [hashtable] $Options = @{}) {
        $base = "Software\SnapmakerStudioCiAssertTest\$Guid"
        $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("$base\Microsoft\Windows\CurrentVersion\Uninstall\Snapmaker Studio")
        $key.SetValue('InstallLocation', $(if ($Options.ContainsKey('InstallLocation')) { $Options.InstallLocation } else { $Dir }))
        $key.Dispose()
        $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("$base\DeadlyVirusIn / Snapmaker Studio\Snapmaker Studio")
        $key.SetValue('', $(if ($Options.ContainsKey('RememberedLocation')) { $Options.RememberedLocation } else { $Dir })); $key.Dispose()
        $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("$base\DeadlyVirusIn / Snapmaker Studio"); $key.Dispose()
        if ($Options.ContainsKey('Run') -and $Options.Run) {
            $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("$base\Microsoft\Windows\CurrentVersion\Run")
            $key.SetValue('Snapmaker Studio', 'bad'); $key.Dispose()
        }
    }

    function Assert-HelperFixture([string] $Path, [string] $Name) {
        Assert-PositiveHelperGrammar $Path | Should -BeTrue
        (Get-WriterHash $Path) | Should -Be $writerPins[$Name]
    }
}

AfterAll {
    if (Test-Path $fixtureRoot) { Remove-Item $fixtureRoot -Recurse -Force }
}

Describe 'CI assertion helper design and behavior' {
    It 'uses a closed grammar and a literal pinned writer for all helpers' {
        foreach ($path in Get-ChildItem $scriptDir -Filter 'ci-assert-*.ps1' -File) {
            Assert-PositiveHelperGrammar $path.FullName | Should -BeTrue
            Assert-HelperFixture $path.FullName $path.Name
        }
    }

    It 'writes a fresh OutFile end to end for every output helper' {
        $disk = Join-Path $fixtureRoot 'install'; New-Item -ItemType Directory -Force $disk | Out-Null
        Set-Content (Join-Path $disk 'a.txt') 'fixture'; $env:RUNNER_TEMP = $fixtureRoot
        $cases = @(
            @{ Path='ci-assert-manifest.ps1'; Args=@{ InstallDir=$disk; OutFile=(Join-Path $fixtureRoot 'manifest.json') } }
            @{ Path='ci-assert-registry.ps1'; Args=@{ Action='Report'; RegistryRoot='HKCU:\Software\MissingCiAssert'; InstallDir=$disk; OutFile=(Join-Path $fixtureRoot 'registry.json') } }
            @{ Path='ci-assert-shortcuts.ps1'; Args=@{ Action='AssertAbsent'; StartMenuDir=$fixtureRoot; DesktopDir=$fixtureRoot; OutFile=(Join-Path $fixtureRoot 'shortcuts.json') } }
        )
        foreach ($case in $cases) {
            $argsForCall = $case.Args
            $Path = Join-Path $scriptDir $case.Path
            { & $Path @argsForCall } | Should -Not -Throw
            Test-Path $case.Args.OutFile | Should -BeTrue
        }
    }

    It 'checks exact scratch-hive registration states and preserves remembered location after uninstall' {
        $guid = [guid]::NewGuid().ToString(); $dir = Join-Path $fixtureRoot 'owned'; New-Item -ItemType Directory $dir | Out-Null
        $root = "HKCU:\Software\SnapmakerStudioCiAssertTest\$guid"
        try {
            try { Set-RegistryFixture $guid $dir } catch [System.UnauthorizedAccessException],[System.Security.SecurityException] { Set-ItResult -Skipped -Because $_.Exception.Message; return }
            . (Join-Path $scriptDir 'ci-assert-registry.ps1')
            { Assert-CiRegistryState $root $dir } | Should -Not -Throw
            Set-RegistryFixture $guid $dir @{ InstallLocation=(Join-Path $fixtureRoot 'wrong') }
            { Assert-CiRegistryState $root $dir } | Should -Throw
            Set-RegistryFixture $guid $dir @{ RememberedLocation=(Join-Path $fixtureRoot 'wrong') }
            { Assert-CiRegistryState $root $dir } | Should -Throw
            Set-RegistryFixture $guid $dir @{ Run=$true }
            { Assert-CiRegistryState $root $dir } | Should -Throw
            Remove-ScratchHive $guid
            { Assert-CiRegistryState $root $dir } | Should -Throw
            Set-RegistryFixture $guid $dir
            Remove-ScratchHive $guid
            $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("Software\SnapmakerStudioCiAssertTest\$guid\DeadlyVirusIn / Snapmaker Studio\Snapmaker Studio")
            $key.SetValue('', $dir); $key.Dispose()
            Remove-Item $dir -Recurse -Force
            { Assert-CiRegistryState $root $dir -AfterUninstall } | Should -Not -Throw
        } finally { Remove-ScratchHive $guid }
    }

    It 'checks sorted manifests and compares synthetic SHA256SUMS offline' {
        $disk = Join-Path $fixtureRoot 'sorted'; New-Item -ItemType Directory -Force $disk | Out-Null
        Set-Content (Join-Path $disk 'z.txt') 'z'; Set-Content (Join-Path $disk 'a.txt') 'a'
        . (Join-Path $scriptDir 'ci-assert-manifest.ps1')
        $items = @(Get-CiInstalledTreeManifest $disk); @($items.Path) | Should -Be @('a.txt','z.txt')
        . (Join-Path $scriptDir 'ci-assert-sha256sums.ps1')
        $file = Join-Path $disk 'a.txt'; $hash = (Get-FileHash $file -Algorithm SHA256).Hash.ToLowerInvariant()
        { Compare-CiSha256Sums "$hash *a.txt`n" $file } | Should -Not -Throw
        { Compare-CiSha256Sums (('0' * 64) + ' *a.txt') $file } | Should -Throw
    }

    It 'checks AUMID bytes, target-only links, and AssertAbsent mode' {
        $good = Join-Path $fixtureRoot 'good.lnk'; $bad = Join-Path $fixtureRoot 'bad.lnk'
        [IO.File]::WriteAllBytes($good, [Text.Encoding]::Unicode.GetBytes('com.snapmakerstudio.desktop'))
        [IO.File]::WriteAllBytes($bad, [Text.Encoding]::Unicode.GetBytes('other'))
        (Test-CiShortcutAumid $good 'com.snapmakerstudio.desktop') | Should -BeTrue
        (Test-CiShortcutAumid $bad 'com.snapmakerstudio.desktop') | Should -BeFalse
        $shell = [Activator]::CreateInstance([Type]::GetTypeFromProgID('WScript.Shell'))
        $targetOnly = Join-Path $fixtureRoot 'target-only.lnk'; $link = $shell.CreateShortcut($targetOnly)
        $link.TargetPath = (Join-Path $fixtureRoot 'app.exe'); $link.Save()
        (Test-CiShortcutAumid $targetOnly 'com.snapmakerstudio.desktop') | Should -BeFalse
        { Assert-CiShortcutsAbsent $fixtureRoot $fixtureRoot } | Should -Not -Throw
        New-Item (Join-Path $fixtureRoot 'Snapmaker Studio.lnk') -ItemType File | Out-Null
        { Assert-CiShortcutsAbsent $fixtureRoot $fixtureRoot } | Should -Throw
    }

    It 'asserts guaranteed /S shortcut fixtures and reports invocation-dependent desktop state' {
        $start = Join-Path $fixtureRoot 'Programs'; $desktop = Join-Path $fixtureRoot 'Desktop'; $disk = Join-Path $fixtureRoot 'app'
        New-Item -ItemType Directory -Force $start,$desktop,$disk | Out-Null
        $target = Join-Path $disk 'snapmaker-studio-desktop.exe'; Set-Content $target 'fixture'
        $aumid = 'com.snapmakerstudio.desktop'
        function New-LinkFixture([string]$Path,[string]$Target,[bool]$WithAumid) {
            $shell = [Activator]::CreateInstance([Type]::GetTypeFromProgID('WScript.Shell'))
            $link = $shell.CreateShortcut($Path); $link.TargetPath = $Target; $link.Save()
            if ($WithAumid) { [IO.File]::AppendAllText($Path, $aumid, [Text.Encoding]::Unicode) }
        }
        New-LinkFixture (Join-Path $start 'Snapmaker Studio.lnk') $target $true
        New-LinkFixture (Join-Path $desktop 'Snapmaker Studio.lnk') $target $true
        { Assert-CiShortcuts $start $desktop $disk $aumid } | Should -Not -Throw
        Remove-Item (Join-Path $start 'Snapmaker Studio.lnk')
        { Assert-CiShortcuts $start $desktop $disk $aumid } | Should -Throw
        New-LinkFixture (Join-Path $start 'Snapmaker Studio.lnk') (Join-Path $disk 'wrong.exe') $true
        { Assert-CiShortcuts $start $desktop $disk $aumid } | Should -Throw
        New-LinkFixture (Join-Path $start 'Snapmaker Studio.lnk') $target $false
        { Assert-CiShortcuts $start $desktop $disk $aumid } | Should -Throw
        Remove-Item (Join-Path $desktop 'Snapmaker Studio.lnk')
        $optional = Read-CiShortcut (Join-Path $desktop 'Snapmaker Studio.lnk') $target $aumid
        $optional.Present | Should -BeFalse
        New-LinkFixture (Join-Path $desktop 'Snapmaker Studio.lnk') $target $true
        (Read-CiShortcut (Join-Path $desktop 'Snapmaker Studio.lnk') $target $aumid).TargetMatches | Should -BeTrue
    }

    It 'rejects alternate data streams after the drive colon in every writer' {
        $env:RUNNER_TEMP = $fixtureRoot
        $streamPath = Join-Path $fixtureRoot 'file.json:stream'
        foreach ($name in @('ci-assert-manifest.ps1','ci-assert-registry.ps1','ci-assert-sha256sums.ps1','ci-assert-shortcuts.ps1')) {
            . (Join-Path $scriptDir $name)
            { Write-CiAssertOutput ([pscustomobject]@{ Fixture = $true }) $streamPath } | Should -Throw -Because $name
        }
    }

    It 'rejects every requested mutation from a passing copy of every helper' {
        $mutations = @(
            @{ Name='primitive'; Text='ni x' }
            @{ Name='writer one byte'; Text='__WRITER_BYTE__' }
            @{ Name='AllowedOutRoot'; Text='param([string] $AllowedOutRoot)' }
            @{ Name='dynamic member'; Text='$o.($name)' }
            @{ Name='dynamic static member'; Text='[type]::$member' }
            @{ Name='dynamic method'; Text='$o.($method)()' }
            @{ Name='redirection'; Text='> out.txt' }
        )
        foreach ($sourcePath in Get-ChildItem $scriptDir -Filter 'ci-assert-*.ps1' -File) {
            $source = Get-Content $sourcePath.FullName -Raw
            foreach ($mutation in $mutations) {
                $candidate = if ($mutation.Name -eq 'writer one byte') {
                    $source.Replace('ConvertTo-Json', 'ConvertTo-JsoN')
                } else { $source + "`n$($mutation.Text)`n" }
                $path = Join-Path $fixtureRoot "$($sourcePath.BaseName)-$([guid]::NewGuid()).ps1"
                Set-Content $path $candidate
                { Assert-HelperFixture $sourcePath.FullName $sourcePath.Name } | Should -Not -Throw
                { Assert-HelperFixture $path $sourcePath.Name } | Should -Throw -Because "$($sourcePath.Name): $($mutation.Name)"
                Remove-Item $path -Force
            }
        }
    }

    It 'rejects every unlisted static call, instance call, and member assignment' {
        $negative = @(
            '[IO.File]::Delete($path)'
            '[System.IO.File]::Delete($path)'
            '[IO.Directory]::Delete($path)'
            '[IO.File]::WriteAllBytes($path, [byte[]]@())'
            '[IO.File]::AppendAllText($path, $text)'
            '[IO.File]::Move($a, $b)'
            '[IO.File]::Copy($a, $b)'
            '[IO.File]::Open($path, 0)'
            '[Diagnostics.Process]::Start($path)'
            '$p.Start()'
            '$o.Remove($name)'
            '$k.DeleteValue($name)'
            '$k.DeleteSubKey($name)'
            '$k.DeleteSubKeyTree($name)'
            '$k.SetValue($name, $value)'
            '[Microsoft.Win32.Registry]::SetValue($name, $value)'
            '[Environment]::SetEnvironmentVariable($name, $value, [EnvironmentVariableTarget]::User)'
            '$link.TargetPath = $path'
            '$link.Save()'
        )
        $sourcePath = Join-Path $scriptDir 'ci-assert-manifest.ps1'
        $source = Get-Content $sourcePath -Raw
        foreach ($snippet in $negative) {
            $path = Join-Path $fixtureRoot "negative-$([guid]::NewGuid()).ps1"
            Set-Content -LiteralPath $path -Value ($source + "`n" + $snippet)
            try { { Assert-PositiveHelperGrammar $path } | Should -Throw -Because $snippet } finally { Remove-Item -LiteralPath $path -Force }
        }
    }
}
