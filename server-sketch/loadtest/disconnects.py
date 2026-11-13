#!/usr/bin/env python3
"""Disconnect / rejoin scenarios for the EXVS2 IB matchmakers.  EXPERIMENTAL, fake cabinets only.

Run through loadtest.py:
  loadtest.py --scenario disconnects --url http://127.0.0.1:28080/match [--card-url http://127.0.0.1:28080/] \
              [--restart-cmd 'script that restarts the server keeping its node-id file'] [--people 150]
Two parts:
  1. probes      - small scripted cases (4-7 cabinets each, own attr1 bucket so they never mix) with an expected
                   outcome per case: rejoin after short / long gaps with same / new node ids, drop right after the
                   match, requeue mid-battle, pair partner / leader drop, partner rejoining solo, out-of-order cancel,
                   retried requests, re-registration, server restart.
  2. population  - ~100-200 people queueing for 300 s with disconnect-heavy behaviour (see DPROFILE), a mass
                   disconnect (30 % of everyone at once, then a rejoin burst) and optionally a server restart.
What a real cabinet does after a drop is NOT known (analysis/disconnect-test.md §1): the harness assumes it runs
IssueNodeId + EntryMatching again with a new apply_id (the game's apply_id is a counter, matchmaking.md §2.2).
"""
import http.client, json, os, random, subprocess, threading, time, urllib.parse, uuid
from collections import Counter, defaultdict
import loadtest as L

SUCCESS, MATCH_CANCELED, NOENTRY = 0, 1, 103
STALE = 20          # server default StaleAfterSeconds
_ser = [0]
_lock = threading.Lock()


def mono(): return time.monotonic()


class Cab:
    """One fake cabinet with a background poller (start_polling / stop = simulated drop)."""
    def __init__(self, sim, tag, group, loc=None):
        with _lock:
            _ser[0] += 1; n = _ser[0]
        self.sim, self.group = sim, group
        self.serial = 'DCPCB%06d' % n
        self.loc = loc or 'DCLOC%04d' % n
        self.am = 8000000 + n
        self.conn = L.Conn(sim.url, sim.stats)
        self.apply = random.randint(1, 1000)
        self.node = self.npc = None
        self.results = []           # (t, node, code, room_id, clients)
        self._poll = None; self._stop = threading.Event()

    def issue(self):
        r = self.conn.call({'type': L.ISSUE, 'request_id': L.rid(), 'issue_node_id': {
            'pcb_serial': self.serial, 'loc_id': self.loc, 'issue_at': int(time.time()), 'issue_count': 2}}, 'issue')
        ids = (r or {}).get('issue_node_id', {}).get('node_id', [])
        self.node, self.npc = ids[0], ids[1]
        self.sim.issued.extend(ids)
        return ids

    def register(self):
        if self.sim.card_url:
            self.sim.register_pcb(self)

    def entry(self, world=23, node=None, new_apply=True, sortie='S', partner=None, attr2=0):
        node = node or self.node
        if new_apply: self.apply += 1
        groups = []
        if sortie == 'TN':
            groups = [{'client': L.client(self.npc, L.NPC, self.loc, '0.0.0.0', 0, human=False), 'player': {'banapassport_am_id': 0}}]
        elif sortie == 'T':
            groups = [{'client': L.client(partner.node, partner.serial, partner.loc, '198.18.200.2', 41000),
                       'player': {'banapassport_am_id': partner.am}}]
        e = {'apply_id': self.apply, 'myclient': L.client(node, self.serial, self.loc, '198.18.200.1', 40000),
             'myplayer': {'banapassport_am_id': self.am,
                          'parameters': [{'attribute_id': 1, 'parameter': self.group}, {'attribute_id': 2, 'parameter': attr2},
                                         {'attribute_id': 3, 'parameter': 0}]},
             'world': {'mucha_game_id': 'GIB1', 'version': 1, 'world_id': world}, 'groups': groups,
             'matching_timeout': 150, 'seq_num': 1, 'create_room_flag': 1, 'entry_at': int(time.time())}
        self.last_entry = e
        r = self.conn.call({'type': L.ENTRY, 'request_id': L.rid(), 'entry_matching': e}, 'entry')
        return (r or {}).get('code')

    def resend_entry(self):
        r = self.conn.call({'type': L.ENTRY, 'request_id': L.rid(), 'entry_matching': self.last_entry}, 'entry_retry')
        return (r or {}).get('code')

    def check(self, node=None):
        node = node or self.node
        r = self.conn.call({'type': L.CHECK, 'request_id': L.rid(), 'check_matching': {'node_id': node, 'check_at': int(time.time())}}, 'check')
        if r is None: return None, None, []
        cm = r.get('check_matching') or {}
        return r.get('code'), cm.get('room_id'), L.slim(cm.get('clients', []))

    def cancel(self, apply=None, node=None):
        self.conn.call({'type': L.CANCEL, 'request_id': L.rid(), 'cancel_matching': {
            'node_id': node or self.node, 'apply_id': self.apply if apply is None else apply, 'cancel_at': int(time.time())}}, 'cancel')

    def start_polling(self, node=None, interval=3.0):
        """Poll until matched / ended / stopped; the result is appended to self.results."""
        self.stop()
        self._stop = threading.Event(); stop = self._stop; node = node or self.node
        def run():
            while not stop.wait(interval):
                code, room, cl = self.check(node)
                if code is None: continue
                if code != SUCCESS or cl:
                    self.results.append((mono(), node, code, room, cl)); return
        self._poll = threading.Thread(target=run, daemon=True); self._poll.start()

    def stop(self):
        self._stop.set()

    def outcome(self, node=None):
        for t, n, code, room, cl in self.results:
            if node is None or n == node: return {'code': code, 'room': room, 'nodes': sorted(c[1] for c in cl), 't': t}
        return None


