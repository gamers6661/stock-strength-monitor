"""Count completed MA5 repair patterns without altering the production model."""
import copy,gzip,json,random,sqlite3,sys,time
from collections import Counter
from pathlib import Path
from statistics import mean
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,scoring,ma_trend as T,observed_history
OUT=Path(__file__).parent;D=json.loads((OUT/'definition.json').read_text(encoding='utf8'))
started=time.monotonic()
if '--reuse' in sys.argv:
    frozen=json.load(gzip.open(OUT/'inputs.json.gz','rt',encoding='utf8'))
    meta=frozen['meta'];pool=frozen['pool'];histories=frozen['histories'];calendar=frozen['calendar']
    recent20=calendar[-20];recent60=calendar[-60]
else:
    snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf8'))
    meta=dict(source=snap['quote_capture_at'],completed=snap['strength_model']['asof'],version=T.VERSION,implementation_hash=T.IMPLEMENTATION_HASH,
        generation=snap.get('ui_generation'))
    pool={r['code']:dict(name=r['name'],limit_pct=r.get('limit_pct')) for r in snap['stocks']+snap.get('coverage_catalog',[])}
    del snap
    with sqlite3.connect(config.KLINE_DB.resolve().as_uri()+'?mode=ro',uri=True) as con:histories=scoring.formal_histories(pool,con)
    histories={c:observed_history.traded_bars([b for b in bs if b['date']<=meta['completed']]) for c,bs in histories.items()}
    calendar=sorted({b['date'] for bs in histories.values() for b in bs});recent20=calendar[-20];recent60=calendar[-60]
    with gzip.open(OUT/'inputs.json.gz','wt',encoding='utf8',compresslevel=1) as stream:
        json.dump(dict(meta=meta,pool=pool,histories=histories,calendar=calendar),stream,ensure_ascii=False,separators=(',',':'))
print('captured',len(pool),'latest',meta['completed'],'recent20',recent20,'seconds',round(time.monotonic()-started,2),flush=True)
events=[];eligible=0;hist_lengths=Counter();regimes=Counter()
for c in sorted(pool):
    bs=histories.get(c,[]);n=len(bs);hist_lengths[n]+=1
    if n<D['warmup_valid_bars']+D['repair_hold_days']:continue
    eligible+=1
    lines={period:[T.average(bs,i,period) for i in range(n)] for period in (5,10,20)}
    units=[T.atr(bs,i) for i in range(n)]
    ordinary=pool[c]['limit_pct']==10 and not pool[c]['name'].upper().startswith(('ST','*ST'))
    regimes[str(pool[c]['limit_pct'])]+=1
    seen=set()
    for start in range(D['warmup_valid_bars'],n-D['repair_hold_days']+1):
        end=start+D['repair_hold_days']-1
        if not (bs[start-1]['close']<lines[5][start-1] and bs[start]['close']>=lines[5][start]):continue
        prior=range(start-D['recent_weak_days'],start)
        if sum(bs[j]['close']<lines[5][j] for j in prior)<D['minimum_prior_closes_below_ma5']:continue
        if not any(bs[j]['close']<lines[10][j] for j in prior):continue
        if not all(bs[j]['close']>=lines[5][j] for j in range(start,end+1)):continue
        if not all(lines[5][j]>lines[5][j-1] for j in range(end-2,end+1)):continue
        strict_ma10_end=bs[end]['close']>=lines[10][end]>lines[10][end-1]
        if D['repair_end_above_rising_ma10'] and not strict_ma10_end:continue
        if not all(T.positive(b.get('volume')) for b in bs[start-5:end+1]):continue
        repair_mean=mean(b['volume'] for b in bs[start:end+1]);prior_mean=mean(b['volume'] for b in bs[start-5:start]);vr=repair_mean/prior_mean
        if vr>=D['repair_volume_ratio_max_exclusive']:continue
        reset=max(j for j in range(start-5,end+1) if bs[j]['close']<lines[10][j])
        if reset in seen:continue
        seen.add(reset)
        confirmation=None;seal_at=None;breakout_at=None;pending=False
        stop=min(n,start+D['strong_confirmation_total_window'])
        for j in range(start,stop):
            # At most the first five repair closes and five later closes. A
            # completed MA5 loss ends this specific along-MA5 pattern.
            if bs[j]['close']<lines[5][j]:break
            pct=100*(bs[j]['close']/bs[j-1]['close']-1)
            sealed=ordinary and abs(pct-10)<=D['limit_tolerance_pp'] and abs(bs[j]['close']-bs[j]['high'])<1e-8
            span=bs[j]['high']-bs[j]['low'];pos=(bs[j]['close']-bs[j]['low'])/span if span>0 else 0.
            high=max(b['high'] for b in bs[j-5:j]);unit=units[j-1]
            # Only a completed repair can supply its volume baseline. Early
            # seal evidence may be known sooner; the pattern still confirms
            # no earlier than the fifth completed repair close.
            local=(j>=end and T.positive(unit) and bs[j]['close']>=high+D['breakout_atr_buffer']*unit
                and pct>=D['breakout_min_day_pct'] and pos>=D['breakout_min_close_position']
                and T.positive(bs[j].get('volume')) and bs[j]['volume']>=D['breakout_min_volume_vs_repair_mean']*repair_mean)
            if sealed and seal_at is None:seal_at=j
            if local and breakout_at is None:breakout_at=j
            if (sealed or local) and confirmation is None:confirmation=max(end,j)
        if confirmation is None and start+D['strong_confirmation_total_window']>n and all(bs[j]['close']>=lines[5][j] for j in range(end,n)):
            pending=True
        event=dict(code=c,name=pool[c]['name'],start=bs[start]['date'],formation=bs[end]['date'],
            reset=bs[reset]['date'],repair_volume_ratio=vr,repair_start_close=bs[start]['close'],
            formation_close=bs[end]['close'],formation_gain_pct=100*(bs[end]['close']/bs[start-1]['close']-1),
            confirmation=bs[confirmation]['date'] if confirmation is not None else None,
            sealed_at=bs[seal_at]['date'] if seal_at is not None else None,
            local_breakout_at=bs[breakout_at]['date'] if breakout_at is not None else None,
            confirmation_wait_days=confirmation-start+1 if confirmation is not None else None,
            confirm_volume_ratio_vs_previous5=(bs[confirmation]['volume']/mean(b['volume'] for b in bs[confirmation-5:confirmation])) if confirmation is not None else None,
            incomplete_confirmation_window=pending,start_index=start,formation_index=end,confirmation_index=confirmation,
            limit_regime_known=ordinary,strict_ma10_formation=strict_ma10_end)
        if confirmation is not None:
            setup=T.daily(bs[:confirmation+1],calendar,10 if ordinary else None)
            event.update(existing_cycle_at_confirmation=setup['stage'] is not None,existing_stage=setup['stage'],
                existing_origin=(setup.get('origin') or {}).get('date'),last_exit=(setup.get('last_exit') or {}).get('date'))
        events.append(event)
    if len(events) and len(events)%250==0:print('progress',c,'events',len(events),flush=True)
