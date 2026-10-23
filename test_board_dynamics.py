"""Source-time, common-cohort, state and isolation contracts for the boards page."""
import copy
import json
import unittest
from datetime import datetime, timedelta
import board_dynamics as B


def fixture(steps=7, move=None, board_score=None, stock_score=None):
    codes=['600%03d'%i for i in range(12)]
    controls=['000%03d'%i for i in range(12)]
    board=dict(id='theme:示例',name='示例',type='theme',catalog_listed=True,member_codes=codes,
        market_strength=dict(expected_codes=codes,trend_score=72.,emotion_score=70.,trend_strong=True,
            emotion_strong=True,dominant_period=5,phase='推进',history_trend=[dict(date='2026-10-15',score=75.)],
            trend_parts_by_period={'5':dict(K=.95,health=1.)},reasons=[]))
    ring=[]
    for step in range(steps):
        at=datetime(2026,10,16,9,40)+timedelta(minutes=5*step)
        values={}
        for i,c in enumerate(codes):
            ret=move(step,i) if move else -.8+.25*step+i*.005
            score=stock_score(step,i) if stock_score else 70. if step>=3+i//3 else 45.
            values[c]=[ret,score,score]
        values.update({c:[step*.03,30.,30.] for c in controls})
        score=board_score(step) if board_score else 70. if step>=4 else 55.
        ring.append(dict(at=str(at),version='v',pool_hash='pool',stocks=values,
            quote_evidence={c:dict(at=str(at),return_pct=v[0]) for c,v in values.items()},
            boards={board['id']:dict(trend=score,emotion=score,membership=B.membership(codes))}))
    return dict(session='早盘',quote_capture_at=ring[-1]['at'],market_strength=dict(implementation_hash='v'),
        direction_observations=ring,stocks=[dict(code=c,name='股'+c) for c in codes+controls],board_catalog=[board])


def row(s):
    return B.build(s)['by_id']['theme:示例']


class BoardDynamicsTests(unittest.TestCase):
    def retime(self,s,times):
        for point,at in zip(s['direction_observations'],times):
            point['at']=at
            for q in point['quote_evidence'].values():q['at']=at
        s['quote_capture_at']=times[-1]
        return s

    def test_latest_two_any_gap(self):
        for times in [
            ['2026-10-16 09:40:00','2026-10-16 09:41:00'],
            ['2026-10-16 09:40:00','2026-10-16 11:20:00'],
            ['2026-10-16 11:25:00','2026-10-16 13:05:00'],
            ['2026-10-15 14:55:00','2026-10-16 09:40:00']]:
            s=self.retime(fixture(steps=2),times);w=row(s)['change']
            self.assertEqual(w['from_at'],times[0]);self.assertEqual(w['to_at'],times[1])
            self.assertAlmostEqual(w['delta_pp'],.25)
            self.assertNotIn('speed_pp15',w)

    def test_close_reads_collapse_to_one_trading_point(self):
        s=self.retime(fixture(steps=3),['2026-10-16 14:55:00','2026-10-16 15:05:25','2026-10-16 16:15:00'])
        s.update(session='已收盘',close_daily_verified_at='2026-10-16 16:20:00')
        w=row(s)['change']
        self.assertEqual(w['from_at'],'2026-10-16 14:55:00')
        self.assertEqual(w['to_at'],'2026-10-16 15:00:00')
        self.assertEqual(len(B.samples(s)),2)
        self.assertAlmostEqual(w['delta_pp'],.5)
        s['direction_observations']=s['direction_observations'][1:]
        self.assertIsNone(row(s)['change'])

    def test_future_closing_read_cannot_replace_known_close(self):
        s=self.retime(fixture(steps=3),['2026-10-16 14:55:00','2026-10-16 15:05:00','2026-10-16 18:00:00'])
        s.update(session='已收盘',close_daily_verified_at='2026-10-16 15:07:00',quote_capture_at='2026-10-16 16:15:00')
        self.assertAlmostEqual(row(s)['change']['delta_pp'],.25)

    def test_non_trading_fetch_times_are_not_quotes(self):
        for at in ['2026-10-16 09:29:59','2026-10-16 11:30:01','2026-10-16 12:00:00','2026-10-16 15:00:01']:
            s=self.retime(fixture(steps=1),[at])
            self.assertEqual(B.samples(s),[])

    def test_delayed_capture_preserves_trading_quote_time(self):
        s=self.retime(fixture(steps=2),['2026-10-16 14:50:00','2026-10-16 14:55:00'])
        s['direction_observations'][-1]['at']='2026-10-16 16:15:00'
        s['quote_capture_at']='2026-10-16 16:15:00'
        self.assertEqual(row(s)['change']['to_at'],'2026-10-16 14:55:00')

    def test_latest_qualified_pair_skips_incomplete_record(self):
        s=fixture(steps=3)
        s['direction_observations'][1]['stocks']={}
        w=row(s)['change']
        self.assertEqual(w['from_at'],s['direction_observations'][0]['at'])
        self.assertEqual(w['to_at'],s['direction_observations'][2]['at'])

    def test_two_points_suffice_for_judgment(self):
        s=fixture(steps=2,move=lambda t,i:1+t,stock_score=lambda t,i:70)
        r=row(s);self.assertTrue(r['confirmed']['attack']);self.assertIsNone(r['confirmation_at'])

    def test_source_order_not_record_order(self):
        s=fixture();s['direction_observations'].reverse()
        w=row(s)['change'];self.assertEqual(w['from_at'],'2026-10-16 10:05:00')
        self.assertEqual(w['to_at'],'2026-10-16 10:10:00')

    def test_duplicate_source_not_second_point(self):
        s=fixture(steps=1);s['direction_observations'].append(copy.deepcopy(s['direction_observations'][0]))
        self.assertIsNone(row(s)['change'])

    def test_future_source_excluded(self):
        s=fixture(steps=3);s['quote_capture_at']=s['direction_observations'][1]['at']
        self.assertEqual(row(s)['change']['to_at'],s['quote_capture_at'])

    def test_changed_members_use_fixed_available_cohort(self):
        s=fixture();s['board_catalog'][0]['member_codes'].append('600999')
        s['board_catalog'][0]['market_strength']['expected_codes'].append('600999')
        w=row(s)['change'];self.assertEqual(w['common_count'],12);self.assertEqual(w['expected'],13)

    def test_pool_change_uses_shared_quotes(self):
        s=fixture();s['direction_observations'][-1]['pool_hash']='new'
        self.assertIsNotNone(row(s)['change'])

    def test_frozen_member_quotes_cannot_drive_change(self):
        s=fixture()
        for sample in s['direction_observations']:
            for c in ['600000','600001','600002']:sample['quote_evidence'][c]['at']='2026-10-16 10:00:00'
        self.assertIsNone(row(s)['change'])

    def test_no_price_move_is_not_attack(self):
        r=row(fixture(move=lambda t,i:1.,stock_score=lambda t,i:40+8*t))
        self.assertFalse(r['confirmed']['attack'])

    def test_isolation_and_version(self):
        s=fixture();before=copy.deepcopy(s);row(s);self.assertEqual(s,before)
        s['market_strength']['implementation_hash']='new';self.assertIsNone(row(s)['change'])

    def test_missing_is_not_zero(self):
        s=fixture();s['direction_observations']=[];r=row(s)
        self.assertEqual(r['current'],{});self.assertIsNone(r['change'])

    def test_auction_keeps_distinct_mode(self):
        s=fixture();s['session']='集合竞价';self.assertEqual(row(s)['status'],'待开盘')


if __name__=='__main__':unittest.main()
