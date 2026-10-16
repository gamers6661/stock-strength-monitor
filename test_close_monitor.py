"""收盘名单与次日15分钟均线跟踪的确定性验收。"""
import tempfile
import unittest
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import close_monitor as cm


def minute_bars(start, minutes, low_at=0, recover_at=None, low=99, high=101):
    out = []
    for i in range(minutes):
        at = start + timedelta(minutes=i)
        close = high if recover_at is not None and i >= recover_at else (low if i >= low_at else high)
        out.append({"at": at.strftime("%Y-%m-%d %H:%M"), "open": close,
                    "close": close, "low": low if i == low_at else close, "high": high,
                    "price_basis": "raw",
                    "price_basis_source": "sina_1m_unadjusted"})
    return out


def completed_bars(closes=None):
    days = []
    day = datetime(2026, 8, 31)
    while len(days) < 20:
        if day.weekday() < 5:
            days.append(day.strftime("%Y-%m-%d"))
        day += timedelta(days=1)
    closes = list(closes or [100.0] * 20)
    out = []
    for day, close in zip(days, closes):
        close = float(close)
        out.append({"date": day, "open": close, "high": close + .1,
                    "low": close - .1, "close": close,
                    "price_basis": "qfq", "price_basis_source": "tencent_qfqday"})
    return out


def quote(price=101, last_close=100, low=99, quote_at="2026-09-28 09:50:00"):
    return {"price": price, "open": price, "low": low, "last_close": last_close,
            "quote_at": quote_at, "price_basis": "raw",
            "price_basis_source": "tencent_realtime_quote",
            "last_close_semantics": "previous_trade_day_raw_close"}


