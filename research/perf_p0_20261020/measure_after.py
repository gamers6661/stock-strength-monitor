"""Measure the slimmed generation without activating it."""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config
import ui_payload


def size(value):
    return len(ui_payload.dumps(value).encode('utf-8'))


start = time.perf_counter()
snap = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
print('load', round(time.perf_counter() - start, 3))
template = (ROOT / 'dashboard_template.html').read_text(encoding='utf-8')
with tempfile.TemporaryDirectory(prefix='perf-after-') as directory:
    page = Path(directory) / 'dashboard.html'
    started = time.perf_counter()
    packet, token = ui_payload.prepare(snap, template, page)
    print('prepare', round(time.perf_counter() - started, 3), 'packet MB', round(size(packet) / 1e6, 2))
    brief = ui_payload.unpack(packet)
    for key in ('stocks', 'coverage_catalog', 'board_catalog', 'stock_activity'):
        print(key, round(size(brief.get(key)) / 1e6, 2))
    ma = sum(size(row.get('ma_trend') or {}) for row in brief.get('stocks') or [])
    print('ma_trend MB', round(ma / 1e6, 2))
    db = next(Path(directory).rglob('*.db'))
    print('db MB', round(db.stat().st_size / 1e6, 2))
