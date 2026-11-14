#!/usr/bin/env bash
# Builds dist/exvs2-matchmaking-<version>.zip from release/package (our files only - no upstream code or binaries).
# Usage: release/make-release.sh v0.1.0-pre
set -euo pipefail
VERSION="${1:?usage: make-release.sh <version>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
NAME="exvs2-matchmaking-$VERSION"
OUT="$HERE/dist"; STAGE="$OUT/$NAME"
rm -rf "$STAGE" "$OUT/$NAME.zip"; mkdir -p "$STAGE"
cp -r "$HERE/package/." "$STAGE/"
# the patch must be the published one
cmp "$STAGE/files/online-matchmaking.patch" "$REPO/server-sketch/ib-server/online-matchmaking.patch"
# Windows line endings for files people open in Notepad / cmd; LF for Linux scripts
for f in "$STAGE"/*.txt "$STAGE"/*.bat "$STAGE"/scripts/*.ps1 "$STAGE"/test-tools/*.ps1; do sed -i 's/\r$//; s/$/\r/' "$f"; done
for f in "$STAGE"/linux/*; do sed -i 's/\r$//' "$f"; done
chmod +x "$STAGE"/linux/*.sh
echo "$VERSION" > "$STAGE/files/VERSION"
# never ship anything that isn't ours
if find "$STAGE" -iname '*.exe' -o -iname '*.dll' -o -iname '*.db' -o -iname '*.pfx' | grep -q .; then
  echo "binary/data file in package - refusing" >&2; exit 1; fi
(cd "$OUT" && zip -qr -X "$NAME.zip" "$NAME")
(cd "$OUT" && sha256sum "$NAME.zip" > "$NAME.zip.sha256")
echo "$OUT/$NAME.zip"; cat "$OUT/$NAME.zip.sha256"
