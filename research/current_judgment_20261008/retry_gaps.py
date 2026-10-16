"""对剩余缺口再取同源整段；返回仍缺失的日期如实留存。"""
import gzip
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config
import datafeed as df
import scoring
OUT=Path(__file__).parent
gaps=json.loads((OUT/'history_gaps.json').read_text(encoding='utf-8'))
codes=[r['code'] for r in gaps]
series=scoring.formal_histories(codes)
with gzip.open(OUT/'histories_before_retry.json.gz','wt',encoding='utf-8') as f:json.dump(series,f,ensure_ascii=False)
fetched,truncated=df.fetch_klines_bulk(codes,days=160)
conn=df.db();conn.execute('PRAGMA busy_timeout=30000')
inserted=df.save_klines(conn,'kline','code',fetched);conn.close()
asof=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))['strength_model']['asof']
checks=[]
for g in gaps:
    b=[b for b in fetched.get(g['code'],[]) if b['date']<=asof];dates={b['date'] for b in b}
    checks.append(dict(code=g['code'],name=g['name'],in_main=g['in_main'],received=len(b),
       filled_dates=[d for d in g['missing_dates'] if d in dates],
       still_missing=[d for d in g['missing_dates'] if d not in dates],
       reason='同源接口仍无这些交易日日线' if b else '同源接口未返回历史'))
result=dict(requested=len(codes),received=len(fetched),rows_written=inserted,truncated=truncated,
    filled_stocks=sum(bool(c['filled_dates']) for c in checks),checks=checks)
(OUT/'retry_gaps.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='checks'},ensure_ascii=False))
