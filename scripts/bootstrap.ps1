$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Python = if ($env:AI_UI_BOOTSTRAP_PYTHON) {
    $env:AI_UI_BOOTSTRAP_PYTHON
}
else {
    $VenvPython
}
$SystemPython = if ($env:AI_UI_BOOTSTRAP_SYSTEM_PYTHON) {
    $env:AI_UI_BOOTSTRAP_SYSTEM_PYTHON
}
else {
    'python'
}
$Pnpm = if ($env:AI_UI_BOOTSTRAP_PNPM) {
    $env:AI_UI_BOOTSTRAP_PNPM
}
else {
    'pnpm.cmd'
}
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $ProjectRoot '.playwright-browsers'

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock] $Command,
        [Parameter(Mandatory = $true)]
        [string] $Name
    )

    & $Command
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        throw "$Name failed with exit code $ExitCode"
    }
}

if (-not $env:AI_UI_BOOTSTRAP_PYTHON -and -not (Test-Path -LiteralPath $VenvPython)) {
    Invoke-NativeChecked {
        & $SystemPython -m venv (Join-Path $ProjectRoot '.venv')
    } 'Python virtual environment creation'
}

function Test-PythonDependencies {
    & $Python -c "import fastapi, jsonschema, mypy, playwright, pydantic_settings, pytest, ruff, uvicorn"
    return $LASTEXITCODE -eq 0
}

if (-not (Test-PythonDependencies)) {
    Invoke-NativeChecked { & $Python -m pip install --upgrade pip } 'pip bootstrap toolchain'
    Invoke-NativeChecked {
        & $Python -m pip install --requirement "$ProjectRoot\backend\requirements.lock"
    } 'Locked Python dependencies'
}

Invoke-NativeChecked {
    & $Python -m pip install --no-deps --editable "$ProjectRoot\backend"
} 'Editable backend package'
Invoke-NativeChecked { & $Python -m playwright install chromium } 'Playwright Chromium'

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'frontend\node_modules'))) {
    Push-Location (Join-Path $ProjectRoot 'frontend')
    try {
        Invoke-NativeChecked {
            & $Pnpm install --store-dir "$ProjectRoot\.pnpm-store"
        } 'Frontend dependencies'
    }
    finally {
        Pop-Location
    }
}

Write-Host 'Project dependencies are ready.'
