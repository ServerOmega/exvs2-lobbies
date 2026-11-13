# Networking issues: Windows settings, NAT and VPNs (EXVS2 IB online matching)

> ⚠️ Nothing here was tested with the real game. Tags: **[C]** checked in `vsac29_Release.exe` (static
> disassembly, 2026-11-13) or in the EXVS2-POC hook source · **[M]** likely, from code reading but not every path
> traced · **[L]** inferred / unknown · **[W]** from a web source (linked).

How a match connects, in one paragraph: the card server's RegisterPcb gives the cabinet the MMS URL and a STUN
server. The cabinet runs STUN from its game UDP socket, sends **global ip:port (from STUN) + local ip:port (from its
adapter list) + NAT type** in EntryMatching, and gets the other 3 cabinets' addresses back from CheckMatching. Then
the cabinets hole-punch and play **UDP P2P**. Our server only relays addresses; every problem below is about the
addresses being wrong or UDP not getting through.

## 1. Top findings
1. **Use the POC/IB hook's `IpAddress=` (or `InterfaceName=`).** Without it, the game picks its "local" adapter with a
   quirky rule (§2.2): on a PC with ≥ 2 adapters it takes the **first adapter whose name contains neither "Loopback"
   nor the character "2"**. "Ethernet 2", "Wi-Fi 2" and "ZeroTier One [8056c2e21c…]" are skipped, a Hyper-V/WSL
   `vEthernet (…)` adapter may be taken instead of the real NIC, and connected state is not checked. With the
   hook, the game sees exactly one adapter with the chosen IP, and every bind goes to that IP **[C]**.
2. **Windows Firewall is the most common blocker.** The exe adds no firewall rules (no firewall APIs imported) **[C]**.
   Windows asks on first use, and pressing **Cancel creates permanent block rules** that win over allow rules and
   stop the prompt from appearing again **[W]**. VPN adapters (ZeroTier on Win 11, KM-TEST loopback) come up as
   **Public**, where the "Private only" allow doesn't apply **[W]**.
3. **Fixed ports, no UPnP.** The game binds UDP `0.0.0.0:48000` (+ terminal offset) and `:49000` **[C]** and has no
   UPnP/NAT-PMP code (no strings or imports) **[C]**. So it relies on hole punching. Two players behind
   **symmetric / CGNAT** NAT will usually fail; manual port forwarding of UDP 48000 (+offset) is the fix where possible.
4. **The best supported setup is an overlay where everybody is "on one LAN":** Radmin VPN / Tailscale / ZeroTier,
   every cabinet's hook bound to its overlay IP, and the **STUN server reachable on the overlay**, i.e. bound to the
   server's overlay IP. Then STUN's mapped address equals the local address. The game then marks itself "no NAT"
   (filtering 0) **[C]** and peers dial overlay IPs directly. No port forwarding needed.
5. **Commercial VPNs (NordVPN etc.) are a bad idea for this:** STUN sees the VPN exit IP, inbound UDP is not
   forwarded (Nord: no port forwarding on normal servers) **[W]**, and the exit NAT is often symmetric **[L]**.

## 2. What the exe does (verified)
### 2.1 Sockets [C]
* Game UDP socket (0x140304dd0): `socket(AF_INET, SOCK_DGRAM)`, `bind(INADDR_ANY, port)`, non-blocking (FIONBIO),
  `SO_BROADCAST`, `SO_SNDBUF` 64 KB, `SO_RCVBUF` 128 KB, `SIO_UDP_CONNRESET = FALSE` (ICMP "port unreachable" from
  a peer that isn't up yet doesn't kill the socket), then WSAEventSelect. No SO_REUSEADDR (multi-instance.md).
* A twin at 0x1403052a0 creates an **AF_INET6** socket. An IPv6 path exists, selected by the TestMode `ipMode`
  debug value (0x1406c3700 → address family) **[M]**. Default is believed IPv4 **[L]**. The POC bind hook rewrites only
  IPv4 binds and passes IPv6 through unchanged **[C POC]**. **Keep everything IPv4.**
