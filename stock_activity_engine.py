"""V2.1 事件及身份纯投影；网络、共享评分与页面筛选不参与判定。"""
import copy
import hashlib
import math
from statistics import median

import intraday
import intraday_path
import observed_history
from stock_activity_rules import VERSION, SCORE_VERSION, RULES as R


def clip(x, lo=0., hi=1.):
    return max(lo, min(hi, x))


def elapsed(a, b):
    return intraday_path.gap_seconds(a, b)


def confirmed(e, key):
    return e.get('evidence', {}).get(key, {}).get('status') == 'confirmed'


def role_confirmed(event):
    return ((event.get('role') == '板块先行' and confirmed(event, 'timing'))
            or (event.get('role') == '独立进攻' and confirmed(event, 'independent')))


def source_comparable(a, b):
    import stock_activity as A
    x, y = A.stamp(a), A.stamp(b)
    return bool(x and y and abs((x-y).total_seconds()) <= R['source_skew_max'])


class SourceReference:
    """接收同批行情仍须按目标股票的源时间核验可比覆盖。"""
    def __init__(self, frame, assignments, groups, count):
        import stock_activity as A
        self.frame, self.assignments, self.groups, self.count = frame, assignments, groups, count
        self.times={p['at']:A.stamp(p['at']).timestamp() for p in frame.values()}
        self.ordered=sorted((self.times[p['at']],c,p['change']) for c,p in frame.items())
        self.seconds=[x[0] for x in self.ordered]
        self.cache = {}

    def get(self, code):
        import stock_activity as A
        from bisect import bisect_left, bisect_right
        point = self.frame.get(code)
        if not point:
            return None
        at = self.times[point['at']]
        bounds=(bisect_left(self.seconds,at-R['source_skew_max']),bisect_right(self.seconds,at+R['source_skew_max']))
        if bounds[1]-bounds[0]<self.count*R['coverage_min']:
            return None
        if bounds not in self.cache:
            values = {c:v for _,c,v in self.ordered[bounds[0]:bounds[1]]}
            self.cache[bounds] = A.Reference(values, self.assignments, self.groups, self.count)
        return self.cache[bounds].get(code)


def pause_observation(state):
    """缺失是观察暂停，不是一次价格失败或事件到期。"""
    state.update(points=[], data_gap=True, recovery_required=True)
    state.pop('movement', None)
    identity = state.get('identity', {})
    identity['bad_count'] = 0
    identity.pop('bad_since', None)
    if state.get('events'):
        event = state['events'][-1]
        if event['status'] in ('triggered', 'confirmed'):
            if event.get('observation_status')!='paused':
                change_journal(state,state.get('last_point',{}).get('at'), 'observation',
                               event.get('observation_status','observing'),'paused','有效采样中断，冻结事件与身份',event['id'])
            event.update(observation_status='paused', failure_streak=0, follow_samples=0,
                         continuous_follow_seconds=0, last_continuous_at=None)


def restore_previous(previous):
    """仅兼容已知前版，迁移不删除已确认身份，也不把旧时序混用沿用为新证据。"""
    if (previous.get('version') == '个股主动强度V2.1-20261019.1'
            and previous.get('score_version') == 'LHEQ-R关闭-20261019.1'):
        previous['migrated_from'] = previous['version']
        previous.update(version=VERSION, score_version=SCORE_VERSION)
        for state in previous.get('items', {}).values():
            for event in state.get('events', []):
                if event.get('role') == '独立进攻' and confirmed(event, 'timing'):
                    mark = event['evidence'].pop('timing')
                    mark['migrated_from'] = previous['migrated_from']
                    event['evidence']['independent'] = mark
            pause_observation(state)
    elif (previous.get('version') in ('个股主动强度V2.1-20261019.2',
                                       '个股主动强度V2.1-20261019.3')
          and previous.get('score_version')==SCORE_VERSION):
        previous['migrated_from']=previous['version']
        previous['version']=VERSION
        for state in previous.get('items',{}).values():pause_observation(state)
    return previous


def evidence(event, key, at, detail):
    mark = event.setdefault('evidence', {}).setdefault(key, {})
    if mark.get('status') != 'confirmed':
        mark.update(status='confirmed', observed_at=at,
                    confirmed_at=max(event.get('evaluation_at',at),event.get('detected_at',at)),detail=detail)


