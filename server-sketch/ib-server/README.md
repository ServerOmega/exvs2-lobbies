# Step 3 — card server with online matchmaking (EXVS2-IB-Server patch)

> ⚠️ **Experimental — not tested with the real game, not functioning yet.** Only tested on Linux with fake
> cabinets (`../python/fake_cabinet.py`) and the smoke test in this folder. You must already have a copy of the game.

This patches [Chiang-17/EXVS2-IB-Server](https://github.com/Chiang-17/EXVS2-IB-Server) (Infinite Boost card
server, v1.2.0, commit `7f4b280`) so that it:

* tells the cabinet where the **matchmaking server** (full URL) and a **STUN server** are (RegisterPcb),
* runs the **matchmaker in-process** on `/match` (alias `/mms`): unique node ids, EntryMatching / CheckMatching /
  CancelMatching, per-mode queues, solo shuffle, fixed pairs, CPU stand-ins, ranked class buckets with level widening,
* sends IB-style **LoadClassMatch** tables (hour-based schedule + unix fallback, grade→level patterns, search ratios),
* **stores ranked results** (rate, class, grade, class wins/losses from `SaveVsmOnResult`) and returns them in `PreLoadCard`,
* can be built and run **on Linux** (`-p:LinuxHost=true`) as well as Windows.

Upstream has **no license**, so it is not forked or redistributed here — only our changes, as a patch
(`online-matchmaking.patch`, a `git format-patch` of the local branch `online-matchmaking`).
Full change list and config reference: `ONLINE_MATCHMAKING.md` inside the patch.

## Build
Needs the .NET 9 SDK (`yay -S dotnet-sdk` on Arch; on Windows install .NET 9 SDK).
```bash
git clone https://github.com/Chiang-17/EXVS2-IB-Server && cd EXVS2-IB-Server
git checkout 7f4b280
git am /path/to/exvs2-matchmaking/server-sketch/ib-server/online-matchmaking.patch    # creates one commit

# Windows server (like upstream's release):
dotnet publish Server-Infinite -c Release -r win-x64
# or Linux server:
dotnet build Server-Infinite -c Release -p:LinuxHost=true -o out
# matchmaker unit tests (29 tests):
dotnet test Tests/Matchmaking.Tests
```
Copy your existing `ServerInfinite.db` next to the new build if you want to keep cards; the new migration
(`AddClassMatchGrade`) adds one column on first start. **Back the DB up first.**

## Configure
In `Configurations/server.json` under `CardServerConfig` → `OnlineMatching`:

| key | default | meaning |
|---|---|---|
| `Enabled` | `false` | `true` = send SRV_MATCH (full URL) + SRV_STUN in RegisterPcb |
| `MatchUrl` | `""` | `""` = built-in MMS `http://<host the cabinet used>/match`; or the external Python server, e.g. `http://203.0.113.10:5000/mms` |
| `StunHost` / `StunPort` | `""` / `3478` | coturn address; use an IP literal. `""` = same host as the card server |
| `StunUser` / `StunPass` | `""` | only if coturn requires long-term credentials |
| `PollingIntervalSeconds` | `3` | CheckMatching poll interval sent to the cabinet |
| `FillAfterSeconds` / `AllowPartialRooms` | `30` / `true` | allow a 1v1 / 2v1 room after this wait |
| `SoftAttributeWaitSeconds` | `15` | time win-rate bucket / veteran flag must match in free/mix modes |
| `StaleAfterSeconds` | `20` | drop a waiting cabinet that stopped polling (no ghost matches) |
| `NodeIdStateFile` / `FirstNodeId` | `mms_nodeids.json` / `1000` | node ids are never reused |
| `ClassMatchScheduleMode` | `Both` | `Both` / `Hours` / `UnixTime` (upstream) schedule rows in LoadClassMatch |
| `PersistClassMatchResult` | `true` | store ranked results from SaveVsmOnResult |
| `VerboseLog` | `false` | also log every CheckMatching poll (address/NAT lines are always logged once per entry / match) |

Environment variables work too and win over `server.json`: `CardServerConfig__OnlineMatching__Enabled=true`.

Network log lines (`NET ...`, `NET-WARN ...`, `MATCH-NET ...`, `drop ... reason=`) are explained in
[analysis/networking-issues.md §6](../../analysis/networking-issues.md#6-reading-the-network-log).

## Run the pieces
1. **STUN**: `turnserver -c ../coturn/turnserver.conf` (UDP 3478 open; set `external-ip`).
2. **Card server + MMS**: start the patched server (port 28080 by default, `Configurations/kestrel.json`).
   Open TCP 28080 for other players' cabinets (card + `/match` traffic share the port).
3. *(optional)* external matchmaker instead of the built-in one: `python3 ../python/mms_server.py --port 5000`
   and set `MatchUrl` to `http://<ip>:5000/mms`.
4. **Cabinet**: back up `testmode_pcb.json`, set `battleMode: 0` in the active entry (with `svd1.py`), point the
   game's card server address at the patched server, then queue for a match and watch the server log
   (`MMS IssueNodeId`, `entry …`, `MATCH room=…`).

P2P battles still need reachable UDP between cabinets (public IP / UPnP, or a shared VPN such as Radmin).

## Check it without the game
```bash
pip install protobuf grpcio-tools
python -m grpc_tools.protoc -I ../../analysis/proto/from_exe --python_out=. game_server_nue.proto
PYTHONPATH=../python python3 check_card_server.py --url http://127.0.0.1:28080/            # RegisterPcb, LoadClassMatch, 4-cabinet shuffle
PYTHONPATH=../python python3 check_card_server.py --url http://127.0.0.1:28080/ --ranked-save  # + fake test card ranked result round-trip (writes to the DB)
```
Box result 2026-11-13 (Linux build): RegisterPcb → `SRV_MATCH http://127.0.0.1:28080/match` + `SRV_STUN 127.0.0.1:3478`;
LoadClassMatch parses strictly with schedule hit by hour and by unix time; 2-cabinet team+CPU, 4-solo shuffle,
pair+2 solos, and 8-cabinet ranked (two classes → two separate rooms) all matched; ranked save round-trip
(class 1→2, grade 0→7, rate 1500→1512.5, class win +1) OK; 10/10 unit tests pass; Windows (win-x64) build: 0 errors.

Load test 2026-11-13 (`../loadtest/loadtest.py`, 100–500 fake cabinets): see `../../analysis/load-test.md`;
matchmaker bugs found and fixed in this patch: double room on a repeated entry, node-id takeover by another
cabinet, ghost matches of cabinets that stopped polling, partner got ERR_MATCH_NOENTRY instead of
MATCH_CANCELED, one cabinet waiting in two queues at once, wall-clock-based timers.

## Not done / risks
* Never run against the real cabinet; hole-punch / P2P format still unknown.
* Mode→world ids, class ids 1–4, and the hour-based schedule are inferred from static analysis.
* Matchmaker state is in memory (a restart drops waiting players); hidden MMR from the Python sketch is not ported
  (no reliable link between MMS am_id and card id yet) — ranked pairs by class + level only.
* The client is trusted for rate/grade (only NaN/out-of-range rates are rejected).
