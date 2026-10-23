"""Acquisition repair and independent recovery-event business contracts."""
import copy,json,tempfile,unittest,subprocess,csv,io
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import close_monitor as C
import ma_trend as T
import intraday
import config
from test_ma_trend import sample,run
from test_ma_radar_transition import minutes
from test_market_strength_integration import render

def candidate_fixture():
    f=sample();code=next(iter(f[3]));bars=f[3][code]
    values=[105,107,110,108,106,103,99,99,99,99,99,108.9]
    for j,c in enumerate(values):
        i=len(bars)-len(values)+j;op=bars[i-1]['close']
        bars[i].update(open=op,close=c,high=max(op,c)+.2,low=min(op,c)-.2,volume=250 if j==0 else 40)
    bars[-1].update(high=108.9,volume=50)
    q=f[1][code];q.update(last_close=108.9,price=109.,open=108.9,high=109.1,low=108.9,change_pct=100*(109/108.9-1))
    return f

class RecoveryCandidate(unittest.TestCase):
    def test_candidate_is_separate_from_old_origin_and_not_qualified(self):
        f=candidate_fixture();bars=next(iter(f[3].values()));setup=T.daily(bars,f[4],limit_pct=10)
        c=setup['recovery_candidate'];self.assertTrue(c['active']);self.assertEqual(c['date'],bars[-1]['date'])
        self.assertLess(c['previous_origin'],c['previous_exit']);self.assertLess(c['previous_exit'],c['date'])
        self.assertIsNone(setup['stage']);self.assertLess(c['volume_ratio'],T.P['volume_ratio'])
        m=run(f);self.assertTrue(m['candidate_mode']);self.assertFalse(m['eligible']);self.assertFalse(m['pending'])
        self.assertIsNone(m['stage']);self.assertIsNone(m['exit_at']);self.assertIn('涨停收复',m['events'])
        self.assertIn(m['code'],f[0]['ma_trend']['startup_pending']);self.assertNotIn(m['code'],f[0]['ma_trend']['current'])
        rank=f[0]['stock_board_ranking']['all']['items'][m['code']]
        self.assertIn('涨停收复',rank['style_labels']);self.assertFalse(rank['trend'])

    def test_unsealed_unknown_limit_and_no_reclaim_do_not_create_event(self):
        for change in ('unsealed','unknown','not_limit','no_reclaim'):
            f=candidate_fixture();bars=next(iter(f[3].values()));limit=10
            if change=='unsealed':bars[-1]['high']+=.1
            if change=='unknown':limit=None
            if change=='not_limit':bars[-1].update(close=107.,high=107.)
            if change=='no_reclaim':bars[-2].update(open=109.,close=109.,high=109.2,low=108.8)
            self.assertIsNone(T.daily(bars,f[4],limit_pct=limit)['recovery_candidate'],change)

    def test_continuous_wave_does_not_reset_to_recovery_event(self):
        f=sample('retained');bars=next(iter(f[3].values()));b=bars[-1];b.update(close=bars[-2]['close']*1.1,high=bars[-2]['close']*1.1,volume=40)
        self.assertIsNone(T.daily(bars,f[4],limit_pct=10)['recovery_candidate'])

    def test_completed_ma10_failure_ends_candidate(self):
        f=candidate_fixture();bars=next(iter(f[3].values()));day=f[5].date().isoformat()
        bars.append(dict(bars[-1],date=day,open=108.9,close=98.,high=109.,low=98.))
        c=T.daily(bars,f[4]+[day],limit_pct=10)['recovery_candidate']
        self.assertFalse(c['active']);self.assertEqual(c['state'],'候选已失效');self.assertEqual(c['ended_at'],day)

    def test_timed_candidate_failure_persists_after_intraday_recovery(self):
        f=candidate_fixture();code=next(iter(f[1]));q=f[1][code]
        ctx=intraday.align_price_basis(q,f[3][code],f[4],observation_day=f[5].date().isoformat())
        price=ctx['thresholds'][10]-.1*ctx['atr20'];q.update(price=price,low=price-.01)
        m=run(f);self.assertEqual(m['status'],'支撑过程待核验');self.assertTrue(m['recovery_candidate']['active'])
        m=run(f,minutes=minutes(f,price));self.assertEqual(m['status'],'候选已失效');self.assertFalse(m['startup_pending'])
        prior=copy.deepcopy(f[0]);q.update(price=109.,quote_at=str(f[5]+timedelta(minutes=1)))
        m=run((*f[:5],f[5]+timedelta(minutes=1)),previous=prior)
        self.assertEqual(m['status'],'候选已失效');self.assertFalse(m['recovery_candidate']['active'])
        failed=copy.deepcopy(f[0]);q['quote_at']=str(f[5]-timedelta(minutes=11))
        m=run(f,previous=failed);self.assertTrue(m['pending'])
        gap=copy.deepcopy(f[0]);q['quote_at']=str(f[5]+timedelta(minutes=2))
        m=run((*f[:5],f[5]+timedelta(minutes=2)),previous=gap)
        self.assertEqual(m['status'],'候选已失效');self.assertFalse(m['recovery_candidate']['active'])

    def test_current_uncompleted_limit_price_cannot_create_recovery(self):
        f=candidate_fixture();bars=next(iter(f[3].values()));bars[-1].update(close=99.,high=99.)
        q=next(iter(f[1].values()));q.update(last_close=99.,price=108.9,high=108.9,low=105.,change_pct=10.)
        m=run(f);self.assertIsNone(m.get('recovery_candidate'))

    def test_candidate_label_date_tooltip_and_csv_share_backend(self):
        f=candidate_fixture();m=run(f);date=m['recovery_candidate']['date']
        rendered=render(f[0],"MS_VIEW.radar.scope='startup_pending';MS_VIEW.radar.phase='涨停收复';var rs=mtRows();document.getElementById('proof').innerHTML=JSON.stringify({codes:rs.map(r=>r.code),html:mtTable(rs)});")
        result=json.loads(rendered['els']['proof']['innerHTML'])
        self.assertEqual(result['codes'],[m['code']]);self.assertIn('本轮收复 '+date,result['html'])
        self.assertNotIn('历史启动',result['html']);self.assertIn('data-tip=',result['html'])
        data=json.dumps(dict(rows=f[0]['stocks'],data=f[0],contexts=dict(view='radar')),ensure_ascii=False)
        p=subprocess.run(['node','csv_export.js'],input=data,capture_output=True,text=True,encoding='utf-8',check=True)
        row=next(csv.DictReader(io.StringIO(p.stdout.lstrip('\ufeff'))));self.assertEqual(row['涨停收复候选日期'],date)

