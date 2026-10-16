"""统一盘中价格口径的构造场景验收。"""
from datetime import datetime, timedelta
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import close_monitor
import intraday
import scoring


def prior_days(count=21):
    out = []
    day = datetime(2026, 8, 28)
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day.strftime("%Y-%m-%d"))
        day += timedelta(days=1)
    return out


def history(closes=None, basis="qfq", source="tencent_qfqday"):
    days = prior_days()
    closes = list(closes or [100.0] * len(days))
    return [{"date": day, "open": close, "high": close + .1,
             "low": close - .1, "close": close,
             "price_basis": basis, "price_basis_source": source}
            for day, close in zip(days, closes)]


def quote(last_close=99.0, price=99.2, at="2026-09-28 09:32:00"):
    return {"quote_at": at, "price": price, "open": 99.0,
            "high": max(price, 99.3), "low": 98.99,
            "last_close": last_close,
            "last_close_semantics": "previous_trade_day_raw_close",
            "price_basis": "raw", "price_basis_source": "tencent_realtime_quote",
            "change_pct": (price / last_close - 1) * 100 if last_close else None,
            "amount_wan": 1000.0, "volume_shou": 10000,
            "board_type": "sh_main", "limit_pct": 10.0,
            "limit_up": 108.9, "limit_down": 89.1}


def minute_pair(day="2026-09-28", threshold=99.0, current=99.2):
    return [
        {"at": day + " 09:31", "open": threshold, "high": threshold + .03,
         "low": threshold - .02, "close": threshold - .01, "source": "新浪1分钟OHLC",
         "price_basis": "raw", "price_basis_source": "sina_1m_unadjusted"},
        {"at": day + " 09:32", "open": current - .02, "high": current,
         "low": current - .04, "close": current, "source": "新浪1分钟OHLC",
         "price_basis": "raw", "price_basis_source": "sina_1m_unadjusted"},
    ]


