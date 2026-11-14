<#
  EXVS2 matchmaking server - configure (step 2).
  Writes server\Configurations\server.json (OnlineMatching / OnlineTag) and kestrel.json (listen port).
  Your old files are kept as *.bak. Run it again any time to change the settings.

  Non-interactive examples:
    configure.ps1 -Role Host -Ip 203.0.113.10                 (public / VPN / LAN IP of THIS server)
    configure.ps1 -Role Player -MatchServer 203.0.113.10       (use someone else's matchmaking server)
#>
param(
    [ValidateSet("", "Host", "Player")] [string]$Role = "",
    [string]$Ip = "",                 # Host: the address players use to reach this PC
    [string]$MatchServer = "",        # Player: the matchmaking server, "IP" or "IP:port" (port default 28080)
    [int]$HttpPort = 0,
    [int]$StunPort = 3478,
    [double]$FillAfterSeconds = 15,
    [switch]$NoFirewall,
    [switch]$NoPrompt
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Cfg = Join-Path (Join-Path $Root "server") "Configurations"
$ServerJson = Join-Path $Cfg "server.json"
$KestrelJson = Join-Path $Cfg "kestrel.json"
$OnWindows = ($env:OS -eq "Windows_NT")

function Fail($t) { Write-Host ""; Write-Host "ERROR: $t" -ForegroundColor Red; exit 1 }
function Ask($q, $default) {
    if ($NoPrompt) { return $default }
    $a = Read-Host "$q [$default]"
    if ([string]::IsNullOrWhiteSpace($a)) { return $default } else { return $a.Trim() }
}
function IsIPv4($s) {
    $ip = $null
    return ($s -match '^\d{1,3}(\.\d{1,3}){3}$') -and [Net.IPAddress]::TryParse($s, [ref]$ip)
}
function SetProp($obj, $name, $value) {
    if ($obj.PSObject.Properties[$name]) { $obj.$name = $value }
    else { $obj | Add-Member -NotePropertyName $name -NotePropertyValue $value }
}
function GetOrAdd($obj, $name) {
    if (-not $obj.PSObject.Properties[$name]) { $obj | Add-Member -NotePropertyName $name -NotePropertyValue ([pscustomobject]@{}) }
    return $obj.$name
}
function ReadJson($p) { return (Get-Content -Raw -Encoding UTF8 $p) | ConvertFrom-Json }
function WriteJson($p, $o) {
    $text = $o | ConvertTo-Json -Depth 32
    [IO.File]::WriteAllText($p, $text, (New-Object Text.UTF8Encoding($false)))
}

if (-not (Test-Path $ServerJson)) { Fail "server\Configurations\server.json not found. Run 1-Build-Server.bat first." }

Write-Host "EXVS2 matchmaking server - configure" -ForegroundColor Green
if (-not $Role) {
    Write-Host ""
    Write-Host "What do you want to do?"
    Write-Host "  1 = HOST a matchmaking server on this PC (other players connect to me)"
    Write-Host "      Also pick this for a LAN party or a server only you and friends on a VPN use."
    Write-Host "  2 = PLAY on someone else's matchmaking server (my cards stay on this PC)"
    Write-Host "      Pick this if you use SnowLauncher, or want to keep your own card server."
    $r = Ask "Type 1 or 2" "1"
    if ($r -eq "2") { $Role = "Player" } else { $Role = "Host" }
}

$s = ReadJson $ServerJson
$c = GetOrAdd $s "CardServerConfig"
$om = GetOrAdd $c "OnlineMatching"
$ot = GetOrAdd $c "OnlineTag"

if ($Role -eq "Host") {
    if (-not $Ip) {
        Write-Host ""
        Write-Host "Which address will the PLAYERS use to reach this PC?" -ForegroundColor Yellow
        Write-Host "  - Internet with port forwarding, or a rented server (VPS): your PUBLIC IP"
        Write-Host "  - VPN (Tailscale / ZeroTier / Radmin / N2N / Hamachi): this PC's VPN IP"
        Write-Host "  - Only PCs in your home: this PC's LAN IP (usually 192.168.x.x)"
        $list = @()
        if ($OnWindows) {
            try {
                $list = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
                    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
                    Sort-Object InterfaceMetric | Select-Object IPAddress, InterfaceAlias)
            } catch {}
        }
        $default = ""
        if ($OnWindows) {
            try {
                $route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction Stop | Sort-Object { $_.RouteMetric + $_.InterfaceMetric } | Select-Object -First 1
                $default = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex -ErrorAction Stop | Select-Object -First 1).IPAddress
            } catch {}
        }
        Write-Host ""
        Write-Host "This PC's addresses:"
        $i = 0
        foreach ($a in $list) { $i++; Write-Host ("  {0} = {1,-15} ({2})" -f $i, $a.IPAddress, $a.InterfaceAlias) }
        $pub = ""
        if (-not $NoPrompt) {
            $q = Read-Host "Look up your PUBLIC IP online (api.ipify.org)? [Y/n]"
            if ($q -notmatch '^[nN]') {
                try { $pub = (Invoke-RestMethod -Uri "https://api.ipify.org" -TimeoutSec 6).ToString().Trim() } catch {}
                if ($pub) { $i++; $list += [pscustomobject]@{ IPAddress = $pub; InterfaceAlias = "public IP - needs port forwarding" }
                            Write-Host ("  {0} = {1,-15} (public IP - needs port forwarding)" -f $i, $pub) }
                else { Write-Host "  (could not look it up - type it in yourself)" }
            }
        }
        while ($true) {
            $ans = Ask "Type a number from the list, or type the IP" $default
            if ($ans -match '^\d{1,2}$' -and [int]$ans -ge 1 -and [int]$ans -le $list.Count) { $ans = $list[[int]$ans - 1].IPAddress }
            if (IsIPv4 $ans) { $Ip = $ans; break }
            if ($NoPrompt) { Fail "No valid IP. Pass -Ip <address>." }
            Write-Host "  That is not an IPv4 address like 203.0.113.10 - try again." -ForegroundColor Yellow
        }
    }
    if (-not (IsIPv4 $Ip)) { Fail "'$Ip' is not an IPv4 address." }
    if ($Ip -like "127.*") { Write-Host "WARNING: 127.x.x.x only works for a game on this same PC." -ForegroundColor Yellow }
    if ($HttpPort -le 0) { $HttpPort = [int](Ask "Port for the card server + matchmaker (keep 28080 unless you know why)" "28080") }
    if (-not $NoPrompt) { $FillAfterSeconds = [double](Ask "Seconds to wait for 4 players before starting a 1v1/2v1" "$FillAfterSeconds") }

    SetProp $om "Enabled" $true
    SetProp $om "MatchUrl" ""            # "" = cabinets get http://<address they used>/match = this server
    SetProp $om "StunHost" $Ip
    SetProp $om "StunPort" $StunPort
    SetProp $om "BuiltinStun" $true
    SetProp $om "FillAfterSeconds" $FillAfterSeconds
    SetProp $om "AllowPartialRooms" $true
    SetProp $om "CpuStandInSeats" $false
} else {
    if (-not $MatchServer) {
        Write-Host ""
        Write-Host "Type the matchmaking server's address that its host gave you." -ForegroundColor Yellow
        Write-Host "Example: 203.0.113.10   or   100.101.102.103 (VPN)   or   203.0.113.10:28080"
        while (-not $MatchServer) { $MatchServer = (Read-Host "Matchmaking server").Trim() }
    }
    $MatchServer = $MatchServer -replace '^https?://', '' -replace '/.*$', ''
    $parts = $MatchServer.Split(':')
    $mHost = $parts[0]
    $mPort = 28080
    if ($parts.Count -gt 1) { $mPort = [int]$parts[1] }
    if (-not (IsIPv4 $mHost)) { Fail "'$mHost' is not an IPv4 address (the STUN address must be an IP, not a name)." }
    if ($HttpPort -le 0) { $HttpPort = 28080 }   # the game always talks to its card server on 28080

    SetProp $om "Enabled" $true
    SetProp $om "MatchUrl" "http://${mHost}:$mPort/match"
    SetProp $om "StunHost" $mHost
    SetProp $om "StunPort" $StunPort
    SetProp $om "BuiltinStun" $false     # STUN runs on the matchmaking server
    SetProp $om "CpuStandInSeats" $false
}
foreach ($kv in @(@("SendTagTeams", $true), @("TagStatus", 0), @("MaxTeams", 20), @("OneTimeInviteCode", $true))) {
    if (-not $ot.PSObject.Properties[$kv[0]]) { SetProp $ot $kv[0] $kv[1] }
}

