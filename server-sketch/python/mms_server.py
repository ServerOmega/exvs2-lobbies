#!/usr/bin/env python3
"""Prototype universal EXVS2 IB matchmaking server (nue.protocol.mms over HTTP POST).

*** EXPERIMENTAL — tested only against fake_cabinet.py on the box, never against the real game. ***

Stdlib only.  Run:  python3 mms_server.py --port 5000 [--state mms_state.json] [--ratings mms_ratings.json] [-v]
Point the card server's RegisterPcb SRV_MATCH uri at  http://<this-host>:5000/mms
(the game uses the uri verbatim as the URL and ignores the port field).

Protocol facts this follows (see analysis/matchmaking.md, analysis/ranked-matching.md):
  * body = serialized nue.protocol.mms.Request; reply must be HTTP 200 + serialized Response
    with type/request_id/code always present (proto2 required fields).
  * IssueNodeId: game asks issue_count=2 and rejects replies with fewer node_ids.
  * EntryMatching: game reads only poling_interval (seconds).
  * CheckMatching: code 0 + empty clients = "keep polling"; when matched return room_id and
    ALL clients (incl. the requester and CPU stand-ins), group_id = team (0/1).  The client keeps only
    clients whose property[0] == "Y" (humans, max 4) and derives team = (group_id != first client's).
  * Casual / shuffle (analysis/casual-shuffle-matching.md): solo-sortie entries carry no groups and are
    shuffled into pairs by the SERVER; team-sortie entries carry their partner ("Y") or CPU ("N") as
    groups[0] and are never split.  Per-mode buckets by world_id (+attr2 where it encodes shop/settings).
  * CancelMatching: reply ignored by the game.
  * Ranked = "Class Match G" (OnlineMatchingMode OMM_CLASS): world_id 13 (solo/shuffle) or 14 (team/fixed).
    Player.parameters: attr1 = TestMode wanMatchingGroupId (or 0), attr2 = class_id (team: the pair's
    class), attr3 = subnet/LAN flag, attr4 = matching level from the LoadClassMatch pattern table.
    The MMS protocol carries no rate/grade/name: opponents' class/grade are exchanged P2P, and the new
    rate is computed by the client and uploaded to the CARD server (SaveVsmOnResult.class_match_result).
"""
import argparse, json, logging, os, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pbwire import encode, decode

PING, ISSUE_NODE_ID, ENTRY, CHECK, CANCEL, MATCHING_SETTING = 0, 1, 2, 3, 4, 100
SUCCESS, MATCH_CANCELED, PROCESS_WAIT = 0, 1, 2
ERR_REQUEST, ERR_SERVER, ERR_MAINTENANCE, ERR_MATCH_NOENTRY = 100, 101, 102, 103
ERR_NODEID, ERR_MATCH_CONDITION, ERR_DUPLICATE_ENTRY = 200, 201, 202
NPC_SERIAL = 'PCB00000NPC'          # CPU stand-in a TEAM-sortie entry puts in groups[0] (property "N")
POLL_INTERVAL = 3                   # PROCESS_WAIT_POLING_INTERVAL from the proto
STALE_AFTER = 20                    # s without CheckMatching -> drop entry
MATCHED_KEEP = 60                   # s to keep a finished room for late polls

# Ranked (Class Match G).  world ids from the client's mode->world table (0x140753330), see ranked-matching.md §2.
CLASS_WORLDS = {13: 'class-solo', 14: 'class-team'}
A_GROUP, A_CLASS, A_LANFLAG, A_LEVEL = 1, 2, 3, 4
A_EXTRA = 2                         # casual worlds: attr2 = mode-specific value (see casual-shuffle-matching.md §4)
# Search widening for ranked: (seconds waited, max |level diff|, max |mmr diff|).  Last row = anything goes.
RANKED_BANDS = [(0, 0, 100), (15, 1, 200), (35, 2, 350), (60, 99, 10 ** 9)]

