"""验证进攻与低波动分离、真实形态、价格口径和时段边界。"""
import copy
import tempfile
from pathlib import Path
from datetime import datetime
import unittest
from unittest.mock import patch

import attack_model as attack
import stock_strength
import strength
import scoring
import intraday_path
from test_stock_strength import bars


class AttackModelTest(unittest.TestCase):
    def fund_row(self, source='东财主力净流入', ratio=10):
        return dict(fund_today_yi=.1 if ratio > 0 else -.1 if ratio < 0 else 0,
                    fund_today_ratio=ratio, fund_today_source=source,
                    fund_today_at='2026-09-30 10:01:00', intraday_quote_at='2026-09-30 10:00:55')

    def test_fund_inputs_have_no_weight_or_score(self):
        for source, weight in [('东财主力净流入', .15), ('新浪当日超大单净额', .075)]:
            for ratio, score in [(-20, 0), (0, 50), (10, 75), (20, 100)]:
                f = attack.fund_confirmation(self.fund_row(source, ratio),
                    dict(source=source, stale=False, period='today'), '2026-09-30 10:02:00')
                self.assertEqual(f['weight'], 0)
                self.assertIsNone(f['score'])

    def test_missing_stale_wrong_date_unknown_source_or_conflicting_sign_not_zero(self):
        for kind in ('missing', 'stale', 'old', 'yesterday', 'source', 'sign', 'bad_ratio'):
            row = self.fund_row()
            meta = dict(source='东财主力净流入', stale=False)
            if kind == 'missing': row['fund_today_ratio'] = None
            if kind == 'stale': meta['stale'] = True
            if kind == 'old': row['fund_today_at'] = '2026-09-30 09:00:00'
            if kind == 'yesterday': row['fund_today_at'] = '2026-09-29 10:01:00'
            if kind == 'source': meta['source'] = '未核验来源'
            if kind == 'sign': row['fund_today_yi'] = -.1
            if kind == 'bad_ratio': row['fund_today_ratio'] = 101
            f = attack.fund_confirmation(row, meta, '2026-09-30 10:02:00')
            self.assertIsNone(f['score'], kind)
            self.assertEqual(f['weight'], 0, kind)

    def test_fund_does_not_change_live_or_daily_score(self):
        snap, quotes, contexts = self.live_fixture()
        attack.enrich(snap, quotes, contexts)
        price = snap['stocks'][0]['live_attack_score']
        self.assertEqual(snap['stocks'][0]['live_attack_price_score'], price)
        self.assertIsNone(snap['stocks'][0]['live_attack_fund']['score'])
        snap['stocks'][0].update(self.fund_row(ratio=-20))
        snap.update(generated_at='2026-09-30 10:02:00', fund_meta=dict(source='东财主力净流入', stale=False))
        attack.enrich(snap, quotes, contexts)
        row = snap['stocks'][0]
        self.assertEqual(row['live_attack_score'], price)
        self.assertEqual(row['stock_strength_score'], 66)

    def test_fund_cannot_promote_price_b_to_a(self):
        snap, quotes, contexts = self.live_fixture()
        snap['stocks'][0].update(self.fund_row(ratio=20))
        snap.update(generated_at='2026-09-30 10:02:00', fund_meta=dict(source='东财主力净流入', stale=False))
        item = {'score': 64, 'parts': {'attack5': 64, 'attack10': 64, 'attack20': 64}}
        with patch.object(attack, 'momentum_scores', return_value={'600001': item}):
            attack.enrich(snap, quotes, contexts)
        row = snap['stocks'][0]
        self.assertEqual(row['live_attack_score'], 64)
        self.assertEqual(row['live_attack_price_tier'], 'B')
        self.assertEqual(row['live_attack_tier'], 'B')
        self.assertFalse(row['attack_watch_candidate'])

    def test_legacy_lunch_observation_does_not_mix_new_fund_score(self):
        snap, quotes, contexts = self.live_fixture()
        attack.enrich(snap, quotes, contexts)
        snap['stocks'][0]['attack_model_version'] = attack.VERSION
        snap['stocks'][0].pop('live_attack_fund')
        snap['attack_monitor']['version'] = attack.VERSION
        new = copy.deepcopy(snap)
        new['session'] = '午间休市'
        new['stocks'][0].update(self.fund_row())
        new.update(generated_at='2026-09-30 10:02:00', fund_meta=dict(source='东财主力净流入', stale=False))
        attack.enrich(new, quotes, contexts, snap)
        self.assertEqual(new['attack_monitor']['reference_version'], attack.VERSION)
        self.assertIsNone(new['stocks'][0]['live_attack_fund']['score'])
        self.assertEqual(new['attack_monitor']['count'], 0)

    def test_slow_stock_has_low_score_even_as_relative_leader(self):
        returns = {'slow': {5: 1, 10: 2, 20: 3},
                   'flat': {5: 0, 10: 0, 20: 0}, 'fall': {5: -2, 10: -3, 20: -4}}
        score = attack.momentum_scores(returns)['slow']['score']
        self.assertLess(score, 65)
        self.assertEqual(attack.tier(score, returns['slow'], True), 'C')

    def test_explosive_stock_a_without_smoothness_or_volume_gate(self):
        r = {5: 6, 10: 12, 20: 15}
        score = attack.momentum_scores({'attack': r})['attack']['score']
        self.assertEqual(attack.tier(score, r, True), 'A')
        self.assertIsNone(attack.tier(score, r, False))

    def test_equal_returns_tied_and_missing_returns_not_zero(self):
        r = {5: 5, 10: 9, 20: 15}
        result = attack.momentum_scores({'a': r, 'b': r, 'missing': {5: 5, 20: 15}})
        self.assertNotIn('missing', result)
        self.assertEqual(result['a'], result['b'])

    def test_falling_leader_never_a(self):
        returns = {'leader': {5: -.1, 10: -.2, 20: -.3},
                   'weak': {5: -5, 10: -10, 20: -15}}
        score = attack.momentum_scores(returns)['leader']['score']
        self.assertEqual(attack.tier(score, returns['leader'], True), 'C')

    def test_tier_threshold_equality_and_no_quota(self):
        self.assertEqual(attack.tier(65, {5: 5, 10: 8, 20: 12}, True), 'A')
        self.assertEqual(attack.tier(64.99, {5: 5, 10: 8, 20: 12}, True), 'B')
        self.assertEqual(attack.tier(45, {5: -1, 10: 2, 20: 6}, True, 10), 'B')

    def test_reversal_does_not_pretend_twenty_day_breakout(self):
        history = bars(30, .05)
        history[-3].update(high=22.0)
        history[-1].update(open=21.4, close=21.2, high=21.6, low=21.1)
        p = attack.price_pattern(history, 21.7, 21, 2, live=True)
        self.assertEqual(p['event'], '反包修复')
        self.assertFalse(p['confirmed'])
        self.assertEqual(p['high20'], 22)
        p = attack.price_pattern(history, 22.1, 21, 3, live=True)
        self.assertEqual(p['event'], '整理突破')

    def test_prior_high_touch_and_line_loss_are_not_current_breakout(self):
        history = bars(30, .05)
        high = max(b['high'] for b in history[-20:])
        self.assertIsNone(attack.price_pattern(history, high, 21, 2)['event'])
        self.assertIsNone(attack.price_pattern(history, high+1, high+2, 5)['event'])

    def live_fixture(self):
        history = bars(30, .20)
        q = {'price': 27, 'change_pct': 5, 'open': 25.8}
        row = dict(code='600001', name='示例', price=27, change_pct=5,
                   intraday_quote_fresh=True, intraday_trend_ok=True,
                   intraday_serious_weakness=False, intraday_ma10_exact=24.9,
                   intraday_risk_flags=['触板未封', '位置偏热'],
                   stock_strength_score=66, trend_tier=None, daily_attack_tier='A')
        context = {'valid': True, 'aligned_bars': history}
        return {'session': '早盘', 'stocks': [row]}, {'600001': q}, {'600001': context}

    def test_risk_remains_visible_with_attack_and_daily_immutable(self):
        snap, quotes, contexts = self.live_fixture()
        before = copy.deepcopy(snap['stocks'][0])
        attack.enrich(snap, quotes, contexts)
        row = snap['stocks'][0]
        self.assertEqual(row['live_attack_tier'], 'A')
        self.assertTrue(row['attack_watch_candidate'])
        self.assertFalse(row['attack_risk_clear'])
        self.assertEqual(row['intraday_risk_flags'], before['intraday_risk_flags'])
        self.assertEqual(row['stock_strength_score'], before['stock_strength_score'])
        self.assertEqual(snap['attack_monitor']['rows'][0]['trend_tier'], 'A')

    def test_stale_unknown_basis_recovery_wait_and_serious_risk_never_candidate(self):
        for kind in ('stale', 'basis', 'recovery', 'severe'):
            snap, quotes, contexts = self.live_fixture()
            row = snap['stocks'][0]
            if kind == 'stale': row['intraday_quote_fresh'] = False
            if kind == 'basis': contexts['600001']['valid'] = False
            if kind == 'recovery': row['trade_status'] = 'trade_recovered_wait_daily'
            if kind == 'severe': row['intraday_serious_weakness'] = True
            attack.enrich(snap, quotes, contexts)
            self.assertFalse(row['attack_watch_candidate'], kind)
            if kind != 'severe': self.assertIsNone(row['live_attack_score'], kind)

    def test_lunch_reference_and_auction_do_not_generate_new_candidates(self):
        snap, quotes, contexts = self.live_fixture()
        attack.enrich(snap, quotes, contexts)
        for phase in ('午间休市', '盘前', '集合竞价', '非交易日', '已收盘'):
            new = copy.deepcopy(snap)
            new['session'] = phase
            attack.enrich(new, quotes, contexts, snap)
            self.assertFalse(new['stocks'][0]['attack_watch_candidate'], phase)
            self.assertEqual(new['attack_monitor']['count'], 0)
            if phase != '已收盘':
                self.assertTrue(new['attack_monitor']['retained'])
                self.assertEqual(len(new['attack_monitor']['rows']), 1)

    def test_attack_watch_does_not_require_day_range_for_one_price_limit(self):
        snap, quotes, contexts = self.live_fixture()
        row = snap['stocks'][0]
        row.update(intraday_score=None, intraday_trade_restriction='一字涨停',
                   intraday_risk_flags=['一字涨停'])
        attack.enrich(snap, quotes, contexts)
        self.assertTrue(row['attack_watch_candidate'])
        self.assertFalse(row['attack_risk_clear'])

    def test_auction_shortcut_clears_last_session_attack_candidates(self):
        now = datetime(2026, 9, 30, 9, 20, 0)
        previous = {'stocks': [{'code':'600001','attack_watch_candidate':True,
                               'attack_risk_clear':True}], 'coverage_catalog':[],
                    'attack_monitor': {'version':attack.VERSION,'count':1,'rows':[{'code':'600001'}]}}
        quotes = {'600001':{'price':10.5,'last_close':10,'ts':'20260930092000'}}
        with tempfile.TemporaryDirectory() as test_cache, \
             patch.object(scoring.config,'SNAPSHOT_JSON',Path(test_cache)/'snapshot.json'), \
             patch.object(scoring,'datetime') as clock, \
             patch.object(scoring.df,'build_pool',return_value={'600001':{}}), \
             patch.object(scoring.df,'realtime_quotes',return_value=quotes), \
             patch.object(intraday_path,'save_acquisition'), \
             patch.object(scoring.config,'atomic_write_text'):
            clock.now.return_value=now
            snap=scoring._auction_snapshot(previous,'quick',now)
        self.assertFalse(snap['stocks'][0]['attack_watch_candidate'])
        self.assertEqual(snap['attack_monitor']['count'],0)
        self.assertTrue(snap['attack_monitor']['retained'])

    def test_volume_and_drawdown_do_not_change_price_attack_score(self):
        series = {'a': bars(slope=.15), 'b': bars(slope=.15), 'c': bars(slope=.02)}
        for b in series['b'][-3:]:
            b['volume'] *= 8
            b['high'] += 3
        metrics = {c: strength.day_metrics(v) for c,v in series.items()}
        scores, _ = stock_strength.score(metrics, {c:{} for c in series}, series)
        self.assertEqual(scores['a']['stock_strength_score'], scores['b']['stock_strength_score'])


if __name__ == '__main__':
    unittest.main()