* No QoS/DSCP (`qwave` not imported; no IP_TOS setsockopt seen) **[C imports]**, no MTU handling. The payload size of
  battle packets is unknown **[L]**.
### 2.2 Local address = adapter enumeration [C]
`0x1402df9d0` (called from 16 places incl. STUN 0x1407b8b1a): `GetAdaptersAddresses(AF_INET or AF_INET6, flags
0x16 = skip anycast/multicast/DNS)`.
* 1 adapter → use its unicast addresses.
* ≥ 2 adapters → walk the list; **skip any adapter whose FriendlyName contains "Loopback" or "2"** (plain `strstr`)
  and take the **first remaining adapter**, with no OperStatus/gateway/metric check. IPv6 entries are flagged when
  they contain "fe80".
* An older helper (0x1402df8a0, GetAdaptersInfo) does the same with the adapter **Description** containing "2".
* Order is whatever Windows enumerates (not the route metric) **[W general/L]**. A disconnected or virtual adapter
  that sorts first can become the "local" IP.
The POC hook replaces both APIs with a fake single adapter (the selected IP/mask/gateway, name, MAC) and rewrites
every IPv4 `bind` to that IP **[C POC SocketHooks.cpp]**. Note that `InterfaceName=` is an **exact** match in current
code (the prefix match is commented out), even though `config.ini` says it matches prefixes. Use the full name or `IpAddress=`.
### 2.3 STUN / NAT type [C]
After a Binding response (0x1407b8af0): if XOR-MAPPED ip == local ip **and** mapped port == bound port → filtering
= 0 ("open"). Otherwise it needs RFC 5780 OTHER-ADDRESS for the full test. Without it: filtering = 4, mapping = 0. The NAT
result never blocks entry (matchmaking.md §7.4).
### 2.4 Which peer address is dialled [C]
0x140794590: if the peer's global IP string equals mine → dial the peer's **local** ip:port, else its global
ip:port. Consequences:
* Two players behind one router reach each other on the LAN; **no hairpin NAT is needed**, provided the local IPs
  are right (finding 1).
* On an overlay with STUN inside it, global == local overlay IP for everyone and all dialling is direct.
* Mixed setups break: e.g. A's STUN goes over the internet and B's over the overlay. Their globals then differ in kind, and
  A dials B's internet address.
* With a bound overlay IP, Windows' strong host model sends only via routes on that interface **[W]**. So an
  **internet STUN server is unreachable from an overlay-bound socket** unless the VPN routes it. Put STUN on the overlay.

## 3. Troubleshooting checklist (in priority order)
1. **Which IP does the game use?** Set `IpAddress=` in config.ini (hook) and check the hook log lines
   `Selected interface … Address` and `bind(...) -> <ip>:48000`. Without the hook, run `Get-NetAdapter`. Any adapter
   name with "2"/"Loopback" is skipped, the first remaining one is used. Rename the adapters or disable the extra
   ones (vEthernet/WSL/Hyper-V, VirtualBox, old VPNs).
2. **Firewall.** `wf.msc` → Inbound Rules → delete any **Block** rules for `vsac29_Release.exe` (left by a cancelled
   prompt). Add an allow rule for the exe (UDP, all profiles), or at least UDP 48000–48020 and 49000–49020.
   For example (elevated PowerShell): `New-NetFirewallRule -DisplayName "EXVS2 IB" -Direction Inbound -Program "<path>\vsac29_Release.exe" -Action Allow -Profile Any`.
   Rules are tied to the full exe path, so moving the game folder needs a new rule **[W]**.
3. **Network profile.** `Get-NetConnectionProfile`. Set the game/overlay adapter to Private:
   `Set-NetConnectionProfile -InterfaceAlias "<name>" -NetworkCategory Private` **[W]**.
4. **Third-party AV/firewalls** (Norton, Kaspersky, Bitdefender, ESET, Comodo…) have their own rules and "trusted
   network" lists. Mark the VPN adapter as trusted and allow the exe **[W Radmin help]**. To test, disable them briefly.
5. **Same STUN for everybody, reachable from the bound IP.** In the server log (`NET entry ... global=`, §6), the
   global IP should be either every player's real public IP (internet STUN) or every player's overlay IP (overlay
   STUN), never a mix. A `NET-WARN ... != request source` line for a player points here.
