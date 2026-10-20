"""Only compact board-member affiliation resolves the frozen stock classification."""
import json
import subprocess
import unittest


def resolve(action):
    code="""const fs=require('fs'),vm=require('vm');const ctx={DATA:{stocks:[{code:'000002',primary_industry:'房地产开发',industry:['房地产开发','房地产']}],coverage_catalog:[]},showBoardById:()=>{},msAffiliation:(r,key)=>({industry:r.industry_detail||r.industry||'行业未收录',key})};vm.createContext(ctx);vm.runInContext(fs.readFileSync('board_chart_ui.js','utf8'),ctx);console.log(JSON.stringify(vm.runInContext(ACTION,ctx)));""".replace('ACTION',json.dumps(action))
    p=subprocess.run(['node','-'],input=code,encoding='utf8',text=True,capture_output=True,check=True)
    return json.loads(p.stdout)


class BoardMemberDisplay(unittest.TestCase):
    def test_compact_member_uses_detailed_industry(self):
        self.assertEqual(resolve("msAffiliation({code:'000002'},'members')")['industry'],'房地产开发')

    def test_other_page_rendering_keeps_original_behavior(self):
        self.assertEqual(resolve("msAffiliation({code:'000002'},'stocks')")['industry'],'行业未收录')

    def test_member_explicit_detail_wins(self):
        self.assertEqual(resolve("msAffiliation({code:'000002',industry_detail:'住宅开发'},'members')")['industry'],'住宅开发')

    def test_unknown_industry_is_pending_not_guessed_from_theme(self):
        self.assertEqual(resolve("msAffiliation({code:'600000',themes:['租售同权']},'members')")['industry'],'行业待核对')


if __name__=='__main__':unittest.main()