def wait_for(pred, timeout):
    t0 = mono()
    while mono() - t0 < timeout:
        if pred(): return True
        time.sleep(0.25)
    return pred()


class Probes:
    def __init__(self, sim):
        self.sim, self.out = sim, []
        self.gid = 1000

    def g(self):
        self.gid += 1; return self.gid

    def cabs(self, n, group, world=23, poll=True):
        cs = [Cab(self.sim, 'x', group) for _ in range(n)]
        for c in cs:
            c.issue(); c.entry(world)
            if poll: c.start_polling()
        return cs

    def rec(self, name, ok, expect, got, **kw):
        self.out.append(dict(probe=name, ok=bool(ok), expect=expect, got=got, **kw))
        print('[%s] %s  expect: %s | got: %s' % ('PASS' if ok else 'FAIL', name, expect, got), flush=True)

    # ---- 1. drop while waiting, rejoin -----------------------------------------------------------------------
    def p_rejoin_short_same_node_new_mode(self):
        g = self.g(); a = Cab(self.sim, 'a', g); a.issue(); a.entry(23); a.start_polling(); time.sleep(4); a.stop()
        time.sleep(6)                                             # 10 s gap < StaleAfter
        a.entry(18, node=a.node); t_re = mono(); a.start_polling()   # same node, new apply_id, other mode
        o23 = self.cabs(3, g, 23); o18 = self.cabs(3, g, 18)
        wait_for(lambda: a.outcome(), 15)
        oa = a.outcome(); r23 = [c.outcome() for c in o23]
        in23 = any(r and a.node in r['nodes'] for r in r23)
        ok = oa and oa['code'] == 0 and set(oa['nodes']) == {a.node} | {c.node for c in o18}
        self.rec('rejoin <stale, same node, new mode', ok, 'matched with the 3 world-18 cabinets',
                 'room %s' % (oa and oa['nodes']) + (' / also put in the world-23 room' if in23 else ''),
                 rematch_s=round(oa['t'] - t_re, 1) if oa else None)
        for c in o23 + o18: c.stop()

    def p_rejoin_short_new_node(self):
        g = self.g(); a = Cab(self.sim, 'a', g); a.issue(); old = a.node; a.entry(23); a.start_polling(); time.sleep(4); a.stop()
        time.sleep(6)
        a.issue(); a.entry(23); t_re = mono(); a.start_polling()
        o = self.cabs(3, g, 23)
        wait_for(lambda: a.outcome(), 15)
        oa = a.outcome(); code_old = a.check(old)[0]
        ok = oa and oa['code'] == 0 and a.node in oa['nodes'] and old not in oa['nodes'] and code_old == MATCH_CANCELED
        self.rec('rejoin <stale, new node', ok, 'new node matched once, old node -> MATCH_CANCELED',
                 'room %s, old node code %s' % (oa and oa['nodes'], code_old), rematch_s=round(oa['t'] - t_re, 1) if oa else None)
        for c in o: c.stop()

    def p_rejoin_long(self, same_node):
        g = self.g(); a = Cab(self.sim, 'a', g); a.issue(); old = a.node; a.entry(23); a.start_polling(); time.sleep(3); a.stop()
        time.sleep(STALE + 4)                                     # gone longer than StaleAfter
        o = self.cabs(3, g, 23)
        time.sleep(4)
        early = [c.outcome() for c in o if c.outcome()]
        code_old = a.check(old)[0]                                # what the returning cabinet sees for its old node
        if not same_node:
            a.register(); a.issue()
        a.entry(23, node=a.node); t_re = mono(); a.start_polling()
        wait_for(lambda: a.outcome(), 12)
        oa = a.outcome()
        ok = not early and oa and oa['code'] == 0 and a.node in oa['nodes'] and code_old in (MATCH_CANCELED, NOENTRY)
        self.rec('rejoin >stale, %s node%s' % ('same' if same_node else 'new', '' if same_node else ' (+RegisterPcb)'), ok,
                 'no ghost match while gone; old node told canceled; rematched on return',
                 'ghost room %s; old node code %s; room %s' % (bool(early), code_old, oa and oa['nodes']),
                 rematch_s=round(oa['t'] - t_re, 1) if oa else None)
        for c in o: c.stop()

    # ---- 2. drop right after the match was found --------------------------------------------------------------
    def p_drop_after_match(self):
        g = self.g(); cs = self.cabs(3, g, 23)
        d = Cab(self.sim, 'd', g); d.issue(); d.entry(23)         # enters, never polls again (drops as the room forms)
        wait_for(lambda: all(c.outcome() for c in cs), 10)
        r = [c.outcome() for c in cs]
        room = r[0] and r[0]['room']
        ghost = bool(r[0]) and d.node in r[0]['nodes']
        # the 3 others notice the missing peer (P2P fails - assumption) and requeue at once with new ids, + 1 newcomer
        t_re = mono()
        for c in cs: c.issue(); c.entry(23); c.start_polling()
        n = Cab(self.sim, 'n', g); n.issue(); n.entry(23); n.start_polling()
        wait_for(lambda: all(c.outcome(c.node) for c in cs + [n]), 12)
        r2 = [c.outcome(c.node) for c in cs + [n]]
        clean = all(x and x['code'] == 0 for x in r2) and len({x['room'] for x in r2}) == 1 and d.node not in r2[0]['nodes']
        # the dropped cabinet comes back 5 s later with the same node: new apply_id (game counter) vs a retried entry
        time.sleep(5)
        d.entry(23, node=d.node, new_apply=False); same_apply = d.check()[1]
        d.entry(23, node=d.node, new_apply=True); new_apply = d.check()
        self.rec('drop right after match', ghost and clean, 'room formed with the dropped cabinet (server cannot know); '
                 'others requeue and rematch cleanly; room is not refilled',
                 'room %s had the dropped cabinet: %s; requeued 3+1 rematched in one room: %s' % (room, ghost, clean),
                 rematch_s=round(max(x['t'] for x in r2) - t_re, 1) if clean else None,
                 dropped_returns_same_apply_gets_room=same_apply, dropped_returns_new_apply=('waiting' if new_apply[0] == 0 and not new_apply[2] else new_apply[:2]))

    # ---- 3. mid-battle disconnect then requeue ----------------------------------------------------------------
    def p_mid_battle_requeue(self):
        g = self.g(); cs = self.cabs(4, g, 23)
        wait_for(lambda: all(c.outcome() for c in cs), 10)
        room = cs[0].outcome()['room']
        time.sleep(3)
        a, b = cs[0], cs[1]
        a.entry(23, node=a.node); a.start_polling()                       # same node, new apply_id, at once
        b.issue(); b.entry(23); b.start_polling()                         # new node ids
        t_re = mono(); news = self.cabs(2, g, 23)
        wait_for(lambda: a.outcome(a.node) and len(a.results) > 1 and b.outcome(b.node), 12)
        ra = a.results[-1] if len(a.results) > 1 else None
        rb = b.outcome(b.node)
        ok = ra and ra[2] == 0 and ra[3] != room and rb and rb['code'] == 0 and rb['room'] != room
        self.rec('mid-battle drop, immediate requeue (same node+new apply / new node)', ok, 'both get a NEW room',
                 'same-node: room %s, new-node: room %s (old %s)' % (ra and ra[3], rb and rb['room'], room),
                 rematch_s=round(max(ra[0], rb['t']) - t_re, 1) if ok else None)
        for c in news: c.stop()

    # ---- 4. pairs --------------------------------------------------------------------------------------------
    def pair(self, g):
        loc = 'DCLOCP%04d' % g
        L_, P = Cab(self.sim, 'L', g, loc), Cab(self.sim, 'P', g, loc)
        P.issue(); L_.issue(); L_.entry(23, sortie='T', partner=P)
        L_.start_polling(); P.start_polling(P.node)
        return L_, P

    def p_pair_member_drop(self, who):
        g = self.g(); L_, P = self.pair(g)
        time.sleep(4); (P if who == 'partner' else L_).stop()
        stay = L_ if who == 'partner' else P
        time.sleep(STALE + 4)
        o = self.cabs(2, g, 23)
        wait_for(lambda: stay.outcome() or all(c.outcome() for c in o), 8)
        so = stay.outcome()
        ghost = bool(so and so['code'] == 0)
        ok = so and so['code'] == MATCH_CANCELED
        self.rec('pair: %s stops polling' % who, ok, 'pair dropped after StaleAfter; the other cabinet gets MATCH_CANCELED',
                 'other cabinet got %s' % ('a room with the ghost %s' % who if ghost else (so and so['code'])))
        for c in o + [L_, P]: c.stop()

    def p_partner_rejoins_solo(self, same_node):
        g = self.g(); L_, P = self.pair(g)
        time.sleep(4); P.stop()
        if not same_node: P.issue()
        P.entry(23, node=P.node); P.start_polling(P.node)
        wait_for(lambda: L_.outcome(), 6)
        lo = L_.outcome()
        o = self.cabs(3, g, 23)
        wait_for(lambda: P.outcome(P.node), 10)
        po = P.outcome(P.node)
        ok = lo and lo['code'] == MATCH_CANCELED and po and po['code'] == 0 and L_.node not in po['nodes']
        self.rec('pair: partner rejoins solo (%s node)' % ('same' if same_node else 'new'), ok,
                 'leader told MATCH_CANCELED; partner matched solo',
                 'leader code %s; partner room %s' % (lo and lo['code'], po and po['nodes']))
        for c in o + [L_, P]: c.stop()

    # ---- 5. flaky network ------------------------------------------------------------------------------------
    def p_cancel_out_of_order(self):
        g = self.g(); a = Cab(self.sim, 'a', g); a.issue(); a.entry(23); first = a.apply
        a.entry(23, node=a.node)                                  # re-entry (new apply) overtakes ...
        a.cancel(apply=first)                                     # ... the late cancel of the first attempt
        a.start_polling(); o = self.cabs(3, g, 23)
        wait_for(lambda: a.outcome(), 10)
        oa = a.outcome()
        ok = oa and oa['code'] == 0 and a.node in oa['nodes']
        self.rec('late CancelMatching for an older apply_id', ok, 'current entry survives and matches',
                 'got %s' % ((oa['code'], oa['nodes']) if oa else None,))
        for c in o: c.stop()

    def p_retries(self):
        g = self.g(); a = Cab(self.sim, 'a', g); a.issue(); a.entry(23)
        c2 = a.resend_entry(); c3 = a.resend_entry()             # response "lost", client retries the same request
        a.check(); a.check()
        a.start_polling(); o = self.cabs(3, g, 23)
        wait_for(lambda: a.outcome() and all(c.outcome() for c in o), 10)
        rooms = {x['room'] for x in [a.outcome()] + [c.outcome() for c in o] if x}
        ok = (c2, c3) == (0, 0) and len(rooms) == 1 and a.outcome()['nodes'].count(a.node) == 1
        self.rec('retried Entry / Check (lost responses)', ok, 'one unit, one room', 'codes %s, rooms %s' % ((c2, c3), rooms))
        for c in o: c.stop()

    def p_reregistration(self):
        before = set(self.sim.issued)
        cs = [Cab(self.sim, 'r', 0) for _ in range(40)]
        got = []; lk = threading.Lock()
        def go(c):
            for _ in range(3):
                c.register(); ids = c.issue()
                with lk: got.extend(ids)
        ts = [threading.Thread(target=go, args=(c,)) for c in cs]
        [t.start() for t in ts]; [t.join() for t in ts]
        new = got
        ok = len(new) == len(set(new)) == 240 and not (set(new) & before)
        self.rec('re-registration: 40 cabinets x 3 (RegisterPcb + IssueNodeId) in parallel', ok, '240 unique new ids',
                 '%d ids, %d unique, %d collide with earlier' % (len(new), len(set(new)), len(set(new) & before)))

    # ---- 6. server restart -----------------------------------------------------------------------------------
    def p_restart(self):
        if not self.sim.restart_cmd:
            return
        g = self.g(); cs = self.cabs(3, g, 23)
        time.sleep(2)
        hi = max(self.sim.issued)
        t0 = mono(); subprocess.run(self.sim.restart_cmd, shell=True, check=False)
        self.sim.restarts.append(round(mono() - self.sim.t0, 1))
        wait_for(lambda: all(c.outcome() for c in cs), 15)
        codes = [c.outcome() and c.outcome()['code'] for c in cs]
        # harness assumption: on an error the cabinet runs IssueNodeId + EntryMatching again
        t_re = mono()
        for c in cs: c.issue(); c.entry(23); c.start_polling()
        n = Cab(self.sim, 'n', g); n.issue(); n.entry(23); n.start_polling()
        wait_for(lambda: all(c.outcome(c.node) for c in cs + [n]), 12)
        r = [c.outcome(c.node) for c in cs + [n]]
        ids_ok = min(c.node for c in cs + [n]) > hi
        ok = all(x and x['code'] == 0 for x in r) and ids_ok and all(cd == MATCH_CANCELED for cd in codes)
        self.rec('server restart while 3 cabinets wait', ok,
                 'waiting cabinets told MATCH_CANCELED; re-entry rematches; new node ids never collide',
                 'codes after restart %s; rematched %s; ids after restart > before: %s' % (codes, all(x and x['code'] == 0 for x in r), ids_ok),
                 rematch_s=round(max(x['t'] for x in r if x) - t_re, 1) if all(r) else None,
                 restart_s=round(t_re - t0, 1))

    def run(self):
        steps = [self.p_rejoin_short_same_node_new_mode, self.p_rejoin_short_new_node,
                 lambda: self.p_rejoin_long(True), lambda: self.p_rejoin_long(False),
                 self.p_drop_after_match, self.p_mid_battle_requeue,
                 lambda: self.p_pair_member_drop('partner'), lambda: self.p_pair_member_drop('leader'),
                 lambda: self.p_partner_rejoins_solo(False), lambda: self.p_partner_rejoins_solo(True),
                 self.p_cancel_out_of_order, self.p_retries, self.p_reregistration]
        ts = [threading.Thread(target=s) for s in steps]           # independent buckets (attr1) -> run in parallel
        [t.start() for t in ts]; [t.join() for t in ts]
        self.p_restart()                                          # last: it wipes the server's memory
        return self.out


