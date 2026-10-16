"""雷达与每日观察先按自身目标排序再截取名额。"""
import unittest

import radar
import strength


class RadarStrengthTest(unittest.TestCase):
    def row(self, code, score, ret20):
        return dict(code=code, name=code, watch_candidate=True, score=score,
                    stock_strength_score=score, stock_strength_percentile=score,
                    stock_strength_rank=int(100-score)+1,
                    stock_strength_reference_count=100,
                    stock_strength_parts={'persistence': 70, 'acceptance': 70},
                    stock_strength_motion='维持', volume_spike_stall=False,
                    beat_days10=8, ret5_ex_market=2,
                    ret20=ret20, ret5=6, ret10=9, ma5=12,
                    ma10=11, ma20=10, touch_state="无回踩", fund_state="未知",
                    industry_breadth=None, risk_notes=[], entry_state="观察",
                    factors={"rs": score}, overheated=False)

    def test_radar_caps_each_tier_after_strength_sort(self):
        rows = [self.row(f"{i:02d}", 90-i*3, 10) for i in range(20)]
        for row in rows[9:15]:
            row.update(ret5=3, ret10=5)
        for row in rows[15:]:
            row.update(ret5=1, ret10=2, ret20=3)
        result = radar.build_trend(rows, cap=1)
        self.assertEqual([r["code"] for r in result["items"]], ["00", "09", "15"])
        self.assertEqual([t["n"] for t in result["tiers"]], [9, 6, 5])
        self.assertEqual(rows[0]["trend_pool_rank"], 1)
        self.assertEqual(rows[0]["trend_pool_percentile"], 100)

    def test_slow_growth_cannot_be_a_and_risk_does_not_cancel_attack(self):
        rows = [self.row(f"{i:02d}", 99-i, 10) for i in range(20)]
        for row in rows:
            row.update(ret5=1, ret10=2, ret20=3)
        result = radar.build_trend(rows)
        self.assertEqual(result['tiers'][0]['n'], 0)
        self.assertEqual(rows[0]['trend_tier'], 'C')
        rows[0].update(ret5=6, ret10=9, ret20=15, volume_spike_stall=True,
                       risk_notes=['位置偏热', '触板未封'])
        radar.assign_trend_tiers(rows)
        self.assertEqual(rows[0]['trend_tier'], 'A')

    def test_daily_groups_use_strength_not_ret20_order(self):
        rows = [self.row("low", 80.89, 100), self.row("high", 99, 10)]
        for row in rows:
            row.update(entry_watch=True, current_pullback_candidate=True,
                       touch_state="回踩反弹", industry_supported=False,
                       board_name="沪主板", risk_notes=[], limit_today=False)
        snap = {"stocks": rows, "generated_at": "today", "session": "盘中",
                "strength_model": {"asof": "yesterday"}}
        result = strength.daily_advice(snap)
        self.assertEqual(result["items"][0]["groups"][0]["stocks"][0]["code"], "high")
        self.assertEqual(result["items"][0]["groups"][0]["label"], "当前回踩候选")
        self.assertIn("盘中MA10", result["items"][0]["groups"][0]["hint"])


if __name__ == "__main__":
    unittest.main()
