# Drives the app's native Win32 Open dialog WITHOUT UI Automation (UIA queries against the app crashed its WebView2 renderer
# in this build; plain Win32 messages to the standard dialog controls do not). The dialog is an owned top-level #32770 of the
# app: located with EnumWindows by owner pid, the filename Edit is found by walking child windows, text is set with WM_SETTEXT,
# and Open (IDOK=1) / Cancel (IDCANCEL=2) is pressed with BM_CLICK. Only a window of the named pid is ever touched.
param([Parameter(Mandatory)][int]$OwnerPid, [string]$Path, [switch]$Cancel, [int]$TimeoutSec = 25)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices; using System.Text;
public class ND {
  public delegate bool CB(IntPtr h, IntPtr l);
  [DllImport("user32")] public static extern bool EnumWindows(CB c, IntPtr l);
  [DllImport("user32")] public static extern bool EnumChildWindows(IntPtr p, CB c, IntPtr l);
  [DllImport("user32")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
  [DllImport("user32", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32")] public static extern IntPtr GetDlgItem(IntPtr h, int id);
  [DllImport("user32", CharSet = CharSet.Unicode)] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, string l);
  [DllImport("user32", CharSet = CharSet.Unicode)] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, StringBuilder l);
  [DllImport("user32")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  public static IntPtr Dialog(uint pid) { IntPtr f = IntPtr.Zero; EnumWindows((h, l) => { uint p; GetWindowThreadProcessId(h, out p); if (p != pid || !IsWindowVisible(h)) return true; var c = new StringBuilder(64); GetClassName(h, c, 64); if (c.ToString() == "#32770") { f = h; return false; } return true; }, IntPtr.Zero); return f; }
  public static IntPtr FilenameEdit(IntPtr dlg) {
    IntPtr f = IntPtr.Zero;
    EnumChildWindows(dlg, (h, l) => { var c = new StringBuilder(64); GetClassName(h, c, 64); if (c.ToString() == "Edit") { f = h; return false; } return true; }, IntPtr.Zero);
    return f;
  }
  public static string Text(IntPtr h) { var sb = new StringBuilder(2048); SendMessage(h, 0x000D, (IntPtr)2048, sb); return sb.ToString(); }
}
"@
$deadline = (Get-Date).AddSeconds($TimeoutSec); $dlg = [IntPtr]::Zero
while ((Get-Date) -lt $deadline -and $dlg -eq [IntPtr]::Zero) { $dlg = [ND]::Dialog([uint32]$OwnerPid); if ($dlg -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 300 } }
if ($dlg -eq [IntPtr]::Zero) { throw "no file dialog appeared for pid $OwnerPid within ${TimeoutSec}s" }
Write-Host "dialog hwnd=$dlg"
Start-Sleep -Milliseconds 1200
if ($Cancel) { [void][ND]::PostMessage([ND]::GetDlgItem($dlg, 2), 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero); Write-Host 'cancel clicked'; exit 0 }
$edit = [ND]::FilenameEdit($dlg)
if ($edit -eq [IntPtr]::Zero) { throw 'no filename Edit control found in the dialog' }
[void][ND]::SendMessage($edit, 0x000C, [IntPtr]::Zero, $Path)   # WM_SETTEXT
$back = [ND]::Text($edit)
if ($back -ne $Path) { throw "filename did not take: '$back'" }
Write-Host 'filename set and read back'
$ok = [ND]::GetDlgItem($dlg, 1)
if ($ok -eq [IntPtr]::Zero) { throw 'no IDOK button' }
[void][ND]::PostMessage($ok, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)   # BM_CLICK
$end = (Get-Date).AddSeconds(12); $closed = $false
while ((Get-Date) -lt $end) { if ([ND]::Dialog([uint32]$OwnerPid) -eq [IntPtr]::Zero) { $closed = $true; break }; Start-Sleep -Milliseconds 250 }
if (-not $closed) { throw 'the dialog is still open after pressing Open' }
Write-Host 'dialog closed'
