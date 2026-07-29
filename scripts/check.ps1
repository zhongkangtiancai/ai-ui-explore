$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $ProjectRoot '.playwright-browsers'

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Project virtual environment not found. Run scripts\bootstrap.cmd first.'
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock] $Command,
        [Parameter(Mandatory = $true)]
        [string] $Name
    )

    Write-Host "[$Name]"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

Push-Location (Join-Path $ProjectRoot 'backend')
try {
    Invoke-Checked { & $Python -m pytest } 'Backend tests'
    Invoke-Checked { & $Python -m ruff check . } 'Backend lint'
    Invoke-Checked { & $Python -m mypy } 'Backend typecheck'
}
finally {
    Pop-Location
}

Push-Location (Join-Path $ProjectRoot 'frontend')
try {
    Invoke-Checked { pnpm.cmd test } 'Frontend tests'
    Invoke-Checked { pnpm.cmd lint } 'Frontend lint'
    Invoke-Checked { pnpm.cmd typecheck } 'Frontend typecheck'
    Invoke-Checked { pnpm.cmd format:check } 'Frontend format'
    Invoke-Checked { pnpm.cmd build } 'Frontend build'
}
finally {
    Pop-Location
}

Write-Host 'All quality checks passed.'
