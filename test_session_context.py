"""竞价、昨日收盘衔接、复权尺度及过期报价边界。"""
import copy
from datetime import datetime,timedelta
import unittest
from unittest.mock import patch

import session_context as sc
import serve
from test_price_basis import history,quote

class ContextTests(unittest.TestCase):
    def build(self,price=101,at='09:16:00',session='集合竞价',captured=None,bars=None):
        bars=bars or history([80+i for i in range(21)])
        q=quote(last_close=100,price=price,at='2026-09-28 '+at)
        q.update(amount_wan=0,volume_shou=0)
        row={'code':'600001','name':'样本','daily_attack_tier':'A','trend_online':1,'stock_strength_score':80}
        snap={'session':session,'quote_capture_at':captured or '2026-09-28 '+at,
              'strength_model':{'asof':bars[-1]['date']},'stocks':[row]}
        model=sc.attach(snap,{'600001':q},{'600001':bars},[b['date'] for b in bars],
                        baseline={'600001':{'code':'600001'}})
        return row['session_context'],model

    def test_auction_zero_volume_has_price_judgment_and_yesterday_background(self):
        c,m=self.build()
        self.assertTrue(c['quote_valid']);self.assertTrue(c['price_basis_valid'])
        self.assertEqual(c['label'],'强股竞价承接');self.assertTrue(c['previous_close_board'])
        self.assertIsNotNone(c['gap_atr']);self.assertIsNotNone(c['price_attack_score'])
        self.assertIn('不能确认量价突破',c['reason']);self.assertEqual(m['structure_judged_count'],1)

    def test_short_history_keeps_price_and_available_mas_without_empty_comparison(self):
        for n in (1,7,15):
            c,m=self.build(bars=history([80+i for i in range(21)])[-n:])
            self.assertTrue(c['quote_valid']);self.assertTrue(c['partial_history'])
            self.assertIsNone(c['provisional_trend']);self.assertIsNone(c['available_ma']['20'])
            self.assertIn('有效日线',c['label']);self.assertIsNone(c['price_attack_score'])
            self.assertEqual(m['structure_judged_count'],0)

    def test_below_yesterday_ma20_is_weakened_even_if_yesterday_strong(self):
        c,_=self.build(80)
        self.assertEqual(c['label'],'竞价结构转弱');self.assertFalse(c['monitor_candidate'])

    def test_stale_auction_cannot_judge(self):
        c,m=self.build(captured='2026-09-28 09:19:01')
        self.assertFalse(c['quote_valid']);self.assertIsNone(c['price_attack_score']);self.assertEqual(m['auction_rows'],[])

    def test_prior_day_quote_cannot_judge(self):
        c,_=self.build(captured='2026-09-29 09:16:00')
        self.assertFalse(c['quote_valid'])

    def test_0925_last_price_usable_before_open(self):
        c,_=self.build(at='09:25:00',session='竞价结束',captured='2026-09-28 09:29:00')
        self.assertTrue(c['quote_valid']);self.assertEqual(c['auction_phase'],'竞价末价')

    def test_final_window_uses_latest_quotes_without_expiring_0925_result(self):
        for source in ('09:25:00', '09:26:00', '09:29:59'):
            c,m=self.build(price=102,at=source,session='竞价结束',captured='2026-09-28 09:29:59')
            self.assertTrue(c['quote_valid'],source)
            self.assertEqual(c['price'],102)
            self.assertEqual(m['price_judged_count'],1)
        c,_=self.build(at='09:29:59',session='早盘',captured='2026-09-28 09:30:00')
        self.assertFalse(c['quote_valid'])

    def test_final_scheduler_reads_latest_quote_without_an_archive(self):
        with patch.dict(serve.SNAPSHOT_META, snapshot_auction_latest_quote_at='2026-09-28 09:26:00'):
            self.assertTrue(serve.boundary_capture_done(datetime(2026,9,28,9,26,30),'auction_final'))
            self.assertFalse(serve.boundary_capture_done(datetime(2026,9,28,9,27,0),'auction_final'))

    def test_normal_zero_volume_does_not_reuse_auction_judgment(self):
        c,_=self.build(at='09:31:00',session='早盘')
        self.assertFalse(c['quote_valid'])

    def test_unknown_history_source_preserves_price_but_no_ma_inference(self):
        bars=history([80+i for i in range(21)],source='unknown')
        c,_=self.build(bars=bars)
        self.assertTrue(c['quote_valid']);self.assertFalse(c['price_basis_valid'])
        self.assertIn('结构口径待核验',c['label']);self.assertIsNone(c['price_attack_score'])

    def test_split_scale_history_maps_to_quote_and_does_not_mutate(self):
        bars=history([(80+i)*.99 for i in range(21)]);before=copy.deepcopy(bars)
        c,_=self.build(bars=bars)
        self.assertTrue(c['price_basis_valid']);self.assertEqual(c['prior_close'],100)
        self.assertAlmostEqual(c['gap_pct'],1);self.assertEqual(bars,before)

    def test_0920_cannot_cancel_stage(self):
        c,_=self.build(at='09:20:00');self.assertEqual(c['auction_phase'],'不可撤单阶段')

    def test_scheduler_starts_0915_and_refreshes_auction_each_minute(self):
        self.assertFalse(serve.is_trading_time(datetime(2026,9,28,9,14)))
        self.assertTrue(serve.is_trading_time(datetime(2026,9,28,9,15)))
        with patch.dict(serve.SNAPSHOT_META,{'snapshot_auction_latest_quote_at':'2026-09-28 09:15:00'}):
            self.assertTrue(serve.boundary_capture_done(datetime(2026,9,28,9,15,30),'auction_start'))
            self.assertFalse(serve.boundary_capture_done(datetime(2026,9,28,9,16),'auction_start'))

if __name__=='__main__':unittest.main()
