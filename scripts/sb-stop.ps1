# Stops the Second Brain bot and Ollama. Data (cards, index, archive, .env) is on disk and untouched.
$root = Split-Path -Parent $PSScriptRoot
# Stop the scheduled tasks first so they don't relaunch things (does NOT disable them).
foreach ($t in "SecondBrainBot", "SecondBrainSync") { Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue }

$bot = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'secondbrain\.cli\s+(bot|sync)' }
if ($bot) { $bot | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Write-Host "Bot/sync: stopped" } else { Write-Host "Bot: was not running" }

$o = Get-Process -Name "ollama", "ollama app", "ollama_llama_server" -ErrorAction SilentlyContinue
if ($o) { $o | Stop-Process -Force; Write-Host "Ollama: stopped" } else { Write-Host "Ollama: was not running" }
