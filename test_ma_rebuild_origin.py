"""Delayed MA turns must not hide a strong new wave or date it at an older exit."""
import copy,csv,io,json,subprocess,unittest
from datetime import timedelta
import ma_trend as T
from test_ma_trend import sample,run
from test_ma_lifecycle_confirmation import append_closes
from test_market_strength_integration import render

def rebuild_fixture(first_wave=True):
    f=sample();bars=next(iter(f[3].values()))
    values=[105.,115.5,127.05,122.,120.,120.,125.,111.,104.,111.,104.,105.,99.,95.,104.5,114.95,126.445]
    start=len(bars)-len(values)
    for j,price in enumerate(values):
        opening=bars[start+j-1]['close']
        bars[start+j].update(open=opening,close=price,high=max(opening,price)+.2,low=min(opening,price)-.2,
            volume=250. if first_wave and j==0 else 40.)
    for b in bars[-3:]:b['high']=b['close']
    return f

class RebuildOrigin(unittest.TestCase):
    def test_first_limit_can_precede_both_ma_turns_and_confirmation_stays_later(self):
        f=rebuild_fixture();bars=next(iter(f[3].values()));event=len(bars)-3
        self.assertLess(T.average(bars,event,5),T.average(bars,event-1,5))
        self.assertLess(bars[event]['close'],T.average(bars,event,10))
        self.assertIsNone(T.origin(bars,len(bars)-1,limit_pct=10))
        for end in (event+1,event+2):self.assertIsNone(T.daily(bars[:end],f[4],10)['stage'])
        d=T.daily(bars,f[4],10);o=d['origin'];p=o['confirmation']
        self.assertEqual(d['stage'],5);self.assertEqual(o['kind'],'涨停重建均线后确认')
        self.assertEqual(o['date'],bars[event]['date']);self.assertEqual(p['date'],bars[-1]['date'])
        self.assertEqual(d['last_confirmation']['date'],bars[-1]['date'])
        self.assertLess(p['previous_exit'],o['date']);self.assertLess(o['volume_ratio'],T.P['volume_ratio'])

    def test_first_observed_wave_does_not_need_a_fabricated_prior_qualified_exit(self):
        f=rebuild_fixture(False);bars=next(iter(f[3].values()));d=T.daily(bars,f[4],10)
        self.assertEqual(d['stage'],5);p=d['origin']['confirmation']
        self.assertIsNone(p['previous_exit']);self.assertIsNone(d['last_exit'])
        self.assertLess(p['event_previous_close'],p['event_previous_ma10'])

    def test_history_window_changes_do_not_move_an_observed_recent_start(self):
        f=rebuild_fixture();bars=next(iter(f[3].values()));event=bars[-3]['date']
        for count in (30,45,len(bars)):
            d=T.daily(bars[-count:],f[4],10)
            self.assertEqual(d['stage'],5,count);self.assertEqual(d['origin']['date'],event,count)
            self.assertEqual(d['origin']['confirmation']['date'],bars[-1]['date'],count)

    def test_single_limit_then_ordinary_low_volume_bounce_does_not_use_new_channel(self):
        f=rebuild_fixture();bars=next(iter(f[3].values()))
        bars[-2].update(close=110.,high=110.2);bars[-1].update(open=110.,close=121.,high=121.2)
        self.assertIsNone(T.daily(bars,f[4],10)['stage'])

    def test_second_seal_without_ma10_turning_up_is_not_confirmation(self):
        f=rebuild_fixture();bars=next(iter(f[3].values()));bars[-11].update(close=130.,high=130.2)
        self.assertLess(T.average(bars,len(bars)-1,10),T.average(bars,len(bars)-2,10))
        self.assertIsNone(T.daily(bars,f[4],10)['stage'])

    def test_expired_event_cannot_be_reused_for_a_late_second_limit(self):
        f=rebuild_fixture();bars=next(iter(f[3].values()));del bars[-2:]
        bars,dates=append_closes(f,[110.]*5+[121.])
        bars[-1]['high']=121.
        self.assertIsNone(T.daily(bars,dates,10)['stage'])

    def test_ma5_failure_invalidates_the_old_start(self):
        f=rebuild_fixture();bars=next(iter(f[3].values()));event=bars[-3]['date']
        bars[-2].update(close=90.,low=89.8,high=105.)
        bars[-1].update(open=90.,close=99.,high=99.,low=89.8)
        d=T.daily(bars,f[4],10)
        self.assertNotEqual((d.get('origin') or {}).get('date'),event)

    def test_unknown_limit_regime_and_unsealed_event_are_excluded(self):
        f=rebuild_fixture();bars=next(iter(f[3].values()))
        self.assertIsNone(T.daily(bars,f[4],None)['stage'])
        bars[-3]['high']+=.5;bars[-2]['high']+=.5
        self.assertIsNone(T.daily(bars,f[4],10)['stage'])

    def test_continuing_wave_keeps_its_start_after_more_limits(self):
        f=rebuild_fixture();bars=next(iter(f[3].values()));o=T.daily(bars,f[4],10)['origin']
        bars,dates=append_closes(f,[139.0895]);bars[-1]['high']=bars[-1]['close']
        d=T.daily(bars,dates,10)
        self.assertEqual(d['origin']['date'],o['date'])
        self.assertEqual(d['origin']['confirmation']['date'],o['confirmation']['date'])
        self.assertEqual(d['last_confirmation']['date'],bars[-1]['date'])

    def test_archived_wave_and_export_keep_the_new_start_without_current_membership(self):
        f=rebuild_fixture();bars=next(iter(f[3].values()));setup=T.daily(bars,f[4],10);root=setup['origin']
        # Use a real model container and assert the archive, not current labels.
        f=sample();m=run(f);m.update(status='已退出',eligible=False,stage=5,origin=root,
            last_exit=dict(stage=5,date='2026-10-14',origin=root,reason='本轮支撑失守',platform={},support=120.))
        out=render(f[0],"document.getElementById('proof').innerHTML=mtTable(DATA.stocks)+mtHistoryDetail(DATA.stocks[0].ma_trend);")['els']['proof']['innerHTML']
        table,archive=out.split('data-ma-history',1)
        self.assertNotIn(root['date'],table);self.assertIn(root['date'],archive)
        self.assertIn('当前未入观察',table)
        payload=json.dumps(dict(rows=f[0]['stocks'],data=f[0],contexts=dict(view='radar')),ensure_ascii=False)
        result=subprocess.run(['node','csv_export.js'],input=payload,capture_output=True,text=True,encoding='utf8',check=True)
        row=next(csv.DictReader(io.StringIO(result.stdout.lstrip('\ufeff'))))
        self.assertFalse(row['起点日期']);self.assertEqual(json.loads(row['完整均线依据'])['origin']['date'],root['date'])

    def test_rebuild_proof_scales_prices_but_preserves_returns_and_dates(self):
        f=rebuild_fixture();bars=next(iter(f[3].values()));d=T.daily(bars,f[4],10)
        scaled=T.scale_setup(d,2.)['origin']['confirmation'];p=d['origin']['confirmation']
        for key in ('close','event_close','event_previous_close','event_previous_ma10','ma5_previous','ma10_previous'):
            self.assertEqual(scaled[key],p[key]*2.)
        self.assertEqual(scaled['confirmation_return_pct'],p['confirmation_return_pct'])
        self.assertEqual(scaled['date'],p['date'])

if __name__=='__main__':unittest.main()
