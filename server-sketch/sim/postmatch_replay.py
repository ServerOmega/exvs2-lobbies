#!/usr/bin/env python3
"""Post-match HTTP replay harness (results-hang simulation, analysis/results-hang-sim.md section 2).

Replays the card-server calls a cabinet makes when a versus match ends, the way vsac29 makes them (exe analysis,
results-hang-logs.md section 7.2 / 8.3):
  * every call is a libcurl POST with CURLOPT_TIMEOUT = 10 s;
  * a failed call (error != 0, HTTP error, or timeout) is re-sent at once, at most 5 tries, then the task gives up;
  * task S (SaveResult) sends its saves one after the other; task C (ResultCapture) runs at the same time:
    up to 3 frame captures of <= 300 frames (5 s) each + SaveResultCapture (224);
  * the results screen can only close when F (Finish, ~589 frames = 9.8 s), S, A and C are all done.
Which saves S sends and in what order is inferred [I] (versus online: 201, 221, 223; LM-local: 200, 220, 223;
"pessimistic" adds the methods upstream leaves unhandled: 205, 211, 225).

A fault proxy sits between the "cabinets" and the real (patched) C# server and can delay, drop, 500 or ErrServer chosen
methods. Fault scenarios run time-scaled (--scale 0.1: 10 s timeout -> 1 s, 12 s delay -> 1.2 s) and are reported in
game seconds. The DB-lock scenarios run in real time: a second process holds an EXCLUSIVE lock on the SQLite file, which
is the one realistic way for this server to answer slowly (Microsoft.Data.Sqlite waits up to 30 s on a busy file).

Fake cabinets and FAKE cards only (TESTSIM... codes). Needs game_server_nue_pb2 on PYTHONPATH.
Usage: postmatch_replay.py --server-dir /path/to/linux-build [--scale 0.1] [--quick] [--json out.json]
"""
import argparse, http.server, json, os, shutil, signal, socket, socketserver, sqlite3, subprocess, sys, threading, time
import urllib.error, urllib.request, uuid
import game_server_nue_pb2 as pb

TIMEOUT_S, MAX_TRIES = 10.0, 5
F_FINISH_S = 0x24d / 60.0          # Finish sub-flow, frame scripted (~9.8 s)
CAPTURES = 3
CAPTURE_TYPICAL_S, CAPTURE_WORST_S = 10 / 60.0, 300 / 60.0   # per capture: assumed typical / code limit (300 frames)
CAPTURE_S = CAPTURE_TYPICAL_S
SEQ = {
    'online': [pb.MTHD_SAVE_VSM_ON_RESULT, pb.MTHD_SAVE_BATTLE_LOG_ON, pb.MTHD_SAVE_USER_PLAY_RESEARCH_DATA],
    'lm': [pb.MTHD_SAVE_VSM_RESULT, pb.MTHD_SAVE_BATTLE_LOG, pb.MTHD_SAVE_USER_PLAY_RESEARCH_DATA],
    'pessimistic': [pb.MTHD_SAVE_VSM_ON_RESULT, pb.MTHD_SAVE_VSM_TO_RESULT, pb.MTHD_SAVE_MEDAL, pb.MTHD_SAVE_BATTLE_LOG_ON,
                    pb.MTHD_SAVE_FAILED_BATTLE_LOG_ON, pb.MTHD_SAVE_USER_PLAY_RESEARCH_DATA],
}
NAME = {v: k for k, v in pb.MethodType.items()}


def base(method, serial):
    q = pb.Request(); q.type = method; q.request_id = uuid.uuid4().hex
    q.pcb_serial = serial; q.loc_id = 'SIMLOC0001'; q.token = ''
    return q


