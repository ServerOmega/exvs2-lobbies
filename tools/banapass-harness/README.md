# banapass-harness

Compile check + unit harness for `analysis/patches/poc-banapass-cancel.diff` (results-hang fix #2, proposal v2).
Results and the test list: `analysis/results-hang-sim.md` §4.

```bash
git clone https://github.com/asesidaa/EXVS2-POC.git /tmp/poc   # public source; the script uses commit 23437956
POC=/tmp/poc tools/banapass-harness/build_and_test.sh
```

* Applies the diff to a temp copy of the POC (nothing from the POC is copied into this repo).
* If clang + mingw-w64 headers are installed: syntax check of the patched `Config.cpp` / `banapass.cpp` for Windows.
* Builds `banapass.cpp` (original, v1 from commit 44a2708, v2) natively with `mock/` (Win32 stand-ins that never load a
  DLL or write a card file, a fake card key, a mock of vsac29's reader wrapper) and runs `test_main.cpp`.
* Nothing here builds a DLL for the game or runs anything in a game.
