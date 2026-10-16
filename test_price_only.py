"""资金退出后，旧缓存、排序和历史盘中资格不能继续带入资金判断。"""
from copy import deepcopy
import unittest

import attack_model
import intraday_path
import price_only


class PriceOnlyTests(unittest.TestCase):
    def test_cached_fund_never_changes_price_score_or_board_sort(self):
        base = dict(stocks=[dict(code='a', live_attack_score=70, live_attack_price_score=80,
                                live_attack_price_tier='A', fund_today_yi=999, fund_positive_all=True,
                                factors=dict(rs=88, fund=100))],
                    boards=[dict(name='a', rs=50, momentum=50, linkage=50, gate=1, fund=100, score=90),
                            dict(name='b', rs=60, momentum=60, linkage=60, gate=1, fund=0, score=30)])
        snap = price_only.sanitize(deepcopy(base))
        self.assertEqual(snap['stocks'][0]['live_attack_score'], 80)
        self.assertIsNone(snap['stocks'][0]['fund_today_yi'])
        self.assertIsNone(snap['stocks'][0]['fund_positive_all'])
        self.assertEqual(snap['stocks'][0]['factors']['rs'], 88)
        self.assertEqual([b['name'] for b in snap['boards']], ['b', 'a'])
        self.assertEqual([b['score'] for b in snap['boards']], [60, 50])
        self.assertEqual(snap, price_only.sanitize(deepcopy(snap)))

    def test_old_weighted_reference_is_not_relabelled_price_only(self):
        point = dict(valid=True, attack=True, attack_score=80, attack_tier='A', price=10,
                     fund=dict(score=90, weight=.15))
        row = dict(code='a', intraday_last_judgment=point)
        price_only.clear_rows([row])
        self.assertIsNone(point['attack_score'])
        self.assertFalse(point['attack'])
        self.assertEqual(point['price'], 10)

    def test_weighted_history_cannot_create_current_attack_reference(self):
        record = [None]*41
        record[1] = '2026-10-09 10:00:00'; record[2] = 10
        record[31] = True; record[33] = 80; record[34] = 'A'; record[36] = True
        record[37] = dict(weight=.15, score=100)
        old = intraday_path.point(record, '2026-10-09 10:00:01')
        self.assertTrue(old['valid'])
        self.assertEqual(old['price'], 10)
        self.assertIsNone(old['attack_score'])
        self.assertFalse(old['attack'])
        record[37] = dict(weight=0, score=None)
        new = intraday_path.point(record, '2026-10-09 10:00:01')
        self.assertEqual(new['attack_score'], 80)
        self.assertTrue(new['attack'])


if __name__ == '__main__':
    unittest.main()
