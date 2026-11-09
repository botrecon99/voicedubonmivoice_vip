AI DUBBING - FIX EXE CHO MAY MOI

1) Giai nen toan bo vao D:\OmniVoice_multi_speaker (giu folder scripts).
2) Tren may cu da cai venv: chay CAI_EXE_FFMPEG_YTDLP.bat de test.
3) Tren may moi: chay INSTALL_NEW_PC.bat, da tu goi SETUP_TOOLS.ps1.
4) Upload len GitHub 3 file: INSTALL_NEW_PC.bat, CAI_EXE_FFMPEG_YTDLP.bat, scripts/INSTALL_NEW_PC.ps1, scripts/SETUP_TOOLS.ps1 (4 file).
5) Khong upload ffmpeg.exe, ffprobe.exe, yt-dlp.exe, cookies.txt; .gitignore da loai tru.
6) Cookie YouTube la du lieu ca nhan: moi may can tu nap neu tinh nang tai video yeu cau.
7) Node.js LTS duoc cai vi taiok.bat dung --js-runtimes node.

CMD PUSH:
cd /d D:\OmniVoice_multi_speaker
git add INSTALL_NEW_PC.bat CAI_EXE_FFMPEG_YTDLP.bat scripts/INSTALL_NEW_PC.ps1 scripts/SETUP_TOOLS.ps1
git commit -m "Install FFmpeg and yt-dlp on new PCs"
git push origin main

Luu y: bo cai chua the chay tren Windows trong moi truong sandbox nay.