# world_id -> (name, attr2 policy).  'hard' = attr2 must be equal to share a room, 'soft' = preferred only,
# None = ignored.  Source: mode code -> world table 0x140753a3c and attr builders 0x140752b60 / 0x140753ab4.
# Solo-sortie entries (kind 0) carry NO groups; team-sortie entries (kind 1) carry 1 group = the partner
# (property "Y" = human partner cabinet, "N" = CPU stand-in PCB00000NPC).  See casual-shuffle-matching.md.
WORLDS = {
    5:  ('legacy-mode0', None),
    13: ('class-solo', 'class'), 14: ('class-team', 'class'),              # Class Match G (ranked)
    15: ('instore-solo', 'hard'), 16: ('instore-team', 'hard'),           # attr2 = hex(last 4 chars of loc_id)
    17: ('shop-setting', 'hard'),                                          # attr2 = TestMode shop match settings
    18: ('free-solo', 'soft'), 19: ('free-team', 'soft'), 20: ('free-solo-b', 'soft'),
    25: ('free-mixed', 'soft'),                                            # attr2 = win-rate bucket 1/2
    23: ('mix-match', 'soft'),                                             # Mix Match: solo+team, attr2 = 'veteran' flag
    21: ('mode1', None), 22: ('mode2', None),
    6: ('tag-solo', 'hard'), 7: ('tag-team', 'hard'), 24: ('tag-mixed', 'hard'),
    26: ('tag-solo-def', 'hard'), 27: ('tag-team-def', 'hard'), 32: ('tag-mixed-def', 'hard'), 33: ('tag7', 'hard'),
    8: ('mode8', 'hard'), 9: ('mode9', 'hard'),
}
SOFT_WAIT = 15                      # s during which a 'soft' attr2 (win-rate bucket, veteran flag) must match
FILL_AFTER = 30                     # s the oldest waiter waits for a full 2v2 before a short-handed room is allowed
POOL_MAX = 12                       # candidates examined per anchor (combinatorics bound)
TEAM_SLOTS = 2                      # 2 players per side

log = logging.getLogger('mms')

class NodeIdAllocator:
    """Monotonic, persisted, globally unique node ids (never reuse: is_self == node_id compare)."""
    def __init__(self, path=None, start=1000):
        self.path, self.lock = path, threading.Lock()
        self.next = start
        if path and os.path.exists(path):
            self.next = max(start, json.load(open(path)).get('next_node_id', start))

    def take(self, n):
        n = max(1, min(int(n or 1), 16))
        with self.lock:
            ids = list(range(self.next, self.next + n)); self.next += n
            if self.path:
                tmp = self.path + '.tmp'
                json.dump({'next_node_id': self.next}, open(tmp, 'w')); os.replace(tmp, self.path)
        return ids


class RatingStore:
    """Server-side hidden MMR per banapassport_am_id (team-average Elo).  Only used to order ranked
    candidates inside the same class; the game's own visible class/grade/rate live on the card server.
    Updated through POST /result (to be called by the card server's SaveVsmOnResult handler)."""
    def __init__(self, path=None, base=1500.0, k=32.0):
        self.path, self.base, self.k, self.lock = path, base, k, threading.Lock()
        self.r = {}
        if path and os.path.exists(path):
            self.r = {int(a): float(v) for a, v in json.load(open(path)).items()}

    def get(self, am):
        return self.r.get(am, self.base)

    def team(self, ams):
        ams = [a for a in ams if a]
        return sum(self.get(a) for a in ams) / len(ams) if ams else self.base

    def update(self, win_ams, lose_ams):
        with self.lock:
            rw, rl = self.team(win_ams), self.team(lose_ams)
            ew = 1.0 / (1.0 + 10 ** ((rl - rw) / 400.0))
            d = self.k * (1.0 - ew)
            for a in win_ams:
                if a: self.r[a] = self.get(a) + d
            for a in lose_ams:
                if a: self.r[a] = self.get(a) - d
            if self.path:
                tmp = self.path + '.tmp'
                json.dump({str(a): round(v, 2) for a, v in self.r.items()}, open(tmp, 'w')); os.replace(tmp, self.path)
            return d


