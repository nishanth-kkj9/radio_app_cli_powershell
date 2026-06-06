# Start-Radio.ps1
# PowerShell Radio Pro — Windows launcher
# Run from PowerShell:  .\Start-Radio.ps1
# With category:        .\Start-Radio.ps1 -Category jazz
# Check deps:           .\Start-Radio.ps1 -Check

param(
    [string]$Category = "",
    [switch]$Check,
    [switch]$Help
)

# ── Banner ────────────────────────────────────────────────────────────────────
$banner = @"
  ____  ____     ____          _ _
 |  _ \/ ___|   |  _ \ __ _ __| (_) ___
 | |_) \___ \   | |_) / _` / _` | |/ _ \
 |  __/ ___) |  |  _ < (_| | (_| | | (_) |
 |_|   |____/   |_| \_\__,_|\__,_|_|\___/
  PowerShell Radio Pro v2.0 — Windows Native
"@
Write-Host $banner -ForegroundColor Cyan

# ── Help ──────────────────────────────────────────────────────────────────────
if ($Help) {
    Write-Host ""
    Write-Host "Usage:" -ForegroundColor Yellow
    Write-Host "  .\Start-Radio.ps1                   # Top Charts"
    Write-Host "  .\Start-Radio.ps1 -Category jazz    # Start on Jazz"
    Write-Host "  .\Start-Radio.ps1 -Category hindi   # Start on Hindi"
    Write-Host "  .\Start-Radio.ps1 -Check            # Check dependencies"
    Write-Host ""
    Write-Host "Categories: top, hindi, kannada, pop, rock, jazz, classical, news, favorites, recent"
    Write-Host ""
    exit 0
}

# ── Locate Python ─────────────────────────────────────────────────────────────
$pythonExe = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $ver = & $candidate --version 2>&1
        if ($ver -match "Python 3\.[9-9][0-9]*|Python 3\.1[0-9]") {
            $pythonExe = $candidate
            Write-Host "  Python: $ver" -ForegroundColor Green
            break
        } elseif ($ver -match "Python 3\.[0-8]") {
            Write-Host "  [WARN] Found $ver but Python 3.9+ is required." -ForegroundColor Yellow
        }
    } catch {}
}

if (-not $pythonExe) {
    Write-Host ""
    Write-Host "  [ERROR] Python 3.9+ not found." -ForegroundColor Red
    Write-Host "  Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "  Make sure to check 'Add Python to PATH' during install." -ForegroundColor Yellow
    Write-Host ""
    pause
    exit 1
}

# ── Locate VLC ────────────────────────────────────────────────────────────────
$vlcPaths = @(
    "C:\Program Files\VideoLAN\VLC\vlc.exe",
    "C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    "$env:LOCALAPPDATA\Programs\VideoLAN\VLC\vlc.exe"
)
$vlcFound = $false
foreach ($p in $vlcPaths) {
    if (Test-Path $p) {
        $vlcFound = $true
        Write-Host "  VLC:    $p" -ForegroundColor Green
        break
    }
}
if (-not $vlcFound) {
    Write-Host ""
    Write-Host "  [WARN] VLC not found in standard locations." -ForegroundColor Yellow
    Write-Host "  Download 64-bit VLC from: https://www.videolan.org/vlc/" -ForegroundColor Yellow
    Write-Host "  Continuing anyway (VLC may still be on PATH)..."
    Write-Host ""
}

# ── Script directory ──────────────────────────────────────────────────────────
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# ── Check mode ────────────────────────────────────────────────────────────────
if ($Check) {
    Write-Host ""
    & $pythonExe radio.py --check
    exit $LASTEXITCODE
}

# ── Install dependencies if needed ───────────────────────────────────────────
Write-Host ""
Write-Host "  Checking Python packages..." -ForegroundColor Cyan

$needsInstall = $false
foreach ($pkg in @("vlc", "rich", "requests")) {
    $result = & $pythonExe -c "import $pkg" 2>&1
    if ($LASTEXITCODE -ne 0) {
        $needsInstall = $true
        Write-Host "  [MISSING] $pkg" -ForegroundColor Yellow
    }
}

if ($needsInstall) {
    Write-Host ""
    Write-Host "  Installing missing packages..." -ForegroundColor Cyan
    & $pythonExe -m pip install -r requirements.txt --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] pip install failed. Try manually:" -ForegroundColor Red
        Write-Host "    pip install python-vlc rich requests" -ForegroundColor Yellow
        Write-Host ""
        pause
        exit 1
    }
    Write-Host "  Packages installed." -ForegroundColor Green
} else {
    Write-Host "  All packages present." -ForegroundColor Green
}

# ── Configure Windows Terminal for Unicode ────────────────────────────────────
# Ensure UTF-8 output so Rich renders box-drawing characters correctly
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8

# ── Launch ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  Launching radio..." -ForegroundColor Cyan
Write-Host ""

if ($Category -ne "") {
    & $pythonExe radio.py -c $Category
} else {
    & $pythonExe radio.py
}

$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "  Radio exited with code $exitCode" -ForegroundColor Yellow
    Write-Host "  Run: .\Start-Radio.ps1 -Check  to diagnose issues" -ForegroundColor DarkGray
}