# ------------------------------------------------------------------------------------------------ population
DPROFILE = dict(drop_wait=0.20, short_gap=(3, 15), long_gap=(25, 50), same_node=0.4, drop_after_match=0.08,
                mid_battle=0.10, partner_drop=0.3, lost_resp=0.06, drop_req=0.03, ooo_cancel=0.3,
                mass_at=110, mass_frac=0.30, mass_gap=(30, 40))


class FlakyConn(L.Conn):
    """Loses some responses (request reaches the server, the client times out and retries the same body) and
    drops some requests outright (never sent; the client retries after 1 s) - the game retries Check after
    errors every 1 s (matchmaking.md §2.3)."""
    def __init__(self, url, stats, rng, p):
        super().__init__(url, stats); self.rng, self.p = rng, p
    def raw(self, body, tag='raw'):
        x = self.rng.random()
        if x < self.p['drop_req']:
            self.stats.err(tag, 'harness: request dropped'); time.sleep(1.0)
        elif x < self.p['drop_req'] + self.p['lost_resp']:
            super().raw(body, tag); self.stats.err(tag, 'harness: response lost, retried'); time.sleep(1.0)
        return super().raw(body, tag)


class Population:
    def __init__(self, sim, people):
        self.sim, self.people, self.P = sim, people, DPROFILE
        self.ev = sim.stats.ev
        self.mass = threading.Event(); self.mass_back = {}
        self.sidc = 0; self.lock = threading.Lock()

    def sid(self):
        with self.lock: self.sidc += 1; return self.sidc

    def person(self, i, rng, start):
        P = self.P; sim = self.sim
        c = Cab(sim, 'p', 0); c.conn = FlakyConn(sim.url, sim.stats, rng, P)
        pair_partner = Cab(sim, 'pp', 0, loc=c.loc) if rng.random() < 0.2 else None
        if pair_partner: pair_partner.conn = FlakyConn(sim.url, sim.stats, rng, P)
        time.sleep(start)
        c.register(); c.issue()
        prev = None            # (sid, kind, t_left) of the session we are rejoining from
        last_node = None; late_cancel = None
        while mono() < sim.stop_at:
            if pair_partner and c.node != last_node: pair_partner.issue()
            last_node = c.node
            sid = self.sid(); sortie = 'T' if pair_partner else rng.choice(['S', 'S', 'S', 'TN'])
            # ranked (world 13/14, 4 classes) keeps queues thin enough that people really wait (and drop) there
            world = rng.choice([23, 23, 18, 13, 13]) if sortie == 'S' else rng.choice([23, 23, 14])
            cls = rng.randint(1, 4) if world in (13, 14) else 0
            t_sent = round(time.time() - sim.stats.t0, 3)       # the room can form inside this call
            code = c.entry(world, node=c.node, sortie=sortie, partner=pair_partner, attr2=cls)
            t_e = mono()
            if late_cancel and code == SUCCESS:                           # cancel of the previous attempt arrives late
                c.cancel(apply=late_cancel); self.ev('d_late_cancel', sid=sid, node=c.node, apply=late_cancel)
            late_cancel = None
            self.ev('d_entry', sid=sid, serial=c.serial, node=c.node, npc=c.npc if sortie == 'TN' else None,
                    pnode=pair_partner.node if pair_partner else None, pserial=pair_partner.serial if pair_partner else None,
                    world=world, sortie=sortie, code=code, rejoin_of=prev[0] if prev else None,
                    rejoin_kind=prev[1] if prev else None, gap=round(t_e - prev[2], 1) if prev else None, apply=c.apply,
                    t_sent=t_sent)
            if code != SUCCESS:
                c.issue(); time.sleep(1); continue
            # behaviour of this session
            drop_at = t_e + rng.uniform(1, 25) if rng.random() < P['drop_wait'] else None
            pdrop_at = t_e + rng.uniform(3, 30) if pair_partner and rng.random() < P['partner_drop'] else None
            if pair_partner: pair_partner.start_polling(pair_partner.node)
            res = None; node = c.node
            while True:
                now = mono()
                if self.mass.is_set() and i in self.mass_back:
                    res = ('mass_drop', now); break
                if drop_at and now >= drop_at:
                    res = ('drop_wait', now); break
                if pdrop_at and now >= pdrop_at:
                    pair_partner.stop(); self.ev('d_partner_drop', sid=sid, node=pair_partner.node); pdrop_at = None
                if now - t_e > 155:
                    res = ('stuck', now); break
                time.sleep(3 * rng.uniform(0.9, 1.1))
                code, room, cl = c.check(node)
                if code is None: continue
                if code == SUCCESS and cl:
                    res = ('matched', mono(), room, cl); break
                if code != SUCCESS:
                    res = ('code%d' % code, mono()); break
            if pair_partner: pair_partner.stop()
            kind = res[0]
            self.ev('d_end', sid=sid, node=node, result=kind, waited=round(res[1] - t_e, 2),
                    room=res[2] if kind == 'matched' else None, clients=res[3] if kind == 'matched' else None)
            if kind == 'matched':
                if rng.random() < P['drop_after_match']:                  # P2P never starts: requeue at once
                    prev = (sid, 'after_match', mono()); time.sleep(rng.uniform(1, 4))
                elif rng.random() < P['mid_battle']:                      # dropped mid-battle
                    prev = (sid, 'mid_battle', mono()); time.sleep(rng.uniform(3, 10))
                else:
                    prev = None; time.sleep(rng.uniform(20, 45))
                if rng.random() >= 0.3: c.issue()                       # else: same node, new apply_id
            elif kind in ('drop_wait', 'mass_drop'):
                t_left = res[1]
                gap = self.mass_back.get(i) if kind == 'mass_drop' else \
                    rng.uniform(*(P['short_gap'] if rng.random() < 0.5 else P['long_gap']))
                if kind == 'mass_drop': self.mass_back.pop(i, None)
                self.ev('d_left', sid=sid, node=node, how=kind, gap=round(gap, 1))
                time.sleep(gap)
                same = rng.random() < P['same_node']
                if same and rng.random() < P['ooo_cancel']: late_cancel = c.apply
                if not same:
                    if gap > STALE: c.register()
                    c.issue()
                prev = (sid, '%s_%s_%s' % (kind, 'short' if gap < STALE else 'long', 'same' if same else 'new'), t_left)
            else:                                                          # MATCH_CANCELED / NOENTRY / stuck
                prev = (sid, 'after_' + kind, mono()); c.issue(); time.sleep(rng.uniform(1, 3))

    def run(self):
        sim, P = self.sim, self.P
        rng = random.Random(sim.seed)
        sim.stop_at = mono() + sim.duration
        ts = []
        for i in range(self.people):
            start = rng.uniform(0, 3) if i < self.people * 0.4 else rng.uniform(0, 90)
            ts.append(threading.Thread(target=self.person, args=(i, random.Random(sim.seed * 7919 + i), start), daemon=True))
        [t.start() for t in ts]
        def mass():
            time.sleep(P['mass_at'])
            pick = rng.sample(range(self.people), int(self.people * P['mass_frac']))
            for i in pick: self.mass_back[i] = rng.uniform(*P['mass_gap'])
            self.ev('d_mass', n=len(pick)); self.mass.set()
            time.sleep(8); self.mass.clear()
        threading.Thread(target=mass, daemon=True).start()
        if sim.restart_cmd and sim.restart_at:
            def restart():
                time.sleep(sim.restart_at)
                self.ev('d_restart'); subprocess.run(sim.restart_cmd, shell=True, check=False)
                sim.restarts.append(round(mono() - sim.t0, 1))
            threading.Thread(target=restart, daemon=True).start()
        for t in ts: t.join(timeout=sim.duration + 240)


