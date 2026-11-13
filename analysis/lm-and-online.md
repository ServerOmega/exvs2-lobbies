# LM and non-LM players on one matchmaking server

> **Goal: ONE universal matchmaking server that everyone connects to.** That means players at a store with a
> Live Monitor (LM), players without an LM (home / standalone), and players at many different LMs, all in the
> same server and able to match each other wherever the network allows. No separate server per store or group.

> ⚠️ Nothing here was tested with the real game. Tags: **[C]** checked in `vsac29_Release.exe` (static
> disassembly, 2026-11-13) or in the EXVS2-POC source (commit 2343795) · **[M]** likely, from code reading ·
> **[L]** inferred / not traced. Box tests used fake cabinets only (fake serials and card ids, documentation IPs).

"LM" here means the **Live Monitor**, the store's master machine for in-store (LAN) play (`CAcSeqLmRoot`,
`CAcSeqLmFaciliator`). It is the same exe started in the LM role.

## 1. Answers
| Question | Answer |
|---|---|
| Can several LMs (different stores / LANs) use the same matchmaking server at once? | **Yes.** The LM never talks to the MMS; each cabinet does, over plain HTTP (§2.2). The server sees cabinets, not LMs, so any number of stores can connect. Two fixes were needed for that to work (§3). |
| Can LM players and non-LM players be matched together? | **Yes, in the online modes** (casual / free / mix / ranked worlds), as long as they can reach each other over UDP (same "network realm", §3.2). The box test put store, home and other-store players in the same rooms (§4). |
| Can an in-store pair from an LM team up and fight online players? | **Yes on the server side.** A team sortie sends the partner in `groups` [C]. The server keeps that pair on one side and fills the other side with anyone (another pair or two solos). Whether the partner is found through the LM is not traced [L]. |
| What can't be crossed? | (1) Players the network can't connect: e.g. a Radmin-overlay player vs an internet player (§3.2, workaround §5). (2) **In-store match** (worlds 15/16) is per shop by design: the cabinet sends a shop hash, so only same-shop players meet (§3.3). (3) Cabinets left on an LM LAN battleMode (≠ 0) never contact the MMS (§2.1). |

## 2. What the exe does
### 2.1 LAN (LM) vs online is per setting entry [C]
* `CAcSecPcbMatching` type 1 = LAN/in-store via the store's P2P terminal list; type 2 = WAN (`CAcSeqWanEntry` /
  `CAcSeqWanTagEntry`). Type 2 only when the active `testmode_pcb.json` setting entry has `battleMode: 0`
  (matchmaking.md §7.1–7.2) [C].
* In a store, the terminals' TestMode data is pushed by the LM (`ULGRequestTestModeData` / `ULGNoticeTestModeData`
  RPCs exist) [C for the RPC names], so for LM-attached cabinets **battleMode is probably set on the LM**
  (`testmode_lm.json`) [L].
### 2.2 The LM never contacts the MMS [C]
* The WAN manager (`CAcSeqWanMatchingManager`, ctor 0x140752020) is created in exactly one place: 0x1406fd860
  (`CAcSeqPcbRoot::Proc_CreateWanMatchingManager`), called only from the PCB root (0x1406fd0b0) [C].
  The LM root doesn't create one, so every cabinet runs its own STUN + IssueNodeId + Entry/Check against the MMS.
* LM roles: `CLIENT_TYPE` in `bootparam.bin` 1/3 → terminal (kind 1, index 0..15), 2/4 → LM (kind 2). Terminal
  value 101 = main LM, 100 = sub LM. The main LM uses UDP 49000..49015 for its 16 terminals (multi-instance.md §2.1) [C].
* LM ↔ terminal RPCs are `ULG*`: `EntryMatching`, `DecideTeam`, `EntryCard`, `EntryTarget`, `SpreadInfo`,
  `StartInGame`, `RequestLMInfo/Schedule`, `NoticeTournamentState`, blacklists, replay/live... [C names]. These are
  the in-store path. The 16 is `totalConnectionNum` with the pairing table 0↔1, 2↔3, … (matchmaking.md §3) [C table].
* RegisterPcb `lm_ip_addresses` different from the cabinet's own IP are handed to 0x1407329a0 (LM addresses) [M].
  The card server doesn't need to send them for online play [M].
