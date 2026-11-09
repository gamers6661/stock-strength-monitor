"""Frozen same-input ranking diagnostics. No fitting or trading-return claims."""
import sys,json,gzip,hashlib,time,copy,importlib.util
from pathlib import Path
from datetime import datetime
from statistics import mean,median
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,stock_selection as S,stock_selection_turning as T
import stock_selection_data as D,fund_history,stock_activity as A
import stock_selection_validation as V

REPORT=Path(__file__).resolve().parent
def save(name,value):
    (REPORT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

def signatures(model):return {c:(x['score'],x['eligible'],x['list_name'],x['dimensions']) for c,x in model['items'].items()}
def selected(model,new=False):
    return [c for c in (model['turning_order'] if new else model['order'])
       if model['items'][c].get('eligible') or new and (model['items'][c].get('observation_only') or model['items'][c].get('startup_observation'))][:20]

def current():
    source=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf8'))
    source=dict(source,_security_master=S.read('security_master.json').get('stocks',{}),
        _universe_at=str(datetime.now().date()),_fund_records=fund_history.load(),_gap_proofs=S.read('history_gap_verification.json'))
    h,cal=S.inputs(source);amounts=D.load();previous=S.read('state.json')
    now=S.parse_at(source.get('quote_capture_at')) or datetime.now()
    frames=A.archive_frames(now,set(S.unique_rows(source)),since=now-__import__('datetime').timedelta(seconds=660))
    bundle=dict(source=source,histories=h,calendar=cal,amounts=amounts,previous=previous,frames=frames,now=str(now))
    with gzip.open(REPORT/'current-inputs.json.gz','wt',encoding='utf8',compresslevel=2) as f:json.dump(bundle,f,ensure_ascii=False,separators=(',',':'))
    import stock_selection_intraday as I
    model=S.build(source,h,cal,previous,amounts,frames,now=now);before=signatures(model);oldtop=selected(model)
    I.attach(model,source,cal);T.attach(model,source,h,cal,previous,frames,now=datetime.now());newtop=selected(model,True)
    assert before==signatures(model)
    def rows(codes):
        return [dict(code=c,name=model['items'][c]['name'],score=model['items'][c]['score'],eligible=model['items'][c]['eligible'],
            observation=model['items'][c]['startup_observation'],stage=model['items'][c]['turning']['stage'],
            metrics=model['items'][c]['turning']['metrics'],risks=model['items'][c]['turning']['risks']) for c in codes]
    result=dict(asof=str(datetime.now()),source_at=model['source_at'],daily_at=model['daily_at'],implementation_hash=S.IMPLEMENTATION_HASH,
        core_signatures_unchanged=True,counts=model['counts'],old_top20=rows(oldtop),new_top20=rows(newtop),
        available=sum(x['turning']['available'] for x in model['items'].values()),
        active=sum(x['turning']['active'] for x in model['items'].values()),
        live_evidence=sum(x['turning']['metrics'].get('evidence_mode')=='同刻盘中' for x in model['items'].values()))
    save('current-comparison.json',result);print(json.dumps({k:v for k,v in result.items() if k not in ('old_top20','new_top20')},ensure_ascii=False),flush=True)

def historical():
    path=ROOT/'research/stock_selection_v3_fix2_20261021/replay-inputs.json.gz'
    with gzip.open(path,'rt',encoding='utf8') as f:bundle=json.load(f)
    h=bundle['histories'];cal=bundle['calendar'];source=bundle['source'];state={};observations=[];days=[];first={}
    # Consecutive completed dates, frozen before inspecting results. No synthetic live quotes.
    dates=cal[-25:-5]
    for day in dates:
        src=dict(source,quote_capture_at=day+' 15:00:00',session='已收盘',close_daily_verified_at=day+' 16:00:00',_historical_replay=True,_fund_records=bundle['funds'])
        model=S.build(src,h,cal,state,bundle['amounts'],now=S.parse_at(day+' 16:00:00'));state=model['_state'];before=signatures(model)
        old=selected(model);T.attach(model,src,h,cal,historical=True);new=selected(model,True);assert before==signatures(model)
        coverage=model['coverage']['amount_complete']/max(model['coverage']['daily'],1)
        lists=dict(old_strength=old,recent_turning=new)
        days.append(dict(day=day,amount_coverage=coverage,old=old,new=new,
            old_mean_prior5=mean(model['items'][c]['evidence']['returns']['5'] for c in old) if old else None,
            new_mean_prior5=mean(model['items'][c]['evidence']['returns']['5'] for c in new) if new else None))
        # Final-qualification comparison is meaningful only when the pool's real amounts are covered.
        if coverage>=.8:
            for horizon in (1,3,5):
                values={c:v for c,x in model['items'].items() if x['score'] is not None and (v:=V.outcome(h.get(c,[]),day,horizon,cal)) is not None}
                if len(values)<model['coverage']['daily']*.8:continue
                base=median(v['return_pct'] for v in values.values())
                for name,codes in lists.items():
                    for c in codes:
                        if c in values:observations.append(dict(day=day,code=c,method=name,horizon=horizon,excess_pct=values[c]['return_pct']-base,**values[c]))
        print('historical',day,'old',len(old),'recent',len(new),'amount coverage',round(coverage,3),flush=True)
    aggregate=[dict(method=m,horizon=h,**V.summarize([r for r in observations if r['method']==m and r['horizon']==h])) for m in ('old_strength','recent_turning') for h in (1,3,5)]
    save('historical-comparison.json',dict(implementation_hash=S.IMPLEMENTATION_HASH,turning_version=T.VERSION,days=days,aggregate=aggregate,effectiveness_validated=False,
        limitations=['Current-universe reconstruction; historical membership and delisted pool not recovered.',
          'Only amount-covered dates enter forward-return diagnostics; overlapping samples are not independent.',
          'No fitting, transaction costs, execution simulation, or live first-seen reconstruction.']))
    print(json.dumps(aggregate,ensure_ascii=False),flush=True)

if __name__=='__main__':
    if (REPORT/'experiment-freeze.json').exists():raise SystemExit('Frozen experiment exists; create a new experiment rather than overwrite evidence.')
    save('experiment-freeze.json',dict(frozen_at=str(datetime.now()),implementation_hash=S.IMPLEMENTATION_HASH,version=S.VERSION,turning_rules=T.RULES,
        historical_dates='calendar[-25:-5]',horizons=[1,3,5],no_parameter_search=True))
    current();historical()
