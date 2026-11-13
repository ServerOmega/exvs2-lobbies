# EXVS2 IB — official WAN matchmaking (MMS) and the "16-player LM" limit

> **2026-11-13 note:** the box project folder (binary, RE tools, earlier analysis files) was lost
> between sessions. This file was restored from the session transcript; content of §0–§6 is the
> original 2026-11-13 analysis. §7 is the follow-up. Re-running any address check needs
> `binaries/vsac29_Release.exe` copied back to the box.

Static analysis of `vsac29_Release.exe` (box copy only; no patches applied).
Tools used: capstone + RTTI + `.pdata` + string xrefs (`tools/re/relib.py`, `build_xrefs.py`, `scan_disp.py` — lost, re-creatable).
`.text` file offset = VA − 0x140000C00 (VA 0x140001000 ↔ raw 0x400).

Confidence: **[C]** confirmed in disassembly, **[H]** high, **[M]** medium (inferred), **[L]** guess.

## 0. TL;DR
* Two systems: (1) **LAN/store matching** via the Live Monitor (`CAcLocalGroupMediator`, `CAcSeqPcbFaciliator`, `ULG*` RPCs, `VDK::FWK::CP2PSignalingTerminal*`), used today over N2N/Radmin, bounded by the shop model (16 terminal slots) **[M]**; (2) **WAN matching** (`CAcSeqWanMatchingManager`, `CAcSeqWanEntry`, `CStunClinet`, HTTP protobuf `nue.protocol.mms`), no LM.
* MMS URL comes **only** from `Response.RegisterPcb.server_info[SRV_MATCH].uri`; STUN **only** from `server_info[SRV_STUN]` **[C]**.
* IB-Server today: MATCH entry but no STUN entry, `IssueNodeId → [1]`, `ERR_SERVER` for Entry/Check/Cancel — each blocks WAN play **[C]**.
* Minimal universal server = RegisterPcb change + 5 HTTP/protobuf RPCs + RFC 5389/5780 STUN. See `matchmaking-server-design.md`.

## 1. How the game finds the MMS server
### 1.1 HTTP client [C]
`SEQ::CAcSeqHttpClient` (vt 0x141461ec8, ctor 0x1406d3540): 3 endpoint slots (0x48 B at `this+0x4b8+i*0x48`), setter `0x1406d4f90(client, idx, cstr)`.
* slot 0 = exvs game server: `0x140718c10` ← `0x1406bf9c0` ← Mucha/AllNet `[0x14287f548]+0x30` (`0x140102f10`). Dev flag (+0x16) ⇒ hardcoded `https://vsac29-development.vsac29.bng.jp/game_server/exvs/rpc`; else string +0xe8 when auth flag (+0x15). Unauthenticated ⇒ slots 0/1 set to "" (0x140719053..0x14071907b).
* slot 1 = MMS: set **only** in RegisterPcb handler `0x14076cd10`.

### 1.2 RegisterPcb handler `0x14076cd10` [C]
* Success iff `[resp+0x24]==0` (0x14076cd55); then `[obj+0x510]=1`, next proc 0x14076e6f0.
* SRV_MATCH (cmp **0x14076cdb3**) → `0x1406d4f90([obj+0x4c0], 1, uri)` (0x14076cdd8). **uri used verbatim as URL; port ignored.**
* SRV_STUN: uri/account_name/account_pass/port copied (last entry wins) → `0x140755a20` (0x14076d003): host mgr+0x4ec, account +0x56c, pass +0x610, port +0x650, then IssueNodeId (`0x140755580`). If `[obj+0x4b0]` set, parked at `[obj+0x4f8]`.
* sram_clear → `[[obj+0x4d0]]`; core_dump_res → `[obj+0x4e8]`; lm_ip_addresses ≠ own IP → `0x1407329a0([obj+0x4c8], ip)` (0x14076d46b, LM addresses [M]); ipv4_flag → `0x1406c2a40(Cpn, flag==0)`.

### 1.3 Transport [C]
* `0x1406d48c0` → `0x1406d29b0`; body = SerializeToString (0x1405537b0). **No app-level crypto/checksum.**
* Headers `Content-type: application/x-protobuf`, `X-Nue-Protobuf-Revision: 141` (exvs) / `6` (mms). Timeout 10 s. libcurl `BAS::CHttpClient` 0x1402d8260 → 0x1402d7480. Use plain HTTP.
* Response `0x1406d59f0`: HTTP 200 + parse required (else −1000). proto2 required fields must be present [H].
* mms header fill (type, request_id): `0x1406d3df0`.

## 2. MMS per method
MMS client at WanMatchingManager+0x868: [0] httpclient, +8 state, +0x10 status, +0x14 apply_id, +0x18 node_id, +0x28 poling_interval, +0x58 room_id, +0x60 matched vector (0x58 stride).

