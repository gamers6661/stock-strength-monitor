"""Final frozen audit after correcting current-direction and distance interpretation."""
import sys,json,gzip,hashlib,copy
from pathlib import Path
from datetime import datetime
from statistics import median,mean
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import stock_selection as S,stock_selection_turning as T,stock_selection_intraday as I
import stock_selection_validation as V
REPORT=Path(__file__).resolve().parent
def save(name,value):(REPORT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
def signature(m):return {c:(x['score'],x['eligible'],x['list_name'],x['dimensions']) for c,x in m['items'].items()}
def ids(m,new=False):return [c for c in (m['turning_order'] if new else m['order']) if m['items'][c]['eligible'] or new and (m['items'][c].get('startup_observation') or m['items'][c].get('observation_only'))][:20]
if (REPORT/'final-comparison.json').exists():raise SystemExit('Final experiment already completed; preserve this frozen evidence.')
save('release-freeze.json',dict(frozen_at=str(datetime.now()),version=S.VERSION,implementation_hash=S.IMPLEMENTATION_HASH,turning_version=T.VERSION,
    turning_rules=T.RULES,core_weights=S.R['weights'],historical_dates=['2026-10-12','2026-10-13'],
    input_sha256=hashlib.sha256((REPORT/'current-inputs.json.gz').read_bytes()).hexdigest(),
    corrections='Require current positive market-relative response; use absolute distance to the local high; retain actual first-seen events.',effectiveness_validated=False))
with gzip.open(REPORT/'current-inputs.json.gz','rt',encoding='utf8') as f:b=json.load(f)
now=S.parse_at(b['now']);m=S.build(b['source'],b['histories'],b['calendar'],b['previous'],b['amounts'],b['frames'],now=now)
oldids=ids(m);original=signature(m);I.attach(m,b['source'],b['calendar']);T.attach(m,b['source'],b['histories'],b['calendar'],b['previous'],b['frames'],now=datetime.now());newids=ids(m,True)
assert original==signature(m)
def rows(codes):return [dict(code=c,name=m['items'][c]['name'],score=m['items'][c]['score'],eligible=m['items'][c]['eligible'],
    startup=m['items'][c]['startup_observation'],stage=m['items'][c]['turning']['stage'],metrics=m['items'][c]['turning']['metrics'],risks=m['items'][c]['turning']['risks']) for c in codes]
save('final-current-comparison.json',dict(source_at=m['source_at'],daily_at=m['daily_at'],counts=m['counts'],core_signatures_unchanged=True,
    active=sum(x['turning']['active'] for x in m['items'].values()),old_top20=rows(oldids),new_top20=rows(newids),
    old_mean_prior5=mean(m['items'][c]['evidence']['returns']['5'] for c in oldids),
    new_mean_prior5=mean(m['items'][c]['evidence']['returns']['5'] for c in newids)))
print('current final',m['counts'],flush=True)
with gzip.open(ROOT/'research/stock_selection_v3_fix2_20261021/replay-inputs.json.gz','rt',encoding='utf8') as f:b=json.load(f)
observations=[];days=[];state={}
for day in ['2026-10-12','2026-10-13']:
    src=dict(b['source'],quote_capture_at=day+' 15:00:00',session='已收盘',close_daily_verified_at=day+' 16:00:00',_historical_replay=True,_fund_records=b['funds'])
    m=S.build(src,b['histories'],b['calendar'],state,b['amounts'],now=S.parse_at(day+' 16:00:00'));state=m['_state'];original=signature(m);oldids=ids(m)
    T.attach(m,src,b['histories'],b['calendar'],historical=True);newids=ids(m,True);assert original==signature(m)
    coverage=m['coverage']['amount_complete']/m['coverage']['daily'];assert coverage>=.8
    days.append(dict(day=day,amount_coverage=coverage,old=oldids,new=newids))
    for horizon in (1,3,5):
        values={c:v for c,x in m['items'].items() if x['score'] is not None and (v:=V.outcome(b['histories'][c],day,horizon,b['calendar'])) is not None}
        base=median(v['return_pct'] for v in values.values())
        for name,codes in [('old_strength',oldids),('recent_turning',newids)]:
            for c in codes:
                if c in values:observations.append(dict(day=day,code=c,method=name,horizon=horizon,excess_pct=values[c]['return_pct']-base,**values[c]))
    print('final historical',day,flush=True)
aggregate=[dict(method=method,horizon=h,**V.summarize([r for r in observations if r['method']==method and r['horizon']==h])) for method in ('old_strength','recent_turning') for h in (1,3,5)]
save('final-comparison.json',dict(implementation_hash=S.IMPLEMENTATION_HASH,days=days,aggregate=aggregate,effectiveness_validated=False,
    note='Only two amount-complete decision dates are available in the frozen historical cohort. This cannot establish effectiveness, early-detection lead or a false-start rate. The first 20-date diagnostic remains under its original implementation hash.'))
print(json.dumps(aggregate,ensure_ascii=False),flush=True)
