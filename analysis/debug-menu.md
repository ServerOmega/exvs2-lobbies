# EXVS2 IB "secret debug menu" (開発用設定 / Development Settings) — 2026-11-13

Tags: **[C]** confirmed (disassembly / source / page read), **[M]** inferred, **[L]** guess.
Exe analysed: box copy `binaries/vsac29_Release.exe` (md5 a5cdf4cf5a0922872ced752865424c85,
sha256 e4509672c9e61d91c7c3cc6f3390197264dcce40e39a9bb67f1b7f32676ed91c). The user's PC was
**offline**, so the game-folder DLLs (bngrw.dll, amactivator.dll, lmgrw.dll, wajvio.dll) and the live
`testmode_pcb.json` were **not** inspected. Nothing was downloaded, run, patched or launched.
File offset = VA − 0x140000C00.

## 1. What the community DLL is

* It is a **modified `bngrw.dll`** — the same hook DLL every PC setup already uses (the game imports `bngrw.dll`
  for the Banapass card reader; the EXVS2-POC project replaces it with its own build that hooks the exe with MinHook).
  Not a winmm/dinput8/version proxy and not injected by SnowLauncher. [C for the mechanism, from POC source]
* The NA/EN community guide (Google Doc, linked from the IB V29 "Mei Ver." Nyaa page) says:
  - "Ask for bngrwl.dll. This one has debug and fixes desync issue"
  - "Bngrw.dll: You need a modified one to access the debug menu to band-aid lag issues."
  - Lag section: "Test Menu -> Debug mode … you need to ask for proper bngrw.dll to access Debug mode",
    "Extra tweak in Test menu with delay input", delay-input table (ping <90 → 5, 90–110 → 5/6, >110 → 6, 150+ → 7, 200+ → ≥8).
  - Skins: "In Client: Test menu -> debug (bottom option with proper bngrw.dll) -> 3rd page" [C, doc read]
