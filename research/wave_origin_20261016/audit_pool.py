"""Replay the fixed rule on every member and audit every new completed entry."""
import ast,copy,gzip,hashlib,importlib.util,json,random,sys,time
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import ma_trend as T,observed_history
OUT=Path(__file__).parent
s=json.load(gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf8'))
d=json.load(gzip.open(OUT/'inputs.json.gz','rt',encoding='utf8'))
rows=s['stocks']+s.get('coverage_catalog',[]);pool={r['code']:r for r in rows};now=datetime.fromisoformat(s['quote_capture_at']);day=s['quote_capture_at'][:10]
def input_digest():return hashlib.sha256(json.dumps([d['quotes'],d['histories']],sort_keys=True).encode()).hexdigest()
digest=input_digest();other=copy.deepcopy([(r['code'],r.get('market_strength'),r.get('emotion_relay')) for r in rows])
spec=importlib.util.spec_from_file_location('wave_before',OUT/'baseline/ma_trend.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
tree=ast.parse((OUT/'baseline/config.py').read_text(encoding='utf8'));node=next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(k,ast.Name) and k.id=='MA_TREND' for k in n.targets))
old.P=eval(compile(ast.Expression(node),'<baseline>','eval'),{'__builtins__':{}});old.VERSION=old.P['version']
started=time.monotonic();cache=OUT/'baseline/replayed_models.json.gz'
if cache.exists():
    frozen=json.load(gzip.open(cache,'rt',encoding='utf8'));assert frozen['digest']==digest
    before=frozen['models'];old_counts=frozen['counts']
else:
    old.attach(s,d['quotes'],pool,d['histories'],d['calendar'],now=now,minute_data=d['minutes'],fetch_minutes=False)
    before={r['code']:copy.deepcopy(r['ma_trend']) for r in rows};old_counts=s['ma_trend']['counts']
    with gzip.open(cache,'wt',encoding='utf8',compresslevel=1) as f:json.dump(dict(digest=digest,models=before,counts=old_counts),f,ensure_ascii=False,separators=(',',':'))
print('baseline',round(time.monotonic()-started,2),flush=True)
def signature(bars):return tuple((b['date'],b['close'],b.get('volume')) for b in observed_history.traded_bars(bars) if b['date']<day)
by_signature={signature(b):c for c,b in d['histories'].items()}
current_code=None;events=[];original_daily=T.daily;original_anchor=T.recent_reclaim_anchor
def traced_daily(bars,calendar,limit_pct=None):
    global current_code
    current_code=by_signature[signature(bars)]
    try:return original_daily(bars,calendar,limit_pct)
    finally:current_code=None
def traced_anchor(*args):
    result=original_anchor(*args)
    if result and result['kind']=='涨停重建均线后确认':
        assert current_code
        events.append(dict(code=current_code,name=pool[current_code]['name'],origin=copy.deepcopy(result)))
    return result
T.daily=traced_daily;T.recent_reclaim_anchor=traced_anchor
try:T.attach(s,d['quotes'],pool,d['histories'],d['calendar'],now=now,minute_data=d['minutes'],fetch_minutes=False);T.validate(s)
finally:T.daily=original_daily;T.recent_reclaim_anchor=original_anchor
after={r['code']:copy.deepcopy(r['ma_trend']) for r in rows}
print('new replay',round(time.monotonic()-started,2),'events',len(events),flush=True)
checks=0;window_checks=0
for e in events:
    bars=observed_history.traded_bars([b for b in d['histories'][e['code']] if b['date']<day]);o=e['origin'];p=o['confirmation']
    start=next(i for i,b in enumerate(bars) if b['date']==o['date']);end=next(i for i,b in enumerate(bars) if b['date']==p['date'])
    assert 1<=end-start<5
    for at in (start,end):
        assert bars[at]['close']==bars[at]['high']
        assert abs(100*(bars[at]['close']/bars[at-1]['close']-1)-10)<=T.P['limit_return_tolerance_pp']
    assert bars[start-1]['close']<T.average(bars,start-1,5) and bars[start]['close']>=T.average(bars,start,5)
    assert all(bars[i]['close']>=T.average(bars,i,5) for i in range(start+1,end+1))
    assert all(bars[end]['close']>=T.average(bars,end,n)>T.average(bars,end-1,n) for n in (5,10))
    if p['previous_exit']:assert p['previous_exit']<o['date']
    else:assert bars[start-1]['close']<T.average(bars,start-1,10)
    # Replay immediately before and at confirmation, including archived waves.
    earlier=T.daily(bars[:end],d['calendar'],10);confirmed=T.daily(bars[:end+1],d['calendar'],10)
    assert ((earlier.get('origin') or {}).get('confirmation') or {}).get('date')!=p['date']
    assert confirmed['origin']['date']==o['date'] and confirmed['origin']['confirmation']['date']==p['date']
    assert confirmed['entry_date']==p['date'] and confirmed['last_confirmation']['date']>=p['date']
    checks+=1
