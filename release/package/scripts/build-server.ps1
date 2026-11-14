<#
  EXVS2 matchmaking server - build script (step 1).
  Downloads the EXVS2-IB-Server card server source (pinned commit) from GitHub, applies the
  exvs2-matchmaking patch, and builds a ready-to-run Windows server into the "server" folder.
  Everything it downloads goes into the "tools" and "build" folders next to this package.
  No admin rights needed. Nothing outside this folder is changed.
#>
param(
    # Optional: your official Server-Infinite v1.2.0 folder, to copy the WebUI pictures (and your card database).
    [string]$OfficialServerFolder = "",
    # Don't ask questions (for automated tests).
    [switch]$NoPrompt,
    # Runtime to build for. Default win-x64 (Windows 10/11 64-bit).
    [string]$Runtime = "win-x64"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # makes Invoke-WebRequest much faster on Windows PowerShell 5.1
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

$UpstreamRepo   = "Chiang-17/EXVS2-IB-Server"
$UpstreamCommit = "7f4b28057631dbd7801c0b079b8455dcaa9c9a7b"   # v1.2.0
$MinGitUrl      = "https://github.com/git-for-windows/git/releases/download/v2.56.1.windows.1/MinGit-2.56.1-64-bit.zip"
$MinGitSha256   = "4a92850b6e917da4fd010669b614b55dccf5b0ec333a534cc4be4700dfefdafd"

$Root      = Split-Path -Parent $PSScriptRoot
$Tools     = Join-Path $Root "tools"
$Build     = Join-Path $Root "build"
$ServerDir = Join-Path $Root "server"
$Patch     = Join-Path $Root "files\online-matchmaking.patch"
$OnWindows = ($env:OS -eq "Windows_NT")
$ExeName   = if ($OnWindows -or $Runtime -like "win-*") { "Server-Infinite.exe" } else { "Server-Infinite" }

function Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Info($text) { Write-Host "    $text" }
function Fail($text) { Write-Host ""; Write-Host "ERROR: $text" -ForegroundColor Red; exit 1 }
function Download($url, $dest) {
    Info "Downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
}

Write-Host "EXVS2 matchmaking server - build" -ForegroundColor Green
Info "Package folder: $Root"
if (-not (Test-Path $Patch)) { Fail "files\online-matchmaking.patch is missing. Re-extract the whole zip." }
if ($Root -match '[^\x20-\x7E]') {
    Write-Host "    Note: the folder path has non-English characters. If the build fails, move the folder to e.g. C:\exvs2-server." -ForegroundColor Yellow
}

# Refuse to replace the exe while it is running.
if ($OnWindows) {
    $running = Get-Process -Name "Server-Infinite" -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($ServerDir, [StringComparison]::OrdinalIgnoreCase) }
    if ($running) { Fail "The server is running (Server-Infinite.exe). Close its window first, then run this again." }
}
New-Item -ItemType Directory -Force -Path $Tools, $Build | Out-Null

# ---------------------------------------------------------------- git (only used to apply the patch)
Step "1/5  Checking for git"
$git = (Get-Command git -ErrorAction SilentlyContinue).Source
if (-not $git) {
    $git = Join-Path $Tools "mingit\cmd\git.exe"
    if (-not (Test-Path $git)) {
        if (-not $OnWindows) { Fail "git not found. Install git and run again." }
        Info "git not installed - downloading a portable copy (MinGit, ~40 MB) into tools\mingit"
        $zip = Join-Path $Tools "mingit.zip"
        Download $MinGitUrl $zip
        $hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
        if ($hash -ne $MinGitSha256) { Remove-Item $zip; Fail "MinGit download is damaged (checksum mismatch). Try again." }
        Expand-Archive -Path $zip -DestinationPath (Join-Path $Tools "mingit") -Force
        Remove-Item $zip
    }
}
Info "Using git: $git"

# ---------------------------------------------------------------- .NET 9 SDK
Step "2/5  Checking for the .NET 9 SDK"
$dotnet = $null
$localDotnetDir = Join-Path $Tools "dotnet"
$localDotnet = Join-Path $localDotnetDir ($(if ($OnWindows) { "dotnet.exe" } else { "dotnet" }))
foreach ($candidate in @($localDotnet, (Get-Command dotnet -ErrorAction SilentlyContinue).Source)) {
    if ($candidate -and (Test-Path $candidate)) {
        $sdks = & $candidate --list-sdks 2>$null
        if ($sdks -match '^9\.') { $dotnet = $candidate; break }
    }
}
if (-not $dotnet) {
    if (-not $OnWindows) { Fail ".NET 9 SDK not found. Install it (https://dot.net) and run again." }
    Info ".NET 9 SDK not found - installing a private copy into tools\dotnet (~250 MB download, no admin needed)"
    $installer = Join-Path $Tools "dotnet-install.ps1"
    Download "https://dot.net/v1/dotnet-install.ps1" $installer
    & powershell -NoProfile -ExecutionPolicy Bypass -File $installer -Channel 9.0 -InstallDir $localDotnetDir -NoPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $localDotnet)) { Fail ".NET SDK install failed (see messages above)." }
    $dotnet = $localDotnet
}
Info "Using dotnet: $dotnet ($((& $dotnet --version)))"
$env:DOTNET_CLI_TELEMETRY_OPTOUT = "1"
$env:DOTNET_NOLOGO = "1"
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = "1"
if ($dotnet -eq $localDotnet) { $env:DOTNET_ROOT = $localDotnetDir }

