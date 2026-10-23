"""Measure publish stages without touching the live dashboard generation."""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config
import make_dashboard

snap = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
with tempfile.TemporaryDirectory(prefix='measure-publish-') as directory:
    make_dashboard.OUT = Path(directory) / 'dashboard.html'
    for attempt in range(40):
        started = time.monotonic()
        try:
            page = make_dashboard.build(snap)
            break
        except config.PipelineBusy:
            print('busy, retry', attempt + 1, flush=True)
            time.sleep(5)
    else:
        raise SystemExit('pipeline busy')
    print('wall', round(time.monotonic() - started, 3), 'page', page)
    print('publish_performance', json.dumps((snap.get('publish_performance') or {}), ensure_ascii=False, indent=2))
