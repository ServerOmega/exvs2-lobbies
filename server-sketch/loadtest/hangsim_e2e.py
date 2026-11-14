#!/usr/bin/env python3
"""End-to-end test for the results-hang simulation drafts (analysis/results-hang-sim.md section 5) against the patched
C# server. FAKE cards only (TESTSIM... codes written into the server DB); never prints a code.

  * LoadBlackList: defaults are upstream's 300 / 1 / 300 / 300 / 5; with --blacklist RTT,FRAME the reply carries the
    configured values (server env CardServerConfig__LoadBlackList__ThresholdDelayedRtt / __ThresholdDelayedFrame).
  * MaskCardSecretsInLog (default true): after card calls the server log holds no fake access code / chip id.
  * PostMatchWatchdogMs: an outside process locks the SQLite file; SaveResultCapture (writes the upload token) must
    get Success in < 10 s with the watchdog on, and must NOT be answered within the game's 10 s timeout with it off.

Usage: hangsim_e2e.py --url http://127.0.0.1:28080/ --db /path/ServerInfinite.db --log /path/Logs/log-YYYYMMDD.txt
       [--watchdog-on] [--blacklist 200,4]
"""
import argparse, os, sqlite3, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'sim'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game_server_nue_pb2 as pb
from postmatch_replay import Card, build, raw_post, base
from online_tag_e2e import check, RESULTS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:28080/')
    ap.add_argument('--db', required=True)
    ap.add_argument('--log', required=True)
    ap.add_argument('--watchdog-on', action='store_true')
    ap.add_argument('--blacklist', default='300,5')
    a = ap.parse_args()
    rtt, frame = (int(x) for x in a.blacklist.split(','))

    card = Card(a.url, 1, 'SIMPCB9001')
    print('fake card pilot id %d' % card.pilot)

    r = raw_post(a.url, base(pb.MTHD_LOAD_BLACK_LIST, card.serial), 15)
    b = r.load_black_list
    check('LoadBlackList values %d/1/300/300/%d' % (rtt, frame),
          r.error == pb.SUCCESS and b.threshold_delayed_rtt == rtt and b.max_blacklist_num == 1 and
          b.delay_restrict_condition == 300 and b.delay_permit_condition == 300 and b.threshold_delayed_frame == frame,
          'got %d/%d/%d/%d/%d' % (b.threshold_delayed_rtt, b.max_blacklist_num, b.delay_restrict_condition,
                                  b.delay_permit_condition, b.threshold_delayed_frame))
    try:
        r.SerializeToString()            # all required fields present
        check('LoadBlackList reply passes strict proto2', True)
    except Exception as e:
        check('LoadBlackList reply passes strict proto2', False, repr(e))

    time.sleep(1.5)
    txt = open(a.log, errors='replace').read()
    check('server log has no clear-text fake access code / chip id', card.access not in txt and card.chip not in txt)
    check('server log shows masked values', '<masked:' in txt)

    lock = sqlite3.connect(a.db, timeout=30, isolation_level=None, check_same_thread=False)
    lock.execute('BEGIN EXCLUSIVE')
    rel = threading.Timer(14, lambda: (lock.execute('COMMIT'), lock.close())); rel.start()
    t = time.monotonic()
    try:
        r = raw_post(a.url, build(pb.MTHD_SAVE_RESULT_CAPTURE, card), 10.0)
        took, ok = time.monotonic() - t, r.error == pb.SUCCESS
    except Exception:
        took, ok = time.monotonic() - t, False
    if a.watchdog_on:
        check('DB locked: SaveResultCapture answered Success within the 10 s game timeout (%.1f s)' % took, ok and took < 9.6)
    else:
        check('DB locked, watchdog off: no answer within the 10 s game timeout (%.1f s) = game would retry' % took,
              not ok and took >= 9.9)
    rel.join(); time.sleep(1)
    r = raw_post(a.url, build(pb.MTHD_SAVE_RESULT_CAPTURE, card), 10.0)
    check('after the lock: SaveResultCapture Success with an upload URL', r.error == pb.SUCCESS and len(r.save_result_capture.url) == 1)
    bad = [n for n, ok in RESULTS if not ok]
    print('\n%d/%d passed' % (len(RESULTS) - len(bad), len(RESULTS)))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
