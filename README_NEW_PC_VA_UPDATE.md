# AI Dubbing Studio — Install new PC + GitHub Update

Repo chinh: `https://github.com/botrecon99/voicedubonmivoice_vip.git`

## A. MAY CHU / CHU PHAN MEM (LAM LAN DAU)

1. **PUSH full source trong ZIP nay vao repo GitHub**, giu `INSTALL_NEW_PC.bat`, `UPDATE.bat`, `START_APP.bat`, folder `scripts/` o cung cap voi `modern_gui.py`, `core.py`, `requirements.txt`.
2. Neu repo dang empty, can tao first commit va `git push` truoc khi cai may moi.
3. KHONG push `license_config.json` (URL local), `%LOCALAPPDATA%\AI_Dubbing_Studio\license.json`, `.env`, `.dev.vars`, `voices/`, `downloaded_data/`, `.venv_roles/` va `venv/`. File `.gitignore` da chan cac duong dan tren, nhung nen kiem tra `git status` truoc khi push.
4. `cloudflare-worker` la SERVER LICENSE, chi admin deploy. MAY CLIENT khong can Node.js / D1 / admin token.

## B. CAI MAY WINDOWS 10/11 MOI (NHAP MOT LAN)

**Cach khuyen nghi (de UPDATE hoat dong):** Sau khi repo co source, `git clone https://github.com/botrecon99/voicedubonmivoice_vip.git` (hoac tai bootstrap bundle nho) va chay `INSTALL_NEW_PC.bat`.

- Neu BAT dang o trong *Git clone*: cai ngay trong folder repo do.
- Neu BAT duoc chay tu *bo kit* khong co `.git`: tu clone vao `D:\OmniVoice_multi_speaker` (neu may co o D) hoac `%USERPROFILE%\OmniVoice_multi_speaker`.
- Script tu cai Git, Python 3.12 x64, FFmpeg va Chrome qua Windows winget neu chua co. Windows co the hoi quyen UAC. Can Internet va nhieu GB dung luong de tai PyTorch/AI.
- Tao `venv` chinh va cai nguyen file `requirements.txt` ma ban cung cap (Torch 2.5.1 CUDA 12.4), them Selenium.
- Tao `.venv_roles` rieng cho Pyannote. Neu co NVIDIA, thu cai PyTorch CUDA 12.6 cho AI phan vai. Hai venv KHONG chong cheo.
- Sinh `license_config.json` tu `license_config.example.json` NEU no chua ton tai. Doi `api_url` thanh Worker URL that va nhap license key khi mo app.
- Ghi log tai `%LOCALAPPDATA%\AI_Dubbing_Studio\install_*.log`. Neu loi se dung, KHONG in thong bao thanh cong gia.
- Model Pyannote tren Hugging Face co the yeu cau chap nhan gated license + HF_TOKEN. Installer chi cai dependencies, khong tu xin token.
- Sau khi cai, chay `START_APP.bat`.

**Luu y compatibility:** requirements file export tu may cu co `torch==2.5.1+cu124`. Wheel Windows phien ban nay ho tro Python 3.10/3.11/3.12, KHONG co cp313 Windows cu124. Vi vay script dung Python 3.12 de tranh loi incompatible wheels. Neu dependeny tuong lai thay doi, can cap nhat requirements.

## C. CAP NHAT PHAN MEM

1. Admin commit va push code moi len GitHub (nhanh main hoac nhanh hien tai).
2. May client DONG APP, nhan `UPDATE.bat`.
3. Script chi dung `git pull --ff-only origin <branch-dang-dung>`; neu co file tracked dang sua local => DUNG, KHONG ghi de; neu divergence => DUNG (khong force, reset, clean).
4. Code duoc sao luu vao `%LOCALAPPDATA%\AI_Dubbing_Studio\source_backup_*` truoc khi pull. Neu `requirements.txt` doi thi tu dong cai lai dependencies cua `venv`.
5. KHONG xoa voice, video, key license, .venv_roles hay du lieu. Log tai `%LOCALAPPDATA%\AI_Dubbing_Studio\update_*.log`.

**Quan trong:** `UPDATE.bat` chi keo SOURCE tu GitHub, KHONG giai quyet phien ban ban phat hanh bat buoc cua Cloudflare. Neu Admin bat `mandatory update`, phai cap nhat ca `APP_VERSION` trong `license_client.py` va version tren D1 cho khop. Neu dung GitHub private repo, may moi phai duoc cap quyen Git truoc.

## D. DE TU DONG CLONE TREN MAY MOI KHONG CAN TU GO GIT

Giai nen ZIP, chi can mang bo **`INSTALL_NEW_PC.bat` + `scripts/INSTALL_NEW_PC.ps1`** sang may moi. Nhap dup BAT -> no tu cai Git, clone repo da duoc push va cai deps. Neu repo van empty, script se dung, khong bao cai xong sai.

## E. KIEM TRA THU CONG NEU GAP LOI

```bat
venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
.venv_roles\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
git status
git remote -v
```

**Chua the chay Windows installer / network install tren may that tu sandbox Linux.** Scripts duoc dong goi, kiem tra file va Python source compile; can test thuc te tren may Windows co NVIDIA. 
