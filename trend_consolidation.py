"""强股整理观察：完成日确定平台与进攻前史，真实采样确定盘中变化。"""
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
from statistics import mean

import config
import intraday
import intraday_path
import stock_strength
import consolidation_tracking
import consolidation_rebound
import consolidation_proximity

VERSION = "强股整理观察7"
COMPATIBLE_VERSIONS = (VERSION, '强股整理观察6', '强股整理观察5')
DIRECTORY = config.CACHE_DIR / "trend_consolidation"
SEVERE = {"接近跌停", "大幅下跌", "明显冲高回落", "一字跌停",
          "现价失守盘中MA10", "现价失守盘中MA20"}


def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def ma(bars, end, period):
    return mean(b['close'] for b in bars[end-period+1:end+1])


def online(bars, i):
    return (i >= 20 and ma(bars,i,5) > ma(bars,i,10) > ma(bars,i,20)
            and ma(bars,i,20) > ma(bars,i-1,20) and bars[i]['close'] >= ma(bars,i,10))


def attack_before(bars, peak, require_trend=False):
    """只从整理前的端点计算进攻；A档不能绕过绝对涨幅。"""
    p = config.TREND_CONSOLIDATION
    endpoints = range(peak-p['impulse_search_days']+1, peak+1)
    choices=list(endpoints)
    trend_choices=[i for i in choices if online(bars,i)] if require_trend else choices
    values = {n: max((100*(bars[i]['close']/bars[i-n]['close']-1), i)
                     for i in (trend_choices or choices) if i >= n) for n in (5,10)}
    passed = [n for n in (5,10) if values[n][0] >= p[f'impulse{n}_min_pct']-1e-9]
    period = passed[0] if passed else 5
    return dict(qualified=bool(passed) and (not require_trend or bool(trend_choices)), impulse5_pct=round(values[5][0],3),
                impulse10_pct=round(values[10][0],3), attack_period=period,
                attack_gain_pct=round(values[period][0],3),
                impulse_end=bars[values[period][1]]['date'], end_index=values[period][1],
                attack_trend_online=bool(trend_choices) if require_trend else None)


