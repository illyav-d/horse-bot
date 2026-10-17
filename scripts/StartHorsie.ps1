$privateLauncher = Join-Path $PSScriptRoot "StartHorseBot.ps1"
if (Test-Path -LiteralPath $privateLauncher) {
    & $privateLauncher
} else {
    python (Join-Path (Split-Path -Parent $PSScriptRoot) "main.py")
}
