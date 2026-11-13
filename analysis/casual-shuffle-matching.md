# Casual / shuffle matchmaking in EXVS2 IB (vsac29) — static analysis

Status: **static analysis only, untested in game.** VAs are for `vsac29_Release.exe` (file offset = VA − 0x140000C00).
Confidence: **[C]** confirmed in code, **[H]** high, **[M]** medium, **[L]** low/guess.
Companion docs: `matchmaking.md` (protocol), `ranked-matching.md` (Class Match G), `matchmaking-server-design.md`.

## 1. Official mode list (IB)
Source: https://gundam-vs.jp/extreme/ac2ib/howto/game_mode/online/ (read 2026-11-13). Menu order:

1. **Class Match G**: ranked (see ranked-matching.md).
2. **Mix Match (ミックスマッチ)**: solo and team players are all matched together unconditionally. No class effect and no record. It cannot be chosen while you are in a custom room.
3. **Custom Match** (formerly private match): Private room / Public room (daily schedule) / Event room. You join through vsmobile or the Live Monitor.
4. **In-store match (店内対戦)**: only cabinets in the same shop.
- **Solo sortie (ソロ出撃)**: solo players are randomly combined into teams. This is the *shuffle*.
- **Team sortie (チーム出撃)**: you pick a partner by in-store team, online tag (friend/group tag), or partner recruit (パートナー急募, Class Match G only).
- Mix Match from 0:00 to 7:00 and in-store match can be played without a registered card.

## 2. How the client selects a mode
- **Menu item → play-mode** `[0x14257b7a0]+0x4cc`. The setter is SetPlayMode at 0x140875e00 [C]:

  | Menu item | 1 | 2 | 3 | 4 | 14 | 15 |
  |---|---|---|---|---|---|---|
  | Play-mode | 1 | 2 | 4 | 3 | 5 | 6 |

  The sub-mode is at `+0x4d0`.
- **Sortie type** `[0x14257b7a0]+0x4c4` [M-H]: 0 = solo, 1 = team, 2–5 = the partner-selection routes. It is switched in 0x140877cf0, which calls the kind setter 0x140794360 with kind 0 (case 0) or kind 1 (case 1).
- **Kind** `[wan+0x52c]`: 0 = solo sortie, 1 = team sortie [H]. Kind 1 also passes the extra params {2, 400} (meaning unknown [L]).
- **Mode code** comes from dispatcher 0x140790f70 [C]:

| play-mode | probable official mode | kind 0 (solo) code | kind 1 (team) code | world_id solo / team |
|---|---|---|---|---|
| 1 | Class Match G [H] | 0x0a | 0x0b | 13 / 14 |
| 2 | **Mix Match** [H-M] | 0x0f | 0x10 | **23 / 23** (one pool) |
| 3 | In-store match [H] | 0x0c | 0x0d | 15 / 16 |
| 4 | Custom/free match, sub = room type [M] | 0x11; sub2→0x14; sub3→0x13 | 0x12; sub2→0x15 | 18; sub2→25; sub3→20 / 19; sub2→25 |
| 5 (menu 14) | tag / event room [M] | 0x03; sub2→0x05; sub3→0x07 | 0x04; sub2→0x06 | 26/6/override; 24/32/override; 33 / 27/7/override; 24 |
| 6 (menu 15) | shop-setting match [L] | 0x0c | 0x0e | 15 / 17 |
| other | — | 0x0c | 0x0d | 15 / 16 |

- **Mode code → world** comes from 0x140753330 (table 0x140753a3c) [C].
  - Codes 3–6 take `+0x718`: 2 → fixed world, 3 → server-given world `+0x71c`, else the default.
  - `+0x71c` comes from the Cpn struct (0x1406bfd90, +0x34, used when +0x28==1). It is most likely `PreLoadCard.matching_tag.world_id` from the card server [M].