def _daily_setup(history, asof, calendar, a_dates=()):
    """未来K线先截断；上涨端点必须早于整理首日，不用当前档位替代前史。"""
    p = config.TREND_CONSOLIDATION
    bars = sorted((dict(b) for b in history if str(b.get('date','')) <= asof), key=lambda b:b['date'])
    def fail(why,pending=False,**facts):
        return dict(eligible=False,reason=why,pending=pending,
                    stage='历史数据待补齐' if pending else '尚未形成整理' if '至少2个完成交易日' in why else '整理条件未满足',
                    failure_kind='data_unavailable' if pending else 'condition_unmet',
                    baseline_asof=asof,history_available_count=len(bars),history_required=p['history_bars'],**facts)
    window = p['history_bars']
    dates = [d for d in calendar if d <= asof][-window:]
    if len(bars) < window or len(dates) < window:
        return fail('整理判断所需40个完成交易日不足', True)
    bars = bars[-window:]
    if [b['date'] for b in bars] != dates or len(set(dates)) != len(dates):
        return fail('整理历史窗口有交易日缺口或日期重复', True)
    modes = {(b.get('price_basis'),b.get('price_basis_source')) for b in bars}
    allowed = {('qfq',s) for s in intraday._QFQ_HISTORY_SOURCES} | {('raw',s) for s in intraday._RAW_HISTORY_SOURCES}
    if len(modes) != 1 or not modes.issubset(allowed):
        return fail('整理历史价格来源或复权方式待核验', True)
    if not all(intraday._valid_historical_price_bar(b) for b in bars):
        return fail('整理历史含异常OHLC价格', True)
    end = len(bars)-1
    ranges=[b['high']-b['low'] if i==0 else max(b['high']-b['low'],abs(b['high']-bars[i-1]['close']),abs(b['low']-bars[i-1]['close']))
            for i,b in enumerate(bars)]
    atr=mean(ranges[-20:])
    if atr <= 0:
        return fail('整理ATR无效', True)
    # 最近12天以内的收盘峰值是确定性的锚点；当日最高价不改写平台。
    peak = max(range(end-p['max_days'],end+1), key=lambda i:(bars[i]['close'],i))
    age = end-peak
    anchor_kind='近期收盘峰值'
    # 平台可以小幅抬高；波动收敛属于质量加分，不代替平台宽度资格。
    if age < 3:
        for candidate in range(end-3,end-p['max_days']-1,-1):
            quiet=bars[candidate+1:]
            tight=(max(b['high'] for b in quiet)-min(b['low'] for b in quiet))/atr <= p['horizontal_range_atr']
            slow=max(b['close'] for b in quiet)-bars[candidate]['close'] <= p['horizontal_rise_allow_atr']*atr
            impulse_before=attack_before(bars,candidate,require_trend=True)
            if tight and slow and online(bars,candidate) and impulse_before['qualified']:
                peak=candidate;age=end-peak;anchor_kind='上涨窗口末日';break
    strict = online(bars,end)
    if not strict:
        return fail('完成日未满足MA5>MA10>MA20、MA20向上及守住MA10')
    if age < p['min_pullback_days']:
        return fail('尚未形成至少2个完成交易日的整理',completed_consolidation_days=age,
                    minimum_consolidation_days=p['min_pullback_days'])
    if not online(bars,peak):
        return fail('整理前锚点未形成多头排列，不属于前期强股整理')
    consolidation = bars[peak+1:]
    if any(bars[i]['close'] < ma(bars,i,20) for i in range(peak+1,end+1)):
        return fail('整理期间完成日收盘曾失守MA20')
    ma10_repaired=any(bars[i]['close'] < ma(bars,i,10) for i in range(peak+1,end+1))
    if ma10_repaired and bars[end]['close'] < ma(bars,end,5):
        return fail('整理曾失守MA10，尚未收复MA5')
    attack=attack_before(bars,peak,require_trend=True)
    impulse_end=attack['end_index']
    a_before = sorted(d for d in a_dates if bars[max(0,peak-p['impulse_search_days']+1)]['date'] <= d <= bars[peak]['date'])
    if not attack['qualified']:
        return fail('整理前进攻不足或上涨终点未多头排列：5日需涨15%或10日需涨20%')
    pullback = max(0,(bars[peak]['close']-bars[end]['close'])/atr)
    width = (max(b['high'] for b in consolidation)-min(b['low'] for b in consolidation))/atr
    if pullback > p['max_pullback_atr']:
        return fail('整理回撤超过2.5 ATR')
    if width > p['max_pullback_width_atr']:
        return fail('整理区间超过3 ATR，波动过宽')
    if len(consolidation) >= 3 and all(consolidation[i]['low'] < consolidation[i-1]['low']
                                      and consolidation[i]['close'] < consolidation[i-1]['close'] for i in (-1,-2)):
        return fail('整理连续低点及收盘价下移')
    horizontal = age >= 3 and width <= p['horizontal_range_atr']
    if not horizontal and pullback < p['preferred_pullback_atr'][0]:
        return fail('回踩幅度不足且尚无横盘平台')
    rise = bars[impulse_end-attack['attack_period']+1:impulse_end+1]
    volumes_valid = all(number(b.get('volume')) and b['volume'] > 0 for b in rise+consolidation)
    vr = mean(b['volume'] for b in consolidation)/mean(b['volume'] for b in rise) if volumes_valid else None
    # 同时比上涨窗口和紧邻的量能基准，避免把上涨后正常换手误叫放量下跌。
    down_days = [bars[i]['date'] for i in range(peak+1,end+1)
                if volumes_valid and bars[i]['volume'] > p['expanded_down_volume_ratio']*max(
                    mean(r['volume'] for r in rise),mean(r['volume'] for r in bars[i-5:i]),bars[i-1]['volume'])
                             and bars[i-1]['close']-bars[i]['close'] >= p['expanded_down_move_atr']*atr
                ]
    # 分歧仍可观察，初启动确认必须连续采样收复修复价。
    repair_price=max([bars[-1]['high']]+[b['close'] for b in consolidation if b['date'] in down_days])
    contraction = mean(ranges[max(peak+1,end-2):])/mean(ranges[peak-2:peak+1]) if mean(ranges[peak-2:peak+1]) > 0 else None
    preferred = p['preferred_days'][0] <= age <= p['preferred_days'][1]
    shrink = vr is not None and vr <= p['shrink_volume_ratio']
    contracted = contraction is not None and contraction <= p['contract_range_ratio']
    quality = 30*preferred + 25*shrink + 25*contracted + 20*(p['preferred_pullback_atr'][0] <= pullback <= p['preferred_pullback_atr'][1])
    setup=dict(eligible=True,phase='consolidating', baseline_asof=asof, setup_id=bars[peak]['date']+'|'+asof,
                consolidation_asof=asof,
                peak_date=bars[peak]['date'], anchor_kind=anchor_kind, consolidation_start=consolidation[0]['date'],
                days=age, preferred_days=preferred, trend_online=strict,
                trend_label='多头排列 · MA20向上',
                **{k:v for k,v in attack.items() if k not in ('qualified','end_index')},
                attack_evidence='整理前实际进攻，A档不豁免涨幅',
                attack_a_dates=a_before, shape='横盘整理' if horizontal else '回踩整理',
                expanded_down_dates=down_days,ma10_repaired=ma10_repaired,
                needs_repair_confirmation=bool(down_days or ma10_repaired),repair_price=repair_price,
                quality_score=quality, shrink_volume=shrink, volume_ratio=round(vr,3) if vr is not None else None,
                volume_status='完成日量能可比' if volumes_valid else '量能待核验，未计缩量加分',
                contraction_ratio=round(contraction,3) if contraction is not None else None,
                range_contracting=contracted, pullback_atr=round(pullback,3), width_atr=round(width,3),
                peak_close=bars[peak]['close'], trough_close=min(b['close'] for b in consolidation),
                platform_high=max(b['high'] for b in bars[peak:]),
                platform_low=min(b['low'] for b in consolidation),
                previous_high=bars[-1]['high'], atr20=atr)
    return setup


def daily_setup(history, asof, calendar, a_dates=(), _allow_breakout=True):
    """先有合格整理，再查其后的转强；不能用后来平台倒推主升日已整理完成。"""
    base=_daily_setup(history,asof,calendar,a_dates)
    if not _allow_breakout or base.get('pending') or '完成日未满足' in base.get('reason',''):return base
    bars=sorted((b for b in history if b['date']<=asof),key=lambda b:b['date'])
    if len(bars)<40:return base
    initial=None
    for back in range(1,4):
        prior=_daily_setup(history,bars[-back-1]['date'],calendar,a_dates)
        if not prior['eligible']:continue
        for i in range(len(bars)-back,len(bars)):
            if bars[i]['close']<ma(bars,i,20):break
            if not online(bars,i):continue
            ranges=[max(bars[j]['high']-bars[j]['low'],abs(bars[j]['high']-bars[j-1]['close']),
                        abs(bars[j]['low']-bars[j-1]['close'])) for j in range(i-19,i+1)]
            signal=completion_signal(prior,bars[i]['close'],ma(bars,i,5),mean(ranges),
                                     100*(bars[i]['close']/bars[i-1]['close']-1),previous_high=bars[i-1]['high'])
            if signal:
                return dict(prior,eligible=False,phase='completed',stage='已整理完毕转强',
                            reason=signal['reason'],completion_type=signal['kind'],completion_level=signal['level'],
                            completed_at=bars[i]['date'],completion_confirmed=True,
                            completion_evidence='合格整理之后的完成日收盘确认',
                            baseline_asof=asof,setup_id=prior['peak_date']+'|'+asof)
        later=range(len(bars)-back,len(bars))
        if initial is None and all(online(bars,i) and bars[i]['close']>ma(bars,i,5)
                                   and bars[i]['close']>prior['previous_high'] for i in later):
            initial=dict(prior,phase='initial',stage='初步转强',daily_initial=True,
                         baseline_asof=asof,setup_id=prior['peak_date']+'|'+asof,
                         previous_high=bars[-1]['high'])
    if not base['eligible'] and initial is not None:return initial
    return base


