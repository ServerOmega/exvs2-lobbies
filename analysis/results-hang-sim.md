# Results-screen hang: simulations of the fixes + new fix drafts (2026-11-14, ~05:10 PT)

Follows [results-hang-fixes.md](results-hang-fixes.md) §4 (fixes 1–4, commit 44a2708). The test PC was offline, so
everything here ran on the box against the patched Linux server build, fake cabinets and **fake cards only**. The game
exe and the community DLLs were never run; the card-reader code was compiled from the public POC source with mocks
and run only inside a unit harness. **[C]** = from code / measured, **[I]** = inference, **[H]** = model hypothesis.

## 1. What was built
| # | Simulation | File | What it does |
|---|---|---|---|
| 1 | Post-match HTTP replay + fault proxy | `server-sketch/sim/postmatch_replay.py` | Replays a cabinet's post-match card-server calls the way vsac29 makes them (10 s libcurl timeout, ≤ 5 immediate tries, S sequential, C in parallel, gate = max(F, S, C)) against the real patched server, two cabinets at once, flags off/on. A proxy injects delays, dropped replies, HTTP 500, ErrServer; a second process holds an EXCLUSIVE lock on the SQLite file (real time). |
| 2 | State-machine model of the results gate | `server-sketch/sim/hang_model.py` | 60 fps, two cabinets in lockstep: F/S/A/C, ResultConfirm (300-frame counter + untimed WaitHud), ReturnMatch / FormInstantTeam prompts, the vsac29 reader wrapper, and 4 DLL variants (POC original, v2 patch, v2 + wait timeout, AutomaticCardButton). Unknowns are switches (H1–H3); every outcome is checked against the real-game evidence E1–E8. |
| 3 | Card-reader patch: compile check + unit harness | `tools/banapass-harness/` | Applies `patches/poc-banapass-cancel.diff` to the public POC @ `2343795`, syntax-checks `Config.cpp` + `banapass.cpp` against real Windows headers (clang, mingw-w64 target), then builds `banapass.cpp` natively with mocked Win32 / input / config and a mock of vsac29's reader wrapper, for the original, v1 and v2. POC source is copied to a temp dir only. |
| 4 | Matchmaker simulation, HumansTeamVsCpu | `Tests/Matchmaking.Tests/HumansVsCpuSimTests.cs` (in the server patch) | 10 seeds × 6 / 24 / 120 fake cabinets (55 % solo, 25 % 2-human team, 20 % own CPU partner; Mix 23 or casual 21; random arrival over 4 min; polled every second), same population with the flag off and on. |
| 5 | Hang probe for the PC | `tools/hang-probe.ps1` | Read-only snapshot to run during a hang (see §5, draft B). |

## 2. Replay results (simulation 1)
Order and set of S calls are [I]: versus online 201 → 221 → 223, LM-local 200 → 220 → 223, "pessimistic" adds the
unhandled 205 / 211 / 225. C = 3 captures (10 frames each, worst case 300) + 224. F = 589 frames (9.8 s). Fault rows
ran time-scaled ×0.1 and are shown in game seconds; baseline and DB-lock rows ran in real time. Two cabinets each.

| scenario | server flags | S (s) | C (s) | gate (s) | longer than F by | HTTP tries | calls that gave up |
|---|---|---|---|---|---|---|---|
| baseline online | off | 0.1 | 0.7 | 9.8 | 0 | 8 | – |
| baseline LM-local | off | 0.2 | 0.7 | 9.8 | 0 | 8 | – |
| pessimistic (205/211/225 unhandled) | off | 0.1 | 0.7 | 9.8 | 0 | 38 | 205, 211, 225 (5 fast tries each) |
| same | on (stubs) | 0.0 | 0.7 | 9.8 | 0 | 14 | – |
| worst-case capture (3 × 300 frames) | either | 0.0 | 15.2 | 15.2 | 5.4 | 8 | – |
| 12 s delay on 201, every try | off | 50.2 | 2.1 | 50.2 | 40.4 | 16 | 201 |
| 12 s delay on 201, first try only | off | 10.1 | 0.5 | 10.1 | 0.3 | 10 | – |
| 9 s delay on every call | off | 27.2 | 19.6 | 27.2 | 17.3 | 9 | – |
| 9.5 s delay, pessimistic seq | off | 172.2 | 20.1 | 172.2 | 162.3 | 39 | 205, 211, 225 |
| server never answers | off | 150.3 | 50.6 | 150.3 | 140.4 | 40 | all |
| server never answers, pessimistic | off | **300.5** | 50.6 | **300.5** | 290.7 | 70 | all |
| ErrServer / HTTP 500 on every call | off | 0.1 | 0.6 | 9.8 | 0 | 40 | all (fast) |
| 224 dropped | off | 0.1 | 50.6 | 50.6 | 40.8 | 16 | 224 |
| SQLite locked 35 s, online | off | 0.1 | 35.2 | 35.2 | 25.4 | 14 | – |
| SQLite locked 35 s, LM-local | off | 35.4 | 35.0 | 35.4 | 25.6 | 20 | – |
| SQLite locked 35 s, online | **on (watchdog 8 s)** | 0.1 | 8.5 | 9.8 | 0 | 8 | – |
| SQLite locked 35 s, LM-local | **on (watchdog 8 s)** | 16.1 | 8.5 | 16.1 | 6.3 | 8 | – |

