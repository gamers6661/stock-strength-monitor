"""主板成员机会。只消费已有数据；独立于指数状态机和个股评分。"""
import copy
import hashlib
import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from statistics import mean, median

import config
import intraday
import board_trend
import scan_cache

VERSION = '板块机会规则2026-10-12.1'
LABELS = ('回踩再启动', '持续强势', '新启动')


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def stamp(value):
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def identity(codes):
    return hashlib.sha256(json.dumps(sorted(set(codes))).encode()).hexdigest()[:20]


def session_part(at):
    if at is None:
        return None
    minute = at.hour * 60 + at.minute
    return 'AM' if 570 <= minute <= 690 else 'PM' if 780 <= minute <= 900 else None


def confirmation(old, meets, sample_at, day, members_hash, session, count, span):
    """重复源批不计数；所有断点重置，首次确认仅保留同日同规则同成员记录。"""
    p = config.BOARD_OPPORTUNITY
    at = stamp(sample_at)
    scope = [VERSION, day, members_hash]
    old = old if old and old.get('scope') == scope else {}
    first_confirmed = old.get('first_confirmed_at')
    base = dict(scope=scope, part=session_part(at), count=0, span_seconds=0,
                first_sample_at=None, last_sample_at=None, confirmed=False,
                first_confirmed_at=first_confirmed,
                last_observed_at=max(filter(None, [old.get('last_observed_at'), sample_at]), default=None))
    if not meets or at is None or at.date().isoformat() != day:
        return base
    if session not in ('早盘', '午盘', '尾盘'):
        # 收盘复核可撤销，但不能补采确认。午休由 enrich 保留上午完整结果。
        if session == '已收盘' and old.get('part') == 'PM':
            return copy.deepcopy(old)
        return base
    part = session_part(at)
    if part != ('AM' if session == '早盘' else 'PM'):
        return base
    seen = stamp(old.get('last_observed_at'))
    if old.get('part') == part and seen and at <= seen:
        return copy.deepcopy(old) if at == seen and old.get('count') else base
    last = stamp(old.get('last_sample_at'))
    if old.get('part') == part and last:
        gap = (at-last).total_seconds()
        if gap == 0:
            return copy.deepcopy(old)
        if 0 < gap <= p['max_sample_gap_seconds']:
            base = copy.deepcopy(old)
    base.update(count=base['count']+1, last_sample_at=sample_at)
    base['last_observed_at'] = sample_at
    base['first_sample_at'] = base.get('first_sample_at') or sample_at
    base['span_seconds'] = (at-stamp(base['first_sample_at'])).total_seconds()
    base['confirmed'] = base['count'] >= count and base['span_seconds'] >= span
    if base['confirmed'] and not base.get('first_confirmed_at'):
        base['first_confirmed_at'] = sample_at
    return base


def check(key, actual, threshold, passed):
    return dict(key=key, actual=actual, threshold=threshold, passed=passed)


def ge(key, actual, threshold):
    return check(key, actual, '≥ '+str(threshold), actual >= threshold if number(actual) and number(threshold) else None)


def positive(key, actual):
    return check(key, actual, '> 0', actual > 0 if number(actual) else None)


def verdict(checks):
    if any(c['passed'] is False for c in checks):
        return False
    return None if any(c['passed'] is None for c in checks) else True


def trimmed(values):
    p = config.BOARD_OPPORTUNITY
    if len(values) < p['min_members']:
        return None, 0
    n = p['trim_small_count'] if len(values) <= p['small_sample_max'] else p['trim_large_count']
    return mean(sorted(values)[:-n]), n


