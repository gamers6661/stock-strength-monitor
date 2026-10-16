"""Regression for the three independently reproduced acceptance failures."""
import copy
import csv
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
import config
import ui_payload
import market_strength as M
from test_market_strength import fixture


class TimeProtection(unittest.TestCase):
    def evaluate(self, at, session, now, verified=None):
        s,q,p,h,c,_=fixture()
        s['session']=session
        if verified:
            s['close_daily_verified_at']=verified
            for bars in h.values():
                bars.append(dict(bars[-1],date=now.date().isoformat(),open=100.,high=110.,low=100.,close=110.))
            c.append(now.date().isoformat())
        for quote in q.values():quote.update(price=110.,open=100.,high=110.,low=100.,change_pct=10.,quote_at=at)
        M.attach(s,q,p,h,c,now=now)
        M.validate(s)
        return s

    def test_illegal_close_quotes_cannot_score_either_axis(self):
        now=datetime(2026,10,13,16)
        for at in ('2026-10-12 15:00:00','2026-10-14 15:00:00','2026-10-13 10:00:00','2026-10-13 12:30:00','2026-10-13 16:30:00'):
            with self.subTest(at=at):
                s=self.evaluate(at,'已收盘',now,str(now))
                self.assertEqual(s['market_strength']['counts']['focus'],0)
                for row in s['stocks']:
                    m=row['market_strength'];self.assertIsNone(m['trend_score']);self.assertIsNone(m['emotion_score']);self.assertTrue(m['data_reasons'])

    def test_formal_close_real_today_survives_age(self):
        now=datetime(2026,10,13,20)
        s=self.evaluate('2026-10-13 15:00:00','已收盘',now,'2026-10-13 16:00:00')
        self.assertEqual(s['market_strength']['counts']['focus'],10)
        self.assertEqual(s['stocks'][0]['market_strength']['emotion_score'],65.5)

    def test_verification_must_belong_to_evaluation_close(self):
        now=datetime(2026,10,13,16)
        for verified in ('2026-10-12 16:00:00','2026-10-14 16:00:00','2026-10-13 10:00:00','16:00:00','garbage'):
            with self.subTest(verified=verified):
                s=self.evaluate('2026-10-13 15:00:00','已收盘',now,verified)
                self.assertEqual(s['market_strength']['counts']['focus'],0)

    def test_lunch_rejects_non_trading_timestamps(self):
        now=datetime(2026,10,13,12,30)
        for at in ('2026-10-13 12:30:00','2026-10-13 11:33:00','2026-10-13 10:00:00','2026-10-12 11:30:00','2026-10-13 13:00:00'):
            with self.subTest(at=at):
                s=self.evaluate(at,'午间休市',now)
                self.assertEqual(s['market_strength']['counts']['focus'],0)

    def test_reliable_morning_edge_and_afternoon_remain_available(self):
        for at,session,now in [('2026-10-13 11:30:00','午间休市',datetime(2026,10,13,12,30)),('2026-10-13 11:31:11','午间休市',datetime(2026,10,13,12,30)),('2026-10-13 11:32:59','午间休市',datetime(2026,10,13,12,30)),('2026-10-13 13:05:00','午盘',datetime(2026,10,13,13,5))]:
            with self.subTest(at=at):
                s=self.evaluate(at,session,now)
                self.assertEqual(s['market_strength']['counts']['focus'],10)
                self.assertEqual(s['stocks'][0]['market_strength']['quote_at'],at)


