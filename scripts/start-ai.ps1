param([int]$Port = 18081)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
& '.\.venv\Scripts\python.exe' -m uvicorn ai_service.main:app --host 127.0.0.1 --port $Port
if ($LASTEXITCODE -ne 0) { throw 'AI service exited with an error.' }