### 2.1 IssueNodeId [C] — `CAcHttpRequestIssueNodeId` vt 0x1415eced8
Request 0x1407bc340: pcb_serial, loc_id, issue_at, **issue_count = 2** (0x140755640). Response 0x1407bc010: code 0, body present, `node_id_size >= issue_count` (cmp **0x1407bc08f**, jl 0x1407bc097 → error 4). Error map 102→2, 101→1, 2→3, other→7.

### 2.2 EntryMatching [C] — 0x1407ba790, info 0x140753330
apply_id (counter mgr+0x66c); matching_timeout 90 if world_id==5 else 150 (0x1407536c8 / 0x1407536e1); seq_num; create_room_flag; entry_at; blacklists (am_ids, ≤15 loc_ids).
myclient: node_id, pcb_serial, loc_id, pref_code, subnet_id only if `0x1406c0bb0(Cpn)==0` (0x1407babce), STUN global ip/port, local ip/port, NAT mapping/filtering, property {0,"Y"}.
myplayer: am_id; attr1 = TestMode `wanMatchingGroupId` (+0x4f4) only if `0x1406c0f70(Cpn,4)` (0x1407baf3a) [M: feature/debug gate]; attr2/3 info+0x58/+0x60; attr4 some worlds.
world: "GIB1", version `0x1405b89f0()`, world_id from mode mgr+0x710 (0→5, 1→0x15, 2→0x16, 3–6→6/0x1a/7/0x1b/0x18/0x20, 7→0x21, 8→8, 9→9, 10–14→0xd–0x11, 15/16→0x17, 17–19→0x12–0x14, 20/21→0x19, default 5).
groups: exactly one — partner cabinet (mgr+0x95c) or `PCB00000NPC` CPU.
Response: poling_interval only (apply_id unread).

### 2.3 CheckMatching [C] — 0x1407ba650 / cb 0x1407b9d20
Polled every poling_interval s (0x140756380); retries 3000 ms (PROCESS_WAIT) / 1000 ms after errors. Code 0 + empty = keep polling. Matched: room_id + MatchedClient list; **self entry required** (0x1407542c0); team table ≤4, team = group_id differs from first (0x140792760); peer address local if same global IP (0x140794590).

### 2.4 CancelMatching [C] — 0x1407ba4f0, reply ignored.
### 2.5 Ping / MatchingSetting [M] — Ping from 0x140753b30 (WAN mgr) and 0x1407fb4c0 (TestMode net check); MatchingSetting never sent.
### 2.6 STUN [C/H] — `SEQ::CStunClinet` vt 0x1415d5d48
Binding 0x1407b7f80 (cookie 0x2112A442), txid 0x1407b8400; XOR-MAPPED/XOR-PEER/XOR-RELAYED parse 0x1407b9020 (IPv4/6); RFC 5780 OTHER-ADDRESS 0x802c (0x1407b9190) for NAT tests (state machine 0x1407b8970; missing → result 4); 401/438 → REALM/NONCE + MESSAGE-INTEGRITY with RegisterPcb creds (0x1407b7ff0).

## 3. The 16 (LAN/store model) [M]
* TestMode `gameServerPcb.settingFile[*]` (0x9c B, deserializer 0x1406dc370): `totalConnectionNum` (+0x34, pack default 16), `networkGroup`, `group[3]`.
* `0x1407749e0` loops terminal index 0..15 (`cmp ebx,0x10` 0x140774a94) through `0x1406d8ad0`.
* `CAcLocalGroupMediator` pairing table **0x1414a6500**: 0↔1, 2↔3, 4↔5, 6↔7 (loop 0x14072d31a in 0x14072d250, via lambda 0x1407307c0) [C table].
* TestMode debugParam block at +0x4e8: lanMatchingGroupId +0x4f0, wanMatchingGroupId +0x4f4, keyDelay +0x4f8, ipMode +0x4fc, classMatchSearchId +0x500, liveInitialBufferSize +0x504, debugParams +0x510 [C].
* WAN rooms are 4 clients; no global cap client-side.

## 4. Client gates / branch
* WAN manager always created at boot (`CAcSeqPcbRoot::Proc_CreateWanMatchingManager` 0x1406fd860) [C].
* `CAcSecPcbMatching` (vt 0x141597120, ctor 0x1407909c0) proc `0x140790f70`: `[this+0x528]==1` → LAN (P2P terminal list 0x140347fe0); else `[this+0x52c]` 0/1 → `CAcSeqWanEntry` (ctor 0x1408218d0) [C]. Created by `CAcSeqPcbFaciliator` (0x14074df90), `CAcSeqPcbTournamnetFaciliator` (0x140750680), `CAcSeqWanMatchingManager` (0x140756d00) [C].
* `0x1406c0bb0`: returns 0 if debug flag 6 (`0x1406e3980(6)`), else Cpn+0x4a4 (==2 → Cpn+0x4a0) [C]; `0x1406d89b0(tm,n)` = debugParams[n] when `0x1406c0f70(Cpn,4)` [C].

