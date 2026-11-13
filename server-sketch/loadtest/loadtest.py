#!/usr/bin/env python3
"""Load test for the EXVS2 IB matchmakers (nue.protocol.mms over HTTP).  EXPERIMENTAL.

Simulates N *people* (fake cabinets, fake ids only - never real card data) that keep queueing for
online matches against either matchmaker:
  * C# card server (patched EXVS2-IB-Server):  --url http://127.0.0.1:28080/match  [--card-url http://127.0.0.1:28080/]
  * Python sketch (mms_server.py):             --url http://127.0.0.1:5000/mms
Each session follows what static analysis says vsac29 does: IssueNodeId x2 -> EntryMatching ->
CheckMatching every poling_interval until clients come back, MATCH_CANCELED, or its own matching_timeout.
With --card-url every cabinet first sends RegisterPcb to the card server and uses the advertised SRV_MATCH uri.

Mix: solo shuffle (Mix Match 23, free 18, in-store 15), CPU-partner teams (TN), human pairs (T; the partner
cabinet polls and, half the time, sends its own entry too), ranked Class Match solo 13 / team 14 across
classes 1-4 and levels 1-4.  Burst + trickle arrivals, random cancels, silent drop-outs, requeue after a
simulated battle, and a few misbehaving clients (duplicate entries, cancel after match, garbage bodies,
stale node-id reuse).  --hijack N adds N attackers who enter with another waiting player's node id.

Output: a JSON report (--out) + a printed summary.  Run analysis only:  loadtest.py --analyze events.json
"""
import argparse, http.client, json, os, random, statistics, sys, threading, time, urllib.parse, uuid, zlib
from collections import Counter, defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
from pbwire import encode, decode

PING, ISSUE, ENTRY, CHECK, CANCEL = 0, 1, 2, 3, 4
SUCCESS, MATCH_CANCELED = 0, 1
NPC = 'PCB00000NPC'
SOLO_WORLDS = {13, 15, 18, 23}
TEAM_WORLDS = {14, 16, 19, 23}

# --------------------------------------------------------------------------------------------- transport
class Conn:
    """One keep-alive HTTP connection per simulated cabinet thread."""
    def __init__(self, url, stats):
        u = urllib.parse.urlparse(url)
        self.host, self.port, self.path = u.hostname, u.port or 80, u.path or '/'
        self.stats, self.c = stats, None

    def raw(self, body, tag='raw'):
        for attempt in range(3):
            t0 = time.time()
            try:
                if self.c is None:
                    self.c = http.client.HTTPConnection(self.host, self.port, timeout=15)
                self.c.request('POST', self.path, body=body, headers={
                    'Content-Type': 'application/x-protobuf', 'X-Nue-Protobuf-Revision': '6'})
                r = self.c.getresponse(); data = r.read()
                self.stats.lat(tag, time.time() - t0, r.status)
                return r.status, data
            except Exception as ex:
                self.stats.err(tag, repr(ex)); self.c = None
                time.sleep(0.2 * (attempt + 1))
        return None, b''

    def call(self, req, tag):
        st, data = self.raw(encode('Request', req), tag)
        if st != 200:
            return None
        try:
            return decode('Response', data)
        except Exception as ex:
            self.stats.err(tag, 'decode ' + repr(ex)); return None


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.lats = defaultdict(list); self.status = Counter(); self.errors = Counter()
        self.events = []          # (t, kind, dict)
        self.t0 = time.time()

    def lat(self, tag, dt, st):
        with self.lock: self.lats[tag].append(dt); self.status[(tag, st)] += 1

    def err(self, tag, msg):
        with self.lock: self.errors[(tag, msg[:120])] += 1

    def ev(self, kind, **kw):
        kw['t'] = round(time.time() - self.t0, 3); kw['kind'] = kind
        with self.lock: self.events.append(kw)

# --------------------------------------------------------------------------------------------- protocol
def client(node, serial, loc, ip, port, human=True):
    return {'node_id': node, 'pcb_serial': serial, 'loc_id': loc, 'pref_code': 13,
            'global_ipaddress': ip, 'global_port': port, 'local_ipaddress': '192.168.0.10', 'local_port': port,
            'nat_mapping_type': 1, 'nat_filtering_type': 1,
            'property': [{'property_id': 0, 'property_value': 'Y' if human else 'N'}]}

def rid(): return uuid.uuid4().hex

def shop_hash(loc): return int(zlib.crc32(loc.encode()) & 0xffff)

