# Installed-build acceptance for Snapmaker Studio.
#
# Installs the built NSIS installer into an isolated directory, launches the
# installed application with its WebView2 opened for remote debugging, drives the
# real UI over CDP, then uninstalls and proves the machine is clean.
#
# Why this exists: every capability check before this ran against the dev server.
# That proves the feature works; it does not prove the installer ships it. This
# runs the shipped exe and the frozen sidecar.
#
# SAFETY, and these are not negotiable:
#  * Every process this script starts is tracked by PID and only those are ever
#    stopped. A Snapmaker Orca or other user process is never touched.
#  * The app runs with an isolated WebView2 profile and an isolated engine data
#    directory, so the maintainer's own library, recent files and settings are
#    neither read nor modified - which also keeps private model names out of the
#    screenshots this produces.
#  * If another Snapmaker Studio is already installed, its uninstall registry key
#    is exported first and restored afterwards.
#  * Nothing is installed to a shared location and nothing needs administrator.
#
# Usage:
#   pwsh -File tools/acceptance/run.ps1 [-Installer <path>] [-KeepInstall]
#        [-SpoolmanUrl host:port] [-BambuddyUrl host:port] [-SpoolEasePort 9403]
#
# v1.2: this run now also drives the spool-note and nozzle-confirmation phases
# in checks.mjs (W1-W9), no extra parameter needed - they run against the U1's
# stock placeholder host, with no printer present. A3.7: the acceptance.json
# report is now also swept for bare/bracketed IPv6 and IPv4 addresses, and the
# run fails outright if a supplied provider address survives redaction.

[CmdletBinding()]
param(
    [string]$Installer,
    [string]$WorkDir = (Join-Path $env:TEMP "snapstudio-acceptance"),
    [int]$DebugPort = 9333,
    [switch]$KeepInstall,
    # A previous installer. When given, it is installed first and its settings and
    # library are checked for survival across the upgrade - the path every existing
    # user actually takes to a new release.
    [string]$UpgradeFrom,
    # A material provider on this network, when one is available to test against.
    # Optional: without it the provider checks still prove the frozen build carries
    # the route, refuses an address that is not local, and claims nothing about
    # remaining filament. With it they prove the whole path inside the installed app.
    [string]$SpoolmanUrl,
    # A second provider. Studio normalises both into one contract, so with both
    # supplied the run also proves that equivalent facts produce equal decisions
    # in the installed build rather than only in the test suite.
    [string]$BambuddyUrl,
    [int]$SpoolEasePort = 9403,
    # Ports for the two throwaway probe servers this script owns. One counts the
    # requests it receives, which is how "no provider is configured" becomes a
    # measurement; the other answers every request with a redirect to a public
    # host, which is the only way to prove the shipped build refuses to follow
    # one off the local network.
    [int]$ProbePort = 9401,
    [int]$RedirectPort = 9402
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$started = @()          # every PID this script created
$checks = @()

function Add-Check($name, $ok, $detail = "") {
    $script:checks += [pscustomobject]@{ name = $name; ok = [bool]$ok; detail = $detail }
    $tag = if ($ok) { "PASS" } else { "FAIL" }
    Write-Host ("{0}  {1}{2}" -f $tag, $name, $(if ($detail) { "  - $detail" } else { "" }))
}

function Resolve-Installer {
    if ($Installer) { return (Resolve-Path $Installer).Path }
    $bundle = Join-Path $repo "desktop\src-tauri\target\release\bundle\nsis"
    $newest = Get-ChildItem $bundle -Filter "*_x64-setup.exe" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $newest) { throw "No installer found in $bundle - run `npm run release:windows` first." }
    return $newest.FullName
}

