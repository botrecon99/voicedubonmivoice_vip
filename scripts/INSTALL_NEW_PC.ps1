#requires -Version 5.1
# ONE-CLICK INSTALL V4 - Windows 10/11 x64, PowerShell 5.1+
# User files and secrets are never deleted. Rerun to resume after network failures.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$script:Repo = 'https://github.com/botrecon99/voicedubonmivoice_vip.git'
$script:LicenseApi = 'https://ai-dubbing-license.laughlicense-pnmedia2026.workers.dev'
$script:State = Join-Path $env:LOCALAPPDATA 'AI_Dubbing_Studio'
$script:Cache = Join-Path $script:State 'installer_cache'
$script:Log = Join-Path $script:State ('install_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.log')
$script:Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
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
        & $file @arglist
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
    if ((Test-Path -LiteralPath (Join-Path $script:Root 'core.py')) -and (Test-Path -LiteralPath (Join-Path $script:Root 'modern_gui.py'))) {
        Info ('Su dung project hien tai: ' + $script:Root); return $script:Root
    }
    $dest = if (Test-Path -LiteralPath 'D:\') { 'D:\OmniVoice_multi_speaker' } else { Join-Path $env:USERPROFILE 'OmniVoice_multi_speaker' }
    if (Test-Path -LiteralPath $dest) {
        if (@(Get-ChildItem -LiteralPath $dest -Force).Count -ne 0) { ErrorStop ('Thu muc da co file, khong de: ' + $dest) }
    }
    if ($git) {
        Exec $git @('clone',$script:Repo,$dest)
    } else {
        # No Git/winget: fall back to GitHub archive, can install but updates need Git later.
        $z=Join-Path $script:Cache 'repo-main.zip'
        Download 'https://github.com/botrecon99/voicedubonmivoice_vip/archive/refs/heads/main.zip' $z
        $unpack=Join-Path $script:Cache 'unpack_repo'
        if (Test-Path -LiteralPath $unpack) { Remove-Item -LiteralPath $unpack -Recurse -Force }
        Expand-Archive -LiteralPath $z -DestinationPath $unpack
        $first=Get-ChildItem -LiteralPath $unpack -Directory | Select-Object -First 1
        if (-not $first) { ErrorStop 'Giai nen GitHub zip loi' }
        if (-not (Test-Path -LiteralPath $dest)) { New-Item -ItemType Directory -Path $dest -Force | Out-Null }
        Copy-Item -Path (Join-Path $first.FullName '*') -Destination $dest -Recurse -Force
        Warning 'Khong co git: da tai ZIP source, UPDATE.bat se can Git sau nay.'
    }
    foreach ($f in @('core.py','modern_gui.py','requirements.txt')) { if (-not (Test-Path -LiteralPath (Join-Path $dest $f))) { ErrorStop ('Source GitHub thieu ' + $f) } }
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
function CheckImport([string]$py,[string]$expr) {
    try {
        $old=$ErrorActionPreference; $ErrorActionPreference='Continue'
        & $py -c $expr
        $rc=$LASTEXITCODE
        $ErrorActionPreference=$old
        return ($rc -eq 0)
    } catch { $ErrorActionPreference=$old; return $false }
}
function EnsureFFmpeg {
    $ff=Join-Path $script:App 'ffmpeg.exe'; $probe=Join-Path $script:App 'ffprobe.exe'
    if ((Test-Path $ff) -and (Test-Path $probe) -and (CheckExecutable $ff @('-version')) -and (CheckExecutable $probe @('-version'))) { Info 'FFmpeg + ffprobe local OK'; return }
    $binary=Locate 'ffmpeg.exe'
    if (-not $binary) { [void](WingetInstall 'Gyan.FFmpeg'); PathRefresh; $binary=Locate 'ffmpeg.exe' }
    if ($binary) {
        $other=Join-Path (Split-Path -Parent $binary) 'ffprobe.exe'
        if (Test-Path $other) {
            Copy-Item -LiteralPath $binary -Destination $ff -Force
            Copy-Item -LiteralPath $other -Destination $probe -Force
        }
    }
    if ((Test-Path $ff) -and (Test-Path $probe) -and (CheckExecutable $ff @('-version')) -and (CheckExecutable $probe @('-version'))) { return }
    Info 'Tu tai bo FFmpeg essentials ZIP chua ffprobe (khong can winget)...'
    $archive=Join-Path $script:Cache 'ffmpeg-release-essentials.zip'
    Download 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' $archive
    $temp=Join-Path $script:Cache 'ffmpeg_extract'
    if (Test-Path $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
    Expand-Archive -LiteralPath $archive -DestinationPath $temp -Force
    $c=Get-ChildItem -LiteralPath $temp -Filter ffmpeg.exe -File -Recurse | Select-Object -First 1
    if (-not $c) { ErrorStop 'Khong thay ffmpeg.exe trong archive' }
    $p=Join-Path $c.DirectoryName 'ffprobe.exe'
    if (-not (Test-Path $p)) { ErrorStop 'FFmpeg archive thieu ffprobe.exe' }
    Copy-Item -LiteralPath $c.FullName -Destination $ff -Force
    Copy-Item -LiteralPath $p -Destination $probe -Force
    if (-not (CheckExecutable $ff @('-version')) -or -not (CheckExecutable $probe @('-version'))) { ErrorStop 'FFmpeg/ffprobe da tai nhung khong chay duoc' }
    Info 'FFmpeg & ffprobe OK tai thu muc app.'
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
    [void](WingetInstall 'OpenJS.NodeJS.LTS')
    PathRefresh
    $node=Locate 'node.exe' @((Join-Path $env:ProgramFiles 'nodejs\node.exe'))
    if ($node -and (CheckExecutable $node @('--version'))) { return }
    $dest=Join-Path $script:App '.tools\node\node.exe'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
    Download 'https://nodejs.org/download/release/latest-v24.x/win-x64/node.exe' $dest
    if (-not (CheckExecutable $dest @('--version'))) { ErrorStop 'Node portable khong chay duoc' }
    # Only add portable runtime to per-user PATH when missing, for taiok.bat launched from Python GUI.
    $userPath=[string][Environment]::GetEnvironmentVariable('Path','User')
    $nodeDir=Split-Path -Parent $dest
    if (([string]$userPath -split ';') -notcontains $nodeDir) {
        [Environment]::SetEnvironmentVariable('Path',($userPath.TrimEnd(';') + ';' + $nodeDir),'User')
    }
    $env:PATH=$nodeDir + ';' + $env:PATH
    Info 'Node portable OK, them vao PATH user.'
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
function EnsureRoles([hashtable]$p,[version]$driver) {
    $bin=EnsureVenv $p '.venv_roles'
    $ready=Join-Path $script:App '.setup\roles-v4.txt'
    $cuda=($null -ne $driver -and $driver -ge [version]'560.35')
    $mode=if ($cuda) { 'cu126' } else { 'cpu' }
    if (-not (Test-Path $ready) -or ([IO.File]::ReadAllText($ready).Trim() -ne $mode)) {
        EnsurePip $bin
        $index='https://download.pytorch.org/whl/' + $mode
        Exec $bin @('-m','pip','install','torch==2.11.0','torchaudio==2.11.0','--index-url',$index,'--retries','5','--timeout','60')
        Exec $bin @('-m','pip','install','pyannote.audio==4.0.7','transformers>=4.45,<5','numpy<3','--prefer-binary','--retries','5','--timeout','60')
    }
    if (-not (CheckImport $bin 'import torch,pyannote.audio;print("ROLES:",torch.__version__,"CUDA:",torch.cuda.is_available())')) {
        ErrorStop 'Pyannote environment import fail. Xem log.'
    }
    if ($cuda) {
        if (-not (CheckImport $bin 'import torch;assert torch.cuda.is_available();print(torch.cuda.get_device_name(0))')) {
            Warning 'NVIDIA driver co nhung CUDA roles khong hoat dong, tu chuyen CPU.'
            $mode='cpu'
            Exec $bin @('-m','pip','install','--force-reinstall','torch==2.11.0','torchaudio==2.11.0','--index-url','https://download.pytorch.org/whl/cpu')
            if (-not (CheckImport $bin 'import torch,pyannote.audio;assert not torch.cuda.is_available()')) { ErrorStop 'CPU roles fallback that bai' }
        }
    }
    [IO.File]::WriteAllText($ready,$mode)
    $script:RolesReady=$true
}
try {
    if (-not [Environment]::Is64BitOperatingSystem -or [Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { ErrorStop 'Bo cai ho tro Windows 10/11 x64 (khong ho tro 32-bit/ARM).' }
    New-Item -ItemType Directory -Force -Path $script:State,$script:Cache | Out-Null
    Start-Transcript -LiteralPath $script:Log -ErrorAction Stop | Out-Null
    $script:TranscriptOn=$true
    Write-Host ''; Write-Host 'ONE-CLICK INSTALLER V4 - WINDOWS 10/11 x64' -ForegroundColor Green
    Info ('LOG: ' + $script:Log)
    Info ('Root: ' + $script:Root)
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
    if (-not (CheckImport $venv 'import torch,customtkinter,whisper,omnivoice;print("GPU main:",torch.cuda.is_available())')) { ErrorStop 'Final test main FAIL' }
    [IO.File]::WriteAllText((Join-Path $script:State 'installation_path.txt'),$script:App)
    Step 9 'XONG'
    Info 'MAIN + ROLES + FFMPEG + YTDLP + NODE: DA KIEM TRA THANH CONG'
    Info ('App: ' + $script:App)
    Info 'Mo START_APP.bat trong thu muc app. Nhap LICENSE KEY do Admin cap.'
    Info 'Lan sau chi can UPDATE.bat (neu repo co Git).'
    Warning 'Pyannote lan dau: can HF_TOKEN va quyen truy cap model tren Hugging Face.'
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
