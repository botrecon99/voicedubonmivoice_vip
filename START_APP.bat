@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" "modern_gui.py"
) else if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "modern_gui.py"
) else (
  echo [ERROR] Thieu main venv. Chay INSTALL_NEW_PC.bat truoc.
  pause
  exit /b 1
)
if errorlevel 1 (echo [ERROR] App exited with error. & pause)
