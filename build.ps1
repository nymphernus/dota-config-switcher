param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

# Build Dota 2 Config Switcher into a single-file windowed EXE using PyInstaller.
# Run from project root, preferably inside activated .venv.

if ($Clean) {
    if (Test-Path build) { Remove-Item -Recurse -Force build }
    if (Test-Path dist) { Remove-Item -Recurse -Force dist }
    if (Test-Path Dota2ConfigSwitcher.spec) { Remove-Item -Force Dota2ConfigSwitcher.spec }
}

$pyinstaller = "pyinstaller"
if (Test-Path ".\.venv\Scripts\pyinstaller.exe") {
    $pyinstaller = ".\.venv\Scripts\pyinstaller.exe"
}

& $pyinstaller --noconfirm --clean --onefile --windowed --name "Dota2ConfigSwitcher" main.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

Write-Host "Build complete: dist\Dota2ConfigSwitcher.exe" -ForegroundColor Green
