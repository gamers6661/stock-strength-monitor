"""Board-only dispatch, filtering, detail and export behavior in the JS runtime."""
import copy
import csv
import io
import json
import subprocess
import unittest
from pathlib import Path
import board_dynamics as B
from test_board_dynamics import fixture


def render(action):
    s=fixture();s['board_dynamics']=B.build(s);s['ui_generation']='frozen-generation'
    script=r'''
const fs=require('fs'),vm=require('vm'),els={};
function element(){return {innerHTML:'',style:{},textContent:'',querySelector(){return element()},insertAdjacentHTML(pos,h){this.innerHTML=h+this.innerHTML}}}
const ctx={DATA:INPUT,STATE:{pane:'stocks'},document:{activeElement:null,head:{appendChild(){}},createElement:element,getElementById(id){return els[id]||(els[id]=element())}},fmt:(v,d)=>v==null?'—':Number(v).toFixed(d),esc:String,jsq:String,setTimeout:fn=>fn(),showBoardById:id=>{ctx.document.getElementById('dr-b').innerHTML='original detail';return id},renderBoards:()=>{},erRenderBoards:()=>{},downloadMSCSV:(s,n)=>{ctx.csv=s;ctx.csvName=n}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('board_dynamics_ui.js','utf8'),ctx);vm.runInContext(ACTION,ctx);
console.log(JSON.stringify({ids:ctx.bdRows().map(r=>r.id),view:ctx.BD_VIEW,csv:ctx.csv,csvName:ctx.csvName,detail:els['dr-b']&&els['dr-b'].innerHTML,board:els['board-center']&&els['board-center'].innerHTML,dispatch:ctx.renderBoards===ctx.bdRenderBoards&&ctx.erRenderBoards===ctx.bdRenderBoards}));
'''.replace('INPUT',json.dumps(s,ensure_ascii=False)).replace('ACTION',json.dumps(action))
    p=subprocess.run(['node','-'],input=script,encoding='utf8',text=True,capture_output=True,check=True)
    return json.loads(p.stdout)


class BoardDynamicsUI(unittest.TestCase):
    def test_dynamic_dispatch_replaces_both_board_entry_points(self):
        r=render('renderBoards();');self.assertTrue(r['dispatch']);self.assertIn('方向动态',r['board'])

    def test_other_page_board_detail_is_unchanged(self):
        r=render("showBoardById('theme:示例');")
        self.assertEqual(r['detail'],'original detail')

    def test_boards_page_detail_keeps_existing_sections(self):
        r=render("STATE.pane='boards';showBoardById('theme:示例');")
        self.assertIn('original detail',r['detail']);self.assertIn('board-dynamics-detail',r['detail'])
        self.assertIn('frozen-generation',r['detail']);self.assertIn('上调条件',r['detail'])

    def test_csv_uses_visible_order_and_published_generation(self):
        r=render('bdCSV();');rows=list(csv.DictReader(io.StringIO(r['csv'])))
        self.assertEqual([x['ID'] for x in rows],r['ids']);self.assertEqual(rows[0]['UI版本'],'frozen-generation')
        self.assertEqual(rows[0]['状态'],'转强')

    def test_kind_and_status_filters(self):
        self.assertEqual(render("BD_VIEW.kind='industry';")['ids'],[])
        self.assertEqual(render("BD_VIEW.filter='cooling';")['ids'],[])
        self.assertEqual(render("BD_VIEW.filter='spreading';")['ids'],['theme:示例'])

    def test_search_opens_full_directory_and_preserves_composition(self):
        r=render("BD_VIEW.kind='industry';BD_VIEW.filter='cooling';bdSearch({value:'示例',_bdComposing:true},{isComposing:true});")
        self.assertEqual(r['ids'],['theme:示例']);self.assertEqual(r['view']['kind'],'all');self.assertIsNone(r.get('board'))


if __name__=='__main__':unittest.main()
