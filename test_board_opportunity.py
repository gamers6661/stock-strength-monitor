"""Board current contract replaces V1 sampling/advance-member/event qualification."""
import copy
import unittest
from datetime import timedelta
import market_strength as M
import board_opportunity as B
from test_market_strength import fixture,run

class BoardOpportunityTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture(10);self.s,self.q,self.p,self.h,self.c,self.now=self.f
        for q in self.q.values():q.update(price=110.,open=100.,high=110.,low=100.,change_pct=10.)
    def model(self):
        B.enrich(self.s,self.q,self.p,histories=self.h,calendar=self.c,now=self.now,persist=True)
        B.validate(self.s);return self.s['board_catalog'][0]['market_strength']
    def test_projection_does_not_sample_or_rescore(self):
        m=copy.deepcopy(self.model());self.assertTrue(m['focus']);self.assertEqual(m,self.model())
        self.s['board_catalog'][0]['index_quote']={}
        self.assertTrue(self.model()['focus'])
    def test_official_index_alone_cannot_qualify(self):
        for q in self.q.values():q.update(price=100.,open=100.,high=101.,low=99.,change_pct=0.)
        self.s['board_catalog'][0]['index_quote']=dict(valid=True,change_pct=10.)
        self.assertFalse(self.model()['focus'])
    def test_missing_members_and_coverage_boundary(self):
        for missing in (1,2,3):
            with self.subTest(missing=missing):
                self.f=fixture(10);self.s,self.q,self.p,self.h,self.c,self.now=self.f
                for q in self.q.values():q.update(price=110.,open=100.,high=110.,low=100.,change_pct=10.)
                for code in list(self.q)[:missing]:del self.q[code]
                m=self.model();self.assertEqual(m['expected'],10)
                self.assertEqual(m['emotion_parts']['valid'],10-missing)
                self.assertEqual(m['emotion_parts']['coverage_pct'],100-10*missing)
                if missing<=2:self.assertIsNotNone(m['emotion_score'])
                else:self.assertIsNone(m['emotion_score'])
    def test_five_members_no_conclusion(self):
        self.s['board_catalog'][0]['member_codes']=list(self.q)[:5];m=self.model();self.assertIsNone(m['trend_score']);self.assertIsNone(m['emotion_score'])
    def test_explicit_no_trade_excluded_missing_not_excluded(self):
        self.q[list(self.q)[0]].update(amount_wan=0.,volume_shou=0.);del self.q[list(self.q)[1]]
        m=self.model();self.assertEqual(m['expected'],9);self.assertEqual(m['emotion_parts']['valid'],8)
    def test_member_risk_no_exclusion(self):
        for r in self.s['stocks']:r.update(intraday_serious_weakness=True,intraday_trade_restriction='涨停')
        self.assertTrue(self.model()['focus'])
    def test_trim_is_ten_percent_each_side(self):
        values={str(i):float(i) for i in range(20)};r,removed=M.trim(values);self.assertEqual(r,9.5);self.assertEqual(removed,['0','1','18','19'])
    def test_raw_members_and_index_unchanged(self):
        self.s['board_catalog'][0]['index_quote']=dict(valid=True,change_pct=-1.,source='THS')
        before=copy.deepcopy((self.q,self.p,self.h,self.s['board_catalog'][0]['member_codes'],self.s['board_catalog'][0]['index_quote']))
        m=self.model();self.assertIn('指数/主板成员分歧',m['reasons']);self.assertEqual(before,(self.q,self.p,self.h,self.s['board_catalog'][0]['member_codes'],self.s['board_catalog'][0]['index_quote']))
    def test_next_round_both_weak_exit(self):
        self.model()
        for q in self.q.values():q.update(price=100.,open=100.,high=101.,low=99.,change_pct=0.)
        run(self.f);self.assertFalse(self.s['board_catalog'][0]['market_strength']['focus'])
    def test_stale_quotes_no_strength(self):
        for q in self.q.values():q['quote_at']=str(self.now-timedelta(hours=1))
        m=self.model();self.assertIsNone(m['trend_score']);self.assertIsNone(m['emotion_score'])
