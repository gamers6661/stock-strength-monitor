"""日期合并、连续窗口与指数/成员独立资格的真实边界。"""
from datetime import date, timedelta
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing

import board_trend as B


def sample(closes=None):
    closes = closes or [100+i for i in range(30)]
    day = date(2025, 11, 3)
    days = []
    while len(days) < len(closes):
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    return [dict(date=d, open=c, close=c, high=c+1, low=c-1, volume=100, amount=10000)
            for d, c in zip(days, closes)], days


class BoardTrendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'test.db'
        self.bars, self.days = sample()

    def tearDown(self):
        self.tmp.cleanup()

    def test_atr_gap_and_online_exact_formula(self):
        self.bars[-1].update(open=140, close=140, high=142, low=138)
        r = B.calculate(self.bars, self.days, self.days[-1])
        self.assertTrue(r['ready'])
        self.assertTrue(r['trend_online'])
        # 19个普通TR=2；末日含昨收128到最高142的跳空TR=14。
        self.assertAlmostEqual(r['atr20'], (19*2+14)/20)
        self.assertAlmostEqual(r['ma10_distance_atr'], (140-r['ma10'])/r['atr20'])

    def test_missing_latest_and_interior_both_block(self):
        latest = B.calculate(self.bars[:-1], self.days, self.days[-1])
        gap = B.calculate(self.bars[:20]+self.bars[21:], self.days, self.days[-1])
        self.assertFalse(latest['ready'])
        self.assertFalse(gap['ready'])
        self.assertEqual(gap['missing_dates'], [self.days[20]])
        self.assertIsNone(gap['trend_online'])

    def test_unfinished_and_nontrading_bars_cannot_change_result(self):
        baseline = B.calculate(self.bars, self.days, self.days[-1])
        extra = copy.deepcopy(self.bars[-1])
        extra.update(date='2025-12-31', close=1000, high=1001)
        self.assertEqual(baseline, B.calculate(self.bars+[extra], self.days, self.days[-1]))

    def test_initial_strength_and_weakening_are_adjacent_transitions(self):
        bars, days = sample([100-i*.1 for i in range(29)]+[150])
        r = B.calculate(bars, days, days[-1])
        self.assertTrue(r['initial_strength'])
        self.assertFalse(r['previous_online'])
        self.bars[-1].update(open=110, close=110, high=111, low=109)
        r = B.calculate(self.bars, self.days, self.days[-1])
        self.assertTrue(r['weakening'])
        self.assertFalse(r['trend_online'])

    def test_pullback_requires_existing_trend_and_actual_touch(self):
        self.bars[-1]['low'] = 124
        r = B.calculate(self.bars, self.days, self.days[-1])
        self.assertTrue(r['pullback'])
        self.assertEqual(r['pullback_kind'], '触及MA10收回')
        bars, days = sample([100-i*.1 for i in range(29)]+[150])
        bars[-1]['low'] = 95
        self.assertFalse(B.calculate(bars, days, days[-1])['pullback'])

    def test_ma5_must_exceed_ma10_even_when_both_rise_and_price_holds(self):
        bars, days = sample([100]*21+[110]*5+[90]*4+[111])
        r = B.calculate(bars, days, days[-1])
        self.assertGreater(r['ma5'], r['ma5_prev'])
        self.assertGreater(r['ma10'], r['ma10_prev'])
        self.assertGreater(r['close'], r['ma10'])
        self.assertLess(r['ma5'], r['ma10'])
        self.assertFalse(r['advance_signal'])
        self.assertFalse(r['strong_advance'])

    def test_three_day_ma5_startup_is_allowed_below_ma20(self):
        bars, days = sample([200]*20+[150]*5+[100]*5+[110,120,130])
        self.assertFalse(B.calculate(bars[:-1], days[:-1], days[-2])['observing'])
        r = B.calculate(bars, days, days[-1])
        self.assertEqual(r['state'], '启动观察')
        self.assertTrue(r['observing'])
        self.assertLess(r['close'], r['ma20'])
        self.assertFalse(r['ma20_support_established'])

    def test_advance_does_not_require_ma10_above_ma20(self):
        bars, days = sample([200]*20+[100]*8+[101,102,103])
        r = B.calculate(bars, days, days[-1])
        self.assertTrue(r['strong_advance'])
        self.assertGreater(r['ma5'], r['ma10'])
        self.assertLess(r['close'], r['ma20'])
        self.assertFalse(r['ma20_support_established'])

    def pullback_series(self, gaps, spike=None):
        closes = [100+i*.5 for i in range(60)]
        for gap in gaps:
            # ATR初始2点；解出相对当日MA10的收盘缺口，不采用盘后均线倒算。
            closes.append(sum(closes[-9:])/9-10/9*gap*2)
        bars, days = sample(closes)
        if spike is not None:
            bars[60+spike]['high'] = 1000
        return bars, days, B.calculate(bars, days, days[-1])

    def test_shallow_break_preserves_trend_despite_ma5_falling(self):
        _, _, r = self.pullback_series([.2])
        self.assertLess(r['ma5'], r['ma5_prev'])
        self.assertTrue(r['trend_online'])
        self.assertFalse(r['strong_advance'])
        self.assertEqual(r['state'], '浅破待收复')
        self.assertEqual(r['ma10_break_days'], 1)
        self.assertEqual(r['buffer_days_left'], 1)

    def test_third_break_day_downgrades_to_ma20_support(self):
        for gaps in ([.2], [.2,.2]):
            self.assertTrue(self.pullback_series(gaps)[2]['priority_observation'])
        _, _, r = self.pullback_series([.2,.2,.2])
        self.assertEqual(r['state'], '20日支撑观察')
        self.assertFalse(r['trend_online'])
        self.assertTrue(r['support_observation'])
        self.assertTrue(r['observing'])
        self.assertFalse(r['priority_observation'])

    def test_one_day_reclaim_cannot_reset_first_break_or_atr(self):
        bars, days, r = self.pullback_series([.2,-.05,.2])
        self.assertFalse(B.calculate(bars[:-1], days[:-1], days[-2])['strong_advance'])
        self.assertEqual(r['first_ma10_break'], days[60])
        self.assertEqual(r['ma10_break_days'], 3)
        self.assertEqual(r['pullback_atr_asof'], days[59])
        self.assertTrue(r['support_observation'])

    def test_atr_is_frozen_before_pullback_not_inflated_by_spike(self):
        _, days, r = self.pullback_series([.2,.4], spike=0)
        self.assertGreater(r['atr20'], 40)
        self.assertEqual(r['pullback_atr'], 2)
        self.assertEqual(r['pullback_atr_asof'], days[59])
        self.assertAlmostEqual(r['ma10_gap_fixed_atr'], .4)
        self.assertEqual(r['state'], '深回踩警戒')

    def test_large_ma10_break_downgrades_even_when_ma20_still_holds(self):
        _, _, r = self.pullback_series([1.01])
        self.assertGreaterEqual(r['close'], r['ma20'])
        self.assertTrue(r['support_observation'])
        self.assertFalse(r['priority_observation'])

    def test_two_reclaims_confirm_repair_and_reset_buffer(self):
        _, _, r = self.pullback_series([.2,-.05,-.05])
        self.assertTrue(r['repair_confirmed'])
        self.assertTrue(r['trend_online'])
        self.assertIsNone(r['first_ma10_break'])
        self.assertIsNone(r['pullback_atr'])

    def test_deep_intraday_wick_reclaimed_is_not_automatic_exit(self):
        self.bars[-1]['low'] = 110
        r = B.calculate(self.bars, self.days, self.days[-1])
        self.assertEqual(r['pullback_kind'], '深探收回')
        self.assertTrue(r['observing'])
        self.assertFalse(r['weak'])

    def test_ma20_close_exit_has_priority_no_same_day_reentry(self):
        self.bars[-1].update(open=110, close=110, high=150, low=109)
        r = B.calculate(self.bars, self.days, self.days[-1])
        self.assertEqual(r['state'], '趋势转弱')
        self.assertFalse(r['observing'])
        self.assertIsNone(r['episode_start'])
        self.assertEqual(r['exit_date'], self.days[-1])
        self.assertIn('20日', r['risk_reason'])

    def test_recovery_without_ma20_support_exits_on_ma10_failure(self):
        closes = [200]*20+[100]*8+[101,102,103]+[90]
        bars, days = sample(closes)
        r = B.calculate(bars, days, days[-1])
        self.assertTrue(r['weak'])
        self.assertFalse(r['observing'])
        self.assertIn('10日', r['risk_reason'])

    def test_ma20_arms_after_two_closes_and_overrules_fresh_advance_signal(self):
        closes = [200]*20+[100]*8+[101,102,103]
        for index, gap in enumerate((1,1,-1)):
            # 解出当日收盘与MA20正/负1点的差值。
            closes.append((sum(closes[-19:])+20*gap)/19)
            bars, days = sample(closes)
            r = B.calculate(bars, days, days[-1])
            self.assertTrue(r['advance_signal'])
            if index == 0:
                self.assertFalse(r['ma20_support_established'])
            elif index == 1:
                self.assertTrue(r['ma20_support_established'])
            else:
                self.assertTrue(r['weak'])
                self.assertFalse(r['strong_advance'])
                self.assertFalse(r['observing'])

    def test_startup_failure_before_strong_exits_after_two_closes_below_ma5(self):
        bars, days = sample([200]*20+[150]*5+[100]*5+[110,120,130]+[115,112])
        r = B.calculate(bars, days, days[-1])
        self.assertTrue(r['weak'])
        self.assertIn('5日', r['risk_reason'])

    def test_replay_never_uses_future_bars_or_carries_across_old_gap(self):
        bars, days, r = self.pullback_series([.2,-.05,.2])
        prior = B.calculate(bars[:-1], days[:-1], days[-2])
        self.assertEqual(prior, B.calculate(bars, days, days[-2]))
        # 22日窗口以前的缺口不会让旧的20日支撑或趋势穿过缺口继承。
        missing = bars[10]['date']
        gap = B.calculate([b for b in bars if b['date'] != missing], days, days[-1])
        self.assertTrue(gap['ready'])
        self.assertGreater(gap['replay_start'], missing)
        self.assertGreater(gap['episode_start'], missing)

    def test_flat_zero_atr_has_no_distance_no_false_online(self):
        for b in self.bars:
            b.update(open=100, close=100, high=100, low=100)
        r = B.calculate(self.bars, self.days, self.days[-1])
        self.assertTrue(r['ready'])
        self.assertIsNone(r['ma10_distance_atr'])
        self.assertFalse(r['trend_online'])

    def test_source_priority_and_older_payload_never_delete_latest(self):
        B.save('885001', self.bars, '2025.js', self.path)
        old = copy.deepcopy(self.bars[:-1])
        old[-1].update(open=10, close=10, low=9, high=11)
        B.save('885001', old, path=self.path)
        rows = B.load('885001', self.path)
        self.assertEqual(rows[-1], self.bars[-1])
        self.assertEqual(rows[-2], self.bars[-2])

    def test_invalid_bar_never_counts_as_complete(self):
        self.bars[-1]['close'] = float('nan')
        B.save('885001', self.bars, path=self.path)
        self.assertFalse(B.calculate(B.load('885001', self.path), self.days, self.days[-1])['ready'])

    def test_stale_last_annual_fallback_and_fresh_cache_no_requests(self):
        with patch.object(B.datafeed, 'fetch_ths_board_kline', return_value=('测试', self.bars[:-1])), \
             patch.object(B, 'parse_year', return_value=(None, self.bars)) as annual:
            r = B.observe('885001', '测试', self.days, self.days[-1], path=self.path)
            self.assertTrue(r['ready'])
            annual.assert_called_once_with('885001', '2025')
        with patch.object(B.datafeed, 'fetch_ths_board_kline') as fetch, patch.object(B, 'parse_year') as annual:
            self.assertTrue(B.observe('885001', '测试', self.days, self.days[-1], path=self.path)['ready'])
            fetch.assert_not_called()
            annual.assert_not_called()

    def test_mismatched_name_and_failure_cooldown(self):
        with patch.object(B.datafeed, 'fetch_ths_board_kline', return_value=('错误名称', self.bars)) as fetch:
            self.assertFalse(B.observe('885001', '测试', self.days, self.days[-1], path=self.path)['ready'])
            self.assertFalse(B.observe('885001', '测试', self.days, self.days[-1], path=self.path)['ready'])
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(B.load('885001', self.path), [])

    def test_attachment_never_mutates_stocks_and_no_parent_industry_alias(self):
        snap = dict(strength_model={'asof':self.days[-1]}, stocks=[{'code':'000001','score':99}],
                    board_catalog=[{'id':'industry:细分行业','name':'细分行业','type':'industry',
                                    'ranking_eligible':True,'trend_state':'持续扩散'}])
        before = copy.deepcopy(snap['stocks'])
        with patch.object(B, 'identities', return_value={'industry:上位行业':'881001'}):
            B.attach(snap, self.days, fetch=False, path=self.path)
        self.assertIsNone(snap['board_catalog'][0]['index_trend'])
        self.assertTrue(snap['board_catalog'][0]['member_diffusion'])
        self.assertEqual(before, snap['stocks'])

    def test_verified_completed_signal_day_bridges_in_memory_close_without_guessing(self):
        import sqlite3
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('CREATE TABLE kline(code TEXT,date TEXT)')
            conn.executemany('INSERT INTO kline VALUES(?,?)', [('1',d) for d in self.days[:-1]])
        asof = self.days[-1]
        self.assertNotIn(asof, B.calendar_from_db(asof, self.path))
        self.assertIn(asof, B.calendar_from_db(asof, self.path, {'stocks':[{'signal_date':asof}]}))
        self.assertNotIn(asof, B.calendar_from_db(asof, self.path, {'stocks':[{'signal_date':self.days[-2]}]}))

    def test_rolling_caller_window_does_not_truncate_episode_history(self):
        import sqlite3
        B.save('885001', self.bars, '2025.js', self.path)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('CREATE TABLE kline(code TEXT,date TEXT)')
            conn.executemany('INSERT INTO kline VALUES(?,?)', [('1',d) for d in self.days])
        snap = dict(strength_model={'asof':self.days[-1]}, stocks=[],
                    board_catalog=[{'id':'theme:测试','name':'测试','type':'theme','ranking_eligible':True}])
        with patch.object(B,'identities',return_value={'theme:测试':'885001'}):
            B.attach(snap, self.days[-22:], fetch=False, path=self.path)
        self.assertEqual(snap['board_trend_model']['calendar'],self.days)
        full = B.calculate(self.bars,self.days,self.days[-1])
        self.assertEqual(snap['board_catalog'][0]['index_trend']['episode_start'],full['episode_start'])


if __name__ == '__main__':
    unittest.main()
