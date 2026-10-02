#requires -Version 7.0
# HarnessLauncher - the ONE shared, fail-closed workstation lane for issue #55.
#
# Used by tools/acceptance/run.ps1, tools/hardware/verify.ps1, tools/demo/record.ps1 and
# scripts/capture_embedded.ps1. No harness keeps its own copy of any of this logic.
#
# What this lane is: a REWRAPPED, ACCEPTANCE-IDENTITY installer (tools/release/rewrap_installer.ps1) is
# copied into the harness tree, hashed against its attestation, installed with /S /NCRC /NS into
# <harness root>\install\<runId>, driven, and uninstalled. It proves the rewrapped acceptance-identity
# lane. It does NOT prove the production installer: production registration, shortcut creation,
# default-path upgrade and uninstall are proven only by the disposable CI lanes.
#
# Scope of the controls: accident / agent-error control, not a defence against a maintainer who
# deliberately bypasses it. Everything fails closed. Nothing here ever installs, runs, writes or
# deletes anything under the PRODUCTION identity; production state is only READ (preflight + tripwire).
#
# Honest limits: there is no handle-based confinement, so every containment check narrows (does not
# eliminate) a check-then-use window; the tripwire DETECTS and reports, it never restores or deletes.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot '..\lib\InstallGuard.psm1') -DisableNameChecking
Import-Module (Join-Path $PSScriptRoot 'HarnessJournal.psm1') -DisableNameChecking

$script:Identity = Get-HarnessIdentity
$script:RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$script:LaneLabel = 'rewrapped acceptance-identity installer'
$script:UpgradeLaneLabel = 'upgrade between two rewrapped acceptance-identity installers (OLD -> NEW); not a production upgrade'
$script:NotProven = 'Production registration, shortcut creation, default-path install/upgrade/uninstall of the real installer are NOT proven by this lane; they are proven only by the disposable CI lanes.'
$script:WebView2ClientGuid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
# Only these tools may be started through Start-HarnessTool (image base names, without .exe).
$script:AllowedTools = @('node', 'ffmpeg')
# Test-only hooks. Never a parameter of any harness script; tests set them through InModuleScope.
# Keys: RoamingDir, LocalDir, EngineDir, RealStartMenuDir, RealDesktopDir, RegistryRoot, MutexName,
#       ProductionProcessProvider, WebViewWaitSeconds, CdpWaitSeconds, PortWaitSeconds, ExitWaitSeconds
$script:TestHooks = @{}

# PERSISTED EVIDENCE IS A CLOSED SCHEMA (privacy by construction). Evidence files carry only the typed fields of
# $script:EvidenceSchema: enums, fixed REASON CODES, integer counts, booleans, hashes, versions and harness-relative
# artifact names built from validated ids. Raw exception text, command output, paths (absolute or otherwise), user names,
# registry paths, hosts and every other free-text string are NEVER persisted. Those stay console-only, through the
# best-effort scrubber (Protect-LaneText), which is a SECONDARY layer and not a privacy boundary.
$script:ReasonCodes = @(
    'INSTALLER_PREFLIGHT_FAILED', 'INSTALL_FAILED', 'INSTALL_TIMEOUT', 'ORPHANED_INSTALL', 'UNINSTALL_FAILED',
    'UNINSTALL_HANDOFF_INCOMPLETE', 'UNKNOWN_OUTCOME', 'RECOVERY_PENDING', 'APP_LAUNCH_FAILED', 'WEBVIEW_PREFLIGHT_FAILED',
    'PROFILE_CHECK_FAILED', 'CDP_CHECK_FAILED', 'PORT_IN_USE', 'PRODUCTION_RUNNING', 'UPDATE_CHECK_PREFLIGHT_FAILED',
    'TRIPWIRE_VIOLATION', 'SHORTCUT_ASSERTION_FAILED', 'PENDING_JOURNAL_BLOCKS_LANE', 'TOOL_NOT_ALLOWED', 'REPORT_WRITE_FAILED',
    'LANE_STEP_FAILED', 'LOCK_RELEASE_FAILED', 'JOURNAL_RECORD_FAILED', 'UNCLASSIFIED_ERROR'
)
$script:UninstallOutcomes = @('NotRun', 'NothingInstalled', 'NotLaunched', 'Success', 'Failed', 'Unknown')
$script:InstallArgumentsText = '/S /NCRC /NS /D=<install dir>'
$script:EvidenceSchemaId = 'harness-lane-evidence/2'
# A run id is OPAQUE and generated ('h' + 32 lowercase hex). No human-chosen word can ever be a run id; phase ids add -u<N>.
$script:RunIdPattern = '^h[0-9a-f]{32}$'
$script:PhaseIdPattern = '^h[0-9a-f]{32}(-u[2-9])?$'
# Strict numeric release shapes only (1.2.0, 0.4.0-beta.20.2, 1.0.0-rc.1): never a word a person chose.
$script:SourceVersionPattern = '^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta|rc)(\.[0-9]+){1,3})?$'
$script:EvidenceSchema = $null     # built lazily (it embeds the lane labels defined above)

function Get-Hook {
    param([string]$Name, $Default = $null)
    if ($script:TestHooks.ContainsKey($Name) -and $null -ne $script:TestHooks[$Name]) { return $script:TestHooks[$Name] }
    $Default
}

# ---------------------------------------------------------------------------
# Seams (private). Tests Mock these with -ModuleName HarnessLauncher; production code never bypasses them.
# ---------------------------------------------------------------------------

function Start-HarnessChildProcess {
    # THE only place a child process is created. Environment is applied to the CHILD (ProcessStartInfo.Environment);
    # the session's $env: is never read-modify-written here or anywhere in the harness (L13).
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$ArgumentString,
        [hashtable]$Environment = @{},
        [string]$WorkingDirectory,
        [switch]$Hidden, [switch]$RedirectOutput, [switch]$RedirectInput
    )
    $psi = [System.Diagnostics.ProcessStartInfo]::new($FilePath)
    $psi.UseShellExecute = $false
    if ($ArgumentString) { $psi.Arguments = $ArgumentString } else { foreach ($a in $ArgumentList) { $psi.ArgumentList.Add([string]$a) } }
    foreach ($k in $Environment.Keys) { $psi.Environment[[string]$k] = [string]$Environment[$k] }
    if ($WorkingDirectory) { $psi.WorkingDirectory = $WorkingDirectory }
    if ($Hidden) { $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden; $psi.CreateNoWindow = $true }
    if ($RedirectOutput) { $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true }
    if ($RedirectInput) { $psi.RedirectStandardInput = $true }
    [System.Diagnostics.Process]::Start($psi)
}

function Get-LiveProcessInfo {
    param([Parameter(Mandatory)][int]$ProcessId)
    try { $p = Get-Process -Id $ProcessId -ErrorAction Stop } catch { return $null }
    $path = $null; try { $path = $p.Path } catch { }
    $ticks = $null; try { $ticks = $p.StartTime.ToUniversalTime().Ticks } catch { return $null }
    [pscustomobject]@{ Id = $ProcessId; StartTicks = [int64]$ticks; Path = $path }
}

function Stop-ProcessById { param([Parameter(Mandatory)][int]$ProcessId) Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue }

function Get-Win32ProcessList {
    # ProcessId, ParentProcessId, Name, ExecutablePath for every process (read-only).
    @(Get-CimInstance Win32_Process -ErrorAction Stop | ForEach-Object {
            [pscustomobject]@{ ProcessId = [int]$_.ProcessId; ParentProcessId = [int]$_.ParentProcessId; Name = [string]$_.Name; ExecutablePath = [string]$_.ExecutablePath }
        })
}

function Get-PortOwnerPid {
    param([Parameter(Mandatory)][int]$Port)
    $c = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($c.Count -eq 0) { return $null }
    [int]$c[0].OwningProcess
}

function Test-LoopbackPortFree {
    param([Parameter(Mandatory)][int]$Port)
    $l = $null
    try {
        $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $l.Start()
        return $true
    } catch { return $false } finally { if ($l) { try { $l.Stop() } catch { } } }
}

function Test-CdpEndpoint {
    param([Parameter(Mandatory)][int]$Port)
    try { (Invoke-WebRequest "http://127.0.0.1:$Port/json/version" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { $false }
}

function Get-WebView2RuntimeVersion {
    # Read-only registry probe. Never runs or installs the bootstrapper (S6).
    foreach ($k in @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$script:WebView2ClientGuid",
            "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$script:WebView2ClientGuid",
            "HKCU:\Software\Microsoft\EdgeUpdate\Clients\$script:WebView2ClientGuid")) {
        if (Test-Path -LiteralPath $k) {
            $pv = (Get-ItemProperty -LiteralPath $k -ErrorAction Stop).PSObject.Properties['pv']
            if ($pv -and $pv.Value -and [string]$pv.Value -ne '0.0.0.0') { return [string]$pv.Value }
        }
    }
    $null
}

function Invoke-RewrapScript {
    # tools/release/rewrap_installer.ps1 is the only thing allowed to touch a REAL installer (extract + compile only).
    param([Parameter(Mandatory)][hashtable]$Parameters)
    $script = Join-Path $script:RepoRoot 'tools\release\rewrap_installer.ps1'
    $out = @(& $script @Parameters)
    $res = @($out | Where-Object { $_ -and $_.PSObject.Properties['AttestationPath'] -and $_.PSObject.Properties['InstallerPath'] })
    if ($res.Count -eq 0) { throw 'Refused: the rewrap did not return an installer and attestation.' }
    $res[-1]
}

# ---------------------------------------------------------------------------
# Paths and isolation
# ---------------------------------------------------------------------------

function Assert-HarnessPathInside {
    <# Positive containment for every isolation path: raw-syntax allowlist + strictly inside the harness root
       + reparse-free chain from the volume root + not a production location. Returns the canonical path. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Root, [string]$What = 'path')
    $full = Assert-AllowedOverridePath -Path $Path -What $What
    if (-not (Test-PathContained -Path $full -Root $Root)) { throw "Refused: $What is not strictly inside the harness directory." }
    Assert-HarnessOwnedPath -Path $full -Root $Root -What $What
    $full
}

function Assert-NoWildcardPath {
    param([string]$Path, [string]$What)
    if ([string]::IsNullOrWhiteSpace($Path)) { throw "Refused: $What was not supplied." }
    if ($Path -match '[*?\[\]]') { throw "Refused: $What must be an exact file path (no wildcard / glob discovery)." }
}

function New-HarnessRunId { 'h' + [guid]::NewGuid().ToString('N') }

function Get-HarnessLanePaths {
    <# Pure path derivation, validated. Nothing is created. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$RunId)
    if ($RunId -cnotmatch $script:RunIdPattern) { throw "Refused: invalid run id '$RunId'." }
    $sub = $script:Identity.HarnessSubdirs
    $runDir = Join-Path (Join-Path $Root 'run') $RunId
    $p = [ordered]@{
        Root        = $Root
        RunDir      = $runDir
        InstallDir  = Join-Path (Join-Path $Root $sub.Install) $RunId
        ProfileDir  = Join-Path $runDir 'webview-profile'
        DataDir     = Join-Path $runDir 'engine-data'
        EvidenceDir = Join-Path $runDir 'evidence'
        ShortcutDir = Join-Path $runDir 'shortcuts'   # journal destinations: <ShortcutDir>\StartMenu and \Desktop (harness-owned, EMPTY)
    }
    foreach ($k in 'RunDir', 'InstallDir', 'ProfileDir', 'DataDir', 'EvidenceDir', 'ShortcutDir') { [void](Assert-HarnessPathInside -Path $p[$k] -Root $Root -What $k) }
    $p
}

function Assert-LaneIsolation {
    <# Every launch re-derives and re-validates: all isolation paths resolve (reparse-free) INSIDE the harness
       directory, the install dir is below <harness>\install, and the app exe is the RENAMED acceptance binary. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [switch]$ForInstall)
    $root = $Lane.Root
    foreach ($k in 'RunDir', 'ProfileDir', 'DataDir', 'EvidenceDir', 'ShortcutDir', 'InstallDir') { [void](Assert-HarnessPathInside -Path $Lane[$k] -Root $root -What "isolation path $k") }
    if (-not (Test-PathContained -Path $Lane.InstallDir -Root (Join-Path $root $script:Identity.HarnessSubdirs.Install))) { throw 'Refused: install dir is not below the harness install tree.' }
    $exe = [string]$Lane.AppExe
    $acc = $script:Identity.Acceptance
    if ([IO.Path]::GetFileName($exe) -ine $acc.MainBinaryName) { throw "Refused: the app exe must be the acceptance binary '$($acc.MainBinaryName)'." }
    if ([IO.Path]::GetFileName($exe) -ieq $script:Identity.Production.MainBinaryName) { throw 'Refused: the production exe name is never launched.' }
    if (-not (Test-PathContainedNoReparse -Path $exe -Root $Lane.InstallDir)) { throw 'Refused: the app exe is not inside the harness install dir.' }
    if ($ForInstall) { return }   # before the installer ran the exe cannot exist yet; every other check above still applies
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Refused: the app exe does not exist (not installed).' }
}

