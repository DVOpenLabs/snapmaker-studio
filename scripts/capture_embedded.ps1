#requires -Version 7.0
# Privacy-safe capture of the embedded Model Browser inside Studio - REWRAPPED ACCEPTANCE-IDENTITY lane.
# Drives the app via UI Automation (accessibility), then PrintWindow with
# PW_RENDERFULLCONTENT captures ONLY the Studio window's own content (no screen scrape).
#
# The app is installed and launched through tools/harness/HarnessLauncher.psm1 (REWRAPPED acceptance installer,
# isolated WebView2 profile and engine data directory, passed only to the child process). The window is found by
# the TRACKED process id, so another window titled like Studio (for example the production app) is never touched,
# and every process this script starts is stopped by pid + start time, never by name. The production app must not
# be running and its update auto-check must be off (or its state file absent).
#
# Usage:
#   pwsh -File scripts/capture_embedded.ps1 -InstallerPath <rewrapped installer> -AttestationPath <its attestation>
#        [-OutFile <png>] [-KeepInstall]
#   or: -RealInstaller <path> -ExpectedSha256 <sha256> -SourceVersion <semver> [-Sha256SumsPath <path>]

[CmdletBinding()]
param(
    [string]$InstallerPath,
    [string]$AttestationPath,
    [string]$RealInstaller,
    [string]$ExpectedSha256,
    [string]$Sha256SumsPath,
    [string]$SourceVersion,
    # Defaults to the embedded-browser screenshot in the repository's docs tree.
    [string]$OutFile,
    [int]$DebugPort = 9347,
    [switch]$KeepInstall
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutFile) { $OutFile = Join-Path $repo "docs\screenshots\beta13\embedded-browser-beta13.png" }
Import-Module (Join-Path $PSScriptRoot "..\tools\harness\HarnessLauncher.psm1") -Force -DisableNameChecking
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes,System.Drawing
Add-Type @"
using System;using System.Runtime.InteropServices;
public class W{
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
 [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out R r);
 public struct R{public int L,T,Rt,B;}
}
"@

$laneArgs = @{
    InstallerPath = $InstallerPath; AttestationPath = $AttestationPath
    RealInstaller = $RealInstaller; ExpectedSha256 = $ExpectedSha256; Sha256SumsPath = $Sha256SumsPath; SourceVersion = $SourceVersion
}
$lane = Start-HarnessLane -Name "capture" -Kind capture @laneArgs -DebugPort $DebugPort -KeepInstall:$KeepInstall
$result = $null
$failure = $null

try {
    $inst = Install-HarnessBuild -Lane $lane -Which Primary
    if ($inst.ExitCode -ne 0) { throw "install failed with exit code $($inst.ExitCode)" }

    $appHandle = Start-HarnessApp -Lane $lane -SettleSeconds 9 -Label "app"
    $appPid = $appHandle.Pid

    $root = [System.Windows.Automation.AutomationElement]::RootElement
    function Find($name, $base, [int]$onlyPid = 0) {
        $c = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $name)
        if ($onlyPid) {
            $pc = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $onlyPid)
            $c = New-Object System.Windows.Automation.AndCondition($c, $pc)
        }
        return $base.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $c)
    }
    $win = $null
    for ($i = 0; $i -lt 10 -and -not $win; $i++) { $win = Find "Snapmaker Studio" $root $appPid; if (-not $win) { Start-Sleep 1 } }
    if (-not $win) { throw "NO STUDIO WINDOW (UIA) for the tracked app process" }
    $hwnd = [IntPtr]$win.Current.NativeWindowHandle
    Write-Host "studio hwnd=$hwnd"
    function Click($n) {
        $e = Find $n $win
        if ($e) { try { $ip = $e.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern); $ip.Invoke(); Write-Host "clicked $n"; return $true } catch { Write-Host "no-invoke $n" } }
        else { Write-Host "notfound $n" }
        return $false
    }
    Click "Find Models" | Out-Null
    Start-Sleep 2
    Click "Printables" | Out-Null
    Start-Sleep 8
    $r = New-Object W+R; [W]::GetClientRect($hwnd, [ref]$r) | Out-Null
    $w = $r.Rt - $r.L; $h = $r.B - $r.T; Write-Host "client ${w}x${h}"
    if ($w -gt 0 -and $h -gt 0) {
        $bmp = New-Object System.Drawing.Bitmap $w, $h
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $hdc = $g.GetHdc()
        $ok = [W]::PrintWindow($hwnd, $hdc, 2)
        $g.ReleaseHdc($hdc); $g.Dispose()
        New-Item -ItemType Directory -Force (Split-Path -Parent $OutFile) | Out-Null
        $bmp.Save($OutFile)
        $bmp.Dispose()
        Write-Host "PrintWindow ok=$ok saved"
    } else {
        throw "the Studio window has no client area to capture"
    }
}
catch {
    $failure = $_
    Write-Host "FAIL  capture aborted: $(Protect-LaneText -Text $_.Exception.Message -Lane $lane)"
}
finally {
    # Always runs, including with -KeepInstall (which skips the uninstall and the recovery): the tracked app and its sidecar are
    # closed gracefully then stopped by verified pid; uninstall, journal recovery, production tripwire, lock release.
    $result = Complete-HarnessLane -Lane $lane
}

# Persist the CLOSED-SCHEMA lane evidence (fixed codes and counts only) next to the screenshot; a writer failure FAILS the lane.
$rc = Publish-HarnessLaneReport -Lane $lane -Result $result -EvidencePath ([IO.Path]::ChangeExtension($OutFile, ".lane-evidence.json")) -Failed:([bool]$failure)
if ($KeepInstall) { Write-Host "NOTE  -KeepInstall: the acceptance install and its journal(s) were KEPT (not uninstalled, not recovered). Uninstall it yourself, then for EACH journal run: tools/harness/Repair-Harness.ps1 -RunId <id> -ShortcutDir $($lane.ShortcutDir)   (journal ids: $((@($lane.Phases | ForEach-Object { $_.RunId })) -join ', '))" }
if ($rc -ne 0) { exit 1 }
Write-Host "done"
