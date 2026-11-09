#requires -version 5.1
param([string]$SourceDir = '')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$RepoUrl = 'https://github.com/botrecon99/voicedubonmivoice_vip.git'
$AppName = 'AI Dubbing Studio'
$StateDir = Join-Path $env:LOCALAPPDATA 'AI_Dubbing_Studio'
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$Log = Join-Path $StateDir ('install_' + $Stamp + '.log')
$script:TranscriptStarted = $false

function Say([string]$Message) { Write-Host ('[SETUP] ' + $Message) -ForegroundColor Cyan }
function Warn([string]$Message) { Write-Host ('[WARN] ' + $Message) -ForegroundColor Yellow }
function Fail([string]$Message) { throw $Message }
function Run([string]$Exe, [string[]]$Argv) {
    Write-Host ('> ' + (Split-Path -Leaf $Exe) + ' ' + ($Argv -join ' ')) -ForegroundColor DarkGray
    & $Exe @Argv
    if ($LASTEXITCODE -ne 0) { Fail ("Command failed (exit $LASTEXITCODE): " + $Exe + ' ' + ($Argv -join ' ')) }
}
function Refresh-Path {
    $env:PATH = [Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('PATH', 'User') + ';' + $env:PATH
}
function Find-Program([string]$Name, [string[]]$Candidates = @()) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source)) { return $cmd.Source }
    foreach ($c in $Candidates) { if ($c -and (Test-Path -LiteralPath $c)) { return $c } }
    return $null
}
function Install-Winget([string]$Id) {
    $wg = Find-Program 'winget.exe'
    if (-not $wg) { Fail ("Thieu winget. Hay cai App Installer trong Microsoft Store, roi chay lai. Package: $Id") }
    Say ("Cai qua winget: $Id (co the yeu cau Windows UAC)")
    Run $wg @('install', '--id', $Id, '-e', '--accept-source-agreements', '--accept-package-agreements')
    Refresh-Path
}
function Get-Git {
    $g = Find-Program 'git.exe' @("$env:ProgramFiles\Git\cmd\git.exe", "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe", "$env:ProgramFiles\Git\bin\git.exe")
    if (-not $g) { Install-Winget 'Git.Git'; $g = Find-Program 'git.exe' @("$env:ProgramFiles\Git\cmd\git.exe", "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe") }
    if (-not $g) { Fail 'Da cai Git nhung chua tim thay git.exe. Mo cua so moi va chay lai.' }
    return $g
}
function Probe-Python312 {
    $py = Find-Program 'py.exe' @("$env:WINDIR\py.exe", "$env:LOCALAPPDATA\Programs\Python\Launcher\py.exe")
    if ($py) {
        & $py -3.12 -c 'import sys, struct; assert sys.version_info[:2] == (3,12) and struct.calcsize("P") == 8' *> $null
        if ($LASTEXITCODE -eq 0) { return @{ Path=$py; Prefix=@('-3.12') } }
    }
    $candidates = @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", "$env:ProgramFiles\Python312\python.exe", 'C:\Python312\python.exe')
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $candidates += $cmd.Source }
    foreach ($direct in $candidates) {
        if (-not (Test-Path -LiteralPath $direct)) { continue }
        & $direct -c 'import sys, struct; assert sys.version_info[:2] == (3,12) and struct.calcsize("P") == 8' *> $null
        if ($LASTEXITCODE -eq 0) { return @{ Path=$direct; Prefix=@() } }
    }
    return $null
}
function Get-Python312 {
    $found = Probe-Python312
    if ($found) { return $found }
    Install-Winget 'Python.Python.3.12'
    $found = Probe-Python312
    if ($found) { return $found }
    Fail 'Chua tim thay Python 3.12 x64 sau khi cai. Mo CMD moi va chay lai.'
}
function Ensure-FFmpeg {
    $ff = Find-Program 'ffmpeg.exe'
    if (-not $ff) {
        Install-Winget 'Gyan.FFmpeg'
        $ff = Find-Program 'ffmpeg.exe' @((Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\ffmpeg.exe'))
    }
    if (-not $ff) {
        $base = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
        if (Test-Path $base) {
            $candidate = Get-ChildItem -Path $base -Filter 'ffmpeg.exe' -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.FullName -match 'Gyan.FFmpeg' } | Select-Object -First 1
            if ($candidate) { $ff = $candidate.FullName; $env:PATH = (Split-Path -Parent $ff) + ';' + $env:PATH }
        }
    }
    if (-not $ff) { Fail 'FFmpeg da duoc goi cai nhung chua tim thay ffmpeg.exe. Mo CMD moi roi chay lai.' }
    Say ('FFmpeg OK: ' + $ff)
}
function Ensure-Chrome {
    $paths = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe")
    $installed = $false
    foreach ($p in $paths) { if (Test-Path -LiteralPath $p) { $installed=$true; break } }
    if ($installed) { Say 'Google Chrome OK (Selenium Manager se tu xu ly ChromeDriver).'; return }
    Say 'Khong co Google Chrome, cai cho Selenium...'
    Install-Winget 'Google.Chrome'
    Warn 'Neu Chrome vua cai, hay mo Chrome mot lan de hoan tat khoi tao ho so truoc khi dung Selenium.'
}
function Python-Venv([hashtable]$Python, [string]$Path) {
    $bin = Join-Path $Path 'Scripts\python.exe'
    if (-not (Test-Path $bin)) {
        Say ('Tao venv: ' + $Path)
        Run $Python.Path ($Python.Prefix + @('-m','venv', $Path))
    }
    if (-not (Test-Path $bin)) { Fail ('Tao venv that bai: ' + $Path) }
    & $bin -c 'import sys; assert sys.version_info[:2] == (3,12), sys.version' *> $null
    if ($LASTEXITCODE -ne 0) { Fail ("Env $Path khong dung Python 3.12. Sao luu env cu roi tao lai; script KHONG tu xoa env.") }
    return $bin
}
function Sha256([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Target-Dir([string]$Base, [string]$Git) {
    if ($Base -and (Test-Path -LiteralPath (Join-Path $Base '.git')) -and (Test-Path -LiteralPath (Join-Path $Base 'modern_gui.py'))) { return (Resolve-Path -LiteralPath $Base).Path }
    $d = if (Test-Path 'D:\') { 'D:\OmniVoice_multi_speaker' } else { Join-Path $env:USERPROFILE 'OmniVoice_multi_speaker' }
    if (Test-Path -LiteralPath (Join-Path $d '.git')) { return $d }
    if (Test-Path -LiteralPath $d) {
        $hasFiles = @(Get-ChildItem -LiteralPath $d -Force -ErrorAction Stop).Count -gt 0
        if ($hasFiles) { Fail "Thu muc $d da co du lieu ma khong phai Git clone. Khong ghi de. Hay doi ten thu muc / sao luu, hoac chay BAT ngay trong repo da git clone." }
    }
    Say ('Clone source ve: ' + $d)
    Run $Git @('clone', '--', $RepoUrl, $d)
    if (-not (Test-Path -LiteralPath (Join-Path $d 'modern_gui.py'))) { Fail 'GitHub repository chua co modern_gui.py. Hay PUSH source len GitHub truoc khi cai may moi.' }
    return $d
}

try {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { Fail 'Script nay chi chay tren Windows.' }
    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
    Start-Transcript -LiteralPath $Log -ErrorAction Stop | Out-Null; $script:TranscriptStarted=$true
    Say 'INSTALL NEW PC - AI DUBBING (Python 3.12 / Git / FFmpeg / CUDA)'
    Say ('Log: ' + $Log)
    Say 'Khong xoa downloaded_data, voices, license hay venv co san.'
    Refresh-Path
    $git = Get-Git
    # Neu BAT dang nam trong Git clone, tu nhan dien root tu PSScriptRoot.
    # Khong truyen 'D:\folder\' qua CMD argument de tranh loi quote trailing slash.
    $candidateRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
    if ((Test-Path -LiteralPath (Join-Path $candidateRoot '.git')) -and (Test-Path -LiteralPath (Join-Path $candidateRoot 'modern_gui.py'))) {
        $SourceDir = $candidateRoot
    }
    $appDir = Target-Dir $SourceDir $git
    Say ('App folder: ' + $appDir)
    $needed = @('modern_gui.py','core.py','role_review_ui.py','speaker_ai.py','license_client.py','license_ui.py','requirements.txt')
    foreach ($name in $needed) { if (-not (Test-Path -LiteralPath (Join-Path $appDir $name))) { Fail ("Repo thieu file: $name. Hay push FULL SOURCE len GitHub.") } }
    $py = Get-Python312
    Ensure-FFmpeg
    Ensure-Chrome
    $venvBin = Python-Venv $py (Join-Path $appDir 'venv')
    Say 'Cap nhat pip main env...'
    Run $venvBin @('-m','pip','install','--upgrade','pip','setuptools','wheel')
    $req = Join-Path $appDir 'requirements.txt'
    $stampFile = Join-Path $appDir '.setup\requirements.sha256'
    $hash = Sha256 $req
    $previous = if (Test-Path $stampFile) { [IO.File]::ReadAllText($stampFile).Trim() } else { '' }
    if ($hash -ne $previous) {
        Say 'Cai tat ca dependencies theo requirements.txt (lan dau co the tai vai GB)...'
        Run $venvBin @('-m','pip','install','-r', $req)
        New-Item -ItemType Directory -Path (Split-Path -Parent $stampFile) -Force | Out-Null
        [IO.File]::WriteAllText($stampFile, $hash)
    } else { Say 'Requirements khong doi: bo qua cai lai main env.' }
    & $venvBin -m pip show selenium *> $null
    if ($LASTEXITCODE -ne 0) {
        Say 'Cai Selenium...'
        Run $venvBin @('-m','pip','install','selenium>=4.15,<5')
    }
    Say 'Cai/kiem tra ffmpeg.exe, ffprobe.exe, yt-dlp.exe va Node.js cho taiok.bat...'
    Run 'powershell.exe' @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'SETUP_TOOLS.ps1'),'-AppDir',$appDir)
    Say 'Tao va cai AI phan vai Pyannote trong .venv_roles (rieng biet)...'
    $roleBin = Python-Venv $py (Join-Path $appDir '.venv_roles')
    Run $roleBin @('-m','pip','install','--upgrade','pip','setuptools','wheel')
    $rolesMarker = Join-Path $appDir '.setup\roles.ready'
    if (-not (Test-Path $rolesMarker)) {
        Run $roleBin @('-m','pip','install','pyannote.audio>=4.0,<5','transformers>=4.45,<5','numpy<3')
        $nvidia = Find-Program 'nvidia-smi.exe' @("$env:ProgramFiles\NVIDIA Corporation\NVSMI\nvidia-smi.exe")
        if ($nvidia) {
            Say 'NVIDIA phat hien: cai PyTorch CUDA 12.6 cho AI phan vai...'
            Run $roleBin @('-m','pip','install','torch==2.11.0','torchaudio==2.11.0','--index-url','https://download.pytorch.org/whl/cu126')
        } else { Warn 'Khong thay NVIDIA: Pyannote se dung CPU.' }
        New-Item -ItemType Directory -Path (Split-Path -Parent $rolesMarker) -Force | Out-Null
        [IO.File]::WriteAllText($rolesMarker, (Get-Date).ToString('o'))
    } else { Say 'Role env da cai: bo qua tai model libraries.' }
    $cfg = Join-Path $appDir 'license_config.json'
    $cfgExample = Join-Path $appDir 'license_config.example.json'
    if (-not (Test-Path $cfg) -and (Test-Path $cfgExample)) {
        Copy-Item -LiteralPath $cfgExample -Destination $cfg -ErrorAction Stop
        Warn 'Da tao license_config.json mau. CAN THAY URL Cloudflare Worker thuc te.'
    }
    [IO.File]::WriteAllText((Join-Path $StateDir 'installation_path.txt'), $appDir)
    Say 'Kiem tra nhanh Python, CUDA...'
    Run $venvBin @('-c','import torch, customtkinter, whisper, selenium; print("MAIN torch:", torch.__version__, "CUDA:",torch.cuda.is_available())')
    Run $roleBin @('-c','import torch, pyannote.audio; print("ROLES torch:", torch.__version__, "CUDA:",torch.cuda.is_available())')
    Say 'CAI DAT HOAN TAT! Chay START_APP.bat trong folder app.'
    Say 'Neu dung AI phan vai: can HF_TOKEN va quyen model Pyannote tren Hugging Face.'
    Warn 'Voi license: phai dien URL Cloudflare Worker vao license_config.json, sau do nhap key duoc admin cap.'
    if ($script:TranscriptStarted) { Stop-Transcript | Out-Null }
    exit 0
} catch {
    Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host ('[ERROR] Xem log: ' + $Log) -ForegroundColor Yellow
    if ($script:TranscriptStarted) { Stop-Transcript | Out-Null }
    exit 1
}
