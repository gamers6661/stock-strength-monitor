import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config
import board_trend
import make_dashboard
snap = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
summary = board_trend.attach(snap, fetch=False)
make_dashboard.attach_klines(snap)
html = (ROOT/'dashboard_template.html').read_text(encoding='utf-8').replace(
    make_dashboard.PLACEHOLDER, json.dumps(snap, ensure_ascii=False, separators=(',',':')))
config.atomic_write_text(Path(__file__).parent/'preview.html', html)
print(json.dumps(summary, ensure_ascii=False))
