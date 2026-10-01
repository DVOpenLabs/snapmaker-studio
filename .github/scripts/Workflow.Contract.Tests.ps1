<#
Workflow-shape and regression checks (an accident control); whole-file pins are the review gate.
The YAML parser is minimal. Runner-identity environment variables (runneradmin,
RUNNER_ENVIRONMENT, ImageOS) and the AUMID check are verified at the first dry CI run.
Actions are tag-pinned; CDP is unproven. The real protection is the Task A InstallGuard,
journal and identity, the Task B attested acceptance-identity rewrap, the Task C guarded
harnesses, and real production-identity install, upgrade and uninstall limited to disposable CI.
#>

BeforeAll {
    $pwsh = (Get-Command pwsh -CommandType Application -ErrorAction Stop).Source
    $workflowPreflight = @"
if (`$env:GITHUB_ACTIONS -ne 'true' -or `$env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or [string]::IsNullOrWhiteSpace(`$env:ImageOS) -or `$env:GITHUB_REPOSITORY -ne 'DVOpenLabs/snapmaker-studio' ``
-or `$env:ACT -or `$env:WDAGUtilityAccount) { throw 'Disposable preflight failed.' }
"@.TrimEnd()


    function Replace-First([string] $Text, [string] $Old, [string] $New) {
        $index = $Text.IndexOf($Old, [StringComparison]::Ordinal)
        if ($index -lt 0) { throw "Mutation needle not found: $Old" }
        $Text.Substring(0, $index) + $New + $Text.Substring($index + $Old.Length)
    }

    function Get-WorkflowRunTexts {
        param([string] $Path)
        $lines = @(Get-Content -LiteralPath $Path); $steps = [Collections.Generic.List[object]]::new(); $pendingName = ''
        for ($index = 0; $index -lt $lines.Count; $index++) {
            $line = $lines[$index]
            if ($line -match '^\s*- name:\s*(?<name>.+?)\s*$') { $pendingName = $matches.name.Trim(); continue }
            if ($line -notmatch '^(?<indent>\s*)(?:-\s+)?run:\s*(?<value>.*)$') { continue }
            $indent = $matches.indent.Length; if ($indent -lt 6) { continue }
            $value = $matches.value; $text = $value.Trim()
            if ($value -match '^[|>]') {
                $body = [Collections.Generic.List[string]]::new(); $bodyIndent = $null
                for ($next = $index + 1; $next -lt $lines.Count; $next++) {
                    if ($lines[$next] -match '^\s*$') { [void] $body.Add(''); continue }
                    $bodyIndent = $lines[$next].Length - $lines[$next].TrimStart().Length
                    if ($bodyIndent -le $indent) { break }
                    if ($null -eq $bodyIndent) { $bodyIndent = ($lines[$next] -replace '^\s*').Length }
                    [void] $body.Add($lines[$next].Substring([Math]::Min($bodyIndent, $lines[$next].Length))); $index = $next
                }
                $text = $body -join "`n"
            }
            [void] $steps.Add([pscustomobject] @{ Name = $pendingName; Text = $text })
            if ($line -match '^\s*-\s+run:') { $pendingName = '' }
        }
        $steps
    }

    function Assert-WorkflowRunExpressions {
        param([string] $Path)
        $safe = @('runner.temp', 'github.workspace', 'github.repository')
        foreach ($step in Get-WorkflowRunTexts $Path) {
            foreach ($match in [regex]::Matches($step.Text, '\$\{\{.*?\}\}')) {
                $expression = $match.Value -replace '^\$\{\{\s*|\s*\}\}$', ''
                if ($expression -notin $safe) { throw "Unsafe workflow run expression $($match.Value) in $($step.Name)." }
            }
        }
    }

    function Assert-WorkflowShape {
        param([string] $Path)

        $raw = Get-Content -LiteralPath $Path -Raw
        if ($raw -match '(?im)^\s*permissions:\s*write-all\s*(?:#.*)?$' -or
            $raw -match '(?im)^\s*actions:\s*write\s*(?:#.*)?$' -or
            $raw -match '(?im)^\s*contents:\s*["'']?write["'']?\s*(?:#.*)?$') {
            throw 'Workflow permissions are writable.'
        }
        if ($raw -match '(?im)^\s{4}if:\s*.*always\s*\(\s*\)' -or
            $raw -match '(?i)always\s*\(\s*\)\s*&&\s*true' -or
            $raw -match '(?i)runs-on:\s*.*self-hosted') {
            throw 'Unsafe workflow scheduling condition or runner.'
        }
        foreach ($job in @('real-identity', 'windows-upgrade-smoke')) {
            if ($raw -match "(?ms)^  ${job}:\s*`n(?<body>.*?)(?=^  \S|\z)") {
                if ($matches.body -notmatch "(?m)^    if: github\.repository == 'DVOpenLabs/snapmaker-studio'\s*$") {
                    throw "Destructive job $job has no exact repository guard."
                }
            }
        }
    }

    function Assert-WorkflowNativeExitChecks {
        param([string] $Path)
        foreach ($step in Get-WorkflowRunTexts $Path) {
            if ($step.Text -match '(?im)(?<!-NoProfile\s)pwsh\s+-File\s+\.github/scripts/ci-assert-') {
                throw "Non-canonical helper invocation in $($step.Name)."
            }
            $calls = @([regex]::Matches($step.Text, '(?im)(?:^|;)\s*(?:gh\s+|pwsh\s+-NoProfile\s+-File\s+)'))
            if (-not $calls.Count) { continue }
            $checks = @([regex]::Matches($step.Text, '(?i)\$LASTEXITCODE\s*-ne\s*0'))
            $checks.Count | Should -Be $calls.Count -Because "$Path step $($step.Name) native call/check count"
            for ($index = 0; $index -lt $calls.Count; $index++) {
                $start = $calls[$index].Index
                $end = if ($index + 1 -lt $calls.Count) { $calls[$index + 1].Index } else { $step.Text.Length }
                $bodyAfterCall = $step.Text.Substring($start, $end - $start)
                $bodyAfterCall | Should -Match '\$LASTEXITCODE\s*-ne\s*0' -Because "$Path step $($step.Name) native call $($index + 1)"
                if ($bodyAfterCall -match '(?is)\$LASTEXITCODE\s*-ne\s*0\s*\)\s*\{(?<body>.*?)\}') {
                    $matches.body | Should -Match '(?i)\bthrow\b' -Because "$Path step $($step.Name) exit check must throw"
                }
            }
        }
    }

    function Assert-WorkflowMutatingPreflights {
        param([string] $Path, [ValidateSet('InstallerSmoke','ReleaseCandidate')][string] $Kind)
        $names = if ($Kind -eq 'InstallerSmoke') {
            @('Download target installer and verify live SHA256SUMS', 'Download previous installer and verify live SHA256SUMS',
                'Preflight and install previous release at the exact default path', 'Assert previous install exact surfaces',
                'Preflight and upgrade target in place', 'Assert target shortcuts and capture installed-tree manifest',
                'Preflight and launch smoke without CDP', 'Preflight and uninstall only the recorded owned path', 'Report final registry state')
        } else {
            @('Download the published v1.1.0 installer, verify its checksum', 'Install v1.1.0 (default path), record its registration',
                'Assert previous install shortcuts', 'Install the release candidate over it (default path, same key)',
                'Capture release-candidate installed-tree manifest', 'Uninstall, verify the machine is clean')
        }
        foreach ($name in $names) {
            $step = @(Get-WorkflowRunTexts $Path | Where-Object { $_.Name -eq $name })
            $step.Count | Should -Be 1 -Because "$Path preflight step $name exists"
            $text = [string]$step[0].Text
            $preflightPattern = [regex]::Escape($workflowPreflight)
            $text | Should -Match $preflightPattern -Because "$Path step $name has the pinned preflight"
            $firstCode = @($text -split "`n" | Where-Object { $_.Trim() -and $_.Trim() -notmatch '^\$ErrorActionPreference' })[0].Trim()
            $firstCode | Should -Be (($workflowPreflight -split "`n")[0]) -Because "$Path step $name starts with the pinned preflight"
        }
    }

    $script:WorkflowStepNames = @{
        InstallerSmoke = @{
            'real-identity' = @('Check out helper scripts','Download target installer and verify live SHA256SUMS','Download previous installer and verify live SHA256SUMS',
                'Preflight and install previous release at the exact default path','Assert previous install exact surfaces','Preflight and upgrade target in place',
                'Assert target shortcuts and capture installed-tree manifest','Upload installed-tree reference manifest','Preflight and launch smoke without CDP',
                'Preflight and uninstall only the recorded owned path','Report final registry state')
        }
        ReleaseCandidate = @{
            'windows-upgrade-smoke' = @('Check out helper scripts','Download the release-candidate installer',
                'Download the published v1.1.0 installer, verify its checksum','Install v1.1.0 (default path), record its registration',
                'Assert previous install shortcuts','Install the release candidate over it (default path, same key)',
                'Capture release-candidate installed-tree manifest','Upload release-candidate installed-tree manifest','Uninstall, verify the machine is clean')
            'manifest' = @('Write the manifest','Upload the manifest')
        }
    }
    $script:WorkflowPins = @{
        'installer-smoke.yml' = '64650bfa07b00c48c7ac94abcd28a5444390c175082f56a5ab6cb17cd6002d04'
        'release-candidate.yml' = '5fa258ea21ae34d794bd2bdf203cb0255340102ee01292274c7ee09ec7223040'
    }

    function Get-WorkflowJobBlocks([string] $Path) {
        $lines = @(Get-Content -LiteralPath $Path)
        $jobsLine = @($lines | Select-String -Pattern '^jobs:\s*$').LineNumber
        if ($jobsLine.Count -ne 1) { throw 'Workflow must have exactly one jobs map.' }
        $result = [ordered]@{}
        $current = $null; $body = [Collections.Generic.List[string]]::new()
        foreach ($line in $lines[($jobsLine[0])..($lines.Count - 1)]) {
            if ($line -match '^  (?<job>[A-Za-z0-9_-]+):\s*(?:#.*)?$') {
                if ($current) { $result[$current] = @($body); $body = [Collections.Generic.List[string]]::new() }
                $current = $matches.job; continue
            }
            if ($current) { [void]$body.Add($line) }
        }
        if ($current) { $result[$current] = @($body) }
        $result
    }

    function Get-YamlMapAtIndent([string[]] $Lines, [int] $Indent, [string] $Key) {
        $index = 0; $map = [ordered]@{}
        while ($index -lt $Lines.Count) {
            $prefix = (' ' * $Indent)
            $mapPattern = '^' + [regex]::Escape($prefix) + [regex]::Escape($Key) + ':\s*(?:#.*)?$'
            if ($Lines[$index] -match $mapPattern) {
                $index++
                while ($index -lt $Lines.Count -and ($Lines[$index].Trim() -eq '' -or
                        $Lines[$index].Length - $Lines[$index].TrimStart().Length -gt $Indent)) {
                    $entryPrefix = (' ' * ($Indent + 2))
                    $entryPattern = '^' + [regex]::Escape($entryPrefix) + '(?<name>[^:#]+):\s*(?<value>[^#]*?)(?:\s+#.*)?$'
                    if ($Lines[$index] -match $entryPattern) {
                        $map[$matches.name.Trim()] = $matches.value.Trim().Trim([char]39, [char]34)
                    }
                    $index++
                }
                return $map
            }
            $index++
        }
        $null
    }

    function Assert-WorkflowStructuralContract([string] $Path, [ValidateSet('InstallerSmoke','ReleaseCandidate')][string] $Kind) {
        $raw = Get-Content -LiteralPath $Path -Raw; $lines = @(Get-Content -LiteralPath $Path)
        $expectedTrigger = if ($Kind -eq 'InstallerSmoke') { 'workflow_call' } else { 'workflow_dispatch' }
        $triggerPattern = '(?m)^  ' + [regex]::Escape($expectedTrigger) + ':\s*(?:\{\})?\s*$'
        if ($raw -notmatch '(?m)^on:\s*$' -or $raw -notmatch $triggerPattern) { throw "trigger must be exactly $expectedTrigger" }
        foreach ($trigger in @('pull_request_target','pull_request','push','schedule','workflow_dispatch','workflow_call')) {
            $unexpectedPattern = '(?m)^  ' + [regex]::Escape($trigger) + ':\s*'
            if ($trigger -ne $expectedTrigger -and $raw -match $unexpectedPattern) { throw "unexpected trigger $trigger" }
        }
        foreach ($mapOwner in @(@{Indent=0;Key='permissions'}, @{Indent=4;Key='permissions'})) {
            $map = Get-YamlMapAtIndent $lines $mapOwner.Indent $mapOwner.Key
            if ($map) {
                if ($map.Count -ne 1 -or $map['contents'] -ne 'read') { throw "permissions map is not exactly contents: read" }
            }
        }
        $blocks = Get-WorkflowJobBlocks $Path
        if ($raw -match '(?m)^\s*permissions:\s*\{') { throw 'flow-style permissions are not accepted without exact map equality' }
        $expectedJobs = if ($Kind -eq 'InstallerSmoke') { @('real-identity') } else { @('windows','linux','windows-upgrade-smoke','manifest') }
        if ((@($blocks.Keys) -join "`n") -cne ($expectedJobs -join "`n")) { throw 'job list changed or contains an unguarded extra job' }
        foreach ($job in $blocks.Keys) {
            $body = @($blocks[$job]); $perm = Get-YamlMapAtIndent $body 4 'permissions'
            if ($null -eq $perm -or $perm.Count -ne 1 -or $perm['contents'] -ne 'read') { throw "job $job permissions must equal contents: read" }
            if ($body -match '(?m)^    (?:continue-on-error|if):\s*(?:true|false)\s*$' -or
                $body -match '(?m)^      (?:continue-on-error|if):\s*(?:true|false)\s*$' -or
                $body -match '(?m)^        (?:continue-on-error|if):\s*(?:true|false)\s*$') { throw "job $job has unsafe continue-on-error/if" }
            $stepNames = [Collections.Generic.List[string]]::new(); $stepStart = -1
            for ($lineIndex = 0; $lineIndex -lt $body.Count; $lineIndex++) {
                $line = $body[$lineIndex]
                if ($line -match '^      - run:') { throw "job $job has unnamed run step" }
                if ($line -match '^      - name:\s*(?<name>.+?)\s*$') {
                    if ($stepStart -ge 0) {
                        $step = @($body[$stepStart..($lineIndex - 1)])
                        if (@($step | Where-Object { $_ -match '^        run:' }).Count -and
                            -not @($step | Where-Object { $_ -match '^        shell:\s*\S+' }).Count) {
                            throw "job $job run step has no explicit shell"
                        }
                    }
                    $stepName = [regex]::Match($line, '^      - name:\s*(?<name>.+?)\s*$').Groups['name'].Value.Trim()
                    $stepStart = $lineIndex; [void]$stepNames.Add($stepName)
                }
            }
            if ($stepStart -ge 0) {
                $step = @($body[$stepStart..($body.Count - 1)])
                if (@($step | Where-Object { $_ -match '^        run:' }).Count -and
                    -not @($step | Where-Object { $_ -match '^        shell:\s*\S+' }).Count) {
                    throw "job $job run step has no explicit shell"
                }
            }
            if ($stepNames.Count -ne @($stepNames | Select-Object -Unique).Count) { throw "job $job has duplicate step names" }
            if ($raw -match '(?m)^\s*permissions:\s*\{') { throw 'flow-style permissions' }
            if ($script:WorkflowStepNames[$Kind].ContainsKey($job)) {
                $expected = @($script:WorkflowStepNames[$Kind][$job])
                if (($stepNames -join "`n") -cne ($expected -join "`n")) { throw "step list changed for job $job" }
            } elseif ($stepNames.Count) { throw "unexpected job steps for $job" }
        }
        if ($Kind -eq 'ReleaseCandidate') {
            $manifest = @($blocks['manifest']) -join "`n"
            if ($manifest -notmatch '(?m)^    needs:\s*\[(?<needs>[^]]+)\]\s*$') { throw 'manifest dependency rule is missing' }
            $manifestNeeds = @($matches.needs -split ',' | ForEach-Object Trim | Where-Object { $_ }) | Sort-Object
            if (($manifestNeeds -join ',') -cne 'linux,windows,windows-upgrade-smoke') { throw 'manifest dependency rule must be exactly windows, linux, windows-upgrade-smoke' }
            if ($manifest -notmatch '(?m)^    runs-on:\s*ubuntu-latest\s*$') { throw 'manifest runs-on must be ubuntu-latest' }
            $manifestStep = [regex]::Match($manifest, '(?ms)^      - name: Write the manifest\r?\n.*?(?=^      - name:|\z)').Value
            if (-not $manifestStep) { throw 'manifest Write the manifest step is missing' }
            if ($manifestStep -notmatch '(?m)^        shell:\s*pwsh\s*$') { throw 'manifest step shell must be pwsh' }
            if ($manifestStep -notmatch '(?i)Tee-Object\s+-FilePath\s+RELEASE_CANDIDATE\.txt') { throw 'manifest output file rule requires Tee-Object RELEASE_CANDIDATE.txt' }
            $upgrade = @($blocks['windows-upgrade-smoke']) -join "`n"
            if ($upgrade -notmatch '(?m)^    needs:\s*windows\s*$') { throw 'windows-upgrade-smoke dependency rule requires windows' }
            if ($raw -notmatch '(?m)^          EXPECTED_RC_SHA256: \$\{\{ needs\.windows\.outputs\.installer_sha256 \}\}') { throw 'RC output wiring changed' }
            if ($raw -notmatch 'b41931774eac5586bc31746599d4a637e89eda195c620067dc1c756281b217ee') { throw 'published v1.1.0 hash changed' }
            $installBlock = [regex]::Match($upgrade, '(?ms)^      - name: Install the release candidate over it \(default path, same key\).*?(?=^      - name:|\z)').Value
            if ($installBlock -notmatch '(?m)^        shell:\s*pwsh\s*$') { throw 'RC install step shell changed' }
        }
    }

    function Assert-WorkflowContract {
        param([string] $Path, [ValidateSet('InstallerSmoke','ReleaseCandidate')][string] $Kind,
            [switch] $SkipHash)
        $raw = Get-Content -LiteralPath $Path -Raw
        Assert-WorkflowStructuralContract $Path $Kind
        if (-not $SkipHash -and $script:WorkflowPins.ContainsKey([IO.Path]::GetFileName($Path))) {
            $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actual -ne $script:WorkflowPins[[IO.Path]::GetFileName($Path)]) { throw "workflow whole-file SHA256 pin mismatch: $actual" }
        }
        Assert-WorkflowShape $Path
        Assert-WorkflowRunExpressions $Path
        Assert-WorkflowAssetPatterns $Path
        if ($raw -match '(?m)^\s*&\s*\$[A-Za-z_]') { throw 'Unnamed variable step detected.' }
        if ($raw -notmatch '(?m)^\s+runs-on:\s*windows-latest\s*$') { throw 'Runner pin changed.' }
        $expectedUses = if ($Kind -eq 'InstallerSmoke') {
            @('actions/checkout@v4', 'actions/upload-artifact@v4')
        } else {
            @('./.github/workflows/release.yml', './.github/workflows/release-linux.yml',
                'actions/checkout@v4', 'actions/download-artifact@v4', 'actions/upload-artifact@v4')
        }
        foreach ($use in $expectedUses) { if ($raw -notmatch [regex]::Escape("uses: $use")) { throw "Action ref changed: $use" } }
        $steps = @(Get-WorkflowRunTexts $Path)
        $stepCount = @(Get-Content -LiteralPath $Path | Where-Object { $_ -match '^      - name:' }).Count
        if ($stepCount -ne 11) { throw "Workflow step count changed: $stepCount" }
        $destructive = if ($Kind -eq 'InstallerSmoke') {
            @('Preflight and install previous release at the exact default path', 'Preflight and upgrade target in place',
                'Preflight and launch smoke without CDP', 'Preflight and uninstall only the recorded owned path')
        } else {
            @('Install v1.1.0 (default path), record its registration', 'Install the release candidate over it (default path, same key)',
                'Uninstall, verify the machine is clean')
        }
        foreach ($name in $destructive) {
            $step = @($steps | Where-Object Name -eq $name)
            if ($step.Count -ne 1) { throw "Destructive step missing: $name" }
        }
        if ([regex]::Matches($raw, 'Disposable preflight').Count -lt $destructive.Count) {
            throw 'Preflight guard count changed.'
        }
        $workflowLines = @(Get-Content -LiteralPath $Path)
        for ($i = 0; $i -lt $workflowLines.Count; $i++) {
            if ($workflowLines[$i] -match '(?i)pwsh\s+-File\s+\.github/scripts/ci-assert-' -and
                $workflowLines[$i] -notmatch '(?i)-NoProfile\s+-File\s+\.github/scripts/ci-assert-') {
                throw 'Non-canonical helper call is missing -NoProfile.'
            }
            if ($workflowLines[$i] -match 'pwsh -NoProfile -File \.github/scripts/ci-assert-') {
                $checked = $false
                for ($j = $i; $j -lt [Math]::Min($i + 8, $workflowLines.Count); $j++) {
                    if ($workflowLines[$j] -match 'LASTEXITCODE') { $checked = $true; break }
                }
                if (-not $checked) { throw 'Helper call is missing its exit-code check.' }
            }
        }
        $expectedLines = if ($Kind -eq 'InstallerSmoke') {
            @('$p=Start-Process -FilePath $env:PREVIOUS_INSTALLER -ArgumentList ''/S'',''/NCRC'' -PassThru -Wait;',
                '$p=Start-Process -FilePath $env:TARGET_INSTALLER -ArgumentList ''/S'',''/NCRC'' -PassThru -Wait;',
                '$p=Start-Process $app -PassThru;',
                '$p=Start-Process $env:OWNED_UNINSTALL -ArgumentList ''/S'' -PassThru -Wait;')
        } else {
            @('$p = Start-Process -FilePath $old -ArgumentList ''/S'', ''/NCRC'' -PassThru -Wait',
                '$p = Start-Process -FilePath $rc.FullName -ArgumentList ''/S'', ''/NCRC'' -PassThru -Wait',
                '$p = Start-Process -FilePath $env:owned_uninstaller -ArgumentList ''/S'' -PassThru -Wait')
        }
        $literalPins = if ($Kind -eq 'InstallerSmoke') {
            @('455d0a09e7b9b73fd7854ca17e2cfb55d2c904c7877f54d56fb993397b8d8b4b',
                '2cd4df6673c07b2403ba14fd639e11fbe44194d8a5b1d5a5cc0ccca551c6d415',
                '5e97b8eb98fe34edf628ab7fc2affa1dfe6c95b7a534aa880a8c4e7114987a46',
                'ef1c81647023585ce72059e6e916fbc28389dd89e1a474b265b98170bf08041a')
        } else {
            @('73fe3f85d01826f454eeb247d616fb622774e92767ad19ebfc4c38e2fbbc3c54',
                'eeb0d451a14d31b4e61932f4c1e7eed81784b2aacb4851d57469f5855b206ff1',
                'ea17c81c00d003f11b2235e8076a0eb7e7b5cb2462c0e33d4d24233f7a70cbed')
        }
        $pinIndex = 0
        foreach ($line in $expectedLines) {
            $found = @($workflowLines | Where-Object { $_.Trim() -ceq $line })
            if ($found.Count -ne 1) { throw "Pinned process body changed: $line" }
            $stepName = @($steps | Where-Object Text -match ([regex]::Escape($line)))[0].Name
            $stepBody = (@($steps | Where-Object Name -eq $stepName)[0]).Text
            $hash = ([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($stepBody)) |
                ForEach-Object ToString x2) -join ''
            if ($hash -ne $literalPins[$pinIndex]) { throw "Literal process body pin mismatch for $stepName." }
            $pinIndex++
        }
        if ($Kind -eq 'ReleaseCandidate') {
            $shortcutStep = @($steps | Where-Object Name -eq 'Assert previous install shortcuts')
            if ($shortcutStep.Count -ne 1) { throw 'RC shortcut assertion step is missing.' }
            $shortcutHash = ([Security.Cryptography.SHA256]::Create().ComputeHash(
                [Text.Encoding]::UTF8.GetBytes($shortcutStep[0].Text)) | ForEach-Object ToString x2) -join ''
            if ($shortcutHash -ne 'c34932e4d5bbe6f5244688763a368acabddb9a0aea4a7978f98d9d171f5deacc') {
                throw 'RC shortcut assertion step pin mismatch.'
            }
            $shortcutStep[0].Text | Should -Match '(?i)-Action Assert'
            $shortcutStep[0].Text | Should -Match '(?i)\$LASTEXITCODE\s*-ne\s*0\)\s*\{\s*throw'
        }
        $expectedStartCount = @($expectedLines | Where-Object { $_ -match 'Start-Process' }).Count
        if (@([regex]::Matches($raw, '(?i)Start-Process')).Count -ne $expectedStartCount) {
            throw 'Pinned process statement count changed.'
        }
        Assert-WorkflowMutatingPreflights $Path $Kind
        Assert-WorkflowNativeExitChecks $Path
    }

    function Assert-WorkflowAssetPatterns {
        param([string] $Path)
        $raw = Get-Content -LiteralPath $Path -Raw
        foreach ($match in [regex]::Matches($raw, '(?m)--pattern\s+["'']?(?<pattern>[^\s"'']+)["'']?')) {
            if ($match.Groups['pattern'].Value.IndexOfAny([char[]] '*?') -ge 0) { throw "Wildcard release asset pattern: $($match.Value)" }
        }
        foreach ($line in Get-Content -LiteralPath $Path) {
            if ($line -match '(?i)Get-ChildItem' -and $line -match '[*?]') { throw "Wildcard Get-ChildItem asset selection: $line" }
        }
    }

    function Get-WorkflowProcessPinViolations {
        param([string] $Path)
        $expected = @{
            'Preflight and install previous release at the exact default path' = @('$p = Start-Process -FilePath $env:PREVIOUS_INSTALLER -ArgumentList ''/S'', ''/NCRC'' -PassThru -Wait')
            'Preflight and upgrade target in place' = @('$p = Start-Process -FilePath $env:TARGET_INSTALLER -ArgumentList ''/S'', ''/NCRC'' -PassThru -Wait')
            'Preflight and launch smoke without CDP' = @('$p = Start-Process $app -PassThru')
            'Preflight and uninstall only the recorded owned path' = @('$p = Start-Process $env:OWNED_UNINSTALL -ArgumentList ''/S'' -PassThru -Wait')
            'Install v1.1.0 (default path), record its registration' = @('$p = Start-Process -FilePath $old -ArgumentList ''/S'', ''/NCRC'' -PassThru -Wait')
            'Install the release candidate over it (default path, same key)' = @('$p = Start-Process -FilePath $rc.FullName -ArgumentList ''/S'', ''/NCRC'' -PassThru -Wait')
            'Uninstall, verify the machine is clean' = @('$p = Start-Process -FilePath $env:owned_uninstaller -ArgumentList ''/S'' -PassThru -Wait')
        }
        $violations = [Collections.Generic.List[string]]::new()
        foreach ($step in Get-WorkflowRunTexts $Path) {
            if (-not $expected.ContainsKey($step.Name)) { continue }
            $normalizedStep = $step.Text -replace "[$([char]0x60)]\r?\n\s*", ' '
            $normalizedStep = $normalizedStep -replace [char]0x60, ''
            $lines = @($normalizedStep -split "`n|;" | ForEach-Object Trim | Where-Object { $_ })
            $processLines = @($lines | Where-Object { $_ -match '(?i)(Start-Process|Invoke-Item|Invoke-Expression|^\s*[&.]\s*)' })
            foreach ($line in $processLines) {
                $normalized = $line -replace '\s+', ' ' -replace '\s*,\s*', ',' -replace '\s*=\s*', '='
                $allowedLine = @($expected[$step.Name] | ForEach-Object { $_ -replace '\s+', ' ' -replace '\s*,\s*', ',' -replace '\s*=\s*', '=' })
                if ($normalized -notin $allowedLine) { [void] $violations.Add("$($step.Name): $line") }
            }
            foreach ($statement in @($expected[$step.Name])) {
                $normalizedStatement = $statement -replace '\s+', ' ' -replace '\s*,\s*', ',' -replace '\s*=\s*', '='
                if ($normalizedStatement -notin @($lines | ForEach-Object { $_ -replace '\s+', ' ' -replace '\s*,\s*', ',' -replace '\s*=\s*', '=' })) { [void] $violations.Add("$($step.Name): missing exact process statement") }
            }
        }
        $violations
    }
}

