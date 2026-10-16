"""进攻模型：实际推进和相对速度计分，形态、风险与成交条件各自判断。"""
from bisect import bisect_left, bisect_right
import math
from datetime import datetime


VERSION = "趋势进攻模型1"
LIVE_VERSION = "盘中价格进攻模型3"
LIVE_WEIGHTS = {"price": 1.0}
WEIGHTS = {"attack5": .50, "attack10": .30, "attack20": .20}
LABELS = {"attack5": "5日攻击速度", "attack10": "10日推进", "attack20": "20日涨幅基础"}
# 初版研究参数，固定公布；不能为单只股票更改或使用未来收益寻优。
PARAMETERS = {"absolute_weight": .60, "relative_weight": .40,
              "full_score_returns": {5: 8.0, 10: 12.0, 20: 20.0},
              "a_score_min": 65.0, "b_score_min": 45.0,
              "a_returns": {5: 5.0, 10: 8.0, 20: 12.0},
              "b_returns": {5: 3.0, 10: 5.0, 20: 8.0},
              "past_impulse5_min": 8.0, "day_attack_min": 3.0}
CRITERION = "完成日趋势在线；进攻分≥65；5日和20日上涨；5日≥5%/10日≥8%/20日≥12%至少一项。无固定名额；整理和风险独立展示"


def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def percentiles(values):
    ordered = sorted(v for v in values.values() if number(v))
    return {c: (None if not number(v) else 50.0 if len(ordered) == 1 else
                round((bisect_left(ordered, v) + bisect_right(ordered, v) - 1)
                      / 2 / (len(ordered)-1) * 100, 2)) for c, v in values.items()}


def momentum_scores(returns):
    """完整三周期才评分；绝对收益为负时该项绝对推进为0，不能抗跌代替上涨。"""
    valid = {c: r for c, r in returns.items() if all(number(r.get(n)) for n in (5, 10, 20))}
    ranks = {n: percentiles({c: r[n] for c, r in valid.items()}) for n in (5, 10, 20)}
    out = {}
    for code, r in valid.items():
        parts, evidence = {}, {}
        for n in (5, 10, 20):
            absolute = max(0.0, min(100.0, r[n] / PARAMETERS["full_score_returns"][n] * 100))
            parts[f"attack{n}"] = round(PARAMETERS["absolute_weight"] * absolute
                                         + PARAMETERS["relative_weight"] * ranks[n][code], 2)
            evidence[f"attack{n}"] = (f"{n}日实际涨幅 {r[n]:+.2f}%；绝对推进 {absolute:.1f}分，"
                                       f"同口径样本分位 {ranks[n][code]:.1f}；本项60%绝对推进+40%相对速度")
        out[code] = {"score": round(sum(parts[k]*WEIGHTS[k] for k in WEIGHTS), 2),
                     "parts": parts, "evidence": evidence,
                     "percentiles": {n: ranks[n][code] for n in (5, 10, 20)}}
    return out


def tier(score, returns, trend, impulse5=None):
    """A是进攻强度，B含强股整理；平稳慢涨不能靠低回撤升A。"""
    if not trend or not number(score) or not all(number(returns.get(n)) for n in (5, 10, 20)):
        return None
    a_move = any(returns[n] >= limit for n, limit in PARAMETERS["a_returns"].items())
    b_move = any(returns[n] >= limit for n, limit in PARAMETERS["b_returns"].items())
    if score >= PARAMETERS["a_score_min"] and a_move and returns[5] > 0 and returns[20] > 0:
        return "A"
    if score >= PARAMETERS["b_score_min"] and returns[20] > 0 and (
            b_move or (number(impulse5) and impulse5 >= PARAMETERS["past_impulse5_min"])):
        return "B"
    return "C"


def price_pattern(bars, price, ma10, day_change, *, live=False):
    """bars只含判断日之前的历史K；现价突破与日内曾触及分开。无量能推断。"""
    if len(bars) < 20 or not all(number(v) and v > 0 for v in (price, ma10)):
        return {"event": None, "stage": "形态待核验", "high20": None, "high3": None}
    high20, high3 = max(b["high"] for b in bars[-20:]), max(b["high"] for b in bars[-3:])
    previous = bars[-1]
    recent_down = any(bars[i]["close"] < bars[i-1]["close"] for i in range(len(bars)-3, len(bars)))
    # 整理依据：此前有实际回落，最近三个完成日收盘各守各自MA10。
    structure_holds = len(bars) >= 12 and all(
        bars[i]["close"] >= sum(b["close"] for b in bars[i-9:i+1])/10
        for i in range(len(bars)-3, len(bars)))
    consolidation = recent_down and structure_holds
    positive = number(day_change) and day_change > 0
    event = None
    if price >= ma10 and positive:
        if price > high20:
            event = "整理突破" if consolidation else "20日新高突破"
        elif previous["close"] < previous["open"] and price >= previous["open"]:
            event = "反包修复"
        elif price > high3:
            event = "整理再启动" if consolidation else "短期突破"
    stage = event or ("趋势整理" if price >= ma10 and consolidation else
                      "趋势推进" if price >= ma10 else "MA10结构受损")
    return {"event": event, "stage": stage, "high20": high20, "high3": high3,
            "consolidation": consolidation, "completed_structure_holds": structure_holds,
            "confirmed": not live,
            "note": ("盘中现价条件成立，待收盘确认" if live and event else
                     "完成日收盘形态" if event else "价格结构描述；不代表成交确认")}


