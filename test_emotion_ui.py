"""Render the shared relay and merged-direction scripts with backend fixtures."""
import json,subprocess,unittest
from pathlib import Path
import config
from test_emotion_relay import sample,run


def render(snapshot,action):
    tpl=(config.ROOT/'dashboard_template.html').read_text(encoding='utf-8')
    formats=tpl[tpl.index('function fmt('):tpl.index('/* 成交额格式化')]
    script="""const fs=require('fs'),vm=require('vm'),els={};const ctx={DATA:INPUT,STATE:{pane:'emotion',boardFilterId:null,q:''},RENDERED:{},closeDrawer(){},goPane(){},defaultFilters:()=>({}),refreshPageFreshness(){},document:{activeElement:null,addEventListener(){},querySelector(){return {style:{}}},getElementById(id){return els[id]||(els[id]={innerHTML:'',textContent:'',style:{},contains:()=>false})}},esc:v=>String(v),jsq:v=>String(v),boardById:id=>ctx.DATA.board_catalog.find(b=>b.id===id),setTimeout(){}};vm.createContext(ctx);vm.runInContext(FORMATS,ctx);for(const path of ['radar_ui.js','stock_rank_ui.js','ma_trend_ui.js','emotion_ui.js'])vm.runInContext(fs.readFileSync(path,'utf8'),ctx);ctx.mtSnapshotFresh=()=>true;vm.runInContext(ACTION,ctx);console.log(JSON.stringify({els,ids:ctx.erRows().map(r=>r.code),directions:ctx.erBoardRows().map(b=>b.id)}));"""
    script=script.replace('INPUT',json.dumps(snapshot,ensure_ascii=False)).replace('FORMATS',json.dumps(formats)).replace('ACTION',json.dumps(action))
    result=subprocess.run(['node','--input-type=commonjs','-'],input=script,capture_output=True,text=True,encoding='utf-8',check=True)
    return json.loads(result.stdout)


class EmotionUI(unittest.TestCase):
    def setUp(self):
        self.f=sample();run(self.f);self.s=self.f[0]
    def test_relay_page_uses_roles_closed_and_pending_heights(self):
        r=render(self.s,"MS_VIEW.emotion.scope='continuation';renderEmotion();")
        self.assertEqual(r['ids'],self.s['emotion_relay']['lists']['continuation'])
        r=render(self.s,"MS_VIEW.emotion.scope='all';renderEmotion();")
        body=r['els']['emotion-host']['innerHTML']
        for text in ('近期周期最高标','当前在板最高','节点接续候选','当前涨停','data-tip=','分母与缺口分别显示'):self.assertIn(text,body)
        self.assertNotIn('在板待收盘',body)
        self.assertNotIn('当前在板，待收盘确认',body)
        self.assertNotIn('情绪强度分',body)
    def test_merged_direction_filter_and_member_rank_overlay(self):
        r=render(self.s,"MS_VIEW.directions.kind='theme';erRenderBoards();document.getElementById('rank').innerHTML=msRankTools()+msRankTable(msRankRows(),100);")
        self.assertEqual(r['directions'],[self.s['board_catalog'][0]['id']])
        self.assertIn('全部方向',r['els']['board-center']['innerHTML'])
        self.assertIn('完整成员排名',r['els']['board-center']['innerHTML'])
        body=r['els']['rank']['innerHTML'];self.assertIn('接力地位排序',body);self.assertIn('接力地位 / 板块名次',body)
        self.assertEqual(body.count('data-strength-id='),20)
    def test_expired_relay_quotes_do_not_remain_current_candidates(self):
        r=render(self.s,"mtSnapshotFresh=()=>false;renderEmotion();")
        self.assertEqual(r['ids'],self.s['emotion_relay']['lists']['all'])
        body=r['els']['emotion-host']['innerHTML']
        self.assertIn('行情待刷新 · 保留上次结果',body)
        self.assertIn('上次封板',body)
        self.assertIn('上次晋级记录',body)
        self.assertIn('data-cap-code=',body)
        self.assertNotIn(' · 当前涨停',body)
        self.assertNotIn('>当前晋级<',body)

    def test_retained_records_do_not_become_fresh_and_new_batch_removes_warning(self):
        action="""mtSnapshotFresh=()=>false;renderEmotion();
        if(erLive())throw Error('old records became current');
        mtSnapshotFresh=()=>true;renderEmotion();"""
        r=render(self.s,action);body=r['els']['emotion-host']['innerHTML']
        self.assertNotIn('行情待刷新 · 保留上次结果',body)
        self.assertIn(' · 当前涨停',body)
    def test_emotion_has_two_pools_and_ignores_legacy_hidden_direction_state(self):
        r=render(self.s,"MS_VIEW.emotion.themeIds=['does-not-exist'];renderEmotion();")
        self.assertEqual(r['ids'],self.s['emotion_relay']['lists']['all'])
        body=r['els']['emotion-host']['innerHTML']
        self.assertNotIn('ms-direction-picker',body)
        for label in ('当日涨停池','断板观察池','data-cap-code=','data-break-code=','erOpenPromotion(','炸板次数','封单 / 成交额'):self.assertIn(label,body)
        for p in self.s['emotion_relay']['promotion']:
            self.assertIn('data-promotion-height="'+str(p['height'])+'"',body)
    def test_missing_relay_evidence_preserves_independent_trend_tag(self):
        row=self.s['stocks'][0];row['emotion_relay']['valid']=False
        rank=self.s['emotion_relay']['rankings']['all'];rank['items'][row['code']]['style_labels']=['趋势观察','接力观察']
        r=render(self.s,"document.getElementById('tags').innerHTML=msRankStyleTags(DATA.stocks[0],DATA.emotion_relay.rankings.all.items[DATA.stocks[0].code],'全池',false);")
        body=r['els']['tags']['innerHTML'];self.assertIn('>趋势观察<',body);self.assertNotIn('>接力观察<',body)


if __name__=='__main__':unittest.main()
