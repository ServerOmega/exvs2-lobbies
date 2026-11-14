#!/usr/bin/env python3
"""End-to-end test for the results-hang fixes (#1 HumansTeamVsCpu, #4 PostMatchStubs + network_report log) against the
patched C# server. EXPERIMENTAL, fake cabinets and FAKE cards only (TESTHF... access codes, written into the server DB).

  4. Card server: SaveVsmToResult 205, SaveMedal 211, SaveFailedBattleLogOn 225, RegisterOption 306,
     LoadReplayCard 406, PreSaveReplay 407 each get error=SUCCESS and a reply that parses with strict proto2 (missing
     required field = failure, like the cabinet). SaveVsmOnResult with a network_report gets SUCCESS (with --log the
     NETREPORT line is checked in the server log).  --expect-off: the same calls must still get "Unhandled case".
  1. MMS (Mix Match 23, FillAfterSeconds small): two solo cabinets -> one room, both humans group 0, two CPU stand-ins
     (PCB00000NPC, "N") in group 1 on the cabinets' own 2nd node ids; both cabinets get the same list. A 2-human team
     waiting alone -> team vs two stand-ins.  --expect-off: two solos get the normal 1v1 (opposite groups).

Needs game_server_nue_pb2 on PYTHONPATH (python -m grpc_tools.protoc -I analysis/proto/from_exe --python_out=DIR
game_server_nue.proto). Usage: hangfix_e2e.py --url http://127.0.0.1:28080/ [--log server.log] [--expect-off]
Server env for the "on" run: CardServerConfig__PostMatchStubs=true CardServerConfig__OnlineMatching__Enabled=true
CardServerConfig__OnlineMatching__HumansTeamVsCpu=true CardServerConfig__OnlineMatching__FillAfterSeconds=3
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loadtest as L
import game_server_nue_pb2 as pb
from online_tag_e2e import check, post_pb, base, Cab, RESULTS


class Card:
    def __init__(self, url, n, run):
        self.url = url
        self.access, self.chip = 'TESTHF%05d%09d' % (run % 100000, n), 'TESTHFCHIP%05d%04d' % (run % 100000, n)
        p = self.pre_load()
        if p.is_new_card:
            q = base(pb.MTHD_REGISTER_CARD, 'HFPCB0001')
            r = q.register_card; r.session_id = p.session_id; r.is_card = True
            r.access_code = self.access; r.chip_id = self.chip; r.mucha_country_code = 'JPN'
            post_pb(url, q, strict=False)
            p = self.pre_load()
        self.session, self.pilot = p.session_id, p.load_player.pilot_id

    def pre_load(self):
        q = base(pb.MTHD_PRE_LOAD_CARD, 'HFPCB0001')
        p = q.pre_load_card; p.is_card = True; p.access_code = self.access; p.chip_id = self.chip; p.mucha_country_code = 'JPN'
        return post_pb(self.url, q, strict=False).pre_load_card


def stubs(url, card, off):
    now = int(time.time())
    calls = []
    q = base(pb.MTHD_SAVE_VSM_TO_RESULT); s = q.save_vsm_to_result
    s.pilot_id = card.pilot; s.session_id = card.session; s.shuffle_flag = False
    calls.append(('205 SaveVsmToResult', q, 'save_vsm_to_result', None))
    q = base(pb.MTHD_SAVE_MEDAL); m = q.save_medal
    m.is_card = True; m.access_code = card.access; m.chip_id = card.chip; m.mucha_country_code = 'JPN'
    m.medal_mode = pb.MEDAL_LOAD; m.grant_at = now; m.medal = 0
    calls.append(('211 SaveMedal', q, 'save_medal',
                  lambda r: r.acid_error == pb.ACID_SUCCESS and r.pilot_id == card.pilot))
    q = base(pb.MTHD_SAVE_FAILED_BATTLE_LOG_ON); f = q.save_failed_battle_log_on
    f.pilot_id = card.pilot; f.played_at = now; f.room_id = 7; f.my_fault_flag = False
    f.online_matching_mode = list(pb.OnlineMatchingMode.values())[0]; f.loc_id = 'HFLOC'
    calls.append(('225 SaveFailedBattleLogOn', q, 'save_failed_battle_log_on', None))
    q = base(pb.MTHD_REGISTER_OPTION); q.register_option.mobile_user_id = card.pilot; q.register_option.friend_pilot_id = 1
    calls.append(('306 RegisterOption', q, 'register_option', None))
    q = base(pb.MTHD_LOAD_REPLAY_CARD); lr = q.load_replay_card
    lr.is_card = True; lr.access_code = card.access; lr.chip_id = card.chip; lr.mucha_country_code = 'JPN'
    calls.append(('406 LoadReplayCard', q, 'load_replay_card', lambda r: r.acid_error == pb.ACID_NO_USE))
    q = base(pb.MTHD_PRE_SAVE_REPLAY); ps = q.pre_save_replay
    for fld, v in (('replay_size', 1000), ('played_at', now), ('stage_id', 1), ('special_flag', 0), ('replay_service_flag', 0),
                   ('mobile_user_id', 0), ('matching_mode', 0), ('team_type', 0), ('return_match_flag', 0), ('battle_class', 0)):
        try: setattr(ps, fld, v)
        except (TypeError, ValueError): setattr(ps, fld, bool(v))
    calls.append(('407 PreSaveReplay', q, 'pre_save_replay', lambda r: r.status == 2 and r.url))
    for name, q, field, extra in calls:
        try:
            r = post_pb(url, q, strict=True)
        except Exception as e:
            check(name + ' parses strictly', False, repr(e)); continue
        if off:
            check(name + ' still unhandled (flag off)', r.error == pb.ERR_SERVER and r.error_msg == 'Unhandled case')
            continue
        ok = r.error == pb.SUCCESS and r.HasField(field)
        if ok and extra: ok = bool(extra(getattr(r, field)))
        check(name + ' -> SUCCESS', ok, '' if ok else str(r)[:300])


def network_report(url, card, log):
    q = base(pb.MTHD_SAVE_VSM_ON_RESULT); s = q.save_vsm_on_result
    s.pilot_id = card.pilot; s.session_id = card.session
    n = s.network_report
    n.battle_pad_input_delay_frame = 4; n.battle_start_delay_frame = 6; n.delay_src_flag = 1
    n.total_posed_frame = 30; n.total_posed_num = 2
    for ser, rtt in (('HFPCBNR001', 21), ('HFPCBNR002', 23)):
        p = n.pcb_data.add(); p.pcb_serial = ser; p.loc_id = 'HFLOC'; p.rtt = rtt; p.packet_lost_rate = 0.01; p.max_rtt = rtt + 9
    r = post_pb(url, q, strict=False)
    check('SaveVsmOnResult with network_report -> SUCCESS', r.error == pb.SUCCESS)
    if log:
        time.sleep(1.5)
        txt = open(log, errors='replace').read()
        line = [l for l in txt.splitlines() if 'NETREPORT pilot=%d ' % card.pilot in l]
        check('NETREPORT logged', line and 'input_delay=4f' in line[-1] and 'HFPCBNR002@HFLOC:rtt=23ms,max=32ms' in line[-1],
              line[-1][-160:] if line else '')
        check('no card secrets in the stub / NETREPORT log lines',
              all(card.access not in l and card.chip not in l for l in txt.splitlines() if 'STUB' in l or 'NETREPORT' in l))


def mms(url, off):
    mm = url.rstrip('/') + '/match'
    A, B = Cab(mm, 'HA'), Cab(mm, 'HB')
    for c in (A, B):
        c.entry(23, 0, 0, timeout=60)
    ra, rb = A.wait(25), B.wait(5)
    ga = sorted(ra[2]); a2, b2 = A.node + 1, B.node + 1
    if off:
        check('flag off: two solos -> 1v1', len(ga) == 2 and ga[0][0] != ga[1][0], str(ga)); return
    check('two solos -> one 4-seat room', len(ga) == 4 and ra[1] == rb[1], str(ra[2]))
    check('both humans in group 0', {(0, A.node), (0, B.node)} <= set(ga), str(ga))
    check('CPU stand-ins in group 1 on the 2nd node ids', {(1, a2), (1, b2)} <= set(ga), str(ga))
    check('both cabinets get the same list', ra[2] == rb[2])
    # a 2-human team alone (leader C, partner D listed in groups) -> team vs 2 stand-ins
    C, D = Cab(mm, 'HC'), Cab(mm, 'HD')
    C.entry(23, 0, 0, timeout=60, groups=[{'client': D.me(), 'player': {'banapassport_am_id': 0}}])
    rc = C.wait(25); rd = D.wait(5)
    gc = sorted(rc[2])
    check('lone 2-human team -> vs two stand-ins', {(0, C.node), (0, D.node), (1, C.node + 1), (1, D.node + 1)} == set(gc), str(gc))
    check('partner cabinet sees the same room', rd[1] == rc[1], '%s %s' % (rc[1], rd[1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:28080/')
    ap.add_argument('--log', help='server log file (checks the NETREPORT line)')
    ap.add_argument('--expect-off', action='store_true', help='server runs with the flags off (defaults)')
    a = ap.parse_args()
    card = Card(a.url, 1, int(time.time()))
    print('fake card pilot id %d' % card.pilot)
    stubs(a.url, card, a.expect_off)
    network_report(a.url, card, a.log)
    mms(a.url, a.expect_off)
    bad = [n for n, ok in RESULTS if not ok]
    print('\n%d/%d passed' % (len(RESULTS) - len(bad), len(RESULTS)))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
