"""Turning observations: causal windows, live clocks, source coverage and unchanged admission."""
import copy
import unittest
from datetime import timedelta
import stock_selection as S
import stock_selection_turning as T
from test_stock_selection import sample,run

TEMP_PATHS=[]


def attach(f,model=None,previous=None,frames=None,historical=False):
    model=model or run(f)
    return T.attach(model,f[0],f[1],f[2],previous=previous,frames=frames,now=f[4],historical=historical)


def rewrite(f,code,prices,volume=1.4e6):
    bars=f[1][code]
    for b,p in zip(bars[-len(prices):],prices):b.update(open=p-.2,close=p,high=p+.2,low=p-.4,volume=volume)
    for b in bars:f[3][code][b['date']]=dict(b,amount=b['close']*b['volume'],source=S.amounts.SOURCE)
    p=bars[-1]['close'];q=next(r for r in f[0]['stocks'] if r['code']==code)
    q.update(price=p*1.005,last_close=p,open=p,high=p*1.005+.1,low=p-.5,amount_wan=p*100,volume_shou=10000.,change_pct=.5)


class Turning(unittest.TestCase):
    def test_recent_change_can_outrank_old_strength_without_changing_strength(self):
        f=sample();old,new=f[-1][:2]
        rewrite(f,new,[100,100,100,101,103,104])
        model=run(f);before={c:(x['score'],x['eligible'],x['list_name']) for c,x in model['items'].items()}
        result=attach(f,model);item=result['items'][new]
        self.assertTrue(item['turning']['active'],item['turning'])
        self.assertLess(result['turning_order'].index(new),result['turning_order'].index(old))
        self.assertEqual(before,{c:(x['score'],x['eligible'],x['list_name']) for c,x in result['items'].items()})

    def test_future_bars_cannot_change_ranking(self):
        f=sample();rewrite(f,f[-1][1],[100,100,100,101,103,104]);a=attach(f)
        for bs in f[1].values():bs.append(dict(bs[-1],date='2030-01-01',close=1e9,high=1e9))
        b=attach(f)
        self.assertEqual(a['turning_order'],b['turning_order'])
        self.assertEqual(a['items'][f[-1][1]]['turning']['metrics'],b['items'][f[-1][1]]['turning']['metrics'])

    def test_invalid_quote_and_missing_liquidity_never_create_observation(self):
        for failure in ('quote','amount'):
            f=sample();c=f[-1][1];rewrite(f,c,[100,100,100,101,103,104])
            if failure=='quote':f[0]['stocks'][1].update(quote_at='2020-01-01 10:00:00',ts='2020-01-01 10:00:00')
            else:f[3][c]={}
            x=attach(f)['items'][c]
            self.assertFalse(x['startup_observation']);self.assertFalse(x['turning']['active'])

    def test_first_seen_is_real_recorded_once_and_historical_replay_cannot_invent_it(self):
        f=sample();c=f[-1][1];rewrite(f,c,[100,100,100,101,103,104]);a=attach(f)
        b=attach(f,previous=a['_state']);self.assertEqual(a['items'][c]['turning']['first_seen_at'],b['items'][c]['turning']['first_seen_at'])
        self.assertEqual(b['items'][c]['turning']['since_first_pct'],0.)
        historical=attach(f,historical=True)
        self.assertIsNone(historical['items'][c]['turning']['first_seen_at'])
        self.assertNotIn('turning_event',historical['_state']['items'][c])

    def live_case(self):
        f=sample();c=f[-1][1];bs=f[1][c]
        # A local five-day platform still below the prior twenty-day high.
        b=bs[-18];b.update(open=110.,close=110.,high=110.3,low=109.6)
        f[3][c][b['date']]=dict(b,amount=110*b['volume'],source=S.amounts.SOURCE)
        q=f[0]['stocks'][1];q.update(price=103.,open=100.,last_close=100.,high=103.,low=99.,change_pct=3.)
        model=run(f);model['items'][c]['intraday']['volume_ratio_same_time']=2.
        return f,c,model

    def test_intraday_local_start_can_appear_before_twenty_day_breakout(self):
        f,c,model=self.live_case();self.assertFalse(model['items'][c]['eligible'])
        result=attach(f,model);x=result['items'][c]
        self.assertTrue(x['startup_observation'],x['turning']);self.assertFalse(x['eligible'])
        self.assertEqual(x['turning']['stage'],'盘中局部启动')

    def test_single_jump_without_same_clock_volume_or_hold_is_pending(self):
        f,c,model=self.live_case();model['items'][c]['intraday']['volume_ratio_same_time']=None
        x=attach(f,model)['items'][c]
        self.assertFalse(x['startup_observation']);self.assertFalse(x['turning']['metrics']['live_confirmed'])
        frames=[(str(f[4]-timedelta(seconds=s)),{c:dict(at=str(f[4]-timedelta(seconds=s)),price=103.)}) for s in (240,120)]
        x=attach(f,model,frames=frames)['items'][c]
        self.assertTrue(x['startup_observation']);self.assertTrue(x['turning']['metrics']['live_confirmed'])

    def test_sample_gap_does_not_count_as_continuous_hold(self):
        f,c,model=self.live_case();model['items'][c]['intraday']['volume_ratio_same_time']=None
        frames=[(str(f[4]-timedelta(seconds=s)),{c:dict(at=str(f[4]-timedelta(seconds=s)),price=103.)}) for s in (500,380)]
        self.assertFalse(attach(f,model,frames=frames)['items'][c]['startup_observation'])

    def test_market_clock_gap_disables_live_excess_but_keeps_completed_evidence(self):
        f,c,model=self.live_case()
        for other in f[-1][:4]:
            model['items'][other]['intraday']['at']=str(f[4]-timedelta(seconds=120))
        x=attach(f,model)['items'][c]
        self.assertEqual(x['turning']['metrics']['evidence_mode'],'完成日')
        self.assertFalse(x['startup_observation'])

    def test_peer_comparison_excludes_self_and_requires_coverage(self):
        f,c,model=self.live_case();x=attach(f,model)['items'][c]
        self.assertAlmostEqual(x['turning']['metrics']['board_excess_pct'],3.)
        self.assertEqual(x['turning']['metrics']['board_positive_share'],0.)
        f,c,model=self.live_case();model['items'][c]['board']['expected']=100
        self.assertIsNone(attach(f,model)['items'][c]['turning']['metrics']['board_excess_pct'])

    def test_missing_or_invalid_data_has_no_shortened_window(self):
        f=sample();c=f[-1][1];rewrite(f,c,[100,100,100,101,103,104]);f[1][c][-1]['volume']=None
        x=attach(f)['items'][c];self.assertFalse(x['turning']['available']);self.assertFalse(x['startup_observation'])

    def test_lazy_summary_keeps_order_and_minimal_row_evidence(self):
        import ui_payload
        f,c,model=self.live_case();full=attach(f,model);summary=ui_payload.selection_summary(full)
        self.assertEqual(summary['turning_order'],full['turning_order'])
        self.assertTrue(summary['items'][c]['startup_observation'])
        self.assertNotIn('order',summary['items'][c]['turning'])
        self.assertEqual(summary['items'][c]['turning']['metrics']['excess3'],full['items'][c]['turning']['metrics']['excess3'])

    def test_current_down_day_does_not_remain_an_active_turning_signal(self):
        f,c,model=self.live_case()
        # A previously qualified completed signal, but current recovery remains below yesterday.
        d=T.daily_inputs(f[1][c],model['daily_at']);self.assertIsNotNone(d)
        rewrite(f,c,[100,100,100,101,103,104])
        row=f[0]['stocks'][1];row.update(price=103.,last_close=104.,open=102.,high=104.,low=101.,change_pct=-.96)
        x=attach(f)['items'][c]
        self.assertFalse(x['turning']['active']);self.assertFalse(x['startup_observation'])


    def test_first_seen_event_survives_list_exit_and_is_not_duplicated(self):
        import tempfile,json,config
        from pathlib import Path
        from unittest.mock import patch
        folder=Path(tempfile.mkdtemp(prefix='turning-events-',dir='D:/Temp/stock-monitor'))
        TEMP_PATHS.append(str(folder))
        f=sample();c=f[-1][1];rewrite(f,c,[100,100,100,101,103,104])
        model=attach(f);events=copy.deepcopy(model['_turning_new_events'])
        with patch.object(config,'CACHE_DIR',folder):
            T.persist_events(model)
            T.persist_events(dict(_turning_new_events=events))
        path=next((folder/'stock_selection_v3/turning_events').glob('*.jsonl'))
        records=[json.loads(line) for line in path.read_text(encoding='utf8').splitlines()]
        self.assertEqual(len(records),len({r['id'] for r in records}))
        self.assertIn(c,[r['code'] for r in records])
        self.assertNotIn('_turning_new_events',model)


    def test_pre_tracking_policy_does_not_fabricate_an_older_first_seen_for_new_rules(self):
        f=sample();c=f[-1][1];rewrite(f,c,[100,100,100,101,103,104])
        previous=run(f)['_state']
        previous['items'][c]['turning_event']=dict(first_seen_at='2020-01-01 10:00:00',first_seen_price=1.,
            first_native=1.,basis_date=f[1][c][-1]['date'],basis_close=f[1][c][-1]['close'],last_active_day=str(f[4].date()))
        result=attach(f,previous=previous)
        self.assertEqual(result['items'][c]['turning']['first_seen_at'],str(f[4]))
        event=next(e for e in result['_turning_new_events'] if e['code']==c)
        self.assertEqual(event['version'],T.VERSION)



if __name__=='__main__':unittest.main()
