"""均线趋势观察：完成日线三线排列、回踩MA10，资金单独确认。"""
from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean, median
import math

import config
import stock_strength


VERSION = "趋势与进攻强度 V4.0"
CORE_BARS = 25  # MA20 五日前参考需要25根，进攻三周期和结构判断复用该窗口。


def valid_bars(bars):
    for b in bars:
        vals = [b.get(k) for k in ("open", "high", "low", "close", "volume")]
        if any(isinstance(v, bool) or not isinstance(v, (float, int))
               or not math.isfinite(v) or v <= 0 for v in vals):
            return False
        if not b["low"] <= min(b["open"], b["close"]) <= max(b["open"], b["close"]) <= b["high"]:
            return False
    return True


def core_window_issue(bars, calendar):
    if not bars:
        return "no_kline"
    if not calendar or bars[-1]["date"] != calendar[-1]:
        return "stale"
    if len(bars) < CORE_BARS:
        return "short_history"
    if [b["date"] for b in bars[-CORE_BARS:]] != calendar[-CORE_BARS:]:
        return "unaligned"
    return None if valid_bars(bars[-CORE_BARS:]) else "invalid"


def completed(klines, now=None):
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    closed = now.hour * 60 + now.minute >= 15 * 60 + 5
    return [b for b in klines if b["date"] < today or (b["date"] == today and closed)]


def trading_calendar(klines):
    counts = Counter(b["date"] for ks in klines.values() for b in ks)
    threshold = max(counts.values(), default=0) * 0.5
    return sorted(d for d, n in counts.items() if n >= threshold)


def day_metrics(bars, calendar=None):
    """仅使用调用方提供的截至信号日数据；回放与实时共用。"""
    if len(bars) < CORE_BARS:
        return None
    ks = bars[-CORE_BARS:]
    if not valid_bars(ks) or (calendar is not None and core_window_issue(bars, calendar)):
        return None
    long_ok = (len(bars) >= 61 and valid_bars(bars[-61:])
               and (calendar is None or [b["date"] for b in bars[-61:]] == calendar[-61:]))
    close = ks[-1]["close"]
    ma5 = mean(b["close"] for b in ks[-5:])
    ma10 = mean(b["close"] for b in ks[-10:])
    ma20 = mean(b["close"] for b in ks[-20:])
    ma60 = mean(b["close"] for b in bars[-60:]) if long_ok else None
    ma20_prev = mean(b["close"] for b in ks[-21:-1])
    ma5_prev = mean(b["close"] for b in ks[-6:-1])
    ma10_prev = mean(b["close"] for b in ks[-11:-1])
    ma20_2ago = mean(b["close"] for b in ks[-22:-2])
    ma5_2ago = mean(b["close"] for b in ks[-7:-2])
    ma10_2ago = mean(b["close"] for b in ks[-12:-2])
    ma20_3ago = mean(b["close"] for b in ks[-23:-3])
    ma20_5ago = mean(b["close"] for b in ks[-25:-5])
    atr20 = mean(max(ks[i]["high"] - ks[i]["low"],
                     abs(ks[i]["high"] - ks[i - 1]["close"]),
                     abs(ks[i]["low"] - ks[i - 1]["close"])) for i in range(len(ks) - 20, len(ks)))
    ph20 = max(b["high"] for b in ks[-21:-1])
    lo60 = min(b["low"] for b in bars[-60:]) if long_ok else None
    hi60 = max(b["high"] for b in bars[-60:]) if long_ok else None
    above60 = int(close > ma60) if long_ok else None
    breakout = close > ph20
    trend_aligned = ma5 > ma10 > ma20 and ma20 > ma20_prev
    trend_online = trend_aligned and close >= ma10
    trend_online_prev = ma5_prev > ma10_prev > ma20_prev and ma20_prev > ma20_2ago and ks[-2]["close"] >= ma10_prev
    trend_online_prev2 = (ma5_2ago > ma10_2ago > ma20_2ago
                          and ma20_2ago > ma20_3ago and ks[-3]["close"] >= ma10_2ago)
    path = [b["close"] for b in ks[-21:]]
    travel = sum(abs(path[i] - path[i - 1]) for i in range(1, len(path)))
    peak = path[1]
    max_dd20 = 0.0
    for value in path[1:]:
        peak = max(peak, value)
        max_dd20 = min(max_dd20, (value / peak - 1) * 100)
    # 只看最近3个完成交易日，每天都用当日的10日线判定是否触及。
    touches = []
    for offset in (2, 1, 0):
        end = len(ks) - offset
        line = mean(b["close"] for b in ks[end - 10:end])
        bar = ks[end - 1]
        if bar["low"] <= line:
            touches.append((offset, bar["close"] >= line, bar["close"]))
    latest_touch = touches[-1] if touches else None
    if not trend_aligned:
        touch_state = "排列未成立"
    elif close < ma10:
        touch_state = "回踩失守" if latest_touch else "收盘失守10日线"
    elif latest_touch is None:
        touch_state = "沿趋势运行"
    elif latest_touch[0] == 0:
        touch_state = "回踩反弹" if close > ks[-2]["close"] else "站回待确认"
    elif not latest_touch[1]:
        touch_state = "跌破后收复"
    else:
        touch_state = "回踩后上行" if close > latest_touch[2] else "站回待确认"
    pullback = touch_state in ("回踩反弹", "站回待确认", "回踩后上行")
    return {
        **{f"ret{n}": (close / ks[-1 - n]["close"] - 1) * 100 for n in (3, 5, 20)},
        "ret60": (close / bars[-61]["close"] - 1) * 100 if long_ok else None,
        "daily_core_bars": CORE_BARS,
        "reference60_status": "完整61日参考" if long_ok else "61日参考窗口不足、缺口或异常；不影响核心评分",
        "signal_date": ks[-1]["date"], "signal_close": close,
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60, "ma20_prev": ma20_prev,
        "atr20": atr20, "trend_aligned": int(trend_aligned), "trend_online": int(trend_online),
        "trend_online_prev": int(trend_online_prev), "trend_online_prev2": int(trend_online_prev2),
        "ma20_slope5_pct": (ma20 / ma20_5ago - 1) * 100,
        "path_eff20": (path[-1] - path[0]) / travel if travel > 0 else 0.0,
        "max_dd20_pct": max_dd20,
        "touch_state": touch_state, "touch_age": latest_touch[0] if latest_touch else None,
        "above20": int(close > ma20), "above60": above60,
        "ph20": ph20, "broke20": int(breakout), "pullback_observe": int(pullback),
        "entry_state": touch_state,
        "dist_atr": (close - ma10) / atr20 if atr20 > 0 else None,
        "bias20": (close / ma20 - 1) * 100,
        "position60": ((close - lo60) / (hi60 - lo60) * 100 if hi60 > lo60 else 50.0) if long_ok else None,
        "amt_med20_wan": median(b["volume"] * b["close"] / 1e4 for b in ks[-20:]),
        "volume_ratio_closed": ks[-1]["volume"] / median(b["volume"] for b in ks[-21:-1]),
        "bars": len(bars),
    }


