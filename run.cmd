@echo off
REM Debug launcher: same app, but with a console so tracebacks are visible.
setlocal
set "FOUND="
for /d %%D in ("%LOCALAPPDATA%\hermes\tools\python-*") do (
    if exist "%%D\python.exe" set "FOUND=%%D\python.exe"
)
if not defined FOUND (
    where python >nul 2>&1 && set "FOUND=python"
)
if not defined FOUND (
    echo No python.exe found.
    exit /b 1
)
"%FOUND%" "%~dp0app.pyw"
pause
