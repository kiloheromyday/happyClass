param([int]$Port = 18080)
$ErrorActionPreference = 'Stop'
$previousDemoMode = $env:EMOJI_DEMO_MODE
try {
    $env:EMOJI_DEMO_MODE = '1'
    & (Join-Path $PSScriptRoot 'start.ps1') -Port $Port
} finally {
    $env:EMOJI_DEMO_MODE = $previousDemoMode
}
