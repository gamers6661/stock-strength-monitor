# -*- coding: utf-8 -*-
"""盘中价格强度、暂态趋势、风险门槛与真实扫描留痕。

盘中分描述每次有效获取的价格表现；日内路径关联当天采样，不改写完成日线进攻分。
阈值均为透明研究初值；有效报价必须来自同一日、时间新鲜且可比的样本。
"""
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta
from hashlib import sha256
import json
import math
import re
from pathlib import Path
from statistics import mean

import config
import intraday_path


VERSION = "盘中观察初版7"
PRICE_BASIS_VERSION = "统一盘中价格口径2"
HISTORY_DIR = config.CACHE_DIR / "intraday_history"
REFERENCE_DIR = config.CACHE_DIR / "intraday_reference"
REPORT_PATH = config.ROOT / "research" / "intraday_validation_report.md"
PAIR_HISTORY_PATH = HISTORY_DIR / "pairs.jsonl"
CLOSE_HISTORY_DIR = config.CACHE_DIR / "intraday_close_observations"


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _positive(value):
    return _number(value) and value > 0


def _average(values):
    return sum(values) / len(values) if values else None


def price_at_or_above_line(price, line):
    """未舍入边界规则：刚好等于线时归为守住。"""
    if not _positive(price) or not _positive(line):
        return None
    return price >= line


_RAW_QUOTE_SOURCES = {"tencent_realtime_quote", "akshare_sina_spot"}
_QFQ_HISTORY_SOURCES = {"tencent_qfqday"}
_RAW_HISTORY_SOURCES = {"tencent_day"}
_RAW_MINUTE_SOURCES = {"sina_1m_unadjusted"}
_QUOTE_CLOSE_PRICE_DECIMALS = {"tencent_realtime_quote": 2, "akshare_sina_spot": 2}
_HISTORY_CLOSE_PRICE_DECIMALS = {"tencent_day": 2}


def _known_price_decimals(explicit, source, contracts):
    """读取来源合同的实际价格字段精度；未知来源不猜测精度。"""
    if isinstance(explicit, int) and not isinstance(explicit, bool) and 0 <= explicit <= 8:
        return explicit
    return contracts.get(source)


def _raw_close_rounding_tolerance(quote, history_bar):
    q_decimals = _known_price_decimals(
        quote.get("last_close_precision_digits"), quote.get("price_basis_source"),
        _QUOTE_CLOSE_PRICE_DECIMALS)
    h_decimals = _known_price_decimals(
        history_bar.get("close_precision_digits"), history_bar.get("price_basis_source"),
        _HISTORY_CLOSE_PRICE_DECIMALS)
    if q_decimals is None or h_decimals is None:
        return None
    # 两个独立显示字段各自四舍五入时，最大误差为两个半最小单位之和。
    return 0.5 * (10 ** (-q_decimals) + 10 ** (-h_decimals))


def trading_calendar_from_klines(klines):
    """按全市场共同出现的K线日期构建交易日序列，不用自然日推算。"""
    counts = {}
    for bars in (klines or {}).values():
        for bar in bars or []:
            day = str(bar.get("date") or "")
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                counts[day] = counts.get(day, 0) + 1
    threshold = max(counts.values(), default=0) * 0.5
    return sorted(day for day, count in counts.items() if count >= threshold)


def _explicit_quote_datetime(quote, quote_at=None):
    raw = quote_at or (quote or {}).get("quote_at") or (quote or {}).get("ts")
    if isinstance(raw, datetime):
        return raw
    value = str(raw or "").strip()
    if not (re.match(r"^\d{12}(?:\d{2})?$", value)
            or re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?$", value)):
        return None
    return parse_quote_timestamp(value)


def _valid_historical_price_bar(bar):
    values = [bar.get(key) for key in ("open", "high", "low", "close")]
    if not all(_positive(value) for value in values):
        return False
    opening, high, low, close = values
    return low <= min(opening, close) <= max(opening, close) <= high


def align_price_basis(quote, history_bars, calendar, observation_day=None, quote_at=None):
    """统一核验逐股报价和完成日K线，并把历史价格换到报价尺度。

    只有显式来源、逐股日期、交易日窗口、昨收字段语义和价格有效性均通过后，
    才会返回可计算的对齐K线。5%差异只拦截异常，不能单独证明口径可比。
    """
    q = quote or {}
    result = {"version": PRICE_BASIS_VERSION, "valid": False,
              "reason": None, "aligned_bars": [], "scale_factor": None,
              "gap_pct": None, "quote_day": None, "quote_at": None,
              "expected_history_date": None, "last_history_date": None,
              "quote_basis": q.get("price_basis"),
              "quote_basis_source": q.get("price_basis_source"),
              "history_basis": None, "history_basis_source": None,
              "daily_ma": {}, "thresholds": {}, "provisional_ma": {},
              "atr20": None, "atr20_status": "待核验",
              "atr20_reason": "尚未完成21根数据核验", "atr20_dates": [],
              "raw_close_tolerance": None}

    def fail(reason):
        result["reason"] = reason
        return result

    at = _explicit_quote_datetime(q, quote_at)
    if at is None:
        return fail("逐股报价日期或时间缺失，无法核验报价日")
    quote_day = at.date().isoformat()
    result.update(quote_day=quote_day, quote_at=at.isoformat(sep=" ", timespec="seconds"))
    if observation_day and quote_day != str(observation_day)[:10]:
        return fail(f"逐股报价日期{quote_day}与观察日{str(observation_day)[:10]}不一致")

    quote_close = q.get("last_close")
    if not _positive(quote_close):
        return fail("报价昨收缺失、为零或无效")
    if q.get("last_close_semantics") != "previous_trade_day_raw_close":
        return fail("报价昨收字段含义未确认（需为前一交易日未复权收盘）")
    if q.get("price_basis") != "raw" or q.get("price_basis_source") not in _RAW_QUOTE_SOURCES:
        return fail("报价来源或复权方式未确认")

    dates = sorted(set(str(day) for day in (calendar or [])
                       if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day))
                       and str(day) < quote_day))
    if not dates:
        return fail("缺少报价日前交易日历")
    expected = dates[-1]
    result["expected_history_date"] = expected
    source_bars = [bar for bar in (history_bars or [])
                   if str(bar.get("date") or "") < quote_day]
    source_bars.sort(key=lambda bar: str(bar.get("date") or ""))
    last_date = str(source_bars[-1].get("date") or "") if source_bars else None
    result["last_history_date"] = last_date
    if last_date != expected:
        return fail(f"历史最后完成日{last_date or '缺失'}不是报价日前一交易日{expected}")
    expected_window = dates[-20:]
    if len(expected_window) < 20:
        return fail("报价日前20个应有交易日不足，MA20历史窗口不完整")
    by_date = {str(bar.get("date") or ""): bar for bar in source_bars}
    if len(by_date) != len(source_bars):
        return fail("历史K线日期重复，窗口无法核验")
    if [str(bar.get("date") or "") for bar in source_bars[-20:]] != expected_window:
        return fail("报价日前最近20个应有交易日存在历史窗口缺口")
    aligned_input = [by_date[day] for day in expected_window]
    if not all(_valid_historical_price_bar(bar) for bar in aligned_input):
        return fail("报价日前历史窗口含缺失、零值或异常OHLC价格")

    history_modes = {(bar.get("price_basis"), bar.get("price_basis_source"))
                     for bar in aligned_input}
    if len(history_modes) != 1:
        return fail("历史窗口来源或复权方式混杂，无法同比例换算")
    history_basis, history_source = next(iter(history_modes))
    result.update(history_basis=history_basis, history_basis_source=history_source)
    if history_basis not in ("qfq", "raw"):
        return fail("历史日线复权方式或来源字段缺失，旧缓存待核验")
    if history_basis == "qfq" and history_source not in _QFQ_HISTORY_SOURCES:
        return fail("前复权日线来源未确认，不允许比例换算")
    if history_basis == "raw" and history_source not in _RAW_HISTORY_SOURCES:
        return fail("未复权日线来源未确认")

    history_close = aligned_input[-1].get("close")
    if not _positive(history_close):
        return fail("对应历史完成日收盘缺失、为零或无效")
    gap = (quote_close / history_close - 1) * 100
    result["gap_pct"] = gap
    limit = config.INTRADAY["max_price_basis_gap_pct"]
    if abs(gap) > limit:
        return fail(f"报价昨收与对应历史收盘相差{gap:+.2f}%，超过{limit:.1f}%异常限制")

    if history_basis == q.get("price_basis") == "raw":
        tolerance = _raw_close_rounding_tolerance(q, aligned_input[-1])
        result["raw_close_tolerance"] = tolerance
        if tolerance is None:
            return fail("同尺度未复权昨收精度信息缺失，无法核验来源舍入容差")
        difference = abs(float(quote_close) - float(history_close))
        if difference > tolerance:
            return fail(
                f"同日期同尺度未复权昨收差异{difference:.4f}元，"
                f"超过来源精度舍入容差{tolerance:.4f}元")

    if history_basis == "qfq" and q.get("price_basis") == "raw":
        factor = quote_close / history_close
    elif history_basis == q.get("price_basis") == "raw":
        # 同为明确标记的未复权价格，按同尺度直接比较；差异阈值不参与此判断。
        factor = 1.0
    else:
        return fail("报价与历史日线的复权方式组合不支持转换")

    aligned = []
    for bar in aligned_input:
        copied = dict(bar)
        for key in ("open", "high", "low", "close"):
            copied[key] = float(bar[key]) * factor
        copied["aligned_price_basis"] = "quote_scale"
        aligned.append(copied)
    closes = [bar["close"] for bar in aligned]
    fixed = {period: _average(closes[-period:]) for period in (5, 10, 20)}
    thresholds = {period: _average(closes[-(period - 1):]) for period in (5, 10, 20)}
    price = q.get("price")
    provisional = ({period: ((sum(closes[-(period - 1):]) + price) / period
                             if _positive(price) else None)
                    for period in (5, 10, 20)})
    atr = None
    atr_status = "待核验"
    atr_reason = None
    atr_dates = dates[-21:]
    if len(atr_dates) < 21:
        atr_reason = "ATR所需21个应有交易日不足"
    elif any(day not in by_date for day in atr_dates):
        atr_reason = "ATR所需21根历史K线存在应有交易日缺口"
    else:
        atr_bars = [by_date[day] for day in atr_dates]
        atr_modes = {(bar.get("price_basis"), bar.get("price_basis_source"))
                     for bar in atr_bars}
        if len(atr_modes) != 1 or next(iter(atr_modes)) != (history_basis, history_source):
            atr_reason = "ATR 21根窗口来源或复权尺度混杂"
        elif not all(_valid_historical_price_bar(bar) for bar in atr_bars):
            atr_reason = "ATR 21根窗口含缺失、零值或异常OHLC价格"
        else:
            # ATR必须整窗使用已确认的同一个转换系数，原始K线仍保持不变。
            scaled = [{key: float(bar[key]) * factor for key in ("high", "low", "close")}
                      for bar in atr_bars]
            true_ranges = [max(scaled[i]["high"] - scaled[i]["low"],
                               abs(scaled[i]["high"] - scaled[i - 1]["close"]),
                               abs(scaled[i]["low"] - scaled[i - 1]["close"]))
                           for i in range(1, len(scaled))]
            if len(true_ranges) == 20:
                atr = _average(true_ranges)
                atr_status = "可用"
            else:
                atr_reason = "ATR 21根窗口未形成20个有效真实波幅"
    result.update(valid=True, reason=None, aligned_bars=aligned,
                  scale_factor=factor, daily_ma=fixed, thresholds=thresholds,
                  provisional_ma=provisional, atr20=atr,
                  atr20_status=atr_status, atr20_reason=atr_reason,
                  atr20_dates=atr_dates if atr_status == "可用" else [])
    return result


