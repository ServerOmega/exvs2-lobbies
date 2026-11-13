# EXVS2 IB — what a server must emulate for a ranked ("Class Match G") online search

> **Status: EXPERIMENTAL / static analysis only.** Nothing here has been tested against the real game.
> All addresses refer to the box copy of `vsac29_Release.exe` (unpacked x64, V29). No exe patches applied.
> `.text` file offset = VA − 0x140000C00 (e.g. VA 0x140753330 ↔ file 0x752730).
> Confidence: **[C]** confirmed in disassembly / extracted data, **[H]** high, **[M]** medium (inferred), **[L]** guess.
> Builds on `matchmaking.md` (MMS transport, IssueNodeId, Entry/Check/Cancel) — not repeated here.

## 0. TL;DR
* **Ranked exists and is called "Class Match G"** (クラスマッチG): enum `OnlineMatchingMode.OMM_CLASS = 0`
  in the card-server proto. Classes Pilot / Valiant / Ace / Extreme, solo (shuffle) and team (fixed) tracked
  separately, grades 10→1 inside each class (Extreme also "∞"), promotion/demotion judged after every match.
  Pilot is solo-only; teams start at Valiant [C for the proto, official site for the rules — §4].
* **Two servers are involved:**
  1. **Card/game server** (`nue.protocol.exvs`, rev 141): `LoadClassMatch` (tables that drive the search),
     `PreLoadCard`/`LoadCard` (your class/grade/rate), `SaveVsmOnResult` (+`SaveBattleLogOn`, `CheckCommunication`)
     after the battle. The **client computes the new rate** and uploads `before_rate/after_rate/obtained_rate`;
     the server only stores it and returns it next time [H].
  2. **MMS** (`nue.protocol.mms`, rev 6): the same 5 RPCs as any online match. A ranked search is just an
     `EntryMatching` with **world_id 13 (solo) or 14 (team)** and Player.parameters
     **{1: wanMatchingGroupId/0, 2: class_id, 3: subnet/LAN flag, 4: matching level}** [C], plus `seq_num` /
     `create_room_flag` taken from the `LoadClassMatch.ClassMatchingRequest` table [C].
* **The MMS protocol carries no rate, grade, name or pilot data.** `CheckMatching.MatchedClient` is only
  `{group_id, Client(addresses)}` [C], so opponents' class/grade shown in the versus screen must come P2P from
  the other cabinets [H]. The matcher therefore only needs to pair compatible entries.
* Minimal ranked emulation = (a) card server returns a sane `LoadClassMatch` + class fields in
  `PreLoadCard.LoadPlayer` and persists `SaveVsmOnResult.class_match_result`; (b) MMS buckets world 13/14 by
  class (attr2) and prefers close levels (attr4), widening over time. Implemented in
  `server-sketch/python/mms_server.py` (box-tested with `fake_cabinet.py --ranked`, **not** with the game).

## 1. The card-server side (`game_server_nue.proto`) [C]
The whole exvs descriptor was extracted this pass: serialized `FileDescriptorProto` at **file offset 0x13c8d70
(60 724 bytes)** → `analysis/proto/from_exe/game_server_nue.proto` (2 385 lines; renderer `tools/re/desc2proto.py`).
Ranked-relevant pieces:

