"""Compare current-state rules on the exact previously acquired quote batch."""
import gzip,hashlib,importlib.util,json,sys
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import emotion_relay as E,intraday
OUT=Path(__file__).parent
s=json.loads((OUT/'snapshot_before.json').read_text(encoding='utf-8'))
now=datetime.fromisoformat(s['quote_capture_at'])
with gzip.open(intraday.HISTORY_DIR/'acquisitions'/(now.date().isoformat()+'.jsonl.gz'),'rt',encoding='utf-8') as stream:
    record=next(json.loads(line) for line in stream if json.loads(line)['captured_at']==s['quote_capture_at'])
quotes={v[0]:dict(zip(record['fields'],v)) for v in record['rows']}
spec=importlib.util.spec_from_file_location('old_relay',OUT/'baseline/emotion_relay.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
times=sorted(t for q in quotes.values() if (t:=intraday.parse_quote_timestamp(q.get('quote_at'))) and t.date()==now.date())
center=times[len(times)//2];rows=s['stocks']+s.get('coverage_catalog',[])
keys=('valid','reason','sealed','touched','height','height_exact','prior_height','prior_exact','completed_height','limit_price','price')
changed=[];tested=0
def digest():return hashlib.sha256(json.dumps([quotes,[(r['code'],r['emotion_relay']['history']) for r in rows]],sort_keys=True).encode()).hexdigest()
before=digest()
for row in rows:
    c=row['code'];q=quotes.get(c) or {};path=row['emotion_relay']['history']
    a=old.current(c,row,q,path,now,s['session'],center,{})
    b=E.current(c,row,q,path,now,s['session'],center,{})
    tested+=1
    differences={k:[a.get(k),b.get(k)] for k in keys if a.get(k)!=b.get(k)}
    if differences:changed.append(dict(code=c,fields=differences))
result=dict(captured_at=s['quote_capture_at'],tested=tested,current_rule_changes=changed,
            original_quotes_and_histories_unchanged=before==digest(),
            note='This compares current quote admission and board height; acquisition timing and labels are verified separately.')
(OUT/'frozen_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False));assert not changed and result['original_quotes_and_histories_unchanged']
