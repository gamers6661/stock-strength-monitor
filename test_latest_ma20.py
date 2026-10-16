import copy,unittest
from datetime import timedelta
import ma_trend as T
from test_ma_trend import sample,run
from test_market_strength_integration import render


class LatestMA20(unittest.TestCase):
    def test_fresh_strong_wave_does_not_keep_an_earlier_wave_base(self):
        f=sample('ma20');bars=f[3][next(iter(f[3]))]
        bars[25].update(open=100.,close=105.,high=105.2,low=99.8,volume=250.)
        setup=T.daily(bars,f[4])
        self.assertEqual(setup['stage'],20)
        self.assertEqual(setup['platform']['origin']['date'],bars[-22]['date'])

    def test_recent_new_peak_cannot_borrow_an_older_flat_window(self):
        f=sample('ma20');bars=f[3][next(iter(f[3]))];root=T.daily(bars,f[4])['origin']
        bars[-2].update(close=123.,high=123.2)
        self.assertIsNone(T.latest_platform(bars,len(bars)-1,root))

    def test_unconfirmed_reclaim_keeps_same_ma20_cycle_without_creating_a_new_one(self):
        f=sample('ma20');bars=f[3][next(iter(f[3]))];before=T.daily(bars,f[4]);self.assertEqual(before['stage'],20)
        dates=list(f[4]);day=f[5].date()
        for j in range(8):
            d=(day+timedelta(days=j)).isoformat();dates.append(d)
            bars.append(dict(bars[-1],date=d,open=122.4,close=122.5,low=122.3,high=122.7,volume=40.))
        after=T.daily(bars,dates)
        # Flat closes after reclaim have no later rising close to confirm MA5.
        # Keep the old structural stage pending, without lending its large gain.
        self.assertEqual(after['stage'],20)
        self.assertIsNotNone(after['ma20_restart_observation'])
        self.assertFalse(after['ma20_candidate'])
        self.assertEqual(after['origin'],T.daily(next(iter(f[3].values()))[:-8],dates)['origin']);self.assertFalse(after['progressing'])

    def test_same_cycle_ma10_progression_accumulates_gain_before_ma20_handoff(self):
        f=sample('ma10');bars=f[3][next(iter(f[3]))];self.assertEqual(T.daily(bars,f[4])['stage'],10)
        dates=list(f[4]);day=f[5].date()
        for j,price in enumerate([117.,121.,125.,126.]+[125.5]*16):
            d=(day+timedelta(days=j)).isoformat();dates.append(d)
            bars.append(dict(bars[-1],date=d,open=price-.1,close=price,low=price-.2,high=price+.05,volume=30.))
        setup=T.daily(bars,dates)
        self.assertEqual(setup['stage'],20)
        self.assertTrue(any(t['from_stage']==10 and t['to_stage']==20 for t in setup['transitions']))

    def test_completed_platform_can_form_after_ma10_hands_off_to_tracking(self):
        f=sample('ma20');bars=f[3][next(iter(f[3]))];start=len(bars)-26
        prices=[105.+5*j for j in range(10)]+[136.]*16
        for j,price in enumerate(prices):
            bars[start+j].update(open=price-.2,close=price,low=price-.4,high=price+.05,
                volume=250. if j==0 else 100. if j<10 else 35.)
        setup=T.daily(bars,f[4]);self.assertEqual(setup['stage'],20)
        self.assertTrue(any(t['from_stage']==10 and t['to_stage']==20 for t in setup['transitions']))
        self.assertFalse(any(e['stage']==10 for e in setup['exits']))
        self.assertTrue(setup['platform']['latest_cycle'])

    def test_platform_bottom_must_retain_twenty_percent_not_just_peak(self):
        f=sample('ma20');bars=f[3][next(iter(f[3]))];root=T.daily(bars,f[4])['origin']
        for b in bars[-15:]:b.update(open=110.1,close=110.,low=109.8,high=110.2)
        self.assertIsNone(T.latest_platform(bars,len(bars)-1,root,require_position=False))

    def test_failed_floor_is_not_lowered_to_create_a_new_platform(self):
        f=sample('ma20');bars=f[3][next(iter(f[3]))];before=T.daily(bars,f[4]);floor=before['platform']['low']
        dates=list(f[4]);day=f[5].date()
        for j in range(6):
            d=(day+timedelta(days=j)).isoformat();dates.append(d)
            bars.append(dict(bars[-1],date=d,open=floor-.05,close=floor-.1,low=floor-.2,high=floor))
        setup=T.daily(bars,dates);self.assertNotEqual(setup['stage'],20)
        self.assertEqual(setup['last_exit']['support'],floor)
        self.assertIn('平台底部',setup['last_exit']['reason'])

    def test_auction_reference_does_not_replay_yesterdays_minute_request(self):
        f=sample('ma20');run(f);previous=copy.deepcopy(f[0]);c=next(iter(f[1]))
        previous['stocks'][0]['ma_trend']['minute_needed']=True
        f[0]['session']='集合竞价'
        T.attach(f[0],{},f[2],f[3],f[4],now=f[5],previous=previous,fetch_minutes=False)
        self.assertTrue(f[0]['stocks'][0]['ma_trend']['reference_only'])
        self.assertEqual(f[0]['ma_trend']['minute_needed'],0)

    def test_default_radar_contains_all_members_with_all_stages(self):
        f=sample();run(f);out=render(f[0],"renderRadar();")
        html=out['els']['ma-radar-host']['innerHTML']
        self.assertIn('value="all" selected',html);self.assertIn('全部阶段',html)

    def test_old_ma20_exit_is_not_a_current_ma20_member(self):
        f=sample('ma20');run(f);m=f[0]['stocks'][0]['ma_trend']
        m.update(status='已退出',eligible=False,exit_at='2026-09-01 15:00:00')
        f[0]['ma_trend']['current']=[]
        f[0]['ma_trend']['exited']=[m['code']]
        out=render(f[0],"MS_VIEW.radar.phase='20';mtRender();")
        self.assertNotIn('data-strength-id=',out['els']['ma-radar-host']['innerHTML'])
        out=render(f[0],"MS_VIEW.radar.scope='exited';MS_VIEW.radar.phase='20';mtRender();")
        self.assertNotIn('data-strength-id=',out['els']['ma-radar-host']['innerHTML'])
        self.assertNotIn('历史退出 · MA20',out['els']['ma-radar-host']['innerHTML'])

    def test_search_has_no_overlaid_icon_and_returns_are_colored(self):
        f=sample();run(f);out=render(f[0],"mtRender();")
        html=out['els']['ma-radar-host']['innerHTML']
        self.assertNotIn('⌕',html);self.assertIn('pct-change up',html)

if __name__=='__main__':unittest.main()
