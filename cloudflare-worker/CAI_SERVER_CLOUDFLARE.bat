@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo AI DUBBING - CLOUDFLARE WORKER + D1 INITIAL SETUP
 echo ============================================================
echo.
echo [1] Dang nhap Cloudflare (mo trinh duyet de xac thuc)
call npx wrangler login
if errorlevel 1 goto fail
echo.
echo [2] Tao database D1. NEU DATABASE DA TON TAI THI BO QUA LENH NAY.
echo Ban can copy database_id duoc in ra vao file wrangler.toml.
choice /C YN /M "Tao D1 database moi"
if errorlevel 2 goto skipcreate
call npx wrangler d1 create ai-dubbing-license-db
:skipcreate
echo.
echo [3] MO FILE wrangler.toml VA THAY database_id = "THAY_BANG_D1_DATABASE_ID"
echo Chua thay ID thi dung: npx wrangler d1 list
notepad wrangler.toml
pause
echo.
echo [4] Apply migration vao database remote
call npx wrangler d1 migrations apply ai-dubbing-license-db --remote
if errorlevel 1 goto fail
echo.
echo [5] Deploy Worker
call npx wrangler deploy
if errorlevel 1 goto fail
echo.
echo [6] Cai ADMIN_TOKEN va KEY_ENCRYPTION_KEY (secret KHONG nam trong source)
echo Chay file TAO_SECRET_CLOUDFLARE.ps1 o thu muc cha de tao 2 ma.
echo Pastes moi ma khi Wrangler hoi.
call npx wrangler secret put ADMIN_TOKEN
if errorlevel 1 goto fail
call npx wrangler secret put KEY_ENCRYPTION_KEY
if errorlevel 1 goto fail
echo.
echo XONG. Sao chep dia chi https://...workers.dev vao client_patch\license_config.json
pause
exit /b 0
:fail
echo.
echo LOI THIET LAP. Doc README_HUONG_DAN.md va kiem tra Cloudflare.
pause
exit /b 1
