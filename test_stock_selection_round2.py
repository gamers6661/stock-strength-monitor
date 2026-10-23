"""Round-two regressions for confirmed audit defects; fixtures are constructed, not live signals."""
import copy
import gzip
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch

import config
import stock_selection as S
import stock_selection_validation as V
import stock_selection_intraday as I
import stock_selection_rollout as R
from test_stock_selection import sample


TEMP_PATHS=[]


def ready_model(day='2026-10-19',eligible=True):
    x=dict(score=70.,eligible=eligible,list_name='strong' if eligible else 'watch',data_status='有效',board=dict(industry='测试行业'),
        evidence=dict(amount_days=20,median_amount=1e8,market_returns={'5':3.}),
        intraday=dict(available=True,completed_daily_proof=dict(date=day)))
    return dict(version='fixture',implementation_hash='fixture',day=day,daily_at=day,close_finalized=True,
        captured_at=day+' 16:00:00',source_at=day+' 15:00:00',pool_count=1,
        coverage=dict(daily=1,market=1.,amount_complete=1),items={'600000':x})


def freeze():
    return dict(implementation_hash='fixture',frozen_at='2026-01-01 10:00:00',rules=copy.deepcopy(S.R))


def bar(day,price=100.):
    return dict(date=day,open=price,close=price,high=price+1,low=price-1,volume=1e6,
        price_basis='raw',price_basis_source=next(iter(S.intraday._RAW_HISTORY_SOURCES)))


