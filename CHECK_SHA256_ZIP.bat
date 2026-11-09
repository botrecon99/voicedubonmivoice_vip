@echo off
chcp 65001 >nul
if "%~1"=="" (
 echo Keo file ZIP tha len file BAT nay, hoac chay: CHECK_SHA256_ZIP.bat duong_dan_file.zip
 pause
 exit /b 1
)
powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath '%~1').Hash.ToLowerInvariant()"
pause
