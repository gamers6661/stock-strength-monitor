import ast,copy,gzip,json,hashlib,sys,time
from pathlib import Path
from datetime import datetime
from collections import Counter
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import market_strength as M,ma_trend as T,emotion_relay as E
OUT=Path(__file__).resolve().parent
with gzip.open(OUT/'frozen_inputs.json.gz','rt',encoding='utf-8') as f:v=json.load(f)
s=v['snapshot'];q=v['quotes'];h=v['histories'];cal=v['calendar'];now=datetime.fromisoformat(s['quote_capture_at'])
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
rows=s['stocks']+s.get('coverage_catalog',[]);pool={r['code']:r for r in rows}
before=dict(ms=copy.deepcopy(s['market_strength']['coverage']),ma=Counter(r['ma_trend']['status'] for r in rows),emotion=copy.deepcopy(s['emotion_relay']['lists']),
    members=digest([(b['id'],b.get('member_codes'),b.get('index_trend'),b.get('index_current')) for b in s['board_catalog']]),
    histories=digest(h),quotes=digest(q),daily=digest([(r['code'],r.get('stock_strength_score'),r.get('daily_attack_tier'),r.get('signal_close')) for r in rows]))
start=time.monotonic();M.attach(s,q,pool,h,cal,now=now);M.validate(s);T.attach(s,q,pool,h,cal,now=now,fetch_minutes=False,minute_data={});T.validate(s)
assert before['histories']==digest(h) and before['quotes']==digest(q)
assert before['members']==digest([(b['id'],b.get('member_codes'),b.get('index_trend'),b.get('index_current')) for b in s['board_catalog']])
assert before['daily']==digest([(r['code'],r.get('stock_strength_score'),r.get('daily_attack_tier'),r.get('signal_close')) for r in rows])
assert before['emotion']==s['emotion_relay']['lists']
assert s['market_strength']['coverage']['trend_valid']>len(rows)*.9
assert len(s['ma_trend']['pending'])<len(rows)*.1
assert s['ma_trend']['minute_needed']==0
assert all(r['ma_trend']['status']!='支撑过程待核验' for r in rows)
def parameters(path,name):
    node=next(n.value for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets))
    pairs=[(k,v) for k,v in zip(node.keys,node.values) if not isinstance(k,ast.Constant) or k.value!='version'];node.keys=[k for k,v in pairs];node.values=[v for k,v in pairs]
    return ast.dump(node)
for name in ('MA_TREND','MARKET_STRENGTH'):assert parameters(ROOT/'config.py',name)==parameters(OUT/'baseline/config.py',name)
report=dict(before=before,after=dict(ms=s['market_strength']['coverage'],close=s['market_strength'].get('close_verification'),ma=Counter(r['ma_trend']['status'] for r in rows),counts=s['ma_trend']['counts'],
    pending_reasons=Counter(r['ma_trend']['reason'] for r in rows if r['ma_trend']['pending']),minute_needed=s['ma_trend']['minute_needed']),seconds=round(time.monotonic()-start,2),
    hashes=dict(ms=M.IMPLEMENTATION_HASH,ma=T.IMPLEMENTATION_HASH,emotion=E.IMPLEMENTATION_HASH),
    unchanged=['raw quotes and source timestamps','native daily histories','daily strength values','board memberships and index histories','emotion pool membership before relay recomputation','all MA and strength numerical thresholds'],
    cases=[dict(code=r['code'],name=r['name'],model=r['ma_trend']) for r in rows if r['code'] in ('002343','000995','600241','000993','002815','600825')])
(OUT/'frozen_comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
with gzip.open(OUT/'frozen_output.json.gz','wt',encoding='utf-8',compresslevel=1) as f:json.dump(s,f,ensure_ascii=False)
print(json.dumps({k:v for k,v in report.items() if k not in ('before','cases')},ensure_ascii=False),flush=True)
print('cases',[(r['code'],r['name'],r['model']['stage'],r['model']['status'],r['model']['reason']) for r in report['cases']],flush=True)