def industry_context(metrics, industries):
    """使用唯一行业归属；去自身、有效同伴不足时不补值。"""
    groups = defaultdict(list)
    for code, m in metrics.items():
        name = industries.get(code)
        if name:
            groups[name].append(code)
    totals = {name: sum(metrics[c]["above20"] for c in codes) for name, codes in groups.items()}
    min_peers = config.SIMPLE_STRENGTH["min_industry_peers"]
    market_trend = mean(bool(m.get("trend_online")) for m in metrics.values()) * 100 if metrics else 0.0
    market_trend_prior = [mean(bool(m.get(key)) for m in metrics.values()) * 100 if metrics else 0.0
                          for key in ("trend_online_prev2", "trend_online_prev")]
    market_breadth = mean(bool(m.get("above20")) for m in metrics.values()) * 100 if metrics else 0.0
    market_ret = {n: mean(m[f"ret{n}"] for m in metrics.values() if m.get(f"ret{n}") is not None)
                  if any(m.get(f"ret{n}") is not None for m in metrics.values()) else None for n in (5, 20)}
    out = {}
    for code in metrics:
        name = industries.get(code)
        peers = len(groups.get(name, [])) - 1 if name else 0
        up = totals.get(name, 0) - metrics[code]["above20"] if name else 0
        peer_codes = [c for c in groups.get(name, []) if c != code]
        trend = sum(bool(metrics[c].get("trend_online")) for c in peer_codes)
        trend_prev = sum(bool(metrics[c].get("trend_online_prev")) for c in peer_codes)
        trend_prev2 = sum(bool(metrics[c].get("trend_online_prev2")) for c in peer_codes)
        stripped = sorted(peer_codes, key=lambda c: metrics[c].get("ret20") or 0, reverse=True)[2:]
        peer_ret = {n: mean(metrics[c][f"ret{n}"] for c in peer_codes if metrics[c].get(f"ret{n}") is not None)
                    if any(metrics[c].get(f"ret{n}") is not None for c in peer_codes) else None for n in (5, 20)}
        breadth = round(up / peers * 100, 2) if peers >= min_peers else None
        out[code] = {
            "primary_industry": name,
            "industry_peers": max(peers, 0),
            "industry_above20": max(up, 0),
            "industry_breadth": breadth,
            "industry_breadth_vs_market_pp": round(breadth - market_breadth, 2) if breadth is not None else None,
            "industry_peer_trend_pct": round(trend / peers * 100, 2) if peers >= min_peers else None,
            "industry_peer_trend_delta_pp": round((trend - trend_prev) / peers * 100, 2) if peers >= min_peers else None,
            "industry_peer_trend_prev2_pct": round(trend_prev2 / peers * 100, 2) if peers >= min_peers else None,
            "industry_peer_trend_rising_days2": int(trend_prev > trend_prev2) + int(trend > trend_prev)
            if peers >= min_peers else None,
            "industry_peer_trend_above_market_days3": sum(
                peer / peers * 100 > market for peer, market in
                zip((trend_prev2, trend_prev, trend), (*market_trend_prior, market_trend)))
            if peers >= min_peers else None,
            "industry_ex_top2_trend_pct": round(sum(bool(metrics[c].get("trend_online")) for c in stripped) / len(stripped) * 100, 2)
            if len(stripped) >= min_peers else None,
            "market_trend_pct": round(market_trend, 2),
            "market_breadth_pct": round(market_breadth, 2),
            **{f"ret{n}_ex_market": round(metrics[code][f"ret{n}"] - market_ret[n], 2)
               if metrics[code].get(f"ret{n}") is not None and market_ret[n] is not None else None for n in (5, 20)},
            **{f"ret{n}_ex_industry": round(metrics[code][f"ret{n}"] - peer_ret[n], 2)
               if metrics[code].get(f"ret{n}") is not None and peer_ret[n] is not None and peers >= min_peers else None for n in (5, 20)},
            **{f"industry_ret{n}_ex_market": round(peer_ret[n] - market_ret[n], 2)
               if peer_ret[n] is not None and market_ret[n] is not None and peers >= min_peers else None for n in (5, 20)},
        }
    return out


