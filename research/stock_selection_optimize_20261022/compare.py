"""Reproduce the frozen factor comparison; no fitting, no production writes."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import copy,gzip,json,hashlib,importlib.util,time
from datetime import datetime
import stock_selection as S
import stock_selection_data as D
import stock_selection_validation as V
import stock_selection_calendar as C

REPORT=Path(__file__).resolve().parent
def save(name,value):
    (REPORT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

if (REPORT/'comparison.json').exists():raise SystemExit('Frozen comparison already exists; copy this research folder before a new experiment.')
started=time.monotonic()
input_path=ROOT/'research/stock_selection_v3_fix2_20261021/replay-inputs.json.gz'
with gzip.open(input_path,'rt',encoding='utf8') as f:bundle=json.load(f)
old=module('_optimization_baseline',REPORT/'baseline/stock_selection.py')
old.R=module('_optimization_baseline_rules',REPORT/'baseline/stock_selection_rules.py').RULES
calendar=C.load_calendar(bundle['calendar'][0],bundle['calendar'][-1])
if not calendar:raise ValueError('authoritative calendar unavailable')
save('freeze.json',dict(frozen_at=str(datetime.now()),implementation_hash=S.IMPLEMENTATION_HASH,version=S.VERSION,rules=S.R,
    input_file=str(input_path),input_sha256=hashlib.sha256(input_path.read_bytes()).hexdigest(),
    calendar_source=C.SOURCE,calendar=calendar,candidate='price + 0.25 * (0.5 * efficiency - 0.5 * persistence)',
    candidate_default=False,scope='Historical current-pool diagnostics, not unbiased point-in-time return evidence'))
observations=[];changes=[];state={};oldstate={}
for day in calendar[-45:]:
    source=dict(bundle['source'],quote_capture_at=day+' 15:00:00',session='已收盘',
        close_daily_verified_at=day+' 16:00:00',_historical_replay=True,_fund_records=bundle['funds'])
    args=(source,bundle['histories'],calendar)
    current=S.build(*args,previous=state,amount_records=bundle['amounts'],now=S.parse_at(day+' 16:00:00'))
    baseline=old.build(*args,previous=oldstate,amount_records=bundle['amounts'],now=S.parse_at(day+' 16:00:00'))
    state=current.pop('_state');oldstate=baseline.pop('_state')
    scored=[c for c in current['order'] if current['items'][c]['score'] is not None and baseline['items'][c]['score'] is not None]
    methods=dict(baseline=sorted(scored,key=lambda c:(-baseline['items'][c]['score'],c))[:20],
        volume_fixed=sorted(scored,key=lambda c:(-current['items'][c]['score'],c))[:20],
        efficiency_candidate=sorted(scored,key=lambda c:(-current['items'][c]['evidence']['candidate_score'],c))[:20])
    ids={c for c,x in current['items'].items() if x['eligible']};oldids={c for c,x in baseline['items'].items() if x['eligible']}
    changes.append(dict(day=day,scored=len(scored),score_changes=sum(current['items'][c]['score']!=baseline['items'][c]['score'] for c in scored),
        added=sorted(ids-oldids),removed=sorted(oldids-ids),qualified=len(ids),amount_complete=current['coverage']['amount_complete']))
    for horizon in (5,10,20):
        values={c:v for c in scored if (v:=V.outcome(bundle['histories'][c],day,horizon,calendar)) is not None}
        if len(values)<len(scored)*.8:continue
        from statistics import median
        benchmark=median(v['return_pct'] for v in values.values())
        for method,codes in methods.items():
            for c in codes:
                if c in values:observations.append(dict(day=day,code=c,method=method,horizon=horizon,excess_pct=values[c]['return_pct']-benchmark,**values[c]))
    print(day,'scored',len(scored),'changed',changes[-1]['score_changes'],flush=True)
report=dict(version=S.VERSION,implementation_hash=S.IMPLEMENTATION_HASH,seconds=time.monotonic()-started,
    aggregate=[dict(method=m,horizon=h,**V.summarize([r for r in observations if r['method']==m and r['horizon']==h])) for m in ('baseline','volume_fixed','efficiency_candidate') for h in (5,10,20)],
    changes=changes,effect_validated=False,candidate_promoted=False,
    limitations=['Current-pool reconstruction; historical membership and delisted universe not reconstructed.',
      'Top20 score diagnostic is not final selection portfolio or tradable return.',
      'Overlapping horizons are not independent observations; no parameter selection from these results.'])
save('comparison.json',report);print(json.dumps(report['aggregate'],ensure_ascii=False),flush=True)
