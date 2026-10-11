# Initialise l'environnement local : venv .venv + dépendances figées. N'écrase aucun fichier utilisateur.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Test-Py([string]$exe, [string[]]$pre) {
    try {
        $ok = & $exe @pre -c "import sys; print(int(sys.version_info >= (3, 11)))" 2>$null
        return ($ok -eq '1')
    } catch { return $false }
}

$venvPy = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    $found = $null
    $cands = @(
        @{ exe = 'py'; pre = @('-3.11') }, @{ exe = 'py'; pre = @('-3.12') }, @{ exe = 'py'; pre = @('-3.13') },
        @{ exe = 'python'; pre = @() }
    )
    foreach ($p in (Get-ChildItem "$env:APPDATA\uv\python\*\python.exe" -ErrorAction SilentlyContinue)) {
        $cands += @{ exe = $p.FullName; pre = @() }
    }
    foreach ($c in $cands) {
        if (Get-Command $c.exe -ErrorAction SilentlyContinue) {
            if (Test-Py $c.exe $c.pre) { $found = $c; break }
        }
    }
    if (-not $found) { throw "Python >= 3.11 introuvable. Installer Python 3.11+ (python.org ou 'uv python install 3.11') puis relancer." }
    Write-Host "Python détecté : $($found.exe) $($found.pre -join ' ')"
    & $found.exe @($found.pre) -m venv .venv
}
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -r requirements.txt
& $venvPy -m pip install --quiet -e .
if (-not (Test-Path '.env') -and (Test-Path '.env.example')) { Copy-Item '.env.example' '.env' }
Write-Host "Environnement prêt. Suite : .\scripts\demo.ps1 puis .\scripts\run.ps1"