def collect(snapshot, quotes, pool, now, session, excluded_names=None):
    """当前主板池为分母，缺失不剔除；报价可覆盖尚不能评分成员。"""
    rows = {str(r['code']): r for r in (snapshot.get('stocks') or []) + (snapshot.get('coverage_catalog') or [])}
    scored = {str(r['code']) for r in snapshot.get('stocks') or [] if not r.get('coverage_only')}
    asof = (snapshot.get('strength_model') or {}).get('asof')
    pool = {str(c): v for c, v in pool.items()}
    excluded, eligible, audit = {}, set(), {}
    candidate_times = []
    for code in pool:
        q = quotes.get(code) or {}
        at = intraday.parse_quote_timestamp(q.get('quote_at') or q.get('ts'), now)
        if at and at.date() == now.date() and -config.INTRADAY['max_quote_future_seconds'] <= (now-at).total_seconds() and ((session == '已收盘' and at.hour*60+at.minute >= 900) or (now-at).total_seconds() <= config.INTRADAY['max_quote_age_seconds']):
            candidate_times.append(at)
    center = intraday._median_datetime(candidate_times)
    daily, current, events = {}, {}, {}
    for code, meta in pool.items():
        row, q = rows.get(code) or {}, quotes.get(code) or {}
        kind = q.get('board_type') or meta.get('board_type') or config.board_of(code)[0]
        if kind not in ('sh_main', 'sz_main') or kind not in config.pool_boards():
            continue
        name = (excluded_names or {}).get(code) or q.get('name') or row.get('name') or meta.get('name') or ''
        if any(k in name for k in config.POOL['exclude_keywords']):
            excluded[code] = 'ST/退市/风险警示'
            continue
        at, reason, _ = intraday._fresh_quote(q, now, center, True, session)
        timed_nontrade = bool(at and at.date() == now.date() and session_part(at)
                              and -config.INTRADAY['max_quote_future_seconds'] <= (now-at).total_seconds() <= config.INTRADAY['max_quote_age_seconds']
                              and (center is None or abs((at-center).total_seconds()) <= config.INTRADAY['max_quote_batch_skew_seconds'])
                              and row.get('trade_status') == 'no_trade'
                              and (number(q.get('amount_wan')) or number(q.get('volume_shou')))
                              and not intraday._positive(q.get('amount_wan')) and not intraday._positive(q.get('volume_shou')))
        # 沿用正式收盘报价核验；盘后时间不推进确认序列。
        if session == '已收盘':
            if at and at.date() == now.date() and at.hour*60+at.minute >= 900 and (at-now).total_seconds() <= config.INTRADAY['max_quote_future_seconds']:
                at, reason, _ = intraday._fresh_quote(q, at, center, True, None)
            else:
                reason = '尚无同日15:00后有效收盘源报价'
        if reason == '当日无成交或停牌' or timed_nontrade:
            excluded[code] = '当日已确认无成交'
            continue
        eligible.add(code)
        audit[code] = dict(source_at=at.isoformat(sep=' ', timespec='seconds') if at else None,
                           valid=reason == '有效', reason=reason,
                           change_pct=q.get('change_pct') if number(q.get('change_pct')) else None)
        # 未评分对象只参与纯价格统计，不借 coverage 中的局部均线补成趋势/突破。
        if (code in scored and row.get('signal_date') == asof and number(row.get('ret5'))
                and row.get('trend_online') in (True, False, 0, 1)
                and row.get('trend_online') is not None and not row.get('stale_carried')):
            daily[code] = dict(ret5=row['ret5'], trend_online=bool(row['trend_online']))
        if reason != '有效' or not number(q.get('change_pct')):
            continue
        # 午后不能使用上午仍在时效容忍窗内的报价；不能把旧行价格贴在新源时钟上。
        if session in ('午盘', '尾盘') and session_part(at) != 'PM':
            audit[code].update(valid=False, reason='尚无下午有效报价')
            continue
        if row and stamp(row.get('intraday_quote_at')) and at < stamp(row['intraday_quote_at']):
            audit[code].update(valid=False, reason='报价时间倒退')
            continue
        current[code] = dict(change_pct=q['change_pct'], source_at=audit[code]['source_at'])
        if (code in scored and row.get('intraday_price_basis_comparable') is True
                and row.get('intraday_observation_available') is True
                and row.get('intraday_quote_at') == audit[code]['source_at']
                and row.get('intraday_judgment_at') == audit[code]['source_at']
                and row.get('intraday_serious_weakness') is False
                and not row.get('intraday_trade_restriction')
                and row.get('trade_status') not in ('no_trade', 'trade_recovered_wait_daily')
                and not row.get('reference_only') and not row.get('stale_carried')
                and row.get('live_attack_status') not in ('历史观察，当前阶段未重新判断', '本轮报价或价格口径不可判断')
                and row.get('live_attack_pattern') is not None):
            events[code] = row.get('live_attack_event')
    return eligible, excluded, daily, current, events, audit


