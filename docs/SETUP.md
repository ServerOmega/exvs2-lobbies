# Setup guide: host a matchmaking server, connect a cabinet

> ⚠️ Experimental. Verified in the real game on 2026-11-13 with **two cabinets on one PC** only
> ([test report](../analysis/real-game-test-2026-11-13.md)). Matching between separate machines / over the internet
> is not yet tested. You must already have your own copy of the game; nothing here includes game files.

The matchmaking server is the **patched EXVS2-IB-Server** (card server + matchmaker + optional STUN in one exe),
built from [`server-sketch/ib-server/online-matchmaking.patch`](../server-sketch/ib-server/online-matchmaking.patch).
All config keys below are under `CardServerConfig` → `OnlineMatching` in `Configurations/server.json`
(full reference: [`server-sketch/ib-server/README.md`](../server-sketch/ib-server/README.md#configure)).

---

## Part A — Hosting the matchmaking server

### A1. Build
Needs the **.NET 9 SDK** and git (Windows or Linux can build the Windows exe).
```bash
git clone https://github.com/Chiang-17/EXVS2-IB-Server && cd EXVS2-IB-Server
git checkout 7f4b280
git am /path/to/exvs2-matchmaking/server-sketch/ib-server/online-matchmaking.patch

# Windows server: self-contained single-file exe (~220 MB), runs without any .NET installed
dotnet publish Server-Infinite -c Release -r win-x64 -o out-win
#   (building on Linux: add -p:EnableWindowsTargeting=true)

# or a Linux server (needs the .NET 9 runtime to run):
dotnet build Server-Infinite -c Release -p:LinuxHost=true -o out-linux

dotnet test Tests/Matchmaking.Tests      # optional: matchmaker unit tests
```
No pre-built download is published; build it yourself. If you already run an IB card server, copy its
`ServerInfinite.db` next to the new exe to keep your cards (**back it up first**; a migration adds one column).

### A2. Configure `Configurations/server.json` → `CardServerConfig.OnlineMatching`
Minimum for a matchmaker with built-in STUN:
```json
"OnlineMatching": {
  "Enabled": true,
  "MatchUrl": "",
  "StunHost": "203.0.113.10",
  "StunPort": 3478,
  "BuiltinStun": true,
  "FillAfterSeconds": 15,
  "AllowPartialRooms": true,
  "CpuStandInSeats": false
}
```
| Key | What to set |
|---|---|
| `Enabled` | `true`, otherwise RegisterPcb behaves like upstream (no online matching). |
| `MatchUrl` | `""` = cabinets are sent `http://<the address they used to reach this server>/match` (this server's built-in matchmaker). Set a full URL only to forward matchmaking elsewhere (split setup, A6). |
| `StunHost` | **This host's IP as the players reach it** (IP literal): your public IP for internet play, the overlay IP (Radmin/Tailscale/ZeroTier) for VPN play, the LAN IP on a LAN. Not `127.0.0.1` for remote players. When it is one of this PC's own addresses, the built-in STUN binds to it (needed on PCs with several adapters). |
| `StunPort` | `3478` (default). Built-in STUN also uses `StunPort + 1` (`BuiltinStunAltPort`, 0 = port+1). |
| `BuiltinStun` | `true` = STUN runs inside this server (no coturn). `false` = use an external STUN server at `StunHost:StunPort` (e.g. [coturn](../server-sketch/coturn/turnserver.conf)). |
| `FillAfterSeconds` | Seconds the oldest waiting player waits for a full 2v2 before a short-handed room (1v1 / 2v1, at least 2 humans) forms. Default 15; 3 is fine for a LAN test; 10–15 for a public server. |
| `AllowPartialRooms` | `true` = allow those short-handed rooms; `false` = only full 4-player rooms. |
| `CpuStandInSeats` | **Experimental**, leave `false`. Lists a CPU client for each empty seat; it did not fix the results-screen hang. |
| `PollingIntervalSeconds`, `StaleAfterSeconds`, `NetworkRealms`, `InStoreScope`, `ShopKeys`, `VerboseLog` | Optional; see the [config reference](../server-sketch/ib-server/README.md#configure). |

Any key can also be set with an environment variable, which wins over the file, e.g.
`CardServerConfig__OnlineMatching__FillAfterSeconds=10`.

The listen address/port is in `Configurations/kestrel.json` (`"Url": "http://0.0.0.0:28080"` by default).

### A3. Ports
| Where | Port | Why |
|---|---|---|
| Server | **TCP 28080** (or whatever `kestrel.json` says) | card server + matchmaker `/match` (HTTP) |
| Server | **UDP 3478 and 3479** (`StunPort`, `StunPort+1`) | built-in STUN (NAT test) — only with `BuiltinStun: true` |
| Each player's PC | **UDP 48000** (+ terminal offset) | the game's own P2P battle socket; the game has no UPnP, so behind a strict NAT forward it, or use an overlay VPN |
| LM stores only | UDP 49000 | LM broadcast, local network only — never forward it |

Forward the server ports on your router to the server PC if players come from the internet. With an overlay
VPN (Radmin / Tailscale / ZeroTier) no forwarding is needed; use the overlay IP as `StunHost`.
More: [analysis/networking-issues.md](../analysis/networking-issues.md).

### A4. Firewall
* **Windows Firewall:** the first start of `Server.exe` may show an "allow access" prompt — allow it on the profile
  the players come in on (Private/Public), or add inbound rules for TCP 28080 and UDP 3478–3479. Check `wf.msc` for
  leftover **Block** rules on the exe.
* **TinyWall** (or another allow-list firewall): add `Server.exe` (and on player PCs every copy of the game exe /
  launcher) to the allowed applications; each copied folder is a different exe path and needs its own entry.

### A5. Run it and read the log
Start `Server.exe` (Linux: `dotnet Server-Infinite.dll` in the output folder). Logs go to `Logs/log-<date>.txt`.
Lines to watch, in the order a match happens:
| Log line | Meaning |
|---|---|
| `STUN built-in server on UDP 3478 (+alt 3479)...` | built-in STUN is up (at start) |
| `NET register-pcb src=<ip> -> match=<url> stun=<host>:<port>` | a cabinet booted and was told where the matchmaker and STUN are. `NET-WARN register-pcb` = a remote cabinet got a loopback address → fix `StunHost` / `MatchUrl` |
| `MMS IssueNodeId x2 -> [..]` | the cabinet started online matching |
| `NET entry node=N ... global=<ip:port> ... class=<c>` | a player queued. `class=stun-missing` = STUN failed (firewall / wrong `StunHost`) |
| `entry <mode> nodes=[..] slots=.. queue=..` | the player is waiting in that mode's queue |
| `MATCH room=R <mode> S[..] vs S[..] (humans=x/4)` + `MATCH-NET room=R ...` | a room formed; MATCH-NET shows which address each pair will dial |
| `drop nodes=[..] reason=...` | a player left the queue (cancel, timeout, stopped polling) |
| `check node=N -> ...` | one line per poll; only with `VerboseLog: true` |
Details: [networking-issues.md §6](../analysis/networking-issues.md#6-reading-the-network-log).

### A6. Split setup: a separate card server forwards matchmaking
Players can keep their own card server (cards stay local) and only match on the shared server. On the
**player's** card server (the same patched build):
```json
"OnlineMatching": {
  "Enabled": true,
  "MatchUrl": "http://<matchmaker-ip>:28080/match",
  "StunHost": "<matchmaker-ip>",
  "StunPort": 3478,
  "BuiltinStun": false
}
```
The cabinet then registers on its own card server, but queues on (and gets STUN from) the shared matchmaker.
Results are still saved to the player's own card server. This was tested on 2026-11-13 (one cabinet on a second
card-server instance, one directly on the matchmaker; they matched and played).

---

## Part B — Players: connecting a cabinet to a matchmaking server

### B1. Requirements
* EXVS2 **Infinite Boost** with the POC client (the build this project analysed), working locally.
* A card server: either the matchmaker itself, or your own patched card server in the split setup (A6).
* UDP reachability to the other players (public IP / forwarded UDP 48000, or the same overlay VPN as everyone).

### B2. Switch the cabinet to online matching (`battleMode: 0`)
1. Close the game. **Back up `testmode_pcb.json`.**
2. In the **active** setting entry of `testmode_pcb.json`, set `battleMode` to `0` using a testmode editor
   (this project used its `svd1.py` tool on the test PC; it is not in this repo). Any other value keeps the
   LM / in-store path.
3. Never use **EXIT & SAVE** in the in-game test menu, and don't edit the file while the game runs (the game
   rewrites it).

### B3. Point the cabinet at the server
* **Card server = the matchmaker:** set your POC client's card-server address to the matchmaker host and port
  (28080). Nothing else is needed: RegisterPcb tells the cabinet the matchmaker URL and the STUN server.
* **SnowLauncher users:** SnowLauncher ignores its `Server=` key — the client always talks to `127.0.0.1:28080`.
  So run a **local** patched card server on port 28080 and use the split setup (A6): `MatchUrl` and `StunHost`
  point at the remote matchmaker. (SnowLauncher once wiped the `AccessCode` in its ini during testing — keep a
  backup of your launcher/card config.)

### B4. Queue
1. Start the game, insert your card, pick an online mode. **Everyone must pick the same mode** to meet
   (each mode is its own queue; e.g. Mix Match and Class Match solo never mix).
2. Wait. A full 2v2 forms as soon as 4 players are queued; with fewer, a 1v1 / 2v1 forms after
   `FillAfterSeconds` (default 15 s). In a 1v1 the game adds your CPU partner itself.
3. Cancelling in the game's search screen works and leaves the queue.
4. After the match, results (class-match rate, badge) are saved to **your own** card server.

### B5. Troubleshooting
| Symptom | Likely cause / fix |
|---|---|
| No `NET register-pcb` line for your cabinet | the cabinet isn't talking to this card server: check the address/port (SnowLauncher: local server on 28080), firewall |
| `register-pcb` but no `MMS IssueNodeId` / no `NET entry` | `battleMode` isn't 0 in the active entry, or `Enabled` is false on the card server the cabinet uses |
| Stuck searching; `NET entry ... class=stun-missing` or a `NET-WARN ... no STUN global address` | STUN not reachable: UDP 3478/3479 blocked or forwarded wrong, or `StunHost` isn't the host's reachable IP (on a multi-adapter host it must be one of its own IPs) |
| `entry ...` lines but never `MATCH` | players are in different modes, or in different network realms (e.g. one on Radmin, one on the internet — they can never reach each other), or only one player queued |
| `MATCH` but the battle never starts | P2P UDP between players is blocked: firewall on the game exe, strict/CGNAT NAT without UDP 48000 forwarded → use an overlay VPN |
| Results screen hangs for minutes after a versus match | **known issue with two cabinets on one PC** (also happens in local LM mode without any matchmaker); the games recover by themselves. Not seen with a solo match; separate-machine test pending ([report](../analysis/real-game-test-2026-11-13.md#4-results-screen-hang-open)) |

Running two cabinets on one PC for testing: see the recipe in
[real-game-test-2026-11-13.md §5](../analysis/real-game-test-2026-11-13.md#5-recipe-two-cabinets-on-one-pc).
