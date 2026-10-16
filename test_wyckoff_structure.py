"""固定结构的时间顺序、失败留档、缺失数据与旁路隔离场景。"""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import wyckoff_structure as w
import trend_consolidation as tc
from test_trend_consolidation import fixture


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.bars,self.calendar,self.asof,self.day=fixture()
        self.cycle,issue=w.create_cycle('600001',self.bars,self.asof,self.calendar,
                                       self.day+' 10:00:00',price_factor=1)
        self.assertIsNone(issue)
        self.a=self.cycle['atr0']; self.u=self.cycle['platform_high']

    def add(self,close,low=None,high=None,volume=2000):
        d=datetime.fromisoformat(self.bars[-1]['date'])+timedelta(days=1)
        while d.weekday()>=5: d+=timedelta(days=1)
        bar=dict(date=d.date().isoformat(),open=close-.1*self.a,close=close,
                 low=close-.2*self.a if low is None else low,
                 high=close+.05*self.a if high is None else high,volume=volume,
                 price_basis='qfq',price_basis_source='tencent_qfqday')
        bar['open']=min(bar['high'],max(bar['low'],bar['open']))
        self.bars.append(bar);self.calendar.append(bar['date'])
        return bar

    def review(self,cycle=None):
        return w.review_daily(cycle or self.cycle,self.bars,self.bars[-1]['date'],
                              self.calendar,self.bars[-1]['date']+' 15:15:00')

    def breakout(self,volume=2000):
        return self.add(self.u+.6*self.a,low=self.u-.05*self.a,volume=volume)

    def live(self,cycle=None,price=None,points=(),at='10:10:00',fresh=True,session='早盘'):
        row=dict(code='600001',name='样本',price=price or self.u+self.a,
                 intraday_quote_fresh=fresh,intraday_quote_at=self.day+' '+at,
                 intraday_judgment_at=self.day+' '+at,intraday_trend_ok=True,
                 intraday_serious_weakness=False,intraday_risk_flags=[],overheated=False)
        return w.display_cycle(cycle or self.cycle,row,{'valid':True,'scale_factor':1},
                               points,session,self.day+' '+at)

    def test_fixed_platform_atr_and_reference_survive_large_breakout(self):
        self.breakout();cycle=self.review()
        self.assertEqual(cycle['state'],'volume_breakout')
        for k in ('cycle_id','platform_high','platform_low','atr0','volume0','origin'):
            self.assertEqual(cycle[k],self.cycle[k])

    def test_future_bar_cannot_create_past_event(self):
        self.breakout()
        cycle=w.review_daily(self.cycle,self.bars,self.asof,self.calendar,self.day+' 10:00:00')
        self.assertEqual(cycle['events'],[])
        self.assertEqual(cycle['state'],'consolidating')

    def test_equal_threshold_does_not_break_out(self):
        self.add(self.u+.1*self.a)
        self.assertEqual(self.review()['state'],'consolidating')

    def test_missing_volume_preserves_price_fact_without_volume_confirmation(self):
        self.breakout(volume=None);cycle=self.review()
        self.assertEqual(cycle['state'],'price_breakout')
        self.assertIsNone(cycle['attempts'][0]['volume_at'])
        self.assertFalse(self.live(cycle)['current_structure_clear'])

    def test_low_volume_and_low_close_location_do_not_confirm(self):
        self.breakout(volume=1000)
        self.assertEqual(self.review()['state'],'price_breakout')
        self.bars[-1]['volume']=3000;self.bars[-1]['high']=self.u+3*self.a
        self.assertEqual(self.review()['state'],'price_breakout')

    def test_high_equals_low_is_not_full_confirmation(self):
        b=self.breakout();b.update(open=b['close'],low=b['close'],high=b['close'])
        self.assertEqual(self.review()['state'],'price_breakout')

    def test_price_then_later_volume_confirmation_has_distinct_dates(self):
        price=self.breakout(volume=1000);cycle=self.review()
        full=self.add(self.u+.8*self.a,volume=2000)
        result=self.review(cycle)
        self.assertEqual(result['attempts'][0]['price_at'],price['date'])
        self.assertEqual(result['attempts'][0]['volume_at'],full['date'])

    def test_breakout_day_cannot_also_confirm_retest(self):
        self.breakout();cycle=self.review()
        self.assertIsNone(cycle['attempts'][0]['retest'])

    def test_retest_requires_later_day_and_allows_confirmation_day_volume(self):
        self.breakout();cycle=self.review()
        touch=self.add(self.u+.1*self.a,low=self.u-.1*self.a,high=self.u+.2*self.a,volume=600)
        cycle=self.review(cycle)
        self.assertEqual(cycle['attempts'][0]['retest']['status'],'waiting')
        confirm=self.add(self.u+.5*self.a,low=self.u-.05*self.a,volume=5000)
        result=self.review(cycle)
        self.assertEqual(result['state'],'retest_confirmed')
        e=result['events'][-1]
        self.assertEqual(e['test_dates'],[touch['date']])
        self.assertEqual(e['day'],confirm['date'])
        self.assertTrue(result['attempts'][0]['sos_features'])
        self.assertTrue(result['attempts'][0]['retest']['lps_features'])

    def test_high_volume_narrow_spread_is_not_sos(self):
        self.add(self.u+.6*self.a,low=self.u+.59*self.a,high=self.u+.601*self.a,volume=5000)
        cycle=self.review()
        self.assertEqual(cycle['state'],'volume_breakout')
        self.assertFalse(cycle['attempts'][0]['sos_features'])
        self.assertFalse(self.live(cycle)['wyckoff_evidence']['sos'])

    def test_low_volume_wide_retest_is_not_lps(self):
        self.breakout();cycle=self.review()
        self.add(self.u+.1*self.a,low=self.u-.1*self.a,high=self.u+.6*self.a,volume=600)
        cycle=self.review(cycle)
        self.add(self.u+1.1*self.a,low=self.u+.2*self.a,volume=5000)
        result=self.review(cycle)
        self.assertEqual(result['state'],'retest_confirmed')
        self.assertFalse(result['attempts'][0]['retest']['lps_features'])

    def test_missing_retest_volume_cannot_confirm(self):
        self.breakout();cycle=self.review()
        self.add(self.u+.1*self.a,low=self.u-.1*self.a,high=self.u+.2*self.a,volume=None)
        cycle=self.review(cycle)
        self.add(self.u+.5*self.a,low=self.u-.05*self.a)
        result=self.review(cycle)
        self.assertNotEqual(result['state'],'retest_confirmed')
        self.assertEqual(result['attempts'][0]['retest']['volume_status'],'待核验')

    def test_new_low_damages_retest_even_if_same_bar_closes_high(self):
        self.breakout();cycle=self.review()
        self.add(self.u+.1*self.a,low=self.u-.1*self.a,high=self.u+.2*self.a,volume=600)
        cycle=self.review(cycle)
        self.add(self.u+.5*self.a,low=self.u-.25*self.a)
        result=self.review(cycle)
        self.assertEqual(result['attempts'][0]['retest']['status'],'damaged')
        self.assertNotEqual(result['state'],'retest_confirmed')

    def test_no_retest_does_not_fail_direct_continuation(self):
        self.breakout();cycle=self.review()
        for _ in range(6):
            self.add(self.u+1.1*self.a,low=self.u+.6*self.a)
            cycle=self.review(cycle)
        self.assertEqual(cycle['state'],'volume_breakout')
        self.assertTrue(any(e['kind']=='no_retest' for e in cycle['events']))

    def test_failure_kept_when_a_second_breakout_occurs(self):
        self.breakout();cycle=self.review()
        failure=self.add(self.u-.35*self.a,low=self.u-.6*self.a)
        cycle=self.review(cycle)
        self.assertEqual(cycle['state'],'consolidating')
        self.breakout();result=self.review(cycle)
        self.assertEqual(len(result['attempts']),2)
        self.assertEqual(result['attempts'][0]['failed_at'],failure['date'])
        self.assertTrue(any(e['kind']=='breakout_failed' for e in result['events']))

    def test_two_closes_below_upper_fail_but_one_small_retest_does_not(self):
        self.breakout();cycle=self.review()
        self.add(self.u-.1*self.a);cycle=self.review(cycle)
        self.assertEqual(cycle['state'],'volume_breakout')
        self.add(self.u-.1*self.a);cycle=self.review(cycle)
        self.assertEqual(cycle['state'],'consolidating')

    def test_structure_close_is_terminal_and_cannot_be_revived(self):
        self.breakout();cycle=self.review()
        self.add(self.cycle['platform_low']-self.a)
        cycle=self.review(cycle)
        self.assertEqual(cycle['state'],'closed')
        self.breakout();result=self.review(cycle)
        self.assertEqual(result,cycle)

    def test_gap_and_unknown_source_are_pending_without_new_events(self):
        self.breakout()
        for kind in ('gap','source','ohlc'):
            bars=copy.deepcopy(self.bars)
            if kind=='gap': bars.pop(-2)
            elif kind=='source': bars[-1]['price_basis_source']=None
            else: bars[-1]['high']=1
            result=w.review_daily(self.cycle,bars,bars[-1]['date'],self.calendar,self.day+' 15:00:00')
            self.assertTrue(result['pending_reason'])
            self.assertEqual(result['events'],[])

    def test_uniform_scale_change_preserves_origin_and_events(self):
        self.breakout();expected=self.review();scaled=copy.deepcopy(self.bars)
        for b in scaled:
            for k in ('open','high','low','close'): b[k]*=2
        result=w.review_daily(self.cycle,scaled,scaled[-1]['date'],self.calendar,self.day+' 15:00:00')
        self.assertEqual(result['state'],expected['state'])
        self.assertEqual(result['origin'],self.cycle['origin'])
        self.assertEqual(result['atr0'],self.a)
        self.assertEqual(result['price_scale_factor'],2)

    def test_nonuniform_history_revision_cannot_rewrite_old_structure(self):
        self.breakout();self.bars[-5]['close']+=.01
        result=self.review()
        self.assertIn('非同比例',result['pending_reason'])
        self.assertEqual(result['events'],[])

    def test_two_quotes_count_once_and_duplicate_latest_can_cancel(self):
        point=dict(at=self.day+' 10:05:00',price=self.u+self.a,valid=True)
        self.assertEqual(self.live(points=[point,point])['live_samples'],2)
        same=dict(point,at=self.day+' 10:10:00')
        self.assertEqual(self.live(points=[same])['live_samples'],1)
        self.assertEqual(self.live(points=[same],price=self.u-.01)['live_samples'],0)

    def test_invalid_quote_gap_and_future_point_do_not_confirm(self):
        for point in (dict(at=self.day+' 09:40:00',price=self.u+self.a,valid=True),
                      dict(at=self.day+' 10:05:00',price=self.u+self.a,valid=False),
                      dict(at=self.day+' 10:15:00',price=self.u+self.a,valid=True)):
            self.assertEqual(self.live(points=[point])['live_samples'],1)

    def test_stale_and_lunch_are_reference_only(self):
        self.assertFalse(self.live(fresh=False)['live_valid'])
        self.assertFalse(self.live(session='午间休市')['live_valid'])
        self.assertFalse(self.live(session='集合竞价')['live_valid'])

    def test_same_day_unfinished_daily_is_not_processed_in_normal_session(self):
        self.breakout()
        snap=dict(generated_at=self.bars[-1]['date']+' 10:00:00',session='早盘',
                  strength_model={'asof':self.bars[-1]['date']},stocks=[{'code':'600001','price':130}])
        state={'version':w.VERSION,'cycles':{'600001':self.cycle}}
        model=w.attach(snap,{'600001':self.bars},self.calendar,state=state)
        self.assertEqual(model['rows'][0]['events'],[])
        self.assertTrue(model['rows'][0]['pending_reason'])

    def test_attach_changes_only_its_own_fields(self):
        row={'code':'600001','name':'样本','stock_strength_score':77,'trend_online':True,
             'attack_watch_candidate':True,'trend_consolidation':self.cycle.copy()}
        row['trend_consolidation']=tc.daily_setup(self.bars,self.asof,self.calendar)
        snap={'stocks':[row],'generated_at':self.day+' 10:00:00','session':'早盘',
              'strength_model':{'asof':self.asof},'attack_monitor':{'version':'既有','rows':[{'code':'600001'}]}}
        before=copy.deepcopy(snap)
        w.attach(snap,{'600001':self.bars},self.calendar,contexts={'600001':{'valid':True,'scale_factor':1}})
        snap.pop('wyckoff_structure')
        for s in snap['stocks']:s.pop('wyckoff_structure',None)
        self.assertEqual(snap,before)

    def test_wrong_version_state_and_backup_are_not_consumed(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)/'state.json';state.write_text(json.dumps({'version':'旧版','cycles':{'600001':self.cycle}}),encoding='utf-8')
            with patch.object(w,'STATE_FILE',state):self.assertEqual(w.load_state()['cycles'],{})

    def test_serialization_and_repeated_review_are_idempotent(self):
        self.breakout();cycle=self.review()
        restored=json.loads(json.dumps(cycle))
        result=self.review(restored)
        self.assertEqual(result['events'],cycle['events'])
        self.assertEqual(result['attempts'],cycle['attempts'])

    def test_first_identification_has_no_backfilled_events(self):
        self.assertEqual(self.cycle['events'],[])
        self.assertEqual(self.cycle['last_processed_asof'],self.asof)

    def test_formal_close_waits_for_same_source_database_bar(self):
        b=self.breakout()
        snap=dict(generated_at=b['date']+' 15:10:00',session='已收盘',
                  strength_model={'asof':b['date']},stocks=[{'code':'600001','price':b['close']}])
        state={'version':w.VERSION,'cycles':{'600001':self.cycle}}
        model=w.attach(snap,{'600001':self.bars},self.calendar,state=state,
                       daily_history_loader=lambda code:self.bars[:-1])
        self.assertEqual(model['rows'][0]['events'],[])
        self.assertTrue(model['rows'][0]['pending_reason'])
        model=w.attach(snap,{'600001':self.bars},self.calendar,state=state,
                       daily_history_loader=lambda code:self.bars)
        self.assertEqual(model['rows'][0]['state'],'volume_breakout')

    def test_pre_1505_close_quote_cannot_confirm_daily_structure(self):
        b=self.breakout()
        snap=dict(generated_at=b['date']+' 15:01:00',session='已收盘',
                  strength_model={'asof':b['date']},stocks=[{'code':'600001','price':b['close']}])
        model=w.attach(snap,{'600001':self.bars},self.calendar,state={'version':w.VERSION,'cycles':{'600001':self.cycle}})
        self.assertEqual(model['rows'][0]['events'],[])

    def test_corrupt_state_is_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json';path.write_text('{broken',encoding='utf-8')
            with patch.object(w,'STATE_FILE',path):
                with self.assertRaises(RuntimeError):w.load_state()
            self.assertEqual(path.read_text(encoding='utf-8'),'{broken')

    def test_retest_confirmation_window_expires(self):
        self.breakout();cycle=self.review()
        self.add(self.u+.05*self.a,low=self.u-.1*self.a,high=self.u+.2*self.a,volume=600)
        cycle=self.review(cycle)
        for _ in range(4):
            self.add(self.u+.05*self.a,low=self.u-.05*self.a,high=self.u+.2*self.a,volume=600)
            cycle=self.review(cycle)
        self.assertEqual(cycle['attempts'][0]['retest']['status'],'expired')
        self.assertEqual(cycle['state'],'volume_breakout')

    def test_unsafe_risk_never_erases_historical_confirmation(self):
        self.breakout();cycle=self.review()
        row=dict(price=self.u+self.a,intraday_quote_fresh=True,intraday_trend_ok=True,
                 intraday_serious_weakness=False,intraday_risk_flags=['触板未封'],
                 intraday_quote_at=self.day+' 10:10:00',overheated=True)
        result=w.display_cycle(cycle,row,{'valid':True,'scale_factor':1},[],'早盘',self.day+' 10:10:00')
        self.assertEqual(result['state'],'volume_breakout')
        self.assertFalse(result['current_structure_clear'])
        self.assertIn('位置偏热',result['restrictions'])

    def test_closed_or_pending_cycle_does_not_project_unverified_live_scale(self):
        row=dict(price=self.u+self.a,intraday_quote_fresh=True,intraday_trend_ok=True,
                 intraday_serious_weakness=False,intraday_quote_at=self.day+' 10:10:00')
        for change in ({'state':'closed'}, {'pending_reason':'原历史价格改写'}, {}):
            cycle=copy.deepcopy(self.cycle);cycle.update(change)
            context={'valid':bool(change),'scale_factor':2}
            result=w.display_cycle(cycle,row,context,[],'早盘',self.day+' 10:10:00')
            self.assertIsNone(result['live_platform_high'])
            self.assertIsNone(result['live_breakout_threshold'])
            self.assertFalse(result['live_valid'])
            self.assertEqual(result['platform_high'],self.u)


if __name__=='__main__':unittest.main()
