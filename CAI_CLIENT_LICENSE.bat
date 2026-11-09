@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "DEST=D:\OmniVoice_multi_speaker"
if not exist "%DEST%\modern_gui.py" (
 echo KHONG TIM THAY %DEST%\modern_gui.py
 echo Hay sua bien DEST tai dong 4 trong file BAT theo duong dan thuc te.
 pause
 exit /b 1
)
if not exist "%~dp0client_patch\modern_gui.py" (
 echo Chua giai nen du goi ZIP hoac thieu thu muc client_patch.
 pause
 exit /b 1
)
echo.
echo ====================================================
echo CAI LICENSE VAO: %DEST%
echo CHI THAY GUI + THU VIEN LICENSE, KHONG DOI core.py
echo ====================================================
echo.
choice /C YN /M "Da dong AI Dubbing Studio va muon cai dat"
if errorlevel 2 exit /b 0
powershell -NoProfile -Command "$p='%DEST%\modern_gui.py'; $backup=$p+'.bak_'+(Get-Date -Format 'yyyyMMdd_HHmmss'); Copy-Item -LiteralPath $p -Destination $backup -ErrorAction Stop; Write-Host ('Da sao luu: '+$backup)"
if errorlevel 1 goto failed
copy /Y "%~dp0client_patch\modern_gui.py" "%DEST%\modern_gui.py" >nul
if errorlevel 1 goto failed
copy /Y "%~dp0client_patch\license_client.py" "%DEST%\license_client.py" >nul
if errorlevel 1 goto failed
copy /Y "%~dp0client_patch\license_ui.py" "%DEST%\license_ui.py" >nul
if errorlevel 1 goto failed
if not exist "%DEST%\license_config.json" copy /Y "%~dp0client_patch\license_config.json" "%DEST%\license_config.json" >nul
echo.
echo DA CAI XONG FILE LICENSE.
echo Quan trong: Nhap URL Cloudflare Workers thuc te vao license_config.json.
notepad "%DEST%\license_config.json"
pause
exit /b 0
:failed
echo.
echo CAI DAT LOI. Vui long khoi phuc modern_gui.py tu file .bak.
pause
exit /b 1
