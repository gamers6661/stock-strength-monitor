"""MA10降级/MA20退出与靠线提示的完整业务路径。"""
import copy
import unittest
from unittest.mock import patch

import consolidation_proximity as proximity
import consolidation_tracking as tracking
import trend_consolidation as tc
import test_trend_consolidation as fixtures
from test_trend_consolidation import ConsolidationFixture


class MA20ModelTests(ConsolidationFixture):
    confirmed_previous=fixtures.CompletedTrackingTests.confirmed_previous
    review=fixtures.CompletedTrackingTests.review
    close=fixtures.CompletedTrackingTests.close
    def test_formal_ma10_loss_keeps_ma20_tracking(self):
        _, model = self.close(self.confirmed_previous(),price=118)
        item = model['completed_rows'][0]
        self.assertEqual(model['withdrawn_rows'],[])
        self.assertEqual(item['tracking_state'],'ma10_close_downgraded')
        self.assertTrue(item['ma10_downgraded'])
        self.assertLess(item['close_review_price'],item['close_review_ma10'])
        self.assertGreater(item['close_review_price'],item['close_review_ma20'])
        self.assertFalse(item['current_breakout_confirmed'])

    def test_repeated_ma10_breaks_never_exit(self):
        prior=self.confirmed_previous()
        for time in ('10:15:00','10:20:00','10:25:00'):
            prior, model=self.review(prior,price=118,time=time)
            self.assertFalse(model['completed_rows'][0]['trend_exited'])
            self.assertFalse(model['completed_rows'][0]['current_breakout_confirmed'])
        self.assertEqual(model['completed_rows'][0]['tracking_state'],'ma10_downgraded')

    def test_old_ma10_exit_migrates_without_fake_ma20_exit_or_attack(self):
        prior=self.confirmed_previous()
        item=prior['trend_consolidation']['completed_rows'].pop()
        item.update(trend_exited=True,tracking_state='ma10_close_lost',trend_exit_at=self.day+' 10:12:00')
        item.pop('exit_line',None)
        prior['trend_consolidation']['withdrawn_rows']=[item]
        prior['trend_consolidation']['version']='强股整理观察6'
        _, model=self.review(prior,price=118)
        item=model['completed_rows'][0]
        self.assertFalse(item['trend_exited'])
        self.assertIsNone(item['trend_exit_at'])
        self.assertEqual(item['legacy_ma10_exit_at'],self.day+' 10:12:00')
        self.assertFalse(item['current_breakout_confirmed'])

    def test_unknown_own_ma20_does_not_count_as_break(self):
        prior=self.confirmed_previous()
        pt=self.point('10:15:00',price=105);pt.pop('ma20')
        _,model=self.review(prior,time='10:20:00',points=[pt])
        self.assertEqual(model['completed_rows'][0]['ma20_below_samples'],1)
        self.assertFalse(model['completed_rows'][0]['trend_exited'])

    def test_current_ma20_unknown_goes_pending(self):
        def missing(row,context):context['thresholds'].pop(20)
        _,model=self.review(self.confirmed_previous(),change=missing)
        self.assertEqual(model['completed_rows'],[])
        self.assertEqual(model['pending_rows'][0]['reason'],'MA20边界待核验')


