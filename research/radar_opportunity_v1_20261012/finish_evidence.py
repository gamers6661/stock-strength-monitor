import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import radar_forward_report as forward
OUT=Path(__file__).resolve().parent
raw=(OUT/'browser_output.txt').read_text(encoding='utf-8-sig')
assert '### Error' not in raw,raw[-2000:]
result,_=json.JSONDecoder().raw_decode(raw.split('### Result',1)[1].lstrip())
(OUT/'browser_evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
a=dict(code='600000',at='2026-10-12 10:00:00',kind='breakout',stage='正式触发',outcomes={'1':dict(status='可计算',excess_pp=1.)})
b=dict(a,kind='restart');c=dict(a,code='600001',outcomes={'1':dict(status='可计算',excess_pp=-1.)})
test=forward.summarize([a,b,c],1)
assert test['total']==2 and test['overlap_rows']==1 and test['mean_excess_pp']==0 and test['positive_pct']==50
unknown=forward.summarize([dict(a,outcomes={'1':dict(status='未来完成交易日尚未齐备')})],1)
assert unknown['mean_excess_pp'] is None and unknown['valid']==0
(OUT/'forward_grouping_check.json').write_text(json.dumps(dict(dedup_and_distribution=test,unknown_remains_null=unknown),ensure_ascii=False,indent=2),encoding='utf-8')
print('浏览器HTTP验收成功；前向统计去重及未知边界通过')