class Round2(unittest.TestCase):
    def setUp(self):
        self.tmp=Path(tempfile.mkdtemp(prefix='selection-round2-',dir='D:/Temp/stock-monitor'))
        TEMP_PATHS.append(str(self.tmp))
        self.cache=patch.object(config,'CACHE_DIR',self.tmp);self.cache.start();self.addCleanup(self.cache.stop)
        R.save(R.root()/'validation-registry.json',{'fixture':freeze()})

    def close(self,model):
        R.save(R.root()/('close-'+model['daily_at']+'.json'),model)

    def test_pending_data_never_seals_zero_and_can_later_become_ready(self):
        model=ready_model();x=model['items']['600000'];x.update(eligible=False,data_status='真实成交额待补齐')
        x['evidence'].update(amount_days=19,median_amount=None);model['coverage']['amount_complete']=0
        self.close(model);a=V.forward({},[])
        self.assertEqual(a['signal_days'],0);self.assertEqual(len(a['pending_decisions']),1)
        self.assertEqual(list((R.root()/'shadow').glob('forward-signals-*')),[])
        self.close(ready_model());b=V.forward({'600000':[bar('2026-10-19'),bar('2026-10-20',102)]},['2026-10-19','2026-10-20'])
        self.assertEqual(b['signal_days'],1);self.assertEqual(b['decisions'][0]['selected_count'],1)
        self.assertEqual(b['mature'],1);self.assertAlmostEqual(b['observations'][0]['return_pct'],2.)

    def test_genuine_zero_signal_day_is_recorded_separately_from_missing_data(self):
        self.close(ready_model(eligible=False));report=V.forward({},[])
        self.assertEqual(report['signal_days'],1);self.assertEqual(report['decisions'][0]['selected_count'],0)
        self.assertEqual(report['pending_decisions'],[]);self.assertEqual(report['observations'],[])

    def test_missing_close_quote_does_not_seal_a_decision(self):
        m=ready_model();m['items']['600000']['intraday']['available']=False;self.close(m)
        report=V.forward({},[])
        self.assertEqual(report['signal_days'],0);self.assertTrue(report['pending_decisions'])

    def test_first_ready_decision_remains_immutable(self):
        self.close(ready_model());V.forward({},[])
        self.close(ready_model(eligible=False));b=V.forward({},[])
        self.assertEqual(b['decisions'][0]['selected_count'],1)

    def test_mature_result_survives_loss_of_current_history(self):
        self.close(ready_model());a=V.forward({'600000':[bar('2026-10-19'),bar('2026-10-20',102)]},['2026-10-19','2026-10-20'])
        b=V.forward({},[])
        self.assertEqual(a['mature'],b['mature']);self.assertEqual(b['mature'],1)
        self.assertEqual(b['observations'][0]['return_pct'],a['observations'][0]['return_pct'])

    def test_old_removed_security_uses_full_database_without_current_pool(self):
        dates=[];d=datetime(2026,1,2)
        while len(dates)<120:
            if d.weekday()<5:dates.append(str(d.date()))
            d+=timedelta(days=1)
        db=self.tmp/'history.db';con=sqlite3.connect(db)
        con.execute('CREATE TABLE kline(code TEXT,date TEXT,open REAL,close REAL,high REAL,low REAL,volume REAL,amount REAL,price_basis TEXT,price_basis_source TEXT)')
        for i,day in enumerate(dates):
            b=bar(day,100+i)
            con.execute('INSERT INTO kline VALUES(?,?,?,?,?,?,?,?,?,?)',('600000',day,b['open'],b['close'],b['high'],b['low'],b['volume'],1e8,b['price_basis'],b['price_basis_source']))
        con.commit();con.close()
        self.close(ready_model(dates[0]))
        with patch.object(config,'KLINE_DB',db),patch('stock_selection_calendar.load_calendar',return_value=dates),patch.object(S,'inputs',side_effect=AssertionError('must not read today pool')):
            result=V.forward()
        self.assertEqual(result['mature'],4);self.assertEqual(result['signal_days'],1)

    def test_mixed_price_basis_is_not_a_future_return(self):
        bars=[bar('2026-10-19'),bar('2026-10-20',102)];bars[-1]['price_basis']='qfq'
        self.assertIsNone(V.outcome(bars,'2026-10-19',1,['2026-10-19','2026-10-20']))

    def test_low_liquidity_is_known_not_a_data_gap(self):
        m=ready_model(eligible=False);m['items']['600000'].update(data_status='流动性不足',list_name='excluded')
        m['items']['600000']['evidence']['median_amount']=1e6
        self.assertTrue(V.valid_forward_model(m,freeze()))

    def quote_case(self,confirmed=False):
        f=sample();snap,h,cal,records,_,codes=f;day=cal[-1];code=codes[1]
        snap.update(quote_capture_at=day+' 15:00:00',session='已收盘',close_daily_verified_at=day+' 16:00:00')
        for row in snap['stocks']:row['quote_at']=day+' 15:00:00'
        high,low,volume=(103.2,100.,2e6) if confirmed else (105.,99.,1e6)
        b=h[code][-1];b.update(open=100.,close=103.,high=high,low=low,volume=volume)
        records[code][day]=dict(b,amount=103*volume,source=__import__('stock_selection_data').SOURCE)
        row=next(r for r in snap['stocks'] if r['code']==code)
        row.update(price=103.,open=100.,high=high,low=low,last_close=100.,amount_wan=103*volume/10000,volume_shou=volume/100,change_pct=3.)
        return snap,h,cal,records,datetime.fromisoformat(day+' 16:00:00'),code

    def test_price_only_close_is_not_labeled_confirmed(self):
        snap,h,cal,records,now,c=self.quote_case()
        m=S.build(snap,h,cal,amount_records=records,now=now)['items'][c]
        self.assertEqual(m['pattern'],'突破待确认');self.assertFalse(m['eligible'])
        self.assertEqual(m['intraday']['state'],'价格突破待量价确认')
        self.assertFalse(m['intraday']['completed_breakout_confirmed'])

    def test_formal_breakout_gate_and_label_are_consistent(self):
        snap,h,cal,records,now,c=self.quote_case(True)
        m=S.build(snap,h,cal,amount_records=records,now=now)['items'][c]
        self.assertTrue(next(g['passed'] for g in m['gates'] if g['name']=='突破确认'))
        self.assertEqual(m['intraday']['state'],'突破收盘确认');self.assertTrue(m['eligible'])

    def test_next_day_hold_does_not_hide_current_weakness(self):
        snap,h,cal,records,now,c=self.quote_case(True)
        prev=h[c][-2];prev.update(open=110.,close=110.,high=111.,low=109.)
        b=h[c][-1];b.update(open=110.,close=103.,high=110.,low=102.,volume=1e6)
        records[c][cal[-1]]=dict(b,amount=103e6,source=__import__('stock_selection_data').SOURCE)
        row=next(r for r in snap['stocks'] if r['code']==c)
        row.update(last_close=110.,open=110.,high=110.,low=102.,volume_shou=10000.,amount_wan=10300.,change_pct=100*(103/110-1))
        previous={'items':{c:{'breakout':dict(date=cal[-2],level=101.,volume_confirmed=False,basis_date=cal[-2],basis_close=110.)}}}
        m=S.build(snap,h,cal,previous=previous,amount_records=records,now=now)['items'][c]
        self.assertTrue(next(g['passed'] for g in m['gates'] if g['name']=='突破确认'))
        self.assertEqual(m['intraday']['state'],'转弱');self.assertFalse(m['eligible'])
        self.assertFalse(m['intraday']['completed_breakout_confirmed'])

    def test_unfinished_or_previous_day_cannot_be_finalized(self):
        snap,h,cal,records,now,c=self.quote_case(True)
        model=S.build(snap,h,cal,amount_records=records,now=now+timedelta(days=1))
        self.assertFalse(model['close_finalized'])
        model=S.build(snap,h,cal,amount_records=records,now=now.replace(hour=15))
        self.assertFalse(model['close_finalized'])

    def same_time_case(self,days=5,offset=-20):
        calendar=['2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16','2026-10-19']
        db=sqlite3.connect(I.path());db.execute('CREATE TABLE volumes(day TEXT,second INTEGER,code TEXT,volume REAL,PRIMARY KEY(day,second,code))')
        for day in calendar[:days]:db.execute('INSERT INTO volumes VALUES(?,?,?,?)',(day,36000+offset,'600000',1000.))
        db.commit();db.close()
        source=dict(quote_capture_at='2026-10-19 10:00:00',stocks=[dict(code='600000',volume_shou=2000.,price_basis='raw',price_basis_source='tencent_realtime_quote')])
        model=dict(day='2026-10-19',items={'600000':dict(score=77.,eligible=True,intraday=dict(available=True,at='2026-10-19 10:00:00'))})
        return I.attach(model,source,calendar)['items']['600000']

    def test_same_clock_ratio_computes_with_five_real_days_and_does_not_change_score(self):
        x=self.same_time_case()
        self.assertEqual(x['intraday']['volume_ratio_same_time'],2.)
        self.assertEqual(x['score'],77.);self.assertTrue(x['eligible'])

    def test_same_clock_missing_day_is_unknown(self):
        x=self.same_time_case(days=4)
        self.assertIsNone(x['intraday']['volume_ratio_same_time'])
        self.assertEqual(x['intraday']['same_time_reference_days'],4)

    def test_same_clock_outside_tolerance_is_not_substituted(self):
        x=self.same_time_case(offset=-121)
        self.assertIsNone(x['intraday']['volume_ratio_same_time'])

    def test_current_other_source_cannot_use_tencent_reference(self):
        self.same_time_case()
        source=dict(stocks=[dict(code='600000',volume_shou=2000.,price_basis='raw',price_basis_source='akshare_sina_spot')])
        model=dict(day='2026-10-19',items={'600000':dict(intraday=dict(available=True,at='2026-10-19 10:00:00'))})
        x=I.attach(model,source,['2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16','2026-10-19'])['items']['600000']['intraday']
        self.assertIsNone(x['volume_ratio_same_time']);self.assertIn('来源待核验',x['same_time_volume_reason'])

    def test_ingestion_accepts_only_true_tencent_and_is_idempotent(self):
        day='2026-10-20';at=day+' 10:00:00'
        q=dict(price=100.,open=100.,high=101.,low=99.,last_close=100.,change_pct=0.,amount_wan=10000.,volume_shou=10000.,quote_at=at,
               price_basis='raw',price_basis_source='tencent_realtime_quote',last_close_semantics='previous_trade_day_raw_close',last_close_precision_digits=2)
        fields=['code']+list(q)
        rows=[['600000']+list(q.values()),['600001']+list(dict(q,price_basis_source='akshare_sina_spot').values())]
        folder=self.tmp/'intraday_history';(folder/'acquisitions').mkdir(parents=True)
        with gzip.open(folder/'acquisitions'/('2026-10-20.jsonl.gz'),'wt',encoding='utf8') as stream:
            stream.write(json.dumps(dict(captured_at=at,session='早盘',fields=fields,rows=rows))+'\n')
        with patch.object(S.intraday,'HISTORY_DIR',folder):
            first=I.update_history([day],datetime(2026,10,21,10));second=I.update_history([day],datetime(2026,10,21,10))
        con=sqlite3.connect(I.path());codes=list(con.execute('SELECT code FROM volumes'));con.close()
        self.assertEqual(codes,[('600000',)]);self.assertEqual(first['inserted'],1);self.assertEqual(second['inserted'],0)

    def test_next_completed_hold_can_confirm_below_updated_high(self):
        snap,h,cal,records,now,c=self.quote_case(True)
        prev=h[c][-2];prev.update(open=104.,close=104.,high=104.2,low=103.)
        row=next(r for r in snap['stocks'] if r['code']==c);row.update(last_close=104.,change_pct=100*(103/104-1))
        previous={'items':{c:{'breakout':dict(date=cal[-2],level=101.,volume_confirmed=False,basis_date=cal[-2],basis_close=104.)}}}
        m=S.build(snap,h,cal,previous=previous,amount_records=records,now=now)['items'][c]
        self.assertTrue(m['eligible']);self.assertFalse(m['intraday']['breakout_pending'])
        self.assertEqual(m['intraday']['state'],'突破收盘确认')

    def gap_case(self,known=True,ipo=False):
        dates=[];d=datetime(2026,8,3)
        while len(dates)<27:
            if d.weekday()<5:dates.append(str(d.date()))
            d+=timedelta(days=1)
        missing=dates[-1] if not known else dates[5]
        history=[bar(d) for d in dates if d!=missing]
        master={'600000':dict(ipoDate=dates[-3] if ipo else '1990-01-01')}
        if ipo:history=[bar(d) for d in dates[-3:]]
        snap=dict(stocks=[dict(code='600000')],_security_master=master,quote_capture_at=dates[-1]+' 16:00:00')
        old=dict(asof=dates[-2],halted_dates=[missing] if known and not ipo else [],ipo_date=master['600000']['ipoDate'],source='BaoStock 日线 tradestatus / volume',checked_at=dates[-2]+' 16:00:00')
        R.save(R.root()/'history_gap_verification.json',{'600000':old})
        return snap,{'600000':history},dates,missing

    def test_verified_halt_facts_survive_next_market_day(self):
        import stock_selection_maintenance as M
        snap,h,cal,missing=self.gap_case()
        with patch.object(M,'fetch_halted_dates',side_effect=AssertionError('known dates need no new source call')):
            report=M.refresh_gap_proofs(snap,h,cal)
        self.assertEqual(report['updated'],1);self.assertEqual(S.read('history_gap_verification.json')['600000']['asof'],cal[-1])

    def test_new_gap_requires_new_verified_halt(self):
        import stock_selection_maintenance as M
        snap,h,cal,missing=self.gap_case(known=False)
        with patch.object(M,'fetch_halted_dates',return_value={missing}):report=M.refresh_gap_proofs(snap,h,cal)
        self.assertEqual(report['updated'],1);self.assertIn(missing,S.read('history_gap_verification.json')['600000']['halted_dates'])

    def test_unproven_new_gap_keeps_old_proof_and_pending(self):
        import stock_selection_maintenance as M
        snap,h,cal,missing=self.gap_case(known=False)
        with patch.object(M,'fetch_halted_dates',return_value=set()):report=M.refresh_gap_proofs(snap,h,cal)
        self.assertEqual(report['updated'],0);self.assertTrue(report['pending'])
        self.assertEqual(S.read('history_gap_verification.json')['600000']['asof'],cal[-2])

    def test_verified_ipo_date_updates_window_without_inventing_history(self):
        import stock_selection_maintenance as M
        snap,h,cal,missing=self.gap_case(ipo=True)
        with patch.object(M,'fetch_halted_dates',side_effect=AssertionError('IPO date already verified')):report=M.refresh_gap_proofs(snap,h,cal)
        self.assertEqual(report['updated'],1);self.assertEqual(len(h['600000']),3)
        proof=S.read('history_gap_verification.json')['600000'];self.assertEqual(proof['asof'],cal[-1]);self.assertEqual(proof['halted_dates'],[])

    def halt_source_fixture(self,code='sh.600000'):
        from types import SimpleNamespace
        class Query:
            fields=['date','code','volume','tradestatus'];error_code='0';taken=False
            def next(self):
                if self.taken:return False
                self.taken=True;return True
            def get_row_data(self):return ['2026-10-20',code,'','0']
        return SimpleNamespace(login=lambda:SimpleNamespace(error_code='0'),logout=lambda:None,query_history_k_data_plus=lambda *a,**k:Query())

    def test_real_source_empty_volume_with_explicit_halt_status_is_verified(self):
        import stock_selection_maintenance as M
        with patch.dict('sys.modules',{'baostock':self.halt_source_fixture()}):
            self.assertEqual(M.fetch_halted_dates('600000','2026-10-19','2026-10-20'),{'2026-10-20'})

    def test_halt_source_wrong_security_is_rejected(self):
        import stock_selection_maintenance as M
        with patch.dict('sys.modules',{'baostock':self.halt_source_fixture('sh.600001')}):
            with self.assertRaises(ValueError):M.fetch_halted_dates('600000','2026-10-19','2026-10-20')

    def test_quality_and_forward_publish_finish_before_optional_fund_request(self):
        import stock_selection_maintenance as M
        import io
        from contextlib import redirect_stdout
        events=[];snap=self.tmp/'snapshot.json';snap.write_text(json.dumps(dict(quote_capture_at='2026-10-20 16:00:00',stocks=[])),encoding='utf8')
        R.save(R.root()/'security_master.json',dict(observed_at=str(datetime.now()),stocks={}))
        with patch('stock_selection_calendar.refresh_calendar',return_value={}),patch.object(M.config,'SNAPSHOT_JSON',snap),patch.object(M.S,'inputs',return_value=({},['2026-10-20'])),\
             patch.object(M,'refresh_gap_proofs',side_effect=lambda *a:events.append('quality') or {}),\
             patch.object(M,'publish_and_validate',side_effect=lambda:events.append('publish-forward') or {}),\
             patch.object(M.fund_history,'refresh',side_effect=lambda *a,**k:events.append('fund') or (_ for _ in ()).throw(RuntimeError('fund unavailable'))),redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):M.maintain()
        self.assertEqual(events,['quality','publish-forward','fund'])

    def test_post_close_publish_precedes_forward_sealing(self):
        import stock_selection_maintenance as M
        events=[]
        with patch.object(M.S,'refresh_projection',side_effect=lambda:events.append('publish') or {'result_version':'r'}),\
             patch('stock_activity.live_view',return_value={}),patch.object(M.config,'SNAPSHOT_JSON',self.tmp/'snap.json'),\
             patch.object(V,'archive_metadata',side_effect=lambda s:events.append('metadata')),\
             patch.object(V,'forward',side_effect=lambda:events.append('forward') or dict(mature=0,awaiting=0,pending_decisions=[])):
            (self.tmp/'snap.json').write_text('{}',encoding='utf8')
            M.publish_and_validate()
        self.assertEqual(events,['publish','metadata','forward'])


if __name__=='__main__':unittest.main()
