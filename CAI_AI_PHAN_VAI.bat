@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul

echo =============================================
echo  AI PHAN VAI - PYANNOTE (MOI TRUONG RIENG)
echo =============================================
echo Tool nay tao .venv_roles RIENG, KHONG SUA venv OMNIVOICE.
echo.
set "PYRUN="
py -3.11 -c "import sys" >nul 2>nul && set "PYRUN=py -3.11"
if not defined PYRUN py -3.12 -c "import sys" >nul 2>nul && set "PYRUN=py -3.12"
if not defined PYRUN py -3.10 -c "import sys" >nul 2>nul && set "PYRUN=py -3.10"
if not defined PYRUN (
  echo [LOI] Chua co Python 3.10, 3.11 hoac 3.12 trong Python Launcher.
  echo Hay cai Python 3.11 tu python.org roi chay lai.
  pause
  exit /b 1
)

if not exist ".venv_roles\Scripts\python.exe" (
  echo Tao virtualenv rieng...
  %PYRUN% -m venv .venv_roles
  if errorlevel 1 goto :failed
)

echo.
echo Cap nhat pip...
".venv_roles\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

echo.
echo Cai pyannote.audio va transformers...
".venv_roles\Scripts\python.exe" -m pip install "pyannote.audio>=4.0,<5" "transformers>=4.45,<5" "numpy<3"
if errorlevel 1 goto :failed

echo.
echo [OK] Da cai xong AI phan vai.
echo Ban co the mo app va bam AI PHAN VAI.
echo Khi quet AI, model se duoc tai tu Hugging Face va cache tai may lan dau.
pause
exit /b 0

:failed
echo.
echo [LOI] Cai dat that bai. Kiem tra ket noi Internet, Python va dung luong o dia.
pause
exit /b 1