function Get-CurrentUserName { [Environment]::UserName }   # seam (tests substitute a user name)

function Protect-LaneText {
    <# Everything that reaches evidence or the console goes through here: harness/repo/temp roots become placeholders, any
       other absolute local path becomes <path>, and the current user name becomes <user>. #>
    param([AllowNull()][string]$Text, $Lane)
    if ([string]::IsNullOrEmpty($Text)) { return $Text }
    $t = ConvertTo-PublicPath -Path $Text -Lane $Lane
    # (1) A quoted absolute path (drive or UNC) is consumed through its closing quote, spaces and all.
    $t = [regex]::Replace($t, '(?<q>["''])(?:[A-Za-z]:[\\/]|\\\\)[^\r\n]*?\k<q>', '${q}<path>${q}')
    # (2) An unquoted absolute path (drive or UNC) is consumed up to the first delimiter: a quote or angle bracket, a newline,
    #     ' : ', '; ' or the end. Over-redaction is preferred to leaking the tail of a path that contains spaces.
    $t = [regex]::Replace($t, '(?<![A-Za-z0-9<])(?:[A-Za-z]:[\\/]|\\\\)(?:(?! : |; )[^\r\n"''<>|])*', '<path>')
    $u = Get-CurrentUserName
    if ($u -and $u.Length -ge 3) { $t = [regex]::Replace($t, [regex]::Escape($u), '<user>', [Text.RegularExpressions.RegexOptions]::IgnoreCase) }
    $t
}

function Resolve-ReasonCode {
    # Every error / finding / warning maps to exactly ONE code from the fixed list; anything else is UNCLASSIFIED_ERROR.
    param([string]$Code)
    if ($Code -and $script:ReasonCodes -ccontains $Code) { $Code } else { 'UNCLASSIFIED_ERROR' }
}

# The Text is CONSOLE-ONLY (best-effort scrubbed). Only the Code is ever persisted.
function Add-LaneError {
    param($Lane, [string]$Text, [string]$Code = 'UNCLASSIFIED_ERROR')
    $Lane.Errors.Add((Protect-LaneText -Text $Text -Lane $Lane)); $Lane.ErrorCodes.Add((Resolve-ReasonCode $Code))
}
function Add-LaneFinding {
    param($Lane, [string]$Text, [string]$Code = 'UNCLASSIFIED_ERROR')
    $Lane.Findings.Add((Protect-LaneText -Text $Text -Lane $Lane)); $Lane.FindingCodes.Add((Resolve-ReasonCode $Code))
}
function Add-LaneWarning {
    param($Lane, [string]$Text, [string]$Code = 'UNCLASSIFIED_ERROR')
    $Lane.Warnings.Add((Protect-LaneText -Text $Text -Lane $Lane)); $Lane.WarningCodes.Add((Resolve-ReasonCode $Code))
}

function Get-PreflightReasonCode {
    # Classifies one of OUR OWN preflight refusals into a fixed code (the message itself is never persisted).
    param([string]$Message)
    if ($Message -match 'production Snapmaker Studio process') { return 'PRODUCTION_RUNNING' }
    if ($Message -match 'update_check|auto-check') { return 'UPDATE_CHECK_PREFLIGHT_FAILED' }
    if ($Message -match 'WebView2 runtime') { return 'WEBVIEW_PREFLIGHT_FAILED' }
    if ($Message -match 'debug port') { return 'PORT_IN_USE' }
    'LANE_STEP_FAILED'
}

function Get-RepairHint {
    # The exact Repair-Harness.ps1 invocation for THIS lane's journals (same text everywhere it is needed).
    param($Lane)
    $ids = (@($Lane.Phases | ForEach-Object { $_.RunId }) -join ', ')
    if (-not $ids) { $ids = $Lane.RunId }
    $sc = ConvertTo-PublicPath -Path $Lane.ShortcutDir -Lane $Lane
    "For EACH journal run tools/harness/Repair-Harness.ps1 -RunId <id> -ShortcutDir $sc (journals: $ids; <harness-root> is the per-user SnapmakerStudio-Harness folder). Without -ShortcutDir the destinations do not match and Repair-Harness exits 2."
}

function Get-EvidenceSchema {
    if ($script:EvidenceSchema) { return $script:EvidenceSchema }
    $hex = '^[0-9a-f]{64}$'
    $ver = $script:SourceVersionPattern
    $rid = $script:PhaseIdPattern
    $lid = $script:RunIdPattern
    $counts = @{ T = 'int' }
    $code = @{ T = 'enum'; V = $script:ReasonCodes }
    $script:EvidenceSchema = @{
        schema           = @{ T = 'enum'; V = @($script:EvidenceSchemaId) }
        lane             = @{ T = 'enum'; V = @($script:LaneLabel, $script:UpgradeLaneLabel) }
        laneKind         = @{ T = 'enum'; V = @('acceptance', 'hardware', 'demo', 'capture') }
        identity         = @{ T = 'enum'; V = @('acceptance') }
        status           = @{ T = 'enum'; V = @('pass', 'fail') }
        installerSha256  = @{ T = 'pattern'; P = $hex; Null = $true }
        sourceVersion    = @{ T = 'pattern'; P = $ver; Null = $true }
        templateSha256   = @{ T = 'pattern'; P = $hex; Null = $true }
        rewrappedOnDemand = @{ T = 'bool' }
        installDir       = @{ T = 'pattern'; P = '^install\\h[0-9a-f]{32}$'; Null = $true }
        installArguments = @{ T = 'enum'; V = @($script:InstallArgumentsText) }
        preflight        = @{ T = 'object'; Props = @{
                updateCheck     = @{ T = 'enum'; V = @('absent', 'auto_check=false'); Null = $true }
                webView2Runtime = @{ T = 'pattern'; P = '^[0-9][0-9.]{0,31}$'; Null = $true }
            } }
        keptInstall      = @{ T = 'bool' }
        repair           = @{ T = 'object'; Null = $true; Props = @{
                journalIds = @{ T = 'array'; Item = @{ T = 'pattern'; P = $rid } }
                shortcutDir = @{ T = 'pattern'; P = '^run\\h[0-9a-f]{32}\\shortcuts$' }
            } }
        journals         = @{ T = 'array'; Item = @{ T = 'object'; Props = @{
                    runId = @{ T = 'pattern'; P = $rid }
                    installExitCode = @{ T = 'int'; Null = $true }
                    finalized = @{ T = 'bool'; Null = $true }
                } } }
        orphanedInstall  = @{ T = 'object'; Null = $true; Props = @{
                files = $counts
                dir = @{ T = 'pattern'; P = '^install\\h[0-9a-f]{32}$' }
            } }
        uninstallOutcome = @{ T = 'enum'; V = $script:UninstallOutcomes }
        errorCount       = $counts
        warningCount     = $counts
        reasonCodes      = @{ T = 'array'; Item = @{ T = 'object'; Props = @{ code = $code; count = $counts } } }
        warningCodes     = @{ T = 'array'; Item = @{ T = 'object'; Props = @{ code = $code; count = $counts } } }
        tripwire         = @{ T = 'object'; Props = @{ violations = $counts; added = $counts; changed = $counts; removed = $counts; leveldbChanged = $counts; structural = $counts } }
        shortcutFindings = $counts
        notProven        = @{ T = 'enum'; V = @($script:NotProven) }
    }
    $script:EvidenceSchema
}

function Test-EvidenceNode {
    # $null when $Value conforms to $Spec, else a short reason that never echoes the offending VALUE.
    param($Value, $Spec, [string]$At)
    if ($null -eq $Value) { if ($Spec.ContainsKey('Null') -and $Spec.Null) { return $null } else { return "$At is null" } }
    switch ($Spec.T) {
        'bool' { if ($Value -isnot [bool]) { return "$At is not a boolean" } }
        'int' { if ($Value -isnot [int] -and $Value -isnot [long]) { return "$At is not an integer" } }
        'enum' { if ($Value -isnot [string] -or $Spec.V -cnotcontains $Value) { return "$At is not an allowed enum value" } }
        'pattern' { if ($Value -isnot [string] -or $Value -cnotmatch $Spec.P) { return "$At does not match its fixed pattern" } }
        'array' {
            if ($Value -isnot [System.Collections.IList]) { return "$At is not an array" }
            $i = 0
            foreach ($item in $Value) { $r = Test-EvidenceNode -Value $item -Spec $Spec.Item -At "$At[$i]"; if ($r) { return $r }; $i++ }
        }
        'object' {
            if ($Value -isnot [System.Collections.IDictionary]) { return "$At is not an object" }
            foreach ($k in $Value.Keys) {
                if (-not $Spec.Props.ContainsKey([string]$k)) { return "$At has a property that is not in the closed schema" }
            }
            foreach ($k in $Spec.Props.Keys) {
                if (-not $Value.Contains($k)) { return "$At.$k is missing" }
                $r = Test-EvidenceNode -Value $Value[$k] -Spec $Spec.Props[$k] -At "$At.$k"; if ($r) { return $r }
            }
        }
        default { return "$At has an unknown schema type" }
    }
    $null
}

function Test-HarnessLaneEvidenceSchema {
    # $null when the evidence conforms to the CLOSED schema (unknown property, value outside its enum or strict pattern, wrong type => a reason).
    [CmdletBinding()]
    param([Parameter(Mandatory)][AllowNull()]$Evidence)
    $schema = Get-EvidenceSchema
    Test-EvidenceNode -Value $Evidence -Spec @{ T = 'object'; Props = $schema } -At 'evidence'
}

function Assert-HarnessLaneEvidenceSchema {
    [CmdletBinding()]
    param([Parameter(Mandatory)][AllowNull()]$Evidence)
    $r = Test-HarnessLaneEvidenceSchema -Evidence $Evidence
    if ($r) { throw "REPORT_WRITE_FAILED: the lane evidence is not closed-schema ($r)" }
}

function Get-EvidencePatternValues {
    # The string VALUES of pattern-typed fields (not property names, enums or fixed constants).
    param($Value, $Spec)
    if ($null -eq $Value -or $null -eq $Spec) { return }
    switch ($Spec.T) {
        'pattern' { if ($Value -is [string]) { $Value } }
        'object' { if ($Value -is [System.Collections.IDictionary]) { foreach ($k in $Spec.Props.Keys) { if ($Value.Contains($k)) { Get-EvidencePatternValues -Value $Value[$k] -Spec $Spec.Props[$k] } } } }
        'array' { if ($Value -is [System.Collections.IList]) { foreach ($i in $Value) { Get-EvidencePatternValues -Value $i -Spec $Spec.Item } } }
    }
}

function Write-HarnessLaneEvidence {
    <# The ONLY way harness scripts persist lane evidence. The object must already be the closed-schema object produced by
       Get-HarnessLaneEvidence; it is validated against the whitelist (unknown property, or a value outside its enum, strict pattern or type => REPORT_WRITE_FAILED)
       and serialised as-is: nothing is scrubbed-then-saved. A SECONDARY check then looks for absolute paths, UNC or
       forward-slash drive paths, the user name and any -Redact value (for example a printer address) in the output; it
       should find nothing, and if it does the write FAILS closed (nothing is persisted) instead of editing the text. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [Parameter(Mandatory)][AllowNull()]$Evidence, [Parameter(Mandatory)][string]$Path, [string[]]$Redact = @())
    Assert-HarnessLaneEvidenceSchema -Evidence $Evidence
    $json = $Evidence | ConvertTo-Json -Depth 8
    $plain = $json.Replace('\\', '\')
    $user = Get-CurrentUserName
    $patternValues = @(Get-EvidencePatternValues -Value $Evidence -Spec @{ T = 'object'; Props = (Get-EvidenceSchema) })
    $bad = ($plain -match '(?<![A-Za-z0-9<])[A-Za-z]:[\\/]') -or ($plain -match '\\\\[^\\\s"]+\\') -or ($plain -match '(?<![A-Za-z0-9])/(?:home|Users|tmp|var|etc)/') -or
        ($user -and $user.Length -ge 3 -and @($patternValues | Where-Object { $_.IndexOf($user, [StringComparison]::OrdinalIgnoreCase) -ge 0 }).Count -gt 0)
    foreach ($r in $Redact) { if ($r -and $json.IndexOf($r, [StringComparison]::OrdinalIgnoreCase) -ge 0) { $bad = $true } }
    if ($bad) { throw 'REPORT_WRITE_FAILED: the closed-schema evidence still contains sensitive-looking content; nothing was written.' }
    Set-Content -LiteralPath $Path -Value $json -Encoding utf8
    $Path
}
$script:AcceptanceReportEvidence = '<harness-root>\run\<run id>\evidence'

