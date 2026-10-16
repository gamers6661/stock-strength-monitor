# -*- coding: utf-8 -*-
"""收盘强势名单与次日均线监控。评分资格仍由现有日线模型决定。"""
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import config
import intraday
import stock_strength
import datafeed as df


VERSION = "收盘进攻名单与趋势监控2"
CLOSE_DIR = config.CACHE_DIR / "close_strong_attack_v6"
MINUTE_DIR = config.CACHE_DIR / "trend_monitor_minutes"
LIVE_DIR = config.CACHE_DIR / "intraday_new_strength"
TREND_DIR = config.CACHE_DIR / "trend_ma5_observation"
TREND_DIRS = {5: TREND_DIR, 10: config.CACHE_DIR / "trend_ma10_observation",
              20: config.CACHE_DIR / "trend_ma20_observation"}
TREND_VERSION = "均线趋势统一价格口径8"
TREND_NEAR_PCT = 1.0
LINES = (5, 10, 20)
_MINUTE_SOURCE_PREF = "sina"


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _positive(value):
    return _number(value) and value > 0


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _close_path(day):
    return CLOSE_DIR / (day + ".json")


def _latest_close(before_day=None):
    try:
        paths = sorted(CLOSE_DIR.glob("????-??-??.json"), reverse=True)
    except OSError:
        return None
    for path in paths:
        if before_day and path.stem >= before_day:
            continue
        record = _read_json(path)
        if (isinstance(record, dict) and record.get("asof") == path.stem
                and record.get("version") == VERSION and isinstance(record.get("stocks"), list)):
            return record
    return None


def build_close_board(snap):
    """主榜沿用 persistent_strong 硬资格，并用现有日线基础分排序。"""
    model = snap.get("strength_model") or {}
    asof = model.get("asof")
    board_index = {(b.get("type"), b.get("name")): b for b in snap.get("board_catalog", [])}

    def peer_change(board, code):
        # 环境数据只用同一完成日、同花顺成员中的其他有效股票。
        if not board or board.get("asof") != asof:
            return None, 0
        values = [m.get("change_pct") for m in board.get("members") or []
                  if m.get("code") != code and _number(m.get("change_pct"))]
        if len(values) < 3:
            return None, len(values)
        return round(sum(values) / len(values), 2), len(values)

    def display_row(s):
        code = s.get("code")
        industry = s.get("primary_industry")
        industry_change, industry_peers = peer_change(board_index.get(("industry", industry)), code)
        concepts = []
        seen = set()
        for name in s.get("display_boards") or s.get("boards") or []:
            if not isinstance(name, str) or name in seen:
                continue
            seen.add(name)
            change, peers = peer_change(board_index.get(("theme", name)), code)
            if change is not None and change > 0:
                concepts.append({"name": name, "peer_change_pct": change, "peer_count": peers})
        concepts.sort(key=lambda item: (-item["peer_change_pct"], item["name"]))
        close, previous = s.get("signal_close"), s.get("last_close")
        today_change = (round((close / previous - 1) * 100, 2)
                        if s.get("signal_date") == asof and _positive(close) and _positive(previous)
                        else None)
        return {
            "code": code, "name": s.get("name"),
            "score": s.get("stock_strength_score"),
            "percentile": s.get("stock_strength_percentile"),
            "motion": s.get("stock_strength_motion"),
            "trend_stage": s.get("trend_stage"),
            "ret5": s.get("ret5"), "ret20": s.get("ret20"),
            "ma5": s.get("ma5"), "ma10": s.get("ma10"), "ma20": s.get("ma20"),
            "close": close, "today_change_pct": today_change,
            "industry": industry, "industry_peer_change_pct": industry_change,
            "industry_peer_count": industry_peers,
            "themes": (s.get("display_boards") or s.get("boards") or [])[:2],
            "rising_concepts": concepts[:3],
            "risk_notes": s.get("risk_notes") or [],
            "evidence": s.get("stock_strength_evidence") or {},
        }

    rows = sorted((s for s in snap.get("stocks", []) if s.get("persistent_strong") is True),
                  key=lambda s: (-(s.get("stock_strength_score") or 0), str(s.get("code") or "")))
    return {
        "version": VERSION, "asof": asof, "observed_at": snap.get("generated_at"),
        "factor_model_version": snap.get("factor_model_version"),
        "strength_version": model.get("strength_version"),
        "criterion": stock_strength.PERSISTENT_CRITERION,
        "count": len(rows),
        "stocks": [display_row(s) for s in rows],
    }


def _save_close_board(snap, scan_day):
    board = build_close_board(snap)
    # 只把报价日自己的正式完成日线落为收盘主榜。同日后续修正用最新快照覆盖。
    if snap.get("session") == "已收盘" and board.get("asof") == scan_day:
        CLOSE_DIR.mkdir(parents=True, exist_ok=True)
        config.atomic_write_text(_close_path(scan_day), json.dumps(board, ensure_ascii=False, separators=(",", ":")))
        return board
    existing = _read_json(_close_path(str(board.get("asof") or "")))
    if isinstance(existing, dict) and existing.get("version") == VERSION:
        return existing
    return _latest_close()


