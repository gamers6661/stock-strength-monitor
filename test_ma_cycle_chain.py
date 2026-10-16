"""Cycle identity, genuine exits and same-cycle stage recovery."""
import copy,csv,io,json,subprocess,unittest
from datetime import timedelta
from unittest.mock import patch
import ma_trend as T
from test_ma_trend import sample,run
from test_ma_lifecycle_confirmation import append_closes
from test_market_strength_integration import render


class CycleChain(unittest.TestCase):
    def test_ma20_restart_keeps_cycle_origin_and_has_separate_leg_dates(self):
        f=sample('ma20');before=T.daily(next(iter(f[3].values())),f[4])
        bars,dates=append_closes(f,[123.,124.]);after=T.daily(bars,dates)
        self.assertEqual(after['stage'],20)
        self.assertEqual(after['origin'],before['origin'])
        self.assertEqual(after['leg_origin']['date'],bars[-2]['date'])
        self.assertEqual(after['restart_event']['confirmation']['date'],bars[-1]['date'])
        self.assertEqual(after['cycle_id'],before['origin']['date'])
        self.assertEqual(after['entry_date'],before['entry_date'])
        self.assertEqual(after['last_phase']['cause'],'stage_progression');self.assertTrue(after['progressing'])
        self.assertEqual(after['last_exit'],before['last_exit'])

    def test_chain_starts_at_ma5_and_all_handoffs_share_the_origin(self):
        f=sample('ma20');bars,dates=append_closes(f,[123.,124.]);v=T.daily(bars,dates)
        chain=v['transitions'];self.assertEqual(chain[0]['from_stage'],None)
        self.assertEqual(chain[0]['to_stage'],5)
        for left,right in zip(chain,chain[1:]):self.assertEqual(left['to_stage'],right['from_stage'])
        self.assertTrue(all(t['cycle_id']==v['origin']['date'] for t in chain))
        self.assertIn((5,10),[(t['from_stage'],t['to_stage']) for t in chain])
        self.assertIn((10,20),[(t['from_stage'],t['to_stage']) for t in chain])
        self.assertNotIn((20,5),[(t['from_stage'],t['to_stage']) for t in chain])

    def test_one_bar_can_cross_ma5_and_ma10_in_order(self):
        f=sample('ma20');bars=next(iter(f[3].values()))[:-18]
        d=f[5].date().isoformat();bars.append(dict(bars[-1],date=d,open=121.,close=105.,high=121.2,low=104.8))
        v=T.daily(bars,f[4]+[d]);today=[t for t in v['transitions'] if t['date']==d]
        self.assertEqual([(t['from_stage'],t['to_stage']) for t in today],[(5,10),(10,20)])
        self.assertEqual(v['stage'],20)

    def test_ma10_reclaim_changes_progression_state_without_changing_stage(self):
        f=sample('ma10');before=T.daily(next(iter(f[3].values())),f[4])
        bars,dates=append_closes(f,[113.,114.]);v=T.daily(bars,dates)
        self.assertEqual(v['stage'],10);self.assertEqual(v['origin'],before['origin']);self.assertTrue(v['progressing'])
        self.assertEqual(v['restart_event']['confirmation']['prior_stage'],10)
        self.assertEqual(v['restart_event']['confirmation']['kind'],'MA10承接后再启动')

    def test_ma10_progression_event_does_not_leak_into_the_new_ma20_stage(self):
        f=sample('ma10');bars,dates=append_closes(f,[117.,121.,125.,126.]+[125.5]*16)
        v=T.daily(bars,dates);self.assertEqual(v['stage'],20)
        self.assertIsNone(v['restart_event']);self.assertFalse(v['progressing'])
        self.assertEqual(v['last_phase']['stage'],10)

    def test_ma5_pullback_after_progression_returns_to_ma20_consolidation(self):
        f=sample('ma20');original=T.daily(next(iter(f[3].values())),f[4])
        bars,dates=append_closes(f,[123.,124.,121.]);v=T.daily(bars,dates)
        self.assertEqual(v['origin'],original['origin']);self.assertEqual(v['stage'],20)
        self.assertFalse(v['progressing']);self.assertIsNone(v['last_exit'])
        self.assertEqual(v['entry_date'],original['entry_date'])

    def test_platform_age_alone_does_not_end_a_supported_cycle(self):
        f=sample('ma10');before=T.daily(next(iter(f[3].values())),f[4])
        bars,dates=append_closes(f,[112.8]*25);after=T.daily(bars,dates)
        self.assertIn(after['stage'],(5,10));self.assertEqual(after['origin'],before['origin'])
        self.assertEqual(after['last_exit'],before['last_exit'])

    def test_ma20_position_alone_cannot_create_a_cycle(self):
        from test_market_strength import fixture
        f=fixture(1);bars=next(iter(f[3].values()))
        # Even if a structural detector returns a near-MA20 shape, a stock
        # without any accepted strong MA5 entry has no stage lineage.
        with patch.object(T,'ma20_rise',return_value={'ready':True}) as detector:
            T._DAILY_CACHE.clear();v=T.daily(bars,f[4]);self.assertIsNone(v['stage'])
            detector.assert_not_called()

    def test_failure_is_final_and_later_cycle_requires_its_own_entry(self):
        f=sample('ma20');bars,dates=append_closes(f,[110.,111.,112.,113.])
        v=T.daily(bars,dates);self.assertIsNone(v['stage'])
        self.assertEqual(v['transitions'][-1]['to_stage'],None)
        self.assertFalse(v['ma20_primary_candidate']);self.assertFalse(v['ma20_candidate'])
        self.assertIsNone(v['restart_observation'])

    def test_ma10_low_gain_is_tracking_not_a_direct_ma5_exit(self):
        f=sample();bars,dates=append_closes(f,[105.2]*4+[103.8]);v=T.daily(bars,dates)
        self.assertEqual(v['stage'],10);self.assertIsNone(v['last_exit'])
        self.assertLess(v['ma10_gain']['rise_pct'],T.P['ma10_rise_pct'])
        m=dict(stage=10,price=103.9,atr20=1.,platform=v['platform'],origin=v['origin'],leg_origin=v['leg_origin'],provisional=False,ma10_gain=v['ma10_gain'])
        self.assertEqual(T.position_state(m,v,{},dates[-1]),'前段上涨不足')

    def test_new_cycle_base_cannot_cross_the_preceding_cycle_exit(self):
        f=sample();bars,dates=append_closes(f,[99.,104.])
        bars[-3]['low']=98.0
        bars[-2]['low']=98.9;bars[-1].update(open=99.,high=104.2,low=98.9,volume=400.)
        v=T.daily(bars,dates);self.assertEqual(v['stage'],5)
        self.assertEqual(v['last_exit']['date'],bars[-2]['date'])
        self.assertGreaterEqual(v['origin']['base_at'],v['last_exit']['date'])
        self.assertEqual(v['origin']['base_low'],98.9)

    def test_price_scaling_keeps_cycle_and_leg_proofs_separate(self):
        f=sample('ma20');bars,dates=append_closes(f,[123.,124.]);v=T.daily(bars,dates);w=T.scale_setup(v,2.)
        self.assertEqual(w['origin']['price'],v['origin']['price']*2)
        for key in ('leg_origin','restart_event'):
            self.assertEqual(w[key]['price'],v[key]['price']*2)
            self.assertEqual(w[key]['confirmation']['event_close'],v[key]['confirmation']['event_close']*2)
        self.assertEqual(w['cycle_id'],v['cycle_id'])

    def test_confirmed_ma20_progression_is_not_automatically_near_line_observation(self):
        f=list(sample('ma20'));bars,dates=append_closes(f,[123.,124.]);f[4]=dates
        f[5]=f[5]+timedelta(days=2);q=next(iter(f[1].values()))
        q.update(price=124.1,last_close=124.,open=124.,high=124.2,low=124.,quote_at=str(f[5]),change_pct=100*(124.1/124.-1))
        m=run(f);self.assertEqual(m['stage'],20);self.assertTrue(m['advance'])
        self.assertFalse(m['eligible']);self.assertEqual(m['position_state'],'推进延续')
        self.assertTrue(m['progressing']);self.assertEqual(m['origin']['date'],m['cycle_id'])

    def test_ui_and_both_csv_views_show_original_and_restart_dates(self):
        f=sample('ma20');run(f);bars,dates=append_closes(f,[123.,124.]);v=T.daily(bars,dates)
        m=f[0]['stocks'][0]['ma_trend'];m.update({k:copy.deepcopy(v[k]) for k in ('origin','leg_origin','restart_event','restart_observation','entry_date','last_confirmation','cycle_id')})
        m.update(stage=20,stage_label=T.LABELS[20],status='推进延续',eligible=False,advance=True)
        out=render(f[0],"document.getElementById('proof').innerHTML=mtDates(DATA.stocks[0].ma_trend);")['els']['proof']['innerHTML']
        self.assertIn('本轮启动 '+v['origin']['date'],out)
        self.assertIn('本段再启动 '+v['restart_event']['date'],out)
        self.assertIn('再启动确认 '+bars[-1]['date'],out)
        for view in ('radar','ranking'):
            data=json.dumps(dict(rows=f[0]['stocks'],data=f[0],contexts=dict(view=view)),ensure_ascii=False)
            result=subprocess.run(['node','csv_export.js'],input=data,capture_output=True,text=True,encoding='utf8',check=True)
            row=next(csv.DictReader(io.StringIO(result.stdout.lstrip('\ufeff'))))
            self.assertEqual(row['起点日期' if view=='radar' else '本轮启动日'],v['origin']['date'])
            self.assertEqual(row['本段启动日'],v['leg_origin']['date'])
            self.assertEqual(row['再启动确认日'],bars[-1]['date'])
            self.assertEqual(row['阶段确认日'],v['entry_date'])

if __name__=='__main__':unittest.main()