function Test-HarnessAcceptanceReportFile {
    <# Re-reads the FINAL on-disk acceptance.json and validates it against its own fixed structure: exactly the keys
       schema_version / lane / checks / passed / total / evidence; the literal schema version and evidence constant; integer
       totals consistent with the checks; every check exactly {name (printable ASCII), ok (bool)}; and the lane block valid
       against the closed lane-evidence schema. Returns $null when valid, else a short reason. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)
    $j = $null
    try { $j = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -AsHashtable -DateKind String } catch { return 'the report is not valid JSON' }
    if ($j -isnot [System.Collections.IDictionary]) { return 'the report is not an object' }
    $want = @('schema_version', 'lane', 'checks', 'passed', 'total', 'evidence')
    foreach ($k in $j.Keys) { if ($want -cnotcontains [string]$k) { return 'the report has a key that is not in its fixed structure' } }
    foreach ($k in $want) { if (-not $j.Contains($k)) { return "the report is missing $k" } }
    if ($j['schema_version'] -cne 'acceptance/3') { return 'schema_version is not the literal' }
    if ($j['evidence'] -cne $script:AcceptanceReportEvidence) { return 'evidence is not the fixed constant' }
    if (($j['passed'] -isnot [int] -and $j['passed'] -isnot [long]) -or ($j['total'] -isnot [int] -and $j['total'] -isnot [long])) { return 'totals are not integers' }
    if ($j['checks'] -isnot [System.Collections.IList]) { return 'checks is not an array' }
    $ok = 0
    foreach ($c in $j['checks']) {
        if ($c -isnot [System.Collections.IDictionary] -or $c.Count -ne 2 -or -not $c.Contains('name') -or -not $c.Contains('ok')) { return 'a check is not exactly {name, ok}' }
        if ($c['name'] -isnot [string] -or $c['name'] -cnotmatch '^[ -~]{1,200}$') { return 'a check name is not printable ASCII' }
        if ($c['ok'] -isnot [bool]) { return 'a check ok flag is not a boolean' }
        if ($c['ok']) { $ok++ }
    }
    if ($j['total'] -ne $j['checks'].Count -or $j['passed'] -ne $ok) { return 'totals do not match the checks' }
    if ($null -ne $j['lane']) { $r = Test-HarnessLaneEvidenceSchema -Evidence $j['lane']; if ($r) { return "the lane block: $r" } }
    $null
}

function Write-HarnessAcceptanceReport {
    <# Assembles acceptance.json from CLOSED parts: fixed literals, the check names (scrubbed with -ScrubName BEFORE assembly,
       values only) with pass/fail, integer totals, and the closed-schema lane block, which is inserted AFTER any scrubbing and
       never modified again. The final on-disk file is then re-read and validated; any mismatch deletes it and throws
       REPORT_WRITE_FAILED. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [AllowNull()]$LaneEvidence, [Parameter(Mandatory)]$Checks, [scriptblock]$ScrubName)
    if ($null -ne $LaneEvidence) { Assert-HarnessLaneEvidenceSchema -Evidence $LaneEvidence }
    $rows = @(foreach ($c in $Checks) {
            $n = [string]$c.name
            if ($ScrubName) { $n = [string](& $ScrubName $n) }
            [ordered]@{ name = $n; ok = [bool]$c.ok }
        })
    $report = [ordered]@{
        schema_version = 'acceptance/3'
        lane           = $LaneEvidence
        checks         = $rows
        passed         = [int]@($rows | Where-Object { $_.ok }).Count
        total          = [int]$rows.Count
        evidence       = $script:AcceptanceReportEvidence
    }
    Set-Content -LiteralPath $Path -Value ($report | ConvertTo-Json -Depth 10) -Encoding utf8
    $why = Test-HarnessAcceptanceReportFile -Path $Path
    if ($why) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
        throw "REPORT_WRITE_FAILED: the final acceptance report failed its closed-structure validation ($why); the file was deleted."
    }
    $Path
}

function Publish-HarnessLaneReport {
    <# Shared tail of the three evidence-writing scripts. Prints the scrubbed findings and errors, persists the lane evidence
       through the closed-schema writer and returns the exit code to use (0 only when the lane and the evidence write both
       succeeded). A writer failure (locked file, disk error, residual sensitive content) FAILS the lane. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, $Result, [Parameter(Mandatory)][string]$EvidencePath, [string[]]$Redact = @(), [switch]$Failed)
    $rc = if ($Failed) { 1 } else { 0 }
    if (-not $Result) { return 1 }
    try {
        $dir = Split-Path -Parent $EvidencePath
        if ($dir) { [void][IO.Directory]::CreateDirectory($dir) }
        $closed = Get-HarnessLaneEvidence -Lane $Lane -Failed:$Failed
        [void](Write-HarnessLaneEvidence -Lane $Lane -Evidence $closed -Path $EvidencePath -Redact $Redact)
    } catch {
        Write-Host "FAIL  REPORT_WRITE_FAILED: lane evidence could not be written: $(Protect-LaneText -Text $_.Exception.Message -Lane $Lane)"
        $rc = 1
    }
    foreach ($f in $Lane.Findings) { Write-Host "FAIL  $f" }
    foreach ($e in $Lane.Errors) { Write-Host "FAIL  harness cleanup: $e" }
    if ($Result.ExitCode -ne 0) { $rc = 1 }
    $rc
}

function ConvertTo-PublicPath {
    # Evidence never carries absolute local paths.
    param([string]$Path, $Lane)
    if ([string]::IsNullOrEmpty($Path)) { return $Path }
    $t = $Path
    foreach ($pair in @(@($Lane.Root, '<harness-root>'), @($script:RepoRoot, '<repo>'), @([IO.Path]::GetTempPath().TrimEnd('\'), '<temp>'))) {
        if ($pair[0]) { $t = $t.Replace($pair[0], $pair[1], [StringComparison]::OrdinalIgnoreCase) }
    }
    $t
}

# ---------------------------------------------------------------------------
# Production-state preflight (S1 / N2 / N3) - READ-ONLY
# ---------------------------------------------------------------------------

function Get-ProductionStatePaths {
    # Resolved via known folders, never env vars. Tests redirect through hooks.
    $b = $script:Identity.Production
    [ordered]@{
        Roaming = Get-Hook 'RoamingDir' (Join-Path ([Environment]::GetFolderPath('ApplicationData')) $b.BundleId)
        Local   = Get-Hook 'LocalDir' (Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) $b.BundleId)
        Engine  = Get-Hook 'EngineDir' (Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) $b.EngineDataDirName)
    }
}

function Assert-ProductionIdle {
    # Refuse if the PRODUCTION exe is running (by the HarnessIdentity process name). Never closes it.
    [CmdletBinding()]
    param()
    $prov = Get-Hook 'ProductionProcessProvider'
    $running = if ($prov) { Test-ProductionRunning -ProcessProvider $prov } else { Test-ProductionRunning }
    if ($running) { throw 'Refused: the production Snapmaker Studio process is running. Close it yourself; the harness will not.' }
}

function Assert-UpdateCheckPreflight {
    <# S1/N3. The published app writes %APPDATA%\<bundle id>\update_check.json when auto_check is on and due, and
       its location cannot be redirected. Refuse unless the file is ABSENT or parses as JSON with auto_check
       explicitly false. Corrupt / unreadable / ambiguous / reparse => refuse. Read-only; never flips the preference;
       never prints the file's contents. #>
    [CmdletBinding()]
    param([string]$Path)
    if (-not $Path) { $Path = Join-Path (Get-ProductionStatePaths).Roaming 'update_check.json' }
    $attr = $null
    try { $attr = [IO.File]::GetAttributes($Path) }
    catch [System.IO.FileNotFoundException], [System.IO.DirectoryNotFoundException] { return 'absent' }
    catch { throw 'Refused: update_check.json could not be inspected (ambiguous state).' }
    if (($attr -band [IO.FileAttributes]::ReparsePoint) -or ($attr -band [IO.FileAttributes]::Directory)) { throw 'Refused: update_check.json is not a plain file (ambiguous state).' }
    $text = $null
    try {
        $fs = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
        try { $sr = [IO.StreamReader]::new($fs); $text = $sr.ReadToEnd() } finally { $fs.Dispose() }
    } catch { throw 'Refused: update_check.json is unreadable (ambiguous state).' }
    $j = $null
    try { $j = $text | ConvertFrom-Json -AsHashtable -ErrorAction Stop } catch { throw 'Refused: update_check.json is not valid JSON.' }
    if ($j -isnot [System.Collections.IDictionary] -or -not $j.Contains('auto_check') -or $j['auto_check'] -isnot [bool]) {
        throw 'Refused: update_check.json has no explicit boolean auto_check.'
    }
    if ($j['auto_check'] -ne $false) { throw 'Refused: the maintainer has update auto-check ON (auto_check true). Launching any build could write the shared update_check.json. The harness never changes that preference; turn it off yourself first.' }
    'auto_check=false'
}

function Assert-WebView2Runtime {
    [CmdletBinding()]
    param()
    $v = Get-WebView2RuntimeVersion
    if (-not $v) { throw 'Refused: the WebView2 runtime is not installed. The harness never runs or installs the bootstrapper; install the runtime yourself.' }
    $v
}

function Assert-DebugPortFree {
    [CmdletBinding()]
    param([Parameter(Mandatory)][int]$Port)
    if ($Port -lt 1024 -or $Port -gt 65535) { throw "Refused: debug port $Port is out of range." }
    # A just-closed app can hold the port for a moment; wait a bounded time, then refuse.
    $free = Wait-ForCondition -TimeoutSeconds ([double](Get-Hook 'PortWaitSeconds' 10)) -Condition { Test-LoopbackPortFree -Port $Port }
    if (-not $free) { throw "Refused: debug port $Port is already in use." }
}

function Assert-LaunchPreflight {
    # Run BEFORE every launch of the app (warm-up, relaunches, every phase).
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [switch]$SkipPort)
    Assert-ProductionIdle
    $uc = Assert-UpdateCheckPreflight
    $wv = Assert-WebView2Runtime
    if (-not $SkipPort) { Assert-DebugPortFree -Port $Lane.DebugPort }
    $Lane.Preflight['updateCheck'] = $uc
    $Lane.Preflight['webView2Runtime'] = $wv
}

# ---------------------------------------------------------------------------
# Tripwire (detection only; NEVER restores or deletes)
# ---------------------------------------------------------------------------

