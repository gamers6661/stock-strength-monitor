"""Display-only official board OHLC; no network, scoring or cache writes."""
import math
import sqlite3
from contextlib import closing
from datetime import datetime

import config


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def valid(bar):
    try:
        datetime.strptime(bar['date'], '%Y-%m-%d')
        return (all(number(bar.get(k)) and bar[k] > 0 for k in ('open', 'high', 'low', 'close'))
                and bar['low'] <= min(bar['open'], bar['close'])
                <= max(bar['open'], bar['close']) <= bar['high']
                and number(bar.get('volume')) and bar['volume'] >= 0)
    except (KeyError, ValueError, TypeError):
        return False


def timestamp(value):
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def same_value(left, right):
    return number(left) and number(right) and left > 0 and right > 0 and abs(left-right) <= max(.002, left*.00001)


def project(board, bars, captured, calendar=None):
    daily = board.get('index_trend') or {}
    code = str(daily.get('code') or '')
    out = dict(code=code, source=daily.get('source') or '同花顺指数', bars=[], current_price=None)
    if not code or not captured:
        out['reason'] = '该方向暂无对应的同花顺指数日线'
        return out
    day = captured.date().isoformat()
    trading_days = set(calendar or [])
    by_date = {b['date']: dict(b) for b in bars if valid(b) and b['date'] <= day
               and (not trading_days or b['date'] in trading_days)}
    quote = board.get('index_quote') or {}
    at = timestamp(quote.get('quote_at'))
    comparable = (str(quote.get('code') or '') == code and quote.get('name') == board.get('name')
                  and quote.get('price_basis') == '同花顺指数原值'
                  and at is not None and at.date() == captured.date() and at <= captured
                  and number(quote.get('price')) and quote['price'] > 0)
    before = [by_date[d] for d in sorted(by_date) if d < day]
    comparable = comparable and bool(before) and same_value(quote.get('previous_close'), before[-1]['close'])
    today = by_date.get(day)
    if today:
        observed = timestamp(today.get('observed_at'))
        completed = (captured.hour*60+captured.minute >= 15*60+5
                     and observed is not None and observed.date() == captured.date()
                     and observed.hour*60+observed.minute >= 15*60+5
                     and comparable and same_value(today['close'], quote['price']))
        if not completed:
            del by_date[day]
            out['reason'] = '当日日线未完成或与收盘指数报价不一致；显示此前完成日K线'
    selected = [by_date[d] for d in sorted(by_date)][-80:]
    out['bars'] = [{k: b[k] for k in ('date', 'open', 'high', 'low', 'close', 'volume')} for b in selected]
    out['asof'] = selected[-1]['date'] if selected else None
    if comparable and selected and selected[-1]['date'] < day:
        out.update(current_price=quote['price'], current_at=quote['quote_at'])
    if not selected:
        out.setdefault('reason', '暂无可用的同花顺指数OHLC历史')
    return out


def attach(full, path=None):
    """Freeze chart evidence into each detail, preserving all quantitative models."""
    captured = timestamp(full.get('quote_capture_at') or full.get('generated_at'))
    boards = full.get('board_catalog') or []
    codes = {str((b.get('index_trend') or {}).get('code') or '') for b in boards} - {''}
    histories = {c: [] for c in codes}
    if codes and captured:
        try:
            with closing(sqlite3.connect((path or config.KLINE_DB).resolve().as_uri() + '?mode=ro', uri=True)) as con:
                rows = con.execute('''SELECT b.board,b.date,b.open,b.high,b.low,b.close,b.volume,s.observed_at
                    FROM board_kline b JOIN board_bar_source s ON b.board=s.board AND b.date=s.date
                    WHERE b.date<=? ORDER BY b.date''', (captured.date().isoformat(),))
                keys = ('date', 'open', 'high', 'low', 'close', 'volume', 'observed_at')
                for code, *values in rows:
                    if str(code) in histories:
                        histories[str(code)].append(dict(zip(keys, values)))
        except sqlite3.Error:
            pass
    result = dict(full)
    calendar = (full.get('board_trend_model') or {}).get('calendar') or []
    result['board_catalog'] = [dict(b, index_chart=project(b, histories.get(str((b.get('index_trend') or {}).get('code')), []), captured, calendar)) for b in boards]
    return result
