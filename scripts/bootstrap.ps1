$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $ProjectRoot '.playwright-browsers'

if (-not (Test-Path -LiteralPath $Python)) {
    python -m venv (Join-Path $ProjectRoot '.venv')
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -e "$ProjectRoot\backend[dev]"
& $Python -m playwright install chromium

Push-Location (Join-Path $ProjectRoot 'frontend')
try {
    pnpm.cmd install --store-dir "$ProjectRoot\.pnpm-store"
}
finally {
    Pop-Location
}

Write-Host 'Project dependencies are ready.'
