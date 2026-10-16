"""趋势整理资格、未来信息隔离与逐轮确认的业务场景验收。"""
import copy
import json
from pathlib import Path
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

import intraday
import trend_consolidation as tc


def fixture():
    days=[]
    day=datetime(2026,8,3)
    while len(days)<40:
        if day.weekday()<5: days.append(day.date().isoformat())
        day+=timedelta(days=1)
    closes=[90+.2*i for i in range(27)]+[98+3*i for i in range(10)]+[124,123,123.6]
    bars=[dict(date=d,open=c,close=c,high=c+.3,low=c-.3,
               volume=800 if i>=37 else 2000 if i>=27 else 1000,
               price_basis='qfq',price_basis_source='tencent_qfqday') for i,(d,c) in enumerate(zip(days,closes))]
    asof=days[-1]
    observation_day=(datetime.fromisoformat(asof)+timedelta(days=3)).date().isoformat()
    return bars,days,asof,observation_day


class ConsolidationFixture(unittest.TestCase):
    def setUp(self):
        self.bars,self.calendar,self.asof,self.day=fixture()
        self.setup=tc.daily_setup(self.bars,self.asof,self.calendar)

    def live(self,time='10:10:00',price=125.4):
        q=dict(price=price,open=123.5,high=max(125,price),low=123,last_close=self.bars[-1]['close'],
               price_basis='raw',price_basis_source='tencent_realtime_quote',
               last_close_semantics='previous_trade_day_raw_close',quote_at=self.day+' '+time)
        context=intraday.align_price_basis(q,self.bars,self.calendar,observation_day=self.day,quote_at=q['quote_at'])
        row=dict(code='600001',name='强股整理样本',price=price,change_pct=(price/q['last_close']-1)*100,
                 daily_attack_tier='C',intraday_observation_available=True,intraday_quote_fresh=True,
                 intraday_judgment_at=q['quote_at'],intraday_quote_at=q['quote_at'],
                 intraday_price_basis_comparable=True,intraday_ma10_trigger_price=context['thresholds'][10],
                 intraday_relative_return_pct=1,intraday_open_return_pct=(price/q['open']-1)*100,
                 intraday_risk_flags=[],trend_online=True)
        snap=dict(generated_at=q['quote_at'],quote_capture_at=q['quote_at'],session='早盘',
                  strength_model=dict(asof=self.asof),stocks=[row])
        return snap,row,q,context

    def attach(self,snap,q,context,history=None,previous=None):
        with patch.object(tc,'historical_a_dates',return_value={}):
            return tc.attach(snap,{'600001':self.bars},{'600001':q},{'600001':context},self.calendar,
                             history=history,previous=previous)

    def point(self,time='10:05:00',price=125.4,valid=True):
        return dict(at=self.day+' '+time,valid=valid,price=price,ma10=117,ma20=110,
                    relative=1,open_return=1,flags=[],trend_ok=True,ma5=124,change=1.5)