- **Codes 0x0c–0x10 pinned** [C for the code→world mapping, M for the names]:

  | Code | Mode | World | attr2 / level |
  |---|---|---|---|
  | 0x0c | in-store solo (also the pm6/default solo) | 15 | hex value of the last 4 chars of loc_id (0x140752f40) |
  | 0x0d | in-store team | 16 | same as 0x0c |
  | 0x0e | pm6 team | 17 | TestMode shop-matching settings (+0x3e0/+0x3e4/+0x3e8) [L] |
  | 0x0f | Mix solo | 23 | max(own +0x740, partner +0x924) ≥ 2 → "veteran" flag [L meaning] |
  | 0x10 | Mix team | 23 | same as 0x0f |

## 3. EntryMatching differences per mode

| field | solo sortie (kind 0) | team sortie (kind 1) |
|---|---|---|
| `groups[]` | **none**: `info+0x30`=0 (0x1407bb14a skips the group loop) [C] | **1 group**: the partner [C] |
| group property[0] | — | `"Y"` if a human partner (`info+0x7c` ← mgr+0x95c), else `"N"` [C] (0x1407bb39f) |
| CPU stand-in | — | pcb_serial `PCB00000NPC`, node_id = 2nd IssueNodeId id (mgr+0x664), am_id 0 [C] (0x140753962) |
| myclient property | `{0,"Y"}` | `{0,"Y"}` |

- The **groups flag table** is at 0x140755484, indexed by mode−4 (0 → flag=1). Groups are sent for codes **4, 6, 9, 0x0b, 0x0d, 0x0e, 0x10, 0x12, 0x15**, i.e. exactly the kind-1 codes (plus 9). Codes 0–3 never send groups [C].
- **seq_num / create_room_flag** come from 0x1407551b0 [C]:
  - Mix (15/16): seq 1 while try-count `+0x674` < 2, then 2/3. create_room is 0 on tries 1–2 and 1 afterwards. This suggests the official server first tried to *join* existing rooms, then allowed creating one.
  - In-store/custom (12–14, 17–21): seq 1, create 1.
  - Tag/event (3–9): create 1; seq = min(try count `+0x670`, 2/3).
- `matching_timeout` is per entry. The server can only answer within it. After it, the client stops polling.
- The client sends nothing that names a room (Property is constant, there is no room code) [C]. Private/event separation therefore has to come from **world_id** (server-given `+0x71c`) and/or attr2 (Cpn+4).

## 4. Player attributes per world (0x140752b60 / 0x140753ab4) [C]
- **attr1** = TestMode wanMatchingGroupId.
- **attr2** depends on the world:

  | World | attr2 |
  |---|---|
  | 13/14 | class |
  | 15/16 | shop hash (last 4 loc_id chars) |
  | 17 | shop settings |
  | 18/19/20/25 | win-rate bucket 1/2: card wins/losses against the threshold `[data+0xd0]+0x34`, min with the partner |
  | 23 | veteran flag |
  | 6–9, 24, 26–33 | Cpn+4 (tag/room id?) [L] |

- **attr3** = subnet/LAN flag.
- **attr4** is sent only for worlds {5–9, 13, 14, 24, 26–33}.

## 5. How the client reads CheckMatching (decides who decides teams)
- The callback is 0x1407b9d20 [C]. For each MatchedClient it stores group_id, node_id, NAT types, IPs/ports and loc/pcb, plus `is_self = (node_id == own node_id)`. It also stores `flag(+0x54) = (property[0].value == "Y")`.
- 0x1407540e0(…, 1) copies only the `"Y"` entries. 0x140792760 then builds the team table {node_id, team = group_id ≠ group_id of the first "Y" entry}.
  - The table holds **4 slots**, and the count lives right after it, so **never return more than 4 "Y" clients** [C].
- 0x1407541a0 counts the "Y" entries, and 0x140823ce0 only requires ≥1. 0x1407542c0 requires a self entry.
- **Conclusion [C]:** team composition is decided entirely by the **server's group_id**. The client never pairs players itself. A shuffle is just the server giving two solo cabinets the same group_id.
- "N" CPU stand-ins may be listed: they are ignored for teams but are harmless.

### Forming a 2v2

