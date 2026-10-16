import gzip,json,shutil,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config
OUT=Path(__file__).resolve().parent;BASE=OUT/'baseline';BASE.mkdir(exist_ok=True)
for name in ('ma_trend.py','ma_trend_ui.js','radar_ui.js','stock_rank_ui.js','dashboard_template.html','config.py','test_ma_trend.py','test_ma_radar_transition.py'):
    target=BASE/name
    if not target.exists():shutil.copy2(ROOT/name,target)
target=BASE/'snapshot.json.gz'
if not target.exists():
    with config.SNAPSHOT_JSON.open('rb') as src,gzip.open(target,'wb',compresslevel=1) as dst:shutil.copyfileobj(src,dst)
target=BASE/'market.db'
if not target.exists():
    src=sqlite3.connect(config.KLINE_DB);dst=sqlite3.connect(target);src.backup(dst);dst.close();src.close()
print('Baseline saved')
