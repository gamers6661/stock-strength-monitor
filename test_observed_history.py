import copy,unittest
from datetime import datetime
from unittest.mock import patch
import datafeed,intraday,ma_trend,make_dashboard,relay_relations,relay_history as H,emotion_relay as E
from test_price_basis import history,quote

class ObservedHistory(unittest.TestCase):
    def test_gap_uses_actual_last_twenty_bars_without_synthetic_prices(self):
        bars=history();full=[b['date'] for b in bars];missing=full[10];bars.pop(10)
        original=copy.deepcopy(bars)
        ctx=intraday.align_price_basis(quote(),bars,full,'2026-09-28')
        self.assertTrue(ctx['valid'],ctx['reason']);self.assertEqual(len(ctx['aligned_bars']),20)
        self.assertEqual(ctx['history_observation']['suspension_days'],[missing])
        self.assertEqual(bars,original)
        self.assertAlmostEqual(ctx['daily_ma'][10],99)

    def test_short_history_exposes_real_ma_periods_only(self):
        bars=history()[-7:];ctx=intraday.align_price_basis(quote(),bars,[b['date'] for b in bars],'2026-09-28',allow_partial=True)
        self.assertTrue(ctx['valid']);self.assertIsNotNone(ctx['daily_ma'][5]);self.assertIsNone(ctx['daily_ma'][10])
        self.assertIsNone(ctx['atr20']);m=ma_trend.daily(bars,[b['date'] for b in bars])
        self.assertFalse(m['pending']);self.assertTrue(m['sample_only'])
        legacy=intraday.align_price_basis(quote(),bars,[b['date'] for b in bars],'2026-09-28')
        self.assertFalse(legacy['valid']);self.assertIn('有效成交日',legacy['reason'])

    def test_halted_and_short_stock_keeps_actual_candles(self):
        bar=history()[-1];row=dict(emotion_relay=dict(suspended_current=True))
        self.assertTrue(make_dashboard.attach_completed_candles(row,[bar],bar['date']))
        self.assertEqual(row['chart_history'],[bar])

    def test_zero_volume_placeholder_never_becomes_a_candle(self):
        bars=history();bars[-2]['volume']=0;row={}
        self.assertTrue(make_dashboard.attach_completed_candles(row,bars,bars[-1]['date']))
        self.assertNotIn(bars[-2]['date'],[b['date'] for b in row['chart_history']])

    def test_source_and_ohlc_conflicts_still_reject_despite_gaps(self):
        for key,value in [('price_basis_source','unknown'),('close',0)]:
            bars=history();cal=[b['date'] for b in bars];bars.pop(8);bars[-1][key]=value
            self.assertFalse(intraday.align_price_basis(quote(),bars,cal,'2026-09-28')['valid'])

class MainBusinessRelations(unittest.TestCase):
    def test_incidental_concepts_do_not_link_ice_machine_to_media_or_feed(self):
        rows={'a':dict(industry=['通用设备','机械设备']),'b':dict(industry=['出版','传媒']),
              'c':dict(industry=['饲料','农林牧渔'])}
        self.assertEqual(relay_relations.shared('a','b',rows),[])
        self.assertEqual(relay_relations.shared('a','c',rows),[])

    def test_same_main_industry_accepts_media_across_subindustries(self):
        rows={'a':dict(industry=['出版','传媒']),'b':dict(industry=['影视院线','传媒'])}
        self.assertEqual([b['name'] for b in relay_relations.shared('a','b',rows)],['传媒'])

    def test_cross_industry_concept_requires_business_evidence_on_both(self):
        fact=dict(name='实际主线',source='issuer-announcement',business_basis='已披露主营产品',verified=True)
        rows={'a':dict(mainline_concept_evidence=[fact]),'b':{}}
        self.assertEqual(relay_relations.shared('a','b',rows),[])
        rows['b']['mainline_concept_evidence']=[dict(fact)]
        self.assertEqual(relay_relations.shared('a','b',rows)[0]['kind'],'main_concept')

class QuoteRetry(unittest.TestCase):
    NOW=datetime(2026,10,15,16)
    def healthy(self):return dict(price=10,open=10,high=11,low=9,volume_shou=10,ts='20261015150000')
    def test_isolated_failure_retries_only_that_stock_and_infers_halt(self):
        with patch.object(datafeed,'tencent_quotes',return_value={}) as fetch:
            out=datafeed.retry_isolated_quotes(['a','b'],{'a':self.healthy()},self.NOW)
        fetch.assert_called_once_with(['b']);state=out['b']['data_availability']
        self.assertEqual(state['kind'],'inferred_suspension');self.assertEqual(state['attempts'],1)
        self.assertNotIn('price',out['b'])

    def test_retry_recovery_and_later_resume_remove_suspension(self):
        with patch.object(datafeed,'tencent_quotes',return_value={'b':self.healthy()}):
            out=datafeed.retry_isolated_quotes(['a','b'],{'a':self.healthy()},self.NOW)
        self.assertEqual(out['b']['data_availability']['kind'],'retry_recovered')
        resumed=datafeed.retry_isolated_quotes(['a','b'],{'a':self.healthy(),'b':self.healthy()},self.NOW)
        self.assertNotIn('data_availability',resumed['b'])

    def test_same_day_old_quote_is_retried_and_auction_is_not_a_live_control(self):
        now=self.NOW.replace(hour=10,minute=5)
        live=dict(self.healthy(),ts='20261016100500')
        # Use the fixture's same date, while varying the actual source clock.
        live['ts']='20261015100500';old=dict(live,ts='20261015093000')
        with patch.object(datafeed,'tencent_quotes',return_value={}) as fetch:
            out=datafeed.retry_isolated_quotes(['a','b'],{'a':live,'b':old},now)
        fetch.assert_called_once_with(['b']);self.assertEqual(out['b']['data_availability']['kind'],'inferred_suspension')
        with patch.object(datafeed,'tencent_quotes') as fetch:
            datafeed.retry_isolated_quotes(['a','b'],{'a':dict(live,ts='20261015092500')},now.replace(hour=9,minute=31))
        fetch.assert_not_called()

    def test_market_feed_outage_and_preopen_do_not_mark_all_stocks_halted(self):
        with patch.object(datafeed,'tencent_quotes') as fetch:
            self.assertEqual(datafeed.retry_isolated_quotes(['a','b'],{},self.NOW),{})
            out=datafeed.retry_isolated_quotes(['a','b'],{'a':self.healthy()},self.NOW.replace(hour=9,minute=20))
        fetch.assert_not_called();self.assertNotIn('b',out)

    def test_historical_gap_preserves_board_height_until_actual_break(self):
        from test_emotion_relay import sample
        s,q,p,h,cal,now,e=sample();c=next(iter(q));e['reference']={}
        # Raw/ref numerical cross-check remains required; test the explicit gap alone.
        e['_raw_index']={c:{}};e['_ref_index']={c:{}}
        sealed,reason,halted=H.classify(c,cal[-1],cal,e)
        self.assertTrue(halted);self.assertIsNone(sealed)

if __name__=='__main__':unittest.main()
