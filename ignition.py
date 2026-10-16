# -*- coding: utf-8 -*-
"""短线启动模型 Ignition-1 —— 打分与硬门槛

与 factors.build_stock_scores（波段趋势 V3）**完全独立**：
各自算各自的分位、各自的权重、各自的候选集，只在数据层共用
K线/行情/题材。绝不把任何一边的分位混进另一边的总分。

核心思想（用户给定的规格）：
  不是找"今天涨得很多"，而是找「Base → Breakout 状态转换发生的第一天」——
  蓄势（压缩）→ 今天首次有效突破平台 → 量能点火 → 板块从无到有启动。
  所以从"趋势强度"转向"趋势变化率"：问的不是 Trend 有多强，而是 ΔTrend 是否刚转正。

先 Gate 再评分：不是首日突破、或已经加速过头的，直接不算候选（ign_score=None）。
"""
import math

import config
import factors as F

IG = config.IGNITION


def _pct_keep_none(vals_by_code):
    """池内分位（0~100）。None 保留 None —— 绝不能当成最小值排到最后。"""
    out = {c: None for c in vals_by_code}
    have = [(c, v) for c, v in vals_by_code.items() if v is not None]
    if not have:
        return out
    have.sort(key=lambda kv: kv[1])
    n = len(have)
    i = 0
    while i < n:
        j = i + 1
        while j < n and have[j][1] == have[i][1]:
            j += 1
        mid = (i + j - 1) / 2.0
        score = round(mid / (n - 1) * 100, 2) if n > 1 else 50.0
        for k in range(i, j):
            out[have[k][0]] = score
        i = j
    return out


def _band(v, ideal_lo, ideal_hi, ok_lo, ok_hi, floor=10.0):
    """区间打分：ideal 内 100，ok 内线性 70~100，ok 之外朝 floor 衰减。

    （"量比不是越大越好"这类形状统一的记分 —— 中间高、两头低。）
    """
    if v is None:
        return None
    if ideal_lo <= v <= ideal_hi:
        return 100.0
    if ok_lo <= v < ideal_lo:
        return 70.0 + 30.0 * (v - ok_lo) / max(1e-9, ideal_lo - ok_lo)
    if ideal_hi < v <= ok_hi:
        return 70.0 + 30.0 * (ok_hi - v) / max(1e-9, ok_hi - ideal_hi)
    if v < ok_lo:
        return max(floor, 70.0 * (v / ok_lo) if ok_lo > 0 else floor)
    return max(floor, 70.0 * (1 - (v - ok_hi) / max(1e-9, ok_hi)))


def _pre_rs_band(excess):
    """突破前相对强度（绝对超额 %，不是全池分位）。

    短线启动要的是"已经悄悄跑赢市场，但尚未成为最拥挤的一批"：
    理想带是 +2%~+8% 的超额（跑赢但没疯），过高说明可能早启动数日、
    过低说明没有资金提前布局。用绝对超额带宽而不是全池分位 ——
    全池分位会把"悄悄涨了 4%"和"已经疯涨"都塞进 60~88 分位，人人 100，失去判别力。
    """
    if excess is None:
        return None
    e = excess
    if 2.0 <= e <= 8.0:
        return 100.0
    if 0.0 <= e < 2.0:
        return 70.0 + 30.0 * e / 2.0
    if 8.0 < e <= 15.0:
        return 100.0 - 40.0 * (e - 8.0) / 7.0
    if e > 15.0:
        return max(0.0, 60.0 - (e - 15.0) * 4.0)
    return max(0.0, 55.0 + e * 5.0)     # e < 0：越弱越低，-11% 归零


def _triangular(pct, ideal_lo, ideal_hi, too_hot, too_weak):
    """（保留：供未来全池分位版本复用，当前前置RS已改用绝对超额带宽。）"""
    if pct is None:
        return None
    if ideal_lo <= pct <= ideal_hi:
        return 100.0
    if too_weak < pct < ideal_lo:
        return 55.0 + 45.0 * (pct - too_weak) / max(1e-9, ideal_lo - too_weak)
    if ideal_hi < pct <= too_hot:
        return 55.0 + 45.0 * (too_hot - pct) / max(1e-9, too_hot - ideal_hi)
    if pct > too_hot:
        return max(0.0, 55.0 * (1 - (pct - too_hot) / (100 - too_hot)))
    return max(0.0, 55.0 * (pct / too_weak) if too_weak > 0 else 0.0)