rng=random.Random(2026101604);groups=defaultdict(list)
for c,m in after.items():
    b=before[c]
    if m.get('origin')!=b.get('origin') or m['status']!=b['status'] or m['stage']!=b['stage']:
        group='当前新增有效观察' if m['eligible'] and not b['eligible'] else '历史阶段已更新' if m['status']=='已退出' else '其他阶段变化'
        groups[group].append(c)
    elif m.get('recovery_current'):groups['原收复候选对照'].append(c)
    elif m['eligible']:groups['原有效观察对照'].append(c)
    elif m['status']=='未入选':groups['未入选对照'].append(c)
samples=[]
for group,codes in groups.items():
    for c in rng.sample(sorted(codes),min(6,len(codes))):
        samples.append(dict(group=group,code=c,name=pool[c]['name'],before={k:before[c].get(k) for k in ('stage','status','eligible','origin','last_exit')},
            after={k:after[c].get(k) for k in ('stage','status','eligible','origin','last_exit','entry_date','last_confirmation','quote_at')}))
selected=rng.sample(events,min(16,len(events)))
for e in selected:
    bars=observed_history.traded_bars([b for b in d['histories'][e['code']] if b['date']<=e['origin']['confirmation']['date']])
    for size in (40,80,120):
        if len(bars)<=size or len(bars)-e['origin']['index']>size-22:continue
        cropped=T.daily(bars[-size:],d['calendar'],10)
        assert cropped['origin']['date']==e['origin']['date']
        assert cropped['origin']['confirmation']['date']==e['origin']['confirmation']['date']
        window_checks+=1
        e.setdefault('window_audit',[]).append(dict(size=size,stage=cropped['stage'],origin=(cropped['origin'] or {}).get('date'),confirmation=((cropped['origin'] or {}).get('confirmation') or {}).get('date')))
changed=[c for c in after if any(after[c].get(k)!=before[c].get(k) for k in ('stage','status','eligible','origin','last_exit'))]
result=dict(source=s['quote_capture_at'],completed=s['strength_model']['asof'],pool=len(rows),old_counts=old_counts,new_counts=s['ma_trend']['counts'],
    new_historical_entries=len(events),new_entry_stocks=len({e['code'] for e in events}),first_observed_wave_entries=sum(not e['origin']['confirmation']['previous_exit'] for e in events),
    entry_prefix_checks=checks,window_checks=window_checks,changed_records=len(changed),groups={k:len(v) for k,v in groups.items()},stratified_samples=len(samples),
    inputs_unchanged=digest==input_digest(),other_models_unchanged=other==[(r['code'],r.get('market_strength'),r.get('emotion_relay')) for r in rows],
    version=T.VERSION,hash=T.IMPLEMENTATION_HASH,seconds=round(time.monotonic()-started,2))
assert result['inputs_unchanged'] and result['other_models_unchanged']
with gzip.open(OUT/'models_comparison.json.gz','wt',encoding='utf8',compresslevel=1) as f:json.dump(dict(before=before,after=after),f,ensure_ascii=False,separators=(',',':'))
(OUT/'new_entries.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf8')
(OUT/'stratified_audit.json').write_text(json.dumps(samples,ensure_ascii=False,indent=2),encoding='utf8')
(OUT/'frozen_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,ensure_ascii=False),flush=True)
