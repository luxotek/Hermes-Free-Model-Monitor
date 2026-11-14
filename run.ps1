# Launcher: finds a usable Python and opens the app in a hidden-window process.
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$candidates = @()
$toolsDir = Join-Path $env:LOCALAPPDATA "hermes\tools"
if (Test-Path $toolsDir) {
    $candidates += Get-ChildItem $toolsDir -Directory -Filter "python-*" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        ForEach-Object { Join-Path $_.FullName "pythonw.exe" }
}
$candidates += (Get-Command pythonw -ErrorAction SilentlyContinue).Source

$pythonw = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if (-not $pythonw) {
    Write-Host "No pythonw.exe found. Install Python 3 (with tkinter) or reinstall Hermes tools." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

Start-Process -FilePath $pythonw -ArgumentList "`"$scriptDir\app.pyw`""