* **No public download for the IB build.** It's handed out on request in the community Discord ("ask for").
  The closest public things:
  - asesidaa/EXVS2-POC had `EnableDebugInPcb` (commit e6be8cd, PR #110, Feb 2024), which hooked the game's
    "dongle debug flag" getter so index 5 returned true. It was **removed** in 72edc17 (PR #114); on master (2343795,
    Aug 2025) the ini key is still parsed but nothing uses it. The POC also only supports VS2 4.00 / XB 4.50 / OB 4.80,
    and calls `fatal()` on an unknown exe, so the public build can't run IB. [C]
  - The OB "GOB10JPN27 Final" Nyaa release says "debug_bngrw.zip provided if needed for latency adjustments"
    (OB only, from the search-result snippet; page returned 502 when fetched). [C snippet / L contents]
* Who: POC authors asesidaa / alexia-midgar / oppenheimerbeach (the original hook). The IB fork's author is not
  named anywhere I found. [C / L]

Links (all actually opened or seen in search results):
* https://github.com/asesidaa/EXVS2-POC — source; `EXVS2-POC/game/DevMenuSubOptionsEnabler.cpp`, `config.ini`
* https://github.com/asesidaa/EXVS2-POC/commit/670dbdbcce516a05b248c300cc220feb9fb707cb (dev-menu option hook, ids 0/6/27)
* https://github.com/asesidaa/EXVS2-POC/commit/72edc177433a60582a536b1c33cd53ee97855833 (EnableDebugInPcb removed)
* https://docs.google.com/document/d/1JID3yWY1f5c8vzm8TCunHi00U-WpeE0Kc09rTTjv5wY/edit (community guide, "Lags" + "FAQ")
* https://nyaa.ink/view/2183606 (IB V29 Mei Ver., links the guide)
* https://nyaa.iss.ink/view/2004469 (OB Final, mentions debug_bngrw.zip)
* https://www.gamekee.com/exvs2xb/619101.html (SnowLauncher, Chinese wiki — launcher only, no debug DLL)

## 2. What's in the exe [C]

### 2.1 The menu
`CAcSecTestModeMenuDebug` (vtable 0x14165e810, ctor 0x140803320). Title **開発用設定** ("Development settings"),
help text: "通常操作では表示されません。ドングルで有効化されると表示されます。" ("Not shown in normal operation. Shown when
enabled by the dongle"). Items:

| item | meaning |
|---|---|
| 各種パラメータの確認... | parameter check (billing data, broadcast rx/tx ports, distributed resources) — `CAcSeqParamCheck` 0x140803ce0 |
| 各種ファイルチェック... | file browser — `CAcSeqTestModeMenuDebugFiler` |
| ルーティングテーブルを表示... | Windows routing table (GetIpForwardTable / GetIpAddrTable) — `CAcSeqRoutingTable` |
| HTTPレスポンスを確認... | HTTP response viewer — `CAcSeqTestModeMenuDebugNetworkDataView` ("ネットワークデータチェック") |
| リージョン(再起動で戻ります) | region override (until reboot) |
| デバッグパラメータエディット... | **debug parameter editor** — `CAcSeqParamEditor` 0x1408046a0 (below) |
| ルートバトルのデバッグ用セーブデータを編集... | Route Battle debug save editor |
| delete: リプレイデータ / LoadGameData / LoadRankingData / 課金エリア未初期化にリセット / リソースダウンロード進捗リセット | wipe replays, cached game/ranking data, billing area, resource-download progress |

It's added as the last item of both root test menus (client 0x140777500 at 0x140778361, LM 0x140775470 at 0x14077649e).

### 2.2 The gate (why you need a DLL)
```
0x140772ae0  -> 0x1406c0f70(Cpn=[0x14257b720], 4, 0)
0x1406c0f70  switch(id): case 4 -> 0x1406e3980(5)           ; "debug/dev" dongle flag
0x1406e3980(i): keychip obj [0x14287f6b0]; requires 0x1406e3b00(2)==0 (game id "2895" check) and
                0x140111460 (serial check); returns byte [obj+0x2c+i]
flags filled at 0x1400ffe20 from a 256-byte licence file read off a removable USB drive
(0x140111110: GetLogicalDrives/GetDriveTypeA==REMOVABLE, FNV hash): bit18→[0], bit0→[1], 0x20→[2], 0x2→[3],
0x4→[4], **0x40→[5] (dev menu)**, 0x80→[6], bit8→[7]
```
So on real hardware a developer USB dongle turns it on. A PC hook just makes `0x1406e3980(5)` (or `0x1406c0f70(.,4)`)
return 1. This is exactly the IB equivalent of the POC's old XB hook (`sub_debug`, XB 0x1406B6F90, `a1==5 → '1'`;
`a1==6 → '1'` "fixes LM to server connection" = IB flag 6 used by 0x1406c0bb0). [C for IB code; M that the community
DLL does it this exact way, since I couldn't read it]

What the same gate (case 4) also switches on, beyond the menu: [C]
* every debug option below (`0x1406d89b0(TestMode, n)` returns `debugParams[n]` only when the gate is on);
* EntryMatching sends **attr1 = TestMode `wanMatchingGroupId`** (0x1407baf3a) — see §3.

### 2.3 Debug parameter editor ("デバッグパラメータエディット") [C]
Numeric params, stored in `testmode_pcb.json` under `"debugParam"` (serializer 0x1406dec70, TestMode +0x4e8):

| JSON key | label | TestMode off |
|---|---|---|
| lanMatchingGroupId | 店内マッチングID (in-store matching ID) | +0x4f0 |
| wanMatchingGroupId | 店外マッチングID (WAN/online matching ID) | +0x4f4 |
| keyDelay | 入力遅延 (input delay — what the community tunes, 5–8) | +0x4f8 |
| ipMode | 実行IP種別 (IP type) | +0x4fc |
| classMatchSearchId | クラスマッチ検索ID | +0x500 |
| liveInitialBufferSize | 中継初期バッファサイズ(LM) (LM relay initial buffer) | +0x504 |
| initWinstreakCount | 初期連勝数 (starting win streak) | |
| routeBattleStageNum | ルートバトルステージ解放数 | |
| locateTestEnable / locateTestDebugValue | (location test) | |
| debugParams | the on/off list below (array, +0x510, 4 bytes each) | +0x510 |

On/off options (label function 0x140808c40, index = `0x1406d89b0` argument; POC's ids 0/6/27/37 match):

| # | label (JP) | English |
|---|---|---|
| 0 | ワークメータ表示 | work meter (POC "performance meter") |
| 1 | パフォーマンスカウンタ表示 | performance counters |
| 2 | 便利モード | "convenience mode" |
| 3 | 入力遅延固定化 | **fix input delay** (use keyDelay) |
| 4 | 特設筐体扱いにする | treat as special cabinet |
| 5 | HTTP通信を最速で行う | **HTTP at fastest rate** |
| 6 | ALLNETメンテナンス中でも接続を強行(JST 2-7) | force ALL.Net during JP maintenance (POC forces on) |
| 7 | 常にオフライン扱いにする(AllNet認証もNG) | always offline |
| 8 | ストレージ書き込みを無効化 | disable storage writes |
| 9 | 仮想カードタッチメニューを表示 | virtual card-touch menu |
| 10 | オンライン時でも時刻変更可能 | allow clock change while online |
| 11–12 | 課金データ生成… | generate billing data |
| 13 | バージョンが異なるリプレイを削除しない | keep other-version replays |
| 14 | サブLM未接続でもグループプレイ設定切り替え可 | group-play switch without sub-LM |
| 15 | 常駐処理(ネットワーク等)の詳細な状態を常に表示 | **always show resident (network etc.) task status** |
| 16 | リプレイの送受信状態を表示 | replay tx/rx status |
| 17 | 中継の送受信状態を表示 | **relay tx/rx status** |
| 18 | 店外マッチングログを表示 | **WAN matching log on screen** (used 28× in EntryMatching etc.) |
| 19 | クラッシュ時のランタイムハンドラ実行 | crash runtime handler |
| 20–22 | replay / reserved-file options | |
| 23 | 子の時刻を親に合わせる(LmMain側で指定) | sync child clock to LM |
| 24 | デバッグ対戦モード | debug battle mode (`CAcSecPcbDebugBattle`; "元に戻す場合は…デバッグパラメータエディットから解除") |
| 25 | 毎回リザルトキャプチャシーケンスを起動する | run result-capture sequence every time |
| 26 | リザルトキャプチャのアップロードステータスを表示 | show result-capture upload status |
| 27 | PCB1,2がいない際のエラーを無効化 | **no error when PCB1/2 absent** (POC forces on for clients) |
| 28 | 戦績保存リクエストでエラーを発生させる | force error on result-save request |
| 29 | リプレイ再生時に不正値検出で停止 | stop replay on bad value |
| 30 | LMアドレスリスト表示 | **show LM address list** |
| 31 | ランクマッチボーナス情報表示 | rank-match bonus info |
| 32–35 | time-limit shorteners (billing 1h, rental 5 min, rental end cmd, training 20 s) | |
| 36 | チュートリアル隠しコマンド | tutorial skip command |
| 37 | 機体選択中にターゲットボタン連打で機体スキンを変更 | skin change (POC "Quick Skin Change"; the guide's "3rd page") |
| 38 | 調整機体をランダムに設定 | random "adjusted" suits |
| 39 | 捨てゲー情報を表示 | show "thrown game" info |
| 40 | 毎日15時以降はOVERクラス開放 | OVER class after 15:00 |
| 41 | 基板情報表示 | **PCB info overlay** |
| 42–43 | アウトエフェクト停止 / 状態表示 | |
| 44 | 戦績保存リクエストの疑似レスポンス遅延(1分) | fake 1-min delay on result-save response |
| 45 | リターンマッチ回数制限解除 | unlimited return matches |
| 46 | バトルFPSログ保存(Profileビルド以上) | (not in Release) |
| 47 | 進行不能確認 | **"stuck/progress-blocked" check** (per-PCB state overlay 0x14074d000: mode / matching-wait etc.) |
| 48–49 | practice-battle shortcuts | |
| 50 | 機体選択画面のやり直しテスト | |
| 51–54, 58–60 | Route Battle debug (debug save, easy win, no time limit, bug codes, no chips, shop reroll) | |
| 53 | カードタッチ画面で称号を表示 | |
| 55 | 全てのタイマーを動作しなくする | **stop ALL timers** (would freeze timed screens) |
| 56 | UPDATE SERVER AUTH TOKENエラーを非表示 | hide that error |
| 57 | チーム情報ログ表示 | **team info log** |
| 61 | 決着後の残存サブタスク確認 | **check sub-tasks still alive after the match is decided** (0x1407c7178) |

Other debug classes present: `CAcSecPcbDebugBattle`, `CAcDebugSeqPcbFaciliator`, `CDebugWanMatchingGprintLog`
("店外マッチングにエントリーします(遅延)/(偽装)", "STUN解決…", hole-punch messages). [C strings; display details M]

## 3. Relevance to our matchmaking / online testing

1. **Results-screen hang** — #61 (sub-tasks left after the match), #47 (stuck check / per-PCB state), #15 (resident
   network task state) and #57 (team info) are the developers' own tools for exactly this kind of stall. Best next
   diagnostic if the user gets a working debug DLL. [C exists / M usefulness]
2. **Check that #55 "stop all timers" isn't on.** If the user's DLL turns the gate on and a shared/copied
   `testmode_pcb.json` has `debugParam.debugParams[55]` set, timed screens freeze. A solo route battle advancing argues
   against it, but it's a 10-second check of the JSON when the PC is online. [L]
3. **Lobby key without patching:** with the gate on, EntryMatching sends attr1 = `wanMatchingGroupId` (editable in
   the param editor). Our matchmaker already buckets on attr1 (`server-sketch`), so different
   "店外マッチングID" values = separate lobbies/regions, set in the test menu. [C send / M behaviour end-to-end]
4. **Network visibility:** #18 WAN matching log, #17 relay status, #30 LM address list, #41 PCB info, routing table and
   HTTP-response viewer — on-screen confirmation of what our server returned. [C exist]
5. **Server robustness tests:** #28 (force result-save error) and #44 (1-min fake result-save delay) let us test how the
   game reacts to a slow/failed card server. #5 HTTP fastest may shorten polling. [M]
6. **LM/topology:** #27 (no PCB1/2 error) and #14 (group play without sub-LM) relax LM pairing — relevant to the
   Sandbox / one-LM tests. `liveInitialBufferSize` tunes the LM relay buffer. [M]
7. **Input delay:** #3 + `keyDelay` is what the community uses for lag over VPN. [C per guide]
8. No direct "skip results" or results-timer item. [C for this list]

## 4. Safety

* The DLL replaces `bngrw.dll`, so it runs with full rights inside the game. It comes from private Discord
  sharing with no source or hashes. Treat it as untrusted: scan it, compare its exports with the current bngrw.dll,
  keep the old one, and ideally try it in the Windows Sandbox first. I didn't download one; there's no public IB copy to hash.
* It also changes other things (the guide says "fixes desync"; the POC version forced ALL.Net/PCB options), so it
  could change behaviour that our tests rely on. Note in test logs which bngrw.dll was used.
* The POC warned that enabling debug "will affect behaviors of (PS4 + XINPUT) Arcade Sticks".
* The debug-param values are saved in `testmode_pcb.json`. Back it up before saving from the dev menu, and undo
  options there (the game itself says so for #24).
* Lower-risk route we control: build our own minimal hook (or a POC fork for IB) that only returns 1 from
  `0x1406e3980` for index 5 (or `0x1406c0f70` id 4), optionally forcing single `0x1406d89b0` ids. Not done,
  and not proposed until the user wants it. First check whether the user's current bngrw.dll already shows the menu.

## 5. To do when the PC is online (read-only)
* Test menu → is there a bottom item "開発用設定" (or a translated "Debug"/"Development")? If yes, the current DLL already
  has it.
* `strings`/exports of the four DLLs. For bngrw.dll, look for MinHook, "debug", "EnableDebug", and the target RVA
  0x6e3980/0x6d89b0/0x6c0f70.
* `testmode_pcb.json` → `debugParam` block (values only; no card data in it).

## 6. Netcode-related options (added 2026-11-13, static analysis only)

Same tags: **[C]** confirmed in disassembly/proto, **[M]** inferred from code shape, **[L]** guess. Nothing was run,
patched or downloaded; the user's PC was offline, so none of this was tried in-game.

### 6.1 Short answer
* EXVS2 IB uses **delay-based (lockstep) netcode**. There is **no rollback setting, no packet-loss/latency
  simulator, and no "force relay"/"force P2P" switch** in the debug menu. I searched every UTF-8 string in the exe for
  遅延/ラグ/同期/パケット/ロス/疑似/STUN/NAT/P2P/RTT/rollback/latency/jitter and walked the xrefs. [C for absence in strings]
  (`Proc_Start_Rollback` exists but it belongs to `CAcSeqPcbModeSelectManager`, a menu "undo", not netcode.)
* The **only real tuning knob is input delay**: debug option **#3 入力遅延固定化 (fix input delay)** + param
  **keyDelay 入力遅延** (range **1–18 frames**). [C]
* Everything else network-related in the menu is **visibility/logging** (#15, #17, #18, #30, #41, routing table,
  HTTP viewer), **IP family** (`ipMode`), the **matching IDs** (lobby partitioning), or LM **live-broadcast** settings.
* Separately, the **card server** (not the debug menu) sends RTT/input-delay thresholds to the game in
  `LoadBlackList`, and the game reports real per-match RTT, packet loss and input delay back in
  `SaveVsmOnResult.network_report`. Those are server-side knobs/telemetry we control without any DLL. [C proto, M semantics]

### 6.2 Table

| # / key | Japanese label | What it does | Conf. | Hang | Matching | Lag tuning |
|---|---|---|---|---|---|---|
| **#3** `debugParams[3]` | 入力遅延固定化 | Sets engine debug-flag bit 0x1000 (mask built in 0x1406c2f90). Battle setup then uses `keyDelay` instead of the normal value: `CAcSecPcbPlayerBattleParty` (vs. humans, 0x14086a740) replaces its computed delay (`+0x680`, copied from the match/battle-flow data) with keyDelay; the CPU modes (practice/training/tutorial/route parties, 0x14084ac70) replace their fixed default **4F** with keyDelay. Needs the dongle gate. | C | no | no | **yes, the main knob** |
| **keyDelay** (TestMode +0x4f8) | 入力遅延 | Frames of input delay used when #3 is on. Editor limits **1–18**; the stored default wasn't confirmed, so set it before turning #3 on. Community table: ping <90 ms → 5, 90–110 → 5/6, >110 → 6, 150+ → 7, 200+ → 8+. | C range / C guide | no | no | **yes** |
| #2 `debugParams[2]` | 便利モード | Bit 0x40. Among other things it turns on an LM overlay: "LM input delay : %d", "Server delay param : A[%d] B[%d]", "Battle of over 6F : [%d]", "Local BlackList size : [%d]" (0x14072df40). | C (overlay) / M (other effects) | maybe | yes | read-only view |
| #15 | 常駐処理(ネットワーク等)の詳細な状態を常に表示 | Always show resident (network etc.) task status. | C label | **yes** | yes | view |
| #17 | 中継の送受信状態を表示 | Relay tx/rx status. In this game 中継 is mostly the **LM live-broadcast** ("対戦ライブ中継") path, so this is probably about broadcast/relay to the store monitor, not the P2P battle link. | C label / M meaning | low | low | low |
| #18 | 店外マッチングログを表示 | On-screen WAN matching log (`CDebugWanMatchingGprintLog`): STUN result ("M[%s] F[%s] NAT[%s] Net[%s]" = NAT mapping/filtering type), global/local addr+port, hole-punch result (タイムアウト / パケット受け取れず / **RTT閾値越え**), "店外マッチング情報[..] RTT閾値[..] 入力遅延閾値[..]", entry notes. 25+ call sites. | C | yes (pre-match) | **best one** | shows RTT threshold |
| #23 | 子の時刻を親に合わせる(LmMain側で指定) | Sync child clock to the LM. Clock sync, not frame sync. | C label | low | low | no |
| #30 | LMアドレスリスト表示 | Show LM address list. | C label | low | LM setups | no |
| #41 | 基板情報表示 | PCB info overlay. | C label | low | yes | no |
| #47 / #61 | 進行不能確認 / 決着後の残存サブタスク確認 | Stuck check / sub-tasks still alive after the match. Not netcode, but the best tools for the results hang. | C | **yes** | no | no |
| #5 | HTTP通信を最速で行う | Card-server HTTP at fastest rate (polling). Not battle netcode. | C label | no | maybe faster | no |
| #28 / #44 | 戦績保存リクエストでエラー / 疑似レスポンス遅延(1分) | Force error / fake 1-minute delay on the result-save request. The only "latency simulation" in the menu, and it is for the HTTP card server only. | C label | **yes (repro)** | no | no |
| **ipMode** (+0x4fc) | 実行IP種別 | 0 = auto (use detected), 1 = force IPv4, 2 = force IPv6 (mapped to Cpn+0x4a4; socket family AF_INET 2 vs AF_INET6 23 in 0x1402dfe60). Dongle flag 6 forces IPv4 regardless. Editor range 0–2. **Keep 0 or 1.** | C | no | IPv6 would break our STUN | no |
| **lanMatchingGroupId** (+0x4f0) | 店内マッチングID | In-store matching ID. | C | no | LM partitions | no |
| **wanMatchingGroupId** (+0x4f4) | 店外マッチングID | Sent as EntryMatching attr1 when the gate is on (0x1407baf3a). Separate values = separate lobbies with no exe patch. | C send / M end-to-end | no | **yes** | no |
| classMatchSearchId (+0x500) | クラスマッチ検索ID | Class-match search ID, range 0–5. | C range | no | ranked only | no |
| liveInitialBufferSize (+0x504) | 中継初期バッファサイズ(LM) | LM **live-broadcast** relay initial buffer, choices **0/10/20/30/40/50** (table 0x141652e50). Not the battle input buffer. | C values / M meaning | no | no | no (spectator only) |
| liveRelayLimitMode (bookkeeping json) | ライブ中継限定モード | LM live-broadcast-only mode (BookKeeping, not debugParam). | M | no | no | no |

### 6.3 Server-side knobs we already control (no DLL needed)
* **`Response.LoadBlackList`** (card server → game, `Handlers/Game/LoadBlackListQueryHandler.cs`, upstream sends
  rtt 300, restrict 300, permit 300, max_blacklist 1, delayed_frame 5). The game copies it into the LM's
  blacklist/delay object (0x140818fb0 → 0x140705f30): `threshold_delayed_rtt`, `threshold_delayed_frame`,
  `delay_restrict_condition` (A), `delay_permit_condition` (B), plus the `blacklist` (loc_id + rtt, max 20). [C copy; field
  order matched to proto layout = M]
  - The LM counts battles that ran with **more than 6F of delay** in a rolling **1-hour** window (0x14072df40,
    0xe10 s). When the count reaches **A** it broadcasts a "restrict" message (type 0xf/5) to the cabinets; when an old
    entry expires and the count is ≤ **B** it broadcasts "permit" (0xf/4). If **A = 0**, LM input delay is pinned to 4
    and the counting is skipped. [C control flow, M for what restrict/permit change in matching]
  - The RTT threshold is what the WAN log shows as "RTT閾値" and what makes hole punching fail with
    `UDPHP_FAIL_RTT_OUT_OF_LIMIT` ("RTTが閾値を超えました"). **If friends over long distance get punch failures, raise
    `threshold_delayed_rtt` on the card server.** [M]
  - The `blacklist` is the "unfitted locations" list; the cabinet then sends `bl_loc_ids` in EntryMatching so the
    matchmaker can avoid pairing badly-connected stores. [C fields / M behaviour]
* **`Request.SaveVsmOnResult.network_report`** (game → card server after every online match): per-PCB `rtt`,
  `packet_lost_rate`, `max_rtt`, plus `battle_pad_input_delay_frame`, `battle_start_delay_frame`, `delay_src_flag`,
  `total_posed_frame`, `total_posed_num` (stall/freeze frames and count), and `unfitted_locs`. **Logging this in our
  server gives real lag numbers per match without any debug DLL** — best first step for "lag tuning". [C proto]
* `Request.SaveLog` also carries rtt / request_count / timeout_count (card-server HTTP health). [C proto]

### 6.4 What to try (in order)
1. **Server telemetry, no DLL:** log `SaveVsmOnResult.network_report` and `LoadBlackList` traffic on mm-server2 /
   the card server. Gives the delay the game actually picked, RTT, loss and stall counts per match.
2. **If a debug-capable bngrw.dll is available (Sandbox first):** turn on #18 (WAN matching log) and #15, then do one
   online match: confirms NAT type, punch result and the RTT / delay thresholds on screen. Add #47/#61 for the
   results hang.
3. **Input-delay tuning:** set keyDelay (start at 5; 6–7 for VPN/long distance), then enable #3. Use the **same value on
   every cabinet** in a match — I could not confirm the game reconciles different fixed delays between peers [L].
   Note #3 also changes CPU-mode delay (default 4F), so turn it off for solo play.
4. Leave ipMode at 0/1, #55 off, and don't touch liveInitialBufferSize (spectator only).

### 6.5 Not found / unknowns
* No rollback frames, no frame-advantage/rift settings, no jitter or packet-loss simulator, no relay/TURN forcing in
  the debug menu (SRV_TURN exists only as a proto enum). [C absence in strings/menus]
* How the **normal** (non-fixed) online delay is computed from RTT: traced only as far as the battle-flow field
  (`+0x1284`, default 4, copied from a matching struct at `+0xcf8`). The exact RTT→frames formula is **not**
  confirmed; the community table above fits roughly ceil(RTT/2 / 16.7 ms) + 2–3. [L]
* What "restrict" vs "permit" changes on the cabinet side. [L]
* Community docs beyond the NA guide's delay table are thin; no public IB debug DLL or option list exists. The XB POC
  only exposed options 0 / 6 / 27. [C searches]