Copy-Item $ServerJson "$ServerJson.bak" -Force
Copy-Item $KestrelJson "$KestrelJson.bak" -Force
WriteJson $ServerJson $s
$k = ReadJson $KestrelJson
$ep = GetOrAdd (GetOrAdd (GetOrAdd $k "Kestrel") "Endpoints") "BaseServer"
SetProp $ep "Url" "http://0.0.0.0:$HttpPort"
WriteJson $KestrelJson $k

Write-Host ""
Write-Host "Saved. (Old settings kept as server.json.bak / kestrel.json.bak)" -ForegroundColor Green
if ($Role -eq "Host") {
    Write-Host "  Players reach this server at:   $Ip  (port $HttpPort)"
    Write-Host "  STUN (NAT test) runs here on:   UDP $StunPort and $($StunPort + 1)"
    Write-Host "  Ports to open / forward:        TCP $HttpPort, UDP $StunPort-$($StunPort + 1)   (see Public-Server.txt)"
    if ($HttpPort -ne 28080) { Write-Host "  NOTE: the game itself only talks to port 28080. Another port only works for players who use their own local card server (option 2)." -ForegroundColor Yellow }
} else {
    Write-Host "  This PC's card server:          port $HttpPort (your game connects here, Server = 127.0.0.1)"
    Write-Host "  Matchmaking + STUN:             $($om.MatchUrl)   STUN $mHost`:$StunPort"
}

if ($Role -eq "Host" -and $OnWindows -and -not $NoFirewall -and -not $NoPrompt) {
    Write-Host ""
    $q = Read-Host "Add Windows Firewall rules for these ports now? (asks for admin rights) [Y/n]"
    if ($q -notmatch '^[nN]') {
        $fw = Join-Path $PSScriptRoot "firewall.ps1"
        try {
            Start-Process powershell -Verb RunAs -Wait -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$fw`"", "-HttpPort", $HttpPort, "-StunPort", $StunPort)
            Write-Host "  Firewall rules added (named 'EXVS2 Matchmaking ...')."
        } catch { Write-Host "  Skipped (admin rights were not given). You can run scripts\firewall.ps1 as admin later." -ForegroundColor Yellow }
    }
}
Write-Host ""
Write-Host "Next: double-click 3-Start-Server.bat"