def completion_signal(setup,price,ma5,atr,gain,previous_high=None,factor=1.0):
    """涨幅只能证明已走远；整理转强还须突破平台或实质收复回踩。"""
    if not departure_reason(setup,price,ma5,atr,gain,previous_high,factor):return None
    previous=setup['previous_high']*factor if previous_high is None else previous_high
    if price<=ma5 or price<=previous:return None
    platform=setup['platform_high']*factor
    if price>platform:
        return dict(kind='平台突破转强',level=platform,reason='合格整理后突破固定平台并离开初启动范围')
    trough=setup.get('trough_close');peak=setup.get('peak_close')
    if not number(trough) or not number(peak) or peak<=trough or setup['pullback_atr']<0.5:return None
    recovery=trough*factor+(peak-trough)*factor*config.TREND_CONSOLIDATION['repair_recovery_min']
    level=max(previous,recovery)
    if gain>=config.TREND_CONSOLIDATION['clear_turn_gain_pct'] and price>=level:
        return dict(kind='回踩修复转强',level=level,reason='合格回踩后收复至少80%回撤，突破前日高点并站上MA5')
    return None


def departure_reason(setup, price, ma5, atr, gain, previous_high=None, factor=1.0):
    """主名单只覆盖整理/初启动；幅度与位置已经走远则退出，不受确认计数影响。"""
    p=config.TREND_CONSOLIDATION
    if not all(number(v) for v in (price,ma5,atr,gain)) or atr <= 0 or gain <= 0:return None
    platform=setup['platform_high']*factor
    previous=setup['previous_high']*factor if previous_high is None else previous_high
    if gain >= p['clear_turn_gain_pct']:
        return f"已明显拉升{gain:.2f}%，离开整理观察阶段"
    if price > platform and gain > p['initial_max_gain_pct']:
        return f"突破平台后已拉升{gain:.2f}%，超出初启动{p['initial_max_gain_pct']:g}%范围"
    if price-platform > p['initial_max_platform_atr']*atr:
        return '已离开原整理平台超过0.5 ATR'
    if price > previous and price-ma5 > p['initial_max_ma5_atr']*atr:
        return '已转强且离开MA5超过0.8 ATR'
    return None


def sampled_completion(setup, context, points):
    """只有不同时间、连续、同方向的有效采样才确认整理完成。"""
    chain=[];confirmed=None
    for pt in points:
        if not (pt.get('valid') and pt.get('trend_ok') is True and number(pt.get('ma10'))
                and number(pt.get('price')) and pt['price']>=pt['ma10']
                and not SEVERE.intersection(pt.get('flags') or [])):
            chain=[];continue
        if chain:
            gap=intraday_path.gap_seconds(chain[-1]['at'],pt.get('at'))
            if gap is not None and gap<0:continue
            if pt.get('at')==chain[-1]['at']:continue
            if gap is None or gap>config.TREND_CONSOLIDATION['max_sample_gap_seconds']:chain=[]
        signal=completion_signal(setup,pt.get('price'),pt.get('ma5'),context['atr20'],pt.get('change'),
                                 factor=context['scale_factor'])
        if signal is None:chain=[];continue
        if chain and chain[-1]['kind']!=signal['kind']:chain=[]
        chain.append(dict(at=pt['at'],**signal))
        if len(chain)>=config.TREND_CONSOLIDATION['confirmation_samples'] and confirmed is None:
            confirmed=dict(chain[-1],samples=len(chain))
    return confirmed


def historical_a_dates(asof, calendar):
    result = {}
    for day in [d for d in calendar if d <= asof][-config.TREND_CONSOLIDATION['max_days']-5:]:
        try: record = json.loads(stock_strength._daily_path(day).read_text(encoding='utf-8'))
        except (OSError, ValueError): continue
        if record.get('version') != stock_strength.VERSION or record.get('asof') != day: continue
        for code,row in (record.get('stocks') or {}).items():
            if row.get('tier') == 'A': result.setdefault(code,[]).append(day)
    return result


def sampling_confirmation(row, setup, context, points):
    """旧采样只取已核验价格/方向；缺口、迟到、重复与午休的口径一致。"""
    factor = context['scale_factor']
    platform, previous = setup['platform_high']*factor, setup['previous_high']*factor
    now = dict(at=row.get('intraday_judgment_at'), valid=row.get('intraday_observation_available') is True,
               price=row.get('price'), ma10=row.get('intraday_ma10_trigger_price'),
               relative=row.get('intraday_relative_return_pct'), open_return=row.get('intraday_open_return_pct'),
               flags=row.get('intraday_risk_flags') or [],
               trend_ok=intraday.provisional_trend(context['aligned_bars'],row.get('price'))['intraday_trend_ok'])
    sequence = []
    for point in list(points)+[now]:
        if not point.get('valid') or not number(point.get('price')) or not number(point.get('ma10')):
            sequence=[]; continue
        if sequence:
            gap=intraday_path.gap_seconds(sequence[-1].get('at'),point.get('at'))
            if gap is not None and gap < 0: continue
            if gap is None or gap > config.TREND_CONSOLIDATION['max_sample_gap_seconds']: sequence=[]
            elif point.get('at') == sequence[-1].get('at'): sequence[-1]=point; continue
        sequence.append(point)
    def holds(point):
        return (point.get('trend_ok') is True and point['price'] >= point['ma10']
                and not SEVERE.intersection(point.get('flags') or []))
    def turning(point,level):
        return (holds(point) and point['price'] > level and number(point.get('relative')) and point['relative'] > 0
                and number(point.get('open_return')) and point['open_return'] >= 0)
    def count(predicate):
        n=0
        for point in reversed(sequence):
            if not predicate(point): break
            n+=1
        return n
    repair=setup['repair_price']*factor
    hold_n, turn_n, break_n=count(holds),count(lambda p:turning(p,previous)),count(lambda p:turning(p,platform))
    repair_n=count(lambda p:turning(p,repair))
    need=config.TREND_CONSOLIDATION['confirmation_samples']
    stage='强股整理'
    if break_n >= need: stage='初步突破'
    elif turn_n >= need: stage='初步转强'
    elif break_n: stage='平台突破待确认'
    elif hold_n >= need and len(sequence)>=2 and sequence[-1]['price'] > sequence[-2]['price']: stage='回踩企稳观察'
    return dict(stage=stage, hold_samples=hold_n, turn_samples=turn_n, breakout_samples=break_n,
                repair_samples=repair_n,repair_trigger_price=round(repair,4),
                confirmation_samples=break_n if '突破' in stage else turn_n if '转强' in stage else hold_n,
                platform_high=round(platform,4), previous_high=round(previous,4),
                platform_distance_pct=round((platform/row['price']-1)*100,3),
                confirmed=stage in ('初步突破','初步转强'),
                confirmation_note='不同时间有效采样；重复不累加，缺口中断；盘中成立仍待收盘确认')


