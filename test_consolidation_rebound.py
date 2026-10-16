"""靠线反弹的路径证据、三条均线与原资格/退出规则相互独立。"""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import consolidation_rebound as rb
import intraday
import intraday_path
import trend_consolidation as tc
from test_trend_consolidation import ConsolidationFixture


class ReboundTests(unittest.TestCase):
    def point(self,time,price,period=10,**kwargs):
        pt=dict(at='2026-09-30 '+time,price=price,valid=True,atr20=1)
        pt[{5:'ma5_boundary',10:'ma10',20:'ma20'}[period]]=100
        pt.update(kwargs)
        return pt

    def chain(self,period=10):
        return [self.point(t,p,period) for t,p in [('10:00:00',101),('10:05:00',100.2),
                                                 ('10:10:00',100.8),('10:15:00',102.3)]]

    def test_three_lines_allow_near_touch_without_exact_hit(self):
        for period in (5,10,20):
            result=rb.sampled(self.chain(period),1)
            self.assertTrue(result['rebound_confirmed'])
            self.assertEqual(result['rebound_line'],period)
            self.assertEqual(result['rebound_samples'],2)
            self.assertGreater(result['rebound_touch_price'],result['rebound_touch_level'])

    def test_one_rise_repeated_gap_missing_and_late_do_not_fabricate_two(self):
        for kind in ('one','repeated','gap','missing','late','basis'):
            pts=self.chain()
            if kind=='one':pts=pts[:3]
            if kind=='repeated':pts[-1]['at']=pts[-2]['at']
            if kind=='gap':pts[-1]['at']='2026-09-30 10:30:01'
            if kind=='missing':pts.insert(-1,self.point('10:12:00',101,valid=False))
            if kind=='late':pts[-1]['at']='2026-09-30 10:08:00'
            if kind=='basis':pts[-2]['ma10']=None
            self.assertIsNone(rb.sampled(pts,1),kind)

    def test_only_small_rise_far_from_line_and_deep_undercut_are_rejected(self):
        for kind in ('small','far','deep','no_approach'):
            pts=self.chain()
            if kind=='small':pts[-1]['price']=101.9
            if kind=='far':pts[1]['price']=100.5
            if kind=='deep':pts[1]['price']=99.8
            if kind=='no_approach':pts[0]['price']=100.3
            self.assertIsNone(rb.sampled(pts,1),kind)

    def test_each_observation_uses_own_line_and_atr_and_nearest_line(self):
        pts=self.chain()
        pts[1].update(ma10=80,ma20=100,ma5_boundary=110)
        self.assertEqual(rb.sampled(pts,9)['rebound_line'],20)
        pts=self.chain()
        pts[1]['atr20']=10
        self.assertIsNone(rb.sampled(pts,.1))

    def test_nearer_line_must_have_approach_and_prices_on_boundary(self):
        pts=self.chain()
        pts[1]['price']=100
        result=rb.sampled(pts,1)
        self.assertEqual(result['rebound_line'],10)

    def test_real_meiyingsen_daily_case_is_ma10_and_has_no_future_information(self):
        data=json.loads((Path(__file__).parent/'test_fixtures'/'rebound_meiyingsen_20260930.json').read_text(encoding='utf-8'))
        bars=data['bars'];calendar=data['calendar']
        setup=tc.daily_setup(bars,'2026-09-29',calendar)
        result=rb.daily(setup,bars)
        self.assertEqual(result['rebound_line'],10)
        self.assertEqual(result['rebound_touch_at'],'2026-09-28')
        self.assertEqual(result['rebound_confirmed_at'],'2026-09-29')
        self.assertEqual(result,rb.daily(setup,[b for b in bars if b['date']<='2026-09-29']))
        earlier=tc.daily_setup(bars,'2026-09-28',calendar)
        self.assertIsNone(rb.daily(earlier,bars))

    def test_old_and_new_history_records_keep_own_boundary_and_basis_gate(self):
        old=['600001',None,102]+[None]*35
        old[7]=101.6;old[9]=100.1;old[28]=True;old[29]=100
        pt=intraday_path.point(old,'2026-09-30 10:05:05')
        self.assertAlmostEqual(pt['ma5_boundary'],101.5)
        self.assertAlmostEqual(pt['ma20'],100)
        new=old+[1,101.55,100.05]
        pt=intraday_path.point(new,'2026-09-30 10:05:05')
        self.assertEqual(pt['ma5_boundary'],101.55)
        self.assertEqual(pt['ma20'],100.05)
        old[28]=False
        self.assertIsNone(intraday_path.point(old,'')['ma20'])


class ReboundIntegrationTests(ConsolidationFixture):
    def test_rebound_labels_cannot_override_divergence_or_initial_breakout(self):
        fake=dict(rebound_confirmed=True,rebound_active=True,rebound_label='回踩反弹·MA10',rebound_line=10)
        snap,row,q,ctx=self.live(price=123.7)
        altered=dict(self.setup,needs_repair_confirmation=True,expanded_down_dates=['2026-09-24'])
        with patch.object(tc,'daily_setup',return_value=altered),patch.object(rb,'observe',return_value=fake):
            m=self.attach(snap,q,ctx)
        self.assertEqual(m['rows'][0]['stage'],'回踩反弹·MA10 · 分歧待修复')
        self.assertFalse(m['rows'][0]['confirmed'])
        snap,row,q,ctx=self.live()
        with patch.object(rb,'observe',return_value=fake):
            m=self.attach(snap,q,ctx,{'points':{'600001':[self.point()]}})
        self.assertEqual(m['rows'][0]['stage'],'初步突破')

    def test_rebound_cannot_keep_stock_that_loses_ma10_or_current_strict_trend(self):
        snap,row,q,ctx=self.live(price=110)
        with patch.object(rb,'observe') as detect:m=self.attach(snap,q,ctx)
        detect.assert_not_called()
        self.assertEqual(m['count'],0)

    def test_elapsed_days_are_completed_trading_days_and_today_is_separate(self):
        snap,row,q,ctx=self.live()
        m=self.attach(snap,q,ctx)
        item=m['rows'][0]
        self.assertEqual(item['consolidation_start'],self.bars[-3]['date'])
        self.assertEqual(item['consolidation_elapsed_days'],3)
        self.assertEqual(item['consolidation_day_number'],4)
        earlier=dict(self.setup,days=2,consolidation_asof=self.calendar[-2])
        tc.duration(earlier,self.calendar,self.day)
        self.assertEqual(earlier['consolidation_elapsed_days'],3)
        completed=dict(self.setup,completion_confirmed=True,completed_at=self.calendar[-1])
        tc.duration(completed,self.calendar,self.day)
        self.assertEqual(completed['consolidation_elapsed_days'],2)

    def test_rebound_conversion_uses_same_verified_quote_scale(self):
        fake=dict(rebound_confirmed=True,rebound_line=10,rebound_touch_price=120,
                  rebound_touch_level=120,rebound_confirm_price=123,rebound_atr=2,
                  rebound_confirmed_at=self.asof,rebound_touch_at=self.calendar[-2])
        snap,row,q,ctx=self.live(price=124.5*1.01)
        q['last_close']*=1.01
        ctx=intraday.align_price_basis(q,self.bars,self.calendar,observation_day=self.day,quote_at=q['quote_at'])
        with patch.object(rb,'daily',return_value=fake),patch.object(rb,'sampled',return_value=None):
            result=rb.observe(self.setup,self.bars,ctx,row,[])
        self.assertAlmostEqual(result['rebound_touch_price'],121.2)
        self.assertAlmostEqual(result['rebound_atr'],2.02)


if __name__=='__main__':unittest.main()
