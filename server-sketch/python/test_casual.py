#!/usr/bin/env python3
"""Deterministic tests for the casual/shuffle matcher in mms_server.py (no network, injected clock).
Run: python3 test_casual.py      EXPERIMENTAL: shapes follow static analysis, untested in game."""
import unittest
from mms_server import (Matchmaker, RatingStore, SUCCESS, MATCH_CANCELED, NPC_SERIAL, ERR_MATCH_NOENTRY,
                        ERR_DUPLICATE_ENTRY, ERR_NODEID)

_n = [100]
def nid():
    _n[0] += 1; return _n[0]

def cl(node, human=True, loc='LOC1'):
    return {'node_id': node, 'pcb_serial': 'P%d' % node if human else NPC_SERIAL, 'loc_id': loc,
            'pref_code': 13, 'nat_mapping_type': 1, 'nat_filtering_type': 1,
            'property': [{'property_id': 0, 'property_value': 'Y' if human else 'N'}]}

def entry(world, sortie='S', attr2=0, level=0, loc=None, timeout=150):
    me = nid(); loc = loc or 'L%d' % me
    groups = []
    if sortie == 'T':  groups = [{'client': cl(nid(), True, loc), 'player': {'banapassport_am_id': 9000 + me}}]
    if sortie == 'TN': groups = [{'client': cl(nid(), False, loc), 'player': {}}]
    return {'apply_id': 1, 'myclient': cl(me, True, loc),
            'myplayer': {'banapassport_am_id': me,
                         'parameters': [{'attribute_id': 1, 'parameter': 0}, {'attribute_id': 2, 'parameter': attr2},
                                        {'attribute_id': 4, 'parameter': level}]},
            'world': {'mucha_game_id': 'GIB1', 'version': 1, 'world_id': world},
            'groups': groups, 'matching_timeout': timeout, 'entry_at': 0}

