# ======================
# BUILD GMP MONITOR
# Usage : .\build.ps1
# ======================

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$ICON = Join-Path $ROOT "assets\monitor.ico"
$SRC  = Join-Path $ROOT "src\monitor.py"
$OUT  = Join-Path $ROOT "dist"

Write-Host "=== Build GMP Monitor ===" -ForegroundColor Cyan

# Verifier PyInstaller
if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "PyInstaller non trouve — installation..." -ForegroundColor Yellow
    pip install pyinstaller
}

# Nettoyage
$buildDir = Join-Path $ROOT "build"
$exeDst   = Join-Path $OUT  "GMP_Monitor.exe"
$specFile = Join-Path $ROOT "GMP_Monitor.spec"

if (Test-Path $buildDir) { Remove-Item $buildDir -Recurse -Force }
if (Test-Path $exeDst)   { Remove-Item $exeDst   -Force }
if (Test-Path $specFile)  { Remove-Item $specFile  -Force }

Write-Host "Compilation en cours..." -ForegroundColor Yellow

$addData = "$ICON;assets"

pyinstaller `
    --onefile `
    --windowed `
    --icon="$ICON" `
    --name="GMP_Monitor" `
    --add-data="$addData" `
    --distpath="$OUT" `
    --workpath="$buildDir" `
    --specpath="$ROOT" `
    --noconfirm `
    "$SRC"

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERREUR build PyInstaller" -ForegroundColor Red
    exit 1
}

# Copier la config si absente du dossier dist
$cfgSrc = Join-Path $ROOT "monitor_config.json"
$cfgDst = Join-Path $OUT  "monitor_config.json"
if ((Test-Path $cfgSrc) -and -not (Test-Path $cfgDst)) {
    Copy-Item $cfgSrc $cfgDst
    Write-Host "Config copiee : monitor_config.json" -ForegroundColor Green
}

# Nettoyage fichiers intermediaires
if (Test-Path $buildDir) { Remove-Item $buildDir -Recurse -Force -ErrorAction SilentlyContinue }
if (Test-Path $specFile)  { Remove-Item $specFile  -Force -ErrorAction SilentlyContinue }

Write-Host ""
Write-Host "=== Build termine ===" -ForegroundColor Cyan
Write-Host "Executable : $exeDst" -ForegroundColor Green
Write-Host "Config     : $cfgDst" -ForegroundColor Green
