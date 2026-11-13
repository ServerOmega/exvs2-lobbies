# exvs2-lobbies — notes (index)

> **2026-11-13:** this box's copy of the project was lost between sessions (binary, `tools/`,
> most `analysis/` files, the original README). This README was re-created as an index; the
> original contained the full history (proto extraction, IB-Server survey, LM Custom Match gates,
> testmode_lm.json edit, network optimizations, debugging notes). Those files must be restored
> from the user's PC / a backup if needed — they were **not** rewritten from memory.

Goal: MBON-style lobbies / large-pool online play for EXVS2 Infinite Boost.

## Present on the box now
- `analysis/matchmaking.md` — WAN/MMS + STUN + "16-player" analysis (restored) + 2026-11-13 follow-up.
- `analysis/matchmaking-server-design.md` — universal matchmaking server design.
- `analysis/proto/from_exe/matchmaking_server_nue.proto` — mms schema (restored verbatim).
- `server-sketch/` — runnable Python prototype (tested with simulated cabinets), C# IB-Server-style sketch, coturn config.

## Key results (short)
- Online matching URL = RegisterPcb SRV_MATCH `uri` (full URL); STUN entry starts online setup; IssueNodeId must return >= 2 unique ids; CheckMatching returns all 4 clients incl. self, group_id = team.
- The 16 is the LAN/store model (settingFile.totalConnectionNum=16, LM pairing table), not WAN.
- No exe patches applied. Patch candidates in `analysis/matchmaking.md` §5 and §7.7 (none needed).
- **WAN vs LAN** (§7.1–7.2): setter 0x140794360 writes +0x528; type = 2 (WAN/MMS) only when the active
  `testmode_pcb.json` setting entry has `battleMode: 0`; every other battleMode → in-store LAN.
- Play mode 1..6 (`[0x14257b7a0]+0x4cc`) → WAN mode code 0x03..0x15 (§7.3).
- NAT test failure does **not** block entry (§7.4). request_id/type are **not** checked; only HTTP 200 + `code==0` (§7.5).

## Restored 2026-11-13
- `binaries/vsac29_Release.exe` (md5 a5cdf4cf5a0922872ced752865424c85, copied back with user approval).
- `tools/venv` (capstone, pefile, numpy) + `tools/re/` (`relib.py`, `build_xrefs.py`→`xrefs.pkl`, `scan_disp.py`,
  `riprefs.py` brute rip-relative search). Run with `tools/venv/bin/python`.

## Missing on the box (needs re-copy)
- `analysis/ghidra_rooms.md`,
  `analysis/server/implementation.md`, `analysis/network-optimizations.md`, `analysis/debugging.md`,
  `analysis/proto/from_exe/game_server_nue.proto`, `analysis/proto/from_ib_server_csharp/`.

## Open
- Names of battleMode values (read testmode_pcb.json at home); exvs `OnlineMatchingMode` ↔ play-mode 1..6; hole-punch packet format (capture live).
- Implement LoadRoom / RegisterRoom in an IB-Server source build (earlier plan).