class Casual(unittest.TestCase):
    def setUp(self):
        self.mm = Matchmaker(RatingStore(), fill_after=30, partial=True, seed=1, stale_after=1e6)  # clock jumps w/o polls

    def enter(self, *es, t=0):
        for e in es: self.assertEqual(self.mm.entry(e, t), SUCCESS)
        return [e['myclient']['node_id'] for e in es]

    def room(self, node, t=1):
        code, r = self.mm.check(node, t)
        self.assertEqual(code, SUCCESS)
        return r

    def teams(self, r):
        g = {}
        for c in r['clients']: g.setdefault(c['group_id'], []).append(c['client'])
        return g

    def test_four_solos_shuffle(self):
        ids = self.enter(*[entry(23, 'S') for _ in range(4)])
        r = self.room(ids[0]); g = self.teams(r)
        self.assertEqual(sorted(len(v) for v in g.values()), [2, 2])
        self.assertEqual({c['node_id'] for v in g.values() for c in v}, set(ids))
        self.assertTrue(all(c['property'][0]['property_value'] == 'Y' for v in g.values() for c in v))
        for n in ids: self.assertEqual(self.room(n)['room_id'], r['room_id'])

    def test_three_solos_wait_then_short(self):
        ids = self.enter(*[entry(23, 'S') for _ in range(3)])
        self.assertIsNone(self.room(ids[0], t=10))
        r = self.room(ids[0], t=31); g = self.teams(r)
        self.assertEqual(sorted(len(v) for v in g.values()), [1, 2])     # 2v1, CPU fills the empty seat [L]

    def test_pair_plus_two_solos(self):
        pair, s1, s2 = entry(23, 'T'), entry(23, 'S'), entry(23, 'S')
        ids = self.enter(pair, s1, s2)
        g = self.teams(self.room(ids[1]))
        partner = pair['groups'][0]['client']['node_id']
        side = [k for k, v in g.items() if any(c['node_id'] == ids[0] for c in v)][0]
        self.assertEqual({c['node_id'] for c in g[side]}, {ids[0], partner})   # fixed pair stays together
        self.assertEqual({c['node_id'] for c in g[1 - side]}, {ids[1], ids[2]})
        self.assertEqual(self.room(partner)['room_id'], self.room(ids[0])['room_id'])   # partner polls too

    def test_two_pairs(self):
        ids = self.enter(entry(16, 'T', attr2=0x1234), entry(16, 'TN', attr2=0x1234))
        g = self.teams(self.room(ids[0]))
        self.assertEqual(sorted(len(v) for v in g.values()), [2, 2])
        self.assertIn(NPC_SERIAL, [c['pcb_serial'] for v in g.values() for c in v])  # CPU stand-in passed through

    def test_pairs_never_split_and_solo_world_separate(self):
        ids = self.enter(entry(13, 'S', attr2=3), entry(14, 'T', attr2=3), entry(13, 'S', attr2=3))
        self.assertIsNone(self.room(ids[0], t=5))                       # worlds 13 / 14 are different buckets

    def test_instore_needs_same_shop(self):
        a = self.enter(*[entry(15, 'S', attr2=0xAAAA) for _ in range(2)])
        b = self.enter(*[entry(15, 'S', attr2=0xBBBB) for _ in range(2)])
        self.assertIsNone(self.room(a[0], t=5))
        r = self.room(a[0], t=31)                                       # short room only within the shop
        self.assertEqual({c['client']['node_id'] for c in r['clients']}, set(a))
        self.assertNotEqual(self.room(b[0], t=31)['room_id'], r['room_id'])

    def test_soft_attr2_preferred(self):
        ids = self.enter(entry(18, 'S', 1), entry(18, 'S', 2), entry(18, 'S', 1), entry(18, 'S', 1))
        self.assertIsNone(self.room(ids[0], t=1))                      # 3 x bucket1 + 1 x bucket2: wait
        ids += self.enter(entry(18, 'S', 1), t=2)
        r = self.room(ids[0], t=2)
        self.assertNotIn(ids[1], {c['client']['node_id'] for c in r['clients']})
        late = self.enter(entry(18, 'S', 1), entry(18, 'S', 1), entry(18, 'S', 1), t=3)
        self.assertIsNone(self.room(ids[1], t=5))
        self.assertIsNotNone(self.room(ids[1], t=16))                  # after SOFT_WAIT buckets mix

    def test_no_partial(self):
        mm = Matchmaker(RatingStore(), fill_after=30, partial=False, stale_after=1e6)
        es = [entry(23, 'S', timeout=60) for _ in range(2)]
        for e in es: mm.entry(e, 0)
        self.assertEqual(mm.check(es[0]['myclient']['node_id'], 40), (SUCCESS, None))
        self.assertEqual(mm.check(es[0]['myclient']['node_id'], 61)[0], MATCH_CANCELED)

    def test_ranked_solo_even_split(self):
        rs = RatingStore(); mm = Matchmaker(rs, seed=2, stale_after=1e6)
        es = [entry(13, 'S', attr2=5, level=0) for _ in range(4)]
        for e, v in zip(es, (1900, 1500, 1500, 1100)): rs.r[e['myplayer']['banapassport_am_id']] = v
        for e in es: mm.entry(e, 0)
        code, r = mm.check(es[0]['myclient']['node_id'], 61)       # bands wide open after 60 s
        g = {}
        for c in r['clients']: g.setdefault(c['group_id'], set()).add(c['client']['node_id'])
        top, low = es[0]['myclient']['node_id'], es[3]['myclient']['node_id']
        self.assertTrue(any({top, low} <= s for s in g.values()))   # strongest paired with weakest

