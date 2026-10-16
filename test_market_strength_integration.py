"""Same-version list/detail/CSV and actual rendering of backend results."""
import copy
import csv
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import config
import ui_payload
import market_strength as M
from test_market_strength import fixture,run


def render(s,action="msRender('stocks');"):
    tpl=(config.ROOT/'dashboard_template.html').read_text(encoding='utf8')
    formats=tpl[tpl.index('function fmt('):tpl.index('/* 成交额格式化')]
    script="""const fs=require('fs'),vm=require('vm');const els={};const ctx={DATA:INPUT,STATE:{boardFilterId:null,q:''},RENDERED:{},closeDrawer:()=>{},goPane:p=>{ctx.pane=p},defaultFilters:()=>({}),document:{activeElement:null,querySelector(){return {style:{}}},getElementById(id){return els[id]||(els[id]={innerHTML:'',textContent:'',style:{}})}},esc:v=>String(v),jsq:v=>String(v),exportCSV:(rows)=>{ctx.exported=rows.map(r=>r.code);return rows},boardById:id=>ctx.DATA.board_catalog.find(b=>b.id===id),openDrawer:(...a)=>{ctx.drawer=a},setTimeout:()=>{}};
    vm.createContext(ctx);vm.runInContext(FORMATS,ctx);vm.runInContext(fs.readFileSync('radar_ui.js','utf8'),ctx);vm.runInContext(ACTION,ctx);console.log(JSON.stringify({els:els,ids:ctx.msRows('stocks').map(r=>r.code),drawer:ctx.drawer,pane:ctx.pane,view:ctx.MS_VIEW.stocks,exported:ctx.exported,formats:[ctx.fmt(null),ctx.pct(null),ctx.fmt(0),ctx.pct(0)]}));"""
    # Rendering assertions use a minimal DOM; browser IME events are checked separately.
    script=script.replace('activeElement:null,', 'activeElement:null,addEventListener(){},')
    script=script.replace('defaultFilters:()=>({}),',"defaultFilters:()=>({}),buildStockCSV:rows=>{ctx.exported=rows.map(r=>r.code);return 'test CSV'},")
    script=script.replace("vm.runInContext(ACTION,ctx)", "vm.runInContext(fs.readFileSync('stock_rank_ui.js','utf8'),ctx);vm.runInContext(fs.readFileSync('ma_trend_ui.js','utf8'),ctx);vm.runInContext(ACTION,ctx)")
    script=script.replace('vm.runInContext(ACTION,ctx)',"ctx.downloadMSCSV=()=>{};vm.runInContext(ACTION,ctx)")
    script=script.replace('INPUT',json.dumps(s,ensure_ascii=False)).replace('FORMATS',json.dumps(formats)).replace('ACTION',json.dumps(action))
    r=subprocess.run(['node','--input-type=commonjs','-'],input=script,capture_output=True,text=True,encoding='utf8',check=True)
    return json.loads(r.stdout)

