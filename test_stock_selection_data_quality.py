"""补采错配、盘前日期、证券状态和同源资金的回归验收。"""
import unittest
from statistics import median
import stock_selection as S
import stock_selection_data as A
from test_stock_selection import sample,run


class DataQuality(unittest.TestCase):
    def test_compact_source_clock_is_normalized_and_not_mislabeled_previous_day(self):
        f=sample();row=f[0]['stocks'][0]
        row['quote_at']=f[-2].strftime('%Y%m%d%H%M%S')
        m=run(f)['items'][f[-1][0]]
        self.assertEqual(m['quote']['at'],str(f[-2]))
        self.assertTrue(m['intraday']['available'])

    def test_independent_sampler_reports_v3_source_age_without_legacy_stamp(self):
        from datetime import datetime
        from pathlib import Path
        from unittest.mock import patch,Mock
        import stock_activity_sampler as sampler
        at=datetime(2026,10,21,10)
        pool=Mock();pool.read_text.return_value='{"600000":{}}'
        snapshot=Mock();snapshot.exists.return_value=True
        quote=dict(price=10.,amount_wan=100.,quote_at='2026-10-21 10:00:00')
        model=dict(result_version='verified',source_at='2026-10-21 09:59:59')
        with patch.object(sampler,'datetime') as clock,patch.object(sampler.config,'POOL_CACHE',pool),patch.object(sampler.config,'SNAPSHOT_JSON',snapshot),patch.object(sampler.config,'atomic_write_text'),patch.object(sampler,'directory',return_value=Path('D:/Temp/stock-monitor/sampler-fixture')),patch.object(sampler.datafeed,'tencent_quotes',return_value={'600000':quote}),patch.object(sampler.intraday_path,'save_acquisition'),patch.object(S,'refresh_projection',return_value=model):
            clock.now.return_value=at
            result=sampler.capture_once()
        self.assertNotIn('projection_error',result)
        self.assertEqual(result['result_version'],'verified')
        self.assertEqual(result['quote_age_at_publication_seconds'],1.)

    def test_amount_response_from_another_stock_is_rejected(self):
        with self.assertRaises(ValueError):
            A.validate_response_identity(dict(code='sz.002719',date='2026-10-20'),'002718','2026-09-01','2026-10-20')
        with self.assertRaises(ValueError):
            A.validate_response_identity(dict(code='sz.002718',date='2026-10-21'),'002718','2026-09-01','2026-10-20')
        A.validate_response_identity(dict(code='sz.002718',date='2026-10-20'),'002718','2026-09-01','2026-10-20')

    def test_premarket_old_quote_date_does_not_drop_latest_completed_day(self):
        f=sample();f[0].update(session='盘前',quote_capture_at=f[2][-1]+' 16:10:00')
        m=run(f)
        self.assertEqual(m['daily_at'],f[2][-1])
        self.assertEqual(m['day'],str(f[-2].date()))

    def test_delisting_uses_effective_date_not_current_status_in_historical_day(self):
        f=sample();snap=f[0];codes=f[-1]
        snap['_security_master']={c:dict(ipoDate='2000-01-01',outDate='',status='1') for c in codes}
        snap['_security_master'][codes[0]].update(outDate='2026-10-14',status='0')
        snap['_universe_at']='2026-10-13';self.assertIn(codes[0],S.unique_rows(snap))
        snap['_universe_at']='2026-10-14';self.assertNotIn(codes[0],S.unique_rows(snap))
        snap['_security_master'].pop(codes[1]);self.assertNotIn(codes[1],S.unique_rows(snap))

    def test_fund_summary_never_leaks_future_or_invents_missing_value(self):
        f=sample();cal=f[2];day=cal[-2]
        record=dict(source='新浪超大单+大单日级净额',rows=[dict(date=d,main_net=10.) for d in cal[-11:]])
        record['rows'][-1]['main_net']=999999.
        r=S.fund_summary(record,cal,day)
        self.assertTrue(r['available']);self.assertEqual(r['net5'],50.)
        self.assertEqual(r['net10'],100.);self.assertEqual(r['main_net'],10.)
        record['rows']=[x for x in record['rows'] if x['date']!=day]
        r=S.fund_summary(record,cal,day)
        self.assertFalse(r['available']);self.assertIsNone(r['main_net']);self.assertIsNone(r['net5'])
        record['source']='unknown';self.assertFalse(S.fund_summary(record,cal,cal[-1])['available'])

    def test_cached_sector_reference_excludes_self_and_top_two(self):
        f=sample();clean=f[1];codes=f[-1];metrics={c:S.base_metrics(clean[c],f[3][c]) for c in codes}
        for i,c in enumerate(codes):metrics[c]['returns']['5']=float(i)
        groups={'i':codes};assigned={c:'i' for c in codes};cache={}
        for c in codes:
            r=S.board_support(c,metrics,clean,groups,assigned,{'i':'行业'},cache)
            peers=sorted(metrics[z]['returns']['5'] for z in codes if z!=c)
            self.assertEqual(r['median5'],median(peers))
            self.assertEqual(r['ex_top2_median5'],median(peers[:-2]))


if __name__=='__main__':unittest.main()
