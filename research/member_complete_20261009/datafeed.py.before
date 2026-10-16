# -*- coding: utf-8 -*-
"""数据层 —— 抓取 / 节流 / 缓存 / 降级

设计原则：
  1. 核心链路（股票池 / K线 / 板块日线 / 外围）零东财依赖，走腾讯+同花顺
  2. 东财只做增强（资金流、板块实时），行业/题材/概念分类全部走同花顺：
     push2 被封时自动切 push2delay，分类链路不调用 datacenter-web
  3. 所有东财请求强制串行节流，带熔断
"""
import hashlib
import html
import io
import json
import math
import random
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ─────────────────────────────────────────────────────
# HTTP 基础设施
# ─────────────────────────────────────────────────────
_EM_LOCK = threading.Lock()
_EM_LAST = [0.0]
_EM_DISABLED = {}       # {接口名: 熔断截止时间戳} —— 按接口隔离，
                        # 避免 push2 域名的失败连带封住 datacenter-web 等独立域名
_EM_HOST_IDX = [0]      # 当前使用的行情域名序号（故障转移游标）

# 数据源健康状态只记录本进程最近一次结果，最终随快照落盘。
# 这样看板能明确区分“实时成功 / 最近成功缓存 / 本轮不可用”，
# 不会把降级后的数字误认为是同一时间点的实时数据。
_SOURCE_HEALTH = {}
_SOURCE_HEALTH_LOCK = threading.Lock()
_AKSHARE_MODULE = None
_AKSHARE_LOCK = threading.Lock()


