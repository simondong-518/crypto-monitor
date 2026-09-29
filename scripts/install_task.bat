@echo off
rem =====================================================================
rem  Register crypto-monitor as a Windows Scheduled Task (headless run).
rem
rem  Result : starts at boot, no window, keeps running after logoff.
rem  Log    : logs\monitor.log
rem  Remove : scripts\uninstall_task.bat
rem
rem  Run this ONCE. If Task Scheduler refuses to create the task, open a
rem  command prompt with "Run as administrator" and run this file again.
rem =====================================================================
setlocal
chcp 65001 >nul
set "TASKNAME=crypto-monitor"
set "RUNNER=%~dp0run_monitor.bat"
set "ROOT=%~dp0.."

if not exist "%RUNNER%" (
    echo [ERROR] not found: %RUNNER%
    pause
    exit /b 1
)

rem --- 1. an absolute interpreter path is REQUIRED for a SYSTEM task ----
rem (SYSTEM's PATH has no anaconda/user entries, so a bare "python" would
rem  fail there while working fine in your own console.)
if not exist "%ROOT%\python_exe.txt" (
    echo.
    echo [ERROR] %ROOT%\python_exe.txt is missing.
    echo         A task running as SYSTEM cannot rely on PATH; it needs an
    echo         absolute interpreter path.
    echo.
    echo   run  scripts\setup_venv.bat   first ^(creates .venv + python_exe.txt^),
    echo   or  write the full path of a python that has pandas into
    echo       %ROOT%\python_exe.txt
    echo.
    pause
    exit /b 1
)
set "PY=python"
set /p PY=<"%ROOT%\python_exe.txt"
echo Using interpreter: "%PY%"
"%PY%" -c "import pandas, requests" || (
    echo [ERROR] that interpreter cannot import pandas/requests.
    pause
    exit /b 1
)

rem --- 2. create / overwrite the task ----------------------------------
rem /sc onstart  -> at system boot
rem /ru SYSTEM   -> no password needed, hidden, survives logoff
echo Creating task "%TASKNAME%" ...
schtasks /create /f /tn "%TASKNAME%" /tr "\"%RUNNER%\" headless" /sc onstart /ru SYSTEM /rl highest
if errorlevel 1 (
    echo.
    echo [ERROR] schtasks failed. Re-run this file from an elevated prompt.
    pause
    exit /b 1
)

rem --- 3. start it now and verify --------------------------------------
echo Starting it now ...
schtasks /run /tn "%TASKNAME%" >nul
ping -n 12 127.0.0.1 >nul

echo.
echo --- task state -----------------------------------------------------
schtasks /query /tn "%TASKNAME%" /fo LIST | findstr /i "TaskName Status Last"
echo.
echo --- log (last 15 lines) -------------------------------------------
if exist "%ROOT%\logs\monitor.log" (
    powershell -NoProfile -Command "Get-Content -Tail 15 -Encoding UTF8 '%ROOT%\logs\monitor.log'"
) else (
    echo   ^(no log yet - wait ~30s and run scripts\show_log.bat^)
)
echo.
echo Done. It will start automatically at every boot.
echo Remove it with scripts\uninstall_task.bat
pause
