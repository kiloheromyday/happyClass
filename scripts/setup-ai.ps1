param([string]$UvPath)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if ($UvPath) { & $UvPath pip install --python '.venv\Scripts\python.exe' -r ai_service\requirements-ai.txt }
else { & '.\.venv\Scripts\python.exe' -m pip install -r ai_service\requirements-ai.txt }
if ($LASTEXITCODE -ne 0) { throw 'AI dependency installation failed.' }
& '.\.venv\Scripts\python.exe' scripts\prepare_ai.py
if ($LASTEXITCODE -ne 0) { throw 'Model preparation failed.' }
