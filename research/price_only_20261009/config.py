# -*- coding: utf-8 -*-
"""全局配置 —— 股票强势监测系统

所有口径、权重、阈值集中在此，改这里不用动逻辑代码。
"""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def atomic_write_text(path, text, encoding="utf-8"):
    """原子写文件：先写同目录临时文件，再 os.replace 覆盖。

    为什么必须原子：快照 4MB、看板 3.6MB，非原子写会在写入过程中暴露一个
    "半截文件"。同机上另一个进程（定时任务 / serve.py 的刷新线程）或正在
    刷新的浏览器恰好此时读取，就会拿到截断的 JSON / HTML ——
    表现为看板空白、或 json.loads 报错。os.replace 在同一分区上是原子的，
    读到的要么是旧版本、要么是新版本，永远不是半截。
    """
    path = Path(path)
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return path

KLINE_DB = CACHE_DIR / "market.db"          # K线 + 板块日线缓存（sqlite）
SNAPSHOT_JSON = CACHE_DIR / "snapshot.json"  # 看板读取的数据快照
POOL_CACHE = CACHE_DIR / "pool.json"         # 股票池缓存
POOL_META_CACHE = CACHE_DIR / "pool_meta.json"   # 池的口径指纹（板别等）、命中数
BOARD_CACHE = CACHE_DIR / "boards.json"      # 概念板块映射缓存
EM_BOARD_CACHE = CACHE_DIR / "em_boards.json"      # 东财概念板块 code→名 缓存
BOARD_ALIAS_CACHE = CACHE_DIR / "board_alias.json"  # 东财板块名→同花顺概念名 映射
THS_MEMBER_CACHE = CACHE_DIR / "ths_members.json"   # 同花顺概念详情→成分股（纯同花顺）
# 同花顺网页端概念目录（名称/885xxx↔网页详情号映射）。
# 这是概念名称的主口径；boards.json 仍保留为板块日线的本地快照，
# 同花顺目录短暂不可访问时不影响看板继续使用上一份可验证数据。
THS_CONCEPT_CACHE = CACHE_DIR / "ths_concepts.json"
# 同花顺行业目录与行业成分缓存。概念（gn）和行业（thshy）是两套目录，
# 例如“化学制药”属于 thshy；不能只靠东财行业字段代替，否则会漏掉
# 同花顺口径下的二级行业归属。
THS_INDUSTRY_CACHE = CACHE_DIR / "ths_industries.json"
THS_INDUSTRY_MEMBER_CACHE = CACHE_DIR / "ths_industry_members.json"
MEMBER_REFRESH_DAYS = 7  # 成员分类周更；报价与指数仍按原5分钟节奏。
# 同花顺个股 F10 概念题材 + 申万行业（页面展示口径）。
THS_STOCK_PROFILE_CACHE = CACHE_DIR / "ths_stock_profiles.json"
# 东财增强数据的最近一次成功结果。仅用于资金流/实时板块行情，不进入行业、题材、概念分类。
# 结果会把 stale/source_age 暴露到快照，避免把旧资金流伪装成实时数据。
EM_FUND_CACHE = CACHE_DIR / "em_fundflow_last_good.json"
EM_BOARD_RT_CACHE = CACHE_DIR / "em_boards_last_good.json"
SOURCE_HEALTH_CACHE = CACHE_DIR / "source_health.json"
# AkShare 是按需启用的免费备用行情源。它的全市场接口需要分页，
# 不能每轮无条件重拉；落盘后只在腾讯批量行情缺口明显时读取/刷新。
AKSHARE_SPOT_CACHE = CACHE_DIR / "akshare_sina_spot.json"
AKSHARE_SPOT_TTL_SECONDS = 5 * 60

# ═══════════════════════════════════════════════════════
# 〇、板别口径  —— 四板的代码前缀与涨跌幅限制
#
# 为什么必须按板别分开算涨停：主板 ±10%，创业板/科创板 ±20%。
# 拿一个 9.8% 的阈值去判全市场，创业板涨 10% 会被错标成"涨停"
# （实际离 20% 停板还差一半），连板高度、情绪因子、涨停家数、
# 领涨题材词频会全线失真。所以涨停阈值必须由板别决定。
# ═══════════════════════════════════════════════════════
BOARDS = {
    # key 同时用作快照里的 board_type，前端直接显示 name
    # em_fs 是该板在东财 clist 里的筛选串（上市日期与资金流按池内板别抓取）
    "sh_main": {"name": "沪主板", "prefix": ("600", "601", "603", "605"),
                "limit_pct": 10.0, "em_fs": "m:1+t:2"},
    "sz_main": {"name": "深主板", "prefix": ("000", "001", "002", "003"),
                "limit_pct": 10.0, "em_fs": "m:0+t:6"},
    "gem":     {"name": "创业板", "prefix": ("300", "301"),
                "limit_pct": 20.0, "em_fs": "m:0+t:80"},
    "star":    {"name": "科创板", "prefix": ("688", "689"),
                "limit_pct": 20.0, "em_fs": "m:1+t:23"},
    # 北交所默认不纳入：±30% 停板、流动性与沪深差异大，混在一起比强弱没意义。
    # 若要纳入，把下面这段打开，并在 POOL["boards"] 里加上 "bse" 即可
    # （候选代码区间由 prefix 自动推出来，不用再手改 datafeed）。
    # "bse": {"name": "北交所",
    #         "prefix": ("430", "831", "832", "833", "834", "835", "836", "837",
    #                    "838", "839", "870", "871", "872", "873", "920"),
    #         "limit_pct": 30.0, "em_fs": "m:0+t:81+s:2048"},
}

