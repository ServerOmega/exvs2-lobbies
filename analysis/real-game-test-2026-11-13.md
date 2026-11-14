# First real-game test — 2026-11-13 (times PT)

Two Infinite Boost cabinets (POC client + SnowLauncher, each with its own LM) on **one Windows 11 PC**, playing
through the patched card server ([`server-sketch/ib-server`](../server-sketch/ib-server/README.md)) with its
in-process matchmaker and built-in STUN. This is the first time the online (WAN) path ran in the real game.

## 1. Summary

| Item | Result |
|---|---|
| `battleMode: 0` in `testmode_pcb.json` switches the cabinet to online matching | ✅ confirmed |
| RegisterPcb → SRV_MATCH (full URL) + SRV_STUN; IssueNodeId; STUN NAT test | ✅ |
| Built-in STUN (`BuiltinStun: true`) instead of coturn | ✅ after the bind fix (§3) |
| Split setup: cabinet's card server ≠ matchmaker (`MatchUrl` → main server `/match`) | ✅ cab1 used a second card-server instance, cab2 the main one; they matched |
| Two cabinets match and play a full match | ✅ Mix Match (world 23) and Class Match solo (world 13) |
| Per-mode queues | ✅ cabinets in different modes don't meet |
| In-game cancel while searching (CancelMatching) | ✅ |
| Short-handed 1v1 room after `FillAfterSeconds` | ✅ (game adds the CPU partner locally) |
| Results saved | ✅ each cabinet's own card server got `SaveVsmOnResult` (HTTP 200): class-match rate, badge |
| Badge exp after a loss | ❌→✅ went 0 → −20; now clamped at 0 |
| Results screen after a 2-cabinet **versus** match | ❌ hangs for minutes (§4) — **not caused by the server** |

## 2. Matching speed
`FillAfterSeconds: 30` (old default) felt slow with only two players. `3` works fine on a LAN test. The repo
default is now **15**; 10–15 is the recommendation for a public server (gives a 4th/3rd player a chance to join
before a short-handed room forms).

## 3. STUN on a multi-homed Windows PC (fixed)
The built-in STUN socket was bound to `0.0.0.0`. Windows sent its replies from the **other** adapter's address
(the N2N overlay IP) instead of `StunHost`, and the game silently dropped every reply whose source was not the
STUN server it asked → NAT test failed / no global address. Fix: the primary STUN socket is bound to `StunHost`
when that IP belongs to the machine (falls back to `0.0.0.0` otherwise). Applies to any server PC with several
adapters (VPN, Radmin, Hyper-V switch, N2N...).

## 4. Results-screen hang (open)
After **every** versus match between the two cabinets, both stay on the results screen for several minutes, then
recover by themselves.

What was ruled out:
* **Server / network:** packet captures (Npcap loopback + adapters, `dumpcap`) show every request answered and
  the two cabinets still exchanging packets in sync after the results; both card servers answered
  `SaveVsmOnResult` with 200. Nothing is waiting on the server.
* **Holding Start** (~3 s) on the results screen: no effect (an earlier recovery that coincided with a Start hold
  was the timeout).
* **Unowned empty seats:** the server-side `CpuStandInSeats` option (each empty seat listed as a CPU client owned
  by a cabinet, same shape as the game's own CPU partner entry) reached both cabinets — still hangs. Kept as an
  opt-in experiment, **off by default**.
* **Matchmaker at all:** the same hang happens in **local LM mode with no matchmaking server**, both with two LMs
  and with one shared LM serving both cabinets.

What does not hang: a **solo** route battle vs CPU on one cabinet.

Conclusion: it only appears when two game instances fight each other **on the same PC**, whatever the
LM/matchmaking setup → most likely the two instances interfering (shared OS network stack, shared input, timers).
Pending:
1. Windows Sandbox test — cab2 inside Windows Sandbox (own network stack, GPU shared), cab1 on the desktop, matched
   through the server. Setup files (`cab2.wsb`, `setup-cab2.ps1`, `start-cab2.bat`) are on the test PC under
   `_re/sandbox`; sanitized templates will be added to this repo once the test has run.
2. Real two-PC (or two-player over the internet) match.

## 5. Recipe: two cabinets on one PC
What it took to get two cabinets + two LMs running side by side (see also [multi-instance.md](multi-instance.md)):
* **Separate IP per cabinet and per LM.** cab1 + LM1 on the Ethernet adapter (main IP + a secondary IP), cab2 + LM2
  on a second adapter (an N2N TAP adapter on its own subnet worked). An LM only finds cabinets on its own subnet;
  for the one-shared-LM test, cab1 got a second address on the N2N subnet (admin needed to add an IP).
* **Weak host model** on both adapters (`netsh interface ipv4 set interface "<name>" weakhostsend=enabled
  weakhostreceive=enabled`) so traffic between the two local subnets is delivered.
* **Firewall:** each copied game/LM folder has its own exe path; allow-list every copy (TinyWall in this setup;
  check wf.msc for Block rules on the copies).
* **Separate card servers / ports** per cabinet (or one server for both); the split setup used a second server
  instance on another port with `MatchUrl` pointing at the main server.
* **SnowLauncher** ignores its `Server=` key (the client always talks to `127.0.0.1:28080`), and once **wiped the
  `AccessCode`** in its ini — keep a backup of each cabinet's launcher/card config.
* **Keys:** LM — arrows move, `Z` = A (select in the LM test menu), `X/C/V` = B/C/D, `Q` Start, `P` card, `5` coin,
  `F3` Test, `F4` Kill (**closes everything**). Client — `W/A/S/D`, `J/I/K/L`, `Return` Start, `4` card, `5` coin,
  `F3` Test, `F2` Service, `F4` Kill. With the POC keyboard hook, **one keyboard drives both game windows** at once;
  start the games from the user's own session (started from another session, the hook gets no keys).
* **Captures:** `pktmon` cannot see loopback traffic. Install Wireshark with **Npcap loopback support** and use
  `dumpcap` (works without admin once Npcap is installed).
* Never use EXIT & SAVE in the test menu; edit `testmode_pcb.json` only on a backup, with `svd1.py`, while the game
  is closed (the game rewrites it while running).

## 6. Server builds used (on the test PC)
Single-file `win-x64` publish of the patched server (needs no .NET install). Sequence: v1 → v2 (RegisterCard
fallback) → v3 (built-in STUN, any-bind) → v4 (STUN bound to StunHost) → v5 (CPU stand-in seats, did not fix the
hang). Server changes from this test are commits 4–6 of `online-matchmaking.patch`.
