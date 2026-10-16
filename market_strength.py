"""Single, stateless market strength model. Percent returns; no strategy eligibility gates."""
import copy
import gzip
import hashlib
import json
import math
from bisect import bisect_left, bisect_right
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import mean, median

import config
import intraday
import closing_price
import observed_history

P = config.MARKET_STRENGTH
VERSION = P['version']


def implementation_hash():
    return hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).with_name('direction_changes.py').read_bytes() + Path(closing_price.__file__).read_bytes() + Path(intraday.__file__).read_bytes() + Path(observed_history.__file__).read_bytes() + json.dumps(P, sort_keys=True).encode()).hexdigest()


IMPLEMENTATION_HASH = implementation_hash()  # fixed at process import


def finite(x):
    return isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x)


def positive(x):
    return finite(x) and x > 0


def clamp(x):
    return max(0., min(1., x))


def rounded(x):
    return float(Decimal(str(x)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)) if finite(x) else None


def level(x):
    return None if x is None else ('很强' if x >= P['very_strong_min'] else
                                  '强' if x >= P['strong_min'] else
                                  '一般' if x >= P['normal_min'] else '弱')


def percentiles(values):
    values = {c: v for c, v in values.items() if finite(v)}
    ordered = sorted(values.values())
    n = len(ordered)
    return {c: 50. if n == 1 else 100. * (bisect_left(ordered, v) +
            (bisect_right(ordered, v)-bisect_left(ordered, v)-1)/2)/(n-1)
            for c, v in values.items()}


def period_score(r, s, k, full):
    # The reference scale is not a hard ceiling. Strong returns retain room
    # to separate, while weak absolute advances cannot win on rank alone.
    x = max(0., r/full)
    edge=P['return_curve_linear_until']
    a=100*x if x<=edge else 100*edge+100*(1.-edge)*(x-edge)/(x-edge+P['return_curve_tail_half_scale'])
    g = P['absolute_weight']*a + P['relative_weight']*s
    return dict(R=r, S=s, A=a, G=g, K=k, T=g*k)


def trend_period_score(r, s, historical_r, historical_s, k, full):
    live = period_score(r, s, k, full)
    past = period_score(historical_r, historical_s, k, full)
    live.update(historical_R=historical_r, historical_S=historical_s,
                historical_A=past['A'], historical_G=past['G'])
    live['T'] = (P['trend_history_weight']*past['G'] + P['trend_current_weight']*live['G'])*k
    return live


def recent_emotion(bars, limit, calendar):
    days = P['emotion_recent_days']
    window = bars[-days-1:]
    if len(window) != days+1 or [b['date'] for b in window] != calendar[-days-1:]:
        return None
    if any(not intraday._valid_historical_price_bar(b) for b in window):
        return None
    modes = {(b.get('price_basis'),b.get('price_basis_source')) for b in window}
    if len(modes)!=1:
        return None
    basis,source=next(iter(modes))
    if not (basis=='qfq' and source in intraday._QFQ_HISTORY_SOURCES or basis=='raw' and source in intraday._RAW_HISTORY_SOURCES):
        return None
    returns = [100*(window[i]['close']/window[i-1]['close']-1) for i in range(1,len(window))]
    active_scale = P['emotion_active_limit_ratio']*limit
    weights = P['emotion_recent_recency_weights']
    activity = sum(w*100*clamp(r/active_scale) for w,r in zip(weights,returns))/sum(weights)
    negative = sum(w*clamp(-r/(P['emotion_recent_negative_scale_ratio']*limit))
                   for w,r in zip(weights,returns))/sum(weights)
    gain = 100*(window[-1]['close']/window[0]['close']-1)
    score=max(0., .70*activity+.30*100*clamp(gain/limit)-P['emotion_recent_negative_penalty']*negative)
    return dict(score=score, returns=returns, recency_weights=list(weights), negative_pressure=negative,
                active_days=sum(r>=active_scale for r in returns), gain=gain,
                dates=[b['date'] for b in window], last_return=returns[-1])


def price_background(price, bars):
    out = {}
    closes = [b['close'] for b in bars]
    for n in (20,60):
        if len(closes)>=n:
            avg=mean(closes[-n:])
            old=mean(closes[-n-5:-5]) if len(closes)>=n+5 else None
            live=(price+sum(closes[-n+1:]))/n
            out[str(n)]=dict(MA=avg, slope5=100*(avg/old-1) if old else None,
                            MA_now=live, slope_now=100*(live/avg-1),
                            distance_pct=100*(price/live-1), return_pct=100*(closes[-1]/closes[-n]-1))
    mid=out.get('20',{})
    out['label'] = ('中期未恢复' if mid.get('distance_pct',0)<0 or mid.get('slope_now',0)<0 or mid.get('slope5',0) is not None and mid.get('slope5',0)<0
                    else '中期上行' if mid else '中期历史不足')
    return out


def structure(price, ma_now, ma_prev, dd, atr=None):
    unit = atr if positive(atr) else ma_now*.01
    dd_damage=(.30*clamp((dd-P['structure_drawdown_free_atr'])/
                        (P['drawdown_max_atr']-P['structure_drawdown_free_atr']))+
               .70*clamp((dd-P['drawdown_max_atr'])/
                        (P['structure_drawdown_damage_atr']-P['drawdown_max_atr'])))
    damage=max(clamp((ma_now-price)/(unit*P['structure_ma_damage_atr'])),
               clamp((ma_prev-ma_now)/(unit*P['structure_slope_damage_atr'])),
               dd_damage)
    return 1.-(1.-P['structure_factors']['damaged'])*damage


def trend_health(price, bars):
    day=100*(price/bars[-1]['close']-1)
    recent=100*(price/bars[-3]['close']-1) if len(bars)>=3 else None
    loss=clamp((-day-P['trend_health_free_loss_pct'])/
               (P['trend_health_full_loss_pct']-P['trend_health_free_loss_pct']))
    retreat=clamp((-recent-P['trend_health_free_3day_loss_pct'])/
                  (P['trend_health_full_3day_loss_pct']-P['trend_health_free_3day_loss_pct'])) if recent is not None else 0.
    return dict(factor=1.-P['trend_health_max_penalty']*max(loss,retreat),day_return=day,
                recent_return=recent,day_damage=loss,recent_damage=retreat)


def trend_raw(price, bars, atr, atr_date, calendar=None):
    out = {}
    for n in P['periods']:
        part = dict(R=None, S=None, A=None, G=None, K=None, T=None,
                    MA_now=None, MA_previous=None, peak=None, dd=None,
                    ATR=atr if positive(atr) else None, ATR_date=atr_date)
        window = bars[-n:]
        if positive(price) and len(window) == n and all(positive(b.get('close')) for b in window):
            if calendar and [b['date'] for b in window] != calendar[-n:]:
                part['reason'] = '完成日窗口存在缺口'
            else:
                closes = [b['close'] for b in window]
                now, prev, peak = (price + sum(closes[1:]))/n, mean(closes), max(b['high'] for b in window)
                if len(bars)<n+1 or calendar and bars[-n-1]['date']!=calendar[-n-1]:
                    part['reason']='完成日收益基点不足或存在缺口'
                    out[str(n)]=part
                    continue
                part.update(R=100*(price/closes[0]-1), historical_R=100*(closes[-1]/bars[-n-1]['close']-1), MA_now=now, MA_previous=prev, peak=peak,
                            dates=[b['date'] for b in window])
                if positive(atr) and atr_date == window[-1]['date']:
                    dd = max(0, peak-price)/atr
                    health=trend_health(price,bars)
                    part.update(dd=dd, K=structure(price, now, prev, dd,atr),
                                health=health['factor'],health_evidence=health)
                else:
                    part['reason'] = '前一完成日ATR20待核验'
        else:
            part['reason'] = '价格或该周期完成日历史不足'
        out[str(n)] = part
    return out