def order(item):
    priority={'初步突破':0,'初步转强':1,'平台突破待确认':2,'回踩企稳观察':4,'强股整理':5}
    return (bool(item.get('reference_only')),bool(item.get('risk_flags') or item.get('needs_repair_confirmation')),
            3 if item.get('rebound_active') else priority.get(item['stage'],9),-item['quality_score'],-item['impulse5_pct'],
            item['code'])


GROUPS = ('rows', 'completed_rows', 'pending_rows', 'withdrawn_rows')


def duration(item,calendar,day):
    if not item.get('consolidation_start') or not calendar: return item
    end=item.get('close_review_day') or item.get('baseline_asof')
    if item.get('completion_confirmed'):
        completed_day=str(item.get('completed_at') or '')[:10]
        end=max((d for d in calendar if d<completed_day),default=end)
    finished=[d for d in calendar if item['consolidation_start']<=d<=str(end or '')]
    item.update(consolidation_elapsed_days=len(finished),consolidation_elapsed_asof=end)
    if not item.get('completion_confirmed') and end and day>end:
        item['consolidation_day_number']=len(finished)+1
    return item


def tracking_origin(prior, bars, asof, calendar):
    """用当前复权历史重建原合格整理，不能以当前MA5交叉抹掉已经确认的事件。"""
    origin = _daily_setup(bars, prior.get('consolidation_asof') or prior.get('baseline_asof'), calendar)
    if not origin.get('eligible'):
        return dict(prior, pending=True, tracking_pending=True,
                    reason='原整理结构/价格口径待核验：' + origin.get('reason', '历史不足'))
    if not prior.get('completion_confirmed'):
        result = dict(prior)
        for key in ('platform_high', 'platform_low', 'peak_close', 'trough_close', 'previous_high', 'atr20'):
            result[key] = origin[key]
        result.update(eligible=True, phase='consolidating', baseline_asof=asof,
                      observation_history_qualified=True, pending=False, tracking_pending=False)
        return result
    before = sorted((b for b in bars if b['date'] <= asof and b['date'] < str(prior['completed_at'])[:10]), key=lambda b:b['date'])
    if not before:
        return dict(prior, pending=True, tracking_pending=True, reason='转强前日价格待核验')
    level = origin['platform_high'] if prior['completion_type'] == '平台突破转强' else max(
        before[-1]['high'], origin['trough_close'] + (origin['peak_close']-origin['trough_close'])*config.TREND_CONSOLIDATION['repair_recovery_min'])
    result = dict(prior)
    for key in ('platform_high', 'platform_low', 'peak_close', 'trough_close', 'previous_high', 'atr20'):
        result[key] = origin[key]
    result.update(eligible=False, phase='completed', completion_level=level, pending=False, tracking_pending=False)
    return result


def confirmed_item(row, setup, context, points, prior=None, bars=()):
    at = row['intraday_judgment_at']
    current = intraday.provisional_trend(context['aligned_bars'], row['price'])
    point = dict(at=at, valid=True, price=row['price'], ma10=context['thresholds'][10],
                 ma20=context['thresholds'][20],
                 ma5=context['provisional_ma'][5], flags=row.get('intraday_risk_flags') or [])
    level = setup['completion_level'] * context['scale_factor']
    status = consolidation_tracking.review(setup, points, point, level, current['intraday_trend_ok'], prior)
    item = dict(setup, **status)
    item.update(code=row['code'], name=row.get('name'), price=row['price'], change_pct=row.get('change_pct'), quote_at=at,
                completion_confirmed=True, eligible=False, phase='withdrawn' if status['trend_exited'] else 'completed',
                completion_trigger_price=round(level, 4), reference_only=False)
    item.update(consolidation_proximity.observe(setup, context, row['price'], at, status['trend_exited']))
    if not status['trend_exited']:
        item.update(consolidation_rebound.observe(setup, bars, context, row, points))
    return item


