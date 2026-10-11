# Télécharge les sources gratuites autorisées (NFL, soccer, NBA si clé) puis évalue les données réelles.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "Environnement absent : lancer .\scripts\setup.ps1" }
$env:PYTHONIOENCODING = 'utf-8'
& $py -m edgecourt.cli fetch
& $py -m edgecourt.cli run --origin real