def is_human(c):
    """Client.property[0] == "Y" marks a real player; the client builds its CPU stand-in with "N"
    (0x1407bb39f) and drops non-"Y" entries from its team table (0x1407540e0 / 0x140792760)."""
    props = c.get('property') or []
    if props:
        return props[0].get('property_value') == 'Y'
    return c.get('pcb_serial') != NPC_SERIAL


class Unit:
    """One EntryMatching = one unit: the requesting cabinet (+ its partner group for a team sortie).
    Solo sortie -> 1 slot, no groups (shuffle candidate).  Team sortie -> 2 slots that always stay on
    the same side; the partner is a human cabinet ("Y") or a CPU stand-in ("N")."""
    def __init__(self, req, now, ratings=None, rng=None):
        e = req
        self.apply_id = e.get('apply_id', 0)
        self.leader = e['myclient']['node_id']
        groups = e.get('groups', [])[:TEAM_SLOTS - 1]                 # never more than one partner per side
        self.clients = [e['myclient']] + [g['client'] for g in groups]
        self.players = [e.get('myplayer', {})] + [g.get('player', {}) for g in groups]
        self.slots = len(self.clients)
        self.team = self.slots > 1
        w = e.get('world', {})
        self.attrs = {p['attribute_id']: p['parameter'] for p in e.get('myplayer', {}).get('parameters', [])}
        self.world = w.get('world_id', 0)
        self.wname, policy = WORLDS.get(self.world, ('world%d' % self.world, 'hard'))
        self.ranked = self.world in CLASS_WORLDS
        # bucket: same game id + version + world (mode) + attr1 (TestMode wanMatchingGroupId when sent).
        self.key = (w.get('mucha_game_id', ''), w.get('version', 0), self.world, self.attrs.get(A_GROUP, 0))
        if policy in ('class', 'hard'):                                # ranked: same class; in-store: same shop ...
            self.key += (self.attrs.get(A_EXTRA, 0),)
        self.soft = self.attrs.get(A_EXTRA, 0) if policy == 'soft' else None
        self.level = self.attrs.get(A_LEVEL, 0)
        self.seq_num = e.get('seq_num', 0)
        self.create_room = e.get('create_room_flag', 1)
        self.bl_am = set(e.get('bl_banapassport_am_ids', []))
        self.bl_loc = set(e.get('bl_loc_ids', []))
        self.timeout = e.get('matching_timeout', 150)
        self.created = self.last_seen = now
        self.mmr = ratings.team(self.am_ids()) if ratings else 1500.0
        self.room = None

    def humans(self):
        return [c for c in self.clients if is_human(c)]

    def node_ids(self):
        return {c['node_id'] for c in self.humans()}

    def am_ids(self):
        return {p.get('banapassport_am_id') for p, c in zip(self.players, self.clients)
                if p.get('banapassport_am_id') and is_human(c)}

    def locs(self):
        return {c.get('loc_id') for c in self.humans()}

    def compatible(self, other, now=None):
        if self.key != other.key: return False
        if self.node_ids() & other.node_ids(): return False          # same cabinet(s)
        if self.am_ids() & other.am_ids(): return False              # same card twice
        if self.bl_am & other.am_ids() or other.bl_am & self.am_ids(): return False
        if self.bl_loc & other.locs() or other.bl_loc & self.locs(): return False
        if (self.soft is not None and other.soft is not None and self.soft != other.soft
                and (now is None or now - min(self.created, other.created) < SOFT_WAIT)):
            return False                                              # prefer like-for-like, then mix
        if self.ranked and now is not None:
            waited = now - min(self.created, other.created)          # the longer waiter widens the search
            lv, mm = 0, 0
            for t, l, m in RANKED_BANDS:
                if waited >= t: lv, mm = l, m
            if abs(self.level - other.level) > lv or abs(self.mmr - other.mmr) > mm: return False
        return True


