# Results-screen hang: other candidate fixes (research, 2026-11-14, times PT)

Scope: the hang after a 2-cabinet **versus** match (two humans as opponents, each with a CPU partner, no lag).
It happens online and in local LM mode (one or two LMs). It does **not** happen in a solo route battle vs CPU.
Earlier analysis: [results-hang-logs.md](results-hang-logs.md), [post-match-flow.md](post-match-flow.md),
[debug-menu.md](debug-menu.md). This page adds web/community research, a cross-check of the upstream card server, and
a ranked list of fixes to try. Nothing was patched, run or redistributed. The test PC was offline, so no new logs.
**[C]** = read from code or a primary source, **[W]** = web/community source, **[I]** = inference.

## 1. What the research found

### 1.1 TeknoParrot changelog (Nov 2 2026): human + CPU teams and the result-screen hang [W]
The TeknoParrot update post ("EXVS2 InfiniteBoost Improvements") lists these changes for InfiniteBoost:
* "Added support for 1 human + 1 CPU teams in Class Matches"
* "Prevents partner session issues"
* "**May also fix hangs on the result screen**"
* Its Live Monitor emulator got "improved accuracy of several commands" and "more LM commands".

Source: https://www.patreon.com/TeknoParrotTeam/posts/teknoparrot-new-174180436 (public post, read 2026-11-14).

This is the only public report found of an IB results hang, and it names the same team layout we use (a human with a
CPU partner). No details were published: we don't know whether the fix is in TeknoParrot's hook DLL, its LM
emulator or its online server. TeknoParrot is closed source. **[I]** "partner session" fits the code path in
results-hang-logs.md §8.1. The ResultConfirm prompts (instant team / return match) check the *partner's* member
record and session (`party+0x158`, `+0xc0`, `+0x60/+0x61`), and a CPU partner may have none, or a half-filled one.

### 1.2 POC card-reader emulation never finishes a cancelled touch wait [C]
In asesidaa/EXVS2-POC `EXVS2-POC/banapass.cpp` (public source, latest `2343795`), with no real card reader:
* `BngRwReqCancel` returns 1 and **never calls the pending `BngRwReqWaitTouch` callback** with a cancel or finish
  status. It also leaves the reader thread running.
* `BngRwReqWaitTouch` sets `readerActive = false`, then **sleeps 250 ms on the calling thread**, then starts a
  polling thread. That thread calls the callback only when the card key is held (or `AutomaticCardButton = true`).
* `BngRwIsCmdExec` always returns 0 ("idle").

All three versus-only result prompts poll the card reader: ReturnMatch, FormInstantTeam and OptionWindow, each with
WaitCardTouch / WaitCardBusy states (results-hang-logs.md §8.3). A cancel that never completes, or a second
`ReqWaitTouch` while one is pending, could leave a prompt waiting until some longer timeout. **[I]**
**[I, timing match]** The 250 ms sleep may also explain the two ≈0.5 s stalls on the results screen in the capture
(results-hang-logs.md §2.6): one stall per instance, each the length of 1–2 `ReqWaitTouch` calls.

**Caveat:** the IB package's `bngrw.dll` is a community fork, not this build (multi-instance.md). Whether it keeps
this card code is unknown until its strings and exports are read on the PC.

Source: https://github.com/asesidaa/EXVS2-POC/blob/main/EXVS2-POC/banapass.cpp

