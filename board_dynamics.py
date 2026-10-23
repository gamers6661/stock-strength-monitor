"""Board-page-only observations, derived from frozen source quotes and shared scores.

Never changes stock/board strength, membership, rank, or the observation ring.
Thresholds describe observed moves; they are fixed research settings, not forecasts.
"""
import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from statistics import median


def mean(values):
    values = list(values)
    return sum(values) / len(values) if values else 0.0

VERSION = 'board-dynamics-2026-10-22.trading-two'
PARAMETERS = dict(min_members=6, min_coverage_pct=80., strong_min=65.,
    max_quote_skew_seconds=120,max_source_age_seconds=600,
    advance_pp=.30, excess_pp=.10,
    breadth_change_pp=5., breadth_members=2, breadth_up_pct=55.,
    fade_pp=-.30,
    structure_min=.85, health_min=.75, waiting_score_min=45., overlap_min=.70,
    priority_strong_pct=30.,concentration_min_members=10,concentration_top3_pct=70.)


def number(v):
    return isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v)


def stamp(v):
    try:
        return datetime.fromisoformat(str(v))
    except (ValueError, TypeError):
        return None


def session(at):
    if not at:
        return None
    seconds=at.hour*3600+at.minute*60+at.second
    if 34200 <= seconds <= 41400:
        return (at.date().isoformat(), 'morning')
    if 46800 <= seconds <= 54000:
        return (at.date().isoformat(), 'afternoon')
    return None


def membership(codes):
    # The existing ring stores this identity; reuse its exact serialization.
    return hashlib.sha256(json.dumps(sorted(codes),sort_keys=True).encode()).hexdigest()


def eligible(codes, expected):
    return len(codes)>=PARAMETERS['min_members'] and bool(expected) and len(codes)*100/len(expected)>=PARAMETERS['min_coverage_pct']


def samples(snap):
    """Use each member's real timestamp, deduplicating frozen closing reads."""
    version=(snap.get('market_strength') or {}).get('implementation_hash')
    verified=stamp(snap.get('close_daily_verified_at'))
    captured=stamp(snap.get('quote_capture_at') or snap.get('generated_at'))
    result={}
    for raw in snap.get('direction_observations') or []:
        if raw.get('version') != version:
            continue
        record_at=stamp(raw.get('at'))
        if not record_at or (captured and record_at>captured):
            continue
        quotes=raw.get('quote_evidence') or {}
        valid={}
        for code,values in (raw.get('stocks') or {}).items():
            q=quotes.get(code) or {}; at=stamp(q.get('at'))
            closing=bool(at and verified and snap.get('session')=='已收盘' and at.date()==verified.date() and at.hour>=15)
            if (len(values)<3 or not number(values[0]) or not any(number(v) for v in values[1:3]) or not at or not record_at or
                    at>record_at or not (session(at) or closing) or at.date()!=record_at.date()):
                continue
            # Verified post-close reads belong to ONE 15:00 closing observation.
            # Acquisition timestamps must never create extra market observations.
            market_at=at.replace(hour=15,minute=0,second=0,microsecond=0) if closing else at
            valid[code]=(values,market_at)
        source=max((v[1] for v in valid.values()),default=None)
        if not source:
            continue
        valid={c:v for c,v in valid.items() if session(v[1])==session(source)
               and (source-v[1]).total_seconds()<=PARAMETERS['max_quote_skew_seconds']}
        if not valid:
            continue
        actual_source=source
        item=dict(at=source, source_at=actual_source, acquired_at=record_at, stocks=valid, boards=raw.get('boards') or {}, pool_hash=raw.get('pool_hash'))
        # Same source time cannot provide a second confirmation, even if rescored.
        if source not in result or record_at>result[source]['acquired_at']:
            result[source]=item
    return [result[k] for k in sorted(result)]


def baseline(ring, end):
    earlier = [point for point in ring if point['at'] < end['at']]
    return max(earlier, key=lambda point: point['at']) if earlier else None


def strong(values):
    return any(number(v) and v>=PARAMETERS['strong_min'] for v in values[1:3])


def consistent(board, points):
    identity=membership(board.get('member_codes') or [])
    return all((s['boards'].get(board['id']) or {}).get('membership')==identity for s in points)


_FORWARD_CACHE = {}


def _forward_codes(points):
    key=tuple(p['at'] for p in points)
    cached=_FORWARD_CACHE.get(key)
    if cached is None:
        codes=set(points[0]['stocks']) if points else set()
        for point in points[1:]:
            codes.intersection_update(point['stocks'])
        # Every member must have a distinct, forward-moving source at each point.
        cached=frozenset(c for c in codes if all(points[i]['stocks'][c][1]<points[i+1]['stocks'][c][1]
                                                 for i in range(len(points)-1)))
        _FORWARD_CACHE[key]=cached
    return cached


