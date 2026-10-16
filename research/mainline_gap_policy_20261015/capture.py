import gzip,json,shutil,sys,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,datafeed as df,intraday_path,strength
OUT=Path(__file__).parent;backup=OUT/'baseline';backup.mkdir(exist_ok=True)
for path in ROOT.iterdir():
    if path.suffix in ('.py','.js','.html','.json') and path.name!='dashboard.html':shutil.copy2(path,backup/path.name)
s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
rows=s['stocks']+s.get('coverage_catalog',[])
q={}
for path in sorted((config.CACHE_DIR/'intraday').rglob('*.jsonl.gz')):
    pass
# Acquisitions are immutable; use the current snapshot's exact batch.
archive=config.CACHE_DIR/'intraday_path'
files=list(config.CACHE_DIR.rglob('*acquisition*'))
print('capture',s.get('quote_capture_at'),'archives',[(str(p),p.is_dir()) for p in files[:12]])
with df.db() as con:
    h={r['code']:df.load_kline(con,'kline','code',r['code'],limit=160) for r in rows}
cal=strength.trading_calendar(h)
for path in config.CACHE_DIR.rglob('acquisitions/*.jsonl.gz'):
    if path.name[:10]!=s['quote_capture_at'][:10]:continue
    with gzip.open(path,'rt',encoding='utf-8') as f:
        for line in f:
            record=json.loads(line)
            if record.get('captured_at')==s['quote_capture_at']:
                q={r[0]:dict(zip(record['fields'][1:],r[1:])) for r in record['rows']}
                break
with gzip.open(OUT/'frozen_base.json.gz','wt',encoding='utf-8',compresslevel=1) as f:json.dump(dict(snapshot=s,quotes=q,histories=h,calendar=cal),f,ensure_ascii=False)
print('saved',len(rows),'short',[(r['code'],r['name'],len(h[r['code']]),r.get('ma_trend',{}).get('reason')) for r in rows if len(h[r['code']])<22])
