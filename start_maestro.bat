@echo off
setlocal
title Maestro
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo Maestro is not installed yet: the folder .venv is missing.
    echo Please ask IT to follow the Quick Start and Web interface steps in README.md.
    goto :fail
)

call ".venv\Scripts\activate.bat"

where maestro >nul 2>nul
if errorlevel 1 (
    echo.
    echo The maestro command is missing in .venv.
    echo Please ask IT to run: pip install -e ".[ui]"
    goto :fail
)

echo Starting Maestro. Your browser opens in a few seconds.
echo Keep this window open while you use Maestro. Close it to stop Maestro.
echo.
maestro ui
if errorlevel 1 (
    echo.
    echo Maestro stopped with an error. Please send the messages above to IT.
    goto :fail
)
exit /b 0

:fail
echo.
pause
exit /b 1