class BoardExportAndMembers(unittest.TestCase):
    def setUp(self):
        s,q,p,h,c,n=fixture(10)
        for quote in q.values():quote.update(price=110.,open=100.,high=110.,low=100.,change_pct=10.)
        s['board_catalog'].append(dict(id='industry:test',name='industry',type='industry',member_codes=list(q)[1:8]))
        M.attach(s,q,p,h,c,now=n);self.s=s
        for b in s['board_catalog']:b['catalog_listed']=True

    def test_full_board_csv_immutable_before_after_detail_reads(self):
        with tempfile.TemporaryDirectory() as d:
            page=Path(d)/'dashboard.html';packet,token=ui_payload.prepare(self.s,'var DATA = /*__DATA__*/null',page)
            ids=[b['id'] for b in self.s['board_catalog']]
            before=ui_payload.export_board_csv(token,ids,page)
            for identity in ids:
                detail=ui_payload.detail(token,'board',identity,page)
                detail['market_strength']['emotion_parts']={}
                self.assertEqual(before,ui_payload.export_board_csv(token,ids,page))
            records=list(csv.DictReader(io.StringIO(before.decode('utf-8-sig'))))
            self.assertEqual([r['ID'] for r in records],ids)
            for r,b in zip(records,self.s['board_catalog']):
                self.assertEqual(json.loads(r['完整模型依据']),json.loads(json.dumps(b['market_strength'])))
                self.assertEqual(r['UI版本'],token)
                self.assertIn('trend_parts_by_period',json.loads(r['完整模型依据']))
            self.assertEqual(len(list(csv.DictReader(io.StringIO(ui_payload.export_board_csv(token,[ids[1]],page).decode('utf-8-sig'))))),1)
            with self.assertRaises(ValueError):ui_payload.export_board_csv(token,['theme:unknown'],page)

    def test_member_entry_resets_scope_and_retains_only_member_subsets(self):
        s=copy.deepcopy(self.s);s['ui_generation']='same-version'
        script="""const vm=require('vm'),fs=require('fs');const els={};const ctx={DATA:INPUT,STATE:{boardFilterId:null,q:'old'},RENDERED:{},defaultFilters:()=>({}),closeDrawer:()=>{},goPane:()=>{},toast:()=>{},document:{getElementById:id=>els[id]||(els[id]={value:'old'}),activeElement:null},boardById:id=>ctx.DATA.board_catalog.find(b=>b.id===id)};vm.createContext(ctx);vm.runInContext(fs.readFileSync('radar_ui.js','utf8'),ctx);ctx.renderStocks=()=>{};ctx.MS_VIEW.stocks.phase='old';ctx.MS_VIEW.stocks.limit=900;ctx.pickBoardMembers('industry:test');const all=ctx.msRows('stocks').map(r=>r.code),view=JSON.parse(JSON.stringify(ctx.MS_VIEW.stocks));ctx.MS_VIEW.stocks.scope='trend';ctx.MS_VIEW.stocks.sort='trend';const trend=ctx.msRows('stocks').map(r=>r.code);ctx.MS_VIEW.stocks.scope='emotion';ctx.MS_VIEW.stocks.sort='emotion';const emotion=ctx.msRows('stocks').map(r=>r.code);ctx.clearMSMembers();console.log(JSON.stringify({all,trend,emotion,view,cleared:ctx.msRows('stocks').map(r=>r.code),board:ctx.STATE.boardFilterId}));"""
        script=script.replace('activeElement:null', 'activeElement:null,addEventListener(){}')
        result=subprocess.run(['node','-'],input=script.replace('INPUT',json.dumps(s)),text=True,encoding='utf8',capture_output=True,check=True)
        r=json.loads(result.stdout);members=set(s['board_catalog'][1]['member_codes']);lists=s['market_strength']['stocks']
        self.assertEqual(r['all'],[c for c in lists['sorts']['trend'] if c in members])
        for key in ('trend','emotion'):self.assertEqual(r[key],[c for c in lists['sorts'][key] if c in members and c in lists[key]])
        self.assertEqual(r['view']['scope'],'all');self.assertEqual(r['view']['industryIds'],['industry:test']);self.assertEqual(r['view']['phase'],'');self.assertEqual(r['view']['q'],'');self.assertEqual(r['view']['limit'],100);self.assertEqual(r['cleared'],lists['sorts']['trend']);self.assertIsNone(r['board'])

    def test_detail_contains_member_entry(self):
        from test_market_strength_integration import render
        html=render(self.s,"showBoardById('theme:测试');")['drawer'][2]
        self.assertIn('在个股页查看该板块全部成员',html);self.assertIn('pickBoardMembers',html)


if __name__=='__main__':unittest.main()