def industry_map(profiles, member_map):
    """F10 所属行业的末级名称优先；详情成员图仅在归属唯一时补充。"""
    out = {}
    for code in set(profiles) | set(member_map):
        names = list(dict.fromkeys((profiles.get(code) or {}).get("industry") or []))
        fallback = list(dict.fromkeys(member_map.get(code) or []))
        if names:
            out[code] = names[-1]
        elif len(fallback) == 1:
            out[code] = fallback[0]
    return out


def build(stocks, klines, industries, now=None):
    """stocks 携带实时报价；所有排名和形态只取对齐的完成日线。"""
    ks = {c: completed(v, now) for c, v in klines.items()}
    calendar = trading_calendar(ks)
    if len(calendar) < CORE_BARS:
        raise ValueError(f"共同日线不足{CORE_BARS}个交易日，保留上一份快照")
    asof = calendar[-1]
    wanted = calendar[-CORE_BARS:]
    metrics, dropped = {}, Counter()
    for code, bars in ks.items():
        bars = [b for b in bars if b["date"] <= asof]
        issue = core_window_issue(bars, calendar)
        if issue:
            dropped[issue] += 1
            continue
        m = day_metrics(bars, calendar)
        if m is None:
            dropped["invalid"] += 1
            continue
        metrics[code] = m
        ks[code] = bars
    contexts = industry_context(metrics, industries)
    own_strength, strength_reference_count = stock_strength.score(metrics, contexts, ks)
    out = []
    for source in stocks:
        code = source["code"]
        m = metrics.get(code)
        if not m:
            continue
        row = dict(source)
        for key in list(row):
            if key.startswith(("score_", "ign_", "emotion_")) or key in {
                    "risk_drag", "short_entry_ok", "swing_entry_ok", "sec_ctx", "ex_sec20",
                    "fund_asof", "fund_positive_all", "fund_state", "axis_group",
                    "trend_assist", "emotion_assist", "board_assist", "roles", "industry_rank20"} or key in {
                        "fund3_yi", "fund5_yi", "fund10_yi"}:
                row.pop(key, None)
        fund = (row.get("factors") or {}).get("fund")
        row.update(m)
        row.update(contexts[code])
        row.update(own_strength[code])
        if row["primary_industry"]:
            row["industry"] = list(dict.fromkeys([row["primary_industry"]] + (row.get("industry") or [])))
        row["downtrend"] = int(not row["trend_aligned"])
        row["factors"] = {"fund": fund}
        row["risk_notes"] = []
        if not row["trend_aligned"]:
            row["risk_notes"].append("5/10/20日线未多头排列且20日线上行")
        elif not row["trend_online"]:
            row["risk_notes"].append("收盘失守10日线")
        # 完成日线强度及其位置只使用判断日收盘；盘中MA10距离由 intraday.py 独立计算。
        row["daily_fixed_dist_atr"] = m["dist_atr"]
        row["live_dist_atr"] = None
        row["overheated"] = False
        completed_hot = m["dist_atr"] is not None and m["dist_atr"] > config.SIMPLE_STRENGTH["max_dist_atr"]
        if row["trend_online"]:
            if completed_hot:
                row["trend_stage"] = "日线加速偏离"
            elif row["touch_state"] in ("站回待确认", "跌破后收复"):
                row["trend_stage"] = "日线回踩待确认"
            elif not row["trend_online_prev"]:
                row["trend_stage"] = "日线初步转强"
            else:
                row["trend_stage"] = "日线趋势延续"
        elif row["trend_online_prev"] or row["trend_aligned"]:
            row["trend_stage"] = "日线结构转弱"
        elif row["ma5"] > row["ma10"] and m["signal_close"] >= row["ma10"]:
            row["trend_stage"] = "日线初步转强"
        else:
            row["trend_stage"] = "日线趋势未成立"
        if row.get("limit_today"):
            row["risk_notes"].append("现价接近涨停，需确认成交条件")
        if row["industry_breadth"] is None:
            row["risk_notes"].append("行业归属或有效同伴不足，广度未知")
        out.append(row)
    for row in out:
        row["score"] = row["stock_strength_percentile"]
        row["strength_percentile"] = row["stock_strength_percentile"]
        row["factors"].update(rs=row["stock_strength_percentile"], sector=row["industry_breadth"])
        row["watch_candidate"] = bool(row["trend_online"])
        row["industry_supported"] = bool(row["industry_breadth"] is not None and row["industry_breadth"] >= 50)
        row["historical_pullback_shape"] = row.get("touch_state") in config.CONFIRMED_PULLBACK_STATES
        row["entry_watch"] = False  # 盘中MA10、跌幅与成交限制由 intraday.enrich 二次约束。
    out.sort(key=lambda r: (-r["stock_strength_score"], r["code"]))
    for i, row in enumerate(out, 1):
        row["rank"] = i
    stock_strength.attach_history(out, wanted[-2], wanted[-6])
    return out, {
        "version": VERSION, "asof": asof, "rank_basis": "日线进攻分：5/10/20日权重50/30/20；各周期60%绝对推进+40%相对速度；盘中暂态进攻另算",
        "trend_basis": "完成日MA5>MA10>MA20；完成日MA20较上一完成日上升；完成日收盘不低于MA10",
        "touch_basis": "历史形态：最近3个完成日线的回踩状态；当前候选另核验盘中MA10、风险与位置",
        "breadth_basis": "当前行业映射；同伴站上20日线比例；排除自身；不参与排名",
        "completed_samples": len(metrics), "ranked_samples": len(out), "dropped": dict(dropped),
        "core_required_bars": CORE_BARS, "reference60_required_bars": 61,
        "persistent_criterion": stock_strength.PERSISTENT_CRITERION,
        "industry_covered": sum(r["industry_breadth"] is not None for r in out),
        "watch_count": sum(r["watch_candidate"] for r in out),
        "strength_reference_count": strength_reference_count,
        "strength_market_benchmark_count": len(metrics),
        "strength_version": stock_strength.VERSION,
        "strength_weights": stock_strength.WEIGHTS,
        "attack_parameters": stock_strength.attack_model.PARAMETERS,
        "persistent_strong_count": sum(r["persistent_strong"] for r in out),
        "recent_improving_count": sum(r["recent_improving"] for r in out),
        "high_fading_count": sum(r["high_fading"] for r in out),
        "entry_watch_count": sum(r["entry_watch"] for r in out),
        "min_industry_peers": config.SIMPLE_STRENGTH["min_industry_peers"],
    }