### 2.3 What a cabinet sends the MMS [C]
* `myclient`: node_id, **pcb_serial**, **loc_id**, pref_code, STUN global ip:port, adapter local ip:port, NAT
  types; `subnet_id` only behind a gate that is normally off (0x1406c0bb0) [C gate, M normally-off].
* `groups`: exactly one: the partner cabinet when `mgr+0x95c` is set (partner block at mgr+0x8e0: node, ids,
  global/local addr, pref, serial +0x934, loc +0x941), else the CPU stand-in `PCB00000NPC` (0x1407538bc…) [C].
  No direct writer of the partner block was found (probably filled by a struct copy), so where it comes from (LAN signalling from the LM / store
  pair, or an online tag) is **not traced** [L]. When a pair is already formed, the PCB facilitator 0x14074e230
  builds `CAcSeqWanTagEntry` (0x140791e20) [C].
* Peer address: if both STUN global IPs are equal, the cabinet dials the peer's **local** ip:port (0x140794590) [C].
  For store cabinets behind one router this means they talk over the store LAN, with no hairpin NAT needed.
### 2.4 Identity values are not unique across stores [C in POC source]
* POC `config.ini` `serial` defaults to **`0001`** (prefixed per version), so every install that keeps the default
  has the **same pcb_serial**. A store's terminals are usually 0001, 0002, ..., so terminal 1 of every LM collides too.
* POC AmAuth emulation hardcodes `place_id = "JPN1"` and the shop name, so **loc_id is probably the same for
  everyone** [M: loc_id = place_id not traced]. That means loc_id can't tell stores apart, and the in-store shop hash
  (last 4 chars of loc_id) is the same for every POC install [M].

