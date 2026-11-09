@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title AI DUBBING - CHECK INSTALL
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\CHECK_INSTALL.ps1"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo [OK] Check hoan tat.) else (echo [ERROR] Van thieu thanh phan, chay INSTALL_NEW_PC.bat lai.)
pause
exit /b %RC%
