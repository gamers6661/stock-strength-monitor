# -*- coding: utf-8 -*-
"""数据源小型基准测试。

只做少量探测，不跑全量扫描、不改快照、不改变因子。用于确认网络恢复后
各源的实时延迟、覆盖量与可用性；结果写入 cache/source_benchmark.json。
"""
import json
import os
import time
from datetime import datetime

import config
import datafeed as df


def _probe(name, fn):
    t0 = time.time()
    try:
        value = fn()
        elapsed = round(time.time() - t0, 2)
        if isinstance(value, tuple):
            count, total, detail = value
        else:
            count, total, detail = value, None, None
        return {"name": name, "status": "ok", "elapsed_s": elapsed,
                "count": count, "total": total, "detail": detail}
    except Exception as e:
        return {"name": name, "status": "error",
                "elapsed_s": round(time.time() - t0, 2),
                "error": f"{type(e).__name__}: {e}"}


def run():
    pool = json.loads(config.POOL_CACHE.read_text(encoding="utf-8")) if config.POOL_CACHE.exists() else {}
    codes = list(pool)[:20] or ["600000", "000001", "300750", "688981"]

    rows = []
    def ths_catalog_probe():
        catalog = df.fetch_ths_concept_catalog(force=True)
        return (len(catalog.get("detail") or {}), len(catalog.get("index") or {}),
                "概念名 / 当前活跃885xxx映射")

    rows.append(_probe("同花顺概念目录", ths_catalog_probe))

    def ths_sample():
        catalog = df.fetch_ths_concept_catalog()
        ids = list((catalog.get("index") or {}).keys())[:3]
        hit = 0
        for idx in ids:
            obj = df._ths_board_kline_raw(idx)
            hit += int(bool(obj and obj.get("data")))
        return hit, len(ids), "同花顺板块日线样本"

    rows.append(_probe("同花顺板块日线(3样本)", ths_sample))
    rows.append(_probe("腾讯实时行情(20只)", lambda: (
        len(df.tencent_quotes(codes)), len(codes), "实时价格/成交量/成交额")))
    rows.append(_probe("东财板块实时(1页)", lambda: (
        len(df.fetch_em_boards(pz=100, max_page=1)), 100, "主力净流入/涨跌家数")))
    rows.append(_probe("东财资金流(1页)", lambda: (
        len(df.fetch_em_fundflow_all(pz=100, max_page=1)), 100, "全量任务按总数分页")))

    token = bool(os.environ.get("TUSHARE_TOKEN"))
    rows.append({"name": "Tushare备用", "status": "configured" if token else "not_configured",
                 "elapsed_s": 0, "detail": "需要用户自己的 TUSHARE_TOKEN 与相应积分权限"})

    result = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "recommendation": {
                  "concept": "同花顺概念目录",
                  "realtime": "腾讯批量行情",
                  "enhancement": "东财资金流（成功时）",
                  "fallback": "最近成功缓存（15分钟内）→题材组/成交额代理",
              },
              "rows": rows,
              "health": df.source_health_snapshot()}
    config.atomic_write_text(config.SOURCE_HEALTH_CACHE,
                             json.dumps({"saved_at": time.time(),
                                         "health": result["health"]}, ensure_ascii=False,
                                        indent=2))
    config.atomic_write_text(config.CACHE_DIR / "source_benchmark.json",
                             json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    run()
