# Registers (or removes) a Windows Task Scheduler task that, every 2 hours, summarises new Claude Code sessions
# and any dropped claude.ai export into private cards (`sb sync`). Local model only: it uses NO Claude quota.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\install-sync-task.ps1          (install)
#         powershell -ExecutionPolicy Bypass -File scripts\install-sync-task.ps1 -Remove  (uninstall)
# Log: raw\sync.log (one line per run).
param([switch]$Remove)

$ErrorActionPreference = "Stop"
$taskName = "SecondBrainSync"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed task $taskName (if it existed)."
    exit 0
}

$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { Write-Error "Not found: $pythonw (create the .venv first)"; exit 1 }

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m secondbrain.cli sync --limit 3" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Hours 2) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Second Brain: summarise new Claude Code sessions and dropped claude.ai exports locally. Log: raw\sync.log" -Force | Out-Null
$registered = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $registered) { Write-Error "Task $taskName was not created."; exit 1 }
Write-Host "Registered task $taskName (state: $($registered.State)). Runs every 2 hours. Log: $root\raw\sync.log"
