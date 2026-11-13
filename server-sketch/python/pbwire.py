"""Tiny dependency-free proto2 codec for nue.protocol.mms (matchmaking_server_nue.proto).

Schema-driven: messages decode to plain dicts {field_name: value}; repeated fields are lists,
sub-messages are dicts. Unknown fields are skipped. Encoding writes fields in field-number order
and fills proto2 *required* fields with their default if missing (the game's ParseFromString
fails on a missing required field).
"""
import struct

# type codes
U32, S64, STR, BOOL, ENUM, MSG = 'u32', 's64', 'str', 'bool', 'enum', 'msg'
OPT, REQ, REP = 'opt', 'req', 'rep'

S = {}
def m(name, *fields):
    S[name] = {f[0]: f[1:] for f in fields}  # num -> (fname, type, label, sub|default)

# --- Request -------------------------------------------------------------
m('Request',
  (1, 'type', ENUM, REQ, 0), (2, 'request_id', STR, REQ, ''),
  (100, 'ping', MSG, OPT, 'Empty'), (101, 'issue_node_id', MSG, OPT, 'Req.IssueNodeId'),
  (102, 'entry_matching', MSG, OPT, 'Req.EntryMatching'), (103, 'check_matching', MSG, OPT, 'Req.CheckMatching'),
  (104, 'cancel_matching', MSG, OPT, 'Req.CancelMatching'), (200, 'matching_setting', MSG, OPT, 'Req.MatchingSetting'))
m('Empty')
m('Req.IssueNodeId', (1, 'pcb_serial', STR, REQ, ''), (2, 'loc_id', STR, REQ, ''),
  (3, 'issue_at', U32, REQ, 0), (4, 'issue_count', U32, OPT, 1))
m('Req.EntryMatching', (1, 'apply_id', U32, REQ, 0), (2, 'myclient', MSG, REQ, 'Client'),
  (3, 'myplayer', MSG, REQ, 'Player'), (4, 'world', MSG, OPT, 'World'),
  (5, 'groups', MSG, REP, 'Req.EntryMatching.Group'), (7, 'matching_timeout', U32, REQ, 0),
  (8, 'seq_num', U32, OPT, 0), (9, 'create_room_flag', U32, OPT, 1), (10, 'entry_at', U32, REQ, 0),
  (11, 'bl_banapassport_am_ids', U32, REP, None), (12, 'bl_loc_ids', STR, REP, None))
m('Req.EntryMatching.Group', (2, 'client', MSG, REQ, 'Client'), (3, 'player', MSG, REQ, 'Player'))
m('Req.CheckMatching', (1, 'node_id', U32, REQ, 0), (2, 'check_at', U32, REQ, 0))
m('Req.CancelMatching', (1, 'node_id', U32, REQ, 0), (2, 'apply_id', U32, REQ, 0), (3, 'cancel_at', U32, REQ, 0))
m('Req.MatchingSetting', (1, 'user_id', U32, REQ, 0), (2, 'world', MSG, REQ, 'World'),
  (3, 'conditions', MSG, REP, 'Req.MatchingSetting.Condition'))
m('Req.MatchingSetting.Condition', (1, 'attribute_id', U32, REQ, 0), (2, 'type', ENUM, REQ, 0),
  (3, 'parameter', S64, REQ, 0), (4, 'expr_id', ENUM, REQ, 0), (5, 'relative', BOOL, REQ, False))
# --- Response ------------------------------------------------------------
m('Response',
  (1, 'type', ENUM, REQ, 0), (2, 'request_id', STR, REQ, ''), (3, 'code', ENUM, REQ, 101),
  (100, 'ping', MSG, OPT, 'Empty'), (101, 'issue_node_id', MSG, OPT, 'Resp.IssueNodeId'),
  (102, 'entry_matching', MSG, OPT, 'Resp.EntryMatching'), (103, 'check_matching', MSG, OPT, 'Resp.CheckMatching'),
  (104, 'cancel_matching', MSG, OPT, 'Empty'), (200, 'matching_setting', MSG, OPT, 'Empty'))
m('Resp.IssueNodeId', (1, 'node_id', U32, REP, None))
m('Resp.EntryMatching', (1, 'poling_interval', U32, REQ, 3), (2, 'apply_id', U32, REQ, 0))
m('Resp.CheckMatching', (1, 'room_id', U32, OPT, 0), (2, 'apply_id', U32, OPT, 0),
  (3, 'clients', MSG, REP, 'Resp.CheckMatching.MatchedClient'))
