#!/usr/bin/env python3
"""End-to-end online tag test against the patched C# server (card server + WebUI API + in-process MMS).
EXPERIMENTAL, fake cabinets and FAKE cards only (TESTTAG... access codes; writes them into the server DB).

  1. Card / WebUI: 4 fake cards; A invites B and C invites D with the partner's user id + invitation code
     (/ui/team/preCreateTeam), wrong code / self / reused one-time code are refused; LoadCard (strict proto2 parse,
     like the cabinet) lists the team in mobile_user_group.tag_teams (36) on BOTH cards with partner_id = partner's
     pilot id.
  2. MMS world 5: each cabinet sends what CAcSeqWanTagEntry sends (attr2 = min(own pilot id, partner_id), am_id = own
     pilot id, timeout 90): A+B and C+D each get a 2-client room (both group 0, leader = lower id first, same list for
     both); two strangers with other keys never pair and get MATCH_CANCELED at their (short) timeout.
  3. The two leaders send a Mix team entry (world 23, groups=[partner "Y"]); the members only poll -> one 2v2 room,
     each tag pair on its own side.
  4. Recruit: two casual recruits (21) pair; ranked recruits (22) of class 2 and 3 do not.

Needs the generated game_server_nue_pb2 on PYTHONPATH (python -m grpc_tools.protoc -I analysis/proto/from_exe
--python_out=DIR game_server_nue.proto) and the protobuf package.
Usage: online_tag_e2e.py --url http://127.0.0.1:28080/   (server started with CardServerConfig__OnlineMatching__Enabled=true)
"""
import argparse, json, os, sys, time, urllib.request, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loadtest as L
import game_server_nue_pb2 as pb

RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append((name, bool(ok)))
    print('[%s] %s %s' % ('PASS' if ok else 'FAIL', name, detail), flush=True)
    return ok


def post_pb(url, q, strict=True):
    req = urllib.request.Request(url, data=q.SerializePartialToString(), method='POST', headers={
        'Content-Type': 'application/x-protobuf', 'X-Nue-Protobuf-Revision': '141'})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = r.read()
    out = pb.Response()
    (out.ParseFromString if strict else out.MergeFromString)(data)   # strict = missing required field raises
    return out


def base(method, serial='TAGPCB0001'):
    q = pb.Request(); q.type = method; q.request_id = uuid.uuid4().hex
    q.pcb_serial = serial; q.loc_id = 'TAGLOC0001'; q.token = ''
    return q


def json_call(url, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url.rstrip('/') + path, data=data, method='POST' if body is not None else 'GET',
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b'null')


class Card:
    def __init__(self, url, n, run):
        self.url, self.access, self.chip = url, 'TESTTAG%05d%08d' % (run % 100000, n), 'TESTTAGCHIP%04d%04d' % (run % 10000, n)
        p = self.pre_load()
        if p.is_new_card:
            q = base(pb.MTHD_REGISTER_CARD)
            r = q.register_card; r.session_id = p.session_id; r.is_card = True
            r.access_code = self.access; r.chip_id = self.chip; r.mucha_country_code = 'JPN'
            post_pb(url, q, strict=False)
            p = self.pre_load()
        self.session, self.pilot = p.session_id, p.load_player.pilot_id

    def pre_load(self):
        q = base(pb.MTHD_PRE_LOAD_CARD)
        p = q.pre_load_card; p.is_card = True; p.access_code = self.access; p.chip_id = self.chip; p.mucha_country_code = 'JPN'
        return post_pb(self.url, q, strict=False).pre_load_card

    def load_card(self):
        q = base(pb.MTHD_LOAD_CARD)
        q.load_card.session_id = self.session; q.load_card.pilot_id = self.pilot
        return post_pb(self.url, q, strict=True).load_card     # strict, like the cabinet

    def teams(self):
        return json_call(self.url, '/ui/team/getTeams/%s/%s' % (self.access, self.chip))

    def invite(self, partner_id, code):
        return json_call(self.url, '/ui/team/preCreateTeam', {
            'accessCode': self.access, 'chipId': self.chip, 'partnerCardId': partner_id, 'partnerToken': code})


