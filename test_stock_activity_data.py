"""Sampling must stay independent of slow scans, using real source times."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch

import config
import stock_activity as A
import stock_activity_sampler as S
from test_stock_activity import sample,calculate


class DataPath(unittest.TestCase):
    def test_closing_projection_recovers_real_source_metadata_without_changing_shared_rows(self):
        f=sample();s=copy.deepcopy(f[0]);s.update(quote_capture_at='2026-10-13 15:06:00',session='已收盘',close_daily_verified_at='2026-10-13 15:08:00')
        quotes={r['code']:dict(r,quote_at='2026-10-13 15:00:00') for r in s['stocks']}
        for r in s['stocks']:
            r['quote_at']='2026-10-13 15:06:00'
            for k in ('price_basis','price_basis_source','last_close_semantics'):r.pop(k)
        saved=copy.deepcopy(s)
        record=dict(captured_at='2026-10-13 15:00:10',session='已收盘',quotes=quotes)
        own=A.live_view(s,now=A.stamp('2026-10-13 16:00:00'),record=record)
        self.assertEqual(own['stock_activity_quote_mode'],'收盘采样参考')
        self.assertEqual(own['stocks'][0]['quote_at'],'2026-10-13 15:00:00')
        self.assertEqual(own['stocks'][0]['received_at'],'2026-10-13 15:00:10')
        self.assertEqual(s,saved)
        for q in quotes.values():q['price']+=1
        self.assertIs(A.live_view(s,now=A.stamp('2026-10-13 16:00:00'),record=record),s)

    def test_slow_full_scan_gap_needs_actual_intermediate_samples(self):
        f=sample(prices=[100,100,100,101.2])
        complete=copy.deepcopy(f)
        f[3][2][1].clear()
        self.assertIsNone(calculate(f)['items']['600000']['event'])
        self.assertEqual(calculate(complete)['items']['600000']['list_name'],'startup')
        self.assertEqual(A.RULES['gap_max'],180)

    def test_capture_normalizes_supplier_time_and_writes_only_own_archive(self):
        f=sample();now=A.stamp(f[0]['quote_capture_at'])
        quotes={r['code']:dict(r,ts=now.strftime('%Y%m%d%H%M%S')) for r in f[0]['stocks']}
        for q in quotes.values():q.pop('quote_at')
        with tempfile.TemporaryDirectory() as d,patch.object(config,'CACHE_DIR',Path(d)),patch.object(config,'POOL_CACHE',Path(d)/'pool.json'),patch.object(config,'SNAPSHOT_JSON',Path(d)/'snapshot.json'),patch.object(S.datafeed,'tencent_quotes',return_value=quotes) as fetch,patch.object(S.datafeed,'realtime_quotes') as fallback,patch.object(S,'datetime') as clock:
            config.POOL_CACHE.write_text(json.dumps({c:{} for c in quotes}),encoding='utf8')
            clock.now.return_value=now
            status=S.capture_once()
            self.assertEqual(status['valid'],12)
            self.assertEqual(fetch.call_count,1);fallback.assert_not_called()
            latest=json.loads((S.directory()/'latest.json').read_text(encoding='utf8'))
            self.assertEqual(latest['quotes']['600000']['quote_at'],str(now))
            self.assertTrue((S.directory()/'acquisitions'/'2026-10-13.jsonl.gz').exists())

    def test_live_projection_uses_fresh_quotes_without_mutating_shared_input(self):
        f=sample();s=f[0];saved=copy.deepcopy(s);now=A.stamp(s['quote_capture_at'])+timedelta(minutes=1)
        quotes={r['code']:dict(r,price=109,high=109,change_pct=9,quote_at=str(now)) for r in s['stocks']}
        with tempfile.TemporaryDirectory() as d,patch.object(config,'CACHE_DIR',Path(d)):
            folder=S.directory();folder.mkdir()
            (folder/'latest.json').write_text(json.dumps(dict(captured_at=str(now),session='早盘',quotes=quotes)),encoding='utf8')
            own=A.live_view(s,now=now)
            self.assertEqual(own['stocks'][0]['price'],109)
            self.assertEqual(s,saved)
            self.assertEqual(own['quote_capture_at'],str(now))
            self.assertIs(A.live_view(s,now=now-timedelta(seconds=1)),s)
            self.assertIs(A.live_view(s,now=now+timedelta(seconds=config.INTRADAY['max_quote_age_seconds']+1)),s)

    def test_next_session_sampling_can_update_before_whole_site_scan(self):
        f=sample();s=f[0]
        s.update(session='已收盘',close_daily_verified_at='2026-10-13 15:08:00')
        now=A.stamp('2026-10-14 09:34:00')
        quotes={r['code']:dict(r,quote_at=str(now)) for r in s['stocks']}
        record=dict(captured_at=str(now),session='早盘',quotes=quotes)
        own=A.live_view(s,now=now,record=record)
        self.assertEqual(own['quote_capture_at'],str(now))
        self.assertEqual(own['session'],'早盘')
        self.assertNotIn('close_daily_verified_at',own)

    def test_sampler_session_and_single_owner(self):
        self.assertTrue(S.sampling_time(A.stamp('2026-10-13 14:00:00')))
        self.assertFalse(S.sampling_time(A.stamp('2026-10-13 12:00:00')))
        self.assertFalse(S.sampling_time(A.stamp('2026-10-13 16:00:00')))
        with tempfile.TemporaryDirectory() as d,patch.object(config,'CACHE_DIR',Path(d)):
            with S.owner() as first:
                self.assertTrue(first)
                with S.owner() as second:self.assertFalse(second)


if __name__=='__main__':unittest.main()
