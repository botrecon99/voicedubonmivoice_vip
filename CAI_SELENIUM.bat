@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)
echo Dang cai Selenium de tu bat URL MP3 khi nghe thu tren Vbee...
"%PYTHON_EXE%" -m pip install --upgrade "selenium>=4.15"
if errorlevel 1 (
  echo KHONG CAI DUOC: Hay chay python -m pip install selenium trong dung moi truong Python cua app.
) else (
  echo DA CAI XONG. Selenium Manager se tim ChromeDriver khi mo Chrome lan dau.
)
pause
