# Does the matchmaker talk to a cabinet's LM or card server after a match? (2026-11-14)

**Short answer: no.** Nothing in the design needs the matchmaking server (MMS) to talk to anyone after a room is made,
and no server-to-server link exists. Evidence below: **[S]** = our server source, **[C]** = exe code
(`binaries/vsac29_Release.exe`, static only, nothing run or patched), **[P]** = `captures/all.tsv`, **[I]** = inference.

## 1. Who talks to whom
| Link | When | Evidence |
|---|---|---|
| card server → MMS (MatchUrl) | **never** | `Server-Infinite` has no outbound HTTP/UDP client at all (no `HttpClient`, `WebRequest`, `UdpClient` sends except the STUN server's replies). `MatchUrl` is used in exactly one place: it is copied into the RegisterPcb reply (`SRV_MATCH` entry) at cabinet boot (`RegisterPcbCommandHandler.AddOnlineMatchingServers`). [S] |
| cabinet → MatchUrl (`/match`, HTTP protobuf `nue.protocol.mms`) | IssueNodeId at boot; Entry / Check / Cancel while searching; Ping every 60 s | the cabinet uses the SRV_MATCH uri verbatim (matchmaking.md §1.2) [C]. In the split setup cab1 therefore called `192.168.1.69:28090/match` itself; mm-server2 never relayed anything. |
| cabinet → STUN (3478/3479) | NAT test before an entry | capture: all 16 STUN packets at 16:59:53–16:59:59 PT (matching phase), **none** after the battle ended at 17:01:50 [P] |
| LM → MMS | **never** | the WAN manager (`CAcSeqWanMatchingManager`) is created only by the PCB root (0x1406fd860); the LM root has none (lm-and-online.md §2.2) [C] |
| MMS → cabinet / LM / card server | **never** | HTTP request/response only; the MMS has no push channel and no address to call [S] |
| cabinet ↔ cabinet (P2P UDP 48000/48001) | battle, results, rematch | rematch handshake (RPC 200/202) is peer to peer (post-match-flow.md §2) [C/P] |
| cabinet → its own card server | results saves (SaveVsmOnResult etc.) | the card server named at boot, not the MMS [C] |

## 2. What the MMS protocol even allows after a match [C/S]
* The protocol has six methods only: Ping(0), IssueNodeId(1), EntryMatching(2), CheckMatching(3), CancelMatching(4),
  MatchingSetting(100). There is **no** leave-room, close-room, report-result or keepalive-in-room message. Our server
  handles all six; anything else gets `ERR_REQUEST` at once.
* **CancelMatching** can be reached from the battle party (`CAcSecPcbPlayerBattleParty` vtable[38] 0x140869040 →
  0x140793420 → `CAcSeqWanEntry` 0x140825160 → 0x1407546b0), but 0x1407546b0 only sends it when the MMS client state
  `[mgr+0x870] == 1` (entry in progress). EntryMatching sets 1 (0x1407ba7ec), CheckMatching sets **3 on match**
  (0x1407ba45e), Cancel sets 2. So after a room is made no CancelMatching is sent; it is a break-in / abort of a *new*
  search. Its reply is ignored anyway.
* **Ping** (`CAcSeqWanMatchingManager` vtable[9] 0x140753b30): a background timer (every 0x3938700 µs = 60 s) in the
  WAN manager, owned by the PCB root, not by the battle or results flow. Fire-and-forget, 10 s curl timeout.
* **Re-queue** after the results is a normal new EntryMatching with the next apply_id (post-match-flow.md §3); it
  happens only after the results screen and the party are gone, so it can't hold the results screen.
* No results task (ResultAction / SaveResult / ResultCapture / Finish, results-hang-logs.md §7) calls the MMS or STUN
  code: the only call paths into the MMS request builders (0x1407ba4f0 / 0x1407ba650 / 0x1407ba790) come from
  `CAcSeqWanEntry`, `CAcSeqWanTagEntry`, `CAcSecPcbMatching`, `CAcSeqWaitMatching`, the root/practice/training
  battle sequences and the PCB root (caller walk with `tools/re`). [C]

## 3. Our server's room state after a match [S]
* A matched unit is kept 60 s (`MatchedKeep`) so late CheckMatching polls still get the same room, then dropped
  silently. Nothing waits for, or sends, anything at battle end.
* A re-entry with the **same** node + apply_id + world within those 60 s is treated as a retry and gets the old room
  back. The game increments apply_id per entry and a battle lasts longer than 60 s, so a real re-queue is a fresh
  entry (covered by `PostMatchTraceTests.RequeueAfterTheBattleIsANewEntryAndIsTraced`).
* An entry from a node with an older waiting unit replaces it; one queue slot per cabinet (disconnect-test.md).

## 4. Captures [P]
Battle end 17:01:50.28 PT. After it the capture has only cab↔cab P2P (60 Hz) and two `LGReportSoftwareVersionRequest`
calls to the LMs (17:01:58/59, answered in < 40 ms). No packet to 3478/3479 after 16:59:59 and no LM ↔ MMS traffic.
HTTP (TCP) was not in this capture; the card-server logs have not been read yet (PC offline).

## 5. Could any of it block the results screen?
No path found. The MMS is not called by the results tasks, the only post-match MMS calls (Ping, re-queue Entry/Check)
belong to the WAN manager / next search, every MMS call is bounded by a 10 s curl timeout, and the hang also happens
in local LM mode where no MMS exists. **The "card server not talking to the matchmaker" theory is ruled out**: that
link does not exist in any mode. [S/C/I]

## 6. Logging added for the next test (default on, logging only)
`OnlineMatching.LogPostMatchTraffic` (true). For 30 min after a cabinet's room was made the server logs:
* `MMS-POST <method> node=N [apply=A] src=<ip> -> <code> [room=R] (<ms>ms) room=R +Ts by=node|ip` for each
  matchmaker request from that cabinet (keep-polling CheckMatching at most every 15 s per node);
* `STUN-POST from=<ip:port> change=.. room=R +Ts by=ip` for STUN requests from its IP (at most every 10 s);
* `MMS-UNHANDLED method=typeN ...` (warning) for any unknown MMS method, always.
`+Ts` counts from the moment the room was made; compare it with the battle length. No pcb serial, am id or card data in
these lines. If the next hung match shows no `MMS-POST`/`STUN-POST` line between the battle end and the end of the
hang, the matchmaker is confirmed out of the picture. Tests: 7 unit tests (`PostMatchTraceTests`, 93 in total) and a
local end-to-end run with fake cabinets (match → Ping → STUN → re-entry → cancel → unknown method), all lines as above.
