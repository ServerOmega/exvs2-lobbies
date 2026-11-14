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
