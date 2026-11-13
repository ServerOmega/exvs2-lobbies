#!/usr/bin/env python3
"""Prototype universal EXVS2 IB matchmaking server (nue.protocol.mms over HTTP POST).

Stdlib only.  Run:  python3 mms_server.py --port 5000 [--state state.json] [-v]
Point the card server's RegisterPcb SRV_MATCH uri at  http://<this-host>:5000/mms
(the game uses the uri verbatim as the URL and ignores the port field).

Protocol facts this follows (see analysis/matchmaking.md):
  * body = serialized nue.protocol.mms.Request; reply must be HTTP 200 + serialized Response
    with type/request_id/code always present (proto2 required fields).
  * IssueNodeId: game asks issue_count=2 and rejects replies with fewer node_ids.
  * EntryMatching: game reads only poling_interval (seconds).
  * CheckMatching: code 0 + empty clients = "keep polling"; when matched return room_id and
    ALL clients (incl. the requester and CPU stand-ins), group_id = team (0/1).
  * CancelMatching: reply ignored by the game.
"""
import argparse, json, logging, os, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pbwire import encode, decode

PING, ISSUE_NODE_ID, ENTRY, CHECK, CANCEL, MATCHING_SETTING = 0, 1, 2, 3, 4, 100
SUCCESS, MATCH_CANCELED, PROCESS_WAIT = 0, 1, 2
ERR_REQUEST, ERR_SERVER, ERR_MAINTENANCE, ERR_MATCH_NOENTRY = 100, 101, 102, 103
ERR_NODEID, ERR_MATCH_CONDITION, ERR_DUPLICATE_ENTRY = 200, 201, 202
NPC_SERIAL = 'PCB00000NPC'          # dummy CPU partner the game puts in groups[0]
POLL_INTERVAL = 3                   # PROCESS_WAIT_POLING_INTERVAL from the proto
STALE_AFTER = 20                    # s without CheckMatching -> drop entry
MATCHED_KEEP = 60                   # s to keep a finished room for late polls

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


class Team:
    """One EntryMatching = one side: the requesting cabinet + its groups[] (partner or CPU)."""
    def __init__(self, req, now):
        e = req
        self.apply_id = e.get('apply_id', 0)
        self.leader = e['myclient']['node_id']
        self.clients = [e['myclient']] + [g['client'] for g in e.get('groups', [])]
        self.players = [e.get('myplayer', {})] + [g.get('player', {}) for g in e.get('groups', [])]
        w = e.get('world', {})
        attrs = {p['attribute_id']: p['parameter'] for p in e.get('myplayer', {}).get('parameters', [])}
        # bucket: same game id + version + world (mode). attr 1 = TestMode wanMatchingGroupId when sent
        self.key = (w.get('mucha_game_id', ''), w.get('version', 0), w.get('world_id', 0), attrs.get(1, 0))
        self.bl_am = set(e.get('bl_banapassport_am_ids', []))
        self.bl_loc = set(e.get('bl_loc_ids', []))
        self.timeout = e.get('matching_timeout', 150)
        self.created = self.last_seen = now
        self.room = None

    def humans(self):
        return [c for c in self.clients if c.get('pcb_serial') != NPC_SERIAL]

    def node_ids(self):
        return {c['node_id'] for c in self.humans()}

    def am_ids(self):
        return {p.get('banapassport_am_id') for p in self.players if p.get('banapassport_am_id')}

    def locs(self):
        return {c.get('loc_id') for c in self.humans()}

    def compatible(self, other):
        if self.key != other.key: return False
        if self.node_ids() & other.node_ids(): return False          # same cabinet(s)
        if self.bl_am & other.am_ids() or other.bl_am & self.am_ids(): return False
        if self.bl_loc & other.locs() or other.bl_loc & self.locs(): return False
        return True


class Matchmaker:
    def __init__(self, allow_same_loc=True):
        self.lock = threading.Lock()
        self.by_node = {}      # node_id -> Team (every human node of a team points to it)
        self.queue = []        # waiting teams, FIFO
        self.next_room = 1
        self.allow_same_loc = allow_same_loc

    def entry(self, e, now):
        t = Team(e, now)
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
        log.info('entry team=%s key=%s queue=%d', sorted(t.node_ids()), t.key, len(self.queue))
        return SUCCESS

    def check(self, node_id, now):
        with self.lock:
            self._sweep(now)
            t = self.by_node.get(node_id)
            if t is None: return ERR_MATCH_NOENTRY, None
            t.last_seen = now
            if t.room: return SUCCESS, t.room
            if now - t.created > t.timeout:
                self._drop(t); return MATCH_CANCELED, None
            return SUCCESS, None                                      # empty = keep polling

    def cancel(self, node_id):
        with self.lock:
            t = self.by_node.get(node_id)
            if t and t.room is None: self._drop(t)

    # -- internals (lock held) --
    def _try_match(self, now):
        i = 0
        while i < len(self.queue):
            a = self.queue[i]
            j = next((j for j in range(i + 1, len(self.queue)) if a.compatible(self.queue[j])), None)
            if j is None: i += 1; continue
            b = self.queue.pop(j); self.queue.pop(i)
            room_id = self.next_room; self.next_room += 1
            clients = [{'group_id': 0, 'client': c} for c in a.clients] + \
                      [{'group_id': 1, 'client': c} for c in b.clients]
            room = {'room_id': room_id, 'clients': clients, 'at': now}
            a.room = dict(room, apply_id=a.apply_id); b.room = dict(room, apply_id=b.apply_id)
            log.info('MATCH room=%d %s vs %s', room_id, sorted(a.node_ids()), sorted(b.node_ids()))

    def _drop(self, t):
        if t in self.queue: self.queue.remove(t)
        for n in list(self.by_node):
            if self.by_node[n] is t: del self.by_node[n]

    def _sweep(self, now):
        for t in set(self.by_node.values()):
            if t.room is None and now - t.last_seen > STALE_AFTER + t.timeout: self._drop(t)
            elif t.room and now - t.room['at'] > MATCHED_KEEP: self._drop(t)


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


def make_handler(mms):
    class H(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def do_POST(self):
            n = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(n)
            log.debug('POST %s rev=%s len=%d', self.path, self.headers.get('X-Nue-Protobuf-Revision'), n)
            out = mms.handle(body)
            self.send_response(200)                      # game requires HTTP 200 for every reply
            self.send_header('Content-Type', 'application/x-protobuf')
            self.send_header('Content-Length', str(len(out)))
            self.end_headers(); self.wfile.write(out)
        def do_GET(self):                                # health check for humans
            out = b'mms ok\n'
            self.send_response(200); self.send_header('Content-Length', str(len(out)))
            self.end_headers(); self.wfile.write(out)
        def log_message(self, fmt, *a): log.debug('%s ' + fmt, self.client_address[0], *a)
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='0.0.0.0'); ap.add_argument('--port', type=int, default=5000)
    ap.add_argument('--state', default='mms_state.json'); ap.add_argument('-v', action='store_true')
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO, format='%(asctime)s %(name)s %(message)s')
    mms = Mms(NodeIdAllocator(a.state), Matchmaker())
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(mms))
    log.info('listening on http://%s:%d/mms', a.host, a.port)
    srv.serve_forever()


if __name__ == '__main__':
    main()
