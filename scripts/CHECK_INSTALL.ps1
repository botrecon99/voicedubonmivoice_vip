#requires -Version 5.1
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Write-Host ('APP: ' + $root)
$checks=@('core.py','modern_gui.py','venv\Scripts\python.exe','.venv_roles\Scripts\python.exe','ffmpeg.exe','ffprobe.exe','yt-dlp.exe','license_config.json')
$bad=$false
foreach($check in $checks){
 $ok=Test-Path -LiteralPath (Join-Path $root $check)
 $prefix = if($ok){'[OK]'}else{'[THIEU]'}
 Write-Host ($prefix + ' ' + $check)
 if(-not $ok){$bad=$true}
}
if(Test-Path (Join-Path $root 'venv\Scripts\python.exe')){
 & (Join-Path $root 'venv\Scripts\python.exe') -c 'import torch,customtkinter,whisper,omnivoice,selenium;print("MAIN",torch.__version__,"CUDA",torch.cuda.is_available())'
 if($LASTEXITCODE -ne 0){$bad=$true}
}
if(Test-Path (Join-Path $root '.venv_roles\Scripts\python.exe')){
 & (Join-Path $root '.venv_roles\Scripts\python.exe') -c 'import torch,pyannote.audio;print("ROLES",torch.__version__,"CUDA",torch.cuda.is_available())'
 if($LASTEXITCODE -ne 0){$bad=$true}
}
if($bad){Write-Host '[ERROR] Cai dat chua du. Chay INSTALL_NEW_PC.bat lai.' -ForegroundColor Red;exit 1}
Write-Host '[OK] Cai dat co du cac thanh phan da kiem tra.' -ForegroundColor Green
exit 0