## 5. Patch candidates (documented only — NOT applied)
| VA | file off | bytes | idea |
|---|---|---|---|
| 0x1407bc097 | 0x7BB497 | `7C 02` | NOP → accept < issue_count node ids (prefer server fix) |
| 0x140755640 | 0x754A40 | `C7 44 24 5C 02 00 00 00` | issue_count 2 → 1 |
| 0x1407536c8 | 0x752AC8 | `B9 5A 00 00 00` | matching_timeout world 5 (90 s) |
| 0x1407536e1 | 0x752AE1 | `B8 96 00 00 00` | matching_timeout others (150 s) |
| 0x1407baf3a | 0x7BA33A | `E8 31 60 F0 FF` | gate for sending attr1 = wanMatchingGroupId |
| 0x1407babce / 0x1407bb290 | 0x7B9FCE / 0x7BA690 | `E8 …` | subnet_id gate (call 0x1406c0bb0) |
| 0x14076cdb3 | 0x76C1B3 | `41 83 78 20 02` | SRV_MATCH type check |

## 6. Why today's setup can't do WAN [C]
1. No SRV_STUN → no IssueNodeId/STUN. 2. IssueNodeId `[1]` < 2 → error 4. 3. Entry/Check/Cancel → ERR_SERVER.

## 7. Follow-up 2026-11-13 (Part 1: what selects the WAN path) — exe restored, re-done
Tags: [C] confirmed in disassembly, [M] inferred, [L] not traced. File offset = VA − 0x140000C00.

### 7.1 Who writes `CAcSecPcbMatching+0x528`
* Setter **0x140794360** (file 0x793760): `movsd [rcx+0x528], [rdx]; mov [rcx+0x530], [rdx+8]` — writes the
  12-byte block {type @+0x528, kind @+0x52c, flag @+0x530} in one `movsd`, which is why plain `mov` scans missed it [C].
* Meaning in the dispatcher `0x140790f70`: type **1 → LAN/in-store path** (broadcast entry to the store's P2P
  terminal list via 0x140347fe0); any other type → **WAN path**: kind 1 → `CAcSeqWanEntry` (ctor 0x1408218d0) with
  extra params {2, 400}; kind 0 → `CAcSeqWanEntry` with plain params. `0x140791e20` (used when a pair is already formed)
  builds `CAcSeqWanTagEntry` (ctor 0x1408262d0) instead [C].
* 15 call sites. The ones that decide by config (mode-select play-mode sequence, 0x140874c40 / 0x140877cf0 /
  0x14087b0d0) all compute `type = (Cfg->field4 != 0) ? 1 : 2` (`neg ecx; sbb eax,eax; add eax,2`) [C].
  `Cfg` = global singleton `[0x14257db50]` (accessor 0x14071bef0, 0x18 bytes, allocated in 0x14071be70) [C].
  Others: WAN manager 0x14075793c sets {1, mgr+0x508!=0, 0}; 0x1407b39b7 and 0x1408dfd0e set {2,1}; 0x140867bc0 {2,0};
  0x1407515bd/0x1407515f7 (tournament) {1,0}/{1,1}; 0x140875add {1,1} when play-mode==1 and Cfg.field8==3 [C].

### 7.2 What sets `Cfg->field4` — the **battleMode** of the active setting file
* Store facilitator 0x14074e6a0 (file 0x74DAA0) reads the *current* setting entry from the TestMode object
  `[0x14257b748]` via 0x1406d8380 (picks one of up to 3 time-slot entries — `defaultFile` / `config1_time+file` /
  `config2_time+file` — of the active `settingFile`) and switches on entry+4 [C].
* Entry layout from the JSON parser 0x1406db9c0: +0 `connectionNum`, +4 **`battleMode`**, +8 `cpuMode`, +0xc
  `trainingMode`, +0x10 `timeRental`, +0x14 `lanBattleTimeLimit`, … [C for +0/+4/+8; order of the rest from the key list, M].
* Jump table 0x14074e8e8 (Cfg.field4 / Cfg.field8):

