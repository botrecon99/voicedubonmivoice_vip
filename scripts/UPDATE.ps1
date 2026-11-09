#requires -version 5.1
param([string]$SourceDir = '')
$ErrorActionPreference = 'Stop'
$StateDir = Join-Path $env:LOCALAPPDATA 'AI_Dubbing_Studio'
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$Log = Join-Path $StateDir ('update_' + $Stamp + '.log')
$script:TranscriptStarted = $false
function Say([string]$s) { Write-Host ('[UPDATE] ' + $s) -ForegroundColor Cyan }
function Warn([string]$s) { Write-Host ('[WARN] ' + $s) -ForegroundColor Yellow }
function Fail([string]$s) { throw $s }
function Git([string[]]$argsList) {
    & $script:GitExe -C $script:AppDir @argsList
    if ($LASTEXITCODE -ne 0) { Fail ("Git failed: git " + ($argsList -join ' ')) }
}
function Git-Text([string[]]$argsList) {
    $text = & $script:GitExe -C $script:AppDir @argsList
    if ($LASTEXITCODE -ne 0) { Fail ('Git failed: ' + ($argsList -join ' ')) }
    return (($text -join "`n").Trim())
}
function Run([string]$exe,[string[]]$argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { Fail ("Command failed: $exe $($argv -join ' ')") }
}
try {
    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
    Start-Transcript -LiteralPath $Log | Out-Null; $script:TranscriptStarted=$true
    Say ('Log: ' + $Log)
    $script:AppDir = ''
    if ($SourceDir -and (Test-Path -LiteralPath (Join-Path $SourceDir '.git'))) {
        $script:AppDir = (Resolve-Path -LiteralPath $SourceDir).Path
    } else {
        $record = Join-Path $StateDir 'installation_path.txt'
        if (Test-Path -LiteralPath $record) { $script:AppDir = [IO.File]::ReadAllText($record).Trim() }
    }
    if (-not $script:AppDir -or -not (Test-Path -LiteralPath (Join-Path $script:AppDir '.git'))) {
        Fail 'Khong tim thay Git clone. Hay chay INSTALL_NEW_PC.bat sau khi push FULL SOURCE len GitHub; UPDATE.bat khong the git pull tu folder ZIP.'
    }
    $script:GitExe = (Get-Command git.exe -ErrorAction SilentlyContinue).Source
    if (-not $script:GitExe) {
        foreach ($x in @("$env:ProgramFiles\Git\cmd\git.exe", "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe")) { if (Test-Path -LiteralPath $x) { $script:GitExe=$x; break } }
    }
    if (-not $script:GitExe) { Fail 'Khong tim thay git.exe. Hay cai Git for Windows.' }
    Say ('Repo: ' + $script:AppDir)
    $remote = Git-Text @('remote','get-url','origin')
    if ($remote -notmatch 'github\.com[:/]botrecon99/voicedubonmivoice_vip(?:\.git)?$') { Fail ('origin khong trung repo du kien: ' + $remote) }
    $dirty = Git-Text @('status','--porcelain','--untracked-files=no')
    if ($dirty) {
        Write-Host $dirty
        Fail 'Co file TRACKED dang sua local. De an toan, UPDATE khong ghi de. Hay commit/stash/sao luu thay doi truoc.'
    }
    $branch = Git-Text @('symbolic-ref','--quiet','--short','HEAD')
    if (-not $branch) { Fail 'Dang o detached HEAD: chuyen ve nhanh main/master truoc khi UPDATE.' }
    $old = Git-Text @('rev-parse','HEAD')
    $backup = Join-Path $StateDir ('source_backup_' + $Stamp)
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    foreach ($name in @('core.py','modern_gui.py','speaker_ai.py','role_review_ui.py','license_client.py','license_ui.py','requirements.txt')) {
        $p = Join-Path $script:AppDir $name
        if (Test-Path -LiteralPath $p) { Copy-Item -LiteralPath $p -Destination (Join-Path $backup $name) -ErrorAction Stop }
    }
    Say ('Backup source: ' + $backup)
    Say ("git pull --ff-only origin $branch")
    Git @('pull','--ff-only','origin', $branch)
    $new = Git-Text @('rev-parse','HEAD')
    if ($old -eq $new) {
        Say 'Da la ban moi nhat, khong co thay doi.'
    } else {
        Say ('Updated: ' + $old.Substring(0,7) + ' -> ' + $new.Substring(0,7))
        $changed = Git-Text @('diff','--name-only',$old,$new)
        if (($changed -split "`n") -contains 'requirements.txt') {
            $venv = Join-Path $script:AppDir 'venv\Scripts\python.exe'
            if (-not (Test-Path -LiteralPath $venv)) {
                $venv = Join-Path $script:AppDir '.venv\Scripts\python.exe'
            }
            if (-not (Test-Path -LiteralPath $venv)) { Fail 'requirements.txt thay doi nhung chua co main venv. Chay INSTALL_NEW_PC.bat.' }
            Say 'requirements.txt da doi, cai lai thu vien...'
            Run $venv @('-m','pip','install','-r',(Join-Path $script:AppDir 'requirements.txt'))
            $marker = Join-Path $script:AppDir '.setup\requirements.sha256'
            New-Item -ItemType Directory -Path (Split-Path $marker -Parent) -Force | Out-Null
            [IO.File]::WriteAllText($marker, (Get-FileHash (Join-Path $script:AppDir 'requirements.txt') -Algorithm SHA256).Hash.ToLowerInvariant())
        }
        if (($changed -split "`n") -contains 'requirements_roles.txt') {
            Warn 'requirements_roles.txt da doi. Can xem huong dan moi de cap nhat .venv_roles.'
        }
    }
    Say 'UPDATE THANH CONG! Khong xoa downloaded_data, voices, license_config.json, .venv_roles, venv.'
    Say 'Dong app truoc khi UPDATE; bay gio co the mo lai START_APP.bat.'
    if ($script:TranscriptStarted) { Stop-Transcript | Out-Null }
    exit 0
} catch {
    Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host ('[ERROR] Xem log: ' + $Log) -ForegroundColor Yellow
    if ($script:TranscriptStarted) { Stop-Transcript | Out-Null }
    exit 1
}
