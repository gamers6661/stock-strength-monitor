"""Freeze inputs and measure real minute provider coverage before changing rules."""
import gzip,json,shutil,sqlite3,sys,time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,close_monitor as C
OUT=Path(__file__).resolve().parent;BASE=OUT/'baseline';BASE.mkdir(exist_ok=True)
for name in ('config.py','ma_trend.py','close_monitor.py','intraday.py','ma_trend_ui.js','stock_rank_ui.js','board_stock_rank.py','csv_export.js'):
    if not (BASE/name).exists():shutil.copy2(ROOT/name,BASE/name)
if not (BASE/'snapshot.json.gz').exists():
    with config.SNAPSHOT_JSON.open('rb') as src,gzip.open(BASE/'snapshot.json.gz','wb',compresslevel=1) as dst:shutil.copyfileobj(src,dst)
with gzip.open(BASE/'snapshot.json.gz','rt',encoding='utf-8') as f:s=json.load(f)
day=s['quote_capture_at'][:10]
if not (BASE/'minutes.json').exists():shutil.copy2(C.MINUTE_DIR/(day+'.json'),BASE/'minutes.json')
if not (BASE/'market.db').exists():
    src=sqlite3.connect(config.KLINE_DB);dst=sqlite3.connect(BASE/'market.db');src.backup(dst);dst.close();src.close()
rows=s['stocks']+s.get('coverage_catalog',[])
print('baseline',s['quote_capture_at'],Counter((r.get('ma_trend') or {}).get('status') for r in rows),flush=True)
codes=['600241','600400','002869','001330','000995','000498']
def probe(code):
    start=time.monotonic()
    try:bars=C._sina_minute_bars(code,day);error=None
    except Exception as e:bars=[];error=str(e)
    return dict(code=code,seconds=round(time.monotonic()-start,3),bars=bars,error=error,
                summary=dict(n=len(bars),first=bars[0]['at'] if bars else None,last=bars[-1]['at'] if bars else None))
with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(probe,codes))
(OUT/'provider_probe.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
for x in results:print({k:v for k,v in x.items() if k!='bars'},flush=True)
