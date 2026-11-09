"""Incremental formal daily acquisition, overlap validation and bounded recovery."""
from datetime import datetime
import json
import time
import math
import sqlite3

import config
import datafeed as df
import strength

VERSION = '正式日线增量3'
PRICE_KEYS = ('open', 'close', 'high', 'low')


def has_activity(quote):
    quote = quote or {}
    return float(quote.get('amount_wan') or 0) > 0 or float(quote.get('volume_shou') or 0) > 0


def valid_source(rows):
    """Authentic no-trade bars may have zero volume; eligibility stays in strength.py."""
    try:
        dates = [datetime.strptime(b['date'], '%Y-%m-%d') for b in rows]
        if not dates or dates != sorted(set(dates)):
            return False
        for b in rows:
            if not (all(math.isfinite(b[k]) and b[k]>0 for k in PRICE_KEYS)
                    and b['low'] <= min(b['open'], b['close']) <= max(b['open'], b['close']) <= b['high']
                    and math.isfinite(b['volume']) and b['volume'] >= 0):
                return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


def requires_full(old, recent):
    """Price revisions/basis changes invalidate the ENTIRE adjustment history."""
    if not old or not recent or not valid_source(recent):
        return True
    # All CURRENT calculations need at most 61 completed bars. An older untagged prefix
    # remains unverified; it must neither be relabelled nor force thousands of full fetches.
    sources = {(b.get('price_basis'), b.get('price_basis_source')) for b in old[-61:] + recent}
    if len(sources) != 1 or None in next(iter(sources)):
        return True
    by_date = {b['date']: b for b in old}
    overlap = [b for b in recent if b['date'] in by_date]
    if not overlap:
        return True
    # Exact source floats, no "within 5%" shortcut. Volume/amount revisions are merged.
    return any(any(b[k] != by_date[b['date']][k] for k in PRICE_KEYS) for b in overlap)


def integrity_due(conn, codes, now=None):
    now=time.time() if now is None else now
    try:
        states={c:(retry,json.loads(payload)) for c,retry,payload in
                conn.execute('SELECT code,next_retry,payload FROM kline_fetch_state')}
        for code in codes:
            retry,meta=states.get(code,(0,{}))
            if not isinstance(meta,dict):
                return True
            if retry>now:
                continue
            checked=max(meta.get('full_checked',0),meta.get('integrity_checked',0))
            if not isinstance(checked,(int,float)) or not math.isfinite(checked) or not 0<=checked<=now:
                return True
            if meta.get('integrity_pending') or checked<now-7*86400:
                return True
    except (ValueError,TypeError,AttributeError):
        return True
    except sqlite3.OperationalError as exc:
        if 'no such table' in str(exc):
            return bool(codes)
        raise
    return False


