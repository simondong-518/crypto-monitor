@echo off
rem ================================================================
rem  crypto-monitor 一键启动（双击本文件）= 前台运行 + 日志
rem
rem  它只负责切 UTF-8 然后调用 scripts\run_monitor.bat interactive。
rem  真正的逻辑（依赖自检 / 崩溃重启 / 日志轮转 / 解释器定位）都在
rem  那个文件里 —— 计划任务也调用同一个文件，避免两处逻辑各自走偏。
rem
rem  想让它"无窗口 + 开机自启" → scripts\install_task.bat
rem  日志怎么看                 → scripts\show_log.bat
rem ================================================================
chcp 65001 >nul
call "%~dp0scripts\run_monitor.bat" interactive
