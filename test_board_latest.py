"""最新指数、历史兼容、盘中确认和分时缓存边界。"""
from datetime import datetime, timedelta
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import board_quote as Q
import board_trend as B
from test_board_trend import sample


class LatestBoardTest(unittest.TestCase):
    def setUp(self):
        self.bars, self.days = sample()
        self.daily = B.calculate(self.bars, self.days, self.days[-1])
        self.daily.update(code='881281', name='电池')
        d = datetime.fromisoformat(self.days[-1])+timedelta(days=1)
        self.now = d.replace(hour=10, minute=5)
        self.quote = dict(code='881281', name='电池', date=d.date().isoformat(),
                          quote_at=self.now.isoformat(sep=' '), price=131, previous_close=129,
                          sampled_low=130, sampled_high=131, change_pct=(131/129-1)*100,
                          source='同花顺板块指数分时', price_basis='同花顺指数原值')

    def observe(self, quote=None, previous=None, session='早盘', now=None, daily=None, bars=None, days=None):
        return B.current_observation(daily or self.daily, bars or self.bars, days or self.days,
                                     quote or self.quote, now or self.now, session, previous)

    def test_current_price_rolls_ma_and_leaves_history_unchanged(self):
        old = copy.deepcopy((self.daily, self.bars))
        r = self.observe()
        self.assertTrue(r['strong_advance'])
        self.assertAlmostEqual(r['ma5'], sum([126,127,128,129,131])/5)
        self.assertEqual(r['ma5_prev'], self.daily['ma5'])
        self.assertEqual((self.daily, self.bars), old)
        self.assertEqual(r['atr20'], self.daily['atr20'])

    def test_old_date_and_overage_never_use_yesterday_state(self):
        q = dict(self.quote, quote_at=self.days[-1]+' 15:00:00')
        self.assertFalse(self.observe(q)['ready'])
        q = dict(self.quote, quote_at=self.now.replace(hour=9,minute=30).isoformat(sep=' '))
        r = self.observe(q)
        self.assertFalse(r['ready'])
        self.assertEqual(r['state'], '指数待更新')

    def test_exact_identity_and_previous_close_are_required(self):
        for changed in [dict(name='锂电池'), dict(code='881101'), dict(previous_close=129.1)]:
            self.assertFalse(self.observe(dict(self.quote, **changed))['ready'])

    def test_lunch_and_afternoon_boundaries(self):
        q = dict(self.quote, quote_at=self.now.replace(hour=11, minute=30).isoformat(sep=' '))
        noon = self.now.replace(hour=12, minute=50)
        self.assertTrue(self.observe(q, session='午间休市', now=noon)['ready'])
        q2 = dict(q, quote_at=self.now.replace(hour=11, minute=29).isoformat(sep=' '))
        self.assertFalse(self.observe(q2, session='午间休市', now=noon)['ready'])
        self.assertFalse(self.observe(q, session='午盘', now=noon.replace(hour=13,minute=1))['ready'])

    def test_auction_requires_actual_auction_quote(self):
        now = self.now.replace(hour=9, minute=20)
        self.assertFalse(self.observe(session='集合竞价',now=now)['ready'])
        q = dict(self.quote, quote_at=now.isoformat(sep=' '))
        self.assertTrue(self.observe(q,session='集合竞价',now=now)['ready'])

    def test_today_complete_is_not_appended_twice(self):
        bar = dict(self.bars[-1], date=self.quote['date'], open=131,close=131,low=130,high=132)
        bars = self.bars+[bar]
        days = self.days+[bar['date']]
        d = B.calculate(bars, days, days[-1]);d.update(code='881281',name='电池')
        r = self.observe(daily=d,bars=bars,days=days)
        self.assertEqual(r['ma5'],d['ma5'])
        self.assertEqual(r['confirmation'],'收盘确认')

    def test_new_strong_can_replace_old_weak_latch(self):
        bars,days = sample([100-i*.1 for i in range(30)])
        d = B.calculate(bars,days,days[-1]);d.update(code='881281',name='电池',weak=True,state='趋势转弱')
        q = dict(self.quote,previous_close=bars[-1]['close'],price=150,sampled_low=150)
        r = self.observe(q,daily=d,bars=bars,days=days)
        self.assertTrue(r['strong_advance'])
        self.assertFalse(r['weak'])

    def test_intraday_strong_background_survives_pullback(self):
        bars,days = sample([100-i*.1 for i in range(30)])
        d = B.calculate(bars,days,days[-1]);d.update(code='881281',name='电池')
        q = dict(self.quote,previous_close=bars[-1]['close'],price=150,sampled_low=150)
        first = self.observe(q,daily=d,bars=bars,days=days)
        q2 = dict(q,price=99,sampled_low=99,quote_at=(self.now+timedelta(minutes=5)).isoformat(sep=' '))
        r = self.observe(q2,previous=first,now=self.now+timedelta(minutes=5),daily=d,bars=bars,days=days)
        self.assertTrue(r['intraday_has_strong'])
        self.assertTrue(r['observing'])
        self.assertFalse(r['strong_advance'])
        self.assertEqual(r['state'],'趋势保持')

    def test_repeated_samples_do_not_confirm_second_reclaim_day(self):
        bars, days = sample([100+i for i in range(30)]+[122,125])
        d=B.calculate(bars,days,days[-1]);d.update(code='881281',name='电池')
        self.assertIsNotNone(d['first_ma10_break'])
        now=(datetime.fromisoformat(days[-1])+timedelta(days=1)).replace(hour=10,minute=5)
        q=dict(self.quote, date=now.date().isoformat(),quote_at=now.isoformat(sep=' '),previous_close=bars[-1]['close'],price=125,sampled_low=125)
        r=self.observe(q,now=now,daily=d,bars=bars,days=days)
        again=self.observe(q,now=now,previous=r,daily=d,bars=bars,days=days)
        self.assertEqual(r['reclaim_days'],again['reclaim_days'])
        self.assertFalse(again['repair_confirmed'])

    def test_incomplete_history_blocks_current_ma_conclusion(self):
        d=dict(self.daily,ready=False,reason='历史窗口有缺口')
        self.assertFalse(self.observe(daily=d)['ready'])

    def test_intraday_cannot_establish_second_completed_ma20_hold(self):
        bars,days=sample([100-i*.1 for i in range(29)]+[150])
        d=B.calculate(bars,days,days[-1]);d.update(code='881281',name='电池')
        self.assertTrue(d['strong_advance'])
        self.assertFalse(d['ma20_support_established'])
        q=dict(self.quote,price=151,previous_close=150,sampled_low=151)
        r=self.observe(q,daily=d,bars=bars,days=days)
        self.assertTrue(r['strong_advance'])
        self.assertFalse(r['ma20_support_established'])


class HistoryRevalidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'boards.db'
        self.bars,self.days=sample()
        B.save('881281',self.bars,'2025.js',self.path)
        self.corrected=copy.deepcopy(self.bars)
        self.corrected[-1].update(close=130,high=131)
        self.now=(datetime.fromisoformat(self.days[-1])+timedelta(days=3)).replace(hour=10,minute=5)
        self.quote=dict(code='881281',name='电池',date=self.now.date().isoformat(),quote_at=self.now.isoformat(sep=' '),
                        price=131,previous_close=130,sampled_low=130,sampled_high=131,
                        change_pct=(131/130-1)*100,source='同花顺板块指数分时',price_basis='同花顺指数原值')
        self.board=dict(name='电池',index_trend=B.calculate(self.bars,self.days,self.days[-1]))
        self.board['index_trend'].update(code='881281',name='电池',source='同花顺行业指数')

    def repair(self):
        return B.revalidate_history([self.board],{'881281':self.quote},self.days,self.now,'早盘',self.path)

    def test_complete_same_date_cache_is_revalidated_on_close_mismatch(self):
        with patch.object(B,'parse_year',return_value=(None,self.corrected)) as fetch:
            result=self.repair()
            self.assertEqual(result['repaired'],1)
            fetch.assert_called_once_with('881281','2025',revalidate=True)
        self.assertEqual(B.load('881281',self.path)[-1]['close'],130)
        current=B.current_observation(self.board['index_trend'],B.load('881281',self.path),self.days,self.quote,self.now,'早盘')
        self.assertTrue(current['ready'])
        self.assertAlmostEqual(current['ma5'],sum([126,127,128,130,131])/5)
        with patch.object(B,'parse_year') as fetch:
            self.assertEqual(self.repair()['needed'],0);fetch.assert_not_called()

    def test_bad_annual_is_not_saved_and_failure_is_throttled(self):
        original=B.load('881281',self.path)
        with patch.object(B,'parse_year',return_value=(None,self.bars)) as fetch:
            self.assertEqual(self.repair()['failed'],1)
            self.assertEqual(self.repair()['deferred'],1)
            self.assertEqual(fetch.call_count,1)
        self.assertEqual(B.load('881281',self.path),original)

    def test_wrong_name_network_failure_and_duplicate_dates_preserve_history(self):
        for returned,bars,error in [('错误名称',self.corrected,None),(None,self.corrected,OSError('offline')),
                                    (None,self.corrected+[self.corrected[-1]],None)]:
            # Independent attempts must not share the previous failure cooldown.
            # sqlite's transaction context does not close the Windows file handle.
            from contextlib import closing
            with closing(B.connect(self.path)) as con, con:con.execute('DELETE FROM board_fetch_state')
            with patch.object(B,'parse_year',return_value=(returned,bars),side_effect=error):
                self.assertEqual(self.repair()['failed'],1)
            self.assertEqual(B.load('881281',self.path)[-1]['close'],129)

    def test_stale_or_wrong_quote_identity_never_triggers_repair(self):
        for change in [dict(name='锂电池'),dict(code='881101'),dict(quote_at=self.days[-1]+' 15:00:00')]:
            original=self.quote;self.quote=dict(original,**change)
            with patch.object(B,'parse_year') as fetch:
                self.assertEqual(self.repair()['needed'],0);fetch.assert_not_called()
            self.quote=original

    def test_unfinished_today_bar_not_written_into_completed_history(self):
        today=dict(self.corrected[-1],date=self.quote['date'],close=131,high=132)
        with patch.object(B,'parse_year',return_value=(None,self.corrected+[today])):
            self.assertEqual(self.repair()['repaired'],1)
        self.assertEqual(B.load('881281',self.path)[-1]['date'],self.days[-1])


