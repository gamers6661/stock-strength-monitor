"""收盘更新调度、正式日线隔离以及发布后资金补采的回归。"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

import config
import scoring
import serve
import fund_history


def bar(day='2026-10-09'):
    return dict(date=day, open=9., close=10., high=11., low=8., volume=100.,
                amount=1000., price_basis='qfq', price_basis_source='tencent_qfqday')


class CloseRefreshTests(unittest.TestCase):
    def test_close_schedule_does_not_wait_for_five_minute_tick_or_repeat_after_done(self):
        today = datetime(2026, 10, 9, 15, 5)
        meta = dict(snapshot_daily_asof='2026-10-08')
        with patch.object(serve, 'SNAPSHOT_META', meta):
            self.assertEqual(serve.pick_mode(today.replace(minute=4)), 'quick')
            self.assertEqual(serve.pick_mode(today), 'close')
            # 日期切到今天也不够，须有正式日线校验和实际收盘主榜。
            meta['snapshot_daily_asof'] = '2026-10-09'
            self.assertFalse(serve.boundary_capture_done(today, 'close_review'))
            meta.update(snapshot_close_board_asof='2026-10-09',
                        snapshot_close_refresh_version=scoring.CLOSE_REFRESH_VERSION,
                        snapshot_close_daily_verified_at='2026-10-09 15:08:00')
            self.assertTrue(serve.boundary_capture_done(today, 'close_review'))
            self.assertEqual(serve.pick_mode(today.replace(minute=25)), 'quick')
            self.assertEqual(serve.pick_mode(datetime(2026, 10, 10, 15, 5)), 'quick')

    def test_close_boundary_runs_independently_at_1505(self):
        state = deepcopy(serve.INIT)
        now = datetime(2026, 10, 9, 15, 5, 1)
        with patch.object(serve, 'INIT', state), patch.object(serve, '_SCAN_LOCK', threading.Lock()), \
             patch.object(serve, 'datetime') as clock, \
             patch.object(serve, 'boundary_trading_evidence', return_value=True), \
             patch.object(serve, 'boundary_capture_done', return_value=False), \
             patch.object(serve.time, 'monotonic', return_value=1000), \
             patch.object(serve.time, 'sleep', side_effect=RuntimeError('stop')), \
             patch.object(serve.scoring, 'run') as scan, patch.object(serve, 'publish_outputs'):
            clock.now.return_value = now
            with self.assertRaisesRegex(RuntimeError, 'stop'):
                serve.boundary_capture_loop()
            scan.assert_called_once_with(mode='close', boundary='close')
            self.assertFalse(state['scan_active'])

    def test_close_coverage_rejects_old_missing_invalid_and_premature_daily(self):
        quotes = {str(i): dict(amount_wan=1) for i in range(10)}
        history = {str(i): [bar()] for i in range(8)}
        now = datetime(2026, 10, 9, 15, 5)
        self.assertEqual(scoring.validate_close_daily(history, quotes, now), 8)
        history['0'] = [bar('2026-10-08')]
        with self.assertRaises(scoring.DataNotReady):
            scoring.validate_close_daily(history, quotes, now)
        history['0'] = [dict(bar(), low=12)]
        with self.assertRaises(scoring.DataNotReady):
            scoring.validate_close_daily(history, quotes, now)
        with self.assertRaises(scoring.DataNotReady):
            scoring.validate_close_daily({str(i): [bar()] for i in range(10)}, quotes, now.replace(minute=4))

    def test_close_quotes_neither_replace_qfq_daily_nor_synthesize_missing_daily(self):
        with TemporaryDirectory() as root, patch.object(config, 'CACHE_DIR', Path(root)), \
             patch.dict(config.KLINE, {'days': 1}), patch.object(scoring, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 9, 15, 6)
            conn = sqlite3.connect(':memory:')
            conn.execute('CREATE TABLE kline(code TEXT,date TEXT,open REAL,close REAL,high REAL,low REAL,volume REAL,amount REAL,price_basis TEXT,price_basis_source TEXT,PRIMARY KEY(code,date))')
            scoring.df.save_klines(conn, 'kline', 'code', {'600000': [bar()], '600001': [bar('2026-10-08')]})
            quotes = {c: dict(price=99, open=98, high=100, low=97, volume_shou=8,
                             ts='2026-10-09 15:00:01', price_basis='raw') for c in ('600000', '600001')}
            with patch.object(scoring.df, 'fetch_klines_bulk') as fetch:
                out = scoring.load_klines(conn, list(quotes), quotes, progress=False)
            fetch.assert_not_called()
            self.assertEqual(out['600000'][-1]['close'], 10)
            self.assertEqual(out['600000'][-1]['price_basis'], 'qfq')
            self.assertEqual(out['600001'][-1]['date'], '2026-10-08')
            conn.close()

    def test_fund_cache_read_does_not_fetch_or_claim_outdated_rows_complete(self):
        dates = ['2026-10-%02d' % i for i in range(1, 21)]
        cache = {'a': dict(rows=[dict(date=d, main_net=1) for d in dates[:-1]])}
        with patch.object(fund_history, 'load', return_value=cache), \
             patch.object(fund_history.datafeed, 'fetch_sina_fundflow') as fetch:
            result = fund_history.cached_status(['a'], dates)
        fetch.assert_not_called()
        self.assertEqual(result['complete20'], 0)
        self.assertTrue(result['deferred'])

    def test_auxiliary_worker_starts_only_after_verified_close_and_once_per_day(self):
        now = datetime(2026, 10, 9, 15, 9)
        snapshot = dict(session='已收盘', strength_model=dict(asof='2026-10-09'), stocks=[])
        with patch.object(serve, '_CLOSE_FUNDS_DAYS', set()), \
             patch.object(serve, 'datetime') as clock, patch.object(serve.threading, 'Thread') as thread:
            clock.now.return_value = now
            serve.start_close_fund_refresh(snapshot)
            thread.assert_not_called()
            snapshot['close_daily_verified_at'] = '2026-10-09 15:08:30'
            serve.start_close_fund_refresh(snapshot)
            serve.start_close_fund_refresh(snapshot)
            self.assertEqual(thread.call_count, 1)
            thread.return_value.start.assert_called_once()


if __name__ == '__main__':
    unittest.main()
