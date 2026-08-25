$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$BackendSrc = Join-Path $ProjectRoot 'backend\src'

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Project virtual environment not found. Run scripts\bootstrap.cmd first.'
}

$PreviousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $BackendSrc

Push-Location (Join-Path $ProjectRoot 'backend')
try {
    & $Python -m uvicorn ai_ui_explorer.main:create_app --factory --reload --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
    $env:PYTHONPATH = $PreviousPythonPath
}