def close_review(item, bars, day, calendar):
    """正式完成日仅复核旧跟踪，不回填新盘中信号；直接使用同源日线收盘与均线。"""
    frame = _daily_setup(bars, day, calendar)
    ordered = sorted((b for b in bars if b['date'] <= day), key=lambda b:b['date'])
    if frame.get('pending') or not ordered or ordered[-1]['date'] != day:
        return dict(item, reference_only=True, current_breakout_confirmed=False,
                    stage='已转强·收盘待核验',last_verified_stage=item.get('last_verified_stage') or item.get('stage'),
                    support_alerts=[],close_review_status='收盘MA20待核验', close_review_reason=frame.get('reason', '正式收盘日线不足'))
    origin = tracking_origin(item, bars, day, calendar)
    if origin.get('tracking_pending'):
        return dict(item, reference_only=True, current_breakout_confirmed=False,
                    stage='已转强·收盘待核验',last_verified_stage=item.get('last_verified_stage') or item.get('stage'),
                    support_alerts=[],close_review_status='收盘MA20待核验', close_review_reason=origin['reason'])
    end = len(ordered)-1
    close, line10, line5 = ordered[-1]['close'], ma(ordered,end,10), ma(ordered,end,5)
    line20 = ma(ordered,end,20)
    close_atr = mean(max(b['high']-b['low'],abs(b['high']-ordered[i-1]['close']),abs(b['low']-ordered[i-1]['close']))
                     for i,b in enumerate(ordered) if end-19<=i<=end)
    point = dict(at=day+' 15:00:00', valid=True, price=close, ma10=line10, ma5=line5,ma20=line20,
                 flags=item.get('risk_flags') or [])
    # 已确认盘中失守不能被收盘的一次收复直接恢复。
    state = consolidation_tracking.review(origin, [], point, origin.get('completion_level',origin['platform_high']), online(ordered,end), item)
    if close < line20:
        state.update(trend_exited=True, tracking_state='ma20_close_lost',
                     stage='收盘确认失守MA20，退出跟踪', reason='正式完成日收盘低于同口径MA20',
                     trend_exit_at=(item.get('trend_exit_at') if item.get('exit_line')=='MA20' and item.get('trend_exited') else None) or day+' 15:00:00',
                     current_breakout_confirmed=False)
    elif close < line10 and not state['trend_exited']:
        state.update(ma10_downgraded=True,tracking_state='ma10_close_downgraded',
                     stage='收盘失守MA10·降级观察MA20',reason='正式收盘低于MA10，仍守住MA20，保留承接及反弹观察',
                     current_breakout_confirmed=False)
    elif not item.get('completion_confirmed') and state['tracking_state']=='holding':
        state.update(stage='整理中·收盘守线',reason='原合格整理仍守线，未新增转强确认',current_breakout_confirmed=False)
    result = dict(item, **state)
    # 盘中价和原转强位保留原报价口径；收盘复核单独标注日线口径，避免混用。
    result.update(phase='withdrawn' if state['trend_exited'] else 'completed' if item.get('completion_confirmed') else 'consolidating',
                  reference_only=True, close_review_status=state['stage'], close_review_day=day,
                  close_review_price=close, close_review_ma10=line10, close_review_ma5=line5,close_review_ma20=line20,
                  close_review_price_basis=ordered[-1]['price_basis'],
                  close_review_source=ordered[-1]['price_basis_source'],
                  close_review_completion_level=origin.get('completion_level'))
    result.update(consolidation_proximity.observe(origin,dict(valid=True,atr20=close_atr,scale_factor=1,
                  thresholds={5:line5,10:line10,20:line20}),close,day+' 15:00:00',state['trend_exited']))
    result['support_alert_basis']='completed_daily'
    if not state['trend_exited']:
        rebound=consolidation_rebound.daily(dict(origin,baseline_asof=day,atr20=close_atr),ordered)
        if rebound:
            rebound.update(rebound_active=close>rebound['rebound_touch_price']+.25*rebound['rebound_atr'] and
                           close>=ma(ordered,end,rebound['rebound_line']),rebound_label='回踩反弹·MA'+str(rebound['rebound_line']))
            result.update(rebound)
            if rebound['rebound_active'] and (not item.get('completion_confirmed') or state['tracking_state']=='ma10_close_downgraded'):
                result['stage']+=' · '+rebound['rebound_label']
    return result


