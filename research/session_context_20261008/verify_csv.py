"""核对从实际浏览器下载的全池CSV与生产快照。"""
import csv
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config
import session_context
import fund_history
import history_reference

snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
stock={r['code']:r for r in snap['stocks']+snap.get('coverage_catalog',[])}
path=ROOT/'output/playwright/context-round2-all.csv'
with path.open(encoding='utf-8-sig',newline='') as f:
    reader=csv.DictReader(f);rows=list(reader);headers=reader.fieldnames
assert len(rows)==len(stock)==3120
assert {r['代码'] for r in rows}==set(stock)
assert len(headers)==len(set(headers))==232
for r in rows:
    source=stock[r['代码']];c=source['session_context']
    assert r['衔接模型']==session_context.VERSION
    assert r['昨收基准日']==c['previous_close_asof']
    assert r['当日综合判断']==c['label']
    assert r['衔接报价截至']==(c['quote_at'] or '')
    assert r['前五日变化来源']==(source.get('strength_delta5_source') or '')
    assert r['资金历史完成日数']==str(source['fund_history_days'])
    assert None not in r
for module in (session_context,fund_history,history_reference):
    assert Path(module.__file__).resolve().parent==ROOT
result={'rows':len(rows),'columns':len(headers),'model':session_context.VERSION,
        'snapshot':snap['generated_at'],'fields_match':True,'backup_imported':False}
(Path(__file__).parent/'csv_evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
