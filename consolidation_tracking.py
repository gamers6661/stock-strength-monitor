"""MA10失守降级，MA20确认失守退出；历史资格与当前进攻分开。"""
import math
import config
import intraday_path


def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def review(setup, points, current, level, strict_trend, previous=None):
    prior = previous or {}
    migrated = bool(prior.get('trend_exited') and prior.get('exit_line') != 'MA20')
    exited = bool(prior.get('trend_exited')) and not migrated
    downgraded = bool(prior.get('ma10_downgraded'))
    below, above = prior.get('ma10_below_samples', 0), prior.get('ma10_recovery_samples', 0)
    below20, above20 = prior.get('ma20_below_samples', 0), prior.get('ma20_recovery_samples', 0)
    watermark = prior.get('tracking_at') or str(setup.get('completed_at') or prior.get('quote_at') or '')
    if migrated:
        # 旧MA10退出不能冒充MA20退出，重放真实采样核验；旧事件另存。
        watermark = str(setup.get('completed_at') or '')
        below20 = above20 = 0
        downgraded = True
    last = watermark
    need = config.TREND_CONSOLIDATION['confirmation_samples']
    limit = config.TREND_CONSOLIDATION['max_sample_gap_seconds']
    exited_at = None if migrated else prior.get('trend_exit_at')
    recovered_at = None if migrated else prior.get('trend_recovered_at')
    repaired20 = bool(prior.get('ma20_repaired_after_exit'))
    repaired10 = bool(prior.get('ma10_repaired_after_downgrade'))
    for point in list(points) + [current]:
        at = str(point.get('at') or '')
        if not at or at <= watermark:
            continue
        gap = intraday_path.gap_seconds(last, at)
        if gap is None or gap > limit or last[:10] != at[:10]:
            below = above = below20 = above20 = 0
        watermark = last = at
        if not point.get('valid') or not all(valid_number(point.get(k)) and point[k] > 0 for k in ('price', 'ma10', 'ma20')):
            below = above = below20 = above20 = 0
            continue
        if point['price'] < point['ma10']:
            below += 1
            above = 0
            if below >= need:
                downgraded = True
                repaired10 = False
        else:
            below = 0
            above = above + 1 if downgraded else 0
            if downgraded and above >= need:
                downgraded = False
                repaired10 = True
        if point['price'] < point['ma20']:
            below20 += 1
            above20 = 0
            if below20 >= need:
                if not exited:
                    exited_at = at
                exited = True
                repaired20 = False
        else:
            below20 = 0
            above20 = above20 + 1 if exited else 0
            if exited and above20 >= need:
                exited = False
                repaired20 = True
                recovered_at = at
    price, ma10, ma5 = current['price'], current['ma10'], current['ma5']
    ma20 = current.get('ma20')
    valid20 = valid_number(ma20) and ma20 > 0
    flags = current.get('flags') or []
    breakout_holds = price >= level
    completed = bool(setup.get('completion_confirmed') or setup.get('phase')=='completed')
    attack_holds = (completed and breakout_holds and price >= ma5 and strict_trend is True and not flags
                    and price >= ma10 and valid20 and price >= ma20 and not exited and not downgraded)
    if not valid20:
        state, stage, reason = 'ma20_pending', 'MA20待核验', '当前MA20口径不足，保留历史跟踪，不确认退出或进攻'
    elif exited:
        state = 'ma20_repair_pending' if price >= ma20 else 'ma20_lost'
        stage = 'MA20修复待确认' if price >= ma20 else '盘中确认失守MA20，退出跟踪'
        reason = '此前MA20已确认失守；需两次不同时间有效报价收复，修复后仍复核MA10及进攻条件' if price >= ma20 else '连续两次不同时间有效报价低于各自MA20边界'
    elif price < ma20:
        state, stage, reason = 'ma20_test', 'MA20试破待确认', '一次报价低于MA20，暂停进攻确认；连续两次失守才退出'
    elif price < ma10:
        state = 'ma10_downgraded' if downgraded else 'ma10_test'
        stage = 'MA10失守·降级观察MA20' if downgraded else 'MA10试破·降级观察'
        reason = 'MA10下方、MA20仍守住，继续观察MA20承接及反弹，不认定当前强势'
    elif downgraded:
        state, stage, reason = 'ma10_repair_pending', 'MA10修复待确认·继续观察', '此前MA10已失守，连续两次有效报价收复后才解除降级'
    elif not breakout_holds:
        state, stage = 'breakout_failed', '突破未站稳' if setup.get('completion_type') == '平台突破转强' else '修复回撤'
        reason = '当前低于原转强位置，取消本轮突破确认；仍守住MA20，保留趋势跟踪'
    elif price < ma5:
        state, stage, reason = 'ma5_pullback', '已转强·MA5回踩', '现价低于MA5，短线降温，继续趋势跟踪'
    elif strict_trend is not True:
        state, stage, reason = 'structure_cooling', '多头排列降温·继续观察', '当前多头排列减弱，但守住MA20；不维持当前进攻确认'
    elif flags:
        state, stage, reason = 'risk_cooling', '风险降级·继续观察', '守住MA20，但本轮出现风险信号：' + '、'.join(flags)
    elif repaired20:
        state, stage, reason = 'ma20_repaired', 'MA20已修复·继续跟踪', '已连续两次收复MA20；历史退出和修复事件保留，进攻条件独立复核'
    elif repaired10:
        state, stage, reason = 'ma10_repaired', 'MA10已修复·继续跟踪', '已连续两次收复MA10，解除降级；当前进攻条件独立复核'
    else:
        state, stage, reason = 'holding', '已整理完毕转强', '已确认整理转强，本轮守住均线及转强位置'
    if not completed and state in ('holding','breakout_failed','ma5_pullback'):
        stage = '整理中·MA5回踩' if state=='ma5_pullback' else '整理中·平台内观察'
        reason = '原合格整理仍在跟踪，当前守住MA20；尚未确认整理转强'
    return dict(tracking_state=state, stage=stage, reason=reason, trend_exited=exited, exit_line='MA20',
                ma10_below_samples=below, ma10_recovery_samples=above, ma10_downgraded=downgraded,
                ma20_below_samples=below20, ma20_recovery_samples=above20, tracking_at=watermark,
                trend_exit_at=exited_at, trend_recovered_at=recovered_at,
                legacy_ma10_exit_at=prior.get('legacy_ma10_exit_at') or (prior.get('trend_exit_at') if migrated else None),
                ma10_repaired_after_downgrade=repaired10, ma20_repaired_after_exit=repaired20,
                current_breakout_confirmed=attack_holds, completion_position_holds=breakout_holds,
                current_ma5_holds=price >= ma5, tracking_ma10=ma10, tracking_ma5=ma5, tracking_ma20=ma20,
                live_trend_online=strict_trend, tracking_price=price, tracking_quote_at=current['at'], risk_flags=flags)
