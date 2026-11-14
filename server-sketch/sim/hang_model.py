#!/usr/bin/env python3
"""Frame-stepped model of the versus results screen (results-hang simulation, analysis/results-hang-sim.md section 3).

What is modelled (60 frames/s, two cabinets in lockstep, both run the same frames):
  * the results gate of CAcSeqBattleFlow_Player: leaves only when F, S, A and C are all done [C];
  * F Finish ~589 frames [C]; C ResultCapture <= 3 x 300 frames [C]; S SaveResult: time per card-server call from
    postmatch_replay.py (10 s x <= 5 tries) [C], + 60 s hold with debug #44 [C];
  * A ResultAction -> ResultConfirm (WaitCounter 300 frames [C], then WaitHud waits for its children with no timer [C])
    -> OptionWindow (until the results HUD closes) [C];
  * ResultConfirm children: ReturnMatch (needs every member carded: +0x60/+0x61) and FormInstantTeam (needs every
    same-team member in the peer-session map) [C]; their HUD countdown (ReturnMatch 7 s [I]; instant team unknown,
    default 10 s [I]); a card touch decides "apply", the countdown decides "no" [C];
  * the bngrw card reader as vsac29 drives it [C]: wait = reset result, BngRwReqWaitTouch; stays "pending" until the
    callback sets the done byte; cancel calls BngRwReqCancel and does NOT change the state;
  * the DLL side: POC original (cancel never calls back, 250 ms sleep per wait, key held -> callback every 100 ms),
    the v2 patch (cancel calls back with status 3, one callback per wait), v2 + CardWaitTimeoutMs, AutomaticCardButton.
Hypotheses that the exe analysis could not settle are switches, so every row says what it assumes:
  H1 cpu_member  the cabinet appends its CPU partner as a party member with +0x60 = 0 (results-hang-fixes 4.1) [C-ish];
                 False = the 8.1 reading (instant-team check only sees the local human, so the prompt can appear).
  H2 exit_waits  a prompt that ends on its countdown cancels the card wait and only exits once the reader is no
                 longer "pending" [I]. False = it exits at once.
Evidence each outcome is compared with (real-game-test-2026-11-13, results-hang-logs.md):
  E1 hang of minutes that ends by itself; E2 both cabinets leave 8 ms apart; E3 steady 60 Hz (only two 0.5 s stalls);
  E4 no peer reliable messages / no RPC 200 during the hang; E5 holding Start does nothing (OPTION not open);
  E6 a route battle vs CPU does not hang; E7 same hang in LM-local mode; E8 every HTTP request answered (200).
  H3 reader_giveup  hypothetical game-side limit on the post-cancel reader wait (not found in the exe) [I].
Usage: hang_model.py [--json out.json] [--md table.md]
"""
import argparse, json

FPS = 60
HORIZON_S = 900


class Reader:
    """vsac29 reader wrapper (state 2 = touch pending, 9 = result ready) + one emulation DLL variant."""
    def __init__(self, dll, keys, timeout_s=0.0):
        self.dll, self.keys, self.timeout_s = dll, keys, timeout_s
        self.pending = False; self.done = False; self.status = None; self.armed_at = 0.0
        self.cancel_cb_at = None; self.stall_frames = 0; self.callbacks = 0; self.gen = 0

    def key(self, t):
        return any(a <= t < b for a, b in self.keys)

    def wait_touch(self, t, owner=None):
        self.pending, self.done, self.status, self.armed_at = True, False, -901, t
        self.cancel_cb_at = None; self.gen += 1; self.owner = owner
        if self.dll == 'poc':
            self.stall_frames += 15          # 250 ms sleep on the game thread
            self.stalls = getattr(self, 'stalls', 0) + 1

    def cancel(self, t):
        if self.dll in ('v2', 'v2_timeout') and self.pending:
            self.cancel_cb_at = t + 1.0 / FPS  # worker thread calls back with status 3

    def tick(self, t):
        if not self.pending:
            return
        if self.cancel_cb_at is not None and t >= self.cancel_cb_at:
            self._callback(3); return
        if self.dll == 'auto' or self.key(t):
            if t - self.armed_at >= 0.1:
                self._callback(0); return
        if self.dll == 'v2_timeout' and self.timeout_s and t - self.armed_at >= self.timeout_s:
            self._callback(3)

    def _callback(self, status):
        self.done, self.status, self.pending = True, status, False
        self.callbacks += 1


