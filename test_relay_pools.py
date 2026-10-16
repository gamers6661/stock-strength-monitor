"""Cap-quality ordering, source clocks, cycle breaks and observed feedback."""
import copy,json,unittest
from datetime import datetime,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import relay_data as D,relay_pools as W
from test_emotion_relay import sample,run

class CapStrength(unittest.TestCase):
    def fixture(self):
        now=datetime(2026,10,15,14,30)
        m=dict(code='600001',price=11.,valid=True,height_exact=True,height=2,mode='盘中暂态',quote_at=str(now))
        pool=dict(day='2026-10-15',provider_market_date=20261015,fetched_at=str(now),entries={
            '600001':dict(price=11,first_seal=93000,last_seal=100012,reopen_count=1,seal_amount_yuan=2000000,amount_yuan=10000000)})
        return m,pool,now
    def test_live_fields_have_verified_units_and_times(self):
        m,p,n=self.fixture();s=W.strength(m,{},p,'2026-10-15',n)
        self.assertTrue(s['verified']);self.assertEqual(s['seal_to_amount_pct'],20)
        self.assertEqual(s['first_seal'],'09:30:00');self.assertEqual(s['labels'],['回封涨停'])
    def test_real_fetch_fractional_seconds_are_preserved_and_accepted(self):
        m,p,n=self.fixture();p['fetched_at']=str(n-timedelta(microseconds=345678))
        s=W.strength(m,{},p,'2026-10-15',n)
        self.assertTrue(s['verified']);self.assertEqual(s['source_at'],p['fetched_at'])
    def test_request_completion_clock_accepts_actual_response_without_moving_quote_clock(self):
        m,p,n=self.fixture();end=n+timedelta(milliseconds=200);p['fetched_at']=str(end)
        with TemporaryDirectory() as folder,patch.object(D,'root',return_value=Path(folder)), \
             patch.object(D,'fetch_pool',return_value=p),patch.object(W,'datetime',wraps=datetime) as clock:
            clock.now.return_value=end
            loaded=W.load_current('2026-10-15',n,False)
            self.assertEqual(loaded,p)
            self.assertEqual(D.read(Path(folder)/'current_pool.json'),p)
        self.assertTrue(W.strength(m,{},p,'2026-10-15',end)['verified'])
        self.assertEqual(m['quote_at'],str(n))
        self.assertFalse(W.strength(m,{},p,'2026-10-15',n+timedelta(minutes=3))['verified'])
    def test_fetched_wrong_date_is_explained_and_cannot_replace_current_pool(self):
        m,p,n=self.fixture();p['provider_market_date']=20261014
        with TemporaryDirectory() as folder,patch.object(D,'root',return_value=Path(folder)), \
             patch.object(D,'fetch_pool',return_value=p),patch.object(W,'datetime',wraps=datetime) as clock:
            clock.now.return_value=n
            loaded=W.load_current('2026-10-15',n,False)
            self.assertIn('响应日期',loaded['fetch_error'])
            self.assertFalse(W.strength(m,{},loaded,'2026-10-15',n)['verified'])
            self.assertFalse((Path(folder)/'current_pool.json').exists())
    def test_pipeline_uses_frozen_same_batch_pool_after_slow_model_work(self):
        f=sample();s,q,_,_,_,now,evidence=f
        p=dict(day=now.date().isoformat(),provider_market_date=int(now.strftime('%Y%m%d')),
               fetched_at=str(now),entries={c:dict(price=v['limit_up'],first_seal=93000,
                   last_seal=93000,reopen_count=0,seal_amount_yuan=10000,amount_yuan=100000) for c,v in q.items()})
        s['emotion_pool_capture']=p;evidence['current_pool']={}
        with patch.object(W,'load_current',side_effect=AssertionError('late pool request')):
            models=run(f)
        cap=[m for m in models.values() if m['sealed']]
        self.assertTrue(cap);self.assertTrue(all(m['cap_strength']['verified'] for m in cap))
        self.assertEqual(s['emotion_relay']['pools']['strength_coverage'],len(cap))
    def test_stale_wrong_date_future_and_price_conflict_do_not_supply_strength(self):
        for change in ('stale','day','future','price','quote_gap','time','nan'):
            m,p,n=self.fixture()
            if change=='stale':p['fetched_at']=str(n-timedelta(minutes=3))
            if change=='day':p['provider_market_date']=20261014
            if change=='future':p['fetched_at']=str(n+timedelta(minutes=2))
            if change=='price':p['entries'][m['code']]['price']=10.99
            if change=='quote_gap':m['quote_at']=str(n-timedelta(minutes=3))
            if change=='time':p['entries'][m['code']]['last_seal']=120000
            if change=='nan':p['entries'][m['code']]['reopen_count']=float('nan')
            self.assertFalse(W.strength(m,{},p,'2026-10-15',n)['verified'],change)
    def test_formal_close_requires_same_day_postclose_pool_not_intraday_stat(self):
        m,p,n=self.fixture();m['mode']='正式收盘';n=n.replace(hour=16)
        self.assertFalse(W.strength(m,{},p,'2026-10-15',n)['verified'])
        p['fetched_at']=str(n.replace(hour=15));self.assertTrue(W.strength(m,{},p,'2026-10-15',n)['verified'])
    def test_board_height_precedes_quality_missing_is_not_zero_opens(self):
        m,p,n=self.fixture();m['cap_strength']=W.strength(m,{},p,'2026-10-15',n)
        a=copy.deepcopy(m);a.update(code='600002',height=3)
        b=copy.deepcopy(m);b.update(code='600003');b['cap_strength']['reopen_count']=0;b['cap_strength']['seal_to_amount_pct']=1
        c=copy.deepcopy(m);c.update(code='600004');c['cap_strength']['verified']=False;c['cap_strength']['reopen_count']=None
        d=copy.deepcopy(m);d.update(code='600005',height_exact=False,height=10)
        self.assertEqual([v['code'] for v in sorted([m,c,a,d,b],key=W.cap_key)],['600002','600003','600001','600004','600005'])
    def test_ratio_and_final_seal_break_ties_without_amount_size_bias(self):
        m,p,n=self.fixture();m['cap_strength']=W.strength(m,{},p,'2026-10-15',n)
        b=copy.deepcopy(m);b['code']='600002';b['cap_strength'].update(seal_to_amount_pct=30,seal_amount_yuan=100)
        c=copy.deepcopy(b);c['code']='600003';c['cap_strength']['last_seal']='09:45:00'
        self.assertEqual([v['code'] for v in sorted([m,b,c],key=W.cap_key)],['600003','600002','600001'])
    def test_vendor_parser_preserves_actual_fields_without_using_vendor_height(self):
        value=dict(rc=0,data=dict(tc=1,qdate=20261015,pool=[dict(c='600001',p=11000,n='样例',lbc=99,fbt=92500,lbt=92500,zbc=0,fund=1000,amount=5000)]))
        with patch.object(D.D,'em_get',return_value=json.dumps(value)):
            e=D.fetch_pool('2026-10-15')['entries']['600001']
        self.assertEqual(e['seal_amount_yuan'],1000);self.assertEqual(e['reopen_count'],0);self.assertEqual(e['first_seal'],92500)
    def test_promotion_ids_equal_numerator_and_have_exact_prior_height(self):
        f=sample();models=run(f)
        for p in f[0]['emotion_relay']['promotion']:
            self.assertEqual(len(p['success_codes']),p['sealed'])
            self.assertTrue(all(models[c]['prior_exact'] and models[c]['prior_height']==p['height'] and models[c]['sealed'] for c in p['success_codes']))