def market_metrics(eligible, daily, current):
    size = len(eligible)
    d, q = list(daily.values()), list(current.values())
    dc, qc = len(d)/size*100 if size else None, len(q)/size*100 if size else None
    limit = config.BOARD_OPPORTUNITY['min_coverage_pct']
    return dict(expected_count=size, daily_count=len(d), quote_count=len(q),
                daily_coverage_pct=dc, quote_coverage_pct=qc,
                daily_ready=bool(dc is not None and dc >= limit and d),
                quote_ready=bool(qc is not None and qc >= limit and q),
                R5=mean(r['ret5'] for r in d) if d else None,
                T=mean(r['trend_online'] for r in d)*100 if d else None,
                R0=mean(r['change_pct'] for r in q) if q else None,
                earliest_quote_at=min((r['source_at'] for r in q), default=None),
                latest_quote_at=max((r['source_at'] for r in q), default=None))


def daily_result(codes, daily, market, asof):
    p = config.BOARD_OPPORTUNITY
    values = [daily[c]['ret5'] for c in codes if c in daily]
    count = len(values)
    r5 = mean(values) if values else None
    trim, removed = trimmed(values)
    e5 = r5-market['R5'] if r5 is not None and market['R5'] is not None else None
    etrim = trim-market['R5'] if trim is not None and market['R5'] is not None else None
    p5 = sum(r > 0 for r in values)/count*100 if count else None
    t = sum(daily[c]['trend_online'] for c in codes if c in daily)/count*100 if count else None
    cover = count/len(codes)*100 if codes else None
    tfloor = max(p['daily_t_floor'], market['T']+p['daily_t_market_add']) if market['daily_ready'] else None
    checks = [ge('日线有效成员', count, p['min_members']), ge('日线覆盖率%', cover, p['min_coverage_pct']),
              check('主板日线基准覆盖%', market['daily_coverage_pct'], '≥ '+str(p['min_coverage_pct']), True if market['daily_ready'] else None),
              ge('R5%', r5, p['daily_r5_min']), ge('E5百分点', e5 if market['daily_ready'] else None, p['daily_e5_min']),
              ge('P5%', p5, p['daily_p5_min']), ge('T%', t, tfloor),
              positive('剔除领先成员R5%', trim), positive('剔除领先成员E5百分点', etrim if market['daily_ready'] else None)]
    ready = count >= p['min_members'] and cover >= p['min_coverage_pct'] and market['daily_ready']
    return dict(asof=asof, valid_count=count, expected_count=len(codes), expected_codes=sorted(codes), coverage_pct=cover, small_sample=6 <= count <= p['small_sample_max'],
                valid_codes=sorted(set(codes) & set(daily)), R5=r5, E5=e5, P5=p5, T=t,
                median5=median(values) if values else None, trimmed_R5=trim, trimmed_E5=etrim,
                trimmed_count=removed, market=copy.deepcopy({k:market[k] for k in ('R5','T','daily_count','daily_coverage_pct','daily_ready')}),
                ready=ready, checks=checks, qualified=verdict(checks) if ready else None)


def history_records(folder, asof):
    records = []
    for path in sorted(Path(folder).glob('*.json')):
        if path.stem > str(asof):
            continue
        try:
            item = json.loads(path.read_text(encoding='utf-8'))
            if item.get('version') == VERSION:
                records.extend(item.get('records') or [])
        except (OSError, ValueError):
            continue
    return records


def index_trace(code, bars, calendar):
    def calculate():
        trace = []
        board_trend.replay(bars, calendar, observer=lambda day, segment, start, ended:
                           trace.append(dict(day=day, segment=segment, start=start, ended=ended)))
        return trace
    return scan_cache.cached('board_opportunity_history', str(code),
                             [VERSION, bars, calendar, board_trend.RULES], calculate)


