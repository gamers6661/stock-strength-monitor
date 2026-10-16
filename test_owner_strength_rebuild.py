"""Business regressions: history matters, start/pullback survive, views have separate purposes."""
import copy
import unittest
import market_strength as M
from test_market_strength import fixture, run
from test_market_strength_integration import render


def prices(f,code,values,current):
    bars=f[3][code]
    for b,v in zip(bars[-len(values):],values):
        b.update(open=v,close=v,high=v+.5,low=v-.5)
    last=bars[-1]['close']
    f[1][code].update(price=current,last_close=last,open=last,high=max(last,current),low=min(last,current),
                      change_pct=100*(current/last-1),limit_up=round(last*1.1,2))


class OwnerStrengthBusiness(unittest.TestCase):
    def test_down_history_one_limit_is_not_established_trend(self):
        f=fixture();code=next(iter(f[1]))
        prices(f,code,[150,145,140,135,130,125,120,115,110,105]+[100]*10,110)
        m=run(f)[code]
        self.assertFalse(m['trend_strong']);self.assertLess(m['trend_score'],50)
        self.assertEqual(m['emotion_score'],77.5)
        self.assertEqual(m['background']['label'],'中期未恢复')
        self.assertTrue(m['day_attack_strong']);self.assertIn('情绪进攻',m['labels']);self.assertNotIn('新进入强势',m['labels'])
        self.assertEqual(len(f[0]['stocks'][0]['strength_history']),60)

    def test_established_history_beats_one_day_jump(self):
        f=fixture();a,b=list(f[1])[:2]
        prices(f,a,[100+i*1.2 for i in range(20)],123)
        prices(f,b,[100]*20,110)
        m=run(f)
        self.assertGreater(m[a]['trend_score'],m[b]['trend_score'])
        self.assertTrue(m[a]['trend_strong']);self.assertFalse(m[b]['trend_strong'])



    def test_small_negative_day_above_ma5_does_not_alone_mean_pullback(self):
        f=fixture();a=next(iter(f[1]))
        prices(f,a,[100+i*1.2 for i in range(20)],121.8)
        m=run(f)[a]
        self.assertGreater(m['R3'],0);self.assertGreater(f[1][a]['price'],m['trend_parts_by_period']['5']['MA_now'])
        self.assertTrue(m['trend_strong']);self.assertEqual(m['phase'],'推进');self.assertNotIn('回踩整理',m['labels'])

    def test_identical_day_gain_uses_recent_history_for_emotion(self):
        f=fixture();a,b=list(f[1])[:2]
        prices(f,a,[100]*20,110)
        prices(f,b,[100]*14+[100,103,106.09,109.2727,112.550881,115.92740743],127.52)
        for code in (a,b):
            q=f[1][code];q['change_pct']=10.;q['price']=q['last_close']*1.1;q['limit_up']=q['price'];q['high']=q['price']
        m=run(f)
        self.assertAlmostEqual(m[a]['emotion_parts']['D'],m[b]['emotion_parts']['D'])
        self.assertGreater(m[b]['emotion_score'],m[a]['emotion_score'])
        self.assertEqual(m[a]['recent_emotion']['active_days'],0)


    def test_emotion_breaks_do_not_change_trend_order(self):
        a=M.empty('t','test');a.update(trend_score=80,emotion_score=0,dominant_period=5)
        b=copy.deepcopy(a);b['emotion_score']=100
        self.assertEqual(M.sort_key(a,'same','trend'),M.sort_key(b,'same','trend'))

    def test_chart_detail_overview_and_merged_stock_table(self):
        f=fixture();code=next(iter(f[1]));prices(f,code,[100+i for i in range(20)],120);run(f)
        body=render(f[0],"showStock('"+code+"');")['drawer'][2]
        self.assertIn('id="k-cv"',body);self.assertIn('60日历史K线',body)
        stocks=render(f[0])['els']['ms-stock-host']['innerHTML']
        self.assertIn('<table',stocks);self.assertIn('按板块 / 题材选股',stocks)
        overview=render(f[0],'renderOverview();')['els']['ms-overview-host']['innerHTML']
        for section in ('市场温度','正在转强','趋势集中方向','情绪集中方向'):self.assertIn(section,overview)
        self.assertNotIn('<table',overview);self.assertNotEqual(overview,stocks)

    def test_emotion_scope_automatically_uses_emotion_sort(self):
        f=fixture();run(f)
        output=render(f[0],"msStockAxis('emotion');")
        html=output['els']['ms-stock-host']['innerHTML']
        self.assertIn('value="all" selected>全部成员',html)
        self.assertIn('当日进攻、区间保持与近期活跃决定情绪排名',html)
        output=render(f[0],"msUpdate('stocks','scope','day_attack');")
        self.assertEqual(output['ids'],f[0]['market_strength']['stocks']['day_attack'])

    def test_history_return_uses_five_completed_intervals(self):
        f=fixture();a=next(iter(f[1]));prices(f,a,[100,101,102,103,104,105],106)
        m=run(f)[a]
        self.assertAlmostEqual(m['trend_parts_by_period']['5']['historical_R'],5)
        self.assertEqual(m['trend_parts_by_period']['5']['dates'][-1],f[4][-1])

if __name__=='__main__':unittest.main()
