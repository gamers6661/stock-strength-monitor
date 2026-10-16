import copy,json,unittest
from datetime import timedelta
import ma_trend as T
import intraday
import board_stock_rank as B
import ui_payload
from test_ma_trend import sample,run
from test_market_strength_integration import render

def minutes(f,price):
    day=f[5].date().isoformat();t=f[5].replace(hour=9,minute=31,second=0);out=[]
    while t<=f[5]:
        out.append(dict(at=str(t)[:16],open=price,close=price,high=price+.01,low=price-.01,
            price_basis='raw',price_basis_source='sina_1m_unadjusted',source='新浪1分钟OHLC'))
        t+=timedelta(minutes=1)
    return {next(iter(f[1])):out}

class Transitions(unittest.TestCase):
    def quote(self,f):
        code=next(iter(f[1]));q=f[1][code]
        ctx=intraday.align_price_basis(q,f[3][code],f[4],observation_day=f[5].date().isoformat())
        return code,q,ctx
    def test_latest_ma5_obvious_loss_above_ma10_downgrades(self):
        f=sample('retained');c,q,ctx=self.quote(f)
        price=(ctx['thresholds'][5]+ctx['thresholds'][10])/2
        q.update(price=price,low=price-.01,high=price+.1)
        m=run(f,minutes=minutes(f,price));self.assertEqual(m['stage'],10)
        self.assertNotEqual(m['status'],'已退出');self.assertIsNone(m['exit_at'])
        self.assertTrue(m['tracking']['transitions']);self.assertEqual(m['support_price'],ctx['thresholds'][10])
        self.assertFalse(m['platform']['confirmed'])
    def test_completed_ma5_loss_keeps_wave_and_moves_to_ma10(self):
        f=sample('retained');c,q,ctx=self.quote(f);bars=f[3][c];before=T.daily(bars,f[4]);day=f[5].date().isoformat()
        price=(ctx['thresholds'][5]+ctx['thresholds'][10])/2
        extra=dict(bars[-1],date=day,open=bars[-1]['close'],close=price,low=price-.01,high=bars[-1]['close']+.01)
        after=T.daily(bars+[extra],f[4]+[day]);self.assertEqual(after['stage'],10)
        self.assertEqual(after['origin']['date'],before['origin']['date']);self.assertEqual(after['transitions'][-1]['to_stage'],10)
    def test_ma10_timed_loss_without_ma20_exits(self):
        f=sample('retained');c,q,ctx=self.quote(f);price=ctx['thresholds'][10]-.1*ctx['atr20']
        q.update(price=price,low=price-.01,high=price+.1)
        m=run(f,minutes=minutes(f,price));self.assertEqual(m['stage'],10)
        self.assertEqual(m['status'],'已退出');self.assertIn('没有合格MA20',m['reason'])
    def test_timed_loss_is_not_inferred_from_missing_minutes(self):
        f=sample('retained');c,q,ctx=self.quote(f);price=ctx['thresholds'][10]-.1*ctx['atr20']
        q.update(price=price,low=price-.01,high=price+.1);m=run(f)
        self.assertTrue(m['pending']);self.assertIsNone(m['exit_at']);self.assertEqual(m['stage'],10)
    def test_confirmed_downgrade_survives_later_ma5_recovery(self):
        f=sample('retained');c,q,ctx=self.quote(f);price=(ctx['thresholds'][5]+ctx['thresholds'][10])/2
        q.update(price=price,low=price-.01,high=price+.1);run(f,minutes=minutes(f,price));prior=copy.deepcopy(f[0])
        q.update(price=ctx['thresholds'][5]+.1,quote_at=str(f[5]+timedelta(minutes=1)))
        again=run((*f[:5],f[5]+timedelta(minutes=1)),previous=prior,minutes=minutes(f,price))
        self.assertEqual(again['stage'],10);self.assertEqual(again['origin']['date'],prior['stocks'][0]['ma_trend']['origin']['date'])
    def test_quote_gap_does_not_erase_confirmed_downgrade(self):
        f=sample('retained');c,q,ctx=self.quote(f);price=(ctx['thresholds'][5]+ctx['thresholds'][10])/2
        q.update(price=price,low=price-.01,high=price+.1);run(f,minutes=minutes(f,price));prior=copy.deepcopy(f[0])
        q['quote_at']=str(f[5]-timedelta(minutes=11));missing=run(f,previous=prior)
        self.assertEqual(missing['stage'],10);self.assertTrue(missing['pending']);self.assertTrue(missing['tracking']['transitions'])
        gap=copy.deepcopy(f[0]);q.update(price=ctx['thresholds'][5]+.1,quote_at=str(f[5]+timedelta(minutes=1)))
        restored=run((*f[:5],f[5]+timedelta(minutes=1)),previous=gap,minutes=minutes(f,price))
        self.assertEqual(restored['stage'],10)
    def test_ma20_stage_is_reached_by_a_formed_platform_not_only_rise(self):
        f=sample('ma20');setup=T.daily(f[3][next(iter(f[3]))],f[4])
        self.assertEqual(setup['stage'],20);self.assertGreaterEqual(setup['platform']['rise_pct'],20)
        self.assertTrue(setup['platform']['confirmed']);self.assertGreaterEqual(setup['platform']['days'],T.P['ma20_days'])
        self.assertTrue(any(t['to_stage']==20 for t in setup['transitions']))
    def test_twenty_percent_rise_without_flat_platform_cannot_fallback(self):
        f=sample('ma20');bars=f[3][next(iter(f[3]))]
        for i,b in enumerate(bars[-13:]):b.update(close=120-i*.5,open=121-i*.5,high=121.3-i*.5,low=119.5-i*.5,volume=200.)
        setup=T.daily(bars,f[4]);self.assertNotEqual(setup['stage'],20)
    def test_limit_breakout_requires_known_limit_and_completed_sealed_close(self):
        f=sample();bars=f[3][next(iter(f[3]))];b=bars[-1];b.update(close=110.,high=110.,open=108.,low=108.,volume=60.)
        self.assertIsNone(T.origin(bars,len(bars)-1))
        signal=T.origin(bars,len(bars)-1,limit_pct=10);self.assertEqual(signal['kind'],'涨停突破')
        self.assertLess(signal['volume_ratio'],T.P['volume_ratio'])
        b['high']=110.2;self.assertIsNone(T.origin(bars,len(bars)-1,limit_pct=10))
    def test_limit_day_without_twenty_day_breakout_is_not_entry(self):
        f=sample();bars=f[3][next(iter(f[3]))];bars[-3]['high']=115.;bars[-1].update(close=110.,high=110.,low=108.,volume=60.)
        self.assertIsNone(T.origin(bars,len(bars)-1,limit_pct=10))
    def test_one_price_sealed_breakout_uses_its_independent_entry(self):
        f=sample();c,q,ctx=self.quote(f);bars=f[3][c]
        bars[-1].update(open=110.,close=110.,high=110.,low=110.,volume=60.)
        q.update(last_close=110.,price=110.1,open=110.,high=110.2,low=109.9)
        signal=T.origin(bars,len(bars)-1,limit_pct=10)
        self.assertEqual(signal['kind'],'涨停突破');self.assertTrue(signal['one_price_limit']);self.assertIsNone(signal['close_position'])
        m=run(f);self.assertTrue(m['eligible']);self.assertEqual(m['stage'],5)
    def test_root_and_recent_confirmation_are_separate_dates(self):
        f=sample('retained');bars=f[3][next(iter(f[3]))];before=T.daily(bars,f[4]);day=f[5].date().isoformat()
        extra=dict(bars[-1],date=day,open=bars[-1]['close'],close=bars[-1]['close']*1.1,high=bars[-1]['close']*1.1,low=bars[-1]['close'],volume=400.)
        after=T.daily(bars+[extra],f[4]+[day],limit_pct=10)
        self.assertEqual(after['origin']['date'],before['origin']['date']);self.assertEqual(after['last_confirmation']['date'],day)