Describe 'workflow shape and regression checks' {
    It 'inspects inline, block, and unnamed run shapes' {
        $path = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"
        Set-Content -LiteralPath $path -Value @('jobs:', '  x:', '    steps:', '      - run: echo inline', '      - name: block', '        run: |', '          echo block', '      - run: |', '          echo unnamed')
        try {
            @(Get-WorkflowRunTexts $path).Count | Should -Be 3
            @(Get-WorkflowRunTexts $path).Text | Should -Contain 'echo block'
            @(Get-WorkflowRunTexts $path).Text | Should -Contain 'echo unnamed'
        } finally { Remove-Item -LiteralPath $path -Force }
    }

    It 'rejects expressions in every run shape, while allowing only exact safe contexts' {
        $path = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"
        Set-Content -LiteralPath $path -Value @(
            'jobs:'
            '  x:'
            '    steps:'
            '      - run: echo ${{ inputs.release-tag }}'
            '      - name: block'
            '        run: |'
            '          echo ${{ needs.windows.outputs.installer_name }}'
            '      - run: |'
            '          echo ${{ github.repository }}'
        )
        try {
            { Assert-WorkflowRunExpressions $path } | Should -Throw
            $safe = "$path.safe"; (Get-Content -LiteralPath $path -Raw).Replace('${{ inputs.release-tag }}', '${{ runner.temp }}').Replace('${{ needs.windows.outputs.installer_name }}', '${{ github.workspace }}') | Set-Content -LiteralPath $safe
            { Assert-WorkflowRunExpressions $safe } | Should -Not -Throw; Remove-Item -LiteralPath $safe -Force
        }
        finally { Remove-Item -LiteralPath $path -Force }
    }

    It 'catches expression mutations in both live workflows' {
        $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
        foreach ($relative in @('.github/workflows/installer-smoke.yml', '.github/workflows/release-candidate.yml')) {
            $mutated = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"; $raw = Get-Content -LiteralPath (Join-Path $root $relative) -Raw
            $expression = if ($relative -like '*installer-smoke*') { '${{ inputs.release-tag }}' } else { '${{ needs.windows.outputs.installer_name }}' }
            $raw = $raw -replace '(?m)(^\s+run:\s*\|\s*\r?\n)', "`$1          echo $expression`r`n"; Set-Content -LiteralPath $mutated -Value $raw
            try { { Assert-WorkflowRunExpressions $mutated } | Should -Throw -Because $relative } finally { Remove-Item -LiteralPath $mutated -Force }
        }
    }

    It 'rejects wildcard asset selection mutations in both workflows' {
        $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
        foreach ($relative in @('.github/workflows/installer-smoke.yml', '.github/workflows/release-candidate.yml')) {
            $mutated = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"
            $raw = Get-Content -LiteralPath (Join-Path $root $relative) -Raw
            $raw += "`n          gh release download v1.2.3 --pattern '*_x64-setup.exe'`n"
            Set-Content -LiteralPath $mutated -Value $raw
            try { { Assert-WorkflowAssetPatterns $mutated } | Should -Throw -Because $relative } finally { Remove-Item -LiteralPath $mutated -Force }
        }
    }

    It 'catches workflow-level contents-write and job-level always mutations' {
        $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
        $source = Get-Content -LiteralPath (Join-Path $root '.github/workflows/installer-smoke.yml') -Raw
        $writePath = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"
        $alwaysPath = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"
        Set-Content -LiteralPath $writePath -Value $source.Replace('contents: read', 'contents: write')
        Set-Content -LiteralPath $alwaysPath -Value ($source -replace '(?m)^  real-identity:', "  real-identity:`r`n    if: always()")
        try {
            { Assert-WorkflowShape $writePath } | Should -Throw
            { Assert-WorkflowShape $alwaysPath } | Should -Throw
        }
        finally {
            Remove-Item -LiteralPath $writePath, $alwaysPath -Force
        }
    }

    It 'pins exact workflow process statements and rejects extra or changed statements' {
        $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
        $source = Join-Path $root '.github/workflows/installer-smoke.yml'
        $extra = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"
        $changed = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"
        $raw = Get-Content -LiteralPath $source -Raw
        Set-Content -LiteralPath $extra -Value $raw.Replace(
            '$p=Start-Process -FilePath $env:TARGET_INSTALLER',
            '$p=Start-Process -FilePath $env:TARGET_INSTALLER; & $env:TARGET_INSTALLER /S'
        )
        Set-Content -LiteralPath $changed -Value ($raw -replace '\$env:TARGET_INSTALLER', '$env:OTHER_INSTALLER')
        try { @(Get-WorkflowProcessPinViolations $extra).Count | Should -BeGreaterThan 0; @(Get-WorkflowProcessPinViolations $changed).Count | Should -BeGreaterThan 0 } finally { Remove-Item -LiteralPath $extra, $changed -Force }
    }

    It 'requires read-only permissions, safe expressions, and exact assets' {
        $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
        foreach ($relative in @('.github/workflows/installer-smoke.yml', '.github/workflows/release-candidate.yml')) {
            $path = Join-Path $root $relative; $raw = Get-Content -LiteralPath $path -Raw
            Assert-WorkflowShape $path
            $raw | Should -Not -Match '(?m)^\s+contents:\s+write\s*$'; $raw | Should -Not -Match '(?im)^\s*id-token\s*:'
            Assert-WorkflowRunExpressions $path
            Assert-WorkflowAssetPatterns $path
            $raw | Should -Not -Match '(?m)^\s*permissions:\s*write\s*$'
        }
    }

    It 'pins the RC shortcut assertion action and throwing exit check as one step body' {
        $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
        $source = Get-Content (Join-Path $root '.github/workflows/release-candidate.yml') -Raw
        $candidate = Join-Path ([IO.Path]::GetTempPath()) "rc-shortcut-pin-$([guid]::NewGuid()).yml"
        try {
            $mutated = Replace-First $source 'ci-assert-shortcuts.ps1 -Action Assert ' 'ci-assert-shortcuts.ps1 -Action Report '
            Set-Content -LiteralPath $candidate -Value $mutated
            $thrown = $null
            try { Assert-WorkflowContract $candidate ReleaseCandidate -SkipHash } catch { $thrown = $_.Exception.Message }
            $thrown | Should -Match 'RC shortcut assertion step pin'
        } finally { Remove-Item -LiteralPath $candidate -Force -ErrorAction SilentlyContinue }
    }

    It 'rejects a changed RC ownership guard and requires post-uninstall absence' {
        $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
        $path = Join-Path $root '.github/workflows/release-candidate.yml'
        $raw = Get-Content $path -Raw
        $raw | Should -Match 'beforeRcLocation.*owned_install_dir'
        $raw | Should -Match 'beforeRcUninstall.*owned_uninstaller'
        $raw | Should -Match 'ci-assert-shortcuts\.ps1 -Action AssertAbsent'
        $mutated = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"
        try {
            Set-Content $mutated ($raw -replace '(?m)^\s*if \(\$beforeRcLocation -ne .*\r?\n', '')
            (Get-Content $mutated -Raw) | Should -Not -Match 'beforeRcLocation.*owned_install_dir'
        } finally { Remove-Item $mutated -Force }
    }

    It 'requires a check after every helper call in the two target workflows' {
        $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
        foreach ($relative in @('.github/workflows/installer-smoke.yml', '.github/workflows/release-candidate.yml')) {
            $lines = Get-Content (Join-Path $root $relative)
            for ($i = 0; $i -lt $lines.Count; $i++) {
                if ($lines[$i] -match 'pwsh -NoProfile -File \.github/scripts/ci-assert-') {
                    $checked = $lines[$i] -match 'LASTEXITCODE'
                    for ($j = $i + 1; $j -lt [Math]::Min($i + 8, $lines.Count); $j++) {
                        if ($lines[$j] -match 'LASTEXITCODE') { $checked = $true; break }
                    }
                    $checked | Should -BeTrue -Because "$relative line $($i + 1)"
                }
            }
        }
    }

    It 'executes the pwsh release-candidate manifest body and rejects placeholder expansion' {
        $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
        $workflow = Join-Path $root '.github/workflows/release-candidate.yml'
        $pwsh = (Get-Command pwsh -CommandType Application -ErrorAction Stop).Source
        $manifestBody = @((Get-WorkflowJobBlocks $workflow)['manifest']) -join "`n"
        $stepMatch = [regex]::Match($manifestBody, '(?ms)^      - name: Write the manifest\r?\n.*?(?=^      - name:|\z)')
        $stepMatch.Success | Should -BeTrue
        $declaredShell = [regex]::Match($stepMatch.Value, '(?m)^        shell:\s*(?<shell>\S+)\s*$').Groups['shell'].Value
        $declaredShell | Should -Be 'pwsh'
        $stepText = [regex]::Match($stepMatch.Value, '(?ms)^        run:\s*\|\r?\n(?<body>.*)$').Groups['body'].Value
        $env:SOURCE_COMMIT='sample-commit'; $env:SOURCE_REF='refs/heads/sample'; $env:RUN_ID='12345'; $env:RUN_URL='https://example.invalid/run/12345'
        $env:WINDOWS_INSTALLER='windows.exe'; $env:WINDOWS_SIZE='101'; $env:WINDOWS_SHA256=('a' * 64)
        $env:LINUX_DEB='linux.deb'; $env:LINUX_SIZE='202'; $env:LINUX_SHA256=('b' * 64)
        $runRoot = Join-Path ([IO.Path]::GetTempPath()) "manifest-run-$([guid]::NewGuid())"; New-Item -ItemType Directory -Force $runRoot | Out-Null
        $runScript = Join-Path $runRoot 'manifest.ps1'; [IO.File]::WriteAllText($runScript, $stepText)
        try {
            Push-Location $runRoot
            try { & $pwsh -NoProfile -NonInteractive -File $runScript | Out-Null; $exitCode = $LASTEXITCODE } finally { Pop-Location }
            $exitCode | Should -Be 0
            $manifestPath = Join-Path $runRoot 'RELEASE_CANDIDATE.txt'
            Test-Path $manifestPath | Should -BeTrue
            $bytes = [IO.File]::ReadAllBytes($manifestPath)
            if ($bytes.Length -ge 3) { (($bytes[0] -eq 0xEF) -and ($bytes[1] -eq 0xBB) -and ($bytes[2] -eq 0xBF)) | Should -BeFalse }
            $lines = @(Get-Content -LiteralPath $manifestPath | Where-Object { $_ -ne '' })
            $expected = @('# Release-candidate manifest','source_commit: sample-commit','source_ref: refs/heads/sample','run_id: 12345','run_url: https://example.invalid/run/12345','windows_installer: windows.exe','windows_size: 101')
            $expected += 'windows_sha256: ' + ('a' * 64)
            $expected += @('linux_deb: linux.deb','linux_size: 202')
            $expected += 'linux_sha256: ' + ('b' * 64)
            $lines | Should -Be $expected
            (Get-Content -Raw $manifestPath) | Should -Not -Match ':SOURCE_COMMIT|:WINDOWS_SHA256|:LINUX_SHA256'
        } finally { Remove-Item -LiteralPath $runRoot -Recurse -Force }
    }

    It 'runs the bounded installer-smoke mutation table and reports each intended rule' {
        $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
        $source = Get-Content (Join-Path $root '.github/workflows/installer-smoke.yml') -Raw
        $mutations = @(
            @{ Name='step continue-on-error'; Text="`n        continue-on-error: true"; Reason='continue-on-error' }
            @{ Name='job continue-on-error'; Text="`n    continue-on-error: true"; Reason='continue-on-error' }
            @{ Name='pinned step if false'; Text="`n        if: false"; Reason='continue-on-error/if' }
            @{ Name='flow permissions'; Text=''; Edit={ param($s) $s -replace 'permissions:\s*\r?\n\s+contents: read', 'permissions: { contents: read, pull-requests: write }' }; Reason='flow-style permissions' }
            @{ Name='pull requests write'; Text=''; Edit={ param($s) Replace-First $s 'contents: read' "contents: read`r`n  pull-requests: write" }; Reason='permissions map' }
            @{ Name='job id token write'; Text=''; Edit={ param($s) $s -replace '(?m)^    permissions:\s*\r?\n      contents: read', "    permissions`r`n      contents: read`r`n      id-token: write" }; Reason='job real-identity permissions' }
            @{ Name='extra unguarded job'; Text="`n  extra-job:`n    runs-on: windows-latest`n    permissions:`n      contents: read`n    steps:`n      - name: x`n        run: echo x`n        shell: pwsh"; Reason='job list' }
            @{ Name='pull request target'; Text=''; Edit={ param($s) $s.Replace('  workflow_call:', '  pull_request_target: {}') }; Reason='trigger' }
            @{ Name='extra process statement'; Text="`n          Start-Process extra"; Reason='process statement count' }
            @{ Name='unnamed run step'; Text="`n      - run: echo mutation`n        shell: pwsh"; Reason='unnamed run step' }
        )
        foreach ($mutation in $mutations) {
            $text = if ($mutation.ContainsKey('Edit')) { $mutation.Edit.Invoke($source) } else { $source + $mutation.Text }
            $candidate = Join-Path ([IO.Path]::GetTempPath()) "installer-mutation-$([guid]::NewGuid()).yml"
            Set-Content -LiteralPath $candidate -Value $text
            try {
                $thrown = $null; try { Assert-WorkflowContract $candidate InstallerSmoke -SkipHash } catch { $thrown = $_.Exception.Message }
                $thrown | Should -Not -BeNullOrEmpty -Because $mutation.Name
                $thrown | Should -Match $mutation.Reason -Because $mutation.Name
            } finally { Remove-Item -LiteralPath $candidate -Force }
        }
        $rcSource = Get-Content (Join-Path $root '.github/workflows/release-candidate.yml') -Raw
        $rcCandidate = Join-Path ([IO.Path]::GetTempPath()) "rc-hash-mutation-$([guid]::NewGuid()).yml"
        Set-Content -LiteralPath $rcCandidate -Value $rcSource.Replace('b41931774eac5586bc31746599d4a637e89eda195c620067dc1c756281b217ee', ('0' * 64))
        try {
            $thrown = $null; try { Assert-WorkflowStructuralContract $rcCandidate ReleaseCandidate } catch { $thrown = $_.Exception.Message }
            $thrown | Should -Match 'published v1.1.0 hash' -Because 'changed v1.1.0 hash'
        } finally { Remove-Item -LiteralPath $rcCandidate -Force }
    }

    It 'rejects each release-candidate manifest contract mutation without relying on the whole-file pin' {
        $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
        $source = Get-Content (Join-Path $root '.github/workflows/release-candidate.yml') -Raw
        $mutations = @(
            @{ Name='missing upgrade smoke dependency'; Edit={ param($s) Replace-First $s 'needs: [windows, linux, windows-upgrade-smoke]' 'needs: [windows, linux]' }; Reason='manifest dependency rule' }
            @{ Name='wrong dependency'; Edit={ param($s) Replace-First $s 'needs: [windows, linux, windows-upgrade-smoke]' 'needs: [windows, linux, other-job]' }; Reason='manifest dependency rule' }
            @{ Name='windows-upgrade-smoke needs removed'; Edit={ param($s) $s -replace '(?m)^    needs: windows\r?\n', '' }; Reason='windows-upgrade-smoke dependency rule' }
            @{ Name='manifest shell bash'; Edit={
                    param($s)
                    $start=$s.IndexOf('      - name: Write the manifest'); $tail=$s.Substring($start)
                    $s.Substring(0,$start) + (Replace-First $tail '        shell: pwsh' '        shell: bash')
                }; Reason='manifest step shell' }
            @{ Name='manifest file write removed'; Edit={ param($s) Replace-First $s ') | Tee-Object -FilePath RELEASE_CANDIDATE.txt' ') | Out-Null' }; Reason='manifest output file rule' }
            @{ Name='manifest output renamed'; Edit={ param($s) Replace-First $s 'RELEASE_CANDIDATE.txt' 'RENAMED.txt' }; Reason='manifest output file rule' }
        )
        foreach ($mutation in $mutations) {
            $candidate = Join-Path ([IO.Path]::GetTempPath()) 'release-candidate.yml'
            try {
                Set-Content -LiteralPath $candidate -Value $mutation.Edit.Invoke($source)
                $thrown = $null; try { Assert-WorkflowContract $candidate ReleaseCandidate -SkipHash } catch { $thrown = $_.Exception.Message }
                $thrown | Should -Match $mutation.Reason -Because $mutation.Name
                $pinnedThrown = $null; try { Assert-WorkflowContract $candidate ReleaseCandidate } catch { $pinnedThrown = $_.Exception.Message }
                $pinnedThrown | Should -Not -BeNullOrEmpty -Because "$($mutation.Name) with pin"
            } finally { Remove-Item -LiteralPath $candidate -Force -ErrorAction SilentlyContinue }
        }
    }

    It 'fails on a first nonzero native result and passes on a second zero result' {
        $lastExitCode = 7
        { if ($lastExitCode -ne 0) { throw 'first call failed' } } | Should -Throw
        $lastExitCode = 0
        { if ($lastExitCode -ne 0) { throw 'second call failed' } } | Should -Not -Throw
    }

    It 'requires canonical helper invocation and a throwing LASTEXITCODE check' {
        $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
        $source = Get-Content (Join-Path $root '.github/workflows/installer-smoke.yml') -Raw
        $nonCanonical = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"
        $noThrow = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"
        try {
            Set-Content $nonCanonical $source.Replace('pwsh -NoProfile -File .github/scripts/ci-assert-', 'pwsh -File .github/scripts/ci-assert-')
            { Assert-WorkflowContract $nonCanonical InstallerSmoke -SkipHash } | Should -Throw
            $needle = "          if (`$LASTEXITCODE -ne 0) { throw 'Target checksum assertion failed.' }"
            $mutated = $source.Replace($needle, "          if (`$LASTEXITCODE -ne 0) { Write-Host 'not an exit check' }")
            Set-Content $noThrow $mutated
            { Assert-WorkflowNativeExitChecks $noThrow } | Should -Throw
        } finally { Remove-Item $nonCanonical,$noThrow -Force }
    }

    It 'rejects every listed mutation from a passing copy of both live workflows' {
        $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
        $mutations = @(
            @{ Name='permissions write-all'; Edit={ param($s) $s -replace 'contents: read', 'permissions: write-all' } }
            @{ Name='actions write'; Edit={ param($s) $s -replace 'contents: read', 'actions: write' } }
            @{ Name='quoted contents write'; Edit={ param($s) $s -replace 'contents: read', 'contents: "write"' } }
            @{ Name='contents trailing comment'; Edit={ param($s) $s -replace 'contents: read', 'contents: write # mutation' } }
            @{ Name='always wrapper'; Edit={ param($s) $s -replace "if: github.repository", "if: always() && github.repository" } }
            @{ Name='always and true'; Edit={ param($s) $s -replace "if: github.repository", "if: always() && true && github.repository" } }
            @{ Name='self-hosted'; Edit={ param($s) $s -replace 'runs-on: windows-latest', 'runs-on: self-hosted' } }
            @{ Name='action ref'; Edit={ param($s) $s -replace 'actions/checkout@v4', 'actions/checkout@v3' } }
            @{ Name='step count'; Edit={ param($s) $s + "`n      - name: unnamed mutation`n        run: echo mutation`n" } }
        )
        foreach ($relative in @('.github/workflows/installer-smoke.yml', '.github/workflows/release-candidate.yml')) {
            $source = Get-Content (Join-Path $root $relative) -Raw
            $kind = if ($relative -like '*installer-smoke*') { 'InstallerSmoke' } else { 'ReleaseCandidate' }
            { Assert-WorkflowContract (Join-Path $root $relative) $kind } | Should -Not -Throw -Because $relative
            foreach ($mutation in $mutations) {
                $candidate = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"
                Set-Content $candidate $mutation.Edit.Invoke($source)
                { Assert-WorkflowContract $candidate $kind -SkipHash } | Should -Throw -Because "${relative}: $($mutation.Name)"
                Remove-Item $candidate -Force
            }
        }
        foreach ($relative in @('.github/workflows/installer-smoke.yml', '.github/workflows/release-candidate.yml')) {
            $source = Get-Content (Join-Path $root $relative) -Raw
            $guardedStepName = if ($relative -like '*installer-smoke*') {
                'Preflight and launch smoke without CDP'
            } else { 'Install the release candidate over it (default path, same key)' }
            $special = @(
                @{ Name='missing job if'; Edit={ param($s) $s -replace "(?m)^    if: github.repository == 'DVOpenLabs/snapmaker-studio'\r?\n", '' } }
                @{ Name='unnamed call operator variable'; Edit={ param($s) $s + "`n      - run: |`n          & `$newLauncher`n" } }
                @{ Name='renamed guarded step'; Edit={ param($s) $s.Replace($guardedStepName, 'Launch step') } }
                @{ Name='preflight removed'; Edit={ param($s) $s.Replace('Disposable preflight failed.', 'preflight removed.') } }
                @{ Name='second helper without exit check'; Edit={ param($s) $s + "`n          pwsh -NoProfile -File .github/scripts/ci-assert-manifest.ps1`n" } }
                @{ Name='process body one byte'; Edit={ param($s) $s.Replace('PassThru', 'PassThruX') } }
            )
            foreach ($mutation in $special) {
                $candidate = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"
                Set-Content $candidate $mutation.Edit.Invoke($source)
                { Assert-WorkflowContract $candidate $kind -SkipHash } | Should -Throw -Because "${relative}: $($mutation.Name)"
                Remove-Item $candidate -Force
            }
        }
    }

    It 'runs the combined M1-M4 regression sweep against live workflow copies' {
        $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
        foreach ($relative in @('.github/workflows/installer-smoke.yml', '.github/workflows/release-candidate.yml')) {
            $source = Get-Content (Join-Path $root $relative) -Raw
            $kind = if ($relative -like '*installer-smoke*') { 'InstallerSmoke' } else { 'ReleaseCandidate' }
            { Assert-WorkflowContract (Join-Path $root $relative) $kind } | Should -Not -Throw -Because "$relative live contract"

            $mutations = @(
                @{ Name='M1 missing job if'; Edit={ param($s) $s -replace "(?m)^    if: github\.repository == 'DVOpenLabs/snapmaker-studio'\r?\n", '' } }
                @{ Name='M4 process statement changed'; Edit={ param($s) $s -replace '(?m)(Start-Process[^\r\n])', '$1X' } }
            )
            foreach ($mutation in $mutations) {
                $candidate = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"
                Set-Content $candidate $mutation.Edit.Invoke($source)
                try { { Assert-WorkflowContract $candidate $kind -SkipHash } | Should -Throw -Because "$relative $($mutation.Name)" } finally { Remove-Item $candidate -Force }
            }

            $stepNames = if ($relative -like '*installer-smoke*') {
                @('Download target installer and verify live SHA256SUMS', 'Download previous installer and verify live SHA256SUMS',
                    'Preflight and install previous release at the exact default path', 'Assert previous install exact surfaces',
                    'Preflight and upgrade target in place', 'Assert target shortcuts and capture installed-tree manifest',
                    'Preflight and launch smoke without CDP', 'Preflight and uninstall only the recorded owned path', 'Report final registry state')
            } else {
                @('Download the published v1.1.0 installer, verify its checksum', 'Install v1.1.0 (default path), record its registration',
                    'Assert previous install shortcuts', 'Install the release candidate over it (default path, same key)',
                    'Capture release-candidate installed-tree manifest', 'Uninstall, verify the machine is clean')
            }
            foreach ($name in $stepNames) {
                $stepPattern = "(?ms)(^      - name: " + [regex]::Escape($name) + ".*?)(?=^      - name:|\z)"
                $stepMatch = [regex]::Match($source, $stepPattern)
                $stepMatch.Success | Should -BeTrue -Because "$relative step $name exists"
                $mutatedStep = Replace-First $stepMatch.Value "`$env:RUNNER_ENVIRONMENT -ne 'github-hosted'" '$false'
                $candidateText = $source.Substring(0, $stepMatch.Index) + $mutatedStep + $source.Substring($stepMatch.Index + $stepMatch.Length)
                $candidate = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"
                Set-Content $candidate $candidateText
                try { { Assert-WorkflowContract $candidate $kind -SkipHash } | Should -Throw -Because "$relative M2 preflight in $name" } finally { Remove-Item $candidate -Force }
            }

            $steps = @(Get-WorkflowRunTexts (Join-Path $root $relative))
            foreach ($step in $steps) {
                $callMatches = @([regex]::Matches($step.Text, '(?im)(?:^|;)\s*(?:gh\s+|pwsh\s+-NoProfile\s+-File\s+)'))
                $checkMatches = @([regex]::Matches($step.Text, '(?i)\$LASTEXITCODE\s*-ne\s*0'))
                for ($call = 0; $call -lt $checkMatches.Count; $call++) {
                    $checkText = $checkMatches[$call].Value
                    $stepPattern = "(?ms)(^      - name: " + [regex]::Escape($step.Name) + ".*?)(?=^      - name:|\z)"
                    $stepMatch = [regex]::Match($source, $stepPattern)
                    $mutatedStep = Replace-First $stepMatch.Value $checkText ''
                    $candidateText = $source.Substring(0, $stepMatch.Index) + $mutatedStep + $source.Substring($stepMatch.Index + $stepMatch.Length)
                    $candidate = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).yml"
                    Set-Content $candidate $candidateText
                    try { { Assert-WorkflowContract $candidate $kind -SkipHash } | Should -Throw -Because "$relative M3 exit check $($step.Name) call $($call + 1)" } finally { Remove-Item $candidate -Force }
                }
            }
        }
    }
}