function Get-DirectoryStateSnapshot {
    <# Names, sizes, mtimes (files) and names (directories) of a directory, read-only, without following reparse
       points. Local Storage leveldb files are additionally hashed with share-read. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)
    $snap = [ordered]@{ Exists = $false; Entries = [ordered]@{} }
    $attr = $null
    try { $attr = [IO.File]::GetAttributes($Path) }
    catch [System.IO.FileNotFoundException], [System.IO.DirectoryNotFoundException] { return $snap }
    catch { $snap.Exists = $true; $snap.Entries['<uninspectable>'] = 'inspect-error'; return $snap }
    $snap.Exists = $true
    if ($attr -band [IO.FileAttributes]::ReparsePoint) { $snap.Entries['<root>'] = 'reparse'; return $snap }
    $rootLen = $Path.TrimEnd('\').Length + 1
    $stack = [System.Collections.Generic.Stack[string]]::new()
    $stack.Push($Path.TrimEnd('\'))
    while ($stack.Count -gt 0) {
        $dir = $stack.Pop()
        $entries = @()
        try { $entries = @([IO.Directory]::EnumerateFileSystemEntries($dir)) } catch { $snap.Entries["<unlistable>:$($dir.Substring([Math]::Min($rootLen, $dir.Length)))"] = 'enum-error'; continue }
        foreach ($e in $entries) {
            $rel = $e.Substring($rootLen)
            $a = $null
            try { $a = [IO.File]::GetAttributes($e) } catch { $snap.Entries[$rel] = 'gone-or-uninspectable'; continue }
            if ($a -band [IO.FileAttributes]::ReparsePoint) { $snap.Entries[$rel] = 'reparse'; continue }
            if ($a -band [IO.FileAttributes]::Directory) { $snap.Entries[$rel] = 'dir'; $stack.Push($e); continue }
            try {
                $fi = [IO.FileInfo]::new($e)
                $desc = "file|$($fi.Length)|$($fi.LastWriteTimeUtc.Ticks)"
                if ($rel -like 'EBWebView\Default\Local Storage\leveldb\*') {
                    $fs = [IO.File]::Open($e, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
                    try { $desc += '|' + (([BitConverter]::ToString([Security.Cryptography.SHA256]::HashData($fs)) -replace '-', '').ToLowerInvariant()) } finally { $fs.Dispose() }
                }
                $snap.Entries[$rel] = $desc
            } catch { $snap.Entries[$rel] = 'file|unreadable' }
        }
    }
    $snap
}

function Get-ProductionStateSnapshot {
    [CmdletBinding()]
    param()
    $p = Get-ProductionStatePaths
    [ordered]@{
        Roaming = Get-DirectoryStateSnapshot -Path $p.Roaming
        Local   = Get-DirectoryStateSnapshot -Path $p.Local
        Engine  = Get-DirectoryStateSnapshot -Path $p.Engine
    }
}

function Compare-DirectorySnapshot {
    # PRIVACY: COUNTS and CATEGORIES only. A file or directory name from a production folder is never reported
    # (production folders can hold private model names). Local Storage leveldb files are reported only as a
    # hashed-changed count.
    param($Before, $After, [string]$Label)
    $out = New-Object System.Collections.Generic.List[string]
    $ldbPrefix = 'EBWebView\Default\Local Storage\leveldb\'
    $add = 0; $rem = 0; $chg = 0; $ldb = 0
    foreach ($k in $After.Entries.Keys) {
        if (-not $Before.Entries.Contains($k)) { $add++ }
        elseif ($Before.Entries[$k] -cne $After.Entries[$k]) { if ($k.StartsWith($ldbPrefix, [StringComparison]::OrdinalIgnoreCase)) { $ldb++ } else { $chg++ } }
    }
    foreach ($k in $Before.Entries.Keys) { if (-not $After.Entries.Contains($k)) { $rem++ } }
    $w = { param($n) if ($n -eq 1) { 'entry' } else { 'entries' } }
    if ($add) { $out.Add("$Label : $add $(& $w $add) ADDED") }
    if ($chg) { $out.Add("$Label : $chg $(& $w $chg) CHANGED") }
    if ($ldb) { $out.Add("$Label : $ldb Local Storage leveldb file(s) hash-CHANGED") }
    if ($rem) { $out.Add("$Label : $rem $(& $w $rem) REMOVED") }
    $out
}
function Compare-ProductionStateSnapshot {
    <# Expectations: Roaming <bundle id> stays ABSENT if it was absent; Local <bundle id> may go absent->EMPTY only;
       the production engine dir is detect-only (any change is reported); anything that already existed must be
       unchanged. Returns violations (string[]); empty = clean. Report only: nothing here touches the disk. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Before, [Parameter(Mandatory)]$After)
    $v = New-Object System.Collections.Generic.List[string]
    if (-not $Before.Roaming.Exists) {
        if ($After.Roaming.Exists) { $v.Add('Roaming <bundle id> folder APPEARED (it must stay absent)') }
    } elseif (-not $After.Roaming.Exists) { $v.Add('Roaming <bundle id> folder DISAPPEARED') }
    else { foreach ($x in (Compare-DirectorySnapshot $Before.Roaming $After.Roaming 'Roaming <bundle id>')) { $v.Add($x) } }

    if (-not $Before.Local.Exists) {
        if ($After.Local.Exists -and $After.Local.Entries.Count -gt 0) { $v.Add("Local <bundle id> folder appeared with $($After.Local.Entries.Count) entr(ies) (only absent->empty is allowed)") }
    } elseif (-not $After.Local.Exists) { $v.Add('Local <bundle id> folder DISAPPEARED') }
    else { foreach ($x in (Compare-DirectorySnapshot $Before.Local $After.Local 'Local <bundle id>')) { $v.Add($x) } }

    if (-not $Before.Engine.Exists) {
        if ($After.Engine.Exists) { $v.Add('production engine data folder APPEARED') }
    } elseif (-not $After.Engine.Exists) { $v.Add('production engine data folder DISAPPEARED') }
    else { foreach ($x in (Compare-DirectorySnapshot $Before.Engine $After.Engine 'production engine data')) { $v.Add($x) } }
    $v.ToArray()
}

function Test-ProductionTripwire {
    # Snapshot now, compare with the lane baseline, record findings. Report only.
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [string]$Stage = 'check')
    $now = Get-ProductionStateSnapshot
    $viol = @(Compare-ProductionStateSnapshot -Before $Lane.Baseline -After $now)
    foreach ($x in $viol) {
        Add-LaneFinding -Lane $Lane -Text "[tripwire:$Stage] $x" -Code 'TRIPWIRE_VIOLATION'
        $tc = $Lane.TripwireCounts
        if ($x -match '(\d+) Local Storage leveldb file\(s\) hash-CHANGED') { $tc.leveldbChanged += [int]$Matches[1] }
        elseif ($x -match ': (\d+) entr(?:y|ies) ADDED') { $tc.added += [int]$Matches[1] }
        elseif ($x -match ': (\d+) entr(?:y|ies) CHANGED') { $tc.changed += [int]$Matches[1] }
        elseif ($x -match ': (\d+) entr(?:y|ies) REMOVED') { $tc.removed += [int]$Matches[1] }
        else { $tc.structural += 1 }
    }
    $viol
}

# ---------------------------------------------------------------------------
# Real Start Menu / Desktop: READ-ONLY absence assertion (never write/restore there)
# ---------------------------------------------------------------------------

function Get-AcceptanceShortcutFindings {
    # Test-Path only. Returns the acceptance .lnk files found in the REAL known folders (should be none: /NS).
    [CmdletBinding()]
    param()
    $name = "$($script:Identity.Acceptance.ProductName).lnk"
    $dirs = @(
        (Get-Hook 'RealStartMenuDir' ([Environment]::GetFolderPath('Programs'))),
        (Get-Hook 'RealDesktopDir' ([Environment]::GetFolderPath('DesktopDirectory'))))
    $found = @()
    foreach ($d in $dirs) {
        if ([string]::IsNullOrWhiteSpace($d)) { throw 'Refused: a real Start Menu / Desktop known folder could not be resolved, so absence cannot be asserted.' }
        if (Test-Path -LiteralPath (Join-Path $d $name)) { $found += (Join-Path (Split-Path -Leaf $d) $name) }
    }
    $found
}

function Assert-NoAcceptanceShortcutInRealFolders {
    [CmdletBinding()]
    param()
    $f = @(Get-AcceptanceShortcutFindings)
    if ($f.Count -gt 0) { throw "Refused: an acceptance-identity shortcut exists in a real Start Menu / Desktop folder ($($f -join ', ')); /NS must have created none. Remove it yourself; the harness never writes there." }
}

# ---------------------------------------------------------------------------
# Installer lane
# ---------------------------------------------------------------------------

function Get-InstallerArguments {
    <# EXACTLY: /S /NCRC /NS /D=<install dir>. /D= is LAST and UNQUOTED (NSIS rule). Never /P, never an app-data flag. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$InstallDir)
    if ($InstallDir -match '["\r\n]') { throw 'Refused: install dir contains a quote or newline.' }
    "/S /NCRC /NS /D=$InstallDir"
}

function Get-UninstallerArguments { '/S' }   # silent only; no app-data delete flag exists in the acceptance template

function Resolve-HarnessBuild {
    <# Returns @{ InstallerPath; AttestationPath; Rewrapped } for ONE installer. Either an already-rewrapped installer
       + its attestation, or a REAL installer + expected sha256 that tools/release/rewrap_installer.ps1 rewraps. #>
    [CmdletBinding()]
    param(
        [string]$InstallerPath, [string]$AttestationPath,
        [string]$RealInstaller, [string]$ExpectedSha256, [string]$Sha256SumsPath, [string]$SourceVersion,
        [string]$HarnessRoot, [string]$What = 'installer'
    )
    $haveRewrapped = [bool]($InstallerPath -or $AttestationPath)
    $haveReal = [bool]($RealInstaller -or $ExpectedSha256 -or $SourceVersion)
    if ($haveRewrapped -and $haveReal) { throw "Refused: give $What either -InstallerPath + -AttestationPath (rewrapped) OR -RealInstaller + -ExpectedSha256 + -SourceVersion (rewrap on demand), not both." }
    if ($haveRewrapped) {
        Assert-NoWildcardPath -Path $InstallerPath -What "$What -InstallerPath"
        Assert-NoWildcardPath -Path $AttestationPath -What "$What -AttestationPath"
        return @{ InstallerPath = [IO.Path]::GetFullPath($InstallerPath); AttestationPath = [IO.Path]::GetFullPath($AttestationPath); Rewrapped = $false }
    }
    if (-not $haveReal) { throw "Refused: no $What supplied. Pass a REWRAPPED acceptance installer (-InstallerPath + -AttestationPath) or a verified real installer to rewrap (-RealInstaller + -ExpectedSha256 + -SourceVersion). There is no installer auto-discovery." }
    Assert-NoWildcardPath -Path $RealInstaller -What "$What -RealInstaller"
    if ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') { throw "Refused: $What -ExpectedSha256 must be a 64-hex sha256." }
    if ([string]::IsNullOrWhiteSpace($SourceVersion)) { throw "Refused: $What -SourceVersion is required for a rewrap." }
    $rp = @{ InstallerPath = $RealInstaller; ExpectedSha256 = $ExpectedSha256; SourceVersion = $SourceVersion }
    if ($Sha256SumsPath) { Assert-NoWildcardPath -Path $Sha256SumsPath -What "$What -Sha256SumsPath"; $rp.Sha256SumsPath = $Sha256SumsPath }
    if ($HarnessRoot) { $rp.HarnessRoot = $HarnessRoot }
    $r = Invoke-RewrapScript -Parameters $rp
    @{ InstallerPath = [string]$r.InstallerPath; AttestationPath = [string]$r.AttestationPath; Rewrapped = $true }
}

function Resolve-AuthorizedBuild {
    # Assert-InstallerAllowed = copy-then-hash-then-launch authorization; returns the harness-owned staged copy.
    param($Spec, [string]$HarnessRoot, [string]$What)
    try { Assert-InstallerAllowed -Path $Spec.InstallerPath -AttestationPath $Spec.AttestationPath -HarnessRoot $HarnessRoot }
    catch { throw "Refused ($What): only a REWRAPPED acceptance-identity installer with its attestation may run on this workstation (a production installer is always refused). $($_.Exception.Message)" }
}

# ---------------------------------------------------------------------------
# Lane lifecycle
# ---------------------------------------------------------------------------

function Start-HarnessLane {
    <# Acquires the machine-wide lock, runs the preflights, takes the tripwire baseline, rewraps on demand,
       authorizes and stages every installer. Installs nothing. On ANY failure the lock is released and the error
       rethrown (nothing was changed yet). The caller MUST run Complete-HarnessLane in a finally block. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][ValidateSet('acceptance', 'hardware', 'demo', 'capture')][string]$Kind,
        [string]$InstallerPath, [string]$AttestationPath,
        [string]$RealInstaller, [string]$ExpectedSha256, [string]$Sha256SumsPath, [string]$SourceVersion,
        [string]$UpgradeFromInstallerPath, [string]$UpgradeFromAttestationPath,
        [string]$UpgradeFromRealInstaller, [string]$UpgradeFromExpectedSha256, [string]$UpgradeFromSourceVersion,
        [string]$HarnessRoot, [string]$RunId, [int]$DebugPort = 9333, [switch]$KeepInstall
    )
    if (-not $RunId) { $RunId = New-HarnessRunId }
    elseif ($RunId -cnotmatch $script:RunIdPattern) { throw 'Refused: a run id is opaque and generated; only the generated format is accepted.' }
    $root = Get-HarnessRoot -HarnessRoot $HarnessRoot
    $paths = Get-HarnessLanePaths -Root $root -RunId $RunId
    if (Test-Path -LiteralPath $paths.RunDir) { throw "Refused: run directory already exists: $RunId" }
    if (Test-Path -LiteralPath $paths.InstallDir) { throw "Refused: install directory already exists: $RunId" }
    if ($DebugPort -lt 1024 -or $DebugPort -gt 65535) { throw "Refused: debug port $DebugPort is out of range." }

    $lockArgs = @{ HarnessRoot = $HarnessRoot }
    $mx = Get-Hook 'MutexName'
    if ($mx) { $lockArgs.MutexName = $mx }
    $lock = Enter-HarnessLock @lockArgs
    try {
        # M2: never start over an unfinished run (a pending journal, or a live acceptance registration, means a
        # previous install may still be on disk and a new run would orphan it).
        $jdir = Get-JournalDir -HarnessRoot $HarnessRoot
        $pending = @()
        if (Test-Path -LiteralPath $jdir) { $pending = @(Get-ChildItem -LiteralPath $jdir -Filter '*.json' -File -ErrorAction Stop | Where-Object { $_.Name -notlike '*.recovered.json' }) }
        if ($pending.Count -gt 0) { throw "Refused: $($pending.Count) unfinished harness journal(s) exist. A previous run left an acceptance install or an unfinished recovery; run tools/harness/Repair-Harness.ps1 first: for EACH journal -RunId <id> -ShortcutDir <harness-root>\run\<id>\shortcuts (pending journal ids: $(($pending | ForEach-Object { $_.BaseName }) -join ', ')); without -ShortcutDir the destinations do not match and it exits 2. Exit codes: 0 = nothing left, 1 = error, 2 = journal missing/corrupt, 3 = a manual step such as uninstalling the acceptance build is needed. See docs/internal/HARNESS_ISOLATION.md." }
        $ukey = (Get-LaneRegistryRoot).TrimEnd('\') + '\' + $script:Identity.Registry.UninstallKeyParent + '\' + $script:Identity.Acceptance.ProductName
        if (Test-Path -LiteralPath $ukey) { throw 'Refused: the acceptance-identity uninstall key already exists, so a previous acceptance install is still registered. Uninstall it (or run tools/harness/Repair-Harness.ps1) before starting another run. See docs/internal/HARNESS_ISOLATION.md.' }
        $lane = [ordered]@{
            Name = $Name; Kind = $Kind; RunId = $RunId; HarnessRootArg = $HarnessRoot; DebugPort = $DebugPort; KeepInstall = [bool]$KeepInstall
            Root = $root; RunDir = $paths.RunDir; InstallDir = $paths.InstallDir; ProfileDir = $paths.ProfileDir; DataDir = $paths.DataDir
            EvidenceDir = $paths.EvidenceDir; ShortcutDir = $paths.ShortcutDir
            AppExe = (Join-Path $paths.InstallDir $script:Identity.Acceptance.MainBinaryName)
            Lock = $lock; Tracked = [System.Collections.Generic.List[object]]::new(); Phases = [System.Collections.Generic.List[object]]::new()
            Builds = @{}; Baseline = $null; Findings = [System.Collections.Generic.List[string]]::new()
            Errors = [System.Collections.Generic.List[string]]::new(); Warnings = [System.Collections.Generic.List[string]]::new()
            Preflight = [ordered]@{}; ErrorCodes = [System.Collections.Generic.List[string]]::new(); FindingCodes = [System.Collections.Generic.List[string]]::new(); WarningCodes = [System.Collections.Generic.List[string]]::new(); TripwireCounts = [ordered]@{ added = 0; changed = 0; removed = 0; leveldbChanged = 0; structural = 0 }; ShortcutFindingCount = 0; Orphan = $null; UninstallLaunched = $false; UninstallOutcome = 'NotRun'; Completed = $false; Result = $null; Upgrade = $false
        }
        Assert-LaunchPreflight -Lane $lane
        Assert-NoAcceptanceShortcutInRealFolders
        $lane.Baseline = Get-ProductionStateSnapshot

        $spec = Resolve-HarnessBuild -InstallerPath $InstallerPath -AttestationPath $AttestationPath -RealInstaller $RealInstaller -ExpectedSha256 $ExpectedSha256 `
            -Sha256SumsPath $Sha256SumsPath -SourceVersion $SourceVersion -HarnessRoot $HarnessRoot -What 'installer'
        $lane.Builds['Primary'] = @{ Spec = $spec; Staged = (Resolve-AuthorizedBuild -Spec $spec -HarnessRoot $HarnessRoot -What 'installer') }
        if ([string]$lane.Builds['Primary'].Staged.Version -cnotmatch $script:SourceVersionPattern) {
            Add-LaneWarning -Lane $lane -Text 'the attestation source version is not a strict numeric release version; it is NOT recorded in the evidence' -Code INSTALLER_PREFLIGHT_FAILED
            Write-Host 'NOTE  the attestation source version is not a strict numeric release version; it will not be recorded in the evidence.'
        }
        if ($UpgradeFromInstallerPath -or $UpgradeFromAttestationPath -or $UpgradeFromRealInstaller -or $UpgradeFromExpectedSha256 -or $UpgradeFromSourceVersion) {
            $old = Resolve-HarnessBuild -InstallerPath $UpgradeFromInstallerPath -AttestationPath $UpgradeFromAttestationPath -RealInstaller $UpgradeFromRealInstaller `
                -ExpectedSha256 $UpgradeFromExpectedSha256 -Sha256SumsPath $Sha256SumsPath -SourceVersion $UpgradeFromSourceVersion -HarnessRoot $HarnessRoot -What 'upgrade-from installer'
            $lane.Builds['UpgradeFrom'] = @{ Spec = $old; Staged = (Resolve-AuthorizedBuild -Spec $old -HarnessRoot $HarnessRoot -What 'upgrade-from installer') }
            $lane.Upgrade = $true
        }
        foreach ($d in @($paths.RunDir, $paths.EvidenceDir, (Join-Path $paths.ShortcutDir 'StartMenu'), (Join-Path $paths.ShortcutDir 'Desktop'))) {
            [void](Assert-HarnessPathInside -Path $d -Root $root -What 'lane directory')
            [void][IO.Directory]::CreateDirectory($d)
        }
        $lane
    } catch {
        try { Exit-HarnessLock -Lock $lock } catch { }
        throw
    }
}