def analyze_pop(ev, restarts):
    ents = {e['sid']: e for e in ev if e['kind'] == 'd_entry'}
    ends = {e['sid']: e for e in ev if e['kind'] == 'd_end'}
    left = {e['sid']: e['t'] for e in ev if e['kind'] == 'd_left'}
    pdrop = {e['sid']: e['t'] for e in ev if e['kind'] == 'd_partner_drop'}
    node_sid = defaultdict(list)
    for s, e in ents.items():
        for n in (e['node'], e.get('pnode'), e.get('npc')):
            if n: node_sid[n].append(s)
    rooms = defaultdict(lambda: {'first': None, 'views': set(), 'seen_by': set()})
    rs_at = sorted(e['t'] for e in ev if e['kind'] == 'd_restart')   # room ids start at 1 again after a restart
    for e in ends.values():
        if e['result'] == 'matched':
            r = rooms[(sum(1 for x in rs_at if x < e['t']), e['room'])]; r['first'] = e['t'] if r['first'] is None else min(r['first'], e['t'])
            r['views'].add(tuple(map(tuple, e['clients']))); r['seen_by'].add(e['node'])
    viol = Counter(); ex = []; dbl = []
    ghosts = 0; ghosts_late = 0; sess_rooms = defaultdict(set); short = 0; short_after_drop = 0
    after_drop = {s for s, e in ents.items() if e.get('rejoin_kind') == 'after_match'}
    after_drop_of = {ents[s]['rejoin_of'] for s in after_drop}
    for rid_, r in rooms.items():
        cl = list(next(iter(r['views'])))
        if len(r['views']) > 1: viol['inconsistent_views'] += 1
        ys = [c for c in cl if c[3] == 'Y']
        if len(ys) > 4 or len(cl) > 4: viol['over_4'] += 1
        if len(cl) < 4: short += 1
        gh = []
        for c in ys:
            # the session this node was matched for = its latest entry before the room formed
            cand = [s for s in node_sid.get(c[1], []) if ents[s].get('t_sent', ents[s]['t']) <= r['first']]
            if cand:
                s0 = max(cand, key=lambda s: ents[s].get('t_sent', ents[s]['t'])); sess_rooms[s0].add(rid_)
                if s0 in after_drop_of: short_after_drop += 1
            for s in node_sid.get(c[1], []):
                if s != (s0 if cand else None): continue      # only the session it was matched for
                if c[1] == ents[s].get('pnode'): gone = pdrop.get(s)
                else: gone = left.get(s)
                if gone is not None and gone < r['first'] - 0.5:
                    gh.append((s, round(r['first'] - gone, 1)))
        if gh:
            ghosts += 1
            # a cabinet gone for > StaleAfter + one poll should never be matched: server-side bug
            if any(d > STALE + 4 for _, d in gh): ghosts_late += 1
            if len(ex) < 8: ex.append({'room': rid_, 'ghost_sessions': gh})
    for s, rs in sess_rooms.items():
        if len(rs) > 1:
            viol['double_room_same_entry'] += 1
            if len(dbl) < 8: dbl.append({'sid': s, 'rooms': sorted(rs)})
    # rejoin -> rematch times
    rej = defaultdict(list); rej_fail = Counter()
    for s, e in ents.items():
        if e.get('rejoin_of'):
            en = ends.get(s)
            k = e['rejoin_kind']
            if en and en['result'] == 'matched': rej[k].append(en['waited'])
            else: rej_fail['%s -> %s' % (k, en['result'] if en else 'unfinished')] += 1
    outcomes = Counter(e['result'] for e in ends.values())
    codes = Counter((e['code']) for e in ents.values())
    mt = [e['waited'] for e in ends.values() if e['result'] == 'matched']
    return {
        'sessions': len(ents), 'outcomes': dict(outcomes), 'entry_codes': dict(codes), 'rooms': len(rooms),
        'double_room_examples': dbl, 'rooms_short_handed': short,
        'room_members_left_after_match': short_after_drop,
        'late_cancels': sum(1 for e in ev if e['kind'] == 'd_late_cancel'),
        'late_cancel_killed_current_entry': sum(1 for e in ev if e['kind'] == 'd_late_cancel'
                                                and ends.get(e['sid'], {}).get('result') not in ('matched', None, 'mass_drop', 'drop_wait')),
        'rooms_with_ghost': ghosts, 'rooms_with_ghost_gone_gt_stale': ghosts_late, 'ghost_examples': ex, 'violations': dict(viol),
        'stuck_no_answer_155s': outcomes.get('stuck', 0),
        'time_to_match_s': {'n': len(mt), 'p50': L.pct(mt, .5), 'p95': L.pct(mt, .95), 'max': max(mt) if mt else None},
        'rematch_after_rejoin_s': {k: {'n': len(v), 'p50': L.pct(v, .5), 'p95': L.pct(v, .95), 'max': max(v)} for k, v in sorted(rej.items())},
        'rejoin_not_matched': dict(rej_fail.most_common()),
        'restarts_at_s': restarts,
    }