6. **NAT type.** If two players fail to connect but each can play others, at least one is behind symmetric NAT /
   CGNAT. Check: WAN IP on the router ≠ public IP (whatismyip) → double NAT or CGNAT. A WAN IP in 100.64.0.0/10 →
   CGNAT. Fixes: forward UDP 48000(+offset) to a static LAN IP, ask the ISP for a public IP, or use an overlay.
   Two symmetric players can only connect over a relay (an overlay with relays, such as Tailscale DERP).
7. **MTU.** If matching works but the battle never starts, or desyncs under load: Tailscale MTU 1280 **[W]**, ZeroTier
   defaults to 2800 and Windows may keep 2800 even after the network MTU is lowered **[W]**. Test with
   `ping -f -l 1372 <peer>` and set `netsh interface ipv4 set subinterface "<adapter>" mtu=1280 store=persistent`.
8. **Latency/jitter.** Prefer wired Ethernet. Disable NIC "Energy Efficient Ethernet"/"Green Ethernet" and Wi-Fi power
   saving ("Allow the computer to turn off this device to save power"), and set Windows power plan to High
   performance **[L general practice]**. Relayed overlay paths (Tailscale DERP, ZeroTier relay, Radmin relay) add
   tens of ms. Check that peers are direct (`tailscale status` shows `direct`, `zerotier-cli peers` shows `DIRECT`).
9. **Adapter metric (Radmin).** Radmin sets its adapter metric to 1 on every boot, which can steal LAN traffic **[W]**.
   It doesn't matter when the hook binds an explicit IP, but it can break other LAN games or the card server path.
10. **IPv6.** Leave `ipMode` at its default (IPv4). Don't advertise IPv6 STUN. The hook doesn't rebind IPv6.

## 4. VPN / overlay comparison
| | Virtual IP | STUN sees | NAT traversal / relay | MTU | Notes |
|---|---|---|---|---|---|
| **Radmin VPN** | 26.x.x.x | overlay IP if STUN is on the overlay | P2P with relay fallback **[L]** | undocumented, test 1200–1500 **[W]** | what the community uses for LM play today; metric reset on boot **[W]**; mark adapter Private |
| **Tailscale** | 100.64.0.0/10 | overlay IP (STUN on a tailnet node) | direct UDP, DERP relay if both are hard NAT **[W]** | 1280 **[W]** | best NAT traversal; ISPs using CGNAT 100.64/10 can conflict **[W]**; adapter name "Tailscale" (no "2") |
| **ZeroTier** | user-chosen | overlay IP | P2P, relays via roots | default 2800, Windows may ignore lower values **[W]** | Win 11 forces Public profile **[W]**; adapter name "ZeroTier One [<netid>]" usually contains "2", so **hook required** |
| **Hamachi** | 25.x.x.x | overlay IP | relay common on free tier **[L]** | lower to 1280–1300 if fragmenting **[W]** | legacy; set Private + top priority **[W]** |
| **WireGuard (self-hosted hub)** | your subnet | overlay IP | hub-and-spoke unless peers can reach each other **[L]** | 1420 default **[L]** | all traffic via the hub adds latency; fine for a small group near the hub |
| **N2N/EasyN2N** | your subnet | overlay IP | supernode relay or P2P | — | used by the Chinese community for LM play; ForceBindIP style **[W]** |
| **NordVPN etc.** | exit IP | VPN exit IP | no inbound/port forwarding on normal servers **[W]** | provider MTU | not recommended; Nord Meshnet has been shut down **[W]** |

## 5. Recommended setups
* **A. Small friends group (recommended):** one overlay (Tailscale preferred for NAT traversal, Radmin if already
  in use). The server PC runs the card server + MMS + **coturn bound to its overlay IP** (`StunHost=<server overlay IP>`).
  Every cabinet: `IpAddress=<own overlay IP>`, `Server=<server overlay IP>`, overlay adapter set to Private, firewall
  allow for the exe. Expect STUN filtering 0 and direct dialling. Check `direct` peers.