def trend_selection(parts):
    valid = [(int(n), v['T']) for n, v in parts.items() if finite(v.get('T'))]
    if not valid:
        return dict(score=None,dominant_period=None,base=None,health_factor=None,conflict_factor=None)
    highest = max(t for _, t in valid)
    dominant = max(n for n, t in valid if highest-t <= P['tie_epsilon'])
    short=parts.get('5',{}).get('T')
    conflict=clamp((P['strong_min']-short)/P['strong_min']) if dominant>5 and finite(short) else 0.
    health=parts[str(dominant)].get('health',1.)
    factor=1.-P['trend_conflict_max_penalty']*conflict
    return dict(score=rounded(highest*health*factor),dominant_period=dominant,base=highest,
                health_factor=health,conflict_factor=factor,short_period_score=short)


def choose(parts):
    result=trend_selection(parts)
    return result['score'],result['dominant_period']


def empty(at, mode):
    return dict(version=VERSION, trend_score=None, emotion_score=None, trend_level=None,
                emotion_level=None, dominant_period=None, phase=None, events=[], event_evidence={},
                trend_strong=False, emotion_strong=False, focus=False, trend_at=at, emotion_at=at,
                mode=mode, trend_parts_by_period={}, emotion_parts={}, reasons=[], risks=[], data_reasons=[])


def brief(m):
    """Display projection; numerical evidence stays on the canonical stock/board detail."""
    keys=('version','trend_score','emotion_score','trend_level','emotion_level','dominant_period',
          'phase','events','trend_strong','emotion_strong','focus','trend_at','emotion_at','mode','reasons','risks','data_reasons',
          'background','recent_emotion','day_attack','day_attack_strong','history_returns',
          'display_evidence','labels','new_strong_axes','direction_change','member_strength')
    return {k:m.get(k) for k in keys}


def finish(m):
    m['trend_selection'] = trend_selection(m['trend_parts_by_period'])
    m['trend_score'], m['dominant_period'] = choose(m['trend_parts_by_period'])
    m['history_returns'] = {n:p.get('historical_R') for n,p in m['trend_parts_by_period'].items()}
    for axis in ('trend', 'emotion'):
        score = m[axis+'_score']
        m[axis+'_level'] = level(score)
        m[axis+'_strong'] = score is not None and score >= P['strong_min']
    m['focus'] = m['trend_strong'] or m['emotion_strong']


def phase(t, e, history, consolidating):
    if len(history) != P['phase_history_days'] or any(x is None for x in history):
        return None, None
    days = sum(x >= P['strong_min'] for x in history)
    if t is not None and t >= P['strong_min']:
        if consolidating is None:
            return None, days
        return ('启动' if history[-1] < P['strong_min'] else
                '回踩整理' if consolidating else '推进'), days
    # A prior trend score cannot establish the start of an emotion move.
    if t is not None and t < P['strong_min'] and history[-1] >= P['strong_min']:
        return '转弱', days
    return None, days


def emotion_raw(q):
    price, op, hi, lo, r, limit = (q.get(k) for k in ('price','open','high','low','change_pct','limit_pct'))
    if not all(positive(v) for v in (price, op, hi, lo, limit)) or not finite(r) or hi < lo:
        return None, '当日情绪字段或正常有效涨幅限制不足'
    if price < lo or price > hi or op < lo or op > hi:
        return None, '现价或开盘价超出当日区间'
    tick = q.get('price_tick') if positive(q.get('price_tick')) else P['quote_tick_default']
    locked = positive(q.get('limit_up')) and abs(price-q['limit_up']) <= tick*P['limit_tick_tolerance']+1e-9
    l = 100*clamp((price-lo)/(hi-lo)) if hi > lo else None
    oscore = 100*clamp((100*(price/op-1))/(P['open_full_limit_ratio']*limit))
    if hi == lo and not locked:
        return None, '非实际涨停的同高低价，完整情绪未知'
    # A single-price limit quote cannot establish holding duration or intraday resilience.
    h = 50. if hi == lo else P['hold_position_weight']*l + P['hold_open_weight']*oscore
    return dict(R0=r, limit_pct=limit, S0=None, J=100*clamp(r/limit), D=None,H_snapshot=h,
                L=l, Oscore=oscore, H=h, actual_limit=locked,
                price=price, open=op, high=hi, low=lo, limit_up=q.get('limit_up'),
                hold_basis='单一价格，保持分中性' if hi == lo else '当日区间位置与开盘后推进'), None


def emotion_path(q, observations):
    """Sparse valid-quote samples, never a claim about continuous sealing."""
    at=intraday.parse_quote_timestamp(q.get('quote_at') or q.get('ts'))
    limit=q.get('limit_pct');r=q.get('change_pct')
    if not at or not positive(limit) or not finite(r):
        return dict(score=50.,available=False,samples=0,basis='抽样不足，过程分中性')
    samples={}
    for obs in observations:
        old_at=intraday.parse_quote_timestamp(obs.get('at'))
        value=obs.get('return')
        if not old_at or old_at.date()!=at.date() or not finite(value) or obs.get('limit_pct')!=limit:
            continue
        minutes=(at-old_at).total_seconds()/60
        if 0<minutes<=P['emotion_path_max_minutes']:
            samples[old_at]=value
    ordered=sorted(samples.items())
    if not ordered or (at-ordered[0][0]).total_seconds()/60<P['emotion_path_min_minutes']:
        return dict(score=50.,available=False,samples=len(ordered),basis='抽样不足，过程分中性')
    first=ordered[0][1];scale=limit*P['emotion_path_move_limit_ratio']
    advance=max(-1.,min(1.,(r-first)/scale))
    retreat=clamp((max([v for _,v in ordered]+[r])-r)/scale)
    active=clamp(first/(limit*P['emotion_active_limit_ratio']))
    score=100*clamp(.50+.25*advance+.25*active-.50*retreat)
    return dict(score=score,available=True,samples=len(ordered)+1,basis='有效报价抽样中的推进与回吐',
                from_at=str(ordered[0][0]),to_at=str(at),advance_pp=r-first,retreat_pp=retreat*scale,
                observations=[dict(at=str(t),return_pct=v) for t,v in ordered]+[dict(at=str(at),return_pct=r)])


