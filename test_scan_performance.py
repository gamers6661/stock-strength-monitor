"""Cache invalidation, true daily increment, retry fairness and wall-clock limits."""
from copy import deepcopy
from datetime import datetime
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

import config
import datafeed as df
import history_increment as H
import scan_cache as C
import strength
import board_trend
from test_strength import bars


def bar(day, close=10):
    return dict(date=day, open=close, close=close, high=close+1, low=close-1,
                volume=100, amount=1000, price_basis='qfq', price_basis_source='tencent_qfqday')


class Morning(datetime):
    @classmethod
    def now(cls):
        return cls(2026, 10, 12, 10)


class IncrementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.cache = patch.object(config, 'CACHE_DIR', Path(self.tmp.name))
        self.cache.start()
        self.settings = patch.dict(config.KLINE, {'days': 2, 'repair_per_scan': 2})
        self.settings.start()
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute('CREATE TABLE kline(code TEXT,date TEXT,open REAL,close REAL,high REAL,low REAL,volume REAL,amount REAL,price_basis TEXT,price_basis_source TEXT,PRIMARY KEY(code,date))')
        self.old = bar('2026-10-08')
        df.save_klines(self.conn, 'kline', 'code', {'a': [self.old]})
        self.quotes = {'a': {'amount_wan': 1}}

    def tearDown(self):
        self.conn.close()
        C.flush()
        self.cache.stop()
        self.settings.stop()
        # Windows cannot remove a SQLite file while a connection remains open.
        with C._lock:
            for key in list(C._connections):
                if key.startswith(self.tmp.name):
                    C._connections.pop(key).close()
        self.tmp.cleanup()

    def update(self, day, **kwargs):
        with patch.object(H, 'datetime', Morning):
            return H.update(self.conn, list(self.quotes), self.quotes, day, progress=False, **kwargs)

    def test_warm_completed_day_does_not_request_history(self):
        with patch.object(df, 'fetch_klines_bulk') as fetch:
            self.assertEqual(self.update('2026-10-08')['requested'], 0)
        fetch.assert_not_called()

    def test_increment_writes_only_new_bar_then_no_requests(self):
        recent = [self.old, bar('2026-10-09', 11)]
        with patch.object(df, 'fetch_klines_bulk', return_value=({'a': recent}, False)) as fetch:
            result = self.update('2026-10-09')
            self.assertEqual(result['changed_rows'], 1)
            self.assertEqual(fetch.call_args.kwargs['days'], 20)
            self.assertEqual(self.update('2026-10-09')['requested'], 0)
            fetch.assert_called_once()
        self.assertEqual(len(df.load_kline(self.conn, 'kline', 'code', 'a')), 2)

    def test_price_revision_requires_full_overlap_and_replaces_old_prices(self):
        revised = [bar('2026-10-08', 9), bar('2026-10-09')]
        with patch.object(df, 'fetch_klines_bulk', side_effect=[({'a': revised}, False), ({'a': revised}, False)]) as fetch:
            result = self.update('2026-10-09')
        self.assertEqual(fetch.call_count, 2)
        self.assertGreater(fetch.call_args.kwargs['days'], 20)
        self.assertEqual(result['full_repairs'], 1)
        self.assertEqual(df.load_kline(self.conn, 'kline', 'code', 'a')[0]['close'], 9)

    def test_failed_adjustment_repair_keeps_originals_and_marks_pending(self):
        revised = [bar('2026-10-08', 9), bar('2026-10-09')]
        with patch.object(df, 'fetch_klines_bulk', side_effect=[({'a': revised}, False), ({}, True)]):
            self.assertEqual(self.update('2026-10-09')['failed'], 1)
        self.assertEqual(df.load_kline(self.conn, 'kline', 'code', 'a'), [self.old])
        payload = json.loads(self.conn.execute('SELECT payload FROM kline_fetch_state WHERE code="a"').fetchone()[0])
        self.assertTrue(payload['integrity_pending'])

    def test_volume_revision_does_not_need_full_adjustment_repair(self):
        recent = [dict(self.old, volume=120), bar('2026-10-09')]
        with patch.object(df, 'fetch_klines_bulk', return_value=({'a': recent}, False)) as fetch:
            self.assertEqual(self.update('2026-10-09')['changed_rows'], 2)
            fetch.assert_called_once()

    def test_missing_overlap_and_unknown_basis_require_full(self):
        self.assertTrue(H.requires_full([self.old], [bar('2026-10-09')]))
        self.assertTrue(H.requires_full([dict(self.old, price_basis=None)], [self.old]))
        self.assertTrue(H.requires_full([self.old], [dict(self.old, price_basis='raw')]))

    def test_short_listing_is_not_repeatedly_full_fetched(self):
        self.quotes = {'b': {'amount_wan': 1}}
        recent = [bar('2026-10-09')]
        with patch.dict(config.KLINE, {'days': 160}), patch.object(df, 'fetch_klines_bulk', return_value=({'b': recent}, False)) as fetch:
            self.update('2026-10-09')
            self.update('2026-10-09')
        fetch.assert_called_once()

    def test_unfinished_source_bar_never_enters_formal_db(self):
        with patch.object(df, 'fetch_klines_bulk', return_value=({'a': [self.old, bar('2026-10-12')]}, False)):
            self.update('2026-10-08', force=True)
        self.assertEqual(df.load_kline(self.conn, 'kline', 'code', 'a'), [self.old])

    def test_failed_symbols_backoff_without_permanent_blacklist(self):
        with patch.object(df, 'fetch_klines_bulk', return_value=({}, True)) as fetch:
            self.update('2026-10-09')
            self.update('2026-10-09')
        fetch.assert_called_once()
        self.assertFalse((config.CACHE_DIR/'no_kline.json').exists())

    def test_volume_alone_does_not_accept_stale_history_as_no_trade(self):
        self.quotes['a'] = {'amount_wan': 0, 'volume_shou': 10}
        with patch.object(df, 'fetch_klines_bulk', return_value=({'a': [self.old]}, False)):
            self.assertEqual(self.update('2026-10-09')['failed'], 1)
        meta = json.loads(self.conn.execute('SELECT payload FROM kline_fetch_state WHERE code="a"').fetchone()[0])
        self.assertNotIn('no_trade_checked_day', meta)

    def test_no_trade_history_is_checked_once_and_resumption_rechecks(self):
        self.quotes['a'] = {'amount_wan': 0, 'volume_shou': 0}
        with patch.object(df, 'fetch_klines_bulk', return_value=({'a': [self.old]}, False)) as fetch:
            self.update('2026-10-09')
            self.update('2026-10-09')
            fetch.assert_called_once()
            self.quotes['a']['amount_wan'] = 1
            self.update('2026-10-09')
            self.assertEqual(fetch.call_count, 2)

    def test_zero_volume_source_bar_is_stored_without_relaxing_eligibility(self):
        self.quotes['a'] = {'amount_wan': 0, 'volume_shou': 0}
        stopped = dict(bar('2026-10-09'), volume=0)
        with patch.object(df, 'fetch_klines_bulk', return_value=({'a': [self.old, stopped]}, False)) as fetch:
            self.update('2026-10-09')
            self.update('2026-10-09')
        fetch.assert_called_once()
        self.assertEqual(df.load_kline(self.conn, 'kline', 'code', 'a')[-1], stopped)
        self.assertFalse(strength.valid_bars([stopped]))

    def test_repair_quota_fairly_advances_past_recent_failures(self):
        self.quotes = {c: {'amount_wan': 1} for c in ['b', 'c', 'd']}
        with patch.object(df, 'fetch_klines_bulk', return_value=({}, False)) as fetch:
            self.assertEqual(self.update('2026-10-09')['deferred'], 1)
            self.update('2026-10-09')
        self.assertEqual(fetch.call_args.args[0], ['d'])

    def test_upsert_unchanged_rows_and_sql_limit_preserve_complete_history(self):
        self.assertEqual(df.save_klines(self.conn, 'kline', 'code', {'a': [self.old]}), 0)
        df.save_klines(self.conn, 'kline', 'code', {'a': [bar('2026-10-09')]})
        self.assertEqual(len(df.load_kline(self.conn, 'kline', 'code', 'a')), 2)
        self.assertEqual(df.load_kline(self.conn, 'kline', 'code', 'a', limit=1)[0]['date'], '2026-10-09')