def summary(group):
    strong=[e for e in group if e['confirmation']]
    seals=[e for e in strong if e['sealed_at']]
    missing=[e for e in strong if not e['existing_cycle_at_confirmation']]
    return dict(repair_events=len(group),repair_stocks=len({e['code'] for e in group}),
        strong_events=len(strong),strong_stocks=len({e['code'] for e in strong}),
        sealed_events=len(seals),sealed_stocks=len({e['code'] for e in seals}),
        missing_cycle_events=len(missing),missing_cycle_stocks=len({e['code'] for e in missing}),
        missing_sealed_events=sum(bool(e['sealed_at']) for e in missing),
        covered_events=len(strong)-len(missing),incomplete_windows=sum(e['incomplete_confirmation_window'] for e in group))
recent=[e for e in events if (e['confirmation'] or e['formation'])>=recent20]
result=dict(**meta,pool=len(pool),stocks_with_enough_history=eligible,history_max=max(hist_lengths),
    history_distribution=dict(hist_lengths),known_regimes=dict(regimes),recent20_from=recent20,recent60_from=recent60,
    full=summary(events),recent20=summary(recent),
    strict_ma10_sensitivity=summary([e for e in events if e['strict_ma10_formation']]),
    current_formation_candidates=[e for e in events if e['incomplete_confirmation_window']],
    definition=D,seconds=round(time.monotonic()-started,2))
(OUT/'events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf8')
(OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
rng=random.Random(2026101606);missing=[e for e in events if e['confirmation'] and not e['existing_cycle_at_confirmation']]
recent_missing=[e for e in missing if e['confirmation']>=recent20]
sample=rng.sample(missing,min(12,len(missing)))+rng.sample(recent_missing,min(6,len(recent_missing)))
sample+= [e for e in events if e['name']=='至纯科技']
unique={(e['code'],e['start']):e for e in sample};sample=list(unique.values())
(OUT/'samples.json').write_text(json.dumps(sample,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k not in ('history_distribution','definition','current_formation_candidates')},ensure_ascii=False),flush=True)
print('zhichun',json.dumps([e for e in events if e['name']=='至纯科技'],ensure_ascii=False),flush=True)
