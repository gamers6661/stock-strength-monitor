"""完成日线的个股自身强度；不使用盘中报价、资金或板块热度加分。"""
from bisect import bisect_left, bisect_right
import json
from statistics import mean, median

import config
import attack_model


VERSION = "日线趋势进攻版6"
PERSISTENT_CRITERION = attack_model.CRITERION
WEIGHTS = attack_model.WEIGHTS
LABELS = attack_model.LABELS


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def _percentiles(values):
    """仅对有值样本做并列平均分位；缺失维持 None。"""
    ordered = sorted(v for v in values.values() if v is not None)
    if not ordered:
        return {code: None for code in values}
    if len(ordered) == 1:
        return {code: 50.0 if value is not None else None for code, value in values.items()}
    return {code: round((bisect_left(ordered, value) + bisect_right(ordered, value) - 1)
                        / 2 / (len(ordered) - 1) * 100, 2) if value is not None else None
            for code, value in values.items()}


def _close_location(bar):
    spread = bar["high"] - bar["low"]
    return (bar["close"] - bar["low"]) / spread * 100 if spread > 0 else 50.0


def _volume_balance(bars, length):
    window = bars[-length - 1:]
    positive = sum(window[i]["volume"] for i in range(1, len(window))
                   if window[i]["close"] > window[i - 1]["close"])
    negative = sum(window[i]["volume"] for i in range(1, len(window))
                   if window[i]["close"] < window[i - 1]["close"])
    total = sum(b["volume"] for b in window[1:])
    return ((positive - negative) / total * 100 if total else 0.0,
            positive / total * 100 if total else 0.0)


def raw_metrics(bars):
    """窗口终点为同一个完成交易日，变化比较使用相邻的等长区间。"""
    closes = [b["close"] for b in bars[-21:]]
    travel = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    path_eff = (closes[-1] - closes[0]) / travel if travel else 0.0
    peak, max_dd, trough, peak_at_trough = closes[1], 0.0, closes[1], closes[1]
    for value in closes[1:]:
        peak = max(peak, value)
        drawdown = (value / peak - 1) * 100
        if drawdown < max_dd:
            max_dd, trough, peak_at_trough = drawdown, value, peak
    repair = (_clamp((closes[-1] - trough) / (peak_at_trough - trough) * 100)
              if peak_at_trough > trough else 100.0)
    high20 = max(b["high"] for b in bars[-20:])
    current_drawdown = (bars[-1]["close"] / high20 - 1) * 100
    balance10, up_share10 = _volume_balance(bars, 10)
    balance5, _ = _volume_balance(bars, 5)
    prev_balance5, _ = _volume_balance(bars[:-5], 5)
    loc3 = mean(_close_location(b) for b in bars[-3:])
    prev_loc3 = mean(_close_location(b) for b in bars[-6:-3])
    base_volume = median(b["volume"] for b in bars[-12:-2])
    two_day_ret = (bars[-1]["close"] / bars[-3]["close"] - 1) * 100
    stall = bool(base_volume > 0 and all(b["volume"] >= 1.3 * base_volume for b in bars[-2:])
                 and loc3 < prev_loc3 and two_day_ret <= 1.0)
    last6 = bars[-6:]
    up_vol = [last6[i]["volume"] for i in range(1, 6) if last6[i]["close"] > last6[i - 1]["close"]]
    down_vol = [last6[i]["volume"] for i in range(1, 6) if last6[i]["close"] < last6[i - 1]["close"]]
    down_expand = bool(up_vol and down_vol and median(down_vol) > 1.3 * median(up_vol))
    pullback_volume_ratio = round(median(down_vol) / median(up_vol), 2) if up_vol and down_vol and median(up_vol) else None
    reclaimed_3d_high = bars[-1]["close"] > max(b["high"] for b in bars[-4:-1])
    return {
        "ret10": round((bars[-1]["close"] / bars[-11]["close"] - 1) * 100, 4),
        "past_impulse5_pct": round(max((closes[i] / closes[i-5] - 1)*100
                                        for i in range(5, len(closes))), 3),
        "path_eff20": round(path_eff, 4), "max_dd20_pct": round(max_dd, 2),
        "distance_high20_pct": round(current_drawdown, 2),
        "current_drawdown_pct": round(current_drawdown, 2),
        "drawdown_repair_pct": round(repair, 2),
        "ret5_prev_pct": round((bars[-6]["close"] / bars[-11]["close"] - 1) * 100, 2),
        "volume_balance10_pct": round(balance10, 2),
        "up_volume_share10_pct": round(up_share10, 2),
        "volume_balance5_pct": round(balance5, 2),
        "volume_balance_prev5_pct": round(prev_balance5, 2),
        "close_location3_pct": round(loc3, 2),
        "close_location_prev3_pct": round(prev_loc3, 2),
        "volume_spike_stall": stall, "down_volume_expand": down_expand,
        "pullback_volume_ratio": pullback_volume_ratio,
        "reclaimed_3d_high": reclaimed_3d_high,
    }


