"""Event dates, subsequent-close confirmation, and stage handoffs share one lifecycle."""
import copy,csv,io,json,subprocess,unittest
from datetime import timedelta
import ma_trend as T
from test_ma_trend import sample,run
from test_minute_recovery import candidate_fixture
from test_market_strength_integration import render

def append_closes(f,prices,volume=40.):
    bars=next(iter(f[3].values()));dates=list(f[4]);day=f[5].date()
    for j,price in enumerate(prices):
        date=(day+timedelta(days=j)).isoformat();opening=bars[-1]['close']
        bars.append(dict(bars[-1],date=date,open=opening,close=price,high=max(price,opening)+.1,
            low=min(price,opening)-.1,volume=volume));dates.append(date)
    return bars,dates

class LifecycleConfirmation(unittest.TestCase):
    def test_recovery_needs_a_later_completed_up_close_and_keeps_event_date(self):
        f=candidate_fixture();bars=next(iter(f[3].values()));event=bars[-1]['date']
        self.assertIsNone(T.daily(bars,f[4],10)['stage'])
        bars,dates=append_closes(f,[111.5]);setup=T.daily(bars,dates,10)
        self.assertEqual(setup['stage'],5);self.assertEqual(setup['origin']['date'],event)
        self.assertEqual(setup['origin']['confirmation']['date'],bars[-1]['date'])
        self.assertEqual(setup['entry_date'],bars[-1]['date'])
        self.assertFalse(setup['recovery_candidate']['active'])
        self.assertLess(setup['origin']['volume_ratio'],T.P['volume_ratio'])

    def test_flat_down_or_below_event_close_does_not_confirm(self):
        for prices in ([108.9],[108.8],[108.,108.5]):
            f=candidate_fixture();bars,dates=append_closes(f,prices)
            self.assertIsNone(T.daily(bars,dates,10)['stage'],prices)

    def test_failed_expired_or_unknown_limit_cannot_use_followthrough(self):
        for prices,limit in (([97.,109.5],10),([108.8]*5+[109.5],10),([109.5],None)):
            f=candidate_fixture();bars,dates=append_closes(f,prices)
            setup=T.daily(bars,dates,limit)
            self.assertNotEqual((setup.get('origin') or {}).get('kind'),'涨停收复后推进确认')

    def test_later_independent_strong_day_updates_confirmation_not_origin(self):
        f=candidate_fixture();event=next(iter(f[3].values()))[-1]['date']
        bars,dates=append_closes(f,[111.5,122.65]);bars[-1].update(volume=400.,high=122.65)
        setup=T.daily(bars,dates,10)
        self.assertEqual(setup['origin']['date'],event)
        self.assertEqual(setup['origin']['confirmation']['date'],bars[-2]['date'])
        self.assertEqual(setup['last_confirmation']['date'],bars[-1]['date'])

    def test_intraday_quotes_and_future_bars_do_not_substitute_for_a_follow_day(self):
        f=candidate_fixture();first=copy.deepcopy(run(f));q=next(iter(f[1].values()))
        q.update(price=109.5,high=109.6,low=108.9,change_pct=100*(109.5/108.9-1))
        self.assertTrue(run(f)['candidate_mode'])
        bars=next(iter(f[3].values()));bars.append(dict(bars[-1],date='2099-01-01',close=150.,high=151.))
        self.assertTrue(run(f)['candidate_mode']);self.assertFalse(first['eligible'])

    def test_ma10_loss_hands_strong_wave_to_ma20_tracking_before_touch(self):
        f=sample('ma20');bars=next(iter(f[3].values()));found=None
        for end in range(22,len(bars)+1):
            setup=T.daily(bars[:end],f[4])
            if setup['stage']==20 and not setup['ma20_entry'].get('touch_confirmed'):
                found=setup;break
        self.assertIsNotNone(found)
        self.assertGreaterEqual(found['ma20_entry']['rise_pct'],20.)
        self.assertGreaterEqual(found['ma20_entry']['rise_atr'],4.)
        self.assertFalse(found['ma20_entry']['ready'])
        self.assertTrue(any(t['from_stage']==10 and t['to_stage']==20 for t in found['transitions']))

    def test_ma20_reclaim_and_follow_are_distinct_dates_without_new_volume_gate(self):
        f=sample('ma20');bars,dates=append_closes(f,[123.,124.])
        observation=T.daily(bars[:-1],dates);confirmed=T.daily(bars,dates)
        self.assertEqual(observation['stage'],20)
        self.assertEqual(confirmed['stage'],20);self.assertTrue(confirmed['progressing'])
        self.assertEqual(confirmed['origin'],observation['origin'])
        self.assertEqual(confirmed['leg_origin']['date'],bars[-2]['date'])
        self.assertEqual(confirmed['leg_origin']['confirmation']['date'],bars[-1]['date'])
        self.assertLess(confirmed['leg_origin']['volume_ratio'],T.P['volume_ratio'])
        self.assertEqual(confirmed['last_phase']['stage'],20)
        self.assertEqual(confirmed['transitions'][-1]['to_stage'],20)

    def test_failed_ma20_cannot_resurrect_from_old_large_gain(self):
        f=sample('ma20');bars,dates=append_closes(f,[110.,111.,112.,113.])
        setup=T.daily(bars,dates)
        self.assertNotEqual(setup['stage'],20)
        self.assertFalse(setup['ma20_primary_candidate'])
        self.assertIsNone(setup['ma20_restart_observation'])

    def test_reclaim_observation_can_precede_ma5_turning_up_but_confirmation_cannot(self):
        f=sample('ma20');bars,dates=append_closes(f,[120.56,123.])
        event=len(bars)-2
        self.assertLess(T.average(bars,event,5),T.average(bars,event-1,5))
        early=T.daily(bars[:-1],dates);later=T.daily(bars,dates)
        self.assertEqual(early['stage'],20)
        self.assertEqual(early['ma20_restart_observation']['date'],bars[event]['date'])
        self.assertEqual(later['stage'],20);self.assertTrue(later['progressing'])
        self.assertEqual(later['origin'],early['origin'])
        self.assertEqual(later['leg_origin']['date'],bars[event]['date'])
        self.assertEqual(later['leg_origin']['confirmation']['date'],bars[-1]['date'])

    def test_lagging_lines_anchor_only_after_independent_entry_without_backdating_eligibility(self):
        f=sample();bars=next(iter(f[3].values()))
        values=[112.,113.,106.,106.,108.,114.,116.,111.,104.,111.,104.,105.,99.,95.,104.5,110.,121.]
        start=len(bars)-len(values)
        for j,price in enumerate(values):
            b=bars[start+j];opening=bars[start+j-1]['close']
            b.update(open=opening,close=price,high=max(opening,price)+.2,low=min(opening,price)-.2,
                volume=250. if j==0 else 400. if j==16 else 40.)
        bars[-3]['high']=bars[-3]['close'];bars[-1]['high']=bars[-1]['close']
        before=T.daily(bars[:-2],f[4],10);after=T.daily(bars,f[4],10)
        self.assertIsNone(before['stage']);self.assertIsNone(before['recovery_candidate'])
        self.assertEqual(after['stage'],5)
        self.assertEqual(after['origin']['date'],bars[-3]['date'])
        self.assertEqual(after['origin']['kind'],'涨停起涨后强势确认')
        self.assertEqual(after['origin']['confirmation']['date'],bars[-1]['date'])
        self.assertEqual(after['origin']['confirmation']['independent_signal']['date'],bars[-1]['date'])
        self.assertEqual(after['last_confirmation']['date'],bars[-1]['date'])
        self.assertLess(T.average(bars,len(bars)-3,5),T.average(bars,len(bars)-4,5))
        self.assertLess(bars[-3]['close'],T.average(bars,len(bars)-3,10))

    def test_price_scaling_includes_confirmation_and_archived_proofs_only_once(self):
        f=sample('ma20');bars,dates=append_closes(f,[123.,124.]);setup=T.daily(bars,dates)
        scaled=T.scale_setup(setup,2.);o=setup['leg_origin'];v=scaled['leg_origin']
        self.assertEqual(v['price'],o['price']*2)
        for key in ('event_close','close','ma5','ma10'):
            self.assertEqual(v['confirmation'][key],o['confirmation'][key]*2)
        self.assertEqual(v['confirmation']['prior_rise_pct'],o['confirmation']['prior_rise_pct'])
        self.assertEqual(scaled['last_phase']['origin']['price'],setup['last_phase']['origin']['price']*2)
        self.assertEqual(scaled['last_phase']['support'],setup['last_phase']['support']*2)
        self.assertEqual(setup['leg_origin']['price'],123.)

    def test_current_dates_and_csv_match_backend_and_hide_recovery_badge_after_confirmation(self):
        f=candidate_fixture();run(f);m=f[0]['stocks'][0]['ma_trend']
        bars,dates=append_closes(f,[111.5]);setup=T.daily(bars,dates,10)
        m.update(stage=5,stage_label=T.LABELS[5],origin=setup['origin'],entry_date=setup['entry_date'],status='守线观察',
            recovery_candidate=setup['recovery_candidate'],candidate_mode=False,recovery_current=False,last_confirmation=setup['last_confirmation'])
        out=render(f[0],"document.getElementById('proof').innerHTML=mtOrigin(DATA.stocks[0].ma_trend)+mtDetail(DATA.stocks[0].ma_trend);")['els']['proof']['innerHTML']
        self.assertIn('本轮起涨 '+setup['origin']['date'],out)
        self.assertIn('阶段确认 '+setup['entry_date'],out)
        self.assertNotIn('ms-recovery-tag',out);self.assertNotIn('放量上攻门槛',out)
        for view in ('radar','ranking'):
            request=json.dumps(dict(rows=f[0]['stocks'],data=f[0],contexts=dict(view=view)),ensure_ascii=False)
            output=subprocess.run(['node','csv_export.js'],input=request,capture_output=True,text=True,encoding='utf8',check=True)
            row=next(csv.DictReader(io.StringIO(output.stdout.lstrip('\ufeff'))))
            self.assertEqual(row['阶段确认日'],setup['entry_date'])
            self.assertEqual(row['起点日期' if view=='radar' else '本轮启动日'],setup['origin']['date'])
            self.assertEqual(row['最近强势确认日'],setup['entry_date'])

if __name__=='__main__':unittest.main()
