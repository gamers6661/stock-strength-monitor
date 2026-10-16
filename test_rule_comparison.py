import unittest
from research.rules_20260929.compare import outcome, rankings
from test_strength import bars


class RuleComparisonTests(unittest.TestCase):
    def test_next_open_and_delayed_locked_exit(self):
        bs=bars(15,0); dates=[b['date'] for b in bs]
        bs[1].update(open=10.5,close=10.5,high=10.6,low=10.4)
        bs[5].update(open=9,close=9,high=9,low=9)
        result=outcome({b['date']:b for b in bs},dates,0,5)
        self.assertEqual(result['entry_date'],dates[1])
        self.assertEqual(result['exit_date'],dates[6])
        self.assertEqual(result['exit_delay'],1)
        self.assertAlmostEqual(result['net_pct'],(10/10.5-1)*100-.3)
        self.assertLess(result['close_drawdown_pct'],0)

    def test_missing_future_does_not_become_zero_loss_or_unseen_selection(self):
        bs=bars(6,0); dates=[b['date'] for b in bs]
        data={b['date']:b for b in bs[:-1]}
        result=outcome(data,dates,0,5)
        self.assertEqual(result['status'],'unresolved_exit')
        self.assertNotIn('net_pct',result)
        data.pop(dates[1])
        self.assertEqual(outcome(data,dates,0,5)['status'],'entry_missing_or_no_trade')

    def test_limit_open_not_filled(self):
        bs=bars(8,0); dates=[b['date'] for b in bs]
        bs[1].update(open=11,close=11,high=11,low=11)
        self.assertEqual(outcome({b['date']:b for b in bs},dates,0,5)['status'],'entry_near_limit_up')

    def test_removing_a_factor_changes_order_but_not_pool(self):
        metrics={'a':{'ret20':1},'b':{'ret20':2}}
        own={'a':{'stock_strength_score':60,'stock_strength_parts':{'attack':100,'persistence':0,'acceptance':0,'recovery':0}},
             'b':{'stock_strength_score':50,'stock_strength_parts':{'attack':0,'persistence':90,'acceptance':90,'recovery':90}}}
        result=rankings(['a','b'],metrics,own)
        self.assertEqual(result['四项强度'],['a','b'])
        self.assertEqual(result['去掉相对进攻'],['b','a'])
        self.assertTrue(all(set(v)=={'a','b'} for v in result.values()))


if __name__=='__main__': unittest.main()
