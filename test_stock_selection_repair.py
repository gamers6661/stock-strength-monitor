"""Regression cases for the audited scoring and source-clock defects."""
import unittest
from datetime import timedelta
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
import config
import stock_selection as S
import stock_selection_rollout as rollout
from test_stock_selection import sample


class Repair(unittest.TestCase):
    def test_weak_shrinking_stock_receives_no_consolidation_bonus(self):
        f=sample();bs=f[1][f[-1][1]]
        for i,b in enumerate(bs):
            p=100-i*.1;b.update(open=p,close=p,high=p+.2,low=p-.2,volume=1000000.)
        for b in bs[-5:]:b.update(high=b['close']+.05,low=b['close']-.05,volume=200000.)
        x=S.base_metrics(bs,{})
        self.assertLess(x['contraction'],1)
        self.assertEqual(x['contraction_score'],0)
        self.assertEqual(x['retention'],0)
        self.assertFalse(x['contraction_qualified'])

    def test_flat_stock_has_no_advance_to_preserve(self):
        f=sample();x=S.base_metrics(f[1][f[-1][1]],{})
        self.assertFalse(x['has_advance']);self.assertEqual(x['retention'],0)

    def test_intact_advance_can_receive_consolidation_bonus(self):
        f=sample();bs=f[1][f[-1][0]];p=bs[-6]['close']
        for b in bs[-5:]:b.update(open=p,close=p,high=p+.1,low=p-.1,volume=400000.)
        x=S.base_metrics(bs,{})
        self.assertTrue(x['prior_advance']);self.assertTrue(x['contraction_qualified'])
        self.assertGreater(x['contraction_score'],0)

    def test_broken_advance_cannot_receive_shrink_bonus(self):
        f=sample();bs=f[1][f[-1][0]]
        for b in bs[-5:]:b.update(open=95.,close=95.,high=95.1,low=94.9,volume=400000.)
        x=S.base_metrics(bs,{})
        self.assertTrue(x['prior_advance']);self.assertEqual(x['contraction_score'],0)

    def live(self,offsets):
        f=sample();code=f[-1][1];row=f[0]['stocks'][1]
        row.update(price=103.,high=103.,low=99.,open=100.,last_close=100.,change_pct=3.)
        frames=[(str(f[4]-timedelta(seconds=s)),{code:dict(at=str(f[4]-timedelta(seconds=s)),price=p)}) for s,p in offsets]
        return S.live_status(row,f[1][code],f[2],None,frames,f[4])

    def test_instant_break_and_continuous_hold_are_different_states(self):
        instant=self.live([]);held=self.live([(240,103.),(120,103.)])
        self.assertFalse(instant['held']);self.assertEqual(instant['state'],'瞬时突破待确认')
        self.assertTrue(held['held']);self.assertEqual(held['held_seconds'],240)
        self.assertEqual(held['state'],'突破守稳待收盘')
        self.assertNotEqual(instant['state'],held['state'])

    def test_old_tail_cannot_bridge_an_unsampled_gap(self):
        x=self.live([(500,103.),(380,103.)])
        self.assertFalse(x['held']);self.assertEqual(x['held_seconds'],0)

    def test_recovery_uses_observed_source_times(self):
        x=self.live([(240,103.),(120,100.)])
        self.assertEqual(x['recovery_seconds'],120)
        self.assertFalse(x['held'])

    def test_shadow_cannot_be_promoted_without_real_observations(self):
        with TemporaryDirectory(dir='D:/Temp/stock-monitor') as tmp,patch.object(config,'CACHE_DIR',Path(tmp)):
            rollout.save(rollout.root()/'rollout.json',dict(stage='shadow',started_at='2026-10-21',technical_acceptance=dict(min_distinct_source_samples=3)))
            with self.assertRaisesRegex(ValueError,'insufficient distinct'):rollout.accept()


if __name__=='__main__':unittest.main()
