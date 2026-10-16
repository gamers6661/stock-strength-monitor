"""题材助攻逐项保留，宽题材可计算，缺数据与未扩散分开。"""
import unittest

import theme_assist


class ThemeAssistTest(unittest.TestCase):
    def test_all_relations_retained_and_self_excluded(self):
        rows = [dict(code=str(i), boards=["概念甲", "概念乙"], ret5=-10 if i == 0 else 5,
                     trend_online=i > 0, trend_online_prev=False, trend_online_prev2=False,
                     emotion_strong=i in (1, 2, 3), emotion_limit=i in (1, 2),
                     emotion_yesterday_limit=False, stock_strength_score=10 if i == 0 else 90)
                for i in range(7)]
        before = [r["stock_strength_score"] for r in rows]
        theme_assist.enrich_stocks(rows)
        target = rows[0]
        self.assertEqual(target["theme_assist"], "按题材分别查看")
        self.assertEqual(len(target["theme_relations"]), 2)
        self.assertEqual(target["theme_relations"][0]["peers"], 6)
        self.assertEqual(target["theme_relations"][0]["trend_pct"], 100)
        self.assertEqual(target["theme_relations"][1]["overlap_group"], "theme:概念甲")
        self.assertEqual([r["stock_strength_score"] for r in rows], before)

    def test_small_and_large_themes(self):
        small = [dict(code=str(i), boards=["小题材"], ret5=1) for i in range(5)]
        theme_assist.enrich_stocks(small)
        self.assertTrue(all(r["theme_relations"][0]["state"] == "数据不足" for r in small))
        large = [dict(code=str(i), boards=["PCB概念"], ret5=i / 10,
                      trend_online=i % 2 == 0, trend_online_prev=False,
                      trend_online_prev2=False, emotion_strong=False,
                      emotion_limit=False, emotion_yesterday_limit=False)
                 for i in range(101)]
        theme_assist.enrich_stocks(large)
        self.assertEqual(large[0]["theme_relations"][0]["peers"], 100)
        self.assertTrue(large[0]["theme_relations"][0]["wide"])
        self.assertNotEqual(large[0]["theme_relations"][0]["state"], "数据不足")

    def test_unverified_f10_remains_unknown(self):
        rows = [dict(code=str(i), boards=["题材"], ret5=1,
                     theme_basis="同花顺详情成员待F10核对") for i in range(7)]
        theme_assist.enrich_stocks(rows)
        self.assertEqual(rows[0]["theme_relations"][0]["state"], "数据不足")


if __name__ == "__main__":
    unittest.main()