**Findings [C, measured]:**
* With the server answering normally, S and C finish in < 1 s and the gate is F (9.8 s). Error replies (ErrServer,
  500, "Unhandled case") are retried 5× but cost milliseconds: they **cannot** hold the results screen.
* The only server behaviours that hold it for minutes are **not answering at all** (≤ 50 s per call: 150 s online,
  300 s with the unhandled methods) or **answering just under 10 s every time** (172 s pessimistic). Both contradict the
  captures (every request answered with 200 quickly, E8).
* A locked database is the one realistic slow-server case for this code: Microsoft.Data.Sqlite waits up to 30 s on a
  busy file, so every write call times out at 10 s and is retried until the lock ends (here 35 s). The background
  write itself fails after 30 s (`WATCHDOG … failed`), the same data loss as without the watchdog.
* `PostMatchStubs` changes nothing when the server is fast, but removes the ×5 multiplier for 205/211/225 when it is
  slow: in the 9.5 s-delay row each of the six calls would take one 9.5 s try instead of five, ≈57 s instead of 172 s [I, computed from the per-call numbers, not run].
* **Worst case measured: 300.5 s** (server never answers, pessimistic sequence). With a responsive server: 15.2 s
  (worst-case capture), i.e. +5.4 s over F.

## 3. Model results (simulation 2)
Hypotheses: **H1** the cabinet appends its CPU partner as a party member (+0x60 = 0) so the instant-team check fails
(results-hang-fixes §4.1; "false" = the §8.1 reading where the prompt can appear). **H2** a prompt that ends on its
countdown cancels the card wait and only exits once the reader is no longer "pending". **H3** a game-side give-up on
that wait after N s (not found in the exe). Evidence: **E1** hang of minutes that ends by itself; **E2** cabinets leave
8 ms apart; **E3** steady 60 Hz, only one ≈0.5 s stall per instance; **E4** no peer reliable messages / RPC 200;
**E5** holding Start does nothing; **E6** route battle vs CPU fine; **E7** LM-local hangs too; **E8** HTTP answered.