class ConsolidationTests(ConsolidationFixture):

    def test_prior_attack_is_before_consolidation_and_current_c_survives(self):
        self.assertTrue(self.setup['eligible'],self.setup)
        self.assertTrue(self.setup['impulse5_pct']>=15 or self.setup['impulse10_pct']>=20)
        self.assertLess(self.setup['impulse_end'],self.setup['consolidation_start'])
        snap,row,q,ctx=self.live()
        model=self.attach(snap,q,ctx)
        self.assertEqual(model['count'],1)
        self.assertEqual(model['rows'][0]['daily_tier'],'C')

    def test_horizontal_not_near_line_is_not_missed(self):
        snap,row,q,ctx=self.live(price=124.2)
        model=self.attach(snap,q,ctx)
        self.assertEqual(model['rows'][0]['location'],'横盘整理')
        self.assertGreater(model['rows'][0]['distance_ma_atr']['10'],.8)

    def test_tight_rising_horizontal_can_make_a_new_closing_high(self):
        bars=copy.deepcopy(self.bars)
        for b,c in zip(bars[-3:],[125.1,125.15,125.2]): b.update(open=c,close=c,low=c-.15,high=c+.15)
        result=tc.daily_setup(bars,self.asof,self.calendar)
        self.assertTrue(result['eligible'],result)
        self.assertEqual(result['shape'],'横盘整理')
        self.assertEqual(result['days'],3)
        self.assertEqual(result['anchor_kind'],'上涨窗口末日')

    def test_recent_online_does_not_bypass_current_ma5_crossing(self):
        bars=copy.deepcopy(self.bars)
        closes=[112,116,120,124,125,126,125,124,123,122,123,124]
        for b,c in zip(bars[-12:],closes): b.update(open=c,close=c,low=c-.3,high=c+.3)
        result=tc.daily_setup(bars,self.asof,self.calendar)
        self.assertFalse(result['eligible'],result)
        self.assertIn('MA5>MA10>MA20',result['reason'])

    def test_slow_stock_and_downtrend_are_excluded(self):
        bars=copy.deepcopy(self.bars)
        closes=[90+.2*i for i in range(37)]+[96.9,96.8,96.95]
        for b,c in zip(bars,closes): b.update(open=c,close=c,low=c-.2,high=c+.2)
        self.assertIn('进攻不足',tc.daily_setup(bars,self.asof,self.calendar)['reason'])
        bars[-1].update(close=80,open=80,low=79,high=81)
        self.assertFalse(tc.daily_setup(bars,self.asof,self.calendar)['eligible'])

    def test_future_bars_do_not_change_historical_setup(self):
        future=dict(self.bars[-1],date=self.day,open=1000,close=1000,high=1001,low=999)
        self.assertEqual(self.setup,tc.daily_setup(self.bars+[future],self.asof,self.calendar+[self.day]))

    def test_calendar_gap_mixed_basis_and_bad_ohlc_are_pending(self):
        for kind in ('gap','basis','ohlc'):
            bars=copy.deepcopy(self.bars)
            if kind=='gap': bars.pop(10)
            if kind=='basis': bars[2]['price_basis']='raw'
            if kind=='ohlc': bars[1]['high']=1
            result=tc.daily_setup(bars,self.asof,self.calendar)
            self.assertFalse(result['eligible'])
            self.assertTrue(result['pending'])

    def test_volume_unknown_does_not_mean_shrink(self):
        bars=copy.deepcopy(self.bars)
        bars[-1]['volume']=None
        result=tc.daily_setup(bars,self.asof,self.calendar)
        self.assertTrue(result['eligible'])
        self.assertIsNone(result['volume_ratio'])
        self.assertFalse(result['shrink_volume'])

    def test_repeated_quote_gap_and_missing_do_not_confirm_breakout(self):
        for history in ([self.point('10:10:00')],[self.point('09:50:00')],
                        [self.point(),self.point('10:07:00',valid=False)]):
            snap,row,q,ctx=self.live()
            model=self.attach(snap,q,ctx,{'points':{'600001':history}})
            self.assertEqual(model['rows'][0]['breakout_samples'],1)
            self.assertEqual(model['rows'][0]['stage'],'平台突破待确认')

    def test_two_distinct_samples_confirm_and_reversal_cancels(self):
        snap,row,q,ctx=self.live()
        model=self.attach(snap,q,ctx,{'points':{'600001':[self.point()]}})
        self.assertEqual(model['rows'][0]['stage'],'初步突破')
        snap,row,q,ctx=self.live(price=123.7)
        model=self.attach(snap,q,ctx,{'points':{'600001':[self.point()]}})
        self.assertEqual(model['rows'][0]['breakout_samples'],0)
        self.assertFalse(model['rows'][0]['confirmed'])

    def test_platform_is_fixed_and_price_basis_conversion_applies(self):
        snap,row,q,ctx=self.live(price=124.5*1.01)
        # 全部比较量按同一已核验比例转换；不拿当日最高价移动平台。
        q['last_close']*=1.01
        ctx=intraday.align_price_basis(q,self.bars,self.calendar,observation_day=self.day,quote_at=q['quote_at'])
        row['intraday_ma10_trigger_price']=ctx['thresholds'][10]
        model=self.attach(snap,q,ctx)
        self.assertAlmostEqual(model['rows'][0]['platform_high'],self.setup['platform_high']*1.01,places=4)

    def test_current_ma10_loss_or_severe_risk_exits(self):
        for kind in ('ma10','risk','restricted'):
            snap,row,q,ctx=self.live(price=110 if kind=='ma10' else 124.5)
            if kind=='risk': row['intraday_risk_flags']=['明显冲高回落']
            if kind=='restricted': row['intraday_trade_restriction']=True
            model=self.attach(snap,q,ctx)
            self.assertEqual(model['count'],0)
            self.assertEqual(len(model['pending_rows']),1)
            self.assertEqual(model['withdrawn_rows'],[])

    def test_missing_quote_retains_last_valid_and_valid_weak_quote_exits(self):
        previous,row,q,ctx=self.live()
        self.attach(previous,q,ctx)
        snap,row,q,ctx=self.live(time='10:15:00')
        row.update(intraday_observation_available=False,intraday_judgment_at=None)
        model=self.attach(snap,q,ctx,previous=previous)
        self.assertTrue(model['rows'][0]['reference_only'])
        self.assertEqual(model['rows'][0]['quote_at'],self.day+' 10:10:00')
        snap,row,q,ctx=self.live(time='10:15:00',price=110)
        model=self.attach(snap,q,ctx,previous=previous)
        self.assertEqual(len(model['rows']),1)
        self.assertTrue(model['rows'][0]['downgraded_observation'])

    def test_lunch_keeps_judgment_and_afternoon_links_excluding_break(self):
        snap,row,q,ctx=self.live(time='11:30:00')
        snap['session']='午间休市';row['intraday_quote_fresh']=False
        morning=self.attach(snap,q,ctx,{'points':{'600001':[self.point('11:25:00')]}})
        self.assertEqual(morning['rows'][0]['stage'],'初步突破')
        snap,row,q,ctx=self.live(time='13:00:00')
        model=self.attach(snap,q,ctx,{'points':{'600001':[self.point('11:30:00')]}})
        self.assertEqual(model['rows'][0]['breakout_samples'],2)

    def test_retained_after_close_is_not_recomputed_with_close_bars(self):
        previous,row,q,ctx=self.live()
        self.attach(previous,q,ctx)
        snap=dict(previous,session='已收盘',strength_model=dict(asof=self.day),stocks=[])
        model=self.attach(snap,q,ctx,previous=previous)
        self.assertEqual(model['pending_rows'][0]['quote_at'],self.day+' 10:10:00')
        self.assertEqual(model['current_count'],0)
        self.assertTrue(model['pending_rows'][0]['reference_only'])

    def test_late_quote_cannot_add_confirmation(self):
        snap,row,q,ctx=self.live()
        points=[self.point('10:05:00'),self.point('10:02:00',price=1),self.point('10:05:00')]
        model=self.attach(snap,q,ctx,{'points':{'600001':points}})
        self.assertEqual(model['rows'][0]['breakout_samples'],2)

    def test_historical_a_never_bypasses_absolute_attack_amplitude(self):
        bars=copy.deepcopy(self.bars)
        closes=[90+.2*i for i in range(37)]+[96.9,96.8,96.95]
        for b,c in zip(bars,closes): b.update(open=c,close=c,low=c-.2,high=c+.2)
        self.assertFalse(tc.daily_setup(bars,self.asof,self.calendar,[bars[-4]['date']])['eligible'])
        self.assertFalse(tc.daily_setup(bars,self.asof,self.calendar,[self.day])['eligible'])

    def test_pending_context_keeps_reference_but_cannot_confirm(self):
        previous,row,q,ctx=self.live()
        self.attach(previous,q,ctx)
        snap,row,q,ctx=self.live(time='10:15:00')
        ctx=dict(ctx,valid=False,reason='来源不明')
        model=self.attach(snap,q,ctx,previous=previous)
        self.assertTrue(model['rows'][0]['reference_only'])
        self.assertEqual(model['pending_rows'][0]['reason'],'来源不明')

    def test_late_current_quote_is_only_pending(self):
        snap,row,q,ctx=self.live(time='10:04:00')
        model=self.attach(snap,q,ctx,{'points':{'600001':[self.point()]}})
        self.assertEqual(model['rows'],[])
        self.assertEqual(len(model['pending_rows']),1)

    def test_declining_lows_excluded_and_volume_divergence_requires_repair(self):
        bars=copy.deepcopy(self.bars)
        for b,c in zip(bars[-3:],[124,123.5,123]): b.update(open=c,close=c,low=c-.3,high=c+.3)
        self.assertEqual(tc.daily_setup(bars,self.asof,self.calendar)['reason'],'整理连续低点及收盘价下移')
        bars=copy.deepcopy(self.bars)
        bars[-2]['volume']=5000
        bars[-2].update(open=122.4,close=122.4,low=122.1,high=122.7)
        result=tc.daily_setup(bars,self.asof,self.calendar)
        self.assertTrue(result['eligible'])
        self.assertTrue(result['needs_repair_confirmation'])
        self.assertEqual(result['expanded_down_dates'],[bars[-2]['date']])
        self.bars=bars
        snap,row,q,ctx=self.live()
        model=self.attach(snap,q,ctx)
        self.assertEqual(model['count'],1)
        self.assertEqual(row['trend_consolidation']['stage'],'整理中 · 分歧待修复')
        self.assertEqual(row['trend_consolidation']['phase'],'consolidating')
        snap,row,q,ctx=self.live()
        model=self.attach(snap,q,ctx,{'points':{'600001':[self.point()]}})
        self.assertEqual(model['count'],1)
        self.assertIn('放量分歧后修复',model['rows'][0]['structure_note'])

    def test_absolute_thresholds_include_equality_and_ten_day_alternative(self):
        for closes,n,passed in (([100]*39+[115],5,True),([100]*39+[114.999],5,False),
                                ([100]*30+[110]*9+[120],10,True),([100]*30+[110]*9+[119.999],10,False)):
            bars=[dict(close=c,date=str(i)) for i,c in enumerate(closes)]
            result=tc.attack_before(bars,39)
            self.assertEqual(result['qualified'],passed)
            if passed:self.assertEqual(result['attack_period'],n)

    def test_intraday_crossing_exits_even_when_completed_daily_is_strict(self):
        snap,row,q,ctx=self.live()
        ctx=copy.deepcopy(ctx)
        # 上涨足够、MA10守住，但当日最近4日价格结构已使MA5低于MA10。
        closes=[90]*10+[123]*5+[115]*5
        for b,c in zip(ctx['aligned_bars'],closes): b['close']=c
        model=self.attach(snap,q,ctx)
        self.assertEqual(model['rows'],[])
        self.assertIn('盘中MA5未高于MA10',model['pending_rows'][0]['reason'])

    def test_past_non_bullish_sample_does_not_confirm_current_repair(self):
        snap,row,q,ctx=self.live()
        p=self.point();p['trend_ok']=False
        model=self.attach(snap,q,ctx,{'points':{'600001':[p]}})
        self.assertEqual(model['rows'][0]['breakout_samples'],1)

    def test_normal_turnover_is_not_historical_volume_divergence(self):
        bars=copy.deepcopy(self.bars)
        bars[-4]['volume']=5000
        bars[-3]['volume']=5000
        bars[-2]['volume']=5000
        bars[-2].update(open=122.4,close=122.4,low=122.1,high=122.7)
        result=tc.daily_setup(bars,self.asof,self.calendar)
        self.assertFalse(result['needs_repair_confirmation'])

    def test_attack_endpoints_never_use_post_consolidation_price(self):
        result=tc.attack_before(self.bars,36)
        altered=copy.deepcopy(self.bars)
        for b in altered[37:]:b['close']=1000
        self.assertEqual(result,tc.attack_before(altered,36))

    def test_completed_breakout_is_not_kept_for_three_days_in_observation(self):
        prefix=[];d=datetime.fromisoformat(self.bars[0]['date'])-timedelta(days=1)
        while len(prefix)<20:
            if d.weekday()<5:
                prefix.append(dict(self.bars[0],date=d.date().isoformat(),open=89,close=89,low=88.7,high=89.3))
            d-=timedelta(days=1)
        bars=list(reversed(prefix))+copy.deepcopy(self.bars)
        calendar=[b['date'] for b in bars]
        original=tc.daily_setup(bars,calendar[-1],calendar)
        d=datetime.fromisoformat(calendar[-1])
        for count,price in enumerate((127,127.5,128,128.5),1):
            d+=timedelta(days=1)
            while d.weekday()>=5:d+=timedelta(days=1)
            bars.append(dict(bars[-1],date=d.date().isoformat(),open=price,close=price,low=price-.3,high=price+.3))
            calendar.append(bars[-1]['date'])
            result=tc.daily_setup(bars,calendar[-1],calendar)
            self.assertFalse(result['eligible'])
            if count<=3:
                self.assertEqual(result['phase'],'completed')
                self.assertEqual(result['platform_high'],original['platform_high'])

    def test_large_current_move_is_completed_instead_of_observation(self):
        snap,row,q,ctx=self.live(price=135)
        earlier=self.point(price=135);earlier.update(ma5=125,change=9.22)
        model=self.attach(snap,q,ctx,{'points':{'600001':[earlier]}})
        self.assertEqual(model['count'],0)
        self.assertEqual(model['completed_count'],1)
        self.assertEqual(row['trend_consolidation']['stage'],'已整理完毕转强')

    def test_past_departure_cannot_reenter_same_setup_on_price_retreat(self):
        snap,row,q,ctx=self.live(price=124.5)
        earlier=self.point(price=135);earlier.update(ma5=125,change=9.22)
        second=dict(earlier,at=self.day+' 10:07:00')
        model=self.attach(snap,q,ctx,{'points':{'600001':[earlier,second]}})
        self.assertEqual(model['count'],0)
        self.assertEqual(model['withdrawn_rows'],[])
        self.assertEqual(model['completed_rows'][0]['stage'],'突破未站稳')
        self.assertFalse(model['completed_rows'][0]['current_breakout_confirmed'])

    def test_clear_move_inside_a_wide_platform_is_also_completed(self):
        setup=dict(self.setup,platform_high=150)
        self.assertIsNotNone(tc.departure_reason(setup,135,125,2,9.22,previous_high=140))
        self.assertIsNone(tc.completion_signal(setup,135,125,2,9.22,previous_high=140))
        self.assertIsNone(tc.departure_reason(setup,124,123,2,5,previous_high=126))

    def test_one_large_quote_requires_confirmation_not_completed_label(self):
        snap,row,q,ctx=self.live(price=135)
        model=self.attach(snap,q,ctx)
        self.assertEqual(model['rows'],[])
        self.assertEqual(model['completed_rows'],[])
        self.assertEqual(model['pending_rows'][0]['stage'],'整理转强待确认')

    def test_completion_repeated_gap_and_invalid_quotes_do_not_confirm(self):
        earlier=self.point(price=135);earlier.update(ma5=125,change=9.22)
        for history in ([dict(earlier,at=self.day+' 10:10:00')],
                        [dict(earlier,at=self.day+' 09:50:00')],
                        [earlier,self.point('10:07:00',valid=False)]):
            snap,row,q,ctx=self.live(price=135)
            model=self.attach(snap,q,ctx,{'points':{'600001':history}})
            self.assertEqual(model['completed_rows'],[])

    def test_rebound_below_platform_without_recovery_is_not_completion(self):
        setup=dict(self.setup,platform_high=150,peak_close=150,trough_close=120,pullback_atr=2)
        self.assertIsNone(tc.completion_signal(setup,135,125,2,9.22,previous_high=132))

    def test_completion_missing_context_is_pending_even_with_daily_evidence(self):
        snap,row,q,ctx=self.live()
        completed=dict(self.setup,eligible=False,phase='completed',completion_level=125,
                       completed_at=self.asof,reason='合格整理后转强')
        with patch.object(tc,'daily_setup',return_value=completed):
            model=self.attach(snap,q,dict(ctx,valid=False,reason='口径不可比'))
        self.assertEqual(model['completed_rows'],[])
        self.assertEqual(model['pending_rows'][0]['reason'],'口径不可比')

    def test_daily_completion_that_loses_its_level_keeps_ma10_tracking(self):
        snap,row,q,ctx=self.live(price=125.4)
        completed=dict(self.setup,eligible=False,phase='completed',completion_level=130,
                       completed_at=self.asof,completion_type='平台突破转强',reason='合格整理后转强')
        with patch.object(tc,'daily_setup',return_value=completed):
            model=self.attach(snap,q,ctx)
        self.assertEqual(model['withdrawn_rows'],[])
        self.assertEqual(model['completed_rows'][0]['stage'],'突破未站稳')
        self.assertFalse(model['completed_rows'][0]['current_breakout_confirmed'])

    def test_repair_requires_eighty_percent_recovery_and_previous_high(self):
        self.assertIsNone(tc.completion_signal(self.setup,124.59,123,2,7))
        signal=tc.completion_signal(self.setup,124.6,123,2,7)
        self.assertEqual(signal['kind'],'回踩修复转强')
        self.assertAlmostEqual(signal['level'],124.6)


