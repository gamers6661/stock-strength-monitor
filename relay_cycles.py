"""Replay dated cycle anchors and event-day first-board cohorts without hindsight."""
from collections import defaultdict
import config,relay_history as H,relay_regulation as R,relay_relations


def runs(path):
    result=[];active=None
    for p in path:
        if p.get('sealed') and p.get('exact'):
            if active is None:
                active=dict(start=p['date'],last=p['date'],height=p['height'],days=[])
            active.update(last=p['date'],height=p['height']);active['days'].append(p['date'])
        elif p.get('halted'):
            continue
        elif active:
            active['end']=p['date'];result.append(active);active=None
    if active:result.append(dict(active,end=None))
    return result


def focus(evidence,codes):
    """Disclosure scope: verified multi-board stocks plus missing actual sessions."""
    selected=set()
    for c in codes:
        raw=evidence.get('_raw_index',{}).get(c,{})
        n=0
        for d,b in sorted(raw.items()):
            ref=evidence.get('_ref_index',{}).get(c,{}).get(d)
            n=n+1 if ref and H.D.tick(b['close'])==H.D.tick(b['high'])==H.D.tick(H.D.limit_price(ref['reference_close'])) else 0
            if n>=2:selected.add(c)
    for record in evidence.get('halts',{}).values():
        selected.update(r['SECURITY_CODE'] for r in record.get('rows',[]) if r.get('SECURITY_CODE') in codes)
    return sorted(selected)


