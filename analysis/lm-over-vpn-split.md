# LM over a VPN, online traffic over the internet ("split")

Question (2026-11-13): a cabinet talks to its store **LM over an overlay VPN** (Radmin VPN, ZeroTier, Tailscale),
while its **online matching** (HTTP to the card server / MMS, STUN, P2P UDP to other players) uses the normal
internet. Does that work?

Tags: **[C]** verified in the exe (`vsac29_Release.exe`) or in the POC hook source, address given ·
**[M]** strong inference from the code · **[L]** Windows / VPN behaviour from documentation, not seen in the exe ·
**[?]** open, needs the real game.

## Verdict (short)

**Probably yes, but not with the hook's default settings.** With the default bind rewrite every game socket is pinned
to one IP, so the cabinet can use only one network: the VPN *or* the internet. The split needs:

1. `DisableSocketHook = true` on the cabinet, so the game's sockets stay on `0.0.0.0` and Windows picks the network per
   destination. The LM subnet goes through the VPN; everything else goes to the internet.
2. `InterfaceName` = the **VPN adapter**, so the address the game announces to the LM is reachable from the LM.
3. LM discovery is a **broadcast** to `255.255.255.255:49000` [C]. Windows has to send it out the VPN adapter
   (lowest-metric adapter), or a helper has to repeat it there [L].
4. The VPN must carry **only its own subnet**, never a default route. The STUN server address must be a public internet
   address. STUN then reports the internet IP, and the server puts the cabinet in the `internet` realm, the same as
   every home player.

Per VPN: **Radmin VPN** and **ZeroTier** carry broadcasts (ZeroTier: "Allow Ethernet Broadcast", on by default) [L].
**Tailscale does not carry broadcast or multicast at all** [L], so the LM most likely can't be found over Tailscale.
The exe has no unicast "LM address" setting that I could find [M]. None of this has been tried with the real game.

## 1. What the exe does

### 1.1 All game UDP goes through one socket class bound to 0.0.0.0 [C]
* The only game-side `socket`/`bind`/`sendto` users are `VDK::ENG::CWinUdpSocket` (vtable 0x14146f900; Open
  0x140304dd0, SendTo 0x140304fc0, RecvFrom 0x140305070/0x140305110) and its IPv6 twin `CWinUdpSocketV6`
  (0x140305290). The other `socket`/`bind` callers (0x140bcd4xx–0x140bce2xx) are the Havok debug-network code.
* Open binds **`0.0.0.0:<port>`** with `SO_BROADCAST`, without `SO_REUSEADDR`. The game never binds to a specific IP
  itself. The single-IP bind comes only from the POC hook (§2).
* The game has no `connect` on its UDP sockets. Every packet is a `sendto` to an explicit address, so with a
  `0.0.0.0` bind Windows chooses the outgoing adapter and source IP per packet from the routing table [C for
  sendto; L for Windows routing].
* There are no `GetBestInterface` / `GetIpForwardTable` calls (the import exists but has 0 xrefs). The game does not
  look at routes. It learns "its own IP" only from `GetAdaptersAddresses` (0x1402df9d0) [C].

### 1.2 Finding the LM: a broadcast on UDP 49000 [C]
* Cabinet boot sequence (`CAcSeqPcbRoot` proc names, string table 0x14147d4c8…): `Proc_InitializeNetworkData` →
  **`Proc_FindLM` → `Proc_WaitFindLM` → `Proc_ConnectLM`**. `Proc_CreateBroadCastManager` exists in both
  `CAcSeqPcbRoot` and `CAcSeqLmRoot`.
* Broadcast manager = singleton `[0x14257b7a8]`, ctor 0x1406ea220, driven by `SEQ::CAcBroadCastPre/Post`
  (vtable 0x14148b4e0; procs 0x140717490 → flush 0x1406ea7b0, 0x140717550 → receive 0x1406ea520).
  - The port is port-block +2 = **49000** (0x140346f10), and its own `CWinUdpSocket` is opened on `0.0.0.0:49000`.
  - Its "own IP" is the **first adapter the adapter-pick function marks** (0x1402df9d0, flag +0x10), stored at +4
    and copied into every packet header (0x1406ea72e).
  - Queue a packet (0x1406ea690): with no target given, the target is **`0xFFFFFFFF` = 255.255.255.255**, port 49000.
    Otherwise it is unicast to the given ip:port.
  - The receive loop (0x1406e7c70) reads packets and the sender address, hands them to a handler, and can reply
    through the same queue.
