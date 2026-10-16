"""真实留存入口及有序采样验收；同一末值应能区分不同的日内路径。"""
from datetime import datetime
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import intraday
import intraday_path as path
import test_intraday as fixtures
import attack_model
import test_attack_model as attack_fixtures


class IntradayPathTests(unittest.TestCase):
    DAY = '2026-09-28'

    @classmethod
    def setUpClass(cls):
        fixtures.IntradayAcceptanceTests.setUpClass()

    def row(self, time='10:10:00', price=10.3, valid=True, attack=True, ma10=10):
        return dict(code='600001', price=price, intraday_judgment_at=self.DAY+' '+time,
                    intraday_quote_at=self.DAY+' '+time, intraday_observation_available=valid,
                    intraday_score=80 if valid else None, intraday_observation_state='观察',
                    intraday_trend_state='趋势在线', intraday_price_basis_comparable=ma10 is not None,
                    intraday_ma10_trigger_price=ma10, attack_observation_candidate=attack,
                    live_attack_score=75, live_attack_tier='A', live_attack_stage='突破',
                    intraday_risk_flags=[], intraday_risk_level='低')

    def evaluate(self, current, prior):
        snap={'stocks':[current], 'quote_capture_at':self.DAY+' 10:10:05'}
        path.attach(snap, {'points':{'600001':prior}})
        return current['intraday_path']

    def as_point(self, row):
        self.evaluate(row, [])
        return row['intraday_last_judgment'] or dict(at=row['intraday_judgment_at'], valid=False)

    def test_same_last_quote_different_histories_change_judgment(self):
        active=self.as_point(self.row('10:05:00'))
        weak=self.as_point(self.row('10:05:00', attack=False))
        ongoing=self.evaluate(self.row(),[active])
        first=self.evaluate(self.row(),[weak])
        self.assertIn('进攻持续',ongoing['state'])
        self.assertIn('本轮达标',first['state'])
        self.assertEqual(ongoing['attack_consecutive'],2)

    def test_recovery_is_based_on_multiple_real_samples(self):
        prior=[self.as_point(self.row('10:00:00',price=10.2)),
               self.as_point(self.row('10:05:00',price=9.8,attack=False))]
        result=self.evaluate(self.row(),prior)
        self.assertEqual([e['kind'] for e in result['events']],
                         ['扫描观察到失守MA10','扫描观察到收复MA10'])
        self.assertIn('失守后收复',result['state'])
        self.assertEqual(result['ma10_hold_consecutive'],1)

    def test_repeated_quote_is_saved_but_not_another_confirmation(self):
        prior=[self.as_point(self.row())]
        result=self.evaluate(self.row(),prior)
        self.assertEqual(result['acquired_count'],2)
        self.assertEqual(result['distinct_count'],1)
        self.assertEqual(result['attack_consecutive'],1)
        self.assertEqual(result['events'],[])

    def test_gap_or_missing_does_not_claim_continuous_confirmation(self):
        prior=self.as_point(self.row('10:00:00'))
        for history in ([prior], [prior,dict(valid=False,at=self.DAY+' 10:05:00')]):
            result=self.evaluate(self.row('10:20:00'),history)
            self.assertEqual(result['attack_consecutive'],1)
            self.assertNotIn('持续',result['state'])
        result=self.evaluate(self.row(),[prior,dict(valid=False,at=self.DAY+' 10:05:00')])
        self.assertEqual(result['missing_count'],1)
        self.assertEqual(result['ma10_hold_consecutive'],1)

    def test_unknown_ma_breaks_hold_count(self):
        prior=[self.as_point(self.row('10:00:00')),self.as_point(self.row('10:05:00',ma10=None))]
        result=self.evaluate(self.row(),prior)
        self.assertEqual(result['ma10_hold_consecutive'],1)

    def test_morning_close_and_afternoon_are_adjacent_trading_samples(self):
        prior=self.as_point(self.row('11:30:00'))
        result=self.evaluate(self.row('13:00:00'),[prior])
        self.assertEqual(result['attack_consecutive'],2)
        self.assertEqual(path.gap_seconds(self.DAY+' 11:25:00',self.DAY+' 13:05:00'),600)

    def test_missing_keeps_last_score_and_attack_without_new_judgment(self):
        prior=self.as_point(self.row('10:05:00'))
        row=self.row(valid=False)
        result=self.evaluate(row,[prior])
        self.assertEqual(row['intraday_last_judgment']['score'],80)
        self.assertEqual(row['intraday_last_judgment']['attack_tier'],'A')
        self.assertIn('保留最近有效',result['state'])
        self.assertEqual(result['attack_consecutive'],0)

    def test_real_history_loader_keeps_per_stock_last_valid_and_rejects_older_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def save(row,time):
                with patch.object(intraday,'HISTORY_DIR',root), patch.object(intraday,'PAIR_HISTORY_PATH',root/'pairs.jsonl'):
                    intraday.save_observation(dict(stocks=[row],session='早盘',mode='quick',
                        generated_at=self.DAY+' '+time, intraday_model={'asof':self.DAY}))
            save(self.row('10:05:00'), '10:05:05')
            save(self.row('10:10:00',valid=False), '10:10:05')
            save(self.row('10:00:00',price=999), '10:11:05')
            result=path.load(root,self.DAY)
            self.assertEqual(path.effective(result['latest_rows']['600001']),self.DAY+' 10:05:00')
            self.assertEqual(len(result['points']['600001']),3)
            self.assertFalse(result['points']['600001'][-1]['valid'])

    def test_raw_input_is_preserved_on_every_acquisition(self):
        with tempfile.TemporaryDirectory() as tmp:
            now=datetime(2026,9,28,10,0)
            for price in (10.1,10.2):
                path.save_acquisition(Path(tmp),{'600001':{'price':price,'quote_at':self.DAY+' 10:00:00'}},now,'早盘')
            with gzip.open(Path(tmp)/'acquisitions'/f'{self.DAY}.jsonl.gz','rt',encoding='utf-8') as stream:
                records=[json.loads(line) for line in stream]
            self.assertEqual(len(records),2)
            self.assertEqual([r['rows'][0][1] for r in records],[10.1,10.2])

    def test_old_incompatible_basis_keeps_price_but_cannot_produce_ma_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(intraday,'HISTORY_DIR',root), patch.object(intraday,'PAIR_HISTORY_PATH',root/'pairs.jsonl'):
                intraday.save_observation(dict(stocks=[self.row('10:05:00',price=9.8)],session='早盘',mode='quick',
                    generated_at=self.DAY+' 10:05:05',intraday_model={'asof':self.DAY,'price_basis_version':'旧口径'}))
            history=path.load(root,self.DAY)
            self.assertEqual(history['points']['600001'][0]['price'],9.8)
            self.assertIsNone(history['points']['600001'][0]['ma10'])
            self.assertEqual(self.evaluate(self.row(),history['points']['600001'])['events'],[])

    def test_core_recovers_prior_valid_row_after_an_intermediate_missing_quote(self):
        fixture=fixtures.IntradayAcceptanceTests()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); code=fixture.CODES[2]
            fixture._scan(datetime(2026,9,28,10,0),1,root)
            fixture._scan(datetime(2026,9,28,10,5),1,root,omissions=(code,))
            rows,_=fixture._scan(datetime(2026,9,28,10,10),2,root)
            row=next(r for r in rows if r['code']==code)
            self.assertTrue(row['intraday_observation_available'])
            self.assertIn('收复',row['intraday_transition'])

    def test_noon_current_quote_grades_and_repeat_does_not_duplicate_transition(self):
        fixture=fixtures.IntradayAcceptanceTests()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            fixture._scan(datetime(2026,9,28,11,25),1,root)
            rows,snap=fixture._scan(datetime(2026,9,28,12,15),2,root,session='午间休市')
            row=rows[2]
            self.assertTrue(row['intraday_observation_available'])
            self.assertEqual(row['intraday_judgment_at'],self.DAY+' 11:30:00')
            self.assertEqual(snap['intraday_model']['latest_judgment_at'],self.DAY+' 11:30:00')
            self.assertIsNotNone(row['intraday_score'])
            self.assertFalse(row['intraday_quote_fresh'])
            again,_=fixture._scan(datetime(2026,9,28,12,25),2,root,session='午间休市',previous_snapshot=snap)
            self.assertIsNone(again[2]['intraday_transition'])

    def test_noon_attack_grade_uses_new_available_flag_and_keeps_daily(self):
        snap,quotes,contexts=attack_fixtures.AttackModelTest().live_fixture()
        snap['session']='午间休市'
        row=snap['stocks'][0]
        row.update(intraday_quote_fresh=False,intraday_observation_available=True,
                   intraday_judgment_at='2026-09-30 11:30:00')
        attack_model.enrich(snap,quotes,contexts)
        self.assertEqual(row['live_attack_tier'],'A')
        self.assertEqual(row['stock_strength_score'],66)
        self.assertFalse(row['attack_watch_candidate'])
        self.assertTrue(row['attack_observation_candidate'])
        self.assertEqual(len(snap['attack_monitor']['rows']),1)

    def test_fund_fetched_after_scan_start_is_checked_at_actual_assessment(self):
        fixture=attack_fixtures.AttackModelTest()
        snap,quotes,contexts=fixture.live_fixture()
        snap['stocks'][0].update(fixture.fund_row())
        snap.update(generated_at='2026-09-30 10:00:00',attack_assessment_at='2026-09-30 10:02:00',
                    fund_meta=dict(source='东财主力净流入',stale=False))
        attack_model.enrich(snap,quotes,contexts)
        self.assertEqual(snap['stocks'][0]['live_attack_fund']['weight'],0)
        self.assertEqual(snap['stocks'][0]['live_attack_score'], snap['stocks'][0]['live_attack_price_score'])

    def test_new_noon_quote_with_unknown_basis_does_not_inherit_old_attack_grade(self):
        import copy
        snap,quotes,contexts=attack_fixtures.AttackModelTest().live_fixture()
        attack_model.enrich(snap,quotes,contexts)
        previous=copy.deepcopy(snap)
        snap['session']='午间休市'
        snap['stocks'][0].update(intraday_quote_fresh=False,intraday_observation_available=True,
                                intraday_price_basis_reason='历史窗口待核验')
        contexts['600001']['valid']=False
        attack_model.enrich(snap,quotes,contexts,previous)
        self.assertIsNone(snap['stocks'][0]['live_attack_score'])
        self.assertIsNone(snap['stocks'][0]['live_attack_tier'])
        self.assertEqual(snap['stocks'][0]['live_attack_status'],'历史窗口待核验')

    def test_missing_quote_keeps_reference_monitor_but_new_weak_quote_exits(self):
        for valid,expected in ((False,1),(True,0)):
            row=self.row(valid=valid,attack=False)
            row['intraday_last_judgment']=self.as_point(self.row('10:05:00'))
            snap=dict(session='午盘',quote_capture_at=self.DAY+' 13:10:00',stocks=[row],
                attack_monitor=dict(rows=[],count=0,sample_count=int(valid)))
            attack_model.retain_missing_observations(snap)
            self.assertEqual(len(snap['attack_monitor']['rows']),expected)
            self.assertEqual(snap['attack_monitor']['count'],0)
            if expected:self.assertTrue(snap['attack_monitor']['rows'][0]['reference_only'])

    def test_reference_monitor_does_not_carry_yesterday(self):
        row=self.row(valid=False)
        row['intraday_last_judgment']=self.as_point(self.row('10:05:00'))
        snap=dict(session='午盘',quote_capture_at='2026-09-29 13:10:00',stocks=[row],
            attack_monitor=dict(rows=[],count=0,sample_count=0))
        attack_model.retain_missing_observations(snap)
        self.assertEqual(snap['attack_monitor']['rows'],[])


if __name__=='__main__':
    unittest.main()
