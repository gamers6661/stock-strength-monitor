"""趋势候选关注层级；全体强度排名保持独立。"""
import config
import attack_model


def build_opportunities(snap, quotes, pool, price_contexts, histories, calendar,
                        previous=None, state=None, persist=False, now=None):
    """全部主板合格样本可进入，日线分档保持原样。"""
    import market_strength
    return market_strength.attach(snap,quotes,pool,histories,calendar,
                                  contexts=price_contexts,now=now,previous=previous)

FACTOR_ORDER = config.STRATEGY['factors']['trend']


def tiers():
    return [dict(t) for t in config.RADAR['tiers']]


def assign_trend_tiers(stocks):
    """名次仅展示；档位由实际进攻条件决定，不设池内百分比名额。"""
    pool = sorted((s for s in stocks if s.get('watch_candidate')),
                  key=lambda s: (-s.get('stock_strength_score', 0), s['code']))
    size = len(pool)
    for s in stocks:
        s['trend_pool_rank'] = None
        s['trend_pool_percentile'] = None
        s['trend_tier'] = None
        s['trend_tier_name'] = '趋势未在线'
    for rank, s in enumerate(pool, 1):
        s['trend_pool_rank'] = rank
        s['trend_pool_percentile'] = round((size-rank)/max(size-1, 1)*100, 2)
        key = attack_model.tier(s.get('stock_strength_score'),
                                {5: s.get('ret5'), 10: s.get('ret10'), 20: s.get('ret20')},
                                True, s.get('past_impulse5_pct')) or 'C'
        s['trend_tier'] = key
        s['trend_tier_name'] = {'A': '进攻强势', 'B': '进攻观察',
                                'C': '结构在线'}[key]
    return size


def build_trend(stocks, cap=None):
    cap = cap or config.RADAR['show_per_tier']
    pool_size = assign_trend_tiers(stocks)
    definitions = tiers()
    counts = {t['key']: 0 for t in definitions}
    shown = {t['key']: 0 for t in definitions}
    items = []
    ranked = sorted((s for s in stocks if s.get('watch_candidate')),
                    key=lambda s: (s['trend_pool_rank'], s['code']))
    for s in ranked:
        key = s['trend_tier']
        counts[key] += 1
        if shown[key] >= cap:
            continue
        strong = [f"全体强度第{s.get('stock_strength_rank', '—')}名；趋势池第{s['trend_pool_rank']}名；"
                  f"自身得分{s.get('stock_strength_score', 0):.1f}",
                  f"5日{s.get('ret5', 0):+.1f}%，10日{s.get('ret10', 0):+.1f}%，20日{s.get('ret20', 0):+.1f}%；"
                  f"形态：{s.get('daily_attack_stage', '待核验')}"]
        risk = list(s.get('risk_notes') or [])
        row = {k: s.get(k) for k in ('code', 'name', 'board_name', 'board_type',
                                     'board_limit', 'is_new', 'list_days', 'price',
                                     'ret5', 'ret20', 'dist_atr', 'limit_today',
                                     'limit_streak')}
        row.update(chg=s.get('change_pct'), tier=key,
                   tier_name=s['trend_tier_name'],
                   score=s.get('stock_strength_percentile'),
                   global_rank=s.get('stock_strength_rank'),
                   pool_rank=s['trend_pool_rank'],
                   pool_percentile=s['trend_pool_percentile'],
                   f=[{'k': k, 'label': label, 'v': (s.get('factors') or {}).get(k)}
                      for k, label in FACTOR_ORDER],
                   style=s.get('entry_state'),
                   why='关注层级只用于趋势候选分组，不代表买点或胜率。',
                   strong=strong, risk=risk, risk_hi=s.get('overheated'),
                   dist_band='位置偏热' if s.get('overheated') else '未触发过热阈值',
                   themes=(s.get('display_boards') or s.get('boards') or [])[:3])
        items.append(row)
        shown[key] += 1
    return {'tiers': [dict(t, n=counts[t['key']], shown=shown[t['key']])
                      for t in definitions],
            'below': 0, 'excluded': len(stocks)-pool_size,
            'total': pool_size, 'cap': cap,
            'strong_q': config.RADAR['strong_q'],
            'weak_q': config.RADAR['weak_q'],
            'items': items, 'board_names': config.pool_board_names()}
