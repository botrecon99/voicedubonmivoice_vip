@echo off
cd /d "%~dp0"
title MODERN GUI LAUNCHER

echo ====================================
echo       MODERN GUI LAUNCHER
echo ====================================

REM Kiem tra Python
py --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Khong tim thay Python!
    echo Hay cai Python truoc.
    pause
    exit /b 1
)

REM Kiem tra venv cu co bi loi khong
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe --version >nul 2>&1
    if errorlevel 1 (
        echo [FIX] Venv cu bi loi, dang xoa...
        rmdir /s /q "venv"
    )
)

REM Tao lai venv neu chua co
if not exist "venv\Scripts\python.exe" (
    echo [SETUP] Dang tao moi venv...
    py -m venv venv
    if errorlevel 1 goto error

    echo [SETUP] Dang cai dependencies...
    venv\Scripts\python.exe -m pip install --upgrade pip
    if exist "requirements.txt" (
        venv\Scripts\python.exe -m pip install -r requirements.txt
        if errorlevel 1 goto error
    )
)

REM Chay GUI
echo [START] Dang chay modern_gui.py...
venv\Scripts\python.exe modern_gui.py

if errorlevel 1 goto error
pause
exit /b 0

:error
echo.
echo [ERROR] Co loi xay ra!
pause
exit /b 1