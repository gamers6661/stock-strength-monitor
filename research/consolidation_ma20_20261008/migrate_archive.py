# -*- coding: utf-8 -*-
"""只升级原有9月30日收盘留档，不回填今天报价或历史实盘预警。"""
import copy,gzip,json,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config,datafeed,strength,trend_consolidation as tc
folder=Path(__file__).resolve().parent
before=json.loads((folder/'before'/'snapshot.json').read_text(encoding='utf-8'))
assert before['quote_capture_at'][:10]=='2026-09-30'
snap=copy.deepcopy(before)
codes={r['code'] for group in tc.GROUPS for r in before['trend_consolidation'][group]}
conn=datafeed.db()
bars={c:[b for b in datafeed.load_kline(conn,'kline','code',c,limit=120) if b['date']<='2026-09-30'] for c in codes}
conn.close()
calendar=strength.trading_calendar(bars)
with patch.object(tc,'DIRECTORY',folder/'isolated_empty_archive'):
    model=tc.attach(snap,bars,{},{},calendar,previous=before,close_history_loader=lambda code:bars[code])
model.update(review_mode='rule_upgrade_close_review',review_note='原9月30日收盘留档按MA20规则升级复核；不是今天行情，也不是历史实盘预警')
model['phase_note']=model['review_note']
for group in tc.GROUPS:
    for item in model[group]:item.update(reference_only=True,reference_reason=model['review_note'])
retained={r['code']:r for group in tc.GROUPS for r in model[group]}
for row in snap['stocks']+snap.get('coverage_catalog',[]):
    if row['code'] in retained:row['trend_consolidation']=dict(retained[row['code']])
assert snap['quote_capture_at']==before['quote_capture_at'] and snap['generated_at']==before['generated_at']
for a,b in zip(before['stocks']+before.get('coverage_catalog',[]),snap['stocks']+snap.get('coverage_catalog',[])):
    assert {k:v for k,v in a.items() if k!='trend_consolidation'}=={k:v for k,v in b.items() if k!='trend_consolidation'}
assert model['version']==tc.VERSION and model['day']=='2026-09-30'
with gzip.open(folder/'archive_upgrade_snapshot.json.gz','wt',encoding='utf-8') as stream:json.dump(snap,stream,ensure_ascii=False)
if '--publish-archive' in sys.argv:
    config.atomic_write_text(tc.DIRECTORY/'2026-09-30.json',json.dumps(model,ensure_ascii=False,separators=(',',':')))
(folder/'archive_upgrade.json').write_text(json.dumps(dict(version=model['version'],day=model['day'],
    original_capture_at=snap['quote_capture_at'],main=len(model['rows']),completed=len(model['completed_rows']),
    pending=len(model['pending_rows']),withdrawn=len(model['withdrawn_rows']),other_stock_field_changes=0,
    note=model['review_note']),ensure_ascii=False,indent=2),encoding='utf-8')
print((folder/'archive_upgrade.json').read_text(encoding='utf-8'))