def _trading_minutes(start, end):
    """午休不计入15分钟观察窗。"""
    if not start or not end or end <= start or start.date() != end.date():
        return 0
    cursor = start.replace(second=0, microsecond=0)
    end = end.replace(second=0, microsecond=0)
    count = 0
    while cursor < end:
        cursor += timedelta(minutes=1)
        minute = cursor.hour * 60 + cursor.minute
        if (9 * 60 + 30 <= minute <= 11 * 60 + 30
                or 13 * 60 < minute <= 15 * 60):
            count += 1
    return count


def _eastmoney_minute_bars(code, day):
    """东财1分钟 OHLC；只取指定交易日，不混入其余四日或盘后点。"""
    secid = ("1." if str(code).startswith("6") else "0.") + str(code)
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "ndays": "5", "iscr": "0", "secid": secid,
    }
    url = "https://push2his.eastmoney.com/api/qt/stock/trends2/get?" + urlencode(params)
    raw = df.http_get(url, headers={"Referer": "https://quote.eastmoney.com/"},
                      timeout=7, retry=0)
    data = json.loads(raw).get("data") or {}
    out = []
    for item in data.get("trends") or []:
        fields = item.split(",")
        if len(fields) < 5 or not fields[0].startswith(day + " "):
            continue
        try:
            at = datetime.strptime(fields[0], "%Y-%m-%d %H:%M")
            opening, close, high, low = (float(fields[i]) for i in (1, 2, 3, 4))
        except (ValueError, IndexError):
            continue
        minute = at.hour * 60 + at.minute
        if not ((9 * 60 + 30 <= minute <= 11 * 60 + 30)
                or (13 * 60 <= minute <= 15 * 60)):
            continue
        if not (_positive(close) and _positive(high) and _positive(low)
                and high >= low and low - .011 <= close <= high + .011):
            continue
        out.append({"at": fields[0], "open": opening, "close": close,
                    "high": high, "low": low, "source": "东方财富1分钟OHLC",
                    "price_basis": "unknown",
                    "price_basis_source": "eastmoney_trends2_unverified"})
    out.sort(key=lambda b: b["at"])
    return out


def _sina_minute_bars(code, day):
    """备用分钟OHLC，与主源一样只保留指定日期的连续交易时段。"""
    symbol = ("sh" if str(code).startswith("6") else "sz") + str(code)
    params = {"symbol": symbol, "scale": "1", "ma": "no", "datalen": "500"}
    url = "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData?" + urlencode(params)
    raw = df.http_get(url, timeout=7, retry=0)
    start, end = raw.find("(["), raw.rfind(");")
    if start < 0 or end < start:
        raise ValueError("新浪分钟响应格式未知")
    out = []
    for item in json.loads(raw[start + 1:end]):
        at = str(item.get("day") or "")
        if not at.startswith(day + " "):
            continue
        try:
            stamp = datetime.strptime(at, "%Y-%m-%d %H:%M:%S")
            opening, high, low, close = (float(item[k]) for k in ("open", "high", "low", "close"))
        except (ValueError, KeyError):
            continue
        minute = stamp.hour * 60 + stamp.minute
        if not ((9 * 60 + 30 <= minute <= 11 * 60 + 30)
                or (13 * 60 <= minute <= 15 * 60)):
            continue
        if not (all(_positive(v) for v in (opening, high, low, close))
                and high >= low and low - .011 <= min(opening, close)
                and max(opening, close) <= high + .011):
            continue
        out.append({"at": at[:16], "open": opening, "close": close,
                    "high": high, "low": low, "source": "新浪1分钟OHLC",
                    "price_basis": "raw", "price_basis_source": "sina_1m_unadjusted"})
    out.sort(key=lambda b: b["at"])
    return out


def _minute_bars(code, day):
    global _MINUTE_SOURCE_PREF
    sources = (("sina", _sina_minute_bars), ("eastmoney", _eastmoney_minute_bars))
    if _MINUTE_SOURCE_PREF == "eastmoney":
        sources = tuple(reversed(sources))
    for name, loader in sources:
        try:
            bars = loader(code, day)
        except (OSError, ValueError, RuntimeError):
            continue
        if bars and all(bar.get("price_basis") == "raw"
                        and bar.get("price_basis_source") in intraday._RAW_MINUTE_SOURCES
                        for bar in bars):
            _MINUTE_SOURCE_PREF = name
            return _certify_no_trade_gaps(code,day,bars)
    return []


def _certified_gap(previous, current):
    """Prove each omitted minute had zero turnover; no synthetic OHLC is made."""
    start=intraday.parse_quote_timestamp(previous.get('at'));end=intraday.parse_quote_timestamp(current.get('at'))
    if not start or not end or start.date()!=end.date():return False
    needed=[];cursor=start
    while cursor<end-timedelta(minutes=1):
        cursor+=timedelta(minutes=1)
        if _trading_minutes(cursor-timedelta(minutes=1),cursor):needed.append(str(cursor)[:16])
    if not needed:return True
    proofs={p.get('at'):p for p in current.get('no_trade_before') or []}
    last_at=previous['at'];last_volume=None;last_amount=None
    for at in needed:
        p=proofs.get(at) or {}
        if (p.get('source')!='tencent_minute_cumulative' or p.get('prior_at')!=last_at
                or not all(_number(p.get(k)) and math.isfinite(p[k]) and p[k]>=0 for k in ('volume_before','volume_after','amount_before','amount_after'))
                or p['volume_before']!=p['volume_after'] or p['amount_before']!=p['amount_after']
                or not _positive(p.get('price')) or abs(p['price']-previous['close'])>.011
                or last_volume is not None and (p['volume_before']!=last_volume or p['amount_before']!=last_amount)):
            return False
        last_at=at;last_volume=p['volume_after'];last_amount=p['amount_after']
    return True