def attach(rows,models,paths,boards,evidence,reg,dates,day):
    P=config.EMOTION_RELAY;all_dates=dates+[day];position={d:i for i,d in enumerate(all_dates)}
    formal=any(m['valid'] and m['mode']=='正式收盘' for m in models.values())
    if formal:
        completed={}
        for c,path in paths.items():
            m=models[c];extra=[]
            if m['valid'] and m['mode']=='正式收盘':
                extra=[dict(date=day,sealed=m['sealed'],height=m['height'] if m['sealed'] else 0,exact=m['height_exact'],halted=False,reason=None)]
            elif H.halt_on(evidence,c,day) and path:
                extra=[dict(path[-1],date=day,sealed=None,halted=True,reason='全天停牌，已完成板位保留且不增长')]
            completed[c]=path+extra
        paths=completed
    lookup={c:{p['date']:p for p in path} for c,path in paths.items()};waves={c:runs(p) for c,p in paths.items()}
    for c,m in models.items():
        if m['valid']:
            lookup[c][day]=dict(date=day,sealed=m['sealed'],height=m['height'] if m['sealed'] else 0,exact=m['height_exact'],halted=False,pending=m['mode']!='正式收盘')
    recent=(all_dates if formal else dates)[-P['cycle_core_recent_days']:]
    def shared(a,b):
        return relay_relations.shared(a,b,rows)
    def top_before(c,d):
        ix=position.get(d,0)-1
        if ix<0:return False,None
        prev=all_dates[ix];p=lookup[c].get(prev,{})
        h=p.get('height') or 0
        maximum=max((v.get(prev,{}).get('height') or 0 for v in lookup.values() if v.get(prev,{}).get('exact') and (v.get(prev,{}).get('sealed') or v.get(prev,{}).get('halted'))),default=0)
        return bool(p.get('exact') and h>=P['cycle_core_min_height'] and h==maximum),h
    cores=[]
    for c,w in waves.items():
        eligible=[r for r in w if r['height']>=P['cycle_core_min_height'] and r['last'] in recent]
        if not eligible:continue
        wave=eligible[-1];m=models[c]
        halt=H.halt_on(evidence,c,day)
        if halt and m['valid']:
            m['risks'].append('停牌记录与有效成交报价冲突');halt=None
        # A dated full-day suspension is distinct from a stale traded quote.
        if halt:
            m.update(suspended_current=True,suspension=halt,eligible=True,feedback_pct=None,sealed=None,height=wave['height'],height_exact=True)
            m['roles'].append('停牌核心观察');m['reason']='全天停牌，保留已完成高度；不计入在板与晋级分母'
            m['last_trade_date']=wave['last'];m['price']=(evidence.get('_raw_index',{}).get(c,{}).get(wave['last']) or {}).get('close')
        m['cycle']=dict(wave,code=c,name=rows[c].get('name'),suspended=bool(halt))
        m['roles'].append('周期核心观察');cores.append(m['cycle'])
    maximum=max((r['height'] for r in cores),default=0)
    for r in cores:
        if r['height']==maximum:models[r['code']]['roles'].append('周期最高标')
    # Published disclosures and actual board breaks are separate event types.
    nodes=[];seen=set()
    for n in sorted(reg.get('notices',[]),key=lambda n:n['published_at']):
        if n['kind']!='serious' or not n.get('available_day'):continue
        d=n['available_day']
        for c in n['codes']:
            if c not in lookup:continue
            ok,height=top_before(c,d)
            wave=next((w for w in waves[c] if w['start']<=d and (not w['end'] or d<=w['end'])),None)
            key=(c,'regulation',(wave or {}).get('start'))
            if not ok or not wave or key in seen:continue
            seen.add(key);nodes.append(dict(id=n['id'],kind='regulation',label='监管接续候选',date=d,leader=c,leader_name=rows[c].get('name'),leader_height=height,known_at=n['published_at'],source=n['url'],leader_chain_start=wave['start']))
    for c,path in paths.items():
        for i,p in enumerate(path):
            if i==0:continue
            prior=path[i-1];kind=None
            if p.get('sealed') is False and prior.get('sealed') is True:kind='break'
            if p.get('halted') and not prior.get('halted'):kind='suspension'
            if not kind:continue
            ok,height=top_before(c,p['date'])
            if not ok:continue
            halt=H.halt_on(evidence,c,p['date']) if kind=='suspension' else None
            if kind=='suspension' and not (halt or {}).get('known_at'):continue
            node_day=max(p['date'],R.available_day(halt['known_at'],dates,day) or day) if halt else p['date']
            wave=next((w for w in waves[c] if w['start']<=p['date'] and (not w['end'] or p['date']<=w['end'])),{})
            nodes.append(dict(id=c+'_'+p['date']+'_'+kind,kind=kind,label='断板补涨候选' if kind=='break' else '停牌接续候选',date=node_day,leader=c,leader_name=rows[c].get('name'),leader_height=height,known_at=(halt or {}).get('known_at') or p['date']+' 15:00:00',source=(halt or {}).get('source'),leader_chain_start=wave.get('start')))
    # A first board must occur ON the node's usable trading day. Following a
    # cohort into its third/fourth board never changes its original anchor.
    for node in nodes:
        node['members']=[]
        for c,m in models.items():
            p=lookup[c].get(node['date'],{})
            if c==node['leader'] or not p.get('exact') or not p.get('sealed') or p.get('height')!=1:continue
            links=shared(node['leader'],c)
            if not links:continue
            cohort=dict(node,boards=links,board=links[0]['name'],board_id=links[0]['id'],first_board_date=node['date'],own_height=m.get('height'),
                active=bool(m['valid'] and m.get('height_exact') and m.get('prior_sealed') and m.get('sealed')),
                basis='节点当日首板且有共同主营行业或业务主线依据；持续跟踪该批次，催化与因果尚待核验')
            cohort.pop('members',None);m.setdefault('node_history',[]).append(cohort);node['members'].append(c)
            # Show current continuing waves, never revive a broken old cohort.
            tail=[v for v in paths[c] if v['date']>=node['date']]
            intact=all(v.get('sealed') or v.get('halted') for v in tail)
            if intact and m['valid'] and m['height_exact'] and (m['sealed'] or m['prior_sealed'] and m['mode']!='正式收盘'):
                cohort['active']=bool(m['sealed']);m['continuation'].append(cohort);m['roles'].append(node['label']);m['eligible']=True
    for core in cores:
        c=core['code'];core_days=set(core['days'])
        for child,rs in waves.items():
            if child==c:continue
            links=shared(c,child)
            if not links:continue
            for wave in rs:
                gap=position.get(wave['start'],-999)-position.get(core['start'],999)
                overlap=sorted(core_days&set(wave['days']))
                if wave['height']>=P['cycle_core_min_height'] and wave['end'] and wave['end']<core['start'] and 0<position.get(core['start'],0)-position.get(wave['last'],-999)<=P['warmup_days']:
                    models[child].setdefault('previous_cores',[]).append(dict(leader=c,leader_name=core['name'],start=wave['start'],last=wave['last'],end=wave['end'],height=wave['height'],boards=links))
                    models[child]['roles'].append('同题材前轮高标')
                if abs(gap)>P['companion_start_gap'] or len(overlap)<P['companion_overlap_days']:continue
                m=models[child];relation=dict(leader=c,leader_name=core['name'],start=wave['start'],core_start=core['start'],start_gap=gap,overlap_days=overlap,boards=links,basis='启动相距不超过2个交易日，至少2个完成日同步封板；仅为伴生关系观察')
                m.setdefault('companions',[]).append(relation);m['roles'].append('伴生关系观察')
                if m['valid']:m['eligible']=True
    for c,m in models.items():
        halt=H.halt_on(evidence,c,day)
        if halt and not m['valid'] and not m['suspended_current']:
            previous=paths[c][-1] if paths[c] else {}
            last=next((p for p in reversed(paths[c]) if p.get('sealed') is not None),{})
            m.update(suspended_current=True,suspension=halt,feedback_pct=None,sealed=None,
                height=previous.get('height'),height_exact=previous.get('exact',False),
                last_trade_date=last.get('date'),price=(evidence.get('_raw_index',{}).get(c,{}).get(last.get('date')) or {}).get('close'))
            m['reason']='按缺失规则推定停牌，保留最后成交日与板位；复牌后续接' if halt.get('inferred') else '全天停牌，保留最后成交日与板位'
        if m.get('suspension',{}).get('inferred'):m['events'].append('停牌（按缺失规则推定）')
        m['history']=[dict(p,close=m.get('price') if p['date']==day and m['valid'] else (evidence.get('_raw_index',{}).get(c,{}).get(p['date']) or {}).get('close')) for p in paths[c][-P['history_days']:]]
        notices=[n for n in reg.get('notices',[]) if c in n['codes']]
        m['regulation']=dict(notices=[{k:v for k,v in n.items() if k!='text'} for n in notices],covered=c in reg.get('covered_codes',[]))
        if notices and any(n['kind']=='serious' for n in notices):m['risks'].append('已披露严重异动')
        if m['eligible'] or c in reg.get('scope_codes',[]):m['regulation']['reference']=R.deviation(c,all_dates if formal else dates,evidence,reg.get('indices',{}))
    return dict(cycle_highest=maximum,cores=sorted(cores,key=lambda r:(-r['height'],r['code'])),nodes=nodes,
        disclosure_coverage=dict(expected=len(reg.get('scope_codes',[])),covered=len(reg.get('covered_codes',[])),errors=reg.get('errors',[])),rule_sources=reg.get('rule_sources',R.RULE_SOURCES))