class BrokenWatch(unittest.TestCase):
    def fixture(self):
        c='600001';dates=['2026-10-09','2026-10-12','2026-10-13','2026-10-14'];day='2026-10-15';now=datetime(2026,10,15,14,30)
        path=[dict(date=d,sealed=i<3,height=i+1 if i<3 else 0,exact=True,halted=False) for i,d in enumerate(dates)]
        m=dict(code=c,valid=True,mode='盘中暂态',quote_at=str(now),height=0,height_exact=True,sealed=False,suspended_current=False,roles=[],eligible=False,feedback_pct=-10.,price=8.1)
        q=dict(price=8.1,last_close=9,open=9,low=8.1,high=9)
        raw=dict(bars=[dict(date=dates[2],close=10),dict(date=dates[3],open=10,high=10.2,low=9,close=9)])
        e=dict(raw={c:raw},current_pool={});return c,{c:m},{c:path},{c:q},e,dates,day,now
    def invoke(self,f):
        c,m,p,q,e,d,day,n=f
        return W.attach({c:{}},m,p,q,e,d,day,n,fetch=False)
    def test_second_day_break_tracks_true_limit_down_and_event_prices(self):
        f=self.fixture();result=self.invoke(f);b=f[1][f[0]]['break_watch']
        self.assertEqual(result['broken'],[f[0]]);self.assertEqual(b['height'],3);self.assertEqual(b['date'],'2026-10-14')
        self.assertIn('跌停负反馈',b['labels']);self.assertIn('跌破断板日低点',b['labels']);self.assertEqual(b['since_break_pct'],-10.)
        self.assertEqual(b['from_last_seal_pct'],-19);self.assertTrue(b['was_market_highest'])
    def test_weak_repair_requires_all_observed_conditions(self):
        f=self.fixture();m=f[1][f[0]];q=f[3][f[0]];m.update(price=9.4,feedback_pct=4.44);q.update(price=9.4,open=8.8,low=8.8,high=9.45)
        self.invoke(f);self.assertIn('弱后转强观察',m['break_watch']['labels'])
        q['open']=9.3;self.invoke(f);self.assertNotIn('弱后转强观察',m['break_watch']['labels']);self.assertIn('反弹观察',m['break_watch']['labels'])
    def test_two_boards_not_admitted_and_return_to_board_is_positive_feedback(self):
        f=self.fixture();f[2][f[0]][2]['height']=2;self.assertEqual(self.invoke(f)['broken'],[])
        f=self.fixture();f[1][f[0]].update(sealed=True,price=9.9,height=1,feedback_pct=10);f[3][f[0]]['price']=9.9
        self.assertEqual(self.invoke(f)['broken'],[f[0]]);self.assertIn('断板后再封板',f[1][f[0]]['break_watch']['labels'])
    def test_unknown_and_halt_never_become_false_breaks(self):
        f=self.fixture();path=f[2][f[0]]
        path[-1].update(sealed=None,halted=True);self.assertIsNone(W.break_event(path))
        path[-1].update(sealed=None,halted=False);self.assertIsNone(W.break_event(path))
        path.append(dict(date='2026-10-15',sealed=False,exact=True));self.assertIsNone(W.break_event(path))
    def test_halt_preserves_height_before_actual_break(self):
        f=self.fixture();p=f[2][f[0]];p.insert(3,dict(date='2026-10-13a',halted=True,sealed=None));self.assertEqual(W.break_event(p)['height'],3)
    def test_latest_new_chain_replaces_older_break(self):
        f=self.fixture();p=f[2][f[0]]
        p.extend([dict(date='a',sealed=True,exact=True,height=1),dict(date='b',sealed=True,exact=True,height=2),dict(date='c',sealed=False,exact=True,height=0)])
        self.assertEqual(W.break_event(p)['date'],'2026-10-14')
        p[-2]['height']=3;self.assertEqual(W.break_event(p)['date'],'c')
        self.assertIsNone(W.break_event(p[:-1]))
    def test_pending_quote_not_presented_as_valid_feedback(self):
        f=self.fixture();f[1][f[0]]['valid']=False;r=self.invoke(f)
        self.assertEqual(r['broken'],[]);self.assertEqual(r['broken_pending'],[f[0]])
    def test_intraday_unsealed_is_provisional_not_formal_break(self):
        f=self.fixture();f[2][f[0]][-1].update(sealed=True,height=4);r=self.invoke(f)
        b=f[1][f[0]]['break_watch'];self.assertTrue(b['pending']);self.assertEqual(b['date'],'2026-10-15');self.assertEqual(b['height'],4)
    def test_first_valid_resume_quote_can_have_provisional_divergence_after_known_halt(self):
        f=self.fixture();f[2][f[0]][-1].update(sealed=None,halted=True,height=3)
        self.invoke(f);b=f[1][f[0]]['break_watch']
        self.assertTrue(b['pending']);self.assertEqual(b['date'],'2026-10-15');self.assertEqual(b['height'],3)

if __name__=='__main__':unittest.main()
