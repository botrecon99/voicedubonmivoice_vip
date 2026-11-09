#requires -version 5.1
param([string]$AppDir = '')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
function Say([string]$m) { Write-Host ('[TOOLS] ' + $m) -ForegroundColor Cyan }
function Fail([string]$m) { throw $m }
function Refresh-Path {
    $env:PATH = [Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('PATH', 'User') + ';' + $env:PATH
}
function Program([string]$name) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source)) { return $cmd.Source }
    return $null
}
function Install-Winget([string]$packageId) {
    $wg = Program 'winget.exe'
    if (-not $wg) { Fail "Khong tim thay winget. Cai App Installer tu Microsoft Store, roi chay lai. Can: $packageId" }
    Say "Dang cai $packageId qua winget..."
    & $wg install --id $packageId -e --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { Fail "Winget cai $packageId that bai (exit $LASTEXITCODE)." }
    Refresh-Path
}
function Find-FFmpeg([string]$name, [string]$base) {
    $localFile = Join-Path $base $name
    if (Test-Path -LiteralPath $localFile) { return $localFile }
    $found = Program $name
    if ($found) { return $found }
    $links = Join-Path $env:LOCALAPPDATA ('Microsoft\WinGet\Links\' + $name)
    if (Test-Path -LiteralPath $links) { return $links }
    foreach ($folder in @((Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'), (Join-Path $env:ProgramFiles 'WinGet\Packages'))) {
        if (-not (Test-Path -LiteralPath $folder)) { continue }
        $match = Get-ChildItem -Path $folder -Filter $name -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.FullName -match 'Gyan\.FFmpeg' } | Select-Object -First 1
        if ($match) { return $match.FullName }
    }
    return $null
}
function Ensure-LocalExe([string]$name, [string]$source, [string]$base) {
    if (-not $source -or -not (Test-Path -LiteralPath $source)) { Fail "Khong tim thay $name" }
    $dest = Join-Path $base $name
    if (-not (Test-Path -LiteralPath $dest)) {
        Say ("Copy " + $name + " vao thu muc project (file EXE nay KHONG duoc push GitHub)...")
        Copy-Item -LiteralPath $source -Destination $dest -Force -ErrorAction Stop
    } else { Say ($name + ' da co trong thu muc project.') }
    if (-not (Test-Path -LiteralPath $dest)) { Fail "Copy $name khong thanh cong." }
    return $dest
}
function Ensure-Node {
    $node = Program 'node.exe'
    if (-not $node) {
        foreach ($p in @((Join-Path $env:ProgramFiles 'nodejs\node.exe'), (Join-Path $env:LOCALAPPDATA 'Programs\nodejs\node.exe'))) {
            if (Test-Path -LiteralPath $p) { $node = $p; break }
        }
    }
    if (-not $node) {
        Say 'taiok.bat co --js-runtimes node, can cai Node.js LTS.'
        Install-Winget 'OpenJS.NodeJS.LTS'
        $node = Program 'node.exe'
        if (-not $node) {
            $p = Join-Path $env:ProgramFiles 'nodejs\node.exe'
            if (Test-Path -LiteralPath $p) { $node = $p }
        }
    }
    if (-not $node) { Fail 'Da cai Node.js nhung khong tim thay node.exe. Mo CMD moi va chay lai.' }
    $out = & $node --version
    if ($LASTEXITCODE -ne 0) { Fail 'node.exe khong chay duoc.' }
    Say ('Node.js OK: ' + $out)
}
try {
    if (-not $AppDir) { $AppDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path }
    $AppDir = (Resolve-Path -LiteralPath $AppDir -ErrorAction Stop).Path
    Say ('Thu muc Studio: ' + $AppDir)
    $py = Join-Path $AppDir 'venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $py)) { Fail 'Chua co venv\Scripts\python.exe. Hay chay INSTALL_NEW_PC.bat truoc.' }
    Refresh-Path
    $ff = Find-FFmpeg 'ffmpeg.exe' $AppDir
    if (-not $ff) {
        Install-Winget 'Gyan.FFmpeg'
        $ff = Find-FFmpeg 'ffmpeg.exe' $AppDir
    }
    if (-not $ff) { Fail 'FFmpeg chua co trong PATH sau cai winget. Mo CMD moi va chay lai.' }
    $ffLocal = Ensure-LocalExe 'ffmpeg.exe' $ff $AppDir
    $fp = Find-FFmpeg 'ffprobe.exe' $AppDir
    if (-not $fp) {
        $sibling = Join-Path (Split-Path -Parent $ff) 'ffprobe.exe'
        if (Test-Path -LiteralPath $sibling) { $fp = $sibling }
    }
    if (-not $fp) { Fail 'Khong tim thay ffprobe.exe trong bo FFmpeg; kiem tra cai dat Gyan.FFmpeg.' }
    $fpLocal = Ensure-LocalExe 'ffprobe.exe' $fp $AppDir
    # yt-dlp pip console launcher is generated inside venv\Scripts.
    $ydl = Join-Path $AppDir 'venv\Scripts\yt-dlp.exe'
    if (-not (Test-Path -LiteralPath $ydl)) {
        Say 'Thieu yt-dlp.exe trong venv: cai lai goi yt-dlp...'
        & $py -m pip install --force-reinstall yt-dlp
        if ($LASTEXITCODE -ne 0) { Fail 'pip install yt-dlp that bai.' }
    }
    if (-not (Test-Path -LiteralPath $ydl)) { Fail 'Khong tim thay venv\Scripts\yt-dlp.exe sau khi cai.' }
    $ydlLocal = Join-Path $AppDir 'yt-dlp.exe'
    if (-not (Test-Path -LiteralPath $ydlLocal)) {
        Copy-Item -LiteralPath $ydl -Destination $ydlLocal -Force -ErrorAction Stop
        Say 'Da tao yt-dlp.exe tai thu muc project.'
    } else { Say 'yt-dlp.exe da co tai thu muc project.' }
    Ensure-Node
    # Test executables in their actual location without changing source or data.
    & $ffLocal -version *> $null
    if ($LASTEXITCODE -ne 0) { Fail 'ffmpeg.exe tai thu muc project khong chay duoc.' }
    & $fpLocal -version *> $null
    if ($LASTEXITCODE -ne 0) { Fail 'ffprobe.exe tai thu muc project khong chay duoc.' }
    $ytVersion = & $ydlLocal --version
    if ($LASTEXITCODE -ne 0) { Fail 'yt-dlp.exe tai thu muc project khong chay duoc.' }
    Say ('yt-dlp OK: ' + $ytVersion)
    Say 'OK: ffmpeg.exe, ffprobe.exe, yt-dlp.exe, Node.js (local + test).'
    exit 0
} catch {
    Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
