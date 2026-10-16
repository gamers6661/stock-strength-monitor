"""仅补板块本地库并生成独立验收快照，不覆盖正在更新的行情快照。"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import board_trend
import config
OUT = Path(__file__).parent
snap = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
original = copy.deepcopy(snap['stocks'])
start = time.time()
summary = board_trend.attach(snap, fetch=True)
assert snap['stocks'] == original
summary['elapsed_seconds'] = round(time.time()-start, 1)
summary['stocks_unchanged'] = True
summary['stocks_sha256'] = hashlib.sha256(json.dumps(original, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
(OUT/'bootstrap.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT/'snapshot.enriched.json').write_text(json.dumps(snap, ensure_ascii=False), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False), flush=True)
