"""只发布已通过全池对照的整理留档，原行情/评分快照由服务正常刷新。"""
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config,trend_consolidation as tc
folder=Path(__file__).resolve().parent
review=json.loads((folder/'review.json').read_text(encoding='utf-8'))
assert review['entry_qualification_changes']==review['other_stock_field_changes']==0
model=review['model'];assert model['version']==tc.VERSION and model['day']=='2026-09-30'
assert model['parameters']==json.loads(json.dumps(config.TREND_CONSOLIDATION))
config.atomic_write_text(tc.DIRECTORY/'2026-09-30.json',json.dumps(model,ensure_ascii=False,separators=(',',':')))
sources=('trend_consolidation.py','consolidation_tracking.py','consolidation_rebound.py','config.py','intraday.py','intraday_path.py','dashboard_template.html')
(folder/'published_source_sha256.json').write_text(json.dumps({n:hashlib.sha256((config.ROOT/n).read_bytes()).hexdigest() for n in sources},indent=2),encoding='utf-8')
print('已发布已验收的收盘复核留档，等待服务读取新版模型')
