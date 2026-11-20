$bot = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'secondbrain\.cli\s+bot' }
Write-Host ("Bot:    " + $(if ($bot) { "RUNNING (pid $($bot.ProcessId))" } else { "stopped" }))
$ok = try { Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null; $true } catch { $false }
Write-Host ("Ollama: " + $(if ($ok) { "RUNNING" } else { "stopped" }))
Write-Host "Last log lines:"; Get-Content (Join-Path (Split-Path -Parent $PSScriptRoot) "raw\bot.log") -Tail 3
