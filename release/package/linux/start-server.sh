#!/usr/bin/env bash
# EXVS2 matchmaking server - Linux start (step 3). Runs in this terminal; stop with Ctrl+C.
# Logs: server-linux/Logs/log-<date>.txt. To run it in the background at boot, see exvs2-matchmaking.service.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="${SERVER_DIR:-$(dirname "$HERE")/server-linux}"
[ -x "$SERVER_DIR/Server-Infinite" ] || { echo "ERROR: server not built yet. Run ./linux/build-server.sh first." >&2; exit 1; }
# Minimal VPS images may lack the ICU library; the server works fine without it in invariant mode.
if ! ldconfig -p 2>/dev/null | grep -q libicuuc; then export DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1; fi
cd "$SERVER_DIR"     # the server reads Configurations/ and writes ServerInfinite.db + Logs/ in its own folder
exec "$SERVER_DIR/Server-Infinite" "$@"