class QuoteCacheTest(unittest.TestCase):
    def setUp(self):
        clock=patch.object(Q,'datetime',wraps=datetime)
        self.clock=clock.start()
        self.clock.now.return_value=datetime(2026,10,9,10,6)
        self.addCleanup(clock.stop)

    def raw(self, at='1005', price=131):
        return 'callback('+json.dumps({'bk_881281':dict(name='电池',date='20261009',pre='129',
                 data='0930,130,1,1,1;'+at+','+str(price)+',1,1,1')})+')'

    def test_parser_uses_source_clock_and_rejects_bad_order(self):
        q=Q.parse(self.raw())['881281']
        self.assertEqual(q['quote_at'],'2026-10-09 10:05:00')
        self.assertEqual(q['sampled_low'],130)
        self.assertEqual(Q.parse(self.raw('0929')), {})

    def test_failed_or_older_fetch_cannot_retimestamp_good_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'quotes.json'
            with patch.object(Q.datafeed,'http_get',return_value=self.raw()):
                first=Q.fetch(['881281'],p)['881281']
            with patch.object(Q.datafeed,'http_get',side_effect=OSError('offline')):
                failed=Q.fetch(['881281'],p)['881281']
            with patch.object(Q.datafeed,'http_get',return_value=self.raw('1004',130)):
                older=Q.fetch(['881281'],p)['881281']
            for r in (failed,older):
                self.assertEqual(r['quote_at'],first['quote_at'])
                self.assertEqual(r['price'],first['price'])
                self.assertTrue(r['fetch_error'])

    def test_cache_revalidation_does_not_change_source_clock_or_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'quotes.json'
            with patch.object(Q.time,'time',return_value=1791525300), \
                 patch.object(Q.datafeed,'http_get',return_value=self.raw()) as get:
                quote=Q.fetch(['881281','881281'],p)['881281']
            self.assertEqual(get.call_count,1)
            self.assertEqual(get.call_args.kwargs['headers']['Cache-Control'],'no-cache')
            self.assertEqual(get.call_args.kwargs['headers']['Pragma'],'no-cache')
            self.assertEqual(get.call_args.kwargs['retry'],1)
            self.assertTrue(get.call_args.args[0].endswith('/last.js?refresh=5971751'))
            self.assertEqual(quote['quote_at'],'2026-10-09 10:05:00')
            self.assertEqual(json.loads(p.read_text(encoding='utf-8'))['fetch_version'],Q.VERSION)

    def test_partial_batch_preserves_missing_member_and_marks_only_that_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'quotes.json'
            with patch.object(Q.datafeed,'http_get',return_value=self.raw()):
                first=Q.fetch(['881281'],p)['881281']
                result=Q.fetch(['881281','881282'],p)
            self.assertNotIn('fetch_error',result['881281'])
            self.assertTrue(result['881282']['fetch_error'])
            self.assertEqual(result['881281']['quote_at'],first['quote_at'])

    def test_older_batch_is_repaired_by_single_source_without_rolling_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'quotes.json'
            with patch.object(Q.datafeed,'http_get',return_value=self.raw()):
                Q.fetch(['881281'],p)
            with patch.object(Q.datafeed,'http_get',side_effect=[self.raw('1004',130),self.raw('1006',132)]) as get:
                result=Q.fetch(['881281'],p)['881281']
            self.assertEqual(get.call_count,2)
            self.assertEqual(result['quote_at'],'2026-10-09 10:06:00')
            self.assertEqual(result['price'],132)
            self.assertNotIn('fetch_error',result)
            self.assertEqual(get.call_args.kwargs['retry'],0)

    def test_network_failure_does_not_trigger_supplement_storm(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Q.datafeed,'http_get',side_effect=OSError('HTTP 429')) as get:
                result=Q.fetch(['881281','881282'],Path(tmp)/'q.json')
            self.assertEqual(get.call_count,1)
            self.assertTrue(all(q.get('fetch_error') for q in result.values()))

    def test_single_stale_response_gets_one_https_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Q.datafeed,'http_get',side_effect=[self.raw('1000',130),self.raw('1000',130),self.raw('1006',132)]) as get:
                result=Q.fetch(['881281'],Path(tmp)/'q.json')['881281']
            self.assertEqual(get.call_count,3)
            self.assertTrue(get.call_args.args[0].startswith('https://d.10jqka.com.cn/'))
            self.assertEqual(result['quote_at'],'2026-10-09 10:06:00')
            self.assertNotIn('fetch_error',result)

    def test_empty_or_blocked_response_does_not_expand_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Q.datafeed,'http_get',return_value='<html>unavailable</html>') as get:
                result=Q.fetch(['881281','881282'],Path(tmp)/'q.json')
            self.assertEqual(get.call_count,1)
            self.assertTrue(all(q.get('fetch_error') for q in result.values()))

    def test_before_market_missing_index_clock_does_not_expand_requests(self):
        self.clock.now.return_value=datetime(2026,10,9,9,20)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Q.datafeed,'http_get',return_value=self.raw()) as get:
                Q.fetch(['881281'],Path(tmp)/'q.json')
            self.assertEqual(get.call_count,1)

    def test_future_cache_cannot_block_valid_early_quote(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'q.json'
            future=Q.parse(self.raw('1500',140))['881281']
            p.write_text(json.dumps({'quotes':{'881281':future}}),encoding='utf-8')
            with patch.object(Q.datafeed,'http_get',return_value=self.raw()) as get:
                result=Q.fetch(['881281'],p)['881281']
            self.assertEqual(result['quote_at'],'2026-10-09 10:05:00')
            self.assertNotIn('fetch_error',result)
            self.assertEqual(get.call_count,1)

    def test_future_response_never_replaces_good_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'q.json'
            with patch.object(Q.datafeed,'http_get',return_value=self.raw()):
                first=Q.fetch(['881281'],p)['881281']
            with patch.object(Q.datafeed,'http_get',return_value=self.raw('1500',140)) as get:
                result=Q.fetch(['881281'],p)['881281']
            self.assertEqual(result['quote_at'],first['quote_at'])
            self.assertEqual(result['fetch_error'],'指数报价时间超前')
            self.assertEqual(get.call_count,3)
            self.assertEqual(json.loads(p.read_text())['quotes']['881281']['quote_at'],first['quote_at'])

    def test_invalid_batch_clock_recovers_from_valid_single_quote(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Q.datafeed,'http_get',side_effect=[self.raw('1500',140),self.raw()]) as get:
                result=Q.fetch(['881281'],Path(tmp)/'q.json')['881281']
            self.assertEqual(get.call_count,2)
            self.assertEqual(result['quote_at'],'2026-10-09 10:05:00')
            self.assertNotIn('fetch_error',result)

    def test_auction_invalid_batch_clock_still_does_not_expand_requests(self):
        self.clock.now.return_value=datetime(2026,10,9,9,20)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Q.datafeed,'http_get',return_value=self.raw('1500',140)) as get:
                result=Q.fetch(['881281'],Path(tmp)/'q.json')['881281']
            self.assertEqual(get.call_count,1)
            self.assertNotIn('quote_at',result)
            self.assertEqual(result['fetch_error'],'指数报价时间超前')

    def test_invalid_clock_cache_is_evicted_even_on_network_failure(self):
        for at in ('1200','0929','1500'):
            with self.subTest(at=at), tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/'q.json'
                q=Q.parse(self.raw(at,140))['881281'] if at!='0929' else dict(Q.parse(self.raw())['881281'],quote_at='2026-10-09 09:29:00')
                p.write_text(json.dumps({'quotes':{'881281':q}}),encoding='utf-8')
                with patch.object(Q.datafeed,'http_get',side_effect=OSError('offline')):
                    result=Q.fetch(['881281'],p)['881281']
                self.assertNotIn('quote_at',result)
                self.assertEqual(json.loads(p.read_text())['quotes'],{})


if __name__ == '__main__':
    unittest.main()