def _ign_sector_ctx(raw_list, code_boards):
    """短线启动版的板块级指标 —— 与 trend 的 _sector_metrics 独立计算。

    成分口径同 trend：通过 Risk Gate 的池内成员。
    相对市场收益用**当日**超额（板块平均涨跌幅 − 全市场中位涨跌幅），
    近 3 日持续性并入「上涨家数比例」里（当日 + 近3日平均）。
    """
    chgs = [F.num(r.get("change_pct")) for r in raw_list]
    market_chg = F.median(chgs)
    buckets = {}
    for r in raw_list:
        for t in code_boards.get(r["code"], []):
            buckets.setdefault(t, []).append(r)
    out = {}
    for t, ms in buckets.items():
        k = len(ms)
        if k < config.SECTOR_MEMBER_MIN or k > config.SECTOR_MEMBER_MAX:
            continue
        if not any(r.get("change_pct") is not None for r in ms):
            continue
        mean_chg = F.mean([r.get("change_pct") for r in ms])
        b1 = sum(1 for r in ms if F.num(r.get("change_pct")) > 0) / k * 100
        b3 = F.mean([min(3, F.num(r.get("up_days_3"))) / 3.0 for r in ms]) * 100
        nh = sum(1 for r in ms if F.num(r.get("is_high20"))) / k * 100
        a5 = sum(F.num(r.get("amt_ma5_wan")) for r in ms)
        a20 = sum(F.num(r.get("amt_ma20_wan")) for r in ms)
        out[t] = {
            "n": k,
            "excess": mean_chg - market_chg,      # 当日相对市场收益
            "breadth": 0.5 * b1 + 0.5 * b3,       # 上涨家数（当日 + 近3日）
            "new_high": nh,
            "amt_expand": (a5 / a20) if a20 > 0 else 1.0,
        }
    return out


