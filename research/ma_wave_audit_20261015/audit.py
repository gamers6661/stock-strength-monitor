import gzip,json,sqlite3,sys
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import datafeed,ma_trend as T
OUT=Path(__file__).resolve().parent
with gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf-8') as f:s=json.load(f)
rows=s['stocks']+s.get('coverage_catalog',[]);conn=sqlite3.connect((OUT/'baseline/market.db').resolve().as_uri()+'?mode=ro',uri=True)
issues={k:[] for k in ('recovery_without_new_entry','origin_exit_mismatch','overdue_catchment','active_after_same_wave_exit','recent_confirmation_same_wave')}
samples=[]
for row in rows:
    m=row['ma_trend'];c=row['code'];bars=[b for b in datafeed.load_kline(conn,'kline','code',c,limit=160) if b['date']<s['quote_capture_at'][:10]]
    if len(bars)<22:continue
    setup=T.daily(bars,[b['date'] for b in bars],limit_pct=10 if not row['name'].upper().startswith(('ST','*ST')) else None)
    item=dict(code=c,name=row['name'],stage=m['stage'],status=m['status'],origin=(m.get('origin') or {}).get('date'),
        confirmation=(m.get('last_confirmation') or {}).get('date'),exit=(setup.get('last_exit') or {}).get('date'),
        platform_start=(m.get('platform') or {}).get('start'),platform_days=(m.get('platform') or {}).get('current_days'),
        source=m.get('quote_at'),daily_stage=setup.get('stage'))
    event=setup.get('last_exit') or {};root=setup.get('origin') or {};p=setup.get('platform') or {}
    if not setup.get('stage') and event and root.get('date')!=(event.get('origin') or {}).get('date'):
        issues['origin_exit_mismatch'].append(item)
    if setup.get('stage')==10 and not p.get('confirmed') and p.get('current_days',0)>T.P['platform_max_days']:
        issues['overdue_catchment'].append(item)
    if setup.get('stage') in (5,10) and event and root.get('date')==(event.get('origin') or {}).get('date') and setup.get('entry_date')>event['date']:
        issues['active_after_same_wave_exit'].append(item)
    if item['stage']==10 and item['confirmation'] and item['confirmation']>str(item['origin']):issues['recent_confirmation_same_wave'].append(item)
    recoveries=[]
    for i in range(max(21,len(bars)-8),len(bars)):
        b=bars[i];pct=100*(b['close']/bars[i-1]['close']-1)
        if abs(pct-10)>.25 or abs(b['close']-b['high'])>1e-8:continue
        lines={n:T.average(bars,i,n) for n in (5,10)}
        reclaimed=all(b['close']>=lines[n] and lines[n]>T.average(bars,i-1,n) for n in lines)
        was_below=any(bars[i-1]['close']<T.average(bars,i-1,n) for n in lines)
        before=T.daily(bars[:i],[x['date'] for x in bars[:i]],limit_pct=10)
        if reclaimed and was_below and not before.get('stage') and before.get('last_exit') and not T.origin(bars,i,limit_pct=10):
            recoveries.append(dict(date=b['date'],pct=pct,close=b['close'],prior_high=max(x['high'] for x in bars[i-20:i])))
    if recoveries:issues['recovery_without_new_entry'].append(dict(item,events=recoveries))
    if len(samples)<5 and m.get('eligible') and m.get('stage')==5:samples.append(item)
conn.close()
report=dict(source=s['quote_capture_at'],total=len(rows),counts={k:len(v) for k,v in issues.items()},issues=issues)
(OUT/'audit_before.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(source=report['source'],total=report['total'],counts=report['counts']),ensure_ascii=False))
for k,v in issues.items():print(k, json.dumps(v[:6],ensure_ascii=False))
