# -*- coding: utf-8 -*-
"""重建第二轮边界案例修改前后结果及一份有效盘中冻结输入。"""
from datetime import datetime, timedelta
from hashlib import sha256
import importlib.util
import json
import copy
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import close_monitor
import intraday


OUT = Path(__file__).resolve().parent
BASE = OUT / "baseline_round2"
DAY = "2026-09-30"
PERIODS = (5, 10, 20)


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


old_intraday = load_module(BASE / "intraday.py", "baseline_round2_intraday")
current_intraday = sys.modules["intraday"]
sys.modules["intraday"] = old_intraday
old_close_monitor = load_module(BASE / "close_monitor.py", "baseline_round2_close_monitor")
sys.modules["intraday"] = current_intraday


def trading_days(end=DAY, count=21):
    target = datetime.fromisoformat(end).date() - timedelta(days=1)
    out = []
    while len(out) < count:
        if target.weekday() < 5:
            out.append(target.isoformat())
        target -= timedelta(days=1)
    return list(reversed(out))


def history(basis="qfq", source="tencent_qfqday", count=21):
    days = trading_days(count=count)
    return [{"date": day, "open": 100.0, "high": 100.1, "low": 99.9,
             "close": 100.0, "price_basis": basis,
             "price_basis_source": source, "close_precision_digits": 2}
            for day in days]


def quote(at=DAY + " 09:37:00", last_close=99.0, price=99.2):
    return {"quote_at": at, "price": price, "open": 99.0,
            "high": max(price, 99.3), "low": 98.98,
            "last_close": last_close, "last_close_precision_digits": 2,
            "last_close_semantics": "previous_trade_day_raw_close",
            "price_basis": "raw", "price_basis_source": "tencent_realtime_quote",
            "change_pct": (price / last_close - 1) * 100 if last_close else None,
            "volume_shou": 10000, "amount_wan": 1000.0,
            "board_type": "sh_main", "limit_pct": 10.0}


def minute_bar(at, opening, high, low, close):
    return {"at": at, "open": opening, "high": high, "low": low,
            "close": close, "source": "新浪1分钟OHLC", "price_basis": "raw",
            "price_basis_source": "sina_1m_unadjusted"}


def failed_minutes(day=DAY):
    return [minute_bar(day + " 09:31", 99.0, 99.02, 98.90, 98.99),
            minute_bar(day + " 09:32", 98.99, 99.0, 98.92, 98.98)]


def recovered_minutes(day=DAY):
    out = failed_minutes(day)
    out.extend([
        minute_bar(day + " 09:33", 98.98, 98.99, 98.93, 98.97),
        minute_bar(day + " 09:34", 98.97, 98.99, 98.92, 98.98),
        minute_bar(day + " 09:35", 99.0, 99.22, 98.99, 99.2),
        minute_bar(day + " 09:39", 99.2, 99.22, 99.12, 99.18),
    ])
    return out


def summarize_context(module, q, bars, calendar):
    context = module.align_price_basis(q, bars, calendar, observation_day=DAY,
                                       quote_at=q.get("quote_at"))
    return context, {key: context.get(key) for key in (
        "valid", "reason", "scale_factor", "gap_pct", "raw_close_tolerance",
        "provisional_ma", "thresholds", "atr20", "atr20_status", "atr20_reason",
        "atr20_dates")}


def raw_close_cases():
    bars = history("raw", "tencent_day")
    calendar = [bar["date"] for bar in bars]
    cases = []
    for label, last_close in (("完全一致", 100.0), ("舍入差异0.005元", 100.005),
                              ("差异1%", 101.0), ("报价昨收缺失", None)):
        q = quote(last_close=last_close, price=100.2)
        old_ctx, old = summarize_context(old_intraday, q, bars, calendar)
        new_ctx, new = summarize_context(intraday, q, bars, calendar)
        cases.append({"name": label, "input": {"quote": q, "history": bars,
                                                   "trading_calendar": calendar},
                      "before": old, "after": new,
                      "assertion": ("同尺度直接比较" if label in ("完全一致", "舍入差异0.005元")
                                   else "待核验，且不得比例缩放"),
                      "old_valid": old_ctx.get("valid"), "new_valid": new_ctx.get("valid")})
    return cases


