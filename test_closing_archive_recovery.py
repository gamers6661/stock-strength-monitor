import gzip,json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
import config,market_strength as M,intraday_path
import ma_trend as T
from test_market_strength import fixture

class ClosingArchiveRecovery(unittest.TestCase):
    def fixture(self):
        f=fixture(8);s,quotes,p,h,cal,now=f;now=now.replace(hour=15,minute=30);day=now.date().isoformat()
        for q in quotes.values():q.update(quote_at=day+' 15:00:00',ts=day+' 15:00:00')
        s.update(session='已收盘',quote_capture_at=str(now),close_daily_verified_at=str(now-timedelta(minutes=1)))
        return s,quotes,p,h,cal,now
    def test_restart_recovers_same_day_raw_close_clock_without_previous_model(self):
        s,q,p,h,c,n=self.fixture()
        with tempfile.TemporaryDirectory() as d,patch.object(config,'CACHE_DIR',Path(d)):
            intraday_path.save_acquisition(Path(d)/'intraday_history',q,n.replace(minute=0,second=17),'尾盘','close')
            raw=json.loads(json.dumps(q));bad={code:dict(v,quote_at=str(n),ts=str(n)) for code,v in q.items()}
            M.attach(s,bad,p,h,c,now=n,previous={})
            self.assertTrue(s['market_strength_close_input']['quotes'])
            for row in s['stocks']:
                self.assertEqual(row['market_strength']['quote_at'],n.date().isoformat()+' 15:00:00')
                self.assertEqual(row['price'],raw[row['code']]['price'])
            self.assertEqual(s['market_strength_close_reference']['archive_captured_at'],str(n.replace(minute=0,second=17)))
    def test_after_close_supplier_timestamp_is_never_rewritten_to_fifteen(self):
        s,q,p,h,c,n=self.fixture()
        with tempfile.TemporaryDirectory() as d,patch.object(config,'CACHE_DIR',Path(d)):
            bad={code:dict(v,quote_at=str(n),ts=str(n)) for code,v in q.items()}
            intraday_path.save_acquisition(Path(d)/'intraday_history',bad,n,'已收盘')
            self.assertIsNone(M.archived_close_input(n,p));M.attach(s,bad,p,h,c,now=n,previous={})
            self.assertFalse(s.get('market_strength_close_input'));self.assertTrue(all(r['market_strength'].get('quote_at') is None for r in s['stocks']))
    def test_wrong_day_incomplete_or_future_batch_is_rejected(self):
        s,q,p,h,c,n=self.fixture()
        with tempfile.TemporaryDirectory() as d,patch.object(config,'CACHE_DIR',Path(d)):
            intraday_path.save_acquisition(Path(d)/'intraday_history',q,n+timedelta(minutes=1),'已收盘')
            self.assertIsNone(M.archived_close_input(n,p))
            intraday_path.save_acquisition(Path(d)/'intraday_history',dict(list(q.items())[:2]),n,'已收盘')
            self.assertIsNone(M.archived_close_input(n,p))
            intraday_path.save_acquisition(Path(d)/'intraday_history',q,n-timedelta(days=1),'已收盘')
            self.assertIsNone(M.archived_close_input(n,p))

    def test_invalid_supplier_clock_cannot_shift_ma_closing_batch_center(self):
        s,q,p,h,c,n=self.fixture();day=n.date().isoformat()
        for code,bars in h.items():bars.append(dict(bars[-1],date=day,close=q[code]['price'],high=max(bars[-1]['high'],q[code]['price'])))
        c.append(day)
        with tempfile.TemporaryDirectory() as d,patch.object(config,'CACHE_DIR',Path(d)):
            intraday_path.save_acquisition(Path(d)/'intraday_history',q,n.replace(minute=0,second=17),'尾盘','close')
            bad={code:dict(v,quote_at=str(n),ts=str(n)) for code,v in q.items()}
            M.attach(s,bad,p,h,c,now=n,previous={})
            # Include a rejected supplier quote alongside the canonical raw batch.
            first=s['stocks'][0];first['market_strength']['price_context']={'valid':False}
            T.attach(s,bad,p,h,c,now=n,minute_data={},fetch_minutes=False)
            for row in s['stocks'][1:]:self.assertEqual(row['ma_trend']['quote_at'],day+' 15:00:00')

if __name__=='__main__':unittest.main()
