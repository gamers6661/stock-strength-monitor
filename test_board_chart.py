import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

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

    def test_stale_completed_bar_rechecked_without_changing_model_history(self):
        class Clock(datetime):
            @classmethod
            def now(cls):return cls(2026,10,13,16,10)
        with tempfile.TemporaryDirectory() as folder:
            cache=Path(folder)/'display.json'
            stale=copy.deepcopy(self.bars);stale[-1]['close']=101
            histories={'881001':stale};original=copy.deepcopy(self.board)
            with patch.object(board_chart,'datetime',Clock):
                meta=board_chart.repair_completed([self.board],histories,self.clock,cache,True,
                    lambda *_:('示例',copy.deepcopy(self.bars)))
            self.assertEqual(meta['repaired'],1);self.assertEqual(self.board,original)
            self.assertEqual(board_chart.project(self.board,histories['881001'],self.clock)['asof'],'2026-10-13')
            # Later publications reuse verified display data without another request.
            with patch.object(board_chart,'datetime',Clock):
                again={'881001':stale[:-1]}
                meta=board_chart.repair_completed([self.board],again,self.clock,cache,True,
                    lambda *_:self.fail('verified cached close should be reused'))
            self.assertEqual(meta['attempted'],0);self.assertEqual(again['881001'][-1]['close'],102)

    def test_bad_official_response_keeps_old_chart(self):
        for bad_name,price in [('别的指数',102),('示例',999)]:
            with self.subTest(name=bad_name,price=price),tempfile.TemporaryDirectory() as folder:
                history={'881001':copy.deepcopy(self.bars[:-1])}
                fresh=copy.deepcopy(self.bars);fresh[-1].update(close=price,high=max(103,price))
                meta=board_chart.repair_completed([self.board],history,self.clock,Path(folder)/'cache.json',True,
                    lambda *_:(bad_name,fresh))
                self.assertEqual(meta['failed'],1);self.assertEqual(len(history['881001']),1)

    def test_intraday_does_not_fetch_or_complete_today(self):
        with tempfile.TemporaryDirectory() as folder:
            meta=board_chart.repair_completed([self.board],{'881001':self.bars[:-1]},datetime(2026,10,13,14),
                Path(folder)/'cache.json',True,lambda *_:self.fail('no close repair during trading'))
            self.assertEqual(meta['attempted'],0)

    def test_partial_year_response_uses_official_complete_today_ohlc(self):
        class Clock(datetime):
            @classmethod
            def now(cls):return cls(2026,10,13,16,10)
        with tempfile.TemporaryDirectory() as folder:
            partial=copy.deepcopy(self.bars);partial[-1]['close']=101
            histories={'881001':partial}
            with patch.object(board_chart,'datetime',Clock),patch('board_trend.parse_year',return_value=('示例',partial)),patch.object(board_chart,'fetch_today',return_value=('示例',self.bars[-1])) as today:
                meta=board_chart.repair_completed([self.board],histories,self.clock,Path(folder)/'cache.json',True)
            self.assertEqual(meta['repaired'],1);today.assert_called_once_with('881001','2026-10-13')
            self.assertEqual(board_chart.project(self.board,histories['881001'],self.clock)['bars'][-1]['close'],102)

    def test_today_endpoint_checks_code_date_and_full_ohlc(self):
        import json
        base={'1':'20261013','7':'100','8':'103','9':'99','11':'102','13':12000,'name':'示例'}
        for code,date,low in [('881001','20261013','99'),('881999','20261013','99'),('881001','20261012','99'),('881001','20261013','104')]:
            row=dict(base,**{'1':date,'9':low})
            response='callback('+json.dumps({'bk_'+code:row})+')'
            with patch('datafeed.http_get',return_value=response):
                if code=='881001' and date=='20261013' and low=='99':
                    self.assertEqual(board_chart.fetch_today('881001','2026-10-13')[1]['close'],102)
                else:
                    with self.assertRaises((ValueError,KeyError)):board_chart.fetch_today('881001','2026-10-13')


if __name__ == '__main__':
    unittest.main()