| message / field | what it is |
|---|---|
| `enum OnlineMatchingMode` | `OMM_CLASS=0, OMM_FREE=1, OMM_LOCAL=2, OMM_LOCATION=3, OMM_FES=4, OMM_PRIVATE=5, OMM_PUB=6, OMM_EVENT=7` |
| `enum OnlineLineType` | `SOLO, PAIR_LEADER, PAIR_MEMBER, SOLO_WITH_CPU, ONTAG_PAIR_LEADER, ONTAG_PAIR_MEMBER` (reported in CheckCommunication) |
| `MTHD_LOAD_CLASS_MATCH = 6` → `Response.LoadClassMatch` | `constant_rate`, `win_score_coefficient`, `initial_rate`, `class_change_initial_rate[]{team_type,class_id,up_default_rate,down_default_rate}`, `grade_thresholds[]{team_type,class_id,grade_id,max_rate,min_rate}`, `search_ratios{solo[],team[]}{class_id,level_id,num,search_ratio}`, `class_matching_time_schedule[]{start_at,end_at,pattern_id}`, `class_matching_pattern_table[]{pattern_id, solo[]/team[]{class_id,level_id,grade_id_start,grade_id_end}}`, `class_matching_request_table[]{room_search_id,matching_try_num,seq_num,make_room_flag}`, `consecutive_win_grade[]/consecutive_lose_grade[]{start,end,grade_num}` |
| `MTHD_LOAD_RANK_MATCH = 5` → `Response.LoadRankMatch` | season/point-based "rank match" tables (seasons, point thresholds, win/lose points, EXX threshold). Probably the Extreme "top point" ladder or a legacy mode — usage not traced [L] |
| `Response.PreLoadCard.LoadPlayer` | `class_id_solo/team`, `grade_solo/team`, `rate_solo/team` (float), `class_solo_win/lose`, `class_team_win/lose`, `vsm_after_class_change_solo/team`, `grade_1_solo/team`, `top_point_rank_*` — all **required** except the change fields |
| `Request.SaveVsmOnResult.PlayResultGroup` | `online_matching_mode` (required), `room_id` (MMS room!), `win_flag`, `partner`/`foes` (`AdversaryManGroup` has `class_id`, `grade_id`), `class_match_result{class_id_solo, class_id_team, before_rate, after_rate, obtained_rate, grade_id}`, `matching_tag`, `on_compe_result`, … |
| `Response.SaveVsmOnResult` | **empty** — nothing to return after a ranked match |
| `Request.SaveBattleLogOn` / `SaveFailedBattleLogOn` | per-pilot `class_id`, `online_matching_mode`, `room_id`, fault flags (disconnect accounting) |
| `Request.CheckCommunication` | matching telemetry: `line_type`, `apply_id`, `matching_try_num`, STUN result, `udp_hp_result`, players' `rtt`, `class_id`, `matching_rank_free/fes` |
| `Request.SaveUserPlayResearchData` | `online_matching_mode`, `class_id_solo/team`, `matching_request_num`, `matching_success_num` |
| `LoadGameData` | `on_vs_info.rule_time_limit_class`, `class_win/lose_badge_point`, `free_matching_tables`, `free_match_rank_tables`, `fes_setting` |
| `Response.LoadRanking` | `ClassMatchScore` / `TagClassMatchScore` leaderboards (`RankBaseType CLASS_MATCH=15, TAG_CLASS_MATCH=16`) |

**Who computes the new rate?** `Request.SaveVsmOnResult…ClassMatchResult` carries `before_rate`, `after_rate`,
`obtained_rate` (floats) and the response is empty, and `LoadClassMatch` hands the client `constant_rate`,
`win_score_coefficient`, grade thresholds and consecutive-win/lose grade steps. So the **client computes rate,
grade and class changes** and the server is a store that must echo them back in the next
`PreLoadCard.LoadPlayer` [H — protocol shape; the formula itself not reversed]. The asesidaa OverBoost server
documents the same model for OB (comment in `LoadClassMatchCommandHandler.cs`: win ≈ `ConstantRate·(1+score/WinScoreCoefficient)`).

## 2. How the client builds a ranked MMS entry [C unless noted]
### 2.1 Choosing ranked
* Mode select → `SetPlayMode` 0x140875e00 stores play-mode 1..6 in `[0x14257b7a0]+0x4cc` (matchmaking.md §7.3).
* `CAcSecPcbMatching` dispatcher 0x140790f70 turns (play-mode, kind) into a **mode code**; play-mode **1 → 0x0a
  (kind 0) / 0x0b (kind 1)**.
* `CAcSeqWanEntry` (fn 0x140822e20, call 0x1408231b4) fills a 0x48-byte param block and copies it into the WAN
  manager with 0x140754f90: `+0`→mgr+0x710 **mode code**, `+4`→+0x714, `+8`→+0x718, … `+0x24`→**+0x734 class_id**,
  `+0x28`→**+0x738 grade**, `+0x2c`→+0x73c **rate (float→int)**, `+0x30`→+0x740, `+0x34/+0x38`→+0x744/+0x748
  (win/lose counts used by free-match), `+0x3c/+0x3d`→+0x74c/+0x74d flags, `+0x40`→+0x750.