| battleMode | Cfg+4 | Cfg+8 | resulting +0x528 type |
|---|---|---|---|
| 0 | 0 | 2 | **2 = WAN (online)** |
| 1 | 1 | 2 | 1 = LAN/store |
| 2 | 2 | 0 | 1 |
| 3 | 2 | 1 | 1 |
| 4 | 2 | 3 | 1 |
| 5 | from store-group info (0x14072b240): 2→2, 3→2, else 1 | 0→1, 2→3, else 0 | 1 |
| 6 | 3 | 0 | 1 |
  Only **battleMode 0** gives the WAN path [C for the arithmetic; names of the battleMode values not found, M].
  battleMode 5 additionally sets Cfg+0=1 and a 0x2a30…0x4d58 table into Cfg+0xc [C].
* **Practical rule:** a cabinet goes online (MMS) when its active `settingFile` entry in `testmode_pcb.json`
  has `battleMode: 0` — a config change, no exe patch [C for code path; check the JSON at home].

### 7.3 Online mode number (what the WAN entry sends)
* Player choice on the mode-select screen → `SetPlayMode` 0x140875e00 stores 1..6 into global
  `[0x14257b7a0]+0x4cc` (and +0x4bc). Menu item → play-mode: 1→1, 2→2, 3→4, 4→3, 14→5, 15→6 (table 0x1408755c8) [C].
* In 0x140790f70 the WAN entry gets a **mode code** (first param word, later used for the MMS entry) [C for the table; use as world/attr M]:

| play-mode (+0x4cc) | kind 0 | kind 1 |
|---|---|---|
| 1 | 0x0a | 0x0b |
| 2 | 0x0f | 0x10 |
| 3 | 0x0c | 0x0d |
| 4 | sub(+0x4d0)=2→0x14, 3→0x13, else 0x11 | 2→0x15, else 0x12 |
| 5 | 2→0x05, 3→0x07, else 0x03 | 2→0x06, else 0x04 |
| 6 | 0x0c | 0x0e |
| other | 0x0c | 0x0d |
  How the exvs `OnlineMatchingMode` enum (CLASS=0 … EVENT=7) relates to play-mode 1..6 is still **not traced** [L];
  the server does not need it: it keys queues on the world/attr the cabinet sends.

### 7.4 NAT result does **not** block entry
* STUN state machine 0x1407b8970 writes mapping (+0x778) and filtering (+0x780); failures write 4 (e.g. no
  OTHER-ADDRESS) [C].
* 0x1407b52e0 (file 0x7B46E0) copies them to the matching client (+0xf40 mapping, default 3 if the test did not finish;
  +0xf44 filtering, default 3) and to global `+0x4c8`, then **always** advances to the next state 0x1407b4dc0 — no
  failure branch [C].
* Later uses only tune behaviour: filtering==2 picks state 0x1407b4dc0 vs 0x1407b4dd0 (0x1407b549b), sets a flag
  (+0xeb4, 0x1407b3dad), and mapping!=0 switches a timer 18000→43200 (0x14079e727, 0x1407a2f1b) [C]. No "NAT bad →
  error" path seen [M: not every reader traced].
* Server consequence: accept `nat_mapping` / `nat_filtering` values outside the proto enum (e.g. 4); never reject on NAT.

### 7.5 Response checks (request_id / type)
* MMS response path 0x1406d59f0: HTTP status must be 200, body must parse as `mms.Response` (else error −1000), then the
  per-method handler is called [C]. `Response` layout: +0x18 request_id, +0x20 type, +0x24 code, +0x30 issue_node_id,
  +0x38 entry_matching, +0x40 check_matching [C].
* Handlers check **only `code` (+0x24) == SUCCESS** and read their sub-message; **request_id and type are not compared**
  in the generic path or in the handlers examined (0x1407bb780 EntryMatching, 0x1407b9d20 CheckMatching,
  0x1407bc010 IssueNodeId) [C for those; M for all]. A missing sub-message falls back to the default instance (all 0).
* IssueNodeId: fails unless `count(node_id) >= requested` (0x1407bc08f) [C].
* EntryMatching non-zero code → internal error: 101→7, 200→2, 201→8, 202→3, other→8 [C].

### 7.6 Hole-punch / P2P packet format
Not reversed this pass. The Proc name strings (`Proc_PreSignaling`, `Proc_Signaling`, …) have no code references
(state functions are set as pointers to `+0x468`), so the format is best taken from a live capture at home [L].

### 7.7 Patch candidates (documented only, NOT applied)
| VA | file off | what | why you'd touch it |
|---|---|---|---|
| 0x14074e711 | 0x74DB11 | battleMode 0 case (`Cfg+4=0`) | not needed — set `battleMode: 0` in JSON instead |
| 0x140874dc1.. | 0x8741C1 | `neg/sbb/add` → type 1/2 | forcing WAN would bypass config; avoid |
| 0x1407b52e0 | 0x7B46E0 | NAT result copy | not needed — NAT never blocks |
None are required for the universal server.
