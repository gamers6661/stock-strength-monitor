import gzip,json,shutil,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import config
OUT=Path(__file__).resolve().parent;BASE=OUT/'baseline';BASE.mkdir(exist_ok=True)
for name in ('config.py','scoring.py','serve.py','make_dashboard.py','ui_payload.py','ui_client.js','dashboard_template.html','radar_ui.js','stock_rank_ui.js','ma_trend_ui.js','ma_trend.py','board_stock_rank.py','csv_export.js'):
    if not (BASE/name).exists():shutil.copy2(ROOT/name,BASE/name)
if not (BASE/'snapshot.json.gz').exists():
    with config.SNAPSHOT_JSON.open('rb') as src,gzip.open(BASE/'snapshot.json.gz','wb',compresslevel=1) as dst:shutil.copyfileobj(src,dst)
if not (BASE/'market.db').exists():
    src=sqlite3.connect(config.KLINE_DB);dst=sqlite3.connect(BASE/'market.db');src.backup(dst);dst.close();src.close()
with gzip.open(BASE/'snapshot.json.gz','rt',encoding='utf-8') as f:s=json.load(f)
if not (BASE/'acquisition.json.gz').exists():
    with gzip.open(config.CACHE_DIR/'intraday_history/acquisitions'/(s['quote_capture_at'][:10]+'.jsonl.gz'),'rt',encoding='utf-8') as f:
        record=next(r for line in f if (r:=json.loads(line))['captured_at'][:19]==s['quote_capture_at'][:19])
    with gzip.open(BASE/'acquisition.json.gz','wt',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False)
print('Baseline',s['quote_capture_at'],'MA',s['ma_trend']['implementation_hash'],flush=True)