* **B. Public internet (larger community):** public card/MMS server + public STUN with **two IPs** (RFC 5780, so the
  game gets real NAT types). Players need a correct local IP (hook) and a firewall allow. Players with symmetric/CGNAT
  NAT need UDP port forwarding or must fall back to setup A. Pair-ups of two hard-NAT players will fail with no relay.
* **Don't mix A and B in one queue:** a cabinet with an overlay global IP and one with an internet global IP can't
  reach each other's advertised addresses.
* **Same house, two PCs:** works on either setup without hairpin (same global → local dial), as long as both local
  IPs are right.

## 6. Reading the network log
Both servers (patched C# card server and `mms_server.py`) log each player's addresses and NAT type, **implemented
2026-11-13**. Card data (ChipId / AccessCode / BootToken) and `pcb_serial` are never logged. There is one line per
register, entry, match or drop, not one per poll. Per-poll lines are opt-in: C# `"VerboseLog": true`, Python `-v`.
C# writes to `server.log` / the console. Python writes to stderr.

Sample lines (box smoke test, fake cabinets, fake/documentation IPs):
```
NET register-pcb src=172.30.0.2 -> match=http://172.30.0.2:28080/match stun=172.30.0.2:3478
NET-WARN register-pcb src=172.30.0.2: a remote cabinet was given a loopback match/STUN address (http://127.0.0.1:28080/match, 172.30.0.2) - set MatchUrl/StunHost to an address it can reach
NET entry node=3238 src=172.30.0.2 local=192.168.1.10:40000 global=172.30.0.2:40000 nat=1/1 class=nat
NET entry node=3236 src=172.30.0.2 local=10.8.0.2:40000 global=203.0.113.7:40000 nat=1/2 class=nat MISMATCH
NET-WARN node=3236 STUN global 203.0.113.7 != request source 172.30.0.2: STUN and this server were reached by different paths (wrong adapter bound, VPN vs internet, or a proxy) - peers may not reach this cabinet
NET entry node=3240 src=172.30.0.2 local=198.51.100.9:40000 global=198.51.100.9:40000 nat=0/0 class=no-nat MISMATCH
MATCH-NET room=1 | g0 node=3236 ... ; g1 node=3238 ... | pairs: 3242<->3238 local same-NAT (192.168.1.10:40000 / 192.168.1.11:40000) ; 3236<->3240 global (198.51.100.9:40000 / 203.0.113.7:40000) ; ...
drop nodes=[1000] reason=stopped polling (stale)
```
| Field | Meaning |
|---|---|
| `src` | IP the HTTP request came from (TCP peer; proxy headers are not trusted) |
| `local` | ip:port the cabinet says its adapter has (§2.2). Wrong here = wrong adapter: use the hook's `IpAddress=` |
| `global` | ip:port STUN saw (§2.3). `0.0.0.0` / empty = STUN failed → `class=stun-missing` |
| `nat=m/f` | NAT mapping / filtering type the game computed. `0/0` = "no NAT" |
| `class` | `no-nat` (local = global: public IP or overlay STUN), `nat`, `stun-missing` |
| `MISMATCH` | STUN global IP ≠ `src`. Ignored when `src` is loopback (server and cabinet on one PC) |
| `MATCH-NET pairs` | for each pair, the address each side dials: `local same-NAT` when both global IPs are equal (exe rule §2.4), else `global` |
| `drop reason` | `matching timeout`, `cancelled by node N`, `stopped polling (stale)`, `replaced by re-entry`, `same cabinet entered again` |

How to read it:
* **MISMATCH is expected** when the server is not on the same network path as the players' STUN, e.g. a LAN or
  overlay card server with an internet STUN. It's a problem when *some* players match `src` and others don't: that's
  the mixed overlay/internet case (§5). Each (source, global) pair is warned about only once.
* **`class=stun-missing`**: STUN unreachable from the game socket (firewall, wrong `StunHost`, coturn down). Peers
  get no usable global address.
* **`local same-NAT` pair with a wrong `local`** (e.g. `172.x` Hyper-V or a `vEthernet` IP): those two players will
  dial an address that isn't theirs. Fix the bound adapter (§3 step 1).
* **Two players with the same global *and* same local**: two instances on one PC/IP. They will dial themselves.
* **`NET-WARN register-pcb ... loopback`**: `MatchUrl` / `StunHost` in `server.json` is `127.0.0.1`/`localhost`, but
  a remote cabinet registered. Set it to an address the cabinets can reach.
* **Matches form but battles never start**, with clean NET lines → UDP is blocked between the dialled addresses
  (firewall §3, symmetric NAT/CGNAT §3 step 6, or MTU).

### 6.1 Server-side mitigations still open
| Idea | Effort | Value |
|---|---|---|
| ~~Log per entry~~ / ~~warn on mismatch~~ | — | **done** (above) |
| ~~Keep overlay and internet players apart~~ | — | **done** 2026-11-13: network realms ([lm-and-online.md §3.2](lm-and-online.md#32-network-realms-who-can-reach-whom)), C# `NetworkRealms`, Python `--realms` |
| **Advertised-IP override** per pcb_serial (config) or "use HTTP source IP as global when STUN failed (0.0.0.0)" | small-medium | rescues broken STUN; risky if the source IP is a proxy |
| **NAT-aware pairing**: avoid symmetric↔symmetric (mapping/filtering values), fall back after a wait | medium | only useful with a 2-IP STUN |
| **Same-NAT detection**: same global IP → already handled by the client (local dial) **[C]**; the server could only warn when local IPs are equal | small | catches two instances on one IP |
| **TURN/relay fallback**: the client parses XOR-RELAYED-ADDRESS **[C]** and sends STUN creds from RegisterPcb, but whether it ever *uses* a relayed address for battle is not traced **[L]** | large / unknown | worth one RE session; otherwise an overlay with relays (Tailscale DERP) is the relay |

## 7. Sources
* Microsoft, Windows Firewall rules (Cancel → block rules, must be deleted): https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules
* Rebex, "Beware pressing Cancel on Windows Firewall Security Alert": https://blog.rebex.net/beware-pressing-cancel-on-windows-firewall-security-alert
* Microsoft, Strong and Weak Host Models: https://learn.microsoft.com/en-us/previous-versions/technet-magazine/cc137807(v=msdn.10)
* Tailscale connection types / hard NAT: https://tailscale.com/docs/reference/connection-types · NAT traversal blog: https://tailscale.com/blog/nat-traversal-improvements-pt-1 · MTU 1280: https://tailscale.com/docs/reference/troubleshooting/network-configuration/tcp-connection-two-devices · CGNAT conflicts: https://tailscale.com/docs/reference/troubleshooting/network-configuration/cgnat-conflicts
* ZeroTier Win 11 forced Public: https://github.com/zerotier/ZeroTierOne/issues/1671 · MTU 2800 not applied on Windows: https://github.com/zerotier/ZeroTierOne/issues/2294
* Radmin VPN help (firewall/trusted adapter): https://www.radmin-vpn.com/help/ · metric reset: https://github.com/fragtion/RadminVPNMetricDisablerPatch
* Hamachi adapter priority: https://lmi-documentation-origin.azurewebsites.net/webhelp/EN/CentralUserGuide/LogMeIn/t_hamachi_nw_change_adapter.html
* NordVPN port forwarding: https://support.nordvpn.com/hc/en-us/articles/19483392309649-Does-NordVPN-offer-port-forwarding · Meshnet shutdown: https://nordvpn.com/blog/meshnet-shutdown/
* Fightcade/Flycast Dojo (firewall first, then forward UDP 6000–6009, else Radmin/OpenVPN): https://dojo-project.gitbook.io/flycast-dojo/overview/frequently-asked-questions
* EXVS2-POC socket hooks: https://deepwiki.com/asesidaa/EXVS2-POC/2.8-network-and-socket-hooks · Stage1st single-PC EXVS2 with EasyN2N + IpAddress: https://stage1st.com/2b/thread-2149179-1-1.html · Bilibili Radmin setup guide: https://www.bilibili.com/opus/830121426320097280
* EXVS2-POC issue #135 (online match fails even with STUN): https://github.com/asesidaa/EXVS2-POC/issues/135