def background(board, old, records, calendar, day, loader):
    """仅真实完成记录或同名指数历史；历史回踩从原状态机观测，不修改它。"""
    p = config.BOARD_OPPORTUNITY
    d, c = board.get('index_trend') or {}, board.get('index_current') or {}
    pending = dict(ready=None, source=None, reason='回踩背景待核验', episode_id=None, pullback_start=None)
    prior = old.get('background') or {}
    segment = (c.get('episode_start') or d.get('episode_start')) if d.get('observing') and not d.get('weak') else day
    episode_id = str(d.get('code'))+'|'+str(segment)
    if not (d.get('ready') and c.get('ready') and d.get('code') == c.get('code')
            and d.get('name') == board['name'] == c.get('name') and c.get('mode') == 'current'):
        if d.get('ready') and prior.get('episode_id') == episode_id:
            return dict(prior, ready=None, reason='回踩背景待核验：当前指数不可判断')
        if prior.get('blocked_episode_id') == episode_id:
            pending['blocked_episode_id'] = episode_id
        return pending
    if c.get('weak') or c.get('weakening') or not c.get('observing'):
        return dict(pending, ready=False, blocked_episode_id=episode_id, reason='指数转弱或趋势段已结束')
    if prior.get('blocked_episode_id') == episode_id:
        return dict(pending, ready=False, blocked_episode_id=episode_id, reason='旧趋势段回踩背景已因指数转弱清除，等待新趋势段')
    start = c.get('pullback_start') or d.get('pullback_start')
    if not start and prior.get('episode_id') == episode_id:
        start = prior.get('pullback_start')
    try:
        bars = [b for b in loader(d['code']) if b.get('date') in calendar and b['date'] <= d['asof'] and board_trend.valid(b)]
    except (OSError, ValueError, sqlite3.Error):
        return dict(pending, episode_id=episode_id, pullback_start=start, reason='回踩背景待核验：指数历史不可读取')
    if not start:
        trace = index_trace(d['code'], bars, [v for v in calendar if v <= d['asof']])
        starts = [r['start'] for r in trace if r['segment'] == segment and r['start'] and not r['ended']]
        start = max(starts) if starts else None
    if not start:
        return dict(pending, ready=False, episode_id=episode_id, reason='本趋势段尚无可核验回踩记录')
    result = dict(pending, episode_id=episode_id, pullback_start=start)
    before = [v for v in calendar if v < start][-p['background_days']:]
    actual = [r for r in records if r.get('id') == board['id'] and r.get('asof') in before
              and r.get('daily', {}).get('qualified') is True]
    if actual:
        record = max(actual, key=lambda r:r['asof'])
        return dict(result, ready=True, source='历史主板成员持续强势', reason=None,
                    evidence_asof=record['asof'], evidence_members_hash=record['members_hash'])
    by_date = {b['date']: b for b in bars}
    for index, date in reversed(list(enumerate(calendar))):
        if date not in before or index < 5:
            continue
        window = calendar[index-5:index+1]
        if all(v in by_date for v in window):
            ret = (by_date[date]['close']/by_date[window[0]]['close']-1)*100
            if ret >= p['index_attack_ret5_min']:
                return dict(result, ready=True, source='指数历史进攻背景', reason=None,
                            evidence_asof=date, evidence_ret5=ret)
    # 每个5日收益都需要完整6日窗口，不能只核验20个结束日。
    needed = [v for v in calendar if v < start][-(p['background_days']+5):]
    complete = len(needed) == p['background_days']+5 and all(v in by_date for v in needed)
    return dict(result, ready=False if complete else None,
                reason='回踩前未核实前期进攻背景' if complete else '回踩背景待核验：同名指数历史不足')


def current_result(codes, current, events, market):
    p = config.BOARD_OPPORTUNITY
    valid = sorted(set(codes) & set(current))
    values = [current[c]['change_pct'] for c in valid]
    count = len(values)
    cover = count/len(codes)*100 if codes else None
    r0 = mean(values) if values else None
    trimmed_r0, removed = trimmed(values)
    e0 = r0-market['R0'] if r0 is not None and market['R0'] is not None else None
    trimmed_e0 = trimmed_r0-market['R0'] if trimmed_r0 is not None and market['R0'] is not None else None
    times = [current[c]['source_at'] for c in valid]
    event_valid_codes = sorted(set(valid) & set(events))
    event_codes = sorted(c for c in valid if events.get(c) in p['events'])
    return dict(valid_count=count, coverage_pct=cover, small_sample=6 <= count <= p['small_sample_max'],
                market=copy.deepcopy({k:market.get(k) for k in ('R0','quote_count','quote_coverage_pct','quote_ready','earliest_quote_at','latest_quote_at')}),
                valid_codes=valid, event_valid_codes=event_valid_codes, event_valid_count=len(event_valid_codes), event_codes=event_codes,
                event_coverage_pct=len(set(valid) & set(events))/len(codes)*100 if codes else None,
                R0=r0, E0=e0, U0=sum(v>0 for v in values)/count*100 if count else None,
                A0=sum(v>=3 for v in values) if values else None, B0=len(event_codes) if event_valid_codes else None,
                median0=median(values) if values else None, trimmed_R0=trimmed_r0, trimmed_E0=trimmed_e0,
                trimmed_count=removed, sample_at=min(times) if times else None, latest_quote_at=max(times) if times else None,
                ready=bool(count >= p['min_members'] and cover >= p['min_coverage_pct'] and market['quote_ready']))


