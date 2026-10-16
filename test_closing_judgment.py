"""Regression for verified post-close source clocks and final MA decisions."""
import copy,unittest,tempfile
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
import config,closing_price as C,market_strength as M,ma_trend as T
from test_market_strength import fixture
from test_ma_trend import sample

def close_fixture(kind=None):
    s,q,p,h,cal,now=sample(kind) if kind else fixture(8)
    now=now.replace(hour=16,minute=30);day=now.date().isoformat();s.update(session='已收盘',close_daily_verified_at=day+' 15:08:10',quote_capture_at=str(now))
    for c,v in q.items():
        v['quote_at']=day+' 16:14:45'
        h[c].append(dict(h[c][-1],date=day,open=v['open'],high=v['high'],low=v['low'],close=v['price'],volume=120.))
    cal.append(day)
    return s,q,p,h,cal,now

class ClosingJudgment(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.patch=patch.object(config,'CACHE_DIR',Path(self.temp.name));self.patch.start()
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def test_verified_final_ohlc_restores_market_axes_and_preserves_raw_inputs(self):
        s,q,p,h,cal,n=close_fixture();before=copy.deepcopy((q,h,cal));M.attach(s,q,p,h,cal,now=n)
        self.assertEqual((q,h,cal),before);self.assertEqual(s['market_strength']['coverage']['trend_valid'],8)
        self.assertEqual(s['market_strength']['coverage']['emotion_valid'],8)
        self.assertEqual(s['market_strength']['close_verification']['verified'],8)
        self.assertEqual(len(s['market_strength_close_input']['quotes']),8)
        for row in s['stocks']:
            self.assertEqual(row['market_strength']['quote_at'],q[row['code']]['quote_at'])
            self.assertEqual(row['market_strength']['completed_daily_proof']['date'],n.date().isoformat())
        M.validate(s)
    def test_native_match_needed_even_with_global_verified_flag(self):
        for fault in ('missing','open','high','low','close','source','scale','duplicate','previous_close','quote_source','semantics','future','wrong_day','verification','early','volume'):
            s,q,p,h,cal,n=close_fixture();c=next(iter(q));quote=q[c];bars=h[c]
            if fault=='missing':bars.pop()
            elif fault in ('open','high','low','close'):bars[-1][fault]+=.02
            elif fault=='source':bars[-1]['price_basis_source']='unknown'
            elif fault=='scale':bars[-1].update(price_basis='qfq',price_basis_source='tencent_qfqday')
            elif fault=='duplicate':bars.append(copy.deepcopy(bars[-1]))
            elif fault=='previous_close':quote['last_close']=80.
            elif fault=='quote_source':quote['price_basis_source']='unknown'
            elif fault=='semantics':quote['last_close_semantics']='unknown'
            elif fault=='future':quote['quote_at']=str(n+timedelta(minutes=5))
            elif fault=='wrong_day':quote['quote_at']=str(n-timedelta(days=1))
            elif fault=='verification':s['close_daily_verified_at']=str(n-timedelta(days=1))
            elif fault=='early':s['close_daily_verified_at']=str(n.replace(hour=15,minute=4))
            elif fault=='volume':quote['amount_wan']=quote['volume_shou']=0
            self.assertIsNone(C.verify(s,quote,bars,cal,n),fault)
    def test_postclose_approval_does_not_relax_intraday_or_unproved_time(self):
        s,q,p,h,cal,n=close_fixture();c=next(iter(q));v=q[c];proof=C.verify(s,v,h[c],cal,n)
        self.assertFalse(M.quote_valid(v,n,'已收盘',None,True)[0])
        self.assertTrue(M.quote_valid(v,n,'已收盘',None,True,proof)[0])
        self.assertFalse(M.quote_valid(v,n,'尾盘',None,True,proof)[0])
        changed=dict(v,price=v['price']+.01);self.assertFalse(M.quote_valid(changed,n,'已收盘',None,True,proof)[0])
        stale=dict(v,quote_at=str(n-timedelta(minutes=20)));self.assertFalse(M.quote_valid(stale,n,'午盘',None)[0])
    def test_one_missing_close_does_not_zero_other_verified_rows(self):
        s,q,p,h,cal,n=close_fixture();c=next(iter(q));h[c].pop();M.attach(s,q,p,h,cal,now=n)
        self.assertEqual(s['market_strength']['coverage']['trend_valid'],7)
        self.assertEqual(s['market_strength']['close_verification']['verified'],7)
    def test_acquisition_before_daily_verification_uses_actual_completed_assessment(self):
        s,q,p,h,cal,n=close_fixture();n=n.replace(hour=15,minute=5)
        for v in q.values():v['quote_at']=str(n)
        s['close_daily_verified_at']=str(n+timedelta(minutes=3))
        M.attach(s,q,p,h,cal,now=n);T.attach(s,q,p,h,cal,now=n,minute_data={},fetch_minutes=False)
        self.assertEqual(s['market_strength']['coverage']['trend_valid'],8)
        self.assertEqual(s['market_strength']['at'],s['close_daily_verified_at'])
        self.assertTrue(all(r['ma_trend']['quote_at']==str(n) for r in s['stocks']))
    def test_saved_final_batch_is_reverified_when_new_source_quote_is_unusable(self):
        s,q,p,h,cal,n=close_fixture();M.attach(s,q,p,h,cal,now=n);previous=copy.deepcopy(s)
        bad={c:dict(v,quote_at=str(n+timedelta(minutes=30))) for c,v in q.items()}
        M.attach(s,bad,p,h,cal,now=n,previous=previous)
        self.assertEqual(s['market_strength']['coverage']['trend_valid'],8)
        self.assertTrue(s.get('market_strength_close_reference'))
        self.assertEqual(s['market_strength_close_input']['quotes'][next(iter(q))]['quote_at'],next(iter(q.values()))['quote_at'])
    def test_archived_late_source_recovers_on_restart_only_with_native_ohlc(self):
        import intraday_path
        s,q,p,h,cal,n=close_fixture()
        intraday_path.save_acquisition(config.CACHE_DIR/'intraday_history',q,n-timedelta(minutes=1),'已收盘')
        bad={c:dict(v,quote_at=str(n+timedelta(minutes=30))) for c,v in q.items()}
        M.attach(s,bad,p,h,cal,now=n,previous={})
        self.assertEqual(s['market_strength']['coverage']['trend_valid'],8)
        self.assertEqual(s['market_strength_close_reference']['source_at'],next(iter(q.values()))['quote_at'])
    def test_final_ma_close_does_not_require_missing_minute_path(self):
        s,q,p,h,cal,n=close_fixture('retained');c=next(iter(q));q[c]['low']=100.;h[c][-1]['low']=100.
        M.attach(s,q,p,h,cal,now=n)
        with patch('close_monitor._get_minutes',side_effect=AssertionError('Final close must not fetch minute path')):
            T.attach(s,q,p,h,cal,now=n,minute_data={},fetch_minutes=True)
        m=s['stocks'][0]['ma_trend'];self.assertFalse(m['pending']);self.assertTrue(m['eligible']);self.assertNotIn('minute_needed',m)
        self.assertEqual(m['quote_at'],q[c]['quote_at']);self.assertEqual(m['decision_at'],n.date().isoformat()+' 15:00:00');T.validate(s)
    def test_final_close_replays_daily_instead_of_retaining_an_intraday_exit(self):
        s,q,p,h,cal,n=close_fixture('retained');M.attach(s,q,p,h,cal,now=n);T.attach(s,q,p,h,cal,now=n,minute_data={},fetch_minutes=False)
        previous=copy.deepcopy(s);m=previous['stocks'][0]['ma_trend'];m.update(status='已退出',exit_at=n.date().isoformat()+' 10:00:00',tracking=dict(exit_at=n.date().isoformat()+' 10:00:00',exit_reason='盘中失守'))
        T.attach(s,q,p,h,cal,now=n,previous=previous,minute_data={},fetch_minutes=False)
        self.assertTrue(s['stocks'][0]['ma_trend']['eligible']);self.assertFalse(s['stocks'][0]['ma_trend']['pending'])
    def test_native_qfq_converted_to_raw_quote_preserves_original_history(self):
        s,q,p,h,cal,n=close_fixture();c=next(iter(q));before=copy.deepcopy(h[c])
        for b in h[c]:
            b.update(price_basis='qfq',price_basis_source='tencent_qfqday')
            for k in ('open','high','low','close'):b[k]/=1.02
        proof=C.verify(s,q[c],h[c],cal,n);self.assertAlmostEqual(proof['scale_factor'],1.02)
        self.assertEqual(proof['prices']['close'],q[c]['price']);self.assertEqual(h[c][-1]['close'],before[-1]['close']/1.02)

if __name__=='__main__':unittest.main()
