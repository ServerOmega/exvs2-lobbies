<#
.SYNOPSIS
  READ-ONLY check of the hidden dev-menu values in EXVS2 IB testmode_pcb.json (results-hang fix #3).

.DESCRIPTION
  Prints the debugParam values that can affect the results screen, online matching or input delay, and flags
  anything that is not the safe value. It never writes, renames or locks any file, never starts the game, and never
  loads or runs a DLL (bngrw.dll is only scanned as bytes for a few config key names). It prints no card data: it
  reads only testmode_pcb.json and, from config.ini, only the card-reader switches listed below (never accessCode /
  chipId / AccessCode / ChipId / BootToken lines).

  debugParams only take effect when the dev-menu gate is on (a modified "debug" bngrw.dll). With the normal DLL the
  game ignores them, but a copied testmode_pcb.json can still carry old values into a later debug-DLL session.
  Source: analysis/debug-menu.md (vsac29 static analysis, serializer 0x1406dec70).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\check-debugparam.ps1 -GameDir "G:\IB\29"
  powershell -ExecutionPolicy Bypass -File tools\check-debugparam.ps1 -Path "D:\cab2\29\testmode_pcb.json"
#>
[CmdletBinding()]
param(
    [string]$GameDir = ".",
    [string]$Path = ""
)
Set-StrictMode -Version 2
$ErrorActionPreference = "Stop"

# index -> (name, safe value, why it matters). "safe" = the value to use for normal play / the hang tests.
$Flags = @{
    3  = @("fix input delay (uses keyDelay)", 0, "netcode knob; also changes CPU-mode delay (4F). Same on every cabinet if used")
    5  = @("HTTP at fastest rate", 0, "changes card-server request pacing")
    7  = @("always offline (AllNet NG)", 0, "breaks online matching")
    8  = @("disable storage writes", 0, "settings / replays not saved")
    9  = @("virtual card-touch menu", 0, "replaces card touches -> card prompts (rematch / team / option) behave differently")
    24 = @("debug battle mode", 0, "different battle flow")
    25 = @("result capture every time", 0, "adds the capture task (~5 s x up to 3) after every match")
    27 = @("no error when PCB1/2 absent", 0, "POC forces this for clients; not a hang cause on its own")
    28 = @("force error on result-save request", 0, "result save fails + retries (task S)")
    44 = @("fake 1-min delay on result-save response", 0, "HANG CANDIDATE: holds the results screen ~60 s per save")
    45 = @("unlimited return matches", 0, "rematch prompt not limited to 2")
    55 = @("stop ALL timers", 0, "HANG CANDIDATE: result HUD countdowns never run out -> results screen never ends")
    15 = @("show resident (network) task status", 0, "diagnostic only (1 is fine while testing)")
    18 = @("WAN matching log on screen", 0, "diagnostic only (1 is fine while testing)")
    47 = @("stuck / progress-blocked check", 0, "diagnostic only (1 is fine while testing)")
    57 = @("team info log", 0, "diagnostic only (1 is fine while testing)")
    61 = @("sub-tasks alive after the match", 0, "diagnostic only: shows F/S/A/C/R letters on a hung results screen")
}
foreach ($i in 32..35) { $Flags[$i] = @("time-limit shortener #$i", 0, "shortens timed modes") }
# allowed to be on (shown in cyan, no warning): the input-delay knob, POC-forced #27, rematch limit, diagnostics
$Diagnostic = @(3, 15, 18, 27, 45, 47, 57, 61)

# scalar debugParam keys (TestMode +0x4f0..)
$Scalars = [ordered]@{
    lanMatchingGroupId    = "in-store matching id (separate in-store lobbies)"
    wanMatchingGroupId    = "online matching id = EntryMatching attr1 when the debug gate is on (separate online lobbies)"
    keyDelay              = "input delay frames used when #3 is on (1-18; community: 5-8)"
    ipMode                = "0 auto, 1 IPv4, 2 IPv6 (keep 0 or 1; IPv6 breaks STUN)"
    classMatchSearchId    = "class match search id"
    liveInitialBufferSize = "LM relay buffer (spectator only; leave as is)"
    initWinstreakCount    = "starting win streak"
    routeBattleStageNum   = "route battle stages unlocked"
    locateTestEnable      = "location test"
    locateTestDebugValue  = "location test value"
}

function Find-Nodes($node, [string]$key, [string]$path, [System.Collections.ArrayList]$out) {
    if ($null -eq $node) { return }
    if ($node -is [System.Management.Automation.PSCustomObject]) {
        foreach ($p in $node.PSObject.Properties) {
            $sub = if ($path) { "$path.$($p.Name)" } else { $p.Name }
            if ($p.Name -eq $key) { [void]$out.Add(@($sub, $p.Value)) }
            Find-Nodes $p.Value $key $sub $out
        }
    } elseif ($node -is [System.Array]) {
        for ($i = 0; $i -lt $node.Count; $i++) { Find-Nodes $node[$i] $key "$path[$i]" $out }
    }
}

function Get-FlagValue($debugParams, [int]$i) {
    if ($null -eq $debugParams) { return $null }
    if ($debugParams -is [System.Array]) {
        $byId = $debugParams.Count -gt 0 -and $debugParams[0] -is [System.Management.Automation.PSCustomObject] -and
            ($debugParams[0].PSObject.Properties["id"] -or $debugParams[0].PSObject.Properties["index"] -or $debugParams[0].PSObject.Properties["no"])
        if (-not $byId -and $i -lt $debugParams.Count) {
            $v = $debugParams[$i]
            if ($v -is [System.Management.Automation.PSCustomObject]) {   # e.g. {"id":3,"value":1}
                foreach ($n in "value", "enable", "flag", "param") { if ($v.PSObject.Properties[$n]) { return $v.$n } }
            }
            return $v
        }
        foreach ($v in $debugParams) {   # list of {"id"/"index": n, "value": x}
            if ($v -is [System.Management.Automation.PSCustomObject]) {
                foreach ($k in "id", "index", "no") {
                    if ($v.PSObject.Properties[$k] -and [int]$v.$k -eq $i) {
                        foreach ($n in "value", "enable", "flag", "param") { if ($v.PSObject.Properties[$n]) { return $v.$n } }
                    }
                }
            }
        }
        return $null
    }
    if ($debugParams -is [System.Management.Automation.PSCustomObject]) {
        $p = $debugParams.PSObject.Properties["$i"]
        if ($p) { return $p.Value }
    }
    return $null
}

function To-Int($v) {
    if ($null -eq $v) { return $null }
    if ($v -is [bool]) { return [int]$v }
    try { return [int64]$v } catch { return $null }
}

# ---- locate the file
if (-not $Path) {
    $cands = @("testmode_pcb.json", "29\testmode_pcb.json", "..\29\testmode_pcb.json") |
        ForEach-Object { Join-Path $GameDir $_ } | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
    if (-not $cands) {
        $found = Get-ChildItem -LiteralPath $GameDir -Filter testmode_pcb.json -Recurse -Depth 3 -ErrorAction SilentlyContinue |
            Select-Object -First 3
        $cands = @($found | ForEach-Object { $_.FullName })
    }
    if (-not $cands) { Write-Host "testmode_pcb.json not found under '$GameDir'. Use -Path." -ForegroundColor Red; exit 2 }
    $Path = @($cands)[0]
}
$Path = (Resolve-Path -LiteralPath $Path).Path
$item = Get-Item -LiteralPath $Path
$hashBefore = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
Write-Host "File     : $Path"
Write-Host "Modified : $($item.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')) (local time)   Size: $($item.Length) bytes"
Write-Host "SHA256   : $hashBefore   (compare between cabinets)"
Write-Host "Read-only check: nothing is written.`n"

$raw = [System.IO.File]::ReadAllText($Path)   # read-only open
try { $json = $raw | ConvertFrom-Json } catch { Write-Host "Not valid JSON: $($_.Exception.Message)" -ForegroundColor Red; exit 3 }

$warn = 0

# ---- battleMode of every setting entry (0 = online / MMS)
$bm = New-Object System.Collections.ArrayList
Find-Nodes $json "battleMode" "" $bm
if ($bm.Count) {
    Write-Host "battleMode (0 = online matching; other values = LM / in-store path):"
    foreach ($b in $bm) { Write-Host ("  {0,-55} {1}" -f $b[0], $b[1]) }
    Write-Host ""
}

# ---- debugParam block
$dp = New-Object System.Collections.ArrayList
Find-Nodes $json "debugParam" "" $dp
if (-not $dp.Count) {
    Write-Host "No 'debugParam' block in this file: the dev-menu values were never saved here (all defaults). OK." -ForegroundColor Green
} else {
    foreach ($d in $dp) {
        $block = $d[1]
        Write-Host "debugParam block at: $($d[0])"
        foreach ($k in $Scalars.Keys) {
            $p = if ($block -is [System.Management.Automation.PSCustomObject]) { $block.PSObject.Properties[$k] } else { $null }
            $val = if ($p) { $p.Value } else { "(absent)" }
            $note = ""
            if ($k -eq "ipMode" -and (To-Int $val) -eq 2) { $note = "  <-- IPv6: breaks STUN / our matchmaker"; $warn++ }
            if ($k -eq "keyDelay" -and $p -and ((To-Int $val) -lt 1 -or (To-Int $val) -gt 18)) { $note = "  <-- outside 1-18" }
            if ($k -eq "wanMatchingGroupId" -and $p -and (To-Int $val) -ne 0) { $note = "  <-- non-zero: only cabinets with the same id meet (when the debug gate is on)" }
            Write-Host ("  {0,-22} = {1,-10} {2}{3}" -f $k, $val, $Scalars[$k], $note)
        }
        $list = if ($block -is [System.Management.Automation.PSCustomObject] -and $block.PSObject.Properties["debugParams"]) { $block.debugParams } else { $null }
        if ($null -eq $list) {
            Write-Host "  debugParams            = (absent) -> all on/off options default (off). OK." -ForegroundColor Green
        } else {
            $count = if ($list -is [System.Array]) { $list.Count } else { @($list.PSObject.Properties).Count }
            Write-Host "  debugParams: $count entries. Relevant options (safe value in brackets):"
            foreach ($i in ($Flags.Keys | Sort-Object)) {
                $f = $Flags[$i]
                $v = Get-FlagValue $list $i
                $n = To-Int $v
                $shown = if ($null -eq $v) { "(absent)" } else { "$v" }
                $bad = ($null -ne $n) -and ($n -ne $f[1])
                $color = "Gray"; $tag = "ok "
                if ($bad -and $Diagnostic -contains $i) { $color = "Cyan"; $tag = "on " }
                elseif ($bad) { $color = "Yellow"; $tag = "SET"; $warn++ }
                if ($bad -and ($i -eq 44 -or $i -eq 55)) { $color = "Red"; $tag = "!!!" }
                Write-Host ("   [{0}] #{1,-2} = {2,-8} [{3}] {4} - {5}" -f $tag, $i, $shown, $f[1], $f[0], $f[2]) -ForegroundColor $color
            }
            # any other non-zero entries
            $others = @()
            if ($list -is [System.Array]) {
                for ($i = 0; $i -lt [Math]::Max($list.Count, 64); $i++) {
                    if (-not $Flags.ContainsKey($i)) { $n = To-Int (Get-FlagValue $list $i); if ($n) { $others += "#$i=$n" } }
                }
            }
            if ($others.Count) { Write-Host "  Other non-zero options: $($others -join ', ')  (see analysis/debug-menu.md section 2.3)" -ForegroundColor Yellow }
        }
        Write-Host ""
    }
}

# ---- card-reader switches (POC-style config.ini), only these keys are printed
$iniKeys = "AutomaticCardButton", "UseRealCardReader", "UsePyBanapassReader", "CardCancelCallback", "CardCancelStatus"
$gameRoot = Split-Path -Parent (Split-Path -Parent $Path)
foreach ($ini in @((Join-Path (Split-Path -Parent $Path) "config.ini"), (Join-Path $gameRoot "config.ini"))) {
    if (Test-Path -LiteralPath $ini -PathType Leaf) {
        Write-Host "Card-reader switches in $ini (other lines are not shown):"
        $hit = $false
        foreach ($line in [System.IO.File]::ReadAllLines($ini)) {
            $t = $line.Trim()
            foreach ($k in $iniKeys) { if ($t -match "^(?i)$k\s*=") { Write-Host "  $t"; $hit = $true } }
        }
        if (-not $hit) { Write-Host "  (none of: $($iniKeys -join ', '))" }
        Write-Host ""
    }
}

# ---- bngrw.dll: which config keys its code knows (byte scan only, the DLL is NOT loaded)
foreach ($dll in @((Join-Path (Split-Path -Parent $Path) "bngrw.dll"), (Join-Path $gameRoot "bngrw.dll"))) {
    if (Test-Path -LiteralPath $dll -PathType Leaf) {
        $bytes = [System.IO.File]::ReadAllBytes($dll)
        $text = [System.Text.Encoding]::ASCII.GetString($bytes)
        $h = (Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash
        Write-Host "bngrw.dll: $dll  ($($bytes.Length) bytes, SHA256 $h) - scanned as bytes, not loaded"
        foreach ($k in "AutomaticCardButton", "UseRealCardReader", "BngRwReqCancel", "BngRwReqWaitTouch", "CardCancelCallback", "EnableDebugInPcb") {
            Write-Host ("  {0,-22} {1}" -f $k, $(if ($text.Contains($k)) { "present" } else { "-" }))
        }
        Write-Host ""
    }
}

$hashAfter = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
if ($hashAfter -ne $hashBefore) { Write-Host "Note: the file changed while reading (the game rewrites it while running)." -ForegroundColor Yellow }
if ($warn) {
    Write-Host "$warn value(s) differ from the safe value. Change them only with the game closed, from a backup copy, never with EXIT & SAVE." -ForegroundColor Yellow
    exit 1
}
Write-Host "No risky values found." -ForegroundColor Green
exit 0