class Person:
    def __init__(self, i, shop, rng):
        self.i = i
        self.serial = 'LTPCB%06d' % i                       # fake serial
        self.loc = 'LTLOC%04d' % shop
        self.am = 7000000 + i                               # fake banapassport am id
        self.cls = rng.choice([1, 1, 2, 2, 2, 3, 3, 4])     # class 1..4 (inferred ids)
        self.level = rng.choice([1, 2, 2, 3, 3, 4])
        self.ip = '198.18.%d.%d' % (i // 250, i % 250 + 1)  # benchmark range, not routable
        self.partner = None
        self.bad = False
        self.last_nodes = None

# --------------------------------------------------------------------------------------------- scenario
class Sim:
    def __init__(self, a):
        self.a = a; self.rng = random.Random(a.seed); self.stats = Stats()
        self.stop_at = None; self.lock = threading.Lock()
        self.waiting = {}         # node -> session id (for --hijack victims)
        self.sid = 0
        self.url = a.url

    def next_sid(self):
        with self.lock: self.sid += 1; return self.sid

    def register_pcb(self, p):
        """Card server flow: RegisterPcb -> SRV_MATCH uri (needs generated game_server_nue_pb2)."""
        try:
            import game_server_nue_pb2 as pb
        except ImportError:
            return self.url
        q = pb.Request(); q.type = pb.MTHD_REGISTER_PCB; q.request_id = rid()
        q.pcb_serial = p.serial; q.loc_id = p.loc; q.token = ''
        u = urllib.parse.urlparse(self.a.card_url)
        c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=15)
        t0 = time.time()
        c.request('POST', u.path or '/', body=q.SerializePartialToString(),
                  headers={'Content-Type': 'application/x-protobuf', 'X-Nue-Protobuf-Revision': '141'})
        r = c.getresponse(); data = r.read(); self.stats.lat('register_pcb', time.time() - t0, r.status)
        out = pb.Response(); out.ParseFromString(data)
        m = [s.uri for s in out.register_pcb.server_info if s.server_type == pb.SRV_MATCH]
        stun = [s for s in out.register_pcb.server_info if s.server_type == pb.SRV_STUN]
        self.stats.ev('register', serial=p.serial, match=m[-1] if m else None, stun=bool(stun))
        return m[-1] if m else self.url

    def pick_mode(self, p, rng):
        if p.partner is not None:                      # human pair
            return rng.choices([(23, 'T'), (14, 'T'), (19, 'T')], [5, 4, 1])[0]
        return rng.choices([(23, 'S'), (13, 'S'), (18, 'S'), (23, 'TN'), (14, 'TN'), (15, 'S')],
                           [30, 30, 10, 10, 10, 10])[0]

    def params(self, world, p, rng, partner=None):
        attr2 = 0
        if world in (13, 14):
            attr2 = max(p.cls, partner.cls) if partner else p.cls
        elif world in (15, 16):
            attr2 = shop_hash(p.loc[-4:])
        elif world in (18, 19, 20, 25):
            attr2 = 1 + (p.i % 2)                       # win-rate bucket
        elif world == 23:
            attr2 = 1 if p.i % 5 == 0 else 0            # veteran flag
        lvl = max(p.level, partner.level) if (partner and world in (13, 14)) else (p.level if world in (13, 14) else 0)
        ps = [(1, 0), (2, attr2), (3, 0)] + ([(4, lvl)] if world in (13, 14) else [])
        return [{'attribute_id': k, 'parameter': v} for k, v in ps], attr2

    # one person's life: queue, (battle), requeue ...
    def person(self, p, conn, start_delay):
        rng = random.Random(self.a.seed * 1000 + p.i)
        time.sleep(start_delay)
        url = self.register_pcb(p) if self.a.card_url else self.url
        if url != conn.path and url.startswith('http'):
            conn = Conn(url, self.stats)
        while time.time() < self.stop_at:
            res = self.session(p, conn, rng)
            if res == 'matched':
                if rng.random() > self.a.requeue: break
                time.sleep(rng.uniform(*self.a.battle))     # simulated battle + result screens
            else:
                if rng.random() > self.a.requeue_fail: break
                time.sleep(rng.uniform(2, 8))

    def session(self, p, conn, rng):
        a, S = self.a, self.stats
        sid = self.next_sid()
        world, sortie = self.pick_mode(p, rng)
        partner = p.partner
        reuse = p.bad and p.last_nodes and rng.random() < 0.5      # misbehaviour: stale node-id reuse
        if reuse:
            me, npc = p.last_nodes
        else:
            r = conn.call({'type': ISSUE, 'request_id': rid(), 'issue_node_id': {
                'pcb_serial': p.serial, 'loc_id': p.loc, 'issue_at': int(time.time()), 'issue_count': 2}}, 'issue')
            ids = (r or {}).get('issue_node_id', {}).get('node_id', [])
            if len(ids) < 2 or len(set(ids)) < 2:
                S.ev('issue_fail', sid=sid, serial=p.serial, ids=ids); return 'error'
            me, npc = ids[0], ids[1]
        p.last_nodes = (me, npc)
        S.ev('issue', sid=sid, serial=p.serial, nodes=[me, npc], reuse=bool(reuse))
        groups, pnode = [], None
        if sortie == 'TN':
            groups = [{'client': client(npc, NPC, p.loc, '0.0.0.0', 0, human=False), 'player': {'banapassport_am_id': 0}}]
        elif sortie == 'T':
            pc = Conn(conn_url(conn), S)
            r = pc.call({'type': ISSUE, 'request_id': rid(), 'issue_node_id': {
                'pcb_serial': partner.serial, 'loc_id': partner.loc, 'issue_at': int(time.time()), 'issue_count': 2}}, 'issue')
            pids = (r or {}).get('issue_node_id', {}).get('node_id', [])
            if len(pids) < 2:
                S.ev('issue_fail', sid=sid, serial=partner.serial, ids=pids); return 'error'
            pnode = pids[0]
            groups = [{'client': client(pnode, partner.serial, partner.loc, partner.ip, 41000), 'player': {'banapassport_am_id': partner.am}}]
        params, attr2 = self.params(world, p, rng, partner if sortie == 'T' else None)
        timeout = a.matching_timeout
        e = {'apply_id': rng.randint(1, 1 << 30), 'myclient': client(me, p.serial, p.loc, p.ip, 40000),
             'myplayer': {'banapassport_am_id': p.am, 'parameters': params},
             'world': {'mucha_game_id': 'GIB1', 'version': 1, 'world_id': world},
             'groups': groups, 'matching_timeout': timeout, 'seq_num': 1, 'create_room_flag': 1,
             'entry_at': int(time.time())}
        cls = (max(p.cls, partner.cls) if sortie == 'T' else p.cls) if world in (13, 14) else None
        lvl = next((x['parameter'] for x in params if x['attribute_id'] == 4), None)
        info = dict(sid=sid, serial=p.serial, world=world, sortie=sortie, node=me, npc=npc if sortie == 'TN' else None,
                    pnode=pnode, pserial=partner.serial if sortie == 'T' else None, cls=cls, level=lvl, attr2=attr2,
                    loc=p.loc, bad=p.bad, reuse=bool(reuse))
        t_entry = time.time()
        r = conn.call({'type': ENTRY, 'request_id': rid(), 'entry_matching': e}, 'entry')
        if not r or r.get('code') != SUCCESS:
            S.ev('entry_fail', code=(r or {}).get('code'), **info); return 'error'
        S.ev('entry', **info)
        interval = max(1, (r.get('entry_matching') or {}).get('poling_interval', 3))
        with self.lock:
            self.waiting[me] = (sid, sortie)
        # misbehaviour flavours
        flavour = rng.choice(['dup', 'cancel_after', 'garbage', 'dup']) if p.bad else None
        if flavour == 'dup':
            r2 = conn.call({'type': ENTRY, 'request_id': rid(), 'entry_matching': e}, 'entry_dup')
            S.ev('dup_entry', sid=sid, code=(r2 or {}).get('code'))
        if flavour == 'garbage':
            threading.Thread(target=self.garbage, args=(conn_url(conn), rng.random()), daemon=True).start()
        # partner cabinet
        pres = {}
        pth = None
        if sortie == 'T':
            own_entry = rng.random() < 0.5
            pth = threading.Thread(target=self.partner_poll, args=(conn_url(conn), sid, pnode, me, e, partner, own_entry, timeout, interval, pres))
            pth.start()
        # behaviour
        cancel_at = t_entry + rng.uniform(3, 60) if rng.random() < a.cancel_rate else None
        vanish_at = t_entry + rng.uniform(3, 60) if rng.random() < a.vanish_rate else None
        out = 'timeout'
        try:
            while True:
                now = time.time()
                if cancel_at and now >= cancel_at:
                    conn.call({'type': CANCEL, 'request_id': rid(), 'cancel_matching': {
                        'node_id': me, 'apply_id': e['apply_id'], 'cancel_at': int(now)}}, 'cancel')
                    S.ev('cancel', sid=sid, node=me, waited=round(now - t_entry, 2)); out = 'cancel'; break
                if vanish_at and now >= vanish_at:
                    S.ev('vanish', sid=sid, node=me, waited=round(now - t_entry, 2)); out = 'vanish'; break
                if now - t_entry > timeout + interval:
                    S.ev('client_timeout', sid=sid, node=me, waited=round(now - t_entry, 2)); out = 'timeout'; break
                time.sleep(interval * rng.uniform(0.9, 1.1))
                r = conn.call({'type': CHECK, 'request_id': rid(), 'check_matching': {'node_id': me, 'check_at': int(time.time())}}, 'check')
                if r is None:
                    continue
                code = r.get('code'); cm = r.get('check_matching') or {}
                cl = cm.get('clients', [])
                if code == SUCCESS and cl:
                    S.ev('matched', sid=sid, node=me, room=cm.get('room_id'), apply_id=cm.get('apply_id'),
                         expect_apply=e['apply_id'], waited=round(time.time() - t_entry, 2), clients=slim(cl))
                    out = 'matched'
                    if flavour == 'cancel_after':
                        conn.call({'type': CANCEL, 'request_id': rid(), 'cancel_matching': {
                            'node_id': me, 'apply_id': e['apply_id'], 'cancel_at': int(time.time())}}, 'cancel_after')
                        r3 = conn.call({'type': CHECK, 'request_id': rid(), 'check_matching': {'node_id': me, 'check_at': int(time.time())}}, 'check')
                        S.ev('cancel_after', sid=sid, code=(r3 or {}).get('code'),
                             room=((r3 or {}).get('check_matching') or {}).get('room_id'))
                    break
                if code != SUCCESS:
                    S.ev('server_end', sid=sid, node=me, code=code, waited=round(time.time() - t_entry, 2))
                    out = 'canceled' if code == MATCH_CANCELED else 'noentry'
                    break
        finally:
            with self.lock:
                self.waiting.pop(me, None)
            S.ev('session_end', sid=sid, result=out)
            if pth: pth.join()
        return out

    def partner_poll(self, url, sid, pnode, leader, e, partner, own_entry, timeout, interval, pres):
        S, c = self.stats, Conn(url, self.stats)
        t0 = time.time()
        if own_entry:            # partner cabinet also enters, naming the leader as its group [unknown in game]
            pe = dict(e); pe['myclient'] = e['groups'][0]['client']
            pe['myplayer'] = {'banapassport_am_id': partner.am, 'parameters': e['myplayer']['parameters']}
            pe['groups'] = [{'client': e['myclient'], 'player': {'banapassport_am_id': e['myplayer']['banapassport_am_id']}}]
            r = c.call({'type': ENTRY, 'request_id': rid(), 'entry_matching': pe}, 'entry_partner')
            S.ev('partner_entry', sid=sid, code=(r or {}).get('code'))
        while time.time() - t0 < timeout + interval:
            time.sleep(interval)
            r = c.call({'type': CHECK, 'request_id': rid(), 'check_matching': {'node_id': pnode, 'check_at': int(time.time())}}, 'check_partner')
            if r is None: continue
            cl = (r.get('check_matching') or {}).get('clients', [])
            if r.get('code') == SUCCESS and cl:
                S.ev('partner_matched', sid=sid, node=pnode, room=r['check_matching'].get('room_id'), clients=slim(cl)); return
            if r.get('code') != SUCCESS:
                S.ev('partner_end', sid=sid, node=pnode, code=r.get('code')); return

    def garbage(self, url, x):
        c, S = Conn(url, self.stats), self.stats
        kinds = [
            ('random_bytes', bytes(random.getrandbits(8) for _ in range(64))),
            ('truncated', encode('Request', {'type': CHECK, 'request_id': 'x' * 20, 'check_matching': {'node_id': 5, 'check_at': 1}})[:-3]),
            ('empty', b''),
            ('entry_no_myclient', encode('Request', {'type': ENTRY, 'request_id': 'g1', 'entry_matching': {'apply_id': 1, 'matching_timeout': 5, 'entry_at': 1}})),
            ('check_unknown_node', encode('Request', {'type': CHECK, 'request_id': 'g2', 'check_matching': {'node_id': 4000000000, 'check_at': 1}})),
            ('unknown_type', encode('Request', {'type': 77, 'request_id': 'g3'})),
            ('issue_count_huge', encode('Request', {'type': ISSUE, 'request_id': 'g4', 'issue_node_id': {'pcb_serial': 'LTBAD', 'loc_id': 'LTBAD', 'issue_at': 1, 'issue_count': 100000}})),
        ]
        for name, body in kinds:
            st, data = c.raw(body, 'garbage')
            ok = None
            try: ok = decode('Response', data).get('code') if st == 200 else None
            except Exception: ok = 'undecodable'
            S.ev('garbage', what=name, status=st, code=ok, n_ids=len(decode('Response', data).get('issue_node_id', {}).get('node_id', [])) if st == 200 and name == 'issue_count_huge' else None)

    def hijacker(self, k):
        """Attacker: waits, then enters with a node id currently owned by another waiting player."""
        rng = random.Random(99 + k); c = Conn(self.url, self.stats)
        time.sleep(10 + 5 * k)
        with self.lock:
            victims = list(self.waiting.items())
        if not victims: return
        pref = [v for v in victims if v[1][1] == ('T' if k % 2 == 0 else 'S')] or victims
        node, (sid, _) = rng.choice(pref)
        e = {'apply_id': 1, 'myclient': client(node, 'LTEVIL%02d' % k, 'LTEVIL', '198.19.0.1', 1),
             'myplayer': {'banapassport_am_id': 6660000 + k}, 'world': {'mucha_game_id': 'GIB1', 'version': 1, 'world_id': 23},
             'groups': [], 'matching_timeout': 150, 'entry_at': int(time.time())}
        r = c.call({'type': ENTRY, 'request_id': rid(), 'entry_matching': e}, 'hijack')
        self.stats.ev('hijack', victim_sid=sid, node=node, code=(r or {}).get('code'))

    def run(self):
        a = self.a; rng = self.rng
        people = []
        shops = max(3, a.people // 4)
        for i in range(a.people):
            people.append(Person(i, rng.randrange(shops), rng))
        # human pairs: same shop
        idx = list(range(a.people)); rng.shuffle(idx)
        npairs = int(a.people * a.pair_frac / 2)
        for k in range(npairs):
            ld, pt = people[idx[2 * k]], people[idx[2 * k + 1]]
            pt.loc = ld.loc; ld.partner = pt; pt.partner = 'busy'
        for p in people:
            if p.partner != 'busy' and rng.random() < a.bad_frac: p.bad = True
        actors = [p for p in people if p.partner != 'busy']
        burst = int(len(actors) * a.burst)
        delays = [rng.uniform(0, 3) if j < burst else rng.uniform(0, a.arrival) for j in range(len(actors))]
        self.stop_at = time.time() + a.duration
        self.stats.t0 = time.time()
        ts = [threading.Thread(target=self.person, args=(p, Conn(self.url, self.stats), d), daemon=True)
              for p, d in zip(actors, delays)]
        ts += [threading.Thread(target=self.hijacker, args=(k,), daemon=True) for k in range(a.hijack)]
        mon = Monitor(a.pid, self.stats); mon.start()
        pauses = []
        def heartbeat():
            # Detects the host stalling: a VM suspend stops CLOCK_MONOTONIC but not the wall clock, and an NTP step
            # moves only the wall clock. Either shows up as a jump in (wall - monotonic) or as a long monotonic gap.
            last, off = time.monotonic(), time.time() - time.monotonic()
            while not done.is_set():
                time.sleep(1); now, o = time.monotonic(), time.time() - time.monotonic()
                if now - last > 5 or abs(o - off) > 2:
                    pauses.append([round(time.time() - self.stats.t0, 1), round(max(now - last, abs(o - off)), 1)])
                last, off = now, o
        done = threading.Event(); threading.Thread(target=heartbeat, daemon=True).start()
        for t in ts: t.start()
        for t in ts: t.join(timeout=a.duration + a.matching_timeout + 120)
        mon.stop(); done.set()
        meta = {'pauses': pauses, 'people': a.people, 'actors': len(actors), 'pairs': npairs, 'bad': sum(p.bad for p in people),
                'url': a.url, 'card_url': a.card_url, 'duration': a.duration, 'elapsed': round(time.time() - self.stats.t0, 1),
                'fill_after': a.fill_after, 'hijack': a.hijack, 'seed': a.seed,
                'people_info': {p.serial: {'cls': p.cls, 'level': p.level, 'loc': p.loc} for p in people}}
        return {'meta': meta, 'events': self.stats.events, 'monitor': mon.samples,
                'lat': {k: v for k, v in self.stats.lats.items()},
                'status': {'%s:%s' % k: v for k, v in self.stats.status.items()},
                'errors': {'%s:%s' % k: v for k, v in self.stats.errors.items()}}


def conn_url(c): return 'http://%s:%d%s' % (c.host, c.port, c.path)

def slim(cl):
    return [[x['group_id'], x['client']['node_id'], x['client']['pcb_serial'], x['client']['property'][0]['property_value']]
            for x in cl]


class Monitor(threading.Thread):
    """Samples server CPU% / RSS from /proc/<pid> once per second."""
    def __init__(self, pid, stats):
        super().__init__(daemon=True); self.pid, self.stats, self.samples, self.on = pid, stats, [], True
    def stop(self): self.on = False
    def run(self):
        if not self.pid: return
        hz = os.sysconf('SC_CLK_TCK'); last = None
        while self.on:
            try:
                f = open('/proc/%d/stat' % self.pid).read().rsplit(')', 1)[1].split()
                ticks = int(f[11]) + int(f[12])
                rss = int(open('/proc/%d/status' % self.pid).read().split('VmRSS:')[1].split()[0]) // 1024
                now = time.time()
                if last:
                    self.samples.append([round(now - self.stats.t0, 1), round(100.0 * (ticks - last[1]) / hz / (now - last[0]), 1), rss])
                last = (now, ticks)
            except Exception:
                return
            time.sleep(1)

# --------------------------------------------------------------------------------------------- analysis
def pct(xs, q, nd=2):
    if not xs: return None
    xs = sorted(xs); k = (len(xs) - 1) * q
    lo = int(k); hi = min(lo + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), nd)