def _certify_no_trade_gaps(code,day,bars):
    gaps=[(a,b) for a,b in zip(bars,bars[1:]) if _trading_minutes(datetime.fromisoformat(a['at']),datetime.fromisoformat(b['at']))>1]
    if not gaps:return bars
    symbol=('sh' if str(code).startswith('6') else 'sz')+str(code)
    try:
        value=json.loads(df.http_get('https://web.ifzq.gtimg.cn/appstock/app/minute/query?code='+symbol,timeout=7,retry=0))
        node=(value.get('data') or {}).get(symbol) or {};data=node.get('data') or {};qt=(node.get('qt') or {}).get(symbol) or []
        clock=intraday.parse_quote_timestamp(qt[30]) if len(qt)>30 and qt[2]==str(code) else None
        if value.get('code')!=0 or data.get('date')!=day.replace('-','') or not clock or clock.date().isoformat()!=day:return bars
        points={}
        for raw in data.get('data') or []:
            fields=raw.split()
            if len(fields)<4 or len(fields[0])!=4:continue
            at=day+' '+fields[0][:2]+':'+fields[0][2:]
            parsed=intraday.parse_quote_timestamp(at)
            if not parsed or parsed>clock:continue
            price,volume,amount=map(float,fields[1:4])
            if all(math.isfinite(v) for v in (price,volume,amount)) and price>0 and volume>=0 and amount>=0:points[at]=(price,volume,amount)
        out=[dict(b) for b in bars];by_at={b['at']:b for b in out}
        for previous,current in gaps:
            proofs=[];cursor=datetime.fromisoformat(previous['at'])
            while cursor<datetime.fromisoformat(current['at'])-timedelta(minutes=1):
                prior_at=str(cursor)[:16];cursor+=timedelta(minutes=1);at=str(cursor)[:16]
                if not _trading_minutes(cursor-timedelta(minutes=1),cursor):continue
                a=points.get(prior_at);b=points.get(at)
                if not a or not b or a!=b:break
                proofs.append(dict(at=at,prior_at=prior_at,source='tencent_minute_cumulative',price=b[0],
                    volume_before=a[1],volume_after=b[1],amount_before=a[2],amount_after=b[2]))
            candidate=dict(current,no_trade_before=proofs)
            if _certified_gap(previous,candidate):by_at[current['at']]['no_trade_before']=proofs
        return out
    except (OSError,ValueError,RuntimeError,KeyError,TypeError):return bars


def _load_minute_cache(day):
    record = _read_json(MINUTE_DIR / (day + ".json")) or {}
    return record if record.get("day") == day else {"day": day, "stocks": {}}


def _merge_minutes(old, fresh, day):
    """Retain real observations across empty/partial responses; never fill prices."""
    def valid(b):
        return (str(b.get('at') or '')[:10] == day
                and intraday.parse_quote_timestamp(b.get('at')) is not None
                and b.get('price_basis') == 'raw'
                and b.get('price_basis_source') in intraday._RAW_MINUTE_SOURCES
                and intraday._valid_historical_price_bar(b))
    old=[b for b in old or [] if valid(b)];fresh=[b for b in fresh or [] if valid(b)]
    if not fresh:return old
    mode=(fresh[0]['price_basis'],fresh[0]['price_basis_source'])
    points={b['at']:b for b in old if (b['price_basis'],b['price_basis_source'])==mode}
    for b in fresh:
        if (b['price_basis'],b['price_basis_source'])!=mode:continue
        b=dict(b)
        if 'no_trade_before' not in b and points.get(b['at'],{}).get('no_trade_before'):
            b['no_trade_before']=points[b['at']]['no_trade_before']
        points[b['at']]=b
    return [points[t] for t in sorted(points)]


def _minute_coverage(bars, day, target):
    """A cached tail alone cannot prove that the session was backfilled."""
    end=intraday.parse_quote_timestamp(target)
    points=[b for b in _merge_minutes([],bars,day) if b['at']<=str(target)[:16]]
    if not end or not points:return False
    times=[intraday.parse_quote_timestamp(b['at']) for b in points]
    allowance=1 if points[0].get('source')=='新浪1分钟OHLC' else 0
    start=datetime.fromisoformat(day+' 09:30')
    return (_trading_minutes(start,times[0])<=allowance
            and _trading_minutes(times[-1],end)<=2
            and all(_trading_minutes(a,b)<=1 or _certified_gap(previous,current)
                    for a,b,previous,current in zip(times,times[1:],points,points[1:])))