# ---------------------------------------------------------------- source
Step "3/5  Downloading the card server source ($UpstreamRepo @ $($UpstreamCommit.Substring(0,7)))"
$src = Join-Path $Build "src"
if (Test-Path $src) { Remove-Item -Recurse -Force $src }
$zip = Join-Path $Build "upstream.zip"
Download "https://github.com/$UpstreamRepo/archive/$UpstreamCommit.zip" $zip
$unz = Join-Path $Build "unzip"
if (Test-Path $unz) { Remove-Item -Recurse -Force $unz }
Expand-Archive -Path $zip -DestinationPath $unz -Force
$inner = Get-ChildItem $unz -Directory | Select-Object -First 1
Move-Item $inner.FullName $src
Remove-Item -Recurse -Force $unz
Remove-Item $zip

Step "     Applying the online-matchmaking patch"
Push-Location $src
try {
    # Its own tiny repo, so 'git apply' never touches anything outside build\src.
    & $git init -q . | Out-Null
    & $git -c core.autocrlf=false apply --check --whitespace=nowarn $Patch
    if ($LASTEXITCODE -ne 0) { Fail "The patch does not apply to this source. Please report this." }
    & $git -c core.autocrlf=false apply --whitespace=nowarn $Patch
    if ($LASTEXITCODE -ne 0) { Fail "Applying the patch failed." }
} finally { Pop-Location }
Info "Patch applied."

# ---------------------------------------------------------------- build
Step "4/5  Building the server (first time takes a few minutes)"
$out = Join-Path $Build "out"
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
& $dotnet publish (Join-Path $src "Server-Infinite") -c Release -r $Runtime -p:EnableWindowsTargeting=true -o $out
if ($LASTEXITCODE -ne 0) { Fail "Build failed (see messages above). Check your internet connection and try again." }
if (-not (Test-Path (Join-Path $out $ExeName))) { Fail "Build finished but $ExeName is missing." }

# ---------------------------------------------------------------- lay out the server folder
Step "5/5  Setting up the server folder"
$firstInstall = -not (Test-Path (Join-Path $ServerDir "Configurations\server.json"))
New-Item -ItemType Directory -Force -Path $ServerDir | Out-Null
$keep = @("Configurations\server.json", "Configurations\kestrel.json", "Configurations\log.json")
Get-ChildItem $out -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($out.Length).TrimStart('\', '/')
    $dest = Join-Path $ServerDir $rel
    $relWin = $rel -replace '/', '\'
    if (-not $firstInstall -and ($keep -contains $relWin) -and (Test-Path $dest)) {
        Copy-Item $_.FullName ($dest + ".new-default") -Force    # keep your settings, save the new default next to them
    } else {
        New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
        Copy-Item $_.FullName $dest -Force
    }
}
Info "Server files are in: $ServerDir"
if (-not $firstInstall) { Info "Your existing Configurations\*.json were kept (new defaults saved as *.new-default)." }

# Optional: pictures + card database from the official release (not in the source code on GitHub).
if (-not $OfficialServerFolder -and -not $NoPrompt) {
    Write-Host ""
    Write-Host "Optional: the card website (WebUI) pictures are not part of the source code." -ForegroundColor Yellow
    Write-Host "If you have the official Server-Infinite v1.2.0 folder (the one with its own Server.exe and wwwroot),"
    Write-Host "type or paste its path to copy the pictures (and, if you want, your card database)."
    $OfficialServerFolder = Read-Host "Path (or just press Enter to skip)"
}
$OfficialServerFolder = $OfficialServerFolder.Trim().Trim('"')
if ($OfficialServerFolder) {
    $offWww = Join-Path $OfficialServerFolder "wwwroot"
    if (-not (Test-Path $offWww)) {
        Write-Host "    No wwwroot folder in '$OfficialServerFolder' - skipped pictures." -ForegroundColor Yellow
    } else {
        Info "Copying pictures (only files the new build doesn't have; this can take a minute)..."
        $newWww = Join-Path $ServerDir "wwwroot"
        if ($OnWindows) {
            # /XC /XN /XO = never overwrite the new build's files; copy only missing ones.
            & robocopy $offWww $newWww /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP | Out-Null
            if ($LASTEXITCODE -ge 8) { Write-Host "    Copying pictures had errors (robocopy code $LASTEXITCODE)." -ForegroundColor Yellow }
        } else {
            Get-ChildItem $offWww -Recurse -File | ForEach-Object {
                $d = Join-Path $newWww $_.FullName.Substring($offWww.Length).TrimStart('\', '/')
                if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path (Split-Path $d) | Out-Null; Copy-Item $_.FullName $d }
            }
        }
        Info "Pictures copied."
    }
    $offDb = Join-Path $OfficialServerFolder "ServerInfinite.db"
    $newDb = Join-Path $ServerDir "ServerInfinite.db"
    if ((Test-Path $offDb) -and -not (Test-Path $newDb)) {
        $ans = if ($NoPrompt) { "n" } else { Read-Host "Copy your card database (ServerInfinite.db) from there? The original stays untouched. [y/N]" }
        if ($ans -match '^[yY]') { Copy-Item $offDb $newDb; Info "Card database copied (it gets one new column on first start)." }
    }
}

Write-Host ""
Write-Host "Build finished." -ForegroundColor Green
Write-Host "Next: double-click 2-Configure.bat"