def daily_advice(snap):
    stocks = snap["stocks"]
    def small(s):
        return {"code": s["code"], "name": s["name"], "chg": s.get("change_pct"),
                "board": s.get("board_name"), "score": s["score"], "themes": (s.get("boards") or [])[:2]}
    watches = sorted((s for s in stocks if s["watch_candidate"]),
                     key=lambda s: (-s.get("stock_strength_score", 0), s["code"]))
    groups = [{"label": name, "hint": hint, "stocks": [small(s) for s in watches if predicate(s)][:6]}
              for name, hint, predicate in [
                  ("当前回踩候选", "历史完成日线形态成立；现价仍守盘中MA10，且风险、过热与成交限制通过；固定日线MA10另见个股详情", lambda s: s.get("current_pullback_candidate", False)),
                  ("日线站回待确认", "最近完成日线触及后收盘站回，但未确认向上；不代表盘中收复", lambda s: s["touch_state"] == "站回待确认"),
                  ("历史日线跌破后收复", "完成日线此前收盘失守MA10、后续重新站回；当前盘中状态以个股趋势和风险字段为准", lambda s: s["touch_state"] == "跌破后收复"),
                  ("行业支持", "同行有效同伴至少半数站上20日线", lambda s: s["industry_supported"])]]
    risks = [{"text": s["name"] + "：" + "；".join(s["risk_notes"]), "tone": "warn"}
             for s in watches if s["overheated"] or s.get("limit_today")
             or s.get("intraday_risk_flags")][:5]
    hold = [{"code": s["code"], "name": s["name"], "chg": s.get("change_pct"),
             "board": s.get("board_name"), "why": s["risk_notes"]}
            for s in stocks if s["risk_notes"]]
    return {"generated_at": snap.get("generated_at"), "session": snap.get("session"),
            "items": [
                {"kind": "watch", "icon": "◇", "title": "趋势观察池", "summary": f"{len(watches)}只 · 排列与回踩状态分开", "groups": groups},
                {"kind": "risk", "icon": "△", "title": "位置风险", "summary": "风险不抵消排名，也不由高排名抵消",
                 "points": risks or [{"text": "当前观察池未触发既定位置风险阈值。", "tone": "flat"}]},
                {"kind": "basis", "icon": "◉", "title": "判断口径", "summary": snap["strength_model"]["asof"] + " 完成日线",
                 "points": [{"text": "MA5>MA10>MA20且MA20上行；收盘守住MA10。5/10/20日实际进攻评分；整理、反包、突破和风险分别展示。", "tone": "flat"},
                            {"text": "回踩允许盘中破10日线，收盘站回；资金3/5/10日只作辅助确认，缺失标未知。", "tone": "flat"}]},
            ], "hold_watch": hold}


