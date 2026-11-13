#!/usr/bin/env python3
"""LM / non-LM / many-LM mix against ONE matchmaking server (analysis/lm-and-online.md).

Fake cabinets only (fake serials, fake card ids, documentation / overlay IPs). Groups:
  LM-A   one store (one LM): 4 cabinets, one public IP, LAN 192.168.10.x, store serials 0001..0004;
         A1+A2 enter as an in-store pair (team sortie with a human partner), A3 / A4 solo
  HOME   4 players without an LM: POC defaults everywhere (serial 0001, loc JPN1, local 192.168.1.10),
         each behind its own home router (own public IP)
  LM-BCDE 4 different stores, one cabinet each: every store's first terminal = serial 0001
  RADMIN (--overlay) 2 players whose STUN result is a Radmin overlay IP (26.x): can't reach internet players
Everyone picks the same mode (default world 23 = Mix Match, solo + team allowed).

--case instore: 3 stores (4 + 2 + 2 cabinets), ALL sending the POC place id JPN1 (same shop code), in in-store
match (world 15). Expected: rooms only ever contain one store. Run it again with --world 23 to see the same
cabinets mix across stores in a normal online mode.

  python3 lm_mix.py --url http://127.0.0.1:28080/match        # C# card server (built-in MMS)
  python3 lm_mix.py --url http://127.0.0.1:5000/mms           # mms_server.py
Prints each room (who, team, realm, which address each pair dials) and checks the invariants.
"""
import argparse, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loadtest as L

RADMIN = ('26.',)

def realm(ip):
    return 'radmin' if ip.startswith(RADMIN) else 'lan' if ip.startswith(('10.', '192.168.', '127.')) else 'internet'

def roster(overlay):
    P = []   # (tag, serial, loc, global, local, partner_tag or None)
    for i in range(1, 5):
        P.append(('LM-A/%d' % i, 'FAKEPCB000%d' % i, 'STOREA', '203.0.113.10', '192.168.10.%d' % i, None))
    for i in range(1, 5):
        P.append(('HOME/%d' % i, 'FAKEPCB0001', 'JPN1', '198.51.100.%d' % i, '192.168.1.10', None))
    for k, s in enumerate('BCDE'):
        P.append(('LM-%s/1' % s, 'FAKEPCB0001', 'STORE' + s, '192.0.2.%d' % (20 + 10 * k), '192.168.%d.1' % (20 + 10 * k), None))
    if overlay:
        for i in range(1, 3):
            P.append(('RADMIN/%d' % i, 'FAKEPCB0001', 'JPN1', '26.0.0.%d' % (4 + i), '26.0.0.%d' % (4 + i), None))
    return P

def roster_instore():
    P = []
    for s, n, g in (('A', 4, '203.0.113.10'), ('F', 2, '198.51.100.60'), ('G', 2, '198.51.100.70')):
        for i in range(1, n + 1):
            P.append(('LM-%s/%d' % (s, i), 'FAKEPCB000%d' % i, 'JPN1', g, '192.168.%d.%d' % (ord(s), i), None))
    return P