class CacheTests(unittest.TestCase):
    setUp = IncrementTests.setUp
    tearDown = IncrementTests.tearDown
    def test_cache_content_calendar_and_rule_changes_invalidate(self):
        count = []
        compute = lambda: (count.append(1) or {'score': 5})
        value = C.cached('test', 'a', ['day', 1], compute)
        value['score'] = 99
        self.assertEqual(C.cached('test', 'a', ['day', 1], compute)['score'], 5)
        C.cached('test', 'a', ['day', 2], compute)
        C.cached('test', 'a', ['next_day', 2], compute)
        self.assertEqual(len(count), 3)
        C.flush()
        C._memory.clear()
        self.assertEqual(C.cached('test', 'a', ['next_day', 2], compute)['score'], 5)
        self.assertEqual(len(count), 3)

    def test_real_strength_current_quotes_change_while_daily_score_stays(self):
        series = {'a': bars(), 'b': bars(slope=.2)}
        source = [{'code': c, 'price': 10, 'limit_today': False} for c in series]
        before, model = strength.build(source, series, {'a': '行业一', 'b': '行业一'})
        changed = deepcopy(source)
        changed[0].update(price=99, limit_today=True)
        after, _ = strength.build(changed, series, {'a': '行业一', 'b': '行业一'})
        old = {r['code']: r for r in before}
        new = {r['code']: r for r in after}
        self.assertEqual(old['a']['stock_strength_score'], new['a']['stock_strength_score'])
        self.assertEqual(new['a']['price'], 99)
        self.assertIn('现价接近涨停，需确认成交条件', new['a']['risk_notes'])

    def test_board_replay_cache_does_not_mutate_or_ignore_history_revisions(self):
        ks = bars()
        days = [b['date'] for b in ks]
        first = board_trend.calculate(ks, days, days[-1])
        first['name'] = '外部变更'
        second = board_trend.calculate(ks, days, days[-1])
        self.assertNotIn('name', second)
        revised = deepcopy(ks)
        revised[-1]['high'] += 2
        self.assertNotEqual(second['atr20'], board_trend.calculate(revised, days, days[-1])['atr20'])

    def test_jsonl_append_and_replacement_both_refresh(self):
        path = config.CACHE_DIR/'pairs.jsonl'
        path.write_text('{"a":1}\n', encoding='utf-8')
        self.assertEqual(C.read_json(path, True), [{'a': 1}])
        with path.open('a', encoding='utf-8') as stream:
            stream.write('{"a":2}\n')
        self.assertEqual(C.read_json(path, True), [{'a': 1}, {'a': 2}])
        path.write_text('{"a":8}\n', encoding='utf-8')
        self.assertEqual(C.read_json(path, True), [{'a': 8}])

    def test_cache_unserializable_input_falls_back_to_calculation(self):
        self.assertEqual(C.cached('test', 'a', float('nan'), lambda: {'a': 3}), {'a': 3})

    def test_live_emotion_changes_without_invalidating_daily_theme_context(self):
        import theme_assist
        rows = [dict(code=str(i), boards=['主题'] if i<7 else ['其他'], ret5=1,
                    trend_online=False, emotion_strong=False, emotion_limit=False,
                    emotion_yesterday_limit=False) for i in range(15)]
        theme_assist.enrich_stocks(rows)
        self.assertEqual(rows[0]['theme_relations'][0]['state'], '未见扩散')
        for r in rows[1:4]: r.update(emotion_strong=True, emotion_limit=True)
        theme_assist.enrich_stocks(rows)
        self.assertEqual(rows[0]['theme_relations'][0]['state'], '情绪扩散')


