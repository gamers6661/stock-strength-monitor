"""Frozen-input causal replay and descriptive follow-up, never a live admission rule."""
import ast,copy,gzip,inspect,importlib.util,json,sqlite3,sys
from collections import Counter,defaultdict
from pathlib import Path
from statistics import mean,median
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,datafeed,strength
OUT=Path(__file__).resolve().parent
cfg=ast.parse((OUT/'baseline/config.py').read_text(encoding='utf-8'))
expr=next(n.value for n in cfg.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='MA_TREND' for t in n.targets))
config.MA_TREND=eval(compile(ast.Expression(expr),'frozen-parameters','eval'),{'__builtins__':{}},{})
spec=importlib.util.spec_from_file_location('frozen_ma_trend',OUT/'baseline/ma_trend.py')
T=importlib.util.module_from_spec(spec);spec.loader.exec_module(T)

# Instrument a copy of daily() to observe each completed day. Production source,
# state and caches are not modified; the replay still only sees bars at/before i.
code=inspect.getsource(T.daily).replace('def daily(', 'def daily_trace(')
code=code.replace("    if key in _DAILY_CACHE:return copy.deepcopy(_DAILY_CACHE[key])\n",'')
code=code.replace('    for i in range(21,len(bars)):', '    audit_path=[]\n    for i in range(21,len(bars)):')
code=code.replace('    i=len(bars)-1', '''        audit_path.append(dict(index=i,date=bars[i]['date'],stage=active,
            origin=(root or {}).get('date'),entry=entered,signal=copy.deepcopy(signal),
            exit=copy.deepcopy(last_exit),lifecycle=lifecycle,
            platform=copy.deepcopy(platform) if active in (10,20) else {}))
    i=len(bars)-1''')
code=code.replace('    if len(_DAILY_CACHE)>3500:_DAILY_CACHE.clear()\n','')
code=code.replace("    _DAILY_CACHE[key]=copy.deepcopy(out)","    out['audit_path']=audit_path")
space=dict(T.__dict__);exec(compile(code,str(OUT/'instrumented_daily.py'),'exec'),space);trace=space['daily_trace']

with gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf-8') as stream:s=json.load(stream)
rows=s['stocks']+s.get('coverage_catalog',[]);asof=s['strength_model']['asof']
conn=sqlite3.connect((OUT/'baseline/market.db').resolve().as_uri()+'?mode=ro',uri=True)
hist={r['code']:[b for b in datafeed.load_kline(conn,'kline','code',r['code'],limit=160) if b['date']<=asof] for r in rows};conn.close()
cal=strength.trading_calendar(hist);last=cal.index(asof);recent=set(cal[max(0,last-19):last+1]);holdout=set(cal[max(0,last-39):last+1])
events=[];invalid=[];paths={};counts=Counter();audit_issues=defaultdict(list)
for r in rows:
    c=r['code'];bars=hist[c]
    if not bars or bars[-1]['date']!=asof:invalid.append(dict(code=c,name=r['name'],reason='最新完成日未覆盖'));continue
    if r['name'].upper().startswith(('ST','*ST')):invalid.append(dict(code=c,name=r['name'],reason='非普通10%制度'));continue
    setup=trace(bars,cal,limit_pct=10)
    if setup['pending']:invalid.append(dict(code=c,name=r['name'],reason=setup['reason']));continue
    path={x['index']:x for x in setup['audit_path']};paths[c]=path
    for i,x in path.items():
        root=x['origin'];exit=x['exit'];p=x['platform']
        if not x['stage'] and exit and root!=(exit.get('origin') or {}).get('date'):
            audit_issues['origin_exit_mismatch'].append(dict(code=c,name=r['name'],date=x['date'],origin=root,exit=exit['date'],exit_origin=(exit.get('origin') or {}).get('date'),lifecycle=x['lifecycle']))
        if x['stage']==10 and not p.get('confirmed') and p.get('current_days',0)>T.P['platform_max_days']:
            audit_issues['overdue_catchment'].append(dict(code=c,name=r['name'],date=x['date'],origin=root,days=p['current_days']))
        if i not in path or i-1 not in path:continue
        prev=path[i-1];b=bars[i]
        if prev['stage'] or not prev['exit']:continue
        pct=100*(b['close']/bars[i-1]['close']-1)
        if abs(pct-10)>.25 or abs(b['close']-b['high'])>1e-8:continue
        lines={n:T.average(bars,i,n) for n in (5,10,20)}
        slopes={n:lines[n]-T.average(bars,i-1,n) for n in lines}
        up=all(b['close']>=lines[n] and slopes[n]>0 for n in (5,10))
        below=any(bars[i-1]['close']<T.average(bars,i-1,n) for n in (5,10))
        if not (up and below):continue
        ratio=b['volume']/mean(t['volume'] for t in bars[i-5:i]) if all(T.positive(t.get('volume')) for t in bars[i-5:i+1]) else None
        kind='existing_entry' if x['signal'] else 'recovery_candidate'
        item=dict(code=c,name=r['name'],date=b['date'],group=kind,origin_before=prev['origin'],old_exit=prev['exit']['date'],
            signal_kind=(x['signal'] or {}).get('kind'),day_pct=pct,volume_ratio=ratio,
            close=b['close'],prior20_high=max(t['high'] for t in bars[i-20:i]),
            above_rising_ma20=b['close']>=lines[20] and slopes[20]>0,
            period='recent40' if b['date'] in holdout else 'earlier',recent20=b['date'] in recent,followup={})
        for n in (1,3,5,10):
            if i+n>=len(bars):continue
            window=range(i+1,i+n+1)
            failures=[j for j in window if bars[j]['close']<T.average(bars,j,10)]
            ret=100*(bars[i+n]['close']/b['close']-1)
            item['followup'][str(n)]=dict(end_above_ma5=bars[i+n]['close']>=T.average(bars,i+n,5),
                end_above_ma10=bars[i+n]['close']>=T.average(bars,i+n,10),
                all_closes_hold_ma10=not failures,first_loss_date=bars[failures[0]]['date'] if failures else None,
                close_return_pct=ret,min_close_return_pct=min(100*(bars[j]['close']/b['close']-1) for j in window),
                max_high_return_pct=max(100*(bars[j]['high']/b['close']-1) for j in window))
        item['bars']=[dict(bars[j],ma5=T.average(bars,j,5),ma10=T.average(bars,j,10),ma20=T.average(bars,j,20)) for j in range(max(21,i-3),min(len(bars),i+11))]
        events.append(item)

def summary(items):
    result=dict(events=len(items),stocks=len({x['code'] for x in items}),followup={})
    for n in (1,3,5,10):
        sample=[x['followup'][str(n)] for x in items if str(n) in x['followup']]
        if not sample:continue
        result['followup'][str(n)]=dict(n=len(sample),hold_all_ma10=sum(x['all_closes_hold_ma10'] for x in sample),
            end_above_ma10=sum(x['end_above_ma10'] for x in sample),end_above_ma5=sum(x['end_above_ma5'] for x in sample),
            median_close_return_pct=median(x['close_return_pct'] for x in sample),
            median_min_close_return_pct=median(x['min_close_return_pct'] for x in sample))
    return result

groups={name:summary([x for x in events if x['group']==group and (ma20 is None or x['above_rising_ma20']==ma20)])
    for name,group,ma20 in [('existing','existing_entry',None),('recovery_all','recovery_candidate',None),('recovery_ma20_up','recovery_candidate',True),('recovery_ma20_not_up','recovery_candidate',False)]}
for group in ('existing_entry','recovery_candidate'):
    for period in ('earlier','recent40'):
        groups[group+'_'+period]=summary([x for x in events if x['group']==group and x['period']==period])
report=dict(rule_version=T.VERSION,rule_hash=T.IMPLEMENTATION_HASH,source=s['quote_capture_at'],asof=asof,coverage=dict(total=len(rows),valid=len(paths),excluded=len(invalid),reasons=dict(Counter(x['reason'] for x in invalid))),
    calendar_from=cal[-160] if len(cal)>=160 else cal[0],groups=groups,
    recent20=[{k:v for k,v in x.items() if k!='bars'} for x in events if x['recent20']],
    audit_issues=dict(audit_issues),events=events,excluded=invalid)
(OUT/'study.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:report[k] for k in ('source','asof','coverage','calendar_from','groups')},ensure_ascii=False,indent=2))
print('issues', {k:len(v) for k,v in audit_issues.items()})
