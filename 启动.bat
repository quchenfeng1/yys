@echo off
cd /d "%~dp0"

REM YYS Auto Script Launcher v2.1
REM Tries multiple Python installations in priority order

REM Try 1: workbuddy venv pythonw (has all dependencies)
set "PYTHONW=C:\Users\q\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
if exist "%PYTHONW%" (
    start "" "%PYTHONW%" main.py
    exit
)

REM Try 2: workbuddy venv python
set "PYTHON=C:\Users\q\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if exist "%PYTHON%" (
    "%PYTHON%" main.py
    pause
    exit
)

REM Try 3: System Python 3.13 pythonw
set "PYTHONW=C:\Users\q\AppData\Local\Programs\Python\Python313\pythonw.exe"
if exist "%PYTHONW%" (
    start "" "%PYTHONW%" main.py
    exit
)

REM Try 4: System Python 3.13 python
set "PYTHON=C:\Users\q\AppData\Local\Programs\Python\Python313\python.exe"
if exist "%PYTHON%" (
    "%PYTHON%" main.py
    pause
    exit
)

echo [ERROR] No Python installation found.
pause
exit /b 1