def cl(node, p, port=48001):
    tag, serial, loc, g, l, _ = p
    c = L.client(node, serial, loc, g, port)
    c['local_ipaddress'] = l
    return c

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--url', default='http://127.0.0.1:28080/match')
    ap.add_argument('--case', choices=['mix', 'instore'], default='mix')
    ap.add_argument('--world', type=int, default=None, help='default 23 (mix) / 15 (instore)')
    ap.add_argument('--overlay', action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument('--interleave', action=argparse.BooleanOptionalAction, default=True,
                    help='arrive round-robin across groups (A1, HOME/1, LM-B, A3, HOME/2, ...) instead of group by group')
    ap.add_argument('--wait', type=float, default=60, help='seconds each cabinet polls before giving up')
    a = ap.parse_args()
    if a.world is None: a.world = 15 if a.case == 'instore' else 23
    P = roster_instore() if a.case == 'instore' else roster(a.overlay)
    st = L.Stats(); by_tag = {p[0]: p for p in P}
    attr2 = L.shop_hash('JPN1') if a.world in (15, 16) else 0      # in-store: shop code, the same for every POC install
    nodes, res, lock = {}, {}, threading.Lock()

    def issue(conn, p):
        r = conn.call({'type': L.ISSUE, 'request_id': L.rid(), 'issue_node_id': {
            'pcb_serial': p[1], 'loc_id': p[2], 'issue_at': int(time.time()), 'issue_count': 2}}, 'issue')
        return r['issue_node_id']['node_id'][0]

    def poll(conn, tag, node):
        t0 = time.time()
        while time.time() - t0 < a.wait:
            time.sleep(1)
            r = conn.call({'type': L.CHECK, 'request_id': L.rid(), 'check_matching': {'node_id': node, 'check_at': int(time.time())}}, 'check')
            if r is None: continue
            cm = r.get('check_matching') or {}
            if r.get('code') == L.SUCCESS and cm.get('clients'):
                with lock: res[tag] = ('room', cm['room_id'], cm['clients']); return
            if r.get('code') != L.SUCCESS:
                with lock: res[tag] = ('code', r.get('code'), None); return
        with lock: res[tag] = ('timeout', None, None)

    def run(p, partner=None):
        conn = L.Conn(a.url, st)
        me = issue(conn, p); nodes[p[0]] = me
        groups = []
        if partner:
            pc = L.Conn(a.url, st); pn = issue(pc, partner); nodes[partner[0]] = pn
            groups = [{'client': cl(pn, partner), 'player': {'banapassport_am_id': 8000 + pn}}]
            threading.Thread(target=poll, args=(pc, partner[0], pn)).start()   # the partner cabinet only polls
        e = {'apply_id': me, 'myclient': cl(me, p), 'myplayer': {'banapassport_am_id': 7000 + me, 'parameters': [
                {'attribute_id': 1, 'parameter': 0}, {'attribute_id': 2, 'parameter': attr2}, {'attribute_id': 3, 'parameter': 0}]},
             'world': {'mucha_game_id': 'GIB1', 'version': 1, 'world_id': a.world}, 'groups': groups,
             'matching_timeout': int(a.wait) + 30, 'seq_num': 1, 'create_room_flag': 1, 'entry_at': int(time.time())}
        r = conn.call({'type': L.ENTRY, 'request_id': L.rid(), 'entry_matching': e}, 'entry')
        if not r or r.get('code') != L.SUCCESS:
            with lock: res[p[0]] = ('entry-fail', (r or {}).get('code'), None); return
        poll(conn, p[0], me)

    order = list(P)
    if a.interleave:
        groups = {}
        for p in P: groups.setdefault(p[0].split('/')[0] if a.case == 'instore' or p[0].startswith(('LM-A', 'HOME', 'RADMIN')) else 'LM-x', []).append(p)
        order = [g[i] for i in range(max(map(len, groups.values()))) for g in groups.values() if i < len(g)]
    ts = []
    for p in order:
        pair = a.case == 'mix'
        if pair and p[0] == 'LM-A/2': continue                          # entered by A1 as its partner
        ts.append(threading.Thread(target=run, args=(p, by_tag['LM-A/2'] if pair and p[0] == 'LM-A/1' else None)))
    for t in ts: t.start(); time.sleep(0.15)
    for t in ts: t.join()
    while len(res) < len(P): time.sleep(0.2)

    tag_of = {v: k for k, v in nodes.items()}
    rooms, ok = {}, True
    for tag, (kind, val, clients) in res.items():
        if kind == 'room': rooms.setdefault(val, clients)
        else: print('NOT MATCHED %-9s %s %s' % (tag, kind, val)); ok = False
    for rid, clients in sorted(rooms.items()):
        hs = [c for c in clients if c['client']['property'][0]['property_value'] == 'Y']
        print('room %d (%d humans)' % (rid, len(hs)))
        for c in hs:
            t = tag_of.get(c['client']['node_id'], '?'); p = by_tag[t]
            print('   team %d  %-9s global=%-13s local=%-13s realm=%s' % (c['group_id'], t, p[3], p[4], realm(p[3])))
        for i in range(len(hs)):
            for j in range(i + 1, len(hs)):
                x, y = hs[i]['client'], hs[j]['client']
                how = 'LAN (same public IP -> local addr)' if x['global_ipaddress'] == y['global_ipaddress'] else 'direct (global addr)'
                print('      %s <-> %s : %s' % (tag_of[x['node_id']], tag_of[y['node_id']], how))
        realms = {realm(c['client']['global_ipaddress']) for c in hs}
        if len(realms) > 1: print('   !! cross-realm room'); ok = False
        stores = {tag_of[c['client']['node_id']].split('/')[0] for c in hs}
        if a.world in (15, 16) and len(stores) > 1: print('   !! in-store room with several stores'); ok = False
        if a.world in (15, 16): print('   stores in room: %s' % ', '.join(sorted(stores)))
        g = {tag_of[c['client']['node_id']]: c['group_id'] for c in hs}
        if a.case == 'mix' and 'LM-A/1' in g and g.get('LM-A/2') != g['LM-A/1']: print('   !! store pair split'); ok = False
    print('matched %d/%d players in %d rooms; invariants %s; http errors %s' % (
        sum(1 for v in res.values() if v[0] == 'room'), len(P), len(rooms), 'OK' if ok else 'FAILED', dict(st.errors) or 0))
    return 0 if ok else 1

if __name__ == '__main__':
    sys.exit(main())
