@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title AI DUBBING - GIT UPDATE
echo ======================================================
echo               AI DUBBING - UPDATE
 echo     git pull --ff-only origin current-branch
 echo ======================================================
echo.
echo Hay DONG app truoc khi chay update.
echo.
if not exist "%~dp0scripts\UPDATE.ps1" (
    echo [ERROR] Thieu scripts\UPDATE.ps1. Hay giai nen ZIP vao thu muc goc Studio.
    pause
    exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\UPDATE.ps1"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo [OK] Cap nhat thanh cong.) else (echo [LOI] Cap nhat chua xong. Khong tu dong git reset/clean.)
echo.
pause
exit /b %RC%
