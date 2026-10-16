"""统一板块成员图和板块内候选名单。指数走势与主板成员观察分列。"""
import json
from collections import defaultdict
from statistics import mean, median

import config
import stock_strength

VERSION = '板块成员完整3'


def _catalog():
    """目录入口与个股的首个细分归属分开，零覆盖板块也保留查询入口。"""
    import datafeed
    out = {'industry': set(), 'theme': set()}
    for kind, path in (('industry',config.THS_INDUSTRY_CACHE),('theme',config.THS_CONCEPT_CACHE)):
        try:
            blob = json.loads(path.read_text(encoding='utf-8'))
            names = set((blob.get('detail') or {}).values())
            out[kind] = {n for n in names if n and (kind == 'industry' or datafeed._theme_ok(n))}
        except (OSError, ValueError):
            pass
    return out


def _cache(filename):
    path = config.CACHE_DIR / filename
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("map") or {}, data.get("stat") or {}, path.stat().st_mtime
    except (OSError, ValueError):
        return {}, {}, None


def _reverse(code_to_names):
    out = defaultdict(set)
    for code, names in code_to_names.items():
        for name in set(names or []):
            out[name].add(code)
    return out


def _avg(rows, key):
    return round(mean(r[key] for r in rows), 2) if rows else None


def build(stocks, quotes, theme_map, index_boards, fund_map, asof):
    """所有入口共用 id/member_codes；源成员数明确是详情缓存，不冒充完整板块。"""
    valid = {s["code"]: s for s in stocks}
    pool = set(quotes)
    groups = defaultdict(set)
    pool_groups = defaultdict(set)
    for s in stocks:
        if s.get("primary_industry"):
            groups["industry:" + s["primary_industry"]].add(s["code"])
        for name in s.get("display_boards") or s.get("boards") or []:
            groups["theme:" + name].add(s["code"])
    for code, item in theme_map.items():
        if code not in pool:
            continue
        industry = (item.get("industry") or [])
        if industry:
            pool_groups["industry:" + industry[0]].add(code)
        for name in item.get("browse_themes") or item.get("themes") or []:
            pool_groups["theme:" + name].add(code)
    theme_detail_map, theme_stat, theme_checked = _cache("ths_members.json")
    industry_detail_map, industry_stat, industry_checked = _cache("ths_industry_members.json")
    detail_themes = _reverse(theme_detail_map)
    detail_industries = _reverse(industry_detail_map)
    catalog = _catalog()
    catalog_ids = set()
    for kind, names in catalog.items():
        detail = detail_themes if kind == 'theme' else detail_industries
        for name in names:
            board_id = kind+':'+name
            catalog_ids.add(board_id)
            # 只取该名称在同花顺详情中的真实成员，不把细分行业改名成上位行业。
            official = detail.get(name,set()) & pool
            verified_industry = (kind == 'industry'
                                 and name not in (industry_stat.get('failed') or [])
                                 and industry_stat.get('complete_counts', {}).get(name) == len(detail.get(name, set()))
                                 and bool(detail.get(name)))
            if verified_industry:
                # 完整同源指数成分优先，旧F10中的移除成员不混入正式行业入口。
                # 个股首个细分归属和未取得完整名单的旧归集均不改动。
                pool_groups[board_id] = set(official)
                groups[board_id] = official & set(valid)
            else:
                pool_groups[board_id].update(official)
                groups[board_id].update(official & set(valid))
    index = {b["name"]: b for b in index_boards}
    market_ret5 = _avg(stocks, "ret5") or 0
    market_trend = mean(bool(s.get("trend_online")) for s in stocks) * 100 if stocks else 0
    market_active = mean(bool(s.get("emotion_strong")) for s in stocks) * 100 if stocks else 0
    out = []
    for board_id in sorted(set(pool_groups) | set(groups) | catalog_ids):
        kind, name = board_id.split(":", 1)
        codes = sorted(groups.get(board_id, ()))
        members = [valid[c] for c in codes]
        pool_codes = pool_groups.get(board_id, set()) | set(codes)
        source_codes = (detail_themes if kind == "theme" else detail_industries).get(name)
        failed = set((theme_stat if kind == "theme" else industry_stat).get("failed") or [])
        detail_count = len(source_codes) if source_codes and name not in failed else None
        disagreement_codes = pool_codes | ((source_codes or set()) & pool)
        disagreement = sum(name in ((theme_map.get(c) or {}).get("member_only_themes") or [])
                           or name in ((theme_map.get(c) or {}).get("f10_only_themes") or [])
                           for c in disagreement_codes) if kind == "theme" else None
        detail_reliable = (detail_count is not None and detail_count >= len(pool_codes)
                           and (disagreement is None or disagreement == 0))
        # 详情成员数小于已确认的主板池成员，或与 F10 有差异时，不称其完整。
        source_count = detail_count if detail_reliable else len(pool_codes)
        source_basis = (("同花顺概念详情成员缓存" if kind == "theme" else "同花顺行业完整成员接口缓存" if industry_stat.get('member_endpoint') else "同花顺行业详情成员缓存")
                        if detail_reliable else
                        "同花顺F10与概念详情合并归集（本系统主板池）" if kind == "theme"
                        else "同花顺行业归集（本系统主板池）")
        ranked = sorted(members, key=lambda s: (-s.get("stock_strength_score", 0), s["code"]))
        positions = {s["code"]: i for i, s in enumerate(ranked, 1)}
        sum5 = sum(s["ret5"] for s in members)
        sum20 = sum(s["ret20"] for s in members)
        trend = [sum(bool(s.get(key)) for s in members) for key in
                 ("trend_online_prev2", "trend_online_prev", "trend_online")]
        trend_pct = round(trend[2] / len(members) * 100, 1) if members else None
        active = sum(bool(s.get("emotion_strong")) for s in members)
        active_pct = round(active / len(members) * 100, 1) if members else None
        prior_strong = [s for s in members if s.get("emotion_yesterday_strong")
                        and s.get("change_pct") is not None]
        positive = sorted((max(0, s.get("change_pct") or 0) for s in members), reverse=True)
        positive_sum = sum(positive)
        top3_share = round(sum(positive[:3]) / positive_sum * 100, 1) if positive_sum else None
        fund_codes = [c for c in codes if (fund_map.get(c) or {}).get("main_5d") is not None]
        fund_sum = round(sum(fund_map[c]["main_5d"] for c in fund_codes), 0) if fund_codes else None
        fund_today_codes = [c for c in codes if (fund_map.get(c) or {}).get("main_today") is not None]
        fund_today_sum = (round(sum(fund_map[c]["main_today"] for c in fund_today_codes), 0)
                          if fund_today_codes else None)
        min_members = config.SIMPLE_STRENGTH["min_industry_peers"] + 1
        eligible = len(members) >= min_members
        coverage_pct = round(len(members) / len(pool_codes) * 100, 2) if pool_codes else 0.0
        trend_state = ("小样本，仅供查询" if not eligible else
                       "持续扩散" if trend[0] < trend[1] < trend[2] and trend_pct > market_trend else
                       "扩散回落" if trend[2] < trend[1] else
                       "单日改善" if trend[2] > trend[1] else
                       "参与稳定" if trend_pct >= market_trend else "未见扩散")
        relation = []
        for s in ranked:
            other_n = len(members) - 1
            peer5 = (sum5 - s["ret5"]) / other_n if eligible else None
            peer20 = (sum20 - s["ret20"]) / other_n if eligible else None
            excess5 = round(s["ret5"] - peer5, 2) if peer5 is not None else None
            excess20 = round(s["ret20"] - peer20, 2) if peer20 is not None else None
            role = ("趋势强势" if s.get("persistent_strong") else
                    "板块内相对领先" if positions[s["code"]] == 1 else "成员观察")
            relation.append({"code": s["code"], "name": s.get("name"),
                             "rank": positions[s["code"]], "score": s.get("stock_strength_score"),
                             "global_rank": s.get("stock_strength_rank"),
                             "global_percentile": s.get("stock_strength_percentile"),
                             "ret5": s["ret5"], "ret20": s["ret20"],
                             "change_pct": s.get("change_pct"),
                             "excess5": excess5, "excess20": excess20,
                             "role": role, "trend_online": bool(s.get("trend_online")),
                             "strength_motion": s.get("stock_strength_motion"),
                             "emotion_heat": s.get("emotion_heat"),
                             "emotion_strong": bool(s.get("emotion_strong")),
                             "limit_today": bool(s.get("emotion_limit"))})
        trend_list = [r for r in relation if valid[r["code"]].get("persistent_strong")]
        recent_list = [r for r in relation if valid[r["code"]].get("recent_improving")]
        recent_list.sort(key=lambda r: (-valid[r["code"]].get("strength_accel5_pp", 0), -r["score"]))
        emotion_list = [r for r in relation if r["emotion_strong"]]
        emotion_list.sort(key=lambda r: (-int(r["limit_today"]),
                                         -valid[r["code"]].get("emotion_active_days3", 0),
                                         -r["change_pct"]))
        index_ref = index.get(name) if kind == "theme" else None
        out.append({"id": board_id, "type": kind, "name": name,
                    "catalog_listed": board_id in catalog_ids,
                    "membership_stale": name in failed,
                    "coverage_state": ('成员待补齐' if not pool_codes else
                                       '日线待补齐' if not members else '已覆盖'),
                    "wide": kind == "theme" and len(members) > 60,
                    "source_members": source_count, "source_basis": source_basis,
                    "source_complete": detail_reliable,
                    "detail_members_cached": detail_count,
                    "source_scope": "详情缓存" if detail_reliable else "本系统主板池",
                    "source_checked_at": (theme_checked if kind == "theme" else industry_checked),
                    "membership_disagreements": disagreement,
                    "pool_members": len(pool_codes), "valid_members": len(members),
                    "ranking_eligible": eligible, "ranking_min_members": min_members,
                    "valid_coverage_pct": coverage_pct,
                    "ranking_reason": (f"至少{min_members}只有效成员；覆盖当前主板成员{coverage_pct:.1f}%"
                                       if eligible else f"有效成员少于{min_members}只，不参与正式排名"),
                    "list_criteria": {"trend": stock_strength.PERSISTENT_CRITERION,
                                      "recent": "统一近期增强资格：增强或修复、全体分位≥50、5日收益为正"},
                    "quote_covered": sum(bool(quotes.get(c, {}).get("price")) for c in pool_codes),
                    "member_codes": sorted(pool_codes), "asof": asof,
                    "member_ret5": _avg(members, "ret5"), "member_ret20": _avg(members, "ret20"),
                    "member_today": _avg(members, "change_pct"),
                    "trend_pct": trend_pct, "trend_delta1_pp":
                    round((trend[2] - trend[1]) / len(members) * 100, 1) if members else None,
                    "trend_state": trend_state,
                    "trend_vs_market_pp": round(trend_pct - market_trend, 1) if trend_pct is not None else None,
                    "emotion_pct": active_pct,
                    "emotion_vs_market_pp": round(active_pct - market_active, 1) if active_pct is not None else None,
                    "limit_count": sum(bool(s.get("emotion_limit")) for s in members),
                    "yesterday_limit_count": sum(bool(s.get("emotion_yesterday_limit")) for s in members),
                    "prior_strong_today_median": round(median(s["change_pct"] for s in prior_strong), 2)
                    if prior_strong else None,
                    "prior_strong_up_pct": round(sum(s["change_pct"] > 0 for s in prior_strong)
                                                 / len(prior_strong) * 100, 1) if prior_strong else None,
                    "prior_strong_count": len(prior_strong),
                    "positive_top3_share": top3_share,
                    "fund_covered": len(fund_codes), "fund_sum_5d": fund_sum,
                    "fund_today_covered": len(fund_today_codes), "fund_sum_today": fund_today_sum,
                    "index_trend": ({"code": index_ref["idx_code"], "ret1": index_ref["ret1"],
                                     "ret5": index_ref["ret5"], "ret20": index_ref["ret20"],
                                     "source": "同花顺概念指数（含非主板成员）"}
                                    if index_ref else None),
                    "members": relation, "lists": {"trend": [r["code"] for r in trend_list],
                                                    "recent": [r["code"] for r in recent_list],
                                                    "emotion": [r["code"] for r in emotion_list]}})
    # 趋势榜仅用主板成员的完成日线；今日情绪另排序，不混用概念指数。
    out.sort(key=lambda b: (not b["ranking_eligible"],
                           -(b["trend_pct"] or 0) if b["ranking_eligible"] else 0,
                           -b["valid_coverage_pct"] if b["ranking_eligible"] else 0,
                           -b["valid_members"] if b["ranking_eligible"] else 0,
                           -(b["member_ret5"] or 0) if b["ranking_eligible"] else 0, b["name"]))
    rank = 0
    for b in out:
        if b["ranking_eligible"]:
            rank += 1
        b["trend_rank"] = rank if b["ranking_eligible"] else None
    return out
