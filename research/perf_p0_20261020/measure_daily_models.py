"""Read-only cost of pure completed-day model functions on the live pool."""
import json
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config
import datafeed
import ma_trend
import observed_history
import strength
import trend_consolidation


def timed(label, fn):
    start = time.perf_counter()
    value = fn()
    print(f'{label}: {time.perf_counter() - start:.3f}s', flush=True)
    return value


snapshot = timed('load snapshot', lambda: json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8')))
codes = sorted({r['code'] for group in ('stocks', 'coverage_catalog') for r in snapshot.get(group, [])})
print('codes', len(codes))
with closing(sqlite3.connect(config.KLINE_DB.resolve().as_uri() + '?mode=ro', uri=True)) as con:
    histories = timed('load 160 bars', lambda: {c: datafeed.load_kline(con, 'kline', 'code', c, limit=160) for c in codes})
calendar = timed('calendar', lambda: strength.trading_calendar({c: strength.completed(v) for c, v in histories.items()}))
print('calendar', len(calendar), calendar[-1] if calendar else None)
asof = calendar[-1]


def ma_inputs(code):
    bars = observed_history.traded_bars(histories.get(code) or [])
    return [b for b in bars if b['date'] <= asof]


def run_ma():
    return {c: ma_trend.daily(ma_inputs(c), calendar, limit_pct=10) for c in codes}


ma = timed('ma_trend.daily all (cold)', run_ma)
print('ma pending', sum(bool(v.get('pending')) for v in ma.values()), 'stage', sum(bool(v.get('stage')) for v in ma.values()))
print('daily cache entries', len(ma_trend._DAILY_CACHE))
ma2 = timed('ma_trend.daily all (warm)', run_ma)
print('warm cache entries', len(ma_trend._DAILY_CACHE), 'same objects', ma == ma2)


def run_consolidation():
    out = {}
    for c in codes:
        bars = ma_inputs(c)
        out[c] = trend_consolidation.daily_setup(bars, asof, calendar, ())
    return out


cons = timed('trend_consolidation.daily_setup all', run_consolidation)
print('consolidation eligible', sum(bool(v.get('eligible')) for v in cons.values()))