* A root-sequence proc (0x1406f25f0, with a near-identical twin at 0x1406f9970) builds a 0x40-byte message from **its adapter IP + its game
  port (port-block +0)** and posts it to the listeners. [M] This is the "here I am / find LM" announce that tells the
  other side where to connect.
* I found no setting, file or MMS field that gives a cabinet the LM's IP directly. RegisterPcb `lm_ip_addresses` is a
  card-server reply consumed by 0x1407329a0, not a discovery path for the LM link [M]. **So the LM link starts with a
  broadcast.**

### 1.3 The LM link and online P2P use the same port number [C], probably the same socket [M]
* Port-block +0 is the game port: 48000, then a terminal sets it to 48000+index+1, and a sub-LM adds 20 (0x140719de0).
  The main LM also builds a 16-entry port list 49000..49015 for its terminals (0x140719e78: `bx - 0x4098`).
* +0 is read by the cabinet's LM procs (0x1406f25f0, 0x140719a20) **and** by the WAN manager / online code
  (0x140755a20, 0x1407b8970, 0x1408226b0, 0x14082f430, …) [C]. Both paths announce "my adapter IP : port +0".
  [M] One P2P/RUDP stack (`CP2PSequenceRoot`, `CP2PSignalingTerminal`, `MATCHING::CRUDPSocket_Impl`) serves both the
  LM link and online peers. I did not trace whether it is literally the same socket object.
* Either way it doesn't block the split, because the socket is bound to `0.0.0.0`: a packet to the LM's VPN IP leaves
  through the VPN, and a packet to an internet peer leaves through the internet [L, Windows routing].
* `CP2PExternalInquiry` (ctor 0x1403565a0) opens its own v4/v6 `CWinUdpSocket` from a network-state callback
  (lambda vtable 0x142053bc0 → 0x140356970) [C]. Its port wasn't traced.

### 1.4 Which IP the game thinks it has [C]
* 0x1402df9d0 lists the adapters. With 2 or more, it skips names containing "Loopback" or "2" and marks the first
  remaining one. Everything above uses that marked adapter's IP as "my IP": the broadcast header, the LM announce,
  and the local IP sent to the MMS.
* With the POC, `GetAdaptersInfo` and `GetAdaptersAddresses` are faked to **one** adapter, the one picked by
  `IpAddress=` / `InterfaceName=`. So the game's "my IP" is always the hook's selected IP, and the skip rule doesn't
  matter.

### 1.5 Is the LM used during online play (battleMode 0)? [?]
* FindLM/ConnectLM is part of the **boot sequence** of every cabinet with `CLIENT_TYPE` terminal [C], so an LM-attached
  cabinet needs the LM link to boot. The hook's `EnableDebugInPcb` comment ("You can disable PCB 1 + 2 checking of LM in
  Debug Menu") points the same way [C in POC source].
* The WAN manager is created only by the PCB root and the LM never contacts the MMS ([lm-and-online.md](lm-and-online.md) §2.2) [C].
* Not known yet: whether the cabinet still sends anything to the LM *during* an online match (time, ranking, team
  sortie, LM schedule `ULGRequestLMSchedule`), and what happens if the LM link drops mid-match. **So the LM link must
  stay up the whole time**, and the split has to really work rather than just pass the boot check.

## 2. What the POC hook does to this [C in POC source, SocketHooks.cpp / Config.cpp / config.ini]

| Setting | Effect on the split |
|---|---|
| default (`DisableSocketHook = false`) | `bindHook` rewrites **every** AF_INET bind (game port, 49000 broadcast, ExternalInquiry) from `0.0.0.0` to the selected IP. All UDP is pinned to one adapter. |
| `IpAddress=` / `InterfaceName=` (one is required) | Chooses that IP. It also fakes the adapter list to only that adapter, so it becomes the game's "my IP" (§1.4), and sets `TenpoRouter` (shop router given to AmAuth) to that adapter's gateway. |
| `DisableSocketHook = true` | Leaves binds at `0.0.0.0` (the adapter list is **still** faked). config.ini says "Particularly useful for LM" and "For LM in Online Matchmaking, please mark this as true". Added in commit e6be8cd, 2024-02-09. |
| `connect` / `sendto` | not hooked |

Why a pinned bind breaks the split [L, Windows strong-host model, which has been the default since Vista]: a socket
bound to IP X only sends out the adapter that owns X.
* **Pinned to the VPN IP:** the VPN adapter has no route to the internet, so STUN/P2P to internet peers fails or never
  leaves. Even if it got out, the source would be an overlay address the internet can't answer. STUN only works if
  the STUN host is on the overlay too, and then it reports the overlay IP (the `radmin` realm in our server). That is
  the "everyone on one overlay" setup, not the split.
