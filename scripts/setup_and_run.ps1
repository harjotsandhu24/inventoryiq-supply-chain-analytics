# InventoryIQ one-step setup for Windows PowerShell.
# Usage (from the repository root):
#   powershell -ExecutionPolicy Bypass -File scripts\setup_and_run.ps1            # setup + build + start
#   powershell -ExecutionPolicy Bypass -File scripts\setup_and_run.ps1 -Pipeline  # also rebuild data from data\raw
param([switch]$Pipeline)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements-dev.txt
& .\.venv\Scripts\python.exe -m pip install --quiet -e . --no-deps

if ($Pipeline) {
    if (Test-Path "data\raw\sales_train_evaluation.csv") {
        & .\.venv\Scripts\python.exe -m inventoryiq.pipeline --source m5
    } else {
        Write-Host "data\raw not found - the app will use the synthetic demo data. See docs\data_access.md."
    }
}

Set-Location app
npm.cmd ci
npm.cmd run build
Write-Host "Starting InventoryIQ at http://localhost:3000 (Ctrl+C to stop)"
npm.cmd run start