def attach(snap, klines, quotes, contexts, calendar, history=None, previous=None, persist=False,
           close_history_loader=None):
    p=config.TREND_CONSOLIDATION
    day=str(snap.get('quote_capture_at') or snap.get('generated_at') or '')[:10]
    asof=(snap.get('strength_model') or {}).get('asof')
    model=dict(version=VERSION,day=day,baseline_asof=asof,observed_at=snap.get('generated_at'),
               price_basis_version=intraday.PRICE_BASIS_VERSION,parameters=p,
               rows=[],pending_rows=[],withdrawn_rows=[],completed_rows=[],excluded_counts={},
               criterion='首次严格强股整理；MA10失守降级观察MA20；MA20连续两次失守或正式收盘失守退出，收复需两次确认',
               count=0,current_count=0,reference_count=0,pending_count=0,completed_count=0,last_valid_quote_at=None)
    old=(previous or {}).get('trend_consolidation') or {}
    if old.get('version') not in COMPATIBLE_VERSIONS or old.get('day','')>day: old={}
    if old and old.get('version')!=VERSION:
        # 旧版未完成对象的退出列表只存姓名/原因，原资格仍在个股记录中。
        # 只能恢复已有且可重建的历史资格，不能依据旧“退出”字样伪造MA20事件。
        legacy_rows={r['code']:r.get('trend_consolidation') or {} for r in
                     (previous or {}).get('stocks',[])+(previous or {}).get('coverage_catalog',[])}
        old=dict(old)
        for group in GROUPS:
            old[group]=[dict(legacy_rows[r['code']],**r) if not r.get('completion_confirmed') and
                        legacy_rows.get(r['code'],{}).get('eligible') is True else dict(r)
                        for r in old.get(group,[])]
        unqualified=[dict(r,eligible=False,stage='旧记录·初始条件未通过',
                         reason='旧版未通过盘中入榜条件，未构成MA20退出事件；'+r.get('reason',''))
                     for r in old.get('withdrawn_rows',[]) if not r.get('completion_confirmed') and r.get('eligible') is not True]
        old['withdrawn_rows']=[r for r in old.get('withdrawn_rows',[]) if r.get('completion_confirmed') or r.get('eligible') is True]
        old['pending_rows']=old.get('pending_rows',[])+unqualified
    # 收盘/非交易阶段只保留实际发布过的判断，不拿收盘后日线回填上午信号。
    session=snap.get('session')
    normal=session in ('早盘','午盘','尾盘','午间休市')
    if not normal:
        if not old or old.get('version')!=VERSION or not any(old.get(g) for g in GROUPS):
            for saved_day in dict.fromkeys((day,asof)):
                if not saved_day:continue
                try: saved=json.loads((DIRECTORY/(saved_day+'.json')).read_text(encoding='utf-8'))
                except (OSError,ValueError): continue
                if saved.get('version')==VERSION and saved.get('day','')<=day and any(saved.get(g) for g in GROUPS):
                    old=saved;break
        if old.get('version') in COMPATIBLE_VERSIONS and old.get('day','') <= day:
            model.update(old, phase_note=old.get('review_note') or '最后有效整理观察，当前不生成新结论')
            if old.get('day')!=day:
                model.update(day=day,reference_day=old.get('day'),observed_at=snap.get('generated_at'),
                             phase_note='沿用'+str(old.get('day'))+'最后有效整理记录；当前阶段不生成新判断')
            model['version']=VERSION
            model['parameters']=p
            model['criterion']='首次严格入榜；MA10失守降级观察，MA20确认失守退出；接近支撑与确认反弹分开'
            model['rows']=[dict(r,reference_only=True,reference_reason=model['phase_note']) for r in old.get('rows',[])]
            model['completed_rows']=[dict(r,reference_only=True,current_breakout_confirmed=False,reference_reason=model['phase_note'])
                                     for r in old.get('completed_rows',[])]
            model.update(current_count=0,reference_count=len(model['rows']))
            # 收盘事实单列复核，只更新已经确认过的跟踪对象。
            if session=='已收盘' and asof==day:
                trackers=[r for group in GROUPS for r in model[group] if r.get('completion_confirmed') or r.get('eligible') is True]
                for group in GROUPS:
                    model[group]=[r for r in model[group] if not (r.get('completion_confirmed') or r.get('eligible') is True)]
                for item in trackers:
                    # 旧完成记录没存涨幅时，只从相同股票、价格、行情时刻补齐，不能拼接不同轮报价。
                    matching=next((r for r in (snap.get('stocks') or [])+(snap.get('coverage_catalog') or [])
                                   if r['code']==item['code'] and r.get('price')==item.get('price') and
                                   r.get('intraday_quote_at')==item.get('quote_at')),None)
                    if item.get('change_pct') is None and matching and number(matching.get('change_pct')):
                        item=dict(item,change_pct=matching['change_pct'])
                    official=close_history_loader(item['code']) if close_history_loader else klines.get(item['code'],[])
                    checked=close_review(item,official,day,calendar)
                    target='pending_rows' if checked.get('close_review_status')=='收盘MA20待核验' else 'withdrawn_rows' if checked.get('trend_exited') else 'completed_rows' if checked.get('completion_confirmed') else 'rows'
                    model[target].append(checked)
            model.update(count=len(model['rows']),reference_count=len(model['rows']),completed_count=len(model['completed_rows']),pending_count=len(model['pending_rows']))
        retained={r['code']:duration(r,calendar,day) for group in GROUPS for r in model[group]}
        for row in (snap.get('stocks') or [])+(snap.get('coverage_catalog') or []):
            row['trend_consolidation']=dict(retained[row['code']]) if row['code'] in retained else dict(
                eligible=None,stage='当前无有效整理记录',reason='收盘后未新增盘中整理判断')
        snap['trend_consolidation']=model
        if persist and old.get('day')==day:
            DIRECTORY.mkdir(parents=True,exist_ok=True)
            config.atomic_write_text(DIRECTORY/(day+'.json'),json.dumps(model,ensure_ascii=False,separators=(',',':')))
        return model
    if not asof or asof >= day:
        model['reason']='报价日前完成日基准待核验'
        snap['trend_consolidation']=model
        return model
    a_dates=historical_a_dates(asof,calendar)
    if not any(old.get(group) for group in GROUPS):
        # 竞价快照不携带整理榜；从最近完成交易日留档续接历史确认。
        for candidate in (day,asof):
            try: saved=json.loads((DIRECTORY/(candidate+'.json')).read_text(encoding='utf-8'))
            except (OSError,ValueError): continue
            if saved.get('version') in COMPATIBLE_VERSIONS and saved.get('day')<=day:
                old=saved;break
    prior_rows={r['code']:r for group in GROUPS for r in old.get(group,[])
                if r.get('eligible') is True and not r.get('completion_confirmed')}
    prior_completed={r['code']:r for group in GROUPS for r in old.get(group,[])
                     if r.get('completion_confirmed') and r.get('completion_type') in ('平台突破转强','回踩修复转强')
                     and str(r.get('completed_at') or '')[:10]<=asof}
    # 同日盘中确认同样需要延续，不能因为峰值或基准日改变重新进入未启动名单。
    prior_completed.update({r['code']:r for group in GROUPS for r in old.get(group,[])
                     if r.get('completion_confirmed') and r.get('completion_type') in ('平台突破转强','回踩修复转强')
                     and str(r.get('completed_at') or '').startswith(day)})
    points=(history or {}).get('points',{})
    counts=Counter()
    for row in (snap.get('stocks') or [])+(snap.get('coverage_catalog') or []):
        code=str(row['code'])
        setup=daily_setup(klines.get(code,[]),asof,calendar,a_dates.get(code,()))
        prior=prior_completed.get(code)
        new_cycle=(prior and (setup.get('eligible') or setup.get('phase')=='completed') and setup.get('peak_date','')>str(prior['completed_at'])[:10]
                   and setup.get('impulse_end','')>str(prior['completed_at'])[:10]
                   and setup.get('consolidation_start','')>str(prior['completed_at'])[:10])
        if prior and not new_cycle:
            setup=tracking_origin(prior,klines.get(code,[]),asof,calendar)
        elif new_cycle:
            prior=None
        prior_main=prior_rows.get(code)
        if not prior and prior_main and (not setup.get('eligible') or setup.get('consolidation_start')==prior_main.get('consolidation_start')) and setup.get('phase')!='completed':
            current_pending=setup.get('reason') if setup.get('pending') else None
            setup=tracking_origin(prior_main,klines.get(code,[]),asof,calendar)
            if current_pending:setup.update(pending=True,tracking_pending=True,reason='当前完成日窗口待核验：'+current_pending)
            if not setup.get('tracking_pending') and len([d for d in calendar if setup['consolidation_start']<=d<=asof])>p['max_days']:
                counts['原整理观察超过最长窗口']+=1
                row['trend_consolidation']=dict(setup,eligible=False,stage='整理观察到期',reason='超过12个完成交易日，须形成新的合格整理')
                continue
        duration(setup,calendar,day)
        row['trend_consolidation']=dict(setup)
        if not setup['eligible'] and setup.get('phase')!='completed' and not setup.get('completion_confirmed'):
            counts[setup['reason']]+=1
            if setup.get('pending') and code in prior_rows:
                model['pending_rows'].append(dict(code=code,name=row.get('name'),reason=setup['reason']))
                model['rows'].append(dict(prior_rows[code],reference_only=True,reference_reason=setup['reason']))
            continue
        at=row.get('intraday_judgment_at')
        usable=row.get('intraday_observation_available') is True and str(at or '').startswith(day)
        last_at=max((str(pt.get('at') or '') for pt in points.get(code,[]) if pt.get('valid')),default='')
        if prior: last_at=max(last_at,str(prior.get('tracking_at') or prior.get('quote_at') or ''))
        if last_at > str(at or ''): usable=False
        context=contexts.get(code) or {}
        reason=None
        if setup.get('tracking_pending'):
            reason=setup['reason']
        elif row.get('trade_status') in ('no_trade','trade_recovered_wait_daily') or (
                row.get('intraday_trade_restriction') and (setup.get('completion_confirmed') or setup.get('phase')=='completed' or prior_main)):
            reason='成交状态不支持整理判断'
        elif not usable: reason='本轮无有效报价，保留最近有效观察'
        elif context.get('valid') is not True or row.get('intraday_price_basis_comparable') is not True:
            reason=context.get('reason') or '价格口径待核验'
        elif not number(context.get('atr20')) or context['atr20'] <= 0: reason='ATR窗口待核验'
        elif not number(context.get('thresholds',{}).get(20)) or context['thresholds'][20]<=0: reason='MA20边界待核验'
        if reason:
            row['trend_consolidation'].update(stage='待核验',reason=reason)
            if setup.get('completion_confirmed'):
                item=dict(setup,code=code,name=row.get('name'),stage='已转强·待核验',reason=reason,
                          reference_only=True,reference_reason=reason,current_breakout_confirmed=False)
                model['pending_rows'].append(item);row['trend_consolidation']=dict(item)
            else:
                model['pending_rows'].append(dict(code=code,name=row.get('name'),reason=reason,quote_at=at))
                prior_main=prior_rows.get(code)
                if prior_main and prior_main.get('setup_id')==setup['setup_id']:
                    model['rows'].append(dict(prior_main,reference_only=True,reference_reason=reason))
            continue
        flags=row.get('intraday_risk_flags') or []
        ma10=context['thresholds'][10]
        earlier=[pt for pt in points.get(code,[]) if str(pt.get('at') or '').startswith(day) and str(pt['at'])<=str(at)]
        # 完成事件在严格首次入口中确认；随后复核无需再次通过MA5入口。
        if setup.get('phase')!='completed' and not setup.get('completion_confirmed'):
            now=dict(at=at,valid=not bool(row.get('intraday_trade_restriction')),
                     trend_ok=intraday.provisional_trend(context['aligned_bars'],row['price'])['intraday_trend_ok'],
                     flags=flags,price=row['price'],ma5=context['provisional_ma'][5],ma10=ma10,change=row.get('change_pct'))
            completed=sampled_completion(setup,context,earlier+[now])
            if completed:
                setup=dict(setup,eligible=False,phase='completed',completion_confirmed=True,
                           completion_type=completed['kind'],completion_level=completed['level']/context['scale_factor'],
                           completed_at=completed['at'],completion_samples=completed['samples'],
                           completion_evidence='合格整理后的连续有效采样确认')
        if setup.get('phase')=='completed' or setup.get('completion_confirmed'):
            if row.get('intraday_trade_restriction'):
                item=dict(setup,code=code,name=row.get('name'),stage='已转强·待核验',reason='当前成交受限，保留历史转强证据',
                          reference_only=True,current_breakout_confirmed=False)
                duration(item,calendar,day)
                model['pending_rows'].append(item);row['trend_consolidation']=dict(item)
                continue
            item=confirmed_item(row,setup,context,earlier,prior or prior_main,bars=klines.get(code,[]))
            duration(item,calendar,day)
            row['trend_consolidation']=dict(item)
            model['withdrawn_rows' if item['trend_exited'] else 'completed_rows'].append(item)
            continue
        current=intraday.provisional_trend(context['aligned_bars'],row['price'])
        if prior_main and not row.get('intraday_trade_restriction'):
            point=dict(at=at,valid=True,price=row['price'],ma5=context['provisional_ma'][5],
                       ma10=ma10,ma20=context['thresholds'][20],flags=flags)
            status=consolidation_tracking.review(setup,earlier,point,setup['platform_high']*context['scale_factor'],current['intraday_trend_ok'],prior_main)
            cooling=(row['price']<ma10 or status['trend_exited'] or status['ma10_downgraded'] or current['intraday_trend_ok'] is not True or SEVERE.intersection(flags))
            if cooling:
                item=dict(setup,**status)
                item.update(code=code,name=row.get('name'),price=row['price'],change_pct=row.get('change_pct'),quote_at=at,
                          phase='withdrawn' if status['trend_exited'] else 'consolidating',
                          eligible=True,observation_history_qualified=True,downgraded_observation=True,
                          reference_only=False,confirmed=False,confirmation_samples=0,breakout_samples=0,turn_samples=0,
                          current_breakout_confirmed=False,location='MA20承接观察',trend_label='原强股资格保留 · 当前降级',
                          daily_tier=row.get('daily_attack_tier'))
                item.update(consolidation_proximity.observe(setup,context,row['price'],at,status['trend_exited']))
                if not status['trend_exited']:
                    item.update(consolidation_rebound.observe(setup,klines.get(code,[]),context,row,earlier))
                    if item.get('rebound_active'):item['stage']+=' · '+item['rebound_label']
                duration(item,calendar,day)
                row['trend_consolidation']=dict(item)
                model['withdrawn_rows' if status['trend_exited'] else 'rows'].append(item)
                continue
        if row['price'] < ma10 or SEVERE.intersection(flags) or row.get('intraday_trade_restriction'):
            why='现价失守MA10' if row['price'] < ma10 else '本轮转弱或成交受限'
            row['trend_consolidation'].update(eligible=False,phase='pending',stage='首次入榜条件未通过',reason=why)
            model['pending_rows'].append(dict(code=code,name=row.get('name'),stage='首次入榜条件未通过',reason=why,quote_at=at))
            continue
        if current['intraday_trend_ok'] is not True:
            why=current.get('intraday_trend_failure') or '盘中多头排列待核验'
            row['trend_consolidation'].update(eligible=False,phase='pending',stage='首次入榜多头条件未通过',reason=why)
            model['pending_rows'].append(dict(code=code,name=row.get('name'),stage='首次入榜多头条件未通过',reason=why,quote_at=at))
            continue
        sampling=sampling_confirmation(row,setup,context,points.get(code,[]))
        departed=departure_reason(setup,row['price'],context['provisional_ma'][5],context['atr20'],row.get('change_pct'),
                                  factor=context['scale_factor'])
        if departed:
            signal=completion_signal(setup,row['price'],context['provisional_ma'][5],context['atr20'],row.get('change_pct'),
                                     factor=context['scale_factor'])
            stage='整理转强待确认' if signal else '反弹已走远，整理转强未确认'
            why=stage+'；涨幅或距离超出初启动，不能据此认定整理完成'
            row['trend_consolidation'].update(eligible=False,phase='pending',stage=stage,reason=why)
            model['pending_rows'].append(dict(code=code,name=row.get('name'),stage=stage,reason=why,quote_at=at))
            continue
        distances={str(n):round((row['price']-context['provisional_ma'][n])/context['atr20'],3) for n in (5,10)}
        near=[n for n in (5,10) if row['price']>=context['thresholds'][n] and 0<=distances[str(n)]<=p['near_line_atr']]
        location=setup['shape'] if setup['shape']!='回踩整理' else '回踩MA'+str(min(near,key=lambda n:abs(distances[str(n)]))) if near else '回踩整理，等待靠线'
        item=dict(setup,**sampling,code=code,name=row.get('name'),price=row['price'],change_pct=row.get('change_pct'),
                  quote_at=at,location=location,distance_ma_atr=distances,
                  risk_flags=flags,fund=row.get('live_attack_fund'),daily_tier=row.get('daily_attack_tier'),
                  reference_only=False,live_pullback_atr=round((setup['peak_close']*context['scale_factor']-row['price'])/context['atr20'],3))
        if prior_main:
            item.update({k:v for k,v in status.items() if k not in ('stage','reason','current_breakout_confirmed')})
        item['current_breakout_confirmed']=False  # 整理/初启动不冒充历史完成转强
        item['structure_note']=('放量分歧后修复：已连续两次收复修复价' if setup['expanded_down_dates'] else
                                'MA10失守后修复：已连续两次收复修复价') if setup['needs_repair_confirmation'] else '整理结构保持'
        item['live_trend_online']=True
        item['phase']='initial' if sampling['stage'] in ('初步突破','初步转强','平台突破待确认') else 'consolidating'
        if row['change_pct']>p['initial_max_gain_pct'] and row['price']<=sampling['platform_high']:
            item.update(stage='整理中 · 平台内反弹',phase='consolidating',confirmed=False)
        if setup['needs_repair_confirmation'] and sampling['repair_samples'] < p['confirmation_samples']:
            item.update(stage='整理中 · 分歧待修复',phase='consolidating',confirmed=False,
                        structure_note='此前存在分歧，仍在整理中；尚未两次收复修复价')
        rebound=consolidation_rebound.observe(setup,klines.get(code,[]),context,row,earlier)
        item.update(rebound)
        item.update(consolidation_proximity.observe(setup,context,row['price'],at))
        # 升级留档中的降级状态不可在普通采样路径中残留。
        item.update(downgraded_observation=False,observation_history_qualified=bool(prior_main))
        if rebound.get('rebound_active') and item['phase']=='consolidating':
            item['stage']=rebound['rebound_label']+(' · 分歧待修复' if setup['needs_repair_confirmation'] and
                                                  sampling['repair_samples']<p['confirmation_samples'] else '')
        row['trend_consolidation']=dict(item)
        model['rows'].append(item)
    model['rows'].sort(key=order)
    model.update(excluded_counts=dict(counts),count=len(model['rows']),pending_count=len(model['pending_rows']),
                 completed_count=len(model['completed_rows']),
                 current_count=sum(not r.get('reference_only') for r in model['rows']),
                 reference_count=sum(bool(r.get('reference_only')) for r in model['rows']),
                 last_valid_quote_at=max((r['quote_at'] for r in model['rows']),default=None))
    snap['trend_consolidation']=model
    if persist:
        DIRECTORY.mkdir(parents=True,exist_ok=True)
        config.atomic_write_text(DIRECTORY/(day+'.json'),json.dumps(model,ensure_ascii=False,separators=(',',':')))
    return model
