# Lance la suite de tests.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "Environnement absent : lancer .\scripts\setup.ps1" }
& $py -m pytest -q
