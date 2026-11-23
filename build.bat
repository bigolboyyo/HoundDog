@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 1
set "failed=0"

echo [1/2] Building HoundDog...
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File "HoundDog\build_exe.ps1"
if errorlevel 1 (
    echo HoundDog build failed.
    set "failed=1"
) else (
    echo HoundDog build succeeded.
)

echo.
echo [2/2] Building ThetaDesk...
python "ThetaDesk\start_project.py" --setup-only
if errorlevel 1 (
    echo ThetaDesk environment setup failed.
    set "failed=1"
) else (
    powershell.exe -NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File "ThetaDesk\build_exe.ps1"
    if errorlevel 1 (
        echo ThetaDesk build failed.
        set "failed=1"
    ) else (
        echo ThetaDesk build succeeded.
    )
)

echo.
if "%failed%"=="0" (
    echo Both builds succeeded.
) else (
    echo One or more builds failed. See the output above.
)
popd
if /i not "%~1"=="--no-pause" pause
exit /b %failed%
