# ─────────────────────────────────────────────────────────────────────────────
# GramWrite — Windows Installer (PowerShell)
# Run as: powershell -ExecutionPolicy Bypass -File install.ps1
# ─────────────────────────────────────────────────────────────────────────────

param(
    [switch]$SkipBackendCheck,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$GramWriteDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $GramWriteDir ".venv"

# ── Colours ───────────────────────────────────────────────────────────────────
function Write-Log  { Write-Host "  ▸ $args" -ForegroundColor Cyan }
function Write-Ok   { Write-Host "  ✓ $args" -ForegroundColor Green }
function Write-Warn { Write-Host "  ⚠ $args" -ForegroundColor Yellow }
function Write-Err  { Write-Host "  ✗ $args" -ForegroundColor Red }
function Write-Head { Write-Host "`n  $args" -ForegroundColor White }

# ── Banner ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ┌─────────────────────────────────────────┐" -ForegroundColor DarkGray
Write-Host "  │  G R A M W R I T E   v1.0.0             │" -ForegroundColor DarkGray
Write-Host "  │  The Invisible Editor for Screenwriters  │" -ForegroundColor DarkGray
Write-Host "  └─────────────────────────────────────────┘" -ForegroundColor DarkGray
Write-Host ""

# ── Python check ──────────────────────────────────────────────────────────────
Write-Head "Checking Python..."

$Python = $null
$PythonCandidates = @("python3.12", "python3.11", "python3.10", "python3", "python")

foreach ($cmd in $PythonCandidates) {
    try {
        $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver) {
            $parts = $ver.Split(".")
            $major = [int]$parts[0]
            $minor = [int]$parts[1]
            if ($major -ge 3 -and $minor -ge 10) {
                $Python = $cmd
                Write-Ok "Found $cmd ($ver)"
                break
            }
        }
    } catch {}
}

if (-not $Python) {
    Write-Err "Python 3.10+ required."
    Write-Host "    Download from: https://python.org/downloads" -ForegroundColor DarkGray
    exit 1
}

# ── Virtual environment ────────────────────────────────────────────────────────
Write-Head "Setting up virtual environment..."

if (Test-Path $VenvDir) {
    Write-Warn "Existing .venv found — reinstalling"
    Remove-Item -Recurse -Force $VenvDir
}

& $Python -m venv $VenvDir
if ($LASTEXITCODE -ne 0) {
    Write-Err "Failed to create virtual environment"
    exit 1
}
Write-Ok "Virtual environment created at .venv"

$PipExe = Join-Path $VenvDir "Scripts\pip.exe"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"

# Upgrade pip
& $PipExe install --upgrade pip --quiet

# ── Core dependencies ─────────────────────────────────────────────────────────
Write-Head "Installing core dependencies..."

& $PipExe install aiohttp PyQt6 PyYAML --quiet
Write-Ok "Core packages installed"

# ── Windows-specific ─────────────────────────────────────────────────────────
Write-Head "Installing Windows-specific packages..."

& $PipExe install uiautomation psutil --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Ok "uiautomation + psutil installed"
} else {
    Write-Warn "uiautomation install failed — text extraction may not work"
}

# ── Install GramWrite ─────────────────────────────────────────────────────────
Write-Head "Installing GramWrite..."

Push-Location $GramWriteDir
& $PipExe install -e . --quiet
Pop-Location
Write-Ok "GramWrite installed (editable mode)"

# ── LLM Backend check ────────────────────────────────────────────────────────
if (-not $SkipBackendCheck) {
    Write-Head "Checking LLM backends..."

    $BackendOk = $false

    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            Write-Ok "Ollama is running at localhost:11434"
            $BackendOk = $true

            # Check for model
            if (-not ($resp.Content -match "qwen3.5")) {
                Write-Log "Pulling qwen3.5:0.8b..."
                try {
                    & ollama pull qwen3.5:0.8b
                    Write-Ok "qwen3.5:0.8b ready"
                } catch {
                    Write-Warn "Could not pull model. Run: ollama pull qwen3.5:0.8b"
                }
            } else {
                Write-Ok "qwen3.5:0.8b already available"
            }
        }
    } catch {}

    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:1234/v1/models" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            Write-Ok "LM Studio is running at localhost:1234"
            $BackendOk = $true
        }
    } catch {}

    if (-not $BackendOk) {
        Write-Warn "No LLM backend detected."
        Write-Host ""
        Write-Host "    Ollama (recommended, free):" -ForegroundColor DarkGray
        Write-Host "      https://ollama.com → install → run: ollama pull qwen3.5:0.8b" -ForegroundColor DarkGray
        Write-Host ""
        Write-Host "    LM Studio:" -ForegroundColor DarkGray
        Write-Host "      https://lmstudio.ai → download a model → start local server" -ForegroundColor DarkGray
    }
}

# ── Create launch script ──────────────────────────────────────────────────────
Write-Head "Creating launch script..."

$LaunchScript = @"
@echo off
set DIR=%~dp0
call "%DIR%.venv\Scripts\activate.bat"
python -m gramwrite %*
"@

$LaunchPath = Join-Path $GramWriteDir "gramwrite.bat"
$LaunchScript | Out-File -FilePath $LaunchPath -Encoding ASCII
Write-Ok "Created gramwrite.bat"

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  Installation complete." -ForegroundColor Green
Write-Host ""
Write-Host "  Start GramWrite:   .\gramwrite.bat" -ForegroundColor White
Write-Host "  With settings:     .\gramwrite.bat --dashboard" -ForegroundColor White
Write-Host "  Debug mode:        .\gramwrite.bat --verbose" -ForegroundColor White
Write-Host ""
Write-Host "  Write first. Polish never. GramWrite exists in the background." -ForegroundColor DarkGray
Write-Host ""
