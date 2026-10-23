"""收盘必须回放本地路径，而不是等待下一批实时行情。"""
import copy
import json
import tempfile
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch

import config
import intraday
import intraday_path
import serve
import stock_activity as A
import stock_activity_close as C
import stock_activity_sampler as S
from test_stock_activity import sample,board_core,calculate,render


def closing_fixture():
    f=board_core(19)
    for i,(at,frame) in enumerate(f[3]):
        at=str(A.stamp(at)+timedelta(hours=4,minutes=54))
        for p in frame.values():p.update(at=at,received_at=at)
        f[3][i]=(at,frame)
    f[0].update(quote_capture_at='2026-10-13 15:06:00',session='已收盘',close_daily_verified_at='2026-10-13 15:08:00')
    for r in f[0]['stocks']:r['quote_at']='2026-10-13 15:00:00'
    return f


def write_frames(f):
    base={r['code']:r for r in f[0]['stocks']}
    for at,frame in f[3]:
        quotes={c:dict(base[c],price=p['price'],quote_at=p['at'],change_pct=p['change']) for c,p in frame.items()}
        intraday_path.save_acquisition(S.directory(),quotes,A.stamp(at),'已收盘' if '15:00' in at else '尾盘')


def clock_error_fixture(count=6,seconds=4):
    f=sample(prices=[100]*3+[101.2]*(count-3))
    base={r['code']:r for r in f[0]['stocks']}
    for i,(at,frame) in enumerate(f[3]):
        source=str(A.stamp(at)+timedelta(seconds=seconds))
        quotes={c:dict(base[c],price=p['price'],quote_at=source) for c,p in frame.items()}
        f[3][i]=(at,A.valid_frame(quotes,A.stamp(at),'早盘'))
    for r in f[0]['stocks']:r['quote_at']=str(A.stamp(f[0]['quote_capture_at'])+timedelta(seconds=seconds))
    return f


