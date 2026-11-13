#!/usr/bin/env python3
"""Smoke-test the patched EXVS2-IB-Server's online-matching bits WITHOUT the game (EXPERIMENTAL).

Sends RegisterPcb and LoadClassMatch to the card server's game endpoint (POST /) and parses the replies
with strict proto2 parsing (missing required fields -> error, like the cabinet), then checks:
  * RegisterPcb has an SRV_MATCH entry whose uri is a full http:// URL and an SRV_STUN entry
  * LoadClassMatch has a schedule row covering the current hour and a pattern table for it
Then runs the MMS smoke test against the advertised match URL with ../python/fake_cabinet.py.

Needs:  pip install protobuf grpcio-tools
        python -m grpc_tools.protoc -I ../../analysis/proto/from_exe --python_out=. game_server_nue.proto
Usage:  python3 check_card_server.py --url http://127.0.0.1:28080/
No real card data is sent (fake serial / loc id).
"""
import argparse, datetime, os, subprocess, sys, urllib.request, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game_server_nue_pb2 as pb   # generated, see above

def call(url, req):
    data = req.SerializePartialToString()      # the request side is not what we are testing
    r = urllib.request.Request(url, data=data, method='POST', headers={
        'Content-Type': 'application/x-protobuf', 'X-Nue-Protobuf-Revision': '141'})
    with urllib.request.urlopen(r, timeout=10) as resp:
        assert resp.status == 200, resp.status
        out = pb.Response()
        out.ParseFromString(resp.read())         # strict: raises if a required field is missing
        return out

def base_req(method):
    q = pb.Request()
    q.type = method
    q.request_id = uuid.uuid4().hex
    q.pcb_serial = 'TESTPCB0001'
    q.loc_id = 'TESTLOC0001'
    q.token = ''
    return q

def pre_load(url, access, chip):
    q = base_req(pb.MTHD_PRE_LOAD_CARD)
    q.pre_load_card.is_card = True
    q.pre_load_card.access_code = access
    q.pre_load_card.chip_id = chip
    q.pre_load_card.mucha_country_code = 'JPN'
    r = pb.Response()
    r.MergeFromString(post_raw(url, q))      # lenient: only the class fields are checked here
    return r.pre_load_card

def post_raw(url, req):
    r = urllib.request.Request(url, data=req.SerializePartialToString(), method='POST', headers={
        'Content-Type': 'application/x-protobuf', 'X-Nue-Protobuf-Revision': '141'})
    with urllib.request.urlopen(r, timeout=10) as resp:
        return resp.read()

def ranked_save(url):
    """Fake card (NOT a real card's ids) -> register -> post one won solo Class Match result -> re-read."""
    access, chip = 'TESTACCESS%010d' % 1, 'TESTCHIP%08d' % 1
    p = pre_load(url, access, chip)
    if p.is_new_card:
        q = base_req(pb.MTHD_REGISTER_CARD)
        q.register_card.session_id = p.session_id
        q.register_card.is_card = True
        q.register_card.access_code = access
        q.register_card.chip_id = chip
        q.register_card.mucha_country_code = 'JPN'
        post_raw(url, q)
        p = pre_load(url, access, chip)
    lp = p.load_player
    before = (lp.class_id_solo, lp.grade_solo, lp.rate_solo, lp.class_solo_win)
    print('before: class_id_solo=%d grade_solo=%d rate_solo=%.1f class_solo_win=%d' % before)
    q = base_req(pb.MTHD_SAVE_VSM_ON_RESULT)
    s = q.save_vsm_on_result
    s.pilot_id = lp.pilot_id
    s.session_id = p.session_id
    s.shuffle_flag = True
    s.result.win_flag = True
    s.result.online_matching_mode = pb.OMM_CLASS
    s.result.room_id = 1
    c = s.result.class_match_result
    c.class_id_solo, c.class_id_team = 2, 2
    c.before_rate, c.after_rate, c.obtained_rate, c.grade_id = lp.rate_solo, lp.rate_solo + 12.5, 12.5, 7
    post_raw(url, q)
    lp2 = pre_load(url, access, chip).load_player
    after = (lp2.class_id_solo, lp2.grade_solo, lp2.rate_solo, lp2.class_solo_win)
    print('after:  class_id_solo=%d grade_solo=%d rate_solo=%.1f class_solo_win=%d' % after)
    good = lp2.class_id_solo == 2 and lp2.grade_solo == 7 and abs(lp2.rate_solo - (lp.rate_solo + 12.5)) < 0.01 \
        and lp2.class_solo_win == lp.class_solo_win + 1
    print('ranked save round-trip:', 'OK' if good else 'FAIL')
    return good

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:28080/')
    ap.add_argument('--skip-mms', action='store_true')
    ap.add_argument('--ranked-save', action='store_true',
                    help='also create a FAKE test card and post a fake Class Match result (writes to the server DB!)')
    a = ap.parse_args()
    ok = True

    r = call(a.url, base_req(pb.MTHD_REGISTER_PCB))
    infos = list(r.register_pcb.server_info)
    for s in infos:
        print('RegisterPcb server_info: type=%s uri=%r port=%d' % (pb.ServerType.Name(s.server_type), s.uri, s.port))
    match = [s for s in infos if s.server_type == pb.SRV_MATCH]
    stun = [s for s in infos if s.server_type == pb.SRV_STUN]
    if not match or not match[-1].uri.startswith('http'):
        print('FAIL: no SRV_MATCH with a full http:// uri (is OnlineMatching.Enabled true?)'); ok = False
    if not stun:
        print('FAIL: no SRV_STUN entry -> the cabinet would never start online matching'); ok = False

    r = call(a.url, base_req(pb.MTHD_LOAD_CLASS_MATCH))
    lcm = r.load_class_match
    hour = datetime.datetime.now().hour
    hour = hour + 24 if hour <= 2 else hour
    now = int(datetime.datetime.now().timestamp())
    rows = [(s.start_at, s.end_at, s.pattern_id) for s in lcm.class_matching_time_schedule]
    print('LoadClassMatch schedules:', rows)
    print('LoadClassMatch patterns:', [(p.pattern_id, len(p.class_matching_solo), len(p.class_matching_team))
                                       for p in lcm.class_matching_pattern_table])
    print('LoadClassMatch request table:', [(q.room_search_id, q.matching_try_num, q.seq_num, q.make_room_flag)
                                            for q in lcm.class_matching_request_table])
    by_hour = [p for s, e, p in rows if s <= hour < e]
    by_unix = [p for s, e, p in rows if s <= now < e]
    print('schedule hit by hour (%d): %s, by unix time: %s' % (hour, by_hour, by_unix))
    if not (by_hour or by_unix):
        print('FAIL: no schedule row covers now'); ok = False

    if not a.skip_mms and match:
        here = os.path.dirname(os.path.abspath(__file__))
        fc = os.path.join(here, '..', 'python', 'fake_cabinet.py')
        print('== MMS smoke test against', match[-1].uri)
        rc = subprocess.call([sys.executable, fc, '--url', match[-1].uri, '--units', 'S,S,S,S', '--world', '23'])
        ok = ok and rc == 0
    if a.ranked_save:
        ok = ranked_save(a.url) and ok
    print('OK' if ok else 'FAILED')
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()