# 涨停判定的容差：报价小数位与四舍五入导致实际涨幅略低于理论停板值，
# 主板留 0.2 个点、20% 板留 0.3 个点（20% 板的绝对误差更大）
BOARD_LIMIT_TOLERANCE = 0.02   # 按 limit_pct 的比例折算：10%→0.2，20%→0.4


def board_of(code):
    """由股票代码判断所属板别，返回 (board_type, 板别名, 涨跌幅限制%)。

    查不到时按深主板处理并返回 10% —— 宁可少标错，也不要让整只股票
    因为板别缺失而拿不到涨跌幅限制（会被当成"永不涨停"）。
    """
    c = str(code or "")
    for key, cfg in BOARDS.items():
        if c.startswith(cfg["prefix"]):
            return key, cfg["name"], float(cfg["limit_pct"])
    return "sz_main", "深主板", 10.0


def limit_pct_for(code, list_days=None):
    """该股当日用于判定涨停的涨跌幅阈值（%）。

    新股无涨跌幅限制期间（主板上市首日 / 创业板·科创板上市前 5 日）
    一律返回 999，即"永不判涨停"——否则新股首日翻倍会被记成 20 连板，
    把情绪因子和涨停题材词频直接打爆。
    """
    key, _, lim = board_of(code)
    if list_days is not None:
        free = POOL["new_limit_free_days"].get(key, 1)
        if list_days <= free:
            return 999.0
    return lim - lim * BOARD_LIMIT_TOLERANCE


# ═══════════════════════════════════════════════════════
# 一、股票池口径  —— 沪深主板 + 创业板 + 科创板，剔ST、标记次新
# ═══════════════════════════════════════════════════════
POOL = {
    # ── 纳入哪些板（BOARDS 的 key）── 这是股票池口径的**唯一真源**：
    # 候选代码区间、东财 em_fs 筛选串都从它派生，改这里就够。
    #
    # 2026-09-20 收回主板：这套系统是为**主板**服务的。
    # 创业板 + 科创板合计近 2000 只、±20% 停板放大波动，混进来会把主板的
    # 机会淹没在噪音里（用户原话：太多了，影响判断）。
    # 想恢复四板只要把 "gem","star" 加回来一行即可。
    "boards": ["sh_main", "sz_main"],
    # 名称含以下关键词的一律剔除
    "exclude_keywords": ["ST", "退", "PT"],
    # 次新股：自 V2.2 起由 RISK_GATE["min_trading_days"]=120 兜住 ——
    # 60 自然日 ≈ 41 交易日 < 120，所以**池内不可能再有次新**。
    # 保留这个标记只为将来放宽门槛时能立刻恢复标注能力，界面上会如实显示"池内 0 只"。
    "min_list_days": 0,
    # 上市不足 N 个自然日 → 标记为次新
    "new_stock_days": 60,
    # 新股无涨跌幅限制的天数（上市当天起算）。这期间不判涨停。
    # 同样已被 Risk Gate 覆盖（上市 ≥120 交易日的股票早已过限售期），
    # 保留是为了口径完整与将来放宽门槛时不出现漏判。
    # 沪深股票上市后的前 5 个交易日不实行价格涨跌幅限制。
    "new_limit_free_days": {"sh_main": 5, "sz_main": 5, "gem": 5, "star": 5},
    # 无成交状态仅用于重建股票池时的诊断统计；代码仍留在池内，以便跟踪恢复成交。
    # 正式可交易候选由每轮最新报价的 Risk Gate 限制。
    # 盘前/盘后不能仅凭成交额为 0 推断停牌。
    "exclude_halted": True,
    "halt_use_amount_check": True,     # 交易时段内额外用成交额判停牌
    # 一字板（涨跌幅≈停板 且 最高==最低）单独标记，不进主榜
    "flag_limit_oneboard": True,
}


def pool_boards():
    """池内纳入的板别 key 列表（顺序即 BOARDS 的声明顺序）。"""
    keys = POOL.get("boards") or list(BOARDS)
    return [k for k in BOARDS if k in keys]


def pool_em_fs():
    """东财 clist 的筛选串 —— 由 POOL["boards"] 派生，避免两处口径各写一份。"""
    return ",".join(BOARDS[k]["em_fs"] for k in pool_boards()
                    if BOARDS[k].get("em_fs"))


# 派生量：下游（datafeed / audit）直接读 POOL["em_fs"]，不必各自拼一次
POOL["em_fs"] = pool_em_fs()


def pool_board_names():
    """池内板别的中文名，用于文案（如"覆盖 沪主板·深主板"）。"""
    return [BOARDS[k]["name"] for k in pool_boards()]

