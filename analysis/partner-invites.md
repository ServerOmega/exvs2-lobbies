# Partner invites (online tag / partner recruit / instant team)

> ⚠️ **Static analysis only.** Nothing has been tested with the real game. The exe was read in place and not copied or patched.
> Confidence tags: [C] confirmed in code, [H] high, [M] medium, [L] low or guess.
> VAs are image VAs; file offset = VA − 0x140000C00.
> Corrects `casual-shuffle-matching.md`; see §2.

> **Status 2026-11-13: Steps A and B are implemented** in the ib-server patch (fake cabinets only, not yet in the real
> game): LoadCard `tag_teams` (36) with `partner_id` = partner's pilot id and configurable `tag_status`; WebUI Teams
> tab re-enabled as the invite (server-checked, one-time code); matchmaker pair rule for worlds 5 / 21 / 22. See
> `server-sketch/ib-server/README.md`, `docs/SETUP.md` B5 (how a player invites a partner) and the TESTING.md
> online-tag checklist. The §5 table below describes upstream **before** that change. Step C (cross-server ids) is
> not done; the Python sketch `mms_server.py` still treats worlds 5 / 21 / 22 as ordinary worlds.

## 1. What the game supports

Sources: the official ac2ib howto/online page and the OB team_solo page, plus the exe strings and code paths below.

| Feature (JP name) | What it is | Exe path | Server dependency |
|---|---|---|---|
| 店内チーム (in-store team) | Partner on another cabinet in the same shop/LM | team-select option 1 → 0x140792a40 → 0x140791bc0 (LAN list) [H] | none for pairing: LAN/LM only. Then a normal team entry with `groups=[partner]` |
| オンラインタッグ (online tag) | Play with a **specific, pre-registered partner** in another shop (friend/group tag on vsmobile) | team-select option 2 → ctor 0x140791d30 → `CAcSeqWanTagEntry` type 0 [C] | card server must send the tag-team list; MMS must pair the two cabinets (world 5) |
| パートナー急募 (partner recruit) | Random online partner. Official site: Class Match only; the exe also has a casual variant | option 4 (+0x523) → ctor 0x140791e20 (from 0x14074e230 / 0x14079a3c0) → `CAcSeqWanTagEntry` type 1/2 [C] | MMS worlds 21 (casual) / 22 (ranked) |
| 即席チーム結成 (instant team) | After a **solo** sortie, ask the random teammate to stay as a team | `CAcSeqBttleFlow_FormInstantTeam`, `CAcSeqFormInstantTeamMediator` (Proc_Connection / WaitFormIntent / WaitStartIntent / Result) [H by name] | probably none: P2P between already-connected cabinets [M]. Results report `instant_team_flag` |
| Team break-up | `CAcSecPcbBreakUpTeam` [H by name] | — | — |
| Recruit failed | `CAcSecPcbWantedFailer` window [M] | — | MMS timeout/cancel |

So **"invite a specific player" = online tag**. There is no in-game code/ID entry. The partner relationship comes from the card server (`tag_teams`), and the cabinets then find each other through MMS world 5 using a shared pair key.

## 2. Mode codes and worlds

Debug name table fn 0x14087d5e0 (strings at file 0x179b2f0) [C]:

| code | name | | code | name |
|---|---|---|---|---|
| 0 | チーム結成 (team formation = online tag) | | 8/9 | イベント solo/team |
| 1 | 急募(カジュアル) (casual recruit) | | 0x0a/0x0b | クラス solo/team |
| 2 | 急募(ランク) (ranked recruit) | | 0x0c/0x0d | 店舗優先 solo/team |
| 3–7 | カスタム solo/team/mix(solo)/mix(team)/1on1 | | 0x0e | 店舗指定 |
| | | | 0x0f/0x10 | ミックス |
| | | | 0x11–0x15 | フェス solo/team/1on1/mix |

* Custom sub-type comes from Cpn+0x28: 1 イベント, 2 プライベート, 4 パブリック [C].
* **Correction:** play-mode 4 = Fes (codes 0x11–0x15) and play-mode 5 = Custom (codes 3–7) (0x140792dd0) [C]. `casual-shuffle-matching.md` had these swapped/merged.

