param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

# Build DotaConfigSwitcher into a single-file windowed EXE using PyInstaller.
# Run from project root, preferably inside activated .venv.

if ($Clean) {
    if (Test-Path build) { Remove-Item -Recurse -Force build }
    if (Test-Path dist) { Remove-Item -Recurse -Force dist }
    if (Test-Path DotaConfigSwitcher.spec) { Remove-Item -Force DotaConfigSwitcher.spec }
}

$pyinstaller = "pyinstaller"
if (Test-Path ".\.venv\Scripts\pyinstaller.exe") {
    $pyinstaller = ".\.venv\Scripts\pyinstaller.exe"
}

& $pyinstaller --noconfirm --clean --onefile --windowed --name "DotaConfigSwitcher" main.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

Write-Host "Build complete: dist\DotaConfigSwitcher.exe" -ForegroundColor Green