def side_splits(units):
    """All ways to put units on two sides of <= TEAM_SLOTS slots each, both sides non-empty;
    a team unit is never split; units[0] is always on side 0."""
    n = len(units)
    for mask in range(1 << (n - 1)):
        sides = ([units[0]], [])
        for i in range(1, n):
            sides[(mask >> (i - 1)) & 1].append(units[i])
        if not sides[1]: continue
        if any(sum(u.slots for u in s) > TEAM_SLOTS for s in sides): continue
        yield sides


class Matchmaker:
    """Per-mode buckets (Unit.key).  Rooms are 2 sides x 2 slots, built from units:
         4 solos            -> shuffle: 2 random pairs (ranked: the most even split by MMR/level)
         team + 2 solos     -> fixed pair vs an instant pair of solos
         team + team        -> pair vs pair
       After FILL_AFTER seconds the oldest waiter may get a short-handed room (>= 2 humans, e.g. 1v1, 2v1);
       empty seats are expected to be CPU-controlled by the cabinets [L - open question for a live test].
       group_id is decided by the server: the client only derives "same team as the first listed client"."""
    def __init__(self, ratings=None, fill_after=FILL_AFTER, partial=True, seed=None):
        import random
        self.lock = threading.Lock()
        self.by_node = {}      # node_id -> Unit (every human node of a unit points to it)
        self.queue = []        # waiting units, FIFO
        self.rooms = {}        # room_id -> {'groups': {0: am_ids, 1: am_ids}, 'world':, 'at':}
        self.next_room = 1
        self.ratings = ratings
        self.fill_after, self.partial = fill_after, partial
        self.rng = random.Random(seed)

    def entry(self, e, now):
        t = Unit(e, now, self.ratings)
        with self.lock:
            self._sweep(now)
            # A partner cabinet may send its own entry naming the leader as its group: merge.
            for n in t.node_ids():
                old = self.by_node.get(n)
                if old and old.room is None and old.node_ids() == t.node_ids():
                    old.last_seen = now
                    for n2 in t.node_ids(): self.by_node[n2] = old
                    return SUCCESS
                if old and old.room is None:
                    self._drop(old)                                   # re-entry replaces stale wait
            for n in t.node_ids(): self.by_node[n] = t
            self.queue.append(t)
            self._try_match(now)
        log.info('entry %s unit=%s slots=%d humans=%d key=%s level=%s mmr=%.0f seq=%s mk_room=%s queue=%d',
                 t.wname, sorted(t.node_ids()), t.slots, len(t.humans()), t.key, t.level, t.mmr,
                 t.seq_num, t.create_room, len(self.queue))
        return SUCCESS

    def check(self, node_id, now):
        with self.lock:
            self._sweep(now)
            t = self.by_node.get(node_id)
            if t is None: return ERR_MATCH_NOENTRY, None
            t.last_seen = now
            if t.room is None: self._try_match(now)                   # bands widen / fill timer runs with time
            if t.room: return SUCCESS, t.room
            if now - t.created > t.timeout:
                self._drop(t); return MATCH_CANCELED, None            # game falls back (CPU battle) [M]
            return SUCCESS, None                                      # empty = keep polling

    def cancel(self, node_id):
        with self.lock:
            t = self.by_node.get(node_id)
            if t and t.room is None: self._drop(t)

    def result(self, room_id, winner_group):
        with self.lock:
            r = self.rooms.get(room_id)
        if not r or winner_group not in (0, 1): return None
        if r.get('rated'): return 0.0                                 # both cabinets report: count once
        r['rated'] = True
        return self.ratings.update(r['groups'][winner_group], r['groups'][1 - winner_group]) if self.ratings else 0.0

    # -- internals (lock held) --
    def _score(self, sides, idx, short):
        """Lower is better.  Ranked: even sides by MMR + level spread.  Casual: FIFO + soft attr2."""
        units = sides[0] + sides[1]
        order = sum(idx[id(u)] for u in units)
        if units[0].ranked:
            mm = lambda s: sum(u.mmr * u.slots for u in s) / max(1, sum(u.slots for u in s))
            lv = [u.level for u in units]
            return (abs(mm(sides[0]) - mm(sides[1])) + (max(lv) - min(lv)) * 1000, order)
        softs = {u.soft for u in units if u.soft is not None}
        return (max(0, len(softs) - 1) * 100 + order, self.rng.random())  # random split = shuffle

    def _best_room(self, anchor, pool, idx, now, short):
        import itertools
        best = None
        for r in range(1, min(3, len(pool)) + 1):
            for combo in itertools.combinations(pool, r):
                units = [anchor] + list(combo)
                slots = sum(u.slots for u in units)
                if short:
                    if slots >= 2 * TEAM_SLOTS or sum(len(u.humans()) for u in units) < 2: continue
                elif slots != 2 * TEAM_SLOTS:
                    continue
                if any(not a.compatible(b, now) for a, b in itertools.combinations(units, 2)): continue
                for sides in side_splits(units):
                    s = (-slots if short else 0,) + self._score(sides, idx, short)
                    if best is None or s < best[0]: best = (s, sides)
        return best[1] if best else None

    def _try_match(self, now):
        made = True
        while made:
            made = False
            buckets = {}
            for u in self.queue: buckets.setdefault(u.key, []).append(u)
            for units in buckets.values():
                idx = {id(u): i for i, u in enumerate(units)}
                for i, a in enumerate(units):
                    pool = [u for u in units[i + 1:] if a.compatible(u, now)][:POOL_MAX]
                    sides = self._best_room(a, pool, idx, now, short=False)
                    if not sides and self.partial and now - a.created >= self.fill_after:
                        sides = self._best_room(a, pool, idx, now, short=True)
                    if sides:
                        self._make_room(sides, now); made = True; break
                if made: break

    def _make_room(self, sides, now):
        room_id = self.next_room; self.next_room += 1
        clients = [{'group_id': g, 'client': c} for g in (0, 1) for u in sides[g] for c in u.clients]
        room = {'room_id': room_id, 'clients': clients, 'at': now}
        for g in (0, 1):
            for u in sides[g]:
                self.queue.remove(u); u.room = dict(room, apply_id=u.apply_id)
        self.rooms[room_id] = {'groups': {g: sorted(set().union(*[u.am_ids() for u in sides[g]])) for g in (0, 1)},
                               'world': sides[0][0].world, 'at': now,
                               'humans': sum(len(u.humans()) for s in sides for u in s)}
        desc = lambda s: '+'.join('%s%s' % ('T' if u.team else 'S', sorted(u.node_ids())) for u in s)
        log.info('MATCH room=%d %s %s vs %s (humans=%d/4)', room_id, sides[0][0].wname,
                 desc(sides[0]), desc(sides[1]), self.rooms[room_id]['humans'])

    def _drop(self, t):
        if t in self.queue: self.queue.remove(t)
        for n in list(self.by_node):
            if self.by_node[n] is t: del self.by_node[n]

    def _sweep(self, now):
        for t in set(self.by_node.values()):
            if t.room is None and now - t.last_seen > STALE_AFTER + t.timeout: self._drop(t)
            elif t.room and now - t.room['at'] > MATCHED_KEEP: self._drop(t)
        for rid in [r for r, v in self.rooms.items() if now - v['at'] > 3600]:
            del self.rooms[rid]