class Cab:
    def __init__(self, mms, name):
        self.conn = L.Conn(mms, L.Stats()); self.name = name
        self.serial, self.loc = 'TAGPCB%s%04d' % (name, os.getpid() % 10000), 'TAGLOC' + name
        r = self.conn.call({'type': L.ISSUE, 'request_id': L.rid(), 'issue_node_id': {
            'pcb_serial': self.serial, 'loc_id': self.loc, 'issue_at': int(time.time()), 'issue_count': 2}}, 'issue')
        self.node = r['issue_node_id']['node_id'][0]; self.apply = 1
        self.ip = '198.18.77.%d' % (10 + len(name) + ord(name[0]) % 200)

    def me(self):
        return L.client(self.node, self.serial, self.loc, self.ip, 40000)

    def entry(self, world, attr2, am, timeout=90, groups=(), new_apply=True):
        if new_apply: self.apply += 1
        e = {'apply_id': self.apply, 'myclient': self.me(),
             'myplayer': {'banapassport_am_id': am, 'parameters': [
                 {'attribute_id': 1, 'parameter': 0}, {'attribute_id': 2, 'parameter': attr2},
                 {'attribute_id': 3, 'parameter': 0}, {'attribute_id': 4, 'parameter': 0}]},
             'world': {'mucha_game_id': 'GIB1', 'version': 1, 'world_id': world}, 'groups': list(groups),
             'matching_timeout': timeout, 'seq_num': 1, 'create_room_flag': 1, 'entry_at': int(time.time())}
        return self.conn.call({'type': L.ENTRY, 'request_id': L.rid(), 'entry_matching': e}, 'entry').get('code', 0)

    def check(self):
        r = self.conn.call({'type': L.CHECK, 'request_id': L.rid(), 'check_matching': {
            'node_id': self.node, 'check_at': int(time.time())}}, 'check')
        cm = r.get('check_matching') or {}
        return r.get('code', 0), cm.get('room_id'), [(c.get('group_id', 0), c['client']['node_id']) for c in cm.get('clients', [])]

    def wait(self, secs):
        t0 = time.time()
        while time.time() - t0 < secs:
            code, room, cl = self.check()
            if code != 0 or cl: return code, room, cl
            time.sleep(1)
        return self.check()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:28080/')
    a = ap.parse_args()
    run = int(time.time())

    # ---------------------------------------------------------------- 1. card server + WebUI invite
    A, B, C, D = (Card(a.url, i, run) for i in range(1, 5))
    print('pilot ids: A=%d B=%d C=%d D=%d' % (A.pilot, B.pilot, C.pilot, D.pilot))
    tb = B.teams()
    code_b = tb['distinctTeamFormationToken']
    check('WebUI shows an invitation code', len(code_b) == 16)
    check('wrong code refused', not A.invite(B.pilot, 'x' * 16)['success'])
    check('team with yourself refused', not A.invite(A.pilot, A.teams()['distinctTeamFormationToken'])['success'])
    r = A.invite(B.pilot, code_b)
    team_ab = r['newTeamId']
    check('A invites B with B\'s id + code', r['success'] and team_ab > 0, 'team %s' % team_ab)
    check('second team A+B refused', not A.invite(B.pilot, B.teams()['distinctTeamFormationToken'])['success'])
    check('B\'s code is one-time (C cannot reuse it)', not C.invite(B.pilot, code_b)['success'])
    check('B got a new code', B.teams()['distinctTeamFormationToken'] != code_b)
    r = C.invite(D.pilot, D.teams()['distinctTeamFormationToken'])
    team_cd = r['newTeamId']
    check('C invites D', r['success'] and team_cd > 0)
    check('B sees the team in its WebUI', any(t['id'] == team_ab for t in B.teams()['teams']))

    partner_of = {}
    for me, other, team in ((A, B, team_ab), (B, A, team_ab), (C, D, team_cd), (D, C, team_cd)):
        try:
            lc = me.load_card()
        except Exception as ex:
            check('LoadCard strict parse (pilot %d)' % me.pilot, False, repr(ex)); continue
        tags = list(lc.mobile_user_group.tag_teams)
        ok = len(tags) == 1 and tags[0].id == team and tags[0].partner_id == other.pilot and tags[0].tag_status == 0
        check('LoadCard tag_teams of pilot %d lists team %d with partner_id %d' % (me.pilot, team, other.pilot), ok,
              str([(t.id, t.partner_id, t.tag_status, t.partner_name) for t in tags]))
        partner_of[me.pilot] = tags[0].partner_id if tags else 0

    # ---------------------------------------------------------------- 2. world 5 pairing
    mms = post_pb(a.url, base(pb.MTHD_REGISTER_PCB)).register_pcb
    match = [s.uri for s in mms.server_info if s.server_type == pb.SRV_MATCH][-1]
    print('MMS', match)
    cab = {n: Cab(match, n) for n in ('A', 'B', 'C', 'D', 'X', 'Y')}
    pilots = {'A': A.pilot, 'B': B.pilot, 'C': C.pilot, 'D': D.pilot}
    key = {n: min(pilots[n], partner_of.get(pilots[n], 0)) for n in pilots}
    check('both partners derive the same pair key', key['A'] == key['B'] and key['C'] == key['D'] and key['A'] != key['C'], str(key))
    cab['X'].entry(5, 900001, 900002, timeout=6)       # strangers: other keys, short timeout
    cab['Y'].entry(5, 900003, 900004, timeout=6)
    for n in ('A', 'C', 'B', 'D'):
        check('entry %s world 5 key %d' % (n, key[n]), cab[n].entry(5, key[n], pilots[n]) == 0)
    res = {n: cab[n].wait(10) for n in ('A', 'B', 'C', 'D')}
    for x, y in (('A', 'B'), ('C', 'D')):
        rx, ry = res[x], res[y]
        lead = x if pilots[x] < pilots[y] else y
        ok = rx[1] and rx[1] == ry[1] and rx[2] == ry[2] and len(rx[2]) == 2 and all(g == 0 for g, _ in rx[2]) \
            and {n for _, n in rx[2]} == {cab[x].node, cab[y].node} and rx[2][0][1] == cab[lead].node
        check('tag pair %s+%s: one 2-client room, both group 0, same order, leader %s first' % (x, y, lead), ok, str((rx, ry)))
    check('the two pairs got different rooms', res['A'][1] != res['C'][1])
    rx, ry = cab['X'].wait(10), cab['Y'].wait(1)
    check('mismatched keys never pair; MATCH_CANCELED at the cabinet timeout', rx[0] == 1 and ry[0] == 1 and not rx[2], str((rx, ry)))

    # ---------------------------------------------------------------- 3. leaders' team entries -> 2v2
    def team(leader, member):
        g = [{'client': cab[member].me(), 'player': {'banapassport_am_id': pilots[member]}}]
        return cab[leader].entry(23, 0, pilots[leader], timeout=150, groups=g)
    l1, m1 = ('A', 'B') if pilots['A'] < pilots['B'] else ('B', 'A')
    l2, m2 = ('C', 'D') if pilots['C'] < pilots['D'] else ('D', 'C')
    check('leader %s team entry' % l1, team(l1, m1) == 0)
    code, room, cl = cab[m1].check()
    check('member %s polls: team search still waiting (not the old pair room)' % m1, code == 0 and not cl, str((code, room, cl)))
    check('leader %s team entry' % l2, team(l2, m2) == 0)
    rr = {n: cab[n].wait(10) for n in ('A', 'B', 'C', 'D')}
    rooms = {r[1] for r in rr.values()}
    cl = rr['A'][2]; grp = {node: g for g, node in cl}
    ok = len(rooms) == 1 and None not in rooms and len(cl) == 4 and grp.get(cab['A'].node) == grp.get(cab['B'].node) \
        and grp.get(cab['C'].node) == grp.get(cab['D'].node) and grp.get(cab['A'].node) != grp.get(cab['C'].node)
    check('the two tag teams match each other 2v2, each pair on one side', ok, str(rr))

    # ---------------------------------------------------------------- 4. recruit
    r1, r2, k2, k3 = (Cab(match, n) for n in ('R1', 'R2', 'K2', 'K3'))
    r1.entry(21, 0, 910001, timeout=150); r2.entry(21, 1, 910002, timeout=150)
    x1, x2 = r1.wait(6), r2.wait(1)
    check('casual recruits pair (2 clients, group 0)', x1[1] and x1[1] == x2[1] and len(x1[2]) == 2 and all(g == 0 for g, _ in x1[2]), str((x1, x2)))
    k2.entry(22, 2, 920002, timeout=6); k3.entry(22, 3, 920003, timeout=6)
    y = k2.wait(10)
    check('ranked recruits of different classes never pair', y[0] == 1 and not y[2], str(y))

    bad = [n for n, ok in RESULTS if not ok]
    print('\n%d/%d checks passed' % (len(RESULTS) - len(bad), len(RESULTS)))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