def raw_post(url, q, timeout):
    req = urllib.request.Request(url, data=q.SerializePartialToString(), method='POST', headers={
        'Content-Type': 'application/x-protobuf', 'X-Nue-Protobuf-Revision': '141'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    out = pb.Response(); out.MergeFromString(data)
    return out


class Card:
    """A fake card registered in the server DB (codes are fake, never printed)."""
    def __init__(self, url, n, serial):
        self.url, self.serial = url, serial
        run = int(time.time()) % 100000
        self.access, self.chip = 'TESTSIM%05d%08d' % (run, n), 'TESTSIMCHIP%05d%04d' % (run, n)
        p = self.pre_load()
        if p.is_new_card:
            q = base(pb.MTHD_REGISTER_CARD, serial); r = q.register_card
            r.session_id = p.session_id; r.is_card = True; r.access_code = self.access; r.chip_id = self.chip
            r.mucha_country_code = 'JPN'
            raw_post(url, q, 15)
            p = self.pre_load()
        self.session, self.pilot = p.session_id, p.load_player.pilot_id

    def pre_load(self):
        q = base(pb.MTHD_PRE_LOAD_CARD, self.serial); p = q.pre_load_card
        p.is_card = True; p.access_code = self.access; p.chip_id = self.chip; p.mucha_country_code = 'JPN'
        return raw_post(self.url, q, 15).pre_load_card


def build(method, card):
    q = base(method, card.serial); now = int(time.time())
    if method == pb.MTHD_SAVE_VSM_ON_RESULT:
        s = q.save_vsm_on_result; s.pilot_id = card.pilot; s.session_id = card.session; s.result.SetInParent()
    elif method == pb.MTHD_SAVE_VSM_RESULT:
        s = q.save_vsm_result; s.pilot_id = card.pilot; s.session_id = card.session; s.shuffle_flag = True
        s.result.SetInParent()
    elif method == pb.MTHD_SAVE_BATTLE_LOG:
        b = q.save_battle_log; b.session_id = card.session; g = b.battle_log
        g.pcb_id = 1; g.revenge_num = 0; g.game_mode = 0; g.stage_id = 1; g.local_priority_match_flag = False; g.scene_id = 0
        p = g.pilots.add(); p.is_human = True; p.player_type = 0; p.pilot_id = card.pilot; p.player_level_id = 1
        p.consecutive_win = 1; p.mst_mobile_suit_id = 1; p.burst_type = 0
    elif method == pb.MTHD_SAVE_BATTLE_LOG_ON:
        q.save_battle_log_on.SetInParent()
    elif method == pb.MTHD_SAVE_USER_PLAY_RESEARCH_DATA:
        d = q.save_user_play_research_data; d.pilot_id = card.pilot; d.session_id = card.session
    elif method == pb.MTHD_SAVE_RESULT_CAPTURE:
        c = q.save_result_capture; c.pilot_id = card.pilot; c.session_id = card.session; c.played_at = now
        c.loc_id = 'SIMLOC0001'; c.paid = True; c.mode = 1
    elif method == pb.MTHD_SAVE_VSM_TO_RESULT:
        s = q.save_vsm_to_result; s.pilot_id = card.pilot; s.session_id = card.session; s.shuffle_flag = False
    elif method == pb.MTHD_SAVE_MEDAL:
        m = q.save_medal; m.is_card = True; m.access_code = card.access; m.chip_id = card.chip
        m.mucha_country_code = 'JPN'; m.medal_mode = pb.MEDAL_LOAD; m.grant_at = now; m.medal = 0
    elif method == pb.MTHD_SAVE_FAILED_BATTLE_LOG_ON:
        f = q.save_failed_battle_log_on; f.pilot_id = card.pilot; f.played_at = now; f.room_id = 1
        f.my_fault_flag = False; f.loc_id = 'SIMLOC0001'
    return q


def game_call(url, method, card, scale):
    """One vsac29 card-server call: <= 5 tries, 10 s (scaled) timeout each, immediate re-send on any failure."""
    tries, t0 = [], time.monotonic()
    for _ in range(MAX_TRIES):
        t = time.monotonic()
        try:
            r = raw_post(url, build(method, card), TIMEOUT_S * scale)
            outcome = 'ok' if r.error == pb.SUCCESS else 'err:%s' % (r.error_msg or r.error)
        except (socket.timeout, TimeoutError):
            outcome = 'timeout'
        except urllib.error.HTTPError as e:
            outcome = 'http%d' % e.code
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            outcome = 'timeout' if 'timed out' in str(e) else 'conn'
        tries.append((outcome, (time.monotonic() - t) / scale))
        if outcome == 'ok':
            break
    return {'method': NAME[method], 'tries': tries, 'game_s': (time.monotonic() - t0) / scale,
            'gave_up': tries[-1][0] != 'ok'}


def cabinet(url, card, seq, scale, out, capture_s=None):
    """Tasks S and C of one cabinet, concurrently; gate = max(F, S, C) (A is modelled in hang_model.py)."""
    res = {}
    def task_s():
        t = time.monotonic(); calls = [game_call(url, m, card, scale) for m in SEQ[seq]]
        res['S'] = {'game_s': (time.monotonic() - t) / scale, 'calls': calls}
    def task_c():
        t = time.monotonic(); calls = []
        for _ in range(CAPTURES):
            time.sleep((capture_s if capture_s is not None else CAPTURE_S) * scale)
        calls.append(game_call(url, pb.MTHD_SAVE_RESULT_CAPTURE, card, scale))
        res['C'] = {'game_s': (time.monotonic() - t) / scale, 'calls': calls}
    th = [threading.Thread(target=task_s), threading.Thread(target=task_c)]
    [x.start() for x in th]; [x.join() for x in th]
    res['gate_s'] = max(F_FINISH_S, res['S']['game_s'], res['C']['game_s'])
    out[card.serial] = res


class FaultProxy(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_handler(upstream, rules, scale):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *a): pass
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            q = pb.Request(); q.MergeFromString(body)
            rule = rules.get(q.type) or rules.get('*')
            if rule:
                st = rule.setdefault('_seen', 0); rule['_seen'] = st + 1
                active = rule.get('first_n') is None or st < rule['first_n']
            if rule and active:
                kind = rule['kind']
                if kind == 'delay':
                    time.sleep(rule['s'] * scale)
                elif kind == 'drop':          # hold the connection, never answer (server hung / packet loss)
                    time.sleep(TIMEOUT_S * scale * 1.5); self.close_connection = True; return
                elif kind == 'http500':
                    self.send_response(500); self.send_header('Content-Length', '0'); self.end_headers(); return
                elif kind == 'errserver':
                    r = pb.Response(); r.type = q.type; r.request_id = q.request_id; r.error = pb.ERR_SERVER
                    r.error_msg = 'injected'
                    data = r.SerializePartialToString()
                    self.send_response(200); self.send_header('Content-Type', 'application/protobuf')
                    self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data); return
            req = urllib.request.Request(upstream, data=body, method='POST', headers={
                'Content-Type': 'application/x-protobuf', 'X-Nue-Protobuf-Revision': '141'})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data, code = r.read(), r.status
            except urllib.error.HTTPError as e:
                data, code = e.read(), e.code
            except Exception:
                self.close_connection = True; return
            try:
                self.send_response(code); self.send_header('Content-Type', 'application/protobuf')
                self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
            except OSError:
                pass
    return H


class Server:
    def __init__(self, build_dir, port, env_flags, log_path):
        self.port = port
        env = dict(os.environ, Kestrel__Endpoints__BaseServer__Url='http://127.0.0.1:%d' % port, **env_flags)
        self.proc = subprocess.Popen(['./Server-Infinite'], cwd=build_dir, env=env, stdout=open(log_path, 'w'),
                                     stderr=subprocess.STDOUT, start_new_session=True)
        self.url = 'http://127.0.0.1:%d/' % port
        self.db = os.path.join(build_dir, 'ServerInfinite.db')
        for _ in range(240):
            try:
                socket.create_connection(('127.0.0.1', port), 0.5).close(); time.sleep(1); return
            except OSError:
                time.sleep(0.5)
        raise RuntimeError('server did not start, see ' + log_path)

    def stop(self):
        os.killpg(self.proc.pid, signal.SIGTERM)
        try: self.proc.wait(15)
        except subprocess.TimeoutExpired: os.killpg(self.proc.pid, signal.SIGKILL)


def run_scenario(srv, name, seq, rules, scale, cabinets=2, db_lock_s=0, capture_s=None):
    proxy = FaultProxy(('127.0.0.1', 0), make_handler(srv.url, rules, scale))
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    url = 'http://127.0.0.1:%d/' % proxy.server_address[1]
    cards = [Card(srv.url, i + 1, 'SIMPCB%04d' % (i + 1)) for i in range(cabinets)]
    lock = None
    if db_lock_s:
        lock = sqlite3.connect(srv.db, timeout=30, isolation_level=None, check_same_thread=False)
        lock.execute('BEGIN EXCLUSIVE')
        def release():
            lock.execute('COMMIT'); lock.close()
        lock_timer = threading.Timer(db_lock_s, release); lock_timer.start()
    out = {}
    th = [threading.Thread(target=cabinet, args=(url, c, seq, scale, out, capture_s)) for c in cards]
    t0 = time.monotonic(); [x.start() for x in th]; [x.join() for x in th]
    proxy.shutdown()
    if db_lock_s:
        lock_timer.join(); time.sleep(2)   # next scenario starts with a free database
    worst = max(v['gate_s'] for v in out.values())
    tries = sum(len(c['tries']) for v in out.values() for k in 'SC' for c in v[k]['calls'])
    gave = sorted({c['method'] for v in out.values() for k in 'SC' for c in v[k]['calls'] if c['gave_up']})
    s_max = max(v['S']['game_s'] for v in out.values()); c_max = max(v['C']['game_s'] for v in out.values())
    row = {'scenario': name, 'seq': seq, 'scale': scale, 'S_max_s': round(s_max, 1), 'C_max_s': round(c_max, 1),
           'gate_s': round(worst, 1), 'over_F_s': round(max(0.0, worst - F_FINISH_S), 1), 'http_tries': tries,
           'gave_up': gave, 'detail': out}
    print('%-46s seq=%-11s S=%6.1fs C=%5.1fs gate=%6.1fs (+%5.1fs over F) tries=%3d gave_up=%s' % (
        name, seq, s_max, c_max, worst, row['over_F_s'], tries, ','.join(g.replace('MTHD_', '') for g in gave) or '-'))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--server-dir', required=True)
    ap.add_argument('--port', type=int, default=28190)
    ap.add_argument('--scale', type=float, default=0.1)
    ap.add_argument('--quick', action='store_true', help='skip the real-time DB-lock scenarios')
    ap.add_argument('--json')
    ap.add_argument('--only', help='run only scenarios whose title contains this text')
    a = ap.parse_args()
    sc = a.scale
    rows = []
    off = {'CardServerConfig__PostMatchStubs': 'false', 'CardServerConfig__PostMatchWatchdogMs': '0'}
    on = {'CardServerConfig__PostMatchStubs': 'true', 'CardServerConfig__PostMatchWatchdogMs': '8000'}
    for flags, tag in ((off, 'flags OFF'), (on, 'flags ON (stubs + watchdog 8 s)')):
        print('\n== server %s' % tag)
        srv = Server(a.server_dir, a.port, flags, '/tmp/postmatch_replay_%s.log' % ('on' if flags is on else 'off'))
        try:
            def R(title, *x, **k):
                if a.only and a.only not in title: return
                rows.append(dict(run_scenario(srv, title, *x, **k), flags=tag))
            R('baseline (real time)', 'online', {}, 1.0)
            R('baseline LM-local (real time)', 'lm', {}, 1.0)
            R('pessimistic incl. unhandled 205/211/225', 'pessimistic', {}, 1.0)
            R('worst-case capture time (3 x 300 frames)', 'online', {}, 1.0, capture_s=CAPTURE_WORST_S)
            if flags is off:
                R('12 s delay on 201, every try', 'online', {pb.MTHD_SAVE_VSM_ON_RESULT: {'kind': 'delay', 's': 12}}, sc)
                R('12 s delay on 201, first try only', 'online', {pb.MTHD_SAVE_VSM_ON_RESULT: {'kind': 'delay', 's': 12, 'first_n': 2}}, sc)
                R('9 s delay on every call (just under timeout)', 'online', {'*': {'kind': 'delay', 's': 9}}, sc)
                R('server never answers (all calls dropped)', 'online', {'*': {'kind': 'drop'}}, sc)
                R('server never answers, pessimistic seq', 'pessimistic', {'*': {'kind': 'drop'}}, sc)
                R('ErrServer on every call', 'online', {'*': {'kind': 'errserver'}}, sc)
                R('HTTP 500 on every call', 'online', {'*': {'kind': 'http500'}}, sc)
                R('224 SaveResultCapture dropped', 'online', {pb.MTHD_SAVE_RESULT_CAPTURE: {'kind': 'drop'}}, sc)
                R('9.5 s delay on every call, pessimistic seq', 'pessimistic', {'*': {'kind': 'delay', 's': 9.5}}, sc)
            if not a.quick:
                R('SQLite file locked 35 s (real time)', 'online', {}, 1.0, db_lock_s=35)
                R('SQLite file locked 35 s, LM-local (real time)', 'lm', {}, 1.0, db_lock_s=35)
        finally:
            srv.stop()
    if a.json:
        json.dump(rows, open(a.json, 'w'), indent=1, default=str)
    worst = max(rows, key=lambda r: r['gate_s'])
    print('\nworst case: %s [%s] gate %.1f s (results screen held %.1f s longer than F)' % (
        worst['scenario'], worst['flags'], worst['gate_s'], worst['over_F_s']))


if __name__ == '__main__':
    main()
