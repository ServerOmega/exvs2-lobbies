# Test checklist

Tick items off as they're verified, and note results/captures next to them. First real-game test: **2026-11-13**, two cabinets on one PC — see [Real-game results](#real-game-results-2026-11-13) and [analysis/real-game-test-2026-11-13.md](analysis/real-game-test-2026-11-13.md).

## Setup (do first)
- [x] Back up `testmode_pcb.json`, then set `battleMode: 0` in the active entry with `_re/tools/svd1.py`; confirm the game switches to online (WAN) matching and no longer uses the LM — **confirmed 2026-11-13**
- [ ] Confirm the game binds to the correct network adapter / IP (currently Radmin VPN); use the hook's `IpAddress=` — without it the exe skips adapters whose name contains "2"/"Loopback" ([analysis/networking-issues.md](analysis/networking-issues.md))
- [ ] Windows: no leftover Block rules for `vsac29_Release.exe` in wf.msc; game/overlay adapter set to Private
- [ ] First real entry: read the `NET entry` line for each player (`local` = the hook's IP, `global` from STUN, no `stun-missing`, no unexpected `MISMATCH`). See [networking-issues.md §6](analysis/networking-issues.md#6-reading-the-network-log)
- [x] Get a card server whose RegisterPcb returns the match server `uri` plus a SRV_STUN entry; confirm IssueNodeId hits our server — patched EXVS2-IB-Server from [`server-sketch/ib-server`](server-sketch/ib-server/README.md), built-in STUN, 2026-11-13 ([results](analysis/real-game-test-2026-11-13.md))

## Basic matchmaking
- [x] Box load test with 100 / 200 / 500 fake cabinets against both matchmakers — no invariant violations after fixes ([analysis/load-test.md](analysis/load-test.md)); fake cabinets only
- [x] Box disconnect/rejoin test (14 probes + 150-person run with mass drop and server restart) — 6 bugs fixed, 14/14 probes pass on both servers ([analysis/disconnect-test.md](analysis/disconnect-test.md)); fake cabinets only
- [ ] Real game: what the cabinet does on MATCH_CANCELED vs ERR_MATCH_NOENTRY, and when a room member drops right after matching
- [x] EntryMatching + CheckMatching polling reaches the matchmaker (built-in `/match`; 2026-11-13). `mms_server.py` not tried in game
- [x] A matched room actually starts a battle (two cabinets on one PC, 2026-11-13; full matches in Mix Match and Class Match solo)
- [ ] Capture the cabinet-to-cabinet (hole-punch / P2P) packet format between **two machines**; keep the `MATCH-NET` line for that room
- [ ] Results screen hangs after every 2-cabinet versus match (also in local LM mode, no matchmaker): retest with cab2 in Windows Sandbox and on two real PCs
- [x] Box: one server for LM-store, home and multi-LM players (`server-sketch/loadtest/lm_mix.py`, 14 fake players): 14/14 matched on both servers after the serial+IP fix (3/14 before). Fake cabinets only ([analysis/lm-and-online.md](analysis/lm-and-online.md) §4)
- [ ] Real game, LM store: find **where battleMode is set**: on the LM machine (`testmode_lm.json` / LM test menu, pushed to the cabinets) or on each cabinet (`testmode_pcb.json`)? Which file / menu, and does a cabinet's own value survive an LM sync? Use backups and `svd1.py`; no EXIT & SAVE
- [ ] Real game, LM store: what the **LM machine itself** does when battleMode is 0 (still in-store/LAN lobby? stays idle? any HTTP to the card server or MMS? capture with tcpdump)
- [ ] Real game: in-store match (world 15/16) from two different stores never meets; one store's cabinets do (server log `entry instore-... key=...|ip:<public IP>`)
- [x] Box: in-store match stays per shop although all stores send shop code JPN1 (`lm_mix.py --case instore`: 3 stores → 3 separate rooms; the same cabinets mix in Mix Match). Fake cabinets only
- [ ] Real game, LM store: with `battleMode: 0`, does an LM-attached cabinet go online, and does its in-store partner show up in `groups` (team sortie)? Keep both cabinets' `NET entry` lines
- [ ] Real game: loc_id and pcb_serial sent by two different POC installs (same `JPN1`/`0001`?). Look in the IssueNodeId / entry log
- [ ] Real game: two players on different networks with the default serial both match (no "same cabinet entered again" in the log)
- [ ] Real game: store pair vs online players: MATCH-NET shows `local same-NAT` for the pair and the battle starts
- [x] Box: IP/NAT log lines on both servers (`NET`, `NET-WARN`, `MATCH-NET`, drop reasons). Unit tests plus a smoke run with fake cabinets and documentation IPs
- [ ] Real game, LM over VPN + online over internet ([analysis/lm-over-vpn-split.md](analysis/lm-over-vpn-split.md) §3): cabinet with POC `DisableSocketHook = true`, `InterfaceName` = VPN adapter, VPN without default route (`route print -4`). Does it boot past Find LM / Connect LM? If not, capture `udp.port == 49000` on the VPN adapter (broadcast leaving? LM reply?) and retry with the VPN adapter's metric set to 1
- [ ] Real game, same setup: `NET entry` shows `local` = VPN IP, `global` = the internet public IP, realm `internet`; a match against a home (no-VPN) player starts and finishes
- [ ] Real game, same setup: during an online battle, is any traffic sent to the LM's VPN IP? Does a 30 s VPN outage drop the match?
- [ ] Real game: two cabinets of one LM in the same online room (same NAT) dial each other's VPN IP (`MATCH-NET` local same-NAT); battle starts
- [ ] Real game: LM over Tailscale (no broadcast). Expected to fail at Find LM; confirm
- [x] Per-mode queues: Mix Match (world 23) and Class Match solo (world 13) stay separate (2026-11-13); other modes not yet tried
- [x] `battleMode` other than 0 still uses the LM path (local LM matches work, 2026-11-13)
- [x] In-game cancel while searching sends CancelMatching and leaves the queue (2026-11-13)
- [x] Split setup: cabinet's own card server ≠ matchmaker (`MatchUrl` → main server); the two cabinets matched (2026-11-13)
- [x] Built-in STUN on a multi-homed Windows server PC: replies must leave from `StunHost` (fixed: bind to it), 2026-11-13

## Casual / shuffle
- [ ] 4 solo cabinets start a 2v2 using the server-assigned teams (`group_id`)
- [x] 1v1 / 2v1 rooms: the game plays them; the CPU partner is added by each cabinet locally (2026-11-13). `CpuStandInSeats` (server lists CPU seats) also accepted but changes nothing visible; off by default
- [x] `FillAfterSeconds`: 30 too slow for 2 players, 3 fine on a LAN; default now 15
- [ ] Fixed pair: does the partner cabinet send its own entry, only poll, or neither?
- [ ] Record the in-game menu names of play modes 4, 5, 6 and their sub-modes (static analysis: 4 = Fes, 5 = Custom; 6 unknown)
- [ ] Team sortie with a CPU partner: is a result that omits the CPU entry accepted?

## Ranked (Class Match)
- [ ] Class Match menu appears with our `LoadClassMatch` tables
- [ ] Which class ID values IB uses; does class 0 break anything?
- [ ] How opponents' rank/grade is exchanged and displayed (P2P capture)
- [x] After a match, `SaveVsmOnResult` uploads the new rate (HTTP 200 on each cabinet's own card server, 2026-11-13); badge exp went negative after a loss → clamped at 0
- [ ] Next card read (`PreLoadCard`) shows the stored rate/grade in the Class Match screen

## Online tag / partner recruit ([analysis/partner-invites.md](analysis/partner-invites.md))
Box, fake cabinets + fake cards (2026-11-13): 15 unit tests + `server-sketch/loadtest/online_tag_e2e.py` 28/28 —
everything below the line is for the **real game**. Both cabinets on the **same card server**; server built from
the online-tag patch. Keep the server log lines named in each item.
- [x] Box: WebUI invite (user id + code; wrong / self / duplicate / reused code refused; code rotates), LoadCard tag_teams on both partners, world-5 pairing, mismatched keys + timeout, two tag pairs → 2v2, casual recruit pair, ranked recruit by class
- [ ] Create a tag team in the WebUI (Customize → Teams: partner's User ID + Invitation Code → ADD); both cards show it in the WebUI
- [ ] Insert both cards: log `LoadCard online tag: CardId=… tag_teams=1 tag_status=0 [team T partner P key K]` for each
- [ ] In the game, team sortie → **online tag** shows the team. If the list is empty: set `OnlineTag.TagStatus: 1`, restart, re-insert; record which value works
- [ ] Both pick the team: one `entry online-tag … key=K` per cabinet with the **same K = lower pilot id**; then `MATCH room=… online-tag pair [n1,n2] key=K am=[a,b]` and no `TAG-WARN`. Note whether am_id equals the pilot id
- [ ] After the pair room: do the cabinets connect to each other (P2P) and show "team formed"? Or do they reject the 2-client CheckMatching (record what the screen says, and capture CheckMatching with Wireshark)
- [ ] Then exactly **one** team entry from the leader (lower pilot id) with the partner in `groups` (`entry mix-match nodes=[leader,member] slots=2` or class-team), and the member only polls. Does the member re-run IssueNodeId first (new node id)?
- [ ] That team then matches (vs another team or 2 solos; or 1v1-style after `FillAfterSeconds`) and the battle starts; `SaveVsmOnResult` carries `tag_team_id` / partner
- [ ] Only one partner searches: after 90 s the cabinet gets `MATCH_CANCELED` (`drop … reason=matching timeout`); what does the game show (CAcSecPcbWantedFailer)?
- [ ] One partner cancels while waiting: the other keeps waiting until its own 90 s; no room with a stranger
- [ ] Two different tag teams searching at once never mix (different `key=`)
- [ ] Results screen after a tag match (same hang as other 2-cabinet matches on one PC?)
- [ ] Partner recruit (急募) casual: two cabinets → `MATCH … recruit-casual pair`; who becomes leader (first listed = lower node id?); line_type PAIR_LEADER / PAIR_MEMBER in CheckCommunication
- [ ] Partner recruit ranked (Class Match): same class pairs (`recruit-ranked … key=…|class`), different classes don't
- [ ] Instant team (即席チーム) after a solo win: confirm no new server request is needed
- [ ] Later: tag partners on **different** card servers (needs globally unique pilot ids, partner-invites.md §6 Step C)

## Lobbies / Custom Match
- [ ] Press Custom Match with the LM running and log what the game requests
- [ ] Implement LoadRoom / RegisterRoom handlers and check whether rooms appear

## Housekeeping
- [ ] Log-capture script for the user's launch method

## Real-game results (2026-11-13)
Times PT. Two cabinets (POC + SnowLauncher) on one Windows 11 PC, patched card server with in-process matchmaker
and built-in STUN. Details and the two-cabinets-on-one-PC recipe: [analysis/real-game-test-2026-11-13.md](analysis/real-game-test-2026-11-13.md).

**Works**
* Online queueing via `battleMode: 0` + built-in STUN; RegisterPcb / IssueNodeId / Entry / Check / Cancel.
* Split setup: cab1's card server was a second server instance whose `MatchUrl` pointed at the main matchmaker.
* Two cabinets matched and played full matches in Mix Match and Class Match solo; per-mode queues; in-game cancel.
* Results saved to each cabinet's own card server (class-match rate, badge).

**Fixed during the test**
* Built-in STUN on a multi-homed PC answered from the wrong source IP (the N2N adapter's) when bound to 0.0.0.0;
  the game dropped those replies → now bound to `StunHost`.
* Badge exp went 0 → −20 after a loss → clamped at 0.
* `FillAfterSeconds` 30 felt slow; 3 works on a LAN → default 15 (10–15 recommended for a public server).

**Open: results-screen hang after every 2-cabinet versus match**
* Servers and network are fine: captures show every message answered and the cabinets staying in sync; both card
  servers answered `SaveVsmOnResult` with 200. The games recover by themselves after a few minutes.
* Holding Start does not clear it. Server-side CPU stand-in seats were sent but did not fix it.
* It **also happens in local LM mode with no matchmaker**, with two LMs and with one shared LM.
* A solo route battle vs CPU does **not** hang.
* Conclusion: not caused by the matchmaking server; most likely two game instances on one OS interfering.
  Pending: Windows Sandbox test (cab2 in the Sandbox, own network stack) and a real two-PC test.