* For play-mode 1 the class triple is read from the card object: **solo struct at card+0xbf8** (0x1406bf850)
  or, when the mode code is 0x0b, **team struct at card+0xc14** (0x1406bf8a0), layout `{u32 class_id, u32 grade,
  float rate}` (0x140822f4a..0x140822ff9). → mode 0x0a = **solo/shuffle class match**, 0x0b = **team/fixed** [H].
  The partner's values sit at mgr+0x918/+0x91c (+0x95c = "has partner").

### 2.2 Mode code → world_id (0x140753330, table 0x140753a3c)
| mode code (mgr+0x710) | world_id | Player attrs (fill variant, table 0x140753ab4) | likely mode |
|---|---|---|---|
| 0x0a | **13 (0x0d)** | 2=class_id, 3=LAN flag, 4=level | **Class Match solo (OMM_CLASS)** [H] |
| 0x0b | **14 (0x0e)** | 2=max(own,partner class), 3=LAN flag, 4=level | **Class Match team** [H] |
| 0x0c / 0x0d | 15 / 16 | 2=hex value of last 4 chars of the string at mgr+0x4c5 (0x140752f40), 3=flag | location/room-code style match [L] |
| 0x0e | 17 | 2=level, 3=flag | [L] |
| 0x0f / 0x10 | 23 | 2=(max class flag ≥2), 3=flag | [L] |
| 0x11–0x15 | 18,19,20,25 | 2=win-rate bucket 1/2 (0x140752dad), 3=flag | free match (OMM_FREE) [M] |
| 0x03–0x07 | 6/7/0x18/0x1a/0x1b/0x20 or mgr+0x71c | 2=Cpn value, 3=mmr-ish, 4=flag | event/fes [L] |
| 0 / 1 / 2 / 7 / 8 / 9 | 5 / 0x15 / 0x16 / 0x21 / 8 / 9 | various | tournament / shop / default [L] |
Builder 0x1407ba790 sends attr4 only for worlds {5–9, 13, 14, 24, 26–33} (table 0x1407bb5fc) — so ranked does
send it. attr1 = TestMode `wanMatchingGroupId` only when debug gate `0x1406c0f70(Cpn,4)` (0x1407baf3a), else 0.
attr3 = `(0x1406c0bb0()==0)` — the same predicate that decides whether `subnet_id` is sent [C; meaning M].

### 2.3 attr4 = "matching level" (0x1407527e0, modes 0x0a/0x0b)
1. hour = `localtime().tm_hour` (+24 if ≤ 2, arcade day) (0x1407528ad..0x1407528ce).
2. Pick `class_matching_time_schedule[i]` with `start_at ≤ hour < end_at` → `pattern_id` (**IB uses hours,
   not unix times** in this compare [H]).
3. In that pattern's `class_matching_solo` (0x0a) or `class_matching_team` (0x0b) list, find the row with
   `class_id == my class` (team: max of pair, or min when flag +0x74d) and `grade_id_start ≤ grade ≤ grade_id_end`
   → return `level_id` (0x140752b5a). **Default 3** when nothing matches (0x140752b24).
So `level` is the server-configured grade bucket; equal levels = "close grades".

### 2.4 seq_num / create_room_flag / room search id (0x140755c30, 0x1407551b0)
* Every entry increments try counters mgr+0x670/+0x674 (0x140755c6b).
* Ranked: room_search_id (mgr+0x678) = TestMode `classMatchSearchId` (+0x500) if non-zero, else picked from
  `search_ratios.{solo|team}` rows with `class_id == class && level_id == level` (weighted by `num/search_ratio`,
  0x140755d4c..) [C for the filter; weighting M].
* `seq_num`/`create_room_flag` = the `class_matching_request_table` row whose `room_search_id` matches
  (0x140755275..0x140755383); defaults `seq_num=1, create_room_flag=1` when tables are empty [C].
  `matching_try_num` (row +0x1c) is presumably how many polls/entries before moving on [M].
