"""验证双轴口径、全报价池统计与行业助攻去自身。"""
from datetime import datetime
import unittest

import emotion
import scoring
import strength


class EmotionTest(unittest.TestCase):
    def sample(self):
        codes = [f"60000{i}" for i in range(7)]
        quotes, klines = {}, {}
        for i, code in enumerate(codes):
            prior_close = 11 if i == 0 else 10
            price = 12.1 if i == 0 else 10
            quotes[code] = dict(code=code, name=code, ts="20260923160000", board_name="沪主板",
                                price=price, last_close=prior_close, open=prior_close,
                                high=price, low=prior_close, amount_wan=1000, turnover_pct=3,
                                change_pct=(price / prior_close - 1) * 100,
                                limit_up=round(prior_close * 1.1, 2), list_days=100)
            klines[code] = [{"date": "2026-09-21", "close": 10},
                            {"date": "2026-09-22", "close": prior_close}]
        return codes, quotes, klines

    def test_full_quote_pool_and_yesterday_feedback(self):
        codes, quotes, klines = self.sample()
        market, detail, extra = emotion.build(quotes, klines, set(),
                                              {c: "同行" for c in codes}, datetime(2026, 9, 23, 16))
        self.assertEqual(market["traded"], 7)
        self.assertEqual(market["limit_up"], 1)
        self.assertEqual(market["limit_up_yesterday"], 1)
        self.assertEqual(market["continued_board"], 1)
        self.assertEqual(len(extra), 1)
        self.assertIsNone(extra[0]["trend_online"])
        self.assertEqual(detail[codes[0]]["emotion_peer_active_pct"], 0)
        self.assertAlmostEqual(detail[codes[1]]["emotion_peer_active_pct"], 100 / 6, places=2)
        self.assertEqual(scoring.build_breadth(quotes, [], detail)["limit_up"], 1)
        self.assertEqual(scoring.build_breadth(quotes, [], detail)["traded"], 7)

    def test_dual_axes_are_independent(self):
        codes, quotes, klines = self.sample()
        market, detail, _ = emotion.build(quotes, klines, set(codes),
                                          {c: "同行" for c in codes}, datetime(2026, 9, 23, 16))
        rows = []
        for i, code in enumerate(codes):
            rows.append(dict(code=code, primary_industry="同行", ret20=20 - i,
                             trend_online=int(i in (0, 1)), industry_peers=6,
                             industry_peer_trend_pct=20, market_trend_pct=10,
                             industry_peer_trend_delta_pp=1,
                             industry_ex_top2_trend_pct=20, industry_ret5_ex_market=1,
                             ret20_ex_industry=1))
        emotion.enrich_stocks(rows, detail, market)
        self.assertEqual(rows[0]["axis_group"], "情绪活跃·趋势在线")
        self.assertEqual(rows[1]["axis_group"], "趋势在线·情绪平稳")
        self.assertEqual(rows[2]["axis_group"], "趋势未在线·情绪平稳")
        self.assertIn("20日领涨", rows[0]["roles"])
        self.assertIn("情绪核心候选", rows[0]["roles"])
        self.assertNotEqual(rows[0]["emotion_assist"], "共振扩散")

    def test_trend_assist_excludes_self_and_top_two(self):
        codes, _, _ = self.sample()
        metrics = {c: dict(above20=1, trend_online=int(i < 3),
                           trend_online_prev=int(i < 2), ret5=10 - i,
                           ret20=20 - i) for i, c in enumerate(codes)}
        context = strength.industry_context(metrics, {c: "同行" for c in codes})
        self.assertAlmostEqual(context[codes[0]]["industry_peer_trend_pct"], 200 / 6, places=2)
        self.assertEqual(context[codes[0]]["industry_ex_top2_trend_pct"], None)
        # 再添一只同伴，剔除前两名后仍有5只，可给出稳健广度。
        metrics["600008"] = dict(above20=1, trend_online=0, trend_online_prev=0, ret5=0, ret20=0)
        context = strength.industry_context(metrics, {c: "同行" for c in metrics})
        self.assertEqual(context[codes[0]]["industry_ex_top2_trend_pct"], 0)

    def test_emotion_expansion_requires_more_participants_than_yesterday(self):
        row = dict(code="600001", primary_industry="同行", ret20=10,
                   trend_online=0, industry_peers=6)
        evidence = dict(emotion_strong=True, emotion_peer_count=6,
                        emotion_peer_comparable=6, emotion_peer_active_pct=50,
                        emotion_peer_limit=2, emotion_peer_yesterday_limit=2)
        market = {"active_count": 1, "traded": 10}
        emotion.enrich_stocks([row], {row["code"]: evidence}, market)
        self.assertNotEqual(row["emotion_assist"], "共振扩散")
        evidence["emotion_peer_yesterday_limit"] = 1
        emotion.enrich_stocks([row], {row["code"]: evidence}, market)
        self.assertEqual(row["emotion_assist"], "共振扩散")

    def test_weak_stock_is_not_called_industry_core(self):
        row = dict(code="600001", primary_industry="同行", ret20=30, ret5=-1,
                   ret5_ex_industry=3, stock_strength_percentile=20,
                   trend_online=1, industry_peers=8, industry_peer_trend_pct=20,
                   market_trend_pct=40, industry_peer_trend_delta_pp=0,
                   industry_ex_top2_trend_pct=20, industry_ret5_ex_market=-1)
        emotion.enrich_stocks([row], {}, {"active_count": 0, "traded": 10})
        self.assertEqual(row["industry_trend_state"], "同行偏弱")
        self.assertEqual(row["trend_assist"], "助攻不明确")
        row["trend_online"] = 0
        emotion.enrich_stocks([row], {}, {"active_count": 0, "traded": 10})
        self.assertEqual(row["trend_assist"], "助攻不明确")

    def test_industry_contraction_does_not_hide_stock_lead(self):
        row = dict(code="600001", primary_industry="同行", ret20=30, ret5=5,
                   ret5_ex_industry=3, stock_strength_percentile=80,
                   trend_online=1, industry_peers=8, industry_peer_trend_pct=20,
                   market_trend_pct=40, industry_peer_trend_delta_pp=-5,
                   industry_ex_top2_trend_pct=20, industry_ret5_ex_market=-1)
        emotion.enrich_stocks([row], {}, {"active_count": 0, "traded": 10})
        self.assertEqual(row["industry_trend_state"], "收缩")
        self.assertEqual(row["industry_stock_relation"], "个股相对领先")
        self.assertEqual(row["trend_assist"], "个股相对领先｜行业收缩")


if __name__ == "__main__":
    unittest.main()
