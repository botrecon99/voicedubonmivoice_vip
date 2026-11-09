AI DUBBING STUDIO - ONE CLICK INSTALLER V4

MAY MOI (Windows 10/11 x64, internet, it nhat 16GB RAM khuyen dung):
1. Clone GitHub vao BAT KY thu muc nao. Neu khong co git, tai ZIP source GitHub va giai nen.
2. Copy 5 file/thu muc cua ZIP nay vao folder cung cap core.py:
   INSTALL_NEW_PC.bat; START_APP.bat; CHECK_INSTALL.bat; scripts/INSTALL_NEW_PC.ps1 va scripts/CHECK_INSTALL.ps1
3. Double click INSTALL_NEW_PC.bat, cho phep UAC khi can.
4. Neu hien OK: mo START_APP.bat va nhap License Key cap tren trang Admin.
5. Sau khi cai: nhap CHECK_INSTALL.bat de kiem tra lai.

Neu dang cai do loi, KHONG XOA THU MUC, click INSTALL_NEW_PC.bat lan nua.
Script KHONG git reset/clean, KHONG xoa voices/video/license/cache.
Khi khong co NVIDIA: su dung Torch CPU; khi driver moi: dung CUDA.
Model AI Pyannote lan dau van can HF_TOKEN va chap nhan dieu khoan cua Hugging Face.
May khong co mang, Windows ARM/32-bit, driver loi, khong du o cung/ram hoac bi Windows policy chan cai dat KHONG duoc dam bao.

LOG: %%LOCALAPPDATA%%\AI_Dubbing_Studio\install_*.log
GIT: sau khi test xong, PUSH INSTALL_NEW_PC.bat START_APP.bat CHECK_INSTALL.bat va scripts\INSTALL_NEW_PC.ps1 scripts\CHECK_INSTALL.ps1 len repo.
DIEU QUAN TRONG: requirements.txt van duoc GIU NGUYEN de khong thay doi code render.