function Get-LaneGuardArgs {
    param($Lane)
    @{ HarnessRoot = $Lane.HarnessRootArg }
}

function Get-LaneRegistryRoot { Get-Hook 'RegistryRoot' 'HKCU:\Software' }

function Register-HarnessProcess {
    <# Local tracked list (authoritative for kills) + best-effort journal record. Kind 'App' = image must be inside the
       harness tree; Kind 'Tool' = image must equal the exact image recorded at start. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [Parameter(Mandatory)]$Process, [ValidateSet('App', 'Tool')][string]$Kind = 'App', [string]$Label = '')
    $info = Get-LiveProcessInfo -ProcessId $Process.Id
    if (-not $info) { return $null }
    $entry = [ordered]@{ Pid = [int]$Process.Id; StartTicks = $info.StartTicks; Path = $info.Path; Kind = $Kind; Label = $Label; Process = $Process }
    $Lane.Tracked.Add($entry)
    # Journal only app launches with a known image (a null path would make the journal fail validation).
    if ($Lane.Phases.Count -gt 0 -and $Kind -eq 'App' -and $info.Path -and $Label -notmatch '^(installer|uninstaller)') {
        try { [void](Add-JournalProcess -Journal $Lane.Phases[$Lane.Phases.Count - 1].Journal -ProcessId $Process.Id -HarnessRoot $Lane.HarnessRootArg) }
        catch { Add-LaneWarning -Lane $Lane -Text "journal could not record pid $($Process.Id) ($Label): $($_.Exception.Message)" -Code JOURNAL_RECORD_FAILED }
    }
    $entry
}

function Stop-HarnessTrackedProcess {
    <# Verified force-kill of ONE tracked process. Never by name. Kills only if the pid is alive AND its start time still
       equals the recorded one AND its image is still what we recorded (App: inside the harness tree; Tool: identical image
       path). Anything else is left alone. Returns a status string. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [Parameter(Mandatory)]$Entry)
    $live = Get-LiveProcessInfo -ProcessId $Entry.Pid
    if (-not $live) { return 'gone' }
    if ($live.StartTicks -ne [int64]$Entry.StartTicks) { return 'start-time-mismatch' }
    if (-not $live.Path) { return 'image-unknown' }
    if ($Entry.Kind -eq 'App') {
        if (-not (Test-PathContainedNoReparse -Path $live.Path -Root $Lane.Root)) { return 'image-outside-harness' }
    } else {
        if (-not $Entry.Path -or -not $live.Path.Equals([string]$Entry.Path, [StringComparison]::OrdinalIgnoreCase)) { return 'image-mismatch' }
    }
    Stop-ProcessById -ProcessId $Entry.Pid
    'killed'
}

function Register-HarnessChildren {
    <# Registers (as tracked, App kind) the descendants of a tracked process whose image is inside the install dir
       (the frozen sidecar). Needed so a leftover sidecar can be stopped by verified pid, never by name. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [Parameter(Mandatory)][int]$ParentPid)
    $all = @(Get-Win32ProcessList)
    $found = New-Object System.Collections.Generic.List[int]
    $frontier = @($ParentPid)
    for ($depth = 0; $depth -lt 8 -and $frontier.Count -gt 0; $depth++) {
        $next = @()
        foreach ($c in ($all | Where-Object { $_.ParentProcessId -in $frontier })) { $next += $c.ProcessId; $found.Add($c.ProcessId) }
        $frontier = $next
    }
    foreach ($childPid in $found) {
        $c = $all | Where-Object ProcessId -eq $childPid | Select-Object -First 1
        if (-not $c -or -not $c.ExecutablePath -or -not (Test-PathContainedNoReparse -Path $c.ExecutablePath -Root $Lane.InstallDir)) { continue }
        if (@($Lane.Tracked | Where-Object { $_.Pid -eq $childPid }).Count -gt 0) { continue }
        $info = Get-LiveProcessInfo -ProcessId $childPid
        if ($info) { $Lane.Tracked.Add([ordered]@{ Pid = $childPid; StartTicks = $info.StartTicks; Path = $info.Path; Kind = 'App'; Label = 'child'; Process = $null }) }
    }
}

function Get-HarnessSidecarProcesses {
    <# Read-only: sidecar processes whose image is inside THIS lane's install dir (path-contained, not name-only). #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [int]$ParentPid)
    $name = $script:Identity.Acceptance.SidecarName
    @(Get-Win32ProcessList | Where-Object {
            $_.Name -ieq $name -and $_.ExecutablePath -and (Test-PathContainedNoReparse -Path $_.ExecutablePath -Root $Lane.InstallDir) -and
            (-not $ParentPid -or $_.ParentProcessId -eq $ParentPid)
        })
}

function Test-IsDescendantOf {
    param([int]$ProcessId, [int]$AncestorPid, $All)
    $cur = $ProcessId
    for ($i = 0; $i -lt 32; $i++) {
        if ($cur -eq $AncestorPid) { return $true }
        $row = $All | Where-Object ProcessId -eq $cur | Select-Object -First 1
        if (-not $row -or $row.ParentProcessId -eq $cur -or $row.ParentProcessId -le 0) { return $false }
        $cur = $row.ParentProcessId
    }
    $false
}

function Assert-CdpOwnedByTrackedApp {
    # M4: whatever listens on the debug port must belong to the app process we just started.
    [CmdletBinding()]
    param([Parameter(Mandatory)][int]$Port, [Parameter(Mandatory)][int]$AppPid)
    $owner = Get-PortOwnerPid -Port $Port
    if ($null -eq $owner) { throw "Refused: nothing owns debug port $Port (cannot attribute the CDP endpoint to the tracked app)." }
    if (-not (Test-IsDescendantOf -ProcessId $owner -AncestorPid $AppPid -All @(Get-Win32ProcessList))) {
        throw "Refused: the CDP endpoint on port $Port belongs to pid $owner, which is not part of the tracked app's process tree."
    }
}

function Wait-ForCondition {
    param([scriptblock]$Condition, [double]$TimeoutSeconds, [double]$IntervalSeconds = 0.5)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ($true) {
        if (& $Condition) { return $true }
        if ([DateTime]::UtcNow -ge $deadline) { return $false }
        Start-Sleep -Milliseconds ([int]($IntervalSeconds * 1000))
    }
}

