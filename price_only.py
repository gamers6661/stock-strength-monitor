"""当前资金参考退场；保留空字段兼容历史文件，不复用旧资金参与的判断。"""
import math
import config

VERSION = '不使用资金流1'


def disabled_fund():
    return dict(score=None, weight=0., ratio=None, status='已停用', source=None, at=None)


def clear_rows(rows):
    for row in rows:
        row['factors'] = dict(row.get('factors') or {}, fund=None)
        for key in ('fund_today_yi', 'fund_today_ratio', 'fund_today_source', 'fund_today_at',
                    'fund3_yi', 'fund5_yi', 'fund10_yi', 'fund_asof', 'fund_positive_all',
                    'fund_history_source', 'fund_history_reason'):
            row[key] = None
        row.update(fund_state='已停用', fund_history_days=0, live_attack_fund=disabled_fund())
        last = row.get('intraday_last_judgment') or {}
        if (last.get('fund') or {}).get('weight', 0) > 0:
            last.update(attack_score=None, attack_tier=None, attack=False, fund=disabled_fund())


def sanitize(snap):
    """发布入口也清理旧快照，防止旧资金缓存通过页面或重建入口重新出现。"""
    snap.update(fund_reference_version=VERSION, fund_available=False, fund_source='已停用',
                fund_meta=dict(source='已停用', enabled=False, stale=False, coverage=0),
                fund_history=dict(enabled=False, requested=0),
                fund_confirmation=dict(enabled=False, total=0, covered=0, positive_all=0, source_counts={}))
    rows = (snap.get('stocks') or []) + (snap.get('coverage_catalog') or [])
    clear_rows(rows)
    snap['fund_confirmation']['total'] = len(rows)
    for row in rows + ((snap.get('attack_monitor') or {}).get('rows') or []):
        if row.get('live_attack_price_score') is not None:
            row['live_attack_score'] = row['live_attack_price_score']
            row['live_attack_tier'] = row.get('live_attack_price_tier')
        else:
            row['live_attack_score'] = row['live_attack_tier'] = None
        row['live_attack_fund'] = disabled_fund()
    monitor = snap.get('attack_monitor') or {}
    monitor['rows'] = [r for r in monitor.get('rows') or [] if isinstance(r.get('live_attack_score'), (float, int))
                       and math.isfinite(r['live_attack_score']) and r.get('live_attack_tier') == 'A']
    for board in (snap.get('boards') or []) + (snap.get('board_catalog') or []):
        board.update(fund=None, fund_src='已停用', fund_covered=0, fund_today_covered=0,
                     fund_sum_5d=None, fund_sum_today=None, fund_observed_at=None)
    # 旧快照的板块综合分也可能混入资金，按原有其余维度比例重算。
    for board in snap.get('boards') or []:
        values = [(config.BOARD_WEIGHTS[k], board.get(k)) for k in ('rs', 'momentum', 'linkage')
                  if isinstance(board.get(k), (int, float)) and math.isfinite(board[k])]
        board['score'] = round(sum(w*v for w,v in values)/sum(w for w,v in values)*board.get('gate', 1), 2) if values else None
    snap['boards'] = sorted(snap.get('boards') or [], key=lambda b: -(b.get('score') or 0))
    for rank, board in enumerate(snap['boards'], 1):
        board['rank'] = rank
    return snap