def _get_minutes(codes, day, quote_times, request_stats=None):
    started=time.monotonic()
    cache = _load_minute_cache(day)
    by_code = cache.get("stocks") or {}
    fetched=cache.get('fetched_at') or {};need=[]
    for code in dict.fromkeys(codes):
        bars = by_code.get(code) or []
        last = bars[-1]["at"] if bars else ""
        target = quote_times.get(code) or ""
        if (not last or not target or last < target[:16]
                or last == target[:16] and fetched.get(code,'') < target
                or not _minute_coverage(bars,day,target)
                or any(bar.get("price_basis") != "raw"
                       or bar.get("price_basis_source") not in intraday._RAW_MINUTE_SOURCES
                       for bar in bars)):
            need.append(code)
    stats=dict(requested=len(need),completed=0,empty=0,errors=0,timeout=0,cache_reused=len(set(codes))-len(need))
    if not need:
        if request_stats is not None:request_stats.update(stats,seconds=round(time.monotonic()-started,3))
        return by_code
    # Every required stock is queued in this scan. A bounded pool replaces the
    # 24-stock rotation which left tails stale for several complete scan cycles.
    if need:
        pool = ThreadPoolExecutor(max_workers=config.MA_TREND['minute_fetch_workers'])
        futures = {pool.submit(_minute_bars, code, day): code for code in need}
        try:
            for future in as_completed(futures, timeout=config.MA_TREND['minute_fetch_seconds']):
                code = futures[future]
                try:
                    fresh=future.result();by_code[code]=_merge_minutes(by_code.get(code),fresh,day)
                    stats['completed']+=1
                    if fresh:fetched[code]=str(datetime.now())
                    else:stats['empty']+=1
                except (OSError, ValueError, RuntimeError):
                    stats['errors']+=1
        except TimeoutError:
            stats['timeout']=len(need)-stats['completed']-stats['errors']
        finally:
            for future in futures:
                if not future.done():
                    future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
    MINUTE_DIR.mkdir(parents=True, exist_ok=True)
    config.atomic_write_text(MINUTE_DIR / (day + ".json"),
                             json.dumps({"day": day, "stocks": by_code,"fetched_at":fetched}, ensure_ascii=False, separators=(",", ":")))
    if request_stats is not None:request_stats.update(stats,seconds=round(time.monotonic()-started,3))
    return by_code


def _line_status(bars, threshold, opened_below, quote_at):
    active = datetime.fromisoformat(quote_at[:10] + " 09:30") if opened_below else None
    latest_event = None
    had_confirmed = False
    confirmed_event = None
    gap = False
    previous = None
    for bar in bars:
        at = datetime.fromisoformat(bar["at"])
        if previous and active and _trading_minutes(previous, at) > 2 and not _certified_gap(previous_bar,bar):
            gap = True
        previous = at;previous_bar=bar
        if intraday.price_at_or_above_line(bar.get("low"), threshold) is False and active is None:
            # 新浪分钟K以区间结束分钟标时；向前取一分钟，避免高估15分钟收回资格。
            active = at - timedelta(minutes=1) if bar.get("source") == "新浪1分钟OHLC" else at
        if active and intraday.price_at_or_above_line(bar.get("close"), threshold) is True:
            elapsed = _trading_minutes(active, at)
            if elapsed <= 15:
                latest_event = {"kind": "快速收回", "breach_at": active.isoformat(sep=" ", timespec="minutes"),
                                "reclaim_at": bar["at"], "minutes": elapsed}
            else:
                had_confirmed = True
                latest_event = {"kind": "曾失守后收回", "breach_at": active.isoformat(sep=" ", timespec="minutes"),
                                "reclaim_at": bar["at"], "minutes": elapsed}
                confirmed_event = latest_event
            active = None
    if gap:
        return {"state": "待核验", "event": latest_event, "reason": "跌破期间分钟数据不连续"}
    if active:
        elapsed = _trading_minutes(active, datetime.fromisoformat(quote_at[:16]))
        state = "确认失守" if elapsed > 15 or had_confirmed else "15分钟内待确认"
        return {"state": state, "event": {"kind": state,
                "breach_at": active.isoformat(sep=" ", timespec="minutes"), "minutes": elapsed},
                "prior_confirmed_event": confirmed_event}
    if had_confirmed:
        return {"state": "曾失守后收回", "event": confirmed_event}
    return {"state": "快速收回" if latest_event else "持稳", "event": latest_event}


def _line_time_note(period, current_holds, minute_state, last_minute_at=None,
                    event=None, reason=None):
    """分别陈述逐股现价事实与分钟记录截至其最后有效时间的历史事实。"""
    line = f"MA{period}"
    current = ("现价已在线上" if current_holds is True else
               "现价已在线下" if current_holds is False else "现价与触线价关系待核验")
    cutoff = str(last_minute_at or "")
    cutoff = cutoff[11:16] if len(cutoff) >= 16 else "未知时间"
    state = minute_state or "待核验"
    if state in ("确认失守", "15分钟内待确认") and current_holds is True:
        return f"{current}；截至{cutoff}的分钟记录仍显示失守，收回时点待确认。"
    if current_holds is False and state in ("持稳", "快速收回", "曾失守后收回",
                                             "15分钟内待确认"):
        if state == "持稳":
            historical = "分钟记录显示此前持稳"
        elif state == "快速收回":
            minutes = (event or {}).get("minutes")
            historical = (f"分钟记录显示此前曾在{minutes}个交易分钟内收回"
                          if minutes is not None else "分钟记录显示此前曾收回")
        elif state == "曾失守后收回":
            historical = "分钟记录显示此前曾失守后收回"
        else:
            historical = "分钟记录显示此前触线，收回仍待确认"
        return f"{current}；截至{cutoff}{historical}，当前失守时点待确认。"
    if current_holds is False and state == "确认失守":
        return f"{current}；截至{cutoff}的分钟记录也显示失守。"
    if current_holds is True and state in ("快速收回", "曾失守后收回"):
        if state == "快速收回":
            minutes = (event or {}).get("minutes")
            duration = f"在{minutes}个交易分钟内" if minutes is not None else ""
            historical = f"分钟记录确认曾跌破后{duration}收回"
        else:
            historical = "分钟记录显示曾失守后收回，且收回超过15分钟"
        return f"{current}；截至{cutoff}{historical}。"
    if current_holds is True and state == "持稳":
        return f"{current}；截至{cutoff}的分钟记录未显示失守。"
    detail = f"（{reason}）" if reason else ""
    return f"{current}；分钟记录截至{cutoff}待核验{detail}。"


