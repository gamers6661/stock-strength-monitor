import gzip,shutil,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import config
OUT=Path(__file__).resolve().parent;BASE=OUT/'baseline';BASE.mkdir(exist_ok=True)
for name in ('config.py','ma_trend.py','ma_trend_ui.js','stock_rank_ui.js','board_stock_rank.py','test_ma_trend.py','test_latest_ma20.py'):
    if not (BASE/name).exists():shutil.copy2(ROOT/name,BASE/name)
if not (BASE/'snapshot.json.gz').exists():
    with config.SNAPSHOT_JSON.open('rb') as src,gzip.open(BASE/'snapshot.json.gz','wb',compresslevel=1) as dst:shutil.copyfileobj(src,dst)
if not (BASE/'market.db').exists():
    src=sqlite3.connect(config.KLINE_DB);dst=sqlite3.connect(BASE/'market.db');src.backup(dst);dst.close();src.close()
print('Baseline saved')
