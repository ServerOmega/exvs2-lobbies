# Matchmaking load test — 100 / 200 / 500 simulated cabinets (2026-11-13)

> ⚠️ **Fake cabinets only. Nothing here was tested with the real game.** The harness sends what static
> analysis says vsac29 sends (see `matchmaking.md`, `casual-shuffle-matching.md`, `ranked-matching.md`).
> Where the harness has to guess how the real cabinet behaves, the guess is listed in §5. Treat the
> numbers as a test of **our server logic and capacity**, not of the game.

Harness: [`server-sketch/loadtest/loadtest.py`](../server-sketch/loadtest/loadtest.py) (stdlib + `pbwire.py`; one
thread per cabinet, keep-alive HTTP). Targets:
* **C#** — patched EXVS2-IB-Server (`server-sketch/ib-server/online-matchmaking.patch`), Linux build, in-process
  matchmaker on `/match`. Every cabinet first sends **RegisterPcb** to the card server and uses the advertised
  `SRV_MATCH` URL (`--card-url`).
* **Python** — `server-sketch/python/mms_server.py` on `/mms`.
All ids are fake (`LTPCB…` serials, `LTLOC…` shops, am_ids 7000000+, IPs in 198.18.0.0/15). No card data.

## 1. What each simulated person does
| Item | Setting (defaults) |
|---|---|
| People | 100 / 200 / 500; 20 % are in **human pairs** (same shop); the leader sends a team entry with the partner as `"Y"` group, the partner cabinet issues its own node id and polls; half the partners also send their own entry |
| Modes (solo people) | Mix Match solo 23/S 30 %, Class Match solo 13/S 30 %, free 18/S 10 %, Mix + CPU partner 23/TN 10 %, Class team + CPU 14/TN 10 %, in-store 15/S 10 % |
| Modes (pairs) | Mix 23/T 50 %, Class team 14/T 40 %, free team 19/T 10 % |
| Ranked | classes 1–4 (weighted 2:3:2:1), levels 1–4; a pair sends max class / max level (attr2 / attr4) |
| Arrivals | 40 % burst in the first 3 s, rest trickle over 120 s; people requeue for 300 s |
| Behaviour | `matching_timeout` 150 s; poll at the server's `poling_interval` (3 s ±10 %); 6 % cancel at 3–60 s; 3 % silently vanish; after a match a 20–45 s "battle", then 80 % requeue (60 % after a timeout/cancel) |
| Misbehaving (5 %) | duplicate EntryMatching, CancelMatching after being matched, garbage bodies (random bytes, truncated, empty, entry without myclient, unknown node, unknown type, `issue_count` 100000), re-using old node ids |
| Attackers (`--hijack`) | enter with a node id currently owned by another waiting cabinet |
| Server settings | defaults: FillAfter 30 s, partial rooms on, SoftWait 15 s, StaleAfter 20 s |

Checks per run: rooms formed, time-to-match, unmatched sessions and why, a node or cabinet in two rooms, >4 `"Y"`
or >4 slots, side >2, teams/groups valid, pair split, CPU stand-in on its owner's side, worlds/classes/shops mixed,
short-room timing vs FillAfter, ghosts (a cabinet that had already left), all members seeing the same room,
HTTP status, latency, server CPU / RSS (from `/proc`).

## 2. Results
All runs on the box (8 vCPU). Times are seconds, CPU % is of one core.

| Run | Sessions | Matched | Rooms (4 / 3 / 2 humans) | Time to match p50 / p95 / max | Invariant violations | Server CPU p50 / p95 | RSS max |
|---|---|---|---|---|---|---|---|
| C# 100, **before fixes** | 324 | 298 | 117 (39 / 38 / 40) | 8.9 / 37.3 / 109.8 | **33** (see §3) | 1 % / 3 % | 283 MB |
| Python 100, **before fixes** | 323 | 299 | 117 (38 / 44 / 35) | 9.4 / 36.3 / 109.9 | **32** | 1 % / 1 % | 24 MB |
| C# 100, after | 290 | 262 | 104 (25 / 35 / 44) | 9.4 / 36.0 / 106.8 | 0 | 1 % / 3 % | 282 MB |
| Python 100, after | 275 | 250 | 96 (31 / 30 / 35) | 9.2 / 38.7 / 141.4 | 0 | 0 % / 1 % | 24 MB |
| C# 200 | 619 | 577 | 205 (78 / 58 / 69) | 5.7 / 33.0 / 126.6 | 0 | 2 % / 5 % | 285 MB |
| Python 200 | 435 | 366 | 125 (56 / 38 / 31) | 3.2 / 30.5 / 88.0 | 0 | 0 % / 2 % | 27 MB |
| **C# 500 (final)** | 1521 | 1429 | 485 (244 / 141 / 100) | **3.2 / 26.8 / 114.3** | **0** | 3 % / 8 % | 313 MB |
| **Python 500 (final)** | 1502 | 1406 | 480 (235 / 148 / 97) | **3.2 / 27.1 / 147.8** | 1 (harness-only, §4) | 2 % / 4 % | 36 MB |