def common_codes(expected, points):
    if not points:
        return []
    return sorted(set(expected) & _forward_codes(points))


def fixed_weights(codes, point):
    ordered=sorted(codes,key=lambda c:(point['stocks'][c][0][0],c))
    cut=max(1,int(len(codes)*.10)) if len(codes)>=6 else 0
    return ordered[cut:len(ordered)-cut] if cut else ordered


def stats(codes, point):
    rows=[point['stocks'][c][0] for c in codes]
    return dict(return_pct=mean(r[0] for r in rows), median_pct=median(r[0] for r in rows),
        up_pct=100*mean(r[0]>0 for r in rows), strong_count=sum(strong(r) for r in rows),
        strong_pct=100*mean(strong(r) for r in rows))


def window(board, ring, end):
    expected=set((board.get('market_strength') or {}).get('expected_codes') or board.get('member_codes') or [])
    start=None; codes=[]
    for candidate in sorted((p for p in ring if p['at']<end['at']),key=lambda p:p['at'],reverse=True):
        comparable=common_codes(expected,[candidate,end])
        if eligible(comparable,expected):
            start=candidate; codes=comparable; break
    if start is None:
        return None
    market=common_codes(set(start['stocks'])&set(end['stocks']),[start,end])
    if not market:
        return None
    weights=fixed_weights(codes,start)
    elapsed=(end['at']-start['at']).total_seconds()/60
    increments={c:end['stocks'][c][0][0]-start['stocks'][c][0][0] for c in codes}
    delta=mean(increments[c] for c in weights)
    market_delta=mean(end['stocks'][c][0][0]-start['stocks'][c][0][0] for c in market)
    before,after=stats(codes,start),stats(codes,end)
    return dict(from_at=str(start['at']),to_at=str(end['at']),minutes=round(elapsed,2),
        delta_pp=round(delta,4),excess_pp=round(delta-market_delta,4),
        market_delta_pp=round(market_delta,4),
        up_delta_pp=round(after['up_pct']-before['up_pct'],2),
        strong_delta=after['strong_count']-before['strong_count'],
        strong_delta_pp=round(after['strong_pct']-before['strong_pct'],2),
        median_delta_pp=round(median(increments.values()),4),
        up_pct=round(after['up_pct'],2),strong_count=after['strong_count'],strong_pct=round(after['strong_pct'],2),
        common_count=len(codes),expected=len(expected),coverage_pct=round(len(codes)*100/len(expected),2),
        common_codes=codes,weighted_codes=weights,
        comparison_basis='当前成员固定回看最近两条有效交易时点；盘后重复收盘数据合并至15:00；跨日时比较各自当日涨幅的变化，不作为区间收益')


def signals(w, board, start, end, prior_strong):
    if not w:
        return dict(attack=False,turning=False,accelerating=False,spreading=False,fading=False,decelerating=False)
    p=PARAMETERS
    old=start['boards'].get(board['id']) or {}; new=end['boards'].get(board['id']) or {}
    entered=old.get('membership')==new.get('membership') and any(
        number(new.get(k)) and new[k]>=p['strong_min'] and number(old.get(k)) and old[k]<p['strong_min']
        for k in ('trend','emotion'))
    advance=(w['delta_pp']>=p['advance_pp'] and w['excess_pp']>=p['excess_pp']
             and w['median_delta_pp']>0 and w['up_pct']>=p['breadth_up_pct'])
    spreading=(w['delta_pp']>0 and w['median_delta_pp']>0 and w['up_delta_pp']>=p['breadth_change_pp']
               and w['strong_delta_pp']>=p['breadth_change_pp'] and w['strong_delta']>=p['breadth_members'])
    fading=(prior_strong and w['delta_pp']<=p['fade_pp'] and w['median_delta_pp']<0
            and (w['strong_delta']<=-p['breadth_members'] or w['up_delta_pp']<=-p['breadth_change_pp']))
    return dict(attack=advance,turning=advance and entered and w['strong_delta']>=0,
                accelerating=False,spreading=spreading,fading=fading,decelerating=False)


def official(board):
    if board.get('catalog_listed') is True:
        return True
    idx=board.get('index_trend') or board.get('index_current') or {}
    code=str(idx.get('code') or '')
    return (board.get('type')=='theme' and idx.get('name')==board.get('name') and len(code)==6
            and code[:3] in ('885','886') and code.isdigit() and str(idx.get('source','')).startswith('同花顺概念指数'))


