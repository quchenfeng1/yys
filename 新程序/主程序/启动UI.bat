@echo off
chcp 65001 >nul
title 阴阳师自动化工具
cd /d "%~dp0"

rem 优先用项目根 .venv（d:\yys\.venv），找不到再试本目录 .venv
if exist "..\..\.venv\Scripts\python.exe" (
    "..\..\.venv\Scripts\python.exe" main.py
    goto :end
)
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
    goto :end
)

echo [错误] 未找到 Python 虚拟环境（..\..\.venv 或 .venv）
echo 请先创建：python -m venv ..\..\.venv 并安装依赖
pause
goto :eof

:end
if errorlevel 1 pause
