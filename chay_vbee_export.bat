@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 vbee_export_all.py
) else (
    python vbee_export_all.py
)
echo.
pause
