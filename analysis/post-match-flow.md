# What happens after a versus match: results, rematch, instant team, option, continue, re-queue (2026-11-14)

Static analysis of `binaries/vsac29_Release.exe` (capstone + `tools/re`), cross-checked with the official
OverBoost / XBoost / Infinite Boost pages and the IB wiki, and with `captures/rpc2.log`. Nothing was run or patched.
**[C]** = read from the code, **[W]** = official site / wiki, **[I]** = inference.

Sources [W]:
* OB "リザルト画面でできること": https://gundam-vs.jp/extreme/ac2ob/howto/result/
* XB "リターンマッチ": https://gundam-vs.jp/extreme/ac2xb/othersystem/returnmatch/ ; "即席チーム": https://gundam-vs.jp/extreme/ac2xb/othersystem/team/
* IB "クレジットモード": https://gundam-vs.jp/extreme/ac2ib/howto/others/credit/ ; IB wiki glossary: https://w.atwiki.jp/exvs2infiniteboost/pages/172.html
* XB wiki changes: https://w.atwiki.jp/exvs2xb/pages/34.html

## 1. The order of things after a human-vs-human match

Nesting [C]: `CAcSeqPcbFaciliator` (game loop) → `CAcSecPcbPlayerBattle` (one "play", may contain several
battles) → network party → `CAcSeqBattleFlow_Player` (battle + results). The results screen and every prompt on it
live **inside the network party**. Continue / game over / re-queue happen only **after** the party has ended.

| # | Screen / prompt | Looks like [W] | Input | Timer | Shown when |
|---|---|---|---|---|---|
| 1 | **Results** (`CInHudResult`, task A `ResultAction` + S save + C capture + F finish) | WIN/LOSE, scores, class/grade change | none needed | F, C bounded (≤5 s per capture); S ≤10 s × 5 per call; `ResultConfirm` `Proc_WaitCounter` 300 frames [C] | always |
| 2a | **RETURN MATCH** window, top right (`CAcSeqBttleFlow_ReturnMatch`, HUD `CAWReturnMatch`, layout `/mc_returnmatch_matome`) | "リターンマッチ" window with countdown | **touch the same card** used at start (card id compared, 0x1406c1450 [C]), then the partner touches; "クレジットを投入してください" if the partner has no credit left; then **Start** | ≈7 s, +5 s per apply [I from HUD +0x68=7 / +=5] | **losing** side, online, **all 4 players carded**, winners able to continue, not Fes [W]; code: party flag +0x1fc, return-match count +0x13b0 < 2 unless debug #45, not modes 2/3/8/9/0xe, operator byte for modes 3–6, every member record +0x60/+0x61 set [C] |
| 2b | **TEAM REQUEST** (instant team, `CAcSeqBttleFlow_FormInstantTeam`) | "TEAM REQUEST" window top right → "スタートボタンで申請を完了します" → "チーム出撃に移行します" | card touch, then **Start**; both winners must apply | HUD countdown (length not found); mediator connect ≤15 s [C] | **winning** side of an online **solo (shuffle)** match, both winners carded and able to continue, and only if the losers did not start a return match [W]; code: flag +0x1fd and +0x4b8 == 1 [C] |
| 3 | **OPTION** window, top right (`CAcSeqBttleFlow_OptionWindow`) | small "OPTION" window; **hold Start** → menu: フレンド申請 / NG登録 / 強制終了 (and "return to mode select" in time rental) | hold Start, lever up/down, Start; friend/NG need a card touch | window closes with the results | after ResultConfirm (items 2a/2b) ends, if `0x14071bf00()` true, mode not 2/3, ResultAction+0x4bf == 0 [C] |
| 4 | *(party ends: results disappear)* | | | | |
| 5 | **Rematch entry** (`Proc_RequestEntryReturnMatch`) | VS screen again, same teams/units/stage; EX burst can be re-picked [W] | – | `Proc_WaitBattleInfo` 30 s [C] | return match was agreed (+0x13a8 == 1, +0x13ac == 0) [C] |
| 6 | **Continue check** (`Proc_CheckEndPlay`) | – | – | instant | otherwise [C] |
| 7a | **Post-battle** (`CAcSecPcbPlayerBattlePostBattle`): `CAcSecPcbBreakUpTeam` (ask whether to continue solo if the team broke up: CheckShift / CheckReturn windows), `CheckCustomMatch` / `CheckFesMatch` windows (room/event over), **10-win reset** window `T_RENT_10WIN` | short info windows | Start / timer (CTimer) | short | player may continue |
| 7b | **GAME OVER** (`CAcSecGameOver`: optional time-rental message, then GAME OVER) → card eject / title | GAME OVER | none | short | play is over |
| 8 | **Re-queue**: `CAcSeqPcbFaciliator` goes WaitPlayerBattle → **CreateWaitMatching** → new matching entry; a CPU battle (対戦待ちCPU戦) may run while waiting and can be broken into (`Proc_WaitBreakIn`) | "matching" screen | none | MMS polling | after 7a [C order of state names, I for the exact entry message] |

