"""Focused regression coverage for K-line host cooldown and close recovery."""
from datetime import date, datetime, timedelta
import json
import sqlite3
import time
import unittest
from unittest.mock import patch

import config
import datafeed as df
import history_increment
import scoring
import serve


CODE = '000001'
FIXED_CLOSE = datetime(2026, 10, 27, 15, 10)


class FrozenCloseDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 27, 15, 10, tzinfo=tz)


def rows_through(day):
    end = date.fromisoformat(day)
    start = end - timedelta(days=10)
    rows = []
    for offset in range(11):
        d = start + timedelta(days=offset)
        close = 10.0 + offset / 100
        rows.append({
            'date': d.isoformat(), 'open': close, 'close': close,
            'high': close + .1, 'low': close - .1, 'volume': 1000.0,
            'amount': 0.0, 'price_basis': 'qfq',
            'price_basis_source': 'tencent_qfqday',
        })
    return rows


def batch_result(code, kind, rows=None, **fields):
    result = df.KlineBatchResult()
    if rows:
        result[code] = rows
    result.fetch_states[code] = {'kind': kind, **fields}
    return result


class CloseSourceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute('''CREATE TABLE kline(
            code TEXT, date TEXT, open REAL, close REAL, high REAL, low REAL,
            volume REAL, amount REAL, price_basis TEXT, price_basis_source TEXT,
            PRIMARY KEY(code,date))''')
        self.conn.execute('''CREATE TABLE kline_fetch_state(
            code TEXT PRIMARY KEY, checked REAL, next_retry REAL, failures INT, payload TEXT)''')
        self.today = FIXED_CLOSE.date().isoformat()
        self.old_rows = rows_through(self.today)[:-1]
        df.save_klines(self.conn, 'kline', 'code', {CODE: self.old_rows})
        payload = {
            'latest': self.old_rows[-1]['date'], 'error': 'previous failure',
            'full_checked': 0, 'integrity_checked': 0,
            'data_fetch': {'kind': 'request_error', 'error_type': 'TimeoutError'},
        }
        self.original_state = (CODE, time.time() - 100, 0.0, 2,
                               json.dumps(payload, ensure_ascii=False))
        self.conn.execute('INSERT INTO kline_fetch_state VALUES(?,?,?,?,?)', self.original_state)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def active_quote(self):
        return {CODE: {'amount_wan': 1.0, 'volume_shou': 1.0}}

    def state_row(self):
        return self.conn.execute(
            'SELECT code,checked,next_retry,failures,payload FROM kline_fetch_state WHERE code=?',
            (CODE,)).fetchone()

    def test_one_error_does_not_quarantine_host_but_repeated_failure_does(self):
        host = config.KLINE['hosts'][0]
        with patch.dict(config.KLINE, {'hosts': [host]}), \
                patch.object(df, '_KLINE_HOST_COOLDOWN', {}), \
                patch.object(df, '_KLINE_HOST_FAILURES', {}), \
                patch.object(df, 'http_get', side_effect=TimeoutError('network')) as get:
            for attempt in range(3):
                with self.assertRaises(TimeoutError):
                    df.fetch_kline(CODE, days=20)
                self.assertEqual(host in df._KLINE_HOST_COOLDOWN, attempt == 2)
            with self.assertRaises(df.KlineHostCooling):
                df.fetch_kline(CODE, days=20)
            self.assertEqual(get.call_count, 3)

    def test_successful_inflight_response_clears_host_failure_and_cooldown(self):
        host = config.KLINE['hosts'][0]
        payload = {'code': 0, 'data': {'sz000001': {'qfqday': [
            ['2026-10-27', '11.27', '11.47', '11.55', '11.24', '1529292', {}]]}}}
        def reply(*args, **kwargs):
            df._KLINE_HOST_COOLDOWN[host] = time.monotonic() + 60
            df._KLINE_HOST_FAILURES[host] = 3
            return json.dumps(payload)
        with patch.dict(config.KLINE, {'hosts': [host]}), \
                patch.object(df, '_KLINE_HOST_COOLDOWN', {}), \
                patch.object(df, '_KLINE_HOST_FAILURES', {}), \
                patch.object(df, 'http_get', side_effect=reply):
            self.assertTrue(df.fetch_kline(CODE, days=20))
            self.assertNotIn(host, df._KLINE_HOST_COOLDOWN)
            self.assertNotIn(host, df._KLINE_HOST_FAILURES)

    def test_new_mirror_recovers_first_host_error_with_same_qfq_rows(self):
        hosts = config.KLINE['hosts'][:2]
        self.assertEqual(hosts[1], 'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get')
        payload = {'code': 0, 'data': {'sz000001': {'qfqday': [
            ['2026-10-27', '11.27', '11.47', '11.55', '11.24', '1529292', {}]]}}}
        with patch.dict(config.KLINE, {'hosts': hosts}), \
                patch.object(df, '_KLINE_HOST_COOLDOWN', {}), \
                patch.object(df, '_KLINE_HOST_FAILURES', {}), \
                patch.object(df, '_KLINE_HOST_IDX', 0), \
                patch.object(df, 'http_get', side_effect=[TimeoutError('first host'), json.dumps(payload)]) as get:
            rows = df.fetch_kline(CODE, days=20)
        self.assertEqual(get.call_count, 2)
        self.assertTrue(get.call_args_list[1].args[0].startswith(hosts[1]))
        self.assertEqual(rows[-1]['close'], 11.47)
        self.assertEqual(rows[-1]['price_basis_source'], 'tencent_qfqday')

    def test_preferred_new_endpoint_preserves_qfq_parser(self):
        self.assertEqual(config.KLINE['hosts'][0],
                         'https://web.ifzq.gtimg.cn/appstock/app/newfqkline/get')
        payload = {'code': 0, 'data': {'sz000001': {'qfqday': [
            ['2026-10-27', '11.27', '11.47', '11.55', '11.24', '1529292', {}]]}}}
        with patch.object(df, '_KLINE_HOST_COOLDOWN', {}), \
                patch.object(df, '_KLINE_HOST_IDX', 0), \
                patch.object(df, 'http_get', return_value=json.dumps(payload)) as get:
            rows = df.fetch_kline('000001', days=20)
        self.assertIn('/newfqkline/get?param=sz000001,day,,,20,qfq', get.call_args.args[0])
        self.assertEqual(rows[-1]['date'], '2026-10-27')
        self.assertEqual(rows[-1]['close'], 11.47)
        self.assertEqual(rows[-1]['volume'], 152929200)
        self.assertEqual(rows[-1]['price_basis_source'], 'tencent_qfqday')

    def test_bulk_separates_cooling_from_real_request_error(self):
        hosts = list(config.KLINE['hosts'])
        cooling = {h: time.monotonic() + 60 for h in hosts}
        with patch.object(df, '_KLINE_HOST_COOLDOWN', cooling), \
                patch.object(df, 'http_get') as get:
            result, truncated = df.fetch_klines_bulk(
                [CODE], workers=1, progress=False, days=20, deadline_seconds=2)
        self.assertFalse(truncated)
        self.assertEqual(result.fetch_states[CODE]['kind'], 'source_cooldown')
        self.assertEqual(result.fetch_states[CODE]['error_type'], 'KlineHostCooling')
        get.assert_not_called()

        with patch.object(df, '_KLINE_HOST_COOLDOWN', {}), \
                patch.object(df, 'http_get', side_effect=TimeoutError('source timed out')):
            result, truncated = df.fetch_klines_bulk(
                [CODE], workers=1, progress=False, days=20, deadline_seconds=2)
        state = result.fetch_states[CODE]
        self.assertFalse(truncated)
        self.assertEqual(state['kind'], 'request_error')
        self.assertEqual(state['error_type'], 'TimeoutError')
        self.assertEqual(state['error_message'], 'source timed out')

    def test_main_batch_cooling_is_deferred_without_state_mutation(self):
        cooldown = batch_result(CODE, 'source_cooldown', error_type='KlineHostCooling')
        before = self.state_row()
        with patch.dict(config.KLINE, {'days': 10}), \
                patch.object(df, 'fetch_klines_bulk', return_value=(cooldown, False)), \
                patch.object(history_increment, 'datetime', FrozenCloseDateTime):
            result = history_increment.update(
                self.conn, [CODE], self.active_quote(), required_day=self.today,
                progress=False, allow_periodic=False)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(result['deferred'], 1)
        self.assertEqual(result['source_cooldown'], 1)
        self.assertEqual(self.state_row(), before)

    def test_full_due_cooling_is_deferred_without_state_mutation(self):
        good_rows = rows_through(self.today)
        good = batch_result(CODE, 'ok', good_rows)
        cooldown = batch_result(CODE, 'source_cooldown', error_type='KlineHostCooling')
        before = self.state_row()
        with patch.dict(config.KLINE, {'days': 10}), \
                patch.object(df, 'fetch_klines_bulk', side_effect=[(good, False), (cooldown, False)]), \
                patch.object(history_increment, 'requires_full', return_value=True), \
                patch.object(history_increment, 'datetime', FrozenCloseDateTime):
            result = history_increment.update(
                self.conn, [CODE], self.active_quote(), required_day=self.today,
                progress=False, allow_periodic=False)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(result['deferred'], 1)
        self.assertEqual(result['source_cooldown'], 1)
        self.assertEqual(result['integrity_pending'], 1)
        self.assertEqual(self.state_row(), before)
        self.assertEqual(df.load_kline(self.conn, 'kline', 'code', CODE)[-1]['date'], self.old_rows[-1]['date'])

    def test_real_failure_keeps_existing_retry_backoff(self):
        failed = batch_result(CODE, 'request_error', error_type='TimeoutError',
                              error_message='source timed out', provider='tencent_kline')
        with patch.dict(config.KLINE, {'days': 10}), \
                patch.object(df, 'fetch_klines_bulk', return_value=(failed, False)), \
                patch.object(history_increment, 'datetime', FrozenCloseDateTime):
            result = history_increment.update(
                self.conn, [CODE], self.active_quote(), required_day=self.today,
                progress=False, allow_periodic=False)
        row = self.state_row()
        meta = json.loads(row[4])
        self.assertEqual(result['failed'], 1)
        self.assertEqual(result['source_cooldown'], 0)
        self.assertEqual(row[3], 3)
        self.assertGreater(row[2], time.time())
        self.assertEqual(meta['data_fetch']['error_type'], 'TimeoutError')
        self.assertEqual(meta['data_fetch']['error_message'], 'source timed out')

    def test_unfinished_truncated_request_is_not_treated_as_success_or_cooling(self):
        unfinished = df.KlineBatchResult()
        with patch.dict(config.KLINE, {'days': 10}), \
                patch.object(df, 'fetch_klines_bulk', return_value=(unfinished, True)), \
                patch.object(history_increment, 'datetime', FrozenCloseDateTime):
            result = history_increment.update(
                self.conn, [CODE], self.active_quote(), required_day=self.today,
                progress=False, allow_periodic=False)
        row = self.state_row()
        self.assertEqual(result['failed'], 1)
        self.assertEqual(result['source_cooldown'], 0)
        self.assertTrue(result['truncated'])
        self.assertEqual(row[3], 3)
        self.assertGreater(row[2], time.time())
        self.assertEqual(df.load_kline(self.conn, 'kline', 'code', CODE)[-1]['date'], self.old_rows[-1]['date'])

    def test_recovered_source_saves_bar_and_clears_failure_state(self):
        good = batch_result(CODE, 'ok', rows_through(self.today), provider='tencent_kline')
        with patch.dict(config.KLINE, {'days': 10}), \
                patch.object(df, 'fetch_klines_bulk', return_value=(good, False)), \
                patch.object(history_increment, 'datetime', FrozenCloseDateTime):
            result = history_increment.update(
                self.conn, [CODE], self.active_quote(), required_day=self.today,
                progress=False, allow_periodic=False)
        row = self.state_row()
        meta = json.loads(row[4])
        self.assertEqual(result['failed'], 0)
        self.assertEqual(result['changed_rows'], 1)
        self.assertEqual(row[2:4], (0.0, 0))
        self.assertEqual(meta['latest'], self.today)
        self.assertIsNone(meta['error'])
        self.assertNotIn('data_fetch', meta)

    def test_close_gate_still_rejects_less_than_eighty_percent(self):
        quotes = {f'{i:06d}': {'amount_wan': 1.0, 'volume_shou': 1.0}
                  for i in range(4)}
        bar = rows_through(self.today)[-1]
        klines = {code: [dict(bar)] for code in list(quotes)[:3]}
        with self.assertRaises(scoring.DataNotReady):
            scoring.validate_close_daily(klines, quotes, datetime.combine(
                date.fromisoformat(self.today), datetime.min.time()).replace(hour=15, minute=5))

    def test_coverage_counts_only_active_codes_and_keeps_eighty_percent_gate(self):
        quotes = {f'{i:06d}': {'amount_wan': 1.0, 'volume_shou': 1.0}
                  for i in range(5)}
        quotes['999999'] = {'amount_wan': 0.0, 'volume_shou': 0.0}
        bar = rows_through(self.today)[-1]
        klines = {code: [dict(bar)] for code in list(quotes)[:4]}
        coverage = {}
        ready = scoring.validate_close_daily(
            klines, quotes, FIXED_CLOSE, coverage=coverage)
        self.assertEqual(ready, 4)
        self.assertEqual(coverage, {
            'asof': self.today, 'active_count': 5, 'ready_count': 4,
            'pending_count': 1, 'pending_codes': ['000004']})
        klines.pop('000003')
        with self.assertRaises(scoring.DataNotReady):
            scoring.validate_close_daily(klines, quotes, FIXED_CLOSE.replace(minute=11), coverage={})

    def test_pending_coverage_keeps_done_semantics_but_pick_mode_retries(self):
        snapshot = {
            'strength_model': {'asof': self.today},
            'close_strong_board': {'asof': self.today},
            'close_daily_verified_at': f'{self.today} 15:10:00',
            'close_refresh_version': scoring.CLOSE_REFRESH_VERSION,
            'close_daily_coverage': {'asof': self.today, 'pending_count': 450},
        }
        self.assertTrue(serve.close_review_done(FIXED_CLOSE, snapshot))
        self.assertEqual(serve.pick_mode(FIXED_CLOSE, snapshot), 'close')

    def test_pending_zero_without_close_proof_still_selects_close(self):
        snapshot = {
            'strength_model': {'asof': self.today},
            'close_strong_board': {'asof': '2026-10-26'},
            'close_daily_coverage': {'asof': self.today, 'pending_count': 0},
        }
        self.assertFalse(serve.close_review_done(FIXED_CLOSE, snapshot))
        self.assertEqual(serve.pick_mode(FIXED_CLOSE, snapshot), 'close')

    def test_yesterday_coverage_is_ignored_when_today_close_is_incomplete(self):
        snapshot = {
            'strength_model': {'asof': '2026-10-26'},
            'close_strong_board': {'asof': '2026-10-26'},
            'close_daily_coverage': {'asof': '2026-10-26', 'pending_count': 450},
        }
        self.assertEqual(serve.pick_mode(FIXED_CLOSE, snapshot), 'close')

    def test_automatic_retry_window_is_separate_from_manual_pick_mode(self):
        pending = {
            'strength_model': {'asof': self.today},
            'close_strong_board': {'asof': self.today},
            'close_daily_verified_at': f'{self.today} 15:10:00',
            'close_refresh_version': scoring.CLOSE_REFRESH_VERSION,
            'close_daily_coverage': {'asof': self.today, 'pending_count': 1},
        }
        at_1550 = FIXED_CLOSE.replace(hour=15, minute=50)
        at_1605 = FIXED_CLOSE.replace(hour=16, minute=5)
        at_1800 = FIXED_CLOSE.replace(hour=18, minute=0)
        self.assertTrue(serve.automatic_close_retry_allowed(at_1550, 'close', False))
        self.assertEqual(serve.pick_mode(at_1800, pending), 'close')
        self.assertFalse(serve.automatic_close_retry_allowed(at_1800, 'close', True))
        self.assertTrue(serve.automatic_close_retry_allowed(at_1605, 'close', True))
        self.assertFalse(serve.automatic_close_retry_allowed(at_1605, 'close', False))
        # A legacy snapshot may have no coverage metadata; real same-day evidence
        # still permits the same 16-18 automatic close retry.
        legacy = {
            'strength_model': {'asof': '2026-10-26'},
            'close_strong_board': {'asof': '2026-10-26'},
            'intraday_model': {'latest_valid_quote_at': f'{self.today} 15:00:00'},
        }
        self.assertEqual(serve.pick_mode(at_1605, legacy), 'close')
        with patch.dict(serve.SNAPSHOT_META, {
                'snapshot_latest_valid_quote_at': f'{self.today} 15:00:00'}):
            evidence = serve.boundary_trading_evidence(at_1605)
            self.assertTrue(evidence)
            self.assertTrue(serve.automatic_close_retry_allowed(at_1605, 'close', evidence))
        self.assertFalse(serve.automatic_close_retry_allowed(at_1605, 'quick', True))

    def test_legacy_snapshot_keeps_previous_close_mode_decision(self):
        incomplete = {
            'strength_model': {'asof': '2026-10-26'},
            'close_strong_board': {'asof': '2026-10-26'},
        }
        self.assertEqual(serve.pick_mode(FIXED_CLOSE, incomplete), 'close')
        complete = {
            'strength_model': {'asof': self.today},
            'close_strong_board': {'asof': self.today},
            'close_daily_verified_at': f'{self.today} 15:10:00',
            'close_refresh_version': scoring.CLOSE_REFRESH_VERSION,
        }
        self.assertEqual(serve.pick_mode(FIXED_CLOSE, complete), 'quick')


if __name__ == '__main__':
    unittest.main()
