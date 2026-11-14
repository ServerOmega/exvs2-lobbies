<#
  EXVS2 matchmaking server - import card-website pictures.
  Copies only wwwroot\images from the official Server-Infinite v1.2.0 folder or zip
  into a built server. Never changes Configurations\ or ServerInfinite.db unless
  you pass -Database (and even then it will not overwrite an existing database).
#>
param(
    [Parameter(Position = 0)]
    [string]$OfficialSource = "",
    [Parameter(Position = 1)]
    [string]$ServerDir = "",
    # Overwrite picture files that are already in the server folder (still never touches settings or the database).
    [switch]$Force,
    # Copy ServerInfinite.db from the official folder only if the destination does not already have one.
    [switch]$Database,
    [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
if (-not $ServerDir) { $ServerDir = Join-Path $Root "server" }

function Info($text) { Write-Host "    $text" }
function Fail($text) { Write-Host ""; Write-Host "ERROR: $text" -ForegroundColor Red; exit 1 }

function Test-LooksLikeImagesDir([string]$dir) {
    if (-not (Test-Path $dir -PathType Container)) { return $false }
    foreach ($name in @("mobile_suits", "pilots", "titles", "navis", "sticker")) {
        if (Test-Path (Join-Path $dir $name) -PathType Container) { return $true }
    }
    $webp = Get-ChildItem $dir -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -match '^\.webp$' }
    return [bool]$webp
}

function Find-ImagesDir([string]$base) {
    $candidates = @(
        (Join-Path $base "wwwroot\images"),
        (Join-Path $base "images")
    )
    $child = Get-ChildItem $base -Directory -ErrorAction SilentlyContinue
    if ($child) {
        foreach ($d in $child) {
            $candidates += (Join-Path $d.FullName "wwwroot\images")
            $candidates += (Join-Path $d.FullName "images")
        }
    }
    $candidates += $base
    foreach ($c in $candidates) {
        if (Test-LooksLikeImagesDir $c) { return (Resolve-Path $c).Path }
    }
    return $null
}

function Find-OfficialRoot([string]$base, [string]$imagesDir) {
    # Folder that would contain Server-Infinite.exe / ServerInfinite.db / wwwroot.
    $p = $imagesDir
    $name = [IO.Path]::GetFileName($p)
    if ($name -eq "images") {
        $parent = Split-Path $p
        if ([IO.Path]::GetFileName($parent) -eq "wwwroot") { return (Split-Path $parent) }
        return $parent
    }
    return $base
}

function Convert-ImageRelPath([string]$rel) {
    # Lowercase only the extension (.WEBP -> .webp) so a copy made on Windows still works on Linux.
    $relWin = $rel.Replace('/', '\').TrimStart('\')
    $dir = [IO.Path]::GetDirectoryName($relWin)
    $name = [IO.Path]::GetFileNameWithoutExtension($relWin)
    $ext = [IO.Path]::GetExtension($relWin)
    if ($ext) { $ext = $ext.ToLowerInvariant() }
    $leaf = "$name$ext"
    if ([string]::IsNullOrEmpty($dir)) { return $leaf }
    return (Join-Path $dir $leaf)
}

function Extract-ImagesFromZip([string]$zipPath, [string]$destDir) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    $copied = 0
    try {
        foreach ($entry in $zip.Entries) {
            $n = $entry.FullName.Replace('\', '/')
            if ($n.EndsWith('/')) { continue }
            if ($n.Contains('..')) { continue }
            $idx = $n.IndexOf('wwwroot/images/', [StringComparison]::OrdinalIgnoreCase)
            if ($idx -lt 0) { continue }
            $rel = $n.Substring($idx + 'wwwroot/images/'.Length)
            if (-not $rel) { continue }
            $out = Join-Path $destDir (Convert-ImageRelPath $rel)
            $outParent = Split-Path $out
            if (-not (Test-Path $outParent)) { New-Item -ItemType Directory -Force -Path $outParent | Out-Null }
            if ((Test-Path $out) -and -not $Force) { continue }
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $out, $true)
            $copied++
        }
    } finally { $zip.Dispose() }
    if ($copied -eq 0) {
        Fail "No wwwroot/images files found in the zip. Is this Server-Infinite-v1.2.0.zip from https://github.com/Chiang-17/EXVS2-IB-Server/releases/tag/v1.2.0 ?"
    }
    return $copied
}

Write-Host "EXVS2 matchmaking server - import pictures" -ForegroundColor Green

if (-not $OfficialSource -and -not $NoPrompt) {
    Write-Host ""
    Write-Host "Pictures come from the official v1.2.0 release:" -ForegroundColor Yellow
    Write-Host "  https://github.com/Chiang-17/EXVS2-IB-Server/releases/tag/v1.2.0"
    Write-Host "Give the path to the extracted official folder (the one with Server-Infinite.exe and wwwroot)"
    Write-Host "or to Server-Infinite-v1.2.0.zip."
    $OfficialSource = Read-Host "Path"
}
$OfficialSource = ($OfficialSource).Trim().Trim('"')
if (-not $OfficialSource) { Fail "No path given. See Import-Pictures.txt." }
if (-not (Test-Path $OfficialSource)) { Fail "Path not found: $OfficialSource" }

if (-not (Test-Path (Join-Path $ServerDir "wwwroot"))) {
    Fail "No wwwroot folder in '$ServerDir'. Build the server first (1-Build-Server.bat), or pass the server folder as the second argument."
}

$destImages = Join-Path $ServerDir "wwwroot\images"
New-Item -ItemType Directory -Force -Path $destImages | Out-Null
Info "Server folder: $ServerDir"
Info "Pictures go to: $destImages"

$srcItem = Get-Item $OfficialSource
$copied = 0
$officialRoot = $null

if ($srcItem.Extension -match '^\.zip$') {
    Info "Reading pictures from the zip (only wwwroot\images; the official program is not copied)..."
    $copied = Extract-ImagesFromZip $srcItem.FullName $destImages
    Info "Copied $copied picture files from the zip."
} else {
    $imagesDir = Find-ImagesDir $srcItem.FullName
    if (-not $imagesDir) {
        Fail "Could not find wwwroot\images under '$OfficialSource'. Extract Server-Infinite-v1.2.0.zip and point at the folder that contains Server-Infinite.exe and wwwroot."
    }
    $officialRoot = Find-OfficialRoot $srcItem.FullName $imagesDir
    Info "Found pictures in: $imagesDir"
    $copied = 0
    Get-ChildItem $imagesDir -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($imagesDir.Length).TrimStart('\', '/')
        $d = Join-Path $destImages (Convert-ImageRelPath $rel)
        if ((Test-Path $d) -and -not $Force) { return }
        New-Item -ItemType Directory -Force -Path (Split-Path $d) | Out-Null
        Copy-Item $_.FullName $d -Force
        $script:copied++
    }
    if ($Force) {
        Info "Copied / updated $copied picture files."
    } else {
        Info "Copied $copied new picture files (existing files were left as they were)."
    }
}

$total = (Get-ChildItem $destImages -Recurse -File -ErrorAction SilentlyContinue).Count
Info "Pictures in server folder now: $total files."

if ($Database) {
    if (-not $officialRoot) {
        Write-Host "    The official v1.2.0 zip does not include a card database. Point at an official folder you have already used if you want to copy ServerInfinite.db." -ForegroundColor Yellow
    } else {
        $offDb = Join-Path $officialRoot "ServerInfinite.db"
        $newDb = Join-Path $ServerDir "ServerInfinite.db"
        if (-not (Test-Path $offDb)) {
            Write-Host "    No ServerInfinite.db in the official folder." -ForegroundColor Yellow
        } elseif (Test-Path $newDb) {
            Write-Host "    Your server already has ServerInfinite.db - left it alone (this script never overwrites the database)." -ForegroundColor Yellow
        } else {
            Copy-Item $offDb $newDb
            Info "Card database copied (it gets one new column on first start). The original is unchanged."
        }
    }
}

Write-Host ""
Write-Host "Done. Hard-reload the card website (Ctrl+F5). If pictures still don't show, restart the server and try again." -ForegroundColor Green
Write-Host "Check:  http://127.0.0.1:28080/images/mobile_suits/0.webp"
