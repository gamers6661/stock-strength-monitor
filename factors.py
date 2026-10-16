# -*- coding: utf-8 -*-
"""因子计算层 —— 纯函数，不碰网络

每个因子先算「原始指标」，再在全池内做分位归一化(0-100)，
这样不同量纲的指标可以相加，且结果天然是"相对强弱"而非绝对值。
"""
import math
from datetime import datetime

import config

# 涨跌停幅度不再用全局常量 —— 主板 ±10%、创业板/科创板 ±20%，
# 由 config.board_of(code) / config.limit_pct_for(code, list_days) 按股决定。
# 保留这个名字只为兼容旧的探测脚本，逻辑代码一律不要再引用它。
LIMIT_PCT = 9.8


# ─────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────
def pct_rank(values, reverse=False):
    """把一组数值映射为 0-100 分位分。

    reverse=False（默认）：数值越大分越高
    reverse=True        ：数值越小分越高

    相同数值使用并列名次的平均位置，避免结果依赖输入顺序。
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [50.0]
    key = lambda i: (values[i] if values[i] is not None else -1e18)
    idx = sorted(range(n), key=key, reverse=bool(reverse))
    out = [0.0] * n
    i = 0
    while i < n:
        j = i + 1
        ki = key(idx[i])
        while j < n and key(idx[j]) == ki:
            j += 1
        mid = (i + j - 1) / 2.0
        score = round(mid / (n - 1) * 100, 2)
        for pos in range(i, j):
            out[idx[pos]] = score
        i = j
    return out


def median(xs):
    s = sorted(v for v in xs if v is not None)
    if not s:
        return 0.0
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def mean(xs):
    xs = [v for v in xs if v is not None]
    return sum(xs) / len(xs) if xs else 0.0


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def period_return(klines, n):
    """n 日区间收益率(%)"""
    if len(klines) <= n:
        return None
    prev = klines[-1 - n]["close"]
    if not prev:
        return None
    return (klines[-1]["close"] / prev - 1) * 100


def moving_avg(klines, n, offset=0):
    """末日往前 offset 天的 N 日均线"""
    end = len(klines) - offset
    if end < n:
        return None
    seg = klines[end - n:end]
    return mean([k["close"] for k in seg])


def clampf(v, lo=0.0, hi=100.0):
    return clamp(v, lo, hi)


def num(v, default=0.0):
    """数值兜底：None / 非数 / 字符串都退化成 default。

    快照和缓存里充满 None（K线不足、字段缺失、停牌），
    直接参与算术会污染整条打分链，所以统一从这里过一道。
    """
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if x == x and x not in (float("inf"), float("-inf")) else default


def floor1(v):
    """向下截断到 1 位小数 —— **总分显示必须先过这一道**。

    为什么不能用 round：分档阈值是 80/70/60 这种整数边界，
    round(69.99, 1) = 70.0，界面就会出现「C 档 · 总分 70.0」这种自相矛盾的显示
    （按说明 70~80 才是 B 档）。截断永远不会把数值抬高，所以
    "显示为 80.0" 的票必然真的 ≥80，档位与数字天然一致。
    """
    try:
        return math.floor(float(v) * 10) / 10.0
    except (TypeError, ValueError):
        return 0.0


def _excess(ret, med):
    """个股收益相对全市场中位数的超额（百分点）。任一缺失就返回 None ——
    返回 0 会被误读成"与市场中位持平"，那是个假结论。"""
    if ret is None or med is None:
        return None
    return round(num(ret) - num(med), 2)


# ─────────────────────────────────────────────────────
# 板块层因子
# ─────────────────────────────────────────────────────
def board_raw_metrics(klines):
    """同花顺板块日线的原始指标"""
    if len(klines) < 25:
        return None
    c = klines[-1]["close"]
    m = {
        "ret1": period_return(klines, 1),
        "ret5": period_return(klines, 5),
        "ret20": period_return(klines, 20),
    }
    # 动能：近 5 日上涨天数
    up5 = sum(1 for i in range(-5, 0) if len(klines) > -i and klines[i]["close"] > klines[i - 1]["close"])
    m["up_days_5"] = up5
    # 位置：收盘在 60 日区间的位置
    seg = klines[-60:] if len(klines) >= 60 else klines
    hi = max(k["high"] for k in seg)
    lo = min(k["low"] for k in seg)
    m["position60"] = (c - lo) / (hi - lo) * 100 if hi > lo else 50.0
    # 量能抬升
    v_recent = mean([k["volume"] for k in klines[-5:]])
    v_base = mean([k["volume"] for k in klines[-25:-5]])
    m["vol_expand"] = v_recent / v_base if v_base else 1.0
    # 成交额动量 —— 东财资金流缺失时的替代指标：资金关注度是否在向该板块汇聚
    a_recent = mean([k.get("amount", 0) for k in klines[-5:]])
    a_base = mean([k.get("amount", 0) for k in klines[-25:-5]])
    m["amount_momentum"] = a_recent / a_base if a_base else 1.0
    return m


# ─────────────────────────────────────────────────────
# 个股层因子 —— 原始指标
# ─────────────────────────────────────────────────────
def intraday_frac(now=None):
    """当日已交易时长占全天(240分钟)的比例，0~1。

    仅用于标注当日K线是否尚未完成，以及记录经过的交易时长。
    不用于把当前累计成交量折算成全天量。
    """
    now = now or datetime.now()
    if now.weekday() >= 5:
        return 1.0
    t = now.hour * 60 + now.minute
    o1, c1, o2, c2 = 9 * 60 + 30, 11 * 60 + 30, 13 * 60, 15 * 60
    total = (c1 - o1) + (c2 - o2)          # 240
    if t <= o1:
        return 0.0
    if t <= c1:
        mins = t - o1
    elif t <= o2:
        mins = c1 - o1
    elif t <= c2:
        mins = (c1 - o1) + (t - o2)
    else:
        return 1.0
    return max(mins, 1) / total


def atr(klines, n=20):
    """ATR(n)：真实波幅均值。用于把"斜率""乖离"标准化成波动单位，

    高波动科技股与低波动蓝筹的价格位移才具备可比性。
    （直接比 MA20 斜率的百分比，会让高波动股天然显得"趋势更陡"）
    """
    if len(klines) < n + 1:
        return None
    trs = []
    for i in range(-n, 0):
        h = klines[i]["high"]
        l = klines[i]["low"]
        pc = klines[i - 1]["close"]
        if h is None or l is None or not pc:
            continue
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return None
    return mean(trs)


def clv(bar):
    """收盘位置 CLV = (收-低)/(高-低)。

    高振幅 + 高 CLV = 分歧后资金重新占优；
    高振幅 + 低 CLV = 冲高回落。振幅本身不能独立正向打分。
    """
    try:
        h, l, c = float(bar["high"]), float(bar["low"]), float(bar["close"])
    except (TypeError, ValueError, KeyError):
        return 0.5
    return (c - l) / (h - l) if h > l else 0.5


def upper_shadow_ratio(bar):
    """上影线占当日振幅的比例（0~1）。长上影 = 盘中冲高被压回。"""
    try:
        h, l = float(bar["high"]), float(bar["low"])
        o, c = float(bar.get("open") or 0), float(bar["close"])
    except (TypeError, ValueError, KeyError):
        return 0.0
    rng = h - l
    if rng <= 0:
        return 0.0
    return max(0.0, (h - max(o, c)) / rng)


def median_window(vals, n, offset=0):
    """末日前 offset 根起、往前 n 个值的中位数（跳过 None）"""
    end = len(vals) - offset
    if end <= 0:
        return None
    seg = [v for v in vals[max(0, end - n):end] if v is not None]
    return median(seg) if seg else None


def hist_percentile(vals, x):
    """x 在 vals（历史序列）中的百分位（0~100）"""
    s = [v for v in (vals or []) if v is not None and v > 0]
    if not s or x is None:
        return None
    below = sum(1 for v in s if v < x)
    return below / len(s) * 100


def stock_raw_metrics(code, klines, quote):
    """个股原始指标（波段 V3 + 短线启动 V2）。klines 为升序日K（成交量已归一化为「股」），quote 为腾讯快照。

    这里只算**原始量**，不做任何 0~100 分位映射 —— 分位必须在全体股票上
    统一做（见 build_stock_scores），否则"今天 20 日涨 15% 算不算强"
    就变成了人为规定的固定标准，而不是由当日市场环境决定。
    """
    min_bars = config.RISK_GATE.get("min_trading_days", 120)
    if len(klines) < min_bars:
        return None
    close = klines[-1]["close"]
    m = {"code": code}

    # ── RS 相对强度 ──
    for tag, n in (("ret3", 3), ("ret5", 5), ("ret20", 20), ("ret60", 60)):
        m[tag] = period_return(klines, n)
    # 近 5 日上涨天数（绝对上涨，不再是"跑赢中位数"——相对超额已由 RS 子项承担）
    up5 = 0
    for i in range(-5, 0):
        if len(klines) > -i and klines[i - 1]["close"]:
            if klines[i]["close"] > klines[i - 1]["close"]:
                up5 += 1
    m["up_days_5"] = up5
    # 近 3 日上涨天数（板块宽度持续性要用）
    up3 = 0
    for i in range(-3, 0):
        if len(klines) > -i and klines[i - 1]["close"]:
            if klines[i]["close"] > klines[i - 1]["close"]:
                up3 += 1
    m["up_days_3"] = up3

    # ── 量价 ──
    # 未完成日K只使用已发生的累计成交量；不按时间或日内分布预测全天。
    today = datetime.now().strftime("%Y-%m-%d")
    elapsed = intraday_frac()
    is_partial = (klines[-1]["date"] == today) and 0.0 < elapsed < 1.0
    m["vol_partial"] = 1 if is_partial else 0
    m["elapsed_frac"] = round(elapsed, 4)

    v_today = klines[-1]["volume"]
    vols_hist = [k["volume"] for k in klines[:-1]]            # 不含今日
    v_med20 = median_window(vols_hist, 20)                     # 20 日中位数（V2.2 口径）
    v_ma5 = mean(vols_hist[-5:]) if len(vols_hist) >= 5 else None
    v_ma20 = mean(vols_hist[-20:]) if len(vols_hist) >= 20 else None
    # VR：今日量 ÷ 近20日**中位数**。V2.2 明确不用均值 ——
    # 均值会被单日爆量拉高，把"今天其实放量了"判成正常。
    m["vr"] = (v_today / v_med20) if v_med20 else 1.0
    # 保留旧字段名给未迁移的展示/自检用（对 5 日均量）
    m["vol_ratio5"] = (v_today / v_ma5) if v_ma5 else 1.0
    # 量能趋势只比较已经完成的历史窗口；今日量能由 VR 单独确认。
    # 旧公式把今日量与 MA5 再平均后除以 MA20，混合了两个问题。
    m["vol_trend"] = (v_ma5 / v_ma20) if (v_ma5 and v_ma20) else 1.0
    m["vol_ratio_rt"] = quote.get("vol_ratio", 0) or 0
    # 换手/量能的历史分位（120 交易日）。
    # 换手率 = 成交量 ÷ 流通股本，同一窗口内流通股本视为不变，
    # 所以**成交量的历史分位与换手率的历史分位同值**。我们拿不到历史换手率，
    # 用成交量分位替代；界面上标注为「量能分位」以免被误读成精确换手分位。
    m["vol_pct_120"] = hist_percentile(vols_hist[-config.TURN_PCT_WINDOW:], v_today)

    # 成交额估算（腾讯历史K线不返回成交额，用 量×收盘价 估算，实测偏差 <3%）
    amt_hist = [config.bar_amount_wan(k) for k in klines[:-1]]
    m["amt_today_wan"] = config.bar_amount_wan(klines[-1])
    m["amt_med20_wan"] = median_window(amt_hist, 20) or 0.0
    m["amt_ma5_wan"] = mean(amt_hist[-5:]) if len(amt_hist) >= 5 else 0.0
    m["amt_ma20_wan"] = mean(amt_hist[-20:]) if len(amt_hist) >= 20 else 0.0

    seg = klines[-60:] if len(klines) >= 60 else klines
    # 位置类指标（60日位置/乖离/ATR距离/是否站上均线）优先用**实时价**：
    # 盘中最后一根K线的 close 是当时的成交价，会随行情跳动；直接用实时价
    # 才不会出现"价格已经跌破 MA20 但乖离还显示正数"这种滞后。
    px = num(quote.get("price")) or close
    hi = max(k["high"] for k in seg)
    lo = min(k["low"] for k in seg)
    m["position60"] = (px - lo) / (hi - lo) * 100 if hi > lo else 50.0
    # 是否创 20 日新高（板块新高宽度用）
    # “收盘创此前 20 日新高”必须排除今天这根 bar；否则当天冲高回落时，
    # 今天自己的最高价会把新高条件抬高，板块扩散被系统性低估。
    _prior20 = klines[-21:-1] if len(klines) >= 21 else klines[:-1]
    m["is_high20"] = 1 if (_prior20 and px >= max(k["high"] for k in _prior20) - 1e-9) else 0
    m["px"] = px
    m["turnover"] = quote.get("turnover_pct", 0) or 0
    m["amount_wan"] = quote.get("amount_wan", 0) or 0
    m["traded"] = 1 if (quote.get("amount_wan", 0) or 0) > 0 else 0
    # 形态：放量上涨 / 缩量回调（保留给旧展示口径）
    chg = quote.get("change_pct", 0) or 0
    m["shape_bonus"] = 0.0
    # ── 量价结构（缩量回踩 / 放量杀跌）──
    # 原始值域：正=健康结构，负=恶化结构。分位化在 build_stock_scores 里做。
    # 「是否仍在 MA20 上方」要用独立算的 MA20 判断，不能引用后面才赋值的字段。
    pv = config.PV
    _ma20_now = moving_avg(klines, 20)
    _px_now = num(quote.get("price")) or close
    _above20_now = bool(_ma20_now and _px_now > _ma20_now)
    struct = 0.0
    if chg < 0 and m["vr"] >= pv["vr_down_bad"]:
        # 下跌还放量 = 放量杀跌，扣得最重
        struct = -1.0
    elif chg < 0 and _above20_now and m["vr"] < pv["shrink_max"]:
        # 仍在 MA20 上方、缩量回调 = 趋势没破但抛压下降，健康
        struct = 1.0
    elif chg > 0 and pv["vr_healthy_lo"] <= m["vr"] <= pv["vr_healthy_hi"]:
        # 温和放量上涨 = 量能确认
        struct = 0.6
    m["pv_struct"] = struct

    # ── 情绪强度 ──
    # 涨停阈值必须按板别取：主板 10%、创业板/科创板 20%。用统一 9.8% 判全市场，
    # 创业板涨 10% 会被错记成"涨停"，连板高度/情绪分/涨停家数/领涨题材词频全失真。
    # 新股无涨跌幅限制期间（主板首日、创业/科创前 5 日）返回 999 → 永不判涨停。
    lim = quote.get("limit_pct")
    if lim is None:
        lim = config.board_of(code)[2]
    bkey = quote.get("board_type") or config.board_of(code)[0]
    ldays = quote.get("list_days")
    free_days = config.POOL.get("new_limit_free_days", {}).get(bkey, 1)
    if ldays is not None and ldays <= free_days:
        lim_eff = 999.0
    else:
        lim_eff = float(lim) * (1.0 - config.BOARD_LIMIT_TOLERANCE)
    m["limit_pct"] = lim_eff
    limit_today = 1 if chg >= lim_eff else 0
    m["limit_today"] = limit_today
    n_limit5 = 0
    for i in range(-5, 0):
        if len(klines) > -i and klines[i - 1]["close"]:
            if (klines[i]["close"] / klines[i - 1]["close"] - 1) * 100 >= lim_eff:
                n_limit5 += 1
    m["limit_5d"] = n_limit5
    m["amplitude"] = quote.get("amplitude_pct", 0) or 0
    # 连板高度
    streak = 0
    for i in range(-1, -8, -1):
        if len(klines) > -i and klines[i - 1]["close"]:
            if (klines[i]["close"] / klines[i - 1]["close"] - 1) * 100 >= lim_eff:
                streak += 1
            else:
                break
    m["limit_streak"] = streak
    # 是否盘中触及过涨停（炸板判定用）：最高价够到停板价但收盘没封住 = 炸板
    prev_close = klines[-2]["close"] if len(klines) >= 2 else 0
    _high = quote.get("high") or klines[-1]["high"]
    if prev_close and lim_eff < 900:
        limit_price = prev_close * (1 + lim_eff / 100.0)
        m["touched_limit"] = 1 if _high >= limit_price * 0.998 else 0
    else:
        m["touched_limit"] = 0
    m["blasted"] = 1 if (m["touched_limit"] and not limit_today) else 0
    # CLV 与上影线：用实时行情的高/低/现价（盘中比最后一根K线的新）
    qbar = {"high": quote.get("high") or klines[-1]["high"],
            "low": quote.get("low") or klines[-1]["low"],
            "open": klines[-1].get("open") or 0,
            "close": quote.get("price") or close}
    m["clv"] = clv(qbar)
    m["upper_shadow"] = upper_shadow_ratio(qbar)

    # ── 均线结构 / 趋势质量 ──
    ma = {n: moving_avg(klines, n) for n in (5, 10, 20, 60)}
    m["ma"] = ma
    bull = 0
    if ma[5] and ma[10] and ma[5] > ma[10]:
        bull += 1
    if ma[10] and ma[20] and ma[10] > ma[20]:
        bull += 1
    if ma[20] and ma[60] and ma[20] > ma[60]:
        bull += 1
    m["bull_count"] = bull
    # 五日线多头（MA5 > MA10 > MA20）—— 用户最常挂在嘴边的形态，
    # 单独给一个布尔量，比让人去猜 bull_count==3 的含义直观
    m["ma5_bull"] = 1 if (ma[5] and ma[10] and ma[20]
                          and ma[5] > ma[10] > ma[20]) else 0
    m["above20"] = 1 if (ma[20] and px > ma[20]) else 0
    m["above60"] = 1 if (ma[60] and px > ma[60]) else 0
    ma20_prev = moving_avg(klines, 20, offset=config.ATR_SLOPE_LOOKBACK)
    m["ma20_prev"] = ma20_prev
    m["ma20_slope"] = ((ma[20] / ma20_prev - 1) * 100) if (ma[20] and ma20_prev) else 0.0
    m["bias20"] = ((px / ma[20] - 1) * 100) if ma[20] else 0.0

    # ── ATR 标准化（趋势斜率与拥挤度的共同分母）──
    a = atr(klines, config.ATR_WINDOW)
    m["atr20"] = a
    if a and ma[20] and ma20_prev:
        # 用 ATR 除，而不是百分比：否则高波动股天然显得"趋势更陡"
        m["slope_atr"] = (ma[20] - ma20_prev) / a
    else:
        m["slope_atr"] = 0.0
    # 拥挤度核心：股价离 MA20 有多少个 ATR
    m["dist_atr"] = ((px - ma[20]) / a) if (a and ma[20]) else 0.0

    # ── 波段路径与回调原料 ──
    # ER20：净位移 / 路径绝对波动，越接近 1 说明上涨更有序。
    _cl20 = [float(k["close"]) for k in klines[-21:]]
    if len(_cl20) >= 2:
        _path = sum(abs(_cl20[i] - _cl20[i - 1]) for i in range(1, len(_cl20)))
        m["er20"] = max(0.0, (_cl20[-1] - _cl20[0]) / _path) if _path else 0.0
        _peak = _cl20[0]
        _max_dd = 0.0
        for _v in _cl20:
            _peak = max(_peak, _v)
            if _peak:
                _max_dd = min(_max_dd, _v / _peak - 1.0)
        m["max_dd20_pct"] = _max_dd * 100.0
    else:
        m["er20"], m["max_dd20_pct"] = None, None

    # 最近 3~8 日回调：固定窗口规则，避免人工挑形态。
    # 以完成的前一日为止识别峰值，当前价只用于判断是否重新站回 MA10。
    _end = len(klines) - 1
    _peak_candidates = list(range(max(0, _end - 8), max(0, _end - 2)))
    _peak_i = max(_peak_candidates, key=lambda i: klines[i]["close"]) if _peak_candidates else None
    _ma10_now = moving_avg(klines, 10)
    m["pullback_valid"] = 0
    m["pullback_volume_ratio"] = None
    m["pullback_depth_atr"] = None
    m["reclaim_ma10"] = 0
    m["rebreak3"] = 0
    if _peak_i is not None and _peak_i < _end - 1:
        _before = [k.get("volume") for k in klines[max(0, _peak_i - 10):_peak_i]
                   if k.get("volume") is not None]
        _after = [k.get("volume") for k in klines[_peak_i + 1:_end]
                  if k.get("volume") is not None]
        _peak_close = float(klines[_peak_i]["close"])
        _trough = min(float(k["low"]) for k in klines[_peak_i + 1:_end])
        _atr_ref = a or 0.0
        m["pullback_valid"] = 1 if (_peak_close > float(klines[_peak_i - 1]["close"])
                                     if _peak_i > 0 else False) else 0
        if _before and _after:
            m["pullback_volume_ratio"] = median(_after) / median(_before) if median(_before) else None
        if _atr_ref:
            m["pullback_depth_atr"] = (_peak_close - _trough) / _atr_ref
        m["reclaim_ma10"] = 1 if (_ma10_now and px >= _ma10_now) else 0
    if len(klines) >= 4:
        _prior3 = max(float(k["close"]) for k in klines[-4:-1])
        m["rebreak3"] = 1 if px > _prior3 else 0

    # ── 资金意图代理（仅展示，不进总分）──
    # 东财资金流缺失时的替代口径：量能变化幅度 × 价格方向。
    #   放量上涨 = 资金流入（正）；放量下跌 = 资金流出（负）
    # 关键：用「量能变化的幅度」乘「价格方向」，而不是 (ratio-1) 直接带符号，
    # 否则缩量下跌（ratio<1 且 chg<0）会算出正值，方向完全反掉。
    d1 = 1.0 if chg > 0 else (-1.0 if chg < 0 else 0.0)
    _r5 = m["ret5"] or 0.0
    d5 = 1.0 if _r5 > 0 else (-1.0 if _r5 < 0 else 0.0)
    m["fund_proxy"] = abs(m["vr"] - 1.0) * d1 * 100 + (m["vol_trend"] - 1.0) * d5 * 40

    # ── 市值 / 价格 ──
    m["float_mcap"] = quote.get("float_mcap_yi", 0) or 0
    m["price"] = quote.get("price", close)
    m["change_pct"] = chg
    m["name"] = quote.get("name", "")
    # ── 板别（从股票池带上来，随行情一起传到快照）──
    # 板别是"必须在每个视图都标出来"的字段：同一张强弱榜里混着
    # 10% 板和 20% 板，不标注的话用户会把 20% 板的一根中阳当成主板涨停看。
    bkey, bname, blim = config.board_of(code)
    m["board_type"] = quote.get("board_type") or bkey
    m["board_name"] = quote.get("board_name") or bname
    m["board_limit"] = blim
    m["list_days"] = quote.get("list_days")
    m["is_new"] = int(quote.get("is_new") or 0)
    m["bars"] = len(klines)

    # ── 短线启动（Ignition-1）原始指标 ──
    # 关键区别：这里所有"平台/收缩/前置"指标都只看**突破前**的窗口，
    # 把今天这根 bar 排除在外 —— 否则"今天这根大阳线"会污染平台宽度、量能收缩，
    # 让"已经突破了"的股票显得"正在压缩"，方向完全反掉。
    try:
        tol = config.IGNITION["plat"]["tol"]
        nshort = config.IGNITION["plat"]["short"]    # 20
        nlong = config.IGNITION["plat"]["long"]      # 60
        if len(klines) >= nlong + 2:
            # 平台高点（突破前窗口：不含今天）
            pre20 = klines[-nshort - 1:-1]
            pre60 = klines[-nlong - 1:-1]
            m["ph20"] = max(float(k["high"]) for k in pre20)
            m["ph60"] = max(float(k["high"]) for k in pre60)
            # 昨天收盘时，昨天往前 20 日的平台高点（判断"昨天是否还没站上"）
            pre20_yest = klines[-nshort - 2:-2]
            m["ph20_yest"] = max(float(k["high"]) for k in pre20_yest) if pre20_yest else None
            # 今天与昨天必须使用同一种平台口径。此前昨天使用收盘价上沿、
            # 今天使用最高价上沿，会把首日判定做成前后不一致。
            m["mc20_yest"] = max(float(k["close"]) for k in pre20_yest) if pre20_yest else None
            pc = float(klines[-2]["close"]) if len(klines) >= 2 else 0.0

            # Base→Breakout 最近发生日。首次突破的原平台、ATR 与前置窗口
            # 一旦识别便冻结，确认期不再用当天滚动窗口重算，避免第 2/3 日
            # 把突破日重新解释成“正在蓄势”。
            _buffer = float(config.IGNITION["plat"].get("breakout_buffer_atr", 0.0))
            m["breakout_age"] = None
            _event = None
            for age in range(0, 4):
                ii = len(klines) - 1 - age
                if ii < nlong + 1:
                    continue
                _pre20 = klines[ii - nshort:ii]
                _pre60 = klines[ii - nlong:ii]
                _prev20 = klines[ii - nshort - 1:ii - 1]
                if len(_pre20) < nshort or len(_prev20) < nshort:
                    continue
                _ph20 = max(float(k["high"]) for k in _pre20)
                _ph60 = max(float(k["high"]) for k in _pre60)
                _prev_close = float(klines[ii - 1]["close"])
                _prev_ph = max(float(k["high"]) for k in _prev20)
                _atr_pre = atr(klines[:ii], config.ATR_WINDOW) or 0.0
                _close_i = float(klines[ii]["close"])
                _effective = _close_i > (_ph20 + _buffer * _atr_pre) if _atr_pre else _close_i > _ph20 * (1 - tol)
                _previous_effective = (_prev_close > (_prev_ph + _buffer * _atr_pre)
                                       if _atr_pre else _prev_close > _prev_ph * (1 - tol))
                if _effective and not _previous_effective:
                    _event = {"age": age, "ii": ii, "ph20": _ph20, "ph60": _ph60,
                              "atr": _atr_pre, "bar": klines[ii], "pre20": _pre20,
                              "pre60": _pre60, "prev_close": _prev_close}
                    break
            if _event:
                m["breakout_age"] = _event["age"]
                m["ph20"] = _event["ph20"]
                m["ph60"] = _event["ph60"]
                m["breakout_date"] = _event["bar"].get("date")
                m["breakout_atr20"] = _event["atr"]
                m["breakout_clv"] = clv(_event["bar"])
                m["breakout_upper_shadow"] = upper_shadow_ratio(_event["bar"])
                _ev_close = float(_event["bar"]["close"])
                m["brk_pct"] = ((_ev_close / _event["ph20"] - 1) * 100
                                 if _event["ph20"] else 0.0)
                m["broke20"] = 1 if close > _event["ph20"] * (1 - tol) else 0
                m["broke60"] = 1 if _ev_close > _event["ph60"] else 0
                _pre = _event["pre20"]
                _cl = [float(k["close"]) for k in _pre]
                m["range20"] = ((max(float(k["high"]) for k in _pre)
                                 - min(float(k["low"]) for k in _pre))
                                / median(_cl) * 100) if _cl else None
                _atr_far = atr(klines[max(0, _event["ii"] - 2 * nshort - 2):
                                     max(0, _event["ii"] - nshort - 1)], config.ATR_WINDOW)
                _atr_near = atr(klines[max(0, _event["ii"] - nshort - 2):_event["ii"]], config.ATR_WINDOW)
                m["atr_contract"] = (_atr_near / _atr_far) if (_atr_near and _atr_far) else None
                _v_near = median([k.get("volume") for k in _pre if k.get("volume") is not None])
                _v_far = median([k.get("volume") for k in _event["pre60"] if k.get("volume") is not None])
                m["vol_contract"] = (_v_near / _v_far) if (_v_near and _v_far) else None
                _ma20_p = moving_avg(klines, 20, offset=len(klines) - _event["ii"])
                _ma60_p = moving_avg(klines, 60, offset=len(klines) - _event["ii"])
                m["ma_converge"] = (abs(_ma20_p - _ma60_p) / _ma60_p * 100
                                     if (_ma20_p and _ma60_p) else None)
                _pc = float(klines[_event["ii"] - 1]["close"])
                _ref5 = float(klines[_event["ii"] - 6]["close"]) if _event["ii"] >= 6 else 0.0
                _ref20 = float(klines[_event["ii"] - 21]["close"]) if _event["ii"] >= 21 else 0.0
                m["r5_pre"] = ((_pc / _ref5 - 1) * 100) if _ref5 else None
                m["r20_pre"] = ((_pc / _ref20 - 1) * 100) if _ref20 else None
                m["dist_pre_atr"] = ((_pc - (_ma20_p or _pc)) / (_atr_near or 1.0))
                _ev_open = float(_event["bar"].get("open") or _ev_close)
                m["gap_pct"] = ((_ev_open / _pc - 1) * 100) if (_ev_open and _pc) else None
                _ev_high = float(_event["bar"].get("high") or _ev_close)
                m["fall_from_high"] = ((_ev_close / _ev_high - 1) * 100) if _ev_high else None
            else:
                # 当前站上平台但没有“从未站上→站上”的事件，仍可展示强度，
                # 但不能被短线启动模型当作新买点。
                m["broke20"] = 1 if close > m["ph20"] + _buffer * (atr(klines[:-1], 20) or 0.0) else 0
                m["broke60"] = 1 if close > m["ph60"] else 0
                m["brk_pct"] = (close / m["ph20"] - 1) * 100 if m["ph20"] else 0.0
                m["breakout_clv"] = None
                m["breakout_upper_shadow"] = None
                m["range20"] = m["atr_contract"] = m["vol_contract"] = None
                m["ma_converge"] = None
                m["r5_pre"] = m["r20_pre"] = m["dist_pre_atr"] = None
                m["gap_pct"] = m["fall_from_high"] = None
            # 兼容旧字段：first_breakout 仍严格表示“今天首日”。
            m["first_breakout"] = 1 if m.get("breakout_age") == 0 else 0
            m["above_yest"] = 0 if not _event else int(_event["prev_close"] <= _event["ph20"] * (1 - tol))
            _th = float(quote.get("high") or klines[-1]["high"])
            m["intraday_fail"] = 1 if (_event and _th > _event["ph20"] * (1 - tol)
                                       and close <= _event["ph20"] * (1 - tol)) else 0
    except Exception:
        # 平台窗口不足或字段缺失时，Ignition 原始指标整体缺省 ——
        # 打分端会据此不给分，而不是用半个值凑数
        pass
    return m


def _sector_members(raw_list, code_boards):
    """题材成员分组，供短线/波段子模型复用。"""
    buckets = {}
    for r in raw_list:
        for t in code_boards.get(r["code"], []):
            buckets.setdefault(t, []).append(r)
    return {
        t: ms for t, ms in buckets.items()
        if config.SECTOR_MEMBER_MIN <= len(ms) <= config.SECTOR_MEMBER_MAX
    }


def _sector_metrics(raw_list, code_boards, med20):
    """按题材聚合板块级指标 —— 波段 V3 的 Sector 因子原料。

    成员口径：**通过 Risk Gate 的股票池成员**，不是概念全量成员。
    这样"板块宽度"描述的是"我实际能买的这批票里有多少在涨"，
    比把一堆停牌/退市/微型股算进分母更贴近可执行性。

    成员 < SECTOR_MEMBER_MIN 的题材样本太小（可能只有自己），
    成员 > SECTOR_MEMBER_MAX 的题材（如"国企改革"）上涨占比恒等于大盘，都没有区分度。
    """
    buckets = _sector_members(raw_list, code_boards)

    out = {}
    for t, ms in buckets.items():
        k = len(ms)
        if k < config.SECTOR_MEMBER_MIN or k > config.SECTOR_MEMBER_MAX:
            continue
        r20 = [x["ret20"] for x in ms if x.get("ret20") is not None]
        if not r20:
            continue
        med_r20 = median(r20)
        # 上涨宽度：当日 + 近3日持续性。只看当日会被"一天集体高开"骗到。
        b1 = sum(1 for x in ms if num(x.get("change_pct")) > 0) / k * 100
        b3 = mean([min(3, num(x.get("up_days_3"))) / 3.0 for x in ms]) * 100
        # 20日新高宽度：比"25只都涨0.5%"更能代表真实扩散
        nh = sum(1 for x in ms if num(x.get("is_high20"))) / k * 100
        # 成交额扩张：板块总成交额 MA5 / MA20（按合计额计算）
        a5 = sum(num(x.get("amt_ma5_wan")) for x in ms)
        a20 = sum(num(x.get("amt_ma20_wan")) for x in ms)
        out[t] = {
            "n": k,
            "med_ret20": med_r20,
            "excess": med_r20 - med20,
            "breadth": 0.5 * b1 + 0.5 * b3,
            "new_high": nh,
            "amt_expand": (a5 / a20) if a20 > 0 else 1.0,
        }
    return out


def _turn_quality(pct):
    """换手/量能历史分位的"健康曲线"。

    V2.2 明确：健康区间大致 60~90 分位；90~95 仍可接受但开始观察拥挤；
    >95 不再奖励；>97~98 若伴随巨大涨幅、爆量、上影线就该扣分。
    所以这里是一条**单峰**曲线而不是单调递增 —— 换手不是越大越好。
    """
    if pct is None:
        return 50.0
    if pct < 40:
        return 25.0 + pct / 40.0 * 25.0
    if pct < 60:
        return 50.0 + (pct - 40) / 20.0 * 25.0
    if pct <= 90:
        return 75.0 + (pct - 60) / 30.0 * 25.0
    if pct <= 95:
        return 100.0 - (pct - 90) * 4.0
    if pct <= 98:
        return 80.0 - (pct - 95) * 10.0
    return max(15.0, 50.0 - (pct - 98) * 8.0)


def _vr_quality(r):
    """方向化量能：VR = 今日量 / 近20日量中位数。

    上涨时 1.2~2.0 倍是健康确认；极端爆量（≥3~4 倍）**不继续线性加分**
    （加速的奖励交给拥挤度去扣）；下跌时放量是杀跌，必须扣分。
    """
    pv = config.PV
    chg = num(r.get("change_pct"))
    vr = num(r.get("vr"), 1.0)
    if chg > 0:
        if vr < pv["vr_healthy_lo"]:
            return clampf(vr / pv["vr_healthy_lo"] * 70.0)
        if vr <= pv["vr_healthy_hi"]:
            return clampf(70.0 + (vr - pv["vr_healthy_lo"])
                          / (pv["vr_healthy_hi"] - pv["vr_healthy_lo"]) * 30.0)
        if vr < pv["vr_extreme"]:
            return clampf(100.0 - (vr - pv["vr_healthy_hi"])
                          / max(1e-6, pv["vr_extreme"] - pv["vr_healthy_hi"]) * 25.0)
        # 极端爆量：不再加分，且明显低于健康区间
        return clampf(max(45.0, 75.0 - (vr - pv["vr_extreme"]) * 8.0))
    if chg < 0:
        if vr >= pv["vr_down_bad"]:
            return clampf(max(0.0, 42.0 - (vr - pv["vr_down_bad"]) * 22.0))
        return 48.0
    return 42.0


def _limit_quality(r):
    """涨停的**边际递减**奖励。

    直接按连板高度线性加分是错的：4 连板股票会因为
    「RS高 + 涨停高 + 情绪高 + 成交高」被同一件事奖励四次。
    这里用逐板递减的边际价值做累积，再归一化：
      每多一板的边际价值 [1.00, 0.55, 0.30, 0.15, 0.06]
      累计 → 首板 48 分、二板 75、三板 90、四板 97、五板及以上 100
    即"首板明显加分、二次继续确认、之后迅速钝化"，与 V2.2 的描述一致。
    """
    steps = list(config.SENT.get("limit_step") or [1.00, 0.55, 0.30, 0.15, 0.06])
    total = sum(steps) or 1.0
    streak = int(num(r.get("limit_streak")))
    if streak >= 1:
        acc = sum(steps[:min(streak, len(steps))])
        if streak > len(steps):
            acc = total          # 超过表长不再加分
        return clampf(acc / total * 100.0)
    l5 = int(num(r.get("limit_5d")))
    if l5 > 0:
        return clampf(min(60.0, 40.0 + 12.0 * l5))
    return 25.0


def _crowd_dist_quality(r, ret5_pct):
    """派发结构：爆量 + 长上影 + 低 CLV + 涨幅已到极值。

    V2.2 举的例子正是"5日涨幅全市场前5% + 换手120日97分位以上 +
    成交量20日中位数2.5倍以上 + 上影明显 + CLV<0.35"。
    命中项越多扣得越狠 —— 这种票即使 RS 很高也会被拥挤度扣分，
    但同时保留 score_strength 供区分强度与追涨风险。
    """
    c = config.CROWD_DIST
    hits = 0
    if ret5_pct is not None and ret5_pct >= c["ret5_pct_top"]:
        hits += 1
    if num(r.get("vol_pct_120")) >= c["turn_pct_top"]:
        hits += 1
    if num(r.get("vr")) >= c["vol_mult"]:
        hits += 1
    if num(r.get("clv"), 0.5) < c["clv_low"]:
        hits += 1
    if num(r.get("upper_shadow")) >= 0.30:
        hits += 1
    table = {0: 100.0, 1: 74.0, 2: 42.0, 3: 16.0, 4: 4.0, 5: 0.0}
    return table.get(hits, 0.0)


def _dist_atr_quality(dist):
    """(Close-MA20)/ATR20 的健康档位。

    注意档位表**不是"超过5ATR必跌"**，而是"再追进去承担的风险明显提高"，
    所以给低分而不是负分 —— 趋势可以继续，只是赔率变差。
    """
    for hi, sc in config.CROWD_ATR_BANDS:
        if dist <= hi:
            return sc
    return 10.0


def _compression_quality(value, ideal_hi=0.85, bad_hi=1.25):
    """把收缩比映射为“越紧越健康”的 0~100 分。"""
    if value is None:
        return 50.0
    value = float(value)
    if value <= ideal_hi:
        return 100.0
    if value >= bad_hi:
        return 20.0
    return 100.0 - 80.0 * (value - ideal_hi) / (bad_hi - ideal_hi)


def _break_quality(r):
    """短线首次突破的结构质量；未发生突破只给观察分，不制造买点。"""
    if not r.get("broke20") or r.get("breakout_age") is None:
        return 35.0
    if r.get("intraday_fail"):
        return 10.0
    brk = num(r.get("brk_pct"), 0.0)
    if brk < 0.10:
        q_brk = 30.0
    elif brk <= 4.5:
        q_brk = 100.0
    elif brk <= 8.0:
        q_brk = 100.0 - 70.0 * (brk - 4.5) / 3.5
    else:
        q_brk = 20.0
    clv = num(r.get("breakout_clv"), num(r.get("clv"), 0.5))
    q_clv = clampf((clv - 0.40) / 0.35 * 100.0)
    q_hold = 100.0 if num(r.get("above20")) else 35.0
    return clampf(0.50 * q_brk + 0.35 * q_clv + 0.15 * q_hold)


def _path_quality(er20, dd20, slope_pct):
    """波段路径质量：上涨效率、回撤控制和均线方向的组合。"""
    er = clampf(num(er20) * 100.0)
    dd = clampf(100.0 + num(dd20), 0.0, 100.0)  # dd20 为负的最大回撤百分比
    slope = clampf(50.0 + num(slope_pct) * 12.0)
    return clampf(0.45 * er + 0.35 * dd + 0.20 * slope)


def _pullback_quality(r, p_vol=None, p_depth=None):
    """波段回调供给质量；没有可识别回调时保持中性，不虚构买点。"""
    if not r.get("pullback_valid"):
        return 50.0
    vol = p_vol if p_vol is not None else 50.0
    depth = p_depth if p_depth is not None else 50.0
    reclaim = 100.0 if r.get("reclaim_ma10") else 25.0
    return clampf(0.50 * vol + 0.25 * depth + 0.25 * reclaim)


def build_stock_scores(raw_list, weights, fund_map, board_ctx, outer):
    """构建短线启动与波段趋势分数。

    波段权重：中期 RS 30% + 回调供给 15% + 路径质量 25% + 板块持续 20% + 再启动 10%；
    拥挤健康度独立用于风险调整，不直接进核心强度分。

    设计要点：
      · 除少数**明确给了区间/档位**的指标（VR、ATR 距离、换手健康曲线、
        CLV、涨停边际递减）外，连续量一律先转成**当日池内 0~100 横截面分位**，
        避免不同量纲直接相加，也避免"20日涨15%永久等于80分"这种硬规定。
      · 主力资金与外围契合**不参与总分**，只作为展示与告警（见 config 注释）。
    """
    if not raw_list:
        return []
    codes = [r["code"] for r in raw_list]
    code_boards = board_ctx.get("code_boards", {})
    industries = board_ctx.get("industries", {})
    theme_groups = board_ctx.get("theme_groups", {})

    def rank(key, reverse=False):
        vals = [num(r.get(key)) for r in raw_list]
        return dict(zip(codes, pct_rank(vals, reverse=reverse)))

    def rank_keep_none(vals_by_code, reverse=False):
        """分位排名，但**保留 None**。

        pct_rank 会把 None 当成最小的 -1e18，于是"没有题材归属"的个股
        会被排到行业相对强度的倒数第一 —— 那不是它的真实强度，
        而是"这条数据我们没有"。直接参与加权等于给缺失数据扣分，
        与"因子缺失时按可用因子重新归一化"的原则相矛盾。
        """
        have = [c for c in codes if vals_by_code.get(c) is not None]
        rk = dict(zip(have, pct_rank([vals_by_code[c] for c in have], reverse=reverse)))
        return {c: rk.get(c) for c in codes}

    # ── 市场基准（全池中位数）──
    med5 = median([r["ret5"] for r in raw_list if r.get("ret5") is not None])
    med20 = median([r["ret20"] for r in raw_list if r.get("ret20") is not None])
    med60 = median([r["ret60"] for r in raw_list if r.get("ret60") is not None])

    # ── 板块级指标 ──
    sec = _sector_metrics(raw_list, code_boards, med20)
    if sec:
        sec_ex = dict(zip(sec.keys(), pct_rank([sec[t]["excess"] for t in sec])))
        sec_bd = dict(zip(sec.keys(), pct_rank([sec[t]["breadth"] for t in sec])))
        sec_nh = dict(zip(sec.keys(), pct_rank([sec[t]["new_high"] for t in sec])))
        sec_ae = dict(zip(sec.keys(), pct_rank([sec[t]["amt_expand"] for t in sec])))
        sw = config.SECTOR_WEIGHTS
        sec_score = {t: clampf(sw["excess"] * sec_ex[t] + sw["breadth"] * sec_bd[t]
                               + sw["new_high"] * sec_nh[t] + sw["amt_expand"] * sec_ae[t])
                     for t in sec}
    else:
        sec_score = {}

    # ── 逐股分位原料 ──
    p_ret3 = rank("ret3")
    p_ret5 = rank("ret5")
    p_ret20 = rank("ret20")
    p_ret60 = rank("ret60")
    p_up5 = rank("up_days_5")
    p_voltrend = rank("vol_trend")
    p_slope = rank("slope_atr")
    p_clv = rank("clv")
    p_er20 = rank_keep_none({r["code"]: r.get("er20") for r in raw_list})
    p_dd20 = rank_keep_none({r["code"]: r.get("max_dd20_pct") for r in raw_list})
    p_pull_vol = rank_keep_none(
        {r["code"]: r.get("pullback_volume_ratio") for r in raw_list}, reverse=True)
    p_pull_depth = rank_keep_none(
        {r["code"]: r.get("pullback_depth_atr") for r in raw_list}, reverse=True)

    # 短线领先性使用 3 日相对强度与所属题材 3 日超额，避免把 20/60 日
    # 趋势分换个权重就叫“短线”。题材中位数按成员池计算，且单独保留缺失。
    med3 = median([r.get("ret3") for r in raw_list if r.get("ret3") is not None])
    sec_ret3 = {}
    for t, ms in _sector_members(raw_list, code_boards).items():
        vals = [x.get("ret3") for x in ms if x.get("ret3") is not None]
        if vals:
            sec_ret3[t] = median(vals)
    short_sector_raw = {}
    for r in raw_list:
        names = [t for t in code_boards.get(r["code"], []) if t in sec_ret3]
        if not names or r.get("ret3") is None:
            short_sector_raw[r["code"]] = None
            continue
        names.sort(key=lambda t: -sec_score.get(t, 0.0))
        vals = [num(r.get("ret3")) - sec_ret3[t] for t in names[:3]]
        short_sector_raw[r["code"]] = sum(vals) / len(vals)
    p_short_sector = rank_keep_none(short_sector_raw)

    # 行业/题材相对强度（20日）：计算个股相对所属题材中位数的超额。
    # 题材相对市场的超额已经由独立 Sector 因子负责，不能在 RS 中重复奖励。
    rs_sector_raw = {}
    for r in raw_list:
        names = [t for t in code_boards.get(r["code"], []) if t in sec]
        if not names:
            rs_sector_raw[r["code"]] = None
            continue
        # 按板块综合分排序取前三，再做 0.6/0.3/0.1 混合 ——
        # 不能直接取"最高分题材"，否则模型永远能为每只票挑出一个最漂亮的概念。
        names.sort(key=lambda t: -sec_score.get(t, 0.0))
        wsum = wtot = 0.0
        for w, t in zip(config.SECTOR_BLEND, names[:len(config.SECTOR_BLEND)]):
            wsum += w * (num(r.get("ret20")) - num(sec[t].get("med_ret20")))
            wtot += w
        rs_sector_raw[r["code"]] = (wsum / wtot) if wtot else None
    p_sector20 = rank_keep_none(rs_sector_raw)

    # ── 兼容字段的基础原料（最终波段字段在 V3 周期模型中覆盖）──
    rs_score, pv_score, trend_score = {}, {}, {}
    sector_score_map, sent_score, crowd_score = {}, {}, {}
    short_score_map, short_entry_map = {}, {}
    swing_score_map, swing_entry_map, risk_adjusted_map = {}, {}, {}
    downtrend, detail = {}, {}
    # 选股雷达的注释原料：每只票的**首要题材**上下文（成员数/上涨宽度/新高宽度/超额）
    sec_ctx = {}
    for r in raw_list:
        c = r["code"]
        r5, r20 = r.get("ret5"), r.get("ret20")

        # ─── RS ───
        rw = config.RS_WEIGHTS
        g = config.RS_GATE
        rs_v = (rw["rs3"] * p_ret3[c] + rw["rs5"] * p_ret5[c]
                + rw["rs20"] * p_ret20[c]
                + rw["rs60"] * p_ret60[c] + rw["updays5"] * p_up5[c])
        if p_sector20.get(c) is not None:
            rs_v += rw["sector20"] * p_sector20[c]
        else:
            # 没有题材归属时按已有子项归一化，不用 50 分白稀释
            rs_v = rs_v / max(1e-6, 1.0 - rw["sector20"])
        # 绝对动量闸门：杀掉"弱市里跌得少"的假强股
        if r20 is not None and r20 < 0 and r5 is not None and r5 < 0:
            rs_v *= g["both_neg_mult"]
        elif r20 is not None and r20 < 0:
            rs_v *= g["r20_neg_mult"]
        # 趋势方向闸门：跌破 MA20 且 MA20 向下 → 封顶
        weak = (num(r.get("above20")) == 0 and num(r.get("ma20_slope")) < 0)
        if weak:
            rs_v = min(rs_v, g["weak_cap"])
        rs_score[c] = round(clampf(rs_v), 2)
        downtrend[c] = 2 if (r5 is not None and r20 is not None and r5 < 0 and r20 < 0) \
            else (1 if weak else 0)

        # ─── 量价结构 ───
        pw = config.PV_WEIGHTS
        tq = _turn_quality(r.get("vol_pct_120"))
        struct_q = {1.0: 100.0, 0.6: 78.0, 0.0: 52.0, -1.0: 8.0}.get(
            round(num(r.get("pv_struct")), 1), 52.0)
        pv_score[c] = round(clampf(pw["vr"] * _vr_quality(r)
                                   + pw["vol_trend"] * p_voltrend[c]
                                   + pw["turn_pct"] * tq
                                   + pw["structure"] * struct_q), 2)

        # ─── 趋势质量（只判断结构完整度）───
        tw = config.TREND_WEIGHTS
        align = {0: 0.0, 1: 40.0, 2: 72.0, 3: 100.0}.get(int(num(r.get("bull_count"))), 0.0)
        # 斜率不无限奖励：加速部分是拥挤度的活，这里把上四分位压平
        sl = p_slope[c]
        slope_q = sl if sl <= 85 else 85.0 + (sl - 85.0) * 0.25
        stand = 50.0 + 30.0 * num(r.get("above20")) + 20.0 * num(r.get("above60"))
        trend_score[c] = round(clampf(tw["ma_align"] * align
                                      + tw["slope_atr"] * slope_q
                                      + tw["ma_stand"] * stand), 2)

        # ─── 板块强度 / 联动扩散 ───
        names = [t for t in code_boards.get(c, []) if t in sec_score]
        if names:
            names.sort(key=lambda t: -sec_score[t])
            wsum = wtot = 0.0
            for w, t in zip(config.SECTOR_BLEND, names[:len(config.SECTOR_BLEND)]):
                wsum += w * sec_score[t]
                wtot += w
            sector_score_map[c] = round(clampf(wsum / wtot), 2)
            # 首要题材（板块分最高的那个）的原始指标 —— 雷达注释要用它说清
            # "强在哪里"：是板块整体在扩散，还是这只票自己独走。
            top = names[0]
            sm = sec.get(top) or {}
            sec_ctx[c] = {
                "name": top,
                "n": int(num(sm.get("n"))),
                "breadth": round(num(sm.get("breadth")), 1),
                "new_high": round(num(sm.get("new_high")), 1),
                "excess": round(num(sm.get("excess")), 2),
                "amt_expand": round(num(sm.get("amt_expand"), 1.0), 2),
                "score": round(num(sec_score.get(top)), 1),
            }
        else:
            sector_score_map[c] = None

        # ─── 情绪 / 价格行为 ───
        ww = config.SENT_WEIGHTS
        clv_v = num(r.get("clv"), 0.5)
        amp = num(r.get("amplitude"))
        amp_clv = clv_v * 100.0 if amp >= config.SENT["amp_hi"] else 45.0 + clv_v * 25.0
        shadow_q = clampf(100.0 - num(r.get("upper_shadow")) * 90.0)
        if num(r.get("blasted")):
            shadow_q *= 0.5        # 炸板：够到停板没封住，明显降分
        sent_score[c] = round(clampf(ww["limit"] * _limit_quality(r)
                                     + ww["clv"] * (p_clv[c] if p_clv.get(c) is not None
                                                    else clv_v * 100.0)
                                     + ww["amp_clv"] * amp_clv
                                     + ww["shadow"] * shadow_q), 2)

        # ─── 拥挤 / 过热健康度 ───
        cw = config.CROWD_WEIGHTS
        dist_q = _dist_atr_quality(num(r.get("dist_atr")))
        # 5日涨幅分位越高 → 越拥挤 → 健康度越低
        ret5_health = 100.0 - (p_ret5[c] if p_ret5.get(c) is not None else 50.0)
        # 换手/量能分位越高 → 越拥挤
        turn_health = 100.0 - num(r.get("vol_pct_120"), 50.0)
        dist_struct = _crowd_dist_quality(r, p_ret5[c])
        crowd_score[c] = round(clampf(cw["dist_atr"] * dist_q
                                      + cw["ret5_pct"] * ret5_health
                                      + cw["turn_pct"] * turn_health
                                      + cw["dist"] * dist_struct), 2)
        detail[c] = {"dist_atr": round(num(r.get("dist_atr")), 2),
                     "vol_pct": round(num(r.get("vol_pct_120")), 1),
                     "vr": round(num(r.get("vr"), 1.0), 2),
                     "clv": round(clv_v, 2)}

        # ── V3 周期因子：把短线启动与波段强度拆成不同问题 ──
        # 中期 RS：20/60 日持续跑赢 + 所属题材内超额。
        _rs_parts = [(p_ret20.get(c), 0.40), (p_ret60.get(c), 0.30),
                     (p_sector20.get(c), 0.30)]
        _rs_have = [(v, wt) for v, wt in _rs_parts if v is not None]
        _swing_rs = (sum(v * wt for v, wt in _rs_have) / sum(wt for _, wt in _rs_have)
                     if _rs_have else 50.0)

        _path = _path_quality(r.get("er20"), r.get("max_dd20_pct"),
                              r.get("ma20_slope"))
        _pull = _pullback_quality(r, p_pull_vol.get(c), p_pull_depth.get(c))
        _sector = sector_score_map[c] if sector_score_map[c] is not None else None
        _relaunch = clampf(0.55 * (100.0 if r.get("rebreak3") else 35.0)
                            + 0.45 * _path)

        # 覆盖旧的“均线排列/单日情绪”含义，六个字段仍保留以兼容雷达与看板。
        rs_score[c] = round(clampf(_swing_rs), 2)
        pv_score[c] = round(clampf(_pull), 2)
        trend_score[c] = round(clampf(_path), 2)
        sent_score[c] = round(clampf(_relaunch), 2)

        # 短线五因子：板块扩散 / 个股领先 / 首次突破结构 / 成交确认 / 收盘承接。
        _short_sector = _sector if _sector is not None else 50.0
        _short_lead_parts = [(p_ret3.get(c), 0.50), (p_short_sector.get(c), 0.50)]
        _short_have = [(v, wt) for v, wt in _short_lead_parts if v is not None]
        _short_lead = (sum(v * wt for v, wt in _short_have) / sum(wt for _, wt in _short_have)
                       if _short_have else 50.0)
        _base_q = 0.35 * _compression_quality(r.get("atr_contract"))
        _base_q += 0.30 * _compression_quality(r.get("vol_contract"))
        _base_q += 0.35 * clampf(100.0 - num(r.get("range20"), 25.0) * 2.0)
        _short_structure = clampf(0.60 * _break_quality(r) + 0.40 * _base_q)
        _short_volume = clampf(0.65 * _vr_quality(r)
                               + 0.35 * _turn_quality(r.get("vol_pct_120")))
        _short_hold = clampf(0.70 * clv_v * 100.0
                             + 0.30 * clampf(100.0 - num(r.get("upper_shadow")) * 100.0))
        short_score = clampf(0.25 * _short_sector + 0.20 * _short_lead
                             + 0.25 * _short_structure + 0.20 * _short_volume
                             + 0.10 * _short_hold)

        _short_cfg = config.EXECUTION["short"]
        short_entry_ok = bool(
            r.get("breakout_age") is not None and r.get("broke20")
            and not r.get("intraday_fail")
            and clv_v >= _short_cfg["min_clv"]
            and _short_cfg["min_break_pct"] <= num(r.get("brk_pct"), -999)
                <= _short_cfg["max_break_pct"]
            and num(r.get("dist_atr"), 999) <= _short_cfg["max_dist_atr"]
            and _short_sector >= _short_cfg["min_sector"]
        )
        _swing_cfg = config.EXECUTION["swing"]
        swing_entry_ok = bool(
            num(r.get("above20")) and num(r.get("ma20_slope")) > 0
            and _sector is not None and _sector >= _swing_cfg["min_sector"]
            and num(r.get("dist_atr"), 999) <= _swing_cfg["max_dist_atr"]
            and num(r.get("er20"), 0) >= _swing_cfg["min_er20"]
            and (not r.get("pullback_valid")
                 or num(r.get("pullback_depth_atr"), 999)
                 <= _swing_cfg["max_pullback_depth_atr"])
            and (r.get("pullback_valid") or r.get("rebreak3"))
        )
        # “拥挤健康”作为独立风险调整：强度分与可执行分同时保留。
        _risk_mult = 0.70 + 0.30 * clampf(crowd_score[c]) / 100.0
        swing_score = clampf(0.30 * _swing_rs + 0.15 * _pull
                             + 0.25 * _path + 0.20 * _short_sector
                             + 0.10 * _relaunch)
        risk_adjusted_swing = clampf(swing_score * _risk_mult)
        short_score_map[c] = round(short_score, 2)
        short_entry_map[c] = int(short_entry_ok)
        swing_score_map[c] = round(swing_score, 2)
        swing_entry_map[c] = int(swing_entry_ok)
        risk_adjusted_map[c] = round(risk_adjusted_swing, 2)

    # ── 展示用：资金流与外围（**不进总分**）──
    has_fund = bool(fund_map)
    if has_fund:
        have = [c for c in codes if c in fund_map]
        fr = dict(zip(have, pct_rank([fund_map[c].get("fund5_ratio", 0.0) for c in have])))
        mr = dict(zip(have, pct_rank([fund_map[c].get("main_ratio", 0.0) for c in have])))
        fund_score = {c: (round(0.6 * fr[c] + 0.4 * mr[c], 2) if c in fund_map else None)
                      for c in codes}
        fund_source = "东财主力净流入"
    else:
        fund_score = dict(zip(codes, pct_rank([num(r.get("fund_proxy")) for r in raw_list])))
        fund_source = "价量代理（东财不可用，已自动降级）"

    sens_kw = outer_cfg_sensitive()
    outer_comp = outer.get("composite", 0.0)
    outer_score, linkage_score = {}, {}
    outer_hit = 0
    lo = config.THEME["link_min_members"]
    hi = config.THEME["link_max_members"]
    cap = config.THEME["link_weight_cap"]
    for r in raw_list:
        c = r["code"]
        bnames = code_boards.get(c, [])
        if theme_groups:
            num_l = den_l = 0.0
            for b in bnames:
                gg = theme_groups.get(b)
                if not gg:
                    continue
                n0 = gg.get("n", 0)
                if n0 < lo or n0 > hi:
                    continue
                wt = min(n0, cap)
                num_l += gg["up_ratio"] * wt
                den_l += wt
            linkage_score[c] = round(num_l / den_l, 2) if den_l else None
            rel = max((sens_kw.get(kw, 0.0) for b in bnames for kw in sens_kw
                       if kw in b), default=0.0)
            if rel > 0:
                outer_hit += 1
            outer_score[c] = round(clampf(50 + 50 * math.tanh(rel * outer_comp / 1.2)), 2)
        else:
            linkage_score[c] = None
            outer_score[c] = None

    # ── 加权汇总 ──
    w = dict(weights)
    if not sec_score:
        w.pop("sector", None)

    out = []
    for r in raw_list:
        c = r["code"]
        f = {"rs": rs_score[c], "pv": pv_score[c], "trend": trend_score[c],
             "sector": sector_score_map[c], "sent": sent_score[c],
             "crowd": crowd_score[c],
             # 展示用（不进总分）
             "fund": fund_score.get(c), "linkage": linkage_score.get(c),
             "outer": outer_score.get(c)}
        # 默认总分是波段核心强度经过拥挤风险调整后的分数；
        # 观察用的 score_strength 保留未调整强度，便于区分“强”与“可追”。
        total = risk_adjusted_map.get(c, swing_score_map.get(c, 0.0))
        short_s = short_score_map.get(c, 0.0)
        # 波段页展示可执行的风险调整分，而不是只展示“强度分”。
        # 未调整的波段强度仍由 score_strength 保留，供复核“强但过热”的股票。
        mid_s = risk_adjusted_map.get(c, swing_score_map.get(c, 0.0))
        sec_v = f["sector"] if f["sector"] is not None else 50.0
        trend_s = clampf(0.45 * f["rs"] + 0.35 * f["trend"] + 0.20 * sec_v)
        d = detail.get(c, {})
        # 强度分把拥挤健康度单独拿开，供“强度 vs 追涨风险”并读；主排序仍使用
        # 风险调整后的 score，避免把过热票误当成安全买点。
        strength_total = swing_score_map.get(c, 0.0)
        out.append({
            "code": c, "name": r["name"], "price": r["price"],
            "change_pct": r["change_pct"], "turnover": r["turnover"],
            "amount_wan": r["amount_wan"], "float_mcap": r["float_mcap"],
            "ret3": r["ret3"], "ret5": r["ret5"], "ret20": r["ret20"], "ret60": r["ret60"],
            "limit_today": r["limit_today"], "limit_streak": r["limit_streak"],
            "limit_5d": int(num(r.get("limit_5d"))),
            "vol_ratio5": round(num(r.get("vol_ratio5"), 1.0), 2),
            "vr": round(num(r.get("vr"), 1.0), 2),
            "vol_pct_120": round(num(r.get("vol_pct_120")), 1),
            "vol_ratio_rt": round(num(r.get("vol_ratio_rt")), 2),
            "vol_partial": r.get("vol_partial", 0),
            "position60": round(num(r["position60"]), 1),
            "bull_count": r["bull_count"], "bias20": round(num(r["bias20"]), 1),
            "dist_atr": d.get("dist_atr", 0.0), "clv": d.get("clv", 0.5),
            "er20": r.get("er20"), "max_dd20_pct": r.get("max_dd20_pct"),
            "pullback_valid": r.get("pullback_valid", 0),
            "pullback_volume_ratio": r.get("pullback_volume_ratio"),
            "pullback_depth_atr": r.get("pullback_depth_atr"),
            "reclaim_ma10": r.get("reclaim_ma10", 0), "rebreak3": r.get("rebreak3", 0),
            "amt_med20_wan": round(num(r.get("amt_med20_wan")), 1),
            "ma5_bull": r.get("ma5_bull", 0),
            "above20": r.get("above20", 0), "above60": r.get("above60", 0),
            "boards": code_boards.get(c, []),
            # 兼容旧快照字段；分类主链路已移除东财标签，scoring 层会明确置空。
            "boards_em": [],
            # 同花顺 thshy 行业和个股 F10 可能同时提供父子层级，不能只取第一个。
            "industry": (industries.get(c) or [])[
                :config.THEME.get("max_industry_per_stock", 4)],
            # ── 选股雷达注释原料（都是已算好的原始量，雷达不再回算）──
            "slope_atr": round(num(r.get("slope_atr")), 2),
            "up5": r.get("up_days_5"),
            "ex5": _excess(r.get("ret5"), med5),
            "ex20": _excess(r.get("ret20"), med20),
            "ex60": _excess(r.get("ret60"), med60),
            "ex_sec20": (None if rs_sector_raw.get(c) is None
                         else round(num(rs_sector_raw.get(c)), 2)),
            "sec_ctx": sec_ctx.get(c),
            # ── 短线启动（Ignition-1）原始指标：打分与注释都由 ignition.py 用 ──
            # 只透传原始量，不做任何分位 —— 两套策略的分位各自算、绝不互借
            "ph20": r.get("ph20"), "ph60": r.get("ph60"),
            "broke20": r.get("broke20"), "broke60": r.get("broke60"),
            "above_yest": r.get("above_yest"), "first_breakout": r.get("first_breakout"),
            "breakout_age": r.get("breakout_age"),
            "brk_pct": r.get("brk_pct"), "intraday_fail": r.get("intraday_fail"),
            "breakout_date": r.get("breakout_date"), "breakout_atr20": r.get("breakout_atr20"),
            "breakout_clv": r.get("breakout_clv"),
            "breakout_upper_shadow": r.get("breakout_upper_shadow"),
            "range20": r.get("range20"), "atr_contract": r.get("atr_contract"),
            "vol_contract": r.get("vol_contract"), "ma_converge": r.get("ma_converge"),
            "r5_pre": r.get("r5_pre"), "r20_pre": r.get("r20_pre"),
            "dist_pre_atr": r.get("dist_pre_atr"),
            "gap_pct": r.get("gap_pct"), "fall_from_high": r.get("fall_from_high"),
            "upper_shadow": r.get("upper_shadow"), "blasted": r.get("blasted"),
            "amplitude": r.get("amplitude"),
            "downtrend": downtrend.get(c, 0),
            "traded": r.get("traded", 1),
            "board_type": r.get("board_type"), "board_name": r.get("board_name"),
            "board_limit": r.get("board_limit"), "list_days": r.get("list_days"),
            "is_new": r.get("is_new", 0), "bars": r.get("bars"),
            "limit_pct": r.get("limit_pct"),
            "factors": f,
            "score": floor1(total),
            "score_strength": floor1(strength_total),
            "risk_drag": round(strength_total - total, 2),
            "score_short": round(short_s, 2),
            "score_mid": round(mid_s, 2),
            "score_swing_strength": round(strength_total, 2),
            "score_trend": round(trend_s, 2),
            "short_entry_ok": short_entry_map.get(c, 0),
            "swing_entry_ok": swing_entry_map.get(c, 0),
        })
    out.sort(key=lambda x: -x["score"])
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out


_SENS_CACHE = None


def outer_cfg_sensitive():
    global _SENS_CACHE
    if _SENS_CACHE is None:
        _SENS_CACHE = config.OUTER["sensitive_keywords"]
    return _SENS_CACHE
