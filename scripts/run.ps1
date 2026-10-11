# Lance l'application locale sur 127.0.0.1 uniquement (http://127.0.0.1:8501).
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "Environnement absent : lancer .\scripts\setup.ps1" }
& $py -m streamlit run src/edgecourt/ui/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
