"""Regression checks for V2.1 source reconciliation and identity giveback."""
import copy
import unittest
from datetime import timedelta

import stock_activity as A
import stock_activity_engine as E
from test_stock_activity import sample, board_core, calculate


class StockActivityImprovements(unittest.TestCase):
    def source_case(self, seconds_later=3):
        f = sample()
        snap = copy.deepcopy(f[0])
        at = A.stamp(snap['quote_capture_at'])
        record = dict(captured_at=str(at), session='早盘',
                      quotes={r['code']:dict(r) for r in snap['stocks']})
        for row in snap['stocks']:
            row.pop('last_close_semantics', None)
            row.pop('price_basis', None)
            row.pop('price_basis_source', None)
            row.pop('last_close_precision_digits', None)
        snap['quote_capture_at'] = str(at + timedelta(seconds=seconds_later))
        return snap, record, at

    def test_nearby_independent_quotes_restore_provenance(self):
        snap, record, at = self.source_case()
        previous = copy.deepcopy(snap)
        result = A.live_view(snap, now=at + timedelta(seconds=4), record=record)
        self.assertIsNot(result, snap)
        self.assertEqual(result['stock_activity_quote_mode'], '逐股校验独立采样')
        self.assertEqual(result['stocks'][0]['last_close_semantics'],
                         'previous_trade_day_raw_close')
        self.assertEqual(result['stocks'][0]['price_basis'], 'raw')
        self.assertEqual(snap, previous)

    def test_older_snapshot_cannot_override_fresh_shared_result(self):
        snap, record, at = self.source_case(seconds_later=60)
        self.assertIs(A.live_view(snap, now=at + timedelta(seconds=61),
                                  record=record), snap)

    def test_no_unverified_price_basis_joins(self):
        snap, record, at = self.source_case()
        for q in record['quotes'].values():
            q.pop('last_close_semantics', None)
        self.assertIs(A.live_view(snap, now=at + timedelta(seconds=4),
                                  record=record), snap)

    def test_no_mismatched_yesterday_close_joins(self):
        snap, record, at = self.source_case()
        for q in record['quotes'].values():
            q['last_close'] += 1.
        self.assertIs(A.live_view(snap, now=at + timedelta(seconds=4),
                                  record=record), snap)

    def test_confirmed_peak_large_giveback_counts_as_weakness(self):
        f=board_core()
        state=copy.deepcopy(calculate(f)['_state']['items']['600000'])
        self.assertEqual(state['identity']['status'],'active')
        # Keep turnover high; large fading should still be noticed.
        p=copy.deepcopy(state['last_point'])
        atr=next(e['atr'] for e in state['events'] if e['id'] in state['identity']['event_ids'])
        peak=max(e['peak'] for e in state['events'] if e['id'] in state['identity']['event_ids'])
        # Emulate a confirmed long trend with a much lower locked structural floor.
        state['identity']['support_price']=peak*.80
        anchor=state['identity']['support_price']
        p['price']=peak-max(2.1*atr,.09*peak)
        self.assertGreater(p['price'],anchor)
        info=dict(event_days={p['at'][:10]},historical_excess=10.)
        E.identity_update(state,p,info,-1.,2.,True)
        self.assertEqual(state['identity']['status'],'weak')
        self.assertEqual(state['identity']['bad_count'],1)

    def test_version_migration_does_not_erase_identity(self):
        result=calculate(board_core())
        previous=copy.deepcopy(result['_state'])
        previous['version']='个股主动强度V2.1-20261019.3'
        migrated=E.restore_previous(previous)
        original=result['_state']['items']['600000']['identity']
        self.assertEqual(migrated['version'],E.VERSION)
        self.assertEqual(migrated['items']['600000']['identity']['created_at'],
                         original['created_at'])


if __name__=='__main__':
    unittest.main()
