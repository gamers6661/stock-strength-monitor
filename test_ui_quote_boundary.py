"""Chart cutoff must follow accepted round facts without accepting future quotes."""
import copy
import unittest
import ui_payload

class QuoteChartBoundaryTests(unittest.TestCase):
    def case(self):
        day='2026-10-22'
        row=dict(code='600031',open=17.7,high=18.0,low=17.5,price=17.8,volume_shou=100,
                 intraday_quote_fresh=True,intraday_quote_at=day+' 11:30:19',
                 strength_history=[dict(date='2026-10-21',open=17.6,high=18.,low=17.,close=17.69)],
                 market_strength=dict(quote_at=day+' 11:30:19',price_context=dict(
                     valid=True,quote_day=day,last_history_date='2026-10-21',scale_factor=1.)))
        return dict(quote_capture_at=day+' 11:30:18',scan_completed_at=day+' 11:31:08',
                    intraday_model=dict(latest_valid_quote_at=day+' 11:30:20',max_quote_future_seconds=90),
                    stocks=[row])
    def test_accepted_quote_after_capture_draws_current_candle(self):
        f=self.case();before=copy.deepcopy(f);r=ui_payload.chart_projection(f)['stocks'][0]
        self.assertEqual(r['chart_history'][-1]['date'],'2026-10-22')
        self.assertEqual(r['chart_history'][-1]['close'],17.8)
        self.assertEqual(f,before)
    def test_unaccepted_quote_stays_history_only(self):
        f=self.case();f['stocks'][0]['intraday_quote_fresh']=False
        self.assertNotIn('chart_history',ui_payload.chart_projection(f)['stocks'][0])
    def test_later_than_scan_completion_is_rejected(self):
        f=self.case();f['scan_completed_at']='2026-10-22 11:30:18'
        self.assertNotIn('chart_history',ui_payload.chart_projection(f)['stocks'][0])
    def test_later_than_validated_round_is_rejected(self):
        f=self.case();f['intraday_model']['latest_valid_quote_at']='2026-10-22 11:30:18'
        self.assertNotIn('chart_history',ui_payload.chart_projection(f)['stocks'][0])
    def test_future_tolerance_still_applies(self):
        f=self.case();f['intraday_model']['max_quote_future_seconds']=0
        self.assertNotIn('chart_history',ui_payload.chart_projection(f)['stocks'][0])
    def test_other_day_quote_is_rejected(self):
        f=self.case();f['stocks'][0]['market_strength']['quote_at']='2026-10-23 11:30:19'
        self.assertNotIn('chart_history',ui_payload.chart_projection(f)['stocks'][0])
if __name__=='__main__':unittest.main()
