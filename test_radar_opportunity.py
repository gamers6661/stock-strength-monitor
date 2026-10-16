"""Current radar contract, replacing V1 confirmation/timer/window expectations.
Old implementation and tests are preserved in the pre-change source backup.
Price-basis, missing values and immutable history still have dedicated regression suites.
"""
import copy
import json
import unittest
from unittest.mock import patch
import radar
import radar_opportunity as R
import market_strength as M
from test_market_strength import fixture

class RadarOpportunityTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture();self.s,self.q,self.p,self.h,self.c,self.now=self.f;self.code=next(iter(self.q))
        self.q[self.code].update(price=110.,open=100.,high=110.,low=100.,change_pct=10.)
    def run_round(self,**kw):
        radar.build_opportunities(self.s,self.q,self.p,{},self.h,self.c,now=self.now,**kw)
        R.validate(self.s);return self.s['stocks'][0]['market_strength']
    def test_state_samples_and_window_cannot_change_scores(self):
        a=copy.deepcopy(self.run_round(state={}))
        self.assertTrue(a['focus'])
        self.assertEqual(a,self.run_round())
        self.s['stocks'][0].update(trend_tier='A',watch_candidate=True,intraday_trend_ok=True,persistent_strong=True)
        self.assertEqual(a,self.run_round(state={'count':999,'confirmed':False,'span_seconds':0,'paused':True}))
    def test_no_state_or_confirmation_cache_write(self):
        with patch.object(R,'save_state',side_effect=AssertionError('legacy state write')) if hasattr(R,'save_state') else patch.object(R,'load_state',side_effect=AssertionError('legacy state read')):
            self.assertTrue(self.run_round(persist=True)['focus'])
    def test_today_negative_can_be_trend_strong(self):
        for b in self.h[self.code][-10:]:b.update(open=120.,close=120.,high=120.5,low=119.5)
        # Twenty-day gain remains intact at 119, below last close 120.
        self.q[self.code].update(price=119.,last_close=120.,open=120.,high=120.,low=118.,change_pct=-.83)
        r=self.run_round();self.assertTrue(r['trend_strong']);self.assertFalse(r['emotion_strong']);self.assertTrue(r['focus'])
    def test_risk_and_limit_do_not_hide(self):
        self.s['stocks'][0].update(intraday_serious_weakness=True,intraday_trade_restriction='涨停',intraday_risk_flags=['位置偏热','冲高回落'])
        self.assertTrue(self.run_round()['focus'])
    def test_board_does_not_rescue_or_block(self):
        a=copy.deepcopy(self.run_round());self.s['board_catalog']=[];self.assertEqual(a,self.run_round())
    def test_next_failed_round_exits(self):
        self.run_round();self.q[self.code].update(price=100.,open=100.,high=101.,low=99.,change_pct=0.)
        self.assertFalse(self.run_round()['focus'])
    def test_core_history_missing_not_zero(self):
        self.h[self.code]=[];r=self.run_round();self.assertIsNone(r['trend_score']);self.assertIsNone(r['emotion_score']);self.assertTrue(r['day_attack_strong'])
    def test_price_basis_unknown_blocks_only_trend(self):
        self.q[self.code]['price_basis']=None;r=self.run_round();self.assertIsNone(r['trend_score']);self.assertTrue(r['emotion_strong'])
    def test_unknown_atr_not_zero_or_one_cent(self):
        self.h[self.code]=self.h[self.code][-20:];r=self.run_round();self.assertIsNone(r['trend_score']);self.assertTrue(r['emotion_strong'])
    def test_zero_open_emotion_unknown_trend_still_valid(self):
        for i,b in enumerate(self.h[self.code][-20:]):
            v=100+i;b.update(open=v,close=v,high=v+.5,low=v-.5)
        self.q[self.code].update(price=120.,last_close=119.,high=120.,open=0.,change_pct=100*(120/119-1))
        r=self.run_round();self.assertIsNone(r['emotion_score']);self.assertTrue(r['trend_strong'])
    def test_future_quote_invalid(self):
        self.q[self.code]['quote_at']='2026-10-13 10:10:00';r=self.run_round();self.assertIsNone(r['trend_score']);self.assertIsNone(r['emotion_score'])
    def test_missing_quote_cannot_use_carried_price(self):
        del self.q[self.code];r=self.run_round();self.assertFalse(r['focus']);self.assertIsNone(r['trend_score'])
    def test_snapshot_json_roundtrip(self):
        self.run_round();self.s=json.loads(json.dumps(self.s));self.run_round()
    def test_public_build_reads_same_model(self):
        R.build(self.s,self.q,self.p,{},self.h,self.c,now=self.now);R.validate(self.s);self.assertEqual(self.s['radar_opportunity']['lists']['current'],self.s['market_strength']['stocks']['focus'])
    def test_raw_histories_and_pool_not_changed(self):
        before=copy.deepcopy((self.q,self.p,self.h,self.c,[b['member_codes'] for b in self.s['board_catalog']]))
        self.run_round();self.assertEqual(before,(self.q,self.p,self.h,self.c,[b['member_codes'] for b in self.s['board_catalog']]))