def evaluate(board, ring, rows, paused, stale=False):
    m=board.get('market_strength') or {}; expected=set(m.get('expected_codes') or board.get('member_codes') or [])
    end=ring[-1] if ring else None
    codes=sorted(expected&set(end['stocks'])) if end else []
    ready=bool(end and eligible(codes,expected))
    daily=any(number(x.get('score')) and x['score']>=PARAMETERS['strong_min'] for x in m.get('history_trend') or [])
    part=(m.get('trend_parts_by_period') or {}).get(str(m.get('dominant_period'))) or {}
    structure=(number(part.get('K')) and part['K']>=PARAMETERS['structure_min']
               and number(part.get('health')) and part['health']>=PARAMETERS['health_min'])
    w=window(board,ring,end) if ready else None
    start=next((s for s in ring if w and str(s['at'])==w['from_at']),None)
    prior_strong=daily or bool(start and any(number(v) and v>=PARAMETERS['strong_min'] for k,v in
        (start['boards'].get(board['id']) or {}).items() if k in ('trend','emotion')))
    sig=signals(w,board,start,end,prior_strong)
    confirmation=None
    confirmed=dict(sig)
    current=stats(codes,end) if ready else {}
    if current:
        weight=fixed_weights(codes,end)
        current['return_pct']=mean(end['stocks'][c][0][0] for c in weight)
        market=mean(v[0][0] for v in end['stocks'].values())
        current.update(excess_pp=current['return_pct']-market,valid=len(codes),expected=len(expected),
                       coverage_pct=len(codes)*100/len(expected))
    tags=[]; reason=[]; lane='ordinary'; status='平稳观察'; priority=8
    trigger='最近两条数据中成员涨幅改善并跑赢可比样本，上涨与强股参与同步改善。'
    invalidate='推进转负且成员参与收缩，或结构受损时下调关注。'
    if not ready or not w or paused:
        status='待开盘' if paused else '比较不足';lane='pending';priority=9
        reason=[('竞价与盘前不沿用连续竞价变化作当前判断。' if paused else
                 '当前报价成员不足6只或覆盖不足80%。' if not ready else
                 '尚未取得两条不同源时点且成员覆盖合格的数据。')]
        trigger='使用最近两条不同源时点的有效数据；相同源时点只保留一条。'
    else:
        if sig['spreading']:tags.append('扩散' if confirmed['spreading'] else '扩散待确认')
        if sig['accelerating']:tags.append('加速' if confirmed['accelerating'] else '加速待确认')
        if sig['decelerating']:tags.append('减速')
        if w['strong_delta']<0 or w['up_delta_pp']<=-PARAMETERS['breadth_change_pp']:tags.append('参与收缩')
        if sig['fading']:
            status='退潮' if confirmed['fading'] else '退潮待确认';lane='cooling';priority=6
            reason=['此前有强势背景；当前推进与成员参与同时回落。']
            trigger='下一条数据的涨幅与参与广度改善后上调关注。'
            invalidate='持续回落或结构受损，退出轮动候选。'
        elif confirmed['attack']:
            new_turn=sig['turning'] or bool(confirmation and confirmation[0]['turning'])
            status='转强' if new_turn else '再启动' if daily and m.get('phase') in ('启动','回踩整理') else '强势推进'
            lane='priority' if (confirmed['spreading'] or confirmed['accelerating'] or
                                current.get('strong_pct',0)>=PARAMETERS['priority_strong_pct'] and w['up_delta_pp']>=0 and w['strong_delta']>=0) else 'watch'
            priority=1 if lane=='priority' and confirmed['spreading'] else 2 if lane=='priority' else 3
            reason=['最近两条数据对比：成员涨幅改善、跑赢可比样本，且多数成员跟随。']
            if confirmed['spreading']:reason.append('上涨比例和强股数量同步增加。')
            if confirmed['accelerating']:reason.append('同一批成员的后段推进速度超过前段。')
            if lane=='watch':reason.append('强股占比尚不足30%或参与有所收缩，继续观察扩散。')
        elif sig['attack'] or sig['spreading']:
            status='转强待确认' if sig['turning'] else '局部转强';lane='watch';priority=4
            reason=['已观察到推进或扩散，尚未形成完整共振。']
        elif (daily and structure and number(m.get('trend_score')) and m['trend_score']>=PARAMETERS['waiting_score_min']
              and not sig['fading'] and w['delta_pp']>PARAMETERS['fade_pp']):
            status='整理等待';lane='waiting';priority=5
            reason=['按当前确认成员回看，近3个完成日曾趋势强势，当前结构保持，眼下缺少已确认进攻。']
            trigger='最近两条数据的成员涨幅改善至少0.30个百分点、相对可比样本改善0.10个百分点，上涨比例≥55%、成员中位数改善。'
            invalidate='结构系数低于0.85、健康度低于0.75，或出现参与持续收缩，退出候选。'
        elif m.get('trend_strong') or m.get('emotion_strong'):
            status='强势保持';lane='watch';priority=4
            reason=['现有强度仍达标，最近两条数据尚未形成进一步扩散。']
        else:
            reason=['本次对比尚未出现符合条件的推进、扩散或历史强势整理候选。']
    if not structure and ready and daily:
        tags.append('结构需修复')
    leaders=[]; new_members=[]; concentration=None
    if w:
        values={c:end['stocks'][c][0][0]-start['stocks'][c][0][0] for c in w['common_codes']}
        positives=sorted((v for v in values.values() if v>0),reverse=True)
        concentration=sum(positives[:3])/sum(positives)*100 if positives else None
        if len(values)>=PARAMETERS['concentration_min_members'] and concentration is not None and concentration>=PARAMETERS['concentration_top3_pct'] and w['median_delta_pp']<=0:
            tags.append('核心独强')
            if lane=='priority':lane='watch';priority=3;reason.append('推进集中于少数成员，先观察扩散。')
        for c in sorted(values,key=lambda c:(-values[c],c))[:5]:
            leaders.append(dict(code=c,name=(rows.get(c) or {}).get('name',c),delta_pp=round(values[c],3),return_pct=end['stocks'][c][0][0]))
        new_members=[dict(code=c,name=(rows.get(c) or {}).get('name',c)) for c in w['common_codes']
                     if strong(end['stocks'][c][0]) and not strong(start['stocks'][c][0])]
    if '指数/主板成员分歧' in (m.get('reasons') or []):tags.append('指数与成员分歧')
    series=[]
    if end:
        points=[start,end] if w else [end]
        fixed=set(expected)
        for s in points:fixed.intersection_update(s['stocks'])
        if eligible(fixed,expected):
            for point in points:
                st=stats(sorted(fixed),point)
                series.append(dict(at=str(point['at']),return_pct=round(st['return_pct'],3),up_pct=round(st['up_pct'],2),strong_pct=round(st['strong_pct'],2)))
    return dict(id=board['id'],name=board['name'],type=board['type'],status=status,lane=lane,priority=priority,
        tags=tags,reasons=reason,trigger=trigger,invalidate=invalidate,current=current,change=w,
        confirmation_at=confirmation[1] if confirmation else None,confirmed=confirmed,
        trend_score=m.get('trend_score'),emotion_score=m.get('emotion_score'),historical_strong=daily,
        structure=dict(coefficient=part.get('K'),health=part.get('health'),holding=bool(structure)),
        source_at=str(end['source_at']) if end else None,leaders=leaders,new_members=new_members,
        top3_advance_share_pct=concentration,series=series,series_count=len(fixed) if end else 0,overlaps=[])