def score(metrics, contexts, bars_by_code):
    """固定完成日线参考池，避免盘中成交先后改变历史强度分位。"""
    codes = list(metrics)
    if not codes:
        return {}, 0
    raw = {code: raw_metrics(bars_by_code[code]) for code in codes}
    market_codes = list(metrics)
    market_daily = [mean((bars_by_code[code][-10 + i]["close"] /
                          bars_by_code[code][-11 + i]["close"] - 1) * 100 for code in market_codes)
                    for i in range(10)]
    market_ret3 = mean(metrics[c]["ret3"] for c in market_codes)
    market_ret5 = mean(metrics[c]["ret5"] for c in market_codes)
    market_prev5 = mean((bars_by_code[c][-6]["close"] / bars_by_code[c][-11]["close"] - 1) * 100
                        for c in market_codes)
    for code in codes:
        bars = bars_by_code[code]
        daily = [(bars[-10 + i]["close"] / bars[-11 + i]["close"] - 1) * 100 for i in range(10)]
        raw[code]["beat_days10"] = sum(daily[i] > market_daily[i] for i in range(10))
    p = {key: _percentiles({c: metrics[c].get(key) for c in codes}) for key in ("ret5", "ret20")}
    volatility = {c: (metrics[c].get("atr20") or 0) / bars_by_code[c][-1]["close"] * 100
                  for c in codes}
    vol_pct = _percentiles(volatility)
    momentum = attack_model.momentum_scores({c: {5: metrics[c]["ret5"],
                                                10: raw[c]["ret10"], 20: metrics[c]["ret20"]}
                                             for c in codes})
    result = {}
    for code in codes:
        m, x, ctx = metrics[code], raw[code], contexts[code]
        # 风险、波动、成交量和同行覆盖均不抵消实际进攻能力。
        parts = momentum[code]["parts"]
        total = momentum[code]["score"]
        rel5 = m["ret5"] - market_ret5
        prev_rel5 = x["ret5_prev_pct"] - market_prev5
        accel = rel5 - prev_rel5
        rel3 = m["ret3"] - market_ret3
        if prev_rel5 < 0 <= rel5 and accel >= 1 and x["close_location3_pct"] >= 40:
            motion = "修复"
        elif accel >= 2 and rel3 >= 0 and x["close_location3_pct"] >= 45 and not x["volume_spike_stall"]:
            motion = "增强"
        elif (accel <= -2 and rel3 <= 0) or (x["volume_spike_stall"] and accel < 0):
            motion = "衰减"
        else:
            motion = "维持"
        descriptions = {
            "acceptance": f"近10日上涨成交量占比 {x['up_volume_share10_pct']:.0f}%，近3日收盘位置 {x['close_location3_pct']:.0f}%"
                          + ("；近两日放量滞涨" if x["volume_spike_stall"] else "")
                          + ("；下跌日量能偏大" if x["down_volume_expand"] else "")
                          + (f"；回调日/上涨日量比 {x['pullback_volume_ratio']:.2f}"
                             if x["pullback_volume_ratio"] is not None else "；近5日缺少双向样本")
                          + ("；已收复近3日高点" if x["reclaimed_3d_high"] else "；尚未收复近3日高点"),
            "recovery": f"20日历史最大回撤 {x['max_dd20_pct']:.1f}%，该次回撤修复 {x['drawdown_repair_pct']:.0f}%；当前距20日最高价 {x['current_drawdown_pct']:.1f}%",
        }
        structure_evidence = descriptions["acceptance"] + "；" + descriptions["recovery"]
        evidence = momentum[code]["evidence"]
        pattern = attack_model.price_pattern(bars_by_code[code][:-1],
                                             bars_by_code[code][-1]["close"], m["ma10"],
                                             (bars_by_code[code][-1]["close"] /
                                              bars_by_code[code][-2]["close"]-1)*100)
        strongest = max(parts, key=parts.get)
        weakest = min(parts, key=parts.get)
        result[code] = {
            **x, "ret5_percentile": p["ret5"][code], "ret20_percentile": p["ret20"][code],
            "daily_attack_pattern": pattern, "daily_attack_stage": pattern["stage"],
            "daily_attack_event": pattern["event"], "structure_evidence": structure_evidence,
            "attack_model_version": attack_model.VERSION,
            "beat_days10_pct": x["beat_days10"] * 10,
            "stock_strength_score": total, "stock_strength_parts": parts,
            "stock_strength_evidence": evidence,
            "stock_strength_main_good": LABELS[strongest],
            "stock_strength_main_weak": LABELS[weakest],
            "stock_strength_motion": motion,
            "daily_motion": motion,
            "stock_strength_motion_basis": f"最近5日对主板 {rel5:+.1f} 点，前5日 {prev_rel5:+.1f} 点；近3日 {rel3:+.1f} 点",
            "strength_accel5_pp": round(accel, 2),
            "ret3_ex_market": round(rel3, 2),
            "strength_direction": ("上涨延续" if m["ret20"] > 0 and m["ret5"] > 0 else
                                   "上涨中回调" if m["ret20"] > 0 else
                                   "近期反弹" if m["ret5"] > 0 else
                                   "相对抗跌" if rel5 > 0 else "绝对下跌"),
            "stock_strength_coverage": "同行超额可参考" if ctx.get("ret5_ex_industry") is not None else "同行超额数据不足；不影响固定评分口径",
            "volatility20_pct": round(volatility[code], 2),
            "volatility_group": ("低波动" if vol_pct[code] < 33.34 else
                                  "中波动" if vol_pct[code] < 66.67 else "高波动"),
        }
    percentiles = _percentiles({c: result[c]["stock_strength_score"] for c in codes})
    for rank, code in enumerate(sorted(codes, key=lambda c: (-result[c]["stock_strength_score"], c)), 1):
        result[code]["stock_strength_percentile"] = percentiles[code]
        result[code]["stock_strength_rank"] = rank
        result[code]["stock_strength_reference_count"] = len(codes)
        returns = {5: metrics[code]["ret5"], 10: raw[code]["ret10"], 20: metrics[code]["ret20"]}
        daily_tier = attack_model.tier(result[code]["stock_strength_score"], returns,
                                      bool(metrics[code]["trend_online"]), raw[code]["past_impulse5_pct"])
        result[code]["daily_attack_tier"] = daily_tier
        if daily_tier in ("A", "B") and result[code]["daily_attack_stage"] == "趋势整理":
            result[code]["daily_attack_stage"] = "强股整理"
            result[code]["daily_attack_pattern"]["stage"] = "强股整理"
        qualification = {
            "完成日趋势在线": bool(metrics[code]["trend_online"]),
            "进攻分至少65": result[code]["stock_strength_score"] >= attack_model.PARAMETERS["a_score_min"],
            "实际涨幅达到进攻门槛": any(returns[n] >= v for n, v in attack_model.PARAMETERS["a_returns"].items()),
            "5日收益为正": metrics[code]["ret5"] > 0,
            "20日收益为正": metrics[code]["ret20"] > 0,
        }
        result[code]["persistent_qualification"] = qualification
        result[code]["persistent_missing"] = [k for k, v in qualification.items() if not v]
        result[code]["persistent_strong"] = all(qualification.values())
        result[code]["recent_improving"] = bool(
            result[code]["stock_strength_motion"] in ("增强", "修复")
            and result[code]["stock_strength_percentile"] >= 50 and metrics[code]["ret5"] > 0)
        result[code]["high_fading"] = bool(
            result[code]["ret20_percentile"] >= 80 and result[code]["stock_strength_motion"] == "衰减")
        result[code]["stock_strength_display_state"] = (
            "总体仍强，近期衰减" if result[code]["persistent_strong"] and result[code]["high_fading"]
            else result[code]["stock_strength_motion"])
    return result, len(codes)


