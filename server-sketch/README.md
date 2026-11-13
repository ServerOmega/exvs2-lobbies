# server-sketch — universal EXVS2 IB matchmaking (MMS) prototype

* `python/` — **runnable, tested** stdlib-only prototype.
  * `mms_server.py` — HTTP POST endpoint for Ping / IssueNodeId / EntryMatching / CheckMatching / CancelMatching / MatchingSetting.
  * `pbwire.py` — dependency-free proto2 codec for `nue.protocol.mms` (cross-checked against protoc-generated code).
  * `fake_cabinet.py` — simulates cabinets the way the game behaves; `python3 fake_cabinet.py --cabinets 4`.
  * Ranked (Class Match G, worlds 13/14): `python3 fake_cabinet.py --ranked "2:3,2:3,3:1,3:1" [--team] [--report]`
    (class:level per cabinet; `--report` exercises the internal `/result` MMR hook). See `../analysis/ranked-matching.md`.
  * **Experimental — only tested against fake_cabinet.py, never against the real game.**
* `csharp/` — **uncompiled** sketch in the Chiang-17 IB-Server style (ASP.NET Core + MediatR + protobuf-net), plus the RegisterPcb change.
* `coturn/turnserver.conf` — STUN-only coturn config.

Quick test (any Linux box):
```
cd python && python3 mms_server.py --port 5000 -v &
python3 fake_cabinet.py --url http://127.0.0.1:5000/mms --cabinets 4
```
Design: `../analysis/matchmaking-server-design.md`. Casual/shuffle: `../analysis/casual-shuffle-matching.md`.
* Casual (shuffle/mix/in-store/custom buckets): `python3 test_casual.py` and
  `python3 fake_cabinet.py --units S,S,S,S --world 23` (S solo, T team+human partner, TN team+CPU; `--same-loc --attr2 N` for in-store 15/16).
  Server options `--fill-after SEC` (short-handed 1v1/2v1 rooms after SEC, untested in game) and `--no-partial`.

Notes from RE 2026-11-13 (see `../analysis/matchmaking.md` §7):
* Cabinet must have `battleMode: 0` in its active setting entry to use MMS at all.
* Game checks only HTTP 200 + parse + `code==SUCCESS`; request_id/type are not checked (server echoes anyway).
* NAT results never block entry; `nat_mapping`/`nat_filtering` may be 3 or 4 when STUN is single-IP — the
  prototype stores them as plain ints and does not reject them.

## Load test
[`loadtest/loadtest.py`](loadtest/loadtest.py) simulates 100–500 cabinets (solo shuffle, pairs, CPU partners, ranked
classes, cancels, drop-outs, requeues, misbehaving clients) against either matchmaker and checks room invariants.
Results and the bugs it found: [`../analysis/load-test.md`](../analysis/load-test.md).
[`loadtest/lm_mix.py`](loadtest/lm_mix.py) puts LM-store, home and multi-LM fake players on one server and
prints who got matched with whom ([`../analysis/lm-and-online.md`](../analysis/lm-and-online.md)).

## Card server (step 3)
See [`ib-server/`](ib-server/README.md): a patch for Chiang-17/EXVS2-IB-Server that advertises the match + STUN servers and runs a C# port of this matchmaker in-process. The Python server here remains usable as an external matchmaker (`MatchUrl`).
