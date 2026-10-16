import gzip,hashlib,importlib.util,json,sys,time
from collections import Counter
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import ma_trend as T
OUT=Path(__file__).parent
s=json.loads((OUT/'snapshot_before.json').read_text(encoding='utf-8'))
d=json.load(gzip.open(OUT/'inputs.json.gz','rt',encoding='utf-8'))
rows=s['stocks']+s.get('coverage_catalog',[]);pool={r['code']:r for r in rows};now=datetime.fromisoformat(s['quote_capture_at'])
def untouched():return hashlib.sha256(json.dumps([d['quotes'],d['histories']],sort_keys=True).encode()).hexdigest()
before=untouched();original=[(r['code'],r['market_strength'].get('trend_score'),r['market_strength'].get('emotion_score'),r['emotion_relay'].get('height')) for r in rows]
spec=importlib.util.spec_from_file_location('old_ma',OUT/'baseline/ma_trend.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
def compact():
 return {r['code']:{k:r['ma_trend'].get(k) for k in ('stage','status','eligible','pending','reason','origin','platform','support_price','primary_support_price','secondary_support_price','defense_mode','ma20_entry')} for r in rows}
started=time.monotonic()
if (OUT/'models_comparison.json.gz').exists():
    previous=json.load(gzip.open(OUT/'models_comparison.json.gz','rt',encoding='utf8'))['before']
    old_counts=json.loads((OUT/'frozen_comparison.json').read_text(encoding='utf8'))['old_counts']
else:
    old.attach(s,d['quotes'],pool,d['histories'],d['calendar'],now=now,minute_data=d['minutes'],fetch_minutes=False)
    previous=compact();old_counts=dict(s['ma_trend']['counts'])
print('baseline',old_counts,round(time.monotonic()-started,2),flush=True)
T.attach(s,d['quotes'],pool,d['histories'],d['calendar'],now=now,minute_data=d['minutes'],fetch_minutes=False);T.validate(s)
current=compact();new20=[c for c,m in current.items() if m['stage']==20 and m['eligible'] and not(previous[c]['stage']==20 and previous[c]['eligible'])]
changed=[c for c in current if any(previous[c].get(k)!=current[c].get(k) for k in ('stage','eligible','pending'))]
result=dict(captured_at=s['quote_capture_at'],old_counts=old_counts,new_counts=s['ma_trend']['counts'],changed=len(changed),new_ma20=new20,
 inputs_unchanged=before==untouched(),other_scores_unchanged=original==[(r['code'],r['market_strength'].get('trend_score'),r['market_strength'].get('emotion_score'),r['emotion_relay'].get('height')) for r in rows],
 version=T.VERSION,implementation_hash=T.IMPLEMENTATION_HASH,
 new_ma20_examples={c:current[c] for c in new20[:8]},elapsed_seconds=round(time.monotonic()-started,3))
(OUT/'frozen_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
with gzip.open(OUT/'models_comparison.json.gz','wt',encoding='utf-8') as f:json.dump(dict(before=previous,after=current),f,ensure_ascii=False,separators=(',',':'))
sample_codes=new20[:5]+[c for c,m in current.items() if m['status']=='已退出'][:3]
(OUT/'ui_samples.json').write_text(json.dumps(dict(meta=s['ma_trend'],rows=[r for r in rows if r['code'] in sample_codes]),ensure_ascii=False),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k!='new_ma20_examples'},ensure_ascii=False),flush=True)
assert result['inputs_unchanged'] and result['other_scores_unchanged']
