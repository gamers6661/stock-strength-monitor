import copy,gzip,json,hashlib,sys,time
from pathlib import Path
from datetime import datetime
from collections import Counter
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import market_strength as M,ma_trend as T,emotion_relay as E,relay_history as H,relay_regulation as R
OUT=Path(__file__).parent
with gzip.open(OUT/'frozen_base.json.gz','rt',encoding='utf-8') as f:v=json.load(f)
s=v['snapshot'];q=v['quotes'];h=v['histories'];cal=v['calendar'];now=datetime.fromisoformat(s['quote_capture_at'])
rows=s['stocks']+s.get('coverage_catalog',[]);pool={r['code']:r for r in rows}
print('input',len(q),'short',[(r['code'],r['name'],len(h[r['code']])) for r in rows if len(h[r['code']])<22],flush=True)
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
immutable=dict(quotes=digest(q),histories=digest(h),boards=digest([(b['id'],b.get('member_codes'),b.get('index_trend')) for b in s['board_catalog']]))
before=dict(ma_pending=Counter(r['ma_trend']['reason'] for r in rows if r['ma_trend']['pending']),ma=s['ma_trend']['counts'],
    relationships={r['code']:r.get('emotion_relay',{}).get('continuation',[]) for r in rows if r['code'] in ('000530','002343')})
M.attach(s,q,pool,h,cal,now=now);M.validate(s);print('market strength complete',flush=True)
T.attach(s,q,pool,h,cal,now=now,fetch_minutes=False,minute_data={});T.validate(s);print('MA replay complete',flush=True)
with patch.object(H,'ingest_close'):
    E.attach(s,q,pool,h,cal,now=now,fetch=False)
E.validate(s);print('relay complete',flush=True)
assert immutable==dict(quotes=digest(q),histories=digest(h),boards=digest([(b['id'],b.get('member_codes'),b.get('index_trend')) for b in s['board_catalog']]))
by={r['code']:r for r in s['stocks']+s['coverage_catalog']}
assert not any(n['leader']=='600825' for n in by['000530']['emotion_relay']['continuation'])
report=dict(before=before,after=dict(ma_pending=Counter(r['ma_trend']['reason'] for r in rows if r['ma_trend']['pending']),ma=s['ma_trend']['counts'],
    ms=s['market_strength']['coverage'],relationships={c:by[c]['emotion_relay']['continuation'] for c in ('000530','002343')}),
    unchanged=list(immutable),versions=dict(ms=M.VERSION,ma=T.VERSION,emotion=E.VERSION))
(OUT/'frozen_comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
with gzip.open(OUT/'frozen_output.json.gz','wt',encoding='utf-8',compresslevel=1) as f:json.dump(s,f,ensure_ascii=False)
print(json.dumps(report,ensure_ascii=False),flush=True)