Code → MMS world (table 0x140753330) [C]:

| code | world | attr2 | attr3 | attr4 | timeout | groups |
|---|---|---|---|---|---|---|
| 0 online tag | **5** | mgr+0x750 = **pair key** | subnet flag | map(+0x714): 1→1, 2→4, 3→5, 4→3, else 0 | **90 s** | none |
| 1 casual recruit | **21** | 0 | subnet flag | — | 150 s | none |
| 2 ranked recruit | **22** | mgr+0x734 (team class) | subnet flag | — | 150 s | none |

Codes 0–3 never send `groups` [C].

## 3. Flows

### 3.1 `CAcSeqWanTagEntry` (vt 0x1416b6990, ctor 0x1408262d0, Entry 0x140826470, StartStun 0x1408268c0)

This is a plain STUN → IssueNodeId → EntryMatching → WaitMatching sequence. `+0x4b0` holds the mode code [C].

**Online tag (type 0)** [C for the code, H for the field meanings]:
* Ctor 0x140791d30 is called from the team-select UI 0x140874c40 option 2. It sets `+0x4c8` = the selected tag-team id, taken from the list at `CAcSecPcbMatching+0x598` (entry +0x10), and sets `+0x530=1`, `+0x5ac=0`.
* Entry 0x140826470 finds the 0x70-byte record in player data +0x550 (lookup 0x1406c0a40) whose `+0` equals the tag id, and reads `B = rec+0x58`. B is probably `partner_id` [M/H].
* `A = [player+0x4c0]+8` = **own pilot_id**. It is the same value as mgr+0x720, which `CheckCommunication` (builder 0x140754740) sends as field 4 `pilot_id` [C].
* `attr2 = min(A, B)` and `+0x74c (leader) = A < B` [C].
* So both partners send the **same pair key**, and the cabinet with the lower pilot id becomes the leader. This only works if each side's `partner_id` equals the other side's real `pilot_id` [H].

**Partner recruit (types 1/2)** [C]:
* Ctor 0x140791e20 sets type = 2 if play-mode is 1 (class/ranked), else 1. It also sets `+0x530=1` and `+0x5ac=1`.
* Entry sets `+0x74c=1` and copies the vector at player+0x580+0x4d0 into mgr+0x758. That vector becomes `EntryMatching.bl_banapassport_am_ids`.
* The vector is probably `LoadCard.MobileUserGroup.partner_recruit_am_id_nglist` (25) [M].
* The builder 0x1407ba790 puts info+0xe0 into `bl_banapassport_am_ids` and info+0xf8 into `bl_loc_ids` (≤15) [C].
* How the leader is picked among two recruits after matching is **unknown** [L]. It may follow client order in CheckMatching or node id.

### 3.2 After a pair forms → team entry

* 0x140793c80 builds a team `CAcSeqWanEntry` when the pair flag `+0x57c` is set [C].
* Team code by play-mode: 1 → 0x0b, 2 → 0x10, custom → 4/6, fes → 0x12/0x15, default 0x0d [C].
* Param +0x3c → mgr+0x74c = `this+0x5ac` (leader flag). Kind params are {2, 400} [C].
* Line type (0x140754740) for team codes {4, 6, 9, 0xb, 0xd, 0xe, 0x10, 0x12, 0x15} [C]:
  * leader with partner → `PAIR_LEADER` (1)
  * leader without partner → `SOLO_WITH_CPU` (3)
  * not leader → `PAIR_MEMBER` (2)
* In-store and fixed pairs (`CAcSeqWanEntry`):
  * The **member** sends `WEAddEntryRequest` (401) to the leader over P2P from Proc_SendStunInfo (0x1408226b0) [C].
  * Only the **leader** runs SetEntryInfo/Entry (0x140822e20 → 0x140754f90 / 0x140754ed0) with `groups=[partner]` [C].
  * The leader then sends `WENoticeMatchingMemberRequest` (402) (0x140823ce0). Spread is 403. Handlers are registered in 0x140825290 [C].
