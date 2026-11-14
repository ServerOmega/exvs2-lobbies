# Adds inbound Windows Firewall rules for the EXVS2 matchmaking server. Needs admin (2-Configure.bat asks for it).
# Remove them later with:  Get-NetFirewallRule -DisplayName "EXVS2 Matchmaking*" | Remove-NetFirewallRule
param([int]$HttpPort = 28080, [int]$StunPort = 3478)
$ErrorActionPreference = "Stop"
Get-NetFirewallRule -DisplayName "EXVS2 Matchmaking*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "EXVS2 Matchmaking HTTP (TCP $HttpPort)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $HttpPort -Profile Any | Out-Null
New-NetFirewallRule -DisplayName "EXVS2 Matchmaking STUN (UDP $StunPort-$($StunPort + 1))" -Direction Inbound -Action Allow -Protocol UDP -LocalPort $StunPort, ($StunPort + 1) -Profile Any | Out-Null
Write-Host "Firewall rules added: TCP $HttpPort, UDP $StunPort-$($StunPort + 1)."
Start-Sleep -Seconds 2
