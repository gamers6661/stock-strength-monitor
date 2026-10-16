# -*- coding: utf-8 -*-
"""打分编排层 —— 组装板块榜 / 个股榜 / 异动告警 / 数据快照

运行模式：
  full  : 全量重建（股票池 + 全部K线 + 板块），收盘后跑，约3-5分钟
  quick : 增量（读K线缓存 + 实时行情覆盖当日bar + 板块），盘中每5分钟
  close : 正式收盘日线更新，正式日线就绪即发布榜单
"""
import json
import math
import re
import time
from collections import Counter
from datetime import datetime
from contextlib import ExitStack, closing

import config
import classification
import board_center
import coverage
import datafeed as df
import emotion
import intraday
import close_monitor
import trend_consolidation
import wyckoff_structure
import session_context
import history_reference
import price_only
import stock_strength
import attack_model
import factors as F
import strength
import theme_assist
import radar
import scan_cache

CLOSE_REFRESH_VERSION = '收盘价格优先发布3'


class DataNotReady(RuntimeError):
    """本轮报价尚未就绪，保留上一份可展示的快照。

    这类"空快照"绝不能写入 —— 覆盖之后看板会被清空成"今天没有数据"，
    而用户其实只想看到上一份数据 + 新鲜度提示。
    """


def opening_quotes_ready(quotes, captured_at, session, pool_count):
    """沿用60%覆盖要求，开盘后的输入必须来自本段交易时间。"""
    floor = '13:00' if session in ('午盘', '尾盘') else '09:30'
    valid = 0
    for quote in quotes.values():
        try:
            at = datetime.fromisoformat(quote.get('quote_at') or '')
            amount = float(quote.get('amount_wan') or 0)
        except (TypeError, ValueError):
            continue
        age = (captured_at - at).total_seconds()
        if (amount > 0 and math.isfinite(amount) and at.date() == captured_at.date()
                and at.strftime('%H:%M') >= floor
                and -90 <= age <= config.INTRADAY['max_quote_age_seconds']):
            valid += 1
    minimum = max(100, int(pool_count * 0.6))
    if valid < minimum:
        raise DataNotReady(f'{floor} 开盘后报价尚未更新：{valid}/{len(quotes)} 只，'
                           f'需至少 {minimum} 只；保留上一份数据，稍后重试')
    return valid


def _merge_current_pool_quotes(pool, fresh_quotes):
    """每轮以最新名称复核风险警示，不能依赖最长六小时的股票池缓存。"""
    merged, excluded = {}, {}
    for code, fresh in fresh_quotes.items():
        cached = pool.get(code)
        if not cached:
            continue
        name = str(fresh.get("name") or cached.get("name") or "")
        if any(keyword in name for keyword in config.POOL["exclude_keywords"]):
            excluded[code] = name
            continue
        quote = dict(fresh)
        for key in ("board_type", "board_name", "limit_pct", "list_days", "is_new"):
            if key in cached:
                quote[key] = cached[key]
        merged[code] = quote
    return merged, excluded


def formal_histories(codes, conn=None):
    """只读取正式落库日线；实时行情合成bar不能成为历史参考。"""
    owned=conn is None
    conn=conn or df.db()
    try:return {c:df.load_kline(conn,'kline','code',c,limit=160) for c in codes}
    finally:
        if owned:conn.close()


def _auction_snapshot(previous_snapshot, mode, scan_started_at, boundary=None):
    """竞价结合完成日线与真实昨收背景判断，成交量确认保留正式证据门槛。"""
    old_rows = (previous_snapshot.get("stocks") or []) + (previous_snapshot.get("coverage_catalog") or [])
    if not old_rows:
        raise DataNotReady("集合竞价报价可获取，但尚无上一完成日快照可供展示")
    pool = df.build_pool(force=False)
    codes = sorted({str(row.get("code")) for row in old_rows if row.get("code")} & set(pool))
    quotes = df.realtime_quotes(codes)
    captured_at = datetime.now()
    intraday.intraday_path.save_acquisition(intraday.HISTORY_DIR, quotes, captured_at, df.session_label(captured_at), boundary)
    age_limit = config.INTRADAY["max_quote_age_seconds"]
    future_limit = config.INTRADAY["max_quote_future_seconds"]
    candidate = {}
    for code, quote in quotes.items():
        at = intraday.parse_quote_timestamp(quote.get("ts"), captured_at)
        price = num(quote.get("price"))
        if not at or at.date() != captured_at.date() or not math.isfinite(price) or price <= 0:
            continue
        minute = at.hour * 60 + at.minute
        age = (captured_at - at).total_seconds()
        if not (9 * 60 + 15 <= minute <= 9 * 60 + 25 and -future_limit <= age <= age_limit):
            continue
        candidate[code] = (at, quote, price)
    if not candidate:
        raise DataNotReady("本轮没有时间与价格均有效的集合竞价报价；保留上一完成日结果")
    latest_at = max(item[0] for item in candidate.values())
    max_skew = config.INTRADAY["max_quote_batch_skew_seconds"]
    observed = {code: item for code, item in candidate.items()
                if (latest_at - item[0]).total_seconds() <= max_skew}
    if not observed:
        raise DataNotReady("本轮集合竞价报价时间明显落后；保留上一完成日结果")

    snap = dict(previous_snapshot)
    auction_phase = df.session_label(captured_at)
    snap.update(session=auction_phase, mode="auction",
                scan_started_at=scan_started_at.isoformat(sep=" ", timespec="seconds"),
                quote_capture_at=captured_at.isoformat(sep=" ", timespec="seconds"))
    auction_day = captured_at.date().isoformat()
    prior_boundaries = previous_snapshot.get("boundary_prices") or {}
    boundaries = (dict(prior_boundaries) if prior_boundaries.get("date") == auction_day
                  else {"date": auction_day})
    if boundary == "auction_final":
        final_quotes = {}
        for code, (at, quote, price) in observed.items():
            if at.hour * 60 + at.minute < 9 * 60 + 25:
                continue
            last_close = num(quote.get("last_close"))
            change = round((price / last_close - 1) * 100, 2) if last_close > 0 else None
            if change is None:
                try:
                    change = float(quote.get("change_pct"))
                except (TypeError, ValueError):
                    continue
            if not math.isfinite(change):
                continue
            final_quotes[code] = {"price": round(price, 3), "change_pct": change,
                                  "source_at": at.isoformat(sep=" ", timespec="seconds")}
        minimum = max(100, int(len(codes) * 0.6))
        if len(final_quotes) < minimum:
            raise DataNotReady(f"9:25 竞价结束报价尚未更新：{len(final_quotes)}/{len(codes)} 只，"
                               f"需至少 {minimum} 只；稍后重试")
        boundaries["auction_final"] = {"cutoff": "09:25",
                                       "captured_at": snap["quote_capture_at"],
                                       "count": len(final_quotes), "prices": final_quotes}
    snap["boundary_prices"] = boundaries

    def auction_row(old):
        row = dict(old)
        code = str(row.get("code") or "")
        item = observed.get(code)
        prior = row.get("auction_observation") or {}
        observation = (prior if str(prior.get("quote_at") or "").startswith(auction_day)
                       and num(prior.get("price")) > 0 else None)
        if item:
            at, quote, price = item
            last_close = num(quote.get("last_close"))
            change = round((price / last_close - 1) * 100, 2) if last_close > 0 else None
            if change is None:
                try:
                    change = float(quote.get("change_pct"))
                    if not math.isfinite(change):
                        change = None
                except (TypeError, ValueError):
                    change = None
            observation = {"quote_at": at.isoformat(sep=" ", timespec="seconds"),
                           "price": price, "change_pct": change,
                           "status": "集合竞价报价；成交额不作门槛"}
        basis_reason = "集合竞价阶段不作盘中均线比较"
        row.update(auction_observation=observation, intraday_phase_status=auction_phase,
                   attack_watch_candidate=False, attack_risk_clear=False,
                   live_attack_status="集合竞价历史参考，当前未判断进攻",
                   intraday_quote_fresh=False, intraday_score_stale=row.get("intraday_score") is not None,
                   intraday_observation_available=False, intraday_judgment_at=None,
                   intraday_quote_status=("集合竞价报价有效，盘中趋势待确认" if item
                                          else "本轮竞价报价未更新，显示本日最近竞价参考" if observation
                                          else "集合竞价报价未更新，沿用上一完成日结果"),
                   intraday_trend_state=f"均线待核验（{basis_reason}）",
                   intraday_trend_ok=None, intraday_trend_failure=basis_reason,
                   intraday_price_basis_version=intraday.PRICE_BASIS_VERSION,
                   intraday_price_basis_comparable=False,
                   intraday_price_basis_status=f"待核验（{basis_reason}）",
                   intraday_price_basis_reason=basis_reason,
                   intraday_observation_state="集合竞价观察",
                   intraday_score_delta=None, intraday_delta_state="集合竞价不比较盘中评分",
                   intraday_transition=None, intraday_transition_state="集合竞价不判断收复或失守",
                   intraday_risk_level="待核验", intraday_risk_flags=[],
                   current_strong_candidate=False, current_pullback_candidate=False,
                   startup_candidate=False, turn_weak_repair_candidate=False,
                   intraday_active_candidate=False, intraday_repair_candidate=False,
                   entry_watch=False)
        row["intraday_atr20"] = None
        row["intraday_atr20_status"] = "待核验"
        row["intraday_atr20_reason"] = basis_reason
        for period in (5, 10, 20):
            for key in (f"intraday_ma{period}", f"intraday_ma{period}_exact",
                        f"intraday_distance_ma{period}_pct", f"intraday_distance_ma{period}_atr",
                        f"intraday_ma{period}_trigger_price", f"intraday_ma{period}_current_holds",
                        f"intraday_ma{period}_day_low_breached", f"intraday_ma{period}_minute_state",
                        f"intraday_ma{period}_minute_note", f"intraday_ma{period}_minute_record_at",
                        f"intraday_ma{period}_current_note", f"daily_ma{period}_fixed",
                        f"daily_ma{period}_fixed_exact"):
                row[key] = None
        return row

    snap["stocks"] = [auction_row(row) for row in previous_snapshot.get("stocks") or []]
    snap["coverage_catalog"] = [auction_row(row) for row in previous_snapshot.get("coverage_catalog") or []]
    intraday_model = dict(previous_snapshot.get("intraday_model") or {})
    intraday_model.update(version=intraday.VERSION,
                          rule_version=config.INTRADAY_RULE_VERSION,
                          price_basis_version=intraday.PRICE_BASIS_VERSION,
                          session=auction_phase, normal_scoring_session=False,
                          phase_status=f"{auction_phase}报价 {len(observed)} 只；不要求成交额，不生成盘中评分",
                          captured_at=captured_at.isoformat(sep=" ", timespec="seconds"),
                          auction_quote_count=len(observed),
                          auction_latest_quote_at=latest_at.isoformat(sep=" ", timespec="seconds"),
                          valid_quote_count=0, complete_score_count=0)
    snap["intraday_model"] = intraday_model
    old_attack = dict(previous_snapshot.get("attack_monitor") or {})
    old_attack.update(session=auction_phase, count=0, retained=True)
    snap["attack_monitor"] = old_attack
    snap["intraday_new_strength"] = {
        "version": close_monitor.VERSION, "day": auction_day, "rows": [],
        "reason": "竞价价格与历史结构判断见竞价观察；连续成交强势使用正式成交证据"}
    # 集合竞价不生成整理信号，但历史记录及个股详情须使用同一版本，不能遗留MA10旧退出语义。
    trend_consolidation.attach(snap, {}, {}, {}, [], previous=previous_snapshot)
    wyckoff_structure.attach(snap, {}, [], state=wyckoff_structure.load_state())
    formal=formal_histories(codes)
    calendar=strength.trading_calendar({c:strength.completed(v) for c,v in formal.items()})
    session_context.attach(snap,quotes,formal,calendar)
    for period in close_monitor.LINES:
        snap[f"trend_ma{period}_observation"] = {
            "version": close_monitor.TREND_VERSION, "line": f"MA{period}",
            "monitor_day": auction_day,
            "baseline_asof": (previous_snapshot.get("strength_model") or {}).get("asof"),
            "near_limit_pct": close_monitor.TREND_NEAR_PCT,
            "base_count": 0, "valid_quote_count": 0,
            "main_rows": [], "reclaim_rows": [], "pending_rows": [],
            "pending_count": 0,
            "price_basis_version": intraday.PRICE_BASIS_VERSION,
            "reason": f"竞价报价不用于 MA{period} 回踩判断，等待正常交易"}
    # 竞价历史只读本地；指数读取同源当日报价，源尚未发布时显示待更新。
    import board_trend
    board_trend.attach(snap, fetch=False, quote_fetch=True, previous_snapshot=previous_snapshot)
    import weekly_members
    snap['member_refresh'] = weekly_members.status()
    completed_at = datetime.now()
    snap["scan_completed_at"] = completed_at.isoformat(sep=" ", timespec="seconds")
    snap["generated_at"] = completed_at.strftime("%Y-%m-%d %H:%M:%S")
    price_only.sanitize(snap)
    snap["close_refresh_version"] = CLOSE_REFRESH_VERSION
    config.atomic_write_text(config.SNAPSHOT_JSON,
                             json.dumps(snap, ensure_ascii=False, separators=(",", ":")))
    print(f"[RUN] 集合竞价有效报价 {len(observed)}/{len(codes)}；沿用完成日线与收盘名单")
    return snap