function Start-HarnessApp {
    <# THE one function that launches the app exe. Every warm-up, relaunch and phase goes through it.
       Isolation variables go ONLY to the child. Refuses unless every isolation path is inside the harness directory,
       the exe is the renamed acceptance binary inside the harness install dir, production is idle, update_check.json is
       absent-or-off, the WebView2 runtime exists and the debug port is free. After launch: the isolated profile must exist
       (hard failure), and the CDP endpoint must belong to the tracked app tree. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [string[]]$Arguments = @(), [double]$SettleSeconds = 0, [string]$Label = 'app')
    if ($Lane.Completed) { throw 'Refused: the lane is already completed.' }
    Assert-LaneIsolation -Lane $Lane
    try { Assert-LaunchPreflight -Lane $Lane }
    catch { Add-LaneError -Lane $Lane -Text "launch preflight: $($_.Exception.Message)" -Code (Get-PreflightReasonCode $_.Exception.Message); throw }
    $env1 = @{
        WEBVIEW2_USER_DATA_FOLDER                 = $Lane.ProfileDir
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS     = "--remote-debugging-port=$($Lane.DebugPort) --remote-allow-origins=*"
        SNAPSTUDIO_DATA_DIR                       = $Lane.DataDir
    }
    $proc = Start-HarnessChildProcess -FilePath $Lane.AppExe -ArgumentList $Arguments -Environment $env1 -WorkingDirectory $Lane.InstallDir
    $entry = $null
    try { $entry = Register-HarnessProcess -Lane $Lane -Process $proc -Kind App -Label $Label }
    catch { Add-LaneWarning -Lane $Lane -Text "launch: the app (pid $($proc.Id)) could not be registered: $($_.Exception.Message)" -Code APP_LAUNCH_FAILED }
    $fail = {
        param($msg, $code)
        Add-LaneError -Lane $Lane -Text "launch postflight: $msg" -Code $code
        # B3: the sweep does not depend on the parent still being alive or on the entry existing.
        Stop-HarnessLaunchTree -Lane $Lane -Entry $entry -ParentPid $proc.Id
        throw $msg
    }
    # S4: register the descendants for cleanup IMMEDIATELY, before any postflight can fail (best effort: a failure here
    # must not stop the failure path below from sweeping).
    try { Register-HarnessChildren -Lane $Lane -ParentPid $proc.Id }
    catch { Add-LaneWarning -Lane $Lane -Text "launch: descendant registration failed: $($_.Exception.Message)" -Code APP_LAUNCH_FAILED }
    if (-not $entry) { & $fail "Refused: the launched app (pid $($proc.Id)) was not found alive; it cannot be tracked." APP_LAUNCH_FAILED }
    if (-not $entry.Path -or -not (Test-PathContainedNoReparse -Path $entry.Path -Root $Lane.InstallDir)) { & $fail 'Refused: the launched process image is not inside the harness install dir.' APP_LAUNCH_FAILED }

    $wvWait = [double](Get-Hook 'WebViewWaitSeconds' 30)
    # S1 / N2: exactly <profile>\EBWebView. No alternative layout is accepted.
    $profileOk = Wait-ForCondition -TimeoutSeconds $wvWait -Condition {
        Test-Path -LiteralPath (Join-Path $Lane.ProfileDir 'EBWebView') -PathType Container
    }
    if (-not $profileOk) { & $fail 'FAILED: <profile>\EBWebView was not created under the harness profile dir; the app may be using a shared profile. Aborted (app and descendants stopped).' PROFILE_CHECK_FAILED }

    $cdpWait = [double](Get-Hook 'CdpWaitSeconds' 60)
    $cdpOk = Wait-ForCondition -TimeoutSeconds $cdpWait -Condition { Test-CdpEndpoint -Port $Lane.DebugPort }
    if (-not $cdpOk) { & $fail "FAILED: the CDP endpoint on port $($Lane.DebugPort) never answered." CDP_CHECK_FAILED }
    try { Assert-CdpOwnedByTrackedApp -Port $Lane.DebugPort -AppPid $proc.Id } catch { & $fail $_.Exception.Message CDP_CHECK_FAILED }

    Register-HarnessChildren -Lane $Lane -ParentPid $proc.Id
    if ($SettleSeconds -gt 0) { Start-Sleep -Milliseconds ([int]($SettleSeconds * 1000)) }
    [pscustomobject]@{ Process = $proc; Pid = $proc.Id; StartTicks = $entry.StartTicks; CdpUrl = "http://127.0.0.1:$($Lane.DebugPort)"; Entry = $entry }
}

function Stop-HarnessLaunchTree {
    # Launch-failure cleanup: re-enumerate the app's descendants, then graceful close, then a VERIFIED force-stop of every
    # tracked pid in the tree (start time + image checked in Stop-HarnessTrackedProcess).
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, $Entry, [Parameter(Mandatory)][int]$ParentPid)
    try { Register-HarnessLaunchSweep -Lane $Lane -ParentPid $ParentPid } catch { Add-LaneWarning -Lane $Lane -Text "launch sweep failed: $($_.Exception.Message)" -Code APP_LAUNCH_FAILED }
    $targets = @($Lane.Tracked | Where-Object { $_.Pid -eq $ParentPid -or $_.Label -eq 'child' -or ($Entry -and $_.Pid -eq $Entry.Pid) })
    if ($Entry -and $Entry.Process) { try { $Entry.Process.Refresh(); if (-not $Entry.Process.HasExited) { [void]$Entry.Process.CloseMainWindow(); [void]$Entry.Process.WaitForExit(5000) } } catch { } }
    foreach ($t in $targets) { [void](Stop-HarnessTrackedProcess -Lane $Lane -Entry $t); [void]$Lane.Tracked.Remove($t) }
}

function Register-HarnessLaunchSweep {
    <# Fallback enumeration for a failed launch. Independent of the parent being alive: read-only. Candidates are
       (1) every descendant of the launched pid (a dead parent still shows as ParentProcessId of its orphans),
       (2) every process whose image is inside the harness install dir, and
       (3) every process whose command line references the harness install dir or profile dir.
       A candidate is only REGISTERED when it is alive; the later stop re-verifies start time and that the image is inside
       the harness tree, so nothing outside the harness can be stopped. Each source failure is a warning, not a stop. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [Parameter(Mandatory)][int]$ParentPid)
    $cand = New-Object System.Collections.Generic.HashSet[int]
    try {
        $all = @(Get-Win32ProcessList)
        $frontier = @($ParentPid)
        for ($d = 0; $d -lt 8 -and $frontier.Count -gt 0; $d++) {
            $next = @()
            foreach ($c in ($all | Where-Object { $_.ParentProcessId -in $frontier })) { $next += $c.ProcessId; [void]$cand.Add([int]$c.ProcessId) }
            $frontier = $next
        }
        foreach ($c in $all) { if ($c.ExecutablePath -and (Test-PathContainedNoReparse -Path $c.ExecutablePath -Root $Lane.InstallDir)) { [void]$cand.Add([int]$c.ProcessId) } }
    } catch { Add-LaneWarning -Lane $Lane -Text "launch sweep: process enumeration failed: $($_.Exception.Message)" -Code APP_LAUNCH_FAILED }
    try {
        foreach ($c in @(Get-Win32CommandLines)) {
            if ($c.CommandLine -and ($c.CommandLine.IndexOf($Lane.InstallDir, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or $c.CommandLine.IndexOf($Lane.ProfileDir, [StringComparison]::OrdinalIgnoreCase) -ge 0)) { [void]$cand.Add([int]$c.ProcessId) }
        }
    } catch { Add-LaneWarning -Lane $Lane -Text "launch sweep: command-line query failed: $($_.Exception.Message)" -Code APP_LAUNCH_FAILED }
    foreach ($id in $cand) {
        if ($id -eq $PID -or $id -eq $ParentPid) { continue }
        if (@($Lane.Tracked | Where-Object { $_.Pid -eq $id }).Count -gt 0) { continue }
        $info = Get-LiveProcessInfo -ProcessId $id
        if ($info) { $Lane.Tracked.Add([ordered]@{ Pid = $id; StartTicks = $info.StartTicks; Path = $info.Path; Kind = 'App'; Label = 'child'; Process = $null }) }
    }
}

function Stop-HarnessApp {
    <# Graceful first (CloseMainWindow, wait), then a VERIFIED force-kill of tracked pids only. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, $App, [double]$GraceSeconds = 15)
    $targets = if ($App) { @($Lane.Tracked | Where-Object { $_.Pid -eq $App.Pid -or $_.Label -eq 'child' }) } else { @($Lane.Tracked | Where-Object { $_.Kind -eq 'App' }) }
    foreach ($t in $targets) {
        if ($t.Process -and $t.Label -ne 'child') {
            try {
                $t.Process.Refresh()
                if (-not $t.Process.HasExited) { [void]$t.Process.CloseMainWindow(); [void]$t.Process.WaitForExit([int]($GraceSeconds * 1000)) }
            } catch { }
        }
    }
    Start-Sleep -Milliseconds 500
    $status = @()
    foreach ($t in $targets) { $status += [pscustomobject]@{ Pid = $t.Pid; Status = (Stop-HarnessTrackedProcess -Lane $Lane -Entry $t) } }
    foreach ($t in $targets) { [void]$Lane.Tracked.Remove($t) }
    $status
}

function Resolve-HarnessToolPath {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Name)
    $base = [IO.Path]::GetFileNameWithoutExtension($Name)
    if ($script:AllowedTools -cnotcontains $base.ToLowerInvariant()) { throw "Refused: '$Name' is not an allowed tool ($($script:AllowedTools -join ', '))." }
    if ($Name -match '[\\/]') {
        if (-not (Test-Path -LiteralPath $Name -PathType Leaf)) { throw "Refused: tool not found: $Name" }
        return [IO.Path]::GetFullPath($Name)
    }
    $cmd = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cmd) { throw "Refused: tool '$Name' was not found on PATH." }
    $cmd.Source
}

function Start-HarnessTool {
    <# Starts an allow-listed helper (node probe server, ffmpeg) and tracks it. Long-lived tools are stopped through
       Stop-HarnessTool (graceful where the tool supports it) or Complete-HarnessLane (verified kill, never by name). #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [Parameter(Mandatory)][string]$Tool, [string[]]$ArgumentList = @(), [hashtable]$Environment = @{},
        [switch]$Hidden, [switch]$RedirectInput, [switch]$RedirectOutput, [string]$Label = '')
    if ($Lane.Completed) { throw 'Refused: the lane is already completed.' }
    try { $path = Resolve-HarnessToolPath -Name $Tool } catch { Add-LaneError -Lane $Lane -Text "tool: $($_.Exception.Message)" -Code TOOL_NOT_ALLOWED; throw }
    $p = Start-HarnessChildProcess -FilePath $path -ArgumentList $ArgumentList -Environment $Environment -Hidden:$Hidden -RedirectInput:$RedirectInput -RedirectOutput:$RedirectOutput
    $entry = Register-HarnessProcess -Lane $Lane -Process $p -Kind Tool -Label $(if ($Label) { $Label } else { $Tool })
    [pscustomobject]@{ Process = $p; Pid = $p.Id; Entry = $entry }
}

function Stop-HarnessTool {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [Parameter(Mandatory)]$Handle, [switch]$QuitOnStdin, [double]$GraceSeconds = 15)
    $p = $Handle.Process
    try {
        if ($QuitOnStdin -and -not $p.HasExited) { $p.StandardInput.WriteLine('q'); $p.StandardInput.Flush(); [void]$p.WaitForExit([int]($GraceSeconds * 1000)) }
    } catch { }
    $st = 'gone'
    if ($Handle.Entry) { $st = Stop-HarnessTrackedProcess -Lane $Lane -Entry $Handle.Entry; [void]$Lane.Tracked.Remove($Handle.Entry) }
    $st
}

function Invoke-HarnessTool {
    <# Runs an allow-listed tool (node, ffmpeg) synchronously, tracked while it runs, output captured. Returns Output +
       ExitCode. Extra environment goes to the CHILD only. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [Parameter(Mandatory)][string]$Tool, [Parameter(Mandatory)][string[]]$ArgumentList, [hashtable]$Environment = @{}, [int]$TimeoutSeconds = 900)
    if ($Lane.Completed) { throw 'Refused: the lane is already completed.' }
    try { $path = Resolve-HarnessToolPath -Name $Tool } catch { Add-LaneError -Lane $Lane -Text "tool: $($_.Exception.Message)" -Code TOOL_NOT_ALLOWED; throw }
    $p = Start-HarnessChildProcess -FilePath $path -ArgumentList $ArgumentList -Environment $Environment -RedirectOutput -Hidden
    $entry = Register-HarnessProcess -Lane $Lane -Process $p -Kind Tool -Label "$Tool-run"
    $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync()
    if (-not $p.WaitForExit($TimeoutSeconds * 1000)) {
        if ($entry) { [void](Stop-HarnessTrackedProcess -Lane $Lane -Entry $entry) }
        throw "$Tool run timed out after $TimeoutSeconds s."
    }
    $p.WaitForExit()
    if ($entry) { [void]$Lane.Tracked.Remove($entry) }
    $text = ($o.Result + $e.Result)
    [pscustomobject]@{ ExitCode = $p.ExitCode; Output = @($text -split "\r?\n" | Where-Object { $_ -ne '' }) }
}

function Invoke-HarnessNode {
    # A CDP check phase: node, synchronously, tracked, output captured.
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [Parameter(Mandatory)][string[]]$ArgumentList, [hashtable]$Environment = @{}, [int]$TimeoutSeconds = 900)
    Invoke-HarnessTool -Lane $Lane -Tool 'node' -ArgumentList $ArgumentList -Environment $Environment -TimeoutSeconds $TimeoutSeconds
}

