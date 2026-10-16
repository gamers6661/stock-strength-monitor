import gzip,json,shutil,sqlite3,sys
from pathlib import Path
from datetime import datetime
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,datafeed,strength,ma_trend,close_monitor
OUT=Path(__file__).resolve().parent;BASE=OUT/'baseline';BASE.mkdir(exist_ok=True)
if not (BASE/'snapshot.json.gz').exists():
    snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
    with gzip.open(BASE/'snapshot.json.gz','wt',encoding='utf-8') as f:json.dump(snap,f,ensure_ascii=False)
    for name in ('ma_trend.py','ma_trend_ui.js','radar_ui.js','config.py','csv_export.js','dashboard_template.html','ui_client.js','ui_payload.py','scoring.py','test_ma_trend.py'):
        shutil.copy2(ROOT/name,BASE/name)
    with gzip.open(BASE/'dashboard.html.gz','wb') as f:f.write((ROOT/'dashboard.html').read_bytes())
    src=sqlite3.connect(config.CACHE_DIR/'market.db');dest=sqlite3.connect(BASE/'market.db');src.backup(dest);dest.close();src.close()
    (BASE/'status.json').write_bytes(urlopen('http://127.0.0.1:8848/__status').read())
    with gzip.open(config.CACHE_DIR/'intraday_history/acquisitions'/(snap['quote_capture_at'][:10]+'.jsonl.gz'),'rt',encoding='utf-8') as f:
        record=next(json.loads(line) for line in f if json.loads(line)['captured_at'][:19]==snap['quote_capture_at'][:19])
    with gzip.open(BASE/'acquisition.json.gz','wt',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False)
    (OUT/'frozen_minutes.json').write_text(json.dumps(close_monitor._load_minute_cache(snap['quote_capture_at'][:10]).get('stocks',{}),ensure_ascii=False),encoding='utf-8')
with gzip.open(BASE/'snapshot.json.gz','rt',encoding='utf-8') as f:snap=json.load(f)
rows=snap['stocks']+snap.get('coverage_catalog',[]);con=sqlite3.connect(BASE/'market.db')
hist={r['code']:datafeed.load_kline(con,'kline','code',r['code'],limit=160) for r in rows};con.close()
cal=strength.trading_calendar({c:strength.completed(v) for c,v in hist.items()})
cases=[]
for row in rows:
    if row['name'] not in ('贝瑞基因','澳洋健康'):continue
    bars=[b for b in hist[row['code']] if b['date']<snap['quote_capture_at'][:10]]
    signals=[ma_trend.origin(bars,i) for i in range(21,len(bars))];signals=[s for s in signals if s]
    cases.append(dict(code=row['code'],name=row['name'],history_days=len(bars),first=bars[0]['date'],last=bars[-1]['date'],daily=ma_trend.daily(bars,cal),current=row['ma_trend'],signals=signals[-15:],bars=bars[-40:]))
(OUT/'diagnosis_before.json').write_text(json.dumps(dict(source=snap['quote_capture_at'],cases=cases),ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(source=snap['quote_capture_at'],cases=[{k:c[k] for k in ('code','name','history_days','first','last')}|{'stage':c['current']['stage'],'status':c['current']['status'],'reason':c['current']['reason'],'root':c['current']['origin'],'signals':[s['date'] for s in c['signals']]} for c in cases]),ensure_ascii=False))