* **Pinned to the real NIC IP:** packets to the LM's VPN IP go to the home router instead of the VPN, and the
  255.255.255.255 broadcast leaves only on the real NIC, so the **LM is never found**. (This corrects the old
  workaround in lm-and-online.md §5, "each cabinet bound to its real NIC": that works for online but loses the LM.)

## 3. Recommended setup to test

Example addresses below. Use your own VPN subnet. Radmin VPN is 26.0.0.0/8, ZeroTier is whatever the network uses
(e.g. 10.147.17.0/24).

**LM machine (in the store, or the host PC)**
1. VPN installed and joined. POC `Mode = LM`, `DisableSocketHook = true` (the hook's own advice),
   `InterfaceName = <VPN adapter name>` (e.g. `Radmin VPN`), so the LM announces its VPN IP.
2. Windows firewall: allow `vsac29_Release.exe` UDP in on the VPN adapter (49000 and 48000–48020), profile Private.

**Cabinet (remote PC)**
1. VPN joined. Check the VPN adds **no default route**: `route print -4` should show `0.0.0.0/0` only via the real
   NIC's gateway, and the VPN only with its subnet (Radmin: `26.0.0.0/8`). ZeroTier: leave "Allow Default Route"
   off. Tailscale: don't use an exit node (and see the broadcast caveat).
2. POC: `Mode = Client`, `DisableSocketHook = true`, `InterfaceName = <VPN adapter name>`.
   `Server =` the card server's **public internet** host/IP, not its VPN IP, so HTTP and STUN go over the internet.
3. Make the limited broadcast leave on the VPN [L]:
   - Option A: give the VPN adapter the lowest interface metric:
     `Set-NetIPInterface -InterfaceAlias "<VPN>" -InterfaceMetric 1`. The default route stays on the NIC, because the VPN
     has no default route.
   - Option B: run a broadcast repeater (WinIPBroadcast-style) that copies 255.255.255.255 packets to every adapter.
   - Radmin VPN and ZeroTier then carry it to the LM.
4. Firewall as on the LM, plus UDP in on the real NIC for online P2P (48000+terminal).

**Check, in this order** (each line is in TESTING.md):
1. The cabinet boots past the LM check (FindLM → ConnectLM). If not, capture on the VPN adapter:
   `pktmon` / Wireshark, `udp.port == 49000`. Do you see the broadcast leaving the cabinet, and the LM's reply?
2. Server log `NET entry`: `local` = the cabinet's VPN IP, `global` = its **internet** public IP, realm `internet`,
   no `stun-missing`.
3. Match against a home player (no VPN): `MATCH-NET` shows `global` dialling, and the battle starts and finishes.
4. During the battle, watch traffic to the LM. Does anything go to the LM's VPN IP? Then unplug the VPN for 30 s:
   does the cabinet drop the match, or only complain afterwards?
5. Two cabinets of the same LM in one online room (same home NAT): the dial uses `local` = VPN IP (same global IP →
   local address, 0x140794590), so that pair goes over the VPN. Does that battle start?

**If step 1 fails and only Tailscale is available:** the LM link can't be fixed without a broadcast; use Radmin VPN or
ZeroTier for the LM link.

## 4. Proposed hook change (not applied, documented only)
These make the split work without changing the adapter metric. They are POC changes, not exe patches.
* **`BindOverlayPorts = 49000`** (proposal): with `DisableSocketHook = true`, still pin only these ports to the
  selected IP. The broadcast socket then sends out the VPN, and the game/STUN socket stays on `0.0.0.0`. Small change
  in `bindHook`: check `ntohs(sin_port)` against the list before rewriting.
* **`BroadcastRewrite = <subnet broadcast>`** (proposal, e.g. `26.255.255.255`): a `sendto` hook that changes the
  destination 255.255.255.255 to the VPN's directed broadcast, which Windows routes over the VPN. Directed broadcast
  over Radmin/ZeroTier is [?].
* **Unicast LM address** (idea only): a `sendto` hook that also sends each 49000 broadcast to a fixed `LmAddress`.
  That would also work on Tailscale, but only if the LM accepts a unicast find packet [?].

## 5. What stays open
* [?] Does the LM answer the source address of the find packet, or the IP inside it? If the second, `InterfaceName`
  must be the VPN adapter (§3), which is why the setup uses that.
* [?] What the cabinet sends to the LM during online play (§1.5).
* [?] Is the LM link literally the same socket as online P2P (§1.3)? It doesn't change the setup.
* [L] Broadcast handling per VPN version. Re-check if a VPN update changes it.
