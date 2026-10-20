"""Exercise actual page renderer load order, including the final auction binding."""
import json
import subprocess
import unittest

import config
from test_market_strength import fixture, run


def sample():
    f=fixture(8);run(f);s=f[0]
    s.update(session='竞价结束',quote_capture_at='2026-10-19 09:26:20',ui_generation='auction-generation')
    items=[]
    for i,r in enumerate(s['stocks']):
        c=dict(code=r['code'],name=r['name'],quote_valid=True,price_basis_valid=True,price=110+i,
               quote_at='2026-10-19 09:26:00',gap_pct=10+i,price_attack_score=80+i,price_attack_tier='A',
               label='竞价承接',current_label='竞价现价突破原平台',risks=['现价失守MA10'] if i==7 else [],
               current_ma10=100,current_ma20=99,monitor_candidate=i<2,reason='源报价结合昨日结构')
        r['session_context']=c;items.append(c)
    m=dict(day='2026-10-19',auction_rows=items,price_judged_count=8,structure_judged_count=8)
    s['session_context']=m;s['intraday_model']={'auction_latest_quote_at':'2026-10-19 09:26:00'}
    for b in s['board_catalog']:
        b.update(catalog_listed=True,member_auction=dict(ready=True,change_pct=3.25,up_pct=75,valid_count=8,pool_count=8,coverage_pct=100,quote_at='2026-10-19 09:26:00'))
    return s


def render(s,action,now='2026-10-19T09:29:59'):
    tpl=(config.ROOT/'dashboard_template.html').read_text(encoding='utf-8')
    formats=tpl[tpl.index('function fmt('):tpl.index('/* 成交额格式化')]
    js=r'''
const fs=require('fs'),vm=require('vm'),els={};
function el(){return {innerHTML:'',textContent:'',style:{},appendChild(){},prepend(){},insertBefore(){},contains(){return false},querySelector(){return null},insertAdjacentHTML(p,h){this.innerHTML=p==='afterbegin'?h+this.innerHTML:this.innerHTML+h},parentNode:{style:{},parentNode:{insertBefore(){}}}}}
const RealDate=Date;class Clock extends RealDate{constructor(...a){super(...(a.length?a:[NOW]))}static now(){return new RealDate(NOW).getTime()}}
const ctx={Date:Clock,DATA:INPUT,STATE:{pane:'stocks',q:''},RENDERED:{},setTimeout:()=>{},location:{protocol:'http:'},document:{activeElement:null,head:{appendChild(){}},addEventListener(){},createElement:el,querySelector:()=>el(),getElementById:id=>els[id]||(els[id]=el())},esc:String,jsq:String,closeDrawer:()=>{},goPane:p=>{ctx.STATE.pane=p},defaultFilters:()=>({}),refreshPageFreshness:()=>{},openDrawer:(a,b,h)=>{els['dr-b']=el();els['dr-b'].innerHTML=h},stockPoolRows:()=>ctx.DATA.stocks,sessionNow:()=>new Clock().getHours()===9&&new Clock().getMinutes()<30?'竞价结束':'早盘',parseDT:v=>v?new Clock(v.replace(' ','T')):null};ctx.window=ctx;
ctx.boardById=id=>ctx.DATA.board_catalog.find(b=>b.id===id);vm.createContext(ctx);vm.runInContext(FORMATS,ctx);
for(const f of ['csv_export.js','radar_ui.js','stock_rank_ui.js','ma_trend_ui.js','board_chart_ui.js','emotion_ui.js','board_dynamics_ui.js','auction_ui.js'])vm.runInContext(fs.readFileSync(f,'utf8'),ctx,{filename:f});
vm.runInContext(ACTION,ctx);console.log(JSON.stringify(els));
'''
    js=js.replace('NOW',json.dumps(now)).replace('INPUT',json.dumps(s,ensure_ascii=False)).replace('FORMATS',json.dumps(formats)).replace('ACTION',json.dumps(action))
    p=subprocess.run(['node','-'],input=js,encoding='utf-8',text=True,capture_output=True)
    if p.returncode:raise AssertionError(p.stderr)
    return json.loads(p.stdout)


class AuctionUI(unittest.TestCase):
    def test_current_page_entry_points_use_same_auction_judgment_after_all_overrides(self):
        s=sample()
        for action,host in [('renderOverview();','ms-overview-host'),('renderStocks();','ms-stock-host'),
                            ('renderRadar();','ma-radar-host'),('renderEmotion();','emotion-host')]:
            html=render(s,action)[host]['innerHTML']
            self.assertIn('竞价现价突破原平台',html)
            self.assertIn('2026-10-19 09:26:00',html)
            self.assertIn('110.00',html)

    def test_board_and_theme_pages_read_member_auction_values(self):
        for action,host in [('renderBoards();','board-center'),('renderThemesPage();','theme-center')]:
            html=render(sample(),action)[host]['innerHTML']
            self.assertIn('3.25%',html);self.assertIn('8 / 8',html)
            self.assertIn('2026-10-19 09:26:00',html)



    def test_stock_and_board_details_show_auction_sources(self):
        s=sample();code=s['stocks'][0]['code']
        html=render(s,"showStock('"+code+"');")['dr-b']['innerHTML']
        self.assertIn('最新竞价判断',html);self.assertIn('110.00',html)
        html=render(s,"showBoardById('theme:测试');")['dr-b']['innerHTML']
        self.assertIn('最新竞价成员判断',html);self.assertIn('3.25%',html)




    def test_at_open_auction_override_and_review_are_absent(self):
        s=sample();s['session']='早盘'
        html=render(s,'renderOverview();',now='2026-10-19T09:30:00')['ms-overview-host']['innerHTML']
        self.assertNotIn('aq-overview',html)
        self.assertNotIn('回看竞价',html)


if __name__=='__main__':unittest.main()
