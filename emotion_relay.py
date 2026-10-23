"""Main-board relay facts, cohorts and candidates, independent of MA eligibility."""
import copy,gzip,hashlib,json,math,time
from collections import Counter,defaultdict
from datetime import datetime,timedelta
from pathlib import Path
from statistics import median,mean
import config,intraday,market_strength as M,relay_data as D,relay_history as H,relay_regulation as R,relay_cycles as C,relay_pools as W,closing_price,relay_relations
P=config.EMOTION_RELAY;VERSION=P['version']
IMPLEMENTATION_HASH=hashlib.sha256(Path(__file__).read_bytes()+Path(D.__file__).read_bytes()+Path(H.__file__).read_bytes()+Path(R.__file__).read_bytes()+Path(C.__file__).read_bytes()+Path(W.__file__).read_bytes()+Path(closing_price.__file__).read_bytes()+Path(relay_relations.__file__).read_bytes()+Path(intraday.__file__).read_bytes()+json.dumps(P,sort_keys=True).encode()).hexdigest()

def number(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def pct(n,d):return round(100*n/d,2) if d else None
def med(v):return round(median(v),2) if v else None
def official(b):
    idx=b.get('index_trend') or b.get('index_current') or {}
    return b.get('catalog_listed') is True or b.get('type')=='theme' and idx.get('name')==b.get('name') and str(idx.get('code',''))[:3] in ('885','886') and str(idx.get('source','')).startswith('同花顺概念指数')

def sealed_day(code,day,calendar,native,evidence):
    pool=evidence['pools'].get(day) or {}
    bar=native.get(day)
    if not pool.get('date_verified'):return None,'涨停池请求日/完整性未核验'
    if not bar or not intraday._valid_historical_price_bar(bar) or not number(bar.get('volume')) or bar['volume']<=0:return None,'完成日线或成交记录缺失'
    entry=(pool.get('entries') or {}).get(code)
    if not entry:return False,None
    if str(entry.get('name') or '').upper().startswith(('ST','*ST','N','C')):return None,'历史特殊涨跌幅制度不混比'
    raw={b['date']:b for b in evidence.get('raw',{}).get(code,{}).get('bars',[])}
    i=calendar.index(day)
    if i<1 or day not in raw or calendar[i-1] not in raw:return None,'原价完成日与前收未覆盖'
    b=raw[day];prev=raw[calendar[i-1]]
    if b.get('corporate_action'):return None,'除权日涨停参考价待核验'
    limit=D.limit_price(prev['close'])
    if not (D.tick(b['close'])==D.tick(b['high'])==D.tick(entry['price'])==D.tick(limit)):
        return None,'原价收盘、最高价与按分取整涨停价不一致'
    return True,None

def chain(code,days,calendar,bars,evidence):
    native={b['date']:b for b in bars};height=0;exact=False;path=[]
    for day in days:
        halted=False
        if 'reference' in evidence:sealed,reason,halted=H.classify(code,day,calendar,evidence)
        else:sealed,reason=sealed_day(code,day,calendar,native,evidence)
        if halted:pass
        elif sealed is None:height=0;exact=False
        elif sealed:height+=1
        else:height=0;exact=True
        path.append(dict(date=day,sealed=sealed,height=height if sealed is not None or halted else None,exact=exact,reason=reason,halted=halted))
    return path

def effective_quote(snap,row,quotes):
    q=quotes.get(row['code']) or {};clock=(row.get('market_strength') or {}).get('quote_at')
    if clock and intraday.parse_quote_timestamp(q.get('quote_at') or q.get('ts'))!=intraday.parse_quote_timestamp(clock):
        for key in ('market_strength_close_input','market_strength_morning_input'):
            saved=((snap.get(key) or {}).get('quotes') or {}).get(row['code']) or {}
            if intraday.parse_quote_timestamp(saved.get('quote_at') or saved.get('ts'))==intraday.parse_quote_timestamp(clock):return saved
    return q

def current(code,row,q,path,now,session,center,old,regime_ready=True,daily_proof=None):
    prior=path[-1] if path else {};previous=path[-2] if len(path)>1 else {}
    formal=bool(daily_proof) or (row.get('market_strength') or {}).get('mode')=='正式收盘'
    valid,at,reason=M.quote_valid(q,now,session,center,formal)
    if daily_proof:valid=True;reason=None
    if session not in ('早盘','午盘','尾盘','午间休市','已收盘'):valid=False;reason='竞价/非交易时段不生成正常接力事件'
    out=dict(version=VERSION,code=code,quote_at=str(at) if at else None,valid=valid,reason=reason,
        mode='正式收盘' if formal else '午休参考' if session=='午间休市' else '盘中暂态',
        valid_until=(str(at+timedelta(seconds=config.INTRADAY['max_quote_age_seconds'])) if at else None),
        prior_date=prior.get('date'),prior_height=prior.get('height'),prior_exact=prior.get('exact',False),
        prior_sealed=prior.get('sealed'),height=None,height_exact=False,sealed=None,touched=None,
        prior_suspended=prior.get('halted',False),suspended_current=False,
        roles=[],events=[],risks=[],eligible=False,history_reason=prior.get('reason'),
        broken_yesterday=bool(prior.get('sealed') is False and previous.get('sealed') is True and (previous.get('height') or 0)>=2),
        broken_from_height=previous.get('height') if prior.get('sealed') is False else None,
        feedback_pct=q.get('change_pct') if valid and number(q.get('change_pct')) else None,
        turnover_pct=q.get('turnover_pct') if valid else None,amount_wan=q.get('amount_wan') if valid else None,
        volume_yi=q['volume_shou']/1e6 if valid and number(q.get('volume_shou')) else None,
        price=q.get('price') if valid else None,limit_price=None,relations=[],continuation=[],observations=[])
    if not valid:return out
    if daily_proof:out['completed_daily_proof']=daily_proof;out['events'].append('收盘日线已核验')
    if session=='午间休市':out['valid_until']=now.date().isoformat()+' 13:00:00'
    elif formal:out['valid_until']=now.date().isoformat()+' 23:59:59'
    limit=q.get('limit_up');prev=q.get('last_close')
    if (not regime_ready or q.get('limit_pct')!=10 or not D.mainboard(code) or str(q.get('name') or row.get('name','')).upper().startswith(('ST','*ST','N','C'))
        or q.get('price_basis')!='raw' or q.get('price_basis_source') not in intraday._RAW_QUOTE_SOURCES
        or q.get('last_close_semantics')!='previous_trade_day_raw_close'
        or not all(number(q.get(k)) and q[k]>0 for k in ('last_close','price','high','low','open','limit_up'))
        or not q['low']<=q['price']<=q['high'] or not q['low']<=q['open']<=q['high']
        or D.tick(q['high'])>D.tick(limit) or D.tick(limit)!=D.tick(D.limit_price(prev))):
        out.update(valid=False,reason='当日主板涨停制度、原价涨停价或OHLC待核验');return out
    out.update(limit_price=limit,sealed=D.tick(q['price'])==D.tick(limit),touched=D.tick(q['high'])>=D.tick(limit),feedback_pct=round(100*(q['price']/prev-1),2))
    if prior.get('sealed') is not None or prior.get('halted'):
        out['height']=(prior.get('height') or 0)+1 if out['sealed'] else prior.get('height')
        out['height_exact']=prior.get('exact',False)
    out['completed_height']=out['height'] if formal and out['sealed'] else 0 if formal else prior.get('height')
    out['eligible']=bool(out['sealed'] or prior.get('sealed') or out['broken_yesterday'])
    if out['sealed']:
        out['events'].append('收盘封板' if formal else '当前涨停')
        if q['open']==q['low']==q['high']:out['risks'].append('一字板')
    elif out['touched']:out['events'].append('触板未封')
    elif prior.get('sealed'):out['events'].append('高标分歧观察' if (prior.get('height') or 0)>=2 else '昨日首板反馈')
    if number(out['feedback_pct']) and out['feedback_pct']<=P['large_loss_pct']:out['risks'].append('明显负反馈')
    if out['broken_yesterday']:out['roles'].append('断板反馈')
    if out['sealed'] and out['height_exact']:
        out['roles'].append('首板启动' if out['height']==1 else '连板晋级')
    elif out['sealed']:out['roles'].append('在板·连板链待补齐')
    recent=[]
    for item in (old or {}).get('observations') or []:
        t=intraday.parse_quote_timestamp(item.get('at'))
        if t and at and t.date()==at.date() and 0<(at-t).total_seconds()<=P['observation_interval_minutes']*60:recent.append(item)
    if recent:
        last=recent[-1]
        if last.get('sealed') is True and not out['sealed']:out['events'].append('采样观察到开板')
        if last.get('sealed') is False and last.get('touched') and out['sealed']:out['events'].append('采样观察到回封')
        if number(last.get('return_pct')) and last['return_pct']<=0 and out['feedback_pct'] is not None and out['feedback_pct']-last['return_pct']>=P['repair_gain_pp']:out['events'].append('采样分歧后修复')
    out['observations']=(recent+[dict(at=str(at),sealed=out['sealed'],touched=out['touched'],return_pct=out['feedback_pct'])])[-8:]
    return out

def board_stats(board,models,exclude=None):
    codes=set(board.get('member_codes') or [])-({exclude} if exclude else set());valid=[models[c] for c in codes if c in models and models[c]['valid']]
    returns=[m['feedback_pct'] for m in valid if number(m['feedback_pct'])]
    up=sum(v>0 for v in returns);sealed=[m for m in valid if m['sealed']]
    return dict(id=board['id'],name=board['name'],type=board['type'],expected=len(codes),valid=len(valid),coverage_pct=pct(len(valid),len(codes)),
        up_pct=pct(up,len(returns)),median_return_pct=med(returns),limit_count=len(sealed),
        ladder=dict(Counter(str(m['height']) for m in sealed if m['height'] is not None and m['height_exact'])),
        reliable=len(valid)>=P['min_peer_count'] and (pct(len(valid),len(codes)) or 0)>=P['min_peer_coverage_pct'])

def order_key(m):
    roles=m['roles'];priority=0 if '空间高标' in roles else 1 if '题材领先候选' in roles else 2 if '连板晋级' in roles else 3 if m['continuation'] else 4 if '首板启动' in roles else 5 if m['prior_sealed'] else 6
    return (not (m['valid'] or m['suspended_current']),not m['eligible'],0 if '周期最高标' in roles else priority,-(m['height'] or 0),not bool(m['sealed']),-(m['feedback_pct'] if number(m['feedback_pct']) else -999),-(m['amount_wan'] or 0),m['code'])

def cohort(models,codes):
    valid=[models[c] for c in codes if models[c]['valid']];sealed=sum(bool(m['sealed']) for m in valid)
    returns=[m['feedback_pct'] for m in valid if number(m['feedback_pct'])]
    return dict(expected=len(codes),valid=len(valid),coverage_pct=pct(len(valid),len(codes)),sealed=sealed,
        expected_codes=list(codes),success_codes=[m['code'] for m in sorted(valid,key=order_key) if m['sealed']],
        pending_codes=[c for c in codes if not models[c]['valid']],
        promotion_pct=pct(sealed,len(valid)),median_return_pct=med(returns),large_loss_count=sum(v<=P['large_loss_pct'] for v in returns),
        basis='有效报价样本内在板/收盘封板比例；未核验报价不计失败，分母及覆盖单列')

def attach(snap,quotes,pool,histories,calendar,now=None,previous=None,evidence=None,fetch=True,persist=True):
    now=now or datetime.fromisoformat(snap['quote_capture_at']);day=now.date().isoformat();session=snap.get('session')
    profile_started=time.monotonic();profile_cpu_started=time.process_time();profile_last=[profile_started];profile={}
    def mark_profile(label):
        now_mono=time.monotonic()
        profile[label]=round(now_mono-profile_last[0],3)
        profile_last[0]=now_mono
    rows={r['code']:r for r in snap.get('stocks',[])+snap.get('coverage_catalog',[])}
    dates=[d for d in calendar if d<day];days=dates[-P['history_days']:];replay_days=dates[-(P['history_days']+P['warmup_days']):]
    effective={c:effective_quote(snap,r,quotes) for c,r in rows.items()}
    verified=intraday.parse_quote_timestamp(snap.get('close_daily_verified_at'))
    if session=='已收盘' and verified and verified.date()==now.date() and verified<=datetime.now()+timedelta(seconds=config.INTRADAY['max_quote_future_seconds']):now=max(now,verified)
    proofs={}
    if session=='已收盘':
        proofs={c:p for c in rows if (p:=H.close_proof(snap,effective[c],histories.get(c) or [],calendar,now,code=c))}
    mark_profile("行情与证明")
    if evidence is None:
        H.ingest_close(snap,effective,now,proofs)
        evidence=H.load(rows,replay_days,dates,day,fetch=fetch and session not in ('盘前','集合竞价','非交易日'))
    mark_profile("证据加载")
    if 'emotion_pool_capture' in snap:
        evidence=dict(evidence,current_pool=snap['emotion_pool_capture'])
    if 'reference' in evidence:H.index(evidence)
    mark_profile("证据索引")
    # Suspension is inferred from verified data availability, not announcement
    # backfills. Callers may still inject explicit evidence for replay/tests.
    reg=evidence.get('regulation') or dict(notices=[],indices={},scope_codes=[],covered_codes=[],suspension_intervals=[],errors=[],rule_sources=R.RULE_SOURCES)
    mark_profile("监管规则")
    evidence['verified_halts']=reg.get('suspension_intervals',[])
    evidence['inferred_halts']={c:q['data_availability'] for c,q in effective.items()
        if (q.get('data_availability') or {}).get('kind')=='inferred_suspension'}
    paths={c:chain(c,replay_days,dates,histories.get(c) or [],evidence) for c in rows}
    mark_profile("历史链")
    times=[intraday.parse_quote_timestamp(q.get('quote_at') or q.get('ts'),now) for q in effective.values()]
    times=sorted(t for t in times if t and t.date()==now.date() and abs((now-t).total_seconds())<=config.INTRADAY['max_quote_age_seconds'])
    center=times[len(times)//2] if times else None
    previous=previous or {};same=(previous.get('emotion_relay') or {}).get('implementation_hash')==IMPLEMENTATION_HASH
    old={r['code']:r.get('emotion_relay') or {} for r in previous.get('stocks',[])+previous.get('coverage_catalog',[])} if same else {}
    models={c:current(c,r,effective[c],paths[c],now,session,center,old.get(c),
        regime_ready=sum(b.get('date','')<day and number(b.get('volume')) and b['volume']>0 for b in histories.get(c) or [])>=5,daily_proof=proofs.get(c)) for c,r in rows.items()}
    mark_profile("逐股模型")
    verified=[m for m in models.values() if m['valid'] and m['height_exact'] and (m['height'] or 0)>=P['leader_min_height']]
    maximum=max((m['height'] or 0 for m in verified),default=0)
    for m in verified:
        if m['height']==maximum:m['roles'].append('空间高标')
    boards=[b for b in snap.get('board_catalog',[]) if official(b)]
    for board in boards:
        board['emotion_relay']=dict(board_stats(board,models),version=VERSION,implementation_hash=IMPLEMENTATION_HASH,
            source_at=max((m['quote_at'] for m in models.values() if m['valid']),default=None))
    market_valid=[m for m in models.values() if m['valid']]
    market_limit_pct=pct(sum(bool(m['sealed']) for m in market_valid),len(market_valid))
    market_coverage=pct(len(market_valid),len(models)) or 0
    for board in boards:
        members=[models[c] for c in set(board.get('member_codes') or []) if c in models]
        leaders=[m for m in members if m['valid'] and m['height_exact'] and (m['height'] or 0)>=P['leader_min_height']]
        top=max((m['height'] for m in leaders),default=0)
        for m in members:
            if not m['eligible'] or not m['valid']:continue
            peers=board_stats(board,models,m['code']);kind='联动待核验'
            if peers['reliable']:
                if peers['limit_count']>=P['diffusion_limit_peers'] and (peers['up_pct'] or 0)>=P['diffusion_up_pct']:kind='同题材扩散'
                elif m['sealed'] and peers['limit_count']==0 and (peers['up_pct'] or 0)<50:kind='个股独立偏强'
                else:kind='题材分化观察'
            peers['state']=kind;m['relations'].append(peers)
            if board['type']=='theme' and m in leaders and m['height']==top and peers['reliable']:m['roles'].append('题材领先候选')
    mark_profile("板块统计")
    cycles=C.attach(rows,models,paths,boards,evidence,reg,dates,day)
    watch=W.attach(rows,models,paths,effective,evidence,dates,day,now,fetch=fetch and session not in ('盘前','集合竞价','非交易日'))
    mark_profile("周期与池")
    for m in models.values():
        rivals=[r['code'] for r in verified if r['code']!=m['code'] and r['prior_height']==m['prior_height'] and (m['prior_height'] or 0)>=2]
        if m['valid'] and rivals:m['roles'].append('同身位竞争');m['rivals']=rivals
        m['roles']=list(dict.fromkeys(m['roles']));m['relations'].sort(key=lambda b:(not b['reliable'],-b['limit_count'],-(b['up_pct'] or 0),b['id']))
        rows[m['code']]['emotion_relay']=m
    mark_profile("角色关系")
    # Roles from board diffusion and cycle attribution are part of the order.
    order_map={c:order_key(m) for c,m in models.items()}
    yesterday=[c for c,m in models.items() if m['prior_sealed'] is True]
    broken=[c for c,m in models.items() if m['broken_yesterday']]
    feedback=cohort(models,yesterday);broken_feedback=cohort(models,broken)
    chain_feedback=cohort(models,[c for c in yesterday if models[c]['prior_exact'] and (models[c]['prior_height'] or 0)>=2])
    formal=session=='已收盘' and any(m['valid'] and m['mode']=='正式收盘' for m in models.values())
    state='接力样本待核验'
    if feedback['valid']>=P['feedback_min_sample'] and (feedback['coverage_pct'] or 0)>=P['min_peer_coverage_pct']:
        state='晋级分化'
        if (feedback['promotion_pct'] or 0)>=P['promotion_strong_pct'] and (feedback['median_return_pct'] or 0)>0:state='高标与晋级维持'
        elif (feedback['promotion_pct'] or 0)<P['promotion_weak_pct'] and (feedback['median_return_pct'] or 0)<=P['negative_feedback_pct']:state='接力负反馈增加'
    rankings={}
    for board in snap.get('board_catalog',[])+[dict(id='all',member_codes=list(rows))]:
        codes=list(dict.fromkeys(board.get('member_codes') or []));base=(snap.get('stock_board_ranking') or {}).get('all') if board['id']=='all' else board.get('stock_ranking')
        base=base or {};emotion=sorted((c for c in codes if c in models and (models[c]['valid'] or models[c]['suspended_current']) and models[c]['eligible']),key=lambda c:order_map[c]);ranks={c:i+1 for i,c in enumerate(emotion)}
        ordered=emotion+[c for c in base.get('all',codes) if c not in ranks]
        items={}
        for c in codes:
            item=dict((base.get('items') or {}).get(c) or {});m=models.get(c) or {}
            labels=[v for v in item.get('style_labels',[]) if v not in ('情绪强势','情绪前排','暂未强势')]
            if c in ranks:labels+=['接力观察']+(m.get('roles') or [])
            if not labels:labels=['暂无接力事件']
            item.update(emotion=c in ranks,emotion_rank=ranks.get(c),style_labels=list(dict.fromkeys(labels)),source_at=m.get('quote_at') or item.get('source_at'))
            items[c]=item
        # Default complete-member order and all trend ranks stay fixed. Only the
        # explicit emotion order/column adopts the new relay evidence ordering.
        rankings[board['id']]=dict(base,all=base.get('all',codes),trend=base.get('trend',codes),emotion=ordered,items=items,
            expected=len(codes),emotion_valid=len(emotion),emotion_basis='高度、角色、在板状态、反馈、成交额；证据排序，不是成功概率')
    mark_profile("排名")
    daily_ladder=Counter(str(m['prior_height']) for m in models.values() if m['prior_exact'] and m['prior_sealed'])
    live_ladder=Counter(str(m['height']) for m in models.values() if m['valid'] and m['sealed'] and m['height_exact'])
    promotion=[dict(height=n,**cohort(models,[c for c in yesterday if models[c]['prior_exact'] and models[c]['prior_height']==n])) for n in sorted({models[c]['prior_height'] for c in yesterday if models[c]['prior_exact']})]
    timeline=[]
    for i,d in enumerate(days):
        offset=len(replay_days)-len(days);known=[p[offset+i] for p in paths.values() if p[offset+i]['sealed'] is not None or p[offset+i]['halted']]
        timeline.append(dict(date=d,valid=len(known),expected=len(rows),suspended=sum(p['halted'] for p in known),limit_count=sum(p['sealed'] is True for p in known),highest=max((p['height'] for p in known if p['exact'] and p['sealed']),default=None),
            retained_highest=max((p['height'] or 0 for p in known if p['exact']),default=None),unknown=len(rows)-len(known)))
    # Include today's completed result only after a verified formal close.
    if formal:
        completed=[m['history'][-1] for m in models.values() if m.get('history') and m['history'][-1]['date']==day and (m['history'][-1]['sealed'] is not None or m['history'][-1]['halted'])]
        timeline=(timeline+[dict(date=day,valid=len(completed),expected=len(rows),suspended=sum(p['halted'] for p in completed),limit_count=sum(p['sealed'] is True for p in completed),
            highest=max((p['height'] or 0 for p in completed if p['exact'] and p['sealed']),default=0),retained_highest=max(cycles['cycle_highest'],max((p['height'] or 0 for p in completed if p['exact']),default=0)),unknown=len(rows)-len(completed))])[-P['history_days']:]
    ordered=sorted(models,key=lambda c:order_map[c]);lists={
        'all':[c for c in ordered if (models[c]['valid'] or models[c]['suspended_current']) and models[c]['eligible']],
        'leaders':[c for c in ordered if (models[c]['valid'] or models[c]['suspended_current']) and any(r in models[c]['roles'] for r in ('周期核心观察','空间高标','题材领先候选','同身位竞争'))],
        'continuation':[c for c in ordered if models[c]['valid'] and models[c]['continuation']],
        'companions':[c for c in ordered if models[c]['valid'] and models[c].get('companions')],
        'suspended':[c for c in ordered if models[c]['suspended_current']],
        'broken':watch['broken'],
        'sealed':watch['sealed'],
        'pending':[c for c in ordered if not models[c]['suspended_current'] and (not models[c]['valid'] or models[c]['prior_sealed'] is None and not models[c]['prior_suspended'])]}
    snap['emotion_relay']=dict(version=VERSION,implementation_hash=IMPLEMENTATION_HASH,parameters=copy.deepcopy(P),at=str(now),
        source_at=max((m['quote_at'] for m in models.values() if m['valid']),default=None),mode='正式收盘' if formal else '午休参考' if session=='午间休市' else '盘中暂态',
        scope='沪深主板普通10%制度；当前封板即计入当日板数，开板撤销当日这一板；历史连板链按完成日线计算',
        history_from=timeline[0]['date'] if timeline else None,history_asof=timeline[-1]['date'] if timeline else None,history_days=len(timeline),
        prior_history_asof=days[-1] if days else None,
        coverage=dict(pool=len(rows),valid_quotes=sum(m['valid'] for m in models.values()),valid_history=timeline[-1]['valid'] if formal else sum(m['prior_sealed'] is not None or m['prior_suspended'] for m in models.values()),
            verified_pool_days=sum(p.get('date_verified') is True for p in evidence['pools'].values()),expected_pool_days=len(days)),
        state=state,highest_previous=max((m['prior_height'] or 0 for m in models.values() if m['prior_exact'] and m['prior_sealed']),default=0),
        highest_completed=(max((m['completed_height'] or 0 for m in models.values() if m['valid'] and m['height_exact']),default=0)
            if formal else max((m['prior_height'] or 0 for m in models.values() if m['prior_exact']),default=0)),
        highest_live=max((m['height'] or 0 for m in verified if m['sealed']),default=0),
        daily_ladder=dict(daily_ladder),live_ladder=dict(live_ladder),promotion=promotion,
        promotion_height_pending=sum(not models[c]['prior_exact'] for c in yesterday),
        yesterday_feedback=feedback,yesterday_chain_feedback=chain_feedback,broken_feedback=broken_feedback,
        lists=lists,pools=watch,boards=[board_stats(b,models) for b in boards],rankings=rankings,timeline=timeline,cycles=cycles,fetch=evidence.get('fetch') or {},
        limitations=['未提供连板成功概率','封板强度使用已核对字段的供应商统计，非逐笔重建；封单可撤销','题材同步不等于因果带动，不推断躲异动动机'],
        profile=dict(profile,total=round(time.monotonic()-profile_started,3),
                    cpu_total=round(time.process_time()-profile_cpu_started,3)))
    if persist and any(m['valid'] for m in models.values()):save_observation(snap)
    snap['emotion_relay']['profile']['total']=round(time.monotonic()-profile_started,3)
    snap['emotion_relay']['profile']['cpu_total']=round(time.process_time()-profile_cpu_started,3)
    return snap['emotion_relay']

def save_observation(snap):
    meta=snap['emotion_relay'];path=D.root()/'observations'/(meta['source_at'][:10]+'.jsonl.gz');last=D.read(path.with_suffix('.last.json')) or {}
    if last.get('at')==meta['source_at'] and last.get('hash')==IMPLEMENTATION_HASH:return
    rows={r['code']:r for r in snap.get('stocks',[])+snap.get('coverage_catalog',[])}
    record=dict(version=VERSION,implementation_hash=IMPLEMENTATION_HASH,source_at=meta['source_at'],captured_at=meta['at'],
        state=meta['state'],candidates=[dict(code=c,name=rows[c].get('name'),**{k:rows[c]['emotion_relay'].get(k) for k in
            ('quote_at','prior_date','prior_height','height','height_exact','price','limit_price','feedback_pct','turnover_pct','roles','events','risks','continuation')}) for c in meta['lists']['all']])
    path.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(path,'at',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
    D.write(path.with_suffix('.last.json'),dict(at=meta['source_at'],hash=IMPLEMENTATION_HASH))

def brief(m):return {k:v for k,v in m.items() if k not in ('observations','history','node_history')}
def validate(snap):
    meta=snap['emotion_relay'];assert meta['version']==VERSION and meta['implementation_hash']==IMPLEMENTATION_HASH
    rows={r['code']:r['emotion_relay'] for r in snap['stocks']+snap.get('coverage_catalog',[])}
    for key,ids in meta['lists'].items():
        assert len(ids)==len(set(ids)) and set(ids)<=set(rows)
        if key!='pending':assert all(rows[c]['valid'] or rows[c]['suspended_current'] for c in ids)
    for c,m in rows.items():
        if m['sealed']:assert m['valid'] and m['price']==m['limit_price']
        if '首板启动' in m['roles']:assert m['height_exact'] and m['height']==1
        if m['continuation']:assert m['valid'] and m['height_exact'] and all(n['first_board_date']==n['date'] for n in m['continuation'])
    assert meta['lists']['sealed']==sorted(meta['lists']['sealed'],key=lambda c:W.cap_key(rows[c]))
    for c in meta['lists']['broken']:
        b=rows[c]['break_watch'];assert rows[c]['valid'] and b['height']>=P['broken_min_height']
    for cohort in meta['promotion']:
        assert len(cohort['success_codes'])==cohort['sealed']
        assert all(rows[c]['prior_exact'] and rows[c]['prior_height']==cohort['height'] and rows[c]['sealed'] and rows[c]['valid'] for c in cohort['success_codes'])
    for rank in meta['rankings'].values():
        assert len(rank['all'])==len(set(rank['all']))==rank['expected']
        assert set(rank['all'])==set(rank['emotion'])==set(rank['trend'])
        eligible=[c for c in rank['emotion'] if c in rows and (rows[c]['valid'] or rows[c]['suspended_current']) and rows[c]['eligible']]
        assert rank['emotion'][:len(eligible)]==sorted(eligible,key=lambda c:order_key(rows[c])), '接力排序与最终角色不一致'
    return True
