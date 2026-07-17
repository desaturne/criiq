# Weekly ICC-rankings refresh for Criiq.
#
# Runs `criiq_data.cli rankings`, which:
#   1. fetches the current ICC rankings -- live from the ICC endpoint if
#      CRIIQ_ICC_RANKINGS_CLIENT_ID is set, otherwise reloading the local
#      rankings CSV (it degrades safely, never errors, when the credential
#      is absent), and
#   2. rebuilds player_registry + player_cards so the new ranks propagate to
#      activity status and the "standing" score component.
#
# Scheduled for Fridays 13:00 via Windows Task Scheduler -- see
# `data-collection/README.md`, "Scheduled weekly ICC rankings update".
# Registered with:
#   schtasks /create /tn "Criiq ICC Rankings Weekly" /sc weekly /d FRI /st 13:00 /f `
#     /tr "powershell -NoProfile -ExecutionPolicy Bypass -File \"<repo>\data-collection\scripts\weekly_icc_update.ps1\""
$ErrorActionPreference = "Stop"

# data-collection dir = parent of this script's /scripts folder (portable; no
# hard-coded absolute path, so it survives the repo being moved/renamed).
$dataCollection = Split-Path $PSScriptRoot -Parent
$py = Join-Path $dataCollection ".venv\Scripts\python.exe"
$logDir = Join-Path $dataCollection "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "icc_weekly.log"

$ts = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
Add-Content -Path $log -Value "==== $ts  weekly ICC rankings update ===="
Set-Location $dataCollection
& $py -m criiq_data.cli rankings 2>&1 | Add-Content -Path $log
Add-Content -Path $log -Value "==== done (exit $LASTEXITCODE) ===="
