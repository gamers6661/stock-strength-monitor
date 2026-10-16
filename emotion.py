"""主板报价池的短期交易行为；与均线趋势资格相互独立。"""
from collections import Counter, defaultdict
from datetime import datetime
from statistics import median

import config
import intraday


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct_median(rows, key):
    vals = [x[key] for x in rows if x.get(key) is not None]
    return round(median(vals), 2) if vals else None


def build(quotes, klines, stock_codes, industries, now=None):
    """返回市场情绪、全报价池逐股证据和主榜之外的情绪候选。"""
    now = now or datetime.now()
    quote_days = {c: intraday.quote_day(q.get("quote_at") or q.get("ts"), now)
                  for c, q in quotes.items()}
    dates = Counter(day for day in quote_days.values() if day)
    day = dates.most_common(1)[0][0] if dates else now.strftime("%Y-%m-%d")
    historical_counts = Counter(b["date"] for bars in klines.values() for b in bars if b["date"] < day)
    common_floor = max(historical_counts.values(), default=0) * 0.5
    history_days = sorted(d for d, count in historical_counts.items() if count >= common_floor)
    prior_days = history_days[-2:]
    eligible = {c: q for c, q in quotes.items()
                if quote_days.get(c) == day and _num(q.get("amount_wan")) > 0
                and _num(q.get("price")) > 0 and _num(q.get("last_close")) > 0}
    turn = [_num(q.get("turnover_pct")) for q in eligible.values() if _num(q.get("turnover_pct")) > 0]
    median_turn = median(turn) if turn else 0.0
    detail = {}
    for code, q in eligible.items():
        price, prev_close = _num(q.get("price")), _num(q.get("last_close"))
        open_price = _num(q.get("open")) or prev_close
        high, low = _num(q.get("high")), _num(q.get("low"))
        change = _num(q.get("change_pct"))
        limit = config.limit_pct_for(code, q.get("list_days"))
        if limit >= 900:
            limit_up = None
        else:
            limit_up = _num(q.get("limit_up")) or prev_close * (1 + _num(q.get("limit_pct"), 10) / 100)
        at_limit = bool(limit_up and price >= limit_up * 0.998)
        touched = bool(limit_up and high >= limit_up * 0.998)
        prior = [b for b in (klines.get(code) or []) if b["date"] < day]
        comparable = bool(len(prior) >= 2 and len(prior_days) == 2
                          and [b["date"] for b in prior[-2:]] == prior_days and prior[-2]["close"])
        prev_return = (prior[-1]["close"] / prior[-2]["close"] - 1) * 100 if comparable else None
        previous_limit = config.limit_pct_for(code, max(0, int(q.get("list_days")) - 1)
                                                   if q.get("list_days") is not None else None)
        # limit_pct_for 已包含因最小价位取整而留的容差。
        yesterday_limit = bool(comparable and previous_limit < 900 and prev_return >= previous_limit)
        yesterday_strong = bool(comparable and prev_return >= 5)
        active = bool(at_limit or change >= 5 and _num(q.get("turnover_pct")) >= median_turn
                      and price >= open_price)
        carry = bool(yesterday_limit and change > 0 and price >= open_price)
        strong = bool(active or carry)
        close_position = (price - low) / (high - low) if high > low else None
        if at_limit:
            heat = "连板" if yesterday_limit else "首板或再涨停"
        elif active:
            heat = "大幅活跃"
        else:
            heat = "平稳"
        if touched and not at_limit:
            acceptance = "触板未封"
        elif carry:
            acceptance = "前日涨停承接"
        elif yesterday_limit and change <= 0:
            acceptance = "前日涨停转弱"
        elif active and close_position is not None and close_position < 0.35:
            acceptance = "冲高回落"
        elif active:
            acceptance = "现价仍强"
        else:
            acceptance = "待观察"
        if touched and not at_limit:
            emotion_risk = "触板未封"
        elif yesterday_strong and change <= -5:
            emotion_risk = "前日强势大跌"
        elif yesterday_limit and change <= 0:
            emotion_risk = "前日涨停转弱"
        elif active and close_position is not None and close_position < 0.35:
            emotion_risk = "冲高回落"
        elif change <= -config.board_of(code)[2] * config.INTRADAY_RISK["near_limit_down_ratio"]:
            emotion_risk = "接近跌停"
        elif change <= -config.board_of(code)[2] * config.INTRADAY_RISK["large_drop_limit_ratio"]:
            emotion_risk = "大幅下跌"
        else:
            emotion_risk = "未见明显短线风险"
        prior_three_ok = bool(len(prior) >= 3 and len(history_days) >= 3
                              and [b["date"] for b in prior[-3:]] == history_days[-3:])
        active_days3 = (int(strong) + sum((prior[i]["close"] / prior[i - 1]["close"] - 1) * 100 >= 5
                                          for i in (-2, -1)) if prior_three_ok else None)
        detail[code] = {
            "emotion_strong": strong, "emotion_heat": heat, "emotion_acceptance": acceptance,
            "emotion_risk": emotion_risk, "emotion_active_days3": active_days3,
            "emotion_limit": at_limit, "emotion_touched": touched,
            "emotion_yesterday_limit": yesterday_limit, "emotion_yesterday_strong": yesterday_strong,
            "emotion_comparable": comparable, "emotion_close_position": round(close_position, 2) if close_position is not None else None,
            "emotion_open_gap_pct": round((open_price / prev_close - 1) * 100, 2),
            "emotion_intraday_pct": round((price / open_price - 1) * 100, 2),
            "emotion_today_pct": change,
        }
    comparable_rows = [v for v in detail.values() if v["emotion_comparable"]]
    yesterday_limit = [v for v in comparable_rows if v["emotion_yesterday_limit"]]
    yesterday_strong = [v for v in comparable_rows if v["emotion_yesterday_strong"]]
    today_limit = sum(v["emotion_limit"] for v in detail.values())
    today_limit_comparable = sum(v["emotion_limit"] for v in comparable_rows)
    failed = sum(v["emotion_touched"] and not v["emotion_limit"] for v in detail.values())
    median_feedback = _pct_median(yesterday_limit, "emotion_today_pct")
    coverage = len(comparable_rows) / len(detail) if detail else 0
    finished = (day < now.strftime("%Y-%m-%d") or
                day == now.strftime("%Y-%m-%d") and (now.hour, now.minute) >= (15, 5))
    for v in detail.values():
        v["emotion_provisional"] = not finished
    if not finished:
        state = "盘中观察"
    elif coverage < 0.8 or len(yesterday_limit) < 5:
        state = "反馈样本不足"
    elif today_limit_comparable > len(yesterday_limit) and median_feedback is not None and median_feedback > 0:
        state = "扩散"
    elif today_limit_comparable >= len(yesterday_limit) and median_feedback is not None and median_feedback >= 0:
        state = "回暖"
    elif today_limit_comparable < len(yesterday_limit) and median_feedback is not None and median_feedback < 0:
        state = "退潮"
    else:
        state = "分歧"
    market = {
        "date": day, "state": state, "provisional": not finished,
        "scope": "当前主板报价池；停牌和无成交不入分母；涨停按报价接近涨停价判定，盘中仅为暂态",
        "pool": len(quotes), "traded": len(detail), "comparable": len(comparable_rows),
        "limit_up": today_limit, "limit_up_comparable": today_limit_comparable,
        "limit_up_yesterday": len(yesterday_limit), "first_board": sum(v["emotion_limit"] and not v["emotion_yesterday_limit"] for v in comparable_rows),
        "continued_board": sum(v["emotion_limit"] and v["emotion_yesterday_limit"] for v in comparable_rows),
        "advance_pct": round(sum(v["emotion_limit"] for v in yesterday_limit) / len(yesterday_limit) * 100, 1) if yesterday_limit else None,
        "touched_unsealed": failed, "limit_down": sum(_num(quotes[c].get("change_pct")) <= -config.limit_pct_for(c, quotes[c].get("list_days"))
                                                    for c in detail),
        "yesterday_limit_median_pct": median_feedback,
        "yesterday_limit_up_pct": round(sum(v["emotion_today_pct"] > 0 for v in yesterday_limit) / len(yesterday_limit) * 100, 1) if yesterday_limit else None,
        "yesterday_limit_gap_median_pct": _pct_median(yesterday_limit, "emotion_open_gap_pct"),
        "yesterday_limit_intraday_median_pct": _pct_median(yesterday_limit, "emotion_intraday_pct"),
        "yesterday_strong_count": len(yesterday_strong),
        "yesterday_strong_median_pct": _pct_median(yesterday_strong, "emotion_today_pct"),
        "yesterday_strong_big_loss_pct": round(sum(v["emotion_today_pct"] <= -5 for v in yesterday_strong) / len(yesterday_strong) * 100, 1) if yesterday_strong else None,
        "active_count": sum(v["emotion_strong"] for v in detail.values()),
        "basis": "状态是初始描述标签；比较涨停数量只用历史可比样本，盘中不作完成日判断。",
    }
    groups = defaultdict(list)
    for code in detail:
        name = industries.get(code)
        if name:
            groups[name].append(code)
    market_active_pct = market["active_count"] / len(detail) * 100 if detail else 0.0
    for code, v in detail.items():
        peers = [c for c in groups.get(industries.get(code), []) if c != code]
        active_peers = sum(detail[c]["emotion_strong"] for c in peers)
        limit_peers = sum(detail[c]["emotion_limit"] for c in peers)
        previous_limit_peers = sum(detail[c]["emotion_yesterday_limit"] for c in peers)
        comparable_peers = sum(detail[c]["emotion_comparable"] for c in peers)
        v["emotion_peer_count"] = len(peers)
        v["emotion_peer_active"] = active_peers
        v["emotion_peer_limit"] = limit_peers
        v["emotion_peer_yesterday_limit"] = previous_limit_peers
        v["emotion_peer_comparable"] = comparable_peers
        v["emotion_peer_active_pct"] = round(active_peers / len(peers) * 100, 2) if len(peers) >= 5 else None
        v["emotion_peer_vs_market_pp"] = round(v["emotion_peer_active_pct"] - market_active_pct, 2) if v["emotion_peer_active_pct"] is not None else None
    extra = []
    for code, v in detail.items():
        if code in stock_codes or not v["emotion_strong"]:
            continue
        q = quotes[code]
        extra.append({"code": code, "name": q.get("name") or code, "price": q.get("price"),
                      "change_pct": q.get("change_pct"), "board_name": q.get("board_name"),
                      "primary_industry": industries.get(code), "trend_stage": "趋势数据不足",
                      "trend_online": None, "axis_group": "情绪活跃·趋势未核验", **v})
    extra.sort(key=lambda s: (-_num(s.get("change_pct")), s["code"]))
    market["emotion_only_count"] = len(extra)
    return market, detail, extra


