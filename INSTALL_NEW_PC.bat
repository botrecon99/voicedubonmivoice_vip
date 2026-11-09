@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title AI DUBBING - INSTALL NEW PC
echo ======================================================
echo           AI DUBBING - INSTALL NEW PC
echo   Git + Python 3.12 + FFmpeg + CUDA + Selenium
echo ======================================================
echo.
echo Hay dong AI Dubbing Studio truoc khi cai.
echo Khong xoa du lieu video / voice / key license.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\INSTALL_NEW_PC.ps1" -SourceDir "%~dp0"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo [OK] Cai dat thanh cong.) else (echo [LOI] Cai dat chua xong. Xem log trong LOCALAPPDATA\AI_Dubbing_Studio.)
echo.
pause
exit /b %RC%