class Prompt:
    """ReturnMatch / FormInstantTeam card prompt: countdown or card touch; with H2 it waits for the reader on exit."""
    def __init__(self, name, start, hud_s, reader, sc, needs_peer_msgs):
        self.name, self.reader, self.sc = name, reader, sc
        self.deadline = start + hud_s
        self.state = 'wait_touch'; self.exit_at = None; self.decision = None
        self.peer_msgs = needs_peer_msgs
        reader.wait_touch(start, self)

    def tick(self, t):
        r = self.reader
        if self.state == 'wait_touch':
            r.tick(t)
            if r.done and r.status == 0:
                self.decision = 'apply (card touch)'; self.state = 'exit'; self.exit_at = t
            elif not self.sc['timers_stopped'] and t >= self.deadline:
                self.decision = 'no (countdown)'; r.cancel(t)
                self.state = 'wait_reader' if self.sc['exit_waits'] else 'exit'
                if self.state == 'exit': self.exit_at = t
        elif self.state == 'wait_reader':
            r.tick(t)
            giveup = self.sc['reader_giveup_s']
            if not r.pending or (giveup and t >= self.deadline + giveup):
                self.state = 'exit'; self.exit_at = t
        return self.state == 'exit'


def prompts_for(sc, side):
    """Which ResultConfirm children a cabinet creates, from the layout and H1 [C for the checks, I for H1]."""
    lay = sc['layout']
    members_carded = lay == 'humans_same_team' and sc['all_four_carded']
    rm = members_carded and side == 'loser' and sc['online']
    if lay == 'human_cpu_each_side':
        it = (not sc['cpu_member']) and sc['instant_team_mode']
    elif lay == 'humans_same_team':
        it = sc['instant_team_mode'] and side == 'winner'
    else:
        it = False
    return rm, it


def run(sc):
    sc = dict(DEFAULTS, **sc)
    cabs = []
    shared = None
    for i in range(2):
        keys = sc['keys'] if (i == 0 or sc['shared_key']) else []
        if sc['shared_reader']:
            shared = shared or Reader(sc['dll'], keys, sc['card_timeout_s'])
            rd = shared
        else:
            rd = Reader(sc['dll'], keys, sc['card_timeout_s'])
        side = sc['sides'][i]
        cabs.append({'reader': rd, 'side': side, 'children': None, 'rc_done_at': None, 'opt_done_at': None,
                     'exit_at': None, 'prompts': [], 'option_open': None})
    s_done = sc['s_time_s'] + (60.0 if sc['debug44'] else 0.0)
    c_done = sc['c_time_s']
    f_done = 589 / FPS
    wall = 0.0
    for frame in range(HORIZON_S * FPS):
        t = frame / FPS
        stall = 0
        for c in cabs:
            if c['exit_at'] is not None:
                continue
            if c['children'] is None and t >= 2 / FPS:         # ResultConfirm created on the 2nd frame
                rm, it = prompts_for(sc, c['side'])
                ch = []
                if rm: ch.append(Prompt('ReturnMatch', t, 7.0, c['reader'], sc, True))
                if it: ch.append(Prompt('FormInstantTeam', t + sc['it_connect_s'], sc['it_hud_s'], c['reader'], sc, True))
                c['children'] = ch; c['prompts'] = [p.name for p in ch]
            if c['children'] is not None and c['rc_done_at'] is None:
                alive = [p for p in c['children'] if not p.tick(t)]
                c['children'] = alive
                if t >= 300 / FPS and not alive:
                    c['rc_done_at'] = t; c['option_open'] = (t, None)
            if c['rc_done_at'] is not None and c['opt_done_at'] is None:
                if not sc['timers_stopped'] and t >= c['rc_done_at'] + sc['option_s']:
                    c['opt_done_at'] = t; c['option_open'] = (c['option_open'][0], t)
            a_done = c['opt_done_at'] is not None
            if a_done and t >= max(s_done, c_done, f_done):
                c['exit_at'] = t
            stall = max(stall, c['reader'].stall_frames); c['reader'].stall_frames = 0
        wall += 1.0 / FPS + stall / FPS
        if all(c['exit_at'] is not None for c in cabs):
            break
    exits = [c['exit_at'] for c in cabs]
    worst = None if None in exits else max(exits)
    kind = 'indefinite' if worst is None else ('finite >30 s' if worst > 30 else 'no hang')
    return {
        'exit_s': [None if e is None else round(e, 2) for e in exits], 'kind': kind,
        'synchronized': 'n/a' if None in exits else abs(exits[0] - exits[1]) < 0.02,
        'prompts': [c['prompts'] for c in cabs],
        'option_open_during_hang': any(c['option_open'] is not None and c['option_open'][0] < 30 and
                                       (c['option_open'][1] is None or c['option_open'][1] > 30) for c in cabs),
        'peer_msgs': any(p in ('ReturnMatch', 'FormInstantTeam') for c in cabs for p in c['prompts']),
        'poc_stalls_per_cab': [getattr(c['reader'], 'stalls', 0) for c in cabs],
    }