def build(snap):
    _FORWARD_CACHE.clear()
    ring=samples(snap)
    # Comparison uses ordered source records, independent of the gap between them.
    captured=stamp(snap.get('quote_capture_at') or snap.get('generated_at'))
    paused=snap.get('session') in ('盘前','集合竞价','竞价结束')
    if captured: ring=[point for point in ring if point['at']<=captured]
    stale=bool(captured and ring and snap.get('session') not in ('已收盘','午间休市')
        and ((captured-ring[-1]['source_at']).total_seconds()>PARAMETERS['max_source_age_seconds']
             or session(captured)!=session(ring[-1]['at'])))
    rows={r['code']:r for key in ('stocks','coverage_catalog') for r in snap.get(key) or []}
    boards=[b for b in snap.get('board_catalog') or [] if official(b)]
    items=[evaluate(b,ring,rows,paused,stale) for b in boards]
    items.sort(key=lambda r:(r['priority'],-((r['change'] or {}).get('excess_pp') or 0),
        -((r['change'] or {}).get('strong_delta_pp') or 0),-((r['change'] or {}).get('delta_pp') or 0),r['name']))
    members={b['id']:set(b.get('member_codes') or []) for b in boards}
    candidates=[r for r in items if r['lane'] in ('priority','watch','waiting')]
    for i,row in enumerate(candidates):
        a=members[row['id']]
        for other in candidates[:i]:
            b=members[other['id']]; union=a|b
            ratio=len(a&b)/len(union) if union else 0
            if ratio>=PARAMETERS['overlap_min']:
                row['overlaps'].append(dict(id=other['id'],name=other['name'],pct=round(ratio*100,1)))
                break
    return dict(version=VERSION,parameters=dict(PARAMETERS),source_at=str(ring[-1]['source_at']) if ring else None,
        mode='竞价／盘前参考' if paused else '收盘复核' if snap.get('session')=='已收盘' else '午休参考' if snap.get('session')=='午间休市' else '盘中观察',
        counts=dict(Counter(r['lane'] for r in items)),order=[r['id'] for r in items],by_id={r['id']:r for r in items},
        basis='同花顺确认主板成员；按实际源报价比较，固定成员与权重，官方指数单列。',
        thresholds_note='首版固定研究阈值；观察优先级用于复核方向，不表示未来轮动概率。')
