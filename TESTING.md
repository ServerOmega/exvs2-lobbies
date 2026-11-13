# Test checklist

Everything here is **untested in the real game**. Tick items off as they're verified, and note results/captures next to them.

## Setup (do first)
- [ ] Back up `testmode_pcb.json`, then set `battleMode: 0` in the active entry with `_re/tools/svd1.py`; confirm the game switches to online (WAN) matching and no longer uses the LM
- [ ] Confirm the game binds to the correct network adapter / IP (currently Radmin VPN); use the hook's `IpAddress=` — without it the exe skips adapters whose name contains "2"/"Loopback" ([analysis/networking-issues.md](analysis/networking-issues.md))
- [ ] Windows: no leftover Block rules for `vsac29_Release.exe` in wf.msc; game/overlay adapter set to Private
- [ ] First real entry: read the `NET entry` line for each player (`local` = the hook's IP, `global` from STUN, no `stun-missing`, no unexpected `MISMATCH`). See [networking-issues.md §6](analysis/networking-issues.md#6-reading-the-network-log)
- [ ] Get a card server whose RegisterPcb returns the match server `uri` plus a SRV_STUN entry; confirm IssueNodeId hits our server — build the patched EXVS2-IB-Server from [`server-sketch/ib-server`](server-sketch/ib-server/README.md) (box-tested with fake cabinets only)

## Basic matchmaking
- [x] Box load test with 100 / 200 / 500 fake cabinets against both matchmakers — no invariant violations after fixes ([analysis/load-test.md](analysis/load-test.md)); fake cabinets only
- [x] Box disconnect/rejoin test (14 probes + 150-person run with mass drop and server restart) — 6 bugs fixed, 14/14 probes pass on both servers ([analysis/disconnect-test.md](analysis/disconnect-test.md)); fake cabinets only
- [ ] Real game: what the cabinet does on MATCH_CANCELED vs ERR_MATCH_NOENTRY, and when a room member drops right after matching
- [ ] EntryMatching + CheckMatching polling reaches the matchmaker (built-in `/match` or `mms_server.py`; capture with tcpdump)
- [ ] A matched room actually starts a battle; capture the cabinet-to-cabinet (hole-punch / P2P) packet format. Keep the `MATCH-NET` line for that room (which address each pair dialled)
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
- [ ] Play modes 1–6 land in separate queues; `battleMode` values other than 0 still use the LM path

## Casual / shuffle
- [ ] 4 solo cabinets start a 2v2 using the server-assigned teams (`group_id`)
- [ ] 1v1 / 2v1 rooms: does the game fill empty seats with CPUs, reject, or hang?
- [ ] Fixed pair: does the partner cabinet send its own entry, only poll, or neither?
- [ ] Record the in-game menu names of play modes 4, 5, 6 and their sub-modes
- [ ] Team sortie with a CPU partner: is a result that omits the CPU entry accepted?

## Ranked (Class Match)
- [ ] Class Match menu appears with our `LoadClassMatch` tables
- [ ] Which class ID values IB uses; does class 0 break anything?
- [ ] How opponents' rank/grade is exchanged and displayed (P2P capture)
- [ ] After a match, `SaveVsmOnResult` uploads the new rate and the next card read (`PreLoadCard`) shows it

## Lobbies / Custom Match
- [ ] Press Custom Match with the LM running and log what the game requests
- [ ] Implement LoadRoom / RegisterRoom handlers and check whether rooms appear

## Housekeeping
- [ ] Log-capture script for the user's launch method
