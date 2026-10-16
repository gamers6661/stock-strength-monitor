import copy,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,scoring,ma_trend as T,observed_history
OUT=Path(__file__).parent
s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf8'))
row=next(r for r in s['stocks']+s.get('coverage_catalog',[]) if r['name']=='至纯科技');c=row['code']
with sqlite3.connect(config.KLINE_DB.resolve().as_uri()+'?mode=ro',uri=True) as con:
    bars=observed_history.traded_bars(scoring.formal_histories([c],con)[c])
bars=[b for b in bars if b['date']<=s['strength_model']['asof']];calendar=[b['date'] for b in bars]
features={'ma':{n:[T.average(bars,i,n) for i in range(len(bars))] for n in T.LABELS},'atr':[T.atr(bars,i) for i in range(len(bars))],'limit_pct':10}
events=[];timeline=[];prior=None
for i in range(21,len(bars)):
    v=T.daily(bars[:i+1],calendar,10);b=bars[i];signal=T.origin(bars,i,features)
    key=(v['stage'],(v.get('origin') or {}).get('date'),(v.get('last_exit') or {}).get('date'),(v.get('restart_event') or {}).get('date'),v.get('progressing'))
    if key!=prior:
        events.append(dict(date=b['date'],stage=v['stage'],origin=(v.get('origin') or {}).get('date'),entry=v.get('entry_date'),
            exit=v.get('last_exit'),restart=v.get('restart_event'),progressing=v.get('progressing'),platform=v.get('platform')))
    if '2026-06-01'<=b['date']<='2026-09-04':
        unit=features['atr'][i-1];ratio=b['volume']/(sum(x['volume'] for x in bars[i-5:i])/5)
        timeline.append(dict(date=b['date'],open=b['open'],close=b['close'],high=b['high'],low=b['low'],volume=b['volume'],
            day_pct=100*(b['close']/bars[i-1]['close']-1),two_pct=100*(b['close']/bars[i-2]['close']-1),
            volume_ratio=ratio,position=(b['close']-b['low'])/(b['high']-b['low']) if b['high']>b['low'] else None,
            ma5=features['ma'][5][i],ma10=features['ma'][10][i],ma20=features['ma'][20][i],
            previous_ma5=features['ma'][5][i-1],previous_ma10=features['ma'][10][i-1],atr=unit,
            one_atr=(b['close']-bars[i-1]['close'])/unit,two_atr=(b['close']-bars[i-2]['close'])/unit,
            prior_high=max(x['high'] for x in bars[i-20:i]),signal=signal,
            stage=v['stage'],origin=(v.get('origin') or {}).get('date'),entry=v.get('entry_date'),
            candidate=v.get('recovery_candidate'),restart_observation=v.get('restart_observation'),restart=v.get('restart_event')))
    prior=key
result=dict(code=c,name=row['name'],source=s['quote_capture_at'],completed=s['strength_model']['asof'],version=T.VERSION,
    hash=T.IMPLEMENTATION_HASH,history_from=bars[0]['date'],history_days=len(bars),current=row['ma_trend'],events=events,timeline=timeline)
(OUT/'diagnosis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(dict(code=c,source=result['source'],history_from=bars[0]['date'],history_days=len(bars),
    current={k:row['ma_trend'].get(k) for k in ('stage','status','origin','entry_date','last_phase','last_exit')},
    events=[{k:e.get(k) for k in ('date','stage','origin','entry','progressing')}|{'exit_date':(e.get('exit') or {}).get('date'),'exit_reason':(e.get('exit') or {}).get('reason'),'restart_date':(e.get('restart') or {}).get('date')} for e in events],
    august=[{k:v for k,v in b.items() if k not in ('candidate','restart','restart_observation','signal')}|{'signal':(b.get('signal') or {}).get('kind')} for b in timeline if '2026-07-28'<=b['date']<='2026-08-31']),ensure_ascii=False),flush=True)