* `matching_timeout` = 150 s for these worlds (only world 5 uses 90 s) (0x1407536c8/0x1407536e1).

### 2.5 What the client expects back
* EntryMatching: `poling_interval` (+ echo apply_id). CheckMatching: `room_id` + 4 clients with `group_id`.
  Same as casual — **no ranked-specific response fields exist** [C].
* On `MATCH_CANCELED`/timeout the client gives up the search (official IB rules: a CPU battle while waiting
  counts as a match in some credit modes) [M].
* After the battle: `SaveVsmOnResult` (+ `SaveBattleLogOn`, `CheckCommunication`, `SaveUserPlayResearchData`)
  to the **card server**; `room_id` there is the MMS room id → the link between both servers.

## 3. Matching parameters summary
| item | value / source |
|---|---|
| HTTP timeout / poll | 10 s; `poling_interval` s; retry 3 s on PROCESS_WAIT, 1 s on errors [C] |
| matching_timeout | 150 s ranked (90 s only world 5) [C] |
| CPU fill | client puts `PCB00000NPC` in `groups[0]` when solo; the server returns it as a normal client [C] |
| partner/team | `groups[0]` = partner cabinet; team class = max(own, partner) (min if +0x74d) [C] |
| blacklist | `bl_banapassport_am_ids`, ≤15 `bl_loc_ids` (from card-server `LoadBlackList`: `max_blacklist_num`, `UnfittedLocationGroup{loc_id,rtt}`, delay thresholds) [C] |
| region | `pref_code` in Client; no other region field [C] |
| rematch | `revenge_num` / `return_match_flag` live in result/replay messages; no MMS rematch call → rematch is P2P/local [M] |

## 4. Prior art (web research, 2026-11-13)
* **asesidaa/EXVS2-POC** — https://github.com/asesidaa/EXVS2-POC (commit 2343795, Aug 2025). `Server-Over`
  (OverBoost) implements `LoadClassMatch` with fixed tables (`Handlers/Game/LoadClassMatchCommandHandler.cs`),
  class records + percentile thresholds, default rate 1500. Its MMS (`Controllers/MatchController.cs`) only
  answers Ping / IssueNodeId (`[1]`) / MatchingSetting — **no Entry/Check/Cancel, so no online matching**;
  `SaveVsmOnResult` is a stub. OB's LoadClassMatch differs from IB's (OB has ClassBaseWinPoint etc.).
  Issue #135 (https://github.com/asesidaa/EXVS2-POC/issues/135): users can't online-match even with STUN.
* **vl00 "ServerIbOnOver"** gist — https://gist.github.com/vl00/20dec6176b5878977101b321db4d3910 — Chinese
  IB-on-Over build with a STUN container and "custom match3: online 2v2 CPU and unrestricted human 2v2";
  binary-only (Baidu link), no source [L on what it does].
* **Official IB rules** — https://gundam-vs.jp/extreme/ac2ib/howto/rules/status/ and
  https://gundam-vs.jp/extreme/ac2ib/features/renewal/mode_menu/ : Class Match G, 4 classes, grades 10→1 (+∞),
  same-class matching, close-grade priority, per-match promotion judging, Pilot solo-only, Extreme resets every
  2-month season; Public rooms (OMM_PUB) don't affect class record; Private rooms; Event rooms.
* **ARTEMiS (SEGA ALL.Net server, chuni)** — https://gitea.tendokyu.moe/Raymonf/artemis/commit/b85a65204fdf28ace1d91b45a53c460acf8ac569 :
  BeginMatching/GetMatchingState: oldest free room or new room, polling interval + countdown, ≤4 members —
  same poll-a-room pattern as nue MMS.
* **Bayshore** (WMMT6) — https://github.com/ProjectAsakura/Bayshore : card/ghost server only; no live matching
  code found in `src/` (grep) [M].
No public server implements nue MMS EntryMatching/CheckMatching for any EXVS2 build as of this date [M].

## 5. Design: ranked search in our server
### 5.1 Queue key and pairing (implemented in `mms_server.py`)
* Key = `(mucha_game_id, version, world_id, attr1, attr2=class_id)` for worlds 13/14; casual unchanged.
  Official rule is "same class only", so class is a hard key.
