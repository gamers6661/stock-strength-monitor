"""Fixed-input whole-pool replay plus deterministic stratified date audits."""
import ast,copy,gzip,hashlib,importlib.util,json,random,sys,time
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import ma_trend as T
OUT=Path(__file__).parent
s=json.load(gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf8'))
d=json.load(gzip.open(OUT/'inputs.json.gz','rt',encoding='utf8'))
rows=s['stocks']+s.get('coverage_catalog',[]);pool={r['code']:r for r in rows};now=datetime.fromisoformat(s['quote_capture_at'])
def fingerprint():return hashlib.sha256(json.dumps([d['quotes'],d['histories']],sort_keys=True).encode()).hexdigest()
original=fingerprint();other=[(r['code'],r.get('market_strength'),r.get('emotion_relay')) for r in rows];other=copy.deepcopy(other)
spec=importlib.util.spec_from_file_location('old_ma',OUT/'baseline/ma_trend.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
tree=ast.parse((OUT/'baseline/config.py').read_text(encoding='utf8'))
node=next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(k,ast.Name) and k.id=='MA_TREND' for k in n.targets))
old.P=eval(compile(ast.Expression(node),'<frozen config>','eval'),{'__builtins__':{}});old.VERSION=old.P['version']
def models():return {r['code']:copy.deepcopy(r['ma_trend']) for r in rows}
started=time.monotonic()
cache=OUT/'baseline/replayed_models.json.gz'
if cache.exists():
    baseline=json.load(gzip.open(cache,'rt',encoding='utf8'));assert baseline['input_digest']==original
    before=baseline['models'];old_counts=baseline['counts']
else:
    old.attach(s,d['quotes'],pool,d['histories'],d['calendar'],now=now,minute_data=d['minutes'],fetch_minutes=False)
    before=models();old_counts=s['ma_trend']['counts']
    with gzip.open(cache,'wt',encoding='utf8',compresslevel=1) as f:json.dump(dict(input_digest=original,models=before,counts=old_counts),f,ensure_ascii=False,separators=(',',':'))
print('frozen baseline',round(time.monotonic()-started,2),flush=True)
T.attach(s,d['quotes'],pool,d['histories'],d['calendar'],now=now,minute_data=d['minutes'],fetch_minutes=False);T.validate(s)
after=models();print('new replay',round(time.monotonic()-started,2),flush=True)
groups=defaultdict(list);changes=[]
for c,m in after.items():
    b=before[c];proof=(m.get('origin') or {}).get('confirmation') or {}
    if any(b.get(k)!=m.get(k) for k in ('stage','status','eligible','origin')):
        group=proof.get('kind') or ('MA20跟踪/承接' if m.get('stage')==20 and m['status']!='已退出' else '周期衔接及支撑变化')
        groups[group].append(c);changes.append(c)
    else:groups['未变化对照'].append(c)
rng=random.Random(20261016);samples=[];checks=0;date_checks=0
for group,codes in sorted(groups.items()):
    for c in rng.sample(sorted(codes),min(6,len(codes))):
        bars=[b for b in d['histories'].get(c,[]) if b['date']<=after[c].get('asof','')]
        if len(bars)<22:continue
        # Recompute recent prefixes: confirmation cannot exist before that close.
        for end in range(max(22,len(bars)-9),len(bars)+1):
            st=T.daily(bars[:end],d['calendar'],10);o=st.get('origin') or {};f=o.get('confirmation') or {}
            assert not f or o['date']<=f['date']<=bars[end-1]['date']
            if f:assert st['entry_date']>=f['date']
            date_checks+=1
        m=after[c];o=m.get('origin') or {};f=o.get('confirmation') or {}
        if f:
            at=next(i for i,b in enumerate(bars) if b['date']==f['date'])
            earlier=T.daily(bars[:at],d['calendar'],10)
            assert ((earlier.get('origin') or {}).get('confirmation') or {}).get('date')!=f['date']
            checks+=1
        samples.append(dict(code=c,name=pool[c]['name'],group=group,before={k:before[c].get(k) for k in ('stage','status','eligible','origin')},
            after={k:m.get(k) for k in ('stage','status','eligible','origin','entry_date','support_price','ma20_entry','ma20_restart_observation','quote_at','reason')},
            last_closes=[dict(date=b['date'],close=b['close'],ma5=T.average(bars,i,5),ma10=T.average(bars,i,10),ma20=T.average(bars,i,20)) for i,b in list(enumerate(bars))[-5:]]))
for c,m in after.items():
    f=(m.get('origin') or {}).get('confirmation') or {}
    if not f or m['status']=='已退出':continue
    if m.get('quote_at') and not m['pending']:assert m['last_confirmation']['date']>=f['date']
    bars=[b for b in d['histories'][c] if b['date']<=m['asof']]
    at=next(i for i,b in enumerate(bars) if b['date']==f['date'])
    assert f['close']==bars[at]['close'] # frozen raw histories have scale 1
    assert abs(f['ma5']-T.average(bars,at,5))<1e-6
    assert abs(f['ma10']-T.average(bars,at,10))<1e-6
    date_checks+=1
result=dict(source=s['quote_capture_at'],completed=s['strength_model']['asof'],pool=len(rows),old_counts=old_counts,new_counts=s['ma_trend']['counts'],
    groups={g:len(c) for g,c in groups.items()},changed=len(changes),stage_counts=dict(Counter(str(m['stage']) for m in after.values())),
    states=dict(Counter(m['status'] for m in after.values())),stratified_samples=len(samples),prefix_and_value_checks=date_checks,no_lookahead_confirmations=checks,
    input_unchanged=original==fingerprint(),other_models_unchanged=other==[(r['code'],r.get('market_strength'),r.get('emotion_relay')) for r in rows],
    version=T.VERSION,implementation_hash=T.IMPLEMENTATION_HASH,seconds=round(time.monotonic()-started,3))
assert result['input_unchanged'] and result['other_models_unchanged']
with gzip.open(OUT/'models_comparison.json.gz','wt',encoding='utf8') as f:json.dump(dict(before=before,after=after),f,ensure_ascii=False,separators=(',',':'))
(OUT/'frozen_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
(OUT/'stratified_audit.json').write_text(json.dumps(samples,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,ensure_ascii=False),flush=True)
