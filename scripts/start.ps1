param([int]$Port = 18080)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $pythonExe)) { throw 'Run setup.ps1 first.' }
if (!(Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html'))) { throw 'Build the frontend first: cd frontend; npm.cmd ci; npm.cmd run build' }
Write-Host "Open http://127.0.0.1:$Port/ | API docs: http://127.0.0.1:$Port/docs"
& $pythonExe -m uvicorn backend.app.main:app --host 127.0.0.1 --port $Port --no-proxy-headers
if ($LASTEXITCODE -ne 0) { throw 'Backend exited with an error.' }