def quote_valid(q, now, session, center, formal_close=False, completed_daily_proof=None):
    at = intraday.parse_quote_timestamp(q.get('quote_at') or q.get('ts'), now)
    if not at:
        return False, None, '报价时间缺失'
    if not positive(q.get('price')) or not (positive(q.get('amount_wan')) or positive(q.get('volume_shou'))):
        return False, at, '报价不可用或无真实成交'
    age = (now-at).total_seconds()
    minute = at.hour*60+at.minute
    if at.date() != now.date() or age < -config.INTRADAY['max_quote_future_seconds']:
        return False, at, '报价日期不一致或时间超前'
    # Only the morning closing edge and the established supplier's 11:31/11:32
    # delayed update may survive lunch. Keep the original source timestamp.
    morning_close = now.replace(hour=11, minute=30, second=0, microsecond=0)
    lunch = session == '午间休市' and -config.INTRADAY['max_quote_age_seconds'] <= (at-morning_close).total_seconds() < 180
    proved_close = formal_close and session=='已收盘' and closing_price.matches(completed_daily_proof,q,now)
    closing_quote = session == '已收盘' and (900 <= minute <= 902 or proved_close)
    if not (570 <= minute <= 690 or 780 <= minute <= 900 or lunch or closing_quote):
        return False, at, '非连续竞价报价'
    if session == '已收盘' and not closing_quote:
        return False, at, '尚无当日收市有效行情'
    if session in ('午盘','尾盘') and minute < 780:
        return False, at, '本段开盘报价未更新'
    if session == '午间休市' and not lunch:
        return False, at, '尚无上午收市有效行情'
    if age > config.INTRADAY['max_quote_age_seconds'] and not lunch and not (formal_close and closing_quote):
        return False, at, '报价过期'
    if center and not lunch and not (formal_close and closing_quote) and abs((at-center).total_seconds()) > config.INTRADAY['max_quote_batch_skew_seconds']:
        return False, at, '报价批次时间偏差过大'
    return True, at, None


