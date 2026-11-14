#!/usr/bin/env bash
# Compile-only + unit harness for analysis/patches/poc-banapass-cancel.diff. Needs a public asesidaa/EXVS2-POC checkout
# at 23437956 (POC=path), g++ and (optional) mingw-w64 + clang. Builds nothing for the game and runs nothing in a game.
# POC source is copied into a temp dir only (never into this repo).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd)
POC=${POC:?set POC=/path/to/EXVS2-POC checkout @23437956}
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
git -C "$POC" show 23437956f869df7dfa4f1e8347a5db1825b480c5:EXVS2-POC/banapass.cpp > "$W/orig.cpp"
git -C "$POC" show 23437956f869df7dfa4f1e8347a5db1825b480c5:EXVS2-POC/banapass.h > "$W/banapass.h"
mkdir -p "$W/tree" && git -C "$POC" archive 23437956f869df7dfa4f1e8347a5db1825b480c5 EXVS2-POC | tar -x -C "$W/tree"
( cd "$W/tree" && patch -s -p1 < "$REPO/analysis/patches/poc-banapass-cancel.diff" ) && echo "patch applies: OK"
cp "$W/tree/EXVS2-POC/banapass.cpp" "$W/v2.cpp"
# v1 = the first proposal (commit 44a2708), rebuilt from git history of this repo, with the same test-only delay
if git -C "$REPO" show 44a2708:analysis/patches/poc-banapass-cancel.diff > "$W/v1.diff" 2>/dev/null; then
  mkdir -p "$W/tree1" && git -C "$POC" archive 23437956f869df7dfa4f1e8347a5db1825b480c5 EXVS2-POC | tar -x -C "$W/tree1"
  ( cd "$W/tree1" && patch -s -p1 < "$W/v1.diff" )
  sed 's/std::thread(\[cb, ctx, status\]() {/&\n            std::this_thread::sleep_for(std::chrono::milliseconds(EXVS2_LOBBIES_TEST_CANCEL_DELAY_MS));/' \
    "$W/tree1/EXVS2-POC/banapass.cpp" > "$W/v1.cpp"
fi
# 1) Windows compile check (syntax only) of the patched files with the real Windows headers (mingw), if available
if command -v clang++ >/dev/null && [ -d /usr/x86_64-w64-mingw32/include ]; then
  mkdir -p "$W/winhdr"; printf '#include <windows.h>\n' > "$W/winhdr/Windows.h"; printf '#include <windows.h>\n#include <mmsystem.h>\n' > "$W/winhdr/joystickapi.h"
  INC="-I $W/tree/EXVS2-POC -I $W/tree/EXVS2-POC/libs/inireader -I $W/winhdr"
  for f in Config.cpp banapass.cpp; do
    # the POC's own MSVC-only 'std::filesystem::path::path(' (unchanged lines) is normalised for clang
    sed 's/std::filesystem::path::path(/std::filesystem::path(/' "$W/tree/EXVS2-POC/$f" > "$W/tree/EXVS2-POC/chk_$f"
    clang++ --target=x86_64-w64-mingw32 -std=c++20 -fms-extensions -Wall -Wextra -Wno-unused-parameter -Wno-sign-compare \
      -fsyntax-only $INC "$W/tree/EXVS2-POC/chk_$f" 2> "$W/$f.warn" && echo "mingw syntax check $f: OK ($(grep -c warning "$W/$f.warn" || true) warnings)" \
      || { cat "$W/$f.warn"; echo "mingw syntax check $f: FAILED"; exit 1; }
  done
fi
# 2) native unit harness: original vs v1 (if V1 given) vs v2
for var in orig v1 v2; do
  [ -f "$W/$var.cpp" ] || continue
  sed 's/std::filesystem::path::path(/std::filesystem::path(/' "$W/$var.cpp" > "$W/bp_$var.cpp"
  ${CXX:-$(command -v g++ || command -v clang++)} -std=c++20 -O1 -pthread -w -DVARIANT="\"$var\"" -DEXVS2_LOBBIES_TEST_CANCEL_DELAY_MS=100 \
      -I "$HERE/mock" -I "$W" -I "$POC/EXVS2-POC/libs/inireader" -I "$POC/EXVS2-POC" \
      "$W/bp_$var.cpp" "$HERE/test_main.cpp" -o "$W/t_$var"
  "$W/t_$var" || RC=1
  echo
done
exit ${RC:-0}