def fund_confirmation(row, meta, captured_at):
    """仅保留旧字段的空值合同；资金流不再进入任何当前判断。"""
    return {"score": None, "weight": 0.0, "ratio": None,
            "status": "已停用", "source": None, "at": None}


def enrich(snap, quotes, price_contexts, previous_snapshot=None):
    """使用均线模块已核验的同一份价格上下文；禁止重新猜测复权尺度。"""
    rows = (snap.get("stocks") or []) + (snap.get("coverage_catalog") or [])
    normal = snap.get("session") in ("早盘", "午盘", "尾盘")
    observation_session = normal or snap.get('session') == '午间休市'
    returns = {}
    eligible = {}
    for row in rows:
        code = str(row["code"])
        row.update(attack_model_version=LIVE_VERSION, live_attack_score=None,
                   live_attack_price_score=None, live_attack_price_tier=None,
                   live_attack_fund=fund_confirmation(row, snap.get("fund_meta") or {}, snap.get("attack_assessment_at") or snap.get("generated_at")),
                   live_attack_parts=None, live_attack_tier=None, live_attack_event=None,
                   live_attack_stage="待核验", attack_watch_candidate=False, attack_observation_candidate=False,
                   attack_risk_clear=False, live_attack_returns=None,
                   live_attack_status="本轮报价或价格口径不可判断", live_attack_pattern=None)
        context = price_contexts.get(code) or {}
        q = quotes.get(code) or {}
        bars = context.get("aligned_bars") or []
        if ((not (normal and row.get("intraday_quote_fresh") is True) and row.get('intraday_observation_available') is not True) or context.get("valid") is not True
                or len(bars) < 20 or not number(q.get("price")) or q["price"] <= 0
                or row.get("trade_status") in ("no_trade", "trade_recovered_wait_daily")):
            continue
        returns[code] = {n: (q["price"]/bars[-n]["close"]-1)*100 for n in (5, 10, 20)}
        eligible[code] = row
    scores = momentum_scores(returns)
    for code, row in eligible.items():
        item, q = scores[code], quotes[code]
        context = price_contexts[code]
        price_key = tier(item["score"], returns[code], row.get("intraday_trend_ok") is True,
                   row.get("past_impulse5_pct"))
        combined = item["score"]
        key = tier(combined, returns[code], row.get("intraday_trend_ok") is True, row.get("past_impulse5_pct"))
        pattern = price_pattern(context["aligned_bars"], q["price"],
                                row.get("intraday_ma10_exact"), q.get("change_pct"), live=True)
        if key in ("A", "B") and pattern["stage"] == "趋势整理":
            pattern["stage"] = "强股整理"
        flags = row.get("intraday_risk_flags") or []
        severe = row.get("intraday_serious_weakness") is not False
        positive_attack = number(q.get("change_pct")) and q["change_pct"] > 0 and (
            q["change_pct"] >= PARAMETERS["day_attack_min"] or pattern["event"] is not None)
        watch = normal and key == "A" and positive_attack and not severe
        observation = observation_session and key == 'A' and positive_attack and not severe
        row.update(live_attack_score=combined, live_attack_price_score=item["score"],
                   live_attack_price_tier=price_key, live_attack_parts=item["parts"],
                   live_attack_tier=key, live_attack_returns={str(n): round(v, 3) for n, v in returns[code].items()},
                   live_attack_event=pattern["event"], live_attack_stage=pattern["stage"],
                   live_attack_pattern=pattern, live_attack_status="盘中暂态，待收盘确认" if normal else "上午收市判断，截至11:30；下午继续跟踪" if snap.get('session') == '午间休市' else "收盘报价参考",
                   attack_watch_candidate=watch,
                   attack_observation_candidate=observation,
                   attack_risk_clear=bool(watch and not flags and not row.get("intraday_trade_restriction")
                                          and row.get("intraday_risk_level") == "低"
                                          and row.get("overheated") is False))
    # 午休已重评的行使用收市判断；缺失行及其他冻结阶段保留旧观察，并标明来源。
    if snap.get("session") in ("午间休市", "非交易日", "盘前", "集合竞价"):
        old_rows = ((previous_snapshot or {}).get("stocks") or []) + ((previous_snapshot or {}).get("coverage_catalog") or [])
        old_by_code = {str(r["code"]): r for r in old_rows
                       if r.get("attack_model_version") in (VERSION, LIVE_VERSION)}
        for row in rows:
            if row['code'] in eligible:
                continue
            if row.get('intraday_observation_available') is True:
                # 报价有效但均线尺度/历史窗口未通过时，不把旧进攻档贴在新报价时间上。
                row['live_attack_status'] = row.get('intraday_price_basis_reason') or '本轮进攻依据待核验'
                continue
            old = old_by_code.get(str(row["code"])) or {}
            for k in ("live_attack_score", "live_attack_tier", "live_attack_returns",
                      "live_attack_event", "live_attack_stage", "live_attack_pattern",
                      "live_attack_price_score", "live_attack_price_tier", "live_attack_fund"):
                if old.get(k) is not None:
                    row[k] = old[k]
            if old and old.get("attack_model_version") == VERSION:
                row["live_attack_price_score"] = old.get("live_attack_score")
                row["live_attack_price_tier"] = old.get("live_attack_tier")
                row["live_attack_fund"] = {"score": None, "weight": 0.0, "ratio": None,
                                           "status": "已停用",
                                           "source": None, "at": None}
            row["live_attack_status"] = "历史观察，当前阶段未重新判断"
    watched = sorted((r for r in rows if r["attack_watch_candidate"]),
                     key=lambda r: (-r["live_attack_score"], -r.get("change_pct", 0), r["code"]))
    shown = sorted((r for r in rows if r.get('attack_observation_candidate')),
                   key=lambda r: (-r['live_attack_score'], -r.get('change_pct',0), r['code'])) if snap.get('session') == '午间休市' else watched
    fields = ("code", "name", "price", "change_pct", "intraday_quote_at", "intraday_judgment_at", "live_attack_score",
              "live_attack_tier", "live_attack_stage", "live_attack_returns", "trend_tier",
              "intraday_risk_flags", "intraday_risk_level", "intraday_trade_restriction", "attack_risk_clear",
              "live_attack_price_score", "live_attack_price_tier", "live_attack_fund")
    monitor_rows = [dict({k: r.get(k) for k in fields},
                         trend_tier=r.get("daily_attack_tier", r.get("trend_tier"))) for r in shown]
    retained = False
    if snap.get('session') == '午间休市' and scores:
        retained = True
    elif snap.get("session") in ("午间休市", "非交易日", "盘前", "集合竞价"):
        old_board = (previous_snapshot or {}).get("attack_monitor") or {}
        if old_board.get("version") in (VERSION, LIVE_VERSION):
            monitor_rows = old_board.get("rows") or []
            retained = True
    snap["attack_monitor"] = {"version": LIVE_VERSION, "session": snap.get("session"),
                              "reference_version": LIVE_VERSION if snap.get('session') == '午间休市' and scores else (old_board.get("reference_version") or old_board.get("version") if retained else None),
                              "count": len(watched), "sample_count": len(scores),
                              "rows": monitor_rows, "retained": retained,
                              "parameters": PARAMETERS, "weights": LIVE_WEIGHTS,
                              "price_weights": WEIGHTS,
                              "criterion": "价格进攻达到暂态A；当日上涨≥3%或反包/突破，现价守住MA10且无严重转弱；MA5过热及成交限制另列"}
    return snap["attack_monitor"]


