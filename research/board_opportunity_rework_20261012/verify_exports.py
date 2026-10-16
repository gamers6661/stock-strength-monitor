# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT))
import ui_payload
OUTPUT=ROOT/'output/playwright/board-opportunity-rework-20261012'
raw=(OUTPUT/'verify_live.txt').read_text(encoding='utf-8-sig')
result,_=json.JSONDecoder().raw_decode(raw.split('### Result',1)[1].lstrip())
assert not result['errors'] and result['generation']==result['finalGeneration']
snapshot=ui_payload.full(result['generation']);by={b['id']:b for b in snapshot['board_catalog']}
for item in result['exports']:
    exported=json.loads((OUTPUT/item['file']).read_text(encoding='utf-8-sig'))
    assert [b['id'] for b in exported['rows']]==item['ids'],item['file']
    assert all(b['type']==item['kind'] for b in exported['rows']),item['file']
    for b in exported['rows']:
        assert b['opportunity']==by[b['id']]['opportunity']
        assert b['member_codes']==by[b['id']]['member_codes']
    item['actual_download_equal']=True;item['count']=len(exported['rows'])
assert result['exports'][1]['ids']==['theme:短剧游戏']
(HERE/'browser_evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'exports_checked':len(result['exports']),'sort_actions':len(result['sorts']),
                  'theme_current':result['exports'][1]['ids'],'hidden_tables':result['detail']['tables'],
                  'generation':result['generation'],'page_errors':result['errors']},ensure_ascii=False))
