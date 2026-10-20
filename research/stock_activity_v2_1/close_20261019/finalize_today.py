"""正式执行：仅访问本地缓存/只读日线库，禁止网络行情调用。"""
import hashlib
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT))
import config
import datafeed
import stock_activity as A


started=time.monotonic()
with patch.object(datafeed,'tencent_quotes',side_effect=AssertionError('本次只读本地缓存')),patch.object(datafeed,'realtime_quotes',side_effect=AssertionError('本次只读本地缓存')):
    model=A.refresh_projection()
assert model.get('close_finalized'),'收盘没有定稿'
latest=A.state_path().parent/'latest.json'
mtime=latest.stat().st_mtime_ns
with patch.object(A,'prepare',side_effect=AssertionError('同日定稿不应再次计算')):
    again=A.refresh_projection()
assert again==model and latest.stat().st_mtime_ns==mtime
manifest=json.loads((HERE/'scope_before.json').read_text(encoding='utf8'))
unchanged={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h for f,h in manifest.items() if f!='shared_snapshot'}
with config.SNAPSHOT_JSON.open('rb') as f:unchanged['shared_snapshot']=hashlib.file_digest(f,'sha256').hexdigest()==manifest['shared_snapshot']
assert all(unchanged.values())
rows={r['code']:r for r in A.snapshot_input()['stocks']+A.snapshot_input()['coverage_catalog']}
top=[dict(code=c,name=rows[c]['name'],change_pct=model['items'][c]['quote'].get('change_pct'),
          daily_gain5=model['items'][c]['evidence'].get('gain5'),
          minute_review=model['items'][c]['evidence'].get('close_minute_review'))
     for c in model['order'] if model['items'][c]['list_name']=='reference'][:10]
report=dict(version=model['version'],implementation_hash=model['implementation_hash'],result_version=model['result_version'],
    market_close_at=model['market_close_at'],source_at=model['source_at'],finalized_at=model['finalized_at'],
    counts=model['counts'],close_review=model['close_review'],top_reference=top,network_quote_calls=0,
    second_call_same_result=True,second_call_no_recalculation=True,second_call_no_file_rewrite=True,
    scope_unchanged=unchanged,seconds=round(time.monotonic()-started,3))
(HERE/'today_close.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(report,ensure_ascii=False,indent=2))
