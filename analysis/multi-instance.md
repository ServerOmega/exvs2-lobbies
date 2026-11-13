# Running several EXVS2 IB clients on one PC (for matchmaking tests)

Status: **research only, nothing tried in the real game yet** (2026-11-13).
Sources: static analysis of the box copy of `vsac29_Release.exe` (md5 a5cdf4cf…, capstone/pefile scripts in `tools/re/`),
the open-source hook DLL [asesidaa/EXVS2-POC](https://github.com/asesidaa/EXVS2-POC) (`EXVS2-POC/`, commit 2343795,
2025-08-11), POC issue [#62](https://github.com/asesidaa/EXVS2-POC/issues/62) and PR [#68](https://github.com/asesidaa/EXVS2-POC/pull/68).
No patches were applied to anything.

Tags: **[C]** confirmed in disassembly or source, **[M]** inferred, **[L]** not traced or guessed.
File offset = VA − 0x140000C00.

> **Main caveat:** the IB package's `bngrw.dll` is not the public POC build. The POC only knows VS2 4.00, XB 4.50 and OB 4.80,
> so the IB package ships a fork (SnowLauncher or community-built). Everything below that relies on hook features
> (bind rewrite, base-path argument, G:/F: redirect, per-instance config) is **[M] until checked on the user's `bngrw.dll`**
> (§6, step 0).

## 0. TL;DR
* **The exe has no single-instance lock.** It creates no named mutex, event, semaphore or file mapping, never calls
  FindWindow, and has no `Global\`/`Local\` strings [C]. The POC hook source has no guard either [C].
  SnowLauncher itself may refuse a second launch [L], so start the exe directly.
* **The one hard collision is UDP ports.** The client binds UDP sockets to `0.0.0.0:<fixed port>` without SO_REUSEADDR
  (defaults 48000 + terminal offset, and 49000) [C]. A second copy on the same IP fails to bind.
* **The fix already exists in the hook (POC):** `bind()` is rewritten to the IP chosen in `config.ini`
  (`IpAddress=` / `InterfaceName=`), and the adapter list the game sees is faked to that one IP [C in POC].
  Give each instance its own IP, for example two IPs on a Windows loopback adapter or a Linux dummy interface, and
  the ports no longer collide.
* **Per-instance files:** the POC takes an optional **single command-line argument = base path**. `config.ini`,
  `card.ini` and every write the game makes to `G:/` or `F:/` (where `./29/testmode_pcb.json`, `bootparam.bin`,
  bookkeeping and similar live) go there [C in POC + exe]. PR #68 added this explicitly "so you can run multiple clients
  out of one directory". Assets still load from CWD, so both instances share the game folder.
* **Peers on the same machine can reach each other:** if a peer's STUN global IP equals your own, the client dials
  the peer's *local* ip:port instead (0x140794590) [C]. Distinct local IPs per instance are therefore enough, with or
  without a real NAT.
* **Input is not focus-gated:** the POC reads the keyboard with `GetAsyncKeyState`, and raw input uses `RIDEV_INPUTSINK` [C].
  Both instances react to the same keys, including **Kill = Esc**, so give each instance different key bindings.
* **Recommended:** Windows 11 native, a KM-TEST loopback adapter with 3 IPs (servers + 2 clients), and two base-path
  folders. Each client does a team sortie with a CPU partner, so 2 humans + 2 CPUs make a full room.
  Use real + `fake_cabinet.py` only as a first step: it proves "match found", but fake peers can't start a battle.
* Confidence: **medium**. Exe-side facts are high; that the IB hook behaves like the POC is unverified.

## 1. Single-instance guards [C]
| Check | Result |
|---|---|
| `CreateMutexA` (IAT 0x1413954f8) | 29 call sites (0x1412e…–0x14133…, CRT/middleware); **every one passes lpName = NULL** (`xor r8d,r8d`) |
| `CreateEventA` (0x141395500) ×5, `CreateEventW` (0x141395300) ×14 | all lpName = NULL (`xor r9d,r9d`) |
| `CreateEventExA` (0x1413954e0) ×6 | all lpName = NULL (`xor edx,edx`) |
| `CreateSemaphoreW` (0x141395240) ×3 | all unnamed |
| `FindWindow*`, `OpenMutex`, `CreateFileMapping*`, `LockFile*` | **not imported**; strings absent. `UnmapViewOfFile` is used only in a handle-cleanup helper (0x140111c40) |
| Window | one `RegisterClassExW` / `CreateWindowExW` in `nu::Window_x64::Initialize` 0x14027e9d0 (class registration is per-process) |
| `GetForegroundWindow` | one call at 0x1400a21a7 (nu framework): passes a "not focused" flag to listeners via vtable +0x18. Effect not traced [L]; not a lock |
| POC hook (`bngrw.dll`) | no mutex, window or file guard in source [C] |

## 2. Shared or fixed resources

### 2.1 UDP ports (the real blocker) [C]
* Port block allocated in 0x140347700 (called from 0x1406eb814) and stored at global `[0x14287f830]`:
  `mov dword [rax], 0xbf68bb80` (0x140347742, file 0x346B42, bytes `C7 00 80 BB 68 BF`) and
  `mov word [rax+4], 0xbf68` (0x140347748). Result: **+0 = 48000, +2 = 49000, +4 = 49000.**
* `+0` is the WAN/STUN game port. STUN setup 0x140755a20 copies it to mgr+0x4e8 (0x140755ab1). The STUN NAT test
  compares the mapped port with it (0x1407b8b63), and the WAN entry code reads it (0x140822a19, 0x14082bf2f).
* `+0` is adjusted by terminal identity in 0x140719de0, with kind/index at `[0x14257b750]`/`[0x14257b752]`:
  kind 1 (PCB terminal, index 0..15) → `48000 + index + 1`; kind 2 with index ≠ 0 → +20; and kind 2 index 0 (main LM)
  builds the list 49000..49015 (`bx - 0x4098`) for the 16 terminals. Terminal value mapping (0x1406e19fe):
  1..16 → kind 1 index v−1, 100 → kind 2 index 1, 101 → kind 2 index 0.
  Kind comes from **`CLIENT_TYPE`** in `./29/bootparam.bin` (0x1406eb960: 1/3 → kind 1, 2/4 → kind 2).
* `+2` (49000) is bound by the singleton `[0x14257b7a8]` (ctor 0x1406ea220, created from 0x1406f5ad9 and
  0x1406fce69, which are PCB/LM root procs) through `VDK::ENG::CWinUdpSocket` (vtable 0x14146f900). Its role is probably the
  LAN/terminal socket [M].
* Socket open `CWinUdpSocket::Open` 0x140304dd0: `socket(AF_INET, SOCK_DGRAM)`, `bind(0.0.0.0:port)` (0x140304e4d), then
  SO_BROADCAST, SNDBUF 64 KiB, RCVBUF 128 KiB, FIONBIO, `SIO_UDP_CONNRESET` off. **No SO_REUSEADDR**, and a failed bind
  closes the socket and returns −1. A second process on the same IP and port therefore fails. Whether that error is fatal
  was not traced [L].
* An IPv6 twin exists (`CWinUdpSocketV6`, vtable 0x142053518, chosen in 0x140356970 by a flag). The POC passes IPv6
  binds through unchanged. RegisterPcb `ipv4_flag = true` (already set by IB-Server) should keep the client on IPv4 [M].
* `hkBsdSocket` (Havok) has `bind`/`listen` (0x140bcdee0) for the Havok visual debugger. It's assumed unused in release [M].
* Own IP: 0x1402df9d0 calls `GetAdaptersAddresses(AF_INET)`. With ≥ 2 adapters it skips any whose description contains
  "Loopback", and takes the **first remaining adapter's** first IPv4. With one adapter it takes that one [C]. The POC
  replaces this list with a single fake "Ethernet Adapter" holding the configured IP, so a KM-TEST loopback adapter is
  **not** filtered when the hook is active [C in POC].

### 2.2 Files and paths
* Storage roots, selector 0x140100910 (jump table 0x140100b50) [C]:

  | type | root |
  |---|---|
  | 0 | CWD |
  | 1, 3 | global path `[0x14287f130]` |
  | 2 | CWD + `/data/x64/localStorage` |
  | 4 | `G:/` |
  | 5 | `F:/` |
  | 6 | `H:/` if it exists, else `C:/Arcade/Dump/` |

* The config/save JSON loaders (0x14019b050, 0x14019b1e0, 0x14019b350 … 0x14019b7a0) open their path on **type 4 (G:/)
  and type 5 (F:/)** [C]. These cover `./29/testmode_pcb.json` (pointer 0x1424049e8), `./29/testmode_lm.json`, bookkeeping,
  `./29/bootparam.bin` (0x142404b40), `./29/time_rental/…`, `./29/tournament_data.json` and others [C for testmode/bootparam;
  M for the rest].
* POC `GameFileSystemHook`: any `CreateFileA` on `G:`/`F:` is **redirected to `<basePath>/<rest>`** [C in POC]. That makes all
  per-cabinet settings (battleMode, terminal number, bootparam) **per base path**.
* The CWD stays the game folder: assets come from CWD (`/data/x64/` at 0x1406d504c), and PR #68 notes "the game builds
  resource paths from cwd". Shared and read-only, so this is fine.
* Possibly shared writable items [L]: `CWD/data/x64/localStorage` (type 2), `29log/BattleLog_*.txt`, the `C:/Arcade/Dump`
  crash dumps, and whatever the package's `nbamsavdat.dll` (save-data API, not hooked by the POC) writes.
  Check with Procmon on Windows or `WINEDEBUG=+file` on Wine during the first two-instance boot.
* POC per-instance files: `<basePath>/config.ini` (hot-reloaded), `<basePath>/card.ini` or `card.txt`, or `CardFileBasePath` [C].

### 2.3 Identity per instance
* **Card:** each instance needs **its own card** (its own `card.ini` in its base path). One card on two cabinets gives
  the same am_id twice, which would confuse partner/blacklist logic and `SaveVsmOnResult`. Never copy or print the
  card values. Let the game or card server create a fresh test card for instance B. Mix Match (0:00–7:00) and in-store
  match also work without a registered card (see `casual-shuffle-matching.md`).
* **PCB serial / PcbId:** POC `Serial=` (4 digits, prefixed per version) and `PcbId` default `ABLN` + serial[5:] [C in POC].
  Use `0001` and `0002`. IssueNodeId ids come from a global counter in our servers (`NodeIdAllocator.cs`,
  `mms_server.py`), so node IDs are unique regardless [C].
* **loc_id:** comes from the auth/card server, so both instances will normally share it ("same shop") [M]. That
  is what in-store worlds 15/16 need (attr2 = hex of the last 4 loc_id chars; `fake_cabinet.py --same-loc` simulates
  this). Other worlds only separate same-loc players if the card server's `LoadBlackList` puts that loc in `bl_loc_ids`.
  Our matchmaker checks `BlLoc` (Matchmaker.cs:198 / mms_server.py:182) [C].
* **Terminal number / CLIENT_TYPE:** they live in the per-base-path `bootparam.bin` / testmode. Giving the two instances
  different terminal numbers also gives them different `+0` ports (48001 vs 48002) [C], but 49000 stays the same.

### 2.4 Hardware emulation (POC) [C in POC]
JVS (`COM3`) and the card reader (`COM4`) are faked by returning a dummy handle, so there's no real device to fight over.
AmAuth is COM-hooked in-process with no listening ports. The `iauthdll` registration ("Initialize iauthdll.bat") is
machine-wide and done once. `nbamUsbFinderGetSerialNumber` returns `Serial`. **Nothing here blocks two instances.**

### 2.5 Watch out: forced reboot path [C call, L trigger]
0x1406e229e calls `ExitWindowsEx(EWX_REBOOT|EWX_FORCE)` after a token-privilege adjust (store/terminal manager code
around 0x1406e21d1). The POC does not hook it. What triggers it (probably a settings change or an LM-commanded reboot) was not traced.
Save your work before testing on bare Windows. A VM or Wine contains it.

## 3. Network: can two instances on one PC match and play?
* **MMS/card server:** both talk HTTP (libcurl) to the same card server (`Server=127.0.0.1`). The POC hook does not touch
  `connect()`, so 127.0.0.1 stays reachable even with a bound IP. ForceBindIP used to break this (issue #62) [C].
* **Peer address choice (0x140794590, WAN path, mode ≥ 0xa)** [C]: it finds the peer in the matched list, then compares
  the peer's global IP string with your own (0x1406c37b0). If equal, it uses the peer's **local** IP (+0x20) and port (+0x30);
  otherwise it uses global IP (+0xc) and port (+0x1c).
  * Same public IP via an internet STUN server, both behind one NAT: equal, so local addresses are used and no hairpin is needed.
    This only works if the **local IPs differ** (or the ports differ, see §5 W-alt).
  * STUN server on the test host at the loopback adapter IP: each instance's "global" IP is its own adapter IP, which differs
    between instances, so the peer's adapter IP is dialed. Works too.
  * NAT hairpinning is never needed for same-PC tests.
* **STUN must answer from an address the instances can reach from their bound IP.** Put the STUN responder on the
  loopback adapter itself (e.g. 10.250.0.1). Without RFC 5780 OTHER-ADDRESS the NAT test ends at result 4, which does not
  block entry (matchmaking.md §7.4) [C]. Behaviour when STUN gives **no** binding answer at all is not traced [L].
* **Firewall (Windows):** a KM-TEST adapter shows up as "Unidentified network" (Public profile), so inbound UDP to the game is
  blocked by default. Set the profile to Private and allow `vsac29_Release.exe` (§6 step 2).
* **Options compared:**

  | Option | Separates IP? | Notes |
  |---|---|---|
  | Loopback adapter (Win) / dummy iface (Linux) with N IPs + hook `IpAddress=` | yes | simplest; needs the IB hook to have the POC bind rewrite |
  | Radmin/N2N TAP adapters, one per instance | yes | proven by issue #62 (OB era, with ForceBindIP + metrics); heavier |
  | Linux `ip netns` + veth per Wine instance | yes, even without a hook | X11 abstract sockets are per-netns (use the filesystem socket or Wayland); point `Server=` at the veth host IP |
  | Hyper-V VM / Windows Sandbox | yes | GPU-P/D3D12 in a VM is fragile; 20+ GB game; Sandbox needs Pro edition and may allow only one instance |
  | Same IP, different ports (exe copy patched, §5) | ports only | relies on the same-global-IP → local-address rule; untested |

## 4. GPU, window, input, audio
* **Window:** POC `Windowed=true`, `BorderlessWindow=false`, `Resolution=720p` lets two windows sit side by side (8K needs
  borderless) [C in POC]. D3D12 (`d3d12.dll`, `CreateDXGIFactory2`). Two D3D12 instances at 720p are easy for an RTX 5070 Ti [M].
* **Frame rate:** the arcade timing assumes 60 Hz. On a high-refresh monitor, set `FramerateLimit=true` (POC limiter) [M].
* **Input focus:** the keyboard is read with `GetAsyncKeyState` (global) and controllers through raw input with `RIDEV_INPUTSINK`
  (background) [C in POC]. The exe's own XInput path polls pad `[obj+0x34]` with no focus check (0x14029239c) [C]. So **both
  instances see every key and pad.** Use disjoint keyboard binds (A: WASD/ZXCV/1/5/F3; B: arrows/numpad/2/6/F4), and
  **different `Kill=` keys** (Esc would kill both). Disable `[controller]`/XInput on one instance, or pick `DeviceId` per instance.
  Note that `Test`/`Service` (F1/F2) also hit both, so change them.
* **Audio:** the POC wraps WASAPI and passes the game's share mode through [C]. If the game opens the device in exclusive mode,
  the second instance's audio init would fail [L]. Use `[audio] DeviceName=` per instance or `DisableHook` and mute one.

## 5. Recommended setups (ranked)

### W1: Windows 11, loopback adapter + per-instance base path (best; feasibility medium-high)
0. **Verify the IB hook** (on Windows or from Linux):
   `strings -n 6 bngrw.dll | grep -E "Invalid commandline \(expected only a path|Selecting interface by address|Socket Bind Enabled|Redirect to"`
   All four present means the POC features below exist. If they're missing, go to W-alt or L2.
1. Build and run the patched card server (`server-sketch/ib-server`, `OnlineMatching.Enabled=true`, `StunHost=10.250.0.1`).
   Run a STUN responder bound to `10.250.0.1:3478` (coturn via WSL2 mirrored networking, or a small Python STUN responder,
   **not written yet**; see §7).
2. Add the adapter: `hdwwiz` → Network adapters → Microsoft → **Microsoft KM-TEST Loopback Adapter**. Rename it `EXVS-LAB`, then (admin PowerShell):
   ```powershell
   New-NetIPAddress -InterfaceAlias EXVS-LAB -IPAddress 10.250.0.1  -PrefixLength 24
   New-NetIPAddress -InterfaceAlias EXVS-LAB -IPAddress 10.250.0.11 -PrefixLength 24
   New-NetIPAddress -InterfaceAlias EXVS-LAB -IPAddress 10.250.0.12 -PrefixLength 24
   Set-NetConnectionProfile -InterfaceAlias EXVS-LAB -NetworkCategory Private
   New-NetFirewallRule -DisplayName "EXVS2 lab" -Direction Inbound -Program "<game>\vsac29_Release.exe" -Action Allow -Protocol UDP
   ```
   POC caveat [C]: `IterateInterfaces` loops `for (cur = list; cur->Next; …)`, which **never checks the last adapter**.
   If EXVS-LAB is enumerated last, selection fails with "Failed to find interface". Usually Windows' "Loopback
   Pseudo-Interface 1" comes after it, but check the hook log.
3. Instance folders `D:\exvs-inst\A` and `\B`. Copy in the current `config.ini` and the current G:/F:-redirected storage
   tree (wherever `29\testmode_pcb.json` lives today; under SnowLauncher that's probably the base path = game root).
   **Back up first**, then set `battleMode: 0` in each copy with `svd1.py`. Don't use "EXIT & SAVE".
4. `config.ini` per instance: `Mode=Client`, `Serial=0001`/`0002`, `IpAddress=10.250.0.11`/`.12` (comment out
   `InterfaceName`), `Server=127.0.0.1`, `Windowed=true`, `BorderlessWindow=false`, `Resolution=720p`, `FramerateLimit=true`,
   disjoint `[keyboard]` binds and Kill/Test/Service keys, `[controller] Enabled=false` on one.
   Card: A keeps the existing card. B gets a **new** card (empty `card.ini` in B; let the game or server create one).
5. Launch from the game folder (CWD = game root), not through SnowLauncher:
   `start "" vsac29_Release.exe D:\exvs-inst\A` and `start "" vsac29_Release.exe D:\exvs-inst\B`.
   Check each hook log for `bind(...) -> 10.250.0.1x:<port> = 0`.
6. Test: both instances do **team sortie with CPU partner** in Mix Match (world 23). The matchmaker then has 2 human + 2 `"N"`
   entries, a valid 2v2 room. Capture with Wireshark/Npcap on EXVS-LAB to get the hole-punch/P2P format (TESTING.md item).

### W-alt: same IP, port-shifted exe copy (needs a patch; feasibility medium; **document only, never apply to the user's files**)
If the IB hook has no bind rewrite: make a **local copy** of the exe for instance B (never in a shared, backed-up or repo location)
and change the port constants:

| VA | file off | original | change (example) |
|---|---|---|---|
| 0x140347744 | 0x346B44 | `80 BB 68 BF` (48000 / 49000) | `E4 BB CC BF` (48100 / 49100) |
| 0x140347749 | 0x346B49 | `68 BF` (49000, the +4 word) | `CC BF` (49100) |

Both instances bind 0.0.0.0 on different ports. Their global IPs are equal, so each dials the other's local IP with the
other's port, which works on one host [M]. Free alternative to try first: give B a different terminal number (separate
`+0` port) and see whether the 49000 bind failure is fatal [L].

### L1: Arch + Wine/Proton, dummy interface (feasibility medium-low)
Same as W1 but with `sudo ip link add exvs0 type dummy && sudo ip addr add 10.250.0.1/24 dev exvs0 && …11 … 12 && sudo ip link set exvs0 up`,
coturn natively (`listening-ip=10.250.0.1`), one Wine prefix, two `wine vsac29_Release.exe Z:\…\inst\A` launches.
Unknowns: whether IB runs under Wine/vkd3d-proton at all, and whether Wine's `GetAdaptersAddresses` lists all secondary IPs
(the POC's address match needs that) [L]. Proton/Steam launches the same non-Steam game only once at a time, so use
umu-launcher or plain wine with the same prefix.

### L2: Arch + network namespaces (fallback with no hook bind rewrite; feasibility medium-low)
Per instance: `ip netns add exvsA`, a veth pair to the host (10.250.1.1 ↔ 10.250.1.11), then
`ip netns exec exvsA sudo -u $USER env WAYLAND_DISPLAY=… DISPLAY=:0 wine …`. X11 abstract sockets don't cross netns,
so use the filesystem socket or Wayland. `Server=`, `StunHost` and the match URL must use 10.250.1.1, not 127.0.0.1.

### H: one real instance + `fake_cabinet.py` (feasible today; partial)
**What it proves:** the real client's RegisterPcb, IssueNodeId(2), STUN start, EntryMatching (world/attr/groups), CheckMatching
polling, team parsing (`group_id`), and the transition into P2P setup. You can also capture the client's first hole-punch packets
if the fake peers' `global_ipaddress:global_port` point at a UDP listener you control.
**What it can't prove:** battle start, P2P exchange, rank exchange or results. The fake cabinets don't speak the game's P2P
protocol, so the real client will time out or error after "match found".
Use it as step 1, before setting up two real instances. Tip: give the fakes `--same-loc` only for in-store worlds 15/16.

### Not recommended
Hyper-V GPU-P or Windows Sandbox (D3D12 in a VM is fragile, heavy, and Sandbox needs Pro). Two physical PCs or a
friend always works and is the final check anyway.

## 6. What to check at home (in order)
1. `bngrw.dll` strings (W1 step 0), and where `29\testmode_pcb.json` actually lives (that's the base path SnowLauncher uses).
2. How SnowLauncher starts the client (its command line, from Task Manager → Details → Command line column).
3. First double launch: both hook logs show successful `bind` on different IPs. Note any boot error that looks like a network or terminal error.
4. Procmon (or `WINEDEBUG=+file`) for writes outside the base path (localStorage, 29log, nbamsavdat).

## 7. Follow-ups (not done)
* Tiny STUN Binding responder in `server-sketch/python/` (stdlib only, one IP, so no RFC 5780) for local Windows tests.
* A `launch-two.ps1` that creates instance folders without touching the originals or copying card data.
* Trace whether a failed 49000 bind is fatal (singleton 0x1406ea220 stores the result at +0x10).
