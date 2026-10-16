"""A coherent morning reference survives lunch, and never qualifies afternoon."""
import copy,json,csv,io,tempfile,unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import market_strength as M
import ui_payload
from test_market_strength import fixture


class LunchContinuity(unittest.TestCase):
    def setUp(self):
        self.f=fixture();s,q,p,h,c,n=self.f
        for quote in q.values():quote.update(price=110.,open=100.,high=110.,low=100.,change_pct=10.,quote_at='2026-10-13 11:31:11')
        s['session']='午间休市'
        M.attach(s,q,p,h,c,now=datetime(2026,10,13,12));M.validate(s)
        self.previous=copy.deepcopy(s)
        self.assertEqual(s['market_strength']['counts']['focus'],10)
        self.assertEqual(s['market_strength']['board_counts']['focus'],1)

    def refresh(self,at='2026-10-13 12:30:00',now=datetime(2026,10,13,12,45),session='午间休市',previous=None,missing=False):
        s,q,p,h,c,_=copy.deepcopy(self.f)
        s['session']=session
        for quote in q.values():quote.update(price=90.,open=100.,high=110.,low=90.,change_pct=-10.,quote_at=at)
        if missing:q={}
        raw=copy.deepcopy(q)
        M.attach(s,q,p,h,c,now=now,previous=self.previous if previous is None else previous)
        self.assertEqual(q,raw);M.validate(s)
        return s

    def test_invalid_lunch_keeps_complete_morning_models_and_order(self):
        s=self.refresh()
        for key in ('stocks','boards','counts','board_counts','reference_pools','emotion_reference_pools','board_reference_pools'):
            self.assertEqual(s['market_strength'][key],self.previous['market_strength'][key])
        for group in ('stocks','board_catalog'):
            for old,new in zip(self.previous[group],s[group]):
                m=copy.deepcopy(new['market_strength']);m.pop('reference_source_at');m['mode']=old['market_strength']['mode']
                self.assertEqual(m,old['market_strength'])
                self.assertIn('午休参考',new['market_strength']['mode'])
                self.assertIn('11:31:11',new['market_strength']['mode'])
        self.assertEqual(s['stocks'][0]['price'],110.)
        self.assertEqual(s['stocks'][0]['quote_at'],'2026-10-13 11:31:11')
        self.assertEqual(s['market_strength']['reference_evaluation_at'],'2026-10-13 12:00:00')

    def test_missing_lunch_quotes_keep_reference(self):
        s=self.refresh(missing=True);self.assertEqual(s['market_strength']['counts']['focus'],10);self.assertEqual(s['market_strength']['board_counts']['focus'],1)

    def test_repeated_invalid_lunch_does_not_advance_original_clock(self):
        s=self.refresh()
        for minute in (46,47,59):
            s=self.refresh(now=datetime(2026,10,13,12,minute),previous=s,missing=minute==47)
            self.assertEqual(s['market_strength']['counts']['focus'],10)
            self.assertEqual(s['market_strength']['reference_source_at'],'2026-10-13 11:31:11')
            self.assertEqual(s['market_strength_morning_input']['at'],'2026-10-13 12:00:00')

    def test_invalid_replacement_is_never_mixed_with_one_valid_quote(self):
        s,q,p,h,c,_=copy.deepcopy(self.f);q[next(iter(q))]['quote_at']='2026-10-13 12:30:00'
        M.attach(s,q,p,h,c,now=datetime(2026,10,13,12,45),previous=self.previous)
        self.assertEqual(s['market_strength']['stocks'],self.previous['market_strength']['stocks'])
        self.assertTrue(all(r['market_strength']['emotion_score']==65.5 for r in s['stocks']))

    def test_uncomputable_lunch_holding_uses_full_previous_evidence(self):
        s,q,p,h,c,_=copy.deepcopy(self.f)
        for quote in q.values():quote['high']=None
        M.attach(s,q,p,h,c,now=datetime(2026,10,13,12,45),previous=self.previous)
        self.assertEqual(s['market_strength']['counts']['focus'],10)
        self.assertTrue(all(r['market_strength']['emotion_score']==65.5 for r in s['stocks']))

    def test_afternoon_valid_quotes_replace_reference_immediately(self):
        lunch=self.refresh()
        s=self.refresh(at='2026-10-13 13:05:00',now=datetime(2026,10,13,13,5),session='午盘',previous=lunch)
        self.assertEqual(s['market_strength']['counts']['focus'],0)
        self.assertTrue(all(r['market_strength']['emotion_score'] is not None for r in s['stocks']))
        self.assertNotIn('午休',s['market_strength']['mode'])
        self.assertNotIn('market_strength_morning_input',s)
        self.assertTrue(all(r['market_strength']['quote_at']=='2026-10-13 13:05:00' for r in s['stocks']))

    def test_afternoon_missing_or_lunch_quotes_never_retain_morning(self):
        for missing in (False,True):
            s=self.refresh(now=datetime(2026,10,13,13,5),session='午盘',previous=self.refresh(),missing=missing)
            self.assertEqual(s['market_strength']['counts']['focus'],0);self.assertEqual(s['market_strength']['board_counts']['focus'],0)
            self.assertTrue(all(r['market_strength']['trend_score'] is None and r['market_strength']['emotion_score'] is None for r in s['stocks']))

    def test_no_prior_valid_morning_data_stays_unknown(self):
        s=self.refresh(previous={});self.assertEqual(s['market_strength']['counts']['focus'],0)

    def test_previous_day_morning_never_retained(self):
        previous=copy.deepcopy(self.previous);previous['market_strength_morning_input']['at']='2026-10-12 12:00:00'
        s=self.refresh(previous=previous);self.assertEqual(s['market_strength']['counts']['focus'],0)

    def test_implementation_change_recalculates_full_raw_morning_batch(self):
        previous=copy.deepcopy(self.previous);previous['market_strength']['implementation_hash']='old-implementation'
        for row in previous['stocks']:row['market_strength']['emotion_score']=1.
        s=self.refresh(previous=previous)
        self.assertEqual(s['market_strength']['implementation_hash'],M.IMPLEMENTATION_HASH)
        self.assertTrue(all(r['market_strength']['emotion_score']==65.5 for r in s['stocks']))

    def test_pre_upgrade_full_snapshot_without_saved_input_is_recalculated(self):
        previous=copy.deepcopy(self.previous);previous.pop('market_strength_morning_input')
        for row in previous['stocks']:row.update(self.f[1][row['code']])
        previous['market_strength']['implementation_hash']='pre-upgrade'
        s=self.refresh(previous=previous)
        self.assertEqual(s['market_strength']['counts']['focus'],10)
        self.assertTrue(all(r['market_strength']['emotion_score']==65.5 for r in s['stocks']))

    def test_known_missing_field_does_not_discard_other_morning_members(self):
        s,q,p,h,c,_=copy.deepcopy(self.f);q[next(iter(q))]['high']=None
        M.attach(s,q,p,h,c,now=datetime(2026,10,13,12))
        old=copy.deepcopy(s);s=self.refresh(previous=old)
        self.assertEqual(s['market_strength']['counts'],old['market_strength']['counts'])
        self.assertEqual(s['market_strength']['stocks'],old['market_strength']['stocks'])

    def test_no_trade_records_preserve_board_denominators(self):
        s,q,p,h,c,_=copy.deepcopy(self.f)
        for code in list(q)[:2]:q[code].update(amount_wan=0.,volume_shou=0.)
        M.attach(s,q,p,h,c,now=datetime(2026,10,13,12));old=copy.deepcopy(s)
        s=self.refresh(previous=old)
        self.assertEqual(s['market_strength']['counts']['focus'],8)
        self.assertEqual(s['board_catalog'][0]['market_strength']['expected'],8)
        for row,before in zip(s['board_catalog'],old['board_catalog']):
            m=copy.deepcopy(row['market_strength']);m.pop('reference_source_at');m['mode']=before['market_strength']['mode']
            self.assertEqual(m,before['market_strength'])

    def test_price_only_boundary_table_cannot_restore_reference(self):
        previous=copy.deepcopy(self.previous);previous.pop('market_strength_morning_input')
        for row in previous['stocks']:
            for key in ('open','high','low'):row.pop(key,None)
        previous['boundary_prices']=dict(date='2026-10-13',prices={r['code']:dict(price=110.,change_pct=10.) for r in previous['stocks']})
        s=self.refresh(previous=previous);self.assertEqual(s['market_strength']['counts']['focus'],0)

    def test_valid_new_morning_quote_is_still_calculated(self):
        s=self.refresh(at='2026-10-13 11:32:00')
        self.assertEqual(s['market_strength']['counts']['focus'],0)
        self.assertTrue(all(r['market_strength']['emotion_score'] is not None for r in s['stocks']))
        self.assertTrue(all(r['market_strength']['quote_at']=='2026-10-13 11:32:00' for r in s['stocks']))

    def test_list_detail_members_and_full_csv_use_one_reference(self):
        s=self.refresh()
        with tempfile.TemporaryDirectory() as d:
            page=Path(d)/'dashboard.html';packet,t=ui_payload.prepare(s,'var DATA = /*__DATA__*/null',page)
            brief=ui_payload.unpack(packet);board=ui_payload.detail(t,'board',s['board_catalog'][0]['id'],page)
            self.assertEqual(brief['market_strength']['counts']['focus'],10)
            self.assertEqual(board['market_strength'],json.loads(json.dumps(s['board_catalog'][0]['market_strength'])))
            rows=list(csv.DictReader(io.StringIO(ui_payload.export_board_csv(t,[board['id']],page).decode('utf-8-sig'))))
            self.assertEqual(json.loads(rows[0]['完整模型依据']),board['market_strength'])
            by={r['code']:r['market_strength'] for r in s['stocks']}
            for member in board['members']:self.assertEqual(member['market_strength'],json.loads(json.dumps(M.brief(by[member['code']]))))

if __name__=='__main__':unittest.main()
