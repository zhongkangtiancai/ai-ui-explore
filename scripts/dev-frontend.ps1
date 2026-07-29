$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Push-Location (Join-Path $ProjectRoot 'frontend')
try {
    pnpm.cmd dev --host 127.0.0.1 --port 5173
}
finally {
    Pop-Location
}