def build_scores(raw_list, code_boards):
    """计算 Ignition-1 六因子与硬门槛。

    返回 dict[code] → {"ign_score": float|None, "ign_factors": {...}|None,
                       "ign_pass": bool, "ign_reasons": [str], "ign_top_theme": str|None}
    未通过门槛的股票 ign_score=None（= 当前不是短线启动窗口），照常写进快照供界面说明原因。
    """
    result = {}
    if not raw_list:
        return result

    # ── 板块级指标（独立计算，只共用题材数据）──
    sec = _ign_sector_ctx(raw_list, code_boards)
    sw = config.IGNITION_SUB["sector"]
    if sec:
        keys = list(sec)
        p_ex = _pct_keep_none({t: sec[t]["excess"] for t in keys})
        p_bd = _pct_keep_none({t: sec[t]["breadth"] for t in keys})
        p_nh = _pct_keep_none({t: sec[t]["new_high"] for t in keys})
        p_ae = _pct_keep_none({t: sec[t]["amt_expand"] for t in keys})
        sec_score = {t: F.clampf(sw["excess"] * (p_ex[t] or 0) + sw["breadth"] * (p_bd[t] or 0)
                                 + sw["new_high"] * (p_nh[t] or 0) + sw["amt_expand"] * (p_ae[t] or 0))
                     for t in keys}
        sec_excess = {t: sec[t]["excess"] for t in keys}
    else:
        sec_score, sec_excess = {}, {}

    # 突破前 20 日相对市场收益：用**绝对超额**（r20_pre - 全市场中位 r20_pre），
    # 而不是全池分位 —— 见 _pre_rs_band 的注释
    med_r20_pre = F.median([r.get("r20_pre") for r in raw_list
                            if r.get("r20_pre") is not None])

    # ── 池内分位原料 ──
    codes = [r["code"] for r in raw_list]
    bycode = {r["code"]: r for r in raw_list}
    p_atr = _pct_keep_none({c: bycode[c].get("atr_contract") for c in codes})
    p_rng = _pct_keep_none({c: bycode[c].get("range20") for c in codes})
    p_vct = _pct_keep_none({c: bycode[c].get("vol_contract") for c in codes})
    p_mcv = _pct_keep_none({c: bycode[c].get("ma_converge") for c in codes})
    p_r20 = _pct_keep_none({c: bycode[c].get("r20_pre") for c in codes})
    p_r5 = _pct_keep_none({c: bycode[c].get("r5_pre") for c in codes})
    p_vr = _pct_keep_none({c: bycode[c].get("vr") for c in codes})
    p_turn = _pct_keep_none({c: bycode[c].get("vol_pct_120") for c in codes})

    # 行业相对强度（突破前 20 日）：先按题材算中位，再算个股对题材的超额
    ind_med = {}
    for t, ms in {t: [bycode[r["code"]] for r in raw_list
                      if t in code_boards.get(r["code"], [])] for t in sec}.items():
        ind_med[t] = F.median([m.get("r20_pre") for m in ms if m.get("r20_pre") is not None])
    p_ind = {}
    for c in codes:
        names = [t for t in code_boards.get(c, []) if t in ind_med]
        if names and bycode[c].get("r20_pre") is not None:
            p_ind[c] = F.median([(bycode[c]["r20_pre"] - ind_med[t]) for t in names])
        else:
            p_ind[c] = None
    p_ind_pct = _pct_keep_none(p_ind)

    w = config.STRATEGY_WEIGHTS["ignition"]
    gate = config.IGNITION["gate"]
    dropped = {"not_first": 0, "r5_hot": 0, "dist_far": 0, "no_plat": 0,
               "weak_close": 0, "bad_break": 0, "weak_sector": 0}

    for r in raw_list:
        c = r["code"]
        reasons = []

        # ── 硬门槛（先 Gate）──
        age = r.get("breakout_age")
        max_age = int(gate.get("max_breakout_age", 0) or 0)
        if age is None or int(age) > max_age:
            result[c] = {"ign_score": None, "ign_factors": None, "ign_pass": False,
                         "ign_reasons": [f"最近一次 Base→Breakout 已超过 {max_age} 日确认窗口"],
                         "ign_top_theme": None}
            dropped["not_first"] += 1
            continue
        # 当前必须仍站在平台上；突破后跌回平台不进入确认窗口。
        if not r.get("broke20"):
            result[c] = {"ign_score": None, "ign_factors": None, "ign_pass": False,
                         "ign_reasons": ["突破后已跌回 20 日平台"],
                         "ign_top_theme": None}
            dropped["not_first"] += 1
            continue
        # 盘中触及平台但收盘失守，或收盘落在全天中下部，不允许被其它高分抵消。
        if r.get("intraday_fail"):
            result[c] = {"ign_score": None, "ign_factors": None, "ign_pass": False,
                         "ign_reasons": ["盘中突破后收盘失守平台"],
                         "ign_top_theme": None}
            dropped["bad_break"] += 1
            continue
        _clv_now = r.get("clv")
        if _clv_now is not None and _clv_now < config.EXECUTION["short"]["min_clv"]:
            result[c] = {"ign_score": None, "ign_factors": None, "ign_pass": False,
                         "ign_reasons": [f"收盘承接偏弱（CLV {_clv_now:.2f}）"],
                         "ign_top_theme": None}
            dropped["weak_close"] += 1
            continue
        # 连续两板及以上通常已经进入延续段，不再把它当作新启动。
        if int(r.get("limit_streak") or 0) >= 2:
            result[c] = {"ign_score": None, "ign_factors": None, "ign_pass": False,
                         "ign_reasons": [f"已 {int(r.get('limit_streak'))} 连板，启动不是今天"],
                         "ign_top_theme": None}
            dropped["not_first"] += 1
            continue
        if r.get("ph20") is None:
            result[c] = {"ign_score": None, "ign_factors": None, "ign_pass": False,
                         "ign_reasons": ["K线不足以判定平台（缺突破前窗口）"],
                         "ign_top_theme": None}
            dropped["no_plat"] += 1
            continue
        r5_pre = r.get("r5_pre")
        p_r5v = p_r5.get(c)
        if r5_pre is not None and r5_pre >= gate["r5_pre_max"]:
            result[c] = {"ign_score": None, "ign_factors": None, "ign_pass": False,
                         "ign_reasons": [f"突破前 5 日已涨 {r5_pre:.1f}%（≥{gate['r5_pre_max']:.0f}%），不是短线启动窗口"],
                         "ign_top_theme": None}
            dropped["r5_hot"] += 1
            continue
        if p_r5v is not None and p_r5v >= 98.0:
            result[c] = {"ign_score": None, "ign_factors": None, "ign_pass": False,
                         "ign_reasons": ["突破前 5 日涨幅已进全市场前 2%，大概率不是第一天"],
                         "ign_top_theme": None}
            dropped["r5_hot"] += 1
            continue
        dpre = r.get("dist_pre_atr")
        if dpre is not None and dpre > gate["dist_atr_max"]:
            result[c] = {"ign_score": None, "ign_factors": None, "ign_pass": False,
                         "ign_reasons": [f"突破前距 MA20 已达 {dpre:.2f} ATR（>{gate['dist_atr_max']}），属已启动"],
                         "ign_top_theme": None}
            dropped["dist_far"] += 1
            continue
        _brk = r.get("brk_pct")
        if (_brk is not None and (_brk < config.EXECUTION["short"]["min_break_pct"]
                                  or _brk > config.EXECUTION["short"]["max_break_pct"])):
            result[c] = {"ign_score": None, "ign_factors": None, "ign_pass": False,
                         "ign_reasons": [f"有效突破幅度 {_brk:.1f}% 超出可执行区间"],
                         "ign_top_theme": None}
            dropped["bad_break"] += 1
            continue
        if (r.get("dist_atr") is not None
                and r.get("dist_atr") > config.EXECUTION["short"]["max_dist_atr"]):
            result[c] = {"ign_score": None, "ign_factors": None, "ign_pass": False,
                         "ign_reasons": [f"当前距 MA20 已达 {r['dist_atr']:.2f} ATR，追价距离过大"],
                         "ign_top_theme": None}
            dropped["dist_far"] += 1
            continue

        # ── 蓄势 / 压缩质量（越小越紧，越好）──
        bw = config.IGNITION_SUB["base"]
        base = _wsum([
            (100 - p_atr.get(c)) if p_atr.get(c) is not None else None,
            (100 - p_rng.get(c)) if p_rng.get(c) is not None else None,
            (100 - p_vct.get(c)) if p_vct.get(c) is not None else None,
            (100 - p_mcv.get(c)) if p_mcv.get(c) is not None else None,
        ], [bw["atr_contract"], bw["range"], bw["vol_contract"], bw["ma_converge"]])

        # ── 首日突破质量 ──
        bw = config.IGNITION_SUB["breakout"]
        brk = r.get("brk_pct")
        q_brk = _band(brk, *config.IGNITION["brk_ideal"],
                      config.IGNITION["brk_ideal"][0], 12.0, floor=35.0) \
            if brk is not None else 55.0
        q60 = 100.0 if r.get("broke60") else 55.0
        clv = r.get("breakout_clv") if r.get("breakout_clv") is not None else (
            r.get("clv") if r.get("clv") is not None else 0.5)
        if clv >= config.IGNITION["clv_good"]:
            q_clv = 100.0
        elif clv <= config.IGNITION["clv_fail"]:
            q_clv = 20.0          # 盘中突破又跌回全天中下部 → 大幅降分
        else:
            q_clv = 20.0 + 80.0 * (clv - config.IGNITION["clv_fail"]) / \
                max(1e-9, config.IGNITION["clv_good"] - config.IGNITION["clv_fail"])
        amp = r.get("amplitude")
        q_amp = 100.0 if (amp is None or amp <= 8.0) else \
            (70.0 if amp <= 12.0 else 35.0)
        breakout = F.clampf(bw["break20"] * q_brk + bw["break60"] * q60
                            + bw["clv"] * q_clv + bw["amp_ok"] * q_amp)

        # ── 量价点火 ──
        bw = config.IGNITION_SUB["ignite"]
        vr = r.get("vr")
        q_vr = _band(vr, *config.IGNITION["vr_ideal"], *config.IGNITION["vr_ok"], floor=10.0)
        turn = r.get("vol_pct_120")
        q_turn = _band(turn, *config.IGNITION["turn_ideal"], 40.0, 100.0, floor=15.0)
        if turn is not None and turn >= config.IGNITION["turn_extreme"]:
            q_turn = min(q_turn, 30.0)    # 极端 99 分位 → 派发风险
        ignite = _wsum([q_vr, q_turn], [bw["vr"], bw["turn"]])

        # ── 板块启动 / 扩散 ──
        names = [t for t in code_boards.get(c, []) if t in sec_score]
        if names:
            names.sort(key=lambda t: -sec_score[t])
            wsum = wtot = 0.0
            for wgt, t in zip(config.SECTOR_BLEND, names[:len(config.SECTOR_BLEND)]):
                wsum += wgt * sec_score[t]
                wtot += wgt
            sector = wsum / wtot if wtot else None
            top_theme = names[0]
        else:
            sector, top_theme = None, None

        # 启动模型要求有可验证的群体扩散；板块缺失只能列为观察，不能放行新仓。
        if sector is None or sector < config.EXECUTION["short"]["min_sector"]:
            result[c] = {"ign_score": None, "ign_factors": None, "ign_pass": False,
                         "ign_reasons": ["板块扩散不足或板块数据缺失"],
                         "ign_top_theme": top_theme}
            dropped["weak_sector"] += 1
            continue

        # ── 突破前相对强度（绝对超额带宽，见 _pre_rs_band）──
        bw = config.IGNITION_SUB["pre_rs"]
        r20p = r.get("r20_pre")
        ex_mkt = (r20p - med_r20_pre) if (r20p is not None) else None
        ex_ind = p_ind.get(c)          # 个股相对所属题材中位 r20_pre 的超额（绝对 %）
        pre_rs = _wsum([_pre_rs_band(ex_mkt), _pre_rs_band(ex_ind)],
                       [bw["market"], bw["industry"]])

        # ── 假突破健康度（从 100 往下扣）──
        fake = 100.0
        gap = r.get("gap_pct")
        if gap is not None and gap > config.IGNITION["gap_max"]:
            fake -= min(30.0, (gap - config.IGNITION["gap_max"]) * 4)
            reasons.append(f"高开 {gap:.1f}%，开盘即透支")
        _shadow = (r.get("breakout_upper_shadow")
                   if r.get("breakout_upper_shadow") is not None
                   else r.get("upper_shadow"))
        if _shadow is not None and _shadow > config.IGNITION["shadow_hi"]:
            fake -= 20.0
            reasons.append("长上影，盘中冲高被压回")
        if r.get("blasted"):
            fake -= 25.0
            reasons.append("炸板（触板未封住）")
        if r.get("intraday_fail"):
            fake -= 35.0
            reasons.append("盘中突破后又跌回平台（收盘失守）")
        ff = r.get("fall_from_high")
        if ff is not None and ff < -3.0:
            fake -= min(20.0, (-ff - 3.0) * 4)
            reasons.append("尾盘明显回落")
        if r5_pre is not None and r5_pre >= gate["r5_pre_soft"]:
            fake -= min(25.0, (r5_pre - gate["r5_pre_soft"]) * 2)
            reasons.append(f"突破前 5 日已涨 {r5_pre:.1f}%，有伪首日嫌疑")
        if vr is not None and vr >= config.IGNITION["vr_ok"][1] and F.num(r.get("change_pct")) < 3.0:
            fake -= 20.0
            reasons.append("爆量滞涨（量能极大但涨幅有限）")
        if top_theme and sec_excess.get(top_theme, 0) < 0:
            fake -= 15.0
            reasons.append("板块逆势（所属题材当日跑输市场）")
        fake = F.clampf(fake)

        # ── 加权汇总 ──
        f = {"base": base, "breakout": breakout, "ignite": ignite,
             "sector": sector, "pre_rs": pre_rs, "fake": fake}
        avail = [k for k in w if f.get(k) is not None]
        ws = sum(w[k] for k in avail)
        total = sum(w[k] * f[k] for k in avail) / ws if ws else None
        # 确认窗口越靠后，候选分略微衰减，但仍保留在候选池供复盘。
        if total is not None and age:
            total *= max(0.85, 1.0 - 0.05 * int(age))
            reasons.append(f"突破后第 {int(age) + 1} 日确认")
        total = round(F.clampf(total), 2) if total is not None else None

        result[c] = {
            "ign_score": total,
            "ign_factors": {k: (round(f[k], 2) if f[k] is not None else None) for k in w},
            "ign_pass": True,
            "ign_reasons": reasons,
            "ign_top_theme": top_theme,
            # Ignition 自己的板块上下文（当日相对市场收益），供雷达注释用 ——
            # 与 trend 的 sec_ctx（20 日超额）不是一回事，不能互借
            "ign_sec_ctx": (None if top_theme is None else {
                "name": top_theme,
                "n": sec[top_theme]["n"],
                "breadth": round(sec[top_theme]["breadth"], 1),
                "new_high": round(sec[top_theme]["new_high"], 1),
                "excess": round(sec[top_theme]["excess"], 2),
                "amt_expand": round(sec[top_theme]["amt_expand"], 2),
            }),
        }

    result["_meta"] = {"candidates": sum(1 for v in result.values()
                                         if v.get("ign_pass")),
                       "dropped": dropped}
    return result


def _wsum(vals, weights):
    """带权平均，缺失项按可用权重重新归一化（不打 0 分、不塞 50 分）。"""
    pairs = [(v, wt) for v, wt in zip(vals, weights) if v is not None]
    if not pairs:
        return None
    wtot = sum(wt for _, wt in pairs)
    return sum(v * wt for v, wt in pairs) / wtot
