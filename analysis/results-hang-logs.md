# Results-screen hang — log comparison (2026-11-13, times PT)

Status: **partial** (static analysis added in §7). The test PC was offline (after the Windows Sandbox reboot) when this was written, so the
card-server logs (`_re\mm-server\server-out*.log`, `_re\mm-server2\server-out*.log`), game/LM/SnowLauncher logs
and the Windows event log could **not** be read. No log or capture of the solo route battle vs CPU (≈17:30–19:00)
exists on the analysis box. The only data on the box is the UDP capture of one **hung two-LM local match**
(`captures/all.tsv`, 16:58:19 → 17:03:10), decoded with `captures/rpc.py` / `rpc2.py`. So the CPU-vs-versus
**API-call diff was not possible yet**; §4 lists the exact read-only commands to collect it.

Legend: **[C]** confirmed from data, **[I]** inferred.

## 1. What the capture covers
| Time (PT) | What happens | Evidence |
|---|---|---|
| 16:58:19 → 16:58:51 | Tail of the **previous** match's results-screen hang (capture started during it) | cab↔cab peer stream at 60 Hz each way, no battle inputs, no reliable messages [C] |
| 16:58:51.561 / .569 | **Both cabinets leave the results screen 8 ms apart**: each sends LM state message (id 8, state 6→5→0x0b) and closes the peer session (id 3 / 9) | rpc2.log [C] |
| 16:58:58 → 17:00:07 | Back to entry: card entry, LGEntryPrepare, DecideTeam, LM pairing | [C] |
| 17:00:07 → 17:00:43 | Peers connect (id 2 / 13 / 522 / 523 / 620), RM packet-loss exchange, battle starts ≈17:00:43 | [C] |
| 17:00:43 → ≈17:01:50 | Battle: input field in the peer packets is non-zero (button bits), `c400` keyframe packets every 0.5 s | [C] |
| 17:01:50.28 | Battle end: cab2 → cab1 `RMNoticePacketLossInfoRequest` (501) + RM spreads; `c400` packets stop; 1 Hz `c101` packets start (same pattern as 16:58:19–16:58:51) | [C] |
| 17:01:58 / 17:01:59 | Each cab → its LM: `LGReportSoftwareVersionRequest` (answered within 33 ms / 19 ms) | [C] |
| 17:01:59 → 17:03:10 (end) | **Hung on results**: peer stream steady at 60 Hz both ways, **zero reliable messages** to LM or peer for 70 s+ | [C] |

## 2. Findings from the hung match
1. **Neither game is frozen.** Both keep sending their 60 Hz lockstep packets with increasing frame/seq numbers
   through the whole hang, and the two streams stay in sync (`c105` ack seq on each side tracks the other). [C]
2. **Input reaches both games during the hang.** At 17:02:1x, 17:02:2x and 17:02:5x the peer packets carry
   non-zero button bits (0x04, 0x10, 0x40, 0x70, 0x80 …), identical on both cabinets (the POC keyboard hook drives
   both windows). The results screen is therefore **not waiting for a button press**; it ignores input. [C]
3. **Nothing is pending on the LM link.** Every cab→LM request in the window was answered in < 40 ms; there are no
   retransmissions during the hang. (One earlier exception: at 16:58:51 cab1's state message was retransmitted
   5× and LM1 answered after ≈380 ms; cab2/LM2 answered in 32 ms. Small, recovered, and *after* the hang.) [C]
4. **No LM replay traffic.** No `LGReplaySend*/LGReplayRecv*` messages appear after the battle. [C] (TCP/HTTP was
   not in this capture, so HTTP card-server calls are not visible here.)
5. **Exit is simultaneous and self-initiated.** At 16:58:51 both cabinets started leaving within 8 ms, with no LM
   or peer message before it that could have triggered it. Either a synchronized step in the lockstep simulation
   (a frame-counted timer — `CAcSeqBttleFlow_ResultConfirm` has a `Proc_WaitCounter` state) or two identical
   timeouts that started on the same frame. [C timing, I cause]
