# Test checklist

Everything here is **untested in the real game**. Tick items off as they're verified, and note results/captures next to them.

## Setup (do first)
- [ ] Back up `testmode_pcb.json`, then set `battleMode: 0` in the active entry with `_re/tools/svd1.py`; confirm the game switches to online (WAN) matching and no longer uses the LM
- [ ] Confirm the game binds to the correct network adapter / IP (currently Radmin VPN)
- [ ] Get a card server whose RegisterPcb returns the match server `uri` plus a SRV_STUN entry; confirm IssueNodeId hits our server — build the patched EXVS2-IB-Server from [`server-sketch/ib-server`](server-sketch/ib-server/README.md) (box-tested with fake cabinets only)

## Basic matchmaking
- [x] Box load test with 100 / 200 / 500 fake cabinets against both matchmakers — no invariant violations after fixes ([analysis/load-test.md](analysis/load-test.md)); fake cabinets only
- [ ] EntryMatching + CheckMatching polling reaches the matchmaker (built-in `/match` or `mms_server.py`; capture with tcpdump)
- [ ] A matched room actually starts a battle; capture the cabinet-to-cabinet (hole-punch / P2P) packet format
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
