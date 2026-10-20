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
    def test_only_new_projection_no_mutation(self):
        s=fixture();before=copy.deepcopy(s);m=B.build(s)
        self.assertEqual(s,before);self.assertEqual(set(m['by_id']),{'theme:示例'})

    def test_confirmed_turning_and_expansion(self):
        r=row(fixture())
        self.assertEqual(r['status'],'转强');self.assertEqual(r['lane'],'priority')
        self.assertIn('扩散',r['tags']);self.assertTrue(r['confirmed']['attack'])
        self.assertGreaterEqual(r['change']['strong_delta'],2)

    def test_acceleration_requires_two_positive_intervals(self):
        r=row(fixture(move=lambda t,i:.5+.03*t*t,stock_score=lambda t,i:70.))
        self.assertTrue(r['confirmed']['accelerating']);self.assertIn('加速',r['tags'])
        self.assertGreater(r['change']['acceleration_pp15'],0)

    def test_one_positive_interval_is_not_acceleration(self):
        r=row(fixture(steps=4,move=lambda t,i:1.+.4*t,stock_score=lambda t,i:70.))
        self.assertIsNone(r['change']['previous_speed_pp15']);self.assertNotIn('加速',r['tags'])

    def test_relative_score_change_without_actual_move_is_not_attack(self):
        r=row(fixture(move=lambda t,i:1.,board_score=lambda t:40.+8*t,stock_score=lambda t,i:40.+8*t))
        self.assertFalse(r['confirmed']['attack']);self.assertNotEqual(r['lane'],'priority')

    def test_broad_market_rise_does_not_alone_create_attack(self):
        s=fixture()
        for step,sample in enumerate(s['direction_observations']):
            for code in sample['stocks']:
                if code.startswith('000'):sample['stocks'][code][0]=step*1.
        r=row(s);self.assertFalse(r['confirmed']['attack']);self.assertLess(r['change']['excess_pp15'],0)

    def test_fading_requires_prior_strength_and_two_observations(self):
        s=fixture(move=lambda t,i:2.-.3*t,stock_score=lambda t,i:70. if t<3+i//3 else 40.)
        r=row(s);self.assertEqual(r['status'],'退潮');self.assertEqual(r['lane'],'cooling')
        s['board_catalog'][0]['market_strength']['history_trend']=[]
        for sample in s['direction_observations']:
            sample['boards']['theme:示例'].update(trend=40.,emotion=40.)
        self.assertNotEqual(row(s)['lane'],'cooling')

    def test_waiting_requires_real_history_and_structure(self):
        s=fixture(move=lambda t,i:1.,stock_score=lambda t,i:50.)
        r=row(s);self.assertEqual(r['lane'],'waiting');self.assertIn('等待',r['status'])
        s['board_catalog'][0]['market_strength']['history_trend']=[]
        self.assertNotEqual(row(s)['lane'],'waiting')
        s=fixture(move=lambda t,i:1.)
        s['board_catalog'][0]['market_strength']['trend_parts_by_period']['5']['K']=.5
        self.assertNotEqual(row(s)['lane'],'waiting')

    def test_repeated_source_never_adds_confirmation(self):
        s=fixture(steps=4);sample=copy.deepcopy(s['direction_observations'][-1]);sample['at']='2026-10-16 10:08:00'
        s['direction_observations'].append(sample)
        self.assertEqual(len(B.samples(s)),4);self.assertFalse(row(s)['confirmed']['attack'])

    def test_capture_clock_does_not_replace_source_clock(self):
        s=fixture();s['direction_observations'][-1]['at']='2026-10-16 10:17:00'
        self.assertEqual(B.build(s)['source_at'],'2026-10-16 10:10:00')

    def test_formal_close_has_one_boundary_and_preserves_source_time(self):
        s=fixture(steps=4);s['session']='已收盘';s['close_daily_verified_at']='2026-10-16 15:06:00'
        for sample,at in zip(s['direction_observations'],['2026-10-16 14:30:00','2026-10-16 14:45:00','2026-10-16 15:01:30','2026-10-16 15:05:00']):
            sample['at']=at
            for q in sample['quote_evidence'].values():q['at']=at
        ring=B.samples(s);self.assertEqual(len(ring),3)
        self.assertEqual(str(ring[-1]['at']),'2026-10-16 15:00:00')
        self.assertEqual(str(ring[-1]['source_at']),'2026-10-16 15:05:00')
        self.assertEqual(row(s)['change']['minutes'],15.)

    def test_unknown_scores_are_not_counted_as_weak_members(self):
        s=fixture()
        for sample in s['direction_observations']:
            for c in ['600000','600001','600002']:sample['stocks'][c][1:]=[None,None]
        self.assertEqual(row(s)['lane'],'pending')

    def test_stale_history_is_not_a_current_opportunity(self):
        s=fixture();s['quote_capture_at']='2026-10-16 10:30:00'
        self.assertEqual(row(s)['status'],'报价待更新');self.assertEqual(row(s)['lane'],'pending')

    def test_midday_retains_original_morning_comparison(self):
        s=fixture();s['session']='午间休市';s['quote_capture_at']='2026-10-16 11:50:00'
        self.assertEqual(row(s)['source_at'],'2026-10-16 10:10:00');self.assertEqual(B.build(s)['mode'],'午休参考')

    def test_member_change_stops_window(self):
        s=fixture();s['board_catalog'][0]['member_codes'].append('600999')
        self.assertEqual(row(s)['lane'],'pending');self.assertIsNone(row(s)['change'])

    def test_source_version_change_stops_comparison(self):
        s=fixture();s['market_strength']['implementation_hash']='new'
        self.assertEqual(row(s)['lane'],'pending');self.assertIsNone(row(s)['source_at'])

    def test_changed_pool_cannot_compare(self):
        s=fixture();s['direction_observations'][-1]['pool_hash']='different'
        self.assertIsNone(row(s)['change'])

    def test_stale_members_stay_in_denominator(self):
        s=fixture()
        for sample in s['direction_observations']:
            for c in ['600000','600001','600002']:sample['quote_evidence'][c]['at']='2026-10-16 09:30:00'
        self.assertEqual(row(s)['lane'],'pending')

    def test_frozen_individual_quotes_cannot_support_window(self):
        s=fixture()
        for sample in s['direction_observations']:
            for c in ['600000','600001','600002']:
                sample['quote_evidence'][c]['at']='2026-10-16 10:00:00'
        self.assertIsNone(row(s)['change'])

    def test_missing_is_not_zero(self):
        s=fixture();s['direction_observations']=[]
        r=row(s);self.assertEqual(r['current'],{});self.assertIsNone(r['change']);self.assertEqual(r['lane'],'pending')

    def test_never_compare_across_lunch(self):
        s=fixture(steps=2)
        for sample,at in zip(s['direction_observations'],['2026-10-16 11:25:00','2026-10-16 13:05:00']):
            sample['at']=at
            for q in sample['quote_evidence'].values():q['at']=at
        self.assertIsNone(row(s)['change'])

    def test_auction_does_not_claim_current_strength(self):
        s=fixture();s['session']='集合竞价'
        self.assertEqual(row(s)['status'],'待开盘');self.assertEqual(B.build(s)['counts'],{'pending':1})

    def test_unequal_windows_use_elapsed_minutes(self):
        s=fixture()
        for i,sample in enumerate(s['direction_observations']):
            at=str(datetime(2026,10,16,9,40)+timedelta(minutes=4*i))
            sample['at']=at
            for q in sample['quote_evidence'].values():q['at']=at
        w=row(s)['change'];self.assertAlmostEqual(w['speed_pp15'],w['delta_pp']*15/w['minutes'],3)

    def test_official_catalog_only_and_overlap_explained(self):
        s=fixture();b=copy.deepcopy(s['board_catalog'][0]);b.update(id='industry:示例行业',name='示例行业',type='industry')
        s['board_catalog'].append(b)
        for sample in s['direction_observations']:sample['boards'][b['id']]=copy.deepcopy(sample['boards']['theme:示例'])
        m=B.build(s);self.assertEqual(len(m['by_id']),2);self.assertTrue(any(r['overlaps'] for r in m['by_id'].values()))
        b['catalog_listed']=False;self.assertEqual(len(B.build(s)['by_id']),1)

    def test_weights_do_not_switch_when_member_rank_changes(self):
        s=fixture();end=s['direction_observations'][-1]
        end['stocks']['600000'][0]=15.
        w=row(s)['change'];self.assertNotIn('600000',w['weighted_codes'])
        self.assertEqual(len(w['weighted_codes']),10)


if __name__=='__main__':unittest.main()