class MarketStrengthIntegration(unittest.TestCase):
    def setUp(self):
        self.f=fixture(8);self.s=self.f[0]
        for q in self.f[1].values():q.update(price=110.,open=100.,high=110.,low=100.,change_pct=10.)
        run(self.f);self.s['ui_generation']='same-version'
        for b in self.s['board_catalog']:b['catalog_listed']=True
    def test_validate_lists_counts_members(self):self.assertTrue(M.validate(self.s))
    def test_summary_keeps_emotion_only_and_unknowns(self):
        self.f[3][next(iter(self.f[1]))]=[];run(self.f)
        brief=ui_payload.summary(self.s,'v');a=brief['stocks'][0]['market_strength'];self.assertIsNone(a['trend_score']);self.assertIsNone(a['emotion_score']);self.assertTrue(a['day_attack_strong'])
    def test_detail_store_same_scores(self):
        with tempfile.TemporaryDirectory() as d:
            page=Path(d)/'dashboard.html';packet,token=ui_payload.prepare(self.s,'var DATA = /*__DATA__*/null',page)
            stock=ui_payload.detail(token,'stock',self.s['stocks'][0]['code'],page)
            board=ui_payload.detail(token,'board',self.s['board_catalog'][0]['id'],page)
            self.assertEqual(stock['market_strength'],json.loads(json.dumps(self.s['stocks'][0]['market_strength'])));self.assertEqual(board['market_strength'],json.loads(json.dumps(self.s['board_catalog'][0]['market_strength'])));self.assertEqual(ui_payload.unpack(packet)['market_strength'],json.loads(json.dumps(self.s['market_strength'])))
    def test_shared_csv_scores_nulls_and_version(self):
        code=self.s['stocks'][0]['code'];self.f[3][code]=[];run(self.f)
        rows=[ui_payload.csv_row(r) for r in self.s['stocks']]
        data=dict(market_strength=self.s['market_strength'],ui_generation='same-version')
        request=json.dumps(dict(rows=rows,data=data,contexts={}),ensure_ascii=False)
        p=subprocess.run(['node','csv_export.js'],input=request,capture_output=True,text=True,encoding='utf8',check=True)
        exported=list(csv.DictReader(io.StringIO(p.stdout.lstrip('\ufeff'))))
        self.assertEqual(len(exported),8);self.assertEqual(exported[0]['趋势分'],'');self.assertEqual(exported[0]['规则版本'],M.VERSION)
        self.assertEqual(exported[0]['情绪分'],'');self.assertIsNone(self.s['stocks'][0]['market_strength']['emotion_score'])
    def test_merged_picker_and_rankings_use_backend_results(self):
        r=render(self.s);body=r['els']['ms-stock-host']['innerHTML']
        self.assertIn('<table',body);self.assertIn('按板块 / 题材选股',body)
        lists=self.s['market_strength']['stocks']
        self.assertEqual(set(r['ids']),set(lists['all']))
        focus=render(self.s,"msUpdate('stocks','scope','focus');")
        self.assertEqual(set(focus['ids']),set(lists['focus']))
    def test_no_process_groups_or_risk_filter(self):
        body=render(self.s,"msUpdate('stocks','scope','focus');")['els']['ms-stock-host']['innerHTML']
        for word in ('待采样','确认计时','等待确认','判断暂停','受限机会'):self.assertNotIn(word,body)
        self.assertIn('位置偏热',body);self.assertNotIn('雷达参考',body)
        self.s['session']='集合竞价';run(self.f);reference=render(self.s,"renderStocks();")
        self.assertEqual(set(reference['ids']),set(self.s['market_strength']['stocks']['all']))
        self.assertIn('参考行情',reference['els']['stk-sub']['textContent'])
    def test_null_render_is_dash_real_zero_zero(self):
        self.assertEqual(render(self.s)['formats'],['—','—','0.00','0.00%'])
    def test_render_emotion_only_detail(self):
        code=self.s['stocks'][0]['code'];self.f[3][code]=[];run(self.f)
        r=render(self.s,"showStock('"+code+"');")
        html=r['drawer'][2];self.assertIn('情绪',html);self.assertIn(M.VERSION,html);self.assertIn('暂无新增形态标签',html)
    def test_board_table_matches_ids(self):
        r=render(self.s,'renderThemesPage();');html=r['els']['theme-center']['innerHTML'];self.assertIn('theme:测试',html)
    def test_combined_priority_no_third_score(self):
        a=M.empty('t','test');a.update(trend_score=66.,emotion_score=66.,trend_strong=True,emotion_strong=True,focus=True)
        b=M.empty('t','test');b.update(trend_score=99.,emotion_score=None,trend_strong=True,focus=True)
        self.assertLess(M.sort_key(b,'b'),M.sort_key(a,'a'));self.assertNotIn('combined_score',a)
    def test_null_sort_last_not_zero(self):
        a=dict(trend_score=None,emotion_score=99.);b=dict(trend_score=0.,emotion_score=None)
        self.assertLess(M.sort_key(b,'b','trend'),M.sort_key(a,'a','trend'))
    def test_search_can_find_not_selected(self):
        code=self.s['stocks'][0]['code'];self.f[1][code].update(price=100.,high=101.,low=99.,open=100.,change_pct=0.);run(self.f)
        r=render(self.s,"MS_VIEW.stocks.scope='all';MS_VIEW.stocks.q='"+code+"';msRender('stocks');")
        self.assertEqual(r['ids'],[code])
    def test_current_model_ignores_legacy_cache_changes(self):
        before=copy.deepcopy(self.s['market_strength'])
        for r in self.s['stocks']:r['radar_opportunity']=dict(current=False,samples=0,pending=True)
        run(self.f);self.assertEqual(before,self.s['market_strength'])