def _daily_path(day):
    return config.CACHE_DIR / "stock_strength_daily" / "v6" / f"{day}.json"


def attach_history(rows, prior_day, prior_five_day):
    """真实留档优先；缺失时读取明确标记的本模型历史重算参考。"""
    import history_reference
    history = {}
    sources = {}
    references = {}
    for key, day in (("strength_delta1", prior_day), ("strength_delta5", prior_five_day)):
        path = _daily_path(day)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}
        valid=record.get("version")==VERSION and record.get('asof',day)==day
        sources[key]='真实收盘留档' if valid else '历史日线重算'
        references[key]=history_reference.load(day)
        if not valid:record=references[key]
        history[key] = record.get("stocks") or {}
    for row in rows:
        for key in ("strength_delta1", "strength_delta5"):
            old = history[key].get(row["code"])
            source=sources[key]
            if old is None:
                old=(references[key].get('stocks') or {}).get(row['code'])
                source='历史日线重算'
            if isinstance(old, dict):
                old = old.get("percentile")
            row[key] = (round(row["stock_strength_percentile"] - old, 2)
                        if isinstance(old, (int, float)) else None)
            row[key+'_source']=source if row[key] is not None else '对应完成日尚无可用参考'
            row[key+'_asof']=prior_day if key=='strength_delta1' else prior_five_day


