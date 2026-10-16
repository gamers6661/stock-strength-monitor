import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import board_chart


class BoardChartTests(unittest.TestCase):
    def setUp(self):
        self.clock = datetime(2026, 10, 13, 16, 6)
        self.board = dict(id='industry:示例', name='示例', index_trend=dict(code='881001', source='同花顺行业指数'),
                          market_strength=dict(trend_score=90),
                          index_quote=dict(code='881001', name='示例', price_basis='同花顺指数原值',
                                           quote_at='2026-10-13 15:00:00', price=102, previous_close=100))
        self.bars = [dict(date='2026-10-12', open=99, high=101, low=98, close=100, volume=10000,
                          observed_at='2026-10-13T15:10:00'),
                     dict(date='2026-10-13', open=100, high=103, low=99, close=102, volume=12000,
                          observed_at='2026-10-13T15:10:00')]

    def test_completed_daily_matches_official_close(self):
        p = board_chart.project(self.board, self.bars, self.clock)
        self.assertEqual(p['asof'], '2026-10-13')
        self.assertIsNone(p['current_price'])

    def test_mismatched_partial_today_is_not_a_completed_candle(self):
        self.bars[-1]['close'] = 101
        p = board_chart.project(self.board, self.bars, self.clock)
        self.assertEqual(p['asof'], '2026-10-12')
        self.assertEqual(p['current_price'], 102)
        self.assertIn('不一致', p['reason'])

    def test_intraday_never_uses_unfinished_today(self):
        clock = datetime(2026, 10, 13, 14, 0)
        self.board['index_quote']['quote_at'] = '2026-10-13 13:59:00'
        p = board_chart.project(self.board, self.bars, clock)
        self.assertEqual(p['asof'], '2026-10-12')
        self.assertEqual(p['current_price'], 102)

    def test_incomplete_ohlc_not_fabricated_from_samples(self):
        self.bars[-1].pop('open')
        self.board['index_quote'].update(sampled_low=99, sampled_high=103)
        p = board_chart.project(self.board, self.bars, self.clock)
        self.assertEqual(len(p['bars']), 1)

    def test_future_source_timestamp_is_not_completion_proof(self):
        self.bars[-1]['observed_at'] = '2026-10-14T15:10:00'
        p = board_chart.project(self.board, self.bars, self.clock)
        self.assertEqual(p['asof'], '2026-10-12')

    def test_future_illegal_and_nontrading_bars_are_excluded(self):
        future = dict(self.bars[-1], date='2026-10-14')
        illegal = dict(self.bars[0], date='2026-10-09', low=105)
        p = board_chart.project(self.board, self.bars+[future, illegal], self.clock, ['2026-10-12'])
        self.assertEqual([b['date'] for b in p['bars']], ['2026-10-12'])

    def test_wrong_index_or_basis_never_gets_a_price_line(self):
        for key, value in [('code', '881999'), ('name', '别的方向'), ('price_basis', '成员等权'),
                           ('previous_close', 88), ('quote_at', '2026-10-14 15:00:00')]:
            b = copy.deepcopy(self.board)
            b['index_quote'][key] = value
            p = board_chart.project(b, self.bars, self.clock)
            self.assertIsNone(p['current_price'])
            self.assertEqual(p['asof'], '2026-10-12')

    def test_missing_mapping_stays_missing(self):
        p = board_chart.project(dict(name='细分行业'), [], self.clock)
        self.assertFalse(p['bars'])
        self.assertIn('暂无对应', p['reason'])

    def test_no_database_creation_or_mutation_of_scores(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder)/'missing.db'
            full = dict(quote_capture_at=str(self.clock), board_catalog=[self.board], market_strength=dict(version='fixed'))
            before = copy.deepcopy(full)
            out = board_chart.attach(full, missing)
            self.assertEqual(full, before)
            self.assertEqual(out['market_strength'], full['market_strength'])
            self.assertEqual(out['board_catalog'][0]['market_strength'], self.board['market_strength'])
            self.assertFalse(missing.exists())


if __name__ == '__main__':
    unittest.main()
