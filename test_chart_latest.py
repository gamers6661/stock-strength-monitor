"""Latest displayed candles cannot change scores, leak closing data or mix price scales."""
import copy
import gc
import gzip
import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import config
import ui_payload
import intraday


def fixture():
    bars = [dict(date='2026-10-%02d' % d, open=100., high=102., low=99., close=101., volume=200.)
            for d in (8, 9, 12)]
    context = dict(valid=True, quote_day='2026-10-13', last_history_date='2026-10-12',
                   scale_factor=2., history_basis='qfq', history_basis_source='tencent_qfqday')
    model = dict(quote_at='2026-10-13 10:00:00', trend_score=73., emotion_score=81., price_context=context)
    stock = dict(code='600241', open=102., high=110., low=100., price=108., volume_shou=123.,
                 strength_history=bars, market_strength=model)
    return dict(stocks=[stock], session='早盘', quote_capture_at='2026-10-13 10:00:30')


class LatestChartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # SQLite context managers commit without closing. Collect any released
        # projection connection before Windows removes this test's database.
        self.addCleanup(gc.collect)
        self.db = Path(self.tmp.name) / 'market.db'
        with closing(sqlite3.connect(self.db)) as con:
            con.execute('CREATE TABLE kline(code TEXT,date TEXT,open REAL,close REAL,high REAL,low REAL,'
                        'volume REAL,price_basis TEXT,price_basis_source TEXT)')
            con.execute('INSERT INTO kline VALUES(?,?,?,?,?,?,?,?,?)',
                        ('600241', '2026-10-13', 51., 56., 58., 50., 500., 'qfq', 'tencent_qfqday'))
            con.commit()

    def project(self, data):
        with patch.object(config, 'KLINE_DB', self.db):
            return ui_payload.chart_projection(data)['stocks'][0]

    def test_short_history_draws_latest_quote_without_claiming_ma20_is_available(self):
        data=fixture();row=data['stocks'][0];row['market_strength']['price_context']={'valid':False}
        row.update(last_close=101.,last_close_semantics='previous_trade_day_raw_close',
                   price_basis='raw',price_basis_source='tencent_realtime_quote')
        for b in row['strength_history']:b.update(price_basis='qfq',price_basis_source='tencent_qfqday')
        original=copy.deepcopy(data);shown=self.project(data)
        self.assertEqual(shown['chart_history'][-1]['date'],'2026-10-13')
        self.assertEqual(shown['chart_history'][-1]['close'],108.)
        self.assertEqual(len(shown['chart_history']),4);self.assertEqual(data,original)
        self.assertFalse(shown['market_strength']['price_context']['valid'])

    def test_coverage_chart_recovers_only_exact_batch_quote_metadata(self):
        data=fixture();row=data['stocks'][0]
        row['market_strength']['price_context']={'valid':False}
        row.update(last_close=101.)
        for b in row['strength_history']:b.update(price_basis='qfq',price_basis_source='tencent_qfqday')
        raw=dict(row,quote_at=row['market_strength']['quote_at'],last_close_semantics='previous_trade_day_raw_close',
                 price_basis='raw',price_basis_source='tencent_realtime_quote')
        row.pop('volume_shou')
        folder=Path(self.tmp.name)/'acquisitions';folder.mkdir()
        with gzip.open(folder/'2026-10-13.jsonl.gz','wt',encoding='utf-8') as stream:
            stream.write(json.dumps(dict(captured_at=data['quote_capture_at'],fields=list(raw),rows=[list(raw.values())]))+'\n')
        original=copy.deepcopy(data)
        with patch.object(intraday,'HISTORY_DIR',Path(self.tmp.name)):
            shown=self.project(data)
            self.assertEqual(shown['chart_history'][-1]['date'],'2026-10-13')
            self.assertEqual(shown['chart_history'][-1]['volume'],12300.)
            self.assertEqual(data,original)
            data['quote_capture_at']='2026-10-13 10:00:31'
            self.assertNotIn('chart_history',self.project(data))

    def test_intraday_uses_actual_quote_not_later_database_close_and_leaves_scores_untouched(self):
        data = fixture(); frozen = copy.deepcopy(data)
        row = self.project(data); latest = row['chart_history'][-1]
        self.assertEqual((latest['open'], latest['high'], latest['low'], latest['close']), (102., 110., 100., 108.))
        self.assertEqual(latest['volume'], 12300.)
        self.assertEqual(row['chart_source'], 'quoted_ohlc')
        self.assertEqual(data, frozen)
        self.assertEqual(row['market_strength'], frozen['stocks'][0]['market_strength'])

    def test_verified_close_uses_formal_bar_converts_prices_but_not_volume(self):
        data = fixture(); data.update(session='已收盘', quote_capture_at='2026-10-13 16:00:00',
                                      close_daily_verified_at='2026-10-13 15:30:00')
        data['stocks'][0]['market_strength']['quote_at'] = '2026-10-13 15:01:00'
        row = self.project(data); latest = row['chart_history'][-1]
        self.assertEqual((latest['open'], latest['high'], latest['low'], latest['close']), (102., 116., 100., 112.))
        self.assertEqual(latest['volume'], 500.)
        self.assertEqual(row['chart_source'], 'formal_daily')

    def test_repeat_projection_replaces_today_once_and_excludes_future_candles(self):
        data = fixture(); data['stocks'][0]['strength_history'] += [dict(date='2026-10-13', open=1., high=2., low=1., close=2.)] * 2
        data['stocks'][0]['strength_history'].append(dict(date='2026-10-14', open=1., high=2., low=1., close=2.))
        row = self.project(data)
        self.assertEqual(sum(b['date'] == '2026-10-13' for b in row['chart_history']), 1)
        self.assertEqual(row['chart_history'][-1]['date'], '2026-10-13')
        self.assertEqual(self.project(dict(data, stocks=[row]))['chart_history'], row['chart_history'])

    def test_stale_future_or_unaligned_quote_cannot_create_latest_candle(self):
        for kind in ('stale', 'future', 'unaligned', 'invalid_ohlc'):
            with self.subTest(kind=kind):
                data = fixture(); row = data['stocks'][0]
                if kind == 'stale': row['market_strength']['quote_at'] = '2026-10-12 15:00:00'
                if kind == 'future': row['market_strength']['quote_at'] = '2026-10-13 10:01:00'
                if kind == 'unaligned': row['market_strength']['price_context']['valid'] = False
                if kind == 'invalid_ohlc': row['high'] = 101.
                self.assertNotIn('chart_history', self.project(data))

    def test_wrong_basis_or_future_verification_falls_back_to_quoted_bar(self):
        for reason in ('basis', 'verification'):
            with self.subTest(reason=reason):
                data = fixture(); data.update(session='已收盘', quote_capture_at='2026-10-13 16:00:00',
                                              close_daily_verified_at='2026-10-13 15:30:00')
                data['stocks'][0]['market_strength']['quote_at'] = '2026-10-13 15:01:00'
                if reason == 'basis':
                    data['stocks'][0]['market_strength']['price_context']['history_basis'] = 'raw'
                else:
                    data['close_daily_verified_at'] = '2026-10-13 16:30:00'
                self.assertEqual(self.project(data)['chart_source'], 'quoted_ohlc')

    def test_published_chart_is_immutable_when_database_changes(self):
        data = fixture(); data.update(session='已收盘', quote_capture_at='2026-10-13 16:00:00',
                                      close_daily_verified_at='2026-10-13 15:30:00')
        data['stocks'][0]['market_strength']['quote_at'] = '2026-10-13 15:01:00'
        page = Path(self.tmp.name) / 'dashboard.html'
        with patch.object(config, 'KLINE_DB', self.db):
            _, token = ui_payload.prepare(data, 'var DATA=/*__DATA__*/null;', page)
            with closing(sqlite3.connect(self.db)) as con:
                con.execute('UPDATE kline SET close=57 WHERE date=?', ('2026-10-13',))
                con.commit()
            self.assertEqual(ui_payload.detail(token, 'stock', '600241', page)['chart_history'][-1]['close'], 112.)
            self.assertEqual(ui_payload.full(token, page)['stocks'][0]['chart_history'][-1]['close'], 112.)


if __name__ == '__main__':
    unittest.main()