Time to match by mode, 500-cabinet C# run (p50 / p95 s): Mix solo 3.1 / 6.2 · Mix pair 3.0 / 3.3 · Mix + CPU 3.0 / 5.8 ·
Class solo 9.1 / 30.0 · Class pair 3.2 / 18.0 · Class + CPU 4.4 / 27.1 · free solo 5.6 / 17.6 · in-store 30.1 / 66.9.
At 100 people Class solo was 19–25 s p50 (fewer people per class) and Mix solo ~6 s.

Other observations (all runs after the fixes):
* **No room ever had >4 `"Y"` or >4 slots**, no side had >2, no pair was split, every CPU stand-in sat with its owner,
  no class / world / shop mixing, every member saw the same client list.
* **Short rooms (1v1 / 2v1)** only formed after FillAfter: earliest 30.0 s, median 31 s (43 of 485 rooms at 500,
  50 of 205 at 200, 45 of 104 at 100 — the smaller the pool, the more short rooms).
* **Ranked level spread** inside a room at 500: 0 levels in 113 rooms, 1 in 88, 2 in 1 (band widening works; at 100
  people 1-level rooms dominate).
* **Unmatched**: almost all are in-store solo (`15/S`, 56 of 92 at 500): ~125 fake shops for 500 people, so few
  shop-mates — a harness assumption. Others: Class solo timeouts in thin class buckets, own cancels / vanishes.
  People who never got a single match: 8 of 500 (C#), 8 of 500 (Python).
* **Misbehaving clients**: duplicate entries merged (66 at 500); cancel-after-match kept the room; garbage
  never crashed either server; `issue_count` 100000 → capped at 16 ids; node-id hijacks rejected with
  `ERR_DUPLICATE_ENTRY` (4/4) and every victim still matched.
* **Latency** (500, C#): Check p50 ≈ 1 ms; the C# CPU peak (179 %) is the first second of the burst (JIT +
  450 RegisterPcb calls; RegisterPcb p99 ≈ 400 ms only then), then 30–60 % for a few seconds and ≤ 10 % after. Python after the Nagle fix: Entry p50 1.1 ms (was 43 ms).
  Request rate is only ~10–20 req/s at 500 people because cabinets poll every 3 s and spend most of the time
  "in battle": neither server is close to a limit at this size.
* **Ghosts left**: 1 room per run at most, always a cabinet that vanished < 20 s (StaleAfter) before the room
  formed, or a pair whose partner kept polling after the leader vanished. That cannot be told apart from a slow
  cabinet; P2P setup will fail for that room.

## 3. Bugs found and fixed (both servers, with unit tests)
| # | Bug (seen in the "before" runs) | Fix |
|---|---|---|
| 1 | **Cabinet in two rooms**: a repeated EntryMatching (same node, same apply_id) after the unit was matched queued a *second* unit; the cabinet was matched again (21 nodes in two rooms, 8 cabinets in two rooms < 10 s apart, per 100-person run) | repeat after match = no-op, next Check returns the same room |
| 2 | **Node-id takeover**: an entry with someone else's node id (ids are sequential) replaced or merged into that cabinet's wait — the 100-person run produced a room mixing world 14 and 23, a missing pair partner and an apply_id mismatch | node held by another `pcb_serial` → `ERR_DUPLICATE_ENTRY`; `node_id` 0 → `ERR_NODEID` |
| 3 | **Ghost matches**: a cabinet that stopped polling stayed matchable for matching_timeout + 20 s (≈170 s) | drop after `StaleAfterSeconds` (20 s, ≥ 3 × poll interval) without a poll |
| 4 | **Wrong end code for pairs**: when a pair timed out / was cancelled, the other cabinet got `ERR_MATCH_NOENTRY` instead of `MATCH_CANCELED` | dropped units leave a 120 s tombstone → `MATCH_CANCELED` |
| 5 | **One cabinet in two queues**: a cabinet that left without CancelMatching and re-entered (new node ids, other mode) could be matched in both (seen once at 500) | new entry from a `pcb_serial` drops its older waiting unit |
| 6 | **Wall-clock timers**: the box paused / its clock jumped (31–275 s) during runs; every waiting cabinet then timed out at once | matchmaker clock is monotonic (`Stopwatch` / `time.monotonic()`) |
| 7 | Python only: Entry / Cancel replies took **~43 ms** (headers + body in 2 writes → Nagle + delayed ACK) | `disable_nagle_algorithm = True` |

Tests: C# `Tests/Matchmaking.Tests` 18/18 (was 10), Python `test_casual.py` 17/17 (was 9). Windows (win-x64) build: 0 errors.
Patch regenerated (`git format-patch 7f4b280`, one commit) and checked with `git am` on a clean upstream clone.

## 4. Not fixed / known
* **Unauthenticated Check / Cancel**: anyone who knows (guesses) a node id can read or cancel that entry. The game
  sends nothing that could authenticate it except pcb_serial on Entry; a fix would need a server-side node→serial
  table from IssueNodeId plus a trust decision. Low risk for a friends server, real risk for a public one.
* **Malformed bodies → HTTP 500 on C#** (`ProtoException` in the model binder, logged as ERR). The Python server
  answers `ERR_REQUEST` with HTTP 200. The real cabinet never sends garbage, so left as is.
* **Re-entry that re-uses the same node id with a new apply_id** merges into the old wait (keeps the old mode).
  Only seen with the harness's "stale node id" misbehaviour (Python 500: 1 apply_id mismatch); the game is
  believed to call IssueNodeId for every attempt.
* **C# logs every MMS request** (`Request is …`, ~600 bytes) to console and file: ~10 GB/day at 200 req/s. Fine
  for testing; lower the level of `MatchController` for a public server.
* A matched room is kept 60 s; a cabinet that does not poll for 60 s after being matched gets `ERR_MATCH_NOENTRY`
  (13 sessions in the C# 500 run, all right after a 67 s box pause).

## 5. Harness assumptions (not server behaviour)
* Shapes of Entry/Check/Cancel, worlds, attrs and classes come from static analysis; the real cabinet may differ.
* Whether a fixed-pair partner cabinet sends its own entry is unknown → the harness does both (50/50).
* Real battles last ~3 min; the harness uses 20–45 s to get more requeues per minute.
* Shop count (people / 4) makes in-store matching rare; real shop sizes are unknown.
* The harness times are wall-clock; the box paused during several runs (logged as `harness_pauses_s` in the
  summary: e.g. 67 s at t = 330 s in both 500 runs, during the drain after the 300 s window). Two earlier 200-person
  runs hit a 275 s pause and were discarded (kept as `*_paused` locally, not used above).
* Room formation time is approximated by the first member to see the room (≤ one poll interval late).

## 6. Reproduce
```bash
# C# (patched EXVS2-IB-Server, Linux build, see server-sketch/ib-server/README.md)
CardServerConfig__OnlineMatching__Enabled=true dotnet Server-Infinite.dll &
python -m grpc_tools.protoc -I analysis/proto/from_exe --python_out=/tmp/pbgen game_server_nue.proto   # for RegisterPcb
PYTHONPATH=/tmp/pbgen python3 server-sketch/loadtest/loadtest.py --url http://127.0.0.1:28080/match \
    --card-url http://127.0.0.1:28080/ --people 500 --hijack 4 --pid $(pgrep -f Server-Infinite.dll) --out cs500.json
# Python sketch
python3 server-sketch/python/mms_server.py --port 5000 &
python3 server-sketch/loadtest/loadtest.py --url http://127.0.0.1:5000/mms --people 500 --pid $(pgrep -f mms_server.py)
# re-analyse a saved run
python3 server-sketch/loadtest/loadtest.py --analyze cs500.json
```
A run takes ~8 min (300 s of queueing + drain). It writes `<out>.json` (raw events, contains only fake ids) and
`<out>.summary.json`.
