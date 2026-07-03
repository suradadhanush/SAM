# SAM Setup Script — Windows
# Run in PowerShell as Administrator:
# Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
# .\setup_windows.ps1

Write-Host "
  ╔═══════════════════════════════════╗
  ║          SAM — Setup              ║
  ║  Personal AI. Fully Local.        ║
  ╚═══════════════════════════════════╝
" -ForegroundColor Blue

# ─── Check Python ─────────────────────────────────────────────────────────
Write-Host "[1/7] Checking Python..." -ForegroundColor Green
$pyVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python not found. Download from https://python.org" -ForegroundColor Red
    exit 1
}
Write-Host "  Found: $pyVersion"

# ─── Install Ollama ───────────────────────────────────────────────────────
Write-Host "[2/7] Installing Ollama..." -ForegroundColor Green
$ollamaPath = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollamaPath) {
    Write-Host "  Downloading Ollama for Windows..."
    $ollamaUrl = "https://ollama.com/download/OllamaSetup.exe"
    $installerPath = "$env:TEMP\OllamaSetup.exe"
    Invoke-WebRequest -Uri $ollamaUrl -OutFile $installerPath
    Start-Process -FilePath $installerPath -ArgumentList "/S" -Wait
    Write-Host "  Ollama installed"
} else {
    Write-Host "  Ollama already installed"
}

# ─── Start Ollama ─────────────────────────────────────────────────────────
Write-Host "[3/7] Starting Ollama..." -ForegroundColor Green
Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 3

# ─── Pull Models ──────────────────────────────────────────────────────────
Write-Host "[4/7] Pulling AI models (this takes time)..." -ForegroundColor Green

# Detect RAM
$ram = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
$ramGB = [math]::Round($ram / 1GB)
Write-Host "  Detected RAM: ${ramGB}GB"

if ($ramGB -ge 32) { $model = "qwen2.5:32b" }
elseif ($ramGB -ge 16) { $model = "qwen2.5:14b" }
else { $model = "qwen2.5:7b" }

Write-Host "  Pulling brain model: $model"
ollama pull $model

Write-Host "  Pulling embedding model: nomic-embed-text"
ollama pull nomic-embed-text

Write-Host "  Pulling vision model: moondream"
ollama pull moondream

# ─── Python Environment ───────────────────────────────────────────────────
Write-Host "[5/7] Creating Python virtual environment..." -ForegroundColor Green
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip --quiet

Write-Host "  Installing Python packages..."
pip install -r requirements.txt --quiet

Write-Host "  Installing Windows-specific packages..."
pip install pyttsx3 pywinauto --quiet

Write-Host "  Installing Playwright browsers..."
playwright install chromium

# ─── Directory Structure ──────────────────────────────────────────────────
Write-Host "[6/7] Creating directories..." -ForegroundColor Green
New-Item -ItemType Directory -Force -Path logs | Out-Null
New-Item -ItemType Directory -Force -Path memory\store\chroma | Out-Null
New-Item -ItemType Directory -Force -Path founder_mode\store | Out-Null
New-Item -ItemType Directory -Force -Path founder_mode\export | Out-Null
New-Item -ItemType Directory -Force -Path skills\compiled | Out-Null

# ─── Windows Task Scheduler (auto-start) ─────────────────────────────────
Write-Host "[7/7] Setting up auto-start via Task Scheduler..." -ForegroundColor Green
$scriptDir = $PSScriptRoot
$action = New-ScheduledTaskAction `
    -Execute "$scriptDir\.venv\Scripts\python.exe" `
    -Argument "$scriptDir\main.py" `
    -WorkingDirectory $scriptDir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0)
Register-ScheduledTask `
    -TaskName "SAM-Assistant" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force | Out-Null
Write-Host "  Task Scheduler entry created: SAM-Assistant"

Write-Host "
╔═══════════════════════════════════════════════════════╗
║               SAM Setup Complete! (Windows)           ║
╠═══════════════════════════════════════════════════════╣
║  Brain model: $model
║                                                       ║
║  To start SAM now:                                    ║
║  .\.venv\Scripts\Activate.ps1                        ║
║  python main.py                                       ║
║                                                       ║
║  SAM auto-starts on login via Task Scheduler.         ║
║  Say 'Hey SAM' to wake it.                            ║
╚═══════════════════════════════════════════════════════╝
" -ForegroundColor Blue
