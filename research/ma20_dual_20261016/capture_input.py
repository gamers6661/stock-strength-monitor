import gzip,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import scoring,intraday,close_monitor
OUT=Path(__file__).parent;s=json.loads((OUT/'snapshot_before.json').read_text(encoding='utf-8'))
with gzip.open(intraday.HISTORY_DIR/'acquisitions'/(s['quote_capture_at'][:10]+'.jsonl.gz'),'rt',encoding='utf-8') as stream:
    record=next(v for line in stream if (v:=json.loads(line))['captured_at']==s['quote_capture_at'])
quotes={v[0]:dict(zip(record['fields'],v)) for v in record['rows']}
histories=scoring.formal_histories(quotes)
calendar=sorted({b['date'] for bars in histories.values() for b in bars if b['date']<s['quote_capture_at'][:10]})
minutes=close_monitor._load_minute_cache(s['quote_capture_at'][:10]).get('stocks',{})
with gzip.open(OUT/'inputs.json.gz','wt',encoding='utf-8') as f:
    json.dump(dict(quotes=quotes,histories=histories,calendar=calendar,minutes=minutes),f,ensure_ascii=False,separators=(',',':'))
print('frozen',s['quote_capture_at'],len(quotes),len(histories),len(minutes))