| id | scenario | exit s (cab1/cab2) | result | prompts (cab1; cab2) | 250 ms stalls | contradicts evidence |
|---|---|---|---|---|---|---|
| U1 | User's layout (human+CPU each side), H1 true | 10.0 / 10.0 | no hang | -; - | 0/0 | E1 (no hang) |
| U2 | User's layout, H1 false (instant-team prompt shown) | never / never | indefinite | FormInstantTeam; FormInstantTeam | 1/1 | E1 (never ends by itself) |
| U3 | U2 + card key held 1 s at 20 s on cabinet 1 | 25.0 / never | indefinite | FormInstantTeam; FormInstantTeam | 1/1 | E1 (never ends by itself) |
| U4 | U2 + card key on both (one keyboard drives both windows) | 25.0 / 25.0 | no hang | FormInstantTeam; FormInstantTeam | 1/1 | E1 (no hang) |
| U5 | U2 but prompt exits without waiting for the reader (H2 false) | 15.0 / 15.0 | no hang | FormInstantTeam; FormInstantTeam | 1/1 | E1 (no hang) |
| U6 | U2 + a game-side reader give-up after 180 s (hypothesis H3) | 195.0 / 195.0 | finite >30 s | FormInstantTeam; FormInstantTeam | 1/1 | **none** |
| U7 | U6 with the v2 DLL patch | 15.1 / 15.1 | no hang | FormInstantTeam; FormInstantTeam | 0/0 | E1 (no hang) |
| T1 | HumansTeamVsCpu: humans same team, won (prompt for winners) | never / never | indefinite | FormInstantTeam; FormInstantTeam | 1/1 | E1 (never ends by itself), E4 (prompt talks to a human peer) |
| T2 | HumansTeamVsCpu: humans same team, lost | 10.0 / 10.0 | no hang | -; - | 0/0 | E1 (no hang) |
| T3 | T1 with the v2 DLL patch | 15.1 / 15.1 | no hang | FormInstantTeam; FormInstantTeam | 0/0 | E1 (no hang), E4 (prompt talks to a human peer) |
| R1 | Cancel never calls back (forced prompt), POC original | never / never | indefinite | FormInstantTeam; FormInstantTeam | 1/1 | E1 (never ends by itself) |
| R2 | R1 with v2 patch (cancel calls back) | 15.1 / 15.1 | no hang | FormInstantTeam; FormInstantTeam | 0/0 | E1 (no hang) |
| R3 | R1 with v2 + CardWaitTimeoutMs 3000 only (no cancel callback) | 15.1 / 15.1 | no hang | FormInstantTeam; FormInstantTeam | 0/0 | E1 (no hang) |
| R4 | R1 with AutomaticCardButton (touch every 100 ms) | 10.0 / 10.0 | no hang | FormInstantTeam; FormInstantTeam | 0/0 | E1 (no hang) |
| X1 | Two instances share ONE reader object, POC | never / never | indefinite | FormInstantTeam; FormInstantTeam | 2/2 | E1 (never ends by itself), E3 (repeated 250 ms stalls) |
| X2 | Two instances share ONE reader object, v2 patch | 15.1 / 15.1 | no hang | FormInstantTeam; FormInstantTeam | 0/0 | E1 (no hang) |
| D1 | Debug #55 timers stopped, no prompt (H1 true) | never / never | indefinite | -; - | 0/0 | E1 (never ends by itself), E5 (OPTION open), E6 (#55 also freezes route battles) [I] |
| D2 | Debug #55 timers stopped + prompt, v2 patch | never / never | indefinite | FormInstantTeam; FormInstantTeam | 0/0 | E1 (never ends by itself), E6 (#55 also freezes route battles) [I] |
| D3 | Debug #44 fake 60 s save hold | 60.2 / 60.2 | finite >30 s | -; - | 0/0 | E6 (#44 also delays route battles) |
| S1 | Server never answers (S = 150 s from replay) | 150.0 / 150.0 | finite >30 s | -; - | 0/0 | E8 (needs unanswered HTTP) |
| S2 | Server never answers, pessimistic seq (S = 300 s) | 300.0 / 300.0 | finite >30 s | -; - | 0/0 | E8 (needs unanswered HTTP) |
| S3 | SQLite locked 35 s, watchdog off, LM-local (S = 35.4 s from replay) | 35.4 / 35.4 | finite >30 s | -; - | 0/0 | E1 (well under minutes) / E8 (slow HTTP answers) |
| S4 | SQLite locked 35 s, watchdog 8 s, LM-local (S = 16.1 s from replay) | 16.1 / 16.1 | no hang | -; - | 0/0 | E1 (no hang) |

Defaults unless stated: H1 true, H2 true, H3 off, POC original DLL, instant-team HUD 10 s [I], option window 5 s [I].

**Findings [H]:**
* **No modelled server behaviour reproduces the hang** without contradicting E8 or E6 (S1–S4, D3).
* With H1 true (CPU partner is a member), the user's layout creates **no prompt** and leaves at F (U1): then the hang
  is somewhere the model does not cover (e.g. inside the results HUD itself).
* If a card prompt does appear (H1 false) and H2 holds, the **POC card reader makes it indefinite** (U2, R1): its
  `BngRwReqCancel` never calls back, so the prompt waits for a callback that only a card-key press produces. The
  **v2 DLL patch** (R2, X2, U7), the v2 wait timeout alone (R3) and AutomaticCardButton (R4) all end it at ≈15 s.
* The **only row that matches every piece of evidence is U6**: prompt + POC cancel + some long game-side give-up (H3).
  It also gives one 250 ms `ReqWaitTouch` stall per instance, close to the single ≈0.5 s stall per instance in the
  capture (E3). U3/U4: a card key pressed on one cabinet ends only that cabinet's wait unless the key reaches both
  windows, which the POC keyboard hook does (it drives both windows). So **the card-key test during a hang is decisive**.