def update(conn, codes, quotes, required_day=None, force=False, progress=True, budget_seconds=None, allow_periodic=True):
    conn.execute('CREATE TABLE IF NOT EXISTS kline_fetch_state(code TEXT PRIMARY KEY,checked REAL,next_retry REAL,failures INT,payload TEXT)')
    conn.commit()
    now = time.time()
    deadline = time.monotonic()+(budget_seconds if budget_seconds is not None else config.KLINE.get('increment_deadline_seconds', 60))
    clock = datetime.now()
    today = clock.strftime('%Y-%m-%d')
    closed = clock.hour*60+clock.minute >= 15*60+5
    states = {}
    broken_states = []
    for c, checked, retry, failures, payload in conn.execute('SELECT * FROM kline_fetch_state'):
        try:
            meta = json.loads(payload)
            if (not isinstance(meta, dict) or not all(isinstance(v, (int,float)) and math.isfinite(v)
                    for v in (checked,retry,failures)) or retry>now+1800 or failures<0):
                raise ValueError('invalid acquisition state')
            # Validate fields subsequently used in arithmetic independently of JSON syntax.
            full_checked = meta.get('full_checked', 0)
            integrity_checked=meta.get('integrity_checked',0)
            if not all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=now
                       for v in (full_checked,integrity_checked)):
                raise ValueError('invalid repair time')
            states[c] = (checked, retry, int(failures), meta)
        except (ValueError, TypeError):
            # A broken optimization record must not block all stocks or silently bless its bars.
            states[c] = (0, 0, 0, {'integrity_pending':True, 'error':'补采状态损坏，重新核验正式历史'})
            broken_states.append((json.dumps(states[c][3],ensure_ascii=False),c))
    if broken_states:
        conn.executemany('UPDATE kline_fetch_state SET checked=0,next_retry=0,failures=0,payload=? WHERE code=?',broken_states)
    counts = dict(conn.execute('SELECT code,COUNT(*) FROM kline GROUP BY code'))
    latest = dict(conn.execute('SELECT code,MAX(date) FROM kline GROUP BY code'))
    day_counts = list(conn.execute('SELECT date,COUNT(*) FROM kline GROUP BY date ORDER BY date'))
    threshold = max((n for _, n in day_counts), default=0)*.5
    calendar = [d for d,n in day_counts if n >= threshold]
    recent_by_code = {}
    if len(calendar) >= strength.CORE_BARS:
        for row in conn.execute('SELECT code,date,open,close,high,low,volume FROM kline WHERE date>=? ORDER BY date',
                                (calendar[-strength.CORE_BARS],)):
            recent_by_code.setdefault(row[0], []).append(dict(zip(('date','open','close','high','low','volume'), row[1:])))
    need = int(config.KLINE['days'] * .9)
    short, incremental, periodic = [], [], []
    target = required_day or max(latest.values(), default='')
    for code in codes:
        state = states.get(code, (0, 0, 0, {}))
        meta = state[3]
        if not force and now < state[1]:
            continue
        insufficient = counts.get(code, 0) < need
        active = has_activity(quotes.get(code))
        broken_core = bool(active and len(calendar) >= strength.CORE_BARS
                           and counts.get(code, 0) >= strength.CORE_BARS
                           and strength.core_window_issue(recent_by_code.get(code, []), calendar)
                           in ('invalid', 'unaligned', 'short_history'))
        # A verified short listing is not capable of inventing a 160-bar history.
        short_known = bool(meta.get('short_checked_day') and meta.get('full_checked', 0) >= now-7*86400)
        if force or meta.get('integrity_pending') or (insufficient and not short_known) or (broken_core and meta.get('core_checked_day') != target):
            short.append(code)
        elif required_day and latest.get(code, '') < target and not (
                not active and meta.get('no_trade_checked_day') == target):
            incremental.append(code)
        elif allow_periodic and max(meta.get('full_checked',0),meta.get('integrity_checked',0)) < now-7*86400 and clock.hour >= 18:
            periodic.append(code)
    # Prioritize oldest/untried repairs, so failed/new symbols cannot starve one another.
    short.sort(key=lambda c: states.get(c, (0,))[0])
    limit = config.KLINE.get('repair_per_scan', 50)
    selected = short if force else short[:limit]
    pending = len(short) - len(selected)
    periodic.sort(key=lambda c: states.get(c, (0, 0, 0, {}))[3].get('full_checked', 0))
    selected_periodic = periodic[:max(0, limit-len(selected))] if not force else []
    selected += selected_periodic
    pending += len(periodic)-len(selected_periodic)
    requested, changed, failed, upgraded = 0, 0, [], []
    timed_out = False
    full_due = []
    got_all, adjustment_pending = {}, set()
    cooldown_deferred = set()
    fetch_states = {}
    full_days=max(config.KLINE['days'],max((counts.get(c,0)+20 for c in selected_periodic),default=0))
    for batch, days in ((incremental, config.KLINE.get('increment_days', 20)),
                        (selected, full_days)):
        if not batch:
            continue
        requested += len(batch)
        got, truncated = df.fetch_klines_bulk(batch, progress=progress, days=days,
                                             deadline_seconds=max(.01, deadline-time.monotonic()))
        fetch_states.update(getattr(got, 'fetch_states', {}))
        timed_out = timed_out or truncated
        for code in batch:
            if (fetch_states.get(code) or {}).get('kind') == 'source_cooldown':
                cooldown_deferred.add(code)
                continue
            rows = [b for b in (got.get(code) or []) if b['date'] < today or b['date'] == today and closed]
            old = df.load_kline(conn, 'kline', 'code', code)
            if not rows or not valid_source(rows) or (target and rows[-1]['date'] < target
                    and has_activity(quotes.get(code))):
                failed.append(code)
                continue
            if code in incremental and requires_full(old, rows):
                adjustment_pending.add(code)
                full_due.append(code)
                continue
            if code in selected and old and requires_full(old, rows) and not set(b['date'] for b in old).issubset({b['date'] for b in rows}):
                adjustment_pending.add(code)
                full_due.append(code)
                continue
            if code in selected_periodic and not {b['date'] for b in old}.issubset({b['date'] for b in rows}):
                failed.append(code)
                continue  # Incomplete source coverage is not a successful full-history audit.
            got_all[code] = rows
    # Full repair must cover all cached history when the adjustment scale was revised.
    if full_due:
        old_series = {c: df.load_kline(conn, 'kline', 'code', c) for c in full_due}
        days = max(config.KLINE['days'], max(len(v) for v in old_series.values())+20)
        requested += len(full_due)
        got, truncated = df.fetch_klines_bulk(full_due, progress=progress, days=days,
                                             deadline_seconds=max(.01, deadline-time.monotonic()))
        fetch_states.update(getattr(got, 'fetch_states', {}))
        timed_out = timed_out or truncated
        for code in full_due:
            if (fetch_states.get(code) or {}).get('kind') == 'source_cooldown':
                cooldown_deferred.add(code)
                continue
            rows = [b for b in (got.get(code) or []) if b['date'] < today or b['date'] == today and closed]
            old = old_series[code]
            if (not rows or not valid_source(rows)
                    or (requires_full(old, rows) and not {b['date'] for b in old}.issubset({b['date'] for b in rows}))
                    or (target and rows[-1]['date'] < target and has_activity(quotes.get(code)))):
                failed.append(code)
                continue
            got_all[code] = rows
            upgraded.append(code)
    changed = df.save_klines(conn, 'kline', 'code', got_all) if got_all else 0
    for code, rows in got_all.items():
        meta = dict(states.get(code, (0, 0, 0, {}))[3])
        if code in selected or code in upgraded:
            meta['full_checked'] = now
            meta['core_checked_day'] = target
        else:
            meta.setdefault('full_checked', 0)
        if code in selected:
            meta['integrity_checked']=now
        if len(rows) < need and code in selected:
            meta['short_checked_day'] = target
        meta.update(latest=rows[-1]['date'], error=None, integrity_pending=False)
        meta.pop('data_fetch', None)  # A recovered series clears the old isolated-empty observation.
        if not has_activity(quotes.get(code)):
            meta['no_trade_checked_day'] = target
        conn.execute('INSERT OR REPLACE INTO kline_fetch_state VALUES(?,?,?,?,?)',
                     (code, now, 0, 0, json.dumps(meta)))
    for code in set(failed):
        prior = states.get(code, (0, 0, 0, {}))
        failures = prior[2]+1
        meta = dict(prior[3], error='请求失败或正式日线尚未齐全')
        meta['data_fetch'] = dict(fetch_states.get(code) or dict(kind='request_error', provider='tencent_kline',
            checked_at=clock.isoformat(timespec='seconds'), peer_success_count=0, peer_codes=[]))
        if meta['data_fetch']['kind'] == 'ok':meta['data_fetch']['kind'] = 'history_incomplete'
        if code in selected:
            meta['integrity_checked']=now
        if code in adjustment_pending:
            meta['integrity_pending'] = True
        conn.execute('INSERT OR REPLACE INTO kline_fetch_state VALUES(?,?,?,?,?)',
            (code, now, now+min(1800, 30*2**min(failures-1, 6)), failures, json.dumps(meta)))
    conn.commit()
    result = dict(version=VERSION, required_day=target, requested=requested, changed_rows=changed,
                  failed=len(set(failed)), full_repairs=len(upgraded),
                  deferred=pending+len(cooldown_deferred), source_cooldown=len(cooldown_deferred),
                  truncated=timed_out,
                  integrity_pending=len((({c for c in codes if states.get(c,(0,0,0,{}))[3].get('integrity_pending')}
                                          |adjustment_pending)-set(got_all))))
    print('[KLINE] 增量：' + json.dumps(result, ensure_ascii=False))
    return result
