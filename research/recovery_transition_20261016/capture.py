import gzip,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,scoring,close_monitor,intraday
OUT=Path(__file__).parent
raw=config.SNAPSHOT_JSON.read_bytes()
with gzip.open(OUT/'baseline/snapshot.json.gz','wb',compresslevel=1) as f:f.write(raw)
s=json.loads(raw);del raw
with gzip.open(intraday.HISTORY_DIR/'acquisitions'/(s['quote_capture_at'][:10]+'.jsonl.gz'),'rt',encoding='utf8') as stream:
    record=next(v for line in stream if (v:=json.loads(line))['captured_at']==s['quote_capture_at'])
quotes={v[0]:dict(zip(record['fields'],v)) for v in record['rows']}
with sqlite3.connect(config.KLINE_DB.resolve().as_uri()+'?mode=ro',uri=True) as con:h=scoring.formal_histories(quotes,con)
day=s['quote_capture_at'][:10];calendar=sorted({b['date'] for bars in h.values() for b in bars if b['date']<day})
minutes=close_monitor._load_minute_cache(day).get('stocks',{})
with gzip.open(OUT/'inputs.json.gz','wt',encoding='utf8',compresslevel=1) as f:
    json.dump(dict(quotes=quotes,histories=h,calendar=calendar,minutes=minutes),f,ensure_ascii=False,separators=(',',':'))
print(json.dumps(dict(source=s['quote_capture_at'],daily=s['strength_model']['asof'],quotes=len(quotes),histories=len(h),minutes=len(minutes)),ensure_ascii=False),flush=True)