def _monitor_row(base, live, quote, bars, completed, quote_at, baseline_asof,
                 price_context=None, calendar=None):
    item = {"code": base["code"], "name": base["name"], "daily_score": base.get("score"),
            "baseline_asof": baseline_asof, "status": "待核验", "lines": {},
            "quote_at": quote_at, "change_pct": live.get("change_pct") if live else None,
            "price": quote.get("price") if quote else None,
            "current_strong_candidate": bool(live and live.get("current_strong_candidate")),
            "minute_source": bars[0].get("source") if bars else None,
            "price_basis_version": intraday.PRICE_BASIS_VERSION}
    if not live or (live.get("intraday_quote_fresh") is not True and live.get('intraday_observation_available') is not True):
        item["reason"] = (live or {}).get("intraday_quote_status") or "逐股报价缺失"
        item["lines"] = {f"MA{period}": {"state": "待核验", "event": None,
                                         "reason": item["reason"]} for period in LINES}
        return item
    context = price_context or intraday.align_price_basis(
        quote, completed, calendar or [], observation_day=str(quote_at or "")[:10],
        quote_at=quote_at)
    item.update(price_basis_status=("可比" if context.get("valid") else "待核验"),
                price_basis_reason=context.get("reason"),
                price_basis_k=context.get("scale_factor"),
                reference_date=context.get("last_history_date"),
                expected_reference_date=context.get("expected_history_date"))
    if not context.get("valid"):
        item["reason"] = "均线待核验（" + str(context.get("reason") or "价格口径未确认") + ")"
        item["lines"] = {f"MA{period}": {"state": "待核验", "event": None,
                                         "reason": item["reason"]} for period in LINES}
        return item
    if not completed or not quote or not quote_at:
        item["reason"] = "完成日线或报价不足"
        item["lines"] = {f"MA{period}": {"state": "待核验", "event": None,
                                         "reason": item["reason"]} for period in LINES}
        return item
    thresholds = context["thresholds"]
    open_price = quote.get("open")
    day_low = quote.get("low")
    current_price = quote.get("price")
    if not _positive(open_price) or not _positive(day_low) or not _positive(current_price):
        item["reason"] = "开盘或日内最低价缺失"
        return item
    breached = {period: intraday.price_at_or_above_line(day_low, thresholds[period]) is False
                for period in LINES}
    needs_minutes = any(breached.values())
    minute_bars = []
    minute_error = None
    if needs_minutes:
        valid_bars = [bar for bar in (bars or []) if bar.get("at", "") <= quote_at[:16]]
        if (not valid_bars or _trading_minutes(datetime.fromisoformat(valid_bars[-1]["at"]),
                                              datetime.fromisoformat(quote_at[:16])) > 2):
            minute_error = "触及均线，但分钟记录未覆盖最新报价"
        else:
            first_limit = quote_at[:10] + (
                " 09:31" if valid_bars[0].get("source") == "新浪1分钟OHLC" else " 09:30")
            if valid_bars[0]["at"] > first_limit:
                minute_error = "分钟记录未覆盖当日触线价格"
            else:
                aligned_minutes = intraday.align_minute_bars(context, valid_bars)
                if not aligned_minutes.get("valid"):
                    minute_error = aligned_minutes.get("reason") or "分钟价格口径待核验"
                else:
                    minute_bars = aligned_minutes["bars"]
                    item["minute_basis_source"] = aligned_minutes.get("source")
                    item["minute_basis_k"] = aligned_minutes.get("scale_factor")
                    if min(bar["low"] for bar in minute_bars) > day_low + .011:
                        minute_error = "分钟记录未覆盖当日触线价格"
    for period, threshold in thresholds.items():
        current_holds = intraday.price_at_or_above_line(current_price, threshold)
        if breached[period] and minute_error:
            detail = {"state": "待核验", "event": None, "reason": minute_error}
        elif breached[period]:
            detail = _line_status(minute_bars, threshold,
                                  intraday.price_at_or_above_line(open_price, threshold) is False,
                                  quote_at[:16])
        else:
            detail = {"state": "持稳", "event": None}
        detail["threshold"] = round(threshold, 4)
        detail["current_holds"] = current_holds
        detail["last_minute_at"] = minute_bars[-1].get("at") if minute_bars else None
        detail["note"] = _line_time_note(
            period, current_holds, detail.get("state"), detail.get("last_minute_at"),
            detail.get("event"), detail.get("reason"))
        item["lines"]["MA" + str(period)] = detail
    states = {period: item["lines"]["MA" + str(period)]["state"] for period in LINES}
    if any(state == "待核验" for state in states.values()):
        item["reason"] = "；".join("MA" + str(period) + " " + str(item["lines"]["MA" + str(period)].get("reason") or "待核验")
                                  for period in LINES if states[period] == "待核验")
    elif any(state == "确认失守" or state == "曾失守后收回" for state in states.values()):
        item["status"] = ("结构受损" if states[20] in ("确认失守", "曾失守后收回") else
                          "趋势受损" if states[10] in ("确认失守", "曾失守后收回") else "短期走弱")
    elif any(state == "15分钟内待确认" for state in states.values()):
        item["status"] = "15分钟内待确认"
    else:
        item["status"] = "符合预期"
    if not item.get("reason"):
        item["reason"] = ("；".join("MA" + str(p) + " " + states[p] for p in LINES
                                  if states[p] != "持稳") or "MA5/10/20 均持稳")
    return item


