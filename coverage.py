"""Explain why a quoted stock is absent from the scored list.

The catalog is a visibility layer, not a second strength ranking. Completed-day
trend evidence is calculated with the same calendar as the main model.
"""
from collections import Counter
from statistics import mean
import math

import strength


REASONS = {
    "no_kline": "缺少历史日线",
    "short_history": "核心评分历史不足25个完成交易日",
    "no_trade": "当日无成交（可能停牌），不进入可交易候选",
    "trade_recovered_wait_daily": "成交已恢复，核心日线尚未重新对齐",
    "raw_invalid": "历史行情数据不足",
    "stale": "完成日线未更新到统一判断日",
    "unaligned": "核心评分最近25个交易日期不齐",
    "invalid": "日线价格或成交量异常",
    "integrity_pending": "正式历史修订或复权口径待完整核验，暂停趋势与评分",
}


def _has_trade(quote):
    for key in ("amount_wan", "volume_shou"):
        try:
            if float(quote.get(key) or 0) > 0:
                return True
        except (TypeError, ValueError):
            pass
    return False


def trend_metrics21(bars):
    """Verify only the user's MA5/10/20 trend rule on 21 completed bars."""
    b = bars[-21:]
    close = b[-1]["close"]
    ma5 = mean(x["close"] for x in b[-5:])
    ma10 = mean(x["close"] for x in b[-10:])
    ma20 = mean(x["close"] for x in b[-20:])
    ma20_prev = mean(x["close"] for x in b[-21:-1])
    return {"signal_date": b[-1]["date"], "signal_close": close,
            "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma20_prev": ma20_prev,
            "trend_online": int(ma5 > ma10 > ma20 and ma20 > ma20_prev and close >= ma10),
            "ret5": (close / b[-6]["close"] - 1) * 100,
            "ret20": (close / b[-21]["close"] - 1) * 100,
            "touch_state": None, "dist_atr": None}


def build(quotes, klines, ranked_codes, raw_reasons, raw_metrics, asof, calendar,
          previous_rows=None):
    wanted = calendar[-strength.CORE_BARS:]
    wanted21 = calendar[-21:]
    previous_by_code = {str(row.get("code")): row for row in (previous_rows or [])
                        if row.get("code")}
    rows = []
    counts = Counter()
    for code, quote in quotes.items():
        if code in ranked_codes:
            continue
        bars = strength.completed(klines.get(code) or [])
        bars = [bar for bar in bars if bar["date"] <= asof]
        metric = None
        date_reason = strength.core_window_issue(bars, calendar)
        if date_reason is None:
            metric = strength.day_metrics(bars, calendar)
        full_metric = metric is not None
        if (metric is None and date_reason in ("unaligned", "short_history")
                and len(bars) >= 21 and [bar["date"] for bar in bars[-21:]] == wanted21
                and all(isinstance(bar.get("close"), (int, float))
                        and math.isfinite(bar["close"]) and bar["close"] > 0
                        for bar in bars[-21:])):
            metric = trend_metrics21(bars)
        raw_reason = raw_reasons.get(code)
        traded = _has_trade(quote)
        known_nontrade = (not traded and
                          (quote.get("amount_wan") is not None or
                           quote.get("volume_shou") is not None))
        old = previous_by_code.get(code) or {}
        recovered_wait = bool(traded and date_reason and old.get("trade_status") in
                              ("no_trade", "trade_recovered_wait_daily"))
        if raw_reason == "no_trade" or known_nontrade:
            reason = "no_trade"
        elif recovered_wait:
            reason = "trade_recovered_wait_daily"
        else:
            reason = ((raw_reason or "raw_invalid") if full_metric
                      else (date_reason or raw_reason or "invalid"))
        reason_text = REASONS.get(reason, reason)
        if reason == "no_trade" and date_reason:
            reason_text += "；" + REASONS.get(date_reason, date_reason)
        elif reason == "trade_recovered_wait_daily" and date_reason:
            reason_text += "（" + REASONS.get(date_reason, date_reason) + "）"
        raw = raw_metrics.get(code) or {}
        row = {
            "code": code, "name": quote.get("name") or code,
            "board_name": quote.get("board_name"),
            "price": quote.get("price"), "change_pct": quote.get("change_pct"),
            "open": quote.get("open"), "high": quote.get("high"), "low": quote.get("low"),
            "last_close": quote.get("last_close"), "limit_up": quote.get("limit_up"),
            "limit_down": quote.get("limit_down"), "limit_pct": quote.get("limit_pct"),
            "board_type": quote.get("board_type"), "ts": quote.get("ts"),
            "quote_at": quote.get("quote_at"), "turnover_pct": quote.get("turnover_pct"),
            "float_mcap_yi": quote.get("float_mcap_yi"),
            "amount_wan": quote.get("amount_wan"),
            "reason": reason, "reason_text": reason_text,
            "trade_status": ("no_trade" if reason == "no_trade" else
                             "trade_recovered_wait_daily" if recovered_wait else "trading_unscored"),
            "data_reason": date_reason, "trend_online": None if metric is None else metric["trend_online"],
            "daily_core_required_bars": strength.CORE_BARS,
            "daily_core_missing_dates": sorted(set(wanted) - {b["date"] for b in bars}),
            "daily_core_invalid_dates": [b["date"] for b in bars[-strength.CORE_BARS:] if not strength.valid_bars([b])],
            "watch_candidate": bool(metric and metric["trend_online"]
                                    and reason != "no_trade" and not recovered_wait),
            "coverage_only": True,
            "trend_basis": "完整25日核心日线" if full_metric else "最近21日均线" if metric else None,
            "daily_strength_status": (
                "当日无成交，暂停当前评分" if reason == "no_trade" else
                "恢复成交，核心日线待对齐" if recovered_wait else
                "核心日线可核验、未参与评分" if full_metric else
                "趋势可核验、强度待评分" if metric else "日线不足"),
            "signal_date": None if metric is None else metric["signal_date"],
            "amt_med20_wan": raw.get("amt_med20_wan"),
        }
        if metric:
            row.update({key: metric[key] for key in (
                "ma5", "ma10", "ma20", "ma20_prev", "signal_close", "ret5", "ret20",
                "touch_state", "dist_atr")})
        rows.append(row)
        counts[reason] += 1
    rows.sort(key=lambda x: x["code"])
    online = sum(x["trend_online"] == 1 for x in rows)
    return rows, {"excluded": len(rows), "trend_online_outside": online,
                  "reasons": dict(counts), "asof": asof}
