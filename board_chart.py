"""Display-only official board OHLC; completed-bar repair never changes model history."""
import json
import math
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
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
    if selected and selected[-1]['date']<day and day in trading_days and captured.hour*60+captured.minute>=905:
        out.setdefault('reason','最新完成日K待源数据核验；当日指数报价或完整OHLC尚未对齐，暂保留此前完成日线')
    if not selected:
        out.setdefault('reason', '暂无可用的同花顺指数OHLC历史')
    return out


def repair_completed(boards, histories, captured, cache_path=None, fetch=False, fetcher=None):
    """Recheck stale close bars against the official year endpoint, in a small display cache."""
    target=cache_path or config.CACHE_DIR/'board_chart_completed.json'
    try:
        cache=json.loads(target.read_text(encoding='utf8'))
    except (OSError,ValueError):
        cache={}
    day=captured.date().isoformat()
    if cache.get('date')!=day:cache=dict(date=day,items={})
    items=cache.setdefault('items',{})
    if cache.get('version')!='official-close-ohlc-1':
        for entry in items.values():
            if entry.get('error'):entry.pop('checked_at',None)
        cache['version']='official-close-ohlc-1'
    needed=[];meta=dict(attempted=0,repaired=0,failed=0,deferred=0)
    for b in boards:
        code=str((b.get('index_trend') or {}).get('code') or '')
        if not code:continue
        entry=items.get(code) or {};bar=entry.get('bar') or {};q=b.get('index_quote') or {}
        before=sorted((r for r in histories.get(code,[]) if r['date']<day and valid(r)),key=lambda r:r['date'])
        if (entry.get('name')==b['name'] and bar.get('date')==day and valid(bar) and before
                and same_value(entry.get('previous_close'),before[-1]['close'])
                and same_value(bar['close'],q.get('price'))):
            histories[code]=[r for r in histories.get(code,[]) if r['date']!=day]+[dict(bar,observed_at=entry['observed_at'])]
        chart=project(b,histories.get(code,[]),captured)
        quote_at=timestamp(q.get('quote_at'))
        if (fetch and captured.hour*60+captured.minute>=905 and quote_at
                and quote_at.date()==captured.date() and quote_at.hour==15 and quote_at.minute==0
                and q.get('code')==code and q.get('name')==b['name']
                and q.get('price_basis')=='同花顺指数原值' and chart.get('asof')!=day
                and (not entry.get('checked_at') or time.time()-entry['checked_at']>=300)):
            needed.append(b)
    if not needed:return meta
    allow_today=fetcher is None
    if fetcher is None:
        from board_trend import parse_year
        fetcher=lambda code,year:parse_year(code,year,revalidate=True)
    def work(b):
        code=str(b['index_trend']['code'])
        try:
            name,bars=fetcher(code,day[:4]);source='同花顺年度指数日线 '+day[:4]+'.js'
            if name and name!=b['name']:raise ValueError('年度指数名称不一致')
            dates=[r['date'] for r in bars]
            if len(dates)!=len(set(dates)):raise ValueError('年度指数日期重复')
            before=sorted((r for r in bars if r['date']<day and valid(r)),key=lambda r:r['date'])
            bar=next((r for r in bars if r['date']==day and valid(r)),None)
            q=b['index_quote']
            if allow_today and (not bar or not same_value(bar['close'],q.get('price'))):
                # Annual responses can still contain a valid-looking midday bar.
                # Read the official complete OHLC endpoint, never sampled extrema.
                name,bar=fetch_today(code,day)
                if name!=b['name']:raise ValueError('当日指数名称不一致')
                source='同花顺指数当日完整OHLC today.js'
            if not bar or not before or not same_value(before[-1]['close'],q.get('previous_close')) or not same_value(bar['close'],q.get('price')):
                raise ValueError('年度完整日K尚未与指数昨收和收盘报价对齐')
            return b,dict(name=b['name'],bar=bar,previous_close=before[-1]['close'],
                source=source,observed_at=datetime.now().isoformat(timespec='seconds'),checked_at=time.time()),None
        except Exception as exc:
            return b,dict(checked_at=time.time(),error=str(exc)),str(exc)
    pool=ThreadPoolExecutor(max_workers=4);futures=[pool.submit(work,b) for b in needed];finished=0;timed_out=False
    try:
        for future in as_completed(futures,timeout=35):
            b,entry,error=future.result();code=str(b['index_trend']['code']);finished+=1;meta['attempted']+=1
            items[code]=entry
            if error:meta['failed']+=1
            else:
                meta['repaired']+=1
                histories[code]=[r for r in histories.get(code,[]) if r['date']!=day]+[dict(entry['bar'],observed_at=entry['observed_at'])]
    except FuturesTimeoutError:timed_out=True
    finally:
        for future in futures:future.cancel()
        pool.shutdown(wait=not timed_out)
    meta['deferred']=len(needed)-finished
    config.atomic_write_text(target,json.dumps(cache,ensure_ascii=False,separators=(',',':')))
    return meta


def fetch_today(code, day):
    import datafeed
    raw=datafeed.http_get('http://d.10jqka.com.cn/v6/line/bk_'+str(code)+'/01/today.js',
        headers={'Referer':'http://q.10jqka.com.cn/','Cache-Control':'no-cache'},encoding='gbk',timeout=8,retry=0)
    match=re.search(r'\((.*)\)\s*;?\s*$',raw.strip(),re.S)
    obj=json.loads(match.group(1)) if match else {}
    row=obj.get('bk_'+str(code)) or {}
    date=datetime.strptime(str(row.get('1')),'%Y%m%d').date().isoformat()
    if date!=day:raise ValueError('当日指数OHLC日期未对齐')
    bar=dict(date=date,open=float(row['7']),high=float(row['8']),low=float(row['9']),
             close=float(row['11']),volume=float(row['13']),amount=float(row.get('19') or 0))
    if not valid(bar):raise ValueError('当日指数完整OHLC校验未通过')
    return row.get('name'),bar


def attach(full, path=None, refresh=False, cache_path=None):
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
    repair=repair_completed(boards,histories,captured,cache_path,fetch=refresh and full.get('session')=='已收盘') if captured else {}
    result = dict(full)
    calendar = (full.get('board_trend_model') or {}).get('calendar') or []
    result['board_catalog'] = [dict(b, index_chart=project(b, histories.get(str((b.get('index_trend') or {}).get('code')), []), captured, calendar)) for b in boards]
    result['board_chart_refresh']=repair
    return result
