"""MA20 admission and independent secondary defense, using observed OHLC."""
import copy,csv,io,json,subprocess,unittest
from datetime import timedelta
import intraday,ma_trend as T
from test_ma_trend import sample,run
from test_market_strength_integration import render


def primary_sample():
    f=sample('ma20');c=next(iter(f[1]));bars=f[3][c]
    for b in bars[-18:]:b['volume']=200.
    bars[-1].update(open=120.8,close=120.8,high=121.)
    line=T.average(bars,len(bars)-1,20);bars[-1]['low']=line+.01
    q=f[1][c];q.update(last_close=120.8,price=120.9,open=120.8,high=121.,low=line+.02)
    q['low']=intraday.align_price_basis(q,bars,f[4])['thresholds'][20]+.02
    return f


def backup_sample():
    f=sample('ma20');c=next(iter(f[1]));bars=f[3][c];start=len(bars)-22
    for j,price in enumerate([105.,115.,125.,130.]+[128.]*18):
        opening=bars[start+j-1]['close']
        bars[start+j].update(open=opening,close=price,high=max(price,opening)+.2,
            low=min(price,opening)-.2 if j<4 else 121.,volume=250. if j==0 else 70. if j<4 else 40.)
    q=f[1][c];q.update(last_close=128.,price=124.,open=128.,high=128.2,low=123.9)
    return f


