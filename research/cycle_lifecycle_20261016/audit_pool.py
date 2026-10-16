"""Fixed-input whole-pool comparison and independent cycle-lineage checks."""
import ast,copy,gzip,hashlib,importlib.util,json,random,sys,time
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import ma_trend as T,observed_history
OUT=Path(__file__).parent
s=json.load(gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf8'))
d=json.load(gzip.open(OUT/'inputs.json.gz','rt',encoding='utf8'))
rows=s['stocks']+s.get('coverage_catalog',[]);pool={r['code']:r for r in rows}
now=datetime.fromisoformat(s['quote_capture_at']);day=now.date().isoformat()
digest=lambda:hashlib.sha256(json.dumps([d['quotes'],d['histories']],sort_keys=True).encode()).hexdigest()
input_hash=digest();other=copy.deepcopy([(r['code'],r.get('market_strength'),r.get('emotion_relay')) for r in rows])
spec=importlib.util.spec_from_file_location('cycle_before',OUT/'baseline/ma_trend.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
tree=ast.parse((OUT/'baseline/config.py').read_text(encoding='utf8'))
node=next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(k,ast.Name) and k.id=='MA_TREND' for k in n.targets))
old.P=eval(compile(ast.Expression(node),'<baseline>','eval'),{'__builtins__':{}});old.VERSION=old.P['version']
started=time.monotonic()
cache=json.load(gzip.open(OUT/'baseline/replay_cache.json.gz','rt',encoding='utf8'));assert cache['digest']==input_hash
before=cache['models'];old_counts=cache['counts']
print('baseline',round(time.monotonic()-started,2),flush=True)
T.attach(s,d['quotes'],pool,d['histories'],d['calendar'],now=now,minute_data=d['minutes'],fetch_minutes=False);T.validate(s)
after={r['code']:copy.deepcopy(r['ma_trend']) for r in rows};setups={};checks=Counter();groups=defaultdict(list)
for c in pool:
    bars=observed_history.traded_bars([b for b in d['histories'].get(c,[]) if b['date']<day])
    limit=10 if d['quotes'][c].get('limit_pct')==10 and not pool[c]['name'].upper().startswith(('ST','*ST')) else None
    v=T.daily(bars,d['calendar'],limit);setups[c]=v
    if v.get('cycle_id'):
        chain=v['transitions'];assert chain and chain[0]['from_stage'] is None and chain[0]['to_stage']==5,(c,chain)
        assert all(t['cycle_id']==v['origin']['date'] for t in chain)
        for a,b in zip(chain,chain[1:]):assert a['to_stage']==b['from_stage'] and a['date']<=b['date'],(c,a,b)
        assert chain[-1]['to_stage']==v['stage'],(c,chain[-1],v['stage'])
        assert v['origin']['date']<=v['leg_origin']['date']<=v['asof']
        assert not (v.get('last_exit') or {}).get('cause')=='platform_expiry'
        checks['cycle_chains']+=1
        checks['sequential_ma20_handoffs']+=sum(t['to_stage']==20 for t in chain)
        if v.get('restart_event'):groups['同轮再启动'].append(c)
        elif v['stage']==20:groups['MA20当前阶段'].append(c)
        elif v['stage']==10:groups['MA10当前阶段'].append(c)
        elif v['stage']==5:groups['MA5当前阶段'].append(c)
        else:groups['整轮退出'].append(c)
    else:groups['无正式启动对照'].append(c)
    if any(before[c].get(k)!=after[c].get(k) for k in ('stage','status','eligible','origin')):checks['changed_records']+=1
print('whole pool',dict(checks),round(time.monotonic()-started,2),flush=True)
rng=random.Random(2026101605);samples=[]
selected=set()
for group,codes in groups.items():
    for c in rng.sample(sorted(codes),min(5,len(codes))):selected.add(c)
selected.update(c for c,r in pool.items() if r['name'] in ('宝鼎科技','澳弘电子','骏亚科技','皇台酒业','闽东电力','贝瑞基因','澳洋健康'))
for c in sorted(selected):
    v=setups[c];bars=observed_history.traded_bars([b for b in d['histories'][c] if b['date']<day])
    limit=10 if d['quotes'][c].get('limit_pct')==10 and not pool[c]['name'].upper().startswith(('ST','*ST')) else None
    proof=[]
    for t in v.get('transitions',[]):
        end=next(i for i,b in enumerate(bars) if b['date']==t['date'])+1
        prefix=T.daily(bars[:end],d['calendar'],limit)
        # Several handoffs may happen on a single close; verify the entire
        # transition prefix and the unchanged cycle origin at that close.
        assert prefix['origin']['date']==v['origin']['date'],(c,t,prefix['origin'])
        assert t in prefix['transitions'],(c,t,prefix['transitions'])
        proof.append(dict(event=t,at_close_stage=prefix['stage'],origin=prefix['origin']['date']))
        checks['prefix_checks']+=1
    samples.append(dict(code=c,name=pool[c]['name'],group=next(k for k,cs in groups.items() if c in cs),
        before=before[c],after=after[c],daily=v,proof=proof))
result=dict(source=s['quote_capture_at'],completed=s['strength_model']['asof'],pool=len(pool),version=T.VERSION,
    hash=T.IMPLEMENTATION_HASH,old_counts=old_counts,new_counts=s['ma_trend']['counts'],checks=dict(checks),
    samples=len(samples),groups={k:len(cs) for k,cs in groups.items()},inputs_unchanged=input_hash==digest(),
    other_models_unchanged=other==[(r['code'],r.get('market_strength'),r.get('emotion_relay')) for r in rows],seconds=round(time.monotonic()-started,2))
assert result['inputs_unchanged'] and result['other_models_unchanged']
for name,value in [('models_comparison',dict(before=before,after=after)),('daily_setups',setups),('samples',samples)]:
    with gzip.open(OUT/(name+'.json.gz'),'wt',encoding='utf8',compresslevel=1) as f:json.dump(value,f,ensure_ascii=False,separators=(',',':'))
(OUT/'frozen_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,ensure_ascii=False),flush=True)
