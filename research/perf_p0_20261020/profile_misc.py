"""Read-only profiling of the non-UI publish stages."""
import cProfile
import json
import pstats
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config


def timed(label, fn):
    start = time.perf_counter()
    value = fn()
    print(f'{label}: {time.perf_counter() - start:.3f}s', flush=True)
    return value


snap = timed('load snapshot', lambda: json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8')))
import report
timed('report.build', lambda: report.build(snap))
import board_dynamics
profile = cProfile.Profile()
profile.enable()
dynamics = board_dynamics.build(snap)
profile.disable()
print('board_dynamics bytes', len(json.dumps(dynamics, ensure_ascii=False)) / 1e6)
pstats.Stats(profile).sort_stats('cumulative').print_stats(20)

import stock_activity
profile = cProfile.Profile()
profile.enable()
activity = stock_activity.prepare(snap)
profile.disable()
print('stock_activity bytes', len(json.dumps(activity, ensure_ascii=False)) / 1e6)
pstats.Stats(profile).sort_stats('cumulative').print_stats(30)

import make_dashboard
limited = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
timed('attach_klines(top 500)', lambda: make_dashboard.attach_klines(limited, 500))
all_rows = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
timed('attach_klines(all)', lambda: make_dashboard.attach_klines(all_rows))
