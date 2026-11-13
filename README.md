# exvs2-lobbies

> ⚠️ **Experimental — work in progress. This does not function yet.**
>
> Nothing here is a working online service. The matchmaking server is an untested sketch,
> the C# handlers are uncompiled, and the in-game WAN path has not been tried on a real cabinet.
> Do not expect to queue up and play from this repository today.

See [TESTING.md](TESTING.md) for the checklist of things that still need a real-game test.

Research and prototypes for **MBON-console-style lobbies/rooms** and a **universal online
matchmaking server** for arcade *Mobile Suit Gundam: Extreme Vs. 2 Infinite Boost* (EXVS2 IB).
The goal is a large shared player pool, beyond the Live Monitor (LM) store model's
16-terminal LAN limit.

This project builds on ideas from [asesidaa/EXVS2-POC](https://github.com/asesidaa/EXVS2-POC)
(community card/game server). It is **not affiliated with Bandai Namco**. No game files are
included. You must already have a copy of the game; this repo is notes, analysis, and server sketches only.

## Current status

| Area | What's here | Works? |
|---|---|---|
| Research | `analysis/` — WAN/MMS + STUN protocol notes, LAN 16-slot limit, server design | Findings from static analysis; not proven in a live match |
| Python MMS sketch | `server-sketch/python/` — stdlib HTTP protobuf prototype + fake cabinets | Exercised against simulated cabinets only, **not** against the game |
| C# handler sketch | `server-sketch/csharp/` — IB-Server-style handlers + RegisterPcb notes | **Uncompiled**, not wired into a running server |
| Card server patch (step 3) | `server-sketch/ib-server/` — patch for Chiang-17/EXVS2-IB-Server: RegisterPcb MATCH+STUN, in-process matchmaker, IB class-match tables, ranked result storage | Builds (Linux + win-x64), unit + fake-cabinet tests pass; **not tested with the game** |
| STUN | `server-sketch/coturn/turnserver.conf` — STUN-only coturn example (TEST-NET placeholder IPs) | Config only; not deployed |
| RE tooling | `tools/re/` — Capstone/pefile scripts for xrefs and scans | Source only; the venv and `xrefs.pkl` cache are not in this repo |
| Project notes | `notes/README.md` — index of what's present, missing, and still open | Informal lab notes |

A copy of the game executable is **not** in this repository and must never be added.

## Key finding (untested in game)

The WAN vs LAN switch is a **config change**, not an exe patch. If the active entry in
`testmode_pcb.json` has `battleMode: 0`, the client takes the WAN path: HTTP protobuf MMS
(rev 6) plus a standard RFC 5389/5780 STUN server. Any other `battleMode` stays on the
shop/LM LAN path (16 terminal slots).

This has been read out of the client; it has **not** been confirmed by running the game
with `battleMode: 0`. Edit those testmode files only with the project's `svd1.py` tool,
and only on a backup you can restore. Do not use "EXIT & SAVE" in the test menu.

Other results, documented in `analysis/matchmaking.md`:

- The match server `uri` from RegisterPcb is used as the full MMS URL; the port field is ignored.
- A `SRV_STUN` entry is required to start STUN and `IssueNodeId`.
- `IssueNodeId` must return at least as many unique IDs as the game asked for (it asks for 2).
- `CheckMatching` must list all four players, including self; `group_id` is the team (2v2).
- The game accepts an MMS reply on HTTP 200 + `code == SUCCESS`; it does not verify request-id.
- A failed NAT test does not, on its own, block queue entry (falls back to type 3 or 4).
- P2P battles still need reachable UDP (public IP, UPnP, or a VPN).

## Layout

```
analysis/            Matchmaking research and the extracted MMS .proto
notes/               Lab index (kept as written; some older notes are still missing)
server-sketch/       Python prototype, C# sketch, coturn example, ib-server card-server patch
tools/re/            Reverse-engineering helper scripts (no game binary, no caches)
```

## License

No license is offered. All rights in the notes and sketches remain with the author.
Game assets and trademarks belong to their owners.
