@echo off
rem ================================================================
rem  crypto-monitor 守护启动（Windows）
rem  用法：直接双击本文件。日志写在 logs\monitor.log
rem
rem  为什么这么写 —— 三个坑，原文都踩了：
rem
rem   1) 必须 set PYTHONUTF8=1
rem      日志重定向到文件时 cmd 默认按 cp936 编码，print(中文) 会抛 UnicodeEncodeError；
rem      而 print(报告) 发生在 send_wx() 之前 → 异常被主循环的 except 吃掉 → 每轮都不推送，
rem      而且日志里连一条报错都看不到。
rem
rem   2) 用 %~dp0 定位脚本自己所在的目录
rem      原文 cd 到 C:\Users\simon\Doubao\chats\2026-09-24\new-chat-1（别人机器的临时目录），
rem      然后启动 monitor_final.py（仓库里根本没有这个文件）→ 永远起不来。
rem
rem   3) 判活要判"主进程还在不在"，而不是"有任意 python 进程就算活着"
rem      原文 tasklist|find python.exe 只要机器上任何一个 python 在跑就认为活着，
rem      于是主程序早崩了也永远不重启。这里改成一个前台子进程：它退出就重启。
rem
rem   另外：启动前先做依赖自检，缺 pandas/requests 直接说清楚要装什么，不要留一堆看不懂的报错。
rem ================================================================
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

if not exist "logs" mkdir "logs"
set LOG=logs\monitor.log

echo [%DATE% %TIME%] ===== 守护启动，工作目录 %CD% ===== >> "%LOG%"

python -c "import pandas, requests" 1>>"%LOG%" 2>&1
if errorlevel 1 (
    echo.
    echo [依赖缺失] 请先在本目录执行:  pip install -r requirements.txt
    echo 详细错误见 logs\monitor.log
    pause
    exit /b 1
)

:loop
echo [%DATE% %TIME%] 启动 main.py >> "%LOG%"
python main.py >> "%LOG%" 2>&1
echo [%DATE% %TIME%] main.py 已退出（退出码 %ERRORLEVEL%），10 秒后重启 >> "%LOG%"
timeout /t 10 /nobreak >nul
goto loop