class CloseMonitorTests(unittest.TestCase):
    DAY = "2026-09-28"

    def test_close_board_uses_existing_qualification_and_score(self):
        snap = {"generated_at": self.DAY + " 15:10:00", "factor_model_version": "existing",
                "strength_model": {"asof": self.DAY, "strength_version": "existing"},
                "stocks": [
                    {"code": "000001", "name": "A", "persistent_strong": True, "stock_strength_score": 71},
                    {"code": "000002", "name": "B", "persistent_strong": False, "stock_strength_score": 99},
                    {"code": "000003", "name": "C", "persistent_strong": True, "stock_strength_score": 91},
                ]}
        board = cm.build_close_board(snap)
        self.assertEqual([s["code"] for s in board["stocks"]], ["000003", "000001"])
        self.assertEqual(board["factor_model_version"], "existing")

    def test_reclaim_within_15_trading_minutes_is_expected(self):
        start = datetime.fromisoformat(self.DAY + " 10:00")
        bars = minute_bars(start, 16, recover_at=15)
        result = cm._line_status(bars, 100, False, self.DAY + " 10:15")
        self.assertEqual(result["state"], "快速收回")
        self.assertEqual(result["event"]["minutes"], 15)

    def test_reclaim_after_15_minutes_preserves_damage(self):
        start = datetime.fromisoformat(self.DAY + " 10:00")
        bars = minute_bars(start, 17, recover_at=16)
        self.assertEqual(cm._line_status(bars, 100, False, self.DAY + " 10:16")["state"], "曾失守后收回")
        self.assertEqual(cm._line_status(bars[:16], 100, False, self.DAY + " 10:15")["state"], "15分钟内待确认")

    def test_prior_confirmed_breach_is_not_hidden_by_second_pending_dip(self):
        start = datetime.fromisoformat(self.DAY + " 10:00")
        bars = minute_bars(start, 17, recover_at=16)
        bars += minute_bars(datetime.fromisoformat(self.DAY + " 10:17"), 3,
                            low_at=0, recover_at=None)
        self.assertEqual(cm._line_status(bars, 100, False, self.DAY + " 10:19")["state"], "确认失守")

    def test_sina_end_of_minute_timestamp_uses_conservative_breach_time(self):
        bars = minute_bars(datetime.fromisoformat(self.DAY + " 10:00"), 16, recover_at=15)
        for bar in bars:
            bar["source"] = "新浪1分钟OHLC"
        self.assertEqual(cm._line_status(bars, 100, False, self.DAY + " 10:15")["state"], "曾失守后收回")

    def test_sina_ohlc_fallback_parses_only_requested_day(self):
        payload = '=([{"day":"2026-09-25 09:31:00","open":"100","high":"101","low":"99","close":"100"},'
        payload += '{"day":"2026-09-28 09:31:00","open":"100","high":"101","low":"99","close":"100"}]);'
        with patch.object(cm.df, "http_get", return_value=payload):
            bars = cm._sina_minute_bars("600519", self.DAY)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["at"], self.DAY + " 09:31")
        self.assertEqual(bars[0]["source"], "新浪1分钟OHLC")
        with patch.object(cm, "_MINUTE_SOURCE_PREF", "eastmoney"), \
             patch.object(cm, "_eastmoney_minute_bars", side_effect=OSError("source down")), \
             patch.object(cm, "_sina_minute_bars", return_value=bars):
            self.assertEqual(cm._minute_bars("600519", self.DAY), bars)

    def test_sina_0931_first_bar_can_confirm_fast_reclaim(self):
        completed = completed_bars()
        bars = minute_bars(datetime.fromisoformat(self.DAY + " 09:31"), 20,
                           recover_at=13)
        for bar in bars:
            bar["source"] = "新浪1分钟OHLC"
        row = cm._monitor_row({"code": "000001", "name": "A", "score": 80},
                              {"intraday_quote_fresh": True, "change_pct": 1},
                              quote(price=101, last_close=100, low=99,
                                    quote_at=self.DAY + " 09:50:00"),
                              bars, completed, self.DAY + " 09:50:00", "2026-09-25",
                              calendar=[bar["date"] for bar in completed])
        self.assertEqual(row["status"], "符合预期")
        self.assertEqual(row["lines"]["MA10"]["state"], "快速收回")

    def test_lunch_does_not_count_toward_15_minutes(self):
        start = datetime.fromisoformat(self.DAY + " 11:25")
        bars = minute_bars(start, 6) + minute_bars(datetime.fromisoformat(self.DAY + " 13:00"), 6,
                                                    low_at=10, recover_at=5)
        # 第一段从11:25跌破，午休后13:05收回，累计10个交易分钟。
        bars[-1]["close"] = 101
        result = cm._line_status(bars, 100, False, self.DAY + " 13:05")
        self.assertEqual(cm._trading_minutes(start, datetime.fromisoformat(self.DAY + " 13:05")), 10)
        self.assertEqual(result["state"], "快速收回")

    def test_old_ma10_cross_is_not_reclaim_of_dynamic_ma10(self):
        closes = [110.0] * 20
        closes[-10] = 80.0  # 旧MA10=107；当前动态阈值=110。
        completed = completed_bars(closes)
        base = {"code": "000001", "name": "A", "score": 80}
        live = {"intraday_quote_fresh": True, "change_pct": -1.8}
        quote_row = quote(price=108, last_close=110, low=108,
                          quote_at=self.DAY + " 09:50:00")
        bars = minute_bars(datetime.fromisoformat(self.DAY + " 09:30"), 21, low_at=0,
                           recover_at=None, low=108, high=108)
        row = cm._monitor_row(base, live, quote_row, bars, completed,
                              self.DAY + " 09:50:00", "2026-09-25",
                              calendar=[bar["date"] for bar in completed])
        self.assertEqual(row["lines"]["MA10"]["state"], "确认失守")
        self.assertNotEqual(row["status"], "符合预期")

    def test_minute_gap_means_unknown(self):
        bars = [{"at": self.DAY + " 10:00", "low": 99, "close": 99},
                {"at": self.DAY + " 10:10", "low": 99, "close": 101}]
        self.assertEqual(cm._line_status(bars, 100, False, self.DAY + " 10:10")["state"], "待核验")

    def test_close_archive_is_reused_until_new_completed_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(cm, "CLOSE_DIR", Path(tmp)):
                snap = {"session": "已收盘", "generated_at": self.DAY + " 15:10:00",
                        "strength_model": {"asof": self.DAY},
                        "stocks": [{"code": "000001", "name": "A", "persistent_strong": True,
                                    "stock_strength_score": 80}]}
                saved = cm._save_close_board(snap, self.DAY)
                self.assertEqual(saved["count"], 1)
                later = dict(snap, strength_model={"asof": self.DAY}, session="早盘")
                self.assertEqual(cm._save_close_board(later, "2026-09-29")["asof"], self.DAY)

    def test_near_line_keeps_risk_visible_and_prioritizes_clean_rows(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(cm, 'TREND_DIRS', {p: Path(tmp)/str(p) for p in cm.LINES}):
            rows, quotes, ks = [], {}, {}
            for code, price, flags in [('risk',100.2,['大幅下跌']), ('clean',100.7,[])]:
                rows.append({'code':code,'signal_date':'2026-09-25','trend_online':1,
                             'signal_close':101,'ma5':100,'ma10':100,'ma20':100,
                             'intraday_quote_fresh':True,'intraday_price_basis_comparable':True,
                             'intraday_quote_at':self.DAY+' 10:00:00','intraday_risk_flags':flags})
                quotes[code]={'price':price,'low':100.15,'last_close':101}
                # 最低价低于昨收，仍在线上；无需分钟源即能核验近线名单。
                ks[code]=completed_bars([100] * 19 + [101])
                quotes[code].update(open=price, quote_at=self.DAY+' 10:00:00',
                                    price_basis='raw',
                                    price_basis_source='tencent_realtime_quote',
                                    last_close_semantics='previous_trade_day_raw_close')
            snap={'session':'早盘','strength_model':{'asof':'2026-09-25'},'stocks':rows}
            with patch.object(cm, '_get_minutes', return_value={}):
                cm._attach_trend_observations(snap,quotes,ks,self.DAY)
            actual=snap['trend_ma10_observation']['main_rows']
            self.assertEqual([r['code'] for r in actual],['clean','risk'])
            self.assertEqual(actual[1]['risk_flags'],['大幅下跌'])

    def test_live_lists_are_retained_through_lunch_without_new_events(self):
        prior_day = "2026-09-25"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(cm, "CLOSE_DIR", root / "close"), \
                 patch.object(cm, "TREND_DIRS", {p: root / f"ma{p}" for p in cm.LINES}), \
                 patch.object(cm, "LIVE_DIR", root / "new"):
                cm.CLOSE_DIR.mkdir()
                (cm.CLOSE_DIR / (prior_day + ".json")).write_text(json.dumps({
                    "version": cm.VERSION, "asof": prior_day,
                    "stocks": [{"code": "000001", "name": "昨日A", "score": 80}]}), encoding="utf-8")
                snap = {"session": "早盘", "generated_at": self.DAY + " 10:00:00",
                        "quote_capture_at": self.DAY + " 10:00:00",
                        "strength_model": {"asof": prior_day},
                        "stocks": [{"code": "000001", "name": "昨日A", "intraday_quote_fresh": True,
                                    "intraday_quote_at": self.DAY + " 10:00:00", "change_pct": 1},
                                   {"code": "000002", "name": "今日B", "intraday_quote_fresh": True,
                                    "intraday_quote_at": self.DAY + " 10:00:00", "change_pct": 2,
                                    "current_strong_candidate": True, "intraday_score": 88,
                                    "intraday_observation_state": "当前强势"}],
                        "coverage_catalog": []}
                quotes = {"000001": {"price": 101, "open": 101, "low": 101, "last_close": 100}}
                klines = {"000001": [{"date": prior_day, "close": 100.0} for _ in range(20)]}
                cm.attach(snap, quotes, klines)
                self.assertEqual([s["code"] for s in snap["intraday_new_strength"]["rows"]], ["000002"])
                retained = dict(snap["intraday_new_strength"])
                self.assertEqual(retained["rows"][0]["kind"], "当前强势")
                lunch = dict(snap, session="午间休市", generated_at=self.DAY + " 12:00:00")
                cm.attach(lunch, {}, klines)
                self.assertEqual([s["code"] for s in lunch["intraday_new_strength"]["rows"]], ["000002"])
                self.assertEqual(retained, lunch["intraday_new_strength"])
                self.assertIn("保留", lunch["trend_ma5_observation"]["phase_note"])

    def test_home_candidates_use_the_same_state_as_stock_detail(self):
        states = (("000001", "当前强势", "current_strong_candidate"),
                  ("000002", "初步转强，待收盘确认", "startup_candidate"),
                  ("000003", "盘中修复", "intraday_repair_candidate"),
                  ("000004", "活跃观察", "intraday_active_candidate"))
        snap = {"session": "早盘", "generated_at": self.DAY + " 10:00:00",
                "stocks": [{"code": c, "name": c, "intraday_quote_fresh": True,
                            "intraday_quote_at": self.DAY + " 10:00:00",
                            "intraday_score": 80, "intraday_observation_state": state, flag: True}
                           for c, state, flag in states]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(cm, "LIVE_DIR", Path(tmp)):
            cm._attach_new_strength(snap, self.DAY)
        home = snap["intraday_new_strength"]["rows"]
        self.assertEqual(["000001", "000002"], [r["code"] for r in home])
        source = {r["code"]: r for r in snap["stocks"]}
        self.assertTrue(all(r["kind"] == source[r["code"]]["intraday_observation_state"] for r in home))


if __name__ == "__main__":
    unittest.main()