class CompleteRanks(unittest.TestCase):
    def test_axis_first_places_compare_strength_even_with_different_coverage(self):
        rows=[dict(code='600001',market_strength=dict(trend_score=99.,emotion_score=None)),
              dict(code='600002',market_strength=dict(trend_score=20.,emotion_score=85.)),
              dict(code='600003',market_strength=dict(trend_score=None,emotion_score=40.)),
              dict(code='600004',market_strength=dict(trend_score=None,emotion_score=35.))]
        s=dict(stocks=rows,board_catalog=[dict(id='theme:sample',member_codes=[r['code'] for r in rows])]);B.attach(s)
        ranking=s['board_catalog'][0]['stock_ranking'];self.assertEqual(ranking['items']['600001']['trend_rank'],1)
        self.assertEqual(ranking['items']['600002']['emotion_rank'],1);self.assertEqual(ranking['all'][0],'600001')
    def fixture(self):
        rows=[]
        for i,(trend,emotion) in enumerate(((80.,10.),(12.,90.),(80.,60.),(None,None),(10.,20.)),1):
            rows.append(dict(code=f'60000{i}',name=f'样本{i}',market_strength=dict(trend_score=trend,emotion_score=emotion,emotion_strong=emotion is not None and emotion>=65,quote_at='2026-10-14 15:00:00'),ma_trend=dict(stage=5 if i==1 else None,eligible=i==1,pending=False,status='守线观察',stage_label='MA5初期推进' if i==1 else '暂无合格阶段',reason='已核验',valid_until='2099-01-01 00:00:00')))
        s=dict(stocks=rows,board_catalog=[dict(id='theme:测试',name='测试',type='theme',catalog_listed=True,member_codes=[r['code'] for r in rows]+['600009'],members=[dict(code='600009',name='缺失样本')])],market_strength={})
        B.attach(s);B.validate(s);return s
    def test_board_contains_weak_emotion_only_and_missing_members(self):
        s=self.fixture();ranking=s['board_catalog'][0]['stock_ranking'];self.assertEqual(len(ranking['all']),6)
        self.assertEqual(ranking['items']['600002']['style_labels'],['情绪强势','情绪前排'])
        self.assertTrue(ranking['items']['600009']['missing']);self.assertEqual(ranking['trend_valid'],4)
        self.assertEqual(ranking['items']['600001']['trend_rank'],ranking['items']['600003']['trend_rank'])
    def test_ui_select_board_shows_full_rank_and_both_axes(self):
        s=self.fixture();out=render(s,"msOpenStocks('theme:测试');")
        self.assertEqual(set(out['ids']),set(s['board_catalog'][0]['member_codes']))
        body=out['els']['ms-stock-host']['innerHTML'];self.assertIn('情绪强势',body);self.assertIn('MA5初期推进',body)
        self.assertIn('data-tip=',body);self.assertIn('板块第',body)
    def test_search_keeps_original_board_rank(self):
        s=self.fixture();out=render(s,"msOpenStocks('theme:测试');MS_VIEW.stocks.q='样本3';msRender('stocks');")
        self.assertEqual(out['ids'],['600003']);rank=s['board_catalog'][0]['stock_ranking']['items']['600003']['rank']
        self.assertIn('data-board-rank="'+str(rank)+'"',out['els']['ms-stock-host']['innerHTML'])
    def test_ma_pending_does_not_hide_independent_valid_emotion(self):
        s=self.fixture();s['stocks'][1]['ma_trend'].update(pending=True,status='支撑过程待核验',reason='分钟记录有缺口')
        B.attach(s);out=render(s,"msOpenStocks('theme:测试');MS_VIEW.stocks.scope='emotion';msRender('stocks');")
        self.assertIn('600002',out['ids']);body=out['els']['ms-stock-host']['innerHTML']
        self.assertIn('情绪强势',body);self.assertIn('分钟记录有缺口',body)
    def test_summary_retains_same_board_ranks(self):
        s=self.fixture();brief=ui_payload.summary(s,'frozen');self.assertEqual(brief['board_catalog'][0]['stock_ranking'],s['board_catalog'][0]['stock_ranking'])

if __name__=='__main__':unittest.main()
