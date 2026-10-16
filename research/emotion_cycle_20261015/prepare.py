import gzip,json,shutil,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import config
OUT=Path(__file__).resolve().parent;BASE=OUT/'baseline';BASE.mkdir(exist_ok=True)
names=('config.py','emotion_relay.py','relay_data.py','emotion_ui.js','csv_export.js','ui_payload.py','serve.py','make_dashboard.py','scoring.py','stock_rank_ui.js','dashboard_template.html','ma_trend.py','ma_trend_ui.js','board_stock_rank.py')
for name in names:
 if not (BASE/name).exists():shutil.copy2(ROOT/name,BASE/name)
if not (BASE/'snapshot.json.gz').exists():
 with config.SNAPSHOT_JSON.open('rb') as src,gzip.open(BASE/'snapshot.json.gz','wb',compresslevel=1) as dst:shutil.copyfileobj(src,dst)
if not (BASE/'market.db').exists():
 src=sqlite3.connect(config.KLINE_DB);dst=sqlite3.connect(BASE/'market.db');src.backup(dst);dst.close();src.close()
with gzip.open(BASE/'snapshot.json.gz','rt',encoding='utf-8') as f:s=json.load(f)
rows=s['stocks']+s.get('coverage_catalog',[]);pool={r['code']:r for r in rows};(OUT/'universe.json').write_text(json.dumps({c:{k:r.get(k) for k in ('name','board_type','list_days','is_new','trade_status')} for c,r in pool.items()},ensure_ascii=False),encoding='utf-8')
with gzip.open(config.CACHE_DIR/'intraday_history/acquisitions'/(s['quote_capture_at'][:10]+'.jsonl.gz'),'rt',encoding='utf-8') as f:
 rec=next(r for line in f if (r:=json.loads(line))['captured_at'][:19]==s['quote_capture_at'][:19])
with gzip.open(BASE/'acquisition.json.gz','wt',encoding='utf-8') as f:json.dump(rec,f,ensure_ascii=False)
conn=sqlite3.connect(BASE/'market.db');cal=[v[0] for v in conn.execute('SELECT date FROM kline WHERE date<=? GROUP BY date HAVING COUNT(DISTINCT code)>=1000 ORDER BY date',(s['strength_model']['asof'],))]
(OUT/'calendar.json').write_text(json.dumps(cal),encoding='utf-8')
print('frozen',s['quote_capture_at'],'pool',len(pool),'days20',cal[-20:],flush=True)
print('basis',conn.execute('SELECT price_basis,price_basis_source,COUNT(*) FROM kline WHERE date>=? GROUP BY price_basis,price_basis_source',(cal[-21],)).fetchall(),flush=True)
for c in ('600825','002343','601811','605577'):
 print(c,{k:pool.get(c,{}).get(k) for k in ('name','trade_status','price','volume_shou','quote_at')},conn.execute('SELECT date,close,volume FROM kline WHERE code=? ORDER BY date DESC LIMIT 4',(c,)).fetchall(),flush=True)
conn.close()
