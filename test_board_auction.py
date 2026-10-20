"""成员竞价汇总的数据有效性与日线隔离。"""
import copy
import unittest
from datetime import datetime, timedelta

import board_center
import config


class BoardAuctionTest(unittest.TestCase):
    def test_final_window_uses_supplier_timestamps_after_0925(self):
        s=self.snapshot('2026-10-12 09:29:59')
        for r in s['stocks']+s['coverage_catalog']:
            r['auction_observation']['quote_at']='2026-10-12 09:28:00'
        board_center.attach_auction(s)
        a=s['board_catalog'][0]['member_auction']
        self.assertTrue(a['ready'])
        self.assertEqual(a['change_pct'],.5)

    def snapshot(self, at='2026-10-12 09:25:15'):
        codes=[f'60000{i}' for i in range(8)]
        rows=[dict(code=c, change_pct=99, auction_observation=dict(
            quote_at='2026-10-12 09:25:00',price=10,change_pct=i-3)) for i,c in enumerate(codes)]
        board=dict(id='industry:测试',member_codes=codes,ranking_min_members=6,
                   member_today=99,member_quote_at='2026-10-09 15:00:00',
                   index_trend=dict(ready=True,ret1=8),
                   members=[dict(code=c,change_pct=99) for c in codes])
        return dict(quote_capture_at=at,stocks=rows[:4],coverage_catalog=rows[4:],board_catalog=[board])

    def test_equal_weight_counts_and_details_keep_daily_fields(self):
        s=self.snapshot();before=copy.deepcopy(s)
        board_center.attach_auction(s)
        b=s['board_catalog'][0];a=b['member_auction']
        self.assertTrue(a['ready']);self.assertEqual(a['change_pct'],.5)
        self.assertEqual(a['valid_count'],8);self.assertEqual(a['up_pct'],50)
        self.assertEqual(a['coverage_pct'],100)
        self.assertEqual([m['auction_change_pct'] for m in b['members']],list(range(-3,5)))
        for key in ('member_today','member_quote_at','index_trend'):
            self.assertEqual(b[key],before['board_catalog'][0][key])
        self.assertEqual(s['stocks'],before['stocks'])

    def test_invalid_date_future_stale_price_and_change_excluded(self):
        changes=[dict(quote_at='2026-10-09 09:25:00'),dict(quote_at='2026-10-12 09:29:00'),
                 dict(quote_at='2026-10-12 09:15:00'),dict(price=0),dict(change_pct=float('nan'))]
        for changed in changes:
            with self.subTest(changed=changed):
                s=self.snapshot('2026-10-12 09:26:00')
                s['stocks'][0]['auction_observation'].update(changed)
                board_center.attach_auction(s)
                self.assertEqual(s['board_catalog'][0]['member_auction']['valid_count'],7)
                self.assertIsNone(s['board_catalog'][0]['members'][0]['auction_change_pct'])

    def test_batch_skew_and_small_sample_do_not_get_ranked_values(self):
        s=self.snapshot()
        skew=config.INTRADAY['max_quote_batch_skew_seconds']+1
        early=(datetime(2026,10,12,9,25)-timedelta(seconds=skew)).isoformat(sep=' ')
        for r in s['stocks'][:3]:r['auction_observation']['quote_at']=early
        board_center.attach_auction(s)
        a=s['board_catalog'][0]['member_auction']
        self.assertFalse(a['ready']);self.assertEqual(a['valid_count'],5)
        self.assertIsNone(a['change_pct']);self.assertIsNone(a['up_pct'])

    def test_missing_and_zero_change_are_distinct(self):
        s=self.snapshot()
        s['stocks'][0]['auction_observation']['change_pct']=0
        s['stocks'][1]['auction_observation']['change_pct']=None
        board_center.attach_auction(s)
        b=s['board_catalog'][0]
        self.assertEqual(b['member_auction']['valid_count'],7)
        self.assertEqual(b['members'][0]['auction_change_pct'],0)
        self.assertIsNone(b['members'][1]['auction_change_pct'])

    def test_each_auction_boundary_and_duplicate_members(self):
        for stamp in ('09:15:00','09:20:00','09:25:00'):
            s=self.snapshot('2026-10-12 '+stamp)
            for r in s['stocks']+s['coverage_catalog']:r['auction_observation']['quote_at']='2026-10-12 '+stamp
            s['board_catalog'][0]['member_codes'].append('600000')
            board_center.attach_auction(s)
            a=s['board_catalog'][0]['member_auction']
            self.assertTrue(a['ready']);self.assertEqual(a['pool_count'],8)
            self.assertEqual(a['quote_at'],'2026-10-12 '+stamp)


if __name__=='__main__':
    unittest.main()
