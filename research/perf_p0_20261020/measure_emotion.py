"""Read-only profile of emotion_relay.attach on the current snapshot."""
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
import emotion_relay
import strength


def timed(label, fn):
    start = time.perf_counter()
    value = fn()
    print(f'{label}: {time.perf_counter() - start:.3f}s', flush=True)
    return value


snap = timed('load snapshot', lambda: json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8')))
print('session', snap.get('session'), 'quote', snap.get('quote_capture_at'))
rows = (snap.get('stocks') or []) + (snap.get('coverage_catalog') or [])
codes = sorted({r['code'] for r in rows})
fields = ('price','open','high','low','last_close','change_pct','limit_pct','limit_up','limit_down',
          'volume_shou','amount_wan','quote_at','ts','price_basis','price_basis_source','last_close_semantics',
          'data_availability','trade_status')
quotes = {r['code']: {k: r.get(k) for k in fields if k in r} for r in rows}
pool = {c: dict(r) for c, r in ((r['code'], r) for r in rows)}
with closing(sqlite3.connect(config.KLINE_DB.resolve().as_uri() + '?mode=ro', uri=True)) as con:
    histories = timed('load histories', lambda: {c: datafeed.load_kline(con, 'kline', 'code', c, limit=160) for c in codes})
calendar = timed('calendar', lambda: strength.trading_calendar({c: strength.completed(v) for c, v in histories.items()}))
print('codes', len(codes), 'calendar', calendar[-1] if calendar else None)
for label in ('cold', 'warm'):
    started = time.perf_counter()
    result = emotion_relay.attach(snap, quotes, pool, histories, calendar, fetch=False, persist=False)
    print(label, 'attach total', round(time.perf_counter() - started, 3))
    print(label, 'profile', json.dumps(result.get('profile'), ensure_ascii=False, indent=2))
    print(label, 'fetch', json.dumps(result.get('fetch'), ensure_ascii=False))
print('counts', result.get('coverage'), 'state', result.get('state'))
