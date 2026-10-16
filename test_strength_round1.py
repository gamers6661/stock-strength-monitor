"""Behavioral regressions for current weakening, cycle conflict and quote paths."""
import copy
import unittest
from datetime import datetime,timedelta

import market_strength as M
from test_market_strength import fixture,run
from test_owner_strength_rebuild import prices


class CurrentTrend(unittest.TestCase):
    def test_large_drop_cannot_remain_very_strong_on_old_gains(self):
        f=fixture();c=next(iter(f[1]))
        prices(f,c,[100+i*2 for i in range(20)],138*.92)
        m=run(f)[c]
        self.assertLess(m['trend_score'],65)
        self.assertEqual(m['trend_selection']['health_factor'],.5)
        self.assertGreater(m['trend_selection']['base'],m['trend_score'])

    def test_small_negative_day_does_not_destroy_existing_trend(self):
        f=fixture();c=next(iter(f[1]))
        prices(f,c,[100+i*1.2 for i in range(20)],122.8*.995)
        m=run(f)[c]
        self.assertTrue(m['trend_strong'])
        self.assertEqual(m['trend_selection']['health_factor'],1)

    def test_strong_absolute_advances_still_separate_after_reference(self):
        scores=[M.period_score(r,95,1,8)['T'] for r in [8,16,32]]
        self.assertTrue(scores[0]<scores[1]<scores[2]<100)
        self.assertAlmostEqual(scores[-1]-scores[0],7.2)

    def test_curve_does_not_promote_slow_advances_by_high_percentile(self):
        for gain,scale in [(2.5,8),(3,12),(5,20)]:
            self.assertLess(M.period_score(gain,95,1,scale)['T'],65)
        self.assertEqual(M.period_score(6,95,1,8)['A'],75)

    def test_ma_and_drawdown_boundaries_are_continuous(self):
        for x in [0,1.5,2.5,3.5]:
            self.assertLess(abs(M.structure(100,100,100,x+1e-5,1)-M.structure(100,100,100,x-1e-5,1)),1e-4)
        self.assertLess(abs(M.structure(100.01,100,99,0,1)-M.structure(99.99,100,99,0,1)),.01)

    def test_short_cycle_conflict_lowers_long_cycle_rank(self):
        weak={'5':dict(T=20,health=1),'20':dict(T=95,health=1)}
        strong={'5':dict(T=70,health=1),'20':dict(T=95,health=1)}
        self.assertLess(M.choose(weak)[0],M.choose(strong)[0])
        self.assertGreater(M.choose(weak)[0],65)  # a recovering long trend can remain strong

    def test_missing_long_cycle_does_not_block_short_start(self):
        self.assertEqual(M.choose({'5':dict(T=75,health=1),'20':dict(T=None)}),(75,5))

    def test_missing_short_cycle_is_not_invented_weakness(self):
        self.assertEqual(M.choose({'5':dict(T=None),'20':dict(T=75,health=1)}),(75,20))

    def test_lower_day_price_monotonically_reduces_health(self):
        bars=[dict(close=100) for _ in range(3)]
        factors=[M.trend_health(p,bars)['factor'] for p in [100,99,97,94,92]]
        self.assertEqual(factors,sorted(factors,reverse=True))

    def test_emotion_input_does_not_modify_trend(self):
        f=fixture();c=next(iter(f[1]));prices(f,c,[100+i for i in range(20)],120)
        first=run(f)[c]['trend_score']
        f[1][c].update(open=110,low=108,high=125)
        self.assertEqual(first,run(f)[c]['trend_score'])