* **HumansTeamVsCpu is a discriminating test, not a fix** (T1–T3): with two carded humans on one team, the instant-team
  prompt is *expected* for the winners. If the card-prompt theory is right, the teammates layout should hang **when
  the humans win** and not when they lose. Record win/loss with each result.
* Debug #55 (timers stopped) hangs forever with or without prompts and even with the DLL patch (D1, D2); #44 gives
  60 s (D3). Both would also affect route battles [I], so they are unlikely, but `check-debugparam.ps1` rules them out.

## 4. Card-reader patch: compile + unit results (simulation 3)
* `patch -p1` applies to POC `23437956`. Syntax check with real Windows headers (clang 19, `x86_64-w64-mingw32`,
  `-fms-extensions -Wall -Wextra`): `Config.cpp` and `banapass.cpp` **OK**. The patched file produces exactly the same
  17 distinct warnings as the original (all upstream `FARPROC` casts); the patch adds none. The POC's own MSVC-only
  `std::filesystem::path::path(` (two unchanged lines) is normalised for the check only.
* Unit harness (native, mocks; vsac29 wrapper = reset status −901 / done 0 before each wait, callback copies 0xa8
  bytes, sets status + done):

| test | original POC | v1 (44a2708) | v2 (this commit) |
|---|---|---|---|
| T1 cancel → callback within 500 ms (status 3) | no (reproduces the stuck wait) | yes | yes |
| T6 `BngRwReqWaitTouch` blocks the game thread ≥ 200 ms | yes (250 ms) | no | no |
| T2 key held 450 ms → more than one callback | yes (every 100 ms) | no (exactly one) | no |
| T3 two waits + key → exactly one callback | no | yes | yes |
| T4 cancel, then immediate re-arm → new wait finished by the old cancel | no | **yes (bug)** | no |
| T5 `CardWaitTimeoutMs=300`, no key → finished (status 3) by 700 ms | no | no | yes |
| T5b timeout 0, no key → still pending at 700 ms | yes | yes | yes |
| T7 cancel with nothing pending → no callback | yes | yes | yes |
| T8 `CardCancelCallback=false` → cancel leaves the wait pending | yes | yes | yes |

  All 32 observations matched the expected behaviour of each variant (exit 0 for all three).
* **Bug found in v1 and fixed in v2:** v1 completed a cancel on a worker thread without checking whether the game had
  already re-armed. The game resets its shared result before each wait, so a late cancel callback would finish the
  **new** wait with "no card". v2 drops the stale completion (generation check under the mutex). The harness exposes
  the race with a test-only 100 ms delay (`EXVS2_LOBBIES_TEST_CANCEL_DELAY_MS`, compiled out otherwise).
* **v2 also adds `CardWaitTimeoutMs`** (default 0 = off): a touch wait with no card for that long is finished like a
  cancel. This is the "timed auto card" idea in its safe form: it never fakes a card, so it can't accept a rematch /
  team / friend prompt. A timed fake card touch was rejected for that reason.
* Run: `POC=/path/to/EXVS2-POC tools/banapass-harness/build_and_test.sh`. Still a **proposal**: not built as a DLL,
  not run with the game. The IB package's `bngrw.dll` is a fork without public source, so this applies to it only if
  it kept the POC card code.

## 5. Matchmaker simulation, HumansTeamVsCpu (simulation 4)
30 runs (10 seeds × 6 / 24 / 120 cabinets), off vs on with the same population: **all invariants held** (≤ 4 seats,
groups 0/1 with ≤ 2 each, no node id twice in a room, no human in two rooms, modes never mixed, humans-vs-cpu rooms
only with the flag, their stand-ins `PCB00000NPC` on the humans' own 2nd ids, never built from a cabinet with its own
CPU partner). **20 humans-vs-cpu rooms** formed (mostly at 6–24 cabinets; at 120 the queue fills real rooms first).
With the flag on, unmatched cabinets were never more than with it off (fewer in 4 runs: lone 2-human teams now play),
and all-human 4-seat rooms stayed within ±1. Server tests: **86/86** (63 earlier + 13 `HangSimTests` + 10 sim runs).