# ═══════════════════════════════════════════════════════
# 一·补、题材（概念）标签口径
#
# 数据源口径：同花顺概念目录（gn）与同花顺个股 F10。
# 东财仅保留在资金流/实时板块行情增强层，不得作为行业、题材、概念的来源或兜底。
# ═══════════════════════════════════════════════════════
THEME = {
    # 历史兼容项；当前成员映射与 F10 展示都不按此项裁剪。
    "precise_only": True,
    # 历史兼容项；当前因子成员图保留全部通过属性过滤的同花顺概念。
    "max_per_stock": 8,
    # 历史合并函数兼容值；当前概念成员映射不再按单股标签数截断。
    "max_tags_total": 22,
    # 行业字段允许保留的同花顺层级标签数，至少能同时看到父子层级。
    "max_industry_per_stock": 4,
    # 属性/状态/指数成分类标签黑名单 —— 它们不是"题材"，
    # 不过滤掉的话题材榜会变成"昨日涨停 / 融资融券 / 沪股通"的天下
    "exclude_keywords": [
        "融资融券", "沪股通", "深股通", "北向", "机构重仓", "基金重仓", "QFII", "社保重仓",
        "券商重仓", "信托重仓", "保险重仓", "MSCI", "富时罗素", "标准普尔", "标普道琼斯",
        "小盘股", "中盘股", "大盘股", "微盘股", "破净股", "破增发价", "高送转", "送转预期",
        "参股新三板", "新三板", "转债标的", "AH股", "B股", "GDR", "深成500", "沪深300",
        "中证500", "上证50", "上证180", "创业板综", "中证1000", "次新股", "ST股",
        "昨日", "最近多板", "东财热股", "东方财富热股", "高振幅", "低价股", "高价股",
        "业绩预增", "业绩预减", "预盈预增", "年报", "中报", "季报", "扭亏", "摘帽",
        "股权转让", "增持", "回购", "解禁", "定增", "员工持股", "股权激励",
        "注册制", "科创板", "创业板", "北交所", "专精特新",
        "破发", "破净", "超跌", "低价", "高价", "强势股", "热门", "榜",
        # 2026-09-18 补录：实测漏网，会把题材榜变成"国企改革"榜
        "国企改革", "央企改革", "国资改革", "参股", "低市净率", "市净率",
        # 2026-09-20 补录：四板扩容 + 标签上限放宽后冒出来的漏网词。
        # 「中字头股票」是同花顺的一个概念，但它是"股本属性"，不是题材。
        "中字头",
        "高股息", "红利", "绩优", "壳资源", "次新",
        # 2026-09-18 二次补录：东财把「规模×风格 / 属性股 / 状态」也塞进了概念池，
        # 实测漏网 30 个标签（小盘价值 198 只、金融地产风格 95 只、趋势股 103 只…），
        # 不滤会把题材榜稀释成风格榜。逐条核对过，均非真实题材。
        "小盘", "中盘", "大盘", "微盘", "风格", "价值", "成长",
        "趋势股", "周期股", "微利股", "题材股", "权重股", "反转股", "百元股",
        "股权", "举牌", "持股", "新高", "新低", "金股", "行业龙头",
        "同花顺果指数", "同花顺出海50", "同花顺新质50", "同花顺漂亮100",
    ],
    # 题材成员数上限：超过这个数量就不是「题材」而是「风格」了
    # （如「央国企改革」覆盖 1100+ 只，其上涨占比恒等于大盘水平，无区分度）
    "max_members": 400,
    # 题材强度榜（ranked）的最小成员数 —— 成员太少的题材，其「上涨占比」由
    # 少数标的决定，统计意义弱；报告标题的口径标注必须与此值一致，否则会
    # 出现"标题写≥8、表内却有 6 只成员的题材"这类自相矛盾（已踩坑）。
    "rank_min_members": 5,
    # 联动因子计入的题材规模区间与加权上限
    "link_min_members": 5,
    "link_max_members": 400,
    "link_weight_cap": 80,
    # 成交覆盖率门槛：题材组成员中「有涨跌方向」的比例。
    # 开盘初期大量个股尚未成交（涨跌幅=0），若把它们排除在分母外，
    # 会出现"10只成员5只涨、5只没成交 → 上涨占比100%"的假象（已踩坑）。
    "min_cover": 0.6,
    # 缓存指纹：黑名单等配置变化时自动失效旧缓存，避免"改了配置却不生效"
    "cache_ver": "2026-09-24b",

    # ── 题材口径：同花顺概念为唯一分类来源 ──
    # 个股 F10 的“相关概念”、概念详情页的成员名单、概念指数板块全部来自同花顺。
    # alias_* 仅保留给历史迁移函数，不参与当前构建。
    "alias_min_len": 3,
    # 东财原名不得作为行业/题材/概念兜底标签。
    "keep_em_fallback": False,
    # 成分数 ≥ 此值的板块视为"风格/全市场口径"（上证380、标普道琼斯等），
    # 只记账告警、不参与题材榜，避免把标签柱污染成几十个而无从查找真题材。
    "member_big_warn": 1200,
}

# ═══════════════════════════════════════════════════════
# 一·补二、同花顺板块榜的「类型」过滤
#
# 同花顺概念指数里混着大量"风格/状态"类板块（次新股、低价股、破净股、
# 融资融券、昨日涨停…）。它们不是题材，且成分股跨行业，没有轮动含义，
# 混进强度榜会挤掉真正有资金聚集的题材。
# ═══════════════════════════════════════════════════════
BOARD = {
    "exclude_keywords": [
        "次新", "低价", "高价", "破净", "破发", "超跌", "强势", "热门",
        "绩优", "预增", "预减", "扭亏", "摘帽", "高送转", "送转",
        "融资融券", "沪股通", "深股通", "标的", "转债", "B股", "AH", "GDR",
        "注册制", "壳资源", "标普", "MSCI", "富时", "成指", "综指", "指数",
        "大盘", "中盘", "小盘", "微盘", "ST",
        # 2026-09-18 二次补录：同花顺概念指数里的国资/参股/高股息类风格指数
        "国企改革", "央企", "国资改革", "中字头",
        "参股", "举牌", "持股", "高股息", "红利",
        "价值", "成长", "风格", "新高", "新低", "股权",
        "题材股", "趋势股", "周期股", "微利股", "权重股", "反转股", "百元股",
        "金股", "行业龙头", "融资", "融券", "重仓", "成分", "成份",
    ],
    # 板块内联动的样本覆盖率下限：低于此值说明该板块当日多数成分股没有成交，
    # 涨跌家数不具代表性，该板块的联动分不参与打分
    "min_cover": 0.5,
}

