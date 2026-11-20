# Registers (or removes) a Windows Task Scheduler task that starts the Second Brain Telegram bot at logon.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1          (install)
#         powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1 -Remove  (uninstall)
# Run it only with the user's approval. Do not run `sb bot` by hand while the task is running
# (Telegram allows one poller per bot and would answer "Conflict").
param([switch]$Remove)

$ErrorActionPreference = "Stop"   # a failed step must stop the script, never print a fake success
$taskName = "SecondBrainBot"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed task $taskName (if it existed)."
    exit 0
}

$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { Write-Error "Not found: $pythonw (create the .venv first)"; exit 1 }

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m secondbrain.cli bot" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"  # DOMAIN\user is required
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Second Brain Telegram bot (morning brief, evening check-in, quick capture). Logs: raw\bot.log" -Force | Out-Null
$registered = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $registered) { Write-Error "Task $taskName was not created."; exit 1 }
Write-Host "Registered task $taskName (state: $($registered.State)). It starts at your next logon. Logs: $root\raw\bot.log"