* ⇒ **The member cabinet does not send its own EntryMatching for the team search** [H]. This answers open question 3 of `casual-shuffle-matching.md`. Our matchmaker already handles `groups=[partner]` units.

### 3.3 Instant team

The mediator states suggest a P2P intent exchange after the battle between two cabinets that are already connected [H by name]. It then probably reuses the pair flag and team entry above [M]. No MMS or card RPC specific to it was found [M]. The card server only gets `instant_team_flag` in results and `instant_team_command_messages` (LoadCard 33) for chat text.

## 4. Fields sent and expected

| Direction | Message / field | Notes |
|---|---|---|
| card → cab | `LoadCard.MobileUserGroup.tag_teams` (36, `TagTeamGroup{id, name, partner_id, tag_status(13, required), group_tag_point, partner_player_level_id, partner_*, on_compe_flag}`) | Most likely feeds the online-tag list [H]. The fill path into +0x598 (0x1407909c0 / 0x14078e520) is not fully traced. A `tag_status` filter is possible [L] |
| card → cab | `MobileUserGroup.group_id` (37), `PreLoadCard.LoadPlayer.tag_teams` (6) | Group tags [M] |
| card → cab | `MobileUserGroup.partner_recruit_am_id_nglist` (25) | Recruit NG list → `bl_banapassport_am_ids` [M] |
| cab → MMS | `EntryMatching` world 5/21/22, attr2/3/4 as in §2, own am_id, pcb_serial, loc_id, subnet_id (mgr+0x788, gated by 0x1406c0bb0), blacklists | [C] |
| MMS → cab | `CheckMatching` result for worlds 5/21/22 | **Shape unknown** [L]. Best guess: exactly 2 clients, the same `group_id`, consistent order, `MATCH_SUCCESS`. On timeout: cancel/failed, so no CPU fill |
| cab → card | `CheckCommunication.line_type`, `SaveVsmOnResult` (tag_team_id 24, partner 39, matching_tag 41, instant_team_flag 59, partner_recruit_flag 61), `SaveUserPlayResearchData` (is_online_tag 9, is_tag_formed 10, instant_team_flag 21, team_dissolution_flag 22, partner_recruit_flag 33) | Telemetry and results only |

Not used for invites:
* `MatchingSetting` (MMS 200) is never sent by the cabinet.
* `LoadMeetingCard` (409) is used only by the LM tournament.
* `LoadRoom` / `RegisterRoom` (1418/1419, `registration_code`) are custom rooms.
* `PreLoadCard.matching_tag` is for private rooms.

## 5. Our server: implemented vs stub (`ib-server-upstream/Server-Infinite`)

| Piece | State |
|---|---|
| Matchmaker worlds 5/21/22 | Listed as ordinary 4-seat worlds ("legacy-mode0", "mode1", "mode2", `Policy.None`), keyed by game/version/world/attr1 only. **attr2 (pair key) is ignored**, so any two online-tag cabinets could be paired. Two recruits wait for 4 seats and then only meet via FillAfter as a short room on **opposite** sides. Almost certainly wrong [H] |
| In-store / fixed pair team entry (`groups=[partner]`) | Works (same as normal team search) [H] |
| `MobileUserGroup.tag_teams` (36) | **Never filled** [C] |
| `PilotDataGroup.TagTeams` | `[ProtoIgnore]` (Game.cs ~6734), so `AppendTeamCommand` output is never sent [C] |
| `online_tag_info` / `OnlinePairCommand` / `QuickTagCommand` | XB/OB-era message, `[ProtoIgnore]` (Game.cs ~7153). Not in IB [C] |
| `TagTeamGroupBuilder` | Sets `TagStatus = 0` [C] |
| `LoadMeetingCard` | Fills tag_teams (LM tournament only) |
| WebUI | Team creation by partner id plus `DistinctTeamFormationToken` (CheckPlayerExistenceResultCommandHandler). This is effectively a friend-code invite already [C] |
| Ids | `pilot_id` = `am_id` = `cardProfile.Id` (PreLoadPlayerBasicInformationCommand.cs:21, PreLoadCardQueryHandler.cs:169). **These are DB row ids, so they collide across card servers** [C] |

