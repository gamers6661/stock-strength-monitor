"""同花顺题材的逐项关系；不代股票事后挑一个最好看的题材。"""
from collections import defaultdict
from statistics import mean
import scan_cache


MIN_PEERS = 5


def _daily_stats(rows):
    members = defaultdict(list)
    for row in rows:
        for name in set(row.get('boards') or []):
            members[name].append(row)
    market_ret5 = mean(r['ret5'] for r in rows)
    stats = []
    for row in rows:
        item = {}
        for name in dict.fromkeys(row.get('boards') or []):
            peers = [r for r in members[name] if r['code'] != row['code']]
            item[name] = {'size': len(peers)}
            if len(peers) >= MIN_PEERS:
                item[name].update(trend=[sum(bool(p.get(key)) for p in peers) for key in
                    ('trend_online_prev2', 'trend_online_prev', 'trend_online')],
                    excess5=mean(p['ret5'] for p in peers)-market_ret5)
        stats.append(item)
    return stats


def enrich_stocks(rows):
    members = defaultdict(list)
    for row in rows:
        for name in set(row.get("boards") or []):
            members[name].append(row)
    if not rows:
        return rows
    daily = [{k:r.get(k) for k in ('code','boards','ret5','trend_online_prev2','trend_online_prev','trend_online')}
             for r in rows]
    stats = scan_cache.cached('theme_daily', 'current_pool',
        [scan_cache.rules('theme_assist.py'), daily, MIN_PEERS], lambda: _daily_stats(daily))
    member_sets = {name: {p['code'] for p in group} for name, group in members.items()}
    overlap = {}
    # Only daily relationships are cached. Current emotion/limits are aggregated anew.
    totals, own = {}, {}
    emotion_keys = ('emotion_strong','emotion_limit','emotion_yesterday_limit')
    for name, group in members.items():
        totals[name] = [sum(bool(p.get(k)) for p in group) for k in emotion_keys]
        by_code = defaultdict(lambda: [0,0,0])
        for p in group:
            for j,k in enumerate(emotion_keys):
                by_code[p['code']][j] += bool(p.get(k))
        own[name] = by_code
    market_trend = mean(bool(r.get("trend_online")) for r in rows) * 100
    market_active = mean(bool(r.get("emotion_strong")) for r in rows) * 100
    market_ret5 = mean(r["ret5"] for r in rows)
    for row_index, row in enumerate(rows):
        relations = []
        for name in dict.fromkeys(row.get("boards") or []):
            daily_peer = stats[row_index][name]
            size = daily_peer['size']
            rel = {"id": "theme:" + name, "name": name, "peers": size,
                   "wide": size >= 60, "source": row.get("theme_basis"),
                   "checked_at": row.get("theme_checked_at"),
                   "state": "数据不足", "reason": "有效同伴少于5只"}
            if row.get("theme_basis") == "同花顺详情成员待F10核对":
                rel["reason"] = "个股F10尚未核对归属"
            elif size >= MIN_PEERS:
                trend = daily_peer['trend']
                rising_days = int(trend[1] > trend[0]) + int(trend[2] > trend[1])
                trend_pct = trend[2] / size * 100
                excess5 = daily_peer['excess5']
                active = totals[name][0]-own[name][row['code']][0]
                active_pct = active / size * 100
                limit_now = totals[name][1]-own[name][row['code']][1]
                limit_prior = totals[name][2]-own[name][row['code']][2]
                trend_support = trend_pct >= market_trend + 5 and rising_days >= 1 and excess5 > 0
                emotion_support = (active >= 2 and active_pct >= market_active + 5
                                   and limit_now >= 1 and limit_now > limit_prior)
                state = ("趋势与情绪共同扩散" if trend_support and emotion_support else
                         "趋势扩散" if trend_support else "情绪扩散" if emotion_support else "未见扩散")
                rel.update(state=state, reason="主板有效同伴，已剔除本股",
                           trend_pct=round(trend_pct, 2), trend_rising_days2=rising_days,
                           ret5_ex_market=round(excess5, 2), active_pct=round(active_pct, 2),
                           limit_now=limit_now, limit_prior=limit_prior)
            relations.append(rel)
        for i, rel in enumerate(relations):
            rel["overlap_group"] = rel["id"]
            mine = member_sets[rel['name']]
            for previous in relations[:i]:
                other = member_sets[previous['name']]
                pair = tuple(sorted((rel['name'], previous['name'])))
                if pair not in overlap:
                    overlap[pair] = bool(mine and other and len(mine & other) / len(mine | other) >= .6)
                if overlap[pair]:
                    rel["overlap_group"] = previous["overlap_group"]
                    break
        row["theme_relations"] = relations
        row["theme_candidate_count"] = len(relations)
        row["theme_assist"] = "按题材分别查看" if relations else "数据不足"
        row["theme_assist_name"] = None
        row["theme_selection_reason"] = "不自动挑选最有利题材；从板块进入时使用对应板块关系"
        row["theme_peer_count"] = None
    return rows
