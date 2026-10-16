"""回归：21根对齐日线只核验趋势；25根完整日线才满足核心评分窗口。"""
from datetime import date, timedelta
import unittest

import coverage


def _trading_days(end, count):
    days = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    return list(reversed(days))


class CoverageHistoryTests(unittest.TestCase):
    @staticmethod
    def _valid_bars(calendar):
        return [{"date": day, "open": 10 + i * .1, "high": 10.2 + i * .1,
                 "low": 9.9 + i * .1, "close": 10 + i * .1, "volume": 100000}
                for i, day in enumerate(calendar)]

    def test_21_aligned_days_verify_trend_but_wait_for_daily_score_history(self):
        calendar = _trading_days(date(2026, 7, 31), 61)
        bars = [{"date": day, "close": float(100 + i)}
                for i, day in enumerate(calendar[-21:])]
        rows, stats = coverage.build(
            {"600001": {"code": "600001", "name": "测试股", "price": 120.0}},
            {"600001": bars}, set(), {}, {}, calendar[-1], calendar)
        row = rows[0]
        self.assertEqual(1, row["trend_online"])
        self.assertTrue(row["watch_candidate"])
        self.assertEqual("最近21日均线", row["trend_basis"])
        self.assertEqual("趋势可核验、强度待评分", row["daily_strength_status"])
        self.assertIsNone(row.get("stock_strength_score"))
        self.assertEqual(1, stats["trend_online_outside"])
        self.assertEqual(25, row['daily_core_required_bars'])
        self.assertEqual(calendar[-25:-21], row['daily_core_missing_dates'])
        self.assertIn('25', row['reason_text'])

    def test_fewer_than_21_days_do_not_claim_a_verifiable_trend(self):
        calendar = _trading_days(date(2026, 7, 31), 61)
        bars = [{"date": day, "close": float(100 + i)}
                for i, day in enumerate(calendar[-20:])]
        rows, _ = coverage.build(
            {"600002": {"code": "600002", "name": "样本股", "price": 120.0}},
            {"600002": bars}, set(), {}, {}, calendar[-1], calendar)
        self.assertIsNone(rows[0]["trend_online"])
        self.assertEqual("日线不足", rows[0]["daily_strength_status"])

    def test_no_trade_is_primary_reason_even_when_close_bar_is_invalid(self):
        calendar = _trading_days(date(2026, 9, 29), 26)
        bars = self._valid_bars(calendar)
        bars[-1]["volume"] = 0
        rows, stats = coverage.build(
            {"600293": {"code": "600293", "name": "三峡新材", "price": 13,
                        "amount_wan": 0, "volume_shou": 0}},
            {"600293": bars}, set(), {"600293": "no_trade"}, {},
            calendar[-1], calendar)
        row = rows[0]
        self.assertEqual("no_trade", row["reason"])
        self.assertEqual("invalid", row["data_reason"])
        self.assertEqual("no_trade", row["trade_status"])
        self.assertEqual("当日无成交，暂停当前评分", row["daily_strength_status"])
        self.assertFalse(row["watch_candidate"])
        self.assertIn("日线价格或成交量异常", row["reason_text"])
        self.assertEqual({"no_trade": 1}, stats["reasons"])

    def test_recovered_trade_waits_for_aligned_completed_window(self):
        calendar = _trading_days(date(2026, 9, 28), 27)
        bars = self._valid_bars(calendar)
        bars[-2]["volume"] = 0
        quote = {"600293": {"code": "600293", "name": "三峡新材", "price": 13,
                            "amount_wan": 500, "volume_shou": 200}}
        rows, _ = coverage.build(quote, {"600293": bars}, set(), {}, {},
                                 calendar[-1], calendar,
                                 previous_rows=[{"code": "600293", "trade_status": "no_trade"}])
        row = rows[0]
        self.assertEqual("trade_recovered_wait_daily", row["reason"])
        self.assertEqual("invalid", row["data_reason"])
        self.assertEqual("恢复成交，核心日线待对齐", row["daily_strength_status"])
        self.assertFalse(row["watch_candidate"])


if __name__ == "__main__":
    unittest.main()