# ═══════════════════════════════════════════════════════
# 二、K线参数
# ═══════════════════════════════════════════════════════
KLINE = {
    # 拉取天数。V2.2 需要 120 日历史分位（换手/量能）与 ATR20，
    # 所以从 70 根提到 160 根（覆盖 120 分位窗口 + MA60 + 缓冲）。
    # 代价：库体积约翻倍，全量重拉一次约 3-5 分钟。
    "days": 160,
    "workers": 10,       # 并发线程（腾讯K线不封IP）
    "ma_windows": [5, 10, 20, 60],
    "rs_windows": {"short": 5, "mid": 20, "long": 60},   # 多周期相对强度
    # 整批抓取的硬超时（秒）。单条请求 timeout=20×retry=2 最坏 60 秒，
    # 一旦腾讯侧开始限流，五千多只 × 10 线程最坏能拖几小时且**全程无输出**，
    # 表现为"卡死"。到点就收下已拿到的，剩余用库里的旧K线兜底，
    # 宁可今天少几只的新K线，也不能让日更任务挂在那里。
    "deadline_seconds": 900,
    # 前复权K线的可用主机 —— **按顺序故障转移**。
    # 2026-09-20 实测：web.ifzq.gtimg.cn 全量返回 501 Not Implemented，
    # 但 proxy.finance.qq.com 上的同名接口照常可用、JSON 结构完全一致
    # （都返回 data.{code}.qfqday）。这就是"域名级封禁"的老套路，
    # 跟东财 push2 封禁一模一样 —— 主域名挂了不代表接口挂了。
    # 当时没有备用主机，结果 5092 只里只有前 2505 只抓成功，
    # 其余全部走重试白等，日志里只表现为"卡在 KLINE 不动"。
    "hosts": [
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
        "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get",
        "https://proxy.finance.qq.com/appstock/app/fqkline/get",
    ],
}

# ═══════════════════════════════════════════════════════
# 一·前置、成交量单位归一化（血泪教训）
#
# 腾讯前复权 K 线的成交量单位**按板块不一致**：
#   主板/创业板（000/001/002/003/300/301/600/601/603/605）→ 单位是「手」，需 ×100
#   科创板（688/689）                                        → 单位是「股」，无需换算
# 实测方式：拿每只个股最后一根K线的 `成交量 × 收盘价` 去比实时成交额，
#          前者比值稳定在 0.010，后者稳定在 1.00（594 个科创板样本无一例外）。
#
# 为什么以前没发现：量比、量能趋势这类**比值**的量纲会自动约掉，
# 成交额绝对值还用于20日中位数展示和板块成交额扩张；
# 不归一化会使不同板别的估算值相差约100倍。
#
# 本函数把成交量统一换算成「股」，写入侧调用；存量库另有一次性迁移。
# ═══════════════════════════════════════════════════════
VOLUME_UNIT = {"default": 100, "688": 1, "689": 1}


def volume_to_shares(code):
    """该代码的成交量换算成「股」需要乘的系数"""
    return VOLUME_UNIT.get(str(code or "")[:3], VOLUME_UNIT["default"])


def bar_amount_wan(bar):
    """单根K线的成交额（万元）。

    腾讯历史K线**不返回成交额**（该字段恒为 0），只有成交量。
    用 `成交量(股) × 收盘价` 估算，实测与实时成交额偏差 <3%
    （日内 VWAP 与收盘价的差，方向随机、不累积）。
    """
    try:
        return float(bar.get("volume") or 0) * float(bar.get("close") or 0) / 1e4
    except (TypeError, ValueError):
        return 0.0

# ═══════════════════════════════════════════════════════
# 三、均线趋势观察：三线排列为资格，个股自身强度另行评分。
# ═══════════════════════════════════════════════════════
SIMPLE_STRENGTH = {
    "min_industry_peers": 5,
    "watch_percentile": 80.0,  # 仅保留旧字段兼容；观察资格由三线排列决定。
    "max_dist_atr": 3.5,
}
CONFIRMED_PULLBACK_STATES = ("回踩反弹", "回踩后上行")

# 独立量价结构观察第一轮；研究初值，不进入进攻分或主榜门槛。
WYCKOFF_STRUCTURE = {
    "shrink_ratio": 0.8, "contraction_ratio": 0.85,
    "breakout_buffer_atr": 0.1, "price_tick": 0.01,
    "close_location_min": 0.7, "breakout_volume_ratio": 1.3,
    "sos_spread_ratio_min": 1.1, "lps_spread_ratio_max": 0.8,
    "failure_buffer_atr": 0.3, "max_setup_days": 12,
    "retest_touch_days": 5, "retest_confirm_days": 3,
    "retest_band_atr": 0.3, "retest_low_buffer_atr": 0.1, "retest_volume_ratio": 0.8,
    "stall_volume_ratio": 2.0, "stall_range_atr": 0.5, "stall_move_atr": 0.2,
    "confirmation_samples": 2, "max_sample_gap_seconds": 900, "scale_tolerance": 1e-6,
}

