# Sets up DigiPal on Windows. Run it with "Install DigiPal.bat" (double-click).
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
Write-Host ""
Write-Host "  ~ Setting up Digi! ~" -ForegroundColor Magenta
Write-Host ""

# 1. find Python
$py = $null
foreach ($cand in @("py", "python", "python3")) {
    try {
        $exe = & $cand -3 -c "import sys; print(sys.executable)" 2>$null
        if (-not $exe) { $exe = & $cand -c "import sys; print(sys.executable)" 2>$null }
        if ($exe -and (Test-Path $exe)) { $py = $exe.Trim(); break }
    } catch {}
}
if (-not $py) {
    Write-Host "I couldn't find Python. Install it from python.org (tick 'Add python.exe to PATH')," -ForegroundColor Red
    Write-Host "then double-click 'Install DigiPal' again." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}
$ver = & $py -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Host "Using Python $ver at $py"

# 2. the things Digi is built with
Write-Host ""
Write-Host "Installing Digi's window library (this can take a few minutes)..." -ForegroundColor Cyan
& $py -m pip install --upgrade pip
& $py -m pip install --upgrade PySide6 psutil
if ($LASTEXITCODE -ne 0) {
    Write-Host "Hmm, that didn't install. Tell Claude what the red text above says!" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}
Write-Host ""
Write-Host "Installing Digi's ears (voice) and music detection..." -ForegroundColor Cyan
& $py -m pip install --upgrade winrt-runtime winrt-Windows.Foundation winrt-Windows.Foundation.Collections `
    winrt-Windows.Globalization winrt-Windows.Media.SpeechRecognition winrt-Windows.Media.Control
if ($LASTEXITCODE -ne 0) {
    Write-Host "(Voice and music detection didn't install - Digi still works without them. Tell Claude!)" -ForegroundColor Yellow
}

# 3. her frames (pictures): from pet_frames.zip in Downloads, or downloaded from GitHub
$zip = Join-Path $env:USERPROFILE "Downloads\pet_frames.zip"
$frames = Join-Path $here "pet_frames"
if (-not (Test-Path $zip) -and -not (Test-Path (Join-Path $frames "idle_00.png"))) {
    try {
        $info = Get-Content (Join-Path $here "version.json") -Raw | ConvertFrom-Json
        Write-Host ""
        Write-Host "Downloading Digi's pictures (about $($info.frames_mb) MB - this can take a while)..." -ForegroundColor Cyan
        $zip = Join-Path $env:TEMP "pet_frames.zip"
        $ProgressPreference = "SilentlyContinue"
        Invoke-WebRequest -Uri $info.frames_url -OutFile $zip -UseBasicParsing
    } catch {
        Write-Host "Couldn't download Digi's pictures: $_" -ForegroundColor Yellow
    }
}
if ((Test-Path $zip) -and -not (Test-Path (Join-Path $frames "idle_00.png"))) {
    Write-Host ""
    Write-Host "Unpacking Digi's frames (about 800 MB, give it a minute)..." -ForegroundColor Cyan
    tar -xf $zip -C $here 2>$null
    if (-not (Test-Path (Join-Path $frames "idle_00.png"))) {
        Expand-Archive -Force -Path $zip -DestinationPath $here
    }
    $junk = Join-Path $here "__MACOSX"
    if (Test-Path $junk) { Remove-Item -Recurse -Force $junk }
}
if (Test-Path (Join-Path $frames "idle_00.png")) {
    Write-Host "Frames are ready!" -ForegroundColor Green
} else {
    Write-Host "I couldn't find Digi's frames. Put pet_frames.zip in Downloads and run this again." -ForegroundColor Yellow
}

# 4. shortcuts on the Desktop and in the Start menu
$pyw = Join-Path (Split-Path -Parent $py) "pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = $py }
$script = Join-Path $here "digipal.py"
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))) {
    try {
        $lnk = $shell.CreateShortcut((Join-Path $dir "DigiPal.lnk"))
        $lnk.TargetPath = $pyw
        $lnk.Arguments = '"' + $script + '"'
        $lnk.WorkingDirectory = $here
        $lnk.IconLocation = (Join-Path $here "digipal.ico")
        $lnk.Description = "Digi, your desktop pal"
        $lnk.Save()
    } catch {}
}
Write-Host "Made a DigiPal shortcut on your Desktop and in the Start menu." -ForegroundColor Green

# 5. say hi!
Write-Host ""
Write-Host "All done! Starting Digi..." -ForegroundColor Magenta
Start-Process -FilePath $pyw -ArgumentList ('"' + $script + '"') -WorkingDirectory $here
Start-Sleep -Seconds 3