def sort_key(board):
    o = board['opportunity']
    q = o['current']
    return tuple(-q[k] if number(q[k]) else math.inf for k in ('E0','U0','R0','valid_count'))+(board['name'], board['id'])


def _archived_v1_enrich(snapshot, quotes, pool, previous=None, persist=True, history_dir=None, index_loader=None, excluded_names=None):
    """仅在线计算入口推进确认和真实日线记录。页面生成禁止调用。"""
    p = config.BOARD_OPPORTUNITY
    now = stamp(snapshot.get('quote_capture_at')) or stamp(snapshot.get('generated_at'))
    if now is None:
        raise ValueError('板块机会缺少实际采集时钟')
    day, session = now.date().isoformat(), snapshot.get('session')
    judgment_at = snapshot.get('attack_assessment_at') or snapshot.get('generated_at') or snapshot.get('quote_capture_at')
    asof = (snapshot.get('strength_model') or {}).get('asof')
    folder = Path(history_dir) if history_dir else config.CACHE_DIR/'board_opportunity_daily'/VERSION
    records = history_records(folder, asof)
    recorded = {(r['id'], r['asof'], r['members_hash']): r for r in records}
    prior_model = (previous or {}).get('board_opportunity_model') or {}
    previous_boards = {b['id']: b for b in (previous or {}).get('board_catalog') or []} if prior_model.get('version') == VERSION else {}
    eligible, excluded, daily, current, events, audit = collect(snapshot, quotes, pool, now, session, excluded_names)
    market = market_metrics(eligible, daily, current)
    calendar = (snapshot.get('board_trend_model') or {}).get('calendar') or []
    new_records = []
    auction = session in ('集合竞价', '竞价结束', '盘前', '非交易日')
    for board in snapshot.get('board_catalog') or []:
        member_codes = sorted(set(map(str, board.get('member_codes') or [])))
        members_hash = identity(member_codes)
        codes = sorted(set(member_codes) & eligible)
        old = (previous_boards.get(board['id']) or {}).get('opportunity') or {}
        if old.get('members_hash') != members_hash:
            old = {}
        d = daily_result(codes, daily, market, asof)
        saved = recorded.get((board['id'], asof, members_hash))
        if saved:
            d = copy.deepcopy(saved['daily'])
        elif persist and d['ready'] and asof:
            new_records.append(dict(id=board['id'], name=board['name'], type=board['type'], asof=asof,
                                    version=VERSION, members_hash=members_hash, member_codes=member_codes,
                                    expected_codes=codes, calculated_at=now.isoformat(sep=' '), daily=copy.deepcopy(d)))
        q = current_result(codes, current, events, market)
        bg = background(board, old, records, calendar, day, index_loader or board_trend.load)
        common = [ge('报价有效成员', q['valid_count'], p['min_members']), ge('报价覆盖率%', q['coverage_pct'], p['min_coverage_pct']),
                  check('主板报价基准覆盖%', market['quote_coverage_pct'], '≥ '+str(p['min_coverage_pct']), True if market['quote_ready'] else None),
                  positive('剔除领先成员R0%', q['trimmed_R0']),
                  positive('剔除领先成员E0百分点', q['trimmed_E0'] if market['quote_ready'] else None)]
        resonance = common+[positive('R0%', q['R0']), positive('E0百分点', q['E0'] if market['quote_ready'] else None), ge('U0%', q['U0'], p['mainline_u0_min'])]
        start_checks = common+[ge('R0%', q['R0'], p['startup_r0_min']), ge('E0百分点', q['E0'] if market['quote_ready'] else None, p['startup_e0_min']),
                              ge('U0%', q['U0'], p['startup_u0_min']), ge('A0只', q['A0'], p['startup_small_a0_min'] if q['small_sample'] else p['startup_a0_min'])]
        c = board.get('index_current') or {}
        restart_checks = common+[check('回踩背景', bg['source'], '本趋势段回踩前已有进攻证据', bg['ready']),
                                  check('当前同名指数', c.get('state'), 'ready=true', True if c.get('ready') else None),
                                  check('指数≥滚动MA5/MA10', c.get('close'), str([c.get('ma5'),c.get('ma10')]),
                                        c['close'] >= c['ma5'] and c['close'] >= c['ma10'] if all(number(c.get(k)) for k in ('close','ma5','ma10')) and c.get('ready') else None),
                                  check('指数未转弱', c.get('state'), '无weak/weakening', not (c.get('weak') or c.get('weakening')) if c.get('ready') else None),
                                  positive('R0%', q['R0']), positive('E0百分点', q['E0'] if market['quote_ready'] else None),
                                  ge('U0%', q['U0'], p['restart_u0_min']), ge('B0只', q['B0'], p['restart_b0_min'])]
        current_ready = q['ready'] and not auction and session != '午间休市'
        raw_start = verdict(start_checks) if current_ready else None
        raw_restart = verdict(restart_checks) if current_ready else None
        mainline_current = verdict(resonance) if current_ready else None
        start_state = confirmation(old.get('startup_confirmation'), raw_start is True, q['sample_at'], day, members_hash, session, p['startup_samples'], p['startup_span_seconds'])
        # 指数也必须为本轮有效报价，且回踩所属趋势段变化不能继承旧确认。
        restart_old = old.get('restart_confirmation') if (old.get('background') or {}).get('episode_id') == bg.get('episode_id') else None
        restart_state = confirmation(restart_old, raw_restart is True, q['sample_at'], day, members_hash, session, p['restart_samples'], p['restart_span_seconds'])
        qualifications = dict(daily_mainline=d['qualified'], mainline=bool(d['qualified'] and mainline_current is True),
                              startup=raw_start is True and start_state['confirmed'], restart=raw_restart is True and restart_state['confirmed'])
        if auction:
            qualifications.update(mainline=False, startup=False, restart=False)
        primary = '回踩再启动' if qualifications['restart'] else '持续强势' if qualifications['mainline'] else '新启动' if qualifications['startup'] else None
        status = '新启动·盘中确认，待收盘复核' if primary == '新启动' else '回踩再启动·盘中确认，待收盘复核' if primary == '回踩再启动' else primary
        if not status:
            status = '日线持续强势·当前待核验' if d['qualified'] and not current_ready else '日线持续强势·当前未共振' if d['qualified'] else '启动待确认' if raw_start else '回踩再启动待确认' if raw_restart else '待核验' if not current_ready else '当前未入选'
        pending = bool((raw_start and not qualifications['startup']) or (raw_restart and not qualifications['restart']))
        all_checks = dict(daily=d['checks'], mainline=resonance, startup=start_checks, restart=restart_checks,
                          startup_confirmation=[ge('连续有效轮数', start_state['count'], p['startup_samples']), ge('源时间跨度秒', start_state['span_seconds'], p['startup_span_seconds'])],
                          restart_confirmation=[ge('连续有效轮数', restart_state['count'], p['restart_samples']), ge('源时间跨度秒', restart_state['span_seconds'], p['restart_span_seconds'])])
        divergence = bool(c.get('ready') and ((c.get('strong_advance') is True and mainline_current is not True) or (qualifications['mainline'] and not c.get('trend_online'))))
        chosen_confirmation = restart_state if primary == '回踩再启动' or (raw_restart and not raw_start) else start_state
        o = dict(version=VERSION, day=day, daily_asof=asof, judgment_at=judgment_at,
                 members_hash=members_hash, expected_count=len(codes), expected_codes=codes,
                 excluded_count=len(set(member_codes)&set(excluded)),
                 excluded={c:excluded[c] for c in member_codes if c in excluded},
                 daily=d, current=q, daily_mainline=d['qualified'], current_mainline=mainline_current,
                 startup_raw=raw_start, restart_raw=raw_restart, qualifications=qualifications,
                 primary_label=primary, status=status, current_opportunity=any(qualifications[k] for k in ('mainline','startup','restart')),
                 pending=pending, verification_pending=not current_ready or d['qualified'] is None or bg['ready'] is None,
                 startup_confirmation=start_state, restart_confirmation=restart_state,
                 first_confirmed_at=restart_state['first_confirmed_at'] if primary=='回踩再启动' else start_state['first_confirmed_at'],
                 confirmation_count=chosen_confirmation['count'], confirmation_span_seconds=chosen_confirmation['span_seconds'],
                 background=bg, index_member_divergence=divergence, checks=all_checks,
                 failed_reasons={k:[v['key']+('待核验' if v['passed'] is None else '未通过') for v in checks if v['passed'] is not True] for k,checks in all_checks.items()},
                 display_phase='竞价观察与日线背景' if auction else '午休保留上午结果' if session=='午间休市' else '收盘复核' if session=='已收盘' else '盘中观察')
        if session == '午间休市' and old.get('day') == day:
            o = copy.deepcopy(old)
            o.update(display_phase='午休保留上午结果', retained=True, retained_until=old['current'].get('sample_at'))
        if session == '已收盘':
            o['close_review'] = dict(at=q['sample_at'], mainline=qualifications['mainline'], startup_conditions=raw_start,
                                     restart_conditions=raw_restart, note='收盘条件复核；不补足盘中确认次数')
        board['opportunity'] = o
    boards = snapshot.get('board_catalog') or []
    ranked = sorted(boards, key=sort_key)
    for rank, board in enumerate(ranked, 1):
        board['opportunity']['sort_rank'] = rank
    def ids(predicate):
        return [b['id'] for b in ranked if predicate(b['opportunity'])]
    lists = dict(current=ids(lambda o:o['current_opportunity']),
                 mainline=ids(lambda o:o['qualifications']['mainline']),
                 startup=ids(lambda o:o['qualifications']['startup']),
                 restart=ids(lambda o:o['qualifications']['restart']),
                 pending=ids(lambda o:o['pending'] or o['verification_pending']),
                 daily=ids(lambda o:o['daily_mainline'] is True))
    model = dict(version=VERSION, daily_asof=asof, judgment_at=judgment_at,
                 session=session, parameters=copy.deepcopy(p), market=market, lists=lists,
                 counts={k:len(v) for k,v in lists.items()}, excluded=excluded, quote_audit=audit,
                 basis='同一当前主板股票池；成员等权；剔除领先成员表示参与程度，不代表官方指数权重贡献')
    if session == '午间休市' and any(b['opportunity'].get('retained') for b in boards):
        model.update(retained_market=copy.deepcopy(prior_model['market']),
                     retained_quote_audit=copy.deepcopy(prior_model['quote_audit']))
    if session == '午间休市' and boards and all(b['opportunity'].get('retained') for b in boards):
        # 午休卡片、成员下钻与导出的基准/源报价同样冻结，避免混入新批次。
        model.update(market=copy.deepcopy(prior_model['market']), quote_audit=copy.deepcopy(prior_model['quote_audit']),
                     excluded=copy.deepcopy(prior_model.get('excluded') or {}), retained=True,
                     retained_until=prior_model.get('judgment_at'))
    snapshot['board_opportunity_model'] = model
    if persist and new_records:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder/(asof+'.json')
        existing = json.loads(target.read_text(encoding='utf-8')) if target.exists() else dict(version=VERSION, asof=asof, records=[])
        # 旧版本文件保留自身口径，用独立版本目录存新记录，禁止重写旧历史。
        if existing.get('version') != VERSION:
            raise ValueError('日线记录规则版本冲突，必须保留原记录')
        existing['records'].extend(new_records)
        config.atomic_write_text(target, json.dumps(existing, ensure_ascii=False, separators=(',',':')))
    return model


