"""个股强度的方向、等长变化、独立性和真实历史记录。"""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import stock_strength
import strength


def bars(n=75, slope=0.1):
    start = datetime(2026, 1, 1)
    out = []
    for i in range(n):
        price = 20 + i * slope
        out.append(dict(date=(start + timedelta(days=i)).strftime("%Y-%m-%d"),
                        open=price, close=price, high=price + 0.1,
                        low=price - 0.1, volume=10_000_000, amount=0))
    return out


class StockStrengthTest(unittest.TestCase):
    def test_falling_path_has_negative_efficiency(self):
        m = strength.day_metrics(bars(slope=-0.1))
        self.assertLess(m["path_eff20"], 0)
        self.assertLess(stock_strength.raw_metrics(bars(slope=-0.1))["path_eff20"], 0)

    def test_trend_online_can_have_weak_recent_return(self):
        series = bars()
        for bar, price in zip(series[-5:], (26.9, 26.88, 26.86, 26.84, 26.82)):
            bar.update(open=price, close=price, high=price + 0.1, low=price - 0.1)
        m = strength.day_metrics(series)
        self.assertTrue(m["trend_online"])
        self.assertLess(m["ret5"], 0)

    def test_volume_spike_without_price_gain_is_penalty_evidence(self):
        series = bars(slope=0.02)
        for bar in series[-2:]:
            bar["volume"] = 40_000_000
            bar["high"] = bar["close"] + 0.5
        self.assertTrue(stock_strength.raw_metrics(series)["volume_spike_stall"])

    def test_missing_prior_record_stays_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(stock_strength, "_daily_path", side_effect=lambda day: Path(tmp) / f"{day}.json"):
                rows = [{"code": "600001", "stock_strength_percentile": 75.0}]
                stock_strength.attach_history(rows, "2026-09-22", "2026-09-16")
                self.assertIsNone(rows[0]["strength_delta1"])
                self.assertIsNone(rows[0]["strength_delta5"])
                (Path(tmp) / "2026-09-22.json").write_text(
                    json.dumps({"version": stock_strength.VERSION, "stocks": {"600001": 70.0}}), encoding="utf-8")
                stock_strength.attach_history(rows, "2026-09-22", "2026-09-16")
                self.assertEqual(rows[0]["strength_delta1"], 5.0)
                self.assertIsNone(rows[0]["strength_delta5"])

    def test_missing_peer_excess_never_changes_attack_score(self):
        series = {str(i): bars(slope=0.04 + i * 0.06) for i in range(3)}
        metrics = {c: strength.day_metrics(v) for c, v in series.items()}
        with_peers = {c: {"ret5_ex_industry": float(i)} for i, c in enumerate(series)}
        without_peers = {c: {"ret5_ex_industry": None} for c in series}
        a, _ = stock_strength.score(metrics, with_peers, series)
        b, _ = stock_strength.score(metrics, without_peers, series)
        self.assertEqual({c: r["stock_strength_score"] for c, r in a.items()},
                         {c: r["stock_strength_score"] for c, r in b.items()})

    def test_current_drawdown_distinct_from_old_repair(self):
        series = bars(slope=0)
        series[-5]["close"] = 20
        series[-4]["close"] = 5
        series[-3]["close"] = 25
        series[-2]["close"] = 30
        series[-1]["close"] = 25
        for bar in series[-5:]:
            bar["high"], bar["low"] = bar["close"] + .1, bar["close"] - .1
        data = stock_strength.raw_metrics(series)
        self.assertEqual(data["drawdown_repair_pct"], 100)
        self.assertLess(data["current_drawdown_pct"], -10)

    def test_daily_history_is_immutable_and_keeps_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "2026-09-23.json"
            with patch.object(stock_strength, "_daily_path", return_value=path):
                row = {"code": "600001", "stock_strength_percentile": 75.0,
                       "stock_strength_score": 65.0,
                       "stock_strength_parts": {"attack": 70.0},
                       "stock_strength_evidence": {"attack": "原始证据"},
                       "stock_strength_motion": "增强", "ret5": 3, "ret20": 10,
                       "primary_industry": "同行", "ret5_ex_industry": 2,
                       "stock_strength_coverage": "同行超额可参考"}
                snap = {"strength_model": {"asof": "2026-09-23", "strength_reference_count": 1},
                        "generated_at": "2026-09-24 10:00", "stocks": [row]}
                stock_strength.save_daily(snap)
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["stocks"]["600001"]["evidence"]["attack"], "原始证据")
                row["stock_strength_percentile"] = 30
                stock_strength.save_daily(snap)
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), saved)


if __name__ == "__main__":
    unittest.main()
