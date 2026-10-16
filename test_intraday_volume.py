"""回归：盘中量价辅助项只记录已发生的累计量，不外推全天成交量。"""
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

import config
import factors


class _MarketClock:
    @classmethod
    def now(cls):
        return datetime(2026, 9, 28, 10, 0)


class IntradayVolumeTests(unittest.TestCase):
    def test_partial_bar_volume_and_amount_are_not_projected(self):
        today = "2026-09-28"
        start = datetime(2026, 5, 31)
        bars = []
        for i in range(config.RISK_GATE.get("min_trading_days", 120)):
            day = (start + timedelta(days=i)).strftime("%Y-%m-%d")
            close = 100.0 + i * 0.05
            bars.append({"date": day, "open": close - 0.05, "high": close + 0.2,
                         "low": close - 0.2, "close": close,
                         "volume": 1000.0, "amount": 0.0})
        bars[-1]["date"] = today
        bars[-1]["volume"] = 100.0
        quote = {"price": bars[-1]["close"], "change_pct": 0.0,
                 "high": bars[-1]["high"], "low": bars[-1]["low"],
                 "turnover_pct": 1.0, "amount_wan": 100.0,
                 "vol_ratio": 1.0, "limit_pct": 10.0,
                 "board_type": "sh_main", "list_days": 1000}
        with patch.object(factors, "datetime", _MarketClock):
            row = factors.stock_raw_metrics("600001", bars, quote)
        self.assertIsNotNone(row)
        self.assertEqual(1, row["vol_partial"])
        self.assertAlmostEqual(0.1, row["vr"])
        self.assertAlmostEqual(0.1, row["vol_ratio5"])
        self.assertAlmostEqual(config.bar_amount_wan(bars[-1]), row["amt_today_wan"])


if __name__ == "__main__":
    unittest.main()