Team = Unit   # backwards-compatible name


class Mms:
    def __init__(self, nodes, mm):
        self.nodes, self.mm = nodes, mm

    def handle(self, body):
        try:
            req = decode('Request', body)
        except Exception as ex:
            log.warning('bad request body: %s', ex)
            return encode('Response', {'type': 0, 'request_id': '', 'code': ERR_REQUEST})
        rtype, rid = req.get('type', 0), req.get('request_id', '')
        resp = {'type': rtype, 'request_id': rid, 'code': SUCCESS}   # always echo type + request_id
        now = time.time()
        if rtype == PING:
            resp['ping'] = {}
        elif rtype == ISSUE_NODE_ID:
            r = req.get('issue_node_id', {})
            ids = self.nodes.take(r.get('issue_count', 1))
            resp['issue_node_id'] = {'node_id': ids}
            log.info('issue %d ids -> %s (serial len %d)', len(ids), ids, len(r.get('pcb_serial', '')))
        elif rtype == ENTRY:
            e = req.get('entry_matching')
            if not e or 'myclient' not in e:
                resp['code'] = ERR_REQUEST
            else:
                resp['code'] = self.mm.entry(e, now)
                resp['entry_matching'] = {'poling_interval': POLL_INTERVAL, 'apply_id': e.get('apply_id', 0)}
        elif rtype == CHECK:
            c = req.get('check_matching', {})
            code, room = self.mm.check(c.get('node_id', 0), now)
            resp['code'] = code
            body_ = {'clients': []}
            if room:
                body_ = {'room_id': room['room_id'], 'apply_id': room['apply_id'], 'clients': room['clients']}
            resp['check_matching'] = body_
        elif rtype == CANCEL:
            self.mm.cancel(req.get('cancel_matching', {}).get('node_id', 0))
            resp['cancel_matching'] = {}
        elif rtype == MATCHING_SETTING:
            resp['matching_setting'] = {}
        else:
            resp['code'] = ERR_REQUEST
        log.debug('type=%s code=%s', rtype, resp['code'])
        return encode('Response', resp)


