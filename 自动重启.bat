@echo off
cd /d "C:\Users\simon\Doubao\chats\2026-09-24\new-chat-1"
:loop
tasklist /fi "imagename eq python.exe" | find /i "python.exe" >nul
if errorlevel 1 (
    echo 启动监测...
    start /min python monitor_final.py
)
timeout /t 60 /nobreak >nul
goto loop