6. **Short stalls during the earlier hang.** At 16:58:28.8 cab1, then at 16:58:30.1 cab2, each stopped acking for
   ≈0.5 s (the other side re-sent a growing bundle of unacked packets, 72 → 492 → 816 bytes) and then caught up.
   Each instance stalled once, one after the other. Possibly window focus / GPU contention between two instances
   on one PC, possibly the user switching windows. [C stall, I cause]

## 3. Candidates for what the results screen waits on (from the exe, not yet confirmed)
After a versus match the game runs flows that a solo route battle does not necessarily run:
* **Result capture upload**: `CAcSeqBattleFlow_ResultCapture`, `CAcSeqResultCaptureManager`
  (`Proc_RequestCapture`/`Proc_WaitCapture`/`Proc_UploadCapture`), `CAcSeqResultCaptureUpload`
  (`Proc_WaitUpload`), HTTP `SaveResultCapture` (method 224) → server returns
  `http://{Host}/upload/uploadImage/{cardId}/{token}` → game HTTP-PUTs the image (token valid 2 min).
  The upstream server implements both; whether our builds log/answer them in the split setup is **unknown until
  the server logs are read**. Debug options #25/#26 (force result capture / show upload status) exist for it. [C strings, I relevance]
* **LM background replay upload**: `CAcSeqLmBackGroundUploadReplay` (`Proc_RequestPreSaveReplay`,
  `Proc_WaitResponce`, `Proc_RequestUpload`), `CAcSeqLmServiceReplayUpload`, plus `/upload/uploadReplay/...` on the
  card server. No LM replay messages were seen in the capture. [C strings, I relevance]
* **Results-confirm counter** (`CAcSeqBttleFlow_ResultConfirm`: `Proc_WaitCounter`, `Proc_WaitHud`) — fits the
  simultaneous exit in §2.5. [I]
* **Result save** (`SaveVsmOnResult`): earlier captures showed HTTP 200 from both card servers, so not a
  missing response; response *time* was not checked. [C 200, unknown latency]

## 4. Logs still to collect (read-only, when the PC is back)
```powershell
$G='E:\Games\Mobile_Suit_Gundam_Extreme_Vs._2_Infinite_Boost\EXVS2IB_V29'; $R="$G\_re"
# server logs: every API call with time, 15:00-19:30 PT
Get-ChildItem "$R\mm-server\server-out*.log","$R\mm-server2\server-out*.log" | select FullName,Length,LastWriteTime
Select-String -Path "$R\mm-server*\server-out*.log" -Pattern 'Mthd|Save|Upload|ResultCapture|Replay|Error|Exception|Timeout|PUT ' |
  % { $_.Line -replace '(?i)(chip_?id|access_?code|boot_?token|session_?id)\S*','$1=<masked>' }
# other game/LM/launcher logs and dumps
Get-ChildItem $G, "$G`_P2" -Recurse -Include *.log,*.txt,*.dmp -ErrorAction SilentlyContinue |
  ? LastWriteTime -gt '2026-11-13 15:00' | select FullName,Length,LastWriteTime
# Windows Application log for the game
Get-WinEvent -FilterHashtable @{LogName='Application'; StartTime='2026-11-13 15:00'; EndTime='2026-11-13 19:30'} |
  ? Message -match 'vsac29|SnowLauncher|LM' | select TimeCreated,Id,ProviderName,Message