def _prev_stock_count():
    """上一份快照的有效样本数，用于识别"样本数塌陷"。读不到就返回 0（首跑）"""
    try:
        with open(config.SNAPSHOT_JSON, encoding="utf-8") as f:
            return int(json.load(f).get("stock_count") or 0)
    except Exception:
        return 0


# ─────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────
_DROP = re.compile(r"[\s　]|概念|板块|指数|\(.*?\)|（.*?）")


def name_key(s):
    """板块名归一化，用于同花顺↔东财的跨源匹配"""
    return _DROP.sub("", str(s or "")).upper()


def fuzzy_key(nk, keys):
    """精确匹配失败时退化为包含匹配。

    同花顺与东财的概念命名体系不同（如「新型烟草(电子烟)」↔「电子烟」、
    「铜缆高速连接」↔「铜缆高速连接概念」），只做精确匹配会丢掉半数板块。
    包含匹配时取最长命中，避免「烟草」把「新型烟草」抢走。
    """
    if nk in keys:
        return nk
    best = None
    for k in keys:
        if len(k) < 2:
            continue
        if k in nk or nk in k:
            if best is None or len(k) > len(best):
                best = k
    return best


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def num(v, d=0.0):
    return v if isinstance(v, (int, float)) else d


def merge_by_name(a_list, b_list):
    """按 name_key 把两个来源的板块合并"""
    bmap = {}
    for b in b_list:
        bmap.setdefault(name_key(b.get("name")), b)
    merged = []
    for a in a_list:
        merged.append({"ths": a, "em": bmap.get(name_key(a.get("name")))})
    # 东财独有、同花顺没有的板块也补进来
    a_keys = {name_key(a.get("name")) for a in a_list}
    for k, b in bmap.items():
        if k and k not in a_keys:
            merged.append({"ths": None, "em": b})
    return merged


def build_theme_groups(theme_map, quotes, fund_map=None, fund_period="5d"):
    """按题材把个股分组，统计组内涨跌家数、等权涨幅与主力净额。

    关键口径（2026-09-18 修正）：
      · 「上涨占比」的分母用 **有成交的成员数**，而不是「上涨+下跌」。
        否则开盘初期大量尚未成交的成员（涨跌幅恰为 0）被排除在分母之外，
        会出现"10 只成员里 5 只涨、5 只还没成交 → 上涨占比 100%"的假象。
      · coverage 暴露成交覆盖率；覆盖率不足的题材不采信（见 rank_themes）。

    传入 fund_map 后同时聚合组内主力净额，供板块层做资金兜底。
    """
    fm = fund_map or {}
    grp = {}
    for c, d in (theme_map or {}).items():
        q = quotes.get(c)
        if not q or not q.get("price"):
            continue
        chg = num(q.get("change_pct"))
        amt = num(q.get("amount_wan"))
        fund = fm.get(c) or {}
        net = fund.get("main_today" if fund_period == "today" else "main_5d")
        traded = amt > 0
        for t in d.get("themes", []):
            g = grp.setdefault(t, {"n": 0, "up": 0, "down": 0, "flat": 0, "traded": 0,
                                   "chg_sum": 0.0, "amount_wan": 0.0, "main_net_sum": 0.0,
                                   "fund_covered": 0})
            g["n"] += 1
            g["chg_sum"] += chg
            g["amount_wan"] += amt
            if net is not None:
                g["main_net_sum"] += num(net)
                g["fund_covered"] += 1
            if traded:
                g["traded"] += 1
            if chg > 0:
                g["up"] += 1
            elif chg < 0:
                g["down"] += 1
            else:
                g["flat"] += 1
    for t, g in grp.items():
        tr = g["traded"]
        # 分母 = 有成交成员数（含平盘），避免"没成交的不进分母"造成虚高
        g["up_ratio"] = round(g["up"] / tr * 100, 2) if tr else 0.0
        g["avg_chg"] = round(g["chg_sum"] / g["n"], 2) if g["n"] else 0.0
        g["amount_wan"] = round(g["amount_wan"], 0)
        g["main_net_sum"] = round(g["main_net_sum"], 0) if g["fund_covered"] else None
        g["fund_coverage"] = round(g["fund_covered"] / g["n"] * 100, 1) if g["n"] else 0.0
        g["coverage"] = round(tr / g["n"] * 100, 1) if g["n"] else 0.0
        g["active"] = tr
    return grp


