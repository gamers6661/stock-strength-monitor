"""数据齐备但形态未形成、最新报价、固定平台和休市参考的业务边界。"""
import copy
import unittest
from unittest.mock import patch
import session_context as sc
import trend_consolidation as tc
from test_trend_consolidation import fixture
from test_price_basis import quote


class CurrentJudgmentTests(unittest.TestCase):
    def setUp(self):
        self.bars,self.calendar,self.asof,self.day=fixture()

    def build(self,price=125.4,at='10:10:00',session='早盘',captured=None,setup=None,structure=None,bars=None):
        bars=bars or self.bars
        q=quote(last_close=bars[-1]['close'],price=price,at=self.day+' '+at)
        row=dict(code='600001',name='样本',daily_attack_tier='A',trend_online=1,
                 trend_consolidation=setup or tc.daily_setup(bars,self.asof,self.calendar),
                 wyckoff_structure=structure or {})
        snap=dict(session=session,quote_capture_at=self.day+' '+(captured or at),
                  strength_model=dict(asof=self.asof),stocks=[row])
        model=sc.attach(snap,{'600001':q},{'600001':bars},self.calendar,baseline={})
        return row['session_context'],model

    def test_complete_history_and_zero_consolidation_days_still_judges_price(self):
        bars=copy.deepcopy(self.bars)
        for b,c in zip(bars[-3:],[128,131,134]):
            b.update(open=c,close=c,high=c+.3,low=c-.3)
        setup=tc.daily_setup(bars,self.asof,self.calendar)
        self.assertFalse(setup['eligible']);self.assertFalse(setup['pending'])
        self.assertEqual(setup['failure_kind'],'condition_unmet')
        self.assertEqual(setup['completed_consolidation_days'],0)
        c,_=self.build(price=137,bars=bars,setup=setup)
        self.assertTrue(c['history_evidence']['valid'])
        self.assertEqual(c['setup_state'],'尚未形成整理')
        self.assertEqual(c['current_label'],'20日新高突破')
        self.assertTrue(c['quote_valid']);self.assertIsNotNone(c['price_attack_score'])

    def test_latest_price_crosses_fixed_platform_without_moving_history(self):
        w=dict(platform_high=130,platform_low=120,atr0=2,price_scale_factor=1)
        before=copy.deepcopy(w)
        c,_=self.build(price=125.4,structure=w)
        d,_=self.build(price=132,at='10:11:00',structure=w)
        self.assertEqual(c['structure_state'],'原平台内承接')
        self.assertEqual(d['current_label'],'现价突破原平台，待成交量与收盘确认')
        self.assertAlmostEqual(d['breakout_threshold'],130.2)
        self.assertEqual(c['previous_close_asof'],d['previous_close_asof'])
        self.assertEqual(w,before)

    def test_current_weakness_overrides_historical_a(self):
        c,_=self.build(price=90)
        self.assertEqual(c['prior_daily_tier'],'A')
        self.assertEqual(c['current_label'],'现价失守MA20')
        self.assertFalse(c['monitor_candidate'])

    def test_lunch_last_morning_update_is_reference_and_never_new_candidate(self):
        c,_=self.build(at='11:31:00',session='午间休市',captured='12:20:00')
        self.assertTrue(c['quote_valid']);self.assertTrue(c['price_basis_valid'])
        self.assertEqual(c['observation_mode'],'午间最新报价参考')
        self.assertIsNotNone(c['current_label']);self.assertFalse(c['monitor_candidate'])

    def test_old_morning_price_is_not_retained_for_whole_lunch(self):
        c,_=self.build(at='11:23:00',session='午间休市',captured='12:20:00')
        self.assertFalse(c['quote_valid']);self.assertIsNone(c['price_attack_score'])

    def test_close_quote_reference_never_creates_candidate(self):
        c,_=self.build(at='15:10:00',session='已收盘',captured='17:20:00')
        self.assertTrue(c['quote_valid']);self.assertEqual(c['observation_mode'],'收盘报价参考')
        self.assertFalse(c['monitor_candidate'])

    def test_reference_from_another_day_rejected(self):
        q=quote(at=self.asof+' 11:31:00')
        from datetime import datetime
        at,reason=sc.live_quote(q,datetime.fromisoformat(self.day+' 12:20:00'),'午间休市')
        self.assertIsNone(at);self.assertIn('当日',reason)

    def test_unknown_basis_does_not_infer_fixed_platform(self):
        bars=copy.deepcopy(self.bars)
        for b in bars:b['price_basis_source']='unknown'
        c,_=self.build(bars=bars,structure=dict(platform_high=130,atr0=2))
        self.assertTrue(c['quote_valid']);self.assertFalse(c['price_basis_valid'])
        self.assertIsNone(c['structure_state']);self.assertIn('待核验',c['current_label'])

    def test_missing_completed_day_differs_from_unformed_pattern(self):
        c,_=self.build(bars=self.bars[:-2]+self.bars[-1:])
        self.assertFalse(c['history_evidence']['valid'])
        self.assertEqual(c['setup_state'],'历史数据待补齐')

    def test_after_daily_update_previous_close_archive_is_still_previous_day(self):
        q=quote(last_close=self.bars[-1]['close'],price=125.4,at=self.day+' 15:10:00')
        row=dict(code='600001',daily_attack_tier='C',trend_online=1)
        snap=dict(session='已收盘',quote_capture_at=self.day+' 16:00:00',
                  strength_model=dict(asof=self.day),stocks=[row])
        with patch.object(sc,'daily_baseline',return_value={'600001':dict(tier='A',score=90)}):
            m=sc.attach(snap,{'600001':q},{'600001':self.bars},self.calendar+[self.day],baseline={})
        c=row['session_context']
        self.assertEqual(m['previous_close_asof'],self.asof)
        self.assertEqual(c['prior_daily_tier'],'A');self.assertEqual(c['background_tier'],'C')


if __name__=='__main__':unittest.main()