# 强股整理观察：公开的研究初值；资格、结构与盘中确认分别判断。
TREND_CONSOLIDATION = {
    "history_bars": 40, "min_pullback_days": 2, "max_days": 12, "preferred_days": (3, 8),
    "impulse5_min_pct": 15.0, "impulse10_min_pct": 20.0, "impulse_search_days": 5,
    "near_line_atr": 0.8,
    "initial_max_gain_pct": 4.0, "initial_max_ma5_atr": 0.8,
    "initial_max_platform_atr": 0.5, "clear_turn_gain_pct": 7.0,
    "repair_recovery_min": 0.8, "max_pullback_width_atr": 3.0,
    "preferred_pullback_atr": (0.5, 2.0), "max_pullback_atr": 2.5,
    "horizontal_range_atr": 2.5, "shrink_volume_ratio": 0.8,
    "horizontal_rise_allow_atr": 0.5, "expanded_down_move_atr": 0.5,
    "contract_range_ratio": 0.85, "expanded_down_volume_ratio": 1.3,
    "confirmation_samples": 2, "max_sample_gap_seconds": 900,
    # 仅描述合格整理内的回踩反弹，不豁免首次多头/前期进攻资格。
    "rebound_near_atr": 0.4, "rebound_undercut_atr": 0.15,
    "support_alert_atr": 0.4,  # 支撑上方0.4 ATR内提示靠近
    "rebound_approach_atr": 0.25, "rebound_min_atr": 0.5,
    "rebound_min_pct": 2.0, "rebound_max_age_days": 3,
}

# ═══════════════════════════════════════════════════════
# 盘中观察模型（研究初值；与完成日线强度分开）
# 报价不完整、过期或不同批次时不参与盘中评分。
# ═══════════════════════════════════════════════════════
INTRADAY = {
    "max_quote_age_seconds": 600,          # 5分钟扫描；超过10分钟不进入新一轮排名
    "max_quote_batch_skew_seconds": 300,   # 同批报价时间跨度容忍值
    "max_quote_future_seconds": 90,        # 行情源时钟略快时的容忍值
    "max_price_basis_gap_pct": 5.0,         # 已核验日期和来源后，仅作为比例转换异常拦截
    "startup_score_min": 70.0,             # 初步启动入口的观察分研究初值
    "min_industry_peers": 5,
}
INTRADAY_RULE_VERSION = "盘中规则2026-09-30.4"
INTRADAY_RISK = {
    "large_drop_limit_ratio": 0.70,        # 相对各板跌幅限制的比例，研究初值
    "near_limit_down_ratio": 0.90,         # 接近跌停，研究初值
    "limit_price_tolerance_pct": 0.25,      # 判断触及停板价的容差
    "high_pullback_min_pct": 2.5,          # 从日内高点至少回撤此幅度才考虑冲高回落
    "weak_day_position_max": 0.40,         # 日内区间位置低于该值
    "min_day_range_pct": 1.5,              # 振幅太小时不判明显冲高回落
    "overheat_dist_atr": 3.5,              # 现价距盘中MA5的ATR阈值（严格超过）
}

FACTOR_WEIGHTS = {"rs": 1.0}  # 保留公共配置名；rs 对应个股自身强度分位。
STRATEGY = {
    "default": "trend",
    "factors": {"trend": [("rs", "日线基础强度分位")]},
    "list": [{"key": "trend", "name": "趋势与进攻强度 V4.0", "short": "趋势观察",
              "model": "完成日5/10/20日均线 · 日线基础强度与盘中观察分开 · 情绪和板块单列",
              "hook": "三线排列且20日线上行、收盘守住10日线；进攻按5/10/20日实际涨幅与相对速度比较，整理突破与风险另列。",
              "hold": "历史回放统一观察10个交易日，尚非最优参数。"}],
}
STRATEGY_WEIGHTS = {"trend": {"rs": 1.0}}

# 以下旧模型参数供历史审查脚本读取，已退出在线选股与看板。
# 分数只负责排序，资格决定是否允许形成新仓。
EXECUTION = {
    "short": {
        "min_clv": 0.55, "min_break_pct": 0.10, "max_break_pct": 8.0,
        "max_dist_atr": 3.5, "min_sector": 45.0,
    },
    "swing": {
        "max_dist_atr": 3.5, "min_sector": 45.0, "min_er20": 0.12,
        "max_pullback_depth_atr": 2.5,
    },
}