def stock_scores(quotes, contexts, histories, calendar, now, session, formal_close=False, observations=None, completed_proofs=None):
    completed_proofs=completed_proofs or {}
    result, aligned = {}, {}
    times = [intraday.parse_quote_timestamp(q.get('quote_at') or q.get('ts'), now) for q in quotes.values()]
    times = [at for at in times if at and at.date() == now.date() and
             -config.INTRADAY['max_quote_future_seconds'] <= (now-at).total_seconds() <= config.INTRADAY['max_quote_age_seconds']]
    center = sorted(times)[len(times)//2] if times else None
    for c, q in quotes.items():
        valid, at, reason = quote_valid(q, now, session, center, formal_close,completed_proofs.get(c))
        mode = '正式收盘' if formal_close else '午休参考' if session == '午间休市' else '连续竞价'
        m = empty(str(at) if at else None, mode)
        result[c] = m
        if observed_history.inferred_quote_halt(q):
            m.update(mode='停牌参考',data_reasons=[],suspension=copy.deepcopy(q['data_availability']),
                reasons=['单股重试仍无当日成交，按停牌规则保留历史参考；复牌后继续计算'])
            continue
        if not valid:
            m['data_reasons'].append(reason)
            continue
        if c in completed_proofs:m['completed_daily_proof']=copy.deepcopy(completed_proofs[c])
        bars = observed_history.traded_bars(histories.get(c) or [])
        native = [b for b in bars if b['date']<now.date().isoformat()]
        dates = [b['date'] for b in native]
        # Completed-day ratios are invariant to a constant price scale. They do
        # not need the current quote/history conversion required by MA and ATR.
        m['recent_emotion'] = recent_emotion(native,q.get('limit_pct',10),dates) if positive(q.get('limit_pct')) else None
        # Always align formal history; never reuse a synthetic current-day bar as completed history.
        context = contexts.get(c) or intraday.align_price_basis(q, bars, calendar, observation_day=now.date().isoformat(),allow_partial=True)
        if context.get('quote_day') != now.date().isoformat():
            context = intraday.align_price_basis(q, bars, calendar, observation_day=now.date().isoformat(),allow_partial=True)
        if context.get('valid'):
            factor = context['scale_factor']
            raw = [dict(b, **{k: b[k]*factor for k in ('open','high','low','close')})
                   for b in bars if b['date'] < now.date().isoformat() and all(positive(b.get(k)) for k in ('open','high','low','close'))]
            aligned[c] = raw
            dates = [b['date'] for b in raw]
            m['trend_parts_by_period'] = trend_raw(q['price'], raw, context.get('atr20'), context.get('last_history_date'), dates)
            m['price_context'] = {k:v for k,v in context.items() if k != 'aligned_bars'}
            m['background'] = price_background(q['price'], raw)
        else:
            m['data_reasons'].append(context.get('reason') or '价格口径待核验')
        emotion, error = emotion_raw(q)
        if emotion:
            path=emotion_path(q,(observations or {}).get(c,[]))
            emotion.update(H_path=path['score'],path=path,
                           H=P['emotion_snapshot_hold_weight']*emotion['H_snapshot']+P['emotion_path_hold_weight']*path['score'])
            m['emotion_parts'] = emotion
        else:
            m['data_reasons'].append(error)
        m['quote_at'] = str(at)
    for n in P['periods']:
        vals = {c:m['trend_parts_by_period'].get(str(n),{}).get('R') for c,m in result.items()
                if m['trend_parts_by_period'].get(str(n),{}).get('K') is not None}
        ranks = percentiles(vals)
        past_ranks = percentiles({c:result[c]['trend_parts_by_period'][str(n)]['historical_R'] for c in vals})
        for c,s in ranks.items():
            part = result[c]['trend_parts_by_period'][str(n)]
            part.update(trend_period_score(part['R'], s, part['historical_R'], past_ranks[c], part['K'], P['stock_full_returns'][n]), N=len(ranks))
    groups = {}
    # S0 uses every valid R0 in the same effective limit group, even if H is unavailable.
    for c,q in quotes.items():
        valid, _, _ = quote_valid(q, now, session, center, formal_close,completed_proofs.get(c))
        if valid and finite(q.get('change_pct')) and positive(q.get('limit_pct')):
            groups.setdefault(q['limit_pct'], {})[c] = q['change_pct']
    for limit, values in groups.items():
        ranks = percentiles(values)
        for c,s in ranks.items():
            result[c]['emotion_reference'] = dict(limit_pct=limit,R0=values[c],S0=s,N=len(ranks))
            attack=P['absolute_weight']*100*clamp(values[c]/limit)+P['relative_weight']*s
            result[c]['day_attack']=rounded(attack)
            result[c]['day_attack_strong']=attack>=P['very_strong_min']
            ep = result[c]['emotion_parts']
            if not ep:
                continue
            ep.update(S0=s, N=len(ranks), D=P['absolute_weight']*ep['J']+P['relative_weight']*s)
            result[c]['day_attack'] = rounded(ep['D'])
            result[c]['day_attack_strong'] = ep['D'] >= P['very_strong_min']
            recent = result[c].get('recent_emotion')
            if recent is not None:
                ep['recent'] = recent['score']
                result[c]['emotion_score'] = rounded(P['emotion_attack_weight']*ep['D']+P['emotion_hold_weight']*ep['H']+P['emotion_recent_weight']*ep['recent'])
            else:
                result[c]['data_reasons'].append('近期活跃背景缺失；当日进攻单独展示')
    for m in result.values():
        finish(m)
    return result, aligned


def historical_scores(histories, calendar, day):
    """Completed-day evaluation: P=day close; ATR/window strictly precede that day."""
    result = {}
    for c, bars in histories.items():
        bars=observed_history.traded_bars(bars)
        prior = [b['date'] for b in bars if b['date']<day]
        by = {b['date']:b for b in bars}
        m = empty(day+' 15:00:00', '完成日历史背景')
        result[c] = m
        current = by.get(day)
        dates = prior[-21:]
        window = [by.get(d) for d in dates]
        if not current or len(dates) < 21 or any(not b or not intraday._valid_historical_price_bar(b) for b in window+[current]):
            continue
        modes = {(b.get('price_basis'),b.get('price_basis_source')) for b in window+[current]}
        if len(modes) != 1:
            continue
        basis, source = next(iter(modes))
        if not (basis == 'qfq' and source in intraday._QFQ_HISTORY_SOURCES or basis == 'raw' and source in intraday._RAW_HISTORY_SOURCES):
            continue
        atr = mean(max(window[i]['high']-window[i]['low'], abs(window[i]['high']-window[i-1]['close']),
                       abs(window[i]['low']-window[i-1]['close'])) for i in range(1,21))
        previous = [b for b in bars if b['date'] < day]
        m['trend_parts_by_period'] = trend_raw(current['close'], previous, atr, prior[-1], prior)
        m['R3'] = 100*(current['close']/previous[-3]['close']-1)
        m['consolidating'] = current['close'] < m['trend_parts_by_period']['5']['MA_now'] or m['R3'] <= 0
    for n in P['periods']:
        vals = {c:m['trend_parts_by_period'].get(str(n),{}).get('R') for c,m in result.items()
                if m['trend_parts_by_period'].get(str(n),{}).get('K') is not None}
        ranks = percentiles(vals)
        past_ranks = percentiles({c:result[c]['trend_parts_by_period'][str(n)]['historical_R'] for c in vals})
        for c,s in ranks.items():
            part = result[c]['trend_parts_by_period'][str(n)]
            part.update(trend_period_score(part['R'],s,part['historical_R'],past_ranks[c],part['K'],P['stock_full_returns'][n]), N=len(ranks))
    for m in result.values():
        finish(m)
        p = m['trend_parts_by_period'].get(str(m['dominant_period']), {})
        if m.get('consolidating') is not None and finite(p.get('dd')):
            m['consolidating'] = m['consolidating'] or p['dd'] > P['drawdown_shallow_atr']
    return result


def trim(values):
    ordered = sorted(values.items(), key=lambda x:(x[1],x[0]))
    k = max(1, math.floor(len(ordered)*P['board_trim_ratio']))
    kept = ordered[k:-k]
    return (mean(v for _,v in kept) if kept else None,
            [c for c,_ in ordered[:k]+ordered[-k:]])


def coverage(codes, expected):
    pct = len(codes)/len(expected)*100 if expected else None
    return dict(valid=len(codes), expected=len(expected), coverage_pct=pct, member_codes=sorted(codes),
                eligible=len(codes) >= P['board_min_valid_members'] and pct is not None and pct >= P['board_min_coverage_pct'])


def board_scores(boards, stocks, pool, quotes=None, at=None):
    result = {}
    for b in boards:
        m = empty(at, '主板成员共振')
        result[b['id']] = m
        # Preserve confirmed membership; missing data remains in the denominator.
        expected = set(b.get('member_codes') or []) & set(pool)
        if quotes is not None:
            expected = {c for c in expected if not (c in quotes and
                        finite(quotes[c].get('amount_wan')) and finite(quotes[c].get('volume_shou')) and
                        quotes[c]['amount_wan'] <= 0 and quotes[c]['volume_shou'] <= 0)}
        m['expected'] = len(expected)
        m['expected_codes'] = sorted(expected)
        for n in P['periods']:
            codes = [c for c in expected if finite(stocks.get(c,{}).get('trend_parts_by_period',{}).get(str(n),{}).get('T'))]
            cov = coverage(codes, expected)
            part = dict(cov, R=None,S=None,A=None,G=None,K=None,T=None, B=None, trimmed_codes=[])
            m['trend_parts_by_period'][str(n)] = part
            if not cov['eligible']:
                part['reason'] = '该周期成员不足6只或覆盖不足80%'
                continue
            part['R'],part['trimmed_codes'] = trim({c:stocks[c]['trend_parts_by_period'][str(n)]['R'] for c in codes})
            part['historical_R'],part['historical_trimmed_codes'] = trim({c:stocks[c]['trend_parts_by_period'][str(n)]['historical_R'] for c in codes})
            part['B'] = mean(stocks[c]['trend_parts_by_period'][str(n)]['K'] >= P['structure_factors']['pullback'] for c in codes)
            part['K'] = mean(stocks[c]['trend_parts_by_period'][str(n)]['K'] for c in codes)
            part['health'] = mean(stocks[c]['trend_parts_by_period'][str(n)].get('health',1.) for c in codes)
        codes = [c for c in expected if stocks.get(c,{}).get('emotion_score') is not None]
        ep = dict(coverage(codes,expected), R0=None,S0=None,J=None,D=None,B=None,H=None, trimmed_codes=[])
        m['emotion_parts'] = ep
        if ep['eligible']:
            ep['R0'],ep['trimmed_codes'] = trim({c:stocks[c]['emotion_parts']['R0'] for c in codes})
            ep['J'] = 100*clamp(ep['R0']/P['board_today_full_return'])
            ep['B'] = 100*mean(stocks[c]['emotion_score'] >= P['strong_min'] for c in codes)
            ep['H'] = median(stocks[c]['emotion_parts']['H'] for c in codes)
        else:
            m['data_reasons'].append('情绪成员不足6只或覆盖不足80%')
    for kind in ('industry','theme'):
        ids = [b['id'] for b in boards if b['type'] == kind and b.get('classification_rankable',True)]
        for n in P['periods']:
            vals = {i:result[i]['trend_parts_by_period'][str(n)]['R'] for i in ids}
            ranks = percentiles(vals)
            past_ranks = percentiles({i:result[i]['trend_parts_by_period'][str(n)].get('historical_R') for i in ranks})
            for i,s in ranks.items():
                part = result[i]['trend_parts_by_period'][str(n)]
                part.update(trend_period_score(part['R'],s,part['historical_R'],past_ranks[i],part['K'],P['board_full_returns'][n]),N=len(ranks))
        ranks = percentiles({i:result[i]['emotion_parts']['R0'] for i in ids})
        for i,s in ranks.items():
            ep = result[i]['emotion_parts']
            ep.update(S0=s,N=len(ranks),D=P['absolute_weight']*ep['J']+P['relative_weight']*s)
            weights = P['board_emotion_weights']
            result[i]['emotion_score'] = rounded(weights['attack']*ep['D']+weights['hot_share']*ep['B']+weights['hold']*ep['H'])
    for m in result.values():
        finish(m)
    return result


def sort_key(m, identity, order='combined'):
    t,e = m.get('trend_score'),m.get('emotion_score')
    last = lambda x: -x if x is not None else math.inf
    if order == 'trend':
        return last(t),last(m.get('trend_parts_by_period',{}).get(str(m.get('dominant_period')),{}).get('historical_R')),identity
    if order == 'emotion':
        return last(e),last((m.get('recent_emotion') or {}).get('score')),identity
    valid = sorted([x for x in (t,e) if x is not None],reverse=True)
    return last(valid[0] if valid else None),last(valid[1] if len(valid)>1 else None),identity


def lists(results):
    ordered = sorted(results,key=lambda c:sort_key(results[c],c))
    out = {'all':ordered, 'focus':[c for c in ordered if results[c]['focus']],
           'trend':[c for c in ordered if results[c]['trend_strong']],
           'emotion':[c for c in ordered if results[c]['emotion_strong']],
           'both':[c for c in ordered if results[c]['trend_strong'] and results[c]['emotion_strong']]}
    out['day_attack'] = sorted([c for c in results if results[c].get('day_attack_strong')],key=lambda c:(-results[c]['day_attack'],c))
    out['starting'] = [c for c in ordered if results[c]['focus'] and results[c].get('phase')=='启动']
    out['pullback'] = [c for c in ordered if results[c]['trend_strong'] and results[c].get('phase')=='回踩整理']
    out['sorts'] = {k:sorted(results,key=lambda c:sort_key(results[c],c,k)) for k in ('combined','trend','emotion')}
    return out


def morning_input(previous, now, pool):
    """A complete observed morning batch, never the price-only boundary table."""
    if not previous:
        return None
    saved = previous.get('market_strength_morning_input')
    if saved is None:
        meta = previous.get('market_strength') or {}
        if meta.get('version') != VERSION or not any(meta.get('coverage',{}).get(k) for k in ('trend_valid','emotion_valid')):
            return None
        saved = dict(at=meta.get('at'),session=previous.get('session'),
                     quotes={r['code']:{k:v for k,v in r.items() if k not in ('market_strength','radar_opportunity')}
                             for r in previous.get('stocks',[])+previous.get('coverage_catalog',[])},
                     risk_flags={r['code']:r.get('intraday_risk_flags',[]) for r in previous.get('stocks',[])+previous.get('coverage_catalog',[])})
    try:
        at = datetime.fromisoformat(saved['at'])
    except (KeyError, TypeError, ValueError):
        return None
    if at.date() != now.date() or at > now or at.hour >= 13 or saved.get('session') not in ('早盘','午间休市'):
        return None
    qs = {c:q for c,q in saved.get('quotes',{}).items() if c in pool}
    valid = {c:q for c,q in qs.items() if quote_valid(q,at,saved['session'],None)[0]}
    if not valid:
        return None
    # OHLC/previous close/limits are indispensable; price/change alone cannot
    # reconstruct the emotion holding evidence or the aligned trend basis.
    if not all(all(k in q for k in ('open','high','low','last_close','limit_pct')) for q in valid.values()):
        return None
    return dict(at=str(at),session=saved['session'],quotes=copy.deepcopy(qs),valid_codes=list(valid),risk_flags=copy.deepcopy(saved.get('risk_flags',{})))


def archived_close_input(now,pool,histories=None,calendar=None,snapshot=None):
    """Recover one intact raw closing acquisition, with original source clocks."""
    day=now.date().isoformat();path=config.CACHE_DIR/'intraday_history'/'acquisitions'/(day+'.jsonl.gz')
    selected=None
    try:
        with gzip.open(path,'rt',encoding='utf-8') as stream:
            for line in stream:
                try:
                    record=json.loads(line);capture=intraday.parse_quote_timestamp(record.get('captured_at'))
                    if not capture or capture.date()!=now.date() or capture>now:continue
                    if record.get('boundary')!='close' and record.get('session')!='已收盘':continue
                    fields=record['fields']
                    required={'code','price','last_close','quote_at','price_basis','price_basis_source','last_close_semantics'}
                    if not required.issubset(fields) or fields[0]!='code':continue
                    quotes={values[0]:dict(zip(fields[1:],values[1:])) for values in record['rows'] if values[0] in pool and len(values)==len(fields)}
                    count=0
                    for c,q in quotes.items():
                        proof=closing_price.verify(snapshot,q,(histories or {}).get(c) or [],calendar or [],now) if snapshot else None
                        count+=quote_valid(q,now,'已收盘',None,True,proof)[0]
                    if count<len(pool)*.60:continue
                    if selected is None or capture>intraday.parse_quote_timestamp(selected['archive_captured_at']):
                        selected=dict(day=day,quotes=quotes,archive_captured_at=record['captured_at'])
                except (ValueError,TypeError,KeyError,IndexError):continue
    except (OSError,EOFError,ValueError):return None
    return selected


def attach(snap, quotes, pool, histories, calendar, contexts=None, now=None, previous=None):
    now = now or datetime.fromisoformat(snap['quote_capture_at'])
    now = closing_price.assessment_time(snap,now)
    session = snap.get('session','')
    rows = {str(r['code']):r for r in snap.get('stocks',[])+snap.get('coverage_catalog',[])}
    for c in pool:
        if c not in rows:
            row = dict(pool[c] if isinstance(pool,dict) else {},code=c,coverage_only=True)
            row.update(quotes.get(c) or {})
            snap.setdefault('coverage_catalog',[]).append(row)
            rows[c] = row
        if (quotes.get(c) or {}).get('data_availability'):
            rows[c]['data_availability']=copy.deepcopy(quotes[c]['data_availability'])
    qs = {c:quotes[c] for c in pool if c in quotes}
    reference = session in ('盘前','集合竞价','竞价结束','非交易日','收盘竞价') or 897 <= now.hour*60+now.minute < 900
    verified_at = intraday.parse_quote_timestamp(snap.get('close_daily_verified_at'))
    formal_close = (session == '已收盘' and verified_at is not None and
                    verified_at.date() == now.date() and verified_at.hour*60+verified_at.minute >= 905 and
                    (verified_at-now).total_seconds() <= config.INTRADAY['max_quote_future_seconds'])
    # Suppliers may update their timestamp after the market has closed. Such
    # quotes still fail quote_valid; reuse an intact, same-day closing batch
    # with its original source clock instead of emptying the published lists.
    close_source = (previous or {}).get('market_strength_close_input') or {}
    completed_proofs={c:p for c,q in qs.items() if (p:=closing_price.verify(snap,q,histories.get(c) or [],calendar,now))} if formal_close else {}
    saved_proofs={c:p for c,q in (close_source.get('quotes') or {}).items() if c in pool and (p:=closing_price.verify(snap,q,histories.get(c) or [],calendar,now))} if formal_close and close_source.get('day')==now.date().isoformat() else {}
    if formal_close:
        saved_valid=sum(quote_valid(q,now,session,None,True,saved_proofs.get(c))[0] for c,q in (close_source.get('quotes') or {}).items() if c in pool) if close_source.get('day')==now.date().isoformat() else 0
        if saved_valid<len(pool)*.60 and sum(quote_valid(q,now,session,None,True,completed_proofs.get(c))[0] for c,q in qs.items())<len(pool)*.60:
            recovered=archived_close_input(now,pool,histories,calendar,snap)
            if recovered:
                close_source=recovered
                saved_proofs={c:p for c,q in recovered['quotes'].items() if (p:=closing_price.verify(snap,q,histories.get(c) or [],calendar,now))}
    if formal_close and close_source.get('day') == now.date().isoformat():
        saved = {c:q for c,q in (close_source.get('quotes') or {}).items() if c in pool}
        valid_now = sum(quote_valid(q,now,session,None,True,completed_proofs.get(c))[0] for c,q in qs.items())
        valid_saved = sum(quote_valid(q,now,session,None,True,saved_proofs.get(c))[0] for c,q in saved.items())
        if valid_now < len(pool)*.60 and valid_saved >= len(pool)*.60:
            qs = copy.deepcopy(saved)
            completed_proofs={c:p for c,q in qs.items() if (p:=closing_price.verify(snap,q,histories.get(c) or [],calendar,now))}
            for c,q in qs.items():
                rows[c].update(copy.deepcopy(q))
            contexts = {}  # Align preserved prices against the actual formal history.
            snap['market_strength_close_reference'] = dict(
                source_at=max(str(q.get('quote_at') or q.get('ts')) for c,q in qs.items()
                              if quote_valid(q,now,session,None,True,completed_proofs.get(c))[0]),
                archive_captured_at=close_source.get('archive_captured_at'),
                reason='收盘后源时间不用于新评分；使用当日已核验收市报价')
    # Reuse only raw return observations. Scores from the previous model are
    # never fed into the new emotion calculation. Legacy samples are accepted
    # only when their producer matches that snapshot and the pool is unchanged.
    observations={}; raw_ring=[]
    if previous:
        pool_hash=hashlib.sha256(json.dumps(sorted(pool),sort_keys=True).encode()).hexdigest()
        old_hash=previous.get('market_strength',{}).get('implementation_hash')
        old_rows={r['code']:r for r in previous.get('stocks',[])+previous.get('coverage_catalog',[])}
        for obs in previous.get('emotion_observations',[]):
            if obs.get('pool_hash')==pool_hash and intraday.parse_quote_timestamp(obs.get('at')):
                raw_ring.append(copy.deepcopy(obs))
        for obs in ([] if raw_ring else previous.get('direction_observations',[])):
            if obs.get('pool_hash')!=pool_hash or obs.get('version') not in (old_hash,IMPLEMENTATION_HASH):
                continue
            converted={}
            for c,values in obs.get('stocks',{}).items():
                quote=(obs.get('quote_evidence') or {}).get(c)
                if not quote:
                    # Legacy ring samples have a batch source clock. The prior
                    # same-day quote supplies the effective limit group only.
                    old=old_rows.get(c,{})
                    old_at=intraday.parse_quote_timestamp(old.get('quote_at') or old.get('ts'))
                    sample_at=intraday.parse_quote_timestamp(obs.get('at'))
                    if not old_at or not sample_at or old_at.date()!=sample_at.date():
                        continue
                    quote=dict(at=obs.get('at'),return_pct=values[0],limit_pct=old.get('limit_pct'))
                converted[c]=copy.deepcopy(quote)
            if converted:
                raw_ring.append(dict(at=obs.get('at'),pool_hash=pool_hash,quotes=converted))
        raw_ring=[obs for obs in raw_ring if intraday.parse_quote_timestamp(obs['at']).date()==now.date()
                  and intraday.parse_quote_timestamp(obs['at'])<=now]
        for obs in raw_ring:
            for c,quote in obs['quotes'].items():
                observations.setdefault(c,[]).append({'at':quote.get('at'),'return':quote.get('return_pct'),'limit_pct':quote.get('limit_pct')})
    current, aligned = stock_scores(qs, contexts or {}, histories, calendar, now, session, formal_close,observations,completed_proofs) if not reference else ({},{})
    raw_quotes={c:dict(at=m['quote_at'],return_pct=qs[c].get('change_pct'),limit_pct=qs[c].get('limit_pct'))
                for c,m in current.items() if m.get('quote_at') and c in qs}
    if raw_quotes:
        raw_at=max(q['at'] for q in raw_quotes.values())
        raw_ring=[obs for obs in raw_ring if obs['at']<raw_at]
        raw_ring.append(dict(at=raw_at,pool_hash=hashlib.sha256(json.dumps(sorted(pool),sort_keys=True).encode()).hexdigest(),quotes=raw_quotes))
    snap['emotion_observations']=raw_ring[-P['direction_observations_max']:]
    source = morning_input(previous,now,pool) if session == '午间休市' else None
    old_models = {r['code']:r.get('market_strength',{}) for r in (previous or {}).get('stocks',[])+(previous or {}).get('coverage_catalog',[])}
    unavailable = source and any(
        not quote_valid(qs.get(c,{}),now,session,None)[0] or
        any(old_models.get(c,{}).get(axis+'_score') is not None and current.get(c,{}).get(axis+'_score') is None
            for axis in ('trend','emotion')) for c in source['valid_codes'])
    if unavailable:
        # Recompute ONE preserved morning batch under the running implementation.
        # This also handles an implementation upgrade without trusting old scores.
        # The call has no previous snapshot, so it cannot recursively retain data.
        for c,q in source['quotes'].items():
            rows[c].update(copy.deepcopy(q))
            rows[c]['intraday_risk_flags'] = copy.deepcopy(source['risk_flags'].get(c,[]))
        old_boards = {b['id']:b for b in previous.get('board_catalog',[])}
        for board in snap.get('board_catalog',[]):
            old = old_boards.get(board['id'],{})
            for key in ('index_quote','index_trend','index_current'):
                board.pop(key,None)
                if key in old:
                    board[key] = copy.deepcopy(old[key])
        snap['session'] = source['session']
        try:
            attach(snap,source['quotes'],pool,histories,calendar,now=datetime.fromisoformat(source['at']),
                   previous=dict(emotion_observations=(previous or {}).get('emotion_observations',[])))
        finally:
            snap['session'] = session
        source_at = max(str(intraday.parse_quote_timestamp(source['quotes'][c].get('quote_at') or source['quotes'][c].get('ts'),now)) for c in source['valid_codes'])
        mode = '午休参考 · 原时点 '+source_at
        for row in snap.get('stocks',[])+snap.get('coverage_catalog',[])+snap.get('board_catalog',[]):
            row['market_strength']['mode'] = mode
            row['market_strength']['reference_source_at'] = source_at
        snap['market_strength']['at'] = str(now)
        snap['market_strength']['mode'] = mode
        snap['market_strength']['reference_source_at'] = source_at
        snap['market_strength']['reference_evaluation_at'] = source['at']
        # Regenerate member summaries after the reference annotation; other
        # projections point to these same model objects and backend lists.
        by = {r['code']:r['market_strength'] for r in snap.get('stocks',[])+snap.get('coverage_catalog',[])}
        for board in snap.get('board_catalog',[]):
            for member in board['members']:
                member['market_strength'] = brief(by[member['code']])
        return snap['market_strength']
    for c in pool:
        current.setdefault(c,empty(None,'参考行情' if reference else '连续竞价'))
        if c not in qs:
            current[c]['data_reasons'].append('本轮报价缺失')
    days = [d for d in calendar if d < now.date().isoformat()][-P['phase_history_days']:]
    history = {d:historical_scores({c:histories.get(c,[]) for c in pool},calendar,d) for d in days}
    boards = snap.get('board_catalog',[])
    board_current = board_scores(boards,current,pool,qs, str(now))
    board_history = {d:board_scores(boards,hist,pool,None,d+' 15:00:00') for d,hist in history.items()}
    for c,m in current.items():
        q = qs.get(c,{})
        bars = aligned.get(c,[])
        m['history_trend'] = [{'date':d,'score':history[d].get(c,{}).get('trend_score')} for d in days]
        m['consolidating'],m['R3'] = None,None
        if len(bars)>=5 and positive(q.get('price')):
            m['R3'] = 100*(q['price']/bars[-3]['close']-1)
            dp = m['trend_parts_by_period'].get(str(m['dominant_period']), {})
            m['consolidating'] = q['price'] < (q['price']+sum(b['close'] for b in bars[-4:]))/5 or m['R3'] <= 0 or finite(dp.get('dd')) and dp['dd'] > P['drawdown_shallow_atr']
        m['phase'],m['strong_days'] = phase(m['trend_score'],m['emotion_score'],[x['score'] for x in m['history_trend']],m['consolidating'])
        if m['phase']=='启动' and not m['trend_strong']:
            m['reasons'].append('情绪先行')
        if m['phase']=='转弱' and m['emotion_strong']:
            m['reasons'].append('短线活跃')
        if m['dominant_period'] in (5,10):
            p20 = m['trend_parts_by_period'].get('20',{})
            if p20.get('MA_now') is not None and (q['price'] < p20['MA_now'] or p20['MA_now'] < p20['MA_previous']):
                m['reasons'].append('短期走强，中期未恢复')
        if m['trend_strong']:
            m['reasons'].append(str(m['dominant_period'])+'日趋势强')
        if m['emotion_strong']:
            m['reasons'].append('当日情绪强')
        # Events depend only on reliable price evidence; never determine admission.
        if bars:
            price = q['price']
            if len(bars)>=P['breakout_days'] and price > max(b['high'] for b in bars[-P['breakout_days']:]):
                m['event_evidence']['突破'] = dict(price=price,threshold=max(b['high'] for b in bars[-20:]),dates=[b['date'] for b in bars[-20:]])
            prev = history.get(days[-1],{}).get(c,{}) if days else {}
            p5 = m['trend_parts_by_period'].get('5',{})
            if prev.get('trend_strong') and prev.get('consolidating') and m['trend_strong'] and finite(q.get('change_pct')) and q['change_pct']>0 and price >= p5.get('MA_now',math.inf) and price > max(b['high'] for b in bars[-P['restart_days']:]):
                m['event_evidence']['再启动'] = dict(price=price,previous_day=days[-1],previous_trend=prev['trend_score'],MA5=p5['MA_now'],threshold=max(b['high'] for b in bars[-3:]),dates=[b['date'] for b in bars[-3:]])
            if bars[-1]['close'] < bars[-1]['open'] and finite(q.get('change_pct')) and q['change_pct']>0 and price>=bars[-1]['open']:
                m['event_evidence']['反包'] = dict(price=price,threshold=bars[-1]['open'],date=bars[-1]['date'])
        m['events'] = [e for e in P['event_priority'] if e in m['event_evidence']]
        m['risks'] = list(dict.fromkeys(rows[c].get('intraday_risk_flags') or [])) if m.get('quote_at') else []
        # Closing price snapshots can legitimately omit intraday flags. A real
        # current quote still supplies the existing limit-relative drop rule.
        drop = intraday._drop_risk(q.get('change_pct'),q.get('limit_pct')) if m.get('quote_at') else None
        if drop:
            m['risks'].append(drop)
            if m.get('trend_strong'):
                m['phase']='明显回落'
        # Old daily risk_notes mixes qualification failures with risk facts; never project it.
        p5=m['trend_parts_by_period'].get('5',{})
        if p5.get('MA_now') is not None and positive(p5.get('ATR')):
            if (q['price']-p5['MA_now'])/p5['ATR'] > config.INTRADAY_RISK['overheat_dist_atr']:
                m['risks'].append('现价距盘中MA5过远，位置偏热')
        if m['emotion_parts'].get('actual_limit'):
            m['risks'].append('当前报价在涨停价')
        m['risks']=list(dict.fromkeys(m['risks']))
        if reference and previous and (previous.get('market_strength') or {}).get('implementation_hash') == IMPLEMENTATION_HASH:
            old = next((r.get('market_strength') for r in previous.get('stocks',[])+previous.get('coverage_catalog',[]) if r['code']==c),None)
            if old:
                m = current[c] = copy.deepcopy(old)
                m['mode'] = '参考行情 · 原时点 '+str(old.get('trend_at') or old.get('emotion_at'))
        rows[c]['market_strength'] = m
        if bars:
            rows[c]['strength_history'] = [dict(b) for b in bars[-60:]]
            rows[c]['strength_history_basis']='已按本次现价口径换算'
        elif m.get('recent_emotion'):
            rows[c]['strength_history'] = [dict(b) for b in histories.get(c,[]) if b['date']<now.date().isoformat()][-60:]
            rows[c]['strength_history_basis']='历史原口径；现价未完成口径换算'
    for b in boards:
        m = board_current[b['id']]
        m['history_trend'] = [{'date':d,'score':board_history[d][b['id']]['trend_score']} for d in days]
        m['history_basis'] = '当前确认成员的历史背景，不是当时成分回测'
        dominant = m['dominant_period']
        codes = m['trend_parts_by_period'].get(str(dominant),{}).get('member_codes',[])
        cons_codes = [c for c in codes if current[c].get('R3') is not None and current[c]['trend_parts_by_period'].get('5',{}).get('MA_now') is not None]
        cp = coverage(cons_codes,m['expected_codes'])
        cons = None
        if cp['eligible']:
            cp['R3'],cp['trimmed_codes'] = trim({c:current[c]['R3'] for c in cons_codes})
            cp['below_MA5_share'] = mean(qs[c]['price'] < current[c]['trend_parts_by_period']['5']['MA_now'] for c in cons_codes)
            day_return=m['emotion_parts'].get('R0')
            cons = cp['R3'] <= 0 or cp['below_MA5_share'] >= P['phase_consolidation_share']
        m['consolidation_parts'] = cp
        m['phase'],m['strong_days'] = phase(m['trend_score'],m['emotion_score'],[x['score'] for x in m['history_trend']],cons)
        if m['phase']=='启动' and not m['trend_strong']:
            m['reasons'].append('情绪先行')
        if m['trend_strong']:
            m['reasons'].append(str(dominant)+'日成员趋势共振')
        if m['emotion_strong']:
            m['reasons'].append('成员情绪共振')
        m['member_event_counts'] = {e:sum(e in current[c]['events'] for c in m['expected_codes']) for e in P['event_priority']}
        m['events'] = [e+str(n)+'只' for e,n in m['member_event_counts'].items() if n]
        idx = (b.get('index_quote') or b.get('index_trend') or {})
        index_r = idx.get('change_pct',idx.get('ret1'))
        rb = m['emotion_parts'].get('R0')
        m['index_reference'] = copy.deepcopy(idx)
        idx_current=b.get('index_current') or {}
        index_valid=bool(idx.get('valid',idx.get('ready',False)) or
                         idx_current.get('ready') and idx_current.get('quote_at')==idx.get('quote_at'))
        m['index_reference']['valid']=index_valid
        if finite(index_r) and finite(rb) and index_r*rb < 0 and index_valid:
            m['reasons'].append('指数/主板成员分歧')
        if reference and previous and (previous.get('market_strength') or {}).get('implementation_hash') == IMPLEMENTATION_HASH:
            old=next((x.get('market_strength') for x in previous.get('board_catalog',[]) if x['id']==b['id']),None)
            if old:
                m=board_current[b['id']]=copy.deepcopy(old)
                m['mode']='参考行情 · 原时点 '+str(old.get('trend_at') or old.get('emotion_at'))
        b['market_strength'] = m
        # Every member, including emotion-only and unknown stocks, uses the stock's single result.
        b['members'] = [dict(code=c,name=rows[c].get('name'),change_pct=rows[c].get('change_pct'),market_strength=brief(current[c])) for c in sorted(set(b.get('member_codes',[]))) if c in current]
        b['lists'] = {k:[r['code'] for r in b['members'] if r['market_strength'][k+'_strong']] for k in ('trend','emotion')}
        b['lists']['focus'] = [r['code'] for r in b['members'] if r['market_strength']['focus']]
        b['opportunity'] = dict(version=VERSION,current_opportunity=m['focus'],primary_label=m['phase'],status=m['phase'] or '—',market_strength=m)
    import direction_changes
    direction_changes.attach(snap, previous, current, board_current, boards, rows, qs, now,
                             reference=reference, parameters=P, implementation_hash=IMPLEMENTATION_HASH)
    stock_lists,board_lists = lists(current),lists(board_current)
    pool_stats = {}
    for n in P['periods']:
        codes = sorted(c for c,m in current.items() if finite(m['trend_parts_by_period'].get(str(n),{}).get('T')))
        pool_stats[str(n)] = dict(N=len(codes),coverage_pct=len(codes)/len(pool)*100 if pool else None,hash=hashlib.sha256(json.dumps(codes).encode()).hexdigest())
    emotion_codes = sorted(c for c,m in current.items() if m['emotion_score'] is not None)
    emotion_groups = {}
    for limit in sorted({q['limit_pct'] for q in qs.values() if positive(q.get('limit_pct'))}):
        codes = sorted(c for c in current if current[c].get('emotion_reference',{}).get('limit_pct')==limit)
        emotion_groups[str(limit)] = dict(N=len(codes),valid=sum(current[c]['emotion_score'] is not None for c in codes),
                                         member_codes=codes,hash=hashlib.sha256(json.dumps(codes).encode()).hexdigest())
    board_pools={}
    for kind in ('industry','theme'):
        ids=[b['id'] for b in boards if b['type']==kind]
        board_pools[kind]={}
        for axis in [str(n) for n in P['periods']]+['emotion']:
            valid_ids=sorted(i for i in ids if (board_current[i]['emotion_score'] if axis=='emotion' else
                             board_current[i]['trend_parts_by_period'].get(axis,{}).get('T')) is not None)
            board_pools[kind][axis]=dict(N=len(valid_ids),ids=valid_ids,hash=hashlib.sha256(json.dumps(valid_ids).encode()).hexdigest())
    snap['market_strength'] = dict(version=VERSION,implementation_hash=IMPLEMENTATION_HASH,parameters=copy.deepcopy(P),
        at=str(now),mode='参考行情' if reference else '正式收盘' if formal_close else '午休参考' if session=='午间休市' else '连续竞价',
        stocks=stock_lists,boards=board_lists,counts={k:len(stock_lists[k]) for k in ('all','focus','trend','emotion','both')},
        board_counts={k:len(board_lists[k]) for k in ('all','focus','trend','emotion','both')},
        reference_pools=pool_stats,emotion_reference_pools=emotion_groups,board_reference_pools=board_pools,
        coverage=dict(pool=len(pool),trend_valid=sum(m['trend_score'] is not None for m in current.values()),
                      emotion_valid=len(emotion_codes),trend_missing=sum(m['trend_score'] is None for m in current.values()),
                      emotion_missing=len(pool)-len(emotion_codes)))
    if formal_close:
        snap['market_strength']['close_verification']=dict(date=now.date().isoformat(),expected=len(pool),verified=len(completed_proofs),
            source_at=max((p['quote_at'] for p in completed_proofs.values()),default=None),basis='独立完成日线开高低收及价格尺度逐项核验')
    # Legacy opportunity objects are projections only. No waiting state or lifecycle accumulation.
    by_code = {c:dict(code=c,name=rows[c].get('name'),version=VERSION,current=m['focus'],market_strength=m,
                     labels=m['events'],main_label=m['phase'],status=m['phase'] or '—',risk=m['risks'],boards=[],categories={}) for c,m in current.items()}
    for c,r in rows.items():
        r['radar_opportunity'] = by_code[c]
    snap['radar_opportunity'] = dict(version=VERSION,implementation_hash=IMPLEMENTATION_HASH,by_code=by_code,
        lists=dict(current=stock_lists['focus']),counts=dict(current=len(stock_lists['focus'])),market_strength_version=VERSION)
    snap['radar'] = dict(market_strength=stock_lists)
    snap['board_opportunity_model'] = dict(version=VERSION,counts=dict(current=len(board_lists['focus'])),lists=dict(current=board_lists['focus']))
    snap.pop('market_strength_morning_input',None)
    snap.pop('market_strength_close_input',None)
    if session == '已收盘':
        closing = {c:copy.deepcopy(qs[c]) for c,m in current.items()
                   if m.get('quote_at') and c in qs}
        if closing:
            snap['market_strength_close_input'] = dict(day=now.date().isoformat(),quotes=closing)
    if session in ('早盘','午间休市') and (any(m['trend_score'] is not None or m['emotion_score'] is not None for m in current.values())):
        snap['market_strength_morning_input'] = dict(at=str(now),session=session,
            quotes=copy.deepcopy(qs),
            risk_flags={c:copy.deepcopy(rows[c].get('intraday_risk_flags',[])) for c in qs})
    return snap['market_strength']


def validate(snap):
    meta = snap['market_strength']
    assert meta['version'] == VERSION
    assert meta['implementation_hash'] == IMPLEMENTATION_HASH
    assert json.dumps(json.loads(json.dumps(meta['parameters'])),sort_keys=True) == json.dumps(json.loads(json.dumps(P)),sort_keys=True)
    rows = snap.get('stocks',[])+snap.get('coverage_catalog',[])
    assert len(rows) == len({r['code'] for r in rows}), 'duplicate stock'
    stocks = {r['code']:r['market_strength'] for r in rows}
    boards = {b['id']:b['market_strength'] for b in snap.get('board_catalog',[])}
    for objects in (stocks,boards):
        for c,m in objects.items():
            assert m['version'] == VERSION
            for axis in ('trend','emotion'):
                score = m[axis+'_score']
                assert score is None or finite(score) and 0<=score<=100 and rounded(score)==score
                assert m[axis+'_strong'] == (score is not None and score>=P['strong_min'])
                assert m[axis+'_level'] == level(score)
            assert m['focus'] == (m['trend_strong'] or m['emotion_strong'])
            assert (m['trend_score'],m['dominant_period']) == choose(m['trend_parts_by_period'])
            for n,part in m['trend_parts_by_period'].items():
                if part.get('T') is not None:
                    scale = P['board_full_returns' if objects is boards else 'stock_full_returns'][int(n)]
                    expected = trend_period_score(part['R'],part['S'],part['historical_R'],part['historical_S'],part['K'],scale)
                    assert all(abs(part[k]-v)<1e-8 for k,v in expected.items())
                    if objects is boards:
                        assert part['valid'] >= P['board_min_valid_members'] and part['coverage_pct']>=P['board_min_coverage_pct']
            if objects is stocks and m['emotion_score'] is not None:
                ep=m['emotion_parts']
                assert m['emotion_score'] == rounded(P['emotion_attack_weight']*ep['D']+P['emotion_hold_weight']*ep['H']+P['emotion_recent_weight']*ep['recent'])
    assert meta['stocks'] == lists(stocks)
    assert meta['boards'] == lists(boards)
    assert meta['counts'] == {k:len(meta['stocks'][k]) for k in ('all','focus','trend','emotion','both')}
    assert meta['board_counts'] == {k:len(meta['boards'][k]) for k in ('all','focus','trend','emotion','both')}
    assert snap['radar_opportunity']['lists']['current']==meta['stocks']['focus']
    for b in snap.get('board_catalog',[]):
        assert b['opportunity']['current_opportunity']==b['market_strength']['focus']
        assert len(b['members'])==len({r['code'] for r in b['members']})
        for r in b['members']:assert r['market_strength']==brief(stocks[r['code']])
        for axis in ('trend','emotion'):assert b['lists'][axis]==[r['code'] for r in b['members'] if r['market_strength'][axis+'_strong']]
    return True