class PriceBasisAcceptanceTests(unittest.TestCase):
    DAY = "2026-09-28"

    def context(self, q=None, bars=None, day=None, calendar=None):
        q = dict(q or quote())
        bars = bars or history()
        calendar = calendar or [bar["date"] for bar in bars]
        return intraday.align_price_basis(
            q, bars, calendar, observation_day=day or self.DAY,
            quote_at=q.get("quote_at"))

    def test_requested_99_scale_ma10_example(self):
        original = history()
        result = self.context(quote(), original)
        self.assertTrue(result["valid"], result["reason"])
        self.assertAlmostEqual(.99, result["scale_factor"], places=12)
        self.assertTrue(all(bar["close"] == 99.0 for bar in result["aligned_bars"][-9:]))
        self.assertAlmostEqual(99.02, result["provisional_ma"][10], places=12)
        self.assertGreater(99.2, result["provisional_ma"][10])
        self.assertIs(True, intraday.price_at_or_above_line(
            99.2, result["thresholds"][10]))
        self.assertAlmostEqual(.198, result["atr20"], places=12)
        self.assertEqual(100.0, original[-1]["close"], "原始前复权历史不得被改写")

    def test_small_positive_and_negative_gaps_use_explicit_conversion(self):
        bars = history()
        for last_close in (100.2, 99.8):
            with self.subTest(last_close=last_close):
                q = quote(last_close=last_close, price=last_close + .2)
                result = self.context(q, bars)
                self.assertTrue(result["valid"], result["reason"])
                self.assertAlmostEqual(last_close / 100, result["scale_factor"], places=12)
                self.assertAlmostEqual(last_close, result["aligned_bars"][-1]["close"], places=12)
                self.assertTrue(intraday.price_at_or_above_line(
                    q["price"], result["thresholds"][10]))
                self.assertAlmostEqual(.2 * result["scale_factor"], result["atr20"], places=12)

    def test_quote_day_and_per_stock_timestamp_must_be_confirmed(self):
        no_time = quote()
        no_time["quote_at"] = None
        self.assertIn("逐股报价日期或时间缺失", self.context(no_time)["reason"])
        wrong_day = quote(at="2026-09-29 09:32:00")
        self.assertIn("与观察日2026-09-28不一致",
                      self.context(wrong_day, day="2026-09-28")["reason"])

    def test_same_raw_basis_keeps_scale_and_does_not_infer_from_five_percent(self):
        bars = history(basis="raw", source="tencent_day")
        q = quote(last_close=100.0, price=100.2)
        result = self.context(q, bars)
        self.assertTrue(result["valid"], result["reason"])
        self.assertEqual(1.0, result["scale_factor"])
        q["price_basis_source"] = "unknown_quote"
        self.assertIn("来源或复权方式未确认", self.context(q, bars)["reason"])

    def test_missing_quote_close_history_source_and_invalid_gap_wait(self):
        q = quote()
        no_close = dict(q, last_close=None)
        self.assertIn("报价昨收缺失", self.context(no_close)["reason"])
        unknown_source = dict(q, price_basis_source=None)
        self.assertIn("报价来源或复权方式未确认", self.context(unknown_source)["reason"])
        qfq_unverified = history(basis=None, source=None)
        self.assertIn("来源字段缺失", self.context(q, qfq_unverified)["reason"])
        invalid_history = history()
        invalid_history[-1]["close"] = 0
        self.assertIn("历史窗口含缺失、零值或异常OHLC价格",
                      self.context(q, invalid_history)["reason"])
        too_far = dict(q, last_close=94.0)
        self.assertIn("超过5.0%异常限制", self.context(too_far)["reason"])

    def test_last_history_bar_must_be_previous_trade_day_not_calendar_yesterday(self):
        bars = history()
        calendar = [bar["date"] for bar in bars] + ["2026-09-28"]
        q = quote(at="2026-09-29 10:00:00")
        result = self.context(q, bars, day="2026-09-29", calendar=calendar)
        self.assertFalse(result["valid"])
        self.assertIn("不是报价日前一交易日2026-09-28", result["reason"])

    def test_quote_day_bar_is_excluded_even_if_daily_close_was_written(self):
        bars = history()
        calendar = [bar["date"] for bar in bars] + ["2026-09-28"]
        with_today = bars + [{"date": "2026-09-28", "open": 999.0, "high": 1000.0,
                              "low": 998.0, "close": 999.0,
                              "price_basis": "qfq", "price_basis_source": "tencent_qfqday"}]
        q = quote(at="2026-09-28 09:32:00")
        result = self.context(q, with_today, day="2026-09-28", calendar=calendar)
        self.assertTrue(result["valid"], result["reason"])
        self.assertEqual("2026-09-25", result["last_history_date"])
        self.assertEqual(20, len(result["aligned_bars"]))
        self.assertTrue(all(bar["date"] < "2026-09-28" for bar in result["aligned_bars"]))
        self.assertAlmostEqual(99.0, result["aligned_bars"][-1]["close"], places=12)

    def test_window_hole_and_duplicate_date_wait(self):
        bars = history()
        missing = bars[:10] + bars[11:]
        full_calendar = [bar["date"] for bar in bars]
        self.assertIn("历史窗口缺口",
                      self.context(quote(), missing, calendar=full_calendar)["reason"])
        duplicate = bars + [dict(bars[-1])]
        self.assertIn("历史K线日期重复", self.context(quote(), duplicate)["reason"])

    def test_equal_threshold_holds_and_unrounded_tick_below_fails(self):
        q = quote(last_close=100, price=100)
        result = self.context(q, history(basis="raw", source="tencent_day"))
        line = result["thresholds"][10]
        self.assertIs(True, intraday.price_at_or_above_line(line, line))
        self.assertIs(False, intraday.price_at_or_above_line(line - .0001, line))

    def test_minute_bars_need_verified_quote_scale_and_source(self):
        result = self.context()
        valid = intraday.align_minute_bars(result, minute_pair())
        self.assertTrue(valid["valid"], valid["reason"])
        invalid_bars = minute_pair()
        invalid_bars[0]["price_basis_source"] = "unknown"
        self.assertIn("来源或复权方式混杂",
                      intraday.align_minute_bars(result, invalid_bars)["reason"])

    def test_price_scale_and_near_line_card_share_ma_distance_and_reclaim(self):
        for last_close in (100.2, 99.8):
            with self.subTest(quote_last_close=last_close):
                codes = [f"60000{i}" for i in range(5)]
                bars = {code: history() for code in codes}
                quotes = {}
                for code in codes:
                    q = quote(last_close=last_close, price=last_close + .2)
                    q.update(open=last_close, high=last_close + .2, low=last_close - .02)
                    quotes[code] = q
                rows = [{"code": code, "name": code, "trend_online": True,
                         "signal_date": "2026-09-25", "signal_close": 100.0,
                         "ma5": 100.0, "ma10": 100.0, "ma20": 100.0,
                         "stock_strength_score": 80.0, "primary_industry": "验收行业",
                         "risk_notes": []} for code in codes]
                at = datetime(2026, 9, 28, 9, 32)
                with tempfile.TemporaryDirectory() as temp, \
                        patch.object(intraday, "HISTORY_DIR", Path(temp)), \
                        patch.object(intraday, "_latest_record", return_value=None):
                    meta = intraday.enrich(rows, [], quotes, bars, codes, captured_at=at,
                                           session="早盘", save_reference=False,
                                           trading_calendar=[bar["date"] for bar in bars[codes[0]]])
                contexts = meta.pop("_price_contexts")
                by_code = {row["code"]: row for row in rows}
                row = by_code[codes[0]]
                context = contexts[codes[0]]
                self.assertAlmostEqual(last_close / 100, context["scale_factor"], places=12)
                self.assertAlmostEqual(last_close + .02, row["intraday_ma10_exact"], places=12)
                self.assertAlmostEqual(row["intraday_ma10_exact"], context["provisional_ma"][10], places=12)
                self.assertIs(True, intraday.price_at_or_above_line(
                    quotes[codes[0]]["price"], row["intraday_ma10_trigger_price"]))
                self.assertTrue(row["intraday_ma10_current_holds"])
                self.assertTrue(row["intraday_ma10_day_low_breached"])

                snap = {"session": "早盘", "generated_at": at.isoformat(sep=" "),
                        "strength_model": {"asof": "2026-09-25"}, "stocks": rows}
                minutes = {code: minute_pair(
                    self.DAY, threshold=last_close, current=last_close + .2) for code in codes}
                with tempfile.TemporaryDirectory() as temp, \
                        patch.object(close_monitor, "TREND_DIRS",
                                     {p: Path(temp) / f"ma{p}" for p in close_monitor.LINES}), \
                        patch.object(close_monitor, "_get_minutes", return_value=minutes):
                    close_monitor._attach_trend_observations(
                        snap, quotes, bars, self.DAY, contexts,
                        [bar["date"] for bar in bars[codes[0]]])
                near = snap["trend_ma10_observation"]
                item = next((entry for key in ("main_rows", "reclaim_rows")
                             for entry in near[key] if entry["code"] == codes[0]), None)
                self.assertIsNotNone(item)
                self.assertAlmostEqual(row["intraday_ma10"], item["provisional_ma"], places=4)
                self.assertAlmostEqual(row["intraday_distance_ma10_pct"], item["distance_pct"], places=3)
                self.assertEqual(row["intraday_ma10_trigger_price"], item["threshold_price"])
                self.assertEqual("15分钟内收回", item["status"])
                self.assertEqual("快速收回", row["intraday_ma10_minute_state"])
                self.assertIn("现价守住", row["intraday_ma10_minute_note"])

    def test_missing_close_keeps_quote_score_but_blocks_ma_candidates_and_risk(self):
        codes = [f"60000{i}" for i in range(5)]
        quotes = {code: quote(last_close=99, price=99.2) for code in codes}
        quotes[codes[0]]["last_close"] = None
        rows = [{"code": code, "name": code, "trend_online": True,
                 "signal_date": "2026-09-25", "signal_close": 100.0,
                 "ma5": 100.0, "ma10": 100.0, "ma20": 100.0,
                 "stock_strength_score": 80.0, "risk_notes": []} for code in codes]
        histories = {code: history() for code in codes}
        at = datetime(2026, 9, 28, 9, 32)
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(intraday, "HISTORY_DIR", Path(temp)), \
                patch.object(intraday, "_latest_record", return_value=None):
            intraday.enrich(rows, [], quotes, histories, codes, captured_at=at,
                            session="早盘", save_reference=False)
        row = next(row for row in rows if row["code"] == codes[0])
        self.assertIsNone(row["intraday_trend_ok"])
        self.assertIn("报价昨收缺失", row["intraday_price_basis_reason"])
        self.assertEqual("待核验", row["intraday_risk_level"])
        self.assertFalse(row["current_strong_candidate"])
        self.assertFalse(row["startup_candidate"])
        self.assertIsNotNone(row["intraday_open_return_pct"])
        self.assertIsNotNone(row["intraday_score"])

    def test_same_or_older_quote_time_does_not_emit_transition(self):
        old = ["600000", "2026-09-28 09:32:00", 99.1, .1, 60, "观察",
               "低", 99, 99, 98, False, 80, True] + [None] * 17
        old[28] = True
        old[29] = 99.0
        event, state = intraday._transition_from_previous(
            old, datetime(2026, 9, 28, 9, 32), 98.9, 99.0)
        self.assertIsNone(event)
        self.assertIn("未前进", state)

    def test_old_rule_version_history_is_not_compared_with_new_basis(self):
        codes = [f"60000{i}" for i in range(5)]
        quotes = {code: quote() for code in codes}
        rows = [{"code": code, "name": code, "trend_online": True,
                 "signal_date": "2026-09-25", "signal_close": 100.0,
                 "ma5": 100.0, "ma10": 100.0, "ma20": 100.0,
                 "stock_strength_score": 80.0, "risk_notes": []} for code in codes]
        legacy_row = [codes[0], "2026-09-28 09:31:00", 99.1, .1, 60, "观察",
                      "低", 99, 99, 98, False, 80, True] + [None] * 17
        old = {"model_version": "盘中观察初版3",
               "rule_version": "盘中规则2026-09-29.4",
               "price_basis_version": None,
               "sample_hash": intraday._hash_codes(codes), "rows": [legacy_row]}
        at = datetime(2026, 9, 28, 9, 32)
        histories = {code: history() for code in codes}
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(intraday, "HISTORY_DIR", Path(temp)), \
                patch.object(intraday, "_latest_record", return_value=old):
            meta = intraday.enrich(rows, [], quotes, histories, codes,
                                   captured_at=at, session="早盘", save_reference=False)
        row = next(item for item in rows if item["code"] == codes[0])
        self.assertFalse(meta["sample_changed_since_previous"])
        self.assertIsNone(row["intraday_transition"])
        self.assertEqual("首轮或无可比报价", row["intraday_delta_state"])

    def test_auction_snapshot_clears_previous_day_quote_scale_ma(self):
        fixed_at = datetime(2026, 9, 30, 9, 20)

        class FrozenClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_at

        previous = {
            "strength_model": {"asof": "2026-09-29"},
            "intraday_model": {"asof": "2026-09-29", "version": intraday.VERSION},
            "stocks": [{"code": "600000", "name": "样本股", "trend_online": True,
                        "stock_strength_score": 80.0, "intraday_price_basis_comparable": True,
                        "intraday_trend_state": "盘中趋势成立", "intraday_trend_ok": True,
                        "intraday_risk_level": "低", "intraday_ma10": 99.02,
                        "intraday_ma10_exact": 99.02, "daily_ma10_fixed": 99.0,
                        "intraday_distance_ma10_pct": 0.18,
                        "intraday_ma10_trigger_price": 99.0,
                        "current_strong_candidate": True}],
            "coverage_catalog": [],
        }
        auction_quote = {"ts": "2026-09-30 09:20:00", "price": 100.0,
                         "last_close": 99.0, "change_pct": 1.01}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(scoring, "datetime", FrozenClock), \
                patch.object(scoring.df, "build_pool", return_value={"600000": {}}), \
                patch.object(scoring.df, "realtime_quotes", return_value={"600000": auction_quote}), \
                patch.object(scoring.config, "SNAPSHOT_JSON", Path(tmp) / "snapshot.json"):
            snap = scoring._auction_snapshot(previous, "quick", fixed_at)

        row = snap["stocks"][0]
        self.assertEqual(80.0, row["stock_strength_score"])
        self.assertFalse(row["intraday_price_basis_comparable"])
        self.assertEqual(intraday.PRICE_BASIS_VERSION, row["intraday_price_basis_version"])
        self.assertIsNone(row["intraday_trend_ok"])
        self.assertIn("均线待核验", row["intraday_trend_state"])
        self.assertEqual("待核验", row["intraday_risk_level"])
        self.assertFalse(row["current_strong_candidate"])
        self.assertIsNone(row["intraday_transition"])
        for key in ("intraday_ma10", "intraday_ma10_exact", "daily_ma10_fixed",
                    "intraday_distance_ma10_pct", "intraday_ma10_trigger_price"):
            self.assertIsNone(row[key], key)
        for period in close_monitor.LINES:
            observation = snap[f"trend_ma{period}_observation"]
            self.assertEqual(intraday.PRICE_BASIS_VERSION, observation["price_basis_version"])
            self.assertEqual([], observation["pending_rows"])
            self.assertEqual(0, observation["pending_count"])


if __name__ == "__main__":
    unittest.main()
