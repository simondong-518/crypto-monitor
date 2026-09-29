@echo off
rem =====================================================================
rem  Stop and unregister the crypto-monitor Scheduled Task.
rem  NOTE: this does NOT kill the python process that is already running.
rem        To stop it, use Task Manager and end the "python.exe" whose
rem        command line contains main.py - do NOT "taskkill /im python.exe"
rem        blindly, that kills every other python program on the machine.
rem =====================================================================
setlocal
chcp 65001 >nul
set "TASKNAME=crypto-monitor"

echo Stopping task "%TASKNAME%" ...
schtasks /end /tn "%TASKNAME%" 2>nul
echo Deleting task "%TASKNAME%" ...
schtasks /delete /f /tn "%TASKNAME%"
if errorlevel 1 (
    echo.
    echo [INFO] nothing to delete (task not registered, or needs an elevated prompt).
)

echo.
echo --- the running python process -------------------------------------
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*main.py*' }; if ($p) { $p | ForEach-Object { Write-Host ('  still running: PID ' + $_.ProcessId + ' - ' + $_.CommandLine); Stop-Process -Id $_.ProcessId -Force; Write-Host '  -> stopped' } } else { Write-Host '  none found' }"
echo.
echo Checked at %DATE% %TIME%
pause
