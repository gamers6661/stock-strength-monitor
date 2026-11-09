"""Targeted quality and current invalidation regression cases."""
import copy
from datetime import datetime,timedelta
import unittest
from unittest.mock import patch

import stock_selection as S
from stock_selection_quality import assess
from stock_selection_rules import QUALITY


def history():
    rows=[]
    for i in range(30):
        price=100.+i
        rows.append(dict(date=str((datetime(2026,9,1)+timedelta(days=i)).date()),
                         open=price,close=price+1,high=price+1.2,low=price-.2,volume=100.,
                         price_basis='qfq',price_basis_source='tencent_qfqday'))
    return rows


def append(rows,opening,close,high,low,volume):
    date=datetime.fromisoformat(rows[-1]['date'])+timedelta(days=1)
    rows.append(dict(date=str(date.date()),open=opening,close=close,high=high,low=low,volume=volume,
                     price_basis='qfq',price_basis_source='tencent_qfqday'))


class QualityTests(unittest.TestCase):
    def assess(self,bars):return assess(bars,2.,70.,True,QUALITY)

    def test_positive_close_with_large_gap_fade_is_supply_not_full_demand(self):
        bars=history();previous=bars[-1]['close']
        append(bars,previous*1.10,previous*1.03,previous*1.10,previous*1.01,1200.)
        q=self.assess(bars)
        self.assertGreater(q['day_results'][-1]['close_move_atr'],0.)
        self.assertLess(q['day_results'][-1]['direction'],0.)
        self.assertGreater(q['distribution_pressure'],.5)
        self.assertLess(q['volume_participation'],100.)

    def test_large_volume_healthy_advance_is_not_distribution(self):
        bars=history();previous=bars[-1]['close']
        append(bars,previous,previous+4,previous+4,previous,1200.)
        q=self.assess(bars)
        self.assertEqual(q['distribution_pressure'],0.)
        self.assertEqual(q['damage_multiplier'],1.)
        self.assertGreater(q['last_day_result'],80.)

    def test_one_price_gap_recovers_credit_after_three_observed_holds(self):
        bars=history();price=bars[-1]['close']*1.1
        append(bars,price,price,price,price,60.)
        first=self.assess(bars);frozen=copy.deepcopy(first)
        self.assertLess(first['impulse_multiplier'],1.)
        for _ in range(3):
            price=bars[-1]['close'];append(bars,price,price+1,price+1,price-.1,100.)
        confirmed=self.assess(bars)
        self.assertEqual(confirmed['confirmed_follow_days'],3)
        self.assertEqual(confirmed['impulse_multiplier'],1.)
        self.assertEqual(first,frozen)

    def test_recovery_above_failed_bar_high_clears_old_pressure(self):
        bars=history();price=bars[-1]['close']
        append(bars,price*1.1,price*1.03,price*1.1,price*1.01,1200.)
        self.assertGreater(self.assess(bars)['distribution_pressure'],0.)
        high=bars[-1]['high'];append(bars,bars[-1]['close'],high+1,high+1,bars[-1]['close'],100.)
        self.assertEqual(self.assess(bars)['distribution_pressure'],0.)

    def test_missing_volume_is_unknown_and_does_not_shortcut_window(self):
        bars=history();bars[-3]['volume']=None
        q=self.assess(bars)
        self.assertFalse(q['volume_available'])
        self.assertIsNone(q['volume_participation'])
        self.assertIsNone(q['distribution_pressure'])
        m=S.base_metrics(bars,{})
        self.assertIsNone(m['volume']);self.assertFalse(m['volume_valid'])

    def test_local_retention_does_not_reward_unproven_sideways_base(self):
        q=assess(history(),2.,0.,False,QUALITY)
        self.assertEqual(q['local_retention'],0.)
        self.assertEqual(q['retention'],0.)


class WeakStateTests(unittest.TestCase):
    def live(self,price,opening,valid=True):
        bars=history();now=datetime(2026,10,29,10)
        row=dict(code='000058',quote_at=str(now),price=price,open=opening,high=max(price,opening)+1,
                 low=min(price,opening),last_close=100.,amount_wan=1.,volume_shou=100.)
        with patch.object(S.market_strength,'quote_valid',return_value=(valid,now,'stale' if not valid else None)),patch.object(S.intraday,'align_price_basis',return_value=dict(valid=True,scale_factor=1.,atr20=2.)):
            return S.live_status(row,bars,[b['date'] for b in bars],None,[],now)

    def test_gap_down_limit_at_its_open_is_weak(self):
        self.assertEqual(self.live(90.,90.)['state'],'转弱')

    def test_large_loss_is_weak_even_when_rebounding_from_open(self):
        self.assertEqual(self.live(96.,92.)['state'],'转弱')

    def test_small_loss_and_stale_quote_are_not_promoted_to_confirmed_weakness(self):
        self.assertNotEqual(self.live(99.,99.)['state'],'转弱')
        stale=self.live(90.,90.,False)
        self.assertFalse(stale['available']);self.assertEqual(stale['state'],'判断暂停')


if __name__=='__main__':unittest.main()