function Install-HarnessBuild {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [ValidateSet('Primary', 'UpgradeFrom')][string]$Which = 'Primary', [int]$TimeoutSeconds = 300)
    try { Install-HarnessBuildCore -Lane $Lane -Which $Which -TimeoutSeconds $TimeoutSeconds }
    catch {
        # A timeout is recorded once, by Complete-HarnessLane (INSTALL_TIMEOUT); everything else is a preflight/guard refusal.
        if ($_.Exception.Message -notmatch '^Installer timed out' -and -not $_.Exception.Data['LaneRecorded']) {
            Add-LaneError -Lane $Lane -Text "install: $($_.Exception.Message)" -Code INSTALLER_PREFLIGHT_FAILED
            # a phase that was added but never ran must not be counted a second time by Complete-HarnessLane
            if ($Lane.Phases.Count -gt 0 -and $null -eq $Lane.Phases[$Lane.Phases.Count - 1].InstallExitCode) { $Lane.Phases[$Lane.Phases.Count - 1].ErrorRecorded = $true }
        }
        throw
    }
}

function Install-HarnessBuildCore {
    <# One install phase: journal (armed) BEFORE the installer starts -> Confirm-InstallerUnchanged -> launch the staged copy
       with the exact argument string -> record ownedAfter. One journal per phase. Never throws on a non-zero installer exit
       (returns it); throws on any guard/journal refusal. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [ValidateSet('Primary', 'UpgradeFrom')][string]$Which = 'Primary', [int]$TimeoutSeconds = 300)
    if ($Lane.Completed) { throw 'Refused: the lane is already completed.' }
    $b = $Lane.Builds[$Which]
    if (-not $b) { throw "Refused: no '$Which' build was prepared for this lane." }
    Assert-LaneIsolation -Lane $Lane -ForInstall
    $phaseRunId = if ($Lane.Phases.Count -eq 0) { $Lane.RunId } else { "$($Lane.RunId)-u$($Lane.Phases.Count + 1)" }
    $g = Get-LaneGuardArgs -Lane $Lane
    $reg = Get-LaneRegistryRoot
    $j = New-HarnessJournal -RunId $phaseRunId -InstallDir $Lane.InstallDir -InstallVersion $b.Staged.Version -RegistryRoot $reg -ShortcutDir $Lane.ShortcutDir @g
    $phase = [ordered]@{ RunId = $phaseRunId; Which = $Which; Journal = $j; InstallerSha256 = $b.Staged.Sha256; Version = $b.Staged.Version; InstallExitCode = $null; Finalized = $null }
    $Lane.Phases.Add($phase)
    Assert-NoAcceptanceShortcutInRealFolders
    Assert-HarnessPathInside -Path $Lane.InstallDir -Root $Lane.Root -What 'install dir' | Out-Null
    [void](Confirm-InstallerUnchanged -Path $b.Staged.Path -ExpectedSha256 $b.Staged.Sha256 @g)
    $proc = Start-HarnessChildProcess -FilePath $b.Staged.Path -ArgumentString (Get-InstallerArguments -InstallDir $Lane.InstallDir) -Hidden
    $entry = Register-HarnessProcess -Lane $Lane -Process $proc -Kind App -Label "installer-$Which"
    if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
        if ($entry) { [void](Stop-HarnessTrackedProcess -Lane $Lane -Entry $entry) }
        $phase.InstallExitCode = -1
        throw "Installer timed out after $TimeoutSeconds s."
    }
    if ($entry) { [void]$Lane.Tracked.Remove($entry) }
    $phase.InstallExitCode = $proc.ExitCode
    try { $phase.Journal = Set-JournalOwnedAfter -Journal $j -InstallerSha256 $b.Staged.Sha256 -RegistryRoot $reg -ShortcutDir $Lane.ShortcutDir @g }
    catch {
        Add-LaneError -Lane $Lane -Text "install: the journal could not be completed: $($_.Exception.Message)" -Code JOURNAL_RECORD_FAILED
        $_.Exception.Data['LaneRecorded'] = $true
        $phase.ErrorRecorded = $true
        throw
    }
    $f = @(Get-AcceptanceShortcutFindings)
    if ($f.Count -gt 0) { $Lane.ShortcutFindingCount += $f.Count; Add-LaneFinding -Lane $Lane -Text "[shortcuts] an acceptance shortcut appeared in a real Start Menu/Desktop folder ($($f -join ', ')); /NS should create none. Not removed (the harness never writes there)." -Code SHORTCUT_ASSERTION_FAILED }
    [pscustomobject]@{ ExitCode = $proc.ExitCode; RunId = $phaseRunId; InstallerSha256 = $b.Staged.Sha256; Version = $b.Staged.Version }
}

function Get-Win32CommandLines {
    # Read-only: ProcessId + CommandLine of every process (finds the NSIS temp-copy uninstaller started with _?=<install dir>).
    @(Get-CimInstance Win32_Process -ErrorAction Stop | ForEach-Object { [pscustomobject]@{ ProcessId = [int]$_.ProcessId; CommandLine = [string]$_.CommandLine } })
}

function Get-InstallDirFileList {
    # Seam: STRICT enumeration (any error throws) of the files under the install dir; a reparse point anywhere is an error.
    param([Parameter(Mandatory)][string]$Dir)
    foreach ($d in @(Get-ChildItem -LiteralPath $Dir -Recurse -Force -Directory -ErrorAction Stop)) {
        if ($d.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'a reparse point exists under the install dir' }
    }
    @(Get-ChildItem -LiteralPath $Dir -Recurse -Force -File -ErrorAction Stop)
}

function Get-InstallDirFileCount {
    <# Returns the file count, or $null when the state is AMBIGUOUS (any enumeration error, unreadable subtree, reparse
       point). Callers must treat $null as "files may remain": never as zero. #>
    param([Parameter(Mandatory)][string]$Dir)
    try { [void][IO.File]::GetAttributes($Dir) }
    catch [System.IO.FileNotFoundException], [System.IO.DirectoryNotFoundException] { return 0 }
    catch { return $null }
    try { @(Get-InstallDirFileList -Dir $Dir).Count } catch { $null }
}

function Get-HandoffProcessCount {
    # Processes (other than this one) whose command line references the harness install dir. Waited for, NEVER killed.
    # Returns $null (UNKNOWN) when the process query fails: never "none found".
    param([Parameter(Mandatory)]$Lane)
    try { @(Get-Win32CommandLines | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine.IndexOf($Lane.InstallDir, [StringComparison]::OrdinalIgnoreCase) -ge 0 }).Count }
    catch { $null }
}

function Invoke-HarnessUninstall {
    <# Silent /S only, after Assert-UninstallerAllowed + Confirm-UninstallerUnchanged. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [int]$TimeoutSeconds = 180)
    if ($Lane.Phases.Count -eq 0) { return [pscustomobject]@{ Attempted = $false; ExitCode = $null; HandoffComplete = $true; DirFiles = 0; HandoffProcesses = 0; Reason = 'nothing was installed' } }
    $last = $Lane.Phases[$Lane.Phases.Count - 1]
    $g = Get-LaneGuardArgs -Lane $Lane
    $uPath = Join-Path $Lane.InstallDir $script:Identity.Acceptance.UninstallerName
    $allowed = Assert-UninstallerAllowed -Path $uPath -RunId $last.RunId -RegistryRoot (Get-LaneRegistryRoot) @g
    [void](Confirm-UninstallerUnchanged -Allowed $allowed)
    $Lane.UninstallLaunched = $true      # from here on any failure leaves the outcome UNKNOWN
    $proc = Start-HarnessChildProcess -FilePath $allowed.Path -ArgumentString (Get-UninstallerArguments) -Hidden
    $entry = Register-HarnessProcess -Lane $Lane -Process $proc -Kind App -Label 'uninstaller'
    if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
        if ($entry) { [void](Stop-HarnessTrackedProcess -Lane $Lane -Entry $entry) }
        throw "Uninstaller timed out after $TimeoutSeconds s."
    }
    if ($entry) { [void]$Lane.Tracked.Remove($entry) }
    # S3: the NSIS uninstaller may hand off to a temp copy (started with _?=<install dir>) and the parent exits at once.
    # Wait, bounded, for BOTH the install dir to hold no files AND no process to reference it. The hand-off child is never killed.
    $done = Wait-ForCondition -TimeoutSeconds ([double](Get-Hook 'ExitWaitSeconds' 30)) -Condition {
        $f = Get-InstallDirFileCount -Dir $Lane.InstallDir
        $q = Get-HandoffProcessCount -Lane $Lane
        ($null -ne $f) -and ($null -ne $q) -and $f -eq 0 -and $q -eq 0
    }
    $files = Get-InstallDirFileCount -Dir $Lane.InstallDir
    $procs = Get-HandoffProcessCount -Lane $Lane
    # $null (ambiguous / query failed) is never "clean".
    $ok = [bool]($done -and ($null -ne $files) -and ($null -ne $procs) -and $files -eq 0 -and $procs -eq 0)
    [pscustomobject]@{ Attempted = $true; ExitCode = $proc.ExitCode; HandoffComplete = $ok; DirFiles = $files; HandoffProcesses = $procs
        Reason = $(if ($ok) { $null } elseif ($null -eq $files -or $null -eq $procs) { 'uninstall hand-off state is unknown (directory or process query failed)' } else { 'uninstall hand-off did not complete' }) }
}