DEFAULTS = dict(layout='human_cpu_each_side', sides=('winner', 'loser'), online=True, all_four_carded=False,
                instant_team_mode=True, cpu_member=True, exit_waits=True, reader_giveup_s=0.0, dll='poc', card_timeout_s=0.0,
                keys=[], shared_key=False, shared_reader=False, timers_stopped=False, debug44=False,
                s_time_s=0.2, c_time_s=0.5, it_connect_s=0.0, it_hud_s=10.0, option_s=5.0)


def evidence(r, sc):
    """Which of E1-E8 the outcome contradicts (only the ones the model can speak to)."""
    bad = []
    sc = dict(DEFAULTS, **sc)
    if r['kind'] == 'no hang': bad.append('E1 (no hang)')
    if r['kind'] == 'indefinite': bad.append('E1 (never ends by itself)')
    if r['synchronized'] is False: bad.append('E2 (cabinets leave apart)')
    if any('ReturnMatch' in p for p in r['prompts']) or \
       (sc['layout'] == 'humans_same_team' and any('FormInstantTeam' in p for p in r['prompts'])):
        bad.append('E4 (prompt talks to a human peer)')
    if r['option_open_during_hang']: bad.append('E5 (OPTION open)')
    if max(r['poc_stalls_per_cab']) > 1: bad.append('E3 (repeated 250 ms stalls)')
    if sc['debug44']: bad.append('E6 (#44 also delays route battles)')
    if sc['s_time_s'] > 40: bad.append('E8 (needs unanswered HTTP)')
    elif sc['s_time_s'] > 20: bad.append('E1 (well under minutes) / E8 (slow HTTP answers)')
    if sc['timers_stopped']: bad.append('E6 (#55 also freezes route battles) [I]')
    return bad