class CompletedTrackingTests(ConsolidationFixture):
    def confirmed_previous(self):
        snap,row,q,ctx=self.live(price=135)
        point=self.point(price=135);point.update(ma5=125,change=9.22)
        self.attach(snap,q,ctx,{'points':{'600001':[point]}})
        return snap

    def review(self,previous,price=105,time='10:15:00',points=(),change=None):
        snap,row,q,ctx=self.live(time=time,price=price)
        if change: change(row,ctx)
        model=self.attach(snap,q,ctx,{'points':{'600001':list(points)}},previous)
        return snap,model

    def test_one_break_is_downgraded_two_breaks_exit_and_recovery_needs_two(self):
        previous=self.confirmed_previous()
        first,m=self.review(previous)
        self.assertEqual(m['completed_rows'][0]['tracking_state'],'ma20_test')
        self.assertFalse(m['completed_rows'][0]['current_breakout_confirmed'])
        second,m=self.review(first,time='10:20:00')
        self.assertEqual(m['completed_rows'],[])
        self.assertEqual(m['withdrawn_rows'][0]['tracking_state'],'ma20_lost')
        recovered,m=self.review(second,price=125.4,time='10:25:00')
        self.assertEqual(m['completed_rows'],[])
        self.assertEqual(m['withdrawn_rows'][0]['tracking_state'],'ma20_repair_pending')
        recovered,m=self.review(recovered,price=125.4,time='10:30:00')
        self.assertEqual(m['count'],0)
        self.assertEqual(m['completed_rows'][0]['tracking_state'],'ma20_repaired')
        self.assertTrue(m['completed_rows'][0]['trend_exit_at'])
        self.assertEqual(m['completed_rows'][0]['completed_at'],previous['trend_consolidation']['completed_rows'][0]['completed_at'])

    def test_repeated_break_gap_and_invalid_cannot_confirm_exit(self):
        for kind in ('repeat','gap','invalid'):
            previous=self.confirmed_previous()
            first,m=self.review(previous)
            time='10:15:00' if kind=='repeat' else '10:40:01' if kind=='gap' else '10:20:00'
            points=[self.point('10:17:00',valid=False)] if kind=='invalid' else []
            _,m=self.review(first,time=time,points=points)
            self.assertEqual(m['withdrawn_rows'],[],kind)
            self.assertEqual(m['completed_rows'][0]['ma20_below_samples'],1,kind)

    def test_each_acquisition_uses_its_own_ma20_not_current_boundary(self):
        previous=self.confirmed_previous()
        pt=self.point('10:15:00',price=105);pt['ma20']=104
        _,m=self.review(previous,time='10:20:00',points=[pt])
        self.assertEqual(m['completed_rows'][0]['ma20_below_samples'],1)

    def test_lunch_break_does_not_interrupt_ma20_confirmation(self):
        previous=self.confirmed_previous()
        first,m=self.review(previous,time='11:30:00')
        _,m=self.review(first,time='13:00:00')
        self.assertEqual(m['withdrawn_rows'][0]['ma20_below_samples'],2)

    def test_unknown_or_late_current_quote_keeps_history_without_current_strength(self):
        for kind in ('basis','missing','late','restricted'):
            previous=self.confirmed_previous()
            def change(row,ctx):
                if kind=='basis': ctx.update(valid=False,reason='来源不明')
                if kind=='missing': row['intraday_observation_available']=False
                if kind=='restricted': row['intraday_trade_restriction']=True
            points=[self.point('10:20:00')] if kind=='late' else []
            pending,m=self.review(previous,change=change,points=points)
            self.assertEqual(m['completed_rows'],[],kind)
            self.assertTrue(m['pending_rows'][0]['completion_confirmed'],kind)
            self.assertFalse(m['pending_rows'][0]['current_breakout_confirmed'],kind)
            self.assertFalse(m['pending_rows'][0]['trend_exited'],kind)
            if kind!='late':
                _,m=self.review(pending,price=135,time='10:25:00')
                self.assertEqual(len(m['completed_rows']),1,kind)

    def test_ma5_cross_and_risk_downgrade_only_after_completion(self):
        for kind in ('ma5','cross','risk'):
            previous=self.confirmed_previous()
            def change(row,ctx):
                if kind=='ma5': ctx['provisional_ma'][5]=136
                if kind=='cross':
                    for b,c in zip(ctx['aligned_bars'],[90]*10+[123]*5+[115]*5): b['close']=c
                if kind=='risk': row['intraday_risk_flags']=['明显冲高回落']
            _,m=self.review(previous,price=135,change=change)
            self.assertEqual(m['withdrawn_rows'],[],kind)
            self.assertFalse(m['completed_rows'][0]['current_breakout_confirmed'],kind)
            self.assertNotEqual(m['completed_rows'][0]['tracking_state'],'holding',kind)

    def test_history_completion_is_found_before_current_ma10_or_risk_gate(self):
        points=[self.point('10:05:00',price=135),self.point('10:07:00',price=135)]
        for pt in points: pt.update(ma5=125,change=9.22)
        snap,row,q,ctx=self.live(price=118)
        model=self.attach(snap,q,ctx,{'points':{'600001':points}})
        self.assertEqual(model['completed_rows'][0]['tracking_state'],'ma10_test')
        self.assertTrue(model['completed_rows'][0]['completion_confirmed'])

    def test_tracking_survives_current_daily_qualification_failure(self):
        previous=self.confirmed_previous()
        with patch.object(tc,'daily_setup',return_value=dict(eligible=False,reason='完成日未满足MA5>MA10>MA20')):
            _,m=self.review(previous,price=124)
        self.assertEqual(m['count'],0)
        self.assertEqual(len(m['completed_rows']),1)

    def test_unknown_original_price_basis_is_pending_not_fabricated_exit(self):
        previous=self.confirmed_previous()
        self.bars[0]['price_basis_source']='unknown'
        _,m=self.review(previous,price=110)
        self.assertTrue(m['pending_rows'][0]['completion_confirmed'])
        self.assertEqual(m['withdrawn_rows'],[])

    def close(self,previous,price=105):
        bars=copy.deepcopy(self.bars)
        bars.append(dict(bars[-1],date=self.day,open=price,close=price,high=price+.3,low=price-.3))
        snap=copy.deepcopy(previous);snap.update(session='已收盘',strength_model=dict(asof=self.day))
        model=tc.attach(snap,{'600001':bars},{},{},self.calendar+[self.day],previous=previous)
        return snap,model

    def test_formal_close_below_ma20_exits_even_without_two_intraday_breaks(self):
        previous=self.confirmed_previous()
        _,m=self.close(previous)
        r=m['withdrawn_rows'][0]
        self.assertEqual(r['tracking_state'],'ma20_close_lost')
        self.assertTrue(r['completion_confirmed'])
        self.assertLess(r['close_review_price'],r['close_review_ma20'])
        self.assertEqual(r['quote_at'],previous['trend_consolidation']['completed_rows'][0]['quote_at'])

    def test_close_above_ma10_but_below_breakout_is_downgraded(self):
        _,m=self.close(self.confirmed_previous(),price=121)
        self.assertEqual(m['completed_rows'][0]['tracking_state'],'breakout_failed')
        self.assertFalse(m['completed_rows'][0]['current_breakout_confirmed'])

    def test_missing_formal_bar_keeps_pending_and_does_not_exit(self):
        previous=self.confirmed_previous()
        snap=copy.deepcopy(previous);snap.update(session='已收盘',strength_model=dict(asof=self.day))
        m=self.attach(snap,{}, {},previous=previous)
        self.assertTrue(m['pending_rows'][0]['completion_confirmed'])
        self.assertEqual(m['withdrawn_rows'],[])

    def test_close_recovery_is_not_two_samples(self):
        first,_=self.review(self.confirmed_previous())
        second,_=self.review(first,time='10:20:00')
        _,m=self.close(second,price=135)
        self.assertEqual(m['completed_rows'],[])
        self.assertEqual(m['withdrawn_rows'][0]['tracking_state'],'ma20_repair_pending')

    def test_close_retains_all_groups_in_detail_and_export_rows(self):
        previous=self.confirmed_previous()
        snap,m=self.close(previous)
        self.assertEqual(snap['stocks'][0]['trend_consolidation'],m['withdrawn_rows'][0])

    def test_confirmed_history_survives_day_rollover_and_does_not_reenter_main(self):
        previous=self.confirmed_previous();original_at=previous['trend_consolidation']['completed_rows'][0]['completed_at']
        for count in range(5):
            price=124.0
            self.bars.append(dict(self.bars[-1],date=self.day,open=price,close=price,low=price-.3,high=price+.3))
            self.calendar.append(self.day);self.asof=self.day
            next_day=datetime.fromisoformat(self.day)+timedelta(days=1)
            while next_day.weekday()>=5:next_day+=timedelta(days=1)
            self.day=next_day.date().isoformat()
            snap,row,q,ctx=self.live(price=124)
            m=self.attach(snap,q,ctx,previous=previous)
            self.assertEqual(m['rows'],[])
            self.assertEqual(m['completed_rows'][0]['completed_at'],original_at)
            previous=snap

    def test_daily_close_does_not_count_as_two_on_repeated_refresh(self):
        first,_=self.review(self.confirmed_previous())
        second,_=self.review(first,time='10:20:00')
        closed,m=self.close(second,price=135)
        samples=m['withdrawn_rows'][0]['ma20_recovery_samples']
        _,again=self.close(closed,price=135)
        self.assertEqual(again['withdrawn_rows'][0]['ma20_recovery_samples'],samples)

    def test_close_confirmation_preserves_prior_intraday_exit_time(self):
        first,_=self.review(self.confirmed_previous())
        second,m=self.review(first,time='10:20:00')
        original=m['withdrawn_rows'][0]['trend_exit_at']
        _,m=self.close(second,price=105)
        self.assertEqual(m['withdrawn_rows'][0]['trend_exit_at'],original)
        self.assertEqual(m['withdrawn_rows'][0]['close_review_day'],self.day)

    def test_saved_checkpoint_blocks_a_rollback_quote_without_acquisition_history(self):
        previous=self.confirmed_previous()
        _,m=self.review(previous,price=118,time='10:08:00')
        self.assertEqual(m['completed_rows'],[])
        self.assertTrue(m['pending_rows'][0]['completion_confirmed'])

    def test_repaired_ma20_with_ma5_cross_stays_cooling_instead_of_attack(self):
        first,_=self.review(self.confirmed_previous())
        second,_=self.review(first,time='10:20:00')
        third,_=self.review(second,price=124.5,time='10:25:00')
        def change(row,ctx):ctx['provisional_ma'][5]=130
        _,m=self.review(third,price=124.5,time='10:30:00',change=change)
        self.assertEqual(m['withdrawn_rows'],[])
        self.assertFalse(m['completed_rows'][0]['current_breakout_confirmed'])
        self.assertTrue(m['completed_rows'][0]['ma20_repaired_after_exit'])

    def test_restricted_current_quote_cannot_supply_second_completion_sample(self):
        point=self.point(price=135);point.update(ma5=125,change=9.22)
        snap,row,q,ctx=self.live(price=135);row['intraday_trade_restriction']=True
        m=self.attach(snap,q,ctx,{'points':{'600001':[point]}})
        self.assertEqual(m['completed_rows'],[])
        self.assertFalse(row['trend_consolidation'].get('completion_confirmed'))

    def test_past_confirmed_completion_is_preserved_as_pending_when_current_restricted(self):
        point=self.point(price=135);point.update(ma5=125,change=9.22)
        second=dict(point,at=self.day+' 10:07:00')
        snap,row,q,ctx=self.live(price=135);row['intraday_trade_restriction']=True
        m=self.attach(snap,q,ctx,{'points':{'600001':[point,second]}})
        self.assertEqual(m['completed_rows'],[])
        self.assertTrue(m['pending_rows'][0]['completion_confirmed'])
        self.assertFalse(m['pending_rows'][0]['current_breakout_confirmed'])

    def test_formal_close_loader_avoids_raw_quote_overlay_and_keeps_daily_inputs_unchanged(self):
        previous=self.confirmed_previous()
        bars=copy.deepcopy(self.bars)
        bars.append(dict(bars[-1],date=self.day,open=121,close=121,low=120.7,high=121.3))
        mixed=copy.deepcopy(bars)
        mixed[-1].update(price_basis='raw',price_basis_source='tencent_realtime_quote')
        snap=copy.deepcopy(previous);snap.update(session='已收盘',strength_model=dict(asof=self.day))
        m=tc.attach(snap,{'600001':mixed},{},{},self.calendar+[self.day],previous=previous,
                    close_history_loader=lambda code:bars)
        self.assertEqual(m['pending_rows'],[])
        self.assertEqual(m['completed_rows'][0]['close_review_price_basis'],'qfq')
        self.assertEqual(mixed[-1]['price_basis'],'raw')
        self.assertEqual(m['completed_rows'][0]['stage'],'突破未站稳')


class RealConsolidationCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data=json.loads((Path(__file__).parent/'test_fixtures'/'consolidation_20260930.json').read_text(encoding='utf-8'))
        cls.klines,cls.calendar=data['klines'],data['calendar']

    def result(self,code,day):return tc.daily_setup(self.klines[code],day,self.calendar)

    def test_main_impulse_day_cannot_be_retrospectively_called_completion(self):
        result=self.result('600641','2026-09-29')
        self.assertTrue(result['eligible'])
        self.assertEqual(result['phase'],'consolidating')
        self.assertEqual(result['peak_date'],'2026-09-24')
        self.assertEqual(result['days'],2)

    def test_bottom_first_turn_without_prior_bullish_attack_is_excluded(self):
        result=self.result('002242','2026-09-23')
        self.assertFalse(result['eligible'])
        self.assertNotEqual(result.get('phase'),'completed')
        self.assertFalse(self.result('002242','2026-09-29')['eligible'])

    def test_one_day_pause_is_not_a_completed_consolidation(self):
        result=self.result('601811','2026-09-29')
        self.assertFalse(result['eligible'])
        self.assertNotEqual(result.get('phase'),'completed')

    def test_prior_qualified_setup_can_cover_initial_turn_instead_of_disappearing(self):
        result=self.result('002388','2026-09-29')
        self.assertTrue(result['eligible'])
        self.assertTrue(result['daily_initial'])
        self.assertEqual(result['phase'],'initial')
        self.assertEqual(result['consolidation_asof'],'2026-09-28')

    def test_actual_completed_examples_have_structure_and_completion_evidence(self):
        for code in ('002487','000710','600059','002388'):
            result=self.result(code,'2026-09-30')
            self.assertEqual(result.get('phase'),'completed',result)
            self.assertGreaterEqual(result['days'],2)
            self.assertTrue(result['attack_trend_online'])
            self.assertGreater(result['completed_at'],result['consolidation_asof'])
            self.assertTrue(result['completion_confirmed'])

    def test_real_cases_never_use_future_bars(self):
        for code,bars in self.klines.items():
            for day in [d for d in self.calendar if d>='2026-09-14']:
                self.assertEqual(self.result(code,day),tc.daily_setup([b for b in bars if b['date']<=day],day,self.calendar))


if __name__=='__main__': unittest.main()