def align_minute_bars(price_context, minute_bars):
    """把分钟线核验到与当前报价相同的尺度；不猜测未知来源的调整方式。"""
    if not price_context or not price_context.get("valid"):
        return {"valid": False, "reason": "分钟线依赖的历史价格口径待核验", "bars": [], "scale_factor": None}
    quote_source = price_context.get("quote_basis_source")
    if price_context.get("quote_basis") != "raw" or quote_source not in _RAW_QUOTE_SOURCES:
        return {"valid": False, "reason": "当前报价价格尺度未确认，无法核验分钟线", "bars": [], "scale_factor": None}
    bars = list(minute_bars or [])
    if not bars:
        return {"valid": False, "reason": "分钟行情缺失", "bars": [], "scale_factor": None}
    modes = {(bar.get("price_basis"), bar.get("price_basis_source")) for bar in bars}
    if len(modes) != 1:
        return {"valid": False, "reason": "分钟行情来源或复权方式混杂", "bars": [], "scale_factor": None}
    basis, source = next(iter(modes))
    if basis != "raw" or source not in _RAW_MINUTE_SOURCES:
        return {"valid": False, "reason": "分钟行情复权方式或来源未确认", "bars": [], "scale_factor": None}
    day = price_context.get("quote_day")
    if any(str(bar.get("at") or "")[:10] != day for bar in bars):
        return {"valid": False, "reason": "分钟行情日期与逐股报价日期不一致", "bars": [], "scale_factor": None}
    if not all(_valid_historical_price_bar(bar) for bar in bars):
        return {"valid": False, "reason": "分钟行情含缺失或异常OHLC价格", "bars": [], "scale_factor": None}
    return {"valid": True, "reason": None, "bars": bars,
            "scale_factor": 1.0, "basis": basis, "source": source}


def parse_quote_timestamp(value, fallback_date=None):
    """解析腾讯/新浪的逐股报价时间；不把未知格式伪装成扫描时间。"""
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(raw, fmt)
            if fmt.startswith("%H"):
                if fallback_date is None:
                    return None
                parsed = datetime.combine(fallback_date.date() if isinstance(fallback_date, datetime)
                                          else fallback_date, parsed.time())
            return parsed
        except ValueError:
            continue
    return None


def quote_day(value, fallback_date=None):
    parsed = parse_quote_timestamp(value, fallback_date)
    return parsed.date().isoformat() if parsed else None


def _hash_codes(codes):
    return sha256("\n".join(sorted(set(map(str, codes or [])))).encode("utf-8")).hexdigest()[:16]


def _median_datetime(values):
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return ordered[middle - 1] + (ordered[middle] - ordered[middle - 1]) / 2


def _percentiles(values):
    ordered = sorted(v for v in values.values() if _number(v))
    if not ordered:
        return {code: None for code in values}
    if len(ordered) == 1:
        return {code: 50.0 if _number(value) else None for code, value in values.items()}
    return {code: round((bisect_left(ordered, value) + bisect_right(ordered, value) - 1)
                        / (2 * (len(ordered) - 1)) * 100, 2) if _number(value) else None
            for code, value in values.items()}


def load_reference_pool(day, codes):
    """一天一份固定比较池；当日后续报价缺失只改变覆盖率，不改基准名单。"""
    path = REFERENCE_DIR / f"{day}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        saved = sorted(set(map(str, data.get("codes") or [])))
        if saved:
            return saved, data.get("pool_hash") or _hash_codes(saved)
    except (OSError, ValueError, TypeError):
        pass
    fixed = sorted(set(map(str, codes or [])))
    if fixed:
        path.parent.mkdir(parents=True, exist_ok=True)
        config.atomic_write_text(path, json.dumps({"day": day, "codes": fixed,
                                                  "pool_hash": _hash_codes(fixed)},
                                                 ensure_ascii=False, separators=(",", ":")))
    return fixed, _hash_codes(fixed)


def _latest_record(day):
    path = HISTORY_DIR / f"{day}.jsonl"
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 2_000_000))
            chunk = f.read().decode("utf-8", errors="replace")
        lines = [line for line in chunk.splitlines() if line.strip()]
        if len(lines) >= 2 and size > 2_000_000:
            lines = lines[1:]
        return json.loads(lines[-1]) if lines else None
    except (OSError, ValueError, IndexError):
        return None