m('Resp.CheckMatching.MatchedClient', (1, 'group_id', U32, REQ, 0), (2, 'client', MSG, REQ, 'Client'))
# --- shared --------------------------------------------------------------
m('Client', (1, 'node_id', U32, REQ, 0), (2, 'pcb_serial', STR, REQ, ''), (3, 'loc_id', STR, REQ, ''),
  (4, 'subnet_id', STR, OPT, ''), (5, 'pref_code', U32, REQ, 0), (6, 'global_ipaddress', STR, OPT, ''),
  (7, 'global_port', U32, OPT, 0), (8, 'local_ipaddress', STR, OPT, ''), (9, 'local_port', U32, OPT, 0),
  (100, 'nat_mapping_type', ENUM, REQ, 0), (101, 'nat_filtering_type', ENUM, REQ, 0),
  (102, 'nat_allocation_policy', ENUM, OPT, 0), (200, 'property', MSG, REP, 'Client.Property'))
m('Client.Property', (1, 'property_id', U32, REQ, 0), (2, 'property_value', STR, REQ, ''))
m('Player', (1, 'banapassport_am_id', U32, REQ, 0), (2, 'parameters', MSG, REP, 'Player.Parameter'))
m('Player.Parameter', (1, 'attribute_id', U32, REQ, 0), (2, 'parameter', S64, REQ, 0))
m('World', (1, 'mucha_game_id', STR, REQ, ''), (2, 'version', U32, REQ, 0), (3, 'world_id', U32, REQ, 0))

# --- wire helpers ----------------------------------------------------------
def _varint(n):
    n &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = n & 0x7f; n >>= 7
        if n: out.append(b | 0x80)
        else: out.append(b); return bytes(out)

def _rvarint(buf, i):
    shift = n = 0
    while True:
        b = buf[i]; i += 1
        n |= (b & 0x7f) << shift; shift += 7
        if not b & 0x80: return n, i
        if shift > 70: raise ValueError('varint too long')

def _zz(n): return (n << 1) ^ (n >> 63)
def _unzz(n): return (n >> 1) ^ -(n & 1)

def _enc_scalar(t, v):
    if t in (U32, ENUM): return _varint(int(v))
    if t == BOOL: return _varint(1 if v else 0)
    if t == S64: return _varint(_zz(int(v)))
    raise TypeError(t)

def encode(mtype, obj):
    out = bytearray()
    for num in sorted(S[mtype]):
        fname, t, label, extra = S[mtype][num]
        if fname not in obj or obj[fname] is None:
            if label != REQ: continue
            v = {} if t == MSG else extra   # proto2 required: emit default
        else:
            v = obj[fname]
        vals = v if label == REP else [v]
        for x in vals:
            if t == MSG:
                body = encode(extra, x)
                out += _varint(num << 3 | 2) + _varint(len(body)) + body
            elif t == STR:
                b = x.encode() if isinstance(x, str) else bytes(x)
                out += _varint(num << 3 | 2) + _varint(len(b)) + b
            else:
                out += _varint(num << 3 | 0) + _enc_scalar(t, x)
    return bytes(out)

def decode(mtype, buf):
    spec = S[mtype]; obj = {}; i = 0
    while i < len(buf):
        key, i = _rvarint(buf, i); num, wt = key >> 3, key & 7
        if wt == 0: val, i = _rvarint(buf, i)
        elif wt == 2:
            ln, i = _rvarint(buf, i); val = buf[i:i + ln]; i += ln
        elif wt == 1: val = buf[i:i + 8]; i += 8
        elif wt == 5: val = buf[i:i + 4]; i += 4
        else: raise ValueError('bad wire type %d' % wt)
        if num not in spec: continue
        fname, t, label, extra = spec[num]
        if wt == 2 and t in (U32, ENUM, S64, BOOL):   # packed repeated (check first: val is bytes)
            vals = []; j = 0
            while j < len(val):
                x, j = _rvarint(val, j); vals.append(_unzz(x) if t == S64 else x)
            obj.setdefault(fname, []).extend(vals); continue
        if t == MSG: val = decode(extra, val)
        elif t == STR: val = bytes(val).decode('utf-8', 'replace')
        elif t == S64: val = _unzz(val)
        elif t == BOOL: val = bool(val)
        elif t == U32: val &= 0xffffffff
        if label == REP: obj.setdefault(fname, []).append(val)
        else: obj[fname] = val
    return obj
