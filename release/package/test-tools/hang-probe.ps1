<#
.SYNOPSIS
  READ-ONLY snapshot of the PC while the EXVS2 IB results screen hangs (results-hang simulation, analysis/results-hang-sim.md).

.DESCRIPTION
  Run it WHILE both cabinets sit on the hung results screen (and once more after they recover, for comparison).
  It writes one text file you can share. What it reads:
    * the game / LM / launcher / server processes: start time, "responding", CPU used during a short window, memory,
      thread count and (Windows) how many threads wait and why. A game that is busy (CPU > 0) and responding is
      waiting on its own logic, not frozen;
    * their network sockets (Windows): TCP connections (to the card server) with state, and UDP ports. A TCP
      connection stuck in SynSent / many CloseWait points at the card server; nothing open points away from it;
    * the tail of the newest card-server log (only result / error / watchdog lines, with timings);
    * recently changed *.log / *.txt files in the game folders (tail only).
  What it never does: write anything except the report file, stop / start / attach to a process, load a DLL, read
  card.ini / card.txt / any AccessCode / ChipId / BootToken value (any such value that appears in a log line is masked
  before it is written). Public IP addresses are shortened to a.b.x.x unless -KeepIps is given.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\hang-probe.ps1 -GameDir "G:\IB\29","G:\IB\29_P2" -ServerDir "G:\_re\mm-server"
  powershell -ExecutionPolicy Bypass -File tools\hang-probe.ps1 -Repeat 4 -Every 20      # 4 snapshots, 20 s apart
#>
[CmdletBinding()]
param(
    [string[]]$GameDir = @(),
    [string[]]$ServerDir = @(),
    [string]$Out = "",
    [int]$Seconds = 3,
    [int]$Repeat = 1,
    [int]$Every = 20,
    [int]$Lines = 60,
    [switch]$KeepIps
)
Set-StrictMode -Version 2
$ErrorActionPreference = "Continue"
if (-not $Out) { $Out = Join-Path (Get-Location) ("hang-probe-{0:yyyyMMdd-HHmmss}.txt" -f (Get-Date)) }
$ProcPattern = '^(vsac\d*.*|.*LiveMonitor.*|LM.*|SnowLauncher.*|Server-Infinite.*|ServerInfinite.*|Server|TeknoParrot.*|amdaemon.*)$'
$SkipFiles = '(?i)(card\.(ini|txt)|accesscode|chipid|boottoken|amconfig|secret)'

function Mask([string]$s) {
    if ($null -eq $s) { return "" }
    $s = [regex]::Replace($s, '(?i)\b(access_?code|chip_?id|session_?id|boot_?token|upload_?token|token)(\s*[:=]\s*)("?)([0-9A-Za-z_\-]{4,})',
        { param($m) $m.Groups[1].Value + $m.Groups[2].Value + $m.Groups[3].Value + "<masked:" + $m.Groups[4].Value.Length + ">" })
    $s = [regex]::Replace($s, '\b\d{20}\b', '<masked:20digits>')          # access-code shaped numbers
    $s = [regex]::Replace($s, '\b[0-9A-Fa-f]{32}\b', '<masked:32hex>')    # chip-id shaped hex
    $s = [regex]::Replace($s, '/upload(Image|Replay)/(\d+)/[0-9a-f]{8,}', '/upload$1/$2/<masked>')
    if (-not $KeepIps) {
        $s = [regex]::Replace($s, '\b(\d{1,3})\.(\d{1,3})\.\d{1,3}\.\d{1,3}\b', {
            param($m) $a = [int]$m.Groups[1].Value; $b = [int]$m.Groups[2].Value
            if ($a -eq 10 -or $a -eq 127 -or ($a -eq 192 -and $b -eq 168) -or ($a -eq 172 -and $b -ge 16 -and $b -le 31) -or
                ($a -eq 100 -and $b -ge 64 -and $b -le 127) -or $a -eq 0) { $m.Value } else { "$a.$b.x.x" } })
    }
    return $s
}
$report = New-Object System.Collections.Generic.List[string]
function W([string]$line = "") { $report.Add((Mask $line)) }

