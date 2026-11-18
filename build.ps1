param(
    [switch]$Clean
)

$env:PYTHONUTF8 = "1"
$ErrorActionPreference = "Stop"

Remove-Item -Recurse -Force build, dist, DotaConfigSwitcher.spec -ErrorAction SilentlyContinue

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

chcp 65001 | Out-Null

& $pyinstaller --noconfirm --clean --onefile --windowed `
    --name "DotaConfigSwitcher" `
    --icon "icon.ico" `
    --add-data "icon.ico;." `
    --add-data "icon.png;." `
    main.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

Write-Host "Build complete: dist\DotaConfigSwitcher.exe" -ForegroundColor Green