def daily_inputs(rows, histories, calendar, day, assignments, groups):
    import stock_activity as A
    bars, contexts, values = {}, {}, {}
    positions = {d:i for i,d in enumerate(calendar)}
    for c, row in rows.items():
        source = observed_history.traded_bars([b for b in histories.get(c, []) if b['date'] < day])
        ctx = intraday.align_price_basis(row, source, calendar, observation_day=day, allow_partial=True)
        contexts[c] = ctx
        if not ctx.get('valid'):
            continue
        clean = [dict(b, **{k:b[k]*ctx['scale_factor'] for k in ('open','high','low','close')}) for b in source]
        bars[c] = clean
        for a,b in zip(clean,clean[1:]):
            if positions.get(b['date'], -2)-positions.get(a['date'], -4) != 1:
                continue  # 复牌跨日收益不能冒充单个市场交易日收益。
            values.setdefault(b['date'], {})[c] = 100*math.log(b['close']/a['close'])
    refs = {d:A.Reference(v,assignments,groups,len(rows)) for d,v in values.items()}
    info = {}
    prior_days = [d for d in calendar if d < day][-20:]
    amounts = {}
    for c, bs in bars.items():
        amounts[c] = {b['date']:(b['amount'] if A.number(b.get('amount')) and b['amount'] > 0
                               else b['volume']*b['close']) for b in bs[-25:] if A.number(b.get('volume')) and b['volume']>0}
    for c,row in rows.items():
        bs = bars.get(c, [])
        atr = contexts[c].get('atr20')
        item = dict(valid=False, reason=contexts[c].get('reason'), atr=atr, bars=bs,
                    historical_excess=None, reference=False, attention_base=None, attention_stability=None,
                    event_days=set(prior_days[-(R['history_events_days']-1):]+[day]))
        info[c] = item
        if len(bs)<R['min_history'] or not A.number(atr) or atr<=0:
            item['reason'] = item['reason'] or '有效日线或ATR历史不足'
            continue
        money = [amounts[c].get(b['date']) for b in bs[-20:]]
        if len(money)!=20 or any(v is None for v in money) or median(money)<R['min_median_amount_yuan']:
            item['reason'] = '完成日成交额中位数未达到2000万元或成交量缺失'
            continue
        expected = prior_days[-10:]
        excess = {}
        for d in prior_days:
            bm = refs.get(d).get(c) if d in refs else None
            if bm and c in values.get(d, {}):
                excess[d] = values[d][c]-max(bm['market'],bm['industry'])
        if not expected or any(d not in excess for d in expected):
            item['reason'] = '近十个市场交易日同行或个股收益不可比'
            continue
        hist = sum(excess[d]*2**(-i/R['history_half_life']) for i,d in enumerate(reversed(prior_days)) if d in excess)
        peers = [p for p in groups.get(assignments.get(c), []) if p != c]
        shares = []
        for d in prior_days:
            available = [amounts.get(p,{}).get(d) for p in peers]
            valid = [v for v in available if v is not None]
            own = amounts.get(c,{}).get(d)
            if own and len(valid)>=R['min_peers'] and len(valid)>=len(peers)*R['coverage_min']:
                shares.append((d,own/(own+sum(valid))))
        base = median(v for _,v in shares) if len(shares)>=10 else None
        stability = sum(v>=base for _,v in shares[-5:])/5 if base and len(shares)>=5 else None
        gains = [max(0.,100*(b['close']/a['close']-1)) for a,b in zip(bs[-6:-1],bs[-5:])]
        effective = sum(gains)**2/sum(v*v for v in gains) if any(gains) else 0.
        gain5 = 100*(bs[-1]['close']/bs[-6]['close']-1)
        reference = (gain5>=R['reference_gain5_pct'] and bs[-1]['close']-bs[-6]['close']>=R['reference_atr_multiple']*atr
                     and effective>=R['effective_pushes_min'] and hist>0)
        item.update(valid=base is not None, reason=None if base else '历史行业成交关注份额不足',
                    historical_excess=hist, daily_excess=excess, reference=reference,
                    gain5=gain5,effective_pushes=effective,attention_base=base,attention_stability=stability,
                    estimated_amount=any(not b.get('amount') for b in bs[-20:]))
    return info


def noise(start, end, atr, seconds):
    return max(R['min_push_pct'],100*R['tick_size']*R['tick_multiple']/start,
               100*atr/start*R['noise_atr_multiple']*math.sqrt(max(seconds,0)/R['session_seconds']))


def window(points, atr):
    from datetime import timedelta
    import stock_activity as A
    if len(points)<R['min_samples']:
        return None
    end = points[-1]
    options = [(abs(seconds-R['window_seconds']),i,seconds) for i,p in enumerate(points[:-1])
               if (seconds:=elapsed(p['at'],end['at'])) is not None
               and abs(seconds-R['window_seconds'])<=R['window_tolerance']]
    if not options:
        return None
    _,i,seconds = min(options)
    part = points[i:]
    if len(part)<R['min_samples']:
        return None
    start = part[0]
    gain = 100*(end['price']/start['price']-1)
    threshold = noise(start['price'],end['price'],atr,seconds)
    uncertainty=max(p.get('clock_uncertainty_seconds',0) for p in part)
    interval=[str(A.stamp(start['at'])-timedelta(seconds=uncertainty)),
              str(A.stamp(end['at'])+timedelta(seconds=uncertainty))]
    return dict(gain=gain,threshold=threshold,start=start,end=end,seconds=seconds,
                trigger_interval=interval,source_interval=[start['at'],end['at']],clock_uncertainty_seconds=uncertainty,part=part)


def change_journal(state, at, kind, old, new, reason, event_id=None):
    if old == new:
        return
    state.setdefault('journal', []).append(dict(at=at,decided_at=state.get('evaluated_at',at),kind=kind,old=old,new=new,reason=reason,event_id=event_id))
    state['journal'] = state['journal'][-60:]


