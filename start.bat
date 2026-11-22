@echo off
where pythonw.exe >nul 2>nul
if errorlevel 1 (
    python "%~dp0launch.py"
    if errorlevel 1 pause
    exit /b
)
start "" pythonw.exe "%~dp0launch.py"
