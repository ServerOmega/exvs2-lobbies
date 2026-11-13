# server-sketch — universal EXVS2 IB matchmaking (MMS) prototype

* `python/` — **runnable, tested** stdlib-only prototype.
  * `mms_server.py` — HTTP POST endpoint for Ping / IssueNodeId / EntryMatching / CheckMatching / CancelMatching / MatchingSetting.
  * `pbwire.py` — dependency-free proto2 codec for `nue.protocol.mms` (cross-checked against protoc-generated code).
  * `fake_cabinet.py` — simulates cabinets the way the game behaves; `python3 fake_cabinet.py --cabinets 4`.
* `csharp/` — **uncompiled** sketch in the Chiang-17 IB-Server style (ASP.NET Core + MediatR + protobuf-net), plus the RegisterPcb change.
* `coturn/turnserver.conf` — STUN-only coturn config.

Quick test (any Linux box):
```
cd python && python3 mms_server.py --port 5000 -v &
python3 fake_cabinet.py --url http://127.0.0.1:5000/mms --cabinets 4
```
Design: `../analysis/matchmaking-server-design.md`.

Notes from RE 2026-11-13 (see `../analysis/matchmaking.md` §7):
* Cabinet must have `battleMode: 0` in its active setting entry to use MMS at all.
* Game checks only HTTP 200 + parse + `code==SUCCESS`; request_id/type are not checked (server echoes anyway).
* NAT results never block entry; `nat_mapping`/`nat_filtering` may be 3 or 4 when STUN is single-IP — the
  prototype stores them as plain ints and does not reject them.
