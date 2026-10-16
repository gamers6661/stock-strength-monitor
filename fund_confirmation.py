"""候选股日级主力净额核验；东财不可用时使用新浪超大单+大单。"""
from datetime import datetime
import json

import config
import datafeed
import fund_history


MAX_CANDIDATES = 60


def _summarize(days, calendar):
    by_date = {d.get("date"): d.get("main_net") for d in days if isinstance(d, dict)}
    result = {}
    for n in (3, 5, 10):
        dates = calendar[-n:]
        result[n] = sum(by_date[d] for d in dates) / 1e8 if len(dates) == n and all(
            fund_history.number(by_date.get(d)) for d in dates) else None
    return result


def attach(stocks, calendar, fetch=True):
    """优先核验回踩候选，再核验其余趋势股；不影响排名和资格。"""
    asof = calendar[-1]
    path = config.CACHE_DIR / "fund_daily" / f"{asof}.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    cache = saved.get("stocks") if saved.get("asof") == asof else None
    cache = cache if isinstance(cache, dict) else {}
    # 优先使用全池补齐的同源资金历史；当日未收盘行由日历窗口自然排除。
    history=fund_history.load()
    for code,item in history.items():
        if not item.get('rows') and not (cache.get(code) or {}).get('rows'):
            cache[code]=item
        if item.get('rows'):
            prior=cache.get(code) or {}
            if len([r for r in item['rows'] if r['date']<=asof and fund_history.number(r.get('main_net'))]) >= len([r for r in prior.get('rows') or [] if r['date']<=asof and fund_history.number(r.get('main_net'))]):
                cache[code]=item
    preferred = sorted((s for s in stocks if s.get("trend_aligned")),
                       key=lambda s: (not bool(s.get("pullback_observe")),
                                      not bool(s.get("entry_watch")), -s["ret20"], s["code"]))
    chosen = preferred[:MAX_CANDIDATES]
    failures = 0
    if fetch:
        for s in chosen:
            code = s["code"]
            prior = cache.get(code) or {}
            if prior.get("rows"):
                if not prior.get("source"):
                    prior["source"] = "东财日级主力净额（旧缓存）"
                continue
            if prior.get("error_at") and prior.get("source") == "东财/新浪均失败":
                try:
                    if (datetime.now() - datetime.fromisoformat(prior["error_at"])).total_seconds() < 1800:
                        continue
                except ValueError:
                    pass
            if failures >= 3:
                break
            try:
                try:
                    rows = datafeed.fetch_em_fundflow(code, days=30)
                    source = "东财日级主力净额"
                except Exception:
                    rows = datafeed.fetch_sina_fundflow(code, days=30)
                    source = "新浪超大单+大单日级净额"
                if not rows:
                    raise ValueError("空资金日线")
                rows=[r for r in rows if r.get('date','')<=asof]
                if not rows or rows[-1]["date"] != asof:
                    raise ValueError("资金最新日期与完成日线不符")
                cache[code] = {"rows": rows, "source": source}
                failures = 0
            except Exception:
                cache[code] = {"error_at": datetime.now().isoformat(timespec="seconds"),
                               "source": "东财/新浪均失败"}
                failures += 1
        path.parent.mkdir(exist_ok=True)
        config.atomic_write_text(path, json.dumps({"asof": asof, "stocks": cache}, ensure_ascii=False))
    covered = 0
    positive = 0
    for s in stocks:
        nums = _summarize((cache.get(s["code"]) or {}).get("rows") or [], calendar)
        for n in (3, 5, 10):
            s[f"fund{n}_yi"] = round(nums[n], 3) if nums[n] is not None else None
        complete = all(nums[n] is not None for n in (3, 5, 10))
        s["fund_history_source"] = ((cache.get(s["code"]) or {}).get("source")
                                    or "东财日级主力净额（旧缓存）") if complete else None
        s["fund_asof"] = asof if complete else None
        s["fund_positive_all"] = all(s[f"fund{n}_yi"] > 0 for n in (3, 5, 10)) if complete else None
        s["fund_state"] = ("3/5/10日均净流入" if s["fund_positive_all"] else
                           "资金未全为正" if complete else "资金未知")
        item=cache.get(s['code']) or {}
        s['fund_history_days']=len({r['date'] for r in item.get('rows') or [] if r.get('date') in calendar[-20:] and fund_history.number(r.get('main_net'))})
        s['fund_history_reason']=None if complete else item.get('error') or (
            '同源资金仅覆盖'+str(s['fund_history_days'])+'个完成日' if item.get('rows') else '资金源尚未返回该股日级历史')
        covered += int(complete)
        positive += int(s["fund_positive_all"] is True)
    sources = {}
    for s in stocks:
        if s.get("fund_history_source"):
            key = s["fund_history_source"]
            sources[key] = sources.get(key, 0) + 1
    return {"source": "东财/新浪个股日级主力净额（按股标注）", "source_counts": sources,
            "asof": asof, "candidate_cap": MAX_CANDIDATES,
            "selected": len(chosen), "total":len(stocks), "covered": covered, "positive_all": positive,
            "scope": "全池同源历史优先；剩余候选按需核验，未知不视为流出"}
