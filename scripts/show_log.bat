@echo off
rem Show the tail of the monitor log (the only view you get in headless mode).
setlocal
chcp 65001 >nul
set "LOG=%~dp0..\logs\monitor.log"
if not exist "%LOG%" (
    echo No log yet: %LOG%
    pause
    exit /b 1
)
powershell -NoProfile -Command "Get-Content -Tail 80 -Encoding UTF8 '%LOG%'"
echo.
echo ---- %LOG% ----
pause
