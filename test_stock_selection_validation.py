"""Evaluation must not invent future bars or zero returns for unavailable samples."""
import unittest
from stock_selection_validation import outcome,summarize,valid_forward_model


class Validation(unittest.TestCase):
    def test_missing_market_date_cannot_shorten_the_horizon(self):
        cal=['2026-10-19','2026-10-20','2026-10-21']
        bars=[dict(date=cal[0],close=100.,high=101.,low=99.),dict(date=cal[2],close=110.,high=111.,low=109.)]
        self.assertIsNone(outcome(bars,cal[0],2,cal))

    def test_unmatured_horizon_is_unknown(self):
        cal=['2026-10-19','2026-10-20'];bars=[dict(date=d,close=100.,high=101.,low=99.) for d in cal]
        self.assertIsNone(outcome(bars,cal[0],5,cal))

    def test_adverse_move_uses_future_low_and_market_date(self):
        cal=['2026-10-19','2026-10-20'];bars=[dict(date=cal[0],close=100.,high=101.,low=99.),dict(date=cal[1],close=103.,high=104.,low=95.)]
        import intraday
        for b in bars:b.update(open=b['close'],price_basis='raw',price_basis_source=next(iter(intraday._RAW_HISTORY_SOURCES)))
        x=outcome(bars,cal[0],1,cal)
        self.assertAlmostEqual(x['return_pct'],3);self.assertAlmostEqual(x['mae_pct'],-5)

    def test_republished_previous_close_cannot_be_a_new_forward_signal(self):
        freeze=dict(frozen_at='2026-10-21 10:10:00',implementation_hash='x')
        model=dict(close_finalized=True,implementation_hash='x',day='2026-10-21',daily_at='2026-10-20',
            captured_at='2026-10-21 16:00:00',source_at='2026-10-20 15:00:00')
        self.assertFalse(valid_forward_model(model,freeze))
        from test_stock_selection_round2 import ready_model
        model=ready_model('2026-10-21');model['implementation_hash']='x'
        self.assertTrue(valid_forward_model(model,freeze))

    def test_no_observations_is_not_zero_excess(self):
        x=summarize([]);self.assertEqual(x['observations'],0);self.assertIsNone(x['mean_excess'])


if __name__=='__main__':unittest.main()
