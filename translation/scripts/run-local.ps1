<# Runs project entry points safely on a workstation with GPIO mocked. #>

[CmdletBinding()]
param(
    [ValidateSet("main", "play-events")]
    [string]$Target = "main"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Local environment not found. Run .\scripts\setup-local.ps1 first."
}

# gpiozero's mock pin factory prevents this workstation from attempting any
# physical GPIO access. It is appropriate for logic/testing only.
$env:GPIOZERO_PIN_FACTORY = "mock"

Push-Location $projectRoot
try {
    if ($Target -eq "main") {
        & $python main.py
    }
    else {
        & $python play_events.py
    }
}
finally {
    Pop-Location
}

