@echo off
cd /d "%~dp0"
set PYTHONW=C:\Users\q\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe
set PYTHON=C:\Users\q\.workbuddy\binaries\python\envs\default\Scripts\python.exe
if exist "%PYTHONW%" (
    start "" "%PYTHONW%" main.py
    exit
) else if exist "%PYTHON%" (
    "%PYTHON%" main.py
    pause
) else (
    echo [Error] Python not found.
    echo Please run: C:\Users\q\.workbuddy\binaries\python\versions\3.13.12\python.exe -m venv C:\Users\q\.workbuddy\binaries\python\envs\default
    pause
)