def enrich_stocks(stocks, detail, market):
    """双轴和行业助攻并列展示；没有盘中先后证据时不宣称带动关系。"""
    market_active_pct = market["active_count"] / market["traded"] * 100 if market.get("traded") else 0.0
    by_industry = defaultdict(list)
    for row in stocks:
        if row.get("primary_industry"):
            by_industry[row["primary_industry"]].append(row)
    ranks = {}
    for name, members in by_industry.items():
        for index, row in enumerate(sorted(members, key=lambda r: (-r["ret20"], r["code"])), 1):
            ranks[row["code"]] = (index, len(members))
    for row in stocks:
        em = detail.get(row["code"])
        known = em is not None
        em = em or {}
        row.update(em)
        row.setdefault("emotion_strong", None)
        row.setdefault("emotion_heat", "数据不足")
        row.setdefault("emotion_acceptance", "数据不足")
        row.setdefault("emotion_risk", "数据不足")
        row.setdefault("emotion_active_days3", None)
        trend = bool(row["trend_online"])
        active = bool(row["emotion_strong"])
        row["axis_group"] = ("情绪数据不足" if not known else
                             "情绪活跃·趋势在线" if trend and active else
                             "情绪活跃·趋势未在线" if active else
                             "趋势在线·情绪平稳" if trend else "趋势未在线·情绪平稳")
        peers = row.get("industry_peers") or 0
        peer_trend = row.get("industry_peer_trend_pct")
        trend_market = row.get("market_trend_pct")
        trend_delta = row.get("industry_peer_trend_delta_pp")
        stripped = row.get("industry_ex_top2_trend_pct")
        excess5 = row.get("industry_ret5_ex_market")
        own_p = row.get("stock_strength_percentile") or 0
        own_excess = row.get("ret5_ex_industry")
        own_leads = (own_p >= 75 and row.get("ret5", 0) > 0 and row.get("ret20", 0) > 0
                     and own_excess is not None and own_excess >= 2)
        own_lags = (own_p < 40 or own_excess is not None and own_excess <= -2)
        row["industry_stock_relation"] = ("个股相对领先" if own_leads else
                                           "个股落后" if own_lags else "个股相对表现待确认")
        if peers < 5 or peer_trend is None or stripped is None or excess5 is None:
            row["industry_trend_state"] = "数据不足"
            trend_assist = "数据不足"
        else:
            spread = (peer_trend > trend_market and stripped > trend_market
                      and trend_delta > 0 and excess5 > 0)
            weak = peer_trend <= trend_market and excess5 <= 0
            shrinking = trend_delta < 0 and excess5 < 0
            rising_days = row.get("industry_peer_trend_rising_days2") or 0
            row["industry_trend_state"] = ("收缩" if shrinking else
                                            "持续扩散" if spread and rising_days == 2 else
                                            "扩散初现" if spread
                                            else "同行偏弱" if weak else "未见扩散")
            if shrinking and own_leads:
                trend_assist = "个股相对领先｜行业收缩"
            elif shrinking:
                trend_assist = "联动转弱"
            elif trend and spread and own_p >= 60 and row.get("ret5", 0) > 0:
                trend_assist = "共振扩散"
            elif own_leads and weak:
                trend_assist = "核心独强"
            elif spread:
                trend_assist = "板块强、个股落后" if own_lags else "板块强、个股待确认"
            else:
                trend_assist = "助攻不明确"
        peer_emotion = row.get("emotion_peer_active_pct")
        peer_limit = row.get("emotion_peer_limit")
        peer_prior_limit = row.get("emotion_peer_yesterday_limit")
        peer_history_ok = (row.get("emotion_peer_count") or 0) > 0 and (
            (row.get("emotion_peer_comparable") or 0) / row["emotion_peer_count"] >= 0.8)
        if not known or peer_emotion is None:
            emotion_assist = "数据不足"
        elif active and peer_history_ok and peer_emotion > market_active_pct and peer_limit >= 2 and peer_limit > peer_prior_limit:
            emotion_assist = "共振扩散"
        elif (active and peer_emotion <= market_active_pct
              and row.get("emotion_acceptance") in ("前日涨停承接", "现价仍强")):
                emotion_assist = "核心独强"
        elif not active and peer_emotion > market_active_pct and peer_limit:
            emotion_assist = "板块强、个股待确认"
        elif row.get("emotion_yesterday_limit") and row.get("emotion_acceptance") == "前日涨停转弱" and not peer_limit:
            emotion_assist = "联动转弱"
        else:
            emotion_assist = "助攻不明确"
        row["trend_assist"] = trend_assist
        row["emotion_assist"] = emotion_assist
        row["board_assist"] = (f"趋势 {trend_assist}｜情绪 {emotion_assist}" if trend or active
                               else "两轴未强，助攻仅供背景观察")
        rank, industry_size = ranks.get(row["code"], (None, 0))
        row["industry_rank20"] = rank
        roles = []
        if rank == 1 and industry_size >= 5:
            roles.append("20日领涨")
        if (trend and row["ret20"] > 0 and row.get("ret5", 0) > 0
                and (row.get("stock_strength_percentile") or 0) >= 75
                and rank is not None and rank <= 3):
            roles.append("趋势核心候选")
        if (row.get("emotion_limit") and row.get("emotion_yesterday_limit")) or (
                row.get("emotion_yesterday_limit") and row.get("emotion_acceptance") == "前日涨停承接"):
            roles.append("情绪核心候选")
        row["roles"] = roles or ["一般成员"]
    return stocks