def attach(snap, quotes, klines, price_contexts=None, trading_calendar=None):
    """在快照发布前附上收盘主榜与盘中观察。"""
    scan_day = str(snap.get("quote_capture_at") or snap.get("generated_at") or "")[:10]
    close_board = _save_close_board(snap, scan_day)
    if not close_board:
        close_board = {"version": VERSION, "asof": None, "stocks": [], "count": 0}
    close_board = dict(close_board)
    capture_time = str(snap.get("quote_capture_at") or "")[11:16]
    close_board["today_pending"] = (snap.get("session") in ("尾盘", "已收盘")
                                     and capture_time >= "15:00"
                                     and close_board.get("asof") != scan_day)
    snap["close_strong_board"] = close_board
    _attach_new_strength(snap, scan_day)
    _attach_trend_observations(snap, quotes, klines, scan_day,
                               price_contexts=price_contexts,
                               trading_calendar=trading_calendar)


def _attach_new_strength(snap, day):
    """收盘后切回盘中页时，仍能查看最后一次有效候选名单。"""
    normal = snap.get("session") in ("早盘", "午盘", "尾盘")
    path = LIVE_DIR / (day + ".json")
    retained = _read_json(path)
    if normal:
        all_rows = (snap.get("stocks") or []) + (snap.get("coverage_catalog") or [])
        fresh = [s for s in all_rows if s.get("intraday_quote_fresh") is True]
        if fresh:
            candidates = [s for s in fresh if s.get("current_strong_candidate") or s.get("startup_candidate")]
            candidates.sort(key=lambda s: (-int(bool(s.get("current_strong_candidate"))),
                                           -(s.get("intraday_score") or 0), str(s.get("code") or "")))
            retained = {"version": VERSION, "day": day, "observed_at": snap.get("generated_at"),
                        "last_valid_quote_at": max((s.get("intraday_quote_at") or "") for s in fresh),
                        "rows": [{"code": s.get("code"), "name": s.get("name"),
                                  "change_pct": s.get("change_pct"),
                                  "relative_return_pct": s.get("intraday_relative_return_pct"),
                                  "intraday_score": s.get("intraday_score"),
                                  "quote_at": s.get("intraday_quote_at"),
                                  "kind": s["intraday_observation_state"]}
                                 for s in candidates]}
            LIVE_DIR.mkdir(parents=True, exist_ok=True)
            config.atomic_write_text(path, json.dumps(retained, ensure_ascii=False, separators=(",", ":")))
    if not isinstance(retained, dict) or retained.get("version") != VERSION:
        retained = {"version": VERSION, "day": day, "rows": [],
                    "reason": "该交易日尚无有效盘中强势留档"}
    snap["intraday_new_strength"] = retained


