# Freeze the Snapmaker Studio engine sidecar into a single Windows .exe and
# stage it for Tauri's externalBin (target-triple-suffixed name).
#
# Requires: Python with the backend installed (pip install -e backend) plus
# pyinstaller + lxml + cryptography (pip install -r backend/requirements-build.txt).
#
# Usage (from anywhere):  desktop/scripts/build-sidecar.ps1
$ErrorActionPreference = "Stop"

$backend = (Resolve-Path "$PSScriptRoot\..\..\backend").Path
$triple  = "x86_64-pc-windows-msvc"
$name    = "snapstudio-api-$triple"

# Resolve an interpreter rather than assuming a bare `python` is on PATH: a
# release build must not depend on which shell it happens to run from.
$python = $null
$pythonArgs = @()
foreach ($candidate in @(@("python", @()), @("python3", @()), @("py", @("-3.13")))) {
    $found = (Get-Command $candidate[0] -ErrorAction SilentlyContinue)?.Source
    if (-not $found) { continue }
    # An interpreter only counts if it can actually import the build dependencies.
    & $found @($candidate[1]) -c "import PyInstaller, lxml, cryptography" 2>$null
    if ($LASTEXITCODE -eq 0) { $python = $found; $pythonArgs = $candidate[1]; break }
}
if (-not $python) {
    throw "No Python with pyinstaller + lxml + cryptography found. Run: pip install -r backend/requirements-build.txt"
}
Write-Host "Using interpreter: $python $pythonArgs"

Write-Host "Freezing sidecar from $backend ..."
Push-Location $backend
try {
    # --collect-data snapstudio_core : bundle data/*.json loaded via importlib.resources
    # --collect-submodules lxml      : ensure the lxml C-extension parts are included
    # --noupx                        : skip UPX packing (reduces Windows AV false-positives)
    & $python @pythonArgs -m PyInstaller --noconfirm --clean --onefile --noupx --name $name `
        --collect-data snapstudio_core `
        --collect-submodules lxml `
        sidecar_main.py
} finally {
    Pop-Location
}

$src = Join-Path $backend "dist\$name.exe"
if (-not (Test-Path $src)) { throw "PyInstaller did not produce $src" }

$dstDir = Join-Path $PSScriptRoot "..\src-tauri\bin"
New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
$dst = Join-Path $dstDir "$name.exe"
Copy-Item $src $dst -Force

Write-Host "Sidecar staged -> $dst"
