@echo off
rem =====================================================================
rem  One-time setup: create a venv for this project and record its
rem  interpreter path in python_exe.txt.
rem
rem  Why: pin the interpreter this project runs with, instead of depending on
rem  whatever "python" happens to be on PATH. A Scheduled Task running as
rem  SYSTEM has none of the user's PATH entries, so a bare "python" would
rem  fail there while working fine in your own console.
rem  (Measured on the dev box: every interpreter already had pandas, so this
rem   is about reproducibility and the SYSTEM case - not a missing dependency.)
rem
rem  Requires network (downloads pandas + requests, ~30 MB).
rem =====================================================================
setlocal
chcp 65001 >nul
set "ROOT=%~dp0.."
pushd "%ROOT%" || (echo [ERROR] cannot enter "%ROOT%" & exit /b 1)

echo [1/4] creating .venv ...
python -m venv .venv
if errorlevel 1 (
    echo [ERROR] "python -m venv" failed. Is "python" on PATH an interpreter with venv?
    echo         Try: py -3 -m venv .venv
    pause
    popd
    exit /b 1
)

echo [2/4] upgrading pip ...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip

echo [3/4] installing requirements ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed - check the network / proxy.
    pause
    popd
    exit /b 1
)

echo [4/4] writing python_exe.txt ...
> "python_exe.txt" echo %ROOT%\.venv\Scripts\python.exe

echo.
echo --- verify ----------------------------------------------------------
".venv\Scripts\python.exe" -c "import pandas, requests, sys; print('python', sys.version.split()[0]); print('pandas', pandas.__version__); print('OK')"
echo.
echo python_exe.txt now contains:
type python_exe.txt
echo.
echo Next: scripts\install_task.bat   (headless, starts at boot)
echo   or : double-click 自动重启.bat  (foreground + log)
pause
popd