# ═══════════════════════════════════════════════════════
# 二·补二、Ignition-1（启动窗口模型）口径
#
# 核心不是"今天涨得多"，而是「Base → Breakout 状态转换发生的首日及随后确认窗口」。
# 所以有硬门槛：窗口外、跌回平台、或已经加速过头的，**直接不算候选**。
# 所有阈值均为先验设定，标注 ⚠ 的尤其该等 OOS 回测来定。
# ═══════════════════════════════════════════════════════
IGNITION = {
    # ── 硬门槛（先 Gate，再评分；过不了的不给 ign_score）──
    "gate": {
        "require_first_breakout": True,   # 保留旧配置名；实际为首日及确认窗口
        "max_breakout_age": 3,            # 首日后的 1~3 个交易日仍可作为确认候选
        # 突破前 5 日涨幅超过此值（%），说明已经加速过，不是"第一天"。
        # 用户给的区间是 20%~25%，取 22 中值 ⚠（OOS 再定）
        "r5_pre_max": 22.0,
        # 突破前距 MA20 超过 3 ATR，同样视为"已经启动"，不是首日 ⚠
        "dist_atr_max": 3.0,
        # 突破前 5 日涨幅超过此值即开始软性扣分（低于硬门槛、高于理想带）⚠
        "r5_pre_soft": 12.0,
    },
    # 平台与突破定义
    "plat": {"short": 20, "long": 60, "tol": 0.001,
             "breakout_buffer_atr": 0.10},
    # 量价点火：今日量 ÷ 近20日成交量中位数（中位数，不是均值）
    "vr_ideal": (1.5, 3.0),     # 理想测试区间
    "vr_ok": (1.2, 4.5),        # 可接受区间，之外线性衰减
    # 换手率自身 120 日分位
    "turn_ideal": (70.0, 95.0), # 优先带
    "turn_extreme": 99.0,       # 极端分位 + 巨量 + 低 CLV → 派发风险
    # 首日突破质量
    "clv_fail": 0.55,           # 收盘承接弱不能仅靠其它因子抵消
    "clv_good": 0.75,           # 理想 CLV
    "brk_ideal": (0.2, 4.5),    # 突破幅度理想带（%，过大=追高）⚠
    "gap_max": 3.0,             # 高开超过此值开始扣分（%）⚠
    "shadow_hi": 0.35,          # 上影线占当日振幅比例超过此值扣分
    # 前置相对强度（突破前 20 日，池内分位）理想带：已悄悄跑赢但未成最拥挤
    "pre_rs_ideal": (60.0, 88.0),
    "pre_rs_too_hot": 96.0,     # 超过此分位说明可能已启动数日
    "pre_rs_too_weak": 40.0,    # 低于此分位说明无资金提前布局
}

# Ignition 各因子内部权重（合计 1.0）
IGNITION_SUB = {
    "base": {"atr_contract": 0.35, "range": 0.25, "vol_contract": 0.20, "ma_converge": 0.20},
    "breakout": {"break20": 0.45, "break60": 0.20, "clv": 0.20, "amp_ok": 0.15},
    "ignite": {"vr": 0.55, "turn": 0.45},
    "sector": {"excess": 0.35, "breadth": 0.25, "new_high": 0.20, "amt_expand": 0.20},
    "pre_rs": {"market": 0.65, "industry": 0.35},
}


def strategy_by_key(key=None):
    """按 key 取策略元信息（key=None 返回默认策略）。"""
    k = key or STRATEGY["default"]
    for s in STRATEGY["list"]:
        if s["key"] == k:
            return s
    return STRATEGY["list"][0]


def strategy_keys():
    return [s["key"] for s in STRATEGY["list"]]


def strategy_weights(key=None):
    k = (key or STRATEGY["default"])
    w = STRATEGY_WEIGHTS.get(k) or STRATEGY_WEIGHTS["trend"]
    # 返回副本，防止调用方无意改动全局
    return dict(w)


def strategy_factors(key=None):
    k = (key or STRATEGY["default"])
    return STRATEGY["factors"].get(k) or STRATEGY["factors"]["trend"]


# ── RS 内部结构（合计 1.0）──
RS_WEIGHTS = {
    "rs3":      0.15,   # 3日市场相对强度：捕捉刚开始加速的股票
    "rs5":      0.20,   # 5日市场相对强度
    "rs20":     0.30,   # 20日市场相对强度
    "rs60":     0.10,   # 60日市场相对强度（降低长期滞后）
    "sector20": 0.15,   # 个股相对所属题材/行业的超额
    "updays5":  0.10,   # 近5日上涨天数
}
# 绝对动量与趋势方向闸门 —— 专门杀"弱市里的抗跌假强股"
# （大盘 20 日 -16%、个股 -4%，RS20 = +12% 横截面排名会很高，
#   但个股本身在跌，绝不能算强势）
RS_GATE = {
    "r20_neg_mult": 0.65,   # 20日绝对收益 < 0 → RS 得分 × 0.65
    "both_neg_mult": 0.50,  # 5日与20日同时 < 0 → × 0.5
    "weak_cap": 35.0,       # 跌破 MA20 且 MA20 斜率向下 → RS 上限 35 分
}

# ── 量价内部结构（合计 1.0）──
PV_WEIGHTS = {
    "vr":         0.35,   # 方向化量能（对 20 日中位数的倍数）
    "vol_trend":  0.20,   # 5/20 日量能趋势
    "turn_pct":   0.20,   # 换手（成交量）历史分位
    "structure":  0.25,   # 缩量回踩 / 放量杀跌结构
}
PV = {
    "vr_healthy_lo": 1.2,   # 上涨时 1.2~2.0 倍视为健康确认
    "vr_healthy_hi": 2.0,
    "vr_extreme": 3.0,      # ≥ 此值不再线性加分，转入拥挤度判断
    "vr_down_bad": 1.5,     # 下跌且量能 > 此值 → 放量杀跌，扣分
    "shrink_max": 0.8,      # 站上 MA20 且量能 < 此值 → 健康缩量回踩，加分
}

# ── 趋势质量内部结构（合计 1.0）──
# 只回答"趋势结构是否完整"，**不再含 60 日价格位置**（那是 RS 的活，
# 放在这里会让同一件事被奖励两次）
TREND_WEIGHTS = {
    "ma_align":  0.40,   # MA5>MA10>MA20>MA60 满足程度
    "slope_atr": 0.35,   # MA20 斜率（ATR20 标准化）
    "ma_stand":  0.25,   # MA20 / MA60 站位
}

