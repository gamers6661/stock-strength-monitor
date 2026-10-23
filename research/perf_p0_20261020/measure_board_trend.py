"""Measure the completed-day part of board trend observation."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import board_trend
import config


def timed(label, fn):
    start = time.perf_counter()
    value = fn()
    print(f'{label}: {time.perf_counter() - start:.3f}s', flush=True)
    return value


snap = timed('load snapshot', lambda: json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8')))
asof = (snap.get('strength_model') or {}).get('asof')
mapping = board_trend.identities()
boards = [b for b in snap.get('board_catalog') or [] if b['id'] in mapping]
print('boards', len(boards), 'asof', asof)
calendar = timed('calendar_from_db', lambda: board_trend.calendar_from_db(asof, config.KLINE_DB, snap))
print('calendar', len(calendar), calendar[-1] if calendar else None)


def run():
    out = {}
    for board in boards:
        code = mapping[board['id']]
        out[board['id']] = board_trend.observe(code, board['name'], calendar, asof, fetch=False)
    return out


result = timed('observe all (fetch=False)', run)
print('ready', sum(bool(v.get('ready')) for v in result.values()))
