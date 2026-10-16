"""开盘输入衔接、收盘源时间与定点失败状态回归。"""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

import config
import scoring
import serve


class ProbeReached(RuntimeError):
    pass


class StopLoop(RuntimeError):
    pass


def quotes(at, count=200):
    return {str(600000 + i): dict(name='测试股', price=10, low=9, high=11, change_pct=1,
                                amount_wan=100, volume_shou=100, quote_at=at,
                                ts=at, board_type='sh_main') for i in range(count)}


class RefreshBoundaryTests(unittest.TestCase):
    def test_lunch_refresh_timestamp_cannot_pass_afternoon_open(self):
        with self.assertRaisesRegex(scoring.DataNotReady, '13:00 开盘后报价尚未更新'):
            scoring.opening_quotes_ready(quotes('2026-10-08 12:59:40'),
                                         datetime(2026, 10, 8, 13, 0, 20), '午盘', 200)

    def test_afternoon_majority_preserves_existing_coverage_threshold(self):
        rows = quotes('2026-10-08 12:59:40')
        for code in list(rows)[:120]:
            rows[code]['quote_at'] = '2026-10-08 13:01:00'
        self.assertEqual(scoring.opening_quotes_ready(rows, datetime(2026, 10, 8, 13, 2), '午盘', 200), 120)
        rows[next(iter(rows))]['quote_at'] = '2026-10-08 12:59:40'
        with self.assertRaises(scoring.DataNotReady):
            scoring.opening_quotes_ready(rows, datetime(2026, 10, 8, 13, 2), '午盘', 200)

    def test_auction_timestamp_cannot_pass_continuous_morning(self):
        with self.assertRaises(scoring.DataNotReady):
            scoring.opening_quotes_ready(quotes('2026-10-08 09:29:50'),
                                         datetime(2026, 10, 8, 9, 30, 20), '早盘', 200)
        self.assertEqual(scoring.opening_quotes_ready(quotes('2026-10-08 09:30:05'),
                         datetime(2026, 10, 8, 9, 30, 20), '早盘', 200), 200)

    def test_old_missing_future_and_expired_quotes_stay_rejected(self):
        for at in ('2026-10-07 13:01:00', '', '2026-10-08 13:20:00', '2026-10-08 13:00:00'):
            with self.subTest(at=at), self.assertRaises(scoring.DataNotReady):
                scoring.opening_quotes_ready(quotes(at), datetime(2026, 10, 8, 13, 12), '午盘', 200)

    def probe_run(self, at, captured, session, boundary):
        rows = quotes(at)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'snapshot.json'
            path.write_text(json.dumps({'stocks': [{}] * 200}), encoding='utf-8')
            with patch.object(config, 'SNAPSHOT_JSON', path), \
                 patch.object(scoring, 'datetime') as clock, \
                 patch.object(scoring.df, 'session_label', return_value=session), \
                 patch.object(scoring.df, 'build_pool', return_value=deepcopy(rows)), \
                 patch.object(scoring.df, 'realtime_quotes', return_value=deepcopy(rows)), \
                 patch.object(scoring.intraday.intraday_path, 'save_acquisition'), \
                 patch('relay_pools.load_current', return_value={}) as cap_pool, \
                 patch.object(scoring.df, 'fetch_outer_resilient', side_effect=ProbeReached) as outer:
                clock.now.return_value = captured
                clock.fromisoformat.side_effect = datetime.fromisoformat
                try:
                    scoring.run(boundary=boundary, progress=False)
                except (scoring.DataNotReady, ProbeReached) as error:
                    if isinstance(error,scoring.DataNotReady):cap_pool.assert_not_called()
                    return error, outer.called
        self.fail('运行没有停在预期节点')

    def test_pre_open_batch_stops_before_auxiliary_requests(self):
        error, reached = self.probe_run('2026-10-08 12:59:40', datetime(2026, 10, 8, 13, 0, 20), '午盘', 'afternoon_open')
        self.assertIsInstance(error, scoring.DataNotReady)
        self.assertFalse(reached)

    def test_post_market_source_timestamp_can_capture_close(self):
        error, reached = self.probe_run('2026-10-08 16:14:45', datetime(2026, 10, 8, 17, 15), '已收盘', 'close')
        self.assertIsInstance(error, ProbeReached)
        self.assertTrue(reached)

    def test_close_rejects_previous_date_and_future_source(self):
        for at in ('2026-10-07 16:14:45', '2026-10-08 17:20:00', '2026-10-08 14:59:59'):
            error, reached = self.probe_run(at, datetime(2026, 10, 8, 17, 15), '已收盘', 'close')
            self.assertIsInstance(error, scoring.DataNotReady)
            self.assertFalse(reached)

    def test_midday_still_rejects_afternoon_source(self):
        error, reached = self.probe_run('2026-10-08 13:01:00', datetime(2026, 10, 8, 13, 2), '午间休市', 'midday')
        self.assertIsInstance(error, scoring.DataNotReady)
        self.assertFalse(reached)

    def test_boundary_failure_does_not_claim_previous_success(self):
        now = datetime(2026, 10, 8, 13, 0, 2)
        state = deepcopy(serve.INIT)
        state['last_scan_ok'] = True
        with patch.object(serve, 'INIT', state), \
             patch.object(serve, '_SCAN_LOCK', threading.Lock()), \
             patch.object(serve, 'datetime') as clock, \
             patch.object(serve, 'boundary_trading_evidence', return_value=True), \
             patch.object(serve, 'boundary_capture_done', return_value=False), \
             patch.object(serve.time, 'monotonic', return_value=1000), \
             patch.object(serve.time, 'sleep', side_effect=StopLoop), \
             patch.object(serve.scoring, 'run', side_effect=scoring.DataNotReady('13:00 开盘后报价尚未更新')):
            clock.now.return_value = now
            with self.assertRaises(StopLoop):
                serve.boundary_capture_loop()
        self.assertFalse(state['last_scan_ok'])
        self.assertFalse(state['scan_active'])
        self.assertIn('尚未更新', state['last_scan_error'])


if __name__ == '__main__':
    unittest.main()