### 1.3 Upstream card server (Chiang-17/EXVS2-IB-Server) [C]
* **No new commits after `7f4b280`** (v1.2.0, 2026-10-31 01:03 PT). The only open PR is
  [#4 "for V13 and some new function"](https://github.com/Chiang-17/EXVS2-IB-Server/pull/4) (2026-10-26 PT): V13
  support, saving badges in route battles, web stats. It has no results or hang fix. Closed issues #1–#3 are about card
  corruption and OB/IB cross-contamination. Nothing related.
* `GameController` (upstream plus our patch) answers every post-match call a 2-human match makes:
  `SaveVsmResult` (200, in-store), `SaveVsmOnResult` (201, online), `SaveBattleLog`/`SaveBattleLogOn`,
  `SaveUserPlayResearchData`, `SaveResultCapture` (224), `LoadBlackList`.
* **Not handled** (they get the fast `ErrServer "Unhandled case"` reply):
  * `SaveVsmToResult` (205)
  * `SaveMedal` (211)
  * `SaveFailedBattleLogOn` (225)
  * `RegisterOption` (306, likely the OPTION window's friend / NG actions **[I]**)
  * `LoadReplayCard` (406)
  * `PreSaveReplay` (407, used by the LM's automatic replay upload; the two commented-out lines are copied from the OB
    server)

  The original POC XB server (`Server/Controllers/GameController.cs`) **does** handle 205, 406 and 407.
  Its `SaveVsmToResult` simply returns Success with an empty body.
* `SaveVsmResult`/`SaveVsmOnResult` look up the card by `SessionId` + `PilotId` and return **Success with an empty
  body** when not found. CPU partners and foes (`CpuFlag != 0`) are skipped. No exception path specific to two humans
  was found. Even an HTTP 500 would be a fast answer (≤ 10 s × 5 tries).
* POC PR [#103](https://github.com/asesidaa/EXVS2-POC/pull/103) ("Fix wrong pilot ID checking in offline PvP") fixed
  `SaveVsmResult` reading `save_vsc_result.PilotId`. The IB server already reads `save_vsm_result.PilotId`
  correctly.

### 1.4 Other sources checked (no results-hang report found)
* asesidaa/EXVS2-POC issues (#1–#154) and releases: no results-hang issue. Related items:
  * [#121](https://github.com/asesidaa/EXVS2-POC/issues/121): LM live streaming "just shows loading" in 2v2. This is
    an LM-side feature that fails in 2v2; unanswered.
  * [#149](https://github.com/asesidaa/EXVS2-POC/issues/149): the maintainer says the dev menu "is buggy and can cause
    unexpected behaviors, e.g. BGM locked, crashing xinput", so `EnableDebugInPcb` was disabled for newer versions.
  * [Release 2.0.0](https://github.com/asesidaa/EXVS2-POC/releases/tag/2.0.0): "Made instructions deterministic, allowing
    cross-play between different CPU brands" ([determinize](https://github.com/ArgoGulskii/determinize)). Without
    it, Intel vs AMD cabinets desync. That matters for two-PC tests, not for the same-PC hang.
  * Config `AutomaticCardButton` ("automatically spamming card reading button") exists in the POC `config.ini`.
* [EXVSDB note on EXVS2 netcode](https://note.com/exvsdb/n/n9863a67a17fd): on real cabinets, an early "wrong winner"
  bug was blamed on input-sync failures. This is background on lockstep desync only.
* The official OB results page (https://gundam-vs.jp/extreme/ac2ob/howto/result/) confirms that RETURN MATCH needs
  all 4 players carded and that TEAM REQUEST needs both winners carded.
* Not usable: Bilibili blocks this box (HTTP 412), so the IB "本地双人同屏联机" video
  (https://www.bilibili.com/video/BV1mispzWEep/) could not be read. Discord content is private. The ppxclub IB
  one-click launcher thread (https://www.ppxclub.com/735846-1-1), the emuline XB/OB guides and the TeknoParrot
  Reddit threads mention no results hang. Japanese searches ("リザルト フリーズ / 止まる / 進まない") found only
  real-arcade lag notices (banasupport, 2026-03) and no results-hang reports.

## 2. Ranked candidate fixes

| # | Candidate | Evidence | How to test | Risk |
|---|---|---|---|---|
| 1 | **Human + CPU partner "partner session" problem** in the versus results (ResultConfirm prompts checking a partner that is a CPU). Fix direction: avoid human+CPU teams. Online, the matchmaker can pair the two humans as **teammates** instead of opponents (we already have Online tag / partner pairing). Otherwise use TeknoParrot's fixed build. | TeknoParrot 2026-11-02 changelog (§1.1) [W]; code path in results-hang-logs §8.1 [C/I] | **A.** Online: make the two cabinets partners (Online tag) and let the server fill the other side. A side with no humans needs a small server option (CPU stand-ins for a whole side), and whether the game accepts it is untested. No hang as teammates → confirmed. **B.** 3 cabinets: humans X+Y as a team vs human Z + CPU. Check whether only Z hangs. **C.** If the user already has TeknoParrot, run the same 1v1 + CPUs there (their own install, nothing copied). | Low for tests. A server-side workaround changes how solo players are matched, and it can't help local LM mode. |
| 2 | **Card-reader emulation:** a cancelled or duplicate `BngRwReqWaitTouch` never completes, so a result prompt sits in WaitCardTouch / WaitCardBusy. | POC `banapass.cpp` (§1.2) [C]; prompts poll the reader [C]; 0.5 s stalls match 250 ms sleeps [I] | During a hang, hold the **card key** (client `4`) ~1 s on one cabinet, then on the other. Note whether the screen moves on. Then try `AutomaticCardButton = true` on one cabinet, if the IB `bngrw.dll` has that key (`strings bngrw.dll`, read-only). No hang with auto-card → reader state. A real fix needs a DLL change (callback on cancel): **document only**, ask the fork's author. | Auto-card may auto-accept prompts (rematch, team, friend) and re-touch at entry. Test only, then turn it back off. |
| 3 | **Dev/debug settings left on** in `testmode_pcb.json` `debugParam` (#44 60 s save hold, #55 stop all timers, #45, others). The POC maintainer calls the dev menu buggy. | #149 maintainer comment [W]; #44/#55 behaviour [C] | Read `debugParam` read-only on both cabinets, or compare against a fresh copy from the package. Look for any non-default entry. | None (read-only). Never EXIT & SAVE. |
| 4 | **Missing card-server methods:** add our own Success stubs for 205 `SaveVsmToResult`, 211 `SaveMedal`, 225 `SaveFailedBattleLogOn`, 306 `RegisterOption`, 406/407 replay (fresh code in our patch, not copied). | Unhandled in IB server; XB POC answers 205/406/407 with Success (§1.3) [C] | `Select-String "Unhandled case"` in both server logs around each match end (results-hang-logs §4). If any appear, add stubs and retest. | Low. The expected effect is small, because each failed call is retried at most 5 times and answered fast. It also clears LM replay-upload errors. |
| 5 | **Two instances on one PC** (window focus, shared keyboard hook driving both windows, shared GPU). | real-game-test §4; capture stalls [I] | Pending Sandbox `cab2.wsb` test, or a real two-PC match (same CPU vendor, or a fork with the determinism fix). | Low. |
| 6 | **Result capture / upload** (task C). | Bounded at 5 s × 3 by code [C] | Debug #25/#26 only if a debug DLL is approved (Sandbox first). | Low relevance. |

Ruled out or unchanged: rematch handshake (no RPC 200 during the hang), continue/credit/FREE PLAY (runs after the results
screen), server latency (every wait ≤ 10 s × 5), and the matchmaker itself (local LM mode hangs too).

## 3. Cheapest order to run
1. Read-only checks when the PC is back: server logs for `Unhandled case`, `debugParam` values, and `bngrw.dll` strings
   (look for `AutomaticCardButton`, `BngRwReqCancel`). These settle #3, #4, and whether #2 applies to the fork.
2. During the next hang: hold the card key on one cabinet (#2), and stopwatch the whole hang (a fixed length means a
   timer).
3. Teammates test (#1 A) or the 3-cabinet test (#1 B).
4. Sandbox / two-PC (#5).

## 4. Implementation of fixes 1–4 (2026-11-14, ~02:55 PT; static analysis + fake cabinets, PC offline)
Server code is in our patch (`server-sketch/ib-server/online-matchmaking.patch`, commit 12 "Results-hang fixes").
Everything is **off by default** except a log line. No exe or DLL was patched, built for the game, or run.

### 4.1 Fix 1: human + CPU partner ("partner session")
**What the exe does with the partner [C].** The battle party's member list (`party+0x148`, up to 4 records of
0x2e0 bytes, count at `+0xb88`) is built **locally** from the cabinet's own player slots by 0x14082fb70 /
0x140836080 / 0x140839060. Each human slot gets `+0x60 = 1` ("present"), its id at `+0x1b8` and `+0x61` = byte +4
of the local player record (card state). **If fewer than 2 members were added, the builder appends a CPU member**
(id 1, `+0x60 = 0`, default team 0, 0x140830218–0x1408302bc). Then:
* Return match (party vfunc +0x158 = 0x1408687e0) needs `+0x60` and `+0x61` set on **every** member, so a CPU
  partner always turns it off. This matches the official rule "all 4 players carded".
* Instant team (vfunc +0x160 = 0x1408685a0) needs every same-team member's id to be in the peer session map
  (`party+0x158`) with `+0xc0 != 0`. The CPU's id (1) has no peer session, so it is off too.

Both checks are plain local reads that return false: they do not wait, and **no server data feeds them**. LoadCard
has no partner-session field, and the MMS `CheckMatching` reply carries only `group_id` + `Client` per seat (no
Player record, see `matchmaking_server_nue.proto`), so the server can't describe a CPU as "carded".

**Options:**
* **(a) Server-side placeholder for a CPU partner:** not possible beyond what `CpuStandInSeats` already does (it
  lists the CPU seat exactly the way the game lists its own CPU partner: `PCB00000NPC`, property "N", the
  cabinet's 2nd node id). The real-game test on 2026-11-13 showed it does not fix the hang. A stand-in marked "Y"
  would make the cabinets try to reach a peer that doesn't exist. Nothing more was implemented.
* **(b) Two humans as teammates against CPUs (implemented, flag `OnlineMatching.HumansTeamVsCpu`, default false).**
  When a short-handed room would have exactly two humans (two solo entries, or one 2-human team waiting alone),
  the matchmaker puts both humans in group 0 and **two CPU stand-ins in group 1**, one on each human's own 2nd
  IssueNodeId id (listed after the humans). With the flag off nothing changes. Full rooms, 3-human short rooms and
  cabinets that brought their own CPU partner ("TN" entries) are unchanged. If a stand-in id would collide with a
  human node, the normal 1v1 forms instead. The log line is `MATCH room=N … humans-vs-cpu [a,b] vs CPU [a2,b2]`.
  **Whether the game accepts a side with no human is untested [I].** The game builds CPU entries itself only as
  the partner of a human ("TN"), so an all-CPU side is a layout it never creates on its own. Possible outcomes:
  it plays normally, it fails at the pre-battle `PBNoticePlayer` wait (30 s timeout, 0x1407ac820), or it
  desyncs. A no-code alternative to compare: online tag (world 5) pairs the two cabinets and the leader's team
  entry waits for opponents; that path is the game's own and was already tested with fake cabinets.
* **(c) Not fixable server-side:** local LM mode (no matchmaker) and any hang inside the cabinets' own result
  tasks. In LM mode, the only test is the same layout chosen by hand (both humans on one team).

**What it proves:** if the hang never happens with the humans as teammates, the human + CPU-partner layout is the
trigger (TeknoParrot's note). If it still hangs, look at fixes 2/3.

### 4.2 Fix 2: card-reader emulation, cancelled wait never completes (proposal only)
**How vsac29 uses the reader [C].** The wrapper object (`0x14287f638`, state at `+0x24`) starts a touch wait with
`BngRwReqWaitTouch` (0x140106b50). It first resets the shared result: status `0x14287f608 = -901` (pending) and
done byte `0x14287f62c = 0`. Then it passes callback 0x140106c50 and context `0x14287f560`, and sets state 2.
The callback copies **0xa8 bytes** from its data pointer, stores the status and sets the done byte. Reader update
0x140106940 (state 2) moves to state 9 **only when the done byte is set**. Poll (0x140106cf0) reports a result
only in state 9: status 0 = card read, **status 3 = finished with nothing to report**, other values go through
0x140106ae0 (-400 → 1, -401 → 3, -200/-201 → 2, -900/-300/-301/-100/-101/-2 → 4). Cancel (0x140106f90) calls
`BngRwReqCancel` in state 2 and **does not change the state**. So after a cancel the reader stays "touch pending"
until a callback arrives.

**What the POC does (asesidaa/EXVS2-POC master `2343795`, `banapass.cpp`):**
* `BngRwReqCancel` returns 1 and never calls back.
* `BngRwReqWaitTouch` clears a global `readerActive`, sleeps **250 ms on the game thread**, then starts a thread.
  While the card key is held, that thread calls the callback **every 100 ms** and keeps running.
* Result: after a cancel, the game's reader stays in state 2 until the next card-key press. That press is then
  delivered to whatever asked last, possibly a stale context.

**Proposed patch:** [`patches/poc-banapass-cancel.diff`](patches/poc-banapass-cancel.diff), against the public POC
source; 4 files, ~120 lines.
* A generation counter + mutex replace `readerActive` and the 250 ms sleep. A new `ReqWaitTouch` retires the old
  thread, and each thread calls back at most once, only for its own request (`ClaimTouch`), then exits.
* `BngRwReqCancel` completes the pending wait. It calls the stored callback on a short worker thread with an
  all-zero 168-byte buffer (the game copies 0xa8 bytes unconditionally) and status `CardCancelStatus`. The default
  is 3: "finished, nothing to report" in vsac29's poll. That value is an inference, since the real library's
  cancel code is not known.
* New config.ini keys `CardCancelCallback = true`, `CardCancelStatus = 3`.

It was not built and not run. It is not redistributed beyond the diff. Before anyone uses it, it must be built
from source by its maintainer and tried in the Sandbox first.

**IB `bngrw.dll` fork:** no public source found. All 60+ GitHub forks of EXVS2-POC checked (2026-11-14) are
at or behind master; the only "ahead" ones change README only. The two IB server repos (Chiang-17, MMMIYon) have no
hook source. `AutomaticCardButton` exists in the public POC (`config.ini`, `Configs.h`, used in `StartReadThread`).
Whether the IB fork keeps it is unknown. `tools/check-debugparam.ps1` reports it from a byte scan of bngrw.dll
(the DLL is not loaded).

### 4.3 Fix 3: dev-menu values (`debugParam`), read-only check
`tools/check-debugparam.ps1` (PowerShell 5.1+ / 7) reads `testmode_pcb.json` and **writes nothing**. It prints the
`battleMode` of every setting entry and the scalar `debugParam` keys, each with a warning where it matters. For the
on/off options it shows the value and the safe value. It also prints only the card-reader switches from
`config.ini` (never `accessCode` / `chipId` lines), plus a byte scan of `bngrw.dll` for `AutomaticCardButton`,
`BngRwReqCancel` and `EnableDebugInPcb`. It shows the SHA256 of each file so the two cabinets can be compared.
Exit code 1 means a risky value was found. Tested on fake files only.

`debugParam` (TestMode `+0x4e8`, serializer 0x1406dec70) only matters when the dev-menu gate is on (debug DLL).
Relevant entries (index into `debugParams`, TestMode `+0x510 + 4*index`):

| # | meaning | safe | why it matters for the hang |
|---|---|---|---|
| 55 | stop all timers | 0 | **hang candidate**: result HUD countdowns never end |
| 44 | fake 1-min delay on result-save response | 0 | **hang candidate**: ≈60 s per save (task S) |
| 28 | force error on result-save request | 0 | save retries (task S) |
| 25 | result capture every time | 0 | adds task C (≈5 s × up to 3) |
| 9 | virtual card-touch menu | 0 | changes how the card prompts are answered |
| 24 | debug battle mode | 0 | different battle flow |
| 5 / 7 / 8 | HTTP fastest / always offline / no storage writes | 0 | request pacing / online off / settings not saved |
| 32–35 | time-limit shorteners | 0 | timed modes |
| 45 | unlimited return matches | 0 (1 ok) | rematch prompt beyond 2 |
| 3 | fix input delay (+ `keyDelay` 1–18) | either | netcode knob; same on both cabinets |
| 27 | no error when PCB1/2 absent | either | the POC forces it on for clients |
| 15 / 18 / 47 / 57 / 61 | diagnostics (resident tasks, WAN log, stuck check, team log, sub-tasks after the match) | 0 (1 ok for tests) | #61 shows the F/S/A/C/R letters on a hung results screen |
| `ipMode` | 0 auto / 1 IPv4 / 2 IPv6 | 0 or 1 | 2 breaks STUN |
| `wanMatchingGroupId` | EntryMatching attr1 with the gate on | same on all cabinets | different ids never meet |

Usage on the PC, game closed: `powershell -ExecutionPolicy Bypass -File tools\check-debugparam.ps1 -GameDir <IB folder>`
(or `-Path …\testmode_pcb.json`). Run it on both cabinets' folders.

### 4.4 Fix 4: unhandled card-server methods + `network_report` log
* **`PostMatchStubs` (CardServerConfig, default false).** It answers the six methods with replies that pass
  strict proto2 parsing. Nothing is stored, and the log lines start with `STUB`. Upstream's own (disabled)
  PreSaveReplay handler is not used.
  * 205 `SaveVsmToResult`, 225 `SaveFailedBattleLogOn` (logged as a warning: pilot, room, my_fault, mode),
    306 `RegisterOption` (friend / NG ids logged, not stored): Success, empty body.
  * 211 `SaveMedal`: `ACID_SUCCESS` + the card's pilot id and 0 medals (`ACID_NO_USE` if the card is unknown).
  * 406 `LoadReplayCard`: `ACID_NO_USE` (no replay service).
  * 407 `PreSaveReplay`: status 2 (reject, the value upstream uses for "slots full") + `http://dummy`, so the LM
    skips its upload.
* **`LogNetworkReport` (default true, logging only):** one line per `SaveVsmOnResult`, e.g.
  `NETREPORT pilot=1 input_delay=4f start_delay=6f delay_src=1 paused=2x/30f pcbs=[PCB…@LOC:rtt=21ms,max=30ms,loss=0.01 …]`.
  It contains no card data.
* Expected effect on the hang: small. Every failed call was already answered fast. The stubs mainly remove the
  `Unhandled case` noise and the LM's replay-upload errors.
* Note: upstream's controller still logs every request in full (`Request is …`), including card access codes. That
  is unchanged upstream behaviour, so don't share raw server logs.

### 4.5 Tests (box, fake cabinets / fake cards only)
* `dotnet test Tests/Matchmaking.Tests`: **63/63 passed**, including 7 new `HangFixTests`: off by default; two
  solos → teammates + 2 stand-ins on their 2nd ids; lone 2-human team → vs 2 stand-ins; lone team without the
  flag never matches; full / 3-human rooms unchanged; "TN" teams not regrouped; no stand-in on a human id.
* `server-sketch/loadtest/hangfix_e2e.py` against the Linux build:
  * Flags on: **15/15** (all six stubs SUCCESS with strict parsing, NETREPORT logged, no card secrets in
    STUB/NETREPORT lines, MMS two-solo and lone-team humans-vs-cpu rooms, same list on both cabinets).
  * Flags off (`--expect-off`): **10/10** (all six still `Unhandled case`, normal 1v1).
* Regression: `online_tag_e2e.py` **28/28**; the patch applies cleanly to upstream `7f4b280`.

### 4.6 What the user can test (when the PC is back)
1. `tools\check-debugparam.ps1` on both cabinets (read-only). Fix #55/#44 first if they are set.
2. Server logs: `Unhandled case` / `NETREPORT` lines around a match end. Then turn on `PostMatchStubs` and repeat
   one hung-layout match.
3. Online, two cabinets: `HumansTeamVsCpu: true` (+ `AllowPartialRooms`, `FillAfterSeconds` 15). Both queue for
   the same mode, solo. After 15 s they should be teammates against two CPUs. Note whether the battle starts, and
   whether the results screen still hangs. Compare with online tag (world 5) as teammates.
4. LM mode: pick the teammates layout by hand.
5. During a hang: the card key on one cabinet (fix 2 symptom check). The DLL patch stays a proposal.

## 5. Follow-up
Simulations of these fixes and new drafts (watchdog, log masking, LoadBlackList config, card-reader patch v2, hang probe): [results-hang-sim.md](results-hang-sim.md).
