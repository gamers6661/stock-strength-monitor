"""V3 acceptance: independent evidence, no future bars, missing versus disqualified."""
import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import stock_selection as S
import stock_selection_data as D
from test_market_strength import fixture


def sample():
    snap,quotes,pool,histories,cal,now=fixture(12)
    codes=sorted(quotes)
    for c,bs in histories.items():
        for i,b in enumerate(bs):
            price=100*(1.008**max(0,i-35)) if c==codes[0] else 100.
            b.update(open=price-.2,close=price,high=price+.3,low=price-.4,volume=1000000.)
        last=bs[-1]['close']
        quotes[c].update(code=c,price=last,last_close=last,open=last,high=last+.5,low=last-.5,
                         amount_wan=last*100,volume_shou=10000.,change_pct=0.)
    snap['stocks']=list(quotes.values())
    snap['board_catalog'].append(dict(id='industry:test',type='industry',name='测试',member_codes=codes))
    records={c:{b['date']:dict(b,amount=100000000.,source=D.SOURCE) for b in bs} for c,bs in histories.items()}
    # Raw amount records must retain a coherent raw VWAP as well as share units.
    for values in records.values():
        for r in values.values():r['amount']=r['close']*r['volume']
    return snap,histories,cal,records,now,codes


def run(f,previous=None):
    snap,h,cal,records,now,codes=f
    return S.build(snap,h,cal,previous,records,now=now)