def breakout_alerts(stocks):
    """兼容旧调用名，但只发布通过盘中约束的当前回踩候选。"""
    return [{"type": "当前回踩候选", "level": "mid", "target": s["code"],
             "text": (f"{s['name']}：历史日线形态{s['touch_state']}；当前价守住盘中MA10，"
                      "且风险、过热与成交限制检查通过。并非买点；固定日线MA10与逐股报价时间见个股详情")}
            for s in stocks if s.get("current_pullback_candidate")]


def save_observation(snap):
    import json
    folder = config.CACHE_DIR / "strength_history"
    folder.mkdir(exist_ok=True)
    observed_at = snap.get("rebuilt_at") or snap["generated_at"]
    record = {"observed_at": observed_at, "model": snap["strength_model"],
              "market_emotion": snap.get("market_emotion"),
              "axis_counts": snap.get("axis_counts"),
              "mapping_basis": "观察时可得的行业映射，不能冒充更早的历史归属",
              "stocks": [{k: s.get(k) for k in ("code", "ret20", "score", "ma5", "ma10", "ma20",
                          "stock_strength_score", "stock_strength_percentile", "stock_strength_motion",
                          "strength_delta1", "strength_delta5", "stock_strength_parts",
                          "trend_aligned", "trend_online", "trend_stage", "axis_group", "emotion_heat",
                          "emotion_acceptance", "emotion_strong", "fund3_yi", "fund5_yi", "fund10_yi",
                          "touch_state", "primary_industry", "industry_peers", "industry_above20",
                          "industry_breadth", "industry_peer_trend_pct", "industry_peer_trend_delta_pp",
                          "industry_ex_top2_trend_pct", "trend_assist", "emotion_assist", "roles",
                          "entry_state", "risk_notes")}
                         for s in snap["stocks"]]}
    # 每个观察日一份；历史日线日期与首次观察日期分别保留。
    date = observed_at[:10]
    config.atomic_write_text(folder / f"{date}.json", json.dumps(record, ensure_ascii=False))
