@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title AI DUBBING STUDIO
set "PATH=%~dp0;%~dp0.tools\node;%PATH%"
if not exist "%~dp0venv\Scripts\python.exe" (
    echo [ERROR] Chua co moi truong Python. Chay INSTALL_NEW_PC.bat.
    pause
    exit /b 1
)
"%~dp0venv\Scripts\python.exe" "%~dp0modern_gui.py"
if errorlevel 1 (
    echo [ERROR] App da gap loi. Xem thong bao phia tren.
    pause
    exit /b 1
)
exit /b 0