class Selection(unittest.TestCase):
    def test_sustained_rise_without_timing_identity(self):
        f=sample();m=run(f)['items'][f[-1][0]]
        self.assertTrue(m['eligible'],m)
        self.assertGreaterEqual(m['score'],65)
        self.assertNotIn('L',m['dimensions'])
        self.assertEqual(m['pattern'],'持续推进')

    def test_flat_stock_cannot_win_by_low_volatility(self):
        f=sample();m=run(f)['items'][f[-1][1]]
        self.assertFalse(m['eligible']);self.assertLess(m['dimensions']['price'],60)

    def test_industry_unavailable_does_not_remove_self_score(self):
        f=sample();a=run(f);f[0]['board_catalog']=[];b=run(f);c=f[-1][0]
        self.assertEqual(a['items'][c]['score'],b['items'][c]['score'])
        self.assertTrue(b['items'][c]['eligible']);self.assertFalse(b['items'][c]['board']['available'])

    def test_future_bars_cannot_change_today_score(self):
        f=sample();a=run(f)
        for bs in f[1].values():bs.append(dict(bs[-1],date='2026-12-01',close=99999.,high=99999.))
        b=run(f)
        self.assertEqual([a['items'][c]['score'] for c in a['order']],[b['items'][c]['score'] for c in a['order']])

    def test_current_quote_does_not_rewrite_completed_score(self):
        f=sample();a=run(f);f[0]['stocks'][0]['price']*=.9;b=run(f);c=f[-1][0]
        self.assertEqual(a['items'][c]['score'],b['items'][c]['score'])

    def test_missing_amount_is_unknown_and_never_estimated(self):
        f=sample();f[3].clear();m=run(f)['items'][f[-1][0]]
        self.assertIsNotNone(m['score']);self.assertFalse(m['eligible'])
        self.assertEqual(m['list_name'],'pending');self.assertFalse(m['evidence']['amount_estimated'])

    def test_known_low_liquidity_is_excluded_not_missing(self):
        f=sample()
        for bs in f[1].values():
            for b in bs:b['volume']=1000.
        for values in f[3].values():
            for b in values.values():b.update(volume=1000.,amount=b['close']*1000.)
        m=run(f)['items'][f[-1][0]]
        self.assertEqual(m['list_name'],'excluded');self.assertEqual(m['data_status'],'流动性不足')

    def test_missing_volume_does_not_redistribute_weights(self):
        f=sample();f[1][f[-1][0]][-1]['volume']=None;m=run(f)['items'][f[-1][0]]
        self.assertIsNone(m['score']);self.assertEqual(m['list_name'],'pending')

    def test_unknown_price_basis_is_not_invented(self):
        f=sample();f[1][f[-1][0]][-1]['price_basis_source']='unknown';m=run(f)['items'][f[-1][0]]
        self.assertIsNone(m['score']);self.assertIn('口径',m['reasons'][0])

    def test_bad_amount_units_are_rejected(self):
        b=dict(date='2026-10-19',volume=1000000.)
        r=dict(date=b['date'],volume=1000000.,amount=100.,source=D.SOURCE,low=9.,high=11.)
        self.assertIsNone(D.verified_amount(b,r))

    def test_amount_mismatching_volume_is_not_joined(self):
        b=dict(date='2026-10-19',volume=1000000.)
        r=dict(date=b['date'],volume=10000.,amount=100000.,source=D.SOURCE,low=9.,high=11.)
        self.assertIsNone(D.verified_amount(b,r))

    def test_current_pool_not_mutated(self):
        f=sample();before=copy.deepcopy(f[0]);run(f);self.assertEqual(f[0],before)

    def test_anchor_does_not_follow_price_down(self):
        f=sample();first=run(f);c=f[-1][0];support=first['items'][c]['anchor']['support']
        f[0]['stocks'][0]['price']*=.99
        second=run(f,first['_state']);self.assertEqual(support,second['items'][c]['anchor']['support'])

    def test_all_dimensions_are_bounded(self):
        for m in run(sample())['items'].values():
            for v in list(m['dimensions'].values())+[m['score']]:
                self.assertTrue(v is None or 0<=v<=100)

    def test_volume_confirmed_breakout_has_its_own_path(self):
        f=sample();c=f[-1][0];b=f[1][c][-1];b.update(volume=2000000.,high=b['close']+.1)
        f[3][c][b['date']]=dict(b,amount=b['close']*b['volume'],source=D.SOURCE)
        m=run(f)['items'][c]
        self.assertEqual(m['pattern'],'突破启动');self.assertTrue(m['eligible'])

    def test_support_break_invalidates_identity_without_lowering_support(self):
        f=sample();c=f[-1][0];first=run(f);support=first['items'][c]['anchor']['support']
        f[2].append('2026-10-13');f[0].update(session='已收盘',close_daily_verified_at='2026-10-13 16:00:00',quote_capture_at='2026-10-13 15:00:00')
        for code,bs in f[1].items():
            p=support-3 if code==c else bs[-1]['close']
            b=dict(bs[-1],date='2026-10-13',open=p+.2,close=p,high=p+.5,low=p-.2);bs.append(b)
            f[3][code][b['date']]=dict(b,amount=p*b['volume'],source=D.SOURCE)
        f=(*f[:4],S.parse_at('2026-10-13 16:00:00'),f[-1])
        m=run(f,first['_state'])['items'][c]
        self.assertEqual(m['pattern'],'结构失效');self.assertFalse(m['eligible'])
        self.assertEqual(m['anchor']['support'],support)

    def test_expired_prior_strength_does_not_authorize_perpetual_consolidation(self):
        f=sample();c=f[-1][0];first=run(f)
        old=first['_state'];old['items'][c]['last_strong_at']=f[2][-25]
        # The explicit anchor age is used independently of sampled attack identities.
        m=run(f,old)['items'][c]
        gates={g['name']:g['passed'] for g in m['gates']}
        self.assertFalse(gates['强势整理'])

    def test_zero_atr_is_local_missing_not_a_whole_page_exception(self):
        f=sample();c=f[-1][1]
        for b in f[1][c]:b.update(open=100.,high=100.,low=100.,close=100.)
        m=run(f)
        self.assertIsNone(m['items'][c]['score']);self.assertIn('ATR',m['items'][c]['reasons'][0])
        self.assertIsNotNone(m['items'][f[-1][0]]['score'])

    def test_intraday_new_breakout_is_visible_without_rewriting_daily_score(self):
        f=sample();c=f[-1][1];before=run(f)['items'][c]['score']
        row=f[0]['stocks'][1];row.update(price=103.,high=103.,low=99.,open=100.,last_close=100.,change_pct=3.)
        m=run(f)['items'][c]
        self.assertEqual(before,m['score']);self.assertTrue(m['eligible'],m)
        self.assertEqual(m['pattern'],'盘中突破待确认');self.assertEqual(m['list_name'],'breakout')

    def test_insufficient_market_coverage_keeps_partial_dimensions(self):
        f=sample()
        for c in f[-1][-3:]:f[1][c][-1]['close']=None
        m=run(f)['items'][f[-1][0]]
        self.assertIsNone(m['score']);self.assertIsNotNone(m['dimensions']['price'])
        self.assertIsNone(m['dimensions']['relative']);self.assertIsNotNone(m['dimensions']['volume'])

    def test_small_red_day_does_not_erase_intact_strong_structure(self):
        f=sample();r=f[0]['stocks'][0];p=r['last_close']*.99
        r.update(price=p,low=p-.1,high=r['open']+.1,change_pct=-1.)
        m=run(f)['items'][f[-1][0]]
        self.assertTrue(m['eligible']);self.assertNotEqual(m['intraday']['state'],'转弱')

    def test_offline_result_stays_pinned_when_live_result_changes(self):
        import config
        import ui_payload
        f=sample();full=copy.deepcopy(f[0]);full['stock_selection']=run(f);full['stock_selection'].pop('_state')
        expected=full['stock_selection']['result_version']
        with TemporaryDirectory() as tmp:
            root=Path(tmp);page=root/'page.html';store=ui_payload.store_root(page)
            with patch.object(config,'CACHE_DIR',root),patch.object(ui_payload,'store_root',return_value=store):
                _,token=ui_payload.prepare(full,'var DATA = /*__DATA__*/null;',page,project_charts=False)
                (root/'stock_selection_v3').mkdir()
                (root/'stock_selection_v3/latest.json').write_text('{"result_version":"later"}',encoding='utf8')
                html=ui_payload.offline_html(token).decode('utf8')
                saved,_=json.JSONDecoder().raw_decode(html.split('var DATA = ',1)[1])
                self.assertEqual(saved['stock_selection']['result_version'],expected)


if __name__=='__main__':unittest.main()
