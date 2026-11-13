#!/usr/bin/env python3
"""Simulate cabinets talking to mms_server.py the way vsac29 does (IssueNodeId x2 -> Entry -> poll Check).
Usage: python3 fake_cabinet.py [--url http://127.0.0.1:5000/mms] [--cabinets 2] [--world 5]
       python3 fake_cabinet.py --ranked "2:3,2:5,3:3,3:3" [--team] [--report]
         ranked = Class Match G: one cabinet per "class:level" item, world 13 (solo) or 14 (--team);
         --report posts a fake result for each room to /result (what the card server hook would do).
       python3 fake_cabinet.py --units "S,S,S,S" --world 23      casual: S = solo sortie (no groups, shuffled),
         T = team sortie with a human partner cabinet (group property "Y"; the partner polls too),
         TN = team sortie with a CPU stand-in partner (PCB00000NPC, property "N").
Without --units/--ranked every cabinet is a team-sortie entry with a CPU partner (old behaviour). No real card data.
EXPERIMENTAL: the message shapes follow static analysis of the exe, not a live capture."""
import argparse, json, threading, time, urllib.request, uuid
from pbwire import encode, decode

def call(url, req):
    data = encode('Request', req)
    r = urllib.request.Request(url, data=data, method='POST', headers={
        'Content-type': 'application/x-protobuf', 'X-Nue-Protobuf-Revision': '6', 'Expect': ''})
    with urllib.request.urlopen(r, timeout=10) as resp:
        assert resp.status == 200
        return decode('Response', resp.read())

def client(node, serial, loc, gip, gport, human=True):
    return {'node_id': node, 'pcb_serial': serial, 'loc_id': loc, 'pref_code': 13,
            'global_ipaddress': gip, 'global_port': gport, 'local_ipaddress': '192.168.0.10',
            'local_port': gport, 'nat_mapping_type': 1, 'nat_filtering_type': 1,
            'property': [{'property_id': 0, 'property_value': 'Y' if human else 'N'}]}

def issue(url, serial, loc, n=2):
    r = call(url, {'type': 1, 'request_id': uuid.uuid4().hex, 'issue_node_id': {
        'pcb_serial': serial, 'loc_id': loc, 'issue_at': int(time.time()), 'issue_count': n}})
    ids = r['issue_node_id']['node_id']; assert len(ids) >= n, ids
    return ids

def poll(url, me, results, key, tries=120):
    for _ in range(tries):
        time.sleep(1)
        r = call(url, {'type': 3, 'request_id': uuid.uuid4().hex,
                       'check_matching': {'node_id': me, 'check_at': int(time.time())}})
        cl = r.get('check_matching', {}).get('clients', [])
        if r['code'] != 0 or cl:
            results[key] = (me, r['code'], r.get('check_matching', {}).get('room_id'),
                            [(c['group_id'], c['client']['node_id'], c['client']['pcb_serial'],
                              c['client']['property'][0]['property_value']) for c in cl])
            return
    results[key] = (me, 'timeout', None, [])

def cabinet(url, idx, world, results, params=(), seq=0, mk_room=1, sortie='TN', loc=None):
    """sortie: 'S' solo (no groups), 'T' team + human partner cabinet, 'TN' team + CPU stand-in."""
    serial, loc = 'TESTPCB%04d' % idx, loc or 'TESTLOC%04d' % idx
    me, npc = issue(url, serial, loc)
    groups = []
    if sortie == 'TN':
        groups = [{'client': client(npc, 'PCB00000NPC', loc, '0.0.0.0', 0, human=False), 'player': {'banapassport_am_id': 0}}]
    elif sortie == 'T':
        pser = 'TESTPCB%04d' % (idx + 500)
        partner = issue(url, pser, loc)[0]
        groups = [{'client': client(partner, pser, loc, '203.0.113.%d' % (idx + 100), 41000 + idx),
                   'player': {'banapassport_am_id': 1500 + idx}}]
        threading.Thread(target=poll, args=(url, partner, results, '%dp' % idx)).start()
    e = {'apply_id': 1, 'myclient': client(me, serial, loc, '203.0.113.%d' % idx, 40000 + idx),
         'myplayer': {'banapassport_am_id': 1000 + idx,
                      'parameters': [{'attribute_id': k, 'parameter': v} for k, v in params]},
         'world': {'mucha_game_id': 'GIB1', 'version': 1, 'world_id': world},
         'groups': groups,
         'matching_timeout': 90 if world == 5 else 150, 'seq_num': seq, 'create_room_flag': mk_room,
         'entry_at': int(time.time())}
    r = call(url, {'type': 2, 'request_id': uuid.uuid4().hex, 'entry_matching': e})
    assert r['code'] == 0, r
    poll(url, me, results, idx)

def report(url, room_id, winner):
    base = url.rsplit('/', 1)[0]
    r = urllib.request.Request(base + '/result', data=json.dumps({'room_id': room_id, 'winner_group': winner}).encode(),
                               method='POST', headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.loads(resp.read())

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:5000/mms')
    ap.add_argument('--cabinets', type=int, default=2); ap.add_argument('--world', type=lambda x: int(x, 0), default=5)
    ap.add_argument('--ranked', help='comma list of class:level, one per cabinet (Class Match G)')
    ap.add_argument('--team', action='store_true', help='ranked team world 14 instead of solo world 13')
    ap.add_argument('--units', help='casual: comma list of S / T / TN, one entry per item (see top)')
    ap.add_argument('--attr2', type=int, default=0, help='casual: attr2 value sent by every cabinet')
    ap.add_argument('--same-loc', action='store_true', help='all cabinets in one shop (in-store worlds 15/16)')
    ap.add_argument('--stagger', type=float, default=0.0, help='seconds between cabinet starts')
    ap.add_argument('--report', action='store_true', help='post a fake result per room (group 0 wins)')
    a = ap.parse_args()
    print('ping:', call(a.url, {'type': 0, 'request_id': 'p1', 'ping': {}}))
    res, specs = {}, []
    if a.ranked:
        world = 14 if a.team else 13
        for i, item in enumerate(a.ranked.split(',')):
            cls, lvl = (int(x) for x in item.split(':'))
            # attr1 group 0, attr2 class, attr3 LAN/subnet flag, attr4 matching level; seq/mk_room as ClassMatchingRequest
            specs.append((i + 1, world, [(1, 0), (2, cls), (3, 0), (4, lvl)], 1, 1, 'S' if not a.team else 'TN'))
    elif a.units:
        specs = [(i + 1, a.world, [(1, 0), (2, a.attr2), (3, 0)], 1, 1, s.strip().upper())
                 for i, s in enumerate(a.units.split(','))]
    else:
        specs = [(i + 1, a.world, [], 0, 1, 'TN') for i in range(a.cabinets)]
    ts = []
    for idx, world, params, seq, mk, sortie in specs:
        t = threading.Thread(target=cabinet, args=(a.url, idx, world, res, params, seq, mk, sortie,
                                                   'TESTLOC0001' if a.same_loc else None)); t.start(); ts.append(t)
        time.sleep(a.stagger)
    [t.join() for t in ts]
    rooms = set()
    time.sleep(1.5)                                  # partner pollers
    for k in sorted(res, key=str):
        print('cabinet', k, '-> node %s code %s room %s clients %s' % res[k])
        if res[k][2]: rooms.add(res[k][2])
    if a.report:
        for rm in sorted(rooms):
            print('result room', rm, '->', report(a.url, rm, 0), '| again ->', report(a.url, rm, 0))
