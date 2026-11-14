// Unit harness for the POC card-reader emulation (banapass.cpp): original vs exvs2-lobbies proposal v1 / v2.
// Native Linux build with mocks only (mock/*.h). Nothing here loads a DLL, touches a game, or reads a real card file.
// The "game" side mimics vsac29's reader wrapper (results-hang-fixes.md 4.2): before each BngRwReqWaitTouch it resets
// status = -901 / done = 0 in ONE shared result struct; the callback copies 0xa8 bytes, stores status, sets done.
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include "Configs.h"
#include "Input.h"
#include "banapass.h"

StartupConfig globalConfig;
std::atomic<bool> g_mockCardKey{false};
InputState InputState::Get() { InputState s; s.Card = g_mockCardKey.load(); return s; }

#ifndef VARIANT
#define VARIANT "unknown"
#endif

struct GameResult { std::atomic<int> status{-901}; std::atomic<bool> done{false}; std::atomic<int> calls{0}; unsigned char card[0xa8]; };
static GameResult g;
static void GameCallback(int, int status, void* data, void* ctx)
{
    auto* r = static_cast<GameResult*>(ctx);
    std::memcpy(r->card, data, 0xa8);             // vsac29 copies unconditionally
    r->status = status; r->done = true; r->calls++;
}
static double Arm()   // returns ms spent inside BngRwReqWaitTouch (game-thread stall)
{
    g.status = -901; g.done = false;
    auto t0 = std::chrono::steady_clock::now();
    BngRwReqWaitTouch(0, 0, 0, GameCallback, &g);
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
}
static void Sleep(int ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
static void Settle() { g_mockCardKey = false; BngRwReqCancel(0); Sleep(400); g.calls = 0; g.done = false; }

static int fails = 0;
static void Report(const char* id, const char* what, bool observed, bool expectedForVariant)
{
    bool ok = observed == expectedForVariant;
    if (!ok) fails++;
    std::printf("%-4s %-62s observed=%-5s expected=%-5s %s\n", id, what, observed ? "yes" : "no",
                expectedForVariant ? "yes" : "no", ok ? "OK" : "MISMATCH");
}

int main()
{
    const std::string v = VARIANT;
    const bool orig = v == "orig", v1 = v == "v1", v2 = v == "v2";
    std::printf("variant=%s\n", VARIANT);

    // T1 cancel completes the pending wait
    double stall = Arm(); Sleep(50); BngRwReqCancel(0); Sleep(500);
    Report("T1", "cancel -> game callback (done) within 500 ms", g.done.load(), !orig);
    if (g.done) Report("T1b", "cancel status == 3 (finished, no card)", g.status == 3, true);
    Report("T6", "BngRwReqWaitTouch blocks the game thread >= 200 ms", stall >= 200, orig);
    Settle();

    // T2 one touch -> exactly one callback (key held 450 ms)
    Arm(); g_mockCardKey = true; Sleep(450); g_mockCardKey = false; Sleep(300);
    Report("T2", "card key held 450 ms -> more than one callback", g.calls > 1, orig);
    Report("T2b", "card key -> at least one callback with status 0", g.calls >= 1 && g.status == 0, true);
    Settle();

    // T3 re-arm while pending: only the newest wait fires, once
    Arm(); Arm(); g_mockCardKey = true; Sleep(350); g_mockCardKey = false; Sleep(300);
    Report("T3", "double ReqWaitTouch + key -> exactly one callback", g.calls == 1, !orig);
    Settle();

    // T4 cancel, then the game re-arms at once: the old cancel must not finish the NEW wait
    Arm(); BngRwReqCancel(0); Arm(); Sleep(400);
    bool stale = g.done.load();
    // orig: no cancel callback at all -> not done; v1: stale completion (with the test delay) -> done; v2: dropped
    Report("T4", "cancel+immediate re-arm -> new wait finished by the stale cancel", stale, v1);
    Settle();

    // T5 no-card timeout (v2 option CardWaitTimeoutMs; ignored by orig/v1)
    globalConfig.CardWaitTimeoutMs = 300;
    Arm(); Sleep(700);
    Report("T5", "CardWaitTimeoutMs=300, no key -> wait finished by 700 ms", g.done.load() && g.status == 3, v2);
    globalConfig.CardWaitTimeoutMs = 0; Settle();
    Arm(); Sleep(700);
    Report("T5b", "CardWaitTimeoutMs=0, no key -> still pending at 700 ms", !g.done.load(), true);
    Settle();

    // T7 cancel with nothing pending -> no callback
    g.calls = 0; BngRwReqCancel(0); Sleep(200);
    Report("T7", "cancel with no pending wait -> no callback", g.calls == 0, true);

    // T8 CardCancelCallback=false keeps the original behaviour
    globalConfig.CardCancelCallback = false;
    Arm(); Sleep(50); BngRwReqCancel(0); Sleep(400);
    Report("T8", "CardCancelCallback=false -> cancel leaves the wait pending", !g.done.load(), true);
    globalConfig.CardCancelCallback = true; Settle();

    std::printf("%s: %s\n", VARIANT, fails ? "MISMATCHES" : "all observations as expected");
    return fails ? 1 : 0;
}