def _attach_trend_observations(snap, quotes, klines, day, price_contexts=None,
                               trading_calendar=None):
    """同一候选池观察 MA5/10/20；分钟数据合并获取，目标线独立判定。"""
    normal = (snap.get("session") in ("早盘", "午盘", "尾盘")
              or snap.get('session') == '午间休市' and any(r.get('intraday_observation_available') is True
                 for r in (snap.get('stocks') or []) + (snap.get('coverage_catalog') or [])))
    baseline_asof = (snap.get("strength_model") or {}).get("asof")
    if not normal:
        for period in LINES:
            directory = TREND_DIRS[period]
            saved = _read_json(directory / (day + ".json"))
            if not saved and snap.get("session") == "非交易日":
                for candidate in sorted(directory.glob("????-??-??.json"), reverse=True):
                    if candidate.stem < day:
                        saved = _read_json(candidate)
                        if saved:
                            break
            key = f"trend_ma{period}_observation"
            if isinstance(saved, dict) and saved.get("version") == TREND_VERSION:
                snap[key] = {**saved, "phase_note": "保留最后一次有效盘中观察；当前不生成新结论"}
            else:
                snap[key] = {"version": TREND_VERSION, "line": f"MA{period}",
                             "monitor_day": day, "baseline_asof": baseline_asof,
                             "near_limit_pct": TREND_NEAR_PCT, "base_count": 0,
                             "valid_quote_count": 0, "main_rows": [], "reclaim_rows": [],
                             "pending_rows": [], "pending_count": 0,
                             "price_basis_version": intraday.PRICE_BASIS_VERSION,
                             "reason": f"等待正常交易时段的有效报价与 MA{period} 观察"}
        return

    all_rows = (snap.get("stocks") or []) + (snap.get("coverage_catalog") or [])
    if not isinstance(price_contexts, dict):
        price_contexts = {}
    bases, near, valid_counts = {}, {p: [] for p in LINES}, {p: 0 for p in LINES}
    pending_rows = {p: [] for p in LINES}
    quote_times = {}
    minute_watch_records = {}
    market_calendar = list(trading_calendar or intraday.trading_calendar_from_klines(klines))
    for period in LINES:
        bases[period] = {str(row.get("code")): row for row in all_rows
                         if isinstance(baseline_asof, str) and baseline_asof < day
                         and row.get("signal_date") == baseline_asof
                         and bool(row.get("trend_online"))
                         and _positive(row.get("signal_close"))
                         and _positive(row.get(f"ma{period}"))
                         and row["signal_close"] >= row[f"ma{period}"]}
    completed = {code: [bar for bar in (klines.get(code) or [])
                        if str(bar.get("date") or "") < day]
                 for code in set().union(*(set(base) for base in bases.values()))}
    for period in LINES:
        for code, row in bases[period].items():
            quote = quotes.get(code) or {}
            bars = completed[code]
            price, low, prior_quote_close = (quote.get(key) for key in ("price", "low", "last_close"))
            quote_at = row.get('intraday_judgment_at') or row.get("intraday_quote_at")
            if ((row.get("intraday_quote_fresh") is not True and row.get('intraday_observation_available') is not True) or not quote_at
                    or not str(quote_at).startswith(day)
                    or not all(_positive(v) for v in (price, low))):
                reason = (row.get("intraday_price_basis_reason")
                          or row.get("intraday_quote_status")
                          or "逐股报价缺失或报价过期")
                pending_rows[period].append({
                    "code": code, "name": row.get("name"), "line": f"MA{period}",
                    "quote_at": quote_at, "status": "待核验", "reason": reason})
                continue
            context = price_contexts.get(code)
            if context is None:
                context = intraday.align_price_basis(
                    quote, bars, market_calendar, observation_day=day, quote_at=quote_at)
                price_contexts[code] = context
            if not context.get("valid"):
                pending_rows[period].append({
                    "code": code, "name": row.get("name"), "line": f"MA{period}",
                    "quote_at": quote_at, "status": "待核验",
                    "reason": context.get("reason") or row.get("intraday_price_basis_reason")
                             or "价格口径待核验"})
                continue
            valid_counts[period] += 1
            threshold = context["thresholds"][period]
            provisional_ma = context["provisional_ma"][period]
            distance_pct = (0.0 if price == threshold
                            else (price / provisional_ma - 1) * 100)
            distance_atr = row.get(f"intraday_distance_ma{period}_atr")
            if (not _number(distance_atr) and _positive(context.get("atr20"))
                    and _positive(provisional_ma)):
                distance_atr = ((0.0 if price == threshold else price - provisional_ma)
                                / context["atr20"])
            if low < threshold and abs(distance_pct) <= TREND_NEAR_PCT:
                quote_times[code] = quote_at
                record = minute_watch_records.get(code)
                if record is None:
                    record = {"row": row, "quote": quote, "bars": bars,
                              "quote_at": quote_at, "context": context,
                              "periods": set()}
                    minute_watch_records[code] = record
                record["periods"].add(period)
            if not (0 <= distance_pct <= TREND_NEAR_PCT
                    and intraday.price_at_or_above_line(price, threshold) is True
                    and low < prior_quote_close):
                continue
            item = {"code": code, "name": row.get("name"), "line": f"MA{period}",
                    "baseline_asof": baseline_asof, "quote_at": quote_at,
                    "price": price, "change_pct": row.get("change_pct"),
                    "daily_score": row.get("stock_strength_score"),
                    f"ma{period}": round(provisional_ma, 4),
                    "provisional_ma": round(provisional_ma, 4),
                    "completed_day_ma": round(context["daily_ma"][period], 4),
                    "threshold_price": threshold,
                    "distance_atr": distance_atr,
                    "atr_status": context.get("atr20_status") or "待核验",
                    "atr_reason": context.get("atr20_reason"),
                    "line_value": round(provisional_ma, 4),
                    "distance_pct": round(distance_pct, 3), "day_low": low,
                    "low_distance_pct": round((low / threshold - 1) * 100, 3),
                    "risk_flags": row.get("intraday_risk_flags") or []}
            near[period].append((item, row, quote, bars, low < threshold))
    minute_map = _get_minutes(list(quote_times), day, quote_times) if quote_times else {}
    checked_rows = {}
    for code, record in minute_watch_records.items():
        row, quote = record["row"], record["quote"]
        bars, quote_at, context = record["bars"], record["quote_at"], record["context"]
        checked_rows[code] = _monitor_row(
            {"code": code, "name": row.get("name"),
             "score": row.get("stock_strength_score")},
            row, quote, minute_map.get(code), bars, quote_at, baseline_asof,
            price_context=context, calendar=market_calendar)
        for checked_period, line in (checked_rows[code].get("lines") or {}).items():
            period_key = checked_period[2:]
            row[f"intraday_ma{period_key}_minute_state"] = line.get("state") or "待核验"
            row[f"intraday_ma{period_key}_minute_record_at"] = line.get("last_minute_at")
            row[f"intraday_ma{period_key}_minute_note"] = line.get("note") or line.get("reason") or "分钟记录待核验"
            row[f"intraday_ma{period_key}_current_note"] = (
                f"现价守住盘中暂态MA{period_key}触线价"
                if line.get("current_holds") is True else
                f"现价低于盘中暂态MA{period_key}触线价"
                if line.get("current_holds") is False else f"MA{period_key}当前关系待核验")
            if int(period_key) in record["periods"] and line.get("current_holds") is False:
                pending_rows[int(period_key)].append({
                    "code": code, "name": row.get("name"), "line": checked_period,
                    "quote_at": quote_at, "status": "现价低于触线价",
                    "reason": line.get("note") or line.get("reason") or "分钟记录待核验"})
    def order(item):
        risks = item.get("risk_flags") or []
        severe = any(flag in risks for flag in ("接近跌停", "大幅下跌", "明显冲高回落", "一字跌停"))
        return (severe, bool(risks), item["distance_pct"], -(item.get("daily_score") or 0), item["code"])
    for period in LINES:
        main_rows, reclaim_rows = [], []
        for item, row, quote, bars, breached in near[period]:
            if not breached:
                item["status"] = "贴线未破"
                row[f"intraday_ma{period}_minute_state"] = "持稳"
                row[f"intraday_ma{period}_minute_note"] = (
                    f"日内最低价未低于MA{period}触线价，现价守住")
                main_rows.append(item)
                continue
            code = item["code"]
            if code not in checked_rows:
                checked_rows[code] = _monitor_row(
                    {"code": code, "name": row.get("name"),
                     "score": row.get("stock_strength_score")},
                    row, quote, minute_map.get(code), bars, item["quote_at"], baseline_asof,
                    price_context=price_contexts.get(code), calendar=market_calendar)
                for checked_period, line in (checked_rows[code].get("lines") or {}).items():
                    state = line.get("state") or "待核验"
                    row[f"intraday_ma{checked_period[2:]}_minute_state"] = state
                    row[f"intraday_ma{checked_period[2:]}_minute_record_at"] = line.get("last_minute_at")
                    row[f"intraday_ma{checked_period[2:]}_minute_note"] = (
                        line.get("note") or line.get("reason") or
                        f"{checked_period}分钟记录待核验")
            checked = checked_rows[code]
            lines = checked.get("lines") or {}
            target = lines.get(f"MA{period}") or {}
            if (target.get("state") == "快速收回"
                    and target.get("current_holds") is True):
                event = target.get("event") or {}
                item.update(status="15分钟内收回", minute_source=checked.get("minute_source"),
                            breach_at=event.get("breach_at"), reclaim_at=event.get("reclaim_at"),
                            reclaim_minutes=event.get("minutes"))
                reclaim_rows.append(item)
            else:
                pending_rows[period].append({
                    "code": item["code"], "name": item["name"],
                    "line": f"MA{period}", "quote_at": item["quote_at"],
                    "status": target.get("state") or "待核验",
                    "reason": target.get("note") or target.get("reason") or
                             "当前报价与分钟记录时间关系待核验"})
        main_rows.sort(key=order)
        reclaim_rows.sort(key=order)
        base = bases[period]
        result = {"version": TREND_VERSION, "line": f"MA{period}",
                  "price_basis_version": intraday.PRICE_BASIS_VERSION,
                  "monitor_day": day, "baseline_asof": baseline_asof,
                  "observed_at": snap.get("generated_at"), "near_limit_pct": TREND_NEAR_PCT,
                  "base_count": len(base), "valid_quote_count": valid_counts[period],
                  "pending_count": len(pending_rows[period]),
                  "pending_rows": pending_rows[period],
                  "last_valid_quote_at": max((row.get('intraday_judgment_at') or row.get("intraday_quote_at") or "" for row in base.values()
                                              if row.get("intraday_quote_fresh") is True or row.get('intraday_observation_available') is True), default=None),
                  "main_rows": main_rows, "reclaim_rows": reclaim_rows,
                  "minute_checked_count": sum(item["code"] in quote_times
                                              for item, *_ in near[period]),
                  "source": "逐股报价与前复权日线由统一口径入口核验；分钟来源另核验未复权尺度"}
        result["criterion"] = (f"前一完成日趋势在线且收盘站上MA{period}；日低低于昨收，"
                               f"现价距暂态MA{period}在0至1%；未破或15个交易分钟内收回。"
                               "仅为近线位置观察，不等于已确认回踩；风险较少者优先，同组再按距离排序")
        snap[f"trend_ma{period}_observation"] = result
        directory = TREND_DIRS[period]
        directory.mkdir(parents=True, exist_ok=True)
        config.atomic_write_text(directory / (day + ".json"),
                                 json.dumps(result, ensure_ascii=False, separators=(",", ":")))