function Stop-Tracked {
    foreach ($procId in $script:started) {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 3
}

# --- prepare -----------------------------------------------------------------

$installer = Resolve-Installer
Write-Host "Installer: $installer"

$installDir = Join-Path $WorkDir "app"
$profileDir = Join-Path $WorkDir "webview-profile"
$dataDir    = Join-Path $WorkDir "engine-data"
$outDir     = Join-Path $WorkDir "evidence"
$sample     = Join-Path $repo "examples\demo_u1_showcase.3mf"
$sampleWork = Join-Path $WorkDir "demo_u1_showcase.3mf"

foreach ($d in @($WorkDir, $outDir)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
# Start from nothing. A WebView2 profile or engine data directory left by an
# earlier run carries recent-file names into the screenshots this produces, which
# is both a privacy problem and a reproducibility one.
foreach ($stale in @($installDir, $profileDir, $dataDir)) {
    if (Test-Path $stale) { Remove-Item $stale -Recurse -Force -ErrorAction SilentlyContinue }
}

# Work on a copy so the repository fixture is provably never written to.
Copy-Item $sample $sampleWork -Force
$sampleHashBefore = (Get-FileHash $sampleWork -Algorithm SHA256).Hash

# A sliced job. Studio does not slice, so the one input the installed build
# cannot make for itself is written here - shaped exactly like real Snapmaker
# Orca output from a physical U1.
# A painted project. Painting is the one thing a beginner cannot see in a file and
# Studio now reads before slicing, so the installed build is asked to read it from
# the frozen engine it actually ships.
#
# Two objects that cannot meet on a layer: one at the bottom painted with filament
# 2 and printing in filament 2, one thirty millimetres up painted with filament 3
# and printing in filament 3. The answers are therefore known before the app is
# asked - two painted slots, and a separation the geometry proves, which is the
# case that turns "cannot classify" into "possible with a planned swap". The
# attribute values are the format's own: "8" is filament 2, "0C" is filament 3.
$paintedWork = Join-Path $WorkDir "acceptance_painted.3mf"
$paintedModel = @'
<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><metadata name="BambuStudio:MmPaintingVersion">1</metadata><resources><object id="1" type="model"><mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/><vertex x="0" y="10" z="10"/></vertices><triangles><triangle v1="0" v2="1" v3="2" paint_color="8"/></triangles></mesh></object><object id="2" type="model"><mesh><vertices><vertex x="0" y="0" z="30"/><vertex x="10" y="0" z="30"/><vertex x="0" y="10" z="40"/></vertices><triangles><triangle v1="0" v2="1" v3="2" paint_color="0C"/></triangles></mesh></object></resources><build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/><item objectid="2" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></build></model>
'@
$paintedSettings = @'
{"printer_model":"Snapmaker U1","filament_colour":["#FF0000","#00FF00","#0000FF","#FFFFFF"],"filament_type":["PLA","PLA","PLA","PLA"],"layer_height":"0.2","initial_layer_print_height":"0.2","nozzle_diameter":["0.4","0.4","0.4","0.4"]}
'@
$paintedParts = @'
<config><object id="1"><part id="1" subtype="normal_part"><metadata key="extruder" value="2"/></part></object><object id="2"><part id="2" subtype="normal_part"><metadata key="extruder" value="3"/></part></object><plate><metadata key="plater_id" value="1"/></plate></config>
'@
if (Test-Path $paintedWork) { Remove-Item $paintedWork -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null
$zip = [System.IO.Compression.ZipFile]::Open($paintedWork, "Create")
foreach ($entry in @(
    @{ name = "3D/3dmodel.model"; body = $paintedModel },
    @{ name = "Metadata/project_settings.config"; body = $paintedSettings },
    @{ name = "Metadata/model_settings.config"; body = $paintedParts })) {
    $item = $zip.CreateEntry($entry.name)
    $writer = New-Object System.IO.StreamWriter($item.Open())
    $writer.Write($entry.body.Trim())
    $writer.Dispose()
}
$zip.Dispose()

$gcodeWork = Join-Path $WorkDir "acceptance_job.gcode"
@'
; HEADER_BLOCK_START
; generated by Snapmaker Orca 2.3.4 on 2026-08-23 at 10:00:00
; total layer number: 12
; max_z_height: 2.40
; HEADER_BLOCK_END
; EXECUTABLE_BLOCK_START
PRINT_START
M140 S60
M104 T1 S220
SET_PRINT_STATS_INFO TOTAL_LAYER=12 CURRENT_LAYER=0
T1
;LAYER_CHANGE
;Z:0.2
G1 X10 Y10 Z0.2 F1200
;LAYER_CHANGE
;Z:0.4
G1 X20 Y20 E1.0
;LAYER_CHANGE
;Z:0.6
G1 X30 Y30 E1.0
PRINT_END
; EXECUTABLE_BLOCK_END

; filament used [mm] = 0.00, 120.00, 0.00, 0.00
; filament used [g] = 0.00, 0.36, 0.00, 0.00
; total filament used [g] = 0.36
; total layers count = 12
; estimated printing time (normal mode) = 4m 10s

; CONFIG_BLOCK_START
; filament_type = PLA;PLA;PLA;PLA
; layer_height = 0.2
; nozzle_diameter = 0.4,0.4,0.4,0.4
; printable_area = 0.5x1,270.5x1,270.5x271,0.5x271
; printer_model = Snapmaker U1
; CONFIG_BLOCK_END
'@ | Set-Content $gcodeWork -Encoding utf8
$gcodeHashBefore = (Get-FileHash $gcodeWork -Algorithm SHA256).Hash

# An existing install of the same app shares the uninstall registry key. Save it.
$existing = Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' |
    Where-Object { (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).DisplayName -like '*Snapmaker Studio*' }
$backupReg = Join-Path $WorkDir "backup-uninstall.reg"
if ($existing) {
    reg export $existing.Name $backupReg /y | Out-Null
    Write-Host "Existing install detected; its registry entry was exported to $backupReg"
}

# Two throwaway servers this run owns. Started before the app so the provider
# checks can reach them, tracked by pid like everything else here, and stopped by
# the same Stop-Tracked that stops the app.
# The repository path contains a space, and an unquoted argument array hands
# node half a path. The first run of this failed with a connection refused that
# looked like a product defect and was this line.
$probeScript = '"' + (Join-Path $PSScriptRoot "probes.mjs") + '"'
$probes = Start-Process -FilePath "node" `
    -ArgumentList $probeScript, $ProbePort, $RedirectPort, $SpoolEasePort `
    -PassThru -WindowStyle Hidden
# Deliberately not in $started. That list is stopped and emptied every time the
# app is restarted with a different project, and the probes have to outlive
# those restarts - they are instruments for the whole run, not part of the app.
# They are stopped in the finally block instead, and only ever by their own pid.
$script:probePid = $probes.Id
Start-Sleep -Seconds 2
$probeUrl = "127.0.0.1:$ProbePort"
$redirectUrl = "127.0.0.1:$RedirectPort"
$env:SNAPSTUDIO_PROBE_URL = $probeUrl
$env:SNAPSTUDIO_REDIRECT_URL = $redirectUrl
$env:SNAPSTUDIO_BAMBUDDY_URL = $BambuddyUrl
$env:SNAPSTUDIO_SPOOLEASE_URL = "127.0.0.1:$SpoolEasePort"
$env:SNAPSTUDIO_SPOOLEASE_KEY = "Fx7-tEsT"
try {
    $probeAlive = (Invoke-WebRequest "http://$probeUrl/__hits" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200
} catch { $probeAlive = $false }
Add-Check "Probe servers this run owns are up" $probeAlive "count $ProbePort, redirect $RedirectPort"

try {
    # --- upgrade path --------------------------------------------------------
    if ($UpgradeFrom) {
        $old = (Resolve-Path $UpgradeFrom).Path
        Write-Host "Upgrading from $old"
        $prev = Start-Process -FilePath $old -ArgumentList '/S', '/NCRC', "/D=$installDir" -PassThru -Wait
        Add-Check "Previous version installs" ($prev.ExitCode -eq 0) "exit code $($prev.ExitCode)"

        # Give the old build a run so it creates the state a real user would have.
        $env:SNAPSTUDIO_DATA_DIR = $dataDir
        $warm = Start-Process -FilePath (Join-Path $installDir "snapmaker-studio-desktop.exe") -PassThru
        Start-Sleep -Seconds 12
        Stop-Process -Id $warm.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 4
        Remove-Item Env:SNAPSTUDIO_DATA_DIR -ErrorAction SilentlyContinue

        Add-Check "Previous version left state to migrate" (Test-Path $dataDir) $dataDir
        $script:stateBefore = @(Get-ChildItem $dataDir -Recurse -File -ErrorAction SilentlyContinue).Count
    }

    # --- install -------------------------------------------------------------
    $proc = Start-Process -FilePath $installer -ArgumentList '/S', '/NCRC', "/D=$installDir" -PassThru -Wait
    Add-Check "Scripted install completes" ($proc.ExitCode -eq 0) "exit code $($proc.ExitCode)"

    if ($UpgradeFrom) {
        $stateAfter = @(Get-ChildItem $dataDir -Recurse -File -ErrorAction SilentlyContinue).Count
        Add-Check "Upgrade keeps the user's data" ($stateAfter -ge $script:stateBefore) `
            "$script:stateBefore file(s) before, $stateAfter after"
        $installs = @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' |
            Where-Object { (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).DisplayName -like '*Snapmaker Studio*' })
        Add-Check "Upgrade does not leave two installations" ($installs.Count -le 1) `
            "$($installs.Count) registration(s)"

        # v1.0.0 release-prep: proves the registration was REPLACED, not
        # merely left alone (e.g. a broken upgrade that silently no-ops
        # would still leave exactly one registration, passing the check
        # above, but with the OLD version still recorded).
        if ($installs.Count -eq 1) {
            $newVersion = if ((Split-Path $installer -Leaf) -match '_([0-9]+\.[0-9]+\.[0-9]+[^_]*)_') { $matches[1] } else { $null }
            $regVersion = (Get-ItemProperty $installs[0].PSPath -ErrorAction SilentlyContinue).DisplayVersion
            Add-Check "Upgrade registration reports the new version" `
                ($null -ne $newVersion -and $regVersion -eq $newVersion) `
                "registry says $regVersion, installer filename says $newVersion"
        }
    }

    $appExe = Join-Path $installDir "snapmaker-studio-desktop.exe"
    $sidecarExe = Join-Path $installDir "snapstudio-api.exe"
    Add-Check "Application installed" (Test-Path $appExe)
    Add-Check "Frozen engine sidecar installed" (Test-Path $sidecarExe) `
        ("{0:N1} MB" -f ((Get-Item $sidecarExe -ErrorAction SilentlyContinue).Length / 1MB))
    Add-Check "Uninstaller installed" (Test-Path (Join-Path $installDir "uninstall.exe"))

    # --- launch --------------------------------------------------------------
    $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=$DebugPort --remote-allow-origins=*"
    $env:WEBVIEW2_USER_DATA_FOLDER = $profileDir
    $env:SNAPSTUDIO_DATA_DIR = $dataDir

    # Hand the project to the app the same way a file association would.
    $app = Start-Process -FilePath $appExe -ArgumentList $sampleWork -PassThru
    $script:started += $app.Id
    Start-Sleep -Seconds 10

    $alive = $null -ne (Get-Process -Id $app.Id -ErrorAction SilentlyContinue)
    Add-Check "Application launches" $alive "pid $($app.Id)"
    Add-Check "Window title" (( Get-Process -Id $app.Id).MainWindowTitle -eq "Snapmaker Studio")

    $sidecars = @(Get-CimInstance Win32_Process -Filter "Name='snapstudio-api.exe'" |
        Where-Object { $_.ExecutablePath -like "$installDir*" })
    Add-Check "Sidecar boots from the install directory" ($sidecars.Count -ge 1) `
        "$($sidecars.Count) process(es)"

    $cdp = "http://127.0.0.1:$DebugPort"
    $node = Join-Path $PSScriptRoot "checks.mjs"

    function Invoke-Phase($phase, $arg = "", $arg2 = "", $arg3 = "") {
        $out = & node $node $phase $cdp $outDir $arg $arg2 $arg3 $SpoolmanUrl 2>&1
        $out | ForEach-Object { Write-Host "    $_" }
        return $LASTEXITCODE
    }

    Add-Check "CDP reachable on the installed webview" `
        ((Invoke-WebRequest "$cdp/json/version" -UseBasicParsing -TimeoutSec 10).StatusCode -eq 200)

    $code = Invoke-Phase "startup"
    Add-Check "Startup checks" ($code -eq 0)

    $code = Invoke-Phase "routes" $sampleWork $gcodeWork $paintedWork
    Add-Check "Engine routes answer from the installed sidecar" ($code -eq 0)

    # --- the project the app was launched with --------------------------------
    #
    # The native picker is deliberately not used here. It is a Win32 common
    # dialog with no DOM, and on this stack invoking it without real user input
    # blocks without ever creating a window - verified by enumerating every
    # top-level window while the call was pending. No UI-automation client can
    # reach a window that does not exist, so the app instead accepts a model on
    # its command line, which a file association needs anyway.
    $code = Invoke-Phase "launch-file"
    Add-Check "Model passed on the command line is open" ($code -eq 0)

    Invoke-Phase "goto-compatibility" | Out-Null
    Start-Sleep -Seconds 4

    $code = Invoke-Phase "ui"
    Add-Check "Project opens and its findings render" ($code -eq 0)

    # --- prepare a copy -------------------------------------------------------
    Invoke-Phase "prepare" | Out-Null
    Start-Sleep -Seconds 3
    $code = Invoke-Phase "prepared"
    Add-Check "Prepare, fidelity, ledger and best-tool render" ($code -eq 0)

    $code = Invoke-Phase "colours"
    Add-Check "Colour plan renders on its own page" ($code -eq 0)

    # --- the post-slice half of the workflow ---------------------------------
    $code = Invoke-Phase "post-slice" $sampleWork $gcodeWork
    Add-Check "Post-Slice Doctor reads a sliced job in the installed app" ($code -eq 0)

    $code = Invoke-Phase "cockpit" $sampleWork $gcodeWork
    Add-Check "One surface shows the whole job" ($code -eq 0)

    # Whether a job belongs to the open project decides whether every other
    # answer on the page is about the right file.
    $code = Invoke-Phase "provenance" $sampleWork $gcodeWork
    Add-Check "Studio explains how sure it is about a job" ($code -eq 0)

    # The states a first-time owner hits, driven through the shipped UI.
    $code = Invoke-Phase "novice" $sampleWork $gcodeWork
    Add-Check "First-evening mistakes are answered, not ignored" ($code -eq 0)

    # --- v1.2: local spool notes and per-printer nozzle confirmation ---------
    #
    # No printer is present for this half of the run (host stays the U1's
    # stock mDNS placeholder), which is deliberate: these checks prove the
    # local-only note path end to end in the installed build without needing
    # real hardware. The real-U1 half of the same feature (a live nozzle
    # reading and a conflict against it) is tools/hardware/checks.mjs +
    # verify.ps1, run separately against an actual printer.
    $code = Invoke-Phase "spool-nozzle-empty"
    Add-Check "Spool notes and nozzle empty states render (W1/W6/W9)" ($code -eq 0)

    $code = Invoke-Phase "spool-notes-create"
    Add-Check "Spool notes are created through the installed UI (W2)" ($code -eq 0)

    $code = Invoke-Phase "spool-edit-validate"
    Add-Check "Editing, clearing and validating a spool note behave as specified (W3/W5/W9)" ($code -eq 0)

    $code = Invoke-Phase "spool-record-used"
    Add-Check "Recording filament used shows an estimate, not a measurement (W4)" ($code -eq 0)

    $code = Invoke-Phase "nozzle-confirm"
    Add-Check "Nozzle sizes are confirmed through the installed UI (W6)" ($code -eq 0)

    $gcodeHashAfter = (Get-FileHash $gcodeWork -Algorithm SHA256).Hash
    Add-Check "Sliced job is byte-identical afterwards" ($gcodeHashBefore -eq $gcodeHashAfter)

    $sampleHashAfter = (Get-FileHash $sampleWork -Algorithm SHA256).Hash
    Add-Check "Original file is byte-identical afterwards" `
        ($sampleHashBefore -eq $sampleHashAfter)

    # --- the painted project, in the installed UI -----------------------------
    #
    # The colours card is where this release's work becomes visible, so it is
    # driven with a project that is actually painted rather than only asserted
    # through the engine. The app is restarted with that project because a model
    # is opened from the command line, which is the same path a file association
    # takes.
    Stop-Tracked
    $script:started = @()
    $paintedApp = Start-Process -FilePath $appExe -ArgumentList $paintedWork -PassThru
    $script:started += $paintedApp.Id
    Start-Sleep -Seconds 12
    $code = Invoke-Phase "painted"
    Add-Check "Painted colour is shown in the installed build" ($code -eq 0)

    # --- v1.2: the same relaunch proves persistence, then destructive removal -
    #
    # The app was just closed (Stop-Tracked above) and started again with a
    # different project - a genuine process relaunch, the same mechanism W7
    # asks for. What was created before that relaunch must still be there.
    $code = Invoke-Phase "spool-nozzle-restored"
    Add-Check "Spool notes and nozzle confirmations survive a relaunch (W7)" ($code -eq 0)

    # Destructive, so run last among the v1.2 checks: nothing after this
    # depends on the notes or nozzle confirmations it removes.
    $code = Invoke-Phase "spool-nozzle-remove"
    Add-Check "Removing nozzles, deleting a note and switching provider kind behave as specified (W8)" ($code -eq 0)

    # --- the material provider, through the installed UI ----------------------
    #
    # Only when an address was supplied. The default and the restart are what
    # matter most: an upgrading v0.7.2 user never had a provider setting, so the
    # app must open with none and contact nothing, and a setting a person typed
    # has to survive closing the app.
    if ($SpoolmanUrl) {
        $code = Invoke-Phase "provider-default"
        Add-Check "A new install offers the provider setting and configures none" ($code -eq 0)

        $code = Invoke-Phase "provider-configure" $sampleWork $gcodeWork
        Add-Check "The provider can be configured in the installed app" ($code -eq 0)
    }

    # --- the provider wire, the safety rules and the second provider ----------
    #
    # These run against the frozen sidecar from inside the app's own origin. The
    # unit suites prove the engine; these prove the binary that was installed
    # actually carries it.
    try {
        $probeStillUp = (Invoke-WebRequest "http://$probeUrl/__hits" `
            -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200
    } catch { $probeStillUp = $false }
    Add-Check "Probe servers survived the app restarts" $probeStillUp

    $code = Invoke-Phase "provider-wire" $sampleWork $gcodeWork
    Add-Check "Both provider wire shapes work in the installed build" ($code -eq 0)

    $code = Invoke-Phase "provider-zero-request" $sampleWork $gcodeWork
    Add-Check "No provider configured means no provider request" ($code -eq 0)

    $code = Invoke-Phase "provider-safety" $sampleWork $gcodeWork
    Add-Check "Provider addresses are validated in the installed build" ($code -eq 0)

    $code = Invoke-Phase "provider-redirect" $sampleWork $gcodeWork
    Add-Check "A redirect off the local network is refused in the installed build" ($code -eq 0)

    if ($BambuddyUrl) {
        $code = Invoke-Phase "provider-adversarial" $sampleWork $gcodeWork
        Add-Check "Impossible provider weights become unknown, never enough" ($code -eq 0)
    }

    if ($SpoolmanUrl -and $BambuddyUrl) {
        $code = Invoke-Phase "provider-equivalence" $sampleWork $gcodeWork
        Add-Check "Equivalent facts from two providers decide the same" ($code -eq 0)

        $code = Invoke-Phase "provider-conflict" $sampleWork $gcodeWork
        Add-Check "A printer/provider disagreement is shown, not resolved" ($code -eq 0)

        $code = Invoke-Phase "provider-upload-contract" $sampleWork $gcodeWork
        Add-Check "The upload route accepts both wire shapes" ($code -eq 0)

    }

    # --- close the real window, prove that alone exits the app cleanly -------
    # Every orphan check below this point (and previously, every "close"
    # check in this script's history) used Stop-Process -Force - a kill, not
    # a close. That measures a different, easier path: Windows' Job Object
    # binding and the app's plain kill()+wait() both fire on any process
    # death, killed or not. It never proved that clicking the X button (or
    # Alt+F4, or any other real close) exits the app at all. It did not,
    # from beta.13 through v0.9.0: closing the main window left the process
    # and its sidecar running in the background - confirmed empirically
    # against the real v0.9.0 release binary before this check existed, then
    # fixed by requesting app exit when the main window is destroyed (the
    # app also owns a second, permanently-hidden window that prevents its
    # own close, which meant Tauri's window-map-empties-so-exit default
    # never fired for the main window either). This check is what actually
    # exercises that fix, and what the "No orphan sidecar after close" check
    # below should have been testing all along.
    $sidecarBeforeClose = @(Get-CimInstance Win32_Process -Filter "Name='snapstudio-api.exe' AND ParentProcessId=$($paintedApp.Id)" |
        Select-Object -ExpandProperty ProcessId)
    $paintedApp.Refresh()
    $realCloseWorked = $false
    if ($paintedApp.MainWindowHandle -ne [IntPtr]::Zero -and $sidecarBeforeClose.Count -gt 0) {
        $paintedApp.CloseMainWindow() | Out-Null
        $appExited = $paintedApp.WaitForExit(15000)
        $sidecarDeadline = (Get-Date).AddSeconds(10)
        $stillAlive = $sidecarBeforeClose
        while ((Get-Date) -lt $sidecarDeadline -and $stillAlive) {
            $stillAlive = $stillAlive | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }
            if ($stillAlive) { Start-Sleep -Milliseconds 250 }
        }
        $realCloseWorked = $appExited -and (-not $stillAlive)
        Add-Check "Closing the real window exits the app and its sidecar (not just a kill)" $realCloseWorked `
            "app exited=$appExited, sidecar PID(s) still alive=$($stillAlive -join ',')"
    } else {
        Add-Check "Closing the real window exits the app and its sidecar (not just a kill)" $false `
            "could not locate the main window or its sidecar PID before attempting the close"
    }
    if (-not $realCloseWorked) {
        # Don't let a failed close leave the rest of the script blocked on a
        # process that should already be gone - force-stop whatever remains
        # so later phases still run, but the FAIL above already recorded it.
        Stop-Process -Id $paintedApp.Id -Force -ErrorAction SilentlyContinue
        foreach ($sc in $sidecarBeforeClose) { Stop-Process -Id $sc -Force -ErrorAction SilentlyContinue }
    }

    # --- close (by kill, the pre-existing check) and prove no orphan --------
    Stop-Tracked
    $script:started = @()
    $orphans = @(Get-CimInstance Win32_Process -Filter "Name='snapstudio-api.exe'" |
        Where-Object { $_.ExecutablePath -like "$installDir*" })
    Add-Check "No orphan sidecar after close" ($orphans.Count -eq 0) `
        "$($orphans.Count) left running"

    # --- reopen ---------------------------------------------------------------
    $again = Start-Process -FilePath $appExe -PassThru
    $script:started += $again.Id
    Start-Sleep -Seconds 8
    Add-Check "Reopens cleanly" ($null -ne (Get-Process -Id $again.Id -ErrorAction SilentlyContinue))

    if ($SpoolmanUrl) {
        $code = Invoke-Phase "provider-restored" $sampleWork $gcodeWork
        Add-Check "Provider settings survive a restart and reach the send decision" ($code -eq 0)
    }

    # Only now, with the first provider's persistence proved, is it safe to
    # switch. Doing it earlier cleared the Spoolman configuration that the
    # restart check above exists to find - which is what the first run of this
    # did, and it read as five product failures.
    if ($SpoolmanUrl -and $BambuddyUrl) {
        $code = Invoke-Phase "provider-switch" $sampleWork $gcodeWork
        Add-Check "Switching provider in the installed app clears the old one" ($code -eq 0)

        # A second restart, so the second provider's persistence is measured the
        # same way the first one's was rather than assumed from it.
        Stop-Tracked
        $script:started = @()
        $third = Start-Process -FilePath $appExe -PassThru
        $script:started += $third.Id
        Start-Sleep -Seconds 8
        Add-Check "Reopens again after switching provider" `
            ($null -ne (Get-Process -Id $third.Id -ErrorAction SilentlyContinue))

        $code = Invoke-Phase "provider-switch-restored" $sampleWork $gcodeWork
        Add-Check "The second provider survives a restart and can then be turned off" ($code -eq 0)
    }

    # SpoolEase runs last so the provider-switch phases above still measure a
    # clean Spoolman -> Bambuddy switch, not a switch away from SpoolEase.
    if ($env:SNAPSTUDIO_SPOOLEASE_KEY) {
        $code = Invoke-Phase "provider-spoolease" $sampleWork $gcodeWork
        Add-Check "SpoolEase can be configured and read in the installed build" ($code -eq 0)

        Stop-Tracked
        $script:started = @()
        $spooleaseAgain = Start-Process -FilePath $appExe -PassThru
        $script:started += $spooleaseAgain.Id
        Start-Sleep -Seconds 8
        $code = Invoke-Phase "provider-spoolease-restored" $sampleWork $gcodeWork
        Add-Check "SpoolEase settings restore without the session key" ($code -eq 0)
    }

    Stop-Tracked
    $script:started = @()
}
finally {
    Stop-Tracked
    if ($script:probePid) {
        Stop-Process -Id $script:probePid -Force -ErrorAction SilentlyContinue
    }
    Remove-Item Env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS -ErrorAction SilentlyContinue
    Remove-Item Env:WEBVIEW2_USER_DATA_FOLDER -ErrorAction SilentlyContinue
    Remove-Item Env:SNAPSTUDIO_DATA_DIR -ErrorAction SilentlyContinue
    foreach ($name in @("SNAPSTUDIO_PROBE_URL", "SNAPSTUDIO_REDIRECT_URL",
                        "SNAPSTUDIO_BAMBUDDY_URL", "SNAPSTUDIO_SPOOLEASE_URL",
                        "SNAPSTUDIO_SPOOLEASE_KEY")) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
}

# --- uninstall ---------------------------------------------------------------
if (-not $KeepInstall) {
    $uninstaller = Join-Path $installDir "uninstall.exe"
    if (Test-Path $uninstaller) {
        $u = Start-Process -FilePath $uninstaller -ArgumentList '/S' -PassThru -Wait
        Start-Sleep -Seconds 3
        Add-Check "Uninstall completes" ($u.ExitCode -eq 0) "exit code $($u.ExitCode)"
        $leftovers = @(Get-ChildItem $installDir -Recurse -File -ErrorAction SilentlyContinue)
        Add-Check "Install directory removed" ($leftovers.Count -eq 0) "$($leftovers.Count) file(s) left"
        $stillRunning = @(Get-CimInstance Win32_Process -Filter "Name='snapstudio-api.exe'" |
            Where-Object { $_.ExecutablePath -like "$installDir*" })
        Add-Check "No sidecar survives uninstall" ($stillRunning.Count -eq 0)
    }
    # Put the maintainer's own uninstall entry back exactly as it was.
    if ($existing -and (Test-Path $backupReg)) {
        reg import $backupReg 2>&1 | Out-Null
        $restored = Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' |
            Where-Object { (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).DisplayName -like '*Snapmaker Studio*' }
        Add-Check "Pre-existing install registration restored" ($null -ne $restored)
    }
}

# --- report -------------------------------------------------------------------
$passed = @($checks | Where-Object ok).Count
$total = $checks.Count
$report = [pscustomobject]@{
    schema_version = "acceptance/1"
    installer      = $installer
    checks         = $checks
    passed         = $passed
    total          = $total
    evidence       = $outDir
}
$reportPath = Join-Path $outDir "acceptance.json"

# The repository's own rules forbid local paths and usernames in tracked files,
# and this report (and every per-phase results-*.json checks.mjs writes
# straight into $outDir) is meant to be committed as release evidence.
#
# A1 (harness-fix round 1, Opus 5/Sol 4): this used to scrub only the
# in-memory acceptance.json string - every results-<phase>.json and log file
# checks.mjs writes directly to $outDir was never touched at all. It also
# leak-checked that SAME already-replaced string, which can never fail (a
# vacuous pass Sol flagged as BLOCK). Fixed: every text file actually in
# $outDir is scrubbed in place, and the final leak check re-reads every file
# fresh off disk afterward, independent of any in-memory string this script
# built along the way.
function Scrub-EvidenceText([string]$text) {
    foreach ($pair in $literalRedactionPairs) {
        $text = $text.Replace($pair.from.Replace('\', '\\'), $pair.to)
        $text = $text.Replace($pair.from, $pair.to)
    }
    # IPv4.
    $text = [regex]::Replace($text, '\b(?:\d{1,3}\.){3}\d{1,3}\b', '<ip>')
    # Bracketed IPv6 (A7-2, Opus): requires either a literal "::" or at least
    # 3 colons inside the brackets - a short bracketed list like a log's
    # "[22:14:05]" (2 colons) or "[1]"/"[2]" (no colon at all) used to match
    # the old, looser "any hex/colon chars in brackets" pattern and get
    # wrongly redacted; neither shape is a real IPv6 address.
    $text = [regex]::Replace($text,
        '\[(?:[0-9a-fA-F]*::[0-9a-fA-F:]*|(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{0,4})(?:%[0-9a-zA-Z]+)?\]',
        '<ip>')
    # Bare compressed IPv6 (fe80::1, 2001:db8::1, ::1, fd00::abcd:1234, ...),
    # with an optional zone id. Requires the literal "::" - a plain clock
    # time like 22:14:05 has no double colon and can never match this, unlike
    # a broader hex-run regex.
    #
    # F7 (Opus polish): also requires a REAL hex group immediately touching
    # the "::" on at least one side - bare "::" with nothing hex-shaped on
    # either side (e.g. "[System.IO.File]::Read(...)", a plain PowerShell/.NET
    # member-access token, not an address) used to match the old, looser
    # "{0,4} on both sides" pattern, since both sides being zero-width was
    # still allowed. The two alternatives below require the LEADING group
    # non-empty (covers "fe80::", "fd00::abcd:1234") or the TRAILING group
    # non-empty (covers "::1") - never both empty at once.
    $text = [regex]::Replace($text,
        '(?<![0-9a-fA-F:])(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{0,4}){0,7}::(?:[0-9a-fA-F]{0,4}:){0,7}[0-9a-fA-F]{0,4}|[0-9a-fA-F]{0,4}(?::[0-9a-fA-F]{0,4}){0,7}::(?:[0-9a-fA-F]{0,4}:){0,7}[0-9a-fA-F]{1,4})(?:%[0-9a-zA-Z]+)?(?![0-9a-fA-F:])',
        '<ip>')
    # A7-4 (Opus): bare, FULLY EXPANDED IPv6 (8 groups, exactly 7 colons, no
    # "::" at all) - the round-1 pattern only matched a compressed form. A
    # plain clock time has only 2 colons and can never satisfy "exactly 7", so
    # this is still never a false positive on one.
    $text = [regex]::Replace($text,
        '(?<![0-9a-fA-F:])(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}(?:%[0-9a-zA-Z]+)?(?![0-9a-fA-F:])',
        '<ip>')
    return $text
}

$literalRedactionPairs = @(
    @{ from = $repo;         to = "<repo>" },
    @{ from = $WorkDir;      to = "<workdir>" },
    @{ from = $env:TEMP;     to = "<temp>" },
    @{ from = $env:USERNAME; to = "<user>" },
    @{ from = $SpoolmanUrl;  to = "<provider-on-lan>" },
    @{ from = $BambuddyUrl;  to = "<provider-on-lan>" }
    @{ from = "Fx7-tEsT";    to = "<fixture-key>" }
) | Where-Object { $_.from }

$json = Scrub-EvidenceText ($report | ConvertTo-Json -Depth 5)
$json | Set-Content $reportPath -Encoding utf8

$textExtensions = @(".json", ".log", ".txt")
foreach ($file in @(Get-ChildItem $outDir -File -Recurse -ErrorAction SilentlyContinue)) {
    if ($file.FullName -eq $reportPath) { continue } # already scrubbed and written above
    if ($textExtensions -notcontains $file.Extension.ToLowerInvariant()) { continue }
    $raw = $null
    try { $raw = Get-Content -Raw -Path $file.FullName -ErrorAction Stop } catch { continue }
    if ($null -eq $raw) { continue }
    $scrubbed = Scrub-EvidenceText $raw
    if ($scrubbed -ne $raw) {
        $scrubbed | Set-Content -Path $file.FullName -Encoding utf8 -NoNewline
    }
}

# Final scan: re-read every file fresh off disk (byte-safe, so a binary
# screenshot is scanned too, not just text) and fail the run if the RAW
# supplied provider address is still found anywhere in the evidence
# directory - independent of the $json variable above, which would trivially
# "pass" having just been replaced in it.
#
# A7-3 (Opus): matched case-INsensitively, and both WITH and WITHOUT the
# address's own port - a log line that dropped the ":port" suffix, or wrote
# the hostname in a different case, used to slip past a case-sensitive,
# exact-string Contains() check.
# F7 (Opus polish): also strips any "http(s)://" prefix, in addition to the
# port, so a candidate supplied as a full URL still produces the bare-host
# form to match against.
function Get-LeakCandidates([string]$addr) {
    if (-not $addr) { return @() }
    $out = New-Object System.Collections.Generic.List[string]
    $out.Add($addr)
    $noScheme = $addr -replace '^[a-zA-Z][a-zA-Z0-9+.-]*://', ''
    if ($noScheme -ne $addr) { $out.Add($noScheme) }
    foreach ($candidate in @($addr, $noScheme)) {
        if ($candidate -match '^(.*):(\d+)$') { $out.Add($matches[1]) }
    }
    return @($out | Select-Object -Unique)
}
$leakCandidates = @(
    (Get-LeakCandidates $SpoolmanUrl) + (Get-LeakCandidates $BambuddyUrl)
) | Select-Object -Unique
# F4 (fix-round-3, Sol 4 BLOCKING): records/prints the FILENAME only on a hit
# - never the candidate string itself. The round-2 code embedded the raw
# address into `$leaked` (`"$($file.Name): $candidate"`) and then printed
# that straight to the console via Write-Host, which is exactly the "write
# the raw address somewhere" mistake H8 exists to prevent elsewhere in this
# same round - it just hadn't been fixed here yet.
$leaked = New-Object System.Collections.Generic.List[string]
if ($leakCandidates.Count -gt 0) {
    $latin1 = [System.Text.Encoding]::GetEncoding(28591)
    foreach ($file in @(Get-ChildItem $outDir -File -Recurse -ErrorAction SilentlyContinue)) {
        $text = $null
        try {
            $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
            $text = $latin1.GetString($bytes)
        } catch { continue }
        foreach ($candidate in $leakCandidates) {
            if ($text.IndexOf($candidate, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                if (-not $leaked.Contains($file.Name)) { $leaked.Add($file.Name) }
                break
            }
        }
    }
}
if ($leaked.Count -gt 0) {
    Write-Host "FAIL  A supplied provider address survived redaction in the evidence directory (F4/A3.7/A1) - found in: $($leaked -join ', ')"
}

Write-Host ""
Write-Host "$passed/$total checks passed"
Write-Host "Evidence and screenshots: $outDir"
if ($passed -ne $total -or $leaked.Count -gt 0) { exit 1 }