def _latest_record_before(day):
    """读取给定日期之前最近一次有效保存的真实扫描。"""
    try:
        paths = sorted((p for p in HISTORY_DIR.glob("????-??-??.jsonl")
                        if p.stem < str(day)), key=lambda p: p.stem, reverse=True)
    except OSError:
        return None
    for path in paths:
        try:
            with path.open("rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 2_000_000))
                chunk = f.read().decode("utf-8", errors="replace")
            lines = [line for line in chunk.splitlines() if line.strip()]
            if len(lines) >= 2 and size > 2_000_000:
                lines = lines[1:]
            if lines:
                record = json.loads(lines[-1])
                if any(intraday_path.observed(r) for r in record.get('rows', []) if isinstance(r, list)):
                    return record
                valid_record = intraday_path.load(HISTORY_DIR, path.stem).get('last_valid_record')
                if valid_record:
                    return valid_record
        except (OSError, ValueError, IndexError):
            continue
    return None


def _record_rows(record):
    return {r[0]: r for r in (record or {}).get("rows", [])
            if isinstance(r, list) and r and isinstance(r[0], str)}


def _fresh_quote(q, now, batch_center, require_today, session=None):
    raw_ts = q.get("quote_at") or q.get("ts")
    at = parse_quote_timestamp(raw_ts, now)
    if at is None:
        return None, "报价时间缺失或无法解析", None
    age = (now - at).total_seconds()
    if age < -config.INTRADAY["max_quote_future_seconds"]:
        return at, "报价时间超前", age
    morning_close = (session == "午间休市" and at.date() == now.date()
                     and 11 * 60 + 30 <= at.hour * 60 + at.minute < 13 * 60)
    if age > config.INTRADAY["max_quote_age_seconds"] and not morning_close:
        return at, "报价过期", age
    if require_today and at.date() != now.date():
        return at, "报价日期与本轮不一致", age
    if session == "午间休市" and not morning_close:
        return at, "尚无11:30上午收市行情", age
    if session in ("早盘", "午盘", "尾盘", "已收盘"):
        minute = at.hour * 60 + at.minute
        in_continuous = (9 * 60 + 30 <= minute <= 11 * 60 + 30
                         or 13 * 60 <= minute <= 15 * 60)
        if not in_continuous:
            return at, "报价时间不符合连续交易时段", age
    if batch_center and not morning_close and abs((at - batch_center).total_seconds()) > config.INTRADAY["max_quote_batch_skew_seconds"]:
        return at, "报价批次时间偏差过大", age
    if not _positive(q.get("price")):
        return at, "现价缺失", age
    if not _positive(q.get("open")):
        return at, "开盘价缺失", age
    if not _number(q.get("change_pct")):
        return at, "当日涨幅缺失", age
    if not _positive(q.get("high")) or not _positive(q.get("low")) or q["high"] < q["low"]:
        return at, "日内高低价缺失或异常", age
    tick = q.get("price_tick") if _positive(q.get("price_tick")) else 0.01
    tolerance = max(float(tick), 0.01) + 1e-8
    if (q["price"] < q["low"] - tolerance or q["price"] > q["high"] + tolerance
            or q["open"] < q["low"] - tolerance or q["open"] > q["high"] + tolerance):
        return at, "现价或开盘价超出日内高低价区间", age
    amount, volume = q.get("amount_wan"), q.get("volume_shou")
    if not _number(amount) and not _number(volume):
        return at, "成交状态缺失", age
    if (not _positive(amount)) and (not _positive(volume)):
        return at, "当日无成交或停牌", age
    return at, "有效", age


def _limit_lock(q):
    high, low, price = q.get("high"), q.get("low"), q.get("price")
    if not all(_number(v) for v in (high, low, price)) or abs(high - low) > 1e-8:
        return None
    tol = config.INTRADAY_RISK["limit_price_tolerance_pct"] / 100
    for key, label in (("limit_up", "一字涨停"), ("limit_down", "一字跌停")):
        limit_price = q.get(key)
        if _positive(limit_price) and abs(price / limit_price - 1) <= tol:
            return label
    return None


def _raw_dimensions(q, market_return):
    price, open_price = q.get("price"), q.get("open")
    relative = q["change_pct"] - market_return if market_return is not None else None
    open_return = (price / open_price - 1) * 100 if _positive(price) and _positive(open_price) else None
    high, low = q.get("high"), q.get("low")
    position = ((price - low) / (high - low) * 100
                if _positive(price) and _number(high) and _number(low) and high > low else None)
    if _number(position):
        position = max(0.0, min(100.0, position))
    return relative, open_return, position


def completed_ma_reference(completed_bars):
    """只用报价日之前的完成日收盘，给固定均线与暂态比较提供共同基准。"""
    bars = completed_bars or []
    closes = [b.get("close") for b in bars]
    out = {"daily_ma5_fixed": None, "daily_ma10_fixed": None,
           "daily_ma20_fixed": None}
    for period, key in ((5, "daily_ma5_fixed"), (10, "daily_ma10_fixed"),
                        (20, "daily_ma20_fixed")):
        if len(closes) >= period and all(_positive(v) for v in closes[-period:]):
            out[key] = round(_average(closes[-period:]), 4)
    return out


def price_basis_compatibility(quote, completed_bars):
    """兼容旧调用名；现在必须通过完整的来源、日期和窗口核验。"""
    dates = sorted({str(bar.get("date") or "") for bar in completed_bars or []
                    if bar.get("date")})
    context = align_price_basis(quote, completed_bars, dates,
                                observation_day=quote_day((quote or {}).get("quote_at")
                                                          or (quote or {}).get("ts")))
    return {"intraday_price_basis_gap_pct": (round(context["gap_pct"], 3)
                                                if _number(context.get("gap_pct")) else None),
            "intraday_price_basis_comparable": context["valid"],
            "intraday_price_basis_status": "可比" if context["valid"]
            else "待核验（" + str(context.get("reason") or "价格口径未确认") + ")"}


def provisional_trend(completed_bars, price, daily_ma20=None):
    """基于已由 align_price_basis 对齐到报价尺度的历史收盘计算暂态均线。"""
    bars = completed_bars or []
    if len(bars) < 20 or not _positive(price):
        return {"intraday_ma5": None, "intraday_ma10": None, "intraday_ma20": None,
                "intraday_trend_ok": None, "intraday_trend_failure": "完成日线不足20根"}
    closes = [b.get("close") for b in bars[-20:]]
    if not all(_positive(v) for v in closes):
        return {"intraday_ma5": None, "intraday_ma10": None, "intraday_ma20": None,
                "intraday_trend_ok": None, "intraday_trend_failure": "完成日线异常"}
    ma5 = _average(closes[-4:] + [price])
    ma10 = _average(closes[-9:] + [price])
    ma20 = _average(closes[-19:] + [price])
    failure = []
    if not ma5 > ma10:
        failure.append("盘中MA5未高于MA10")
    if not ma10 > ma20:
        failure.append("盘中MA10未高于MA20")
    # D 日暂态 MA20 必须和 D-1 的完成日 MA20 比。即使收盘后日线源
    # 已经把正式 D 日 MA20 写回 row，也不能拿它作暂态基准。
    prior_completed_ma20 = _average(closes[-20:])
    if not ma20 > prior_completed_ma20:
        failure.append("盘中MA20未高于报价日前完成日MA20")
    ma10_threshold = _average(closes[-9:])
    if price_at_or_above_line(price, ma10_threshold) is False:
        failure.append("现价低于盘中MA10")
    return {"intraday_ma5": round(ma5, 4), "intraday_ma10": round(ma10, 4),
            "intraday_ma20": round(ma20, 4),
            "intraday_ma5_exact": ma5, "intraday_ma10_exact": ma10,
            "intraday_ma20_exact": ma20,
            "intraday_ma10_trigger_price": ma10_threshold,
            "intraday_trend_ok": not failure,
            "intraday_trend_failure": "；".join(failure) if failure else None,
            "intraday_previous_completed_ma20": round(prior_completed_ma20, 4),
            "intraday_previous_completed_ma20_exact": prior_completed_ma20}


def _transition_from_previous(old, quote_at, price, ma10_threshold):
    """以各轮自己的报价和等价触线价格配对，只在报价时间前进后生成事实。"""
    if not old or len(old) < 30 or not intraday_path.observed(old) or old[28] is not True:
        return None, "首轮或上轮报价无效"
    old_at = parse_quote_timestamp(intraday_path.effective(old))
    if not old_at or not quote_at:
        return None, "逐股报价时间缺失，停止比较"
    if quote_at <= old_at:
        return None, "报价时间未前进，停止新比较"
    old_price, old_threshold = old[2], old[29]
    if not all(_positive(v) for v in (old_price, old_threshold, price, ma10_threshold)):
        return None, "两轮价格或盘中MA10无效，停止比较"
    if (price_at_or_above_line(old_price, old_threshold) is False
            and price_at_or_above_line(price, ma10_threshold) is True):
        return "扫描观察到收复MA10", "扫描观察到收复"
    if (price_at_or_above_line(old_price, old_threshold) is True
            and price_at_or_above_line(price, ma10_threshold) is False):
        return "扫描观察到失守MA10", "扫描观察到失守"
    if (len(old) > 23 and old[23] == "扫描观察到收复MA10"
            and price_at_or_above_line(price, ma10_threshold) is True):
        return "收复保持", "收复保持"
    return None, ""


def _observation_state(row, quote, prior_daily, current_temp):
    """按价格方向、市场相对表现、结构、风险和成交状态作单一描述分类。"""
    if not row.get("intraday_quote_fresh"):
        return row.get("intraday_phase_status") or "数据不可判断"
    if row.get("intraday_trade_restriction"):
        return "封板状态／成交受限"
    flags = row.get("intraday_risk_flags") or []
    if any(flag in flags for flag in
           ("接近跌停", "大幅下跌", "明显冲高回落", "现价失守盘中MA20", "一字跌停")):
        return "风险观察"
    if "触板未封" in flags:
        return "分歧观察"
    if row.get("current_strong_candidate"):
        return "当前强势"
    if row.get("startup_candidate"):
        return "初步转强，待收盘确认"
    if row.get("intraday_repair_candidate"):
        return "盘中修复"
    change = quote.get("change_pct")
    relative = row.get("intraday_relative_return_pct")
    open_return = row.get("intraday_open_return_pct")
    if _number(change) and change < 0 and _number(relative) and relative > 0:
        return "相对抗跌"
    if row.get("intraday_price_basis_comparable") is not True:
        return "均线待核验"
    if row.get("intraday_active_candidate"):
        return "活跃观察"
    if prior_daily and (not current_temp or (_number(relative) and relative < 0)
                        or (_number(open_return) and open_return < 0)
                        or "现价失守盘中MA10" in flags
                        or "现价失守盘中MA20" in flags
                        or "明显冲高回落" in flags):
        return "今日转弱"
    if current_temp:
        return "暂态趋势成立，待观察"
    return "观察"


def _drop_risk(change_pct, board_limit_pct):
    cfg = config.INTRADAY_RISK
    limit = board_limit_pct if _positive(board_limit_pct) and board_limit_pct < 900 else 10.0
    if change_pct <= -limit * cfg["near_limit_down_ratio"]:
        return "接近跌停"
    if change_pct <= -limit * cfg["large_drop_limit_ratio"]:
        return "大幅下跌"
    return None


def enrich(stocks, coverage_rows, quotes, klines, reference_codes, captured_at=None,
           session="", save_reference=True, previous_snapshot=None,
           trading_calendar=None):
    """统一计算盘中分、暂态趋势和风险；返回本轮可比样本元信息。"""
    now = captured_at or datetime.now()
    day = now.strftime("%Y-%m-%d")
    normal_session = session in ("早盘", "午盘", "尾盘")
    observation_session = normal_session or session == "午间休市"
    auction_session = session in ("盘前", "集合竞价")
    frozen_session = session in ("非交易日", "盘前", "集合竞价")
    reference, pool_hash = load_reference_pool(day, reference_codes) if save_reference and session != "非交易日" else (
        sorted(set(map(str, reference_codes or []))), _hash_codes(reference_codes))
    previous = _latest_record(day)
    if (previous is None or not any(intraday_path.observed(r) for r in previous.get('rows',[]) if isinstance(r,list))) and session in ("非交易日", "盘前", "集合竞价"):
        previous = _latest_record_before(day)
    previous_at = parse_quote_timestamp((previous or {}).get("scan_at"))
    comparable_interval = ((now - previous_at).total_seconds()
                           if previous_at and 0 < (now - previous_at).total_seconds() <= 900 else None)
    prev_rows = _record_rows(previous)
    history = intraday_path.load(HISTORY_DIR, day) if previous else {'points': {}, 'latest_rows': {}}
    if history.get('last_scan_at') != (previous or {}).get('scan_at'):
        history = {'points': {}, 'latest_rows': {}}
    # 上轮某股缺失不能抹掉它更早的有效记录。价格口径相同的旧版采样仍保留事实。
    prev_rows.update(history['latest_rows'])
    require_today = session in ("集合竞价", "早盘", "午间休市", "午盘", "尾盘", "已收盘")

    q_by_code = {str(code): q for code, q in (quotes or {}).items() if isinstance(q, dict)}
    parsed_times = []
    for code in reference:
        q = q_by_code.get(code) or {}
        dt = parse_quote_timestamp(q.get("quote_at") or q.get("ts"), now)
        if (dt and dt.date() == now.date()
                and -config.INTRADAY["max_quote_future_seconds"]
                <= (now - dt).total_seconds() <= config.INTRADAY["max_quote_age_seconds"]):
            parsed_times.append(dt)
    batch_center = _median_datetime(parsed_times)
    quote_info = {}
    for code in reference:
        q = q_by_code.get(code) or {}
        at, status, age = _fresh_quote(q, now, batch_center, require_today, session)
        if session == "非交易日":
            status = "非交易日，显示最近交易日结果"
        elif session == "盘前":
            status = "盘前观察，沿用最近收盘结果"
        elif auction_session:
            status = "集合竞价观察，不纳入正常盘中评分"
        fresh = status == "有效" and (observation_session or session == "已收盘")
        effective_at = now.replace(hour=11,minute=30,second=0,microsecond=0) if session == "午间休市" and fresh else at
        prior_at = parse_quote_timestamp(intraday_path.effective(prev_rows.get(code))) if prev_rows.get(code) else None
        if fresh and prior_at and effective_at and effective_at < prior_at:
            fresh, status = False, '报价时间倒退，沿用最近有效判断'
        quote_info[code] = {"at": at, "effective_at": effective_at, "status": status, "age": age, "fresh": fresh}

    mainboard = []
    for code in reference:
        q, info = q_by_code.get(code) or {}, quote_info[code]
        if not info["fresh"] or not _number(q.get("change_pct")):
            continue
        board_type = q.get("board_type") or config.board_of(code)[0]
        if board_type in ("sh_main", "sz_main"):
            mainboard.append(q["change_pct"])
    market_return = mean(mainboard) if len(mainboard) >= 5 else None

    raw = {}
    rel_values, open_values = {}, {}
    for code in reference:
        q, info = q_by_code.get(code) or {}, quote_info[code]
        if not info["fresh"] or market_return is None:
            continue
        rel, opn, pos = _raw_dimensions(q, market_return)
        raw[code] = {"relative": rel, "open": opn, "position": pos}
        rel_values[code] = rel
        open_values[code] = opn
    rel_rank, open_rank = _percentiles(rel_values), _percentiles(open_values)
    valid_codes = sorted(code for code, item in raw.items()
                         if _number(item.get("relative")) and _number(item.get("open")))
    sample_hash = _hash_codes(valid_codes)
    sample_changed = bool(previous and previous.get("sample_hash") != sample_hash)
    if (previous and (previous.get("model_version") != VERSION
                      or previous.get("rule_version") != config.INTRADAY_RULE_VERSION
                      or previous.get("price_basis_version") != PRICE_BASIS_VERSION)):
        # 分位变化仍标样本/版本差异；可比价格及守线事实不随版本升级清空。
        if previous.get("price_basis_version") != PRICE_BASIS_VERSION:
            prev_rows = {}
        previous = None
        sample_changed = False
    rows_by_code = {str(row.get("code")): row for row in (stocks or []) + (coverage_rows or [])}
    market_calendar = list(trading_calendar or trading_calendar_from_klines(klines))
    price_contexts = {}
    prior_snapshot_rows = ((previous_snapshot or {}).get("stocks") or []) + \
                          ((previous_snapshot or {}).get("coverage_catalog") or [])
    prior_snapshot_by_code = {str(r.get("code")): r for r in prior_snapshot_rows}
    prior_model_asof = str(((previous_snapshot or {}).get("strength_model") or {}).get("asof") or "")

    for code, row in rows_by_code.items():
        q = q_by_code.get(code) or {}
        info = quote_info.get(code) or {"at": None, "status": "本轮报价缺失", "age": None, "fresh": False}
        old = prev_rows.get(code)
        row["intraday_quote_at"] = info["at"].isoformat(sep=" ", timespec="seconds") if info["at"] else None
        row["intraday_quote_age_seconds"] = round(info["age"]) if _number(info["age"]) else None
        row["intraday_quote_status"] = info["status"]
        row["intraday_quote_fresh"] = bool(info["fresh"])
        row["intraday_observation_available"] = bool(info["fresh"])
        effective_at = info.get("effective_at") or info.get("at")
        row["intraday_judgment_at"] = effective_at.isoformat(sep=" ", timespec="seconds") if effective_at and info['fresh'] else None
        row["intraday_acquired_at"] = now.isoformat(sep=" ", timespec="seconds")
        row["intraday_price_basis_gap_pct"] = None
        row["intraday_price_basis_comparable"] = None
        row["intraday_price_basis_status"] = "待核验"
        row["intraday_price_basis_reason"] = "尚无本轮有效逐股报价"
        row["intraday_price_basis_version"] = PRICE_BASIS_VERSION
        row["intraday_price_basis_scale_factor"] = None
        row["intraday_price_basis_quote_source"] = None
        row["intraday_price_basis_history_source"] = None
        row["intraday_price_basis_reference_date"] = None
        row["intraday_price_basis_expected_date"] = None
        row["intraday_atr20"] = None
        row["intraday_atr20_status"] = "待核验"
        row["intraday_atr20_reason"] = "尚未完成21根数据核验"
        for period in (5, 10, 20):
            row[f"intraday_distance_ma{period}_pct"] = None
            row[f"intraday_distance_ma{period}_atr"] = None
            row[f"intraday_ma{period}_trigger_price"] = None
            row[f"intraday_ma{period}_current_holds"] = None
            row[f"intraday_ma{period}_day_low_breached"] = None
            row[f"intraday_ma{period}_minute_state"] = None
            row[f"intraday_ma{period}_minute_note"] = None
            row[f"intraday_ma{period}_minute_record_at"] = None
            row[f"intraday_ma{period}_current_note"] = "MA口径待核验"
            row[f"daily_ma{period}_fixed_exact"] = None
        row["quote_stale"] = not info["fresh"]
        row["intraday_components"] = {"market_relative_percentile": None,
                                       "open_return_percentile": None,
                                       "day_position_pct": None}
        row["intraday_score"] = None
        row["intraday_score_stale"] = False
        row["last_valid_intraday_score"] = None
        row["last_valid_price"] = None
        row["last_valid_change_pct"] = None
        row["last_valid_quote_at"] = None
        row["intraday_score_available_components"] = 0
        row["intraday_relative_return_pct"] = None
        row["intraday_market_return_pct"] = round(market_return, 3) if market_return is not None else None
        row["intraday_open_return_pct"] = None
        row["intraday_position_pct"] = None
        row["intraday_score_delta"] = None
        row["intraday_delta_state"] = "首轮或无可比报价"
        row["intraday_transition"] = None
        row["intraday_transition_state"] = "首轮或上轮报价无效"
        row["intraday_trade_restriction"] = None
        row["intraday_position_status"] = "待核验"
        row["intraday_risk_flags"] = []
        row["intraday_risk_level"] = "未知" if not info["fresh"] else "待核验"
        row["intraday_risk_priority"] = 0

        if info["fresh"] and code in raw:
            item = raw[code]
            pos = item.get("position")
            components = {"market_relative_percentile": rel_rank.get(code),
                          "open_return_percentile": open_rank.get(code),
                          "day_position_pct": round(pos, 2) if _number(pos) else None}
            parts = [v for v in components.values() if _number(v)]
            row["intraday_components"] = components
            row["intraday_score_available_components"] = len(parts)
            if len(parts) == 3:
                row["intraday_score"] = round(mean(parts), 2)
            row["intraday_relative_return_pct"] = round(item["relative"], 3)
            row["intraday_open_return_pct"] = round(item["open"], 3)
            row["intraday_position_pct"] = round(pos, 2) if _number(pos) else None
        elif old and len(old) >= 13:
            row["intraday_score"] = old[4] if _number(old[4]) else None
            row["intraday_score_stale"] = True
            row["last_valid_price"] = (old[14] if len(old) >= 15 and _number(old[14])
                                        else old[2] if _number(old[2]) else None)
            row["last_valid_change_pct"] = (old[15] if len(old) >= 16 and _number(old[15])
                                             else old[3] if _number(old[3]) else None)
            row["last_valid_quote_at"] = (old[13] if len(old) >= 14 and old[13]
                                           else old[1])
            row["last_valid_intraday_score"] = old[4] if _number(old[4]) else None

        # 所有盘中均线和后续近线观察共用同一份已核验的报价尺度上下文。
        if info["fresh"]:
            bars = (klines or {}).get(code) or []
            quote_day_value = info["at"].date().isoformat() if info.get("at") else day
            completed = [b for b in bars if str(b.get("date") or "") < quote_day_value]
            context = align_price_basis(q, completed, market_calendar,
                                        observation_day=day, quote_at=info.get("at"))
            price_contexts[code] = context
            row["intraday_price_basis_gap_pct"] = (round(context["gap_pct"], 3)
                                                    if _number(context.get("gap_pct")) else None)
            row["intraday_price_basis_comparable"] = context["valid"]
            row["intraday_price_basis_status"] = (
                f"可比（{context['history_basis']}→报价尺度，k={context['scale_factor']:.6f}）"
                if context["valid"] else "待核验（" + str(context.get("reason") or "价格口径未确认") + ")")
            row["intraday_price_basis_reason"] = context.get("reason")
            row["intraday_price_basis_scale_factor"] = context.get("scale_factor")
            row["intraday_price_basis_quote_source"] = context.get("quote_basis_source")
            row["intraday_price_basis_history_source"] = context.get("history_basis_source")
            row["intraday_price_basis_reference_date"] = context.get("last_history_date")
            row["intraday_price_basis_expected_date"] = context.get("expected_history_date")
            row["intraday_atr20_status"] = context.get("atr20_status") or "待核验"
            row["intraday_atr20_reason"] = context.get("atr20_reason")
            if not context["valid"]:
                trend = {"intraday_ma5": None, "intraday_ma10": None,
                         "intraday_ma20": None, "intraday_trend_ok": None,
                         "intraday_ma5_exact": None, "intraday_ma10_exact": None,
                         "intraday_ma20_exact": None,
                         "intraday_trend_failure": context.get("reason") or "价格口径待核验"}
            else:
                aligned = context["aligned_bars"]
                trend = provisional_trend(aligned, q.get("price"))
                row["intraday_atr20"] = context.get("atr20")
                for period in (5, 10, 20):
                    moving = trend.get(f"intraday_ma{period}_exact")
                    threshold = context["thresholds"].get(period)
                    fixed = context["daily_ma"].get(period)
                    exact_line = _positive(q.get("price")) and q["price"] == threshold
                    distance_delta = 0.0 if exact_line else q.get("price") - moving
                    row[f"intraday_distance_ma{period}_pct"] = (
                        (0.0 if exact_line else (q["price"] / moving - 1) * 100)
                        if _positive(q.get("price")) and _positive(moving) else None)
                    row[f"intraday_distance_ma{period}_atr"] = (
                        distance_delta / context["atr20"]
                        if _positive(q.get("price")) and _positive(moving)
                        and _positive(context.get("atr20")) else None)
                    row[f"intraday_ma{period}_trigger_price"] = threshold
                    row[f"intraday_ma{period}_current_holds"] = price_at_or_above_line(
                        q.get("price"), threshold)
                    row[f"intraday_ma{period}_day_low_breached"] = (
                        price_at_or_above_line(q.get("low"), threshold) is False
                        if _positive(q.get("low")) else None)
                    current_holds = row[f"intraday_ma{period}_current_holds"]
                    if current_holds is True:
                        row[f"intraday_ma{period}_current_note"] = (
                            f"现价守住盘中暂态MA{period}触线价")
                    elif current_holds is False:
                        row[f"intraday_ma{period}_current_note"] = (
                            f"现价低于盘中暂态MA{period}触线价")
                    else:
                        row[f"intraday_ma{period}_current_note"] = f"MA{period}当前关系待核验"
                    if row[f"intraday_ma{period}_day_low_breached"] is True:
                        row[f"intraday_ma{period}_minute_note"] = (
                            f"{row[f'intraday_ma{period}_current_note']}；日内低点曾低于"
                            f"MA{period}触线价，分钟记录待核验")
                    elif row[f"intraday_ma{period}_day_low_breached"] is False:
                        row[f"intraday_ma{period}_minute_note"] = (
                            f"{row[f'intraday_ma{period}_current_note']}；日内最低价未低于"
                            f"MA{period}触线价")
                    row[f"daily_ma{period}_fixed_exact"] = fixed
            row.update(trend)
            row.update(completed_ma_reference(context["aligned_bars"] if context["valid"] else []))
        elif old and len(old) >= 13:
            row["intraday_ma5"] = row["intraday_ma10"] = row["intraday_ma20"] = None
            row["intraday_ma5_exact"] = row["intraday_ma10_exact"] = row["intraday_ma20_exact"] = None
            row["intraday_trend_ok"] = None
            row["intraday_trend_failure"] = "报价已过期；旧口径均线不作为本轮判断"
            prior_display = prior_snapshot_by_code.get(code) or {}
            row["intraday_price_basis_status"] = "历史观察已过期（旧口径，不能用于本轮判断）"
            row["intraday_price_basis_reason"] = "逐股报价已过期"
            row["intraday_price_basis_comparable"] = False
            row["intraday_price_basis_gap_pct"] = None
            row["last_valid_intraday_ma5"] = prior_display.get("intraday_ma5")
            row["last_valid_intraday_ma10"] = prior_display.get("intraday_ma10")
            row["last_valid_intraday_ma20"] = prior_display.get("intraday_ma20")
            row["last_valid_intraday_trend_state"] = prior_display.get("intraday_trend_state")
            completed = [b for b in ((klines or {}).get(code) or [])
                         if str(b.get("date") or "") < day]
            row.update(completed_ma_reference([]))
        else:
            row.update(provisional_trend([], None, row.get("ma20")))
            row.update(completed_ma_reference([]))
            if not info["fresh"]:
                prior_display = prior_snapshot_by_code.get(code) or {}
                row["intraday_price_basis_comparable"] = None
                row["intraday_price_basis_status"] = "报价过期或缺失，本轮价格口径未核验"
                row["intraday_price_basis_reason"] = info.get("status") or "逐股报价缺失"
                row["last_valid_intraday_ma5"] = prior_display.get("intraday_ma5")
                row["last_valid_intraday_ma10"] = prior_display.get("intraday_ma10")
                row["last_valid_intraday_ma20"] = prior_display.get("intraday_ma20")
                row["last_valid_intraday_trend_state"] = prior_display.get("intraday_trend_state")
                row["last_valid_quote_at"] = (prior_display.get("intraday_quote_at")
                                               or prior_display.get("last_valid_quote_at"))

        if info["fresh"]:
            flags = row["intraday_risk_flags"]
            row["intraday_position_status"] = (
                "高低价相同，区间位置不适用"
                if q.get("high") == q.get("low") else "有效")
            limit = q.get("limit_pct") or config.board_of(code)[2]
            drop = _drop_risk(q.get("change_pct"), limit) if _number(q.get("change_pct")) else None
            if drop:
                flags.append(drop)
                row["intraday_risk_priority"] = max(row["intraday_risk_priority"], 100 if drop == "接近跌停" else 80)
            lock = _limit_lock(q)
            if lock:
                row["intraday_trade_restriction"] = lock
                row["intraday_position_status"] = lock + "，区间位置不适用"
                flags.append(lock)
                row["intraday_risk_priority"] = max(row["intraday_risk_priority"], 90 if lock == "一字跌停" else 45)
            high, low, price = q.get("high"), q.get("low"), q.get("price")
            limit_up = q.get("limit_up")
            limit_touch_tolerance = config.INTRADAY_RISK["limit_price_tolerance_pct"] / 100
            if (_positive(limit_up) and _positive(high) and _positive(price)
                    and high >= limit_up * (1 - limit_touch_tolerance)
                    and price < limit_up * (1 - limit_touch_tolerance)):
                flags.append("触板未封")
                row["intraday_risk_priority"] = max(row["intraday_risk_priority"], 55)
            day_range = ((high / low - 1) * 100 if _positive(high) and _positive(low) else 0.0)
            from_high = ((price / high - 1) * 100 if _positive(price) and _positive(high) else None)
            row["intraday_drawdown_from_high_pct"] = round(from_high, 2) if _number(from_high) else None
            if (_number(from_high) and day_range >= config.INTRADAY_RISK["min_day_range_pct"]
                    and from_high <= -config.INTRADAY_RISK["high_pullback_min_pct"]
                    and _number(row.get("intraday_position_pct"))
                    and row["intraday_position_pct"] <= config.INTRADAY_RISK["weak_day_position_max"] * 100):
                flags.append("明显冲高回落")
                row["intraday_risk_priority"] = max(row["intraday_risk_priority"], 65)
            ma10i = row.get("intraday_ma10_exact")
            ma20i = row.get("intraday_ma20_exact")
            ma10_threshold = row.get("intraday_ma10_trigger_price")
            ma20_threshold = row.get("intraday_ma20_trigger_price")
            basis_valid = row.get("intraday_price_basis_comparable") is True
            if basis_valid and price_at_or_above_line(price, ma10_threshold) is False:
                flags.append("现价失守盘中MA10")
                row["intraday_risk_priority"] = max(row["intraday_risk_priority"], 60)
            if basis_valid and price_at_or_above_line(price, ma20_threshold) is False:
                flags.append("现价失守盘中MA20")
                row["intraday_risk_priority"] = max(row["intraday_risk_priority"], 85)
            atr = row.get("intraday_atr20")
            dist = ((price - ma10i) / atr
                    if basis_valid and _positive(price) and _positive(ma10i) and _positive(atr)
                    else None)
            row["live_dist_atr"] = round(dist, 3) if _number(dist) else None
            ma5i = row.get("intraday_ma5_exact")
            heat_dist = ((price - ma5i) / atr
                         if basis_valid and _positive(price) and _positive(ma5i) and _positive(atr) else None)
            row["live_overheat_dist_atr"] = round(heat_dist, 3) if _number(heat_dist) else None
            row["overheated"] = (bool(heat_dist > config.INTRADAY_RISK["overheat_dist_atr"])
                                  if _number(heat_dist) else None)
            if row["overheated"] is True:
                flags.append("现价距盘中MA5过远，位置偏热")
                row["intraday_risk_priority"] = max(row["intraday_risk_priority"], 35)
        else:
            row["intraday_drawdown_from_high_pct"] = None
            row["live_dist_atr"] = None
            row["live_overheat_dist_atr"] = None
            row["overheated"] = None

        serious = any(f in row["intraday_risk_flags"] for f in
                      ("接近跌停", "大幅下跌", "明显冲高回落", "现价失守盘中MA20", "一字跌停"))
        ma10_lost = "现价失守盘中MA10" in row["intraday_risk_flags"]
        basis_valid = row.get("intraday_price_basis_comparable") is True
        row["intraday_serious_weakness"] = (True if serious or ma10_lost else
                                             False if basis_valid else None)
        if any(flag in row["intraday_risk_flags"] for flag in ("接近跌停", "一字跌停")):
            row["intraday_risk_level"] = "严重"
        elif any(flag in row["intraday_risk_flags"] for flag in ("大幅下跌", "现价失守盘中MA20")):
            row["intraday_risk_level"] = "高"
        elif any(flag in row["intraday_risk_flags"] for flag in
                 ("明显冲高回落", "现价失守盘中MA10", "现价距盘中MA5过远，位置偏热")):
            row["intraday_risk_level"] = "中"
        elif row["intraday_risk_flags"]:
            row["intraday_risk_level"] = "提示"
        elif info["fresh"] and (not basis_valid or row.get("intraday_atr20") is None):
            row["intraday_risk_level"] = "待核验"
        elif info["fresh"]:
            row["intraday_risk_level"] = "低"
        prior_snapshot_row = prior_snapshot_by_code.get(code)
        if session in ("尾盘", "已收盘") and prior_snapshot_row and prior_model_asof < day:
            prior_daily_value = prior_snapshot_row.get("trend_online")
            prior_daily_asof = prior_model_asof
        else:
            prior_daily_value = row.get("trend_online")
            prior_daily_asof = row.get("signal_date") or row.get("signal_day")
        # 完成日线输出0/1，旧快照和部分调用使用布尔值；未知仍不算在线。
        prior_daily = prior_daily_value == 1
        row["intraday_prior_daily_trend_online"] = prior_daily_value
        row["intraday_prior_daily_asof"] = prior_daily_asof
        current_temp = row.get("intraday_trend_ok") is True
        if not info["fresh"]:
            prior_display = prior_snapshot_by_code.get(code) or {}
            row["last_valid_intraday_trend_state"] = (
                prior_display.get("intraday_trend_state")
                or (old[16] if old and len(old) >= 17 and old[16]
                    else old[5] if old and len(old) >= 6 else None))
            row["intraday_trend_state"] = "均线待核验（" + info["status"] + "；历史观察已过期）"
        elif row.get("intraday_trend_ok") is None:
            why = row.get("intraday_price_basis_reason") or row.get("intraday_trend_failure") or "均线数据不足"
            row["intraday_trend_state"] = "均线待核验（" + str(why) + ")"
        elif prior_daily and current_temp:
            row["intraday_trend_state"] = "趋势保持"
        elif prior_daily and not current_temp:
            row["intraday_trend_state"] = "盘中转弱"
        elif not prior_daily and current_temp:
            row["intraday_trend_state"] = "盘中初步转强·待收盘确认"
        else:
            row["intraday_trend_state"] = "趋势未成立"
        if info["fresh"] and row.get("intraday_trend_failure") and prior_daily and not current_temp:
            row["intraday_trend_state"] += "（" + row["intraday_trend_failure"] + "）"

        old_quote_at = parse_quote_timestamp(intraday_path.effective(old)) if old and len(old) > 1 else None
        quote_advanced = bool(info["fresh"] and old and len(old) >= 13 and intraday_path.observed(old)
                              and effective_at and old_quote_at and effective_at > old_quote_at)
        quote_gap = (intraday_path.gap_seconds(old_quote_at.isoformat(sep=' '),effective_at.isoformat(sep=' '))
                     if quote_advanced else None)
        if not info["fresh"] and old:
            row["intraday_delta_state"] = "报价缺失或过期，停止比较"
        elif old and info["fresh"] and intraday_path.observed(old) and not quote_advanced:
            row["intraday_delta_state"] = "报价时间未前进，停止新比较"
            row["intraday_transition_state"] = "报价时间未前进，未判断收复或失守"
        elif old and quote_advanced and observation_session:
            if quote_gap is not None and quote_gap <= 900:
                old_score = old[4]
                if _number(old_score) and _number(row.get("intraday_score")):
                    row["intraday_score_delta"] = round(row["intraday_score"] - old_score, 2)
                    row["intraday_delta_state"] = (
                        "相对评分变化（比较样本变化，谨慎解读）" if sample_changed
                        else "相对评分变化（同口径可比）")
                else:
                    row["intraday_delta_state"] = "两轮盘中分不完整，停止分数比较"
            else:
                row["intraday_delta_state"] = "扫描间隔超过15分钟，不比较相对评分"
            if row.get("intraday_price_basis_comparable") is True and quote_gap is not None and 0 <= quote_gap <= 900:
                transition, transition_state = _transition_from_previous(
                            old, effective_at, q.get("price"), row.get("intraday_ma10_trigger_price"))
            else:
                transition, transition_state = None, "价格口径待核验或采样间隔过长，未生成收复或失守事件"
            row["intraday_transition"] = transition
            row["intraday_transition_state"] = transition_state or "报价已前进，本轮未观察到MA10收复或失守"
        elif old and quote_advanced and session == "已收盘":
            row["intraday_delta_state"] = "收盘确认阶段，盘中相对评分不再更新"
            row["intraday_transition_state"] = "正式收盘判断单独保存，不生成新的盘中转换事件"
        elif old:
            if len(old) >= 13 and not intraday_path.observed(old):
                row["intraday_delta_state"] = "上轮报价无效，停止比较"
                row["intraday_transition_state"] = "上轮报价无效，未判断收复或失守"
            else:
                row["intraday_delta_state"] = "上轮间隔过长或日期不可比"
                row["intraday_transition_state"] = "上轮间隔过长或日期不可比"

        score = row.get("intraday_score")
        hist_base = bool(row.get("persistent_strong") or
                         (_number(row.get("stock_strength_percentile"))
                          and row["stock_strength_percentile"] >= 75
                          and _number(row.get("ret20")) and row["ret20"] > 0))
        if "daily_attack_tier" in row:
            # 新模型的历史基础必须有实际进攻；相对分位不能替代绝对涨幅。
            hist_base = row["daily_attack_tier"] in ("A", "B")
        row["historical_strength_base"] = hist_base
        row["historical_pullback_shape"] = row.get("touch_state") in config.CONFIRMED_PULLBACK_STATES
        row["daily_motion"] = row.get("stock_strength_motion")
        has_severe_risk = any(f in row["intraday_risk_flags"] for f in
                              ("接近跌停", "大幅下跌", "明显冲高回落", "现价失守盘中MA20", "一字跌停"))
        price, open_price = q.get("price"), q.get("open")
        relative = row.get("intraday_relative_return_pct")
        positive_day = _number(q.get("change_pct")) and q["change_pct"] > 0
        beating_market = _number(relative) and relative > 0
        holds_open = _positive(price) and _positive(open_price) and price >= open_price
        basis_valid = row.get("intraday_price_basis_comparable") is True
        current_trend_qualification = (
            True if row.get("intraday_trend_ok") is True else
            False if row.get("intraday_trend_ok") is False else
            "待核验（" + str(row.get("intraday_price_basis_reason") or "均线数据不足") + ")")
        if has_severe_risk or row.get("intraday_trade_restriction") or "触板未封" in row["intraday_risk_flags"]:
            risk_qualification = False
        elif not basis_valid:
            risk_qualification = "待核验（均线风险判断未确认）"
        else:
            risk_qualification = not has_severe_risk and not ma10_lost
        qualification = {
            "正常盘中时段": normal_session,
            "报价有效": info["fresh"],
            "历史强势基础": hist_base,
            "上一完成日日线趋势成立": prior_daily,
            "当前暂态趋势成立": current_trend_qualification,
            "当日涨幅为正": positive_day,
            "跑赢主板等权基准": beating_market,
            "现价不低于开盘价": holds_open,
            "三项盘中评分完整": (score is not None
                                and row.get("intraday_score_available_components") == 3),
            "当前风险约束通过": risk_qualification,
        }
        row["current_strong_qualification"] = qualification
        row["current_strong_missing"] = [label for label, passed in qualification.items() if passed is not True]
        row["current_strong_candidate"] = all(passed is True for passed in qualification.values())
        holds_intraday_ma10 = (
            True if basis_valid and price_at_or_above_line(
                price, row.get("intraday_ma10_trigger_price")) is True else
            False if basis_valid else
            "待核验（" + str(row.get("intraday_price_basis_reason") or "MA10口径未确认") + ")")
        no_severe_weakness = (True if row.get("intraday_serious_weakness") is False else
                              False if row.get("intraday_serious_weakness") is True else
                              "待核验（MA均线风险未确认）")
        not_overheated = (True if row.get("overheated") is False else
                          False if row.get("overheated") is True else
                          "待核验（ATR距离未确认）")
        pullback_qualification = {
            "正常盘中时段": normal_session, "报价有效": info["fresh"],
            "完成日已确认回踩反弹或回踩后上行": row["historical_pullback_shape"],
            "现价守住盘中MA10": holds_intraday_ma10,
            "无严重转弱": no_severe_weakness,
            "位置未过热": not_overheated,
            "无成交限制": not row.get("intraday_trade_restriction"),
            "未触板未封": "触板未封" not in row["intraday_risk_flags"],
        }
        row["current_pullback_qualification"] = pullback_qualification
        row["current_pullback_missing"] = [k for k, v in pullback_qualification.items() if v is not True]
        row["current_pullback_candidate"] = all(v is True for v in pullback_qualification.values())
        row["entry_watch"] = row["current_pullback_candidate"]
        startup_qualification = {
            "正常盘中时段": normal_session,
            "报价有效": info["fresh"],
            # 未知不等于未成立；不能把缺少历史判断的股票称为新转强。
            "上一完成日日线趋势明确未成立": prior_daily_value == 0,
            "当前暂态趋势成立": current_trend_qualification,
            "当日涨幅为正": positive_day,
            "跑赢主板等权基准": beating_market,
            "现价不低于开盘价": holds_open,
            "三项盘中评分完整": qualification["三项盘中评分完整"],
            "盘中分达到观察门槛": _number(score) and score >= config.INTRADAY["startup_score_min"],
            "当前风险约束通过": qualification["当前风险约束通过"],
        }
        row["startup_qualification"] = startup_qualification
        row["startup_missing"] = [label for label, passed in startup_qualification.items() if passed is not True]
        row["startup_candidate"] = all(passed is True for passed in startup_qualification.values())
        # 高分但未满足强势/转强资格，只描述活跃；不冒充趋势启动。
        row["intraday_active_candidate"] = bool(
            normal_session and info["fresh"] and positive_day and beating_market and holds_open
            and qualification["三项盘中评分完整"]
            and startup_qualification["盘中分达到观察门槛"]
            and qualification["当前风险约束通过"] is True
            and not row["current_strong_candidate"] and not row["startup_candidate"])
        open_return = row.get("intraday_open_return_pct")
        row["intraday_repair_candidate"] = bool(
            normal_session and info["fresh"] and qualification["三项盘中评分完整"]
            and _number(open_return) and open_return > 0
            and (not positive_day or not beating_market)
            and not has_severe_risk and not row.get("intraday_trade_restriction")
            and "触板未封" not in row["intraday_risk_flags"])
        row["intraday_phase_status"] = session or "阶段未知"
        row["intraday_observation_state"] = _observation_state(
            row, q, prior_daily, current_temp)
        if session == "午间休市" and info["fresh"]:
            observed_row = dict(row)
            observed_row["current_strong_candidate"] = all(v is True for k,v in qualification.items() if k != "正常盘中时段")
            observed_row["startup_candidate"] = all(v is True for k,v in startup_qualification.items() if k != "正常盘中时段")
            observed_row["intraday_active_candidate"] = bool(positive_day and beating_market and holds_open
                and qualification['三项盘中评分完整'] and startup_qualification['盘中分达到观察门槛']
                and qualification['当前风险约束通过'] is True)
            row["intraday_observation_state"] = _observation_state(observed_row, q, prior_daily, current_temp)
        row["turn_weak_repair_candidate"] = bool(
            normal_session and info["fresh"] and hist_base
            and (row["intraday_observation_state"] in
                 ("相对抗跌", "盘中修复", "今日转弱", "分歧观察")
                 or row.get("intraday_transition")))
        if row.get("trade_status") == "trade_recovered_wait_daily":
            # 复牌后的有效报价只能证明重新成交，不能绕过完成日线窗口进入盘中候选。
            for key, missing_key in (("current_strong_qualification", "current_strong_missing"),
                                     ("current_pullback_qualification", "current_pullback_missing"),
                                     ("startup_qualification", "startup_missing")):
                row[key]["停牌后完成日线重新对齐"] = False
                row[missing_key].append("停牌后完成日线重新对齐")
            for key in ("current_strong_candidate", "current_pullback_candidate",
                        "startup_candidate", "intraday_active_candidate",
                        "intraday_repair_candidate", "turn_weak_repair_candidate", "entry_watch"):
                row[key] = False
            row["intraday_observation_state"] = "恢复成交，日线待对齐"
        if row.get("stock_strength_score") is not None:
            row["daily_strength_status"] = "已评分"
        elif not row.get("coverage_only"):
            row["daily_strength_status"] = "趋势可核验、强度待评分"

        if auction_session:
            at = parse_quote_timestamp(q.get("quote_at") or q.get("ts"), now)
            row["auction_observation"] = {
                "quote_at": at.isoformat(sep=" ", timespec="seconds") if at else None,
                "price": q.get("price"), "change_pct": q.get("change_pct"),
                "status": ("盘前观察，与正常盘中排名分开" if session == "盘前"
                           else "集合竞价观察，与正常盘中排名分开")}
        else:
            row["auction_observation"] = None

        if frozen_session:
            last_at = old[13] if old and len(old) >= 14 else (old[1] if old else None)
            if session == "午间休市":
                row["intraday_trend_state"] = ("午间休市，保留上午最后有效判断"
                                                  if last_at else "午间休市，尚无上午有效观察")
                row["intraday_quote_status"] = ("午间休市；上午最后有效报价 " + str(last_at)
                                                 if last_at else "午间休市；尚无上午有效报价")
            elif session == "盘前":
                row["intraday_trend_state"] = ("盘前观察，沿用最近交易日收盘结果"
                                                  if last_at else "盘前观察，尚无最近有效结果")
            elif session == "集合竞价":
                row["intraday_trend_state"] = ("竞价观察，沿用最近交易日收盘结果"
                                                  if last_at else "竞价观察，尚无最近有效结果")
            else:
                row["intraday_trend_state"] = ("非交易日，显示最近交易日结果"
                                                  if last_at else "非交易日，暂无历史盘中结果")
            row["intraday_quote_fresh"] = False
            row["intraday_score_stale"] = _number(row.get("intraday_score"))
            row["intraday_score_delta"] = None
            row["intraday_transition"] = None
            row["intraday_delta_state"] = row["intraday_trend_state"]
            row["intraday_observation_state"] = row["intraday_trend_state"]
            row["current_strong_candidate"] = False
            row["current_pullback_candidate"] = False
            row["startup_candidate"] = False
            row["intraday_active_candidate"] = False
            row["intraday_repair_candidate"] = False
            row["turn_weak_repair_candidate"] = False

        if session == "午间休市":
            # 收市状态照常计算并可展示；休盘期间不发出可交易候选。
            if info['fresh']:
                row['last_valid_quote_at'] = row['intraday_judgment_at']
                row['last_valid_intraday_score'] = row['intraday_score']
                row['last_valid_price'], row['last_valid_change_pct'] = q.get('price'), q.get('change_pct')
                row['last_valid_intraday_trend_state'] = row['intraday_trend_state']
                row['intraday_quote_status'] = '午间收市判断，截至11:30；源刷新 '+row['intraday_quote_at'][11:19]
            row['intraday_quote_fresh'] = False
            row['intraday_score_stale'] = False
            for key in ('current_strong_candidate','current_pullback_candidate','startup_candidate',
                        'intraday_active_candidate','intraday_repair_candidate','turn_weak_repair_candidate','entry_watch'):
                row[key] = False

        for flag in row["intraday_risk_flags"]:
            if flag not in row.setdefault("risk_notes", []):
                row["risk_notes"].append(flag)

    # 行业当日表现单独展示，剔除自身；覆盖不足时保持未知。
    by_industry = {}
    for code, row in rows_by_code.items():
        q = q_by_code.get(code) or {}
        if quote_info.get(code, {}).get("fresh") and _number(q.get("change_pct")) and row.get("primary_industry"):
            by_industry.setdefault(row["primary_industry"], []).append((code, q["change_pct"]))
    for code, row in rows_by_code.items():
        group = by_industry.get(row.get("primary_industry")) or []
        peers = [change for peer_code, change in group if peer_code != code]
        if len(peers) >= config.INTRADAY["min_industry_peers"] and quote_info.get(code, {}).get("fresh"):
            industry_mean = mean(peers)
            row["industry_intraday_change_pct"] = round(industry_mean, 3)
            row["industry_intraday_excess_pct"] = round(q_by_code[code]["change_pct"] - industry_mean, 3)
            row["industry_intraday_peer_count"] = len(peers)
        else:
            row["industry_intraday_change_pct"] = None
            row["industry_intraday_excess_pct"] = None
            row["industry_intraday_peer_count"] = len(peers)

    valid_count = sum(row.get('intraday_quote_fresh') is True for row in rows_by_code.values())
    score_codes = sorted(code for code, row in rows_by_code.items()
                         if row.get("intraday_score") is not None
                         and row.get("intraday_score_available_components") == 3
                         and row.get("intraday_observation_available") is True)
    quote_times = [info["at"] for info in quote_info.values()
                   if info["fresh"] and info.get("at")]
    if len(quote_times) < len(reference):
        for code, row in rows_by_code.items():
            stamp = row.get("last_valid_quote_at")
            if stamp:
                parsed = parse_quote_timestamp(stamp)
                if parsed:
                    quote_times.append(parsed)
    summary = {
        "version": VERSION, "rule_version": config.INTRADAY_RULE_VERSION,
        "asof": (previous.get("day") if session == "非交易日" and previous else day),
        "session": session or "阶段未知", "normal_scoring_session": normal_session,
        "max_quote_age_seconds": config.INTRADAY["max_quote_age_seconds"],
        "max_quote_future_seconds": config.INTRADAY["max_quote_future_seconds"],
        "phase_status": ("盘前观察，沿用最近收盘结果" if session == "盘前" else
                         "集合竞价观察，与盘中榜分开" if session == "集合竞价" else
                         "午间收市判断，截至11:30；每次获取均留痕" if session == "午间休市" else
                         "非交易日，展示最近交易日结果" if session == "非交易日" else
                         "盘中有效报价" if normal_session else
                         "收盘确认阶段" if session in ("尾盘", "已收盘") else "阶段数据待核验"),
        "captured_at": now.isoformat(sep=" ", timespec="seconds"),
        "reference_pool_count": len(reference), "reference_pool_hash": pool_hash,
        "valid_quote_count": valid_count,
        "observation_valid_count": sum(row.get('intraday_observation_available') is True for row in rows_by_code.values()),
        "valid_quote_coverage_pct": round(valid_count / len(reference) * 100, 2) if reference else 0.0,
        "complete_score_count": len(score_codes), "score_sample_hash": _hash_codes(score_codes),
        "price_basis_mismatch_count": sum(
            "超过" in str(row.get("intraday_price_basis_reason") or "")
            for row in rows_by_code.values()),
        "price_basis_unknown_count": sum(
            row.get("intraday_price_basis_comparable") is not True
            for row in rows_by_code.values()),
        "price_basis_version": PRICE_BASIS_VERSION,
        "latest_valid_quote_at": (max(quote_times).isoformat(sep=" ", timespec="seconds")
                                   if quote_times else None),
        "latest_judgment_at": max((row.get('intraday_judgment_at') or row.get('last_valid_quote_at') or ''
                                    for row in rows_by_code.values()), default='') or None,
        "mainboard_benchmark_count": len(mainboard),
        "mainboard_equal_weight_change_pct": round(market_return, 3) if market_return is not None else None,
        "ranked_sample_hash": sample_hash,
        "sample_changed_since_previous": sample_changed,
        "refresh_seconds": config.RUNTIME["refresh_seconds"],
        "score_method": "三项完整时等权：当日相对主板等权涨幅分位、开盘后涨幅分位、日内区间位置；缺一项不生成完整分",
        "risk_thresholds": dict(config.INTRADAY_RISK),
    }
    summary["_price_contexts"] = price_contexts
    summary["_history_context"] = history
    return summary


def save_observation(snap):
    """追加本轮真实报价和状态；本地重建不写入实时观察历史。"""
    if snap.get("mode") == "local-rebuild":
        return None
    meta = snap.get("intraday_model") or {}
    session = snap.get("session") or ""
    scan_at = snap.get("scan_completed_at") or snap.get("generated_at")
    day = (snap.get('quote_capture_at') or scan_at or '')[:10] or meta.get('asof')
    if not day or not scan_at:
        return None
    combined = (snap.get("stocks") or []) + (snap.get("coverage_catalog") or [])
    by_code = {}
    for row in combined:
        code = str(row.get("code") or "")
        if not code:
            continue
        fresh = row.get("intraday_quote_fresh") is True
        last_valid_quote_at = row.get("intraday_quote_at") if fresh else row.get("last_valid_quote_at")
        last_valid_price = (row.get("price") if fresh else row.get("last_valid_price"))
        last_valid_change = (row.get("change_pct") if fresh else row.get("last_valid_change_pct"))
        last_valid_trend = (row.get("intraday_trend_state") if fresh
                            else row.get("last_valid_intraday_trend_state"))
        by_code[code] = [code, row.get("intraday_quote_at"), row.get("price"),
                         row.get("change_pct"), row.get("intraday_score"),
                         row.get("intraday_trend_state"), row.get("intraday_risk_level"),
                         row.get("intraday_ma5"), row.get("intraday_ma10_exact"),
                         row.get("intraday_ma20"), row.get("intraday_trend_ok"),
                         row.get("stock_strength_score"), fresh,
                         last_valid_quote_at, last_valid_price, last_valid_change, last_valid_trend]
        by_code[code].extend([
            row.get("intraday_score_available_components"),
            bool(row.get("current_strong_candidate")),
            bool(row.get("startup_candidate")),
            bool(row.get("current_pullback_candidate")),
            bool(row.get("turn_weak_repair_candidate")),
            row.get("intraday_observation_state"),
            row.get("intraday_transition"),
            row.get("intraday_relative_return_pct"),
            row.get("intraday_open_return_pct"),
            row.get("intraday_quote_status"),
            list(row.get("intraday_risk_flags") or []),
            row.get("intraday_price_basis_comparable") is True,
            row.get("intraday_ma10_trigger_price"),
        ])
        # 前30列保持旧合同。新列补入判断时间、可用性、进攻与资金，午休也落盘。
        by_code[code].extend([row.get('intraday_judgment_at'), row.get('intraday_observation_available') is True,
                             row.get('intraday_acquired_at'), row.get('live_attack_score'),
                             row.get('live_attack_tier'), row.get('live_attack_stage'),
                             row.get('attack_observation_candidate') is True, row.get('live_attack_fund')])
        # 每轮各自的均线边界及ATR；既有列不移动，旧记录可读。
        by_code[code].extend([row.get('intraday_atr20'), row.get('intraday_ma5_trigger_price'),
                             row.get('intraday_ma20_trigger_price')])
    rows = sorted(by_code.values(), key=lambda r: r[0])
    candidate_ids = {
        key: sorted(code for code, values in by_code.items() if len(values) > index and values[index])
        for key, index in (("current_strong", 18), ("startup", 19),
                           ("current_pullback", 20), ("turn_weak_repair", 21))
    }
    record = {"day": day, "scan_at": scan_at, "session": session,
              "model_version": meta.get("version") or VERSION,
              "rule_version": meta.get("rule_version") or config.INTRADAY_RULE_VERSION,
              "price_basis_version": meta.get("price_basis_version") or PRICE_BASIS_VERSION,
              "reference_pool_hash": meta.get("reference_pool_hash"),
              "sample_hash": meta.get("ranked_sample_hash"),
              "score_sample_hash": meta.get("score_sample_hash"),
              "candidate_ids": candidate_ids,
              "candidate_hashes": {key: _hash_codes(codes) for key, codes in candidate_ids.items()},
              "reference_pool_count": meta.get("reference_pool_count"),
              "valid_quote_count": meta.get("valid_quote_count"), "rows": rows}
    previous = _latest_record(day)
    pair_summaries = []
    if previous:
        pair_summary = _summarize_pair(previous, record)
        if pair_summary:
            pair_summaries.append(pair_summary)
    prior_records = []
    try:
        history_path = HISTORY_DIR / f"{day}.jsonl"
        if history_path.exists():
            with history_path.open("rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 2_000_000))
                chunk = f.read().decode("utf-8", errors="replace")
            history_lines = [line for line in chunk.splitlines() if line.strip()]
            if len(history_lines) >= 2 and size > 2_000_000:
                history_lines = history_lines[1:]
            prior_records = [json.loads(line) for line in history_lines[-30:]]
    except (OSError, ValueError):
        prior_records = []
    longer_anchors = set()
    try:
        if PAIR_HISTORY_PATH.exists():
            for line in PAIR_HISTORY_PATH.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                saved_pair = json.loads(line)
                if saved_pair.get("day") == day and saved_pair.get("horizon") == "longer_intraday":
                    longer_anchors.add(saved_pair.get("from"))
    except (OSError, ValueError):
        longer_anchors = set()
    for anchor in prior_records:
        if anchor.get("scan_at") in longer_anchors:
            continue
        t0 = parse_quote_timestamp(anchor.get("scan_at"))
        t1 = parse_quote_timestamp(record.get("scan_at"))
        gap = (t1 - t0).total_seconds() if t0 and t1 else 0
        if 25 * 60 <= gap <= 45 * 60:
            longer = _summarize_pair(anchor, record, horizon="longer_intraday")
            if longer:
                pair_summaries.append(longer)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / f"{day}.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    if pair_summaries:
        PAIR_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PAIR_HISTORY_PATH.open("a", encoding="utf-8", newline="\n") as f:
            for pair_summary in pair_summaries:
                f.write(json.dumps(pair_summary, ensure_ascii=False, separators=(",", ":")) + "\n")
    return path


def _average_ranked_return(entries, signal_key, top_share=0.10):
    eligible = [(row, future) for row, future in entries
                if _number(row.get(signal_key)) and _number(future)]
    if len(eligible) < 20:
        return None, len(eligible)
    eligible.sort(key=lambda item: item[0][signal_key], reverse=True)
    n = max(1, int(len(eligible) * top_share))
    return mean(value for _, value in eligible[:n]), len(eligible)


def save_close_observation(snap, previous_snapshot, confirmation=None):
    """保存当日最后有效盘中信号到正式收盘的单日对照，写入后保持不变。"""
    confirmation = confirmation or snap.get("intraday_close_confirmation") or {}
    day = confirmation.get("asof")
    if not day or not confirmation.get("rows"):
        return None
    path = CLOSE_HISTORY_DIR / f"{day}.json"
    if path.exists():
        return path
    meta = previous_snapshot.get("intraday_model") or {}
    if (meta.get("asof") != day or meta.get("version") != VERSION
            or meta.get("rule_version") != config.INTRADAY_RULE_VERSION):
        return None
    previous_rows = {str(row.get("code")): row for row in
                     (previous_snapshot.get("stocks") or []) +
                     (previous_snapshot.get("coverage_catalog") or [])}
    closing_rows = {str(row.get("code")): row for row in
                    (snap.get("stocks") or []) + (snap.get("coverage_catalog") or [])}
    entries = []
    candidate_ids = {key: [] for key in ("current_strong", "startup", "current_pullback", "turn_weak_repair")}
    for code, old in previous_rows.items():
        closed = closing_rows.get(code)
        if not closed or old.get("intraday_quote_fresh") is not True:
            continue
        price = closed.get("signal_close")
        if not _positive(price):
            price = closed.get("close")
        if not _positive(price):
            continue
        ma10 = closed.get("ma10")
        record = {
            "code": code, "intraday_quote_at": old.get("intraday_quote_at"),
            "intraday_price": old.get("price"), "intraday_change_pct": old.get("change_pct"),
            "intraday_score": old.get("intraday_score"),
            "intraday_score_available_components": old.get("intraday_score_available_components"),
            "close_confirmation": ((confirmation.get("rows") or {}).get(code) or {}).get("confirmation"),
            "intraday_trend_state": old.get("intraday_trend_state"),
            "intraday_relative_return_pct": old.get("intraday_relative_return_pct"),
            "intraday_open_return_pct": old.get("intraday_open_return_pct"),
            "daily_score": old.get("stock_strength_score"),
            "close_price": price, "close_return_pct": (
                (price / old.get("price") - 1) * 100 if _positive(old.get("price")) else None),
            "close_trend_online": bool(closed.get("trend_online")),
            "close_below_ma10": bool(_positive(ma10) and price < ma10),
            "intraday_risk_flags": list(old.get("intraday_risk_flags") or []),
            "candidate_identity": {
                "current_strong": bool(old.get("current_strong_candidate")),
                "startup": bool(old.get("startup_candidate")),
                "current_pullback": bool(old.get("current_pullback_candidate")),
                "turn_weak_repair": bool(old.get("turn_weak_repair_candidate")),
            },
        }
        entries.append(record)
        for key, active in record["candidate_identity"].items():
            if active:
                candidate_ids[key].append(code)
    if not entries:
        return None
    data = {
        "day": day, "horizon": "close", "model_version": meta.get("version"),
        "rule_version": meta.get("rule_version"),
        "reference_pool_hash": meta.get("reference_pool_hash"),
        "sample_hash": meta.get("ranked_sample_hash"),
        "score_sample_hash": meta.get("score_sample_hash"),
        "signal_scan_at": confirmation.get("previous_scan_at"),
        "close_scan_at": snap.get("scan_completed_at") or snap.get("scan_started_at"),
        "candidate_ids": candidate_ids, "entries": entries,
    }
    CLOSE_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    config.atomic_write_text(path, json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    return path


def _spearman(x, y):
    if len(x) < 20:
        return None
    rx = _percentiles({str(i): v for i, v in enumerate(x)})
    ry = _percentiles({str(i): v for i, v in enumerate(y)})
    ax = [rx[str(i)] for i in range(len(x))]
    ay = [ry[str(i)] for i in range(len(y))]
    mx, my = mean(ax), mean(ay)
    den = math.sqrt(sum((a - mx) ** 2 for a in ax) * sum((b - my) ** 2 for b in ay))
    return round(sum((a - mx) * (b - my) for a, b in zip(ax, ay)) / den, 4) if den else None


def _summarize_pair(left, right, horizon="next_scan"):
    """将相邻真实扫描压成小型统计记录，避免每轮重读所有股票明细历史。"""
    if (not left or not right or left.get("day") != right.get("day")
            or left.get("reference_pool_hash") != right.get("reference_pool_hash")
            or left.get("model_version") != right.get("model_version")
            or left.get("rule_version") != right.get("rule_version")):
        return None
    t0, t1 = parse_quote_timestamp(left.get("scan_at")), parse_quote_timestamp(right.get("scan_at"))
    gap = (t1 - t0).total_seconds() if t0 and t1 else 0
    if (not t0 or not t1 or gap <= 0
            or (horizon == "next_scan" and gap > 900)
            or (horizon == "longer_intraday" and not 25 * 60 <= gap <= 45 * 60)):
        return None
    prev = _record_rows(left)
    entries = []
    for row in right.get("rows", []):
        old = prev.get(row[0])
        if not old or len(old) < 28 or len(row) < 28 or old[12] is not True or row[12] is not True:
            continue
        old_quote_at = parse_quote_timestamp(old[1])
        new_quote_at = parse_quote_timestamp(row[1])
        if (not old_quote_at or not new_quote_at or new_quote_at <= old_quote_at
                or not _positive(old[2]) or not _positive(row[2])
                or not _number(old[4]) or old[17] != 3
                or not _number(old[3]) or not _number(old[11])):
            continue
        forward = (row[2] / old[2] - 1) * 100
        entries.append(({"intraday_score": old[4], "change_pct": old[3],
                         "daily_score": old[11]}, forward))
    if len(entries) < 20:
        return None
    signals = {}
    for key in ("intraday_score", "change_pct", "daily_score"):
        eligible = [(row[key], future) for row, future in entries
                    if _number(row.get(key)) and _number(future)]
        if len(eligible) < 20:
            continue
        values = [v for v, _ in eligible]
        forward = [r for _, r in eligible]
        ordered = sorted(eligible, key=lambda x: x[0], reverse=True)
        top_n = max(1, int(len(ordered) * 0.10))
        signals[key] = {
            "n": len(eligible),
            "spearman": _spearman(values, forward),
            "top10_n": top_n,
            "top10_mean_pct": mean(v for _, v in ordered[:top_n]),
            "mean_pct": mean(forward),
        }
    churn = {}
    for view in ("current_strong", "startup", "current_pullback", "turn_weak_repair"):
        a = set((left.get("candidate_ids") or {}).get(view) or [])
        b = set((right.get("candidate_ids") or {}).get(view) or [])
        union = a | b
        churn[view] = {"previous": len(a), "current": len(b),
                       "changed": len(a ^ b),
                       "turnover_pct": round(len(a ^ b) / len(union) * 100, 2) if union else 0.0}
    strong = set((left.get("candidate_ids") or {}).get("current_strong") or [])
    right_rows = _record_rows(right)
    strong_rows = [right_rows[c] for c in strong if c in right_rows and len(right_rows[c]) >= 28]
    ma10_lost = [r for r in strong_rows if "现价失守盘中MA10" in (r[27] or [])]
    fade = [r for r in strong_rows if "明显冲高回落" in (r[27] or [])]
    return {"from": left.get("scan_at"), "to": right.get("scan_at"),
            "day": right.get("day"), "sample_hash": right.get("sample_hash"),
            "model_version": right.get("model_version"),
            "rule_version": right.get("rule_version"),
            "horizon": horizon, "sample_changed": left.get("sample_hash") != right.get("sample_hash"),
            "entries": len(entries), "signals": signals, "candidate_turnover": churn,
            "current_strong_outcomes": {
                "n": len(strong_rows),
                "ma10_loss_rate_pct": round(len(ma10_lost) / len(strong_rows) * 100, 2) if strong_rows else None,
                "high_fade_rate_pct": round(len(fade) / len(strong_rows) * 100, 2) if strong_rows else None,
            }}


def build_validation_report():
    """按交易日与规则版本汇总下一扫描、较长盘中窗口和收盘后表现。"""
    all_pairs = []
    try:
        if PAIR_HISTORY_PATH.exists():
            all_pairs = [json.loads(line) for line in PAIR_HISTORY_PATH.read_text(encoding="utf-8").splitlines()
                         if line.strip()]
    except (OSError, ValueError):
        all_pairs = []
    pairs = [p for p in all_pairs if p.get("model_version") == VERSION
             and p.get("rule_version") == config.INTRADAY_RULE_VERSION]
    close_records = []
    try:
        close_records = [json.loads(path.read_text(encoding="utf-8"))
                         for path in sorted(CLOSE_HISTORY_DIR.glob("????-??-??.json"))]
    except (OSError, ValueError):
        close_records = []
    close_records = [c for c in close_records if c.get("model_version") == VERSION
                     and c.get("rule_version") == config.INTRADAY_RULE_VERSION]

    for close in close_records:
        entries = []
        for row in close.get("entries", []):
            if not all(_number(row.get(k)) for k in
                       ("intraday_score", "intraday_change_pct", "daily_score", "close_return_pct")):
                continue
            entries.append(({"intraday_score": row["intraday_score"],
                             "change_pct": row["intraday_change_pct"],
                             "daily_score": row["daily_score"]}, row["close_return_pct"]))
        signals = {}
        for key in ("intraday_score", "change_pct", "daily_score"):
            selected = [(row[key], future) for row, future in entries]
            if len(selected) < 20:
                continue
            ordered = sorted(selected, key=lambda pair: pair[0], reverse=True)
            top_n = max(1, int(len(ordered) * .10))
            signals[key] = {"n": len(selected), "spearman": _spearman(
                [x for x, _ in selected], [y for _, y in selected]),
                "top10_n": top_n,
                "top10_mean_pct": mean(y for _, y in ordered[:top_n]),
                "mean_pct": mean(y for _, y in selected)}
        close["signals"] = signals
        close["current_strong_outcomes"] = {
            "n": sum(bool(r.get("candidate_identity", {}).get("current_strong"))
                     for r in close.get("entries", [])),
            "ma10_loss_rate_pct": (round(
                sum(bool(r.get("close_below_ma10")) for r in close.get("entries", [])
                    if r.get("candidate_identity", {}).get("current_strong")) /
                sum(bool(r.get("candidate_identity", {}).get("current_strong"))
                    for r in close.get("entries", [])) * 100, 2)
                if any(r.get("candidate_identity", {}).get("current_strong")
                       for r in close.get("entries", [])) else None),
            "high_fade_rate_pct": None,
        }
        close["candidate_turnover"] = {}
        close["horizon"] = "close"
        close["entries_count"] = len(entries)

    by_horizon = {"next_scan": [p for p in pairs if p.get("horizon", "next_scan") == "next_scan"],
                  "longer_intraday": [p for p in pairs if p.get("horizon") == "longer_intraday"],
                  "close": close_records}
    signals = (("intraday_score", "盘中观察分"), ("change_pct", "直接当日涨幅"),
               ("daily_score", "原日线基础分"))
    fmt = lambda value, mult=1: f"{value * mult:.2f}" if _number(value) else "样本不足"
    lines = ["# 盘中评分增量观察", "", f"生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}", "",
             f"模型版本：{VERSION}；规则版本：{config.INTRADAY_RULE_VERSION}。不跨版本比较；"
             f"旧版本或缺少版本号的历史记录 {len(all_pairs) - len(pairs)} 对已排除。", "",
             "对照对象在同一规则版本、同一有效报价交集中计算；盘中相对主板收益只作是否跑赢的解释，排名与直接涨幅一致。"
             "所有结果都是后续价格表现，不代表可实现交易收益。先按交易日汇总，重复扫描不按独立交易样本累计。", ""]
    any_records = False
    for horizon, title in (("next_scan", "下一次有效扫描"),
                           ("longer_intraday", "较长盘中窗口（约25–45分钟）"),
                           ("close", "正式收盘")):
        records = by_horizon[horizon]
        if not records:
            continue
        any_records = True
        daily = {}
        for record in records:
            day = record.get("day")
            if day:
                daily.setdefault(day, []).append(record)
        lines += [f"## {title}", "", "| 排序依据 | 有效交易日 | 每日 Spearman 均值 | 每日头部10%后续变动 | 每日全样本后续变动 | 每日有效样本均值 |",
                  "|---|---:|---:|---:|---:|---:|"]
        for key, label in signals:
            per_day = []
            for day_records in daily.values():
                stats = [r.get("signals", {}).get(key) for r in day_records]
                stats = [s for s in stats if isinstance(s, dict) and s.get("n", 0) > 0]
                if not stats:
                    continue
                sr = [s["spearman"] for s in stats if _number(s.get("spearman"))]
                top = [s["top10_mean_pct"] for s in stats if _number(s.get("top10_mean_pct"))]
                avg = [s["mean_pct"] for s in stats if _number(s.get("mean_pct"))]
                nvals = [int(s.get("n") or 0) for s in stats]
                per_day.append({"sr": mean(sr) if sr else None,
                                "top": mean(top) if top else None,
                                "avg": mean(avg) if avg else None,
                                "n": mean(nvals) if nvals else 0})
            sr_values = [x["sr"] for x in per_day if _number(x.get("sr"))]
            top_values = [x["top"] for x in per_day if _number(x.get("top"))]
            avg_values = [x["avg"] for x in per_day if _number(x.get("avg"))]
            n_values = [x["n"] for x in per_day if x.get("n")]
            lines.append(f"| {label} | {len(per_day)} | {fmt(mean(sr_values)) if sr_values else '样本不足'} | "
                         f"{fmt(mean(top_values), 100)} bp | {fmt(mean(avg_values), 100)} bp | "
                         f"{fmt(mean(n_values)) if n_values else '0'} |")
        lines.append("")

    if any_records:
        lines += ["## 风险与候选变化", "",
                  "| 观察区间 | 有效交易日 | 当前强势候选 MA10 失守率 | 明显冲高回落率 | 当前强势名单变动率 | 初步启动名单变动率 | 回踩名单变动率 | 转弱修复名单变动率 |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for horizon, label in (("next_scan", "下一次有效扫描"),
                               ("longer_intraday", "较长盘中窗口"),
                               ("close", "正式收盘")):
            grouped = {}
            for record in by_horizon[horizon]:
                if record.get("day"):
                    grouped.setdefault(record["day"], []).append(record)
            day_rates = []
            for day_records in grouped.values():
                values = {"loss": [], "fade": [], "strong_turnover": [], "startup_turnover": [],
                          "pullback_turnover": [], "weak_turnover": []}
                for record in day_records:
                    outcome = record.get("current_strong_outcomes") or {}
                    for key, target in (("ma10_loss_rate_pct", "loss"), ("high_fade_rate_pct", "fade")):
                        if _number(outcome.get(key)):
                            values[target].append(outcome[key])
                    turnover = record.get("candidate_turnover") or {}
                    for key, target in (("current_strong", "strong_turnover"), ("startup", "startup_turnover"),
                                        ("current_pullback", "pullback_turnover"),
                                        ("turn_weak_repair", "weak_turnover")):
                        value = (turnover.get(key) or {}).get("turnover_pct")
                        if _number(value):
                            values[target].append(value)
                day_rates.append({key: mean(value) if value else None for key, value in values.items()})
            col = lambda key: fmt(mean([x[key] for x in day_rates if _number(x.get(key))])) \
                if any(_number(x.get(key)) for x in day_rates) else "样本不足"
            if day_rates:
                lines.append(f"| {label} | {len(day_rates)} | {col('loss')}% | {col('fade')}% | "
                             f"{col('strong_turnover')}% | {col('startup_turnover')}% | "
                             f"{col('pullback_turnover')}% | {col('weak_turnover')}% |")
        lines += ["", "候选名单变动率按相邻两轮名单对称差占并集计算；收盘失守率按最后有效盘中候选对照正式完成日 MA10。"]
    if not any_records:
        lines += ["当前还没有满足当前模型和规则版本的有效扫描对或收盘对照。系统从版本启用后逐轮保存，不回填不存在的分时观察。"]
    lines += ["", "样本量较少时只作机制核对。若盘中分在同一候选池内持续没有额外区分能力，应简化评分；不因短样本频繁改权重。"]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.atomic_write_text(REPORT_PATH, "\n".join(lines) + "\n")
    return {"path": str(REPORT_PATH), "pairs": len(pairs),
            "stocks": sum(int(p.get("entries") or 0) for p in pairs)}

