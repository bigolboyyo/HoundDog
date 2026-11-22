@echo off
setlocal
cd /d "%~dp0"
python watcher_server.py %*
if errorlevel 1 (
    echo.
    echo HoundDog server exited with an error.
    pause
)