def save_daily(snap):
    day = (snap.get("strength_model") or {}).get("asof")
    if not day or snap.get("mode") == "local-rebuild":
        return
    path = _daily_path(day)
    # 当日首份完成日线观察固定保存；盘中反复刷新不能悄悄改写历史依据。
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"version": VERSION, "asof": day, "observed_at": snap.get("generated_at"),
              "reference_count": (snap.get("strength_model") or {}).get("strength_reference_count"),
              "stocks": {r["code"]: {
                  "percentile": r["stock_strength_percentile"], "score": r["stock_strength_score"],
                  "parts": r["stock_strength_parts"], "evidence": r["stock_strength_evidence"],
                  "motion": r["stock_strength_motion"], "ret5": r["ret5"], "ret20": r["ret20"],
                  "ret10": r.get("ret10"), "tier": r.get("daily_attack_tier"),
                  "price_pattern": r.get("daily_attack_pattern"),
                  "industry": r.get("primary_industry"), "industry_excess5": r.get("ret5_ex_industry"),
                  "coverage": r["stock_strength_coverage"]}
                         for r in snap.get("stocks", [])
                         if r.get("stock_strength_percentile") is not None}}
    config.atomic_write_text(path, json.dumps(record, ensure_ascii=False, separators=(",", ":")))
