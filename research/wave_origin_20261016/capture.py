import gzip,json,sqlite3,sys,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,scoring,close_monitor,intraday,ma_trend as T
OUT=Path(__file__).parent;BASE=OUT/'baseline';BASE.mkdir(exist_ok=True)
for name in ('config.py','ma_trend.py','board_stock_rank.py','ma_trend_ui.js','stock_rank_ui.js','csv_export.js','test_latest_ma20.py','test_ma_lifecycle_confirmation.py'):
    target=BASE/name
    if not target.exists():shutil.copyfile(ROOT/name,target)
raw=config.SNAPSHOT_JSON.read_bytes();s=json.loads(raw)
with gzip.open(BASE/'snapshot.json.gz','wb',compresslevel=1) as f:f.write(raw)
with gzip.open(intraday.HISTORY_DIR/'acquisitions'/(s['quote_capture_at'][:10]+'.jsonl.gz'),'rt',encoding='utf8') as stream:
    record=next(v for line in stream if (v:=json.loads(line))['captured_at']==s['quote_capture_at'])
quotes={v[0]:dict(zip(record['fields'],v)) for v in record['rows']}
with sqlite3.connect(config.KLINE_DB.resolve().as_uri()+'?mode=ro',uri=True) as con:h=scoring.formal_histories(quotes,con)
day=s['quote_capture_at'][:10];calendar=sorted({b['date'] for bars in h.values() for b in bars if b['date']<day})
minutes=close_monitor._load_minute_cache(day).get('stocks',{})
with gzip.open(OUT/'inputs.json.gz','wt',encoding='utf8',compresslevel=1) as f:
    json.dump(dict(quotes=quotes,histories=h,calendar=calendar,minutes=minutes),f,ensure_ascii=False,separators=(',',':'))
rows=s['stocks']+s.get('coverage_catalog',[]);cases=[r for r in rows if r['name']=='宝鼎科技']
assert len(cases)==1
row=cases[0];code=row['code'];bars=[b for b in h[code] if b['date']<day]
events=[];previous=None;signals=[]
for end in range(22,len(bars)+1):
    setup=T.daily(bars[:end],calendar,10);b=bars[end-1];signal=T.origin(bars,end-1,limit_pct=10)
    if signal:signals.append(signal)
    key=(setup['stage'],(setup.get('origin') or {}).get('date'),(setup.get('last_exit') or {}).get('date'))
    if key!=previous:
        events.append(dict(asof=b['date'],stage=setup['stage'],origin=setup['origin'],entry=setup['entry_date'],last_exit=setup['last_exit'],platform=setup['platform'],last_phase=setup.get('last_phase')))
    previous=key
timeline=[dict(b,ma5=T.average(bars,i,5),ma10=T.average(bars,i,10),ma20=T.average(bars,i,20),signal=next((v for v in signals if v['date']==b['date']),None)) for i,b in enumerate(bars) if b['date']>='2026-06-01']
(OUT/'baoding_before.json').write_text(json.dumps(dict(code=code,name=row['name'],model=row['ma_trend'],events=events,signals=signals,timeline=timeline),ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(dict(source=s['quote_capture_at'],daily=s['strength_model']['asof'],quotes=len(quotes),histories=len(h),code=code,model={k:row['ma_trend'].get(k) for k in ('stage','status','origin','last_exit','last_phase')},events=[dict(date=v['asof'],stage=v['stage'],origin=(v['origin'] or {}).get('date'),exit=(v['last_exit'] or {}).get('date')) for v in events],signals=[dict(date=v['date'],kind=v['kind'],price=v['price'],volume=v['volume_ratio']) for v in signals]),ensure_ascii=False),flush=True)
