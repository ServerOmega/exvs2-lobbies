# Disconnect / rejoin test — 150 simulated cabinets + 14 targeted probes (2026-11-13)

> ⚠️ **Fake cabinets only, nothing tested with the real game.** Ids are fake (`DCPCB…`, `DCLOC…`, am_ids 8000000+).
> What a real cabinet does after a drop is not known; the harness guesses are listed in §1 and kept apart from
> server behaviour.

Harness: `server-sketch/loadtest/disconnects.py`, run with `loadtest.py --scenario disconnects [--part probes|population]`.
Targets: patched EXVS2-IB-Server (C#, primary, RegisterPcb first via `--card-url`) and `mms_server.py` (Python).
All runs used for the numbers below had **no box pause** (heartbeat checks wall vs monotonic clock); one pair of
runs hit a 26 s pause and was discarded.

## 1. Harness assumptions vs known client behaviour
Known from the exe (matchmaking.md §2, plus a new read of CheckMatching at `0x1407ba45b`):
* `apply_id` is a counter (new on each entry); HTTP timeout 10 s; Check retried after 3 s (PROCESS_WAIT) or 1 s after errors.
* On a CheckMatching code ≠ 0 the client sets state 3 and maps **1 MATCH_CANCELED → status 4, 103 NOENTRY → 5,
  2 PROCESS_WAIT → 6, other → 8**. So it does tell "cancelled" from "no entry"; what it does next with each is
  unknown. The fixes below therefore aim for MATCH_CANCELED whenever the server ended the wait.

Assumed (not verified): after an error or drop the cabinet runs IssueNodeId + EntryMatching again (sometimes keeping
its node id with a new apply_id); it re-registers (RegisterPcb) after a long gap; a dropped request is retried after
1 s and a lost response is retried with the same body; battles last 20–45 s; drop timings/probabilities are invented
(`DPROFILE`: 20 % drop while waiting, gaps 3–15 s / 25–50 s, 8 % drop right after match, 10 % mid-battle,
30 % of pairs lose a partner, 6 % lost responses, 3 % dropped requests, late cancels; mass drop of 30 % at 110 s for
30–40 s; server restart at 170 s). Queue mix: casual 23/18 plus ranked 13/14 in 4 classes so that real waits happen.

## 2. Targeted probes (14, each in its own bucket)
| Probe | Before (C# / Py) | After |
|---|---|---|
| Rejoin < StaleAfter, same node, other mode | **FAIL**: merged into old entry, matched in the old mode | PASS, rematch 3.0 s |
| Rejoin < StaleAfter, new node | PASS (old node → MATCH_CANCELED) | PASS, 3.0 s |
| Rejoin > StaleAfter, same node / new node + RegisterPcb | PASS (no ghost room, old node → 1) | PASS, 3.0 s |
| Drop right after match | PASS: room contains the dropped cabinet (server can't know), others requeue and rematch in one room, room not refilled | same, 3.0 s |
| Mid-battle drop, immediate requeue (same node+new apply / new node) | PASS, new room | PASS, 3.0 s |
| Pair: partner stops polling | **FAIL**: leader's polls kept the pair matchable → room with a ghost | PASS: dropped after 20 s, leader gets MATCH_CANCELED |
| Pair: leader stops polling | **FAIL** (same, ghost leader) | PASS |
| Pair partner rejoins solo, new node | PASS (leader → 1) | PASS |
| Pair partner rejoins solo, same node | **FAIL**: leader got 103 | PASS: leader gets MATCH_CANCELED |
| Late CancelMatching for the older apply_id | **FAIL**: cancelled the current entry (103) | PASS: current entry matches |
| Retried Entry/Check (lost responses) | PASS: one unit, one room | PASS |
| Re-registration: 40 cabinets × 3 RegisterPcb+IssueNodeId in parallel | PASS: 240 unique ids, 0 collisions | PASS |
| Server restart with 3 waiting (state kept) | **FAIL**: polls after restart got 103 | PASS: MATCH_CANCELED; re-entry rematched in 3.1 s (C# restart 5.4 s, Py 1.3 s); new ids > old |

7/14 failed on both servers before, 14/14 pass on both after.

## 3. Population run: 150 people, 240 s, mass drop + restart (C# primary)
| | C# before | C# after | Py before | Py after |
|---|---|---|---|---|
| sessions / rooms | 1079 / 372 | 1072 / 368 | 1109 / 383 | 1109 / 383 |
| matched | 1018 | 1015 | 1054 | 1054 |
| waits ended with **103 NOENTRY** | **26** | **0** | **22** | **0** |
| waits ended with MATCH_CANCELED | 1 | 26 | 3 | 26 |
| late cancel killed the current entry | 2 of 3 | 0 of 3 | 0 of 1 | 0 of 1 |
| double rooms (one entry in 2 rooms) | 0 | 0 | 0 | 0 |
| stuck (no answer within 155 s) | 0 | 0 | 0 | 0 |
| rooms with a member gone > StaleAfter | 0 | 0 | 0 | 0 |
| rooms with a member gone 0.7–9 s before (inherent) | 23 | 22 | 22 | 22 |
| short-handed rooms (fill timer) | 6 | 3 | 3 | 2 |
| entries that failed outright (restart window) | 4 | 4 | 0 | 0 |
| time to match p50 / p95 / max (s) | 3.1 / 14.6 / 32.3 | 3.1 / 13.7 / 31.1 | 3.1 / 13.3 / 31.2 | 3.1 / 13.2 / 31.0 |

Time to rematch after a rejoin (C# after; Python similar): after a drop right after the match p50 3.1 s / p95 9.0 s
(n 91); mid-battle p50 3.1 / p95 15.2 (n 89); after MATCH_CANCELED (mostly the restart) p50 3.1 / p95 7.3 / max 12.6
(n 22); mass-drop rejoin burst p50 3.5 / p95 8.0 (n 10, new node) and 3.1 / 5.6 (n 3, same node); drop-while-waiting
rejoins 2.9–3.8 s p50. The p95 tail is the ranked classes (thin queues), not the disconnects.
Transport errors seen by clients (~250 per run) are the harness's own simulated drops and lost responses plus
broken keep-alive sockets / refused connections around the restart. All were retried; only the 4 C# entries sent
during its ~5 s restart failed.

The population mostly re-confirms the probes. Pair-partner drops rarely outlived StaleAfter before the pair matched,
so the ghost-pair bug shows up only in the probes.

## 4. Bugs fixed (both servers, unit tests: C# 25, Python 24)
1. Same leader re-entering with a new apply_id was merged into its old entry (old mode kept) → it now replaces it.
2. Staleness was per unit: one cabinet of a pair polling kept a vanished partner/leader matchable (ghost) → now per cabinet.
3. Partner re-entering solo on the same node left the leader with 103 → it now gets MATCH_CANCELED (tombstone).
4. A late CancelMatching of the leader's older apply_id cancelled its current entry → it is now ignored. Partner
   cancels and apply_id 0 are still honoured.
5. After a restart, polls for node ids issued before it got 103 → they now get MATCH_CANCELED (allocator exposes the first id of this run).
6. A retried poll after the matching timeout (response lost) got 103 → it now gets MATCH_CANCELED again.

## 5. Not fixed / by design
* **Drop within ~1–9 s of a match (or before the first stale window)**: the room still includes the dropped
  cabinet. MMS has no message to tear down or refill a room; the remaining players have to notice in P2P and requeue
  (they rematch in ~3 s). This needs the real game to see what it does.
* **Ranked result when one side never reports**: C# `SaveVsmOnResult` stores results per card, so the side that
  reports is recorded and the other records nothing (no double count, no forfeit). Python `/result` counts once per
  room. No forfeit logic.
* A duplicated entry after a match with the **same** apply_id returns the same room (by design, protects against retries).
* CheckMatching/CancelMatching are still unauthenticated (see load-test.md §4).

## 6. Reproduce
```bash
cd server-sketch/loadtest
# probes (C#); restart script must keep the DB and mms_nodeids.json
PYTHONPATH=/tmp/pbgen python3 loadtest.py --scenario disconnects --part probes --url http://127.0.0.1:28080/match \
    --card-url http://127.0.0.1:28080/ --restart-cmd ./restart_keep_state.sh --out dc_probes.json
# population
PYTHONPATH=/tmp/pbgen python3 loadtest.py --scenario disconnects --part population --people 150 --duration 240 \
    --url http://127.0.0.1:28080/match --card-url http://127.0.0.1:28080/ --restart-cmd ./restart_keep_state.sh \
    --restart-at 170 --pid $(pgrep -f Server-Infinite.dll) --out dc_pop.json
# Python: --url http://127.0.0.1:5000/mms (no --card-url)
```