class Closing(unittest.TestCase):
    def test_observed_clock_error_keeps_received_quotes_with_uncertain_intervals(self):
        f=clock_error_fixture(4)
        m=calculate(f)['items']['600000']
        self.assertEqual(m['list_name'],'startup')
        self.assertEqual(m['event']['source_timestamp'],'2026-10-13 09:36:04')
        self.assertEqual(m['event']['received_at'],'2026-10-13 09:36:00')
        self.assertEqual(m['event']['trigger_interval'],['2026-10-13 09:30:00','2026-10-13 09:36:08'])
        self.assertEqual(m['event']['evidence']['attack']['confirmed_at'],'2026-10-13 09:36:00')
        self.assertNotIn('timing',m['event']['evidence'])

    def test_beyond_documented_clock_error_is_still_rejected(self):
        f=clock_error_fixture(4,6)
        self.assertTrue(all(not frame for _,frame in f[3]))
        self.assertIsNone(calculate(f)['items']['600000']['event'])

    def test_holding_waits_for_duration_lower_bound_with_clock_error(self):
        m=calculate(clock_error_fixture(6))['items']['600000']
        self.assertIsNone(m['factors']['Q'])
        m=calculate(clock_error_fixture(7))['items']['600000']
        self.assertIsNotNone(m['factors']['Q'])

    def test_final_prices_come_from_1500_sources_and_keep_actual_clocks(self):
        f=closing_fixture()
        with tempfile.TemporaryDirectory() as d,patch.object(config,'CACHE_DIR',Path(d)),patch.object(intraday,'HISTORY_DIR',Path(d)/'history'):
            write_frames(f)
            late={r['code']:dict(r,price=108.,high=108.,quote_at='2026-10-13 15:05:00') for r in f[0]['stocks']}
            intraday_path.save_acquisition(S.directory(),late,A.stamp('2026-10-13 15:05:10'),'已收盘')
            snap,frames,meta=C.closing_input(f[0],A.stamp('2026-10-13 17:00:00'))
            self.assertEqual(snap['stocks'][0]['price'],101.2)
            self.assertEqual(snap['stocks'][0]['quote_at'],'2026-10-13 15:00:00')
            self.assertEqual(snap['stocks'][0]['received_at'],'2026-10-13 15:00:00')
            self.assertEqual(meta['market_close_at'],'2026-10-13 15:00:00')
            self.assertEqual(len(frames),19)

    def test_preclose_or_later_vendor_timestamps_are_not_final_sources(self):
        f=closing_fixture()
        with tempfile.TemporaryDirectory() as d,patch.object(config,'CACHE_DIR',Path(d)),patch.object(intraday,'HISTORY_DIR',Path(d)/'history'):
            quotes={r['code']:dict(r,quote_at='2026-10-13 14:59:00') for r in f[0]['stocks']}
            intraday_path.save_acquisition(S.directory(),quotes,A.stamp('2026-10-13 15:00:10'),'已收盘')
            with self.assertRaises(C.CloseNotReady):C.closing_input(f[0],A.stamp('2026-10-13 17:00:00'))

    def test_close_replays_before_migrated_processed_time_and_reuses_final_result(self):
        f=closing_fixture();now=A.stamp('2026-10-13 17:00:00')
        previous=calculate(f)['_state']
        for state in previous['items'].values():
            state.update(events=[],identity=dict(status='none'),points=[],data_gap=True,recovery_required=True)
        previous['processed_at']='2026-10-13 15:06:00'
        with tempfile.TemporaryDirectory() as d,patch.object(config,'CACHE_DIR',Path(d)),patch.object(intraday,'HISTORY_DIR',Path(d)/'history'),patch.object(A,'datetime') as clock:
            clock.now.return_value=now
            clock.fromisoformat.side_effect=datetime.fromisoformat
            write_frames(f);A.state_path().parent.mkdir(parents=True);A.save_state(previous)
            def project(snap,live=False,previous=None,frames=None):
                return A.build(snap,f[1],f[2],frames=frames,previous=previous,detected_at=str(now))
            with patch.object(A,'prepare',side_effect=project) as build:
                model=A.refresh_projection(f[0]);self.assertEqual(build.call_count,1)
            self.assertEqual(model['counts']['core'],1)
            self.assertTrue(model['close_finalized'])
            self.assertEqual(model['close_review']['replay_batches'],19)
            with patch.object(A,'prepare',side_effect=AssertionError('不应重复回放')):
                self.assertEqual(A.refresh_projection(f[0]),model)
            saved=json.loads((A.state_path().parent/'close-2026-10-13.json').read_text(encoding='utf8'))
            self.assertEqual(model,saved)

    def test_day_checkpoint_excludes_same_day_future_events_but_keeps_prior_identity(self):
        state=calculate(board_core())['_state']
        prior=copy.deepcopy(state['items']['600000']['identity'])
        seed=C.day_seed(state,'2026-10-14')
        self.assertEqual(seed['items']['600000']['identity'],prior)
        same=C.day_seed(state,'2026-10-13')
        self.assertEqual(same['items']['600000']['events'],[])
        self.assertNotIn('processed_at',same)
        self.assertEqual(state['items']['600000']['identity'],prior)

    def test_no_quote_request_after_1500_and_next_morning_is_enabled(self):
        for at in ('2026-10-13 15:00:00','2026-10-13 15:01:00','2026-10-13 17:00:00'):
            with patch.object(S,'datetime') as clock,patch.object(S.datafeed,'tencent_quotes') as fetch:
                clock.now.return_value=A.stamp(at)
                self.assertTrue(S.capture_once()['skipped']);fetch.assert_not_called()
            self.assertFalse(serve.is_trading_time(A.stamp(at)))
        self.assertTrue(S.sampling_time(A.stamp('2026-10-14 09:30:00')))
        self.assertTrue(serve.is_trading_time(A.stamp('2026-10-13 14:59:59')))

    def test_UI_close_result_is_not_stale_and_does_not_poll_after_finalization(self):
        f=closing_fixture();m=calculate(f)
        C.finalize(m,dict(market_close_at='2026-10-13 15:00:00'),A.stamp('2026-10-13 17:00:00'))
        f[0]['stock_activity']=m
        f[0]['quote_capture_at']='2026-10-13 20:00:00'
        r=render(f[0],"STATE.pane='stocks';fetch=function(){throw Error('收盘后不能继续轮询');};MS_VIEW.stocks.activityScope='core';msRender('stocks');saPoll();saShow('600000');")
        self.assertEqual(r['ids'],['600000'])
        self.assertNotIn('行情已过期',r['els']['ms-stock-host']['innerHTML'])
        self.assertIn('收盘缓存已核验',r['drawer'][2])

    def test_online_previous_day_close_is_not_a_current_core_or_startup(self):
        f=closing_fixture();m=calculate(f)
        C.finalize(m,dict(market_close_at='2026-10-13 15:00:00'),A.stamp('2026-10-13 17:00:00'))
        f[0].update(stock_activity=m,quote_capture_at='2026-10-14 09:35:00')
        r=render(f[0],"location={protocol:'http:'};STATE.pane='stocks';MS_VIEW.stocks.activityScope='core';msRender('stocks');var calls=0;fetch=function(){calls++;return new Promise(function(){});};saPoll();document.getElementById('poll-proof').textContent=String(calls);")
        self.assertEqual(r['ids'],[])
        self.assertIn('行情已过期',r['els']['ms-stock-host']['innerHTML'])
        self.assertEqual(r['els']['poll-proof']['textContent'],'1')

    def test_exported_close_snapshot_remains_viewable_on_a_later_day(self):
        f=closing_fixture();m=calculate(f)
        C.finalize(m,dict(market_close_at='2026-10-13 15:00:00'),A.stamp('2026-10-13 17:00:00'))
        f[0].update(stock_activity=m,quote_capture_at='2026-10-14 09:35:00')
        r=render(f[0],"location={protocol:'file:'};STATE.pane='stocks';fetch=function(){throw Error('离线快照不能请求实时接口');};MS_VIEW.stocks.activityScope='core';msRender('stocks');saPoll();")
        self.assertEqual(r['ids'],['600000'])
        self.assertNotIn('行情已过期',r['els']['ms-stock-host']['innerHTML'])

    def test_selective_minute_cache_is_evidence_without_filling_score_or_timing(self):
        f=closing_fixture();m=calculate(f);before=copy.deepcopy(m['items']['600000']['factors'])
        bars=[dict(at='2026-10-13 '+t,open=p,high=p,low=p,close=p,price_basis='raw',source='本地分钟缓存') for t,p in [('14:30',100.),('14:59',101.2),('15:00',101.2)]]
        with tempfile.TemporaryDirectory() as d,patch.object(config,'CACHE_DIR',Path(d)):
            path=Path(d)/'trend_monitor_minutes/2026-10-13.json';path.parent.mkdir()
            path.write_text(json.dumps(dict(stocks={'600000':bars},fetched_at={'600000':'2026-10-13 15:01:00'})),encoding='utf8')
            C.finalize(m,dict(market_close_at='2026-10-13 15:00:00'),A.stamp('2026-10-13 17:00:00'))
        self.assertEqual(m['items']['600000']['factors'],before)
        e=m['items']['600000']['evidence']['close_minute_review']
        self.assertFalse(e['used_in_score']);self.assertFalse(e['used_in_timing'])
        self.assertAlmostEqual(e['last_half_hour_return_pct'],1.2)

    def test_close_default_shows_confirmed_core_before_reference_fallback(self):
        f=closing_fixture();m=calculate(f)
        C.finalize(m,dict(market_close_at='2026-10-13 15:00:00'),A.stamp('2026-10-13 17:00:00'))
        f[0]['stock_activity']=m
        self.assertEqual(render(f[0],"msRender('stocks');")['view']['activityScope'],'core')
        m['counts'].update(core=0,startup=0,reference=1)
        m['items']['600000'].update(list_name='reference',eligible=False)
        self.assertEqual(render(f[0],"msRender('stocks');")['view']['activityScope'],'reference')


if __name__=='__main__':unittest.main()
