"""Regressions for factor correctness and unavailable-data boundaries."""
import copy
import sqlite3
import unittest
from unittest.mock import patch
from pathlib import Path
import stock_selection as S
import stock_selection_factors as F
import stock_selection_validation as V
import stock_selection_calendar as C
from test_stock_selection import sample,run


class Optimization(unittest.TestCase):
    def test_missing_volume_preserves_price_relative_and_market_coverage(self):
        f=sample();a=run(f);c=f[-1][0]
        for code in f[-1][:4]:f[1][code][-1]['volume']=None
        b=run(f);x=b['items'][c]
        self.assertEqual(x['dimensions']['price'],a['items'][c]['dimensions']['price'])
        self.assertEqual(x['dimensions']['relative'],a['items'][c]['dimensions']['relative'])
        self.assertEqual(a['coverage']['market'],b['coverage']['market'])
        self.assertIsNone(x['dimensions']['volume']);self.assertIsNone(x['score'])
        self.assertFalse(x['eligible']);self.assertEqual(x['list_name'],'pending')

    def test_no_current_trade_preserves_score_but_suspends_selection(self):
        f=sample();c=f[-1][0];a=run(f)['items'][c]
        f[0]['stocks'][0].update(volume_shou=0.,amount_wan=0.)
        b=run(f)['items'][c]
        self.assertEqual(a['score'],b['score']);self.assertFalse(b['eligible'])
        self.assertTrue(b['historical_qualified']);self.assertEqual(b['list_name'],'pending')
        self.assertEqual(b['anchor']['support'],a['anchor']['support'])
        f[0]['_historical_replay']=True
        self.assertTrue(run(f)['items'][c]['eligible'])

    def test_all_up_is_not_full_volume_asymmetry(self):
        f=sample();e=run(f)['items'][f[-1][0]]['evidence']
        self.assertIsNone(e['volume_asymmetry']);self.assertEqual(e['volume_down_days'],0)
        self.assertLess(e['volume_participation'],100.)

    def test_efficiency_distinguishes_chop_from_smooth_same_gain(self):
        def bars(prices):return [dict(close=p) for p in prices]
        smooth=F.price_observations(bars([100,102,104,106,108,110]))
        rough=F.price_observations(bars([100,108,102,110,104,110]))
        self.assertGreater(smooth['advance_efficiency'],rough['advance_efficiency'])
        self.assertFalse(smooth['recovery_observed']);self.assertTrue(rough['recovered'])

    def test_unrecovered_pullback_is_not_zero_day_recovery(self):
        x=F.price_observations([dict(close=p) for p in [100,110,105,108]])
        self.assertFalse(x['recovered']);self.assertIsNone(x['recovery_days'])
        self.assertEqual(x['unrecovered_days'],2)

    def test_funds_ratio_uses_same_date_and_requires_complete_five_days(self):
        f=sample();c=f[-1][0];day=f[2][-1]
        f[0]['_fund_records']={c:dict(source='新浪超大单+大单日级净额',rows=[dict(date=day,main_net=1e6)])}
        x=run(f)['items'][c];self.assertIsNotNone(x['fund']['net_amount_pct'])
        self.assertIsNone(x['fund']['positive_days5'])
        f[0]['_fund_records'][c]['rows'][0]['date']='1999-01-01'
        self.assertIsNone(run(f)['items'][c]['fund']['net_amount_pct'])

    def test_downside_evidence_needs_three_real_down_days(self):
        f=sample();x=run(f)['items'][f[-1][0]]
        self.assertEqual(x['evidence']['down_market_days'],0)
        self.assertIsNone(x['evidence']['down_market_excess_pp'])

    def test_board_continuity_does_not_increment_on_same_day_or_changed_members(self):
        board=dict(available=True,label='板块支持');cal=['2026-10-19','2026-10-20']
        a=F.board_continuity(board,None,cal[0],cal,['a','b'])
        b=F.board_continuity(board,a,cal[0],cal,['a','b']);self.assertEqual(b['streak'],1)
        c=F.board_continuity(board,b,cal[1],cal,['a','b']);self.assertEqual(c['streak'],2)
        d=F.board_continuity(board,b,cal[1],cal,['a','c']);self.assertEqual(d['streak'],1)

    def test_calendar_does_not_shift_forward_return_across_missing_market_day(self):
        con=sqlite3.connect(':memory:')
        con.execute('CREATE TABLE kline(code TEXT,date TEXT,open REAL,close REAL,high REAL,low REAL,volume REAL,amount REAL,price_basis TEXT,price_basis_source TEXT)')
        source=next(iter(S.intraday._RAW_HISTORY_SOURCES))
        for day,p in [('2026-10-19',100.),('2026-10-21',120.)]:
            con.execute('INSERT INTO kline VALUES(?,?,?,?,?,?,?,?,?,?)',('600000',day,p,p,p+1,p-1,1e6,1e8,'raw',source))
        con.commit()
        dates=['2026-10-19','2026-10-20','2026-10-21']
        with patch('sqlite3.connect',return_value=con),patch.object(C,'load_calendar',return_value=dates):
            h,cal=V.forward_inputs([dict(daily_at=dates[0],items={'600000':{}})],dates[-1])
        self.assertEqual(cal,dates);self.assertIsNone(V.outcome(h['600000'],dates[0],1,cal))

    def test_calendar_requires_every_natural_day_and_respects_holidays(self):
        r=dict(source=C.SOURCE,days={'2026-10-01':'0','2026-10-02':'0','2026-10-03':'0','2026-10-04':'0','2026-10-05':'0','2026-10-06':'0','2026-10-07':'0','2026-10-08':'1'})
        self.assertEqual(C.validate(r,'2026-10-01','2026-10-08'),['2026-10-08'])
        del r['days']['2026-10-04'];self.assertEqual(C.validate(r,'2026-10-01','2026-10-08'),[])

    def test_pattern_sort_evidence_survives_lazy_payload(self):
        from ui_payload import selection_summary
        model=run(sample());packet=selection_summary(model);c=sample()[-1][0]
        self.assertEqual(packet['items'][c]['pattern_order'],model['items'][c]['pattern_order'])

    def test_completed_quote_after_1502_requires_independent_ohlc_and_volume_match(self):
        from test_stock_selection_round2 import Round2
        from unittest.mock import MagicMock
        import stock_selection_data as D
        snap,h,cal,records,now,c=Round2().quote_case(True)
        q=next(r for r in snap['stocks'] if r['code']==c);q['quote_at']=cal[-1]+' 15:05:00'
        snap['market_strength_close_input']=dict(quotes={c:dict(q)})
        con=MagicMock();con.total_changes=0
        with patch.object(D,'connect',return_value=con):D.save_close_quotes(snap,h,cal,now)
        saved=con.executemany.call_args.args[1]
        self.assertIn(c,[r[0] for r in saved])
        self.assertEqual(next(r[-1] for r in saved if r[0]==c),cal[-1]+' 15:05:00')
        snap['market_strength_close_input']['quotes'][c]['volume_shou']*=2
        with patch.object(D,'connect',return_value=con):D.save_close_quotes(snap,h,cal,now)
        self.assertNotIn(c,[r[0] for r in con.executemany.call_args.args[1]])
        snap['market_strength_close_input']['quotes'][c]['volume_shou']/=2
        snap['market_strength_close_input']['quotes'][c]['price']+=1
        with patch.object(D,'connect',return_value=con):D.save_close_quotes(snap,h,cal,now)
        self.assertNotIn(c,[r[0] for r in con.executemany.call_args.args[1]])

    def test_unknown_or_nonfinite_amount_inputs_are_not_accepted(self):
        import stock_selection_data as D
        for value in (None,float('nan'),True):
            self.assertIsNone(D.verified_amount(dict(date='2026-10-22',volume=value),dict(date='2026-10-22',source=D.SOURCE,volume=1e6,amount=1e8,low=99,high=101)))

    def test_changed_data_revision_prevents_reuse_of_old_page(self):
        import serve,json
        from unittest.mock import MagicMock
        root=MagicMock();root.__truediv__.return_value.is_file.return_value=True
        metadata=dict(publication_sources='source',generated_at='same',runtime_contract={},selection_input_revision={'fund':1})
        with patch.object(serve.config,'ROOT',root),patch.object(serve.ui_payload,'active_generation',return_value='g'),patch.object(serve.ui_payload,'blob',return_value=json.dumps(metadata)),patch.object(serve.make_dashboard,'publication_source_hash',return_value='source'),patch.object(serve.stock_selection,'input_revision',return_value={'fund':1}):
            self.assertTrue(serve.reusable_publication(dict(generated_at='same')))
            with patch.object(serve.stock_selection,'input_revision',return_value={'fund':2}):
                self.assertFalse(serve.reusable_publication(dict(generated_at='same')))


if __name__=='__main__':unittest.main()