class DSim:
    def __init__(self, a):
        self.url, self.card_url = a.url, a.card_url
        self.restart_cmd, self.restart_at = a.restart_cmd, a.restart_at
        self.duration, self.seed = a.duration, a.seed
        self.stats = L.Stats(); self.issued = []; self.restarts = []
        self.t0 = mono(); self.stop_at = None
        self._pb = None

    def register_pcb(self, c):
        try:
            import game_server_nue_pb2 as pb
        except ImportError:
            return
        q = pb.Request(); q.type = pb.MTHD_REGISTER_PCB; q.request_id = L.rid()
        q.pcb_serial = c.serial; q.loc_id = c.loc; q.token = ''
        u = urllib.parse.urlparse(self.card_url)
        try:
            h = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=15)
            t0 = time.time(); h.request('POST', u.path or '/', body=q.SerializePartialToString(),
                                        headers={'Content-Type': 'application/x-protobuf', 'X-Nue-Protobuf-Revision': '141'})
            r = h.getresponse(); r.read(); self.stats.lat('register_pcb', time.time() - t0, r.status)
        except Exception as ex:
            self.stats.err('register_pcb', repr(ex))


def run(a):
    sim = DSim(a)
    pauses = []; done = threading.Event()
    def heartbeat():
        last, off = mono(), time.time() - mono()
        while not done.is_set():
            time.sleep(1); now, o = mono(), time.time() - mono()
            if now - last > 5 or abs(o - off) > 2:
                pauses.append([round(now - sim.t0, 1), round(max(now - last, abs(o - off)), 1)])
            last, off = now, o
    threading.Thread(target=heartbeat, daemon=True).start()
    mon = L.Monitor(a.pid, sim.stats); mon.start()
    rep = {'pauses': pauses}
    if a.part in ('all', 'probes'):
        rep['probes'] = Probes(sim).run()
    if a.part in ('all', 'population'):
        sim.stats.events.clear()
        Population(sim, a.people).run()
        rep['population'] = analyze_pop(sim.stats.events, sim.restarts)
        rep['events'] = sim.stats.events
    done.set(); mon.stop()
    rep['errors'] = {'%s:%s' % k: v for k, v in sim.stats.errors.items()}
    rep['status'] = {'%s:%s' % k: v for k, v in sim.stats.status.items()}
    rep['monitor'] = {'cpu_p95': L.pct([m[1] for m in mon.samples], .95), 'rss_max_mb': max([m[2] for m in mon.samples], default=None)}
    json.dump(rep, open(a.out, 'w'))
    summ = {k: v for k, v in rep.items() if k != 'events'}
    json.dump(summ, open(os.path.splitext(a.out)[0] + '.summary.json', 'w'), indent=1)
    print(json.dumps(summ, indent=1, default=str))
