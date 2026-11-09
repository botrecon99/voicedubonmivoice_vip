@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title AI DUBBING - INSTALL ALL IN ONE V6
color 0B
echo ==========================================================
echo      AI DUBBING - INSTALL ALL IN ONE - V6
echo ==========================================================
echo  1 FILE DUY NHAT: cai tu GitHub hoac source da clone.
echo  Python 3.12, FFmpeg, yt-dlp, Node, AI, CUDA/CPU, License.
echo  KHONG xoa video, giong noi, key va moi truong da co.
echo ==========================================================
echo.
set "AI_DUB_INSTALL_SELF=%~f0"
set "AI_DUB_INSTALL_FOLDER=%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $source=[IO.File]::ReadAllText($env:AI_DUB_INSTALL_SELF,[Text.Encoding]::UTF8); $m=('#'+'=BEGIN_AI_POWERSHELL='); $i=$source.LastIndexOf($m,[StringComparison]::Ordinal); if($i -lt 0){throw 'Thieu ma cai dat nhung trong file BAT.'}; & ([ScriptBlock]::Create($source.Substring($i+$m.Length)))"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  color 0A
  echo [OK] BO CAI DA HOAN TAT CAC BUOC KIEM TRA.
  echo [NEXT] Mo START_APP.bat tai thu muc source, nhap License Key.
) else (
  color 0C
  echo [ERROR] CHUA CAI XONG. Chay lai cung file BAT sau khi xu ly loi.
  echo [LOG] %%LOCALAPPDATA%%\AI_Dubbing_Studio\install_*.log
)
echo.
pause
exit /b %RC%
#=BEGIN_AI_POWERSHELL=
#requires -Version 5.1
# ONE FILE INSTALL V6 - Windows 10/11 x64, PowerShell 5.1+
# User files and secrets are never deleted. Rerun to resume after network failures.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$script:Repo = 'https://github.com/botrecon99/voicedubonmivoice_vip.git'
$script:LicenseApi = 'https://ai-dubbing-license.laughlicense-pnmedia2026.workers.dev'
$script:State = Join-Path $env:LOCALAPPDATA 'AI_Dubbing_Studio'
$script:Cache = Join-Path $script:State 'installer_cache'
$script:Log = Join-Path $script:State ('install_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.log')
$script:Root = [IO.Path]::GetFullPath($env:AI_DUB_INSTALL_FOLDER)
$script:App = $null
$script:TranscriptOn = $false
$script:MainReady = $false
$script:RolesReady = $false
$script:CUDA = $false
$script:Warns = New-Object 'System.Collections.Generic.List[string]'