function Snapshot([int]$n) {
    W ("=" * 100)
    W ("Snapshot {0}/{1}  {2:yyyy-MM-dd HH:mm:ss zzz}  host {3}" -f $n, $Repeat, (Get-Date), [Environment]::MachineName)
    $procs = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match $ProcPattern })
    if (-not $procs) { W "No game / LM / launcher / server process found (pattern $ProcPattern)." }
    $cpu0 = @{}
    foreach ($p in $procs) { try { $cpu0[$p.Id] = $p.TotalProcessorTime.TotalMilliseconds } catch { $cpu0[$p.Id] = $null } }
    Start-Sleep -Seconds $Seconds
    W ""
    W ("{0,-7} {1,-24} {2,-19} {3,-5} {4,9} {5,9} {6,8} {7,7}  {8}" -f "PID", "Name", "Started", "Resp", "CPU%", "CPU s", "MB", "Thr", "Window")
    foreach ($p in $procs) {
        try { $p.Refresh() } catch {}
        $cpuMs = $null; $pct = ""
        try { $cpuMs = $p.TotalProcessorTime.TotalMilliseconds } catch {}
        if ($null -ne $cpuMs -and $null -ne $cpu0[$p.Id]) {
            $pct = "{0:N1}" -f (100.0 * ($cpuMs - $cpu0[$p.Id]) / ($Seconds * 1000.0) / [Environment]::ProcessorCount)
        }
        $start = ""; try { $start = "{0:MM-dd HH:mm:ss}" -f $p.StartTime } catch {}
        $resp = ""; try { $resp = $p.Responding } catch {}
        $title = ""; try { $title = $p.MainWindowTitle } catch {}
        W ("{0,-7} {1,-24} {2,-19} {3,-5} {4,9} {5,9:N1} {6,8:N0} {7,7}  {8}" -f $p.Id, $p.ProcessName, $start, $resp, $pct,
           ($(if ($null -ne $cpuMs) { $cpuMs / 1000.0 } else { 0 })), ($p.WorkingSet64 / 1MB), $p.Threads.Count, $title)
        if ($IsWindows -or $env:OS -eq "Windows_NT") {
            try {
                $waits = $p.Threads | Group-Object { if ("$($_.ThreadState)" -eq "Wait") { "Wait:" + $_.WaitReason } else { "$($_.ThreadState)" } } |
                    Sort-Object Count -Descending | ForEach-Object { "{0}x{1}" -f $_.Count, $_.Name }
                W ("        threads: " + ($waits -join ", "))
            } catch { W "        threads: (not readable: $($_.Exception.Message))" }
        }
    }
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        W ""; W "Sockets (TCP state / UDP local ports) per process:"
        foreach ($p in $procs) {
            $tcp = @(Get-NetTCPConnection -OwningProcess $p.Id -ErrorAction SilentlyContinue)
            $udp = @(Get-NetUDPEndpoint -OwningProcess $p.Id -ErrorAction SilentlyContinue)
            $t = $tcp | Group-Object { "{0}->{1}:{2}" -f $_.State, $_.RemoteAddress, $_.RemotePort } | ForEach-Object { "{0}x {1}" -f $_.Count, $_.Name }
            W ("  {0} ({1}): TCP [{2}]  UDP ports [{3}]" -f $p.ProcessName, $p.Id, ($t -join "; "), (($udp | ForEach-Object { $_.LocalPort } | Sort-Object -Unique) -join ","))
        }
    } else { W ""; W "Sockets: Get-NetTCPConnection not available on this system (skipped)." }

    foreach ($d in $ServerDir) {
        $log = Get-ChildItem -Path (Join-Path $d "Logs"), $d -Filter "log-*.txt" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        W ""
        if (-not $log) { W "Server log: none found under $d"; continue }
        W ("Server log {0} (last write {1:HH:mm:ss}), result/error lines, last {2}:" -f $log.FullName, $log.LastWriteTime, $Lines)
        $pat = 'responded|WATCHDOG|STUB|NETREPORT|Unhandled|Exception|fail|error|MATCH |SaveVsm|SaveBattleLog|SaveResultCapture|ResearchData|LoadCard|upload'
        Get-Content -LiteralPath $log.FullName -Tail 4000 -ErrorAction SilentlyContinue |
            Where-Object { $_ -match '^\d{4}-\d\d-\d\d ' -and $_ -match $pat -and $_ -notmatch 'Request is' } |
            Select-Object -Last $Lines | ForEach-Object { W ("  " + $_) }
    }
    foreach ($g in $GameDir) {
        W ""
        $recent = @(Get-ChildItem -Path $g -Recurse -Include *.log, *.txt -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-30) -and $_.Name -notmatch $SkipFiles -and $_.Length -lt 50MB } |
            Sort-Object LastWriteTime -Descending | Select-Object -First 5)
        W ("Game folder {0}: {1} log/txt file(s) changed in the last 30 min" -f $g, $recent.Count)
        foreach ($f in $recent) {
            W ("  -- {0} ({1:N0} bytes, {2:HH:mm:ss}), last 25 lines:" -f $f.FullName, $f.Length, $f.LastWriteTime)
            Get-Content -LiteralPath $f.FullName -Tail 25 -ErrorAction SilentlyContinue | ForEach-Object { W ("     " + $_) }
        }
    }
}

W "EXVS2 results-hang probe (read-only). Note what is on screen and how long the hang has lasted when you run it."
for ($i = 1; $i -le $Repeat; $i++) {
    Snapshot $i
    if ($i -lt $Repeat) { Start-Sleep -Seconds $Every }
}
$report | Set-Content -LiteralPath $Out -Encoding UTF8
Write-Host "Report written to $Out (card values masked). Share this file, not raw logs."
