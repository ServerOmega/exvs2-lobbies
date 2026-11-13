#!/usr/bin/env python3
"""Deterministic tests for the casual/shuffle matcher in mms_server.py (no network, injected clock).
Run: python3 test_casual.py      EXPERIMENTAL: shapes follow static analysis, untested in game."""
import unittest
from mms_server import Matchmaker, RatingStore, SUCCESS, MATCH_CANCELED, NPC_SERIAL

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
        self.mm = Matchmaker(RatingStore(), fill_after=30, partial=True, seed=1)

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
        mm = Matchmaker(RatingStore(), fill_after=30, partial=False)
        es = [entry(23, 'S', timeout=60) for _ in range(2)]
        for e in es: mm.entry(e, 0)
        self.assertEqual(mm.check(es[0]['myclient']['node_id'], 40), (SUCCESS, None))
        self.assertEqual(mm.check(es[0]['myclient']['node_id'], 61)[0], MATCH_CANCELED)

    def test_ranked_solo_even_split(self):
        rs = RatingStore(); mm = Matchmaker(rs, seed=2)
        es = [entry(13, 'S', attr2=5, level=0) for _ in range(4)]
        for e, v in zip(es, (1900, 1500, 1500, 1100)): rs.r[e['myplayer']['banapassport_am_id']] = v
        for e in es: mm.entry(e, 0)
        code, r = mm.check(es[0]['myclient']['node_id'], 61)       # bands wide open after 60 s
        g = {}
        for c in r['clients']: g.setdefault(c['group_id'], set()).add(c['client']['node_id'])
        top, low = es[0]['myclient']['node_id'], es[3]['myclient']['node_id']
        self.assertTrue(any({top, low} <= s for s in g.values()))   # strongest paired with weakest

if __name__ == '__main__':
    unittest.main(verbosity=2)