class ObservationMA20Tests(ConsolidationFixture):
    def original(self):
        snap,row,q,context=self.live(price=124.5)
        self.attach(snap,q,context)
        return snap

    def cycle(self,prior,price,time):
        snap,row,q,context=self.live(price=price,time=time)
        return snap,self.attach(snap,q,context,previous=prior),context

    def test_consolidating_stock_loses_ma10_but_stays_until_ma20_confirmed(self):
        prior=self.original()
        for time in ('10:15:00','10:20:00'):
            prior,model,context=self.cycle(prior,118,time)
            self.assertEqual(len(model['rows']),1)
            item=model['rows'][0]
            self.assertTrue(item['downgraded_observation'])
            self.assertFalse(item.get('completion_confirmed'))
            self.assertFalse(item['current_breakout_confirmed'])
        prior,model,context=self.cycle(prior,105,'10:25:00')
        self.assertEqual(model['rows'][0]['tracking_state'],'ma20_test')
        prior,model,context=self.cycle(prior,105,'10:30:00')
        self.assertEqual(model['rows'],[])
        self.assertTrue(model['withdrawn_rows'][0]['trend_exited'])

    def test_previous_qualified_observation_survives_next_daily_ma10_loss(self):
        prior=self.original()
        bars=copy.deepcopy(self.bars)
        bars.append(dict(bars[-1],date=self.day,open=118,close=118,low=117.7,high=118.3))
        calendar=self.calendar+[self.day]
        snap=copy.deepcopy(prior);snap.update(session='已收盘',strength_model={'asof':self.day})
        model=tc.attach(snap,{'600001':bars},{},{},calendar,previous=prior)
        self.assertEqual(model['rows'][0]['tracking_state'],'ma10_close_downgraded')
        self.assertFalse(model['rows'][0].get('completion_confirmed'))
        self.bars=bars;self.calendar=calendar;self.asof=self.day
        from datetime import datetime,timedelta
        self.day=(datetime.fromisoformat(self.day)+timedelta(days=1)).date().isoformat()
        snap,row,q,context=self.live(price=118)
        next_model=self.attach(snap,q,context,previous={'trend_consolidation':model})
        self.assertEqual(len(next_model['rows']),1)
        self.assertTrue(next_model['rows'][0]['observation_history_qualified'])
        self.assertFalse(next_model['rows'][0]['live_trend_online'])
        self.assertEqual(next_model['rows'][0]['platform_low'],self.setup['platform_low'])

    def test_ma20_rebound_can_be_tagged_below_ma10_without_turn_confirmation(self):
        prior=self.original()
        snap,row,q,context=self.live(price=110.6,time='10:25:00')
        points=[]
        for time,price in [('10:10:00',110),('10:15:00',108.3),('10:20:00',109),('10:25:00',110.6)]:
            points.append(dict(at=self.day+' '+time,price=price,valid=True,atr20=1,
                               ma20=108.1,ma10=119.5,ma5_boundary=123.9,trend_ok=False,flags=[]))
        model=self.attach(snap,q,context,{'points':{'600001':points}},previous=prior)
        item=model['rows'][0]
        self.assertTrue(item['rebound_active'])
        self.assertEqual(item['rebound_line'],20)
        self.assertIn('回踩反弹·MA20',item['stage'])
        self.assertFalse(item.get('completion_confirmed'))
        self.assertFalse(item['current_breakout_confirmed'])

    def test_ma10_recovery_checkpoint_is_kept_on_normal_main_path(self):
        prior,_,_=self.cycle(self.original(),118,'10:15:00')
        prior,_,_=self.cycle(prior,118,'10:20:00')
        prior,model,_=self.cycle(prior,124.5,'10:25:00')
        self.assertTrue(model['rows'][0]['ma10_downgraded'])
        prior,model,_=self.cycle(prior,124.5,'10:30:00')
        self.assertFalse(model['rows'][0]['ma10_downgraded'])
        prior,model,_=self.cycle(prior,124.5,'10:35:00')
        self.assertFalse(model['rows'][0]['ma10_downgraded'])
        self.assertFalse(model['rows'][0]['downgraded_observation'])

    def test_next_auction_keeps_same_version_history_without_new_strength(self):
        prior=self.original()
        original=copy.deepcopy(prior['trend_consolidation']['rows'][0])
        from datetime import datetime,timedelta
        next_day=(datetime.fromisoformat(self.day)+timedelta(days=1)).date().isoformat()
        snap=copy.deepcopy(prior)
        snap.update(session='集合竞价',quote_capture_at=next_day+' 09:20:00',generated_at=next_day+' 09:20:00')
        with patch.object(tc,'DIRECTORY',__import__('pathlib').Path('research/nonexistent_test_archive')):
            model=tc.attach(snap,{},{},{},[],previous=prior)
        self.assertEqual(model['day'],next_day)
        self.assertEqual(model['reference_day'],self.day)
        self.assertEqual(model['count'],1)
        self.assertEqual(model['current_count'],0)
        self.assertTrue(model['rows'][0]['reference_only'])
        self.assertEqual(model['rows'][0]['quote_at'],original['quote_at'])
        self.assertEqual(model['rows'][0]['consolidation_elapsed_days'],original['consolidation_elapsed_days'])
        self.assertEqual(snap['stocks'][0]['trend_consolidation'],model['rows'][0])


class ProximityTests(unittest.TestCase):
    def context(self,factor=1):return dict(valid=True,atr20=2*factor,scale_factor=factor,thresholds={5:101*factor,10:100*factor,20:99*factor})
    def alert(self,price,context=None,exited=False):
        return proximity.observe({'platform_low':100},context or self.context(),price,'2026-10-08 11:30:00',exited)

    def test_exact_near_boundary_bottom_and_lines(self):
        alerts=self.alert(100.8)['support_alerts']
        self.assertEqual({a['label'] for a in alerts},{'接近平台底部','接近MA10'})
        self.assertEqual(self.alert(100.80001)['support_alerts'],[])
        self.assertIn('触及MA10',{a['label'] for a in self.alert(100)['support_alerts']})
        self.assertEqual({a['label'] for a in self.alert(99.5)['support_alerts']},{'接近MA20'})

    def test_price_conversion_and_invalid_basis(self):
        alerts=self.alert(100.8*1.1,self.context(1.1))['support_alerts']
        self.assertEqual(alerts[0]['price'],110)
        self.assertAlmostEqual(alerts[0]['distance_atr'],.4)
        self.assertEqual(self.alert(100,dict(self.context(),valid=False))['support_alerts'],[])
        self.assertEqual(self.alert(100,exited=True)['support_alerts'],[])


if __name__=='__main__':unittest.main()
