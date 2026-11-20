$bot = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'secondbrain\.cli\s+bot' }
Write-Host ("Bot:    " + $(if ($bot) { "RUNNING (pid $($bot.ProcessId))" } else { "stopped" }))
$ok = try { Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null; $true } catch { $false }
Write-Host ("Ollama: " + $(if ($ok) { "RUNNING" } else { "stopped" }))
Write-Host "Last log lines:"; Get-Content (Join-Path (Split-Path -Parent $PSScriptRoot) "raw\bot.log") -Tail 3
$root = Split-Path -Parent $PSScriptRoot
foreach ($f in "inbox", "outbox") {
    $p = Join-Path $root "raw\$f.json"
    $n = 0
    if (Test-Path $p) { try { $j = Get-Content $p -Raw | ConvertFrom-Json; $n = if ($f -eq "outbox") { @($j.items.PSObject.Properties).Count } else { @($j.PSObject.Properties).Count } } catch {} }
    Write-Host ("{0,-7} {1} waiting" -f ($f + ":"), $n)
}