class DualMA20(unittest.TestCase):
    def test_ma20_touch_admits_without_a_contracted_platform(self):
        f=primary_sample();m=run(f)
        self.assertEqual(m['stage'],20);self.assertTrue(m['eligible'])
        self.assertIsNone(m['secondary_support_price'])
        self.assertEqual(m['support_price'],m['primary_support_price'])
        self.assertGreaterEqual(m['ma20_entry']['rise_pct'],20.)
        self.assertGreaterEqual(m['ma20_entry']['rise_atr'],4.)

    def test_break_below_ma20_can_keep_observing_a_valid_fixed_platform(self):
        f=backup_sample();m=run(f)
        self.assertEqual(m['stage'],20);self.assertTrue(m['eligible'])
        self.assertLess(m['price'],m['primary_support_price'])
        self.assertGreater(m['price'],m['secondary_support_price'])
        self.assertEqual(m['defense_mode'],'平台承接')
        self.assertFalse(T.ma20_position(m['price'],m['ma_value'],m['atr20'])[0])

    def test_final_close_exits_only_after_both_supports_fail(self):
        f=backup_sample();bars=f[3][next(iter(f[3]))];calendar=list(f[4]);day=f[5].date()
        for j,price in enumerate([124.,120.]):
            d=(day+timedelta(days=j)).isoformat();calendar.append(d)
            bars.append(dict(bars[-1],date=d,open=price+.1,close=price,high=price+.2,low=price-.2))
            setup=T.daily(bars,calendar)
            if j==0:self.assertEqual(setup['stage'],20)
        self.assertIsNone(setup['stage']);self.assertEqual(setup['last_exit']['stage'],20)
        self.assertIn('同时失守MA20',setup['last_exit']['reason'])
        self.assertEqual(setup['last_exit']['support'],121.)

    def test_unqualified_platform_does_not_defend_a_failed_ma20(self):
        f=primary_sample();m=run(f);line=m['primary_support_price'];c=next(iter(f[1]))
        previous=copy.deepcopy(f[0]);f[1][c].update(price=line-m['atr20'],low=line-m['atr20']-.01)
        m=run(f,previous=previous)
        self.assertEqual(m['status'],'已退出');self.assertFalse(m['eligible'])

    def test_new_ma20_cycle_does_not_inherit_an_old_entry_clock(self):
        f=primary_sample();run(f);previous=copy.deepcopy(f[0])
        old=previous['stocks'][0]['ma_trend']
        old.update(origin=dict(date='2026-06-25'),entry_at='2026-06-25 10:00:00')
        m=run(f,previous=previous)
        self.assertEqual(m['stage'],20)
        self.assertNotEqual(m['entry_at'],old['entry_at'])

    def test_progression_after_primary_entry_keeps_the_ma20_stage_and_cycle(self):
        f=primary_sample();bars=f[3][next(iter(f[3]))];calendar=list(f[4]);day=f[5].date()
        before=T.daily(bars,calendar);self.assertEqual(before['stage'],20);self.assertFalse(before['platform'])
        for j,price in enumerate([123.]+[122.5]*8):
            d=(day+timedelta(days=j)).isoformat();calendar.append(d)
            bars.append(dict(bars[-1],date=d,open=price,close=price,high=price+.1,low=price-.1,volume=200.))
        after=T.daily(bars,calendar)
        self.assertEqual(after['stage'],20);self.assertEqual(after['origin'],before['origin'])
        self.assertTrue(after['restart_event']);self.assertIsNone(after['last_exit'])

    def test_ended_weak_wave_cannot_fund_a_later_unrelated_ma20_entry(self):
        f=sample();bars=f[3][next(iter(f[3]))];calendar=list(f[4]);day=f[5].date()
        for j,price in enumerate([99.]+[100.+.8*k for k in range(30)]):
            date=(day+timedelta(days=j)).isoformat();calendar.append(date)
            bars.append(dict(bars[-1],date=date,open=price,close=price,high=price+.1,low=price-.1,volume=40.))
        line=sum(b['close'] for b in bars[-19:])/19
        date=(day+timedelta(days=31)).isoformat();calendar.append(date)
        bars.append(dict(bars[-1],date=date,open=line,close=line,high=line+.1,low=line,volume=40.))
        setup=T.daily(bars,calendar)
        self.assertIsNotNone(setup['last_exit'])
        self.assertNotEqual(setup['stage'],20);self.assertFalse(setup['ma20_primary_candidate'])

    def test_small_reclaim_requires_the_actual_fast_minute_path(self):
        f=primary_sample();c=next(iter(f[1]));q=f[1][c]
        ctx=intraday.align_price_basis(q,f[3][c],f[4]);line=ctx['thresholds'][20];unit=ctx['atr20']
        q['low']=line-.05*unit
        points=[];t=f[5].replace(hour=9,minute=31,second=0)
        while t<=f[5]:
            breach=t.strftime('%H:%M')=='09:55';v=line-.04*unit if breach else q['price']
            points.append(dict(at=str(t)[:16],open=v,close=v,high=v+.01,low=q['low'] if breach else v-.01,
                               price_basis='raw',price_basis_source='sina_1m_unadjusted',source='新浪1分钟OHLC'))
            t+=timedelta(minutes=1)
        m=run(f,minutes={c:points});self.assertTrue(m['eligible']);self.assertIn('快速收回',m['events'])
        f=primary_sample();f[1][c]['low']=q['low']
        unknown=run(f);self.assertFalse(unknown['eligible']);self.assertTrue(unknown['pending'])

    def test_inactive_stage_does_not_leak_into_lists_but_has_detail_archive(self):
        f=sample();run(f);m=f[0]['stocks'][0]['ma_trend']
        m.update(status='已退出',eligible=False,stage=10,stage_label='MA10承接整理',
                 origin=dict(date='2026-06-25'),exit_at='2026-09-01 15:00:00',last_exit=None)
        action="MS_VIEW.radar.scope='all';renderRadar();document.getElementById('archive').innerHTML=mtHistoryDetail(DATA.stocks[0].ma_trend);"
        output=render(f[0],action);html=output['els']['ma-radar-host']['innerHTML']
        self.assertNotIn('历史阶段',html);self.assertNotIn('2026-06-25',html)
        self.assertNotIn('历史启动',html);self.assertIn('当前未入观察',html)
        archive=output['els']['archive']['innerHTML']
        self.assertIn('data-ma-history',archive);self.assertIn('2026-06-25',archive)
        self.assertNotIn('<details open',archive)

    def test_export_keeps_the_past_in_evidence_not_in_current_columns(self):
        f=sample();run(f);s=f[0];m=s['stocks'][0]['ma_trend']
        m.update(status='已退出',eligible=False,origin=dict(date='2026-06-25'))
        s['stock_board_ranking']={'all':{},'version':'test'}
        for contexts,date_column in (({},'起点日期'),({'view':'ranking'},'本轮启动日')):
            request=json.dumps(dict(rows=s['stocks'],data=s,contexts=contexts),ensure_ascii=False)
            p=subprocess.run(['node','csv_export.js'],input=request,capture_output=True,text=True,encoding='utf8',check=True)
            exported=list(csv.DictReader(io.StringIO(p.stdout.lstrip('\ufeff'))))[0]
            self.assertEqual(exported['均线阶段'],'暂无当前阶段')
            self.assertEqual(exported[date_column],'')
            self.assertEqual(json.loads(exported['完整均线依据'])['origin']['date'],'2026-06-25')

if __name__=='__main__':unittest.main()