def rescale(state, info):
    """用同一历史日期的已核验价格换算锚点，不用每日涨跌移动结构下限。"""
    ref = state.get('basis_reference')
    bs = info['bars']
    if ref:
        bar = next((b for b in bs if b['date']==ref['date']),None)
        if bar is None:
            return False
        factor = bar['close']/ref['close']
        if abs(factor-1)>1e-8:
            for event in state.get('events', []):
                for k in ('base','peak','atr'):
                    event[k] *= factor
            identity = state.get('identity') or {}
            if identity.get('support_price') is not None:
                identity['support_price'] *= factor
            state.setdefault('basis_changes', []).append(dict(date=bar['date'],factor=factor))
            state['points'] = []
    if bs:
        state['basis_reference'] = dict(date=bs[-1]['date'],close=bs[-1]['close'])
    return True


def event_progress(state, p, fresh, atr):
    event = state.get('events', [])[-1] if state.get('events') else None
    if not event:
        return
    age = elapsed(event['observed_at'],p['at'])
    if age is None:
        if event['status'] in ('triggered','confirmed'):
            event['status'] = 'completed' if confirmed(event,'holding') else 'expired'
        return
    if p['price']>event['peak']:
        event.update(peak=p['price'],peak_at=p['at'])
    quiet=elapsed(event.get('peak_at',event['observed_at']),p['at']) or 0
    if not event.get('rearm_at') and (quiet>=R['rearm_seconds'] or event['peak']-p['price']>=R['rearm_atr']*event['atr']):
        event['rearm_at']=p['at']
    if event['status'] not in ('triggered','confirmed'):
        return
    step = elapsed(event.get('last_continuous_at') or event['observed_at'], p['at'])
    if step is not None and 0 < step <= R['gap_max']:
        event['observed_seconds'] = event.get('observed_seconds', 0) + step
        event['continuous_follow_seconds'] = event.get('continuous_follow_seconds', 0) + step
    event['last_continuous_at'] = p['at']
    observation_status = 'recovering' if state.get('recovery_required') else 'observing'
    change_journal(state,p['at'],'observation',event.get('observation_status','observing'),observation_status,
                   '重建连续观察窗口' if observation_status=='recovering' else '连续观察已恢复',event['id'])
    event['observation_status'] = observation_status
    held = clip((p['price']-event['base'])/(event['peak']-event['base'])) if event['peak']>event['base'] else 0.
    event.update(hold=held,last_sample_at=p['at'])
    if fresh:
        event['follow_samples'] = event.get('follow_samples',0)+1
    if fresh and not state.get('recovery_required'):
        failed = held<R['fail_hold'] or p['price']<event['base']-R['identity_break_atr']*event['atr']
        event['failure_streak'] = event.get('failure_streak',0)+1 if failed else 0
        if event['failure_streak']>=R['fail_samples']:
            event['status']='failed'
            change_journal(state,p['at'],'event','active','failed','连续有效采样确认本次进攻成果丧失',event['id'])
            return
        observed_lower=event.get('continuous_follow_seconds',0)-2*max(event.get('clock_uncertainty_seconds',0),p.get('clock_uncertainty_seconds',0))
        if observed_lower>=R['confirm_seconds'] and event['follow_samples']>=R['confirm_samples'] and held>=R['hold_min'] and p['price']>event['base']:
            evidence(event,'holding',p['at'],dict(hold=held,samples=event['follow_samples'],seconds=event['continuous_follow_seconds']))
            event['status']='confirmed'
    if not state.get('recovery_required') and event.get('observed_seconds',0)>=R['event_seconds']:
        event['status']='completed' if confirmed(event,'holding') else 'expired'
        change_journal(state,p['at'],'event','active',event['status'],'事件到期，核心身份单独检查',event['id'])