class MinuteAcquisition(unittest.TestCase):
    DAY='2026-10-15'
    def test_timed_out_running_request_rotates_behind_unattempted_tail(self):
        import threading
        entered=threading.Event();release=threading.Event();completed=threading.Event();calls=[]
        def loader(code,day):
            calls.append(code)
            if code=='first':
                entered.set();release.wait(2);completed.set()
            return []
        with tempfile.TemporaryDirectory() as tmp,patch.object(C,'MINUTE_DIR',Path(tmp)), \
             patch.object(C,'_load_minute_cache',return_value={'stocks':{}}), \
             patch.object(C,'_minute_bars',side_effect=loader), \
             patch.object(C,'_MINUTE_ATTEMPT',{'day':None,'at':{}}), \
             patch.dict(config.MA_TREND,minute_fetch_workers=1,minute_fetch_seconds=.05):
            try:
                C._get_minutes(['first','tail'],self.DAY,dict(first=self.DAY+' 09:50:30',tail=self.DAY+' 09:50:30'))
                self.assertTrue(entered.is_set());self.assertEqual(calls,['first'])
                self.assertIn('first',C._MINUTE_ATTEMPT['at']);self.assertNotIn('tail',C._MINUTE_ATTEMPT['at'])
            finally:
                release.set();completed.wait(2)
            C._get_minutes(['first','tail'],self.DAY,dict(first=self.DAY+' 09:50:30',tail=self.DAY+' 09:50:30'))
            self.assertEqual(calls[:2],['first','tail'])

    def bars(self):
        f=sample();data=minutes(f,101.);out=next(iter(data.values()))[:20]
        for b in out:b['at']=self.DAY+b['at'][10:]
        return out

    def test_empty_partial_and_invalid_fetch_never_erase_real_observations(self):
        bars=self.bars();self.assertEqual(C._merge_minutes(bars,[],self.DAY),bars)
        partial=copy.deepcopy(bars[-3:]);partial[-1]['close']+=.001
        merged=C._merge_minutes(bars,partial,self.DAY);self.assertEqual(len(merged),len(bars));self.assertEqual(merged[-1],partial[-1])
        bad=dict(bars[-1],price_basis_source='unknown')
        self.assertEqual(C._merge_minutes(bars,[bad],self.DAY),bars)

    def fetch(self,cache,loader,codes=None):
        with tempfile.TemporaryDirectory() as d,patch.object(C,'MINUTE_DIR',Path(d)),patch.object(C,'_load_minute_cache',return_value=cache),patch.object(C,'_minute_bars',side_effect=loader) as mock:
            stats={};result=C._get_minutes(codes or ['x'],self.DAY,{c:self.DAY+' 09:50:30' for c in codes or ['x']},request_stats=stats)
            return result,stats,mock.call_count

    def test_all_needed_stocks_are_fetched_without_24_stock_rotation(self):
        codes=[str(i) for i in range(61)];bars=self.bars()
        result,stats,count=self.fetch({'day':self.DAY,'stocks':{}},lambda *_:bars,codes)
        self.assertEqual(count,61);self.assertEqual(stats['completed'],61);self.assertEqual(len(result),61)

    def test_internal_gap_is_backfilled_even_with_current_tail(self):
        bars=self.bars();gap=bars[:5]+bars[6:]
        self.assertFalse(C._minute_coverage(gap,self.DAY,self.DAY+' 09:50:30'))
        result,stats,count=self.fetch({'day':self.DAY,'stocks':{'x':gap}},lambda *_:bars)
        self.assertEqual(count,1);self.assertEqual(result['x'],bars);self.assertTrue(C._minute_coverage(result['x'],self.DAY,self.DAY+' 09:50:30'))

    def test_network_failure_and_empty_response_keep_cache(self):
        for error in (False,True):
            bars=self.bars()
            def loader(*_):
                if error:raise OSError('provider unavailable')
                return []
            result,stats,count=self.fetch({'day':self.DAY,'stocks':{'x':bars}},loader)
            self.assertEqual(result['x'],bars);self.assertEqual(stats['errors' if error else 'empty'],1)

    def test_minutes_after_quote_do_not_count_as_current_evidence(self):
        bars=self.bars();self.assertFalse(C._minute_coverage(bars[10:],self.DAY,self.DAY+' 09:40:30'))

    def certify(self,*,traded=False,wrong_day=False,wrong_price=False,missing=False):
        bars=self.bars();a=bars[4];b=bars[6];gap=bars[:5]+bars[6:]
        price=a['close']+(1 if wrong_price else 0)
        qt=['']*31;qt[2]='600001';qt[30]='20261015095030'
        points=[a['at'][11:].replace(':','')+f' {price} 10 1000',bars[5]['at'][11:].replace(':','')+f' {price} '+('11 1100' if traded else '10 1000')]
        if missing:points=points[:1]
        payload=dict(code=0,data={'sh600001':dict(data=dict(date='20261014' if wrong_day else '20261015',data=points),qt={'sh600001':qt})})
        with patch.object(C.df,'http_get',return_value=json.dumps(payload)):
            return gap,C._certify_no_trade_gaps('600001',self.DAY,gap)

    def test_zero_turnover_evidence_covers_gap_without_creating_ohlc(self):
        gap,certified=self.certify()
        self.assertEqual(len(gap),len(certified));self.assertTrue(C._certified_gap(certified[4],certified[5]))
        self.assertTrue(C._minute_coverage(certified,self.DAY,self.DAY+' 09:50:30'))
        for a,b in zip(gap,certified):
            self.assertEqual({k:a[k] for k in ('at','open','high','low','close')},{k:b[k] for k in ('at','open','high','low','close')})
        ctx=dict(valid=True,quote_basis='raw',quote_basis_source='tencent_realtime_quote',quote_day=self.DAY,support=100.,atr20=5.)
        result=T.minutes_status(certified,ctx,{},self.DAY+' 09:50:30')
        self.assertEqual(result['state'],'守线');self.assertEqual(result['coverage']['no_trade_minutes'],1)
        self.assertEqual(T.minutes_status(gap,ctx,{},self.DAY+' 09:50:30')['state'],'待核验')

    def test_traded_missing_wrong_day_or_unmatched_price_cannot_certify_gap(self):
        for variant in ('traded','missing','wrong_day','wrong_price'):
            gap,certified=self.certify(**{variant:True})
            self.assertFalse(C._certified_gap(certified[4],certified[5]),variant)
            self.assertFalse(C._minute_coverage(certified,self.DAY,self.DAY+' 09:50:30'),variant)

class FreshnessDisplay(unittest.TestCase):
    def test_iso_expiry_and_local_quote_share_the_same_freshness_window(self):
        f=sample();run(f)
        source=Path('dashboard_template.html').read_text(encoding='utf-8')
        parse=source[source.index('function parseDT('):source.index('function sessionNow(')]
        script=parse+"""
        function sessionNow(){return '早盘';}
        var now=new Date(),fresh=new Date(now.getTime()-60000),stale=new Date(now.getTime()-660000);
        function local(d){return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')+' '+String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')+':'+String(d.getSeconds()).padStart(2,'0');}
        function stock(d){return {market_strength:{emotion_at:local(d),emotion_score:70,mode:'连续竞价'}};}
        document.getElementById('proof').innerHTML=JSON.stringify({fresh:msRankFresh(stock(fresh),{}),stale:msRankFresh(stock(stale),{}),iso:mtSnapshotFresh({mode:'连续竞价',valid_until:new Date(now.getTime()+60000).toISOString()})});
        """
        result=json.loads(render(f[0],script)['els']['proof']['innerHTML'])
        self.assertEqual(result,dict(fresh=True,stale=False,iso=True))

if __name__=='__main__':unittest.main()
