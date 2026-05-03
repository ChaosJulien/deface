# Run on Windows (winsrv). Builds dist\deface_gui\deface_gui.exe (folder mode).
# Usage:  pwsh -File .\build_win_gui.ps1
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# 1. venv
if (-not (Test-Path .\.venv-win)) {
    py -3.11 -m venv .venv-win
}
. .\.venv-win\Scripts\Activate.ps1

# 2. deps (CPU-only onnxruntime; pin to avoid GPU/DML wheels)
python -m pip install --upgrade pip
pip install -e .
pip install pyside6 onnxruntime pillow pyinstaller

# 3. clean & build
if (Test-Path .\build) { Remove-Item .\build -Recurse -Force }
if (Test-Path .\dist\deface_gui) { Remove-Item .\dist\deface_gui -Recurse -Force }

pyinstaller deface_gui.spec --clean --noconfirm

Write-Host ""
Write-Host "Built: $Root\dist\deface_gui\deface_gui.exe"