def make_handler(mms, result_token=None):
    class H(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def _send(self, code, out, ctype='application/x-protobuf'):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(out)))
            self.end_headers(); self.wfile.write(out)
        def do_POST(self):
            n = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(n)
            if self.path.rstrip('/') == '/result':
                # Internal JSON hook for the card server: {"room_id": N, "winner_group": 0|1}.
                # Not a game endpoint.  Protect with --result-token in any shared deployment.
                if result_token and self.headers.get('X-Result-Token') != result_token:
                    return self._send(403, b'{"error":"forbidden"}', 'application/json')
                try:
                    j = json.loads(body or b'{}')
                    d = mms.mm.result(int(j['room_id']), int(j['winner_group']))
                except Exception as ex:
                    return self._send(400, json.dumps({'error': str(ex)}).encode(), 'application/json')
                return self._send(200 if d is not None else 404,
                                  json.dumps({'delta': d}).encode(), 'application/json')
            log.debug('POST %s rev=%s len=%d', self.path, self.headers.get('X-Nue-Protobuf-Revision'), n)
            self._send(200, mms.handle(body))           # game requires HTTP 200 for every reply
        def do_GET(self):                                # health check for humans
            self._send(200, b'mms ok\n', 'text/plain')
        def log_message(self, fmt, *a): log.debug('%s ' + fmt, self.client_address[0], *a)
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='0.0.0.0'); ap.add_argument('--port', type=int, default=5000)
    ap.add_argument('--state', default='mms_state.json'); ap.add_argument('--ratings', default='mms_ratings.json')
    ap.add_argument('--result-token', default=os.environ.get('MMS_RESULT_TOKEN'))
    ap.add_argument('--fill-after', type=float, default=FILL_AFTER,
                    help='seconds before a short-handed room (1v1, 2v1) may be formed')
    ap.add_argument('--no-partial', action='store_true', help='only ever form full 4-human-slot rooms')
    ap.add_argument('-v', action='store_true')
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO, format='%(asctime)s %(name)s %(message)s')
    mms = Mms(NodeIdAllocator(a.state), Matchmaker(RatingStore(a.ratings), a.fill_after, not a.no_partial))
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(mms, a.result_token))
    log.info('listening on http://%s:%d/mms', a.host, a.port)
    srv.serve_forever()


if __name__ == '__main__':
    main()