class EmotionSequence(unittest.TestCase):
    def recent(self,returns):
        f=fixture();c=next(iter(f[1]));value=100;bars=f[3][c][-6:]
        for i,b in enumerate(bars):
            if i:value*=1+returns[i-1]/100
            b.update(open=value,close=value,high=value+.1,low=value-.1)
        return M.recent_emotion(bars,10,f[4])

    def test_recent_damage_matters_more_than_old_damage(self):
        recovering=self.recent([-10,3,3,3,3])
        damaged=self.recent([3,3,3,-10,3])
        self.assertAlmostEqual(recovering['gain'],damaged['gain'])
        self.assertGreater(recovering['score'],damaged['score'])

    def test_persistent_advance_stays_high(self):
        self.assertAlmostEqual(self.recent([3,3,3,3,3])['score'],100)

    def test_flat_and_declining_history_do_not_get_activity_points(self):
        self.assertEqual(self.recent([0]*5)['score'],0)
        self.assertEqual(self.recent([-3]*5)['score'],0)

    def q(self):
        return dict(quote_at='2026-10-13 10:20:00',change_pct=5.,limit_pct=10.)

    def obs(self,value,at='2026-10-13 10:00:00',limit=10):
        return {'at':at,'return':value,'limit_pct':limit}

    def test_same_current_quote_distinguishes_advancing_and_retreating(self):
        rising=M.emotion_path(self.q(),[self.obs(3)])
        falling=M.emotion_path(self.q(),[self.obs(7)])
        self.assertGreater(rising['score'],falling['score'])
        self.assertTrue(rising['available']);self.assertEqual(rising['samples'],2)

    def test_held_strong_position_better_than_flat_low_position(self):
        held=M.emotion_path(self.q(),[self.obs(5)])
        q=self.q();q['change_pct']=0
        flat=M.emotion_path(q,[self.obs(0)])
        self.assertGreater(held['score'],flat['score'])

    def test_insufficient_history_is_neutral_and_not_rejection(self):
        for obs in [[],[self.obs(3,'2026-10-13 10:19:00')]]:
            p=M.emotion_path(self.q(),obs)
            self.assertEqual(p['score'],50);self.assertFalse(p['available'])

    def test_future_other_day_old_and_other_limit_samples_are_rejected(self):
        for obs in [self.obs(3,'2026-10-13 10:21:00'),self.obs(3,'2026-10-12 10:00:00'),
                    self.obs(3,'2026-10-13 09:00:00'),self.obs(3,limit=20)]:
            self.assertFalse(M.emotion_path(self.q(),[obs])['available'])

    def test_duplicate_sample_does_not_create_duration(self):
        sample=self.obs(3,'2026-10-13 10:19:00')
        self.assertFalse(M.emotion_path(self.q(),[sample]*100)['available'])

    def test_pipeline_reuses_raw_path_and_repeated_quote_stays_stable(self):
        f=fixture();c=next(iter(f[1]));s,q,p,h,cal,now=f
        q[c].update(price=103,high=103,change_pct=3)
        M.attach(s,q,p,h,cal,now=now)
        previous=copy.deepcopy(s)
        later=now+timedelta(minutes=20)
        for quote in q.values():quote['quote_at']=str(later)
        q[c].update(price=105,high=105,change_pct=5)
        M.attach(s,q,p,h,cal,now=later,previous=previous);M.validate(s)
        ep=s['stocks'][0]['market_strength']['emotion_parts']
        self.assertTrue(ep['path']['available'])
        self.assertGreater(ep['H'],.75*ep['H_snapshot']+.25*50)
        saved=copy.deepcopy(s)
        M.attach(s,q,p,h,cal,now=later,previous=saved);M.validate(s)
        self.assertEqual(s['stocks'][0]['market_strength']['emotion_score'],saved['stocks'][0]['market_strength']['emotion_score'])
        self.assertEqual(s['emotion_observations'],saved['emotion_observations'])

    def test_pool_change_does_not_reuse_raw_path(self):
        f=fixture();s,q,p,h,cal,now=f
        M.attach(s,q,p,h,cal,now=now)
        old=copy.deepcopy(s);old['emotion_observations'][0]['pool_hash']='other'
        for obs in old['direction_observations']:obs['pool_hash']='other'
        later=now+timedelta(minutes=20)
        for quote in q.values():quote['quote_at']=str(later)
        M.attach(s,q,p,h,cal,now=later,previous=old)
        self.assertFalse(s['stocks'][0]['market_strength']['emotion_parts']['path']['available'])


if __name__=='__main__':unittest.main()
