"""盘中改造的受控报价验收；所有行情均为合成输入，不写入生产缓存。"""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import intraday
import scoring
import strength
import config


class IntradayAcceptanceTests(unittest.TestCase):
    def test_overheat_uses_ma5_exact_and_strict_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = datetime(2026, 9, 28, 10, 0)
            rows, _ = self._scan(now, 1, root, save=False)
            row = next(r for r in rows if r['code'] == self.CODES[1])
            exact = (row['price']-row['intraday_ma5_exact'])/row['intraday_atr20']
            self.assertAlmostEqual(row['live_overheat_dist_atr'], exact, places=3)
            self.assertNotAlmostEqual(exact, row['live_dist_atr'], places=2)
            for threshold, expected in ((exact, False), (exact-1e-6, True), (exact+1e-6, False)):
                with patch.dict(config.INTRADAY_RISK, overheat_dist_atr=threshold):
                    repeated, _ = self._scan(now, 1, root, save=False)
                current = next(r for r in repeated if r['code'] == row['code'])
                self.assertEqual(current['overheated'], expected)
                self.assertEqual('现价距盘中MA5过远，位置偏热' in current['intraday_risk_flags'], expected)
                self.assertNotIn('现价距盘中MA10过远，位置偏热', current['intraday_risk_flags'])

    DAY = "2026-09-28"
    CODES = [f"{600000 + i:06d}" for i in range(30)]

    @classmethod
    def setUpClass(cls):
        days = []
        day = datetime(2026, 8, 28)
        while len(days) < 21:
            if day.weekday() < 5:
                days.append(day.strftime("%Y-%m-%d"))
            day += timedelta(days=1)
        cls.bars = cls._tag_history([
            {"date": day, "close": float(100 + i)} for i, day in enumerate(days)])

    @staticmethod
    def _tag_history(bars):
        tagged = []
        for bar in bars:
            close = float(bar["close"])
            tagged.append({**bar, "open": close, "high": close + .1, "low": close - .1,
                           "price_basis": "qfq", "price_basis_source": "tencent_qfqday"})
        return tagged

    @staticmethod
    def _tag_quotes(quotes):
        for quote in quotes.values():
            quote.update(price_basis="raw", price_basis_source="tencent_realtime_quote",
                         last_close_semantics="previous_trade_day_raw_close")
        return quotes

    def _histories(self, quotes, bars=None, codes=None):
        history = self._tag_history(bars or self.bars)
        codes = list(codes or quotes)
        return {code: [dict(bar) for bar in history] for code in codes}

    def _base_rows(self):
        rows = []
        for i, code in enumerate(self.CODES):
            rows.append({
                "code": code, "name": f"测试{i}", "primary_industry": "测试行业",
                "trend_online": i != 4, "persistent_strong": i != 4,
                "stock_strength_percentile": 90.0 if i != 4 else 78.0,
                "stock_strength_score": 80.0, "ret20": 18.0,
                "ma20": 109.5, "atr20": 2.0, "touch_state": "回踩反弹",
                "risk_notes": [],
            })
        return rows

    def _quotes(self, at, phase=1):
        stamp = at.strftime("%Y-%m-%d %H:%M:%S")
        quotes = {}
        for i, code in enumerate(self.CODES):
            price = 119.5 + (i % 3) * 0.1
            quotes[code] = {
                "price": price, "open": 119.0, "high": max(price, 119.0) + 0.5,
                "low": min(price, 119.0) - 0.5, "change_pct": (price / 119.0 - 1) * 100,
                "amount_wan": 1000.0, "volume_shou": 10000,
                "quote_at": stamp, "board_type": "sh_main", "limit_pct": 10.0,
                "limit_up": 130.9, "limit_down": 107.1,
            }
        # 既有强股跌停：即使昨日没有涨停/大涨也必须触发普遍风险。
        quotes[self.CODES[0]].update(price=90.0, open=100.0, high=90.0, low=90.0,
                                     change_pct=-10.0, limit_up=110.0, limit_down=90.0)
        quotes[self.CODES[0]]["open"] = 90.0
        # 过热以后回落并失守盘中 MA10。
        if phase == 1:
            quotes[self.CODES[1]].update(price=125.0, open=120.0, high=125.0,
                                         low=118.0, change_pct=5.0)
        else:
            quotes[self.CODES[1]].update(price=114.0, open=120.0, high=125.0,
                                         low=113.0, change_pct=-4.2)
        # 低开后由 MA10 下方走强并收复。
        if phase == 1:
            quotes[self.CODES[2]].update(price=110.0, open=111.0, high=111.0,
                                         low=109.0, change_pct=-7.6)
        else:
            quotes[self.CODES[2]].update(price=121.0, open=111.0, high=121.5,
                                         low=111.0, change_pct=1.7)
        # 当日涨幅仍高，但从日内高点显著回撤且落在区间低位。
        quotes[self.CODES[3]].update(price=125.0, open=130.0, high=132.0,
                                     low=124.0, change_pct=5.0)
        # 新转强同时具备趋势、上涨、跑赢市场、守住开盘和完整高分。
        quotes[self.CODES[4]].update(price=122.0, open=119.0, high=122.5,
                                     low=118.9, change_pct=(122.0 / 119.0 - 1) * 100)
        # 一字涨停：区间位置不适用，单独标记成交限制。
        quotes[self.CODES[9]].update(price=110.0, open=110.0, high=110.0,
                                     low=110.0, change_pct=10.0,
                                     limit_up=110.0, limit_down=90.0)
        # 触及涨停后回落：记录事实并降低排序优先级，不推断封板时间。
        quotes[self.CODES[16]].update(price=124.0, open=120.0, high=130.9,
                                      low=116.0, change_pct=5.0, limit_up=130.9)
        # 高开后持续回落，但回撤幅度不足以单独判为明显冲高回落。
        quotes[self.CODES[17]].update(price=124.5, open=125.0, high=126.0,
                                      low=123.8, change_pct=3.75)
        # 平价窄幅样本：位置不适用，但不是一字涨跌停。
        quotes[self.CODES[18]].update(price=100.0, open=100.0, high=100.0,
                                      low=100.0, change_pct=0.0,
                                      limit_up=110.0, limit_down=90.0)
        quotes[self.CODES[10]]["quote_at"] = "2026-09-28 09:45:00"  # 过期
        if phase == 1:
            quotes[self.CODES[15]]["quote_at"] = "2026-09-28 09:54:00"  # 新鲜但不属于同一批次
        if phase >= 2:
            quotes[self.CODES[14]]["quote_at"] = "2026-09-28 09:45:00"
        quotes[self.CODES[11]]["amount_wan"] = 0.0                 # 停牌/无成交
        quotes[self.CODES[11]]["volume_shou"] = 0.0
        quotes[self.CODES[12]]["high"] = None                      # 必要字段缺失
        for quote in quotes.values():
            if quote.get("change_pct") is not None and 1 + quote["change_pct"] / 100 > 0:
                quote["last_close"] = quote["price"] / (1 + quote["change_pct"] / 100)
        return self._tag_quotes(quotes)

    def test_no_trade_coverage_status_is_not_overwritten(self):
        at = datetime(2026, 9, 28, 10, 0)
        rows = self._base_rows()
        coverage_row = rows.pop(11)
        coverage_row.pop("stock_strength_score")
        coverage_row.update(coverage_only=True, trade_status="no_trade",
                            daily_strength_status="当日无成交，暂停当前评分")
        quotes = self._quotes(at)
        klines = self._histories(quotes, codes=self.CODES)
        with patch.object(intraday, "_latest_record", return_value=None):
            intraday.enrich(rows, [coverage_row], quotes, klines, self.CODES,
                            captured_at=at, session="早盘", save_reference=False)
        self.assertEqual("当日无成交，暂停当前评分",
                         coverage_row["daily_strength_status"])
        self.assertFalse(coverage_row["current_strong_candidate"])

    def test_recovered_trade_cannot_enter_intraday_candidate_before_daily_alignment(self):
        at = datetime(2026, 9, 28, 10, 0)
        rows = self._base_rows()
        coverage_row = rows.pop(4)
        coverage_row.pop("stock_strength_score")
        coverage_row.update(coverage_only=True, trade_status="trade_recovered_wait_daily",
                            daily_strength_status="恢复成交，核心日线待对齐")
        quotes = self._quotes(at)
        klines = self._histories(quotes, codes=self.CODES)
        with patch.object(intraday, "_latest_record", return_value=None):
            intraday.enrich(rows, [coverage_row], quotes, klines, self.CODES,
                            captured_at=at, session="早盘", save_reference=False)
        self.assertEqual("恢复成交，日线待对齐", coverage_row["intraday_observation_state"])
        self.assertEqual("恢复成交，核心日线待对齐", coverage_row["daily_strength_status"])
        self.assertFalse(any(coverage_row[key] for key in
                             ("current_strong_candidate", "startup_candidate",
                              "current_pullback_candidate", "intraday_active_candidate",
                              "intraday_repair_candidate", "turn_weak_repair_candidate")))

    def _scan(self, at, phase, root, save=True, omissions=(), session="早盘", previous_snapshot=None):
        rows = self._base_rows()
        quotes = self._quotes(at, phase)
        for code in omissions:
            quotes.pop(code, None)
        for row in rows:
            quote = quotes.get(row["code"])
            if quote:
                row.update({key: quote.get(key) for key in
                            ("price", "open", "high", "low", "change_pct", "amount_wan")})
        klines = self._histories(quotes, codes=self.CODES)
        with patch.object(intraday, "HISTORY_DIR", root / "history"), \
             patch.object(intraday, "PAIR_HISTORY_PATH", root / "history" / "pairs.jsonl"):
            meta = intraday.enrich(rows, [], quotes, klines, self.CODES,
                                   captured_at=at, session=session, save_reference=False,
                                   previous_snapshot=previous_snapshot)
            snapshot = {
                "mode": "quick", "session": session, "intraday_model": meta,
                "scan_completed_at": at.isoformat(sep=" ", timespec="seconds"),
                "generated_at": at.isoformat(sep=" ", timespec="seconds"),
                "stocks": rows, "coverage_catalog": [],
            }
            if save:
                intraday.save_observation(snapshot)
            return rows, snapshot

    def test_real_time_risk_score_transitions_and_history_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            t0 = datetime(2026, 9, 28, 10, 0)
            first, _ = self._scan(t0, 1, root, omissions=(self.CODES[13],))
            by_code = {r["code"]: r for r in first}

            limit_down = by_code[self.CODES[0]]
            self.assertIn("一字跌停", limit_down["intraday_risk_flags"])
            self.assertEqual("严重", limit_down["intraday_risk_level"])
            self.assertFalse(limit_down["current_strong_candidate"])
            self.assertFalse(limit_down["current_pullback_candidate"])

            overheated = by_code[self.CODES[1]]
            self.assertTrue(overheated["overheated"])
            self.assertFalse(overheated["current_pullback_candidate"])
            self.assertFalse(overheated["intraday_score"] is None)

            first_recovery = by_code[self.CODES[2]]
            self.assertIsNone(first_recovery["intraday_transition"])
            self.assertTrue(first_recovery["intraday_trend_state"].startswith("盘中转弱"))

            high_fade = by_code[self.CODES[3]]
            self.assertGreater(high_fade["change_pct"], 0)
            self.assertLess(high_fade["intraday_open_return_pct"], 0)
            self.assertIn("明显冲高回落", high_fade["intraday_risk_flags"])

            one_price = by_code[self.CODES[9]]
            self.assertIsNone(one_price["intraday_position_pct"])
            self.assertEqual("一字涨停", one_price["intraday_trade_restriction"])
            self.assertFalse(one_price["current_pullback_candidate"])
            self.assertIsNone(one_price["intraday_score"])
            self.assertEqual(2, one_price["intraday_score_available_components"])
            flat = by_code[self.CODES[18]]
            self.assertIsNone(flat["intraday_position_pct"])
            self.assertIsNone(flat["intraday_score"])
            self.assertIsNone(flat["intraday_trade_restriction"])
            self.assertFalse(any("一字" in flag for flag in flat["intraday_risk_flags"]))
            unsealed = by_code[self.CODES[16]]
            self.assertIn("触板未封", unsealed["intraday_risk_flags"])
            self.assertGreaterEqual(unsealed["intraday_risk_priority"], 55)
            high_open_fade = by_code[self.CODES[17]]
            self.assertLess(high_open_fade["intraday_open_return_pct"], 0)
            self.assertNotIn("明显冲高回落", high_open_fade["intraday_risk_flags"])

            for idx, status in ((10, "报价过期"), (11, "当日无成交或停牌"),
                                (12, "日内高低价缺失或异常")):
                self.assertFalse(by_code[self.CODES[idx]]["intraday_quote_fresh"])
                self.assertIsNone(by_code[self.CODES[idx]]["intraday_score"])
                self.assertIn(status, by_code[self.CODES[idx]]["intraday_quote_status"])
            self.assertFalse(by_code[self.CODES[13]]["intraday_quote_fresh"])
            self.assertIsNone(by_code[self.CODES[13]]["intraday_score"])
            self.assertFalse(by_code[self.CODES[15]]["intraday_quote_fresh"])
            self.assertEqual("报价批次时间偏差过大", by_code[self.CODES[15]]["intraday_quote_status"])
            previous_valid_price = by_code[self.CODES[14]]["price"]

            # 报价缺失不当成转弱、不给零分。
            rows2, _ = self._scan(t0 + timedelta(minutes=5), 2, root)
            by_code2 = {r["code"]: r for r in rows2}
            self.assertEqual({r["code"]: r["stock_strength_score"] for r in first},
                             {r["code"]: r["stock_strength_score"] for r in rows2})
            lost_ma10 = by_code2[self.CODES[1]]
            self.assertIn("现价失守盘中MA10", lost_ma10["intraday_risk_flags"])
            self.assertFalse(lost_ma10["current_pullback_candidate"])
            self.assertFalse(lost_ma10["current_strong_candidate"])
            self.assertNotEqual(overheated["intraday_score"], lost_ma10["intraday_score"])
            order1 = [r["code"] for r in sorted(first,
                     key=lambda r: r.get("intraday_score") if r.get("intraday_score") is not None else -1,
                     reverse=True)]
            order2 = [r["code"] for r in sorted(rows2,
                     key=lambda r: r.get("intraday_score") if r.get("intraday_score") is not None else -1,
                     reverse=True)]
            self.assertNotEqual(order1, order2)

            recovered = by_code2[self.CODES[2]]
            self.assertTrue(recovered["intraday_trend_ok"])
            self.assertEqual("扫描观察到收复MA10", recovered["intraday_transition"])
            self.assertIsNotNone(recovered["intraday_score_delta"])
            self.assertEqual("相对评分变化（比较样本变化，谨慎解读）", recovered["intraday_delta_state"])
            self.assertEqual("上轮报价无效，停止比较", by_code2[self.CODES[13]]["intraday_delta_state"])

            # 昨日趋势未成立但当前暂态结构成立：放进初步启动并注明待收盘确认。
            startup = by_code2[self.CODES[4]]
            self.assertTrue(startup["startup_candidate"])
            self.assertIn("待收盘确认", startup["intraday_trend_state"])

            rows3, _ = self._scan(t0 + timedelta(minutes=10), 3, root)
            stale_again = {r["code"]: r for r in rows3}[self.CODES[14]]
            self.assertFalse(stale_again["intraday_quote_fresh"])
            self.assertEqual(previous_valid_price, stale_again["last_valid_price"])
            self.assertTrue(stale_again["intraday_trend_state"].startswith("均线待核验"))
            self.assertIn("历史观察已过期", stale_again["intraday_trend_state"])
            self.assertIsNone(stale_again["intraday_transition"])

            pairs_path = root / "history" / "pairs.jsonl"
            pairs = [json.loads(line) for line in pairs_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(2, len(pairs))
            self.assertGreaterEqual(pairs[0]["entries"], 20)
            report_path = root / "validation.md"
            with patch.object(intraday, "REPORT_PATH", report_path), \
                 patch.object(intraday, "PAIR_HISTORY_PATH", pairs_path):
                validation = intraday.build_validation_report()
            self.assertEqual(2, validation["pairs"])
            self.assertIn("盘中观察分", report_path.read_text(encoding="utf-8"))

    def test_close_confirmation_keeps_prior_intraday_judgment(self):
        prev = {"intraday_model": {"asof": self.DAY, "version": intraday.VERSION,
                                   "rule_version": scoring.config.INTRADAY_RULE_VERSION},
                "scan_completed_at": self.DAY + " 14:55:00",
                "stocks": [{"code": self.CODES[4], "intraday_quote_fresh": True,
                            "intraday_trend_ok": True,
                            "intraday_trend_state": "盘中初步转强·待收盘确认"}]}
        snap = {"strength_model": {"asof": self.DAY},
                "intraday_model": {"asof": self.DAY, "version": intraday.VERSION,
                                   "rule_version": scoring.config.INTRADAY_RULE_VERSION},
                "quote_capture_at": self.DAY + " 15:06:00",
                "scan_started_at": self.DAY + " 15:05:00", "session": "已收盘",
                "stocks": [{"code": self.CODES[4], "trend_online": False}],
                "coverage_catalog": []}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(scoring.config, "CACHE_DIR", Path(tmp)):
            result = scoring._apply_intraday_close_confirmation(snap, prev)
            self.assertEqual(1, result["unconfirmed"])
            self.assertEqual("盘中暂态转强，收盘未确认", snap["stocks"][0]["intraday_close_confirmation"])
            self.assertEqual("盘中初步转强·待收盘确认", snap["stocks"][0]["intraday_close_intraday_state"])
            later = {"strength_model": {"asof": self.DAY},
                     "intraday_model": {"asof": self.DAY, "version": intraday.VERSION,
                                        "rule_version": scoring.config.INTRADAY_RULE_VERSION},
                     "quote_capture_at": self.DAY + " 15:20:00",
                     "scan_started_at": self.DAY + " 15:19:00", "session": "已收盘",
                     "stocks": [{"code": self.CODES[4], "trend_online": True}],
                     "coverage_catalog": []}
            again = scoring._apply_intraday_close_confirmation(later, prev)
            self.assertEqual("盘中暂态转强，收盘未确认", later["stocks"][0]["intraday_close_confirmation"])
            self.assertEqual(result, again)

    def test_close_archive_keeps_valid_judgment_even_without_complete_score(self):
        previous = {"intraday_model": {"asof": self.DAY, "version": intraday.VERSION,
                                       "rule_version": scoring.config.INTRADAY_RULE_VERSION,
                                       "reference_pool_hash": "pool", "score_sample_hash": "scores"},
                    "stocks": [{"code": self.CODES[6], "intraday_quote_fresh": True,
                                "intraday_quote_at": self.DAY + " 14:55:00", "price": 100.0,
                                "change_pct": 1.0, "intraday_score": None,
                                "intraday_score_available_components": 2,
                                "intraday_trend_ok": True, "intraday_trend_state": "盘中趋势成立"}],
                    "coverage_catalog": []}
        closing = {"scan_completed_at": self.DAY + " 15:06:00",
                   "stocks": [{"code": self.CODES[6], "signal_close": 101.0,
                               "trend_online": True, "ma10": 99.0, "ma20": 98.0}],
                   "coverage_catalog": []}
        confirmation = {"asof": self.DAY, "previous_scan_at": self.DAY + " 14:55:00",
                        "rows": {self.CODES[6]: {"confirmation": "盘中与收盘趋势均成立"}}}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(intraday, "CLOSE_HISTORY_DIR", Path(tmp)):
            saved_path = intraday.save_close_observation(closing, previous, confirmation)
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
            self.assertEqual(1, len(saved["entries"]))
            self.assertIsNone(saved["entries"][0]["intraday_score"])
            self.assertEqual("盘中与收盘趋势均成立", saved["entries"][0]["close_confirmation"])
            original = saved_path.read_text(encoding="utf-8")
            closing["stocks"][0]["signal_close"] = 105.0
            intraday.save_close_observation(closing, previous, confirmation)
            self.assertEqual(original, saved_path.read_text(encoding="utf-8"))

    def test_prior_day_close_confirmation_is_not_attached_to_new_day(self):
        next_day = "2026-09-29"
        snap = {"strength_model": {"asof": next_day},
                "intraday_model": {"asof": next_day, "version": intraday.VERSION,
                                   "rule_version": scoring.config.INTRADAY_RULE_VERSION},
                "quote_capture_at": next_day + " 10:00:00",
                "session": "早盘", "stocks": [{"code": self.CODES[6]}], "coverage_catalog": []}
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "intraday_close_confirmation"
            store.mkdir()
            (store / "latest.json").write_text(json.dumps({
                "asof": self.DAY, "model_version": intraday.VERSION,
                "rule_version": scoring.config.INTRADAY_RULE_VERSION,
                "rows": {self.CODES[6]: {"confirmation": "昨日确认"}}}),
                encoding="utf-8")
            with patch.object(scoring.config, "CACHE_DIR", Path(tmp)):
                result = scoring._apply_intraday_close_confirmation(snap, {})
        self.assertIsNone(result)
        self.assertNotIn("intraday_close_confirmation", snap["stocks"][0])

    def test_same_day_close_confirmation_from_old_rule_is_not_attached(self):
        snap = {"strength_model": {"asof": self.DAY},
                "intraday_model": {"asof": self.DAY, "version": intraday.VERSION,
                                   "rule_version": scoring.config.INTRADAY_RULE_VERSION},
                "quote_capture_at": self.DAY + " 15:20:00", "session": "已收盘",
                "stocks": [{"code": self.CODES[6]}], "coverage_catalog": []}
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "intraday_close_confirmation"
            store.mkdir()
            old_record = {"asof": self.DAY, "previous_scan_at": self.DAY + " 15:05:00",
                          "model_version": intraday.VERSION, "rule_version": "旧规则",
                          "rows": {self.CODES[6]: {"confirmation": "旧规则结论"}}}
            (store / (self.DAY + ".json")).write_text(json.dumps(old_record), encoding="utf-8")
            (store / "latest.json").write_text(json.dumps(old_record), encoding="utf-8")
            with patch.object(scoring.config, "CACHE_DIR", Path(tmp)):
                result = scoring._apply_intraday_close_confirmation(snap, {})
        self.assertIsNone(result)
        self.assertNotIn("intraday_close_confirmation", snap)
        self.assertNotIn("intraday_close_confirmation", snap["stocks"][0])

    def test_provisional_ma20_uses_the_last_completed_day_not_updated_daily_field(self):
        result = intraday.provisional_trend(self.bars, 120.0, daily_ma20=9999.0)
        expected_prior = sum(b["close"] for b in self.bars[-20:]) / 20
        expected_temp = (sum(b["close"] for b in self.bars[-19:]) + 120.0) / 20
        self.assertEqual(round(expected_prior, 4), result["intraday_previous_completed_ma20"])
        self.assertEqual(round(expected_temp, 4), result["intraday_ma20"])
        self.assertTrue(result["intraday_trend_ok"])

    def test_close_time_daily_row_update_does_not_change_same_price_intraday_baseline(self):
        day = self.DAY
        code = self.CODES[5]
        prior_snapshot = {"strength_model": {"asof": "2026-09-25"},
                          "stocks": [{"code": code, "trend_online": True}],
                          "coverage_catalog": []}
        rows_before = self._base_rows()
        rows_after = self._base_rows()
        quote_at = datetime(2026, 9, 28, 14, 55)
        quotes_before = self._quotes(quote_at, 2)
        quotes_after = {key: dict(value) for key, value in quotes_before.items()}
        quotes_after[code]["quote_at"] = "2026-09-28 15:00:00"
        rows_after[5]["trend_online"] = False  # 正式 D 日线已更新，但 D-1 判断仍来自前一快照
        bars_after = self.bars + [{"date": day, "close": 130.0}]
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(intraday, "HISTORY_DIR", Path(tmp)):
            intraday.enrich(rows_before, [], quotes_before, self._histories(quotes_before, codes=self.CODES),
                            self.CODES, captured_at=quote_at, session="尾盘", save_reference=False,
                            previous_snapshot=prior_snapshot)
            intraday.enrich(rows_after, [], quotes_after,
                            self._histories(quotes_after, bars_after, self.CODES), self.CODES,
                            captured_at=datetime(2026, 9, 28, 15, 6), session="已收盘",
                            save_reference=False, previous_snapshot=prior_snapshot)
        before, after = rows_before[5], rows_after[5]
        self.assertEqual(before["intraday_ma20"], after["intraday_ma20"])
        self.assertEqual(before["intraday_ma10"], after["intraday_ma10"])
        self.assertTrue(after["intraday_prior_daily_trend_online"])
        self.assertTrue(after["intraday_trend_ok"])
        self.assertEqual("趋势保持", after["intraday_trend_state"])
        self.assertFalse(after["current_strong_candidate"])

    def _classification_scan(self, prior=0, price=120.5, opened=119.0,
                             high=121.0, low=118.5, market_price=119.0,
                             bars=None, session="早盘", stale=False):
        at = datetime(2026, 9, 28, 10, 0)
        rows = self._base_rows()
        code = self.CODES[4]
        rows[4]["trend_online"] = prior
        quotes = {c: {"price": market_price, "open": 119.0,
                      "high": max(market_price, 119.0) + 1, "low": 118.0,
                      "last_close": 119.0, "change_pct": (market_price / 119 - 1) * 100,
                      "quote_at": at.isoformat(sep=" "), "amount_wan": 1000,
                      "board_type": "sh_main", "limit_up": 130.9, "limit_down": 107.1}
                  for c in self.CODES}
        prior_close = (bars or self.bars)[-1]["close"]
        quotes[code].update(price=price, open=opened, high=high, low=low,
                            last_close=prior_close, change_pct=(price/prior_close-1)*100,
                            quote_at="2026-09-28 09:40:00" if stale else at.isoformat(sep=" "))
        series = self._histories(quotes, codes=self.CODES)
        series[code] = self._tag_history(bars or self.bars)
        self._tag_quotes(quotes)
        for row in rows:
            row.update(quotes[row["code"]])
        with patch.object(intraday, "_latest_record", return_value=None):
            intraday.enrich(rows, [], quotes, series, self.CODES, captured_at=at,
                            session=session, save_reference=False)
        return rows[4]

    def test_startup_requires_structure_direction_score_and_risk_together(self):
        candidate = self._classification_scan()
        self.assertTrue(candidate["startup_candidate"])
        self.assertEqual([], candidate["startup_missing"])
        self.assertEqual("初步转强，待收盘确认", candidate["intraday_observation_state"])
        cases = (
            ({"prior": 1}, "上一完成日日线趋势明确未成立"),
            ({"prior": None}, "上一完成日日线趋势明确未成立"),
            ({"price": 118.0, "opened": 117.0, "high": 118.5, "low": 116.8}, "当日涨幅为正"),
            ({"market_price": 121.0}, "跑赢主板等权基准"),
            ({"opened": 120.8}, "现价不低于开盘价"),
            ({"high": 130.9}, "当前风险约束通过"),
            ({"stale": True}, "报价有效"),
            ({"price": 120.5, "opened": 120.5, "high": 120.5, "low": 120.5}, "三项盘中评分完整"),
        )
        for kwargs, missing in cases:
            with self.subTest(kwargs=kwargs):
                row = self._classification_scan(**kwargs)
                self.assertFalse(row["startup_candidate"])
                self.assertIn(missing, row["startup_missing"])
                self.assertNotEqual("初步转强，待收盘确认", row["intraday_observation_state"])

    def test_active_repair_and_strong_are_distinct_from_startup(self):
        mixed = self._tag_history([
            {"date": b["date"], "close": c}
            for b, c in zip(self.bars, [110]*11+[130]*4+[110]*6)])
        active = self._classification_scan(bars=mixed, price=120, opened=118,
                                           high=120.2, low=117.5)
        self.assertGreaterEqual(active["intraday_score"], 70)
        self.assertFalse(active["intraday_trend_ok"])
        self.assertTrue(active["intraday_active_candidate"])
        self.assertEqual("活跃观察", active["intraday_observation_state"])
        repair = self._classification_scan(price=118, opened=117, high=118.5, low=116.8)
        self.assertTrue(repair["intraday_repair_candidate"])
        self.assertEqual("盘中修复", repair["intraday_observation_state"])
        strong = self._classification_scan(prior=1)
        self.assertTrue(strong["current_strong_candidate"])
        self.assertEqual("当前强势", strong["intraday_observation_state"])
        for row in (active, repair, strong, self._classification_scan()):
            self.assertEqual(1, sum(bool(row.get(key)) for key in
                ("current_strong_candidate", "startup_candidate", "intraday_active_candidate", "intraday_repair_candidate")))

    def test_nontrading_phases_clear_active_and_repair_candidates(self):
        for session in ("午间休市", "盘前", "集合竞价", "非交易日", "已收盘"):
            with self.subTest(session=session):
                row = self._classification_scan(session=session)
                self.assertFalse(any(row.get(k) for k in
                    ("current_strong_candidate", "startup_candidate", "intraday_active_candidate", "intraday_repair_candidate")))

    def test_daily_build_integer_trend_reaches_current_strong(self):
        at = datetime(2026, 9, 28, 10, 0)
        series = {}
        for i, code in enumerate(self.CODES[:8]):
            bars = []
            for offset in range(61):
                price = 10 + offset * (0.02 + i * 0.01)
                bars.append({"date": (at - timedelta(days=61-offset)).strftime("%Y-%m-%d"),
                             "open": price, "close": price, "high": price + .1,
                             "low": price - .1, "volume": 1000000})
            series[code] = self._tag_history(bars)
        with patch.object(strength.stock_strength, "attach_history"):
            rows, _ = strength.build(
                [{"code": c, "name": c} for c in series], series, {}, now=at)
        target = max(rows, key=lambda r: r["stock_strength_score"])
        self.assertIs(type(target["trend_online"]), int)
        self.assertEqual(1, target["trend_online"])
        quotes = {}
        for row in rows:
            prior = series[row["code"]][-1]["close"]
            change = 2.0 if row is target else .2
            price = prior * (1 + change / 100)
            quotes[row["code"]] = {
                "quote_at": at.isoformat(sep=" "), "price": price, "open": prior,
                "high": price + .1, "low": prior - .1, "last_close": prior,
                "change_pct": change, "amount_wan": 1000, "volume_shou": 10000,
                "board_type": "sh_main", "limit_pct": 10.0,
                "limit_up": prior * 1.1, "limit_down": prior * .9}
            row.update(quotes[row["code"]])
        self._tag_quotes(quotes)
        daily_scores = {r["code"]: r["stock_strength_score"] for r in rows}
        with patch.object(intraday, "_latest_record", return_value=None):
            intraday.enrich(rows, [], quotes, series, list(series), captured_at=at,
                            session="早盘", save_reference=False)
        self.assertEqual([], target["current_strong_missing"])
        self.assertTrue(target["current_strong_candidate"])
        self.assertFalse(target["startup_candidate"])
        self.assertEqual("趋势保持", target["intraday_trend_state"])
        self.assertEqual(daily_scores, {r["code"]: r["stock_strength_score"] for r in rows})

    def test_prior_daily_trend_accepts_integer_and_boolean_flags(self):
        at = datetime(2026, 9, 28, 14, 55)
        for value, expected in ((1, True), (True, True), (0, False), (False, False), (None, False)):
            with self.subTest(value=value, value_type=type(value).__name__):
                rows = self._base_rows()
                code = self.CODES[5]
                previous = {"strength_model": {"asof": "2026-09-25"},
                            "stocks": [{"code": code, "trend_online": value}]}
                with patch.object(intraday, "_latest_record", return_value=None):
                    intraday.enrich(rows, [], self._quotes(at, 2),
                                    self._histories(self._quotes(at, 2), codes=self.CODES), self.CODES,
                                    captured_at=at, session="尾盘", save_reference=False,
                                    previous_snapshot=previous)
                self.assertEqual(expected, rows[5]["current_strong_qualification"]["上一完成日日线趋势成立"])

    def test_transition_checks_current_line_before_emitting_event(self):
        at = datetime(2026, 9, 28, 10, 5)
        # 最近9日收盘均值固定为100.1；现价更新时，MA10也同时移动。
        cases = ((100.0, 100.095, None),
                 (100.2, 100.105, None),
                 (100.0, 100.1, "扫描观察到收复MA10"),
                 (100.2, 100.099, "扫描观察到失守MA10"))
        for old_price, price, expected in cases:
            with self.subTest(old_price=old_price, price=price):
                old_ma10 = round((9 * 100.1 + old_price) / 10, 4)
                ma10 = round((9 * 100.1 + price) / 10, 4)
                old = [self.CODES[0], "2026-09-28 10:00:00", old_price, 0, 50,
                       "观察", "低", 100, old_ma10, 99, False, 80, True] + [None] * 17
                old[28] = True
                old[29] = 100.1
                trigger = 100.1
                event, _ = intraday._transition_from_previous(old, at, price, trigger)
                self.assertEqual(expected, event)

    def test_transition_uses_each_rounds_own_ma10_and_advancing_quote_time(self):
        old = [self.CODES[0], "2026-09-28 10:00:00", 111.0, 1.0, 60.0,
               "趋势保持", "低", 110.0, 110.0, 109.0, True, 75.0, True] + [None] * 17
        old[28] = True
        old[29] = 110.0
        # 旧价格高于旧 MA10，本轮价格低于本轮 MA10；应记失守而非收复。
        transition, state = intraday._transition_from_previous(
            old, datetime(2026, 9, 28, 10, 5), 112.0, 113.0)
        self.assertEqual("扫描观察到失守MA10", transition)
        self.assertEqual("扫描观察到失守", state)
        transition, state = intraday._transition_from_previous(
            old, datetime(2026, 9, 28, 10, 0), 115.0, 114.0)
        self.assertIsNone(transition)
        self.assertIn("未前进", state)
        recovered_last = list(old)
        recovered_last[23] = "扫描观察到收复MA10"
        transition, state = intraday._transition_from_previous(
            recovered_last, datetime(2026, 9, 28, 10, 5), 112.0, 112.0)
        self.assertEqual("收复保持", transition)
        self.assertEqual("收复保持", state)

    def test_quote_range_and_volume_are_required_for_intraday_validity(self):
        now = datetime(2026, 9, 28, 10, 0)
        q = {"quote_at": now.isoformat(sep=" "), "price": 10.2, "open": 10.0,
             "high": 10.1, "low": 9.9, "change_pct": 2.0,
             "amount_wan": 10.0, "volume_shou": 10.0}
        _, status, _ = intraday._fresh_quote(q, now, None, True)
        self.assertEqual("现价或开盘价超出日内高低价区间", status)
        q.update(price=10.0, high=10.1, low=9.9, open=10.0, amount_wan=0.0, volume_shou=0.0)
        _, status, _ = intraday._fresh_quote(q, now, None, True)
        self.assertEqual("当日无成交或停牌", status)

    def test_price_basis_mismatch_pauses_only_ma_judgment(self):
        flat_history = self._tag_history([
            {"date": bar["date"], "close": 100.0} for bar in self.bars])
        quote = {"quote_at": "2026-09-28 10:00:00", "last_close": 80.0,
                 "price_basis": "raw", "price_basis_source": "tencent_realtime_quote",
                 "last_close_semantics": "previous_trade_day_raw_close"}
        basis = intraday.price_basis_compatibility(
            quote, flat_history)
        self.assertFalse(basis["intraday_price_basis_comparable"])
        self.assertIn("待核验", basis["intraday_price_basis_status"])
        quote["last_close"] = 100.3
        comparable = intraday.price_basis_compatibility(
            quote, flat_history)
        self.assertTrue(comparable["intraday_price_basis_comparable"])

    def test_high_relative_score_cannot_qualify_a_down_day_as_current_strong(self):
        at = datetime(2026, 9, 28, 10, 0)
        rows = self._base_rows()
        quotes = {}
        for code in self.CODES:
            quotes[code] = {
                "quote_at": at.strftime("%Y-%m-%d %H:%M:%S"), "price": 116.0,
                "open": 115.0, "high": 117.0, "low": 114.5,
                "last_close": 119.0, "change_pct": (116.0 / 119.0 - 1) * 100,
                "amount_wan": 1000.0, "volume_shou": 10000,
                "board_type": "sh_main", "limit_pct": 10.0,
                "limit_up": 130.9, "limit_down": 107.1,
            }
        for row in rows:
            row.update({key: quotes[row["code"]][key] for key in
                        ("price", "open", "high", "low", "change_pct", "amount_wan")})
        quotes[self.CODES[5]].update(
            price=117.0, open=115.0, high=118.0,
            change_pct=(117.0 / 119.0 - 1) * 100)
        self._tag_quotes(quotes)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(intraday, "HISTORY_DIR", Path(tmp)):
            intraday.enrich(rows, [], quotes, self._histories(quotes, codes=self.CODES),
                            self.CODES, captured_at=at, session="早盘", save_reference=False)
        candidate = rows[5]
        self.assertLess(candidate["change_pct"], 0)
        self.assertGreater(candidate["intraday_relative_return_pct"], 0)
        self.assertGreaterEqual(candidate["price"], candidate["open"])
        self.assertTrue(candidate["intraday_trend_ok"])
        self.assertGreater(candidate["intraday_score"], 50)
        self.assertFalse(candidate["current_strong_candidate"])
        self.assertEqual(["当日涨幅为正"], candidate["current_strong_missing"])

    def test_quotes_outside_continuous_session_are_not_current_intraday_quotes(self):
        now = datetime(2026, 9, 28, 9, 31)
        q = {"quote_at": "2026-09-28 09:25:00", "price": 10.0, "open": 10.0,
             "high": 10.0, "low": 10.0, "change_pct": 0.0,
             "amount_wan": 1.0, "volume_shou": 1.0}
        _, status, _ = intraday._fresh_quote(q, now, None, True, "早盘")
        self.assertEqual("报价时间不符合连续交易时段", status)

    def test_close_stage_rejects_after_close_quotes_and_current_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows, _ = self._scan(datetime(2026, 9, 28, 15, 8), 2, Path(tmp),
                                 save=False, session="已收盘")
        self.assertTrue(all(not row["intraday_quote_fresh"] for row in rows))
        self.assertTrue(all(not row["current_strong_candidate"] for row in rows))
        self.assertTrue(all(not row["current_pullback_candidate"] for row in rows))
        self.assertTrue(all(not row["startup_candidate"] for row in rows))
        self.assertTrue(all(not row["turn_weak_repair_candidate"] for row in rows))
        self.assertEqual("报价时间不符合连续交易时段",
                         rows[4]["intraday_quote_status"])

    def test_lunch_updates_closing_judgment_and_other_frozen_sessions_do_not_create_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            morning_at = datetime(2026, 9, 28, 11, 25)
            morning, _ = self._scan(morning_at, 1, root, session="早盘")
            last_quote_at = morning[5]["intraday_quote_at"]
            lunch, lunch_snap = self._scan(datetime(2026, 9, 28, 11, 35), 2, root,
                                            session="午间休市")
            lunch_row = lunch[5]
            self.assertTrue(lunch_row['intraday_observation_available'])
            self.assertEqual("2026-09-28 11:30:00", lunch_row["last_valid_quote_at"])
            self.assertEqual("午间收市判断，截至11:30；每次获取均留痕", lunch_snap["intraday_model"]["phase_status"])
            self.assertFalse(lunch_row["intraday_score_stale"])
            self.assertFalse(lunch_row["current_strong_candidate"])
            self.assertIsNotNone(lunch_row['intraday_score'])

            premarket, premarket_snap = self._scan(datetime(2026, 9, 29, 9, 10), 1, root,
                                                   session="盘前")
            self.assertEqual("盘前观察，沿用最近交易日收盘结果", premarket[5]["intraday_trend_state"])
            self.assertIn("盘前观察", premarket[5]["auction_observation"]["status"])
            self.assertEqual("盘前观察，沿用最近收盘结果", premarket_snap["intraday_model"]["phase_status"])
            self.assertFalse(premarket[5]["current_strong_candidate"])

            auction, auction_snap = self._scan(datetime(2026, 9, 29, 9, 25), 1, root,
                                               session="集合竞价")
            self.assertIn("集合竞价观察", auction[5]["auction_observation"]["status"])
            self.assertEqual("集合竞价观察，与盘中榜分开", auction_snap["intraday_model"]["phase_status"])
            self.assertFalse(auction[5]["current_strong_candidate"])

            nontrading, nontrading_snap = self._scan(datetime(2026, 9, 29, 10, 0), 1, root,
                                                     session="非交易日")
            self.assertEqual("非交易日，显示最近交易日结果", nontrading[5]["intraday_quote_status"])
            self.assertEqual("2026-09-28", nontrading_snap["intraday_model"]["asof"])
            self.assertFalse(nontrading[5]["current_strong_candidate"])
            self.assertIsNone(nontrading[5]["intraday_transition"])


if __name__ == "__main__":
    unittest.main()