"Can continue" (`Proc_CheckEndPlay`, 0x1407a89a0) [C]: a global free/rental flag (+0x519) → yes; otherwise by
credit mode `0x14071bef0()->+4`: **1-credit** = continue only after a win, up to **10 wins** (+0x4e4 ≥ 10 ends it);
**2-credit** = 3 guaranteed battles + extra battles per win; **time rental** = until 30 min are up [W, credit page].
A loss in 1-credit mode → GAME OVER. There is **no "CONTINUE? insert coin" countdown in the versus flow** — the
`Proc_WaitContinue` / "僚機のコンティニュー開始待ち" / "コンティニュー処理へ遷移します" states exist only in
`CAcSecPcbTrainingBattle` (CPU/route modes) [C]. "Plus coin" (プラスコイン) is chosen before the game, not after [W].
Coin settings exist in the test menu "COIN OPTIONS": FREE PLAY / START COST / PLUS COIN COST / CONTINUE COST [C strings].

## 2. Rematch online vs LM [C unless marked]
* Decided on the results screen, **peer to peer**: `CAcSeqReturnMatchMediator` exchanges `PBNoticeMessageRequest`
  (RPC id 200) intents (start → apply → ready → establish) between the cabinets; no timer, ends on answer,
  peer-left or cancel.
* After the party ends, `Proc_RequestEntryReturnMatch` (0x1407a9db0) sends **`PBReturnMatchEntryRequest`
  (RPC 202)** to the battle host peer and goes back to `Proc_WaitBattleInfo` (30 s) for `PBNoticeBattleInfo` (203)
  / `PBNoticePlayer` (204) — the same peer messages used before a normal battle. `rpc2.log` shows PB 200/201/204
  going **cab ↔ cab directly**, not via LM or MMS.
* So rematch is the same online and in-store; **the MMS sees nothing** (no MM*/WE* message for it). The card
  server later sees `return_match_flag` / `revenge_num` in result and replay saves (`game_server_nue.proto`).
* Limit: party flag +0x1fc is false once the return-match counter +0x13b0 reaches 2, unless debug **#45**
  ("リターンマッチ回数制限解除"). The IB wiki says "only once" [W]; the counter probably counts the first battle too [I].
* Who accepts: the **losing** pair, both of them (card + credit + Start). The winners are not asked; they only
  need to be able to continue [W].

## 3. Re-queue / continue
* Winner (or anyone with credits/time left) → PostBattle windows → Faciliator `CreateWaitMatching` → matching again.
  The XB wiki notes casual-match players "go back to in-store-priority matching" after a continuing win [W],
  i.e. a **fresh entry**, not a kept room [I]. Our MMS already handles a cabinet re-entering right after a match
  (disconnect test: re-entry after "drop right after match" rematched in ~3 s) — see `disconnect-test.md`.
* Loser in 1-credit mode → GAME OVER → title / card eject; they need new credits to play again.

## 4. Server work needed
* **Rematch: none** for the MMS (peer-to-peer). Card server: accepts results with `return_match_flag` set (already
  a normal field) [I].
* **Re-queue: none new** — it's a normal EntryMatching. Keep the existing behaviour that a node can re-enter
  immediately after a match.
* Note: with our **CPU stand-in seats**, the return-match window should never appear (it needs all 4 players
  carded), and instant team needs both winners carded [W].

## 5. What this means for the results hang
* Continue / credit / game over / re-queue all run **after** the party (and the results screen) ends, and
  `CheckEndPlay` has no wait. A missing credit cannot hold the results screen. Free play only matters for the
  rematch "insert credit" step and for whether a loser can play again.
* In the hung matches (two humans as **opponents**, each with a **CPU partner**, local LM or online) by the
  official rules **neither RETURN MATCH nor TEAM REQUEST should appear** (both need carded partners). The capture
  agrees for rematch (no RPC 200 during the hang). That leaves the OPTION window path and the results tasks.
* "Holding Start does nothing" means the OPTION window was **not open yet** (or not created). OptionWindow is only
  created after `ResultConfirm` ends, so the hang is most likely **before** it: `ResultConfirm` (`Proc_WaitHud`
  waiting on a child) or the result HUD itself — or the gate is waiting on S/C/F while A never offered the option
  window. [I] Ranking otherwise unchanged from `results-hang-logs.md` §8.4.

## 6. Test for the user (no setup change)
In the next hung match: (1) note which cabinet **won**; (2) look at the **top right** of each results screen and
write down any window ("RETURN MATCH", "TEAM REQUEST", "OPTION") and any countdown; (3) after ~15 s, **hold Start**
for 2 s on one window, then do one **card touch** on one cabinet only; (4) stopwatch the hang; (5) after it ends,
note what each cabinet shows next (winner → matching? loser → GAME OVER?). Also check the test menu's
**COIN OPTIONS → FREE PLAY** value (read only, no EXIT & SAVE).
