"""Compare optimized hot paths with the backed-up implementation."""
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def timed(label, fn):
    start = time.perf_counter()
    value = fn()
    print(f'{label}: {time.perf_counter() - start:.3f}s', flush=True)
    return value


snap = timed('load snapshot', lambda: json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8')))
import board_dynamics as current
before = load('board_dynamics_before', ROOT / 'research/perf_p0_20261020/before/board_dynamics.py')
old = timed('board_dynamics before', lambda: before.build(snap))
new = timed('board_dynamics after', lambda: current.build(snap))
old_text = json.dumps(old, ensure_ascii=False, sort_keys=True)
new_text = json.dumps(new, ensure_ascii=False, sort_keys=True)
print('equal', old_text == new_text)
if old_text != new_text:
    for index, (a, b) in enumerate(zip(old_text, new_text)):
        if a != b:
            print('first diff at', index)
            print('before', old_text[max(0, index - 180):index + 220])
            print('after ', new_text[max(0, index - 180):index + 220])
            break
    print('lengths', len(old_text), len(new_text))

import intraday
cases = ["20261020113000", "2026-10-20 11:30:00", "11:30", "9:31", "bad", ""]
import datetime
fallback = datetime.datetime(2026, 10, 20, 12, 0, 0)
for value in cases:
    print('ts', repr(value), intraday.parse_quote_timestamp(value, fallback))

import make_dashboard
limited = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
timed('attach_klines(top 500)', lambda: make_dashboard.attach_klines(limited, 500))
print('stocks with k', sum(1 for row in limited.get('stocks', []) if row.get('k')))

import ui_payload
sample = limited['stocks'][-1]
print('detail chart before k', bool(sample.get('k')), sample.get('code'))
hydrated = ui_payload._detail_chart(dict(sample))
print('detail chart after k', bool(hydrated.get('k')), len(hydrated.get('kd') or []))

import stock_activity
activity = timed('stock_activity.prepare', lambda: stock_activity.prepare(snap))
print('activity items', len(activity.get('items') or {}))
