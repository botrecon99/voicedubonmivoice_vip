@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
title AI DUBBING - ONE CLICK INSTALL V4
color 0B
echo ===============================================================
echo      AI DUBBING STUDIO - CAI MAY MOI TU DONG V4
echo ===============================================================
echo  Tu cai Python / Git / FFmpeg / yt-dlp / Node / Selenium / AI
 echo  Khong xoa voices, video, license hay du lieu da co.
echo  Can mang Internet; ho tro Windows 10/11 x64.
echo ===============================================================
echo.
if not exist "%~dp0scripts\INSTALL_NEW_PC.ps1" (
  echo [ERROR] Thieu scripts\INSTALL_NEW_PC.ps1. Giai nen CA THU MUC trong ZIP.
  pause
  exit /b 2
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\INSTALL_NEW_PC.ps1"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  color 0A
  echo [OK] DA CAI DAT VA KIEM TRA XONG.
  echo [NEXT] Nhap key khi mo START_APP.bat.
) else (
  color 0C
  echo [ERROR] CAI DAT CHUA HOAN TAT. Xem dong loi ngay tren va log.
  echo [LOG] %%LOCALAPPDATA%%\AI_Dubbing_Studio\install_*.log
)
echo.
pause
exit /b %RC%