## 6. New fix drafts, ranked
| rank | draft | kind / state | what the simulations say | how to try it |
|---|---|---|---|---|
| 1 | **Card-reader patch v2**: cancel calls back (status 3), stale-cancel guard, no 250 ms sleep, one callback per wait, optional `CardWaitTimeoutMs` | DLL diff, **document only** (`patches/poc-banapass-cancel.diff`), compile-checked + unit-tested | Ends every modelled card-prompt hang at ≈15 s (R2, R3, U7, X2, T3); fixes a real race in v1 | Only if the card-key test (below) moves the hang. The fork's maintainer builds it; Sandbox first, current DLL backed up. |
| 2 | **Hang probe + card-key test** | `tools/hang-probe.ps1` (read-only, tested on the box with fake logs; masks card values and public IPs) | Separates S (server, would show TCP / slow `responded` lines) from A (game busy, no traffic) and records which processes wait | During the next hang: run the probe, then hold the card key ~1 s, note whether the screen moves, run the probe again after it recovers. |
| 3 | **`PostMatchWatchdogMs`** (server, default 0 = off) | implemented in the patch, unit + e2e tested | Bounds a slow (locked-DB) post-match save to ≤ 8 s per writing call (35 s → 9.8 / 16.1 s). No effect on the real hang unless the DB is locked (E8) | `"PostMatchWatchdogMs": 8000` if anything else opens `ServerInfinite.db` (DB browser, backup, sync folder, antivirus). |
| 4 | `PostMatchStubs` (existing) | server, off by default | Only matters when the server is also slow (removes ×5 for 205/211/225) | Unchanged advice: turn on if logs show `Unhandled case`. |
| 5 | **`MaskCardSecretsInLog`** (server, default **on**, logging only) | implemented; e2e: no fake code left in the log | Not a hang fix: makes server logs shareable (the upstream request dump and "Card … ChipId = …" lines printed card codes) | Nothing to do; set false to get upstream's raw dump back. |
| 6 | **`LoadBlackList` values in config** (defaults = upstream 300 / 1 / 300 / 300 / 5) | implemented; e2e checks defaults and an override (200 / 4) | Not a hang fix (pre-match quality limits). The netcode lever offered earlier | Leave at defaults; lower `ThresholdDelayedRtt` to keep laggy pairs apart, same on all servers. |
| – | HumansTeamVsCpu | existing flag | Test tool: predicts a hang **only when the teammates win** if the prompt theory is right | Record win/loss for each teammates match. |
| – | Force the result-capture upload off by a config reply | **rejected** | No reply field controls capture (`result_capture_num` is reported *by* the game in research data); C is bounded by the game (≤ 3 × 5 s) and no PUT caller exists. A dropped 224 costs ≤ 50 s, and the watchdog already bounds 224's DB write | – |
| – | Exe idea: give `ResultConfirm::Proc_WaitHud` (0x1408e4ac0) a frame limit | **idea only, nothing written or applied** | Would end any child-prompt wait (incl. #55 cases) | Not pursued: exe patches stay documentation only. |

## 7. What the user can run when the PC is back
1. `tools\check-debugparam.ps1` on both cabinets (rules out #44 / #55).
2. Next hung match: stopwatch; at ~20 s run `tools\hang-probe.ps1 -GameDir <cab1>,<cab2> -ServerDir <server>`; then
   hold the card key ~1 s; write down whether the screen moves (one cabinet or both) and the total hang length.
3. HumansTeamVsCpu match: write down **win or loss** and whether it hung.
4. Only if step 2 moved the hang: ask the bngrw fork's author about patch v2 (try in the Sandbox first).

## 8. Reproduce on a Linux box
```bash
# server: build the patched upstream with -p:LinuxHost=true (release/package/linux/build-server.sh), then
PYTHONPATH=<dir with game_server_nue_pb2.py> server-sketch/sim/postmatch_replay.py --server-dir <build> [--quick]
server-sketch/sim/hang_model.py --md /tmp/model.md
POC=<EXVS2-POC checkout> tools/banapass-harness/build_and_test.sh        # needs g++ or clang++; mingw-w64 optional
dotnet test Tests/Matchmaking.Tests                                     # in the patched upstream tree
server-sketch/loadtest/hangsim_e2e.py --url http://127.0.0.1:28080/ --db <build>/ServerInfinite.db --log <build>/Logs/log-YYYYMMDD.txt [--watchdog-on --blacklist 200,4]
```
