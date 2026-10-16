import unittest
from datetime import timedelta
import board_stock_rank as B
import ma_trend as T
from test_ma_trend import sample
import test_ma_radar_transition as rank_fixtures
from test_market_strength_integration import render


class WaveAuditFixes(unittest.TestCase):
    def expired(self,earlier=False):
        f=sample('ma10');c=next(iter(f[3]));bars=f[3][c]
        if earlier:bars[25].update(open=100.,close=105.,high=105.2,low=99.8,volume=250.)
        start=T.daily(bars,f[4]);self.assertEqual(start['stage'],10)
        dates=list(f[4]);day=f[5].date()
        for j in range(25):
            d=(day+timedelta(days=j)).isoformat();dates.append(d)
            bars.append(dict(bars[-1],date=d,open=112.8,close=112.8,high=112.9,low=112.3,volume=40.))
        return start,T.daily(bars,dates)
    def test_expiry_does_not_end_a_supported_cycle(self):
        before,after=self.expired()
        self.assertIn(after['stage'],(5,10));self.assertEqual(after['origin'],before['origin'])
        self.assertIsNone(after['last_exit'])
    def test_expiry_preserves_an_older_exit_without_misdating_the_current_cycle(self):
        before,after=self.expired(earlier=True)
        self.assertEqual(after['last_exit'],before['last_exit'])
        self.assertEqual(after['origin'],before['origin']);self.assertIn(after['stage'],(5,10))
    def test_exited_stock_keeps_complete_membership_but_not_current_stage_filter(self):
        s=rank_fixtures.CompleteRanks().fixture();m=s['stocks'][0]['ma_trend']
        m.update(status='已退出',eligible=False,exit_at='2026-10-09 15:00:00');B.attach(s)
        out=render(s,"msOpenStocks('theme:测试');")
        self.assertIn('600001',out['ids']);self.assertNotIn('历史阶段 · MA5初期推进',out['els']['ms-stock-host']['innerHTML'])
        self.assertNotIn('已退出',out['els']['ms-stock-host']['innerHTML'])
        out=render(s,"msOpenStocks('theme:测试');MS_VIEW.stocks.phase='MA5初期推进';msRender('stocks');")
        self.assertNotIn('600001',out['ids'])
    def test_radar_historical_origin_is_only_in_the_detail_archive(self):
        from test_ma_trend import run
        f=sample();run(f);m=f[0]['stocks'][0]['ma_trend'];m.update(status='已退出',eligible=False)
        out=render(f[0],"mtRender();document.getElementById('archive').innerHTML=mtHistoryDetail(DATA.stocks[0].ma_trend);")
        self.assertNotIn('历史启动 ',out['els']['ma-radar-host']['innerHTML'])
        self.assertNotIn(m['origin']['date'],out['els']['ma-radar-host']['innerHTML'])
        self.assertIn(m['origin']['date'],out['els']['archive']['innerHTML'])
        self.assertIn('强势起点 / 最近确认',out['els']['ma-radar-host']['innerHTML'])

if __name__=='__main__':unittest.main()