class LoadTestRegressions(unittest.TestCase):
    """Bugs found by server-sketch/loadtest/loadtest.py (2026-11-13)."""
    def setUp(self):
        self.mm = Matchmaker(RatingStore(), fill_after=30, partial=True, seed=1, stale_after=1e6)

    def test_partner_of_timed_out_pair_gets_match_canceled(self):
        e = entry(14, 'T', attr2=3, timeout=60); p = e['groups'][0]['client']['node_id']
        self.mm.entry(e, 0)
        self.assertEqual(self.mm.check(p, 61)[0], MATCH_CANCELED)
        self.assertEqual(self.mm.check(e['myclient']['node_id'], 62)[0], MATCH_CANCELED)   # was ERR_MATCH_NOENTRY
        self.assertEqual(self.mm.check(e['myclient']['node_id'], 63)[0], ERR_MATCH_NOENTRY)

    def test_partner_of_cancelled_pair_gets_match_canceled(self):
        e = entry(23, 'T'); self.mm.entry(e, 0)
        self.mm.cancel(e['myclient']['node_id'], 5)
        self.assertEqual(self.mm.check(e['groups'][0]['client']['node_id'], 6)[0], MATCH_CANCELED)

    def test_silent_cabinet_not_matched(self):
        mm = Matchmaker(RatingStore(), fill_after=30, partial=True, seed=1)      # default stale_after 20 s
        gone = entry(23); mm.entry(gone, 0)
        es = [entry(23) for _ in range(3)]
        for x in es: mm.entry(x, 25)
        self.assertIsNone(mm.check(es[0]['myclient']['node_id'], 26)[1])
        self.assertEqual(mm.check(gone['myclient']['node_id'], 27)[0], MATCH_CANCELED)
        mm.entry(entry(23), 27)
        r = mm.check(es[0]['myclient']['node_id'], 28)[1]
        self.assertNotIn(gone['myclient']['node_id'], {c['client']['node_id'] for c in r['clients']})

    def test_foreign_node_id_rejected(self):
        v = entry(23, 'T'); self.mm.entry(v, 0)
        evil = entry(23); evil['myclient'] = dict(evil['myclient'], node_id=v['myclient']['node_id'], pcb_serial='EVIL')
        self.assertEqual(self.mm.entry(evil, 1), ERR_DUPLICATE_ENTRY)
        self.assertEqual(len(self.mm.queue), 1)

    def test_duplicate_entry_after_match_no_second_room(self):
        es = [entry(23) for _ in range(4)]
        for x in es: self.mm.entry(x, 0)
        r = self.mm.check(es[0]['myclient']['node_id'], 1)[1]; self.assertIsNotNone(r)
        self.assertEqual(self.mm.entry(es[0], 2), SUCCESS)
        self.assertEqual(len(self.mm.queue), 0)
        for x in [entry(23) for _ in range(3)]: self.mm.entry(x, 3)
        self.assertEqual(self.mm.check(es[0]['myclient']['node_id'], 4)[1]['room_id'], r['room_id'])

    def test_partner_own_entry_and_duplicate_still_merge(self):
        e = entry(23, 'T'); self.mm.entry(e, 0)
        own = dict(e, myclient=e['groups'][0]['client'], myplayer=e['groups'][0]['player'],
                   groups=[{'client': e['myclient'], 'player': e['myplayer']}])
        self.assertEqual(self.mm.entry(own, 1), SUCCESS)
        self.assertEqual(self.mm.entry(e, 2), SUCCESS)
        self.assertEqual(len(self.mm.queue), 1)

    def test_new_entry_from_same_cabinet_replaces_old_wait(self):
        old = entry(15, attr2=7); self.mm.entry(old, 0)
        again = entry(23); again['myclient'] = dict(again['myclient'], pcb_serial=old['myclient']['pcb_serial'])
        self.mm.entry(again, 5)
        self.assertEqual(len(self.mm.queue), 1)
        self.assertEqual(self.mm.check(old['myclient']['node_id'], 6)[0], MATCH_CANCELED)
        mate = entry(15, attr2=7); self.mm.entry(mate, 7)
        self.assertIsNone(self.mm.check(mate['myclient']['node_id'], 100)[1])

    def test_node_zero_rejected(self):
        e = entry(23); e['myclient'] = dict(e['myclient'], node_id=0)
        self.assertEqual(self.mm.entry(e, 0), ERR_NODEID)

if __name__ == '__main__':
    unittest.main(verbosity=2)