def atr_window_cases():
    source = history()
    calendar = [bar["date"] for bar in source]
    cases = []
    variants = []
    variants.append(("第21根日期缺口", source[1:], "ATR所需21根历史K线存在应有交易日缺口"))
    unknown = [dict(bar) for bar in source]
    unknown[0]["price_basis_source"] = "unknown_history"
    variants.append(("第21根来源未知", unknown, "ATR 21根窗口来源或复权尺度混杂"))
    mixed = [dict(bar) for bar in source]
    mixed[0].update(price_basis="raw", price_basis_source="tencent_day")
    variants.append(("第21根混合复权尺度", mixed, "ATR 21根窗口来源或复权尺度混杂"))
    abnormal = [dict(bar) for bar in source]
    abnormal[0]["low"] = abnormal[0]["high"] + 1
    variants.append(("第21根OHLC顺序异常", abnormal, "ATR 21根窗口含缺失、零值或异常OHLC价格"))
    zero_price = [dict(bar) for bar in source]
    zero_price[0]["close"] = 0
    variants.append(("第21根零收盘价", zero_price,
                     "ATR 21根窗口含缺失、零值或异常OHLC价格"))
    variants.append(("完整有效21根", source, None))
    q = quote()
    for label, bars, expected in variants:
        old_ctx, old = summarize_context(old_intraday, q, bars, calendar)
        new_ctx, new = summarize_context(intraday, q, bars, calendar)
        cases.append({"name": label, "input": {"quote": q, "history": bars,
                                                   "trading_calendar": calendar},
                      "before": old, "after": new,
                      "expected_after_atr_reason": expected,
                      "ma_window_retained": bool(new_ctx.get("valid") and new_ctx.get("provisional_ma"))})
    return cases


def legacy_note(period, line):
    state = line.get("state") or "待核验"
    if state == "快速收回":
        return f"日内曾低于MA{period}等价触线价，分钟线确认15分钟内收回；现价守住"
    if state == "曾失守后收回":
        return f"日内曾失守MA{period}后收回；现价守住，且收回超过15分钟"
    if state == "确认失守":
        return f"日内失守MA{period}，当前仍在触线价下方"
    if state == "持稳":
        return f"日内最低价未低于MA{period}触线价，现价守住"
    return f"MA{period}分钟触线状态待核验"


def minute_case(name, q, bars, minutes):
    calendar = [bar["date"] for bar in bars]
    old_context, _ = summarize_context(old_intraday, q, bars, calendar)
    new_context, _ = summarize_context(intraday, q, bars, calendar)
    live = {"intraday_quote_fresh": True, "change_pct": q.get("change_pct")}
    base = {"code": "600000", "name": "边界样本"}
    old = old_close_monitor._monitor_row(base, live, q, minutes, bars,
        q["quote_at"], calendar[-1], price_context=old_context, calendar=calendar)
    new = close_monitor._monitor_row(base, live, q, minutes, bars,
        q["quote_at"], calendar[-1], price_context=new_context, calendar=calendar)
    return {"name": name, "input": {"quote": q, "history": bars, "minutes": minutes,
                                      "trading_calendar": calendar},
            "before": {f"MA{p}": {"state": old["lines"][f"MA{p}"].get("state"),
                                   "note": legacy_note(p, old["lines"][f"MA{p}"])}
                       for p in PERIODS},
            "after": {f"MA{p}": {"current_holds": new["lines"][f"MA{p}"].get("current_holds"),
                                  "state": new["lines"][f"MA{p}"].get("state"),
                                  "last_minute_at": new["lines"][f"MA{p}"].get("last_minute_at"),
                                  "note": new["lines"][f"MA{p}"].get("note"),
                                  "event": new["lines"][f"MA{p}"].get("event")}
                      for p in PERIODS}}