def _source_mark(name, status, elapsed=None, coverage=None, detail=None,
                 stale=False, fetched_at=None):
    item = {"status": status, "stale": bool(stale),
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    if elapsed is not None:
        item["elapsed_s"] = round(float(elapsed), 2)
    if coverage is not None:
        item["coverage"] = coverage
    if detail:
        item["detail"] = str(detail)[:240]
    if fetched_at:
        item["fetched_at"] = fetched_at
    with _SOURCE_HEALTH_LOCK:
        _SOURCE_HEALTH[name] = item


def source_health_snapshot():
    """返回可直接放进 snapshot 的数据源状态，不暴露线程内部对象。"""
    with _SOURCE_HEALTH_LOCK:
        return {k: dict(v) for k, v in _SOURCE_HEALTH.items()}


def _read_json_file(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cache_age_seconds(blob, path):
    ts = None
    if isinstance(blob, dict):
        ts = blob.get("saved_at") or blob.get("fetched_at")
    try:
        ts = float(ts) if ts is not None else path.stat().st_mtime
    except (TypeError, ValueError, OSError):
        return None
    return max(0.0, time.time() - ts)


def in_trading_session(now=None):
    """是否处于连续竞价时段（09:30-11:30 / 13:00-15:00，周一至周五）

    用于区分「真停牌」和「盘前盘后本来就零成交」——
    不区分会把整个股票池误判为停牌（已踩坑）。
    """
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return (9 * 60 + 30) <= t <= (11 * 60 + 30) or (13 * 60) <= t <= (15 * 60)


def session_label(now=None):
    """当前数据处于哪个阶段 —— 报告需要据此说明数据性质

    盘前行情来自集合竞价（09:15 起），只有部分标的有报价且无成交额，
    和盘中数据不可直接比较，必须标注。
    """
    now = now or datetime.now()
    if now.weekday() >= 5:
        return "非交易日"
    t = now.hour * 60 + now.minute
    if t < 9 * 60 + 15:
        return "盘前"
    if t < 9 * 60 + 25:
        return "集合竞价"
    if t < 9 * 60 + 30:
        return "竞价结束"
    if t <= 11 * 60 + 30:
        return "早盘"
    if t < 13 * 60:
        return "午间休市"
    if t <= 15 * 60:
        return "尾盘" if t >= 14 * 60 + 30 else "午盘"
    return "已收盘"


def http_get(url, headers=None, timeout=20, encoding=None, retry=2):
    """通用 GET，自动尝试 gbk/utf-8 解码"""
    last_err = None
    for attempt in range(retry + 1):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", UA)
            for k, v in (headers or {}).items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            if encoding:
                return raw.decode(encoding, errors="replace")
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("gbk", errors="replace")
        except Exception as e:
            last_err = e
            if attempt < retry:
                time.sleep(0.4 + attempt * 0.6)
    raise last_err


def em_get(url, headers=None, timeout=20):
    """东财专用入口：串行节流 + 正常 UA/Referer。

    东财风控：每秒>5次 / 1分钟>200次 会被临时封 IP。
    这里强制串行 + 最小间隔，并对连续失败做熔断（见 em_guard）。
    注意：熔断不在此处判断——它按接口隔离在 em_guard 里。
    """
    with _EM_LOCK:
        wait = config.RUNTIME["em_min_interval"] - (time.time() - _EM_LAST[0])
        if wait > 0:
            time.sleep(wait + random.uniform(0.15, 0.45))
        try:
            hdr = {"Referer": "https://quote.eastmoney.com/",
                   "Accept": "*/*",
                   "Accept-Language": "zh-CN,zh;q=0.9"}
            hdr.update(headers or {})
            return http_get(url, headers=hdr, timeout=timeout, retry=1)
        finally:
            _EM_LAST[0] = time.time()


def em_host_url(path, idx=None):
    """按当前域名游标拼东财行情 URL"""
    hosts = config.EM["quote_hosts"]
    i = _EM_HOST_IDX[0] if idx is None else idx
    i = max(0, min(i, len(hosts) - 1))
    return f"https://{hosts[i]}{path}"


def em_get_failover(path, headers=None, params=None, timeout=20):
    """东财行情接口 —— 域名级故障转移。

    push2 被风控整段封禁时，自动切到 push2delay（独立域名/独立风控）。
    切换后游标保持，避免每次请求都撞一次已封的域名。
    """
    hosts = config.EM["quote_hosts"]
    start = _EM_HOST_IDX[0]
    last_err = None
    for step in range(len(hosts)):
        i = (start + step) % len(hosts)
        url = f"https://{hosts[i]}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        try:
            txt = em_get(url, headers=headers, timeout=timeout)
            if i != start:
                _EM_HOST_IDX[0] = i
                print(f"[EM] 行情域名切换 -> {hosts[i]}")
            return txt
        except Exception as e:
            last_err = e
    raise last_err


def em_guard(fn):
    """东财调用包装：按接口隔离的熔断。

    熔断按「接口名」记账，不共享状态——这样 push2 域名的失败不会连带
    封住 datacenter-web 等独立域名（它们风控独立，实测一个挂另一个照常可用）。
    """
    name = fn.__name__

    def wrapper(*a, **kw):
        until = _EM_DISABLED.get(name, 0.0)
        if time.time() < until:
            raise RuntimeError(f"EM_CIRCUIT_OPEN: {name} 熔断中")
        try:
            res = fn(*a, **kw)
            _EM_DISABLED.pop(name, None)
            return res
        except Exception as e:
            if isinstance(e, RuntimeError) and "EM_CIRCUIT_OPEN" in str(e):
                raise
            _EM_DISABLED[name] = time.time() + 600
            print(f"[WARN] {name} 熔断 10 分钟，该接口自动降级：{type(e).__name__}")
            raise
    return wrapper


def em_status():
    now = time.time()
    live = {k: int(v - now) for k, v in _EM_DISABLED.items() if v > now}
    if not live:
        return "可用"
    return "熔断中: " + ", ".join(f"{k}({v}s)" for k, v in live.items())


# ─────────────────────────────────────────────────────
# 1. 股票池：扫描沪深主板代码空间（零东财依赖）
# ─────────────────────────────────────────────────────
_SZ_RANGES = [(1, 4000),                    # 000001-003999  深主板(000/001/002/003)
              (300000, 302000)]             # 300000-301999  创业板(300/301)
_SH_RANGES = [(600000, 606000),             # 600000-605999  沪主板(600/601/603/605)
              (688000, 690000)]             # 688000-689999  科创板(688/689)


def _board_ranges():
    """按 config.POOL["boards"] 生成候选代码区间。

    板别口径的**唯一真源是 config.BOARDS 的 prefix** —— 这里不再硬编码
    600/000/300/688 的区间。以前是两处各写一份：`POOL["em_fs"]` 与
    `_SZ_RANGES/_SH_RANGES`，扩板/收板时漏改一处就会出现
    "池子里有票但拉不到行情"或"扫了一堆不在口径里的代码"。
    """
    spans = []
    for key in config.pool_boards():
        for p in config.BOARDS[key]["prefix"]:
            lo = int(p) * 1000
            spans.append((lo, lo + 1000))
    spans.sort()
    merged = []
    for lo, hi in spans:                      # 合并相邻区间，减少扫描批次
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(a, b) for a, b in merged]


def _gen_candidate_codes():
    codes = []
    for lo, hi in _board_ranges():
        codes += [f"{i:06d}" for i in range(lo, hi)]
    return codes


def _tencent_prefix(code):
    return "sh" if code.startswith(("6", "9")) else ("bj" if code.startswith("8") else "sz")


def _pool_fingerprint():
    """股票池口径指纹。板别/剔除规则一变，池缓存立刻失效重建。

    没有这层保护时的症状：把板别从四板收回主板后，pool.json 里还留着
    创业板/科创板的票，界面继续列出来 —— 用户会以为"改了配置没用"。
    """
    raw = json.dumps({
        "boards": sorted(config.pool_boards()),
        "ex": sorted(config.POOL["exclude_keywords"]),
        "halt": bool(config.POOL["exclude_halted"]),
        "halt_amt": bool(config.POOL["halt_use_amount_check"]),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def tencent_quotes(codes):
    """腾讯批量行情。codes 建议 <=400/批。不封 IP。"""
    t0 = time.time()
    out = {}
    failed = 0
    for i in range(0, len(codes), 400):
        batch = codes[i:i + 400]
        url = "https://qt.gtimg.cn/q=" + ",".join(_tencent_prefix(c) + c for c in batch)
        try:
            txt = http_get(url, encoding="gbk")
        except Exception as e:
            failed += 1
            print(f"[WARN] 腾讯行情批次失败: {e}")
            continue
        for line in txt.strip().split(";"):
            if '"' not in line or "~" not in line:
                continue
            key = line.split("=")[0].split("_")[-1]
            vals = line.split('"')[1].split("~")
            if len(vals) < 53:
                continue
            out[key[2:]] = _parse_tencent_quote(vals)
        time.sleep(0.05)
    _source_mark("tencent_quotes", "ok" if out else "error",
                 elapsed=time.time() - t0,
                 coverage=f"{len(out)}/{len(codes)}",
                 detail=(f"failed_batches={failed}" if failed else None))
    return out


def _akshare_module():
    """懒加载 AkShare，避免正常刷新为一个备用源支付导入成本。

    AkShare 只在腾讯行情出现明显缺口时启用。这样即使用户没有安装可选
    依赖，主链路也仍然完全可用；安装后则自动获得新浪全市场批量补齐。
    """
    global _AKSHARE_MODULE
    if _AKSHARE_MODULE is False:
        return None
    if _AKSHARE_MODULE is not None:
        return _AKSHARE_MODULE
    with _AKSHARE_LOCK:
        if _AKSHARE_MODULE is not None:
            return None if _AKSHARE_MODULE is False else _AKSHARE_MODULE
        try:
            import akshare as ak
            _AKSHARE_MODULE = ak
        except Exception as e:
            _AKSHARE_MODULE = False
            _source_mark("akshare_sina_quotes", "unavailable", detail=e)
            return None
    return _AKSHARE_MODULE


def _ak_code(value):
    """把 AkShare/Sina 的 sh600000、sz000001 等代码统一成六位数字。"""
    m = re.search(r"(\d{6})", str(value or ""))
    return m.group(1) if m else ""


def _ak_float(value, default=0.0):
    try:
        if value is None or value == "" or value == "-":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_akshare_cache(max_age=None):
    p = config.AKSHARE_SPOT_CACHE
    blob = _read_json_file(p) if p.exists() else None
    if not isinstance(blob, dict) or not isinstance(blob.get("rows"), dict):
        return {}, None, None
    age = _cache_age_seconds(blob, p)
    if age is None or (max_age is not None and age > max_age):
        return {}, age, blob
    return blob.get("rows") or {}, age, blob


def fetch_akshare_sina_quotes(codes=None, force=False):
    """按需获取/读取 AkShare 新浪全市场行情备用。

    ``stock_zh_a_spot`` 是分页接口，实测全市场一次约几十秒，因此结果
    必须缓存，且只在主行情缺口时调用。返回字段对齐 tencent_quotes，
    其中新浪成交量是「股」、成交额是「元」，在这里统一成系统的「手/万元」。
    """
    wanted = {_ak_code(c) for c in (codes or []) if _ak_code(c)}
    t0 = time.time()
    ttl = float(getattr(config, "AKSHARE_SPOT_TTL_SECONDS", 300))
    if not force:
        cached, age, blob = _load_akshare_cache(ttl)
        if cached:
            out = {c: dict(v) for c, v in cached.items()
                   if not wanted or c in wanted}
            cache_complete = (not wanted or len(out) >= max(1, int(len(wanted) * 0.95)))
            if out and cache_complete:
                _source_mark("akshare_sina_quotes", "cache", elapsed=time.time() - t0,
                             coverage=f"{len(out)}/{len(wanted) or len(cached)}",
                             detail=f"age={age:.0f}s", stale=True,
                             fetched_at=(blob or {}).get("fetched_at"))
                return out

    ak = _akshare_module()
    if ak is None:
        return {}
    try:
        # AkShare 默认 tqdm 会把 70 页进度刷到服务日志；这里保留错误输出，
        # 抑制正常进度条，避免 pythonw 日志被大段重复文本淹没。
        quiet = io.StringIO()
        with redirect_stdout(quiet), redirect_stderr(quiet):
            raw = ak.stock_zh_a_spot()
        out = {}
        for row in raw.itertuples(index=False, name=None):
            if len(row) < 13:
                continue
            code = _ak_code(row[0])
            if not code:
                continue
            price = _ak_float(row[2])
            last_close = _ak_float(row[7])
            volume_share = _ak_float(row[11])
            amount_yuan = _ak_float(row[12])
            out[code] = {
                "name": str(row[1] or "").strip(),
                "price": price,
                "last_close": last_close,
                # A股现货昨收按人民币分显示；精度用于raw/raw同尺度昨收容差核验。
                "last_close_precision_digits": 2,
                "price_basis": "raw",
                "price_basis_source": "akshare_sina_spot",
                "last_close_semantics": "previous_trade_day_raw_close",
                "open": _ak_float(row[8]),
                "change_pct": _ak_float(row[4]),
                "ts": str(row[13] or "") if len(row) > 13 else "",
                "high": _ak_float(row[9]),
                "low": _ak_float(row[10]),
                "volume_shou": volume_share / 100.0,
                "amount_wan": amount_yuan / 10000.0,
                # 新浪 spot 当前返回列不含换手/市值；合并时保留腾讯已有值。
                "turnover_pct": 0.0,
                "pe_ttm": 0.0,
                "amplitude_pct": 0.0,
                "float_mcap_yi": 0.0,
                "mcap_yi": 0.0,
                "pb": 0.0,
                "limit_up": 0.0,
                "limit_down": 0.0,
                "vol_ratio": 0.0,
            }
        if not out:
            raise RuntimeError("AkShare 新浪行情返回空数据")
        all_rows = out
        # 请求通常是全市场，写入全量结果；若未来接口只返回 wanted，也不破坏
        # 已有缓存，避免一次短暂缺口把备用库覆盖成小子集。
        cached, _, _ = _load_akshare_cache(None)
        if len(cached) > len(all_rows):
            cached.update(all_rows)
            all_rows = cached
        config.atomic_write_text(config.AKSHARE_SPOT_CACHE, json.dumps({
            "saved_at": time.time(),
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rows": all_rows,
        }, ensure_ascii=False, separators=(",", ":")))
        selected = {c: dict(v) for c, v in all_rows.items()
                    if not wanted or c in wanted}
        _source_mark("akshare_sina_quotes", "ok", elapsed=time.time() - t0,
                     coverage=f"{len(selected)}/{len(wanted) or len(all_rows)}")
        print(f"[AK] 新浪备用行情 {len(selected)} 只，耗时 {time.time()-t0:.1f}s")
        return selected
    except Exception as e:
        _source_mark("akshare_sina_quotes", "error", elapsed=time.time() - t0,
                     detail=f"{type(e).__name__}: {e}")
        print(f"[WARN] AkShare 新浪备用行情失败：{type(e).__name__}: {e}")
        return {}


def realtime_quotes(codes):
    """主行情 + AkShare 按需补齐，正常情况下只走腾讯快速批量接口。"""
    codes = list(codes or [])
    out = tencent_quotes(codes)
    expected = {str(c) for c in codes}
    missing = expected - set(out)
    invalid = {c for c, q in out.items() if _ak_float(q.get("price")) <= 0}
    # 早盘全市场成交额本来可能为 0，不以 amount 触发 35 秒备用请求；
    # 只对覆盖率/价格字段的真实缺口启用 AkShare。
    if len(out) < max(1, int(len(expected) * 0.98)) or invalid:
        akq = fetch_akshare_sina_quotes(codes)
        for c, q in akq.items():
            if c not in out or c in invalid:
                out[c] = q
        detail = f"腾讯缺失 {len(missing)}、无效 {len(invalid)}；AkShare 补回 {len(akq)}"
        _source_mark("realtime_quotes", "ok" if out else "error",
                     coverage=f"{len(out)}/{len(expected)}", detail=detail)
    else:
        _source_mark("realtime_quotes", "ok", coverage=f"{len(out)}/{len(expected)}",
                     detail="腾讯覆盖充足，未调用备用源")
    return out


def _f(vals, i, default=0.0):
    try:
        s = vals[i]
        return float(s) if s not in ("", "-", None) else default
    except (ValueError, IndexError):
        return default


def _parse_tencent_quote(vals):
    return {
        "name": vals[1],
        "price": _f(vals, 3),
        "last_close": _f(vals, 4),
        # 腾讯逐股报价接口的A股昨收字段保留到分。
        "last_close_precision_digits": 2,
        "price_basis": "raw",
        "price_basis_source": "tencent_realtime_quote",
        "last_close_semantics": "previous_trade_day_raw_close",
        "open": _f(vals, 5),
        "change_pct": _f(vals, 32),
        "ts": vals[30] if len(vals) > 30 else "",
        "high": _f(vals, 33),
        "low": _f(vals, 34),
        "volume_shou": _f(vals, 36),
        "amount_wan": _f(vals, 37),
        "turnover_pct": _f(vals, 38),
        "pe_ttm": _f(vals, 39),
        "amplitude_pct": _f(vals, 43),
        # 市值字段语义（2026-09-18 用东财 f117/f116 双源校验确认）：
        #   [44] = 流通市值     [45] = 总市值
        # 此前两者写反，导致资金流强度分母用了总市值——对 A+H 股与次新股
        # 误差极大（比亚迪流通 2920 亿 vs 总 7635 亿，差 2.6 倍）
        "float_mcap_yi": _f(vals, 44),
        "mcap_yi": _f(vals, 45),
        "pb": _f(vals, 46),
        "limit_up": _f(vals, 47),
        "limit_down": _f(vals, 48),
        "vol_ratio": _f(vals, 49),
    }


@em_guard
def fetch_list_dates(pz=100, max_page=60):
    """全市场上市日期（东财 clist 字段 f26，格式 YYYYMMDD）。

    用于剔除次新股 —— 上市不满 N 个自然日的个股换手/波动结构尚未稳定，
    且常因解禁、炒新资金留下异常 K 线，会污染强度信号。
    同样走 _em_clist_all 按 total 翻页，避免静默截断（曾只覆盖 2500/3487）。
    """
    rows, total = _em_clist_all(config.POOL["em_fs"], "f12,f14,f26",
                                sort_field="f12", pz=pz, max_page=max_page)
    out = {}
    for i in rows:
        c, dt = i.get("f12"), i.get("f26")
        if c and dt:
            out[c] = str(dt)
    print(f"[POOL] 上市日期覆盖 {len(out)}/{total or '?'} 只")
    return out


def load_list_dates(force=False):
    """上市日期缓存（24 小时有效）。取不到时返回空 dict → 上层自动跳过过滤。"""
    p = config.CACHE_DIR / "list_dates.json"
    if not force and p.exists() and (time.time() - p.stat().st_mtime) < 24 * 3600:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d:
                return d
        except Exception:
            pass
    try:
        d = fetch_list_dates()
    except Exception as e:
        print(f"[POOL] 上市日期获取失败，本次跳过次新股过滤：{type(e).__name__}")
        return {}
    if d:
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


def build_pool(force=False):
    """构建并缓存股票池；无成交股票保留代码，供后续扫描核验恢复交易。

    每只个股带上板别标记：
      board_type / board_name / limit_pct → 分板涨停判定与界面标注
      list_days / is_new                  → 次新标记（Risk Gate 已把次新挡在池外）
    """
    fp = _pool_fingerprint()
    meta = {}
    if config.POOL_META_CACHE.exists():
        try:
            meta = json.loads(config.POOL_META_CACHE.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    if not force and config.POOL_CACHE.exists():
        age = time.time() - config.POOL_CACHE.stat().st_mtime
        if age < 6 * 3600:
            if meta.get("fp") != fp:
                print(f"[POOL] 池口径已变更（板别 → {'/'.join(config.pool_board_names())}），"
                      f"重建股票池 ...")
            else:
                cached = json.loads(config.POOL_CACHE.read_text(encoding="utf-8"))
                # 老缓存没有板别字段（扩容前生成的），直接重建，否则前端会一片"未知"
                if cached and all("board_name" in v for v in cached.values()):
                    return cached
                print("[POOL] 缓存缺少板别字段，重建股票池 ...")

    print(f"[POOL] 扫描 {'/'.join(config.pool_board_names())} 代码空间 ...")
    t0 = time.time()
    cands = _gen_candidate_codes()
    quotes = realtime_quotes(cands)
    print(f"[POOL] 命中 {len(quotes)} 只有效代码，耗时 {time.time()-t0:.1f}s")

    kept, dropped = {}, {"st": 0, "halt_observed": 0, "nolist": 0, "new": 0, "old_board": 0}
    in_session = in_trading_session()
    for code, q in quotes.items():
        nm = q["name"] or ""
        if any(k in nm for k in config.POOL["exclude_keywords"]):
            dropped["st"] += 1
            continue
        if config.POOL["exclude_halted"]:
            # 无成交只阻止进入可交易候选；保留代码，才能在复牌时持续取得新报价。
            # 单凭报价不能区分法定停牌、行情缺失和暂时无成交。
            inactive = q["price"] <= 0
            if (not inactive and config.POOL["halt_use_amount_check"] and in_session
                    and q["amount_wan"] <= 0 and q["volume_shou"] <= 0):
                inactive = True
            if inactive:
                dropped["halt_observed"] += 1
        kept[code] = q

    # ── 板别 + 次新标记 ──
    # 次新股不再剔除（口径扩容），但必须标记出来：界面上打「次新」徽标，
    # 且新股无涨跌幅限制期间不判涨停（否则首日翻倍会被记成 20 连板）。
    ldate = load_list_dates()
    if not ldate:
        print("[POOL] 无上市日期数据，本次次新标记为空（不影响主流程）")
    today = datetime.now()
    new_days = config.POOL.get("new_stock_days") or 60
    board_cnt = {}
    for code, q in kept.items():
        bkey, bname, lim = config.board_of(code)
        ld = ldate.get(code)
        days = None
        if ld:
            try:
                days = (today - datetime.strptime(ld, "%Y%m%d")).days
            except Exception:
                days = None
        q["board_type"] = bkey
        q["board_name"] = bname
        q["limit_pct"] = lim
        q["list_days"] = days
        q["is_new"] = 1 if (days is not None and days < new_days) else 0
        board_cnt[bname] = board_cnt.get(bname, 0) + 1

    if not kept:
        # 防御：绝不允许把空池写进缓存，否则会连锁污染后续所有运行
        if config.POOL_CACHE.exists():
            print("[ERROR] 本次扫描结果为空，已保留原缓存，请检查网络或过滤规则")
            return json.loads(config.POOL_CACHE.read_text(encoding="utf-8"))
        raise RuntimeError("股票池扫描结果为空且无可用缓存")

    config.POOL_CACHE.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
    try:
        config.POOL_META_CACHE.write_text(json.dumps({
            "fp": fp, "boards": config.pool_boards(),
            "board_names": config.pool_board_names(),
            "count": len(kept), "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        print(f"[WARN] 池口径指纹写入失败（下次仍会重建）：{e}")
    comp = "、".join(f"{k}{v}" for k, v in sorted(board_cnt.items(), key=lambda kv: -kv[1]))
    print(f"[POOL] 过滤后 {len(kept)} 只（剔除ST/退市{dropped['st']}，"
          f"待核验无成交{dropped['halt_observed']}只仍保留代码）")
    print(f"[POOL] 板别构成：{comp}｜其中次新 {sum(1 for q in kept.values() if q['is_new'])} 只")
    return kept


# ─────────────────────────────────────────────────────
# 2. 个股K线（腾讯，不封IP）
# ─────────────────────────────────────────────────────
# 前复权K线主机的粘性指针：某个主机失败后切到下一个并记住，
# 避免每条请求都把三个主机各试一遍（5000 只 × 3 次 = 白等几百秒）。
_KLINE_HOST_IDX = 0
_KLINE_HOST_LOCK = threading.Lock()


def fetch_kline(code, days=None):
    """前复权日K。返回按日期升序的 list[dict]

    带**主机级故障转移**：腾讯的 K 线主机和东财一样会按域名封禁。
    2026-09-20 实测 web.ifzq.gtimg.cn 返回 501，而 proxy.finance.qq.com
    上的同路径接口正常 —— 当时因为没有备用主机，5092 只只抓成功一半。
    """
    global _KLINE_HOST_IDX
    days = days or config.KLINE["days"]
    pfx = _tencent_prefix(code)
    hosts = config.KLINE.get("hosts") or []
    if not hosts:
        raise RuntimeError("config.KLINE['hosts'] 为空")
    # 先试上次成功的那个
    order = sorted(range(len(hosts)), key=lambda i: i != _KLINE_HOST_IDX)
    last_err = None
    for i in order:
        url = f"{hosts[i]}?param={pfx}{code},day,,,{days},qfq"
        try:
            d = json.loads(http_get(url))
        except Exception as e:
            last_err = e
            continue
        node = (d.get("data") or {}).get(pfx + code) or {}
        qfq_rows = node.get("qfqday") or []
        raw_rows = node.get("day") or []
        rows = qfq_rows or raw_rows
        if not rows:
            # 该股本身无数据（长期停牌/退市），不是主机问题 —— 不要因此切换主机
            return []
        if i != _KLINE_HOST_IDX:
            with _KLINE_HOST_LOCK:
                if i != _KLINE_HOST_IDX:
                    _KLINE_HOST_IDX = i
                    print(f"[KLINE] 主机故障转移 -> {url.split('/')[2]}"
                          f"（{hosts[0].split('/')[2]} 不可用：{last_err}）")
        price_basis = "qfq" if qfq_rows else "raw"
        price_basis_source = "tencent_qfqday" if qfq_rows else "tencent_day"
        out = []
        for r in rows:
            if len(r) < 6:
                continue
            try:
                # 腾讯在除权除息日把第7项换成分红元数据 dict；那不是成交额，
                # 但前6项仍是完整有效的价量K线，不能因此丢掉整个交易日。
                try:
                    amount = float(r[6]) if len(r) > 6 and r[6] else 0.0
                except (ValueError, TypeError):
                    amount = 0.0
                out.append({
                    "date": r[0],
                    "open": float(r[1]),
                    "close": float(r[2]),
                    "high": float(r[3]),
                    "low": float(r[4]),
                    # 归一化为「股」：腾讯对不同板块用不同单位（见 config.VOLUME_UNIT）
                    "volume": float(r[5]) * config.volume_to_shares(code),
                    "amount": amount,
                    "price_basis": price_basis,
                    "price_basis_source": price_basis_source,
                    # 日K价格为人民币元，A股价格精度为分；同时保留来源精度元数据。
                    "close_precision_digits": 2,
                })
            except (ValueError, TypeError):
                continue
        return out
    raise last_err if last_err else RuntimeError("所有K线主机均不可用")


def fetch_klines_bulk(codes, workers=None, progress=True, days=None):
    """并发拉取K线。腾讯不封IP，可安全并发。

    带整批硬超时（config.KLINE["deadline_seconds"]）：腾讯侧一旦限流，
    单条最多要等 20s×2 次重试，3114 只 × 10 线程能把日更任务拖成"看上去卡死"。
    到点收工，已拿到的照常入库，没拿到的用库里旧数据，并在日志里说清楚少了多少。

    返回 (result, truncated)。**truncated=True 时调用方绝对不能把没拿到的标的
    写进"无历史数据黑名单"** —— 那只是这次请求超时，不是真的没有K线；
    写进去就等于永久拉黑几千只股票（踩过这个坑）。
    """
    workers = workers or config.KLINE["workers"]
    deadline = config.KLINE.get("deadline_seconds", 420)
    result, done = {}, [0]
    total = len(codes)
    t0 = time.time()

    def work(c):
        try:
            return c, fetch_kline(c, days=days)
        except Exception:
            return c, []

    truncated = False
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, c) for c in codes]
        try:
            for f in as_completed(futs, timeout=deadline):
                c, k = f.result()
                if k:
                    result[c] = k
                done[0] += 1
                if progress and done[0] % 500 == 0:
                    print(f"  [KLINE] {done[0]}/{total}")
        except TimeoutError:
            truncated = True
            for f in futs:
                f.cancel()
    if truncated:
        print(f"[WARN] K线抓取超时（>{deadline}s）：已取 {done[0]}/{total} 只，"
              f"其余沿用库内旧数据（涨幅与评分仍可用，日线可能少最后一根）")
    return result, truncated


# ─────────────────────────────────────────────────────
# 3. 同花顺概念板块（日线，零鉴权）
# ─────────────────────────────────────────────────────
def _ths_board_kline_raw(idx_code):
    """同花顺板块日线原始返回"""
    url = f"http://d.10jqka.com.cn/v6/line/bk_{idx_code}/01/last.js"
    txt = http_get(url, headers={"Referer": "http://q.10jqka.com.cn/"}, encoding="gbk")
    m = re.search(r"\((.*)\)\s*;?\s*$", txt.strip(), re.S)
    if not m:
        return None
    return json.loads(m.group(1))


def fetch_ths_board_kline(idx_code):
    """同花顺板块日线 → list[dict]（含中文板块名）"""
    obj = _ths_board_kline_raw(idx_code)
    if not obj:
        return None, []
    name = obj.get("name") or ""
    rows = []
    for item in (obj.get("data") or "").split(";"):
        p = item.split(",")
        if len(p) < 7 or not p[0].strip():
            continue
        d = p[0].strip()
        # 同花顺为 YYYYMMDD，统一成 YYYY-MM-DD
        if len(d) == 8 and d.isdigit():
            d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        try:
            rows.append({
                "date": d,
                "open": float(p[1]),
                "close": float(p[4]),
                "high": float(p[2]),
                "low": float(p[3]),
                "volume": float(p[5]) if p[5] else 0.0,
                "amount": float(p[6]) if p[6] else 0.0,
            })
        except (ValueError, IndexError):
            continue
    return name, rows


def _parse_ths_concept_catalog(txt):
    """解析同花顺概念目录页。

    目录链接是网页详情号（300xxx/308xxx/309xxx），而看板日线接口使用
    885xxx 板块号。同花顺页面把两者的映射放在 gnSection 隐藏 JSON 中，
    能一次拿到当前活跃板块，不必为每个概念再请求一页详情。
    """
    pairs = re.findall(
        r'href="[^\"]*/gn/detail/code/(\d+)/[^\"]*"[^>]*>([^<]{2,40})</a>',
        txt, re.I)
    detail = {str(cid): html.unescape(nm).strip() for cid, nm in pairs
              if html.unescape(nm).strip()}
    index = {}
    # value 通常使用单引号包住 JSON（JSON 内部有大量双引号），
    # 不能用“排除单双引号”的通用写法，否则只会截到第一个键名。
    m = re.search(r'id=["\']gnSection["\'][^>]*value=["\']([^\']+)["\']', txt, re.I)
    if not m:
        m = re.search(r'id=["\']gnSection["\'][^>]*value="([^"]+)"', txt, re.I)
    if m:
        try:
            blob = json.loads(html.unescape(m.group(1)))
            for item in (blob or {}).values():
                if not isinstance(item, dict):
                    continue
                plate = str(item.get("platecode") or "").strip()
                name = html.unescape(str(item.get("platename") or "")).strip()
                if plate and name:
                    index[plate] = {"name": name, "detail_code": str(item.get("cid") or "")}
        except (TypeError, ValueError, json.JSONDecodeError):
            # 目录名仍然可用；旧 boards.json 会承担 885xxx 映射的兜底。
            index = {}
    return {"detail": detail, "index": index,
            "names": sorted(set(detail.values()) | {v["name"] for v in index.values()}),
            "source": "同花顺概念目录"}


def _parse_ths_industry_catalog(txt):
    """解析同花顺行业（thshy）目录页。

    同花顺把“概念”和“行业”放在两个独立目录：``gn`` 页面没有
    “化学制药”，而 ``thshy`` 页面提供 ``881140 -> 化学制药`` 及其
    分页成分名单。这里保持和概念目录相同的数据形状，方便后续统一处理。
    """
    pairs = re.findall(
        r'href="[^"]*/thshy/detail/code/(\d+)/[^"]*"[^>]*>([^<]{2,40})</a>',
        txt, re.I)
    detail = {str(cid): html.unescape(nm).strip() for cid, nm in pairs
              if html.unescape(nm).strip()}
    return {"detail": detail, "index": {}, "names": sorted(set(detail.values())),
            "source": "同花顺行业目录"}


def fetch_ths_concept_catalog(force=False):
    """同花顺概念目录 → 名称、网页详情号与 885xxx 板块号。

    这是概念口径的主源。正常扫描只读本地版本；明确手动更新时才访问网页。
    手动更新失败时保留最近一次成功目录。
    """
    p = config.THS_CONCEPT_CACHE
    # 分类目录只在用户明确要求时更新；日常行情刷新使用已有版本。
    if not force and p.exists():
        blob = _read_json_file(p)
        age = _cache_age_seconds(blob, p)
        if isinstance(blob, dict) and blob.get("detail"):
            _source_mark("ths_concepts", "cache", coverage=len(blob.get("detail") or {}),
                         detail=f"manual_refresh_only; age={age:.0f}s" if age is not None else "manual_refresh_only",
                         stale=False,
                         fetched_at=blob.get("fetched_at"))
            return blob
        raise RuntimeError("同花顺概念目录缓存不可用；请手动刷新分类")
    if not force:
        raise RuntimeError("尚无同花顺概念目录缓存；请手动刷新分类")

    t0 = time.time()
    try:
        txt = http_get("https://q.10jqka.com.cn/gn/",
                       headers={"Referer": "http://www.10jqka.com.cn/"}, encoding="gbk")
        parsed = _parse_ths_concept_catalog(txt)
        if len(parsed["detail"]) < 100:
            raise RuntimeError(f"同花顺概念目录异常：仅解析到 {len(parsed['detail'])} 个概念")
        parsed.update({"fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "saved_at": time.time(),
                       "elapsed_s": round(time.time() - t0, 2)})
        config.atomic_write_text(p, json.dumps(parsed, ensure_ascii=False))
        _source_mark("ths_concepts", "ok", elapsed=time.time() - t0,
                     coverage=len(parsed["detail"]), fetched_at=parsed["fetched_at"])
        return parsed
    except Exception as e:
        blob = _read_json_file(p) if p.exists() else None
        if isinstance(blob, dict) and blob.get("detail"):
            age = _cache_age_seconds(blob, p)
            _source_mark("ths_concepts", "stale_cache", elapsed=time.time() - t0,
                         coverage=len(blob.get("detail") or {}), detail=f"age={age:.0f}s; {e}",
                         stale=True, fetched_at=blob.get("fetched_at"))
            print(f"[WARN] 同花顺概念目录不可用，沿用上次目录（{age/3600:.1f}h）：{e}")
            return blob
        _source_mark("ths_concepts", "error", elapsed=time.time() - t0, detail=e)
        raise


def fetch_ths_concept_names():
    """同花顺概念列表页 → {concept_id: name}（兼容旧调用）"""
    return fetch_ths_concept_catalog().get("detail") or {}


def fetch_ths_industry_catalog(force=False):
    """同花顺行业目录 -> 行业详情号。

    这是“归属行业”口径的主源，和 ``fetch_ths_concept_catalog`` 分开缓存，
    避免把行业误混进题材板块指数。仅在用户明确要求时更新。
    """
    p = config.THS_INDUSTRY_CACHE
    if not force and p.exists():
        blob = _read_json_file(p)
        age = _cache_age_seconds(blob, p)
        if isinstance(blob, dict) and blob.get("detail"):
            _source_mark("ths_industries", "cache", coverage=len(blob.get("detail") or {}),
                         detail=f"manual_refresh_only; age={age:.0f}s" if age is not None else "manual_refresh_only",
                         stale=False,
                         fetched_at=blob.get("fetched_at"))
            return blob
        raise RuntimeError("同花顺行业目录缓存不可用；请手动刷新分类")
    if not force:
        raise RuntimeError("尚无同花顺行业目录缓存；请手动刷新分类")

    t0 = time.time()
    try:
        txt = http_get("https://q.10jqka.com.cn/thshy/",
                       headers={"Referer": "http://www.10jqka.com.cn/"}, encoding="gbk")
        parsed = _parse_ths_industry_catalog(txt)
        if len(parsed["detail"]) < 30:
            raise RuntimeError(f"同花顺行业目录异常：仅解析到 {len(parsed['detail'])} 个行业")
        parsed.update({"fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "saved_at": time.time(),
                       "elapsed_s": round(time.time() - t0, 2)})
        config.atomic_write_text(p, json.dumps(parsed, ensure_ascii=False))
        _source_mark("ths_industries", "ok", elapsed=time.time() - t0,
                     coverage=len(parsed["detail"]), fetched_at=parsed["fetched_at"])
        return parsed
    except Exception as e:
        blob = _read_json_file(p) if p.exists() else None
        if isinstance(blob, dict) and blob.get("detail"):
            age = _cache_age_seconds(blob, p)
            _source_mark("ths_industries", "stale_cache", elapsed=time.time() - t0,
                         coverage=len(blob.get("detail") or {}), detail=f"age={age:.0f}s; {e}",
                         stale=True, fetched_at=blob.get("fetched_at"))
            print(f"[WARN] 同花顺行业目录不可用，沿用上次目录（{age/3600:.1f}h）：{e}")
            return blob
        _source_mark("ths_industries", "error", elapsed=time.time() - t0, detail=e)
        raise


def scan_ths_boards(force=False, lo=885000, hi=887000, workers=8):
    """扫描同花顺概念指数段，自建 {idx_code: name} 映射（响应自带 name，无需爬详情页）"""
    catalog = None
    try:
        catalog = fetch_ths_concept_catalog()
    except Exception as e:
        print(f"[WARN] 同花顺概念目录暂不可用，使用板块日线缓存：{e}")
    if not force and config.BOARD_CACHE.exists():
        raw_cached = _read_json_file(config.BOARD_CACHE) or {}
        if raw_cached:
            cached = dict(raw_cached)
            allowed = set((catalog or {}).get("names") or [])
            if allowed:
                # 同花顺目录是名称主口径：剔除旧扫描里已下线的少量板块，
                # 但保留目录页当前列出的全部概念。
                cached = {str(idx): name for idx, name in cached.items()
                          if name in allowed}
            # 目录页内的 885xxx 映射优先覆盖旧名字；其余旧索引保留，
            # 这样既跟随同花顺当前命名，又不因目录暂时只展示活跃板块而丢历史板。
            for idx, item in (catalog or {}).get("index", {}).items():
                cached[str(idx)] = item.get("name") or cached.get(str(idx))
            if cached != raw_cached:
                config.atomic_write_text(config.BOARD_CACHE,
                                         json.dumps(cached, ensure_ascii=False))
            return cached
        raise RuntimeError("同花顺概念指数映射缓存不可用；请手动刷新分类")
    if not force:
        raise RuntimeError("尚无同花顺概念指数映射缓存；请手动刷新分类")

    codes = [str(i) for i in range(lo, hi)]
    print(f"[BOARD] 扫描同花顺概念指数 {lo}-{hi} ...")
    found, done = {}, [0]

    def work(c):
        try:
            obj = _ths_board_kline_raw(c)
            if obj and obj.get("name") and obj.get("data"):
                return c, obj["name"]
        except Exception:
            pass
        return c, None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, c) for c in codes]
        for f in as_completed(futs):
            c, nm = f.result()
            if nm:
                found[c] = nm
            done[0] += 1
            if done[0] % 500 == 0:
                print(f"  [BOARD] {done[0]}/{len(codes)}  命中 {len(found)}")

    if not found and config.BOARD_CACHE.exists():
        cached = _read_json_file(config.BOARD_CACHE) or {}
        if cached:
            print(f"[WARN] 同花顺板块日线本轮未命中，沿用缓存 {len(cached)} 个")
            return cached
    allowed = set((catalog or {}).get("names") or [])
    if allowed:
        found = {str(idx): name for idx, name in found.items() if name in allowed}
    for idx, item in (catalog or {}).get("index", {}).items():
        found[str(idx)] = item.get("name") or found.get(str(idx))
    config.atomic_write_text(config.BOARD_CACHE,
                             json.dumps(found, ensure_ascii=False))
    print(f"[BOARD] 共识别 {len(found)} 个同花顺概念板块")
    return found


# ─────────────────────────────────────────────────────
# 4. 同花顺题材归因（当日强势股 reason 标签）
# ─────────────────────────────────────────────────────
def fetch_ths_hot(date=None):
    from datetime import date as _d
    day = date or _d.today().strftime("%Y-%m-%d")
    url = (f"http://zx.10jqka.com.cn/event/api/getharden/date/{day}"
           f"/orderby/date/orderway/desc/charset/GBK/")
    d = json.loads(http_get(url))
    return d.get("data") or []


def _parse_ths_stock_concepts(txt):
    """解析同花顺个股 F10「概念题材」页的概念顺序。

    这和概念详情页的“成员名单”是两个方向：成员名单回答“哪些股票属于
    这个概念”，F10 页面回答“这只股票在同花顺里按什么顺序归因”。后者
    才适合放在观察池/个股卡片的前两个展示位，避免把地域或资质标签误当成
    当日上涨原因。
    """
    out = []
    for m in re.finditer(r'<td[^>]*class=["\']gnName["\'][^>]*>(.*?)</td>',
                         txt or "", re.I | re.S):
        name = re.sub(r"<[^>]+>", "", m.group(1) or "")
        name = re.sub(r"\s+", "", html.unescape(name)).strip()
        # 个股 F10 的“相关概念”是展示口径，必须保留同花顺原始顺序和
        # 原始标签（包括融资融券、沪股通等页面标签）。题材榜是否纳入
        # 某个标签由 THS 概念成员管线单独决定，不能在这里用东财黑名单裁剪。
        if name and name not in out:
            out.append(name)
    return out


def _parse_ths_stock_industry(txt):
    """解析同花顺 F10 的“所属申万行业”父子层级。"""
    if not txt:
        return []
    m = re.search(
        r'(?:所属申万行业|所属行业|所属产业)\s*[：:]\s*</strong>\s*'
        r'<span[^>]*>(.*?)</span>', txt, re.I | re.S)
    if not m:
        return []
    raw = re.sub(r'<[^>]+>', '', m.group(1) or '')
    raw = re.sub(r'\s+', ' ', html.unescape(raw)).strip()
    # 页面常见格式：电子 — 元件；兼容半角/全角短横线和箭头。
    parts = re.split(r'\s*(?:—|–|-|－|→|>)\s*', raw)
    return list(dict.fromkeys(p.strip() for p in parts if p.strip()))


def canonicalize_ths_concepts(names, catalog=None):
    """按同花顺概念目录统一个股 F10 的简称和板块目录写法。

    只做同花顺目录内的精确归一（如 AIPC → AI PC），不跨源映射，也不做
    模糊包含匹配。目录中没有的 F10 原名保持不变。
    """
    catalog = catalog or fetch_ths_concept_catalog()
    candidates = list(catalog.get("names") or [])
    candidates.extend((catalog.get("detail") or {}).values())
    candidates.extend((x or {}).get("name") for x in
                      (catalog.get("index") or {}).values())
    canonical = list(dict.fromkeys(str(n).strip() for n in candidates if n))
    aliases = {}
    for name in canonical:
        key = _alias_key(name)
        if key:
            aliases.setdefault(key, name)
        for inner in re.findall(r"[\(（](.*?)[\)）]", name):
            key = _alias_key(inner)
            if key:
                aliases.setdefault(key, name)
    out = []
    for name in names or []:
        name = re.sub(r"\s+", " ", str(name or "")).strip()
        if not name:
            continue
        normalized = aliases.get(_alias_key(name), name)
        if normalized not in out:
            out.append(normalized)
    return out


def fetch_ths_stock_concepts(codes, force=False, ttl=24 * 3600):
    """读取一批个股在同花顺 F10 中的概念顺序（展示用，失败可降级）。

    只给观察池/详情卡片等少量标的调用，不参与因子和板块分数；结果按日缓存，
    网络异常时返回已有缓存或空字典，由上层继续使用普通 ``boards`` 标签。
    """
    codes = [str(c).zfill(6) for c in (codes or []) if str(c).strip()]
    if not codes:
        return {}
    p = config.CACHE_DIR / "ths_stock_concepts.json"
    blob = _read_json_file(p) if p.exists() else None
    now = time.time()
    saved = float(blob.get("saved_at") or 0) if isinstance(blob, dict) else 0.0
    stock_cache = (blob or {}).get("stocks") if isinstance(blob, dict) else None
    if not isinstance(stock_cache, dict):
        stock_cache = {}
    # 过期时只刷新本次需要的代码，不清掉未展示股票的旧顺序。
    need = []
    for c in codes:
        item = stock_cache.get(c) or {}
        try:
            checked = float(item.get("checked_at") or 0)
        except (TypeError, ValueError):
            checked = 0.0
        # F10 页面临时 403/连接中断时，失败项只冷却半小时；成功项仍按 7 天
        # 缓存，避免每次行情刷新都重新请求全市场。
        retry_ttl = 30 * 60 if item.get("errors") else ttl
        if force or checked <= 0 or now - checked >= retry_ttl:
            need.append(c)

    def work(c):
        try:
            txt = http_get(f"https://basic.10jqka.com.cn/{c}/concept.html",
                           headers={"Referer": "https://basic.10jqka.com.cn/"},
                           encoding="gbk", timeout=15, retry=1)
            return c, _parse_ths_stock_concepts(txt)
        except Exception:
            return c, []

    if need:
        done = 0
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = [ex.submit(work, c) for c in need]
            for f in as_completed(futs):
                c, names = f.result()
                done += 1
                # 失败也记录 checked_at，避免同花顺临时 403 时每 5 分钟重复撞接口；
                # 下一天自动重试，成功结果仍按原顺序覆盖。
                stock_cache[c] = {"themes": names[:12], "checked_at": now,
                                  "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        config.atomic_write_text(
            p, json.dumps({"saved_at": now, "stocks": stock_cache}, ensure_ascii=False))
        _source_mark("ths_stock_concepts", "ok", coverage=sum(
            1 for c in codes if (stock_cache.get(c) or {}).get("themes")))

    return {c: (stock_cache.get(c) or {}).get("themes") or [] for c in codes}


def fetch_ths_stock_profiles(codes, force=False, ttl=7 * 86400, progress=True):
    """读取同花顺个股 F10 的完整概念题材和所属申万行业。

    这是个股卡片的展示主源：``concept.html`` 提供“相关概念”，
    ``company.html`` 提供“所属申万行业”（例如“电子 — 元件”）。
    不经过东财映射，也不使用题材黑名单裁剪；题材榜的可交易成员仍由
    ``gn`` 概念详情页单独维护。结果按股票缓存 7 天，网络限流时保留
    该股票上一份成功结果。
    """
    codes = list(dict.fromkeys(str(c).zfill(6) for c in (codes or []) if str(c).strip()))
    if not codes:
        return {}
    p = config.THS_STOCK_PROFILE_CACHE
    blob = _read_json_file(p) if p.exists() else None
    profiles = (blob or {}).get("profiles") if isinstance(blob, dict) else None
    if not isinstance(profiles, dict):
        profiles = {}
    now = time.time()
    need = []
    for c in codes:
        item = profiles.get(c) or {}
        try:
            checked = float(item.get("checked_at") or 0)
        except (TypeError, ValueError):
            checked = 0.0
        retry_ttl = 30 * 60 if item.get("errors") else ttl
        if force or checked <= 0 or now - checked >= retry_ttl:
            need.append(c)

    def work(c):
        concepts, industry = [], []
        errors = []
        # 同花顺 basic 页面对突发并发较敏感，轻微抖动比同时撞上接口更稳定。
        time.sleep(random.uniform(0.03, 0.12))
        try:
            txt = http_get(f"https://basic.10jqka.com.cn/{c}/concept.html",
                           headers={"Referer": "https://basic.10jqka.com.cn/"},
                           encoding="gbk", timeout=20, retry=2)
            concepts = _parse_ths_stock_concepts(txt)
        except Exception as e:
            errors.append(f"concept:{type(e).__name__}")
        try:
            time.sleep(random.uniform(0.03, 0.12))
            txt = http_get(f"https://basic.10jqka.com.cn/{c}/company.html",
                           headers={"Referer": "https://basic.10jqka.com.cn/"},
                           encoding="gbk", timeout=20, retry=2)
            industry = _parse_ths_stock_industry(txt)
        except Exception as e:
            errors.append(f"industry:{type(e).__name__}")
        return c, concepts, industry, errors

    done, ok, failed = 0, 0, []
    if need:
        # 3 个并发足够覆盖全市场，也显著降低 basic.10jqka 的临时限流概率。
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = [ex.submit(work, c) for c in need]
            for f in as_completed(futs):
                c, concepts, industry, errors = f.result()
                done += 1
                old = profiles.get(c) or {}
                # 只用成功返回的字段覆盖旧值，单页限流不会抹掉另一页。
                if concepts:
                    old["concepts"] = concepts
                if industry:
                    old["industry"] = industry
                old["checked_at"] = now
                old["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if errors:
                    old["errors"] = errors
                    if not concepts and not industry:
                        failed.append(c)
                else:
                    old.pop("errors", None)
                profiles[c] = old
                if concepts or industry:
                    ok += 1
                if progress and done % 100 == 0:
                    print(f"  [THEME] 同花顺个股 F10 {done}/{len(need)}  已覆盖 {ok} 只")
        config.atomic_write_text(
            p, json.dumps({"saved_at": now, "profiles": profiles}, ensure_ascii=False))
        _source_mark("ths_stock_profiles", "ok", coverage=sum(
            1 for c in codes if (profiles.get(c) or {}).get("concepts") or
            (profiles.get(c) or {}).get("industry")),
            detail=f"requested={len(codes)}; refreshed={len(need)}; failed={len(failed)}")
    # 同花顺 F10 按父级→子级给出层级（如“电子 — 元件”），界面和行业筛选
    # 把更具体的末级行业放在首位，避免用户看到“电子”而误以为缺少“元件”。
    result = {}
    for c in codes:
        item = dict(profiles.get(c) or {})
        industry = list(item.get("industry") or [])
        if len(industry) > 1:
            item["industry"] = list(reversed(industry))
        result[c] = item
    return result


# ─────────────────────────────────────────────────────
# 5. 外围市场（隔夜美股 / 费半）
# ─────────────────────────────────────────────────────
def fetch_outer():
    codes = list(config.OUTER["indices"].keys()) + ["hkHSI", "hkHSTECH"]
    txt = http_get("https://qt.gtimg.cn/q=" + ",".join(codes), encoding="gbk")
    out = {}
    for line in txt.strip().split(";"):
        if '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) > 32:
            out[key] = {"name": vals[1], "price": _f(vals, 3), "change_pct": _f(vals, 32)}
    cfg = config.OUTER["indices"]
    score = 0.0
    for k, meta in cfg.items():
        if k in out:
            score += out[k]["change_pct"] * meta["weight"]
    return {"indices": out, "composite": round(score, 3)}


def fetch_outer_resilient():
    """外围指数仅作辅助；网络暂断时用最近成功缓存并标记日期，不中止主扫描。"""
    cache_path = config.CACHE_DIR / "outer_last_good.json"
    try:
        out = fetch_outer()
        out.update({"available": True, "stale": False,
                    "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        config.atomic_write_text(cache_path, json.dumps(out, ensure_ascii=False))
        _source_mark("outer_market", "ok", coverage=len(out.get("indices") or []))
        return out
    except Exception as e:
        cached = _read_json_file(cache_path) if cache_path.exists() else None
        if not cached:
            try:
                snapshot = _read_json_file(config.SNAPSHOT_JSON) or {}
                cached = snapshot.get("outer")
                if cached:
                    cached = dict(cached, asof=snapshot.get("generated_at"))
            except Exception:
                cached = None
        if cached:
            out = dict(cached, available=True, stale=True,
                       source_error=f"{type(e).__name__}: {e}"[:180])
            _source_mark("outer_market", "stale_cache", detail=e,
                         coverage=len(out.get("indices") or []), stale=True,
                         fetched_at=out.get("asof"))
            print(f"[WARN] 外围指数暂不可用，沿用 {out.get('asof') or '最近成功'} 缓存：{e}")
            return out
        _source_mark("outer_market", "error", detail=e)
        print(f"[WARN] 外围指数暂不可用，本轮跳过外围风险提示：{e}")
        return {"indices": {}, "composite": None, "available": False,
                "stale": False, "asof": None,
                "source_error": f"{type(e).__name__}: {e}"[:180]}


# ─────────────────────────────────────────────────────
# 6. 东财增强层（可降级）
# ─────────────────────────────────────────────────────
def _em_clist_all(fs, fields, sort_field=None, pz=100, max_page=None):
    """东财 clist 全量分页 —— 按 total 动态翻页。

    实测坑（2026-09-18）：服务端会把 pz 强制压到 100，所以「固定页数 × pz」
    的老写法必然截断。曾导致资金流只覆盖 2136/3040、上市日期只覆盖 2500 只，
    而截断是静默的——上层完全看不出来。现在改为读 total 决定何时停，
    并在未取全时明确告警。

    max_page=None 表示「以 total 为准」，用 ABS_PAGES 做绝对上限兜底。
    曾经 build_ths_members 写死 max_page=30，遇到 3870 只的超大板块
    （上证380 / 标普道琼斯一类几乎覆盖全市场的板块）就静默少了 870 只成员。
    """
    ABS_PAGES = 120                      # 绝对上限：120×100=12000 只，任何 A 股板块都够
    cap = ABS_PAGES if not max_page else min(max_page, ABS_PAGES)
    out, page, total = [], 1, None
    hdr = {"Referer": "https://quote.eastmoney.com/"}
    while page <= cap:
        params = {"pn": str(page), "pz": str(pz), "po": "1", "np": "1",
                  "fltt": "2", "invt": "2", "fs": fs, "fields": fields}
        if sort_field:
            params["fid"] = sort_field
        txt = em_get_failover("/api/qt/clist/get", headers=hdr, params=params)
        d = (json.loads(txt) or {}).get("data") or {}
        if total is None:
            total = d.get("total") or 0
        diff = d.get("diff") or []
        if not diff:
            break
        out.extend(diff)
        if total and len(out) >= total:
            break
        page += 1
    if total and len(out) < total:
        print(f"[WARN] 东财分页未取全：{len(out)}/{total}（页数上限 {cap}）")
    return out, total


@em_guard
def fetch_em_boards(pz=100, max_page=8):
    """东财概念板块实时数据（涨跌幅/涨跌家数/主力净流入）"""
    fields = "f2,f3,f8,f12,f14,f20,f62,f104,f105,f128,f136,f140,f141,f184"
    seen, rows = set(), []
    for pn in range(1, max_page + 1):
        txt = em_get_failover("/api/qt/clist/get", headers={"Referer": "https://quote.eastmoney.com/"},
                              params={"pn": str(pn), "pz": str(pz), "po": "1", "np": "1",
                                      "fltt": "2", "invt": "2", "fs": "m:90+t:3",
                                      "fields": fields})
        d = json.loads(txt)
        diff = (d.get("data") or {}).get("diff") or []
        if not diff:
            break
        for i in diff:
            bc = i.get("f12")
            if bc and bc not in seen:
                seen.add(bc)
                rows.append({
                    "board_code": bc,
                    "name": i.get("f14") or "",
                    "change_pct": _f([i.get("f3")], 0),
                    "turnover_pct": _f([i.get("f8")], 0),
                    "up_count": i.get("f104") or 0,
                    "down_count": i.get("f105") or 0,
                    "leader": i.get("f140") or "",
                    "main_net": i.get("f62") if isinstance(i.get("f62"), (int, float)) else None,
                    "main_ratio": i.get("f184") if isinstance(i.get("f184"), (int, float)) else None,
                })
    return rows


@em_guard
def fetch_em_board_members(board_code, pz=500):
    """东财概念板块成分股 → [code]"""
    txt = em_get_failover("/api/qt/clist/get", headers={"Referer": "https://quote.eastmoney.com/"},
                          params={"pn": "1", "pz": str(pz), "po": "1", "np": "1", "fltt": "2",
                                  "invt": "2", "fs": f"b:{board_code}", "fields": "f12,f14"})
    d = json.loads(txt)
    return [i.get("f12") for i in ((d.get("data") or {}).get("diff") or []) if i.get("f12")]


@em_guard
def fetch_em_fundflow_all(pz=100, max_page=60):
    """东财全市场资金流 —— 分页拿全，含今日/5日/10日主力净额。

    clist 的 f164/f174 直接给出 5日/10日主力净额，无需逐只请求。
    东财主板约 3487 只 → 按服务端实际页长 100 计需 35 页，全部覆盖。
    """
    rows, total = _em_clist_all(config.POOL["em_fs"],
                                "f12,f14,f2,f3,f62,f184,f164,f165,f174,f175",
                                sort_field="f62", pz=pz, max_page=max_page)
    out = {}
    for i in rows:
        c = i.get("f12")
        if not c:
            continue
        out[c] = {
            "main_today": i.get("f62") if isinstance(i.get("f62"), (int, float)) else None,
            "main_ratio": i.get("f184") if isinstance(i.get("f184"), (int, float)) else None,
            "main_5d": i.get("f164") if isinstance(i.get("f164"), (int, float)) else None,
            "main_5d_ratio": i.get("f165") if isinstance(i.get("f165"), (int, float)) else None,
            "main_10d": i.get("f174") if isinstance(i.get("f174"), (int, float)) else None,
        }
    print(f"[EM] 资金流覆盖 {len(out)}/{total or '?'} 只")
    return out


def fetch_em_fundflow_all_resilient(pz=100, max_page=60, prefer_cache=False):
    """全市场资金流 + 短时最近成功缓存备用。

    quick 扫描优先使用短时（默认 15 分钟）内的最近成功结果，避免每轮都等待全市场
    翻页；full 扫描或缓存过期时仍然回源，确保日终数据重新校准。
    """
    t0 = time.time()
    if prefer_cache:
        quick_age = config.EM.get("quick_cache_seconds", 300)
        rows, age, blob = _load_em_rows_cache(config.EM_FUND_CACHE, quick_age)
        if rows:
            try:
                out = {str(k): v for k, v in rows if isinstance(v, dict)}
            except (TypeError, ValueError):
                out = {}
            if out:
                _source_mark("eastmoney_fundflow", "quick_cache",
                             elapsed=time.time() - t0, coverage=len(out),
                             detail=f"age={age:.0f}s", stale=True,
                             fetched_at=(blob or {}).get("fetched_at"))
                print(f"[EM] quick 复用资金流缓存 {len(out)} 只（{age:.0f}s 前）")
                return out, {"source": "东财主力净流入（15分钟快速缓存）",
                             "stale": True, "age_seconds": round(age or 0),
                             "coverage": len(out)}
    try:
        out = fetch_em_fundflow_all(pz=pz, max_page=max_page)
        if not out:
            raise RuntimeError("东财资金流返回空数据")
        fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _save_em_rows_cache(config.EM_FUND_CACHE, list(out.items()), len(out))
        _source_mark("eastmoney_fundflow", "ok", elapsed=time.time() - t0,
                     coverage=len(out), fetched_at=fetched_at)
        return out, {"source": "东财主力净流入", "stale": False,
                     "age_seconds": 0, "coverage": len(out), "fetched_at": fetched_at}
    except Exception as e:
        max_age = config.EM.get("stale_max_seconds", 900)
        rows, age, blob = _load_em_rows_cache(config.EM_FUND_CACHE, max_age)
        if rows:
            try:
                out = {str(k): v for k, v in rows if isinstance(v, dict)}
            except (TypeError, ValueError):
                out = {}
            if out:
                _source_mark("eastmoney_fundflow", "stale_cache",
                             elapsed=time.time() - t0, coverage=len(out),
                             detail=f"age={age:.0f}s; {e}", stale=True,
                             fetched_at=(blob or {}).get("fetched_at"))
                print(f"[WARN] 东财资金流不可用，采用最近成功缓存（{age/60:.1f} 分钟前）：{e}")
                return out, {"source": "东财主力净流入（最近成功缓存）", "stale": True,
                             "age_seconds": round(age or 0), "coverage": len(out),
                             "fetched_at": (blob or {}).get("fetched_at")}
        _source_mark("eastmoney_fundflow", "error", elapsed=time.time() - t0,
                     detail=e)
        raise


def fetch_sina_fundflow_all(quotes):
    """新浪全市场当日超大单净额；仅在东财不可用时使用，不伪造历史资金。"""
    t0 = time.time()
    url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "MoneyFlow.ssl_bkzj_ssggzj?" + urllib.parse.urlencode({
               "page": 1, "num": 7000, "sort": "r0_net", "asc": 0,
               "bankuai": "", "shichang": "",
           }))
    try:
        rows = json.loads(http_get(url, timeout=35, retry=1))
        if not isinstance(rows, list) or len(rows) < 3000:
            raise ValueError("新浪资金全市场返回不完整")
        seen = set()
        matched = 0
        out = {}
        for row in rows:
            symbol = row.get("symbol") or ""
            if not re.fullmatch(r"(?:sh|sz)\d{6}", symbol):
                continue
            code = symbol[-6:]
            quote = quotes.get(code)
            if not quote or code in seen:
                continue
            seen.add(code)
            try:
                price = float(row["trade"])
                quote_price = float(quote["price"])
                net = float(row["r0_net"])
                amount = float(row["amount"])
            except (KeyError, TypeError, ValueError):
                continue
            if not all(math.isfinite(v) for v in (price, quote_price, net, amount)):
                continue
            if price <= 0 or quote_price <= 0 or amount <= 0:
                continue
            # 源未给交易日期，用当期价格交叉核对。个别延迟行情不混入资金排行。
            if abs(price / quote_price - 1) > 0.01:
                continue
            matched += 1
            out[code] = {"main_today": net, "main_ratio": net / amount * 100,
                         "main_5d": None, "main_5d_ratio": None,
                         "main_10d": None}
        if len(out) < len(quotes) * 0.85:
            raise ValueError(f"新浪资金与行情匹配不足：{len(out)}/{len(quotes)}")
        fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _source_mark("sina_fundflow", "ok", elapsed=time.time() - t0,
                     coverage=len(out), fetched_at=fetched_at,
                     detail=f"全市场{len(rows)}条；匹配{matched}/{len(quotes)}；仅当日")
        return out, {"source": "新浪当日超大单净额", "stale": False,
                     "coverage": len(out), "period": "today", "fetched_at": fetched_at,
                     "universe_rows": len(rows), "quote_count": len(quotes)}
    except Exception as e:
        _source_mark("sina_fundflow", "error", elapsed=time.time() - t0, detail=e)
        raise


def fetch_sina_fundflow(code, days=15):
    """逐股日级主力净额 = 新浪超大单净额 + 大单净额，单位元。"""
    symbol = ("sh" if str(code).startswith(("6", "9")) else "sz") + str(code)
    url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "MoneyFlow.ssl_qsfx_lscjfb?" + urllib.parse.urlencode({
               "page": 1, "num": days, "sort": "opendate", "asc": 0,
               "daima": symbol,
           }))
    raw = json.loads(http_get(url, timeout=15, retry=1))
    if not isinstance(raw, list):
        raise ValueError("新浪逐股资金格式异常")
    rows = []
    for item in raw:
        try:
            day = str(item["opendate"])
            big = float(item["r0_net"])
            large = float(item["r1_net"])
        except (KeyError, TypeError, ValueError):
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) and math.isfinite(big + large):
            rows.append({"date": day, "main_net": big + large})
    return sorted(rows, key=lambda x: x["date"])


@em_guard
def fetch_em_fundflow(code, days=20):
    """东财个股日级资金流（主力净流入，单位元）"""
    secid = f"1.{code}" if code.startswith(("6", "9")) else f"0.{code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?" + urllib.parse.urlencode({
        "secid": secid, "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57", "lmt": str(days),
    })
    d = json.loads(em_get(url))
    out = []
    for line in (d.get("data") or {}).get("klines", []) or []:
        p = line.split(",")
        if len(p) >= 6:
            try:
                out.append({"date": p[0], "main_net": float(p[1]),
                            "small_net": float(p[2]), "mid_net": float(p[3]),
                            "large_net": float(p[4]), "super_net": float(p[5])})
            except ValueError:
                continue
    return out


@em_guard
def fetch_em_indices():
    """东财大盘指数"""
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get?" + urllib.parse.urlencode({
        "fltt": "2", "invt": "2",
        "secids": "1.000001,0.399001,1.000300,0.399006",
        "fields": "f2,f3,f4,f12,f14",
    })
    d = json.loads(em_get(url))
    return [{"code": i.get("f12"), "name": i.get("f14"),
             "price": i.get("f2"), "change_pct": i.get("f3")}
            for i in ((d.get("data") or {}).get("diff") or [])]


# ─────────────────────────────────────────────────────
# 6·补、题材归属（东财 datacenter-web，独立风控域名，push2 被封时仍可用）
# ─────────────────────────────────────────────────────
def _dc_get(report, columns="ALL", page=1, pz=5000, sort_col="SECUCODE", sort_type="1",
            extra=None, timeout=30):
    """东财数据中心统一查询"""
    params = {
        "reportName": report, "columns": columns,
        "pageSize": str(pz), "pageNumber": str(page),
        "sortColumns": sort_col, "sortTypes": sort_type,
        "source": "WEB", "client": "WEB",
    }
    if extra:
        params.update(extra)
    url = (f"https://{config.EM['data_host']}/api/data/v1/get?"
           + urllib.parse.urlencode(params))
    d = json.loads(em_get(url, timeout=timeout))
    res = d.get("result") or {}
    return res.get("data") or [], res.get("pages"), res.get("count")


def _theme_fingerprint():
    """题材口径指纹 —— 口径一变，缓存立即失效"""
    raw = json.dumps({
        "ex": sorted(config.THEME["exclude_keywords"]),
        "maxindustry": config.THEME.get("max_industry_per_stock", 4),
        "member_big_warn": config.THEME.get("member_big_warn", 1200),
        "ver": config.THEME.get("cache_ver", "1"),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def _ths_catalog_fingerprint(catalog):
    """目录内容指纹，用来让新增/改名的标签立即使成分缓存失效。"""
    raw = json.dumps({
        "detail": (catalog or {}).get("detail") or {},
        "index": (catalog or {}).get("index") or {},
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def _theme_ok(name):
    """过滤掉属性/状态/指数成分/地域类标签——它们不是题材"""
    if not name:
        return False
    return not any(k in name for k in config.THEME["exclude_keywords"])


@em_guard
def fetch_theme_map(max_pages=30):
    """[旧版兼容] 东财全市场题材归属。

    当前运行链路不会调用此函数；行业、题材、概念统一由同花顺函数提供。
    保留它只为兼容历史脚本和旧缓存诊断。

    数据源 RPT_F10_CORETHEME_BOARDTYPE（94k 行 / 19 页 / 约 23 秒）。
    返回 {code: {"themes": [...], "industry": [...]}}，按 BOARD_RANK 由核心到边缘排序。

    踩坑记录：
      · IS_PRECISE 实际是字符串 "1"（非 int），必须 str() 比较
      · BOARD_TYPE 只有「行业 / 板块(地域) / None」三种，
        概念与属性标签全堆在 None 里，所以必须靠黑名单过滤
    """
    allrows, page = [], 1
    while page <= max_pages:
        rows, pages, count = _dc_get("RPT_F10_CORETHEME_BOARDTYPE",
                                     columns="SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,"
                                             "BOARD_NAME,BOARD_CODE,IS_PRECISE,"
                                             "BOARD_RANK,BOARD_TYPE,BOARD_LEVEL",
                                     page=page)
        if not rows:
            break
        allrows.extend(rows)
        if pages and page >= pages:
            break
        page += 1
        time.sleep(0.5)

    out = {}
    for r in allrows:
        c = r.get("SECURITY_CODE")
        nm = r.get("BOARD_NAME") or ""
        if not c or not nm:
            continue
        d = out.setdefault(c, {"themes": [], "industry": []})
        btype = r.get("BOARD_TYPE") or ""
        if btype == "行业":
            d["industry"].append(nm)
        elif btype == "板块":
            continue                      # 地域板块，丢弃
        else:
            d["themes"].append({
                "name": nm,
                # BOARD_CODE 是东财题材库内部编号，实测「BK」+ 零填充 4 位
                # 就是东财概念板块代码（830 → BK0830 =「区块链」）。
                # 有了它才能把东财题材名对到同花顺概念名（见 build_board_alias）。
                "code": str(r.get("BOARD_CODE") or ""),
                "precise": str(r.get("IS_PRECISE")) == "1",
                "rank": r.get("BOARD_RANK") if isinstance(r.get("BOARD_RANK"), int) else 9999,
            })

    # 排序 + 过滤 + 截断
    # 这里先多取一倍：东财名里有相当一部分对不到同花顺名（如「国产芯片」
    # 同花顺没有同名概念），若在此就截到 8 个，对齐完可能只剩 3-4 个标签，偏薄。
    lim = config.THEME["max_per_stock"] * 2
    final = {}
    for c, d in out.items():
        themes = [t for t in d["themes"] if _theme_ok(t["name"])]
        themes.sort(key=lambda t: (not t["precise"], t["rank"]))
        themes = themes[:lim]
        names = [t["name"] for t in themes]
        if not names:
            continue
        final[c] = {
            "themes": names,
            "theme_codes": [t["code"] for t in themes],
            "industry": d["industry"][:2],
        }
    return final


# ─────────────────────────────────────────────────────
# 6·旧版兼容函数（当前分类链路不调用）
#
# 历史背景（2026-09-18 用户反馈"点领涨题材跳不到对应个股"）：
#   个股身上的题材标签来自东财题材库 CORETHEME，名字是「通信技术 / 电池技术」；
#   而题材榜与板块榜跑的是同花顺概念，名字是「玻璃基板 / 华为海思概念股」。
#   两套命名体系对不上 → 点击题材去筛选个股，命中 0 只。
#
# 打通链路（已实测验证）：
#   CORETHEME.BOARD_CODE(830) ──► 东财概念板块 BK0830 =「区块链」
#                             ──► 同花顺概念名（靠名字归一化匹配）
#   即 "BK" + BOARD_CODE 零填充 4 位 = 东财概念板块代码，无需额外抓取成分股。
#
# 实测效果：个股至少挂上 1 个同花顺标签的覆盖率 91.0%（2486/2731），
#          人均 4.97 个标签，可形成 244 个同花顺口径题材组。
# ─────────────────────────────────────────────────────
def load_em_boards(force=False):
    """东财概念板块 {BKxxxx: 名称}，24 小时缓存。"""
    p = config.EM_BOARD_CACHE
    if not force and p.exists() and time.time() - p.stat().st_mtime < 24 * 3600:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        rows = fetch_em_boards()
    except Exception as e:
        cached = _read_json_file(p) if p.exists() else None
        if isinstance(cached, dict) and cached:
            age = _cache_age_seconds({"saved_at": p.stat().st_mtime}, p)
            _source_mark("eastmoney_board_catalog", "stale_cache",
                         coverage=len(cached), detail=f"age={age:.0f}s; {e}",
                         stale=True)
            print(f"[WARN] 东财板块目录不可用，沿用缓存 {len(cached)} 个：{e}")
            return cached
        raise
    m = {r["board_code"]: r["name"] for r in rows if r.get("board_code") and r.get("name")}
    if m:
        config.atomic_write_text(p, json.dumps(m, ensure_ascii=False))
        _source_mark("eastmoney_board_catalog", "ok", coverage=len(m))
    print(f"[THEME] 东财概念板块 {len(m)} 个")
    return m


def _save_em_rows_cache(path, rows, total=None):
    blob = {"saved_at": time.time(),
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rows": rows, "total": total}
    config.atomic_write_text(path, json.dumps(blob, ensure_ascii=False))


def _load_em_rows_cache(path, max_age=None):
    blob = _read_json_file(path) if path.exists() else None
    if not isinstance(blob, dict) or not isinstance(blob.get("rows"), list):
        return None, None, None
    age = _cache_age_seconds(blob, path)
    if age is None or (max_age is not None and age > max_age):
        return None, age, blob
    return blob.get("rows") or [], age, blob


def fetch_em_boards_resilient(pz=100, max_page=8, prefer_cache=False):
    """东财板块实时 + 最近成功缓存备用。

    备用只接受配置的短时窗口，返回的 meta 会被写入快照；超过窗口宁可
    使用题材组/成交额代理，也不把过期资金流当成实时数据。
    """
    t0 = time.time()
    if prefer_cache:
        quick_age = config.EM.get("quick_cache_seconds", 300)
        rows, age, blob = _load_em_rows_cache(config.EM_BOARD_RT_CACHE, quick_age)
        if rows:
            _source_mark("eastmoney_board_realtime", "quick_cache",
                         elapsed=time.time() - t0, coverage=len(rows),
                         detail=f"age={age:.0f}s", stale=True,
                         fetched_at=(blob or {}).get("fetched_at"))
            print(f"[EM] quick 复用板块缓存 {len(rows)} 个（{age:.0f}s 前）")
            return rows, {"source": "东财板块实时（15分钟快速缓存）",
                          "stale": True, "age_seconds": round(age or 0),
                          "coverage": len(rows)}
    try:
        rows = fetch_em_boards(pz=pz, max_page=max_page)
        if rows:
            _save_em_rows_cache(config.EM_BOARD_RT_CACHE, rows, len(rows))
            _source_mark("eastmoney_board_realtime", "ok", elapsed=time.time() - t0,
                         coverage=len(rows))
            return rows, {"source": "东财板块实时", "stale": False,
                          "age_seconds": 0, "coverage": len(rows)}
        raise RuntimeError("东财板块返回空数据")
    except Exception as e:
        max_age = config.EM.get("stale_max_seconds", 900)
        rows, age, blob = _load_em_rows_cache(config.EM_BOARD_RT_CACHE, max_age)
        if rows:
            _source_mark("eastmoney_board_realtime", "stale_cache",
                         elapsed=time.time() - t0, coverage=len(rows),
                         detail=f"age={age:.0f}s; {e}", stale=True,
                         fetched_at=(blob or {}).get("fetched_at"))
            print(f"[WARN] 东财板块实时不可用，采用最近成功缓存（{age/60:.1f} 分钟前）：{e}")
            return rows, {"source": "东财板块实时（最近成功缓存）", "stale": True,
                          "age_seconds": round(age or 0), "coverage": len(rows)}
        _source_mark("eastmoney_board_realtime", "error", elapsed=time.time() - t0,
                     detail=e)
        raise


def _alias_key(name):
    """归一化：去空白/「概念、板块、指数」/括号内容，转大写。

    与 scoring.name_key 同口径 —— 那边要用同一把尺子做跨源匹配，
    这里单独实现一份是为了避免 datafeed 反向依赖 scoring（分层约定）。
    """
    return re.sub(r"[\s　]|概念|板块|指数|\(.*?\)|（.*?）", "", str(name or "")).upper()


def _alias_match(nk, keys):
    """归一化名 → 目标键，只接受精确键（含同花顺括号内别名）。

    以前这里用“包含即匹配”，会把“LED概念”挂到“MicroLED概念”、
    “大数据”挂到“时空大数据”等更窄的板块。题材归属是个股的事实标签，
    不能用强度榜那种模糊匹配；宁可保留东财原名待搜索，也不能伪造同花顺归属。
    ``keys`` 在 build_board_alias 中同时登记了同花顺外层名和括号内文本，
    因此 CPO、电子烟、算力等明确括号别名仍能准确对齐。
    """
    return nk if nk in keys else None


def build_board_alias(force=False):
    """东财概念板块名 → 同花顺概念名。

    同花顺与东财的概念命名有差异（「华为海思概念股」↔「华为海思」、
    「共封装光学(CPO)」↔「CPO概念」），所以除了归一化精确匹配，
    还额外拿括号里的内容当候选（CPO 就藏在括号里）。

    返回 {"map": {东财名: 同花顺名}, "stat": {...}}，缓存 24 小时。
    """
    p = config.BOARD_ALIAS_CACHE
    catalog = None
    try:
        catalog = fetch_ths_concept_catalog(force=force)
    except Exception:
        catalog = {}
    if not force and p.exists() and time.time() - p.stat().st_mtime < 24 * 3600:
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
            stat = blob.get("stat") or {}
            old_n = stat.get("ths_catalog_total")
            new_n = len((catalog or {}).get("detail") or {})
            if (blob.get("map") and old_n == new_n
                    and stat.get("matcher") == "exact-inner-v2"):
                return blob
            if blob.get("map"):
                print(f"[THEME] 同花顺概念目录数量变化 {old_n} → {new_n}，刷新名称对齐缓存")
        except Exception:
            pass

    em = load_em_boards(force=force)                       # {BKxxx: 东财名}
    ths = scan_ths_boards()                                # {885xxx: 同花顺名}
    # 名称以同花顺概念目录为主；板块日线缓存补充目录页暂未展示、但仍有
    # 历史行情的板块，避免“同步”变成“只剩当前热门板”。
    ths_names = sorted({v for v in ths.values() if v}
                       | set((catalog or {}).get("names") or []))

    # 同花顺名 → 归一化键（含括号内文本的备用键）
    keys = {}
    for n in ths_names:
        keys.setdefault(_alias_key(n), n)
        for inner in re.findall(r"[\(（](.*?)[\)）]", n):
            inner = _alias_key(inner)
            if inner:
                keys.setdefault(inner, n)

    amap, unm = {}, []
    for bk, emn in em.items():
        k = _alias_match(_alias_key(emn), keys)
        if k:
            amap[emn] = keys[k]
        else:
            unm.append(emn)

    stat = {"em_total": len(em), "ths_total": len(ths_names),
            "ths_catalog_total": len((catalog or {}).get("detail") or {}),
            "ths_active_index_total": len((catalog or {}).get("index") or {}),
            "matched": len(amap), "unmatched_sample": unm[:40],
            "matcher": "exact-inner-v2"}
    print(f"[THEME] 东财板块名 → 同花顺名 {len(amap)}/{len(em)} "
          f"= {len(amap)/max(1,len(em))*100:.1f}%")
    p.write_text(json.dumps({"map": amap, "stat": stat}, ensure_ascii=False),
                 encoding="utf-8")
    return {"map": amap, "stat": stat}


def prune_ths_members(blob):
    """按当前配置裁剪成分股缓存：丢掉属性/状态/风格类概念与超大板块。

    踩坑记录（2026-09-18）：第一版直接把东财概念板块的全部成分股并进个股标签，
    结果「融资融券」3870 只、「沪股通」1643 只、「国企改革」1448 只这类
    风格/属性板块也被当成题材挂了上去 —— 单只个股的标签被撑到 39 个，
    真题材（如"共封装光学"）被淹没在几十个仓位口径里，用户根本找不到。
    这类名字在 THEME["exclude_keywords"] 里本来就有，只是成分股这条支路
    当初漏掉了这道过滤。同时成分数 ≥ member_big_warn 的板块一律视为
    全市场口径（上证380/标普道琼斯之类），不可能是题材。
    """
    if not blob or not blob.get("map"):
        return blob
    big_n = config.THEME.get("member_big_warn", 1200)
    m = blob["map"]
    cnt = {}
    for code, lst in m.items():
        for t in lst:
            cnt[t] = cnt.get(t, 0) + 1
    drop = {t for t, c in cnt.items() if (not _theme_ok(t)) or c >= big_n}
    if not drop:
        blob.setdefault("stat", {})["pruned"] = 0
        return blob
    out = {}
    for code, lst in m.items():
        keep = [t for t in lst if t not in drop]
        if keep:
            out[code] = keep
    blob["map"] = out
    st = blob.setdefault("stat", {})
    st["pruned"] = len(drop)
    st["pruned_names"] = sorted(drop)[:30]
    st["stocks"] = len(out)
    print(f"[THEME] 成分股缓存裁剪：剔除 {len(drop)} 个风格/属性/超大概念"
          f"（{'、'.join(sorted(drop)[:6])}…），剩余 {len(out)} 只个股")
    return blob


def fetch_ths_detail_members(detail_code, max_page=60, section="gn", allow_partial=False):
    """从同花顺概念/行业详情页读取真实成分股代码。

    详情页的普通 HTML 分页不需要 ``hexin-v``；需要该 cookie 的是旧版
    ajax 成分接口。普通页的 ``page_info`` 给出总页数，按页读取真实代码。
    行业补库可显式请求部分结果，返回codes/complete/error；常规调用仍须完整成功。
    """
    code = str(detail_code or "").strip()
    if not code:
        return []
    section = "thshy" if str(section).lower() in {"thshy", "industry", "hy"} else "gn"
    base = f"http://q.10jqka.com.cn/{section}/detail/code/{code}/"
    out, total_pages = [], 1
    def fail(message):
        if allow_partial and out:
            return dict(codes=out, complete=False, error=message)
        raise RuntimeError(message)
    for page in range(1, max_page + 1):
        url = base if page == 1 else f"{base}page/{page}/"
        try:
            txt = http_get(url, headers={"Referer": base}, encoding="gbk",
                           timeout=20, retry=1)
        except Exception as exc:
            if allow_partial and out:
                return fail(f'第{page}页读取失败：{type(exc).__name__}: {exc}')
            raise
        seen_before = set(out)
        found = re.findall(r"stockpage\.10jqka\.com\.cn/(\d{6})", txt, re.I)
        for c in found:
            if c not in out:
                out.append(c)
        if page == 1:
            m = re.search(r"page_info[^>]*>.*?(\d+)\s*/\s*(\d+)", txt, re.I | re.S)
            if m:
                total_pages = max(1, int(m.group(2)))
                if total_pages > max_page:
                    return fail(f"同花顺成员分页超出读取范围：{total_pages}>{max_page}")
            elif len(set(found)) >= 20:
                return fail('同花顺成员分页信息缺失，当前页完整性未核验')
        # 返回空页/验证码或重复第一页时不能把前面几页冒充完整成员名单。
        if not found:
            return fail(f"同花顺成员第{page}页无有效代码")
        info = re.search(r"page_info[^>]*>.*?(\d+)\s*/\s*(\d+)", txt, re.I | re.S)
        if info and int(info.group(1)) != page:
            return fail(f"同花顺成员分页未对齐：请求{page}，返回{info.group(1)}")
        if page > 1 and not (set(found)-seen_before):
            return fail(f"同花顺成员第{page}页重复，名单未完整取得")
        if page >= total_pages:
            break
    return dict(codes=out, complete=True, error=None) if allow_partial else out


def _is_verified_ths_member_cache(blob):
    """只把有完整直连记录的同花顺详情缓存作为分类成员来源。"""
    if not isinstance(blob, dict) or not isinstance(blob.get("map"), dict):
        return False
    st = blob.get("stat") or {}
    try:
        concepts = int(st.get("concepts") or 0)
        direct = int(st.get("direct_concepts") or 0)
    except (TypeError, ValueError):
        return False
    return (st.get("member_source") == "ths-detail-v4"
            and direct > 0 and direct == concepts
            and not st.get("fallback_concepts", 0)
            and not st.get("failed") and not st.get("direct_failed"))


def build_ths_members(force=False, progress=True):
    """同花顺概念详情 → 成分股（行业/题材分类的唯一成员来源）。

    同花顺概念详情页的普通 HTML 分页直接包含成分表，名称和成员都与
    同花顺软件口径一致。这里不再读取东财 CORETHEME、东财板块别名或东财
    成分接口；详情页失败时保留上一份成功的同花顺缓存，避免跨源标签混入。
    """
    p = config.THS_MEMBER_CACHE
    # 日常扫描固定使用已保存的分类；手动刷新目录与成员分两步完成。
    catalog = fetch_ths_concept_catalog()
    catalog_fp = _ths_catalog_fingerprint(catalog)
    if not force and p.exists():
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
            st = blob.get("stat") or {}
            if (_is_verified_ths_member_cache(blob)
                    and st.get("catalog_fingerprint") == catalog_fp):
                _source_mark("ths_stock_concepts", "cache", coverage=len(blob["map"]),
                             detail=f"concepts={st.get('concepts', 0)}")
                return blob
        except Exception:
            pass
        raise RuntimeError("同花顺概念成员缓存未通过完整性检查；请手动刷新分类")
    if not force:
        raise RuntimeError("尚无同花顺概念成员缓存；请手动刷新分类")

    # 目录页是名称和详情号的唯一来源；当前分类链路不读取东财板块或别名。

    # 同花顺目录是成分口径主源：即使东财没有同名 BK 板块，也要直接读取
    # 同花顺详情页，不能因为跨源名称对不上就把“同花顺独有概念”误当成无成员。
    # 详情目录的名称可能与 885xxx 日线名有轻微后缀差异，外层名精确优先，
    # 再用同一把 _alias_key 做唯一归一化查找；不再做任意包含匹配。
    direct_targets = {}
    for cid, name in (catalog.get("detail") or {}).items():
        name = str(name or "").strip()
        if name:
            direct_targets.setdefault(name, str(cid))
    # 目录页偶尔只把某个概念放在 885xxx 索引映射里，补入它的详情号；
    # 同名时保留 detail 正文的值，避免重复抓取。
    for item in (catalog.get("index") or {}).values():
        n = str((item or {}).get("name") or "").strip()
        dc = str((item or {}).get("detail_code") or "").strip()
        if n and dc:
            direct_targets.setdefault(n, dc)
    print(f"[THEME] 拉取 {len(direct_targets)} 个同花顺概念详情成分股 ...")
    t0 = time.time()
    out, done, failed = {}, 0, []
    direct_failed = []

    def ths_work(item):
        t, dc = item
        try:
            codes = fetch_ths_detail_members(dc)
            return t, codes, (RuntimeError("同花顺详情页无成分股") if not codes else None)
        except Exception as e:
            return t, [], e

    # 普通详情页是同花顺公开 HTML，适度并发即可；失败项仅记账并保留旧缓存。
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(ths_work, item) for item in direct_targets.items()]
        for f in as_completed(futs):
            t, codes, err = f.result()
            done += 1
            if err:
                direct_failed.append(t)
                failed.append(t)
            for c in codes:
                lst = out.setdefault(c, [])
                if t not in lst:
                    lst.append(t)
            if progress and done % 30 == 0:
                print(f"  [THEME] 同花顺详情 {done}/{len(direct_targets)}  已覆盖 {len(out)} 只"
                      f"  用时 {time.time()-t0:.0f}s")

    # 手动更新时若遇到限流/断网，不让空结果覆盖已有分类成员。
    old_blob = _read_json_file(p) if p.exists() else None
    old_map = old_blob.get("map") if isinstance(old_blob, dict) else None
    old_n = len(old_map or {}) if isinstance(old_map, dict) else 0
    old_is_pure = _is_verified_ths_member_cache(old_blob)
    failed_ratio = len(direct_failed) / max(1, len(direct_targets))
    catastrophic = (old_is_pure and old_n and (not out or
                    (len(out) < max(500, int(old_n * 0.25)) and failed_ratio >= 0.25)))
    if catastrophic:
        print(f"[WARN] 同花顺成分页本轮不可用（新结果 {len(out)} 只，旧缓存 {old_n} 只），"
              "保留上次成功缓存，不覆盖题材归属")
        return old_blob

    stat = {"concepts": len(direct_targets),
            "stocks": len(out),
            "failed": failed[:20], "elapsed": round(time.time() - t0, 1),
            "member_source": "ths-detail-v4", "direct_concepts": len(direct_targets),
            "direct_failed": direct_failed[:20], "fallback_concepts": 0,
            "catalog_fingerprint": catalog_fp,
            "catalog_detail_count": len(catalog.get("detail") or {}),
            "catalog_index_count": len(catalog.get("index") or {})}
    print(f"[THEME] 成分股补全完成：{len(direct_targets)} 个同花顺概念 "
          f"/ {len(out)} 只个股 / 失败 {len(failed)} 个 / "
          f"用时 {stat['elapsed']}s")
    config.atomic_write_text(p, json.dumps({"map": out, "stat": stat}, ensure_ascii=False))
    return {"map": out, "stat": stat}


def build_ths_industry_members(force=False, progress=True):
    """同花顺行业（thshy）-> 成分股。

    行业和概念是同花顺两个独立的目录体系。行业详情页使用同一套分页
    HTML，因此复用 ``fetch_ths_detail_members``，但明确传入 ``thshy``，
    不能把行业名称假定为 ``gn`` 概念。结果供个股 ``industry`` 字段使用，
    不参与题材榜和题材因子，避免把行业误当成短线题材。
    """
    p = config.THS_INDUSTRY_MEMBER_CACHE
    catalog = fetch_ths_industry_catalog()
    catalog_fp = _ths_catalog_fingerprint(catalog)
    if not force and p.exists():
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
            st = blob.get("stat") or {}
            if (blob.get("map") and st.get("member_source") == "ths-industry-detail-v1"
                    and st.get("catalog_fingerprint") == catalog_fp):
                _source_mark("ths_industry_members", "cache", coverage=len(blob["map"]),
                             detail=f"industries={st.get('industries', 0)}")
                return blob
        except Exception:
            pass
        raise RuntimeError("同花顺行业成员缓存不可用；请手动刷新分类")
    if not force:
        raise RuntimeError("尚无同花顺行业成员缓存；请手动刷新分类")

    detail_by_name = {}
    for cid, name in (catalog.get("detail") or {}).items():
        name = str(name or "").strip()
        if name:
            detail_by_name.setdefault(name, str(cid))
    direct_targets = list(detail_by_name.items())
    print(f"[THEME] 拉取 {len(direct_targets)} 个同花顺行业详情成分股 ...")
    t0 = time.time()
    out, done, failed, partial, errors = {}, 0, [], [], {}

    def ths_industry_work(item):
        name, dc = item
        try:
            result = fetch_ths_detail_members(dc, section="thshy", allow_partial=True)
            codes = result['codes']
            return name, codes, (RuntimeError(result['error'] or '同花顺行业详情页无成分股')
                                 if not result['complete'] or not codes else None)
        except Exception as e:
            return name, [], e

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(ths_industry_work, item) for item in direct_targets]
        for f in as_completed(futs):
            name, codes, err = f.result()
            done += 1
            if err:
                failed.append(name)
                errors[name] = str(err)
                if codes:
                    partial.append(name)
            for c in codes:
                out.setdefault(c, []).append(name)
            if progress and done % 15 == 0:
                print(f"  [THEME] 同花顺行业 {done}/{len(direct_targets)}  已覆盖 {len(out)} 只"
                      f"  用时 {time.time()-t0:.0f}s")

    # 并发完成顺序不稳定，按目录顺序固定每只股票的行业顺序，便于前端和
    # 导出文件稳定 diff；同一股票也只保留一次名称。
    order = {name: i for i, (name, _cid) in enumerate(direct_targets)}
    for c, names in list(out.items()):
        out[c] = sorted(set(names), key=lambda n: order.get(n, 10 ** 9))

    old_blob = _read_json_file(p) if p.exists() else None
    old_map = old_blob.get("map") if isinstance(old_blob, dict) else None
    # 单个行业拉取失败保留该行业上次有来源的成员；成功行业按新名单替换。
    # 不因一次空页把某个板块从本地目录里清空。
    if isinstance(old_map, dict) and (old_blob.get('stat') or {}).get('member_source') == 'ths-industry-detail-v1':
        failed_set = set(failed)
        for c, names in old_map.items():
            keep = [name for name in names if name in failed_set and name in detail_by_name]
            if keep:
                out[c] = sorted(set(out.get(c, [])+keep), key=lambda n: order.get(n, 10**9))
    checked_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    stat = {"industries": len(direct_targets), "stocks": len(out),
            "failed": failed, "elapsed": round(time.time() - t0, 1),
            "partial": partial, "errors": errors,
            "checked_at": checked_at,
            "member_source": "ths-industry-detail-v1",
            "catalog_fingerprint": catalog_fp,
            "catalog_detail_count": len(catalog.get("detail") or {})}
    blob = {"map": out, "stat": stat}
    config.atomic_write_text(p, json.dumps(blob, ensure_ascii=False))
    _source_mark("ths_industry_members", "partial" if failed else "ok", elapsed=time.time() - t0,
                 coverage=len(out), detail=f"industries={len(direct_targets)}; incomplete={len(failed)}",
                 stale=bool(failed))
    print(f"[THEME] 同花顺行业成分补全完成：{len(direct_targets)} 个行业 / "
          f"{len(out)} 只股票 / 失败 {len(failed)} 个 / 用时 {stat['elapsed']}s")
    return blob


def merge_theme_members(m, members):
    """[历史兼容] 合并同花顺概念成员；当前构建直接读取纯 THS 成员图。"""
    if not members:
        return m
    cap = config.THEME.get("max_tags_total", 22)
    out = {}
    for c, d in (m or {}).items():
        base = list(d.get("themes") or [])
        extra = [t for t in (members.get(c) or []) if t not in base]
        out[c] = {"themes": (extra + base)[:cap],
                  "themes_em": d.get("themes_em") or [],
                  "industry": d.get("industry") or []}
    # 成分股里出现、但 CORETHEME 没有覆盖的个股也补进来
    for c, lst in members.items():
        if c in out:
            continue
        out[c] = {"themes": list(lst)[:cap], "themes_em": [], "industry": []}
    return out


def merge_industry_members(m, members):
    """把同花顺 thshy 行业成分并入个股 ``industry`` 字段。

    行业标签不进入 ``themes``，也不进入题材榜；这里只补足归属展示和
    行业筛选。对 CORETHEME 没覆盖的股票同样创建最小记录，避免成分表
    有数据而个股页却完全看不到归属。
    """
    if not members:
        return m
    cap = config.THEME.get("max_industry_per_stock", 4)
    out = {}
    for c, d in (m or {}).items():
        base = list(d.get("industry") or [])
        # 行业详情页可能同时提供父级和细分行业，首位保留更细的同花顺归属。
        ths = list(dict.fromkeys(members.get(c) or []))
        extra = ths
        base = [t for t in base if t not in ths]
        row = dict(d)
        # 同花顺 thshy 是分类唯一口径，保留父子层级供行业筛选。
        row["industry"] = (extra + base)[:cap]
        out[c] = row
    for c, lst in members.items():
        if c in out:
            continue
        out[c] = {"themes": [], "themes_em": [],
                  "industry": list(dict.fromkeys(lst))[:cap]}
    return out


def _mark_theme_member_cache_health():
    """题材映射直接命中 themes.json 时，仍把两套成员缓存状态写入快照。"""
    for key, path, source, count_key in (
            ("ths_stock_concepts", config.THS_MEMBER_CACHE, "ths-detail-v4", "concepts"),
            ("ths_industry_members", config.THS_INDUSTRY_MEMBER_CACHE,
             "ths-industry-detail-v1", "industries")):
        blob = _read_json_file(path) if path.exists() else None
        st = blob.get("stat") if isinstance(blob, dict) else None
        if isinstance(st, dict) and st.get("member_source") == source:
            _source_mark(key, "cache", coverage=len(blob.get("map") or {}),
                         detail=f"{count_key}={st.get(count_key, 0)}")


def localize_theme_map(m, alias):
    """[历史兼容] 东财别名迁移函数；当前分类构建不调用此函数。"""
    amap = (alias or {}).get("map") or {}
    out = {}
    for c, d in (m or {}).items():
        ths, em = [], []
        for nm in d.get("themes", []):
            t = amap.get(nm)
            if t:
                # 换成同花顺名后必须再过一道黑名单：
                # 东财名干净不代表同花顺名干净（「次新股」「高股息精选」这类
                # 风格标签在两边都存在，但只有一边的写法会被原黑名单命中）
                if not _theme_ok(t):
                    continue
                if t not in ths:
                    ths.append(t)
            elif config.THEME.get("keep_em_fallback", True) and nm not in em:
                em.append(nm)
        if not ths and not em:
            continue
        out[c] = {"themes": ths[:config.THEME["max_per_stock"]],
                  "themes_em": em[:4],
                  "industry": (d.get("industry") or [])[
                      :config.THEME.get("max_industry_per_stock", 4)]}
    return out


def build_theme_map(force=False):
    """从手动维护的成员缓存构建个股→题材映射。

    缓存带配置指纹：展示规则改变时仅从本地成员缓存重新计算，
    不自动访问同花顺分类页。
    """
    p = config.CACHE_DIR / "themes.json"
    fp = _theme_fingerprint()
    if not force and p.exists():
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
            if blob.get("_fp") == fp and blob.get("map"):
                _mark_theme_member_cache_health()
                return blob["map"]
            print("[THEME] 展示口径变更，从本地成员缓存重建映射 ...")
        except Exception:
            pass
    print("[THEME] 构建同花顺概念/行业归属 ...")
    # 概念详情页成员名单是题材、板块、概念的唯一主源；行业详情页单独写入
    # industry，避免“元件”被错误压成父级“电子”，也避免行业进入题材榜。
    m = {}
    raw_members = {}
    try:
        raw_members = (build_ths_members().get("map") or {})
        for c, names in raw_members.items():
            m[str(c)] = {"themes": list(dict.fromkeys(names)),
                         "themes_em": [], "industry": []}
        print(f"[THEME] 同花顺概念成员覆盖 {len(raw_members)} 只")
    except Exception as e:
        print(f"[WARN] 同花顺概念成员不可用：{e}")
    try:
        ind_mem = (build_ths_industry_members().get("map") or {})
        if ind_mem:
            m = merge_industry_members(m, ind_mem)
            hit = sum(1 for d in m.values() if d.get("industry"))
            print(f"[THEME] 同花顺行业归属覆盖 {hit}/{len(m)} 只")
    except Exception as e:
        print(f"[WARN] 同花顺行业归属不可用：{e}")

    if m:
        # 成员缓存保留同花顺完整目录；因子板块映射只剔除属性、状态、风格和
        # 全市场类标签。不要按单股标签数截断，否则后面的有效概念会消失。
        pruned = prune_ths_members({"map": {
            str(c): list(names or []) for c, names in raw_members.items()
        }, "stat": {}})
        factor_members = pruned.get("map") or {}
        for c, row in m.items():
            row["themes"] = list(dict.fromkeys(factor_members.get(c) or []))
        p.write_text(json.dumps({"_fp": fp, "map": m}, ensure_ascii=False), encoding="utf-8")
    return m


# ─────────────────────────────────────────────────────
# 7. 本地缓存（sqlite）
# ─────────────────────────────────────────────────────
def migrate_volume_unit(conn):
    """一次性把存量K线的成交量统一成「股」。

    老库里的成交量是腾讯原始值：主板/创业板是「手」、科创板是「股」。
    写入侧已经改成统一乘系数，但历史行不会自动重算，所以这里补一次。
    用 meta 表打标记保证幂等 —— 迁移跑两遍会把主板量放大 10000 倍。
    """
    conn.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    done = conn.execute("SELECT v FROM meta WHERE k='vol_unit_shares'").fetchone()
    if done and done[0] == "1":
        return 0
    cur = conn.execute(
        "UPDATE kline SET volume = volume * 100 "
        "WHERE code NOT LIKE '688%' AND code NOT LIKE '689%' AND volume > 0")
    n = cur.rowcount or 0
    conn.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('vol_unit_shares','1')")
    conn.commit()
    print(f"[DB] 成交量单位迁移完成：{n} 行「手」→「股」（科创板本来就是股，跳过）")
    return n


def db():
    conn = sqlite3.connect(config.KLINE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS kline(
        code TEXT, date TEXT, open REAL, close REAL, high REAL, low REAL,
        volume REAL, amount REAL, PRIMARY KEY(code, date))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS board_kline(
        board TEXT, date TEXT, open REAL, close REAL, high REAL, low REAL,
        volume REAL, amount REAL, PRIMARY KEY(board, date))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_kline_date ON kline(date)")
    # 历史收盘价的复权方式必须可追溯；旧缓存没有来源字段，留空表示待核验。
    columns = {row[1] for row in conn.execute("PRAGMA table_info(kline)")}
    if "price_basis" not in columns:
        conn.execute("ALTER TABLE kline ADD COLUMN price_basis TEXT")
    if "price_basis_source" not in columns:
        conn.execute("ALTER TABLE kline ADD COLUMN price_basis_source TEXT")
    conn.commit()
    try:
        migrate_volume_unit(conn)
    except Exception as e:
        print(f"[WARN] 成交量单位迁移跳过：{type(e).__name__}: {e}")
    return conn


def save_klines(conn, table, key_name, data_map):
    """data_map: {code: list[dict]}"""
    rows = []
    if table == "kline":
        for code, ks in data_map.items():
            for k in ks:
                rows.append((code, k["date"], k["open"], k["close"], k["high"],
                             k["low"], k["volume"], k.get("amount", 0),
                             k.get("price_basis"), k.get("price_basis_source")))
        conn.executemany(
            f"INSERT OR REPLACE INTO {table}({key_name},date,open,close,high,low,volume,amount,price_basis,price_basis_source) "
            f"VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
    else:
        for code, ks in data_map.items():
            for k in ks:
                rows.append((code, k["date"], k["open"], k["close"], k["high"],
                             k["low"], k["volume"], k.get("amount", 0)))
        conn.executemany(
            f"INSERT OR REPLACE INTO {table}({key_name},date,open,close,high,low,volume,amount) "
            f"VALUES(?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return len(rows)


def load_kline(conn, table, key_name, code, limit=None):
    if table == "kline":
        q = (f"SELECT date,open,close,high,low,volume,amount,price_basis,price_basis_source "
             f"FROM {table} WHERE {key_name}=? ORDER BY date")
    else:
        q = f"SELECT date,open,close,high,low,volume,amount FROM {table} WHERE {key_name}=? ORDER BY date"
    rows = conn.execute(q, (code,)).fetchall()
    if table == "kline":
        ks = [{"date": r[0], "open": r[1], "close": r[2], "high": r[3],
               "low": r[4], "volume": r[5], "amount": r[6],
               "price_basis": r[7], "price_basis_source": r[8]} for r in rows]
    else:
        ks = [{"date": r[0], "open": r[1], "close": r[2], "high": r[3],
               "low": r[4], "volume": r[5], "amount": r[6]} for r in rows]
    return ks[-limit:] if limit else ks


if __name__ == "__main__":
    print("=== datafeed 自检 ===")
    print("外围 :", fetch_outer())
    print("东财 :", em_status())
    pool = build_pool()
    print("池子 :", len(pool))
    ks = fetch_kline("600519")
    print("K线  :", len(ks), ks[-1]["date"] if ks else "N/A")
    nm, bk = fetch_ths_board_kline("885642")
    print("板块 :", nm, len(bk), bk[-1]["date"] if bk else "N/A")
