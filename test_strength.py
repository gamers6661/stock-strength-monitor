"""关键行为检查：完成日线、去自身、风险与排名分离、成交延迟。"""
import copy
from datetime import datetime, timedelta
import unittest

import strength
import intraday
from fund_confirmation import _summarize
from replay_strength import trade_path


def bars(n=75, slope=0.1):
    start = datetime(2026, 1, 1)
    out = []
    for i in range(n):
        price = 10 + i * slope
        out.append(dict(date=(start + timedelta(days=i)).strftime("%Y-%m-%d"), open=price,
                        close=price, high=price + 0.05, low=price - 0.05, volume=20_000_000, amount=0))
    return out


class StrengthTest(unittest.TestCase):
    def test_core_window_is_25_and_old_gaps_only_disable_long_reference(self):
        ks = bars()
        calendar = [b['date'] for b in ks]
        full = strength.day_metrics(ks, calendar)
        short = strength.day_metrics(ks[-25:], calendar)
        old_gap = strength.day_metrics(ks[:20] + ks[21:], calendar)
        optional = {'ret60', 'ma60', 'above60', 'position60', 'reference60_status', 'bars'}
        for key in set(full) - optional:
            self.assertEqual(full[key], short[key], key)
            self.assertEqual(full[key], old_gap[key], key)
        self.assertIsNone(short['ret60'])
        self.assertIsNone(old_gap['ma60'])
        self.assertIsNone(strength.day_metrics(ks[-24:]))
        self.assertEqual(strength.core_window_issue(ks[:-2] + ks[-1:], calendar), 'unaligned')
        bad = copy.deepcopy(ks)
        bad[-5]['volume'] = 0
        self.assertIsNone(strength.day_metrics(bad, calendar))
        self.assertEqual(strength.core_window_issue(bad, calendar), 'invalid')

    def test_25_day_stock_passes_raw_and_completed_pipeline(self):
        import config
        import factors
        ks = bars()
        short = ks[-25:]
        quote = {'price': short[-1]['close'], 'amount_wan': 1000}
        self.assertEqual(config.RISK_GATE['min_trading_days'], strength.CORE_BARS)
        source = factors.stock_raw_metrics('short', short, quote)
        self.assertIsNotNone(source)
        rows, meta = strength.build([source], {'base1':ks, 'base2':ks, 'short':short}, {}, datetime(2026,5,1,16))
        self.assertEqual([r['code'] for r in rows], ['short'])
        self.assertEqual(meta['core_required_bars'], 25)
        self.assertIsNotNone(rows[0]['stock_strength_score'])
        self.assertIsNone(rows[0]['ret60'])

    def test_trend_uses_ma5_10_20_and_rising_ma20(self):
        m = strength.day_metrics(bars())
        self.assertTrue(m['trend_aligned'])
        self.assertTrue(m['trend_online'])
        self.assertTrue(m['ma5'] > m['ma10'] > m['ma20'] > m['ma20_prev'])

    def test_low_historical_amount_does_not_remove_trend_stock(self):
        ks = bars()
        for bar in ks:
            bar['volume'] = 1000
        row = dict(code='low_amount', name='低成交额样本', price=ks[-1]['close'])
        ranked, _ = strength.build([row], {'low_amount': ks}, {}, datetime(2026, 5, 1, 16))
        self.assertEqual([r['code'] for r in ranked], ['low_amount'])
        self.assertTrue(ranked[0]['trend_online'])
        self.assertLess(ranked[0]['amt_med20_wan'], 10000)

    def test_intraday_ma10_dip_can_reclaim_or_fail(self):
        good = bars()
        line = sum(b['close'] for b in good[-10:]) / 10
        good[-1]['low'] = line - 0.2
        m = strength.day_metrics(good)
        self.assertEqual(m['touch_state'], '回踩反弹')
        bad = bars()
        bad[-1].update(open=17.1, close=16.8, high=17.2, low=16.7)
        m = strength.day_metrics(bad)
        self.assertTrue(m['trend_aligned'])
        self.assertFalse(m['trend_online'])
        self.assertEqual(m['touch_state'], '回踩失守')

    def test_fund_windows_require_same_market_dates(self):
        dates = [f'2026-09-{i:02d}' for i in range(1, 11)]
        rows = [{'date': d, 'main_net': 1e8} for d in dates]
        self.assertEqual(_summarize(rows, dates), {3: 3.0, 5: 5.0, 10: 10.0})
        self.assertIsNone(_summarize(rows[:-1], dates)[3])

    def test_breakout_excludes_signal_day_high(self):
        ks = bars()
        ks[-1].update(close=20, open=19, high=21, low=18)
        m = strength.day_metrics(ks)
        self.assertTrue(m["broke20"])
        self.assertEqual(m["ph20"], max(b["high"] for b in ks[-21:-1]))

    def test_intraday_spike_does_not_change_rank_or_trigger(self):
        ks = bars()
        today = datetime.strptime(ks[-1]["date"], "%Y-%m-%d").replace(hour=11)
        stock = dict(code="a", name="A", price=ks[-2]["close"])
        first, _ = strength.build([stock], {"a": ks}, {}, now=today)
        other = copy.deepcopy(ks)
        other[-1].update(open=100, close=150, low=90, high=160)
        second, _ = strength.build([stock], {"a": other}, {}, now=today)
        for key in ("ret20", "score", "entry_state", "signal_date"):
            self.assertEqual(first[0][key], second[0][key])
        self.assertEqual(first[0]["signal_date"], ks[-2]["date"])

    def test_breadth_excludes_self_and_does_not_impute(self):
        m = {str(i): {"above20": int(i == 0)} for i in range(6)}
        industry = {c: "X" for c in m}
        context = strength.industry_context(m, industry)
        self.assertEqual(context["0"]["industry_breadth"], 0)
        self.assertEqual(context["1"]["industry_breadth"], 20)
        self.assertIsNone(strength.industry_context({"a": {"above20": 1}}, {"a": "X"})["a"]["industry_breadth"])
        self.assertIsNone(strength.industry_context(m, {})["0"]["industry_breadth"])

    def test_live_overheat_never_changes_completed_day_strength(self):
        series = {str(i): bars(slope=0.05 + i * 0.03) for i in range(7)}
        for ks in series.values():
            for bar in ks:
                bar.update(price_basis="qfq", price_basis_source="tencent_qfqday")
        stocks = [dict(code=c, name=c, price=ks[-1]["close"]) for c, ks in series.items()]
        now = datetime.strptime(series["0"][-1]["date"], "%Y-%m-%d") + timedelta(days=1)
        now = now.replace(hour=10)
        industries = {c: "X" for c in series}
        a, _ = strength.build(stocks, series, industries, now)
        daily_scores = [(r["code"], r["stock_strength_score"]) for r in a]
        quotes = {}
        for code, ks in series.items():
            price = ks[-1]["close"] * (1.08 if code == "0" else 1.0)
            quotes[code] = {"price": price, "open": price,
                            "high": price + 0.5, "low": price - 0.5,
                            "change_pct": 8.0 if code == "0" else 0.2,
                            "last_close": ks[-1]["close"],
                            "price_basis": "raw", "price_basis_source": "tencent_realtime_quote",
                            "last_close_semantics": "previous_trade_day_raw_close",
                            "amount_wan": 1000, "quote_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                            "board_type": "sh_main", "limit_pct": 10.0,
                            "limit_up": price * 1.1, "limit_down": price * 0.9}
        intraday.enrich(a, [], quotes, series, list(series), captured_at=now,
                        session="早盘", save_reference=False)
        self.assertEqual(daily_scores, [(r["code"], r["stock_strength_score"]) for r in a])
        self.assertTrue(next(r for r in a if r["code"] == "0")["overheated"])

    def test_stale_or_invalid_bars_are_not_ranked(self):
        ks = bars()
        bad = copy.deepcopy(ks)
        bad[-1]["high"] = 0
        series = {"a": ks, "b": ks, "old": ks[:-2], "bad": bad}
        rows, meta = strength.build([dict(code=c, name=c) for c in series], series, {}, datetime(2026, 5, 1, 16))
        self.assertEqual({r["code"] for r in rows}, {"a", "b"})
        self.assertEqual(meta["dropped"]["stale"], 1)
        self.assertEqual(meta["dropped"]["invalid"], 1)

    def test_trade_uses_next_open_and_defers_locked_exit(self):
        ks = bars(20, 0)
        dates = [b["date"] for b in ks]
        ks[1].update(open=10.5, close=10.5, high=10.6, low=10.4)
        ks[10].update(open=9, close=9, high=9, low=9)
        ks[11].update(open=9, close=9.1, high=9.2, low=8.9)
        result = trade_path({b["date"]: b for b in ks}, dates, 0)
        self.assertEqual(result["entry_price"], 10.5)
        self.assertEqual(result["exit_date"], dates[11])
        self.assertEqual(result["exit_delay"], 1)
        self.assertAlmostEqual(result["net_pct"], (9.1 / 10.5 - 1) * 100 - 0.3)

    def test_limit_open_is_not_assumed_fillable(self):
        ks = bars(20, 0)
        ks[1].update(open=11, close=11, high=11, low=11)
        self.assertEqual(trade_path({b["date"]: b for b in ks}, [b["date"] for b in ks], 0)["status"], "entry_limit")


if __name__ == "__main__":
    unittest.main()
