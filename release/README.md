# Release package (Windows + Linux)

Sources of the downloadable server package published on the
[Releases page](https://github.com/ServerOmega/exvs2-matchmaking/releases). Start with
[`package/START-HERE.txt`](package/START-HERE.txt).

The card server this builds on ([Chiang-17/EXVS2-IB-Server](https://github.com/Chiang-17/EXVS2-IB-Server)) has
**no license**, so the package contains **only our files**: scripts, instructions and
[`online-matchmaking.patch`](package/files/online-matchmaking.patch). The build script downloads upstream at the
pinned commit `7f4b280` (v1.2.0) from GitHub on the user's own PC, applies the patch and builds it there.
No upstream source and no compiled server is uploaded anywhere.

Our scripts and instructions in the package are GPL-3.0 (`package/LICENSE.txt`). The card server and
`online-matchmaking.patch` are **not** covered; see the License section of the main README.

| File | What it does |
|---|---|
| `1-Build-Server.bat` → `scripts/build-server.ps1` | portable git (MinGit, SHA-256 checked) and .NET 9 SDK (`dotnet-install.ps1`, local folder) if missing, download upstream @ 7f4b280, `git apply` the patch, `dotnet publish -r win-x64` (self-contained single exe), lay out `server/` keeping existing `Configurations/*.json` and `ServerInfinite.db`; optional copy of WebUI pictures / DB from an official v1.2.0 folder |
| `2-Configure.bat` → `scripts/configure.ps1` | Host (StunHost = LAN / VPN / public IP, BuiltinStun, FillAfterSeconds 15) or Player (local card server, MatchUrl + StunHost → remote matchmaker); writes `server.json` + `kestrel.json`; optional firewall rules (`scripts/firewall.ps1`, elevated) |
| `3-Start-Server.bat` | runs `server/Server-Infinite.exe` from its folder |
| `linux/build-server.sh`, `configure.sh`, `start-server.sh`, `exvs2-matchmaking.service` | same for a Linux PC / VPS (self-contained linux-x64, `-p:LinuxHost=true`), systemd example |
| `START-HERE.txt`, `Connect-Your-Game.txt`, `Public-Server.txt`, `Troubleshooting.txt` | plain-language instructions |

Build the zip: `release/make-release.sh v0.1.0-pre` → `release/dist/` (not committed).
