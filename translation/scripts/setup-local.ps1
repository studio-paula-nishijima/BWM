<#
Creates the workstation virtual environment used for development without Pi
hardware.  Python 3.11 matches Raspberry Pi OS Bookworm's default version.
#>

[CmdletBinding()]
param(
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venv = Join-Path $projectRoot ".venv"

if (-not $Python) {
    $candidates = @(
        (Get-Command py -ErrorAction SilentlyContinue | ForEach-Object { $_.Source }),
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }

    if ($candidates.Count -eq 0) {
        throw "Python 3.11 was not found. Install Python 3.11, then rerun this script (or pass -Python <path-to-python.exe>)."
    }

    $Python = $candidates[0]
}

& $Python --version
& $Python -m venv $venv

$venvPython = Join-Path $venv "Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $projectRoot "requirements\requirements_local.txt")

Write-Host "Local environment created: $venv"
Write-Host "Run .\scripts\run-local.ps1 from the translation directory."

