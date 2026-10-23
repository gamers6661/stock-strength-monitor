"""Read-only profiling of the publish path; writes only to a temporary generation."""
import cProfile
import json
import pstats
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT))
import config


def timed(label, fn):
    start = time.perf_counter()
    value = fn()
    print(f'{label}: {time.perf_counter() - start:.3f}s', flush=True)
    return value


snap = timed('load snapshot', lambda: json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8')))
tpl = timed('read template', lambda: (ROOT / 'dashboard_template.html').read_text(encoding='utf-8'))
import price_only
timed('price_only.sanitize', lambda: price_only.sanitize(snap))
import make_dashboard
timed('attach_klines(all)', lambda: make_dashboard.attach_klines(snap))
import board_chart
snap = timed('board_chart.attach', lambda: board_chart.attach(snap, refresh=True))
import board_dynamics
timed('board_dynamics.build', lambda: board_dynamics.build(snap))

import ui_payload
with tempfile.TemporaryDirectory(prefix='perf-publish-') as directory:
    page = Path(directory) / 'dashboard.html'
    profile = cProfile.Profile()
    profile.enable()
    package, generation = ui_payload.prepare(snap, tpl, page)
    profile.disable()
    print('generation', generation, 'packet MB', len(ui_payload.dumps(package)) / 1e6)
    stats = pstats.Stats(profile)
    stats.sort_stats('cumulative').print_stats(45)
