#pragma once
#include <atomic>
struct InputState { bool Card = false; static InputState Get(); };
extern std::atomic<bool> g_mockCardKey;   // the harness "holds the card key"
