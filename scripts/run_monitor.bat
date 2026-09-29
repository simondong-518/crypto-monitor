@echo off
rem =====================================================================
rem  crypto-monitor : the real run loop.
rem  Called by 自动重启.bat (interactive) or by the Scheduled Task (headless).
rem  Usage: run_monitor.bat [interactive^|headless]
rem
rem  Why each line exists (every one of these was a bug before):
rem
rem   * PYTHONUTF8=1 / PYTHONIOENCODING
rem       stdout is redirected to a log file; cmd's default cp936 then makes
rem       print() of Chinese text raise UnicodeEncodeError. That exception is
rem       swallowed by the main loop's except, so NOTHING gets pushed and the
rem       log shows no error at all.
rem   * chcp 65001 + ASCII file name
rem       keeps this script readable when launched by the Task Scheduler.
rem   * cd to the repo root (%~dp0..)
rem       the monitor reads/writes state next to the code. Starting from any
rem       other directory used to break it (the old script cd'd into a
rem       temporary folder on somebody else's machine).
rem   * python_exe.txt (optional, one absolute path, no quotes)
rem       pins WHICH interpreter runs the monitor. Needed when the task
rem       runs as SYSTEM (its PATH has none of your anaconda/user entries)
rem       or on any machine whose "python" lacks pandas.
rem       Verified: one line, LF or CRLF both work.
rem       scripts\setup_venv.bat creates a venv and writes this file.
rem   * the dependency check runs BEFORE the loop
rem       so a missing pandas is one clear message instead of a traceback
rem       every ten seconds.
rem   * ping -n 11 as sleep
rem       "timeout" needs a console and fails inside a Scheduled Task
rem       ("ERROR: Input redirection is not supported").
rem   * pause only in interactive mode
rem       a headless task would hang forever waiting for a keypress.
rem =====================================================================
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set "MODE=%~1"
if /i "%MODE%"=="" set "MODE=interactive"

set "ROOT=%~dp0.."
pushd "%ROOT%" || (echo [ERROR] cannot enter "%ROOT%" & exit /b 1)
if not exist "logs" mkdir "logs"
set "LOG=logs\monitor.log"

rem --- which interpreter? ------------------------------------------------
set "PY=python"
if exist "python_exe.txt" set /p PY=<python_exe.txt

echo [%DATE% %TIME%] ===== start (mode=%MODE%, py="%PY%", cwd=%CD%) ===== >> "%LOG%"

"%PY%" -c "import pandas, requests" 1>>"%LOG%" 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] this interpreter cannot import pandas/requests: "%PY%"
    echo.
    echo   fix A: run  scripts\setup_venv.bat   ^(creates .venv + python_exe.txt^)
    echo   fix B: install into the current one:  "%PY%" -m pip install -r requirements.txt
    echo          then write its full path into python_exe.txt
    echo.
    echo   details: %CD%\%LOG%
    if /i "%MODE%"=="interactive" pause
    popd
    exit /b 1
)

rem --- run loop: a foreground child, restarted whenever it exits --------
:loop
for %%A in ("%LOG%") do if %%~zA GTR 5242880 move /y "%LOG%" "%LOG%.1" >nul
echo [%DATE% %TIME%] main.py start >> "%LOG%"
"%PY%" main.py >> "%LOG%" 2>&1
echo [%DATE% %TIME%] main.py exited (code %ERRORLEVEL%), restart in 10s >> "%LOG%"
ping -n 11 127.0.0.1 >nul 2>&1
goto loop