def _archived_v1_validate(snapshot):
    """只读验收存储的公式、确认、名单和排序；不推进状态、不写历史。"""
    model = snapshot['board_opportunity_model']
    assert model['version'] == VERSION
    assert json.loads(json.dumps(model['parameters'])) == json.loads(json.dumps(config.BOARD_OPPORTUNITY))
    rows = {r['code']:r for r in snapshot.get('stocks', [])+snapshot.get('coverage_catalog', [])}
    audit = model['quote_audit']
    current = {code:dict(change_pct=a['change_pct'],source_at=a['source_at']) for code,a in audit.items() if a['valid']}
    for b in snapshot['board_catalog']:
        o = b['opportunity'];q = o['current'];d = o['daily'];qs = o['qualifications']
        assert o['version'] == VERSION and o['daily_asof'] == model['daily_asof']
        assert o['members_hash'] == identity(b['member_codes'])
        assert o['expected_count'] == len(o['expected_codes'])
        assert q['valid_count'] == len(q['valid_codes'])
        assert q['B0'] is None or q['B0'] == len(q['event_codes'])
        quote_data = current
        if o.get('retained'):
            retained_audit = model.get('retained_quote_audit') or audit
            quote_data = {code:dict(change_pct=a['change_pct'],source_at=a['source_at']) for code,a in retained_audit.items() if a['valid']}
        recomputed = current_result(o['expected_codes'], quote_data, {c:'整理突破' if c in q['event_codes'] else None for c in q['event_valid_codes']}, q.get('market') or model['market'])
        for key in ('R0','E0','U0','A0','B0','median0','trimmed_R0','trimmed_E0','sample_at','latest_quote_at','valid_count','coverage_pct'):
            assert recomputed[key] == q[key], (b['name'], key, recomputed[key], q[key])
        assert d['valid_count'] == len(d['valid_codes'])
        assert qs['daily_mainline'] == o['daily_mainline'] == d['qualified']
        if qs['mainline']:
            assert d['qualified'] is True and o['current_mainline'] is True and q['ready']
            assert verdict(o['checks']['daily']) is True and verdict(o['checks']['mainline']) is True
        for kind, raw, required_count, required_span in (('startup','startup_raw','startup_samples','startup_span_seconds'),('restart','restart_raw','restart_samples','restart_span_seconds')):
            state=o[kind+'_confirmation']
            if qs[kind]:
                assert o[raw] is True and verdict(o['checks'][kind]) is True
                assert state['confirmed'] and state['count'] >= config.BOARD_OPPORTUNITY[required_count]
                assert state['span_seconds'] >= config.BOARD_OPPORTUNITY[required_span]
            if state['count']:
                assert state['span_seconds'] == (stamp(state['last_sample_at'])-stamp(state['first_sample_at'])).total_seconds()
        expected_label = '回踩再启动' if qs['restart'] else '持续强势' if qs['mainline'] else '新启动' if qs['startup'] else None
        assert o['primary_label'] == expected_label
        assert o['current_opportunity'] == bool(expected_label)
        if not o.get('retained'):
            for code in q['event_codes']:
                r=rows[code]
                assert r.get('live_attack_event') in config.BOARD_OPPORTUNITY['events']
                assert r.get('intraday_price_basis_comparable') is True
                assert r.get('intraday_serious_weakness') is False and not r.get('intraday_trade_restriction')
                assert r.get('intraday_quote_at') == r.get('intraday_judgment_at') == audit[code]['source_at']
                assert not r.get('coverage_only') and not r.get('stale_carried')
    sorted_boards=sorted(snapshot['board_catalog'],key=lambda b:b['opportunity']['sort_rank'])
    # 午休使用上午冻结次序与指标。
    assert sorted_boards == sorted(snapshot['board_catalog'],key=sort_key)
    predicates=dict(current=lambda o:o['current_opportunity'],mainline=lambda o:o['qualifications']['mainline'],
                    startup=lambda o:o['qualifications']['startup'],restart=lambda o:o['qualifications']['restart'],
                    pending=lambda o:o['pending'] or o['verification_pending'],daily=lambda o:o['daily_mainline'] is True)
    for key, predicate in predicates.items():
        expected=[b['id'] for b in sorted_boards if predicate(b['opportunity'])]
        assert model['lists'][key] == expected and model['counts'][key] == len(expected)
    return dict(version=VERSION, boards=len(snapshot['board_catalog']), counts=model['counts'])


def enrich(snapshot, quotes, pool, previous=None, persist=True, history_dir=None, index_loader=None, excluded_names=None, histories=None, calendar=None, contexts=None, now=None):
    """Use the single backend result. Never collect confirmation samples."""
    import market_strength
    if not snapshot.get('market_strength'):
        import scoring, strength
        histories=histories if histories is not None else scoring.formal_histories(pool)
        calendar=calendar if calendar is not None else strength.trading_calendar(histories)
        market_strength.attach(snapshot,quotes,pool,histories,calendar,contexts=contexts,now=now,previous=previous)
    return snapshot['board_opportunity_model']


def validate(snapshot):
    import market_strength
    return market_strength.validate(snapshot)