# ─────────────────────────────────────────────────────
# 板块榜
# ─────────────────────────────────────────────────────
def build_board_board(conn, theme_map=None, theme_groups=None, refresh=False,
                      progress=True, prefer_cache=False):
    """构建板块强度榜。返回 (boards, board_ctx)"""
    ths_map = df.scan_ths_boards(force=refresh)
    print(f"[BOARD] 同花顺概念 {len(ths_map)} 个，拉取日线 ...")

    # 1. 同花顺板块日线 → 多周期RS + 动能
    ths_rows = []
    idx_codes = list(ths_map.keys())
    t0 = time.time()

    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
    # The legacy board score may consume an unfinished bar. Reuse only when its
    # last bar is complete, and the source has been checked on this observation day.
    now = datetime.now()
    observation_day = now.strftime('%Y-%m-%d')
    target = conn.execute('SELECT MAX(date) FROM kline').fetchone()[0]
    cache_rule = scan_cache.signature([scan_cache.rules('datafeed.py', 'factors.py'), observation_day, target])
    history_counts = Counter()
    batch_deadline = time.monotonic()+60

    def work(ic):
        try:
            if time.monotonic() >= batch_deadline:
                return None
            saved = scan_cache.get('board_history', ic, cache_rule) if not refresh else None
            if saved and saved.get('name') == ths_map.get(ic):
                nm, ks = saved['name'], saved['bars']
                history_counts['reused'] += 1
            else:
                retry = scan_cache.get('board_history_retry', ic, 'retry') or {}
                if not refresh and retry.get('next_retry', 0) > time.time():
                    history_counts['deferred'] += 1
                    return None
                history_counts['requested'] += 1
                nm, ks = df.fetch_ths_board_kline(ic)
                if nm != ths_map.get(ic) or len(ks) < 25:
                    raise ValueError('板块历史名称或窗口未齐全')
                scan_cache.put('board_history_retry', ic, 'retry', {})
                completed_today = now.hour*60+now.minute >= 15*60+5
                if (nm == ths_map.get(ic) and len(ks) >= 25 and ks[-1]['date'] >= (target or '')
                        and (ks[-1]['date'] < observation_day or completed_today)):
                    scan_cache.put('board_history', ic, cache_rule, dict(name=nm, bars=ks))
            if nm and len(ks) >= 25:
                m = F.board_raw_metrics(ks)
                m["name"] = nm
                m["idx_code"] = ic
                m["last_date"] = ks[-1]["date"]
                m['completed_date'] = max((b['date'] for b in ks if b['date'] < observation_day
                    or b['date'] == observation_day and now.hour*60+now.minute >= 15*60+5), default=None)
                if not saved or not saved.get('stored'):
                    m['_history'] = ks
                return m
        except Exception as error:
            history_counts['failed'] += 1
            state = scan_cache.get('board_history_retry', ic, 'retry') or {}
            failures = state.get('failures', 0)+1
            scan_cache.put('board_history_retry', ic, 'retry', dict(failures=failures,
                next_retry=time.time()+min(1800, 300*2**min(failures-1, 3)), error=str(error)[:160]))
        return None

    ex = ThreadPoolExecutor(max_workers=8)
    truncated = False
    try:
        futs = [ex.submit(work, ic) for ic in idx_codes]
        try:
            for f in as_completed(futs, timeout=max(.01,batch_deadline-time.monotonic())):
                r = f.result()
                if r:
                    bars_to_save = r.pop('_history', None)
                    if bars_to_save:
                        import board_trend
                        try:
                            board_trend.save(r['idx_code'], bars_to_save)
                            payload = scan_cache.get('board_history', r['idx_code'], cache_rule)
                            if payload:
                                payload['stored'] = True
                                scan_cache.put('board_history', r['idx_code'], cache_rule, payload)
                        except Exception as error:
                            print(f"[WARN] 板块日线落库失败 {r['idx_code']}: {error}")
                    ths_rows.append(r)
        except FuturesTimeoutError:
            truncated = True
            for future in futs:
                future.cancel()
    finally:
        ex.shutdown(wait=not truncated)
    print(f"[BOARD] 同花顺板块有效 {len(ths_rows)} 个，耗时 {time.time()-t0:.1f}s")
    df._source_mark('ths_board_history', 'partial' if len(ths_rows)<len(idx_codes) else 'ok',
                   elapsed=time.time()-t0, coverage=len(ths_rows), detail=json.dumps(dict(history_counts)))

    # 剔除「风格 / 状态」类板块（次新股、低价股、融资融券、AH股、指数…）：
    # 它们没有题材含义、成分股跨行业，混进强度榜会挤掉真正有资金聚集的题材，
    # 而且其"涨跌幅"本质上只是大盘的一个切面，没有轮动指导意义。
    _bad = [r["name"] for r in ths_rows if not df._theme_ok(r["name"])]
    ths_rows = [r for r in ths_rows if df._theme_ok(r["name"])]
    if _bad:
        print(f"[BOARD] 剔除风格类板块 {len(_bad)} 个：{'、'.join(_bad[:8])}"
              f"{' …' if len(_bad) > 8 else ''}")

    if not ths_rows:
        return [], {}

    # 板块相对强度 = 绝对动量 50% + 相对超额 50% + 上涨天数
    # （同样是防"全市场下跌时跌得少的板块被误判为强势"）
    med5 = F.median([r["ret5"] for r in ths_rows if r["ret5"] is not None])
    med20 = F.median([r["ret20"] for r in ths_rows if r["ret20"] is not None])
    for r in ths_rows:
        a5 = r["ret5"] or 0.0
        a20 = r["ret20"] or 0.0
        abs_part = 0.55 * a5 + 0.45 * a20
        ex_part = 0.55 * (a5 - med5) + 0.45 * (a20 - med20)
        r["rs_raw"] = 0.50 * abs_part + 0.50 * ex_part + 0.20 * (r["up_days_5"] - 2.5) * 2
        r["momentum_raw"] = r["up_days_5"] * 20 + (r["position60"] - 50) * 0.4

    rs_p = dict(zip([r["name"] for r in ths_rows], F.pct_rank([r["rs_raw"] for r in ths_rows])))
    mo_p = dict(zip([r["name"] for r in ths_rows], F.pct_rank([r["momentum_raw"] for r in ths_rows])))
    # 成交额动量与真实资金分列；缺失资金不能变成中性分位。

    # 资金排序已取消；保留同花顺价量和成员联动。
    em_meta = {"source": "已停用", "stale": False, "coverage": 0}
    tg_by_key = theme_groups or {}
    n_exact_f = n_exact_l = 0
    cover_min = config.BOARD["min_cover"] * 100

    def tg_ok(k):
        """题材组能否用于板块层：成员数够 且 当日成交覆盖率达标。

        覆盖率不达标时（开盘初期大量成分股尚未成交），组内涨跌家数只反映了
        少数已成交标的，用它当联动分会把"少数股拉升"误读成"板块整体走强"。
        """
        gg = tg_by_key.get(k)
        return bool(gg and gg.get("n", 0) >= 5
                    and gg.get("coverage", 100.0) >= cover_min)

    # 3. 合并打分
    w = config.BOARD_WEIGHTS
    boards = []
    for r in ths_rows:
        nk = r["name"]  # 跨来源只允许完全同名；不再用包含关系猜归属。
        rs = rs_p.get(r["name"], 50.0)
        mo = mo_p.get(r["name"], 50.0)

        fu, fund_src = None, "已停用"

        # ── 联动：优先自洽的「题材组内上涨占比」，其次东财板块涨跌家数 ──
        li, li_src = None, None
        if tg_ok(nk):
            li, li_src = tg_by_key[nk]["up_ratio"], "主板成员上涨占比"
            n_exact_l += 1
        components = [(w["rs"], rs), (w["momentum"], mo)]
        if li is not None:
            components.append((w["linkage"], li))
        score = sum(weight * value for weight, value in components) / sum(weight for weight, _ in components)

        # 绝对方向闸门：5日/20日双负的板块，强度分封顶，避免"抗跌"被读成"强势"
        a5 = r["ret5"] or 0.0
        a20 = r["ret20"] or 0.0
        if a5 < 0 and a20 < 0:
            gate = 0.55
        elif a5 < 0:
            gate = 0.82
        else:
            gate = 1.0
        score *= gate
        boards.append({
            "name": r["name"], "idx_code": r["idx_code"],
            "last_date": r["last_date"], "completed_date": r.get('completed_date'),
            "ret1": round(r["ret1"] or 0, 2),
            "ret5": round(r["ret5"] or 0, 2),
            "ret20": round(r["ret20"] or 0, 2),
            "up_days_5": r["up_days_5"],
            "position60": round(r["position60"], 1),
            "vol_expand": round(r["vol_expand"], 2),
            "amount_momentum": round(r["amount_momentum"], 2),
            "rs": round(rs, 1), "momentum": round(mo, 1),
            "fund": None if fu is None else round(fu, 1),
            "fund_src": fund_src,
            "linkage": None if li is None else round(li, 1),
            "linkage_src": li_src,
            "gate": gate,
            "score": round(score, 2),
        })
    boards.sort(key=lambda x: -x["score"])
    for i, b in enumerate(boards, 1):
        b["rank"] = i
    board_index = {b["name"]: b["score"] for b in boards}

    n = len(ths_rows) or 1
    print(f"[BOARD] 主板成员联动 {n_exact_l}/{n}")

    return boards, {
        "board_score": board_index,
        # 个股F10核对后的同花顺概念名；缺失F10时标记待核验。
        "code_boards": {c: d.get("themes", []) for c, d in (theme_map or {}).items()},
        # 兼容旧字段；当前纯同花顺映射始终为空。
        "code_boards_em": {c: d.get("themes_em", []) for c, d in (theme_map or {}).items()},
        "industries": {c: d.get("industry", []) for c, d in (theme_map or {}).items()},
        "theme_groups": theme_groups or {},
        "source_meta": em_meta,
        "theme_source": {
            "name": "同花顺个股 F10 / 概念详情交叉核对",
            "member_source": "个股F10相关概念优先；概念详情成员用于交叉核对及缺失提示",
            "industry_source": "个股F10所属申万行业优先；缺失时行业详情成员待核验",
            "stock_profile_source": "同花顺个股 concept.html / company.html",
            "fallback": "无东财行业、题材、概念兜底",
        },
    }


def build_board_chain(boards, stocks, follower_limit=5):
    """只展示同花顺概念内可核验的成员角色，不推断谁带动了谁。"""
    by_board = {}
    for s in (stocks or []):
        if num(s.get("traded"), 1) == 0:
            continue
        for name in (s.get("boards") or []):
            if not name:
                continue
            by_board.setdefault(str(name), []).append(s)

    def key(s):
        # score 是主排序；同分时用已有行情字段稳定打散，不增加任何新权重。
        return (-num(s.get("stock_strength_score")), str(s.get("code") or ""))

    def view(s, role):
        return {
            "code": s.get("code"), "name": s.get("name"), "role": role,
            "score": round(num(s.get("score")), 2),
            "change_pct": round(num(s.get("change_pct")), 2),
            "ret5": round(num(s.get("ret5")), 2),
            "turnover": round(num(s.get("turnover")), 2),
            "limit_today": int(num(s.get("limit_today"))),
            "roles": s.get("roles") or [], "trend_stage": s.get("trend_stage"),
            "emotion_heat": s.get("emotion_heat"), "axis_group": s.get("axis_group"),
        }

    out = {}
    for b in (boards or []):
        name = str(b.get("name") or "")
        rel = sorted(by_board.get(name, []), key=key)
        leader = view(rel[0], "板块内强度领先") if rel else None
        followers = [view(s, "其他已覆盖成员") for s in rel[1:1 + max(0, int(follower_limit))]]
        idx = str(b.get("idx_code") or name)
        out[idx] = {
            "board_name": name,
            "idx_code": b.get("idx_code"),
            "board_score": round(num(b.get("score")), 2),
            "board_rank": int(num(b.get("rank"))),
            "member_count": len(rel),
            "leader": leader,
            "followers": followers,
            "source": "同花顺概念",
            "sort_basis": "按个股四项强度列出已覆盖成员；无盘中先后证据，不推断带动关系",
        }
    return out