Net result: the online-tag option almost certainly shows an empty list [H]. Recruit can't pair two people properly [H].

## 6. Recommended design

### Step A: card server (per card server, small)
1. Fill `LoadCard.MobileUserGroup.tag_teams` (36) from the existing `TagTeamData`: `id` = team id, `name`, `partner_id` = **the partner's pilot_id**, partner level/class fields, and `group_tag_point`.
2. `tag_status`: try 0 first, then 1 if the list stays empty. Keep it configurable.
3. Reuse the WebUI team-creation flow (partner id + `DistinctTeamFormationToken`) as the **invite**: A creates a code, and B redeems it to create the team on both cards.

### Step B: MMS "pair" policy for worlds 5/21/22 (universal matchmaker)
* Room size 2 for all three. Both clients go in the same group (group_id 0). Never use FillAfter/short rooms or CPU fill. Honor `bl_banapassport_am_ids` / `bl_loc_ids` and never pair a cabinet with itself. Use the cabinet's own timeouts (90 s for world 5, 150 s otherwise), then cancel.
* **World 5 (online tag):** hard key `(game, version, attr1, attr2)`. Only identical pair keys match. Optional: also check an invite registry (am_id A ↔ B) to defend against key collisions.
* **World 21:** FIFO random pool.
* **World 22:** keyed by team class (attr2), with optional widening.
* Return the two clients in a deterministic order (e.g. lower node id first) so both cabinets see the same list. That covers the case where the recruit leader is chosen by order.
* After this the cabinets do their own P2P pairing, and the leader starts a normal team search with `groups=[partner]`. The existing team logic already handles that across shops/LMs.

### Step C: cross-card-server invites (only if partners use different card servers)
* The pair key `min(pilot ids)` and the leader rule `own < partner` only work if both sides agree on the ids. Card-server DB ids collide (both servers start at 1).
* Option 1 (recommended): give each card server a disjoint id range (e.g. `pilot_id = serverPrefix·10⁶ + Id`). Do the same for am_id so blacklists and MMR stop colliding. Store the partner's real global id in `partner_id` at invite redemption, via a tiny shared invite service (code → {server, global pilot id, name}).
* Option 2: the MMS invite registry pairs world-5 entries by am_id and ignores attr2. The card servers then pick `partner_id` values only to get one leader and one member. This is more fragile.

### Effort / risk / confidence
* Effort:
  * Step B: about 0.5–1 day including fake-cabinet tests.
  * Step A: about 0.5 day.
  * Step C: about 1 day.
  * Plus at least one live session with 2 cabinets: online tag both ways, recruit casual and ranked, recruit timeout, and instant team.
* Risks:
  1. The CheckMatching shape for pair worlds is unknown (count, group_ids, order) [L].
  2. `tag_status` semantics / list filter [L].
  3. `rec+0x58` = partner_id [M/H].
  4. How the recruit leader is chosen [L].
  5. Cross-server id collisions (certain unless Step C).
* Confidence that A+B make online tag work on one card server: **medium**. Recruit: **medium-low** until the CheckMatching shape is confirmed live.

## 7. Test plan (when available)
1. Fake cabinet: world 5 entries with equal and unequal attr2 → pair only on equal. World 21 FIFO. World 22 class key. NG list respected. Timeout → cancel. No short rooms.
2. Live, same card server: create a tag via WebUI, check the online-tag list shows it (vary tag_status), sortie both. The log should show one EntryMatching per side in world 5 and then a single team EntryMatching from the leader with `groups=[partner]`.
3. Live recruit: two cabinets choose 急募, confirm they team up. Check `line_type` PAIR_LEADER/MEMBER in CheckCommunication.
4. Instant team after a solo win: confirm no new server RPCs are needed.

## 8. Open questions
* Trace 0x1407909c0 / 0x14078e520 (fills +0x598) for a `tag_status` filter.
* What CheckMatching for 5/21/22 must contain.
* The recruit leader rule.
* How the online-tag member reaches the leader (expected: WE 401 over P2P after the pair match).