def role_update(c, state, states, peers, at):
    from datetime import timedelta
    import stock_activity as A
    event = state.get('events', [])[-1] if state.get('events') else None
    if not event or event['status'] in ('failed','expired') or state.get('recovery_required') or elapsed(event['observed_at'],at) is None:
        return
    # 同行必须有覆盖启动前窗口的连续路径，不能把漏采造成的晚发现当成跟随。
    covered=[]; movements=[];movement_errors=[]
    for peer in peers:
        other=states[peer]
        points=other.get('points',[])
        if (not other.get('data_gap') and points and points[0]['at']<=event.get('source_interval',event['trigger_interval'])[0]
                and source_comparable(points[-1]['at'],at)):
            covered.append(peer)
            move=other.get('movement')
            if move and elapsed(move[1],at) is not None and 0<=elapsed(move[1],at)<=R['role_horizon_seconds']:
                movements.append(move)
                movement_errors.append(other.get('movement_uncertainty',0))
    coverage=len(covered)/max(len(peers),1)
    event['peer_coverage']=coverage
    if len(covered)<R['min_peers'] or coverage<R['coverage_min']:
        return
    major=max(R['peer_start_min'],math.ceil(len(peers)*R['peer_start_fraction']))
    role=event.get('role','时序不明')
    if len(movements)>=major:
        # 中间一对界定同行主要启动区间；不采用对某只股票最有利的极端成员。
        starts=sorted(v[0] for v in movements);ends=sorted(v[1] for v in movements)
        error=max(movement_errors or [0])
        sector=[str(A.stamp(starts[len(starts)//2])-timedelta(seconds=error)),
                str(A.stamp(ends[len(ends)//2])+timedelta(seconds=error))]
        event['peer_trigger_interval']=sector
        if event['trigger_interval'][1]<sector[0]:
            role='板块先行';evidence(event,'timing',at,dict(stock=event['trigger_interval'],peers=sector))
        elif sector[1]<event['trigger_interval'][0]:
            role='跟随进攻'
        else:
            role='时序不明'
        if role=='板块先行' and len(movements)>=math.ceil(len(peers)*R['diffusion_fraction']):
            evidence(event,'diffusion',at,dict(fraction=len(movements)/len(peers),causality=False))
    elif (elapsed(event['observed_at'],at) or 0)-2*max(event.get('clock_uncertainty_seconds',0),state.get('last_point',{}).get('clock_uncertainty_seconds',0))>=R['role_wait_seconds']:
        role='独立进攻'
        evidence(event,'independent',at,dict(peer_coverage=coverage,meaning='完整可比窗口内未观察到同行集体先行，不代表时序领先或因果结论'))
    if event.get('role')=='板块先行' and confirmed(event,'timing') and role=='时序不明':
        role='板块先行'  # 后续成员增加不能抹掉已成立的先发证据。
    change_journal(state,at,'role',event.get('role','时序不明'),role,'可比源时间区间与同行覆盖判定',event['id'])
    event['role']=role
    state['role']=role


def identity_update(state, p, info, lead, attention, fresh):
    identity=state.setdefault('identity',dict(status='none'))
    events=state.get('events',[])
    last=events[-1] if events else None
    good=[e for e in events if e['observed_at'][:10] in info['event_days'] and confirmed(e,'holding') and role_confirmed(e) and e['status'] not in ('failed','expired')]
    independent=[e for e in good if e.get('role')=='独立进攻']
    multiple=(len(independent)>=R['independent_events'] and
              (independent[0]['observed_at'][:10]<independent[-1]['observed_at'][:10]
               or (elapsed(independent[0]['observed_at'],independent[-1]['observed_at']) or 0)>=R['independent_span_seconds']))
    board=bool(last and last.get('role')=='板块先行' and confirmed(last,'holding') and confirmed(last,'diffusion') and last['status']!='failed')
    multiple = bool(multiple and last and last in independent)
    if multiple:
        evidence(last,'repeat',p['at'],dict(events=[e['id'] for e in independent]))
    new_identity_evidence=bool(last and last['id'] not in identity.get('event_ids',[]))
    current_support=bool(last and p['price']>last['base'] and last.get('hold',0)>=R['hold_min'])
    if identity['status'] in ('none','invalid') and new_identity_evidence and (board or multiple) and current_support and attention is not None and attention>=R['core_attention_ratio_min']:
        anchor=last if board else independent[0]
        new=dict(status='active',kind='板块先行核心' if board else '独立型核心',created_at=state.get('evaluated_at',p['at']),first_observed_at=p['at'],
                 support_price=anchor['base']-R['identity_break_atr']*anchor['atr'],
                 event_ids=[e['id'] for e in good],last_supported_at=p['at'],bad_count=0)
        change_journal(state,p['at'],'identity',identity['status'],'active','领先、承接及核心关注度证据成立',anchor['id'])
        state['identity']=identity=new
    if identity['status'] not in ('active','weak'):
        return
    broken=p['price']<identity['support_price']
    # Large, persistent giveback of an established impulse can invalidate
    # leadership even when heavy selling leaves turnover/attention elevated.
    confirmed_peaks=[e.get('peak',0.) for e in events
                     if e['id'] in identity.get('event_ids',[])
                     and confirmed(e,'holding')]
    peak=max(confirmed_peaks+[identity.get('peak_price',0.),p['price']])
    identity['peak_price']=peak
    atr=next((e.get('atr') for e in reversed(events)
              if e['id'] in identity.get('event_ids',[]) and e.get('atr',0)>0),None)
    strong_giveback=bool(atr and peak-p['price']>=max(2.*atr,.08*peak)
                         and lead<0 and p['price']<peak-.5*atr)
    loss=lead<R['identity_lead_floor_pp'] and attention is not None and attention<R['identity_attention_min']
    no_support=(info['historical_excess']<=0 and lead<=0 and
                not (last and last['status'] in ('triggered','confirmed') and confirmed(last,'holding')))
    if fresh and (broken or loss or no_support or strong_giveback):
        if not identity.get('bad_count'):
            identity['bad_since']=p['at']
        identity['bad_count']=identity.get('bad_count',0)+1
        seconds=elapsed(identity['bad_since'],p['at']) or 0
        status='invalid' if identity['bad_count']>=R['identity_loss_samples'] and seconds>=R['identity_loss_seconds'] else 'weak'
        reason=('锁定结构失守' if broken else '已确认进攻成果持续大幅回吐' if strong_giveback
                else '领先优势与关注度同时丧失' if loss else '当前及历史超额均不再支持既有核心身份')
        change_journal(state,p['at'],'identity',identity['status'],status,reason)
        identity['status']=status
    elif fresh:
        identity.update(bad_count=0,last_supported_at=p['at'])
        if identity['status']=='weak':
            change_journal(state,p['at'],'identity','weak','active','结构与优势恢复')
        identity['status']='active'


def build(snap, histories, calendar, frames=None, previous=None, detected_at=None):
    import stock_activity as A
    now=A.stamp(snap.get('quote_capture_at'))
    if not now:
        raise ValueError('个股强度缺少采集时点')
    day=str(now.date())
    previous=restore_previous(copy.deepcopy(previous or {}))
    knowledge_at=A.stamp(detected_at) or now
    if (previous.get('version')!=VERSION or previous.get('score_version')!=SCORE_VERSION
            or (A.stamp(previous.get('processed_at')) and A.stamp(previous['processed_at'])>now)
            or (A.stamp(previous.get('knowledge_at')) and A.stamp(previous['knowledge_at'])>knowledge_at)):
        previous={}
    all_rows={r['code']:r for r in snap.get('stocks',[])+snap.get('coverage_catalog',[])}
    rows={};excluded={}
    for c,row in all_rows.items():
        board=row.get('board_type') or ('sh_main' if c.startswith('60') else 'sz_main' if c.startswith(('000','001','002','003')) else None)
        if board not in R['candidate_boards'] or any(s in str(row.get('name','')).upper() for s in ('ST','退','PT')):
            excluded[c]='不属于本页主板候选范围或属于异常名称样本'
        else:rows[c]=row
    assignments,groups,names=A.industry_groups(snap,rows,previous)
    info=daily_inputs(rows,histories,calendar,day,assignments,groups)
    formal=bool(snap.get('session')=='已收盘' and snap.get('close_daily_verified_at'))
    current=A.valid_frame(rows,now,snap.get('session',''),formal)
    if frames is None:
        frames=A.archive_frames(now,set(rows),formal=formal)
    timeline=[(t,f) for t,f in frames if A.stamp(t) and A.stamp(t)<=now and str(t)[:10]==day]
    timeline.append((str(now),current));timeline.sort(key=lambda f:f[0])
    states=previous.get('items',{})
    for c in rows:
        state=states.setdefault(c,dict(events=[],points=[],identity=dict(status='none'),role='时序不明'))
        if info[c]['valid'] and not rescale(state,info[c]):
            info[c].update(valid=False,reason='核心锚点历史尺度无法恢复，保留身份待核验')
    processed=previous.get('processed_at')
    for received,frame in timeline:
        if processed and received<=processed:
            continue
        ref=SourceReference({c:p for c,p in frame.items() if c in rows},assignments,groups,len(rows))
        windows={};fresh_codes=set()
        for c,row in rows.items():
            state=states[c];p=frame.get(c);detail=info[c]
            state['evaluated_at']=detected_at or received
            if not detail['valid'] or p is None or ref.get(c) is None:
                pause_observation(state)
                continue
            p=copy.deepcopy(p);p['received_at']=p.get('received_at') or received
            if ((A.stamp(p['at'])-A.stamp(received)).total_seconds()>p.get('clock_uncertainty_seconds',0) or p['at'][:10]!=day):
                continue
            old=state.get('last_point')
            if old and p['at']<=old['at']:
                stale_seconds=elapsed(old['at'],received)
                if (not formal and snap.get('stock_activity_quote_mode')!='收盘采样参考'
                        and stale_seconds is not None and stale_seconds>R['gap_max']):
                    pause_observation(state)
                continue
            gap=elapsed(old['at'],p['at']) if old else None
            if old and (gap is None or gap>R['gap_max'] or state.get('data_gap')):
                pause_observation(state)
            state['data_gap']=False
            state['evaluated_at']=detected_at or received
            if state.get('events'):state['events'][-1]['evaluation_at']=state['evaluated_at']
            state['last_point']=p
            state.setdefault('points',[]).append(p)
            # 30分钟覆盖角色确认；缺口处已清空，不靠删点填补路径。
            state['points']=[v for v in state['points'] if elapsed(v['at'],p['at']) is not None and elapsed(v['at'],p['at'])<=R['role_horizon_seconds']+R['window_seconds']]
            fresh_codes.add(c)
            w=window(state['points'],detail['atr'])
            if w:
                state['recovery_required']=False
            event_progress(state,p,True,detail['atr'])
            if w:
                windows[c]=w
                if w['gain']>w['threshold'] and not state.get('movement'):
                    state['movement']=w['source_interval']
                    state['movement_uncertainty']=w['clock_uncertainty_seconds']
                elif w['gain']>w['threshold'] and (elapsed(state['movement'][1],p['at']) or 0)>R['role_horizon_seconds']:
                    state['movement']=w['source_interval']
                    state['movement_uncertainty']=w['clock_uncertainty_seconds']
        # 同一帧全部股票先形成实际推进观察，再比较角色，避免遍历顺序制造先后。
        interval_cache={}
        for c,w in windows.items():
            state=states[c];peers=[p for p in groups.get(assignments.get(c),[]) if p!=c]
            start,end=w['start'],w['end']
            if w['gain']<=w['threshold']:
                state['last_window']=dict(gain=w['gain'],threshold=w['threshold'],excess=None,start=start['at'],end=end['at'],reason='实际推进未超过噪声门槛')
                continue
            key=(start['received_at'],end['received_at'],start['at'],end['at'])
            if key not in interval_cache:
                returns={}
                for peer,other in states.items():
                    pts=other.get('points',[])
                    a=next((v for v in pts if v['received_at']==start['received_at']),None)
                    b=pts[-1] if pts else None
                    if (a and b and b['received_at']==end['received_at'] and a['last_close']==b['last_close']
                            and source_comparable(a['at'],start['at']) and source_comparable(b['at'],end['at'])):
                        returns[peer]=100*(b['price']/a['price']-1)
                interval_cache[key]=A.Reference(returns,assignments,groups,len(rows))
            bm=interval_cache[key].get(c)
            if not bm:
                continue
            er=w['gain']-max(bm['market'],bm['industry'])
            state['last_window']=dict(gain=w['gain'],threshold=w['threshold'],excess=er,start=start['at'],end=end['at'])
            events=state.get('events',[]);last=events[-1] if events else None
            rearmed=not last
            if last:
                overnight=elapsed(last['observed_at'],end['at']) is None
                rearmed=overnight or bool(last.get('rearm_at') and start['at']>=last['rearm_at'])
                if last['status'] in ('triggered','confirmed'):
                    rearmed=False
            if w['gain']>w['threshold'] and er>R['excess_min_pp'] and rearmed:
                eid=hashlib.sha256((VERSION+c+start['at']+end['at']).encode()).hexdigest()[:20]
                event=dict(id=eid,status='triggered',role='时序不明',trigger_interval=w['trigger_interval'],
                    source_interval=w['source_interval'],clock_uncertainty_seconds=w['clock_uncertainty_seconds'],
                    observed_at=end['at'],detected_at=detected_at or received,received_at=end.get('received_at',received),
                    source_timestamp=end['at'],reconstructed=bool(detected_at and (A.stamp(detected_at)-A.stamp(received)).total_seconds()>R['gap_max']),
                    evaluation_at=detected_at or received,
                    base=start['price'],peak=end['price'],peak_at=end['at'],atr=info[c]['atr'],hold=1.,
                    threshold=w['threshold'],push_pct=w['gain'],excess_pp=er,follow_samples=0,evidence={})
                evidence(event,'attack',end['at'],dict(push_pct=w['gain'],noise_threshold=w['threshold'],excess_pp=er))
                state.setdefault('events',[]).append(event);state['events']=state['events'][-R['stored_events']:]
                change_journal(state,end['at'],'event',None,'triggered','实际推进、噪声门槛及双基准超额通过',eid)
        amounts={c:p.get('amount_wan') for c,p in frame.items() if c in rows and A.number(p.get('amount_wan')) and p['amount_wan']>0}
        for c in fresh_codes:
            state=states[c];p=state['last_point'];peers=[x for x in groups.get(assignments.get(c),[]) if x!=c]
            role_update(c,state,states,peers,p['at'])
            covered=[amounts[x] for x in peers if x in amounts and source_comparable(frame[x]['at'],p['at'])]
            attention=(amounts[c]/(amounts[c]+sum(covered))/info[c]['attention_base']
                       if c in amounts and len(covered)>=R['min_peers'] and len(covered)>=len(peers)*R['coverage_min'] else None)
            state['attention_ratio']=attention
            bm=ref.get(c)
            if not state.get('recovery_required'):
                identity_update(state,p,info[c],p['change']-max(bm['market'],bm['industry']),attention,True)
        processed=received
    result={}
    latestref=SourceReference(current,assignments,groups,len(rows))
    for c,row in rows.items():
        state=states[c];detail=info[c];p=current.get(c);identity=state.get('identity',dict(status='none'))
        events=state.get('events',[]);last=events[-1] if events else None
        source=p['at'] if p else state.get('last_point',{}).get('at')
        m=dict(code=c,source_at=source,quote={k:row.get(k) for k in ('price','change_pct','quote_at')},
               role=state.get('role','时序不明'),current_state=state.get('current_state'),confirmation='待确认',
               identity=copy.deepcopy(identity),event=copy.deepcopy(last),events=copy.deepcopy(events),
               journal=copy.deepcopy(state.get('journal',[])),eligible=False,list_name='watch',state='watch',
               score=None,rank=None,factors=dict(L=None,H=None,E=None,Q=None,R=None),confidence=0,
               reasons=[],gates=[],trading_constraints=[],industry=names.get(assignments.get(c)),
               data_quality=dict(available=False,source_timestamp=source,
                                 received_at=p.get('received_at') if p else None,last_valid_sample_at=state.get('last_point',{}).get('at'),
                                 status='recovering' if state.get('recovery_required') and p else 'unavailable'),
               evidence=dict(daily_reference=detail['reference'],gain5=detail.get('gain5'),effective_pushes=detail.get('effective_pushes'),
                             historical_excess=detail.get('historical_excess'),price_basis=detail.get('reason'),
                             attention_ratio=state.get('attention_ratio'),estimated_daily_amount=detail.get('estimated_amount'),
                             recent=state.get('last_window'),R=dict(status='未检验',score_used=False)))
        result[c]=m
        bm=latestref.get(c)
        live_identity=identity['status'] in ('active','weak')
        live_event=bool(last and last['status'] in ('triggered','confirmed'))
        if not p or not detail['valid'] or not bm or (state.get('recovery_required') and (live_identity or live_event)):
            m.update(state='pending',list_name='pending',stage='数据待核验')
            m['reasons']=[detail.get('reason') or ('连续观察窗口重建中；保留事件与最后确认身份' if state.get('recovery_required') and p and bm
                                                else '本次行情或同行基准不可比；保留最后确认身份')]
            if last:
                m['evidence']['confirmations']=copy.deepcopy(last.get('evidence',{}))
            m['confidence_parts']=dict(sampling=0,holding=20*bool(last and confirmed(last,'holding')),
                role=30*bool(last and role_confirmed(last)),repeat=20*bool(last and confirmed(last,'repeat')))
            m['confidence']=sum(m['confidence_parts'].values())
            continue
        m['data_quality'].update(available=True,status='recovering' if state.get('recovery_required') else 'available',
                                 realtime_ready=bool(window(state.get('points',[]),detail['atr'])) and not state.get('recovery_required',False))
        today=p['change']-max(bm['market'],bm['industry'])
        contribution=clip(today*R['intraday_excess_weight'],-R['intraday_excess_cap_pp'],R['intraday_excess_cap_pp'])
        x=max(0.,detail['historical_excess']+contribution)
        m['factors']['E']=100*x/(x+R['excess_scale'])
        attention=state.get('attention_ratio')
        historical_days={e['observed_at'][:10] for e in events if e['observed_at'][:10] in detail['event_days'] and e['observed_at'][:10]<day and role_confirmed(e) and confirmed(e,'holding')}
        if attention is not None and detail['attention_stability'] is not None:
            m['factors']['H']=50*clip(attention/R['attention_ratio_cap'])+30*clip(len(historical_days)/5)+20*detail['attention_stability']
        m['evidence'].update(today_excess=today,today_excess_contribution=contribution,history_event_days=sorted(historical_days))
        vwap_points=[v for v in state.get('points',[]) if v.get('vwap') is not None]
        m['evidence']['VWAP']=dict(value=p.get('vwap'),sample_count=len(vwap_points),
                                  sampled_above_ratio=sum(v['price']>=v['vwap'] for v in vwap_points)/len(vwap_points) if vwap_points else None,
                                  meaning='累计成交额/成交股数经单位及价格区间校验；保持比例仅代表采样路径')
        if last:
            scoring=last
            if identity['status'] in ('active','weak') and not (role_confirmed(last) and confirmed(last,'holding')):
                prior=[e for e in events if role_confirmed(e) and confirmed(e,'holding') and e['status'] not in ('failed','expired')]
                if prior:scoring=prior[-1]
            m['evidence']['scoring_event_id']=scoring['id']
            age=elapsed(scoring['observed_at'],source)
            if role_confirmed(scoring):
                m['factors']['L']=50+30+20*clip((age or 0)/R['role_wait_seconds'])
            elif scoring['role']=='跟随进攻':
                m['factors']['L']=0.
            if confirmed(scoring,'holding'):
                m['factors']['Q']=100*scoring['hold']
            marks=last.get('evidence',{})
            role_label='先行' if last.get('role')=='板块先行' else '独立角色'
            m['confirmation']=(role_label+'与承接已确认' if role_confirmed(last) and confirmed(last,'holding')
                               else role_label+'已确认；承接待确认' if role_confirmed(last)
                               else '承接已确认' if confirmed(last,'holding') else '启动待确认')
            m['confidence_parts']=dict(sampling=30*bool(window(state.get('points',[]),detail['atr'])),
                holding=20*bool(confirmed(last,'holding')),role=30*bool(role_confirmed(last)),repeat=20*bool(confirmed(last,'repeat')))
            m['confidence']=sum(m['confidence_parts'].values())
            m['evidence']['confirmations']=marks
        if identity['status'] in ('active','weak'):
            m.update(list_name='core',eligible=True,state='active')
            if last and not confirmed(last,'holding'):
                m['confirmation']='核心身份保留；本次进攻待确认'
            quiet=elapsed(last.get('peak_at',last['observed_at']),source) if last else None
            m['current_state']=('转弱' if identity['status']=='weak' else '强势整理' if not last or last['status']=='completed' or (quiet or 0)>=R['rearm_seconds']
                                else '领先保持' if (quiet or 0)>=120 else '推进')
        elif last and last['status'] in ('triggered','confirmed') and last.get('role')!='跟随进攻':
            # 旧身份退出不遮蔽后来一次真正的新启动；失效所依据的旧事件不能借此返榜。
            if identity['status']!='invalid' or last['id'] not in identity.get('event_ids',[]):
                m.update(list_name='startup',eligible=True,state='startup',current_state='推进')
            else:
                m.update(state='invalid',list_name='watch',current_state='失效')
        elif identity['status']=='invalid':
            m.update(state='invalid',list_name='watch',current_state='失效')
        elif detail['reference']:
            support=detail['bars'][-1]['low']-R['identity_break_atr']*detail['atr']
            losing=(today<R['identity_lead_floor_pp'] and p['price']<detail['bars'][-1]['close']-R['identity_break_atr']*detail['atr'])
            m['evidence']['reference_support_price']=support
            if p['price']<support or losing:
                m.update(list_name='watch',current_state='转弱')
                m['reasons'].append('历史强势，但当前失守完成日结构或明显丧失相对优势')
            else:
                m.update(list_name='reference')
        if not m['eligible'] and m['list_name']!='reference':
            m['reasons'].append('跟随进攻不确认为发动核心' if last and last.get('role')=='跟随进攻' else '尚无可确认的主动进攻身份')
        weights=R['weights_core'] if m['list_name']=='core' else R['weights_start']
        if m['eligible'] and all(m['factors'][k] is not None for k in R['enabled_factors']):
            m['score']=round(sum(weights[k]*m['factors'][k] for k in weights)/sum(weights.values()),2)
        for k,v in m['factors'].items():
            if v is not None:m['factors'][k]=round(v,2)
        if row.get('limit_up') and row['price']>=row['limit_up']-.005:
            m['trading_constraints'].append('涨停，成交可得性未核验')
        m['trading_risk']=dict(
            drawdown_from_day_high_pct=100*(row['high']-row['price'])/row['high'] if row.get('high') else None,
            distance_to_identity_support_pct=100*(row['price']/identity['support_price']-1) if identity.get('support_price') else None,
            execution_verified=False,score_used=False)
        if last and last['status']=='failed' and m['current_state'] is None:
            m['current_state']='转弱'
        state['current_state']=m['current_state']
        m['stage']=(m['identity'].get('kind') if m['list_name']=='core' else '启动待确认' if m['list_name']=='startup'
                    else '日线强势参考' if m['list_name']=='reference' else m['current_state'] or '观察')
        m['gates']=[dict(name='实际进攻证据',passed=bool(last and confirmed(last,'attack')),actual=last.get('push_pct') if last else None,threshold=last.get('threshold') if last else None),
                    dict(name='市场与行业调整超额',passed=bool(last and last.get('excess_pp',0)>R['excess_min_pp']),actual=last.get('excess_pp') if last else None,threshold=R['excess_min_pp']),
                    dict(name='承接确认',passed=bool(last and confirmed(last,'holding')),actual=bool(last and confirmed(last,'holding')),threshold=True),
                    dict(name='可信进攻角色',passed=bool(last and role_confirmed(last)),actual=m['role'],threshold='板块先行证据或独立观察证据'),
                    dict(name='核心身份有效',passed=identity['status'] in ('active','weak'),actual=identity['status'],threshold='active/weak')]
    priority={'core':0,'startup':1,'reference':2,'watch':3,'pending':4}
    def order_key(c):
        m=result[c]
        secondary=(-A.stamp(m['event']['observed_at']).timestamp() if m['list_name']=='startup' and m['score'] is None
                   else -detail_excess(info[c]))
        return priority[m['list_name']],m['score'] is None,-(m['score'] or 0),secondary,c
    order=sorted(rows,key=order_key)
    for name in ('core','startup'):
        for i,c in enumerate([c for c in order if result[c]['list_name']==name and result[c]['score'] is not None],1):result[c]['rank']=i
    counts={k:sum(m['list_name']==k for m in result.values()) for k in ('core','startup','reference','watch','pending')}
    source_times=sorted(p['at'] for p in current.values())
    output=dict(version=VERSION,score_version=SCORE_VERSION,source_at=source_times[len(source_times)//2] if source_times else str(now),
        captured_at=str(now),day=day,mode=snap.get('stock_activity_quote_mode') or ('正式收盘' if formal else '午休参考' if snap.get('session')=='午间休市' else '盘中采样'),
        items=result,order=order,counts=counts,pool_count=len(rows),excluded=excluded,rules=copy.deepcopy(R),assignments=assignments,
        note='事件与核心身份分别管理；R未启用；证据充分度不是上涨概率。')
    output['data_quality']=dict(realtime_ready=sum(bool(m['data_quality'].get('realtime_ready')) for m in result.values()),
                                recovering=sum(m['data_quality']['status']=='recovering' for m in result.values()),
                                quote_available=sum(m['data_quality']['available'] for m in result.values()))
    output['_state']=dict(version=VERSION,score_version=SCORE_VERSION,day=day,source_at=output['source_at'],processed_at=processed,knowledge_at=str(knowledge_at),
                          assignments=assignments,items=states)
    return output


def detail_excess(info):
    return info.get('historical_excess') or 0.