def rank_themes(theme_groups, min_members=5, max_members=None, top=30,
                min_active=None, min_cover=None):
    """题材组强度榜 —— 同花顺概念口径

    三道数据门槛；类别由统一的同花顺标签规则决定，不以成员上限猜测属性：
      n < min_members        样本太小无统计意义
      traded < min_active    当日有成交的成员太少，统计量不可信
      coverage < min_cover   成交覆盖率不足（开盘初期常见），占比会被显著放大

    排序以 **等权涨幅** 为主：它把未成交与平盘成员按 0 计入，天然不会被
    小样本放大；上涨占比放在次位并同时展示，便于判断"普涨还是少数拉升"。
    """
    # 宽题材保留并明确标识，不能仅因成员多就从榜单和助攻中消失。
    min_active = config.THEME["link_min_members"] if min_active is None else min_active
    min_cover = config.THEME.get("min_cover", 0.5) if min_cover is None else min_cover
    rows = []
    for nm, g in theme_groups.items():
        if g["n"] < min_members:
            continue
        tr = g.get("traded", g["up"] + g["down"])
        if tr < min_active:
            continue
        if g.get("coverage", 100.0) / 100.0 < min_cover:
            continue
        rows.append({
            "name": nm, "n": g["n"], "up_ratio": g["up_ratio"], "avg_chg": g["avg_chg"],
            "amount_wan": g["amount_wan"], "active": tr,
            "coverage": g.get("coverage", 100.0), "main_net_sum": g.get("main_net_sum"),
            "fund_covered": g.get("fund_covered", 0), "fund_coverage": g.get("fund_coverage", 0),
            "wide": g["n"] > 60,
            "up": g.get("up", 0), "down": g.get("down", 0), "flat": g.get("flat", 0),
        })
    rows.sort(key=lambda x: (-x["avg_chg"], -x["up_ratio"], -x["amount_wan"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows[:top]


# 分类只使用同花顺概念目录和详情成员，个股卡片的相关概念、行业来自同花顺 F10；
# 资金流的东财来源与分类链路分离。具体成员映射见 datafeed.build_theme_map()。


# ─────────────────────────────────────────────────────
# K线获取（缓存 + 实时覆盖）
# ─────────────────────────────────────────────────────
def validate_close_daily(klines, quotes, now):
    """正式榜发布前检查真实日线日期、OHLC和活跃股票覆盖，不采用报价合成K。"""
    if now.hour * 60 + now.minute < 15 * 60 + 5:
        raise DataNotReady('15:05前不能把当日日线判定为正式收盘')
    target = now.strftime('%Y-%m-%d')
    active_codes = [c for c, q in quotes.items()
                    if num(q.get('amount_wan')) > 0 or num(q.get('volume_shou')) > 0]
    ready = sum(bool(klines.get(c)) and klines[c][-1]['date'] == target
                and strength.valid_bars(klines[c][-1:]) for c in active_codes)
    if not active_codes or ready < len(active_codes) * 0.8:
        raise DataNotReady(f'正式收盘日线仅覆盖 {ready}/{len(active_codes)} 只，保留上一份收盘榜并稍后重试')
    return ready


def load_klines(conn, codes, quotes, refresh=False, progress=True,
                required_day=None, history_cache=None, telemetry=None, budget_seconds=None):
    """增量补齐正式历史；盘中报价仅覆盖内存比较副本，失败进入退避队列。"""
    import history_increment
    acquisition = history_increment.update(conn, codes, quotes, required_day,
                                           force=refresh, progress=progress, budget_seconds=budget_seconds,
                                           allow_periodic=False)
    if telemetry is not None:
        telemetry.update(acquisition)
    history_cache = history_cache if history_cache is not None else {}
    pending = {c for c, payload in conn.execute('SELECT code,payload FROM kline_fetch_state')
               if json.loads(payload).get('integrity_pending')}
    out = {}
    for c in codes:
        ks = df.load_kline(conn, "kline", "code", c)
        if c in pending:
            # Keep originals in SQLite; unverified adjustment copies cannot create MA events.
            ks = [dict(b, price_basis=None, price_basis_source=None, history_integrity_pending=True) for b in ks]
        history_cache[c] = ks
        q = quotes.get(c) or {}
        ts = str(q.get("ts") or "")
        qdate = intraday.quote_day(q.get("quote_at") or ts, datetime.now())
        # 收盘后只用正式落库日线，报价不能替代正式完成K或覆盖复权价格。
        after_close = datetime.now().hour * 60 + datetime.now().minute >= 15 * 60
        if ks and qdate and q.get("price", 0) > 0 and not after_close:
            # 数据库里的历史K线成交量已经统一为「股」，而腾讯实时行情
            # volume_shou 的单位是「手」。盘中追加/覆盖时必须走同一套
            # 板别换算，否则量价因子会被系统性压低 100 倍。
            try:
                q_volume = float(q.get("volume_shou") or 0) * config.volume_to_shares(c)
            except (TypeError, ValueError):
                q_volume = 0.0
            qbar = {"date": qdate, "open": q.get("open") or q["price"],
                    "close": q["price"], "high": q.get("high") or q["price"],
                    "low": q.get("low") or q["price"],
                    "volume": q_volume, "amount": 0.0,
                    "price_basis": q.get("price_basis"),
                    "price_basis_source": q.get("price_basis_source")}
            # quick 扫描通常追加当天第一根盘中 bar；如果当天已经做过
            # full/手动扫描，则必须覆盖同日旧 bar，否则之后的 quick 扫描
            # 会一直停留在那次扫描的价格和成交量。
            if qdate > ks[-1]["date"]:
                ks = ks + [qbar]
            elif qdate == ks[-1]["date"]:
                ks = ks[:-1] + [qbar]
        out[c] = ks
    return out


# ─────────────────────────────────────────────────────
# 全流程
# ─────────────────────────────────────────────────────
def _apply_intraday_close_confirmation(snap, previous_snapshot):
    """每日只固定一次最后有效盘中判断；后续刷新读取原结果，不覆盖对照。"""
    day = (snap.get("strength_model") or {}).get("asof")
    target_meta = snap.get("intraday_model") or {}
    target_version = target_meta.get("version")
    target_rule = target_meta.get("rule_version")
    target_basis_version = target_meta.get("price_basis_version")
    if not target_version or not target_rule:
        return None

    def matches_current_version(record):
        return (record and record.get("model_version") == target_version
                and record.get("rule_version") == target_rule
                and record.get("price_basis_version") == target_basis_version)

    store = config.CACHE_DIR / "intraday_close_confirmation"
    latest_path = store / "latest.json"
    saved = None
    version_conflict = False
    scan_day = str(snap.get("quote_capture_at") or "")[:10]
    if day and day == scan_day and snap.get("session") in ("尾盘", "已收盘"):
        day_path = store / (str(day) + ".json")
        try:
            if day_path.exists():
                saved = json.loads(day_path.read_text(encoding="utf-8"))
                if not matches_current_version(saved):
                    saved = None
                    version_conflict = True
        except (OSError, ValueError):
            saved = None
        if saved is None and not version_conflict:
            prev_meta = previous_snapshot.get("intraday_model") or {}
            prev_scan = str(previous_snapshot.get("scan_completed_at") or
                            previous_snapshot.get("generated_at") or "")
            if (prev_meta.get("asof") == day and prev_scan[:10] == day
                    and prev_meta.get("version") == target_version
                    and prev_meta.get("rule_version") == target_rule
                    and prev_meta.get("price_basis_version") == target_basis_version):
                previous_rows = {str(row.get("code")): row for row in
                                 (previous_snapshot.get("stocks") or []) +
                                 (previous_snapshot.get("coverage_catalog") or [])}
                results = {"asof": day, "previous_scan_at": prev_scan,
                           "confirmed": 0, "unconfirmed": 0, "unchanged": 0,
                           "rows": {}, "model_version": prev_meta.get("version"),
                           "rule_version": prev_meta.get("rule_version"),
                           "price_basis_version": prev_meta.get("price_basis_version")}
                for row in (snap.get("stocks") or []) + (snap.get("coverage_catalog") or []):
                    old = previous_rows.get(str(row.get("code")))
                    if not old or old.get("intraday_quote_fresh") is not True:
                        continue
                    live_ok = old.get("intraday_trend_ok")
                    close_ok = bool(row.get("trend_online"))
                    if live_ok is True and not close_ok:
                        label = "盘中暂态转强，收盘未确认"
                        results["unconfirmed"] += 1
                    elif live_ok is True and close_ok:
                        label = "盘中与收盘趋势均成立"
                        results["confirmed"] += 1
                    elif live_ok is False and close_ok:
                        label = "收盘确认日线趋势"
                        results["confirmed"] += 1
                    elif live_ok is False and not close_ok:
                        label = "盘中与收盘趋势均未成立"
                        results["unchanged"] += 1
                    else:
                        label = "盘中暂态数据不足，无法比较"
                    results["rows"][str(row.get("code"))] = {
                        "confirmation": label,
                        "intraday_state": old.get("intraday_trend_state"),
                        "intraday_trend_ok": live_ok,
                        "intraday_quote_at": old.get("intraday_quote_at"),
                        "intraday_score": old.get("intraday_score"),
                        "intraday_change_pct": old.get("change_pct"),
                        "intraday_candidates": {
                            "current_strong": bool(old.get("current_strong_candidate")),
                            "startup": bool(old.get("startup_candidate")),
                            "current_pullback": bool(old.get("current_pullback_candidate")),
                        },
                        "close_trend_online": close_ok,
                        "close_price": row.get("close", row.get("signal_close")),
                        "close_ma10": row.get("ma10"),
                        "close_ma20": row.get("ma20"),
                    }
                if results["rows"]:
                    store.mkdir(parents=True, exist_ok=True)
                    config.atomic_write_text(day_path, json.dumps(results, ensure_ascii=False))
                    config.atomic_write_text(latest_path, json.dumps(results, ensure_ascii=False))
                    intraday.save_close_observation(snap, previous_snapshot, results)
                    saved = results
    if saved is None:
        try:
            if latest_path.exists():
                saved = json.loads(latest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = None
        if saved and (saved.get("asof") != day or not matches_current_version(saved)):
            saved = None
    if not saved:
        return None
    saved_rows = saved.get("rows") or {}
    for row in (snap.get("stocks") or []) + (snap.get("coverage_catalog") or []):
        item = saved_rows.get(str(row.get("code")))
        if not item:
            continue
        row["intraday_close_intraday_state"] = item.get("intraday_state")
        row["intraday_close_intraday_trend_ok"] = item.get("intraday_trend_ok")
        row["intraday_close_confirmed_trend"] = item.get("close_trend_online")
        row["intraday_close_confirmation_at"] = saved.get("previous_scan_at")
        row["intraday_close_confirmation"] = item.get("confirmation")
        row["intraday_close_asof"] = saved.get("asof")
        row["intraday_close_quote_at"] = item.get("intraday_quote_at")
        row["intraday_close_score"] = item.get("intraday_score")
        row["intraday_close_change_pct"] = item.get("intraday_change_pct")
    summary_keys = ("asof", "previous_scan_at", "confirmed", "unconfirmed", "unchanged",
                    "model_version", "rule_version", "price_basis_version")
    snap["intraday_close_confirmation"] = {key: saved.get(key) for key in summary_keys}
    return snap["intraday_close_confirmation"]


@config.single_writer
@scan_cache.run_guard
def run(mode="quick", rebuild_pool=False, progress=True, boundary=None):
    with ExitStack() as resources:
        return _run(mode, rebuild_pool, progress, boundary, resources)


def _run(mode, rebuild_pool, progress, boundary, resources):
    t_start = time.time()
    timer = scan_cache.Timer(mode)
    scan_started_at = datetime.now()
    snap = {"scan_started_at": scan_started_at.isoformat(sep=" ", timespec="seconds"),
            "generated_at": scan_started_at.strftime("%Y-%m-%d %H:%M:%S"), "mode": mode,
            "close_refresh_version": CLOSE_REFRESH_VERSION}
    previous_snapshot = {}
    try:
        previous_snapshot = json.loads(config.SNAPSHOT_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    previous_boundaries = previous_snapshot.get("boundary_prices") or {}
    snap["boundary_prices"] = (dict(previous_boundaries)
                               if previous_boundaries.get("date") == scan_started_at.strftime("%Y-%m-%d")
                               else {"date": scan_started_at.strftime("%Y-%m-%d")})
    snap["session"] = df.session_label()
    prior_verified = str(previous_snapshot.get('close_daily_verified_at') or '')
    if prior_verified.startswith(scan_started_at.strftime('%Y-%m-%d')) and previous_snapshot.get('close_refresh_version') == CLOSE_REFRESH_VERSION:
        snap['close_daily_verified_at'] = prior_verified
    print(f"[RUN] 数据阶段：{snap['session']}")
    if snap["session"] in ("集合竞价", "竞价结束"):
        return _auction_snapshot(previous_snapshot, mode, scan_started_at, boundary)
    if snap["session"] == "盘前":
        raise DataNotReady("盘前尚无当日竞价报价；保留上一完成日结果")

    # 1. 股票池
    pool = df.build_pool(force=rebuild_pool)
    snap["pool_size"] = len(pool)
    print(f"[RUN] 股票池 {len(pool)} 只 | 模式={mode}")

    # 2. 实时行情（全池，腾讯批量）
    print("[RUN] 拉取全池实时行情 ...")
    quotes = df.realtime_quotes(list(pool.keys()))
    # 实时行情是重新拉的，池里带的板别/次新字段必须补回来 ——
    # 丢了的话涨停判定会退回统一 9.8% 阈值（创业板涨 10% 被误判成涨停），
    # 界面上的板别徽标也会全部变成"未知"。
    quotes, newly_excluded = _merge_current_pool_quotes(pool, quotes)
    if newly_excluded:
        pool = {code: item for code, item in pool.items() if code not in newly_excluded}
        snap["pool_size"] = len(pool)
        print(f"[POOL] 本轮新报价发现 {len(newly_excluded)} 只风险警示/退市名称，已从候选池剔除")
    timer.mark("股票池与实时行情", "归属与外围")
    quote_capture_at = datetime.now()
    for q in quotes.values():
        q["quote_at"] = (intraday.parse_quote_timestamp(q.get("ts"), quote_capture_at)
                          .isoformat(sep=" ", timespec="seconds")
                          if intraday.parse_quote_timestamp(q.get("ts"), quote_capture_at) else None)
    snap["quote_capture_at"] = quote_capture_at.isoformat(sep=" ", timespec="seconds")
    intraday.intraday_path.save_acquisition(intraday.HISTORY_DIR, quotes, quote_capture_at, snap['session'], boundary)
    print(f"[RUN] 行情 {len(quotes)} 只")
    if boundary in ("midday", "close"):
        cutoff = "11:30" if boundary == "midday" else "15:00"
        boundary_rows = {}
        for code, q in quotes.items():
            at = str(q.get("quote_at") or "")
            try:
                at_dt = datetime.fromisoformat(at)
                price = float(q.get("price") or 0)
                low = float(q.get("low") or 0)
                high = float(q.get("high") or 0)
                change = float(q.get("change_pct"))
                traded = float(q.get("amount_wan") or 0) > 0 or float(q.get("volume_shou") or 0) > 0
            except (TypeError, ValueError):
                continue
            if (at[:10] != quote_capture_at.strftime("%Y-%m-%d")
                    or (at_dt - quote_capture_at).total_seconds() > config.INTRADAY["max_quote_future_seconds"]
                    or at[11:16] < cutoff
                    or (boundary == "midday" and at[11:16] >= "13:00")
                    or price <= 0 or low <= 0 or high < low
                    or price < low - 0.011 or price > high + 0.011 or not traded
                    or not all(math.isfinite(v) for v in (price, low, high, change))):
                continue
            boundary_rows[code] = {"price": round(price, 3), "change_pct": round(change, 3),
                                   "source_at": at}
        minimum = max(100, int(len(pool) * 0.6))
        if len(boundary_rows) < minimum:
            raise DataNotReady(f"{cutoff} 收市报价尚未更新：{len(boundary_rows)}/{len(pool)} 只，"
                               f"需至少 {minimum} 只；稍后重试")
        snap["boundary_prices"][boundary] = {
            "cutoff": cutoff, "captured_at": snap["quote_capture_at"],
            "count": len(boundary_rows), "prices": boundary_rows}
        print(f"[RUN] {cutoff} 收市报价 {len(boundary_rows)}/{len(pool)} 只")
    if snap["session"] in ("早盘", "午盘", "尾盘"):
        # 行情源可能仍返回竞价/上一交易日的报价。先用实际逐股时间与成交额
        # 判断本批报价是否就绪，避免跑完题材与板块后才发现有效样本为零。
        prior_count = len(previous_snapshot.get("stocks") or [])
        opening_quotes_ready(quotes, quote_capture_at, snap['session'], prior_count or len(quotes))

    # 3. 外围
    outer = df.fetch_outer_resilient()
    snap["outer"] = outer

    # 3·补、题材归属（同花顺概念/行业，东财不参与分类）
    theme_map = {}
    try:
        theme_map = df.build_theme_map()
        print(f"[RUN] 题材映射覆盖 {len(theme_map)} 只")
    except Exception as e:
        print(f"[WARN] 题材映射不可用，联动/外围因子退出：{e}")
    # F10 是分类核对缓存；日常行情刷新不访问同花顺分类页。
    # 未缓存的个股保留“待核对”，由明确的分类更新命令补齐。
    profile_path = config.THS_STOCK_PROFILE_CACHE
    cached_profiles = (json.loads(profile_path.read_text(encoding="utf-8")).get("profiles", {})
                       if profile_path.exists() else {})
    try:
        theme_map, classification_stats = classification.reconcile(
            theme_map, cached_profiles, df.fetch_ths_concept_catalog(), quotes)
    except Exception as e:
        raise DataNotReady(f"同花顺归属核对失败：{e}") from e
    snap["classification_stats"] = classification_stats
    print(f"[RUN] F10 归属核对 {classification_stats}")

    # 不再获取或使用任何资金流入/流出数据。
    fund_map = {}
    fund_meta = {"source": "已停用", "enabled": False, "stale": False, "coverage": 0}
    snap.update(fund_available=False, fund_source="已停用", fund_meta=fund_meta)

    # 4·补、题材分组（含组内主力净额，供板块层资金兜底）
    theme_groups = build_theme_groups(theme_map, quotes, fund_map,
                                      fund_period=fund_meta.get("period", "5d"))
    for group in theme_groups.values():
        group["fund_period"] = fund_meta.get("period", "5d")
    print(f"[RUN] 题材分组 {len(theme_groups)} 个（成员≥5 的 "
          f"{sum(1 for g in theme_groups.values() if g['n'] >= 5)} 个）")

    timer.mark("归属与外围", "板块历史")
    # 5. 板块
    conn = resources.enter_context(closing(df.db()))
    boards, board_ctx = build_board_board(
        conn, theme_map=theme_map, theme_groups=theme_groups,
        refresh=False, progress=progress, prefer_cache=(mode in ("quick", "close")))
    snap["boards"] = boards
    snap["theme_rank"] = rank_themes(theme_groups)
    # 题材→组内上涨占比 索引，供看板给个股题材标签上色（自洽口径，不跨源匹配）
    snap["theme_index"] = {k: v["up_ratio"] for k, v in theme_groups.items()
                           if v["n"] >= config.THEME["link_min_members"]}
    # 板块层资金口径覆盖率（东财真实资金 vs 题材组兜底 vs 价量代理）
    src_cnt = {}
    for b in boards:
        src_cnt[b["fund_src"]] = src_cnt.get(b["fund_src"], 0) + 1
    snap["board_fund_src"] = src_cnt
    snap["board_source"] = board_ctx.get("source_meta") or {}
    print(f"[RUN] 板块资金口径分布 {src_cnt}")

    # 6. K线
    codes = list(quotes.keys())
    timer.mark("板块历史", "正式日线增量")
    history_cache, kline_telemetry = {}, {}
    # Source-confirmed completed index dates provide a calendar bound; no weekday guessing.
    quote_dates = [q.get('quote_at', '')[:10] for q in quotes.values() if q.get('quote_at')]
    quote_day = Counter(quote_dates).most_common(1)[0][0] if quote_dates else ''
    now = datetime.now()
    daily_closed = now.hour*60+now.minute >= 15*60+5
    historical_dates = [b.get('completed_date') for b in boards if b.get('completed_date') and
                        (b['completed_date'] < quote_day or daily_closed and b['completed_date'] == quote_day)]
    required_day = quote_day if mode == 'close' else max(historical_dates, default=None)
    klines = load_klines(conn, codes, quotes, refresh=(mode == "full"), progress=progress,
                         required_day=required_day, history_cache=history_cache, telemetry=kline_telemetry,
                         budget_seconds=180 if mode == 'close' else config.KLINE['deadline_seconds'] if mode == 'full' else 60)
    timer.mark("正式日线增量", "个股计算")
    snap['kline_acquisition'] = kline_telemetry
    if mode == "close":
        validate_close_daily(klines, quotes, scan_started_at)
        snap['close_daily_verified_at'] = datetime.now().isoformat(sep=' ', timespec='seconds')

    # 7. 个股因子（V3：先过 Risk Gate，再分别计算短线启动与波段模型）
    #
    # Risk Gate 是"根本不该进候选池"的一层，**不计权重**。
    # 顺序：全A → Risk Gate → 周期模型评分 → 排序 → 市场环境决定是否执行。
    # 每一条剔除都必须计数并披露到界面 —— 静默丢股票比丢错股票更糟。
    print("[RUN] 计算简单强势观察（完成日线排名）...")
    b_med5 = F.median([b["ret5"] for b in boards]) if boards else 0.0
    rg = config.RISK_GATE
    gate = {"bars": 0, "notrade": 0, "nokline": 0}
    raw_all = []
    raw_reasons = {}
    for c, q in quotes.items():
        ks = klines.get(c) or []
        if not ks:
            gate["nokline"] += 1
            raw_reasons[c] = "no_kline"
            continue
        # 门槛一：上市/存续交易日不足（用实际K线根数，等价于交易日数）
        if len(ks) < rg["min_trading_days"]:
            gate["bars"] += 1
            raw_reasons[c] = "short_history"
            continue
        # 当日无成交只限制可交易候选；单凭零成交不能断言法定停牌。
        if num(q.get("amount_wan")) <= 0 and num(q.get("volume_shou")) <= 0:
            gate["notrade"] += 1
            raw_reasons[c] = "no_trade"
            continue
        m = F.stock_raw_metrics(c, ks, q)
        if not m:
            gate["bars"] += 1
            raw_reasons[c] = "raw_invalid"
            continue
        raw_all.append(m)
    # 历史成交额保留作参考，不再作为强度主榜的资格门槛。
    raw_list = raw_all
    snap["risk_gate"] = {
        "pool_in": len(quotes),
        "passed": len(raw_list),
        "dropped": gate,
        "min_trading_days": rg["min_trading_days"],
        "amount_basis": "成交量×收盘价 估算（腾讯历史K线不返回成交额）",
    }
    print(f"[GATE] 硬门槛：入池 {len(quotes)} → 通过 {len(raw_list)}"
          f"（剔除 交易日不足 {gate['bars']}、"
          f"无成交/停牌 {gate['notrade']}、无K线 {gate['nokline']}）")
    print(f"[RUN] 有效样本 {len(raw_list)} 只")

    # ── 空数据保护 ────────────────────────────────────────────────
    # 为什么必须有：集合竞价阶段（约 09:15-09:25）实时行情只有报价、没有成交额，
    # 门槛二「当日无成交」会把整个池子判成停牌 —— 实测 09:22 扫描得到
    # 「入池 3118 → 通过 0（停牌 3093）」。这份快照一旦落盘覆盖，看板会被清空成
    # "今天没有数据"。宁可这一轮不写：保留上一份数据，界面上的新鲜度指标会说明
    # 数据是旧的，用户看到的是"没更新"，而不是"数据没了"。
    _prev = int(previous_snapshot.get("stock_count") or 0)
    if len(raw_list) == 0 or (_prev and len(raw_list) < _prev * 0.6):
        # 盘前/集合竞价时成交额为 0 是正常现象；盘中仍触发则优先提示
        # “行情覆盖或历史K线不完整”，避免把 10:00 之后的源中断误报成竞价。
        if snap.get("session") in ("盘前", "集合竞价"):
            hint = "集合竞价期间成交额为 0 会被门槛二判成停牌"
        else:
            hint = (f"当前时段为{snap.get('session')}，"
                    "可能是行情尚无成交或历史K线尚未补齐")
        raise DataNotReady(
            f"本轮有效样本 {len(raw_list)} 只（上一份 {_prev} 只），行情大概率还没就绪"
            f"（{hint}）—— 已放弃写入，看板保留上一份数据")

    stocks = []
    quote_fields = ("price", "change_pct", "open", "high", "low", "last_close", "limit_up",
                    "limit_down", "limit_pct", "board_type", "board_name", "list_days", "is_new",
                    "amount_wan", "turnover_pct", "float_mcap_yi", "ts", "quote_at", "volume_shou",
                    "amplitude_pct", "vol_ratio")
    for source_row in raw_list:
        code = source_row["code"]
        row = dict(source_row,
                   boards=(board_ctx.get("code_boards") or {}).get(code, []),
                   industry=(board_ctx.get("industries") or {}).get(code, []))
        quote = quotes.get(code) or {}
        row.update({key: quote[key] for key in quote_fields if key in quote})
        stocks.append(row)
    price_only.clear_rows(stocks)
    for s in stocks:
        mapping = theme_map.get(s["code"]) or {}
        s["boards"] = list(mapping.get("themes") or [])
        s["display_boards"] = list(mapping.get("browse_themes") or mapping.get("themes") or [])
        s["concepts"] = list(mapping.get("f10_concepts") or [])
        s["attribute_tags"] = [name for name in s["concepts"] if not df._theme_ok(name)]
        s["member_only_themes"] = list(mapping.get("member_only_themes") or [])
        s["f10_only_themes"] = list(mapping.get("f10_only_themes") or [])
        s["theme_basis"] = mapping.get("theme_basis") or "归属待核对"
        s["theme_checked_at"] = mapping.get("theme_checked_at")
        s["industry_basis"] = mapping.get("industry_basis") or "行业待核对"
        s["industry"] = list(mapping.get("industry") or [])
        s["boards_em"] = []
    # 行业分组使用全池现有F10/详情映射；广度分母包含主榜以外的有效同伴。
    ind_path = config.CACHE_DIR / "ths_industry_members.json"
    ind_members = json.loads(ind_path.read_text(encoding="utf-8")).get("map", {}) if ind_path.exists() else {}
    industry_lookup = strength.industry_map(cached_profiles, ind_members)
    formal={c: history_cache[c][-160:] if c in history_cache else df.load_kline(conn,'kline','code',c,limit=160) for c in pool}
    formal_calendar=strength.trading_calendar({c:strength.completed(v) for c,v in formal.items()})
    if formal_calendar:
        snap['history_reference']=history_reference.ensure(formal,formal_calendar[-1])
        snap["fund_history"] = {"enabled": False, "requested": 0}
    try:
        stocks, model = strength.build(stocks, klines, industry_lookup)
    except ValueError as e:
        raise DataNotReady(str(e)) from e
    previous_asof = (previous_snapshot.get('strength_model') or {}).get('asof')
    if previous_asof and model['asof'] < previous_asof:
        raise DataNotReady(f"完成日线从 {previous_asof} 回退到 {model['asof']}，保留上一份快照")
    if not stocks:
        raise DataNotReady("完成日线对齐后无有效个股，保留上一份快照")
    market_emotion, emotion_detail, emotion_extra = emotion.build(
        quotes, klines, {s["code"] for s in stocks}, industry_lookup)
    emotion.enrich_stocks(stocks, emotion_detail, market_emotion)
    theme_assist.enrich_stocks(stocks)
    snap["market_emotion"] = market_emotion
    snap["emotion_candidates"] = emotion_extra
    snap["axis_counts"] = dict(Counter(s["axis_group"] for s in stocks))
    price_only.clear_rows(stocks)
    snap["strength_model"] = model
    snap["risk_gate"]["passed"] = len(stocks)
    snap["risk_gate"]["completed_day_dropped"] = model["dropped"]
    snap["stocks"] = stocks
    snap["stock_count"] = len(stocks)
    snap["board_catalog"] = board_center.build(stocks, quotes, theme_map, boards, fund_map,
                                               model["asof"])
    snap['board_catalog_version'] = board_center.VERSION
    import weekly_members
    snap['member_refresh'] = weekly_members.status()
    for item in snap["board_catalog"]:
        item["member_quote_at"] = snap["quote_capture_at"]
        item["fund_observed_at"] = (fund_meta.get("fetched_at") or snap["generated_at"])
        if not (item["fund_covered"] or item["fund_today_covered"]):
            item["fund_observed_at"] = None
    completed_bars = {c: strength.completed(v) for c, v in klines.items()}
    timer.mark("个股计算", "板块趋势与最新指数")
    import board_trend
    snap["board_trend_model"] = board_trend.attach(
        snap, strength.trading_calendar(completed_bars), fetch=True,
        previous_snapshot=previous_snapshot)
    timer.mark("板块趋势与最新指数", "盘中与结构")
    catalog, catalog_stats = coverage.build(
        quotes, klines, {s["code"] for s in stocks}, raw_reasons,
        {m["code"]: m for m in raw_all}, model["asof"],
        strength.trading_calendar(completed_bars),
        previous_rows=(previous_snapshot.get("stocks") or [])
                      + (previous_snapshot.get("coverage_catalog") or []))
    for row in catalog:
        mapping = theme_map.get(row["code"]) or {}
        row["boards"] = list(mapping.get("themes") or [])
        row["display_boards"] = list(mapping.get("browse_themes") or mapping.get("themes") or [])
        row["concepts"] = list(mapping.get("f10_concepts") or [])
        row["member_only_themes"] = list(mapping.get("member_only_themes") or [])
        row["f10_only_themes"] = list(mapping.get("f10_only_themes") or [])
        row["theme_basis"] = mapping.get("theme_basis") or "归属待核对"
        row["industry"] = list(mapping.get("industry") or [])
        fund = fund_map.get(row["code"]) or {}
        row["fund_today_yi"] = (round(fund["main_today"] / 1e8, 3)
                                if fund.get("main_today") is not None else None)
        row["fund_today_ratio"] = (round(fund["main_ratio"], 2)
                                   if fund.get("main_ratio") is not None else None)
        row["fund_today_source"] = fund_meta.get("source") if fund else None
        row["fund_today_at"] = fund_meta.get("fetched_at") if fund else None
        row["fund_state"] = "资金未知（完整多日覆盖不足）"
    snap["coverage_catalog"] = catalog
    snap["coverage_stats"] = catalog_stats
    # 盘中观察在日线模型之后独立计算；基础分由完整25根对齐完成日线决定。
    snap["intraday_model"] = intraday.enrich(
        stocks, catalog, quotes, klines, list(pool), captured_at=quote_capture_at,
        session=snap["session"], previous_snapshot=previous_snapshot,
        trading_calendar=strength.trading_calendar(completed_bars))
    price_contexts = snap["intraday_model"].pop("_price_contexts", {})
    path_history = snap['intraday_model'].pop('_history_context', {})
    # 9:30 后逐股正式报价可能分批到达；保留同日竞价参考，供未更新的股票标注来源。
    prior_auction = {str(row.get("code")): row.get("auction_observation")
                     for row in (previous_snapshot.get("stocks") or [])
                     + (previous_snapshot.get("coverage_catalog") or [])
                     if row.get("auction_observation")}
    for row in stocks + catalog:
        observation = prior_auction.get(str(row.get("code"))) or {}
        if str(observation.get("quote_at") or "").startswith(scan_started_at.strftime("%Y-%m-%d")):
            row["auction_observation"] = observation
    # 报价完全缺失的旧行保留最后一次有效值，但明确过期并停止产生新状态。
    visible_codes = {str(row.get("code")) for row in stocks + catalog}
    previous_rows = (previous_snapshot.get("stocks", []) +
                     previous_snapshot.get("coverage_catalog", []))
    for old in previous_rows:
        code = str(old.get("code") or "")
        if (not code or code in quotes or code in visible_codes
                or old.get("signal_date") != model.get("asof")):
            continue
        stale = dict(old)
        stale.update({
            "coverage_only": True, "quote_stale": True, "stale_carried": True,
            "intraday_quote_fresh": False, "intraday_score_stale": True,
            "intraday_observation_available": False, "intraday_judgment_at": None,
            "intraday_quote_status": "本轮报价缺失，沿用上次有效值",
            "intraday_score_delta": None, "intraday_delta_state": "报价缺失，停止比较",
            "intraday_transition": None, "intraday_trend_state": "数据不可判断（报价缺失）",
            "intraday_risk_level": "未知", "intraday_risk_flags": ["本轮报价缺失"],
            "intraday_risk_priority": 0, "intraday_serious_weakness": False,
            "current_strong_candidate": False, "current_pullback_candidate": False,
            "startup_candidate": False, "entry_watch": False,
            "intraday_active_candidate": False, "intraday_repair_candidate": False,
            "turn_weak_repair_candidate": False,
            "intraday_observation_state": "数据不可判断（报价缺失）",
            "last_valid_price": old.get("price"),
            "last_valid_change_pct": old.get("change_pct"),
            "last_valid_quote_at": old.get("intraday_quote_at"),
            "last_valid_intraday_score": old.get("intraday_score"),
            "reason_text": "本轮报价缺失；显示上次有效报价，当前状态未知",
        })
        catalog.append(stale)
        visible_codes.add(code)
    _apply_intraday_close_confirmation(snap, previous_snapshot)
    # 资金抓取可能晚于扫描开始；以实际判断时刻核验时效，避免把本轮资金误判成未来数据。
    snap["attack_assessment_at"] = datetime.now().isoformat(sep=" ", timespec="seconds")
    attack_model.enrich(snap, quotes, price_contexts, previous_snapshot)
    intraday.intraday_path.attach(snap, path_history)
    attack_model.retain_missing_observations(snap)
    visible_rows = stocks + catalog
    model["entry_watch_count"] = sum(bool(row.get("entry_watch")) for row in visible_rows)
    model["current_strong_count"] = sum(bool(row.get("current_strong_candidate")) for row in visible_rows)
    model["turn_weak_repair_count"] = sum(
        bool(row.get("turn_weak_repair_candidate")) for row in visible_rows)
    snap["stocks"] = stocks
    snap["stock_count"] = len(stocks)
    # 兼容旧页面字段；板块中心和下钻使用 board_catalog 的同一成员图。
    snap["board_chain"] = build_board_chain(boards, stocks)
    snap["theme_source"] = board_ctx.get("theme_source") or {
        "name": "同花顺概念 / 个股 F10",
        "member_source": "同花顺概念详情页成分名单（纯同花顺）",
        "industry_source": "同花顺个股 company.html 所属申万行业；行业详情页为补充",
        "stock_profile_source": "同花顺个股 concept.html 相关概念",
        "fallback": "无东财行业、题材、概念兜底",
    }

    snap["strategies"] = [dict(s) for s in config.STRATEGY["list"]]
    snap["strategy_factors"] = {k: list(v) for k, v in config.STRATEGY["factors"].items()}
    snap["strategy_weights"] = config.STRATEGY_WEIGHTS
    snap["factor_model_version"] = strength.VERSION
    snap["default_strategy"] = "trend"
    snap["radar"] = {"trend": radar.build_trend(stocks)}

    # 8. 题材热度（同花顺概念单一口径）
    snap["themes"] = build_themes(theme_groups, stocks)

    # 8·补、每日分析（主线 / 观察池 / 风险 / 持仓关注名单）
    snap["daily_advice"] = strength.daily_advice(snap)
    print(f"[RUN] 每日分析已生成（持仓关注名单 {len(snap['daily_advice']['hold_watch'])} 只）")

    # 9. 市场概览
    snap["breadth"] = build_breadth(quotes, stocks, emotion_detail)
    # 9·补、板别构成（四板口径下必须有，否则用户会把 20% 板当主板看）
    snap["board_mix"] = board_mix(quotes, stocks, emotion_detail)
    snap["board_names"] = {k: v["name"] for k, v in config.BOARDS.items()}
    # 池内实际纳入的板别 —— 界面上的"覆盖 XX · YY"与板别筛选项都从这里来，
    # 不再硬编码"沪深四板"（收板/扩板时文案才不会说谎）
    snap["pool_boards"] = config.pool_board_names()
    snap["board_limit_by_name"] = {v["name"]: v["limit_pct"] for v in config.BOARDS.values()}
    snap["new_stock_days"] = config.POOL.get("new_stock_days", 60)
    # 次新入榜情况（口径披露）：池里有几只、真正参与打分的几只。
    # 差集不是"漏了"，而是上市不足 25 个交易日的次新拿不到 MA20/量比基线 ——
    # 强行纳入只会让它们在最长的那个周期上被当成"数据缺失=最差"来扣分。
    # 这个数字必须露出来，否则用户看到"池内次新 20 只"却只筛到 7 只，会以为筛选坏了。
    _np = sum(1 for q in quotes.values() if num(q.get("is_new")))
    _ns = sum(1 for s in stocks if num(s.get("is_new")))
    snap["new_stock_stat"] = {"pool": _np, "scored": _ns,
                              "excluded": max(0, _np - _ns),
                              "min_bars": config.RISK_GATE["min_trading_days"], "min_days": config.POOL.get("new_stock_days", 60)}
    if _np:
        print(f"[RUN] 次新 {_np} 只（其中 {_ns} 只参与打分，"
              f"{snap['new_stock_stat']['excluded']} 只历史日线不足或日期未对齐，未入榜）")
    mix_txt = "、".join(f"{k}{v['n']}" for k, v in
                       sorted(snap["board_mix"].items(), key=lambda kv: -kv[1]["n"]))
    print(f"[RUN] 板别构成 {mix_txt}")

    # 10. 完成日线突破观察
    snap["alerts"] = strength.breakout_alerts(stocks)

    # 附：东财状态
    snap["em_status"] = df.em_status()
    snap["data_sources"] = df.source_health_snapshot()
    snap["elapsed"] = round(time.time() - t_start, 1)
    scan_completed_at = datetime.now()
    snap["scan_completed_at"] = scan_completed_at.isoformat(sep=" ", timespec="seconds")
    snap["generated_at"] = scan_completed_at.strftime("%Y-%m-%d %H:%M:%S")
    close_monitor.attach(snap, quotes, klines, price_contexts=price_contexts,
                         trading_calendar=strength.trading_calendar(completed_bars))
    trend_consolidation.attach(snap, klines, quotes, price_contexts,
        strength.trading_calendar(completed_bars), history=path_history,
        previous=previous_snapshot, persist=True,
        close_history_loader=lambda code: history_cache[code] if code in history_cache else df.load_kline(conn,'kline','code',code))
    wyckoff_structure.attach(snap, klines, strength.trading_calendar(completed_bars),
                            contexts=price_contexts, history=path_history, persist=True,
                            daily_history_loader=lambda code: history_cache[code] if code in history_cache else df.load_kline(conn,'kline','code',code))
    price_only.sanitize(snap)
    session_context.attach(snap,quotes,formal,formal_calendar,contexts=price_contexts)

    timer.mark("盘中与结构", "观察留档与研究")
    append_history(snap)
    strength.save_observation(snap)
    stock_strength.save_daily(snap)
    intraday.save_observation(snap)
    snap["intraday_research"] = intraday.build_validation_report()
    scan_cache.flush()
    timer.mark("观察留档与研究", "快照写盘")
    snap['scan_performance'] = timer.result()
    snap['elapsed'] = round(time.time()-t_start, 3)
    # generated_at remains the judgment clock; performance clocks are separate.
    # 研究报告随快照更新，页面与磁盘快照继续保持同一版本。
    config.atomic_write_text(
        config.SNAPSHOT_JSON,
        json.dumps(snap, ensure_ascii=False, separators=(",", ":")))
    timer.mark("快照写盘", "页面发布")
    snap['scan_performance'] = timer.result()
    snap['elapsed'] = round(time.time()-t_start, 3)
    print(f"[RUN] 扫描完成（含写盘），耗时 {snap['elapsed']}s -> {config.SNAPSHOT_JSON.name}")
    return snap


def build_themes(theme_groups, stocks):
    """题材热度 —— 同花顺概念单一口径

    ranked（题材强度榜）：题材组内等权涨幅 + 上涨占比排序，带成员数可自证样本量
    hot_tags（领涨题材）**：当日涨停个股身上的同花顺概念词频

    为什么领涨题材不用同花顺 event 的 reason 词频（2026-09-18 改）：
      reason 返回的是「次新股 / 业绩增长 / 上海国资」这类**归因短语**，
      跟个股标签上的概念名不是一套命名，点击后筛不到任何个股 —— 用户反馈的
      "点领涨题材跳不到对应个股"就是这个原因。改成统计涨停股的概念归属后，
      词与个股标签同源，点一下必然落到对应股票上。
    """
    ranked = rank_themes(theme_groups, min_members=config.THEME["rank_min_members"], top=30)
    from collections import Counter
    cnt = Counter()
    limit_cnt = 0
    for s in stocks:
        if not s.get("limit_today"):
            continue
        limit_cnt += 1
        for t in s.get("boards") or []:
            cnt[t] += 1
    tags = [{"theme": t, "count": n} for t, n in cnt.most_common(36)]
    return {"ranked": ranked, "hot_tags": tags, "hot_count": limit_cnt}


# ─────────────────────────────────────────────────────
# 每日分析 —— 把当天数据翻译成四类可直接执行的结论
#
# 为什么放在服务端算：结论依赖跨标的的排序与分位（谁在领涨、谁资金真在进），
# 生成快照时算一次就好，看板打开时只负责展示，不做重计算。
#
# 四类（用户 2026-09-18 指定，全部要）：
#   mainline   今日主线题材向 —— 区分「资金真进」与「情绪脉冲」
#   watch      明日观察池 —— 低位启动 / 缩量回踩 / 周期共振
#   risk       风险提示 —— 高位乖离 / 高位资金背离 / 连板断板
#   hold_watch 持仓关注名单 —— 触发减仓信号的个股，看板与本地持仓求交集后落地
# ─────────────────────────────────────────────────────
def _yi(v):
    """元 → 亿元文本"""
    y = num(v) / 1e8
    if abs(y) >= 1:
        return f"{y:.1f}亿"
    return f"{y * 1e4:.0f}万"


def _small(s, ths_display=None):
    """个股精简引用（看板用它做点击联动）。

    ``ths_display`` 是同花顺个股 F10 的概念顺序；没有拿到时才退回完整
    题材映射。不能直接取 ``boards[:2]``，因为成员页是并发抓取的，顺序
    不是个股的归因顺序，曾把宏和科技的“海峡两岸”显示在 PCB 前面。
    """
    ordered = (ths_display or {}).get(str(s.get("code"))) or s.get("boards") or []
    return {"code": s.get("code"), "name": s.get("name"),
            "chg": round(num(s.get("change_pct")), 2),
            "score": round(num(s.get("score")), 1),
            # 板别跟着一起下发：每日分析/抽屉里的个股也要标出属于哪个板，
            # 否则 20% 板的票混在主板票里看不出区别
            "board": s.get("board_name"), "is_new": int(num(s.get("is_new"))),
            "themes": ordered[:2]}


def build_breadth(quotes, stocks, emotion_detail=None):
    # 涨跌与涨停均以同一批有当日报价且实际成交的股票为分母。
    eligible = set(emotion_detail) if emotion_detail is not None else set(quotes)
    up = sum(1 for code in eligible if num(quotes[code].get("change_pct")) > 0)
    dn = sum(1 for code in eligible if num(quotes[code].get("change_pct")) < 0)
    flat = len(quotes) - up - dn
    # 与上涨家数使用同一报价池；不从经过流动性/趋势过滤的 stocks 计数。
    emotion_detail = emotion_detail or {}
    limit_up = sum(bool(v.get("emotion_limit")) for v in emotion_detail.values())
    lu_mix = {}
    for code, v in emotion_detail.items():
        if v.get("emotion_limit"):
            k = quotes[code].get("board_name") or "未知"
            lu_mix[k] = lu_mix.get(k, 0) + 1
    # 尚未成交的个股：开盘初期占比可观，其涨跌幅恒为 0，不应被当作"平盘"解读
    no_trade = sum(1 for q in quotes.values() if num(q.get("amount_wan")) <= 0)
    traded = len(eligible)
    return {
        "up": up, "down": dn, "flat": flat, "no_trade": no_trade, "traded": traded,
        "up_ratio": round(up / max(1, up + dn) * 100, 1),
        "limit_up": limit_up, "limit_up_mix": lu_mix,
    }


def board_mix(quotes, stocks, emotion_detail=None):
    """板别构成统计 —— 总览页用它说明"这张榜里到底有哪些板"。

    扩容到四板后，如果界面只写"沪深主板"，用户会把 20% 板的个股
    当成主板票来看，风险判断会偏。所以板别构成必须显式给出。
    """
    mix = {}
    eligible = set(emotion_detail) if emotion_detail is not None else set(quotes)
    for code, q in quotes.items():
        k = q.get("board_name") or "未知"
        d = mix.setdefault(k, {"n": 0, "up": 0, "down": 0, "limit_up": 0, "new": 0})
        d["n"] += 1
        if code in eligible:
            ch = num(q.get("change_pct"))
            if ch > 0:
                d["up"] += 1
            elif ch < 0:
                d["down"] += 1
        if num(q.get("is_new")):
            d["new"] += 1
    for code, v in (emotion_detail or {}).items():
        if v.get("emotion_limit"):
            k = quotes[code].get("board_name") or "未知"
            if k in mix:
                mix[k]["limit_up"] += 1
    for k, d in mix.items():
        d["up_ratio"] = round(d["up"] / max(1, d["up"] + d["down"]) * 100, 1)
    return mix


# ─────────────────────────────────────────────────────
# 异动告警
# ─────────────────────────────────────────────────────
def _hist_path():
    return config.CACHE_DIR / "history.jsonl"


def append_history(snap):
    slim = {
        "ts": snap["generated_at"],
        "model": snap.get("factor_model_version"),
        "boards": {b["name"]: b["score"] for b in snap.get("boards", [])},
        "stocks": {s["code"]: s["score"] for s in snap.get("stocks", [])[:300]},
    }
    with open(_hist_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(slim, ensure_ascii=False) + "\n")


def _load_prev():
    p = _hist_path()
    if not p.exists():
        return None
    lines = p.read_text(encoding="utf-8").strip().split("\n")
    # 取上一条（最后一条是刚写入的当前）
    for line in reversed(lines[:-1] if len(lines) > 1 else []):
        try:
            return json.loads(line)
        except Exception:
            continue
    return None


def detect_alerts(snap):
    """对比上一次快照，识别板块/个股强度跃升、放量突破、RS突破、外围背离"""
    prev = _load_prev()
    alerts = []
    if not prev:
        return alerts

    cfg = config.ALERT
    # 板块跃升
    pboards = prev.get("boards", {})
    for b in snap.get("boards", [])[:40]:
        old = pboards.get(b["name"])
        if old is not None and b["score"] - old >= cfg["board_score_jump"]:
            alerts.append({"type": "板块强度跃升", "level": "high",
                           "text": f"{b['name']} 强度 {old:.1f} → {b['score']:.1f}（+{b['score']-old:.1f}）",
                           "target": b["name"]})
    # 个股跃升 + 放量突破 + RS突破
    pstocks = prev.get("stocks", {})
    for s in snap.get("stocks", [])[:200]:
        old = pstocks.get(s["code"])
        if old is not None and s["score"] - old >= cfg["stock_score_jump"]:
            alerts.append({"type": "个股强度跃升", "level": "high",
                           "text": f"{s['name']}({s['code']}) 强度 {old:.1f} → {s['score']:.1f}",
                           "target": s["code"]})
        if s.get("vol_ratio5", 0) >= cfg["volume_surge_ratio"] and num(s.get("change_pct")) > 3:
            partial_note = "；未完成日K，仅为截至当前累计量" if s.get("vol_partial") else ""
            alerts.append({"type": "放量突破", "level": "mid",
                           "text": f"{s['name']}({s['code']}) {s['change_pct']:+.2f}%，累计量/5日均量 {s['vol_ratio5']}{partial_note}",
                           "target": s["code"]})
    # 外围背离
    comp = num(snap.get("outer", {}).get("composite"))
    b = snap.get("breadth", {})
    if abs(comp) >= cfg["outer_diverge"]:
        a_ratio = num(b.get("up_ratio"), 50)
        if (comp > 0 and a_ratio < 40) or (comp < 0 and a_ratio > 60):
            alerts.append({"type": "外围背离", "level": "mid",
                           "text": f"隔夜外围 {comp:+.2f}%，A股上涨占比 {a_ratio}%，方向背离",
                           "target": "market"})
    # 去重 + 截断
    seen, out = set(), []
    for a in alerts:
        k = (a["type"], a["target"])
        if k not in seen:
            seen.add(k)
            out.append(a)
    return out[:40]


if __name__ == "__main__":
    import sys
    m = sys.argv[1] if len(sys.argv) > 1 else "quick"
    s = run(mode=m, rebuild_pool=(m == "full"))
    print(json.dumps({k: (v if not isinstance(v, list) else f"<{len(v)} items>")
                      for k, v in s.items() if k not in ("stocks",)},
                     ensure_ascii=False, indent=2)[:2500])