class BoardHistoryTests(unittest.TestCase):
    setUp = IncrementTests.setUp
    tearDown = IncrementTests.tearDown

    def prepare(self, unfinished=False):
        series = bars()
        end = datetime(2026, 10, 8)
        for i, b in enumerate(series):
            b['date'] = (end-timedelta(days=len(series)-1-i)).strftime('%Y-%m-%d')
        if unfinished:
            series.append(bar('2026-10-12', 18))
        return series

    def test_complete_board_history_is_requested_once_then_reused(self):
        import scoring
        with patch.object(scoring, 'datetime', Morning), patch.object(df, 'scan_ths_boards', return_value={'885001':'概念甲'}), \
             patch.object(df, 'fetch_ths_board_kline', return_value=('概念甲',self.prepare())) as fetch, \
             patch.object(board_trend, 'save') as save:
            first, _ = scoring.build_board_board(self.conn)
            second, _ = scoring.build_board_board(self.conn)
        self.assertEqual(first, second)
        fetch.assert_called_once()
        save.assert_called_once()

    def test_unfinished_board_bar_is_never_frozen(self):
        import scoring
        with patch.object(scoring, 'datetime', Morning), patch.object(df, 'scan_ths_boards', return_value={'885001':'概念甲'}), \
             patch.object(df, 'fetch_ths_board_kline', return_value=('概念甲',self.prepare(True))) as fetch, \
             patch.object(board_trend, 'save'):
            scoring.build_board_board(self.conn)
            scoring.build_board_board(self.conn)
        self.assertEqual(fetch.call_count, 2)

    def test_board_failures_backoff(self):
        import scoring
        with patch.object(scoring, 'datetime', Morning), patch.object(df, 'scan_ths_boards', return_value={'885001':'概念甲'}), \
             patch.object(df, 'fetch_ths_board_kline', side_effect=OSError('offline')) as fetch:
            self.assertEqual(scoring.build_board_board(self.conn)[0], [])
            self.assertEqual(scoring.build_board_board(self.conn)[0], [])
        fetch.assert_called_once()


class DeadlineTests(unittest.TestCase):
    def test_quote_batches_keep_full_request_count_without_internal_retries(self):
        with patch.object(df, 'http_get', side_effect=OSError('offline')) as get:
            self.assertEqual(df.tencent_quotes([str(600000+i) for i in range(850)]), {})
        self.assertEqual(get.call_count, 3)
        self.assertEqual(get.call_args.kwargs['timeout'], 6)
        self.assertEqual(get.call_args.kwargs['retry'], 0)

    def test_batch_deadline_does_not_wait_for_running_executor_and_discards_late_data(self):
        def slow(code, **kwargs):
            time.sleep(.25)
            return [bar('2026-10-09')]
        start = time.monotonic()
        with patch.dict(config.KLINE, {'deadline_seconds': .04}), patch.object(df, 'fetch_kline', side_effect=slow):
            result, truncated = df.fetch_klines_bulk(['a', 'b', 'c'], workers=1, progress=False)
            self.assertTrue(truncated)
            self.assertEqual(result, {})
            self.assertLess(time.monotonic()-start, .20)
            time.sleep(.27)
            self.assertEqual(result, {})


if __name__ == '__main__':
    unittest.main()
