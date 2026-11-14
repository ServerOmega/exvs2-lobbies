#!/usr/bin/env bash
# EXVS2 matchmaking server - Linux build (step 1). Same as 1-Build-Server.bat, for a Linux PC or VPS.
# Downloads the EXVS2-IB-Server source (pinned commit) from GitHub, applies the exvs2-matchmaking patch,
# and builds a self-contained linux-x64 server into ../server-linux. No root needed.
# Needs: bash, curl, unzip, git (sudo apt install curl unzip git   /   sudo dnf install curl unzip git).
set -euo pipefail

UPSTREAM_REPO="Chiang-17/EXVS2-IB-Server"
UPSTREAM_COMMIT="7f4b28057631dbd7801c0b079b8455dcaa9c9a7b"   # v1.2.0
RUNTIME="${RUNTIME:-linux-x64}"                              # or linux-arm64 for ARM VPSes (untested)

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
TOOLS="$ROOT/tools"
BUILD="$ROOT/build"
SERVER_DIR="${SERVER_DIR:-$ROOT/server-linux}"
PATCH="$ROOT/files/online-matchmaking.patch"

step() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[ -f "$PATCH" ] || fail "files/online-matchmaking.patch is missing. Re-extract the whole zip."
for t in curl unzip git; do
  command -v "$t" >/dev/null || fail "'$t' is not installed. Install it first (e.g. sudo apt install curl unzip git)."
done
if pgrep -f "$SERVER_DIR/Server-Infinite" >/dev/null 2>&1; then
  fail "The server is running. Stop it first (Ctrl+C, or: sudo systemctl stop exvs2-matchmaking)."
fi
mkdir -p "$TOOLS" "$BUILD"

step "1/4  Checking for the .NET 9 SDK"
DOTNET=""
for c in "$TOOLS/dotnet/dotnet" "$(command -v dotnet || true)"; do
  if [ -n "$c" ] && [ -x "$c" ] && "$c" --list-sdks 2>/dev/null | grep -q '^9\.'; then DOTNET="$c"; break; fi
done
if [ -z "$DOTNET" ]; then
  echo "    .NET 9 SDK not found - installing a private copy into tools/dotnet (~250 MB, no root needed)"
  curl -fsSL https://dot.net/v1/dotnet-install.sh -o "$TOOLS/dotnet-install.sh"
  bash "$TOOLS/dotnet-install.sh" --channel 9.0 --install-dir "$TOOLS/dotnet" --no-path
  DOTNET="$TOOLS/dotnet/dotnet"
  export DOTNET_ROOT="$TOOLS/dotnet"
fi
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1
echo "    Using dotnet: $DOTNET ($("$DOTNET" --version))"

step "2/4  Downloading the card server source ($UPSTREAM_REPO @ ${UPSTREAM_COMMIT:0:7})"
rm -rf "$BUILD/src" "$BUILD/unzip"
curl -fsSL "https://github.com/$UPSTREAM_REPO/archive/$UPSTREAM_COMMIT.zip" -o "$BUILD/upstream.zip"
unzip -q "$BUILD/upstream.zip" -d "$BUILD/unzip"
mv "$BUILD/unzip/"*/ "$BUILD/src"
rm -rf "$BUILD/unzip" "$BUILD/upstream.zip"

step "     Applying the online-matchmaking patch"
( cd "$BUILD/src" && git init -q . \
  && git -c core.autocrlf=false apply --check --whitespace=nowarn "$PATCH" \
  && git -c core.autocrlf=false apply --whitespace=nowarn "$PATCH" ) \
  || fail "The patch does not apply to this source. Please report this."
echo "    Patch applied."

step "3/4  Building the server (first time takes a few minutes)"
rm -rf "$BUILD/out"
# LinuxHost=true: no Windows-only parts (WinForms pop-up). Self-contained: no .NET needed to run it.
"$DOTNET" publish "$BUILD/src/Server-Infinite" -c Release -r "$RUNTIME" \
  -p:LinuxHost=true -p:SelfContained=true -p:PublishSingleFile=false -o "$BUILD/out" \
  || fail "Build failed (see messages above)."
[ -x "$BUILD/out/Server-Infinite" ] || fail "Build finished but Server-Infinite is missing."

step "4/4  Setting up the server folder"
first=1; [ -f "$SERVER_DIR/Configurations/server.json" ] && first=0
mkdir -p "$SERVER_DIR"
( cd "$BUILD/out" && find . -type f ) | while read -r rel; do
  rel="${rel#./}"; dest="$SERVER_DIR/$rel"
  case "$rel" in
    Configurations/server.json|Configurations/kestrel.json|Configurations/log.json)
      if [ "$first" = 0 ] && [ -f "$dest" ]; then cp "$BUILD/out/$rel" "$dest.new-default"; continue; fi ;;
  esac
  mkdir -p "$(dirname "$dest")"; cp "$BUILD/out/$rel" "$dest"
done
chmod +x "$SERVER_DIR/Server-Infinite"
echo "    Server files are in: $SERVER_DIR"
[ "$first" = 0 ] && echo "    Your existing Configurations/*.json were kept (new defaults saved as *.new-default)."

if [ -n "${OFFICIAL_SERVER_FOLDER:-}" ] && [ -d "$OFFICIAL_SERVER_FOLDER/wwwroot" ]; then
  echo "    Copying WebUI pictures from $OFFICIAL_SERVER_FOLDER/wwwroot (missing files only)"
  cp -rn "$OFFICIAL_SERVER_FOLDER/wwwroot/." "$SERVER_DIR/wwwroot/"
fi

printf '\nBuild finished.\nNext: ./linux/configure.sh\n'
