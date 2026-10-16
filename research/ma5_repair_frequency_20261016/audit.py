"""Verify raw repairs and separate strength AFTER five completed repair days."""
import copy,gzip,json,random,sys
from collections import Counter
from pathlib import Path
from statistics import mean
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import ma_trend as T
OUT=Path(__file__).parent
d=json.load(gzip.open(OUT/'inputs.json.gz','rt',encoding='utf8'));events=json.loads((OUT/'events.json').read_text(encoding='utf8'))
definition=json.loads((OUT/'definition.json').read_text(encoding='utf8'));hist=d['histories'];calendar=d['calendar'];recent=calendar[-20]
checks=Counter();strict=[]
for e in events:
    bs=hist[e['code']];start=e['start_index'];end=e['formation_index']
    line=lambda j,n:round(sum(b['close'] for b in bs[j-n+1:j+1])/n,10)
    assert bs[start-1]['close']<line(start-1,5) and bs[start]['close']>=line(start,5)
    assert all(bs[j]['close']>=line(j,5) for j in range(start,end+1))
    assert any(bs[j]['close']<line(j,10) for j in range(start-5,start))
    assert sum(bs[j]['close']<line(j,5) for j in range(start-5,start))>=2
    assert all(line(j,5)>line(j-1,5) for j in range(end-2,end+1))
    repair=mean(b['volume'] for b in bs[start:end+1]);assert repair<mean(b['volume'] for b in bs[start-5:start])
    checks['raw_repair_events']+=1
    for j in range(end,min(len(bs),start+10)):
        if bs[j]['close']<line(j,5):break
        pct=100*(bs[j]['close']/bs[j-1]['close']-1)
        sealed=e['limit_regime_known'] and abs(pct-10)<=.25 and abs(bs[j]['close']-bs[j]['high'])<1e-8
        unit=T.atr(bs,j-1);span=bs[j]['high']-bs[j]['low'];pos=(bs[j]['close']-bs[j]['low'])/span if span>0 else 0.
        high=max(b['high'] for b in bs[j-5:j]);breakout=bs[j]['close']>=high+.3*unit and pct>=4 and pos>=.75 and bs[j]['volume']>=1.2*repair
        if not (sealed or breakout):continue
        v=T.daily(bs[:j+1],calendar,10 if e['limit_regime_known'] else None)
        # Pending/invalid history cannot be presented as a rule omission.
        assert not v['pending'],(e['code'],bs[j]['date'],v['reason'])
        strict.append(dict(e,strict_confirmation=bs[j]['date'],strict_confirmation_index=j,
            strict_sealed_confirmation=sealed,strict_local_breakout=breakout,
            strict_existing_cycle=v['stage'] is not None,strict_existing_stage=v['stage'],
            strict_existing_origin=(v.get('origin') or {}).get('date')))
        checks['raw_strong_and_model_prefix']+=1
        break
    if e['confirmation']:
        v=T.daily(bs[:e['confirmation_index']+1],calendar,10 if e['limit_regime_known'] else None)
        assert not v['pending']
        assert e['existing_cycle_at_confirmation']==(v['stage'] is not None)
        checks['broad_coverage_prefix']+=1
def counts(xs):
    missing=[e for e in xs if not e['strict_existing_cycle']]
    return dict(strong_events=len(xs),strong_stocks=len({e['code'] for e in xs}),
        sealed_events=sum(e['strict_sealed_confirmation'] for e in xs),
        covered_events=len(xs)-len(missing),missing_events=len(missing),missing_stocks=len({e['code'] for e in missing}))
latest=[e for e in strict if e['strict_confirmation']>=recent]
missing=[e for e in strict if not e['strict_existing_cycle']]
rng=random.Random(2026101607);sample=rng.sample(missing,min(12,len(missing)))
sample+=[e for e in latest if not e['strict_existing_cycle']]
sample+=[e for e in strict if e['name']=='至纯科技']
sample=list({(e['code'],e['start']):e for e in sample}.values())
result=dict(completed=d['meta']['completed'],source=d['meta']['source'],version=T.VERSION,hash=T.IMPLEMENTATION_HASH,
    checks=dict(checks),full=counts(strict),recent20=counts(latest),recent20_from=recent,
    samples=len(sample),recent_missing=[e for e in latest if not e['strict_existing_cycle']])
(OUT/'strict_sequence_events.json').write_text(json.dumps(strict,ensure_ascii=False,indent=2),encoding='utf8')
(OUT/'audit_samples.json').write_text(json.dumps(sample,ensure_ascii=False,indent=2),encoding='utf8')
(OUT/'audit_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k!='recent_missing'},ensure_ascii=False),flush=True)
print('recent missing',json.dumps([{k:e.get(k) for k in ('code','name','start','formation','strict_confirmation','repair_volume_ratio','strict_sealed_confirmation','strict_existing_origin')} for e in result['recent_missing']],ensure_ascii=False),flush=True)
print('samples',json.dumps([{k:e.get(k) for k in ('code','name','start','strict_confirmation','repair_volume_ratio')} for e in sample],ensure_ascii=False),flush=True)