SCENARIOS = [
    # id, title, scenario, what it represents
    ('U1', "User's layout (human+CPU each side), H1 true", {}),
    ('U2', "User's layout, H1 false (instant-team prompt shown)", dict(cpu_member=False)),
    ('U3', 'U2 + card key held 1 s at 20 s on cabinet 1', dict(cpu_member=False, keys=[(20, 21)])),
    ('U4', 'U2 + card key on both (one keyboard drives both windows)', dict(cpu_member=False, keys=[(20, 21)], shared_key=True)),
    ('U5', 'U2 but prompt exits without waiting for the reader (H2 false)', dict(cpu_member=False, exit_waits=False)),
    ('U6', 'U2 + a game-side reader give-up after 180 s (hypothesis H3)', dict(cpu_member=False, reader_giveup_s=180.0)),
    ('U7', 'U6 with the v2 DLL patch', dict(cpu_member=False, reader_giveup_s=180.0, dll='v2')),
    ('T1', 'HumansTeamVsCpu: humans same team, won (prompt for winners)', dict(layout='humans_same_team', sides=('winner', 'winner'))),
    ('T2', 'HumansTeamVsCpu: humans same team, lost', dict(layout='humans_same_team', sides=('loser', 'loser'))),
    ('T3', 'T1 with the v2 DLL patch', dict(layout='humans_same_team', sides=('winner', 'winner'), dll='v2')),
    ('R1', 'Cancel never calls back (forced prompt), POC original', dict(cpu_member=False)),
    ('R2', 'R1 with v2 patch (cancel calls back)', dict(cpu_member=False, dll='v2')),
    ('R3', 'R1 with v2 + CardWaitTimeoutMs 3000 only (no cancel callback)', dict(cpu_member=False, dll='v2_timeout', card_timeout_s=3.0)),
    ('R4', 'R1 with AutomaticCardButton (touch every 100 ms)', dict(cpu_member=False, dll='auto')),
    ('X1', 'Two instances share ONE reader object, POC', dict(cpu_member=False, shared_reader=True)),
    ('X2', 'Two instances share ONE reader object, v2 patch', dict(cpu_member=False, shared_reader=True, dll='v2')),
    ('D1', 'Debug #55 timers stopped, no prompt (H1 true)', dict(timers_stopped=True)),
    ('D2', 'Debug #55 timers stopped + prompt, v2 patch', dict(timers_stopped=True, cpu_member=False, dll='v2')),
    ('D3', 'Debug #44 fake 60 s save hold', dict(debug44=True)),
    ('S1', 'Server never answers (S = 150 s from replay)', dict(s_time_s=150.0)),
    ('S2', 'Server never answers, pessimistic seq (S = 300 s)', dict(s_time_s=300.0)),
    ('S3', 'SQLite locked 35 s, watchdog off, LM-local (S = 35.4 s from replay)', dict(s_time_s=35.4)),
    ('S4', 'SQLite locked 35 s, watchdog 8 s, LM-local (S = 16.1 s from replay)', dict(s_time_s=16.1)),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json'); ap.add_argument('--md')
    ap.add_argument('--s-flagsoff-dblock', type=float, help='S time measured by postmatch_replay for the DB-lock row')
    a = ap.parse_args()
    rows = []
    for sid, title, sc in SCENARIOS:
        r = run(sc); bad = evidence(r, sc)
        rows.append(dict(id=sid, title=title, scenario=sc, **r, contradicts=bad))
        ex = '/'.join('-' if e is None else '%.1f' % e for e in r['exit_s'])
        print('%-3s %-62s exit=%-11s %-13s sync=%-5s stalls=%s prompts=%-34s contradicts=%s' % (
            sid, title, ex, r['kind'], r['synchronized'], r['poc_stalls_per_cab'],
            '|'.join(','.join(p) or '-' for p in r['prompts']), ', '.join(bad) or 'none'))
    if a.json:
        json.dump(rows, open(a.json, 'w'), indent=1)
    if a.md:
        with open(a.md, 'w') as f:
            f.write('| id | scenario | exit s (cab1/cab2) | result | prompts (cab1; cab2) | 250 ms stalls | contradicts evidence |\n|---|---|---|---|---|---|---|\n')
            for r in rows:
                ex = ' / '.join('never' if e is None else '%.1f' % e for e in r['exit_s'])
                pr = '; '.join(','.join(p) or '-' for p in r['prompts'])
                f.write('| %s | %s | %s | %s | %s | %s | %s |\n' % (r['id'], r['title'], ex, r['kind'], pr,
                        '/'.join(map(str, r['poc_stalls_per_cab'])), ', '.join(r['contradicts']) or '**none**'))


if __name__ == '__main__':
    main()
