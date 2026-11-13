# Universal matchmaking server for EXVS2 IB — design (2026-11-13)

Goal: one public server where every IB cabinet (no Live Monitor, no shared VPN for matching) queues
for online battles, replacing the per-store LM limit (16 terminal slots). Based on the static
analysis in `matchmaking.md`. Reference code: `server-sketch/` (Python prototype is runnable and
tested against simulated cabinets; C# is an uncompiled sketch in the Chiang-17 IB-Server style).

## 1. Components
```
 cabinet (vsac29_Release.exe)
   | exvs RPC (card server, existing)  -> RegisterPcb returns SRV_MATCH uri + SRV_STUN
   | HTTP POST protobuf (mms, rev 6)   -> MMS endpoint  /mms     (new)
   | UDP STUN (RFC 5389/5780)           -> coturn :3478          (new)
   | UDP P2P battle                     -> other cabinets directly (global or local addr from CheckMatching)
```

## 2. RegisterPcb (card server change)  [code: server-sketch/csharp/RegisterPcb.patch.md]
* `server_info{SRV_MATCH, uri="http://<public>:<port>/mms"}` — full URL; port field ignored by the game. **[C]**
* `server_info{SRV_STUN, uri="<stun ip>", port=3478, account_name, account_pass}` — presence of this
  entry is what starts STUN + IssueNodeId on the cabinet. **[C]** Use an IP literal (DNS untested).
* Each cabinet still needs a working card-server login (Mucha/AllNet auth); otherwise the game blanks
  the URLs. The community hook already provides this. **[C]/[M]**

For a shared server, everybody's RegisterPcb must point at the same MMS + STUN. Two options:
(a) everyone keeps their local card server and only edits the two RegisterPcb entries (simplest);
(b) a shared card server. (a) is enough for matchmaking.

## 3. MMS endpoint  [code: server-sketch/python/mms_server.py, csharp/Mms*.cs]
Framing: POST body = `nue.protocol.mms.Request`; reply **always HTTP 200**, body =
`Response{type, request_id (echo), code, <sub-message>}` with every proto2 *required* field set.
(RE 2026-11-13: the game checks HTTP 200, parse success and `code==SUCCESS` only; request_id/type are not
compared — echo them anyway. IssueNodeId must return ≥ the requested count. A missing sub-message is read as
all-zero, e.g. `poling_interval=0`, so always include it.)

| method | server behaviour |
|---|---|
| Ping (0) | code 0, `ping{}` |
| IssueNodeId (1) | allocate `issue_count` (game sends 2) ids from a persisted monotonic counter; never reuse |
| EntryMatching (2) | build a **Team** = myclient + groups[] (partner cabinet or `PCB00000NPC` CPU); queue; reply `poling_interval=3`, echo `apply_id` |
| CheckMatching (3) | unknown node → 103 ERR_MATCH_NOENTRY; waiting → code 0 + empty clients; matched → code 0, `room_id`, all clients of both teams (incl. requester, incl. CPU entries), `group_id` 0/1 = team; waited past `matching_timeout` → 1 MATCH_CANCELED |
| CancelMatching (4) | drop the team (reply ignored by the game) |
| MatchingSetting (100) | code 0 (never sent by the game) |

### 3.1 Queue / grouping key
`(world.mucha_game_id "GIB1", world.version, world.world_id, player attr1)`.
* `world_id` encodes the mode the player picked (client jump table, see matchmaking.md §2.2).
* `version` keeps different builds apart (avoids desyncs).
* attr1 = TestMode `wanMatchingGroupId` when the game sends it — usable as a lobby/region code. **[M]**

### 3.2 2v2 assembly
* One entry = one side. Solo player: groups[0] is the CPU stand-in with a real issued node id.
  Two cabinets as partners: the leader's groups[0] is the partner's client; if the partner also
  sends an entry with the same node set, the server merges it (no duplicate team). **[M]** (which
  cabinet sends the entry for a real pair is not verified).
* Pair the first two **compatible** teams FIFO: same key, no shared node ids, neither side's
  `bl_banapassport_am_ids` / `bl_loc_ids` hits the other.
* Room = team A clients (group 0) + team B clients (group 1) → ≤ 4 clients (game's team table holds 4).
* Optional later: rank/class bands from `myplayer.parameters` (attr2/attr3), region via `pref_code`,
  NAT-aware pairing (avoid symmetric↔symmetric).

### 3.3 Timeouts / cleanup
* `matching_timeout` from the request (90 s world 5, else 150 s) → MATCH_CANCELED on the next poll.
* Teams not polled for 20 s beyond their timeout are swept; matched rooms kept 60 s for late polls.
* Game-side: 10 s HTTP timeout, poll every `poling_interval` s, retry 1–3 s after errors.

## 4. STUN  [server-sketch/coturn/turnserver.conf]
* `stun-only` coturn on UDP 3478. Two public IPs enable RFC 5780 OTHER-ADDRESS → the game's NAT
  mapping test. With one IP the NAT result is "unknown" (the game reports 3/4) — RE 2026-11-13 shows this
  **does not block entry** (matchmaking.md §7.4); it only affects hole-punch odds. Never reject on NAT values,
  and accept out-of-enum values (4).
* Long-term credentials optional (game answers 401/438 with REALM/NONCE + MESSAGE-INTEGRITY).

## 5. Battle connectivity
The server only exchanges addresses. Cabinets then connect P2P (hole punching by `CAcSeqWanEntry`,
`Proc_WaitPartnerStun` / `Proc_WaitHolePunching`). Requirements: UDP not blocked; endpoint-independent
NAT or UPnP/port-forward works best. Fallback: keep a mesh VPN (Tailscale/ZeroTier/Radmin) **for
battle traffic only** and run STUN inside it — then global == local and the game uses local addresses.

## 6. Security / ops notes
* No auth or signing in the protocol: anyone can enqueue. Rate-limit per IP, cap queue size, log
  pcb_serial lengths not values. Do not log card identifiers.
* Plain HTTP (game would need a trusted CA for HTTPS).
* Single process, in-memory state is fine for hundreds of players; node-id counter must persist.

## 7. Test plan (box → home)
1. Box: `python3 fake_cabinet.py --cabinets 4` against `mms_server.py` — passes (2 rooms of 2v2 with CPU partners).
2. Home, 1 PC: point RegisterPcb at the prototype on localhost + local coturn; boot without LM;
   check server log for IssueNodeId(2) → EntryMatching (note `world_id`) → CheckMatching polls.
3. Home, 2 PCs (or friend): both enter the same mode → expect MATCH log + battle start (or capture
   where it fails: STUN, hole punch, NAT unknown).


## Addendum 2026-11-13 — what puts a cabinet on the WAN path
A cabinet uses MMS (this server) only when its active `testmode_pcb.json` setting entry has **`battleMode: 0`**
(matchmaking.md §7.2). Other battleMode values use the in-store LAN path (LM / ≤16 terminals). No exe patch is
needed; the home test is a config change. The WAN entry also carries a mode code per play mode (§7.3), so different
play modes are naturally put in different queues by the existing (game, version, world_id, attr1) key.