function Info([string]$m) { Write-Host ('[OK/SETUP] ' + $m) -ForegroundColor Cyan }
function Note([string]$m) { Write-Host ('[NOTE] ' + $m) -ForegroundColor DarkYellow }
function Warning([string]$m) { $script:Warns.Add($m); Write-Host ('[WARN] ' + $m) -ForegroundColor Yellow }
function ErrorStop([string]$m) { throw $m }
function Step([int]$number,[string]$title) { Write-Host ''; Write-Host ('=========== BUOC ' + $number + '/9: ' + $title + ' ===========') -ForegroundColor Green }
function Exec([string]$file,[string[]]$arglist) {
    if (-not $file) { ErrorStop 'Chua tim thay executable.' }
    Write-Host ('> ' + (Split-Path -Leaf $file) + ' ' + ($arglist -join ' ')) -ForegroundColor DarkGray
    $old = $ErrorActionPreference
    try {
        $ErrorActionPreference='Continue'
        # Display command output, but do not leak it as a function return value.
        & $file @arglist 2>&1 | Out-Host
        $rc = $LASTEXITCODE
    } finally { $ErrorActionPreference=$old }
    if ($rc -ne 0) { ErrorStop ('Lenh loi exit=' + $rc + ': ' + $file) }
}
function TryExec([string]$file,[string[]]$arglist) {
    if (-not $file) { return $false }
    try { Exec $file $arglist; return $true } catch { Warning ('Lenh khong thanh cong: ' + $_.Exception.Message); return $false }
}
function PathRefresh {
    $m = [Environment]::GetEnvironmentVariable('PATH','Machine')
    $u = [Environment]::GetEnvironmentVariable('PATH','User')
    $env:PATH = $m + ';' + $u + ';' + $env:PATH
}
function Locate([string]$exe,[string[]]$candidates = @()) {
    foreach ($f in $candidates) { if ($f -and (Test-Path -LiteralPath $f -PathType Leaf)) { return $f } }
    $c = Get-Command $exe -ErrorAction SilentlyContinue
    if ($c -and $c.Source -and (Test-Path -LiteralPath $c.Source -PathType Leaf)) { return $c.Source }
    return $null
}
function Download([string]$url,[string]$dest,[long]$minBytes = 1024) {
    if (Test-Path -LiteralPath $dest) { if ((Get-Item -LiteralPath $dest).Length -ge $minBytes) { return } }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
    for ($i=1; $i -le 3; $i++) {
        try {
            Info ('Tai lan ' + $i + ': ' + $url)
            $part = $dest + '.partial'
            if (Test-Path -LiteralPath $part) { Remove-Item -LiteralPath $part -Force }
            Invoke-WebRequest -Uri $url -UseBasicParsing -OutFile $part -TimeoutSec 600 -MaximumRedirection 8 -ErrorAction Stop
            if ((Get-Item -LiteralPath $part).Length -lt $minBytes) { throw 'File tai ve qua nho.' }
            Move-Item -LiteralPath $part -Destination $dest -Force
            return
        } catch {
            Note ('Tai that bai: ' + $_.Exception.Message)
            if ($i -eq 3) { throw }
            Start-Sleep -Seconds (3 * $i)
        }
    }
}
function VerifyPublisher([string]$path) {
    $sig = Get-AuthenticodeSignature -LiteralPath $path
    if ($sig.Status -ne 'Valid') { ErrorStop ('Chu ky file cai khong hop le: ' + $path + ' - ' + $sig.Status) }
}
function WingetInstall([string]$id) {
    $wg = Locate 'winget.exe'
    if (-not $wg) { return $false }
    Info ('Thu cai qua winget: ' + $id)
    return (TryExec $wg @('install','--id',$id,'--exact','--silent','--disable-interactivity','--accept-source-agreements','--accept-package-agreements'))
}
function Probe312([string]$file,[string[]]$prefix = @()) {
    if (-not $file -or -not (Test-Path -LiteralPath $file -PathType Leaf)) { return $false }
    # A missing py -3.12 prints to stderr; do NOT let Windows PowerShell turn that into fatal error.
    $p = $null
    try {
        $a = @($prefix) + @('-c','import sys,struct;sys.exit(0 if sys.version_info[:2]==(3,12) and struct.calcsize("P")==8 else 1)')
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $file
        $psi.Arguments = ($a | ForEach-Object { '"' + ($_ -replace '"','\"') + '"' }) -join ' '
        $psi.UseShellExecute=$false; $psi.CreateNoWindow=$true
        $psi.RedirectStandardOutput=$true; $psi.RedirectStandardError=$true
        $p = [Diagnostics.Process]::Start($psi)
        if (-not $p.WaitForExit(15000)) { try { $p.Kill() } catch {}; return $false }
        return $p.ExitCode -eq 0
    } catch { return $false } finally { if ($p) { $p.Dispose() } }
}
function FindPython312 {
    $candidates = @(
      (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
      (Join-Path $env:LOCALAPPDATA 'AI_Dubbing_Studio\Python312\python.exe'),
      (Join-Path $env:ProgramFiles 'Python312\python.exe'),
      'C:\Python312\python.exe'
    )
    $cmd = Locate 'python.exe'; if ($cmd) { $candidates += $cmd }
    foreach ($x in ($candidates | Select-Object -Unique)) { if (Probe312 $x) { return @{Exe=$x; Prefix=@()} } }
    $launcher = Locate 'py.exe' @((Join-Path $env:WINDIR 'py.exe'),(Join-Path $env:LOCALAPPDATA 'Programs\Python\Launcher\py.exe'))
    if ($launcher -and (Probe312 $launcher @('-3.12'))) { return @{Exe=$launcher; Prefix=@('-3.12')} }
    return $null
}
function EnsurePython312 {
    $p = FindPython312
    if ($p) { Info ('Python 3.12 x64 san sang: ' + $p.Exe); return $p }
    Note 'May chua co Python 3.12 x64. Thu cai tu dong...'
    [void](WingetInstall 'Python.Python.3.12')
    PathRefresh
    $p = FindPython312; if ($p) { Info ('Python OK: ' + $p.Exe); return $p }
    # Independent of winget and py launcher: Python.org signed installer per-user.
    $installer = Join-Path $script:Cache 'python-3.12.10-amd64.exe'
    Download 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' $installer
    VerifyPublisher $installer
    $target = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312'
    Info 'Cai Python 3.12.10 cho current user (khong yeu cau Admin)...'
    Exec $installer @('/quiet','InstallAllUsers=0','Include_pip=1','Include_launcher=1','InstallLauncherAllUsers=0','PrependPath=0','Include_test=0',('TargetDir=' + $target))
    PathRefresh
    $p = FindPython312
    if (-not $p) { ErrorStop 'Python 3.12 da chay bo cai nhung khong tim thay. Kiem tra antivirus/quyen ghi va log.' }
    Info ('Python 3.12 x64 OK: ' + $p.Exe)
    return $p
}
function EnsureGit {
    $g = Locate 'git.exe' @((Join-Path $env:ProgramFiles 'Git\cmd\git.exe'),(Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd\git.exe'))
    if ($g) { Info ('Git OK: ' + $g); return $g }
    if (WingetInstall 'Git.Git') { PathRefresh; $g=Locate 'git.exe' @((Join-Path $env:ProgramFiles 'Git\cmd\git.exe')); if ($g) { return $g } }
    # Github release API official Git for Windows installer, only if Git is actually needed.
    try {
        Info 'Khong co winget/Git: dang lay Git for Windows tu GitHub Releases...'
        $release=Invoke-RestMethod -Uri 'https://api.github.com/repos/git-for-windows/git/releases/latest' -Headers @{'User-Agent'='AI-Dubbing-Installer'} -TimeoutSec 30
        $asset=$release.assets | Where-Object { $_.name -match '^Git-[0-9].*-64-bit\.exe$' } | Select-Object -First 1
        if (-not $asset) { throw 'Khong tim thay Git for Windows x64 installer.' }
        $path=Join-Path $script:Cache $asset.name
        Download $asset.browser_download_url $path
        VerifyPublisher $path
        Exec $path @('/VERYSILENT','/NORESTART','/NOCANCEL','/CURRENTUSER')
        PathRefresh
        $g=Locate 'git.exe' @((Join-Path $env:ProgramFiles 'Git\cmd\git.exe'),(Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd\git.exe'))
        if ($g) { return $g }
    } catch { Warning ('Tu cai Git khong thanh cong: ' + $_.Exception.Message) }
    return $null
}
function EnsureProject([string]$git) {
    $candidates = @($script:Root, 'D:\dub\voicedubonmivoice_vip', 'D:\OmniVoice_multi_speaker', (Join-Path $env:USERPROFILE 'OmniVoice_multi_speaker'))
    foreach ($folder in ($candidates | Select-Object -Unique)) {
        if ((Test-Path -LiteralPath (Join-Path $folder 'core.py')) -and
            (Test-Path -LiteralPath (Join-Path $folder 'modern_gui.py')) -and
            (Test-Path -LiteralPath (Join-Path $folder 'requirements.txt'))) {
            Info ('Dung source da co: ' + $folder)
            return [IO.Path]::GetFullPath($folder)
        }
    }
    $dest = if (Test-Path -LiteralPath 'D:\') { 'D:\OmniVoice_multi_speaker' } else { Join-Path $env:USERPROFILE 'OmniVoice_multi_speaker' }
    if (Test-Path -LiteralPath $dest) {
        if (@(Get-ChildItem -LiteralPath $dest -Force).Count -ne 0) {
            ErrorStop ('Thu muc dich da co file nhung thieu source: ' + $dest + '. Khong tu ghi de.')
        }
    }
    if ($git) {
        Info ('Clone ' + $script:Repo + ' -> ' + $dest)
        Exec $git @('clone','--depth','1',$script:Repo,$dest)
    } else {
        Info 'Chua co Git: thu tai ma nguon ZIP qua HTTPS.'
        $z=Join-Path $script:Cache 'repo-main-v6.zip'
        Download 'https://github.com/botrecon99/voicedubonmivoice_vip/archive/refs/heads/main.zip' $z
        $unpack=Join-Path $script:Cache 'unpack_repo_v6'
        if (Test-Path -LiteralPath $unpack) { Remove-Item -LiteralPath $unpack -Recurse -Force }
        Expand-Archive -LiteralPath $z -DestinationPath $unpack
        $first=Get-ChildItem -LiteralPath $unpack -Directory | Select-Object -First 1
        if (-not $first) { ErrorStop 'Giai nen GitHub ZIP loi.' }
        if (-not (Test-Path -LiteralPath $dest)) { New-Item -ItemType Directory -Path $dest -Force | Out-Null }
        Copy-Item -Path (Join-Path $first.FullName '*') -Destination $dest -Recurse -Force
        Warning 'May nay khong co Git; UPDATE.bat se can Git de git pull.'
    }
    foreach ($f in @('core.py','modern_gui.py','requirements.txt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $dest $f))) { ErrorStop ('Source Github thieu ' + $f) }
    }
    return $dest
}
function GetNvidiaDriver {
    $smi=Locate 'nvidia-smi.exe' @((Join-Path $env:ProgramFiles 'NVIDIA Corporation\NVSMI\nvidia-smi.exe'),(Join-Path $env:WINDIR 'System32\nvidia-smi.exe'))
    if (-not $smi) { return $null }
    try {
        $out= & $smi '--query-gpu=driver_version' '--format=csv,noheader' 2>$null
        $first=($out | Select-Object -First 1)
        if ($LASTEXITCODE -ne 0 -or -not $first) { return $null }
        return ([version]($first.ToString().Trim()))
    } catch { return $null }
}
function EnsureVenv([hashtable]$py,[string]$name) {
    $dir=Join-Path $script:App $name
    $exe=Join-Path $dir 'Scripts\python.exe'
    if (Test-Path -LiteralPath $exe) {
        if (-not (Probe312 $exe)) { ErrorStop ('Venv ' + $name + ' khong dung Python 3.12 hoac hong. Khong tu xoa. Hay doi ten ' + $dir + ' roi cai lai.') }
        Info ('Da co venv: ' + $name); return $exe
    }
    Exec $py.Exe ($py.Prefix + @('-m','venv',$dir))
    if (-not (Probe312 $exe)) { ErrorStop ('Khong tao duoc venv ' + $name) }
    return $exe
}
function EnsurePip([string]$p) { Exec $p @('-m','pip','install','--upgrade','pip','setuptools','wheel','--disable-pip-version-check','--retries','5','--timeout','60') }
function EffectiveReq([bool]$cpu) {
    $original=Join-Path $script:App 'requirements.txt'
    if (-not (Test-Path -LiteralPath $original)) { ErrorStop 'Thieu requirements.txt' }
    $raw=[IO.File]::ReadAllLines($original)
    $out=New-Object 'System.Collections.Generic.List[string]'
    foreach ($line in $raw) {
        if ($line -match '^\s*--extra-index-url\s+https://download\.pytorch\.org/whl/') {
            if ($cpu) { $out.Add('--extra-index-url https://download.pytorch.org/whl/cpu') } else { $out.Add($line) }; continue
        }
        if ($cpu -and $line -match '^\s*(torch|torchaudio|torchvision)==([0-9.]+)\+cu[0-9]+\s*$') {
            $out.Add($Matches[1] + '==' + $Matches[2] + '+cpu'); continue
        }
        $out.Add($line)
    }
    $path=Join-Path $script:App '.setup\requirements_effective.txt'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $path) | Out-Null
    [IO.File]::WriteAllLines($path,$out.ToArray(),[Text.UTF8Encoding]::new($false))
    return $path
}
function PipInstallReq([string]$py,[string]$file,[string]$mark) {
    $hash=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
    $marker=Join-Path $script:App ('.setup\' + $mark)
    if ((Test-Path -LiteralPath $marker) -and ([IO.File]::ReadAllText($marker).Trim() -eq $hash)) {
        Info 'Requirements khong doi, bo qua cai lai.'; return
    }
    Exec $py @('-m','pip','install','-r',$file,'--prefer-binary','--disable-pip-version-check','--retries','5','--timeout','60')
    [IO.File]::WriteAllText($marker,$hash)
}
# Windows PowerShell 5.1 may strip double quotes when forwarding a `python -c` expression.
# Execute the exact expression from a UTF-8 .py file instead (also works for paths with spaces).
function CheckImport([string]$py,[string]$expr) {
    $old = $ErrorActionPreference
    $tempDir = Join-Path $script:Cache 'python_checks'
    $file = Join-Path $tempDir 'check_env.py'
    try {
        New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
        [IO.File]::WriteAllText($file,($expr + [Environment]::NewLine),[Text.UTF8Encoding]::new($false))
        $ErrorActionPreference='Continue'
        # Pipe through Out-Host: CheckImport must return only one Boolean.
        & $py $file 2>&1 | Out-Host
        $rc=$LASTEXITCODE
        return ($rc -eq 0)
    } catch {
        Note ('Kiem tra Python loi: ' + $_.Exception.Message)
        return $false
    } finally {
        $ErrorActionPreference=$old
    }
}
function EnsureFFmpeg {
    $ff=Join-Path $script:App 'ffmpeg.exe'; $probe=Join-Path $script:App 'ffprobe.exe'
    if ((Test-Path $ff) -and (Test-Path $probe) -and (CheckExecutable $ff @('-version')) -and (CheckExecutable $probe @('-version'))) {
        Info 'FFmpeg/ffprobe trong thu muc app OK'; return
    }
    $binary=Locate 'ffmpeg.exe'
    if ($binary) {
        $other=Join-Path (Split-Path -Parent $binary) 'ffprobe.exe'
        if (Test-Path -LiteralPath $other) {
            Copy-Item -LiteralPath $binary -Destination $ff -Force
            Copy-Item -LiteralPath $other -Destination $probe -Force
        }
    }
    if ((Test-Path $ff) -and (Test-Path $probe) -and (CheckExecutable $ff @('-version')) -and (CheckExecutable $probe @('-version'))) { return }
    try {
        Info 'Tai FFmpeg/ffprobe package da duoc dong goi...'
        $archive=Join-Path $script:Cache 'ffmpeg-release-essentials.zip'
        Download 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' $archive 1000000
        $temp=Join-Path $script:Cache 'ffmpeg_extract'
        if (Test-Path $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
        Expand-Archive -LiteralPath $archive -DestinationPath $temp -Force
        $c=Get-ChildItem -LiteralPath $temp -Filter ffmpeg.exe -File -Recurse | Select-Object -First 1
        if (-not $c) { throw 'Khong thay ffmpeg.exe trong ZIP' }
        $p=Join-Path $c.DirectoryName 'ffprobe.exe'
        if (-not (Test-Path $p)) { throw 'ZIP thieu ffprobe.exe' }
        Copy-Item -LiteralPath $c.FullName -Destination $ff -Force
        Copy-Item -LiteralPath $p -Destination $probe -Force
    } catch {
        Warning ('FFmpeg truc tiep that bai: ' + $_.Exception.Message + '. Thu winget...')
        [void](WingetInstall 'Gyan.FFmpeg')
        PathRefresh
        $binary=Locate 'ffmpeg.exe'
        if ($binary) {
            $other=Join-Path (Split-Path -Parent $binary) 'ffprobe.exe'
            if (Test-Path -LiteralPath $other) {
                Copy-Item -LiteralPath $binary -Destination $ff -Force
                Copy-Item -LiteralPath $other -Destination $probe -Force
            }
        }
    }
    if (-not (CheckExecutable $ff @('-version')) -or -not (CheckExecutable $probe @('-version'))) { ErrorStop 'FFmpeg / ffprobe chua cai duoc.' }
    Info 'FFmpeg/ffprobe OK'
}
function CheckExecutable([string]$f,[string[]]$arglist) {
    if (-not (Test-Path -LiteralPath $f)) { return $false }
    try {
        $o=& $f @arglist 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}
function EnsureYtdlp {
    $exe=Join-Path $script:App 'yt-dlp.exe'
    if (CheckExecutable $exe @('--version')) { Info 'yt-dlp.exe OK'; return }
    # Standalone official EXE: no reliance on launcher from different machine/venv.
    $archive=Join-Path $script:Cache 'yt-dlp.exe'
    Download 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe' $archive
    # Validate against official release checksums when available.
    $sums=Join-Path $script:Cache 'yt-dlp.sha256sums'
    try {
        Download 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS' $sums 256
        $found=Get-Content -LiteralPath $sums | Where-Object { $_ -match '\s\*?yt-dlp\.exe\s*$' } | Select-Object -First 1
        if ($found) {
            $expected=($found -split '\s+')[0].ToLowerInvariant()
            $actual=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($expected -ne $actual) { ErrorStop 'SHA256 yt-dlp.exe KHONG KHOP' }
        } else { Warning 'Khong tim thay checksum yt-dlp.exe, dung TLS HTTPS va test chay.' }
    } catch {
        if ($_.Exception.Message -match 'SHA256 yt-dlp.exe KHONG KHOP') { throw }
        Warning ('Khong tai duoc file checksum yt-dlp: ' + $_.Exception.Message)
    }
    Copy-Item -LiteralPath $archive -Destination $exe -Force
    if (-not (CheckExecutable $exe @('--version'))) { ErrorStop 'yt-dlp.exe khong chay duoc.' }
    Info 'yt-dlp.exe OK'
}
function EnsureNode {
    $node=Locate 'node.exe' @((Join-Path $env:ProgramFiles 'nodejs\node.exe'),(Join-Path $script:App '.tools\node\node.exe'))
    if ($node -and (CheckExecutable $node @('--version'))) { Info ('Node OK: ' + $node); return }
    # A portable node.exe avoids slow/hanging winget installers on 10+ PCs.
    $nodeDir=Join-Path $script:App '.tools\node'
    $dest=Join-Path $nodeDir 'node.exe'
    New-Item -ItemType Directory -Force -Path $nodeDir | Out-Null
    try {
        Download 'https://nodejs.org/download/release/latest-v24.x/win-x64/node.exe' $dest 1000000
        if (-not (CheckExecutable $dest @('--version'))) { throw 'Node portable khong chay duoc.' }
    } catch {
        Warning ('Khong lay duoc Node portable: ' + $_.Exception.Message + '. Thu cai winget...')
        [void](WingetInstall 'OpenJS.NodeJS.LTS')
        PathRefresh
        $dest=Locate 'node.exe' @((Join-Path $env:ProgramFiles 'nodejs\node.exe'))
        if (-not $dest -or -not (CheckExecutable $dest @('--version'))) { ErrorStop 'Node.js chua cai duoc (ca portable va winget deu that bai).' }
    }
    $env:PATH = (Split-Path -Parent $dest) + ';' + $env:PATH
    if ($dest -like ($nodeDir + '*')) {
        $userPath=[string][Environment]::GetEnvironmentVariable('Path','User')
        if (([string]$userPath -split ';') -notcontains $nodeDir) {
            [Environment]::SetEnvironmentVariable('Path',(($userPath.TrimEnd(';') + ';' + $nodeDir).TrimStart(';')),'User')
        }
    }
    Info ('Node OK: ' + $dest)
}
function EnsureChrome {
    $paths=@((Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),(Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),(Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe'))
    foreach ($x in $paths) { if (Test-Path -LiteralPath $x) { Info 'Chrome OK'; return } }
    [void](WingetInstall 'Google.Chrome')
    foreach ($x in $paths) { if (Test-Path -LiteralPath $x) { return } }
    try {
        $installer=Join-Path $script:Cache 'ChromeSetup.exe'
        Download 'https://dl.google.com/chrome/install/latest/chrome_installer.exe' $installer
        VerifyPublisher $installer
        Exec $installer @('/silent','/install')
        foreach ($x in $paths) { if (Test-Path -LiteralPath $x) { return } }
    } catch { Warning ('Khong the tu cai Chrome: ' + $_.Exception.Message) }
    Warning 'Chrome chua co: Selenium co the khong tai video dang nhap duoc. Can cai Chrome neu dung tinh nang nay.'
}
function EnsureVCRuntime {
    # PyTorch, torchaudio and several ONNX libraries need Microsoft VC++ DLLs.
    $registry=@('HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
                'HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64')
    foreach ($key in $registry) {
        if (Test-Path $key) {
            try { $v=Get-ItemProperty -Path $key; if ($v.Installed -eq 1) { Info 'Microsoft VC++ x64 runtime OK'; return } } catch {}
        }
    }
    Warning 'Chua thay Microsoft VC++ Redistributable x64. Thu cai tu Microsoft (co the hoi UAC).'
    try {
        $exe=Join-Path $script:Cache 'vc_redist.x64.exe'
        Download 'https://aka.ms/vc14/vc_redist.x64.exe' $exe
        VerifyPublisher $exe
        # Installer can request elevation via UAC; exit 3010 means reboot recommended.
        $p=Start-Process -FilePath $exe -ArgumentList @('/install','/passive','/norestart') -PassThru -Wait
        if ($p.ExitCode -notin @(0,1638,3010)) { Warning ('VC++ runtime exit=' + $p.ExitCode + '. Neu PyTorch bao DLL, cai bang quyen Admin.') }
        if ($p.ExitCode -eq 3010) { Warning 'VC++ runtime yeu cau restart Windows sau khi cai.' }
    } catch { Warning ('Khong cai duoc VC++ runtime: ' + $_.Exception.Message) }
}
# Pin both PyTorch wheels while resolving pyannote dependencies. A plain pip install of
# pyannote.audio can upgrade the previously installed CUDA torch to a newer CPU build.
function RoleCheck([string]$bin,[string]$mode) {
    $code = @'
import torch,torchaudio,pyannote.audio
v=torch.__version__
a=torchaudio.__version__
print('ROLES:',v,'TORCHAUDIO:',a,'CUDA_AVAILABLE:',torch.cuda.is_available())
assert v.startswith('2.11.0+MODE'), 'Torch was changed by pip'
assert a.startswith('2.11.0+MODE'), 'Torchaudio must match torch'
if 'MODE' != 'cpu':
    assert torch.cuda.is_available(), 'GPU is not usable by PyTorch'
    torch.ones(1,device='cuda')
'@
    $code=$code.Replace('MODE',$mode)
    return (CheckImport $bin $code)
}
function InstallRolesWithPinnedTorch([string]$bin,[string]$mode) {
    $index = 'https://download.pytorch.org/whl/' + $mode
    $constraintDir = Join-Path $script:App '.setup'
    New-Item -ItemType Directory -Force -Path $constraintDir | Out-Null
    $constraints = Join-Path $constraintDir ('roles_torch_' + $mode + '.txt')
    # Both wheels MUST have this exact local build tag (+cu126 or +cpu).
    [IO.File]::WriteAllLines($constraints, [string[]]@(
        ('torch==2.11.0+' + $mode),
        ('torchaudio==2.11.0+' + $mode)
    ), [Text.UTF8Encoding]::new($false))
    Info ('Cai PyTorch 2.11 + ' + $mode + ' cho Pyannote, KHONG sua venv chinh.')
    Exec $bin @('-m','pip','install','torch==2.11.0','torchaudio==2.11.0',
                '--index-url',$index,'--retries','5','--timeout','60')
    # Make the resolver keep the existing torch and torchaudio CUDA/CPU variants.
    Info 'Cai pyannote.audio voi constraints (khong duoc thay torch/torchaudio).'
    Exec $bin @('-m','pip','install','pyannote.audio==4.0.7','transformers>=4.45,<5','numpy<3',
                '--constraint',$constraints,'--extra-index-url',$index,
                '--prefer-binary','--retries','5','--timeout','60')
    # Validate actual installed binaries, never trust pip success alone.
    if (-not (RoleCheck $bin $mode)) {
        Warning 'Pip da thay hoac CUDA chua dung duoc. Khoi phuc dung torch/torchaudio tu index chuan.'
        Exec $bin @('-m','pip','install','--force-reinstall','--no-deps',
                    'torch==2.11.0','torchaudio==2.11.0','--index-url',$index,
                    '--retries','5','--timeout','60')
    }
    if (-not (RoleCheck $bin $mode)) { ErrorStop ('Pyannote hoac torch ' + $mode + ' import/kiem tra that bai.') }
}
function EnsureRoles([hashtable]$p,[version]$driver) {
    $bin=EnsureVenv $p '.venv_roles'
    $ready=Join-Path $script:App '.setup\roles-v6.txt'
    $wantCuda=($null -ne $driver -and $driver -ge [version]'560.35')
    $wanted=if ($wantCuda) { 'cu126' } else { 'cpu' }
    $mode=$wanted
    $tag=('v6-2.11.0-' + $wanted)
    $already=(Test-Path -LiteralPath $ready) -and ([IO.File]::ReadAllText($ready).Trim() -eq $tag)
    if ($already -and (RoleCheck $bin $wanted)) {
        Info ('Pyannote ' + $wanted + ' da duoc kiem tra, bo qua cai lai.')
        $script:RolesReady=$true
        return
    }
    EnsurePip $bin
    try {
        InstallRolesWithPinnedTorch $bin $wanted
    } catch {
        if (-not $wantCuda) { throw }
        Warning ('Khong cai/chay duoc GPU roles: ' + $_.Exception.Message)
        Warning 'Tu dong chuyen Pyannote sang CPU (khong xoa venv, khong can clone lai).'
        $mode='cpu'
        InstallRolesWithPinnedTorch $bin 'cpu'
    }
    # Installer marker is written ONLY after complete validation succeeds.
    [IO.File]::WriteAllText($ready,('v6-2.11.0-' + $mode))
    $script:RolesReady=$true
    Info ('Pyannote ROLES READY: ' + $mode)
}

try {
    if (-not [Environment]::Is64BitOperatingSystem -or [Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { ErrorStop 'Bo cai ho tro Windows 10/11 x64 (khong ho tro 32-bit/ARM).' }
    New-Item -ItemType Directory -Force -Path $script:State,$script:Cache | Out-Null
    Start-Transcript -LiteralPath $script:Log -ErrorAction Stop | Out-Null
    $script:TranscriptOn=$true
    Write-Host ''; Write-Host 'ONE FILE INSTALLER V6 - WINDOWS 10/11 x64' -ForegroundColor Green
    Info ('LOG: ' + $script:Log)
    Info ('File bat dang o: ' + $script:Root)
    $rootDrive = [IO.Path]::GetPathRoot($script:Root)
    $free = (New-Object System.IO.DriveInfo -ArgumentList $rootDrive).AvailableFreeSpace
    if ($free -lt 12000000000) { Warning 'O dia con duoi 12GB trong: thu vien AI co the khong du cho cai dat.' }
    Step 1 'KIEM TRA PROJECT / GIT'
    $git=EnsureGit
    $script:App=EnsureProject $git
    $needed=@('modern_gui.py','core.py','requirements.txt','license_client.py','license_ui.py','speaker_ai.py')
    foreach ($f in $needed) { if (-not (Test-Path -LiteralPath (Join-Path $script:App $f))) { ErrorStop ('Repo thieu ' + $f) } }
    Step 2 'PYTHON 3.12 x64 (TU DONG CAI)'
    $py=EnsurePython312
    Step 3 'FFMPEG + FFPROBE + YT-DLP + NODE.JS'
    EnsureFFmpeg; EnsureYtdlp; EnsureNode
    Step 4 'GOOGLE CHROME / SELENIUM'
    EnsureChrome
    Step 5 'MOI TRUONG CHINH (venv)'
    EnsureVCRuntime
    $venv=EnsureVenv $py 'venv'
    EnsurePip $venv
    $driver=GetNvidiaDriver
    $script:CUDA=($null -ne $driver -and $driver -ge [version]'551.78')
    if ($script:CUDA) { Info ('NVIDIA driver ' + $driver + ': su dung CUDA cu124 cho main') }
    else { Warning 'May khong co NVIDIA CUDA 12.4 driver ho tro: dung PyTorch CPU cho main.' }
    $req=EffectiveReq (-not $script:CUDA)
    PipInstallReq $venv $req 'requirements-v4.sha256'
    Exec $venv @('-m','pip','install','selenium>=4.15,<5','--prefer-binary','--retries','5','--timeout','60')
    if (-not (CheckImport $venv 'import torch,torchaudio,customtkinter,whisper,selenium,moviepy.editor,omnivoice;print("MAIN:",torch.__version__,"CUDA:",torch.cuda.is_available())')) {
        if ($script:CUDA) {
            Warning 'MAIN CUDA import that bai, thu tu chuyen CPU (khong xoa venv).'
            $script:CUDA=$false
            $req=EffectiveReq $true
            PipInstallReq $venv $req 'requirements-v4.sha256'
        }
        if (-not (CheckImport $venv 'import torch,torchaudio,customtkinter,whisper,selenium,moviepy.editor,omnivoice')) {
            ErrorStop 'Main env chua import du thu vien. Xem log phia tren, khong bao CAI DAT THANH CONG.'
        }
    }
    $script:MainReady=$true
    Step 6 'PYANNOTE MULTI-SPEAKER RIENG'
    EnsureRoles $py $driver
    Step 7 'KIEM TRA FILE VA LICENSE'
    $cfg=Join-Path $script:App 'license_config.json'
    if (-not (Test-Path -LiteralPath $cfg)) {
        $v=@{api_url=$script:LicenseApi} | ConvertTo-Json
        [IO.File]::WriteAllText($cfg,$v,[Text.UTF8Encoding]::new($false))
        Info 'Da tao license_config.json: URL server license cua ban (khong luu key).'
    } else { Info 'Giữ nguyen license_config.json hien tai' }
    $folder=Join-Path $script:App 'voices'; if (-not (Test-Path $folder)) { New-Item -ItemType Directory $folder | Out-Null }
    $folder=Join-Path $script:App 'downloaded_data'; if (-not (Test-Path $folder)) { New-Item -ItemType Directory $folder | Out-Null }
    Step 8 'KIEM TRA CUOI CUNG'
    foreach ($x in @('ffmpeg.exe','ffprobe.exe','yt-dlp.exe','venv\Scripts\python.exe','.venv_roles\Scripts\python.exe','license_config.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $script:App $x))) { ErrorStop ('Kiem tra thieu: ' + $x) }
    }
    if (-not (CheckExecutable (Join-Path $script:App 'ffmpeg.exe') @('-version'))) { ErrorStop 'Test ffmpeg FAIL' }
    if (-not (CheckExecutable (Join-Path $script:App 'yt-dlp.exe') @('--version'))) { ErrorStop 'Test yt-dlp FAIL' }
    if (-not (Locate 'node.exe' @((Join-Path $script:App '.tools\node\node.exe'),(Join-Path $env:ProgramFiles 'nodejs\node.exe')))) { ErrorStop 'Test node FAIL' }
    if (-not (CheckImport $venv 'import torch,customtkinter,whisper,omnivoice;print("GPU main:",torch.cuda.is_available())')) { ErrorStop 'Final test main FAIL' }
    [IO.File]::WriteAllText((Join-Path $script:State 'installation_path.txt'),$script:App)
    Step 9 'XONG'
    Info 'MAIN + ROLES + FFMPEG + YTDLP + NODE: DA KIEM TRA THANH CONG'
    Info ('App: ' + $script:App)
    Info 'Mo START_APP.bat trong thu muc app. Nhap LICENSE KEY do Admin cap.'
    Info 'Lan sau chi can UPDATE.bat (neu repo co Git).'
    Warning 'Pyannote lan dau: can HF_TOKEN va quyen truy cap model tren Hugging Face. Token khong nam trong bo cai.'
    if ($script:Warns.Count -gt 0) { Info ('So luu y: ' + $script:Warns.Count) }
    Stop-Transcript | Out-Null
    exit 0
} catch {
    Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host ('[ERROR] Tai buoc cai dat. MAIN_READY=' + $script:MainReady + ' ROLES_READY=' + $script:RolesReady) -ForegroundColor Yellow
    Write-Host ('[ERROR] Log: ' + $script:Log) -ForegroundColor Yellow
    if ($script:TranscriptOn) { try { Stop-Transcript | Out-Null } catch {} }
    exit 1
}