def build_failure_evidence():
    bars = history()
    online = quote(at=DAY + " 09:33:00", last_close=99.0, price=99.2)
    online.update(open=99.1, low=98.9)
    below = quote(at=DAY + " 09:40:00", last_close=99.0, price=98.99)
    below.update(open=99.1, low=98.9)
    raw_1pct = quote(last_close=101.0, price=101.2)
    missing = quote(last_close=None)
    atr = atr_window_cases()
    return {
        "title": "第二轮价格口径与时间口径边界失败样本修改前后",
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "before_code": "baseline_round2/（第一轮完成后、第二轮补修前保存）",
        "after_versions": {"model": intraday.VERSION,
                           "rules": __import__("config").INTRADAY_RULE_VERSION,
                           "price_basis": intraday.PRICE_BASIS_VERSION,
                           "near_line": close_monitor.TREND_VERSION},
        "cases": {
            "minute_lag_current_quote_online_minute_still_broken": minute_case(
                "现价在线上，最新分钟记录仍失守", online, bars, failed_minutes()),
            "minute_lag_current_quote_below_minute_previously_recovered": minute_case(
                "现价在线下，分钟记录此前已收回", below, bars, recovered_minutes()),
            "raw_raw_close": raw_close_cases(),
            "atr_full_21_window": atr,
        },
        "scope_note": "所有失败案例均为确定性构造输入；真实盘中行情是否命中异常由在线快照另行报告。"
    }


def build_frozen_round2_comparison():
    frozen_path = ROOT / "research" / "price_basis_20260929" / "frozen_baseline.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    codes = list(frozen["rows"])
    input_rows = [frozen["rows"][code]["row"] for code in codes]
    quotes = {code: frozen["rows"][code]["quote"] for code in codes}
    klines = {code: frozen["rows"][code]["bars"] for code in codes}
    calendar = sorted({str(bar.get("date")) for bars in klines.values()
                       for bar in bars if bar.get("date")})
    captured_at = datetime.fromisoformat(frozen["quote_capture_at"])

    def replay(module):
        rows = copy.deepcopy(input_rows)
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(module, "HISTORY_DIR", Path(temp) / "history"), \
                patch.object(module, "_latest_record", return_value=None):
            meta = module.enrich(rows, [], quotes, klines, codes,
                captured_at=captured_at, session=frozen["session"],
                save_reference=False, trading_calendar=calendar)
        return rows, meta

    before_rows, before_meta = replay(old_intraday)
    after_rows, after_meta = replay(intraday)
    before = {str(row["code"]): row for row in before_rows}
    after = {str(row["code"]): row for row in after_rows}
    daily_fields = ("stock_strength_score", "stock_strength_parts",
                    "stock_strength_percentile", "trend_online", "signal_date",
                    "signal_close", "ma5", "ma10", "ma20", "persistent_strong")
    daily_diff = {field: sum(before[code].get(field) != after[code].get(field)
                             for code in codes) for field in daily_fields}
    trend_lists = {
        "trend_online_before": sorted(code for code in codes if before[code].get("trend_online") == 1),
        "trend_online_after": sorted(code for code in codes if after[code].get("trend_online") == 1),
        "persistent_strong_before": sorted(code for code in codes if before[code].get("persistent_strong")),
        "persistent_strong_after": sorted(code for code in codes if after[code].get("persistent_strong")),
    }
    intraday_fields = ("intraday_price_basis_comparable", "intraday_price_basis_status",
                       "intraday_price_basis_reason", "intraday_trend_ok",
                       "intraday_trend_state", "intraday_risk_level",
                       "current_strong_candidate", "startup_candidate",
                       "current_pullback_candidate", "intraday_transition")
    intraday_diff = {field: sum(before[code].get(field) != after[code].get(field)
                                for code in codes) for field in intraday_fields}
    changed_codes = [code for code in codes if any(
        before[code].get(field) != after[code].get(field) for field in intraday_fields)]
    examples = []
    for code in changed_codes[:8]:
        examples.append({"code": code,
            "before": {field: before[code].get(field) for field in intraday_fields},
            "after": {field: after[code].get(field) for field in intraday_fields}})
    return {
        "source_file": "research/price_basis_20260929/frozen_baseline.json",
        "input_sha256": frozen["frozen_input_sha256"],
        "snapshot_generated_at": frozen["snapshot_generated_at"],
        "quote_capture_at": frozen["quote_capture_at"],
        "session": frozen["session"], "daily_asof": frozen["daily_asof"],
        "rows": len(codes),
        "source_tags_present": sum(bool(rec["quote"].get("price_basis_source"))
                                    and all(bar.get("price_basis_source")
                                            for bar in rec["bars"])
                                    for rec in frozen["rows"].values()),
        "daily_field_diff_counts": daily_diff,
        "daily_trend_lists_equal": trend_lists["trend_online_before"] == trend_lists["trend_online_after"],
        "persistent_strong_lists_equal": (
            trend_lists["persistent_strong_before"] == trend_lists["persistent_strong_after"]),
        "daily_trend_list_count": len(trend_lists["trend_online_before"]),
        "persistent_strong_count": len(trend_lists["persistent_strong_before"]),
        "intraday_field_diff_counts": intraday_diff,
        "intraday_changed_code_count": len(changed_codes),
        "intraday_examples": examples,
        "before_versions": {"model": old_intraday.VERSION,
                            "price_basis": old_intraday.PRICE_BASIS_VERSION},
        "after_versions": {"model": intraday.VERSION,
                           "rules": __import__("config").INTRADAY_RULE_VERSION,
                           "price_basis": intraday.PRICE_BASIS_VERSION},
        "scope_note": "这份收盘冻结输入仅比较盘中代码处理前后的日线字段是否被原样保留，不是从原始行情完整重算日线评分的A/B。"
    }