* Inside a key, pair the **closest** candidate by `|level diff|·1000 + |mmr diff|`, with a band that widens
  with the longer waiter's wait (`RANKED_BANDS`): 0 s: same level & ±100 MMR → 15 s: ±1 level, ±200 → 35 s:
  ±2, ±350 → 60 s: anything in the class. Re-evaluated on every CheckMatching poll.
* Shared exclusions: same node, same am_id on both sides, either side's blacklist.
* `seq_num`/`create_room_flag` are logged only; with one central matcher "make room vs search" doesn't matter.
### 5.2 Rating
* **Visible** class/grade/rate: owned by the client + card server. Card server must:
  1. return `LoadClassMatch` (IB shape!) with schedule rows covering all hours (e.g. `start_at=0,end_at=27`),
     one pattern per class mapping grade ranges to levels (e.g. grades 10–8→1, 7–5→2, 4–3→3, 2–1→4), a
     request table row `{room_search_id:1, try:3, seq:1, make_room:true}`, `search_ratios` rows for every
     (class, level) → room 1, thresholds/initial rates; 
  2. persist `class_match_result.after_rate`, `grade_id`, `class_id_*` from `SaveVsmOnResult` and return them
     in `PreLoadCard.LoadPlayer` (`rate_*`, `grade_*`, `class_id_*`, win/lose counters).
  Optionally clamp `obtained_rate` to a sane range (anti-cheat: the client is trusted otherwise).
* **Hidden MMR** (optional, implemented): team-average Elo (K=32, base 1500) per `banapassport_am_id`, used only
  to order candidates inside a class. Updated via an internal `POST /result {"room_id", "winner_group"}` that
  the card server's `SaveVsmOnResult` handler should call (it knows `room_id` + `win_flag`); counted once per
  room. Glicko-2 would be a drop-in later (needs rating deviation per player; low play volume favours it).
  Protect `/result` with `--result-token` / `X-Result-Token` when shared.
### 5.3 Team class rule
The client already sends the pair's class (max) in attr2 and level in attr4, so the server needs no partner lookup.

## 6. Open questions (need a live capture / home test)
1. Does mode select even show Class Match without a valid `LoadClassMatch` / schedule? (no menu gate traced) [L]
2. Exact P2P exchange of opponents' class/grade/name (hole-punch format still unknown, matchmaking.md §7.6).
3. Does the client require `PreLoadCard.LoadPlayer` class fields to be non-zero (class_id 0 = unranked?) and what
   are the numeric class ids (expect 1 Pilot … 4 Extreme as in the OB server, unverified for IB).
4. Rate formula and grade step rules (client side; only needed if we want server-side validation).
5. Meaning of mode codes 0x0c–0x10 / worlds 15–17, 23 (location / private / public rooms?) and of the +0x74d flag.
6. What `LoadRankMatch` drives in IB (Extreme ladder? unused?).
7. Whether both cabinets of a fixed pair send EntryMatching (merge logic in the server handles both).

## 7. Files
* `analysis/proto/from_exe/game_server_nue.proto` — new, full exvs proto (card/game server).
* `tools/re/desc2proto.py` — descriptor → .proto renderer.
* `server-sketch/python/mms_server.py` — ranked key/bands, hidden MMR store, `/result` hook.
* `server-sketch/python/fake_cabinet.py` — `--ranked "class:level,..." [--team] [--report]`.
* `server-sketch/python/pbwire.py` — fix: packed repeated fields decoded before scalar handling.
Box test 2026-11-13: 6 ranked cabinets `2:3,3:3,2:5,3:3,2:3,2:5` → pairs (2:3,2:3), (3:3,3:3), (2:5,2:5);
`2:1` vs `2:3` matched after 35 s widening; casual 4-cabinet test still passes. **Not tested with the game.**

> **Correction (casual-shuffle-matching.md §3/§5):** Class Match solo entries (code 0x0a, world 13) carry **no** groups and no CPU stand-in. The server forms 2v2 rooms by shuffling 4 solos into group_ids. Only team entries (0x0b, world 14) carry a partner/CPU group. mms_server.py now does this.
