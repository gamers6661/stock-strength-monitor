"""板块入口、内部强度顺序与自剔除超额的数据契约。"""
import unittest
from unittest.mock import patch
import copy

import board_center


class BoardCenterTest(unittest.TestCase):
    def setUp(self):
        self.catalog = patch.object(board_center,'_catalog',return_value={'industry':set(),'theme':set()})
        self.catalog.start()
        self.addCleanup(self.catalog.stop)

    def test_official_board_does_not_overwrite_granular_stock_industry(self):
        rows=[dict(code=str(i),name=str(i),primary_industry='种植业',ret5=2,ret20=4,
                   change_pct=1,stock_strength_score=80) for i in range(6)]
        before=copy.deepcopy(rows)
        mapping={r['code']:{'industry':['种植业','农林牧渔']} for r in rows}
        source={r['code']:['种植业与林业'] for r in rows}
        with patch.object(board_center,'_catalog',return_value={'industry':{'种植业与林业'},'theme':set()}), \
             patch.object(board_center,'_cache',side_effect=lambda name:(source if name=='ths_industry_members.json' else {},{},None)):
            out=board_center.build(rows,{r['code']:{'price':10} for r in rows},mapping,[],{},'2026-10-08')
        b={b['id']:b for b in out}
        self.assertEqual(b['industry:种植业与林业']['member_codes'],list(map(str,range(6))))
        self.assertEqual(b['industry:种植业']['valid_members'],6)
        self.assertTrue(b['industry:种植业与林业']['ranking_eligible'])
        self.assertEqual(rows,before)

    def test_catalog_without_members_remains_queryable_not_qualified(self):
        with patch.object(board_center,'_catalog',return_value={'industry':{'缺成员'},'theme':{'缺日线'}}), \
             patch.object(board_center,'_cache',return_value=({}, {},None)):
            out=board_center.build([],{}, {},[],{},'2026-10-08')
        self.assertEqual({b['name'] for b in out},{'缺成员','缺日线'})
        self.assertTrue(all(not b['ranking_eligible'] and b['trend_rank'] is None for b in out))
        self.assertTrue(all(b['coverage_state']=='成员待补齐' for b in out))

    def test_verified_industry_removes_old_members_without_changing_stocks(self):
        rows=[dict(code=c,name=c,primary_industry='钢铁',ret5=2,ret20=4,
                   change_pct=1,stock_strength_score=80) for c in ('600001','600019')]
        before=copy.deepcopy(rows)
        mapping={r['code']:{'industry':['钢铁']} for r in rows}
        source={'600019':['钢铁']}
        for complete in (True,False):
            stat={'complete_counts':{'钢铁':1},'failed':[] if complete else ['钢铁']}
            with patch.object(board_center,'_catalog',return_value={'industry':{'钢铁'},'theme':set()}), \
                 patch.object(board_center,'_cache',side_effect=lambda name:(source,stat,None) if name=='ths_industry_members.json' else ({},{},None)):
                b=board_center.build(rows,{r['code']:{'price':10} for r in rows},mapping,[],{},'2026-10-08')[0]
            self.assertEqual(b['member_codes'],['600019'] if complete else ['600001','600019'])
            self.assertEqual(b['source_complete'],complete)
            self.assertEqual(rows,before)

    def test_same_members_three_lists_and_self_excluded_excess(self):
        rows = []
        for i in range(7):
            rows.append({"code": str(i), "name": str(i), "boards": ["PCB概念"],
                         "primary_industry": "元件", "ret5": i * 2, "ret20": i * 3,
                         "change_pct": i, "trend_online": True, "trend_online_prev": False,
                         "trend_online_prev2": False, "emotion_strong": i == 5,
                         "emotion_limit": i == 5, "emotion_yesterday_limit": False,
                         "stock_strength_score": 70 + i, "stock_strength_rank": 7 - i,
                         "stock_strength_percentile": 10 + i * 10,
                         "stock_strength_parts": {"persistence": 65, "acceptance": 60},
                         "stock_strength_motion": "增强" if i == 4 else "维持",
                         "strength_accel5_pp": i, "persistent_strong": i >= 3,
                         "recent_improving": i == 4})
        quotes = {str(i): {"price": 10} for i in range(7)}
        mapping = {str(i): {"themes": ["PCB概念"], "industry": ["元件"]} for i in range(7)}
        result = board_center.build(rows, quotes, mapping, [], {}, "2026-09-24")
        theme = next(b for b in result if b["id"] == "theme:PCB概念")
        self.assertEqual(theme["valid_members"], 7)
        self.assertEqual(theme["member_codes"], sorted(quotes))
        self.assertEqual(theme["members"][0]["code"], "6")
        self.assertAlmostEqual(theme["members"][0]["excess5"], 7)
        self.assertEqual(theme["lists"]["recent"], ["4"])
        self.assertEqual(theme["lists"]["emotion"], ["5"])
        self.assertIsNone(theme["fund_sum_5d"])

    def test_board_and_close_share_qualification_even_when_fading(self):
        import close_monitor
        rows = [{"code": str(i), "name": str(i), "boards": ["测试"],
                 "ret5": 2, "ret20": 6, "change_pct": 1,
                 "stock_strength_score": 90-i, "stock_strength_rank": i+1,
                 "stock_strength_motion": "衰减" if i == 0 else "增强",
                 "persistent_strong": i < 2, "recent_improving": i == 2,
                 "volume_spike_stall": True, "trend_online": True} for i in range(6)]
        quotes = {r['code']: {'price': 10} for r in rows}
        mapping = {c: {'themes': ['测试']} for c in quotes}
        board = board_center.build(rows, quotes, mapping, [], {}, '2026-09-28')[0]
        close = close_monitor.build_close_board({'stocks': rows, 'strength_model': {'asof': '2026-09-28'}})
        self.assertEqual(board['lists']['trend'], [r['code'] for r in close['stocks']])
        self.assertEqual(board['lists']['trend'], ['0', '1'])
        self.assertEqual(board['lists']['recent'], ['2'])
        self.assertEqual(board['members'][0]['strength_motion'], '衰减')

    def test_small_board_has_no_rank_and_ties_prefer_coverage(self):
        rows, quotes, mapping = [], {}, {}
        for name, count, pool_count in [('单股', 1, 1), ('不足同伴', 5, 5), ('完整', 6, 6), ('部分', 6, 12)]:
            for i in range(pool_count):
                code = name + str(i)
                quotes[code] = {'price': 10}
                mapping[code] = {'themes': [name]}
                if i < count:
                    rows.append({'code': code, 'boards': [name], 'ret5': 2, 'ret20': 5,
                                 'change_pct': 1, 'stock_strength_score': 80, 'trend_online': True})
        boards = board_center.build(rows, quotes, mapping, [], {}, '2026-09-28')
        ranked = [b['name'] for b in boards if b['trend_rank'] is not None]
        self.assertEqual(ranked, ['完整', '部分'])
        self.assertEqual({b['name'] for b in boards if not b['ranking_eligible']}, {'单股', '不足同伴'})
        self.assertTrue(all(b['trend_rank'] is None for b in boards if b['valid_members'] < 6))


if __name__ == "__main__":
    unittest.main()