def build_valid_freeze():
    code = "600000"
    bars = history(count=21)
    calendar = [bar["date"] for bar in bars]
    q = quote(at=DAY + " 09:37:00", last_close=99.0, price=99.2)
    q.update(open=99.0, high=99.3, low=98.98)
    minutes = [minute_bar(DAY + f" 09:{minute:02d}",
                          99.0 if minute == 31 else 98.99,
                          99.02 if minute < 36 else 99.22,
                          98.90 if minute < 36 else 98.99,
                          98.99 if minute < 36 else 99.2)
               for minute in range(31, 37)]
    row = {"code": code, "name": "尺度一致样本", "trend_online": True,
           "signal_date": calendar[-1], "signal_close": 100.0,
           "ma5": 100.0, "ma10": 100.0, "ma20": 100.0,
           "stock_strength_score": 80.0, "primary_industry": "冻结构造样本",
           "risk_notes": []}
    with tempfile.TemporaryDirectory() as temp, \
            patch.object(intraday, "HISTORY_DIR", Path(temp) / "history"), \
            patch.object(intraday, "_latest_record", return_value=None):
        meta = intraday.enrich([row], [], {code: q}, {code: bars}, [code],
            captured_at=datetime.fromisoformat(q["quote_at"]), session="早盘",
            save_reference=False, trading_calendar=calendar)
    contexts = meta.pop("_price_contexts")
    if code not in contexts:
        raise RuntimeError("冻结报价未进入共用口径计算：" + json.dumps(
            {"code": code, "quote": q, "row": {key: row.get(key) for key in (
                "intraday_quote_at", "intraday_quote_fresh", "intraday_quote_status",
                "intraday_price_basis_reason")}, "meta_keys": list(meta)}, ensure_ascii=False))
    snap = {"session": "早盘", "generated_at": q["quote_at"],
            "strength_model": {"asof": calendar[-1]}, "stocks": [row]}
    with tempfile.TemporaryDirectory() as temp, \
            patch.object(close_monitor, "TREND_DIRS",
                         {p: Path(temp) / f"ma{p}" for p in PERIODS}), \
            patch.object(close_monitor, "_get_minutes", return_value={code: minutes}):
        close_monitor._attach_trend_observations(
            snap, {code: q}, {code: bars}, DAY, contexts, calendar)
    context = contexts[code]
    detail = close_monitor._monitor_row({"code": code, "name": row["name"]}, row, q,
        minutes, bars, q["quote_at"], calendar[-1], price_context=context, calendar=calendar)
    results = {}
    for period in PERIODS:
        board = snap[f"trend_ma{period}_observation"]
        near = next(item for item in board["reclaim_rows"] + board["main_rows"]
                    if item["code"] == code)
        results[f"MA{period}"] = {
            "intraday": {"ma_display": row[f"intraday_ma{period}"],
                         "ma_exact": row[f"intraday_ma{period}_exact"],
                         "threshold": row[f"intraday_ma{period}_trigger_price"],
                         "distance_pct": row[f"intraday_distance_ma{period}_pct"],
                         "distance_pct_display": round(row[f"intraday_distance_ma{period}_pct"], 3),
                         "distance_atr": row[f"intraday_distance_ma{period}_atr"],
                         "current_holds": row[f"intraday_ma{period}_current_holds"]},
            "near_line": {"ma": near["provisional_ma"],
                          "threshold": near["threshold_price"],
                          "distance_pct": near["distance_pct"],
                          "distance_atr": near["distance_atr"],
                          "status": near["status"]},
            "minute": {"threshold": detail["lines"][f"MA{period}"]["threshold"],
                       "current_holds": detail["lines"][f"MA{period}"]["current_holds"],
                       "state": detail["lines"][f"MA{period}"]["state"],
                       "last_minute_at": detail["lines"][f"MA{period}"]["last_minute_at"],
                       "note": detail["lines"][f"MA{period}"]["note"]}}
        results[f"MA{period}"]["consistency"] = {
            "display_ma_equal": (results[f"MA{period}"]["intraday"]["ma_display"] ==
                                 results[f"MA{period}"]["near_line"]["ma"]),
            "threshold_equal": (results[f"MA{period}"]["intraday"]["threshold"] ==
                                 results[f"MA{period}"]["near_line"]["threshold"] ==
                                 results[f"MA{period}"]["minute"]["threshold"]),
            "distance_display_equal": (results[f"MA{period}"]["intraday"]["distance_pct_display"] ==
                                       results[f"MA{period}"]["near_line"]["distance_pct"]),
            "atr_distance_equal": (results[f"MA{period}"]["intraday"]["distance_atr"] ==
                                   results[f"MA{period}"]["near_line"]["distance_atr"]),
            "current_holds_equal": (results[f"MA{period}"]["intraday"]["current_holds"] is True and
                                    results[f"MA{period}"]["near_line"]["status"] == "15分钟内收回" and
                                    results[f"MA{period}"]["minute"]["current_holds"] is True),
        }
    return {
        "title": "有效盘中报价三入口冻结输入",
        "captured_at": q["quote_at"],
        "input_sha256": sha256(json.dumps(
            {"quote": q, "history": bars, "minutes": minutes, "calendar": calendar},
            ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "input": {"code": code, "quote": q, "history": bars,
                  "minutes": minutes, "trading_calendar": calendar,
                  "history_last_date": calendar[-1], "basis_conversion_preset":
                  "来源明示qfq日线、raw腾讯逐股与raw新浪分钟，允许同比例换算"},
        "context": {"version": context["version"], "valid": context["valid"],
                    "scale_factor": context["scale_factor"],
                    "atr20": context["atr20"], "atr20_status": context["atr20_status"]},
        "results": results,
        "scope_note": "冻结样本只核验同一尺度上的MA、距离、当前守线和分钟历史关系；单股样本不足以证明盘中评分或趋势资格。"
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "round2_failure_evidence.json").write_text(
        json.dumps(build_failure_evidence(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (OUT / "frozen_intraday_quote.json").write_text(
        json.dumps(build_valid_freeze(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (OUT / "frozen_round2_comparison.json").write_text(
        json.dumps(build_frozen_round2_comparison(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("saved round2_failure_evidence.json, frozen_intraday_quote.json and frozen_round2_comparison.json")


if __name__ == "__main__":
    main()
