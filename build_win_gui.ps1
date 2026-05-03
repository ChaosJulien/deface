# Run on Windows (winsrv). Builds dist\deface_gui\deface_gui.exe (folder mode).
# 顺带准备 vendor\tesseract\(tesseract.exe + chi_sim/eng traineddata),让打出来的 exe 自带 OCR。
# Usage:  pwsh -File .\build_win_gui.ps1
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# 1. venv
if (-not (Test-Path .\.venv-win)) {
    py -3.11 -m venv .venv-win
}
. .\.venv-win\Scripts\Activate.ps1

# 2. deps
python -m pip install --upgrade pip
pip install -e .
pip install pyside6 onnxruntime pillow pytesseract pyinstaller

# 3. vendor tesseract(用系统已装的;若没装,提示用户)
$VendorTess = Join-Path $Root 'vendor\tesseract'
if (-not (Test-Path $VendorTess)) {
    $TessRoot = $null
    $candidates = @(
        'C:\Program Files\Tesseract-OCR',
        'C:\Program Files (x86)\Tesseract-OCR',
        "$env:LOCALAPPDATA\Programs\Tesseract-OCR"
    )
    foreach ($c in $candidates) { if (Test-Path (Join-Path $c 'tesseract.exe')) { $TessRoot = $c; break } }
    if (-not $TessRoot) {
        Write-Host "[!] 没找到本机 Tesseract。请先装 UB-Mannheim:" -ForegroundColor Yellow
        Write-Host "    choco install -y tesseract" -ForegroundColor Yellow
        Write-Host "    或下载 https://github.com/UB-Mannheim/tesseract/wiki" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "[*] copying tesseract from $TessRoot ..."
    New-Item -ItemType Directory -Force -Path $VendorTess | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $VendorTess 'tessdata') | Out-Null
    Copy-Item -Path (Join-Path $TessRoot '*.exe') -Destination $VendorTess -Force
    Copy-Item -Path (Join-Path $TessRoot '*.dll') -Destination $VendorTess -Force
    if (Test-Path (Join-Path $TessRoot 'tessdata\eng.traineddata')) {
        Copy-Item -Path (Join-Path $TessRoot 'tessdata\eng.traineddata') -Destination (Join-Path $VendorTess 'tessdata') -Force
    }
    if (Test-Path (Join-Path $TessRoot 'tessdata\osd.traineddata')) {
        Copy-Item -Path (Join-Path $TessRoot 'tessdata\osd.traineddata') -Destination (Join-Path $VendorTess 'tessdata') -Force
    }
    # 中文(simplified)— 系统装的常常没带,从 tessdata_fast 拉
    $chi = Join-Path $VendorTess 'tessdata\chi_sim.traineddata'
    if (-not (Test-Path $chi)) {
        Write-Host "[*] downloading chi_sim.traineddata ..."
        Invoke-WebRequest -Uri 'https://github.com/tesseract-ocr/tessdata_fast/raw/main/chi_sim.traineddata' -OutFile $chi
    }
}

# 4. clean & build
if (Test-Path .\build) { Remove-Item .\build -Recurse -Force }
if (Test-Path .\dist\deface_gui) { Remove-Item .\dist\deface_gui -Recurse -Force }

pyinstaller deface_gui.spec --clean --noconfirm

Write-Host ""
Write-Host "Built: $Root\dist\deface_gui\deface_gui.exe"
