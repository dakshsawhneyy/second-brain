# Starts everything Second Brain needs: Ollama (local model) + the Telegram bot. Safe to run twice.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (-not (Test-Path $pythonw)) { Write-Error "Not found: $pythonw"; exit 1 }

function Get-BotProcess {
    Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'secondbrain\.cli\s+bot' }
}
function Test-Ollama {
    try { Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null; $true } catch { $false }
}

# 1. Ollama
if (Test-Ollama) { Write-Host "Ollama: already running" }
elseif (Test-Path $ollama) {
    Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden
    for ($i = 0; $i -lt 15 -and -not (Test-Ollama); $i++) { Start-Sleep -Seconds 1 }
    if (Test-Ollama) { Write-Host "Ollama: started" } else { Write-Warning "Ollama did not respond (bot still starts; triage/summaries will wait)" }
} else { Write-Warning "Ollama not found at $ollama" }

# 2. Bot (Telegram allows ONE poller, so never start a second)
if (Get-BotProcess) { Write-Host "Bot: already running" }
else {
    Stop-ScheduledTask -TaskName SecondBrainBot -ErrorAction SilentlyContinue   # avoid the logon task racing us
    Start-Process -FilePath $pythonw -ArgumentList "-m secondbrain.cli bot" -WorkingDirectory $root -WindowStyle Hidden
    Start-Sleep -Seconds 3
    if (Get-BotProcess) { Write-Host "Bot: started" } else { Write-Error "Bot exited immediately. See raw\bot.log"; exit 1 }
}
Write-Host "Log: $root\raw\bot.log"