# ── 板块强度 / 联动扩散内部结构（合计 1.0）──
SECTOR_WEIGHTS = {
    "excess":      0.35,   # 板块相对全市场超额收益（20日）
    "breadth":     0.25,   # 上涨家数宽度（当日与近3日平均）
    "new_high":    0.20,   # 20日新高股票占比
    "amt_expand":  0.20,   # 板块成交额 MA5/MA20 扩张
}
# 多题材混合：Top1×0.6 + Top2×0.3 + Top3×0.1
# 不能直接取最高分 —— 否则模型永远能为每只股票挑出一个最强的概念，
# "多题材"就变成了无成本的加分项。
SECTOR_BLEND = (0.60, 0.30, 0.10)
SECTOR_MEMBER_MIN = 5      # 成员 < 此值的题材不参与
SECTOR_MEMBER_MAX = 400    # 成员 > 此值的题材没有区分度，不参与

# ── 情绪 / 价格行为内部结构（合计 1.0）──
SENT_WEIGHTS = {
    "limit":    0.30,   # 当日及近5日涨停行为（**边际递减**）
    "clv":      0.30,   # 收盘位置 CLV
    "amp_clv":  0.25,   # 振幅 × CLV（高振幅+高CLV=承接强；高振幅+低CLV=冲高回落）
    "shadow":   0.15,   # 上影线 / 炸板健康度
}
SENT = {
    # 涨停边际递减：首板满分奖励，连板继续确认，但高度越高加分越少，
    # 到第 N 板之后不再加分（加速部分交给拥挤度去扣）
    "limit_step": [1.00, 0.78, 0.42, 0.20, 0.08],
    "limit_step_beyond": 0.0,
    "amp_hi": 6.0,          # 振幅 ≥ 此值算"高振幅"
    "upper_shadow_bad": 3.0,  # 上影线占当日振幅比例 > 此值算长上影
}

# ── 拥挤 / 过热健康度内部结构（合计 1.0）──
# 专门解决趋势模型最典型的失败模式：越涨越买、买在加速末端
CROWD_WEIGHTS = {
    "dist_atr":  0.40,   # (Close-MA20)/ATR20
    "ret5_pct":  0.25,   # 5日涨幅横截面分位
    "turn_pct":  0.20,   # 换手（成交量）120日历史分位
    "dist":      0.15,   # 派发结构（爆量 + 长上影 + 低 CLV）
}
# (Close-MA20)/ATR20 的健康档位。注意不是">5ATR 必跌"，
# 而是"再追进去所承担的风险明显提高"，所以给低分而不是负分。
CROWD_ATR_BANDS = [
    # (区间上限, 健康分)，最后一项为无穷大的兜底
    (-999.0, 25.0),   # 远在 MA20 之下：趋势偏弱，同样不健康
    (0.0,    45.0),   # 刚跌破/贴着 MA20
    (0.5,    75.0),   # 刚进入趋势
    (2.5,   100.0),   # 主要健康区间
    (3.5,    62.0),   # 开始偏热
    (5.0,    32.0),   # 明显过热
    (9e9,    10.0),   # 极端加速
]
CROWD_DIST = {          # 派发结构判定（同时满足多项 → 明显扣分）
    "ret5_pct_top": 95.0,      # 5日涨幅全市场前 5%
    "turn_pct_top": 97.0,      # 换手（量能）120日分位 ≥ 97
    "vol_mult": 2.5,           # 成交量 ≥ 20 日中位数 2.5 倍
    "clv_low": 0.35,           # CLV < 0.35
}

# ── 通用窗口 ──
ATR_WINDOW = 20           # ATR 周期（ATR20）
ATR_SLOPE_LOOKBACK = 5    # MA20 斜率回看天数
TURN_PCT_WINDOW = 120     # 换手/量能历史分位窗口（交易日）

# ═══════════════════════════════════════════════════════
# 三·前置、Risk Gate —— 硬门槛（**不计权重**）
#
# 有些股票不是"差一点"，而是根本不该进候选池。
# 顺序：全A → Risk Gate → 波段五因子 100 分 → 拥挤风险调整 → 排序 → 市场环境决定执行
# ═══════════════════════════════════════════════════════
RISK_GATE = {
    # 核心需要25根；完成日线日期和数据质量在 strength.build 再检查。
    # 这是数据门槛，不将可见K线根数冒充准确的上市交易日数。
    "min_trading_days": 25,
}

# ═══════════════════════════════════════════════════════
# 三·补、选股雷达：只展示趋势在线候选，按个股自身强度分位分档。
# ═══════════════════════════════════════════════════════
RADAR = {
    # A/B/C 是趋势在线股的关注层级，不改动全体强度排名。
    "tiers": [
        {"key": "A", "label": "A · 进攻强势", "short": "达到进攻门槛",
         "desc": "进攻分≥65，5/20日上涨，5日≥5%或10日≥8%或20日≥12%；不限制名额"},
        {"key": "B", "label": "B · 进攻观察", "short": "推进或强股整理",
         "desc": "进攻分≥45且20日上涨，5日≥3%或10日≥5%或20日≥8%，或近20日有5日≥8%的进攻段"},
        {"key": "C", "label": "C · 结构在线", "short": "尚无足够进攻",
         "desc": "均线结构成立，实际涨幅或进攻速度尚未达标"},
    ],
    # 每档在看板里最多列几条（报告里另有各自的条数）
    "show_per_tier": 500,
    # 因子分 ≥ 此值算"强项"，< weak_q 算"短板"
    "strong_q": 72.0,
    "weak_q": 45.0,
    # 定性判断用的"很热"门槛
    "hot_q": 82.0,
    # 单调注释上限：强项最多 3 条、风险最多 3 条（多了没人看）
    "max_notes": 3,
    # 派发结构判定（与拥挤度的派发子项同源）
    "disp_clv": 0.35,
    "disp_vr": 2.5,
}