```
Diff to make: the API calls after battle end in the route battle (expect `SaveStageResult`/route save, maybe no
`SaveResultCapture`) vs the versus matches (`SaveVsmOnResult`, `SaveResultCapture`, `PUT /upload/uploadImage`,
`PUT /upload/uploadReplay`), with request→response times and the gap until the next call (`LoadCard`/entry) —
that gap is the hang length.

## 5. Most likely cause (inference)
The hang is a **wait inside a versus-only post-match step that ends on a timeout**, not a freeze and not the
input/LM link. Best candidates in order: (1) result-capture/replay upload not completing (HTTP upload step,
which would show in the card-server logs), (2) a results-confirm counter waiting on a peer/seat condition that
never becomes true with two instances on one PC. The "two instances on one PC" theory from the earlier test
report is still possible but this capture does not show interference beyond the two 0.5 s stalls.

## 6. Next tests
1. **Read the server logs** (§4) — decides candidate (1) immediately: if `SaveResultCapture` or a `PUT
   /upload/...` appears at battle end and the next call comes minutes later, or never gets a response, that's it.
2. **One cabinet alone in versus**: close cab2, enter the same online mode on cab1 only, let `FillAfterSeconds`
   make a 1-human room with CPUs. Hang → it's the versus post-match flow (server/upload), not two instances.
   No hang → points at two instances on one PC; then run the Sandbox cab2 test.
3. If the dev menu is available: #26 (result-capture upload status), #61 (sub-tasks alive after the match) and
   #47 (stuck check) on the results screen show the waiting task by name.
4. Time the hang with a stopwatch from the results screen to the exit — a fixed length every time (e.g. 120 s =
   upload token expiry) points to a timeout.

## 7. Static analysis of the post-match flow (2026-11-13 night, exe only, nothing patched)
Method: capstone + pdata/xref helpers in `tools/re` on `binaries/vsac29_Release.exe`. State names are not
referenced by code (debug tables only), so states were identified by RTTI/vtables and the `[obj+0x468]` "next state"
writes. **[C]** = read directly from the code, **[I]** = inference.

### 7.1 What gates leaving the results screen after a versus match [C]
* Versus battles run `CAcSeqBattleFlow_Player` (vtable 0x141604348). Practice / training / tutorial / replay flows
  have different gate functions (0x1407d1ae0, 0x1407dbcf0, 0x1407dcc20, 0x1407de3a0), so a CPU-only battle does not go
  through this gate.
* The skeleton's wait state 0x1408864f0 calls vfunc +0x120 each frame and leaves only when vfunc **+0x128** returns true.
  For the Player flow that is **0x1407c9990**: all four post-match sub-tasks must be gone:

  | letter (#61 overlay) | handle | task | created at |
  |---|---|---|---|
  | F | +0x114c | `CSeqAcBattleSubFlow_Finish` (ctor 0x1408dfef0) | 0x140883b20 |
  | S | +0x2260 | `CAcSeqBttleFlow_SaveResult` (card-server save) | 0x1407c8fc0 |
  | A | +0x2268 | `CAcSeqBttleFlow_ResultAction` (ctor 0x14088dcf0, results HUD / option window) | 0x1407c63c0 |
  | C | +0x2270 | `CAcSeqBattleFlow_ResultCapture` (ctor 0x14088ec50) | 0x1407c69c0 |

  Debug option **#61** (0x1407c7000) prints exactly this: "残存タスク : " followed by F / S / A / C / R (R = battle
  sub-flow #7 not yet in state 1). So with the dev menu, #61 names the task that blocks.
* 0x1407c87f0 (vfunc +0x68 path) aborts them: S gets an abort flag (0x14088cd80), A is told to close (0x14088e850),
  C is killed.

### 7.2 Time limits of each gating task [C]
* **F (Finish):** frame-scripted (counter +0x638 compared with 0x3c/0x1e0/0x1ea/0x24d frames); no open-ended wait found.
* **C (ResultCapture):** up to 3 captures, each waits at most **0x12c = 300 frames (5 s)** (0x14088f420).
* **A → ResultConfirm** (`CAcSeqBttleFlow_ResultConfirm`, vtable 0x1418b3ae0): `Proc_WaitCounter` (0x1408e4a60)
  waits ≤ **300 frames**, then `Proc_WaitHud` (0x1408e4ac0) waits until its child tasks are gone (**no limit of its own**).
  Its child is `CAcSeqBttleFlow_FormInstantTeam` (ctor 0x1408f0c50), created only when flag +0x617 is set
  (= match object vfunc +0x160 && +0x4b8 == 1; 0x1408e49c0) — the after-match "form an instant team with your partner"
  prompt (card touch / button), with `CAcSeqFormInstantTeamMediator` (vtable 0x1418a72b8) negotiating with the peer:
  connect wait ≤ **15 000 ms** (0x1408dfb40, `cmp ms, 0x3a98`), then `WaitStartIntent` (0x1408dfc00) waits **with no
  timer** for the local choice (+0x5f4), and the result waits (0x1408dfc70 / 0x1408dfe10) resend an intent every 10
  frames until the peer answers or leaves the session (0x1408df940).
* **S (SaveResult):** every card-server call is a libcurl POST with **CURLOPT_TIMEOUT = 10 s** (builders 0x1406d2430 /
  0x1406d29b0 set +0x60 = 10; libcurl wrapper 0x1402d7480). On an error response (`error != 0`) the request is resent,
  **max 5 tries** (counter +0x1020, e.g. 0x14088cfa0 / 0x14088d250), then the task exits. Its exit state 0x14088d800
  only waits for an in-flight request; the **60 s hold** (`cmp elapsed_us, 0x3938700`) applies only when the dev gate is on
  **and debugParams[44]** ("fake 1-min result-save delay") is set. Worst case without the dev menu ≈ 5 × 10 s per save call,
  and only if the server doesn't answer at all.

### 7.3 HTTP upload / server endpoints
* The libcurl wrapper supports PUT (type 1: CURLOPT_UPLOAD/PUT/MAX_SEND_SPEED) and ranged GET (type 2), but the only
  three request builders (0x1406d2120 = GET type 2, timeout 10 s; 0x1406d2430 / 0x1406d29b0 = POST type 0) never set
  type 1. **No PUT caller was found in this exe** [C for the 3 callers of 0x1402d8260, I that PUT is unused], so the
  `/upload/uploadImage/...` URL from `SaveResultCapture` (and its host: `Request.Host`, i.e. whatever host the cabinet
  used) is **not** what the results screen waits on. `/upload/uploadReplay` is the LM's path.
* `ResultCapture` (task C) is the frame-buffer capture and is bounded to 5 s per image regardless of the server.
* Server (`online-matchmaking`): every request type the game sends is answered immediately; unknown types get
  `ErrServer "Unhandled case"` (still a fast answer). Unhandled in `GameController`: `SaveFailedBattleLogOn`,
  `SaveVsmToResult`, `SaveMedal`, `RegisterOption`, `UsePCoinTicket`, `LoadAccessCode` (+ `LoadRoom/RegisterRoom` on
  this controller). A fast error makes the game retry ≤ 5 times and move on — it cannot cause a minutes-long wait. [C]
* `SaveResultCapture` returns `ErrServer` when the card's `SessionId` doesn't match (fast answer, task C isn't affected).

### 7.4 What fits the capture (§2) [I]
* The hang is in the Player flow's gate, which a CPU-only battle never enters — matches "CPU route battle OK".
* During the hang there are **zero reliable messages** on the peer link. The mediator's result states resend every
  10 frames, so they are **not** active; the server save task (S) would show HTTP, not UDP. What fits a silent wait
  is A: `ResultConfirm → FormInstantTeam` / mediator `WaitStartIntent` (waiting for the local player's choice, no timer
  in the mediator), or a HUD inside `ResultAction`'s option window. Both cabinets would start such a HUD countdown on the
  same lockstep frame, so they also end it on the same frame — matches the 8 ms-apart exit.
* So the leading hypothesis is now **the VS-only "instant team / option" prompt after the results (task A)**, not the
  card server and not the upload. Whether the prompt is actually shown (flag +0x617) depends on the two humans being
  partners on the same team; that wasn't recorded for the hung matches. Second candidate: task S waiting on HTTP
  timeouts (would need ≥ 10 s of silence per request in the server log). Server/upload is unlikely: the same hang
  occurs in local LM mode without the matchmaker, and all post-match HTTP waits are bounded (10 s × ≤ 5).

### 7.5 Next tests (in order)
1. **Server logs** (§4) once the PC is back: per match, the times of `SaveVsmResult`/`SaveVsmOnResult`,
   `SaveBattleLog(On)`, `SaveUserPlayResearchData`, `SaveResultCapture`, any `Unhandled case`, and the next `LoadCard`.
   If every post-match call is answered in < 1 s, S is ruled out.
2. **Note the team layout and the screen.** Were the two humans partners (same team) or opponents? During the hang,
   is any window / countdown / "card" prompt visible over the results? Try a **card touch** (client key `4`) and each
   button once during the hang; a card touch ending it at once confirms the FormInstantTeam prompt.
3. Repeat with the humans on **opposite teams** (CPU partners). If that doesn't hang but same-team does → task A
   (instant-team prompt). Stopwatch the hang both ways.
4. If the dev menu becomes available: **#61** on the results screen shows the remaining letters (F/S/A/C/R) — the
   definitive answer. Check that **#44** (60 s save hold) and #55 are off.
5. Sandbox / two-PC test as planned — if task A is the cause, it should hang there too (it's game logic, not the OS).

No server-side fix is proposed: nothing the server returns gates this wait beyond 10 s per call. No exe patch was
applied or written.

## 8. Follow-up: the two humans were opponents (2026-11-13, ~23:00 PT, static only)
User report: in every hung match the two human cabinets were **opponents** (each with a CPU partner), and there was
no lag. This section re-checks §7.4 against that. **[C]** = read from the code, **[I]** = inference.

### 8.1 Correction: the instant-team prompt is NOT ruled out by "opponents"
* `+0x617` (ResultConfirm start, 0x1408e49c0) = `party->vfunc+0x160()` && `ResultConfirm+0x4b8 == 1` [C].
* The party object is `CAcSecPcbPlayerBattleParty` (vtable 0x14176b258). Its +0x160 is **0x1408685a0** [C]:
  it needs party flag +0x1fd ("instant team allowed", copied from the battle param +0xf5 built in 0x1407a9070),
  then finds the local member's team id (+0x1c0 of the 0x2e0-byte member record), and returns true only if
  **every party member on my team** has a map entry (party+0x158) with +0xc0 != 0.
* With one human per team (our setup: human + CPU partner) the loop only checks the local cabinet itself, so it
  **can be true for opponents** [C code / I meaning]. §7.4's "only when the two humans are teammates" was an
  inference that the code does not support.
* +0xf5 is false when `0x14071bef0()->+4` is 2 or 3, when `[+0x4d8]+0x52c != 0`, when `[+0x4d8]+0x528 != 2`, or when
  the mode `[+0x4e0]+0x710` is 0xc, 3, 7 or 0x13 (0x1407a93fe–0x1407a946b) [C]. The meaning of these values for
  LM-local vs online versus is not mapped yet.
* `CAcSeqFormInstantTeamMediator::WaitStartIntent` (0x1408dfc00) waits for the local choice and **sends nothing** [C],
  which still fits the capture (§2: no reliable message during the hang).

### 8.2 New: the return-match ("rematch") flow — applies to opponents [C]
* `ResultConfirm` start also calls 0x1408e4120, which creates **`CAcSeqBttleFlow_ReturnMatch`** (ctor 0x1408ef8a0,
  vtable 0x14191ce00) when `party->vfunc+0x158` (0x1408687e0) is true: party flag +0x1fc ("return match allowed",
  param +0xf4) and every member record has bytes +0x60 and +0x61 set. Nothing here depends on teams.
* Param +0xf4 (0x1407a9352–0x1407a93fb) is false when the return-match count `+0x13b0 >= 2` (unless debug **#45**
  "リターンマッチ回数制限解除" is on), in the same modes 2/3 as above, when `[0x14257b7a0]+0x4cc == 4`, when
  `[0x14257b7a0]+0x4d8 != 0`, for modes 8/9/0xe, or for modes 3–6 when an operator setting byte
  `0x1406bfd90()->+0x48` is 0.
* `ResultConfirm::Proc_WaitHud` (0x1408e4ac0) waits until all its children (ReturnMatch and, if created,
  FormInstantTeam) are gone. It has no timer of its own.
* ReturnMatch states (names at 0x14191ca20…): CheckStart / WaitCheckStart / WaitApply / WaitCardTouch-like
  polling of the card reader (0x14287f638 = bngrw card reader wrapper: 0x140106b50 start touch wait,
  0x140106cf0 poll, 0x140106f90 cancel → `BngRwReqCancel`) / WaitCardError / WaitCardBusy (0x1408f0660:
  re-arms the card wait every 16 frames) / Apply / WaitReady / WaitHud / Exit.
* The decision comes from a **card touch** (0x1408f0330 → decision 1, plus credit check 0x1406c1450) or from three
  HUD callbacks (lambdas 0x14191ce70/cea8/cee0 → 0x1408f0250 / 0x1408f01e0 / 0x1408f0150: "no decision → 2,
  cancel"). The countdown therefore lives in the HUD widget `EXVS2::HUD::CAWReturnMatch`. The shared HUD struct
  gets `+0x68 = 7` at prompt start and `+= 5` on each apply (0x1408efd43, 0x1408efb20, 0x1408f0590), which looks
  like a **7 s countdown, +5 s per apply** [I]. That is far shorter than the observed > 70 s hang.
* Its peer handshake is `CAcSeqReturnMatchMediator` (vtable 0x1418a6ce8, created by party vfunc+0x168 =
  0x140867590). States: Setup → SendStartIntent → WaitOtherStartIntent → WaitStartResult → SelectApplyIntent →
  WaitOtherApplyIntent → WaitApplyResult → Ready → WaitOtherReady → WaitEstablish → Exit. Every step sends
  **`PBNoticeMessageRequest` (RPC id 200)** to the peers (0x140821460 with message vtable 0x1415bcf38). The wait
  steps end on peer answer, peer-left (0x1408dde20 compares the group's member count) or cancel; **no timer** [C].
* **Capture check:** after battle end (17:01:50) and during the earlier hang tail (16:58:19–16:58:51) there is
  **not one id-200 message** either way, while 175 of them flowed at 17:00 before the battle [C]. SendStartIntent
  sends as soon as ReturnMatch has decided availability (first frame, 0x1408f0470 always sets +0x5e8 to 1 or 2),
  so **ReturnMatch did not run during the hang** (not created, or `+0x4a0 == 0`, which exits at once in
  0x1408f02b0) [I, strong].

### 8.3 Other versus-only result tasks
* `ResultAction` (vtable 0x1417b5488): Start (0x14088e9a0) → OpenHud (0x14088ea10) → **CreateConfirm** on the next
  frame (0x14088e1d0) → WaitConfirm (0x14088eb60) → CreateOption (0x14088e490) → WaitOption (0x14088ebc0) →
  Shutdown (0x14088eaa0) [C]. S (SaveResult), A (ResultAction) and C (ResultCapture) are all created together
  by Player vfunc+0x118 (0x1407c8fc0), so a slow save does not delay the confirm/option windows [C].
* `CAcSeqBttleFlow_OptionWindow` (0x1408e2ca0): OpenWindow / WaitWindow (0x1408e3890, waits for a HUD choice in
  struct+0x19c or HUD-closed functor) / **WaitCardTouch** / WaitCardError / WaitCardBusy / WaitCloseHud. Also
  card-reader driven (0x1408e30d0 polls 0x140106cf0) [C]. It is created only after ResultConfirm ends, and only
  when `0x14071bf00()` is true, the mode is not 2/3, and ResultAction+0x4bf is 0.
* **Common thread [I]:** all three versus-only result tasks (ReturnMatch, FormInstantTeam, OptionWindow) wait on
  the **bngrw card reader** (touch / busy / error states) and are ended by a HUD countdown. A route battle vs CPU
  runs a different flow with a different gate (0x1407d9f30) that does not include ResultConfirm's prompts.
* SaveResult retries are immediate re-requests (0x14088cfa0 → 0x14088d890 = jmp 0x14088b860; no extra delay) [C].
  The 60 s hold (debug #44, 0x14088d800) also applies to the route-battle save path (same exit state; the route
  gate 0x1407d9f30 also waits on its tasks), so #44 being on would most likely hang route battles too.
  Since route battles do not hang, #44 is probably off [I].
* `CAcSecPcbPlayerBattle` (vtable 0x1415bcd98) has a 30 000 ms timeout in 0x1407ac820, but that is the
  **pre-battle** wait for `PBNoticeBattleInfo`/`PBNoticePlayer` (flags +0x1288/+0x1289 set by RPC handlers
  0x14085dde0/0x14085de40) [C], so it is not this hang.

### 8.4 Revised ranking
1. **Instant-team prompt (`FormInstantTeam`, A)**: still possible with opponents (§8.1), silent on the network,
   waits for a card touch / choice and is ended by a HUD countdown. This fits "no messages", "inputs ignored" and
   "both leave together". Inferred; the length of its HUD timer is not known yet.
2. **OptionWindow card-touch wait (A, after ResultConfirm)**: same pattern, also silent. Inferred.
3. **A bngrw card-reader state that never completes** on one instance (touch wait / busy) with two instances on one
   PC. This would keep any of the above in a WaitCard* state until the HUD gives up. Inferred; the bngrw.dll in use
   was not inspected (PC offline).
4. ReturnMatch handshake: **ruled out** by the capture (no id-200 messages) [I, strong].
5. Card server / HTTP: unlikely (unchanged from §7; every wait is bounded by 10 s × ≤ 5 and local-LM mode hangs too).
No server-side setting found that controls +0x1fc/+0x1fd (they come from local mode/counter/operator values), so
there is **still no server-side fix**; nothing was built.

### 8.5 Most decisive next test (no setup change)
In the next hung match: start a stopwatch when the results screen appears, wait ~15 s, then do a **card touch on one
cabinet only** (the card key of that window). Note whether anything appears or the screen moves on, then do the same
on the other cabinet. Write down the total hang length.
* The hang ends or a prompt reacts to the touch → it is one of the card-touch prompts (§8.4 #1–#3).
* Nothing reacts, and the length is the same each time → a fixed timer. Then the server-log timings (§4) and debug
  #61 (if the menu can be unlocked) are next.

## 9. Post-match flow mapped (2026-11-14, static + official docs)
Full map in [post-match-flow.md](post-match-flow.md). Effect on the diagnosis:
* Continue / credit / GAME OVER / re-queue run **after** the network party (and the results screen) ends;
  `CAcSecPcbPlayerBattle::Proc_CheckEndPlay` (0x1407a89a0) has no wait and the versus flow has **no
  "insert coin to continue" state** (that exists only in `CAcSecPcbTrainingBattle`). Ruled out as the hang [C].
* Rematch is peer to peer (RPC 200 intents, then `PBReturnMatchEntryRequest` 202); the MMS is not involved [C].
  Officially it needs all 4 players carded, and instant team needs both winners carded [W], so with human + CPU
  teams neither prompt should appear — consistent with the capture (no RPC 200 in the hang).
* "Holding Start does nothing" ⇒ the OPTION window (hold Start opens its menu [W]) was not open, so the stall is
  most likely before `OptionWindow` is created: in `ResultConfirm`/result HUD, or in S/C/F with A never reaching
  the option window [I]. Next test: §6 of post-match-flow.md.
