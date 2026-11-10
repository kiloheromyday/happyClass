param([switch]$WithAI)
$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskProjectRoot
if (!(Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Please install Docker Desktop with Linux containers first.' }
& docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop before running this script.' }
$taskSecretDirectory = Join-Path $taskProjectRoot '.docker/secrets'
New-Item -ItemType Directory -Path $taskSecretDirectory -Force | Out-Null
foreach ($taskSecretName in @('ai-service.token', 'ai-ingest.token')) {
    $taskSecretFile = Join-Path $taskSecretDirectory $taskSecretName
    if (!(Test-Path -LiteralPath $taskSecretFile)) {
        $taskBytes = New-Object byte[] 48
        $taskRng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $taskRng.GetBytes($taskBytes) } finally { $taskRng.Dispose() }
        $taskStream = [System.IO.File]::Open($taskSecretFile, [System.IO.FileMode]::CreateNew)
        try {
            $taskEncoded = [System.Text.Encoding]::UTF8.GetBytes([Convert]::ToBase64String($taskBytes))
            $taskStream.Write($taskEncoded, 0, $taskEncoded.Length)
        } finally { $taskStream.Dispose() }
    }
    if (([System.IO.File]::ReadAllText($taskSecretFile)).Trim().Length -lt 32) { throw "Invalid existing secret: $taskSecretName" }
}
$taskComposeArguments = @('compose')
if ($WithAI) { $taskComposeArguments += @('--profile', 'ai') }
$taskComposeArguments += @('up', '--build', '--detach', '--wait')
& docker @taskComposeArguments
if ($LASTEXITCODE -ne 0) { throw 'Compose startup failed. Check docker compose logs.' }
Write-Output 'HappyClass is ready at http://127.0.0.1:18090 (or your EMOJI_WEB_PORT).'
Write-Output 'Create your own first administrator with: docker compose exec web python -m backend.manage create-user --username admin --role ADMIN'
