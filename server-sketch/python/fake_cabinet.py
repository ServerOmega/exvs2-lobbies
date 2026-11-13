#!/usr/bin/env python3
"""Simulate cabinets talking to mms_server.py the way vsac29 does (IssueNodeId x2 -> Entry -> poll Check).
Usage: python3 fake_cabinet.py [--url http://127.0.0.1:5000/mms] [--cabinets 2] [--world 5]
Each fake cabinet enters with a CPU partner (PCB00000NPC) like a solo player would. No real card data."""
import argparse, threading, time, urllib.request, uuid
from pbwire import encode, decode

def call(url, req):
    data = encode('Request', req)
    r = urllib.request.Request(url, data=data, method='POST', headers={
        'Content-type': 'application/x-protobuf', 'X-Nue-Protobuf-Revision': '6', 'Expect': ''})
    with urllib.request.urlopen(r, timeout=10) as resp:
        assert resp.status == 200
        return decode('Response', resp.read())

def client(node, serial, loc, gip, gport):
    return {'node_id': node, 'pcb_serial': serial, 'loc_id': loc, 'pref_code': 13,
            'global_ipaddress': gip, 'global_port': gport, 'local_ipaddress': '192.168.0.10',
            'local_port': gport, 'nat_mapping_type': 1, 'nat_filtering_type': 1,
            'property': [{'property_id': 0, 'property_value': 'Y'}]}

def cabinet(url, idx, world, results):
    rid = lambda: uuid.uuid4().hex
    serial, loc = 'TESTPCB%04d' % idx, 'TESTLOC%04d' % idx
    r = call(url, {'type': 1, 'request_id': rid(), 'issue_node_id': {
        'pcb_serial': serial, 'loc_id': loc, 'issue_at': int(time.time()), 'issue_count': 2}})
    ids = r['issue_node_id']['node_id']; assert len(ids) >= 2, ids
    me, npc = ids[0], ids[1]
    e = {'apply_id': 1, 'myclient': client(me, serial, loc, '203.0.113.%d' % idx, 40000 + idx),
         'myplayer': {'banapassport_am_id': 1000 + idx, 'parameters': []},
         'world': {'mucha_game_id': 'GIB1', 'version': 1, 'world_id': world},
         'groups': [{'client': client(npc, 'PCB00000NPC', loc, '0.0.0.0', 0), 'player': {'banapassport_am_id': 0}}],
         'matching_timeout': 90 if world == 5 else 150, 'seq_num': 0, 'create_room_flag': 1,
         'entry_at': int(time.time())}
    r = call(url, {'type': 2, 'request_id': rid(), 'entry_matching': e})
    assert r['code'] == 0, r
    poll = r['entry_matching']['poling_interval']
    for _ in range(40):
        time.sleep(min(poll, 1))
        r = call(url, {'type': 3, 'request_id': rid(), 'check_matching': {'node_id': me, 'check_at': int(time.time())}})
        cl = r.get('check_matching', {}).get('clients', [])
        if r['code'] != 0 or cl:
            results[idx] = (me, r['code'], r.get('check_matching', {}).get('room_id'),
                            [(c['group_id'], c['client']['node_id'], c['client']['pcb_serial']) for c in cl])
            return
    results[idx] = (me, 'timeout', None, [])

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:5000/mms')
    ap.add_argument('--cabinets', type=int, default=2); ap.add_argument('--world', type=lambda x: int(x, 0), default=5)
    a = ap.parse_args()
    print('ping:', call(a.url, {'type': 0, 'request_id': 'p1', 'ping': {}}))
    res = {}
    ts = [threading.Thread(target=cabinet, args=(a.url, i + 1, a.world, res)) for i in range(a.cabinets)]
    [t.start() for t in ts]; [t.join() for t in ts]
    for k in sorted(res): print('cabinet', k, '-> node %s code %s room %s clients %s' % res[k])
