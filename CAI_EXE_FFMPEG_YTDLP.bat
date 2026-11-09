@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title AI DUBBING - CAI FFMPEG + YT-DLP + NODEJS
echo ===================================================
echo    KIEM TRA / CAI FFMPEG, YT-DLP, NODE.JS
echo ===================================================
echo.
echo Khong xoa video, voice, license, du lieu.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\SETUP_TOOLS.ps1" -AppDir "%~dp0"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo [OK] Cac cong cu download/video da san sang.) else (echo [LOI] Chua cai xong. Xem loi phia tren.)
echo.
pause
exit /b %RC%
