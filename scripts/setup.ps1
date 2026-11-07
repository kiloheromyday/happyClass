param([string]$UvPath)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    if ($UvPath) { python -m venv --without-pip .venv }
    else { python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment.' }
}
if ($UvPath) { & $UvPath pip install --python '.venv\Scripts\python.exe' -r requirements.txt pip }
else { & '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt }
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
Push-Location frontend
try {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