def retain_missing_observations(snap):
    """缺失报价保留最后有效进攻参考；真实新行情不达标时从监测退出。"""
    if snap.get('session') not in ('早盘','午间休市','午盘','尾盘'):
        return
    board=snap.get('attack_monitor') or {}
    shown=list(board.get('rows') or [])
    included={str(r['code']) for r in shown}
    day=str(snap.get('quote_capture_at') or '')[:10]
    for row in (snap.get('stocks') or [])+(snap.get('coverage_catalog') or []):
        last=row.get('intraday_last_judgment') or {}
        if (str(row['code']) in included or row.get('intraday_observation_available') is True
                or last.get('valid') is not True or last.get('attack') is not True
                or (last.get('fund') or {}).get('weight', 0) > 0
                or not day or str(last.get('at') or '')[:10]!=day or not number(last.get('attack_score'))):
            continue
        shown.append(dict(code=row['code'],name=row.get('name'),price=last.get('price'),
            change_pct=last.get('change'),intraday_quote_at=last.get('at'),intraday_judgment_at=last.get('at'),
            live_attack_score=last['attack_score'],live_attack_tier=last.get('attack_tier'),
            live_attack_stage=last.get('attack_stage'),live_attack_fund=last.get('fund'),
            trend_tier=row.get('daily_attack_tier',row.get('trend_tier')),
            intraday_risk_flags=last.get('flags') or [],intraday_risk_level=last.get('risk'),
            reference_only=True,attack_risk_clear=False))
    shown.sort(key=lambda r:(-r['live_attack_score'],str(r['code'])))
    board['rows']=shown
    board['reference_count']=sum(r.get('reference_only') is True for r in shown)
    if board['reference_count'] and board.get('sample_count')==0:
        board.update(retained=True,reference_version=LIVE_VERSION)