## 3. What the server does now (both servers, 2026-11-13)
### 3.1 Same cabinet = serial + public IP (bug fix)
The "one queue slot per cabinet" rule (load-test fix) keyed on `pcb_serial` alone. With the POC defaults, a new
entry from *another* player with serial 0001 dropped the waiting entry ("same cabinet entered again"). Now a
cabinet is the same only if the **serial and the STUN global IP** match. Same store = one public IP, but its
terminals have different serials. Different stores / homes have different public IPs. If either side has no STUN
result, it falls back to the serial only (old behaviour).
Risk [M]: this assumes the leader's copy of its partner's address (in `groups`) has the same global IP as the partner's own
entry. True for a store pair (one router), and the leader learns it from the partner's own STUN run [L].
### 3.2 Network realms (who can reach whom)
Each player's STUN global IP is put in a realm: `radmin` 26/8, `hamachi` 25/8, `cgnat-overlay` 100.64/10, `lan`
(10/8, 172.16/12, 192.168/16, 127/8), else `internet`. Players in **different realms are never put in one room**,
because they can't reach each other: e.g. a cabinet whose STUN went over Radmin has only a 26.x address, which an
internet player can't dial. Within a realm, everyone shares **one pool per mode**, whatever store, LM or home
they play from. Config: C# `OnlineMatching.NetworkRealms` (`""` defaults, `"off"`, or `"name=cidr,..."`); Python
`--realms`. NET log lines show `realm=` (networking-issues.md §6).
### 3.3 Grouping rules (unchanged, for reference)
| What | Rule |
|---|---|
| Mode | one queue per game id + version + world (mode) + attr1 |
| Ranked (13/14) | same class; level / MMR bands widen with wait |
| In-store (15/16), shop-setting (17), tag worlds | attr2 must be equal. For 15/16 attr2 = shop hash from loc_id, so only same-shop players. With the POC's fixed loc_id **every POC install is the "same shop"** [M] |
| Casual / mix (18–20, 23, 25) | attr2 soft (preferred for 15 s, then mixed) |
| Store pair (team sortie) | always on one side; never split |
| Blacklists | `bl_banapassport_am_ids`, `bl_loc_ids` (if the card server's LoadBlackList fills them) |
| Same store opponents | allowed; they dial each other's LAN address (§2.3) |

## 4. Box test: 14 fake players on one server (`server-sketch/loadtest/lm_mix.py`)
Groups: **LM-A** = 1 store, 4 cabinets on one public IP (A1+A2 enter as an in-store pair, A3/A4 solo).
**HOME** = 4 players without an LM, all with the POC defaults (serial 0001, loc JPN1, local 192.168.1.10), each on
its own public IP. **LM-B..E** = 4 different stores with one cabinet each (all serial 0001). **RADMIN** = 2 players
whose STUN result is a 26.x overlay address. Everyone picks Mix Match (world 23) and arrives interleaved.

| Build | Result |
|---|---|
| C# before (serial-only rule) | **3/14 matched**; 10 × "same cabinet entered again" (players with serial 0001 kicked each other out) |
| C# after | **14/14 matched** in 4 rooms, 0 wrong drops, invariants OK |
| Python after | **14/14 matched** in 4 rooms, invariants OK |

C# after (abridged):
```
room 1: team 0 HOME/1 + LM-B/1   vs  team 1 LM-A/1 + LM-A/2 (store pair, dial each other over the store LAN)
room 2: team 0 HOME/2 + LM-C/1   vs  team 1 LM-A/3 + HOME/3
room 3: team 0 LM-D/1 + LM-E/1   vs  team 1 LM-A/4 + HOME/4
room 4: RADMIN/1 vs RADMIN/2 (1v1 after FillAfterSeconds: no reachable partners outside the overlay)
matched 14/14 players in 4 rooms; invariants OK
```
Arriving group by group (`--no-interleave`) gives rooms of one group each (FIFO); both are valid.
Regression checks after the change: unit tests C# 33 / Python 36 pass, disconnect probes 14/14 (C#) and 13/13
(Python), 100-cabinet load test with 0 violations. One probe needed a harness fix (it reported the partner's
address differently from the partner's own entries; see §3.1 risk).

Run:
```bash
python3 server-sketch/python/mms_server.py --port 5000 --fill-after 5 &
python3 server-sketch/loadtest/lm_mix.py --url http://127.0.0.1:5000/mms
# C#: CardServerConfig__OnlineMatching__FillAfterSeconds=5 dotnet Server-Infinite.dll, then --url http://127.0.0.1:28080/match
```

## 5. Where cross-group play is blocked, and the workaround
| Blocker | Why | Workaround |
|---|---|---|
| Cabinet on an LM LAN battleMode (≠ 0) | takes the in-store path, never calls the MMS [C] | set `battleMode: 0` for online play (on the LM's pushed settings for store cabinets [L]). In-store LAN play still works through the LM in other setting entries / time slots [M] |
| Overlay (Radmin/Hamachi/ZeroTier) players vs internet players | an overlay STUN result is only reachable on the overlay | one STUN path for everybody: **internet STUN + each cabinet bound to its real NIC** (overlay only for the LM LAN), or **everybody on one overlay with the STUN host on it**. A TURN relay might bridge both, but whether the game uses relayed addresses is not traced [L] (networking-issues.md §6.1) |
| In-store match across stores | the cabinet sends a shop hash; in-store is per shop by design | use the online modes (casual / mix / ranked) for cross-store play. If the POC loc_id really is fixed, in-store mode already pools every POC player together [M] |
| Two symmetric-NAT / CGNAT players | hole punching fails | port-forward UDP 48000(+terminal), or an overlay with relays |

## 6. To verify in the real game
1. With `battleMode: 0` on an LM-attached cabinet: does it still use the LM for anything during online matching
   (card entry, team decision)? Does the in-store partner end up in `groups`? Keep the `NET entry` lines of both cabinets.
2. The loc_id a POC cabinet sends (one IssueNodeId / Entry log line): is it the same on two different installs?
3. Two stores (or two PCs on different networks) with the default serial 0001: both matched, no
   "same cabinet entered again" in the log.
4. Store pair vs online players: MATCH-NET shows `local same-NAT` for the pair, and the battle starts.
5. In-store match (worlds 15/16) from two different installs: matched together (same POC loc) or not?

## 7. Open questions for the user
* Does "LM" mean the Live Monitor machine (this doc), or the community "LM" LAN over Radmin/N2N? The answer is the
  same server design, but the Radmin case hits the realm rule (§5).
* At a store, is battleMode set on the LM or on each cabinet in your setup?
* Should in-store match (worlds 15/16) stay per shop, or would you like it as one big cross-store pool? The server
  could key it by public IP instead of the shop hash.
