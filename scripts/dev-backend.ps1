$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Project virtual environment not found. Run scripts\bootstrap.cmd first.'
}

Push-Location (Join-Path $ProjectRoot 'backend')
try {
    & $Python -m uvicorn ai_ui_explorer.main:app --reload --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
}