| case | server response |
|---|---|
| 4 solos | 4 "Y" clients, group ids 0,0,1,1 (random pairs; ranked: most even MMR split) |
| fixed pair + 2 solos (Mix / world 25 / 24 only; solo and team worlds differ elsewhere) | pair (host + partner "Y") = group 0, two solos = group 1 |
| 2 fixed pairs | each pair keeps its group; a pair whose partner is "N" contributes 1 human + its CPU |

The fixed-pair partner cabinet has its own node id from its own IssueNodeId. Whether it also sends its own Entry or only polls CheckMatching is **unknown** [L]. The prototype supports both: the partner's node maps to the same unit, and a duplicate entry is merged.

## 6. CPU fill on timeout
- The client inserts a CPU only as the **team-sortie** stand-in ("N" group). Solo entries get no CPU in the MMS exchange [C].
- What happens when CheckMatching returns <4 "Y" clients (1v1, 2v1) is **not proven** statically. Most likely the empty seats become CPUs in the P2P battle setup, matching the official "CPU fills when short" behaviour [L].
- When the server answers MATCH_CANCELED or the client's matching_timeout expires, the client leaves matching. It most likely falls back to a CPU battle or the retry loop (try counters +0x670/+0x674 drive seq_num/create_room) [M].
- Prototype policy:
  - Full 2v2 when possible.
  - After `--fill-after` seconds (default 30, keep it < matching_timeout) it may form short rooms with ≥2 humans.
  - `--no-partial` disables short rooms, so a lone or unmatched unit gets MATCH_CANCELED at its timeout.

## 7. Card-server tables that gate casual modes
These are in `proto/from_exe/game_server_nue.proto`. Their effects are inferred [M]:
- **`LoadGameData.free_matching_tables`** {matching_rank, matching_try_num, seq_num, make_room_flag} likely override the seq/create defaults per try for free/mix modes.
- **`free_match_rank_tables`** {win_num, matching_rank} likely provide the win-rate threshold behind the 18–20/25 attr2 bucket.
- **`fes_setting`** covers event/festival windows.
- **`PreLoadCard.matching_tag`** {tag_type, matching_type, world_id, ...} is the tag/event room → world `+0x71c`.
- **`LoadRoom.RoomGroup`** covers registration_code, tag/matching type, class/grade/win-rate bounds and policy. The card server validates room membership; MMS only sees the world_id.

## 8. Server implementation (server-sketch/python/mms_server.py)
- **Unit** = one EntryMatching: 1 slot (solo) or 2 slots (team; the partner or CPU never split).
- **Buckets** = (game id, version, world, attr1) + attr2 for "hard" worlds:
  - class (13/14)
  - shop hash (15/16)
  - shop settings (17)
  - tag/room worlds
- "Soft" attr2 (worlds 18/19/20/25/23) must match for the first `SOFT_WAIT`=15 s, then the buckets mix.
- **Room** = two sides × 2 slots, search bounded by POOL_MAX=12:
  - Casual: FIFO with a random split (shuffle).
  - Ranked: the most even MMR + level split, still under RANKED_BANDS.
  - group_id 0 = the anchor's side.
- Short rooms are allowed after FILL_AFTER (see §6).
- Tests: `python3 test_casual.py` (9 deterministic cases) and `fake_cabinet.py --units S,S,S,S|T,S,S|TN,T --world N`.

## 9. Open questions for a live test
1. Does a 4-solo room (no "N" entries) start a 2v2 with the server-chosen teams? (Expected yes [H].)
2. 1v1 / 2v1 rooms: do the cabinets fill the seats with CPUs, or do they reject/hang?
3. Fixed pair: does the partner cabinet send its own EntryMatching, only poll, or neither (host-only)?
4. Exact menu meaning of play-modes 4/5/6 and the sub-modes (custom room types vs tag rooms).
5. What populates `+0x71c` (the server-given world) and Cpn+4 (attr2 of tag worlds): PreLoadCard.matching_tag?
6. The meaning of the kind-1 extra params {2, 400} and of `[0x14257b7a0]+0x4e4` (the Mix "veteran" input).
7. Does the client accept a CheckMatching in which its own "N" CPU is missing for a team-sortie entry?