# ═══════════════════════════════════════════════════════
# 四、板块强度因子权重（合计 1.0）—— **板块榜专用**
#
# 注意：这与个股的 Sector 因子（SECTOR_WEIGHTS）是两套口径。
# 板块榜是"板块之间比强弱"，按用户要求保留东财主力资金作为排序项；
# 个股的 Sector 因子只用四项（不含主力资金）。
# ═══════════════════════════════════════════════════════
BOARD_WEIGHTS = {
    "rs":        0.32,   # 板块多周期涨幅相对强度
    "fund":      0.26,   # 板块主力资金净流入（东财口径）
    "linkage":   0.24,   # 板块内联动（上涨家数占比）
    "momentum":  0.18,   # 板块动能（近5日强于大盘天数）
}

# 板块轮动阶段判定阈值（板块涨幅分位 / 资金流分位）
ROTATION = {
    "leader_rs": 0.75,      # 涨幅分位 ≥ 此值算"强势"
    "leader_fund": 0.70,    # 资金分位 ≥ 此值算"资金流入"
}

# ═══════════════════════════════════════════════════════
# 五、外围市场（隔夜美股与费半）
# ═══════════════════════════════════════════════════════
OUTER = {
    "indices": {
        "usDJI":   {"name": "道琼斯",   "weight": 0.20},
        "usIXIC":  {"name": "纳斯达克", "weight": 0.35},
        "usINX":   {"name": "标普500",  "weight": 0.20},
        "usSOXX":  {"name": "费半ETF",  "weight": 0.25},   # 费城半导体指数替代品
    },
    # 对外围敏感的板块关键词 → 关联外围打分
    "sensitive_keywords": {
        "半导体": 1.0, "芯片": 1.0, "集成电路": 1.0, "存储": 0.9, "光模块": 0.9,
        "算力": 0.9, "AI": 0.85, "人工智能": 0.85, "消费电子": 0.8, "PCB": 0.8,
        "先进封装": 0.9, "液冷": 0.8, "服务器": 0.8, "CPO": 0.9, "铜缆": 0.8,
        "机器人": 0.7, "智能驾驶": 0.7, "苹果": 0.75, "特斯拉": 0.7,
    },
}

# ═══════════════════════════════════════════════════════
# 六、异动告警阈值
# ═══════════════════════════════════════════════════════
ALERT = {
    "board_score_jump": 15,      # 板块强度分较上一次跃升 ≥N 触发
    "stock_score_jump": 20,      # 个股强度分跃升 ≥N
    "volume_surge_ratio": 2.5,   # 累计量/近5日均量 ≥N 且上涨；未完成K不折算全天
    "rs_breakout": 0.90,         # RS 进入全市场前 10%
    "outer_diverge": 1.0,        # 外围与A股方向背离幅度(%)
}

# ═══════════════════════════════════════════════════════
# 七、运行时参数
# ═══════════════════════════════════════════════════════
RUNTIME = {
    "refresh_seconds": 300,      # 盘中每5分钟刷新
    "server_port": 8848,
    "report_time": "15:30",      # 收盘报告时间
    "top_n": 30,                 # 榜单条数
    # 看板内联走势序列的只数（按综合分取前 N）。调大会显著增加 dashboard.html 体积。
    "kline_inline_top": 500,
    # 东财节流（防封）：社区实测东财容忍 5次/秒，这里压到 0.8次/秒，安全余量充足
    "em_min_interval": 1.2,
    "em_max_retry": 3,
}

# ═══════════════════════════════════════════════════════
# 八、东财域名（分域防封）
#
# 实测（2026-09-18）：push2.eastmoney.com 会被风控整段封禁，
# 但 datacenter-web 与 push2delay 是独立域名、独立风控，仍然可用。
# 因此资金流/板块数据走「主域名 → 备用域名」自动切换，
# 任一域名被封都不会打断主流程。
#   push2delay 为延时行情（约15分钟），用于资金流/涨跌家数等累计类数据无影响；
#   个股实时价格始终走腾讯，不受此影响。
# ═══════════════════════════════════════════════════════
EM = {
    "quote_hosts": ["push2.eastmoney.com", "push2delay.eastmoney.com"],
    "data_host": "datacenter-web.eastmoney.com",
    "fund_pages": 25,            # 全市场资金流分页数（200/页 → 覆盖 5000 只）
    "board_pages": 8,
    # 连接中断时只允许短时沿用最近成功结果；超过该窗口回退到价量代理。
    "stale_max_seconds": 15 * 60,
    # quick 扫描按 5 分钟节奏运行时，优先复用最近一次成功的东财结果，
    # 允许最多 15 分钟的增强数据延迟，避免每轮都阻塞在 30+ 页资金流翻页；
    # 过期后仍会自动回源刷新，个股行情/同花顺板块日线仍每轮更新。
    "quick_cache_seconds": 15 * 60,
}

# 涨红跌绿（A股习惯）—— 看板用
COLOR_UP = "#e2452f"
COLOR_DOWN = "#12a45c"