function Get-HarnessLaneEvidence {
    <# Builds the closed-schema evidence object FIELD BY FIELD from typed lane state. There is no pass-through of strings:
       every string is either a fixed constant or validated against a fixed pattern/enum, and anything that does not
       validate is DROPPED (null). Error / finding text is never read here; only their reason CODES and counts are. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane, [switch]$Failed)
    $schema = Get-EvidenceSchema
    $safe = { param($v, $field) if ($v -is [string] -and $schema[$field].T -eq 'pattern' -and $v -cmatch $schema[$field].P) { $v } else { $null } }
    $b = $Lane.Builds['Primary']
    $att = if ($b) { $b.Staged.Attestation } else { $null }
    $rid = $script:PhaseIdPattern
    $lid = $script:RunIdPattern
    $group = {
        param($codes)
        @($codes | Group-Object | Sort-Object Name | ForEach-Object { [ordered]@{ code = (Resolve-ReasonCode $_.Name); count = [int]$_.Count } })
    }
    # every error/finding maps to exactly one code: a list entry without a code counts as UNCLASSIFIED_ERROR
    $errCodes = @($Lane.ErrorCodes); for ($i = $errCodes.Count; $i -lt $Lane.Errors.Count; $i++) { $errCodes += 'UNCLASSIFIED_ERROR' }
    $finCodes = @($Lane.FindingCodes); for ($i = $finCodes.Count; $i -lt $Lane.Findings.Count; $i++) { $finCodes += 'UNCLASSIFIED_ERROR' }
    $warnCodes = @($Lane.WarningCodes); for ($i = $warnCodes.Count; $i -lt $Lane.Warnings.Count; $i++) { $warnCodes += 'UNCLASSIFIED_ERROR' }
    # A failed run always carries at least one reason code.
    if ($Failed -and ($errCodes.Count + $finCodes.Count) -eq 0) { $errCodes += 'LANE_STEP_FAILED' }
    $tc = $Lane.TripwireCounts
    $uc = [string]$Lane.Preflight['updateCheck']
    $wv = [string]$Lane.Preflight['webView2Runtime']
    $outcome = [string]$Lane.UninstallOutcome
    $ev = [ordered]@{
        schema            = $script:EvidenceSchemaId
        lane              = if ($Lane.Upgrade) { $script:UpgradeLaneLabel } else { $script:LaneLabel }
        laneKind          = [string]$Lane.Kind
        identity          = 'acceptance'
        status            = if ($Failed -or $Lane.Errors.Count -gt 0 -or $Lane.Findings.Count -gt 0) { 'fail' } else { 'pass' }
        installerSha256   = if ($b) { & $safe ([string]$b.Staged.Sha256) 'installerSha256' } else { $null }
        sourceVersion     = if ($att) { & $safe ([string]$att['source']['version']) 'sourceVersion' } else { $null }
        templateSha256    = if ($att) { & $safe ([string]$att['template']['sha256']) 'templateSha256' } else { $null }
        rewrappedOnDemand = if ($b) { [bool]$b.Spec.Rewrapped } else { $false }
        installDir        = if ($Lane.RunId -cmatch $lid) { "install\$($Lane.RunId)" } else { $null }
        installArguments  = $script:InstallArgumentsText
        preflight         = [ordered]@{
            updateCheck     = if ($uc -in 'absent', 'auto_check=false') { $uc } else { $null }
            webView2Runtime = if ($wv -cmatch '^[0-9][0-9.]{0,31}$') { $wv } else { $null }
        }
        keptInstall       = [bool]$Lane.KeepInstall
        repair            = if ($Lane.KeepInstall -and $Lane.RunId -cmatch $lid) {
            [ordered]@{ journalIds = @($Lane.Phases | ForEach-Object { $_.RunId } | Where-Object { $_ -cmatch $rid }); shortcutDir = "run\$($Lane.RunId)\shortcuts" }
        } else { $null }
        journals          = @($Lane.Phases | Where-Object { $_.RunId -cmatch $rid } | ForEach-Object {
                [ordered]@{
                    runId = [string]$_.RunId
                    installExitCode = if ($null -eq $_.InstallExitCode) { $null } else { [int]$_.InstallExitCode }
                    finalized = if ($null -eq $_.Finalized) { $null } else { [bool]$_.Finalized }
                } })
        orphanedInstall   = if ($Lane.Orphan -and $Lane.RunId -cmatch $lid) { [ordered]@{ files = [int]$Lane.Orphan.Files; dir = "install\$($Lane.RunId)" } } else { $null }
        uninstallOutcome  = if ($script:UninstallOutcomes -ccontains $outcome) { $outcome } else { 'Unknown' }
        errorCount        = [int]$Lane.Errors.Count
        warningCount      = [int]$Lane.Warnings.Count
        reasonCodes       = @(& $group @($errCodes + $finCodes))
        warningCodes      = @(& $group $warnCodes)
        tripwire          = [ordered]@{
            violations = @($finCodes | Where-Object { $_ -eq 'TRIPWIRE_VIOLATION' }).Count; added = [int]$tc.added; changed = [int]$tc.changed
            removed = [int]$tc.removed; leveldbChanged = [int]$tc.leveldbChanged; structural = [int]$tc.structural
        }
        shortcutFindings  = [int]$Lane.ShortcutFindingCount
        notProven         = $script:NotProven
    }
    Assert-HarnessLaneEvidenceSchema -Evidence $ev     # by-construction output is verified against the whitelist too
    $ev
}
function Complete-HarnessLane {
    <# ALWAYS-RUN cleanup, called from a finally block. Each step is isolated so a failure in one never skips the next:
       stop tracked processes (graceful, then verified kill) -> uninstall (unless -KeepInstall) -> journal recovery
       (unless -KeepInstall) -> final tripwire + real-folder shortcut check -> release the lock.
       -KeepInstall skips the uninstall AND the recovery (the journal stays pending), but does NOT skip tripwire reporting or the evidence, which states it. Never restores or deletes
       production state. Returns a result with ExitCode (0 only when everything is clean). #>
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Lane)
    if ($Lane.Completed) { return $Lane.Result }
    $res = [ordered]@{ ExitCode = 0; Uninstall = $null; Recovery = @(); Errors = $Lane.Errors; Findings = $Lane.Findings; Evidence = $null }
    $stepCodes = @{ 'stop-processes' = 'LANE_STEP_FAILED'; 'uninstall' = 'UNINSTALL_FAILED'; 'recovery' = 'RECOVERY_PENDING'; 'tripwire' = 'LANE_STEP_FAILED'; 'shortcut-check' = 'SHORTCUT_ASSERTION_FAILED'; 'evidence' = 'REPORT_WRITE_FAILED' }
    $step = { param($name, $sb) try { & $sb } catch { Add-LaneError -Lane $Lane -Text "${name}: $($_.Exception.Message)" -Code $(if ($stepCodes.ContainsKey($name)) { $stepCodes[$name] } else { 'LANE_STEP_FAILED' }) } }

    & $step 'stop-processes' {
        foreach ($t in @($Lane.Tracked | Where-Object { $_.Process -and $_.Kind -eq 'App' -and $_.Label -notmatch '^(installer|uninstaller)' -and $_.Label -ne 'child' })) {
            try { $t.Process.Refresh(); if (-not $t.Process.HasExited) { [void]$t.Process.CloseMainWindow(); [void]$t.Process.WaitForExit(15000) } } catch { }
        }
        foreach ($t in @($Lane.Tracked)) { [void](Stop-HarnessTrackedProcess -Lane $Lane -Entry $t) }
        $Lane.Tracked.Clear()
    }
    # An installer that failed, was killed or timed out is a lane failure on its own.
    foreach ($ph in $Lane.Phases) {
        if ($ph.Contains('ErrorRecorded') -and $ph.ErrorRecorded) { continue }
        if ($null -eq $ph.InstallExitCode) { Add-LaneError -Lane $Lane -Text "installer phase $($ph.RunId) did not complete (no exit code recorded)" -Code INSTALL_FAILED }
        elseif ($ph.InstallExitCode -eq -1) { Add-LaneError -Lane $Lane -Text "installer phase $($ph.RunId) timed out" -Code INSTALL_TIMEOUT }
        elseif ($ph.InstallExitCode -ne 0) { Add-LaneError -Lane $Lane -Text "installer phase $($ph.RunId) exited with code $($ph.InstallExitCode)" -Code INSTALL_FAILED }
    }
    if (-not $Lane.KeepInstall) {
        # Explicit uninstall outcome: NothingInstalled | NotLaunched (guard refused, nothing ran) | Success | Failed | Unknown.
        # ANY ambiguity (exception after launch, query failure, parent timeout) is Unknown: journal stays pending.
        $Lane.UninstallOutcome = 'NotRun'
        & $step 'uninstall' {
            try {
                $u = Invoke-HarnessUninstall -Lane $Lane
                $res.Uninstall = $u
                if (-not $u.Attempted) { $Lane.UninstallOutcome = 'NothingInstalled' }
                elseif ($u.ExitCode -eq 0 -and $u.HandoffComplete) { $Lane.UninstallOutcome = 'Success' }
                else {
                    # $null (ambiguous directory / failed process query) is UNKNOWN, a definite non-success is Failed.
                    $Lane.UninstallOutcome = if ($null -eq $u.DirFiles -or $null -eq $u.HandoffProcesses) { 'Unknown' } else { 'Failed' }
                    if ($u.ExitCode -ne 0) { Add-LaneError -Lane $Lane -Text "uninstaller exited with code $($u.ExitCode)" -Code UNINSTALL_FAILED }
                    if (-not $u.HandoffComplete) {
                        $fl = if ($null -eq $u.DirFiles) { 'unknown' } else { "$($u.DirFiles)" }
                        $pr = if ($null -eq $u.HandoffProcesses) { 'unknown' } else { "$($u.HandoffProcesses)" }
                        Add-LaneError -Lane $Lane -Text "uninstall hand-off did not complete (files left in the install dir: $fl; processes still referencing it: $pr); journal(s) kept pending. $(Get-RepairHint -Lane $Lane)" -Code $(if ($null -eq $u.DirFiles -or $null -eq $u.HandoffProcesses) { 'UNKNOWN_OUTCOME' } else { 'UNINSTALL_HANDOFF_INCOMPLETE' })
                    }
                }
            } catch {
                if ($Lane.UninstallLaunched) {
                    $Lane.UninstallOutcome = 'Unknown'
                    Add-LaneError -Lane $Lane -Text "uninstall outcome unknown (error: $($_.Exception.Message)); hand-off child may still be running; journal(s) kept pending and recovery NOT run. $(Get-RepairHint -Lane $Lane)" -Code UNKNOWN_OUTCOME
                } else {
                    $Lane.UninstallOutcome = 'NotLaunched'
                    Add-LaneError -Lane $Lane -Text "uninstall: $($_.Exception.Message)" -Code UNINSTALL_FAILED
                }
            }
        }
        & $step 'recovery' {
            # Recovery runs ONLY when: the uninstall explicitly succeeded (or never had anything to run), the strict install-dir
            # check is clean ($null = ambiguous is NOT clean), and the hand-off wait verified no referencing process.
            # Recovery treats unchanged registry/shortcut surfaces as 'noop' and FINALISES the journal, which would orphan a
            # partial/failed install, or an uninstall whose outcome is unknown.
            $oc = $Lane.UninstallOutcome
            $hold = {
                param($why, $code)
                foreach ($ph in $Lane.Phases) { $ph.Finalized = $false }
                Add-LaneError -Lane $Lane -Text "$why; journal(s) kept pending and recovery NOT run. $(Get-RepairHint -Lane $Lane) (see docs/internal/HARNESS_ISOLATION.md)" -Code $code
            }
            # ALLOW-list: only an explicit success (or "nothing to run") may proceed; anything else, including NotRun, holds.
            if ($oc -notin 'Success', 'NothingInstalled', 'NotLaunched') {
                & $hold $(if ($oc -eq 'Failed') { 'uninstall failed or its hand-off did not complete' } else { "uninstall outcome unknown (state: $oc)" }) $(if ($oc -eq 'Failed') { 'UNINSTALL_HANDOFF_INCOMPLETE' } else { 'UNKNOWN_OUTCOME' })
                return
            }
            $left = Get-InstallDirFileCount -Dir $Lane.InstallDir
            if ($null -eq $left) { & $hold 'the install directory state could not be determined (enumeration error); files may remain' UNKNOWN_OUTCOME; return }
            if ($left -gt 0) {
                $rel = "install\$($Lane.RunId)"
                $Lane.Orphan = @{ Files = $left; Dir = $rel }
                & $hold "orphaned acceptance install: $left files under $rel (remove the acceptance install under the harness install folder yourself first)" ORPHANED_INSTALL
                return
            }
            $g = Get-LaneGuardArgs -Lane $Lane
            $rec = @()
            for ($i = $Lane.Phases.Count - 1; $i -ge 0; $i--) {
                $ph = $Lane.Phases[$i]
                $r = Invoke-HarnessRecovery -RunId $ph.RunId -RegistryRoot (Get-LaneRegistryRoot) -ShortcutDir $Lane.ShortcutDir -SkipProcessKill @g
                $ph.Finalized = [bool]$r.Finalized
                $rec += $r
                if ($r.ExitCode -ne 0) { Add-LaneError -Lane $Lane -Text "recovery: run $($ph.RunId) needs a manual step (journal kept). $(Get-RepairHint -Lane $Lane)" -Code RECOVERY_PENDING }
            }
            $res.Recovery = $rec
        }
    }
    & $step 'tripwire' { [void](Test-ProductionTripwire -Lane $Lane -Stage 'final') }
    & $step 'shortcut-check' {
        $f = @(Get-AcceptanceShortcutFindings)
        if ($f.Count -gt 0) { $Lane.ShortcutFindingCount += $f.Count; Add-LaneFinding -Lane $Lane -Text "[shortcuts] acceptance shortcut present in a real Start Menu/Desktop folder at the end of the lane ($($f -join ', '))" -Code SHORTCUT_ASSERTION_FAILED }
    }
    # Release the lock BEFORE the evidence is built, so a lock-release failure is part of the persisted evidence (errorCount).
    try { Exit-HarnessLock -Lock $Lane.Lock } catch { Add-LaneError -Lane $Lane -Text "lock: $($_.Exception.Message)" -Code LOCK_RELEASE_FAILED }
    & $step 'evidence' { $res.Evidence = Get-HarnessLaneEvidence -Lane $Lane }
    $Lane.Completed = $true
    if ($Lane.Errors.Count -gt 0 -or $Lane.Findings.Count -gt 0) { $res.ExitCode = 1 }
    $Lane.Result = [pscustomobject]$res
    $Lane.Result
}

Export-ModuleMember -Function Assert-HarnessPathInside, Assert-NoWildcardPath, New-HarnessRunId, Get-HarnessLanePaths, Assert-LaneIsolation, ConvertTo-PublicPath,
    Get-ProductionStatePaths, Assert-ProductionIdle, Assert-UpdateCheckPreflight, Assert-WebView2Runtime, Assert-DebugPortFree, Assert-LaunchPreflight,
    Get-DirectoryStateSnapshot, Get-ProductionStateSnapshot, Compare-ProductionStateSnapshot, Test-ProductionTripwire,
    Get-AcceptanceShortcutFindings, Assert-NoAcceptanceShortcutInRealFolders, Get-InstallerArguments, Get-UninstallerArguments,
    Resolve-HarnessBuild, Start-HarnessLane, Register-HarnessProcess, Stop-HarnessTrackedProcess, Get-HarnessSidecarProcesses,
    Assert-CdpOwnedByTrackedApp, Start-HarnessApp, Stop-HarnessApp, Resolve-HarnessToolPath, Start-HarnessTool, Stop-HarnessTool, Invoke-HarnessTool, Invoke-HarnessNode,
    Install-HarnessBuild, Invoke-HarnessUninstall, Get-HarnessLaneEvidence, Complete-HarnessLane, Write-HarnessLaneEvidence, Write-HarnessAcceptanceReport, Test-HarnessAcceptanceReportFile, Test-HarnessLaneEvidenceSchema, Assert-HarnessLaneEvidenceSchema, Protect-LaneText, Publish-HarnessLaneReport, Get-InstallDirFileCount