def analyze(rep):
    ev, meta = rep['events'], rep['meta']
    pinfo = meta['people_info']
    fill_after = meta.get('fill_after', 30)
    sess = {}
    for e in ev:
        if e['kind'] == 'entry': sess[e['sid']] = dict(e, t_entry=e['t'])
    by_node = {}
    for s in sess.values():
        by_node.setdefault(s['node'], []).append(s['sid'])
        if s.get('pnode'): by_node.setdefault(s['pnode'], []).append(s['sid'])
    ends = {e['sid']: e['result'] for e in ev if e['kind'] == 'session_end'}
    left_at = {e['sid']: e['t'] for e in ev if e['kind'] in ('cancel', 'vanish', 'client_timeout', 'server_end')}
    matched = [e for e in ev if e['kind'] == 'matched']
    pmatched = [e for e in ev if e['kind'] == 'partner_matched']
    issues = []
    def bad(kind, **kw):
        issues.append(dict(kind=kind, **kw))

    # ---- rooms
    rooms = defaultdict(lambda: {'views': [], 'first': None, 'observers': set()})
    for e in matched + pmatched:
        r = rooms[e['room']]
        r['views'].append(tuple(tuple(x) for x in e['clients']))
        r['first'] = e['t'] if r['first'] is None else min(r['first'], e['t'])
        r['observers'].add(e['node'])
        if e['kind'] == 'matched' and e.get('apply_id') != e.get('expect_apply'):
            bad('apply_id_mismatch', room=e['room'], sid=e['sid'])
    node_rooms = defaultdict(set)
    room_rows = []
    short_waits, humans_hist, ghosts_rooms, level_spread = [], Counter(), 0, []
    for rid_, r in rooms.items():
        views = set(r['views'])
        if len(views) > 1: bad('inconsistent_room_views', room=rid_, n=len(views))
        cl = list(r['views'][0])
        ys = [c for c in cl if c[3] == 'Y']
        humans_hist[len(ys)] += 1
        if len(ys) > 4: bad('more_than_4_humans', room=rid_, humans=len(ys))
        if len(cl) > 4: bad('more_than_4_slots', room=rid_, slots=len(cl))
        groups = Counter(c[0] for c in cl)
        if set(groups) - {0, 1} or len(groups) < 2: bad('bad_groups', room=rid_, groups=dict(groups))
        if any(v > 2 for v in groups.values()): bad('side_over_2', room=rid_, groups=dict(groups))
        if len({c[1] for c in cl}) != len(cl): bad('node_twice_in_room', room=rid_)
        if len({c[2] for c in ys}) != len(ys): bad('cabinet_twice_in_room', room=rid_)
        sids = set()
        for c in cl:
            node_rooms[c[1]].add(rid_)
            for s in by_node.get(c[1], []):
                sids.add(s)
        ss = [sess[s] for s in sids]
        # session that owns each human node in this room (latest entry before room formed)
        members = []
        for c in ys:
            cand = [sess[s] for s in by_node.get(c[1], []) if sess[s]['t_entry'] <= r['first'] + 0.5]
            if not cand:
                bad('unknown_node_in_room', room=rid_, node=c[1]); continue
            members.append((c, max(cand, key=lambda s: s['t_entry'])))
        units = {}
        for c, s in members: units[s['sid']] = s
        worlds = {s['world'] for s in units.values()}
        if len(worlds) > 1: bad('mixed_worlds', room=rid_, worlds=sorted(worlds, key=str))
        w = next(iter(worlds)) if worlds else None
        if w in (13, 14):
            cls = {s['cls'] for s in units.values()}
            if len(cls) > 1: bad('ranked_class_mix', room=rid_, classes=sorted(cls, key=str))
            lv = [s['level'] for s in units.values() if s['level'] is not None]
            if lv: level_spread.append(max(lv) - min(lv))
        if w in (15, 16) and len({s['loc'] for s in units.values()}) > 1: bad('instore_shop_mix', room=rid_)
        if w == 13 and any(s['sortie'] != 'S' for s in units.values()): bad('team_in_solo_world', room=rid_)
        gof = {c[1]: c[0] for c in cl}
        for s in units.values():
            if s['sortie'] == 'T':
                if s['pnode'] not in gof: bad('pair_partner_missing', room=rid_, sid=s['sid'])
                elif gof[s['pnode']] != gof[s['node']]: bad('pair_split', room=rid_, sid=s['sid'])
            if s['sortie'] == 'TN':
                if s['npc'] not in gof: bad('cpu_standin_missing', room=rid_, sid=s['sid'])
                elif gof[s['npc']] != gof[s['node']]: bad('cpu_on_wrong_side', room=rid_, sid=s['sid'])
        # ghosts: humans whose cabinet had already left (cancel / vanish / timeout) before the room formed
        ghosts = [s['sid'] for s in units.values() if s['sid'] in left_at and left_at[s['sid']] < r['first'] - 0.01]
        unseen = [c[1] for c in ys if c[1] not in r['observers']]
        if ghosts: ghosts_rooms += 1
        slots = len(cl)
        wait_oldest = r['first'] - min(s['t_entry'] for s in units.values()) if units else None
        if slots < 4 and wait_oldest is not None:
            short_waits.append(round(wait_oldest, 2))
            if wait_oldest < fill_after - 3.5: bad('short_room_before_fill_after', room=rid_, wait=round(wait_oldest, 2))
        room_rows.append({'room': rid_, 'world': w, 'humans': len(ys), 'slots': slots, 'ghosts': ghosts, 'unseen': unseen,
                          'units': ''.join(sorted(s['sortie'][0] + ('N' if s['sortie'] == 'TN' else '') for s in units.values())),
                          'formed': r['first']})
    reused = {n for s in sess.values() if s.get('reuse') for n in (s['node'], s.get('npc')) if n}
    reuse_rematch = 0
    for n, rs in node_rooms.items():
        if len(rs) > 1:
            if n in reused: reuse_rematch += 1          # harness misbehaviour (stale node id reuse), sequential rooms
            else: bad('node_in_two_rooms', node=n, rooms=sorted(rs))
    # person double-booked: same serial in two rooms formed within 10 s of each other
    serial_rooms = defaultdict(list)
    for rid_, r in rooms.items():
        for c in r['views'][0]:
            if c[3] == 'Y': serial_rooms[c[2]].append((r['first'], rid_))
    ghost_rooms_by_serial = {(sess[g]['serial'], r['room']) for r in room_rows for g in r['ghosts']}
    ghost_requeue = 0
    for ser, lst in serial_rooms.items():
        lst.sort()
        for (t1, r1), (t2, r2) in zip(lst, lst[1:]):
            if t2 - t1 < 10:
                if (ser, r1) in ghost_rooms_by_serial: ghost_requeue += 1   # left, was matched as a ghost, came back
                else: bad('cabinet_in_two_rooms_at_once', serial=ser, rooms=[r1, r2], dt=round(t2 - t1, 2))
    # ---- sessions
    waits = [e['waited'] for e in matched]
    by_mode = defaultdict(list)
    for e in matched:
        s = sess[e['sid']]; by_mode['%d/%s' % (s['world'], s['sortie'])].append(e['waited'])
    outcome = Counter(ends.get(s, 'unfinished') for s in sess)
    unmatched_why = Counter()
    for sid, s in sess.items():
        res = ends.get(sid, 'unfinished')
        if res != 'matched':
            unmatched_why['%s %d/%s' % (res, s['world'], s['sortie'])] += 1
    # people never matched
    ppl_matched = {sess[e['sid']]['serial'] for e in matched} | {sess[e['sid']]['pserial'] for e in matched if sess[e['sid']].get('pserial')}
    all_ppl = set(pinfo)
    garbage = Counter('%s->%s/%s' % (e['what'], e['status'], e['code']) for e in ev if e['kind'] == 'garbage')
    huge = [e['n_ids'] for e in ev if e['kind'] == 'garbage' and e['what'] == 'issue_count_huge']
    hijacks = [e for e in ev if e['kind'] == 'hijack']
    hij_victims = []
    for h in hijacks:
        res = ends.get(h['victim_sid'])
        hij_victims.append({'victim_sid': h['victim_sid'], 'entry_code': h['code'], 'victim_result': res})
    dup = Counter(e['code'] for e in ev if e['kind'] == 'dup_entry')
    ca = Counter('%s/room=%s' % (e['code'], 'same' if e['room'] else 'none') for e in ev if e['kind'] == 'cancel_after')
    pe = Counter(e['code'] for e in ev if e['kind'] == 'partner_entry')
    # pairs where partner never got the room
    partner_seen = {e['sid'] for e in pmatched}
    pair_miss = [e['sid'] for e in matched if sess[e['sid']]['sortie'] == 'T' and e['sid'] not in partner_seen]
    mon = rep.get('monitor') or []
    lat = {k: {'n': len(v), 'p50_ms': round(1000 * pct(v, .5, 6), 1), 'p95_ms': round(1000 * pct(v, .95, 6), 1),
               'p99_ms': round(1000 * pct(v, .99, 6), 1),
               'max_ms': round(1000 * max(v), 1)} for k, v in rep['lat'].items() if v}
    total_req = sum(len(v) for v in rep['lat'].values())
    el = meta['elapsed']
    summary = {
        'harness_pauses_s': meta.get('pauses', []),
        'people': meta['people'], 'pairs': meta['pairs'], 'misbehaving': meta['bad'], 'elapsed_s': el,
        'sessions': len(sess), 'outcomes': dict(outcome),
        'rooms': len(rooms), 'rooms_by_humans': dict(sorted(humans_hist.items())),
        'rooms_by_world': dict(Counter(r['world'] for r in room_rows)),
        'room_unit_shapes': dict(Counter(r['units'] for r in room_rows).most_common()),
        'time_to_match_s': {'n': len(waits), 'p50': pct(waits, .5), 'p95': pct(waits, .95), 'max': max(waits) if waits else None},
        'time_to_match_by_mode': {k: {'n': len(v), 'p50': pct(v, .5), 'p95': pct(v, .95), 'max': max(v)} for k, v in sorted(by_mode.items())},
        'short_rooms': len(short_waits), 'short_room_wait_oldest_s': {'min': min(short_waits) if short_waits else None, 'p50': pct(short_waits, .5)},
        'ranked_level_spread': dict(Counter(level_spread)),
        'rooms_with_ghosts': ghosts_rooms, 'reused_node_rematched': reuse_rematch,
        'ghost_then_requeued': ghost_requeue,
        'rooms_with_unseen_members': sum(1 for r in room_rows if r['unseen']),
        'unmatched_sessions': dict(unmatched_why.most_common()),
        'people_never_matched': len(all_ppl - ppl_matched),
        'pairs_partner_never_saw_room': len(pair_miss),
        'dup_entry_codes': dict(dup), 'cancel_after_match': dict(ca), 'partner_own_entry_codes': dict(pe),
        'garbage': dict(garbage), 'issue_count_huge_ids': huge[:3],
        'hijacks': hij_victims,
        'violations': dict(Counter(i['kind'] for i in issues)), 'violation_examples': issues[:15],
        'http_status': rep['status'], 'transport_errors': rep['errors'],
        'requests': total_req, 'req_per_s': round(total_req / el, 1) if el else None, 'latency': lat,
        'server_cpu_pct': {'p50': pct([m[1] for m in mon], .5), 'p95': pct([m[1] for m in mon], .95), 'max': max([m[1] for m in mon], default=None)},
        'server_rss_mb': {'start': mon[0][2] if mon else None, 'max': max([m[2] for m in mon], default=None), 'end': mon[-1][2] if mon else None},
    }
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--url', default='http://127.0.0.1:28080/match')
    ap.add_argument('--card-url', help='card server base url: send RegisterPcb first and use its SRV_MATCH uri')
    ap.add_argument('--people', type=int, default=100)
    ap.add_argument('--duration', type=float, default=300, help='seconds during which people (re)queue')
    ap.add_argument('--arrival', type=float, default=120, help='trickle arrivals spread over this many seconds')
    ap.add_argument('--burst', type=float, default=0.4, help='fraction of people arriving in the first 3 s')
    ap.add_argument('--pair-frac', type=float, default=0.2, help='fraction of people in human pairs')
    ap.add_argument('--bad-frac', type=float, default=0.05, help='fraction of misbehaving cabinets')
    ap.add_argument('--cancel-rate', type=float, default=0.06); ap.add_argument('--vanish-rate', type=float, default=0.03)
    ap.add_argument('--requeue', type=float, default=0.8, help='P(requeue after a match)')
    ap.add_argument('--requeue-fail', type=float, default=0.6, help='P(requeue after timeout / cancel)')
    ap.add_argument('--battle', type=float, nargs=2, default=(20, 45), help='simulated battle length range (s)')
    ap.add_argument('--matching-timeout', type=int, default=150)
    ap.add_argument('--fill-after', type=float, default=30, help='server setting, only used by the analysis')
    ap.add_argument('--hijack', type=int, default=0)
    ap.add_argument('--pid', type=int, help='server pid for CPU / RSS sampling')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--out', default='loadtest_report.json')
    ap.add_argument('--analyze', help='re-analyze a saved report json')
    ap.add_argument('--scenario', choices=['load', 'disconnects'], default='load',
                    help='disconnects = disconnect / rejoin probes + population (see disconnects.py)')
    ap.add_argument('--part', choices=['all', 'probes', 'population'], default='all', help='disconnects: which part')
    ap.add_argument('--restart-cmd', help='disconnects: shell command that restarts the server (keeps its node-id file)')
    ap.add_argument('--restart-at', type=float, help='disconnects population: restart the server at this second')
    a = ap.parse_args()
    if a.scenario == 'disconnects':
        import disconnects
        return disconnects.run(a)
    if a.analyze:
        rep = json.load(open(a.analyze))
    else:
        rep = Sim(a).run()
        json.dump(rep, open(a.out, 'w'))
    s = analyze(rep)
    json.dump(s, open(os.path.splitext(a.out if not a.analyze else a.analyze)[0] + '.summary.json', 'w'), indent=1)
    print(json.dumps(s, indent=1))

if __name__ == '__main__':
    main()
