"""Repair observation must not weaken existing admission or data gates."""
import unittest
from test_stock_selection import sample,run
import stock_selection as S

class RepairObservation(unittest.TestCase):
    def fixture(self):
        f=sample();c=f[-1][1];bs=f[1][c]
        # A deep prior decline followed by several rising days below the old high.
        for i,b in enumerate(bs):
            price=130. if i<len(bs)-10 else 100.
            b.update(open=price-.2,close=price,high=price+.3,low=price-.4,volume=1000000.)
        for b,p in zip(bs[-5:],[101.,104.,103.,107.,110.]):
            b.update(open=p-1,close=p,high=p+.2,low=p-1.5,volume=1800000.)
        for b in bs:f[3][c][b['date']]=dict(b,amount=b['close']*b['volume'],source=S.amounts.SOURCE)
        f[0]['stocks'][1].update(price=109.,last_close=110.,open=108.,high=112.,low=107.,amount_wan=10900.,volume_shou=10000.,change_pct=-.91)
        return f,c

    def test_repair_visible_with_disagreement_without_strong_upgrade(self):
        f,c=self.fixture();x=run(f)['items'][c]
        self.assertTrue(x['observation_only'],x)
        self.assertFalse(x['eligible']);self.assertEqual(x['list_name'],'repair')
        self.assertEqual(x['intraday']['state'],'分歧')
        self.assertIsNone(x['anchor'])

    def test_invalid_quote_and_missing_liquidity_never_admit(self):
        for invalid in ('quote','amount'):
            with self.subTest(invalid=invalid):
                f,c=self.fixture()
                if invalid=='quote':f[0]['stocks'][1]['quote_at']='2020-01-01 10:00:00';f[0]['stocks'][1]['ts']='2020-01-01 10:00:00'
                else:f[3][c]={}
                x=run(f)['items'][c]
                self.assertFalse(x.get('observation_only'));self.assertFalse(x['eligible'])

    def test_current_weakness_exits_observation_without_rewriting_score(self):
        f,c=self.fixture();before=run(f)['items'][c]
        f[0]['stocks'][1].update(price=99.,low=98.,change_pct=-10.)
        after=run(f)['items'][c]
        self.assertFalse(after['observation_only']);self.assertEqual(before['score'],after['score'])

    def test_one_day_spike_and_no_volume_do_not_qualify(self):
        for failure in ('spike','volume'):
            f,c=self.fixture()
            if failure=='spike':
                for b in f[1][c][-5:-1]:b.update(open=100.,close=100.,high=100.3,low=99.6)
            else:f[1][c][-1]['volume']=1000000.
            for b in f[1][c]:f[3][c][b['date']]=dict(b,amount=b['close']*b['volume'],source=S.amounts.SOURCE)
            self.assertFalse(run(f)['items'][c]['observation_only'])

if __name__=='__main__':unittest.main()
