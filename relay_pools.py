"""Current cap quality and dated >=3-board break feedback; no MA decisions."""
import math
from datetime import datetime
import config,intraday,relay_data as D

P=config.EMOTION_RELAY

def num(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def captured_at(value):
    # Our fetch timestamp is datetime.isoformat, including fractional seconds;
    # do not change the stricter parser for external quote timestamps.
    try:
        at=datetime.fromisoformat(str(value))
        return at if at.tzinfo is None else None
    except (ValueError,TypeError):return None

def seal_time(value):
    if not num(value) or int(value)!=value:return None
    s=str(int(value)).zfill(6)
    if len(s)!=6:return None
    try:t=datetime.strptime(s,'%H%M%S')
    except ValueError:return None
    h=t.hour*3600+t.minute*60+t.second
    if not (9*3600+25*60<=h<=11*3600+30*60 or 13*3600<=h<=15*3600):return None
    return t.strftime('%H:%M:%S')

def pool_clock(pool,day,now,formal):
    at=captured_at((pool or {}).get('fetched_at'))
    if (not at or at.date().isoformat()!=day or str(pool.get('provider_market_date'))!=day.replace('-','')
        or pool.get('day')!=day or (at-now).total_seconds()>config.INTRADAY['max_quote_future_seconds']):return False
    return at.hour>=15 if formal else 0<=(now-at).total_seconds()<=P['pool_quote_gap_seconds']

def load_current(day,now,formal,fetch=True):
    path=D.root()/'current_pool.json';cached=D.read(path) or {}
    at=captured_at(cached.get('fetched_at'))
    if pool_clock(cached,day,now,formal) and (formal or at and (now-at).total_seconds()<P['pool_cache_seconds']):return cached
    if fetch:
        try:
            result=D.fetch_pool(day)
            # A response is acquired after the request clock. Validate against
            # collection completion, while strength() still matches quote time.
            if pool_clock(result,day,datetime.now(),formal):D.write(path,result);return result
            cached=dict(cached,fetch_error='涨停池响应日期或采集时间与本次采集不符')
        except (OSError,ValueError,RuntimeError,TypeError) as e:
            cached=dict(cached,fetch_error=str(e))
    return cached

def strength(m,q,pool,day,now):
    out=dict(verified=False,source='东方财富当日涨停池',source_at=pool.get('fetched_at'),
        reason='当日涨停池封板明细待核验',first_seal=None,last_seal=None,reopen_count=None,
        seal_amount_yuan=None,amount_yuan=None,seal_to_amount_pct=None,labels=[])
    if not pool_clock(pool,day,now,m['mode']=='正式收盘'):
        out['reason']=pool.get('fetch_error') or '本轮未取得日期与时间匹配的涨停明细'
        return out
    e=(pool.get('entries') or {}).get(m['code']) or {}
    if not num(e.get('price')) or D.tick(e['price'])!=D.tick(m['price']):
        out['reason']='当日涨停池与当前核验涨停价未对齐';return out
    if m['mode']!='正式收盘':
        quote_at=intraday.parse_quote_timestamp(m.get('quote_at'));at=captured_at(pool['fetched_at'])
        if not quote_at or abs((at-quote_at).total_seconds())>P['pool_quote_gap_seconds']:
            out['reason']='涨停明细与报价相差超过120秒';return out
    first=seal_time(e.get('first_seal'));last=seal_time(e.get('last_seal'));opens=e.get('reopen_count')
    if (not first or not last or last<first or last>min(now,captured_at(pool['fetched_at'])).strftime('%H:%M:%S') or
        not num(opens) or int(opens)!=opens or opens<0 or
        not num(e.get('seal_amount_yuan')) or e['seal_amount_yuan']<0 or not num(e.get('amount_yuan')) or e['amount_yuan']<=0):return out
    labels=['封板稳定'] if opens==0 else ['反复开板'] if opens>=P['pool_reopen_warning'] else ['回封涨停']
    out.update(verified=True,reason=None,first_seal=first,last_seal=last,reopen_count=int(opens),
        seal_amount_yuan=e['seal_amount_yuan'],amount_yuan=e['amount_yuan'],
        seal_to_amount_pct=round(100*e['seal_amount_yuan']/e['amount_yuan'],4),labels=labels)
    return out

def cap_key(m):
    s=m['cap_strength']
    return (not m['height_exact'],-(m['height'] or 0) if m['height_exact'] else 0,not s['verified'],
        s['reopen_count'] if s['verified'] else 999,
        -(s['seal_to_amount_pct'] or 0),s['last_seal'] or '99',s['first_seal'] or '99',m['code'])

def break_event(path):
    """Unknown sessions invalidate continuity; only an observed noncap is a break."""
    active=None;event=None
    for p in path:
        if p.get('halted'):continue
        if p.get('sealed') is True:
            # A 1/2-board return is feedback on the old break. A newly completed
            # >=3-board cycle supersedes it and will own its next break event.
            if p.get('exact') and (p.get('height') or 0)>=P['broken_min_height']:event=None
            if p.get('exact'):
                if active is None:active=dict(start=p['date'])
                active.update(last=p['date'],height=p.get('height'))
            else:active=None
        elif p.get('sealed') is False:
            if active and (active.get('height') or 0)>=P['broken_min_height']:
                event=dict(active,date=p['date'])
            active=None
        else:active=None;event=None
    return event

def attach(rows,models,paths,quotes,evidence,dates,day,now,fetch=True):
    formal=any(m['valid'] and m['mode']=='正式收盘' for m in models.values())
    pool=evidence.get('current_pool')
    if pool is None:pool=load_current(day,now,formal,fetch=fetch)
    recent=(dates+[day])[-P['broken_watch_days']:];position={d:i for i,d in enumerate(dates+[day])}
    completed={}
    for c,path in paths.items():
        m=models[c];extra=[]
        if m['valid'] and m['mode']=='正式收盘':extra=[dict(date=day,sealed=m['sealed'],height=m['height'],exact=m['height_exact'],halted=False)]
        elif m['suspended_current']:extra=[dict(date=day,sealed=None,halted=True)]
        completed[c]=path+extra
    lookup={c:{p['date']:p for p in path} for c,path in completed.items()}
    raw=evidence.get('_raw_index') or {c:{b['date']:b for b in r.get('bars',[])} for c,r in evidence.get('raw',{}).items()}
    broken=[];pending=[];sealed=[]
    for c,m in models.items():
        if m['valid'] and m['sealed']:
            m['cap_strength']=strength(m,quotes[c],pool,day,now);sealed.append(c)
        event=break_event(completed[c])
        # Intraday failure of yesterday's >=3-board stock is a pending break,
        # never a completed break or a replacement for its completed chain.
        prior=paths[c][-1] if paths[c] else {}
        provisional=bool(m['valid'] and m['mode']!='正式收盘' and not m['sealed'] and
            (prior.get('sealed') or prior.get('halted')) and prior.get('exact') and (prior.get('height') or 0)>=P['broken_min_height'])
        if provisional:
            start=next((w['date'] for w in reversed(paths[c]) if w.get('sealed') and w.get('height')==1),prior['date'])
            event=dict(start=start,last=prior['date'],height=prior['height'],date=day)
        if not event or event['date'] not in recent:continue
        ix=position[event['date']];before=(dates+[day])[ix-1] if ix else None
        highs=[p.get(before,{}) for p in lookup.values()]
        maximum=max((p.get('height') or 0 for p in highs if p.get('exact') and (p.get('sealed') or p.get('halted'))),default=0)
        b=raw.get(c,{}).get(event['date']) or {};last=raw.get(c,{}).get(event['last']) or {}
        if event['date']==day and m['valid']:b=quotes[c]
        bottom=b.get('low');top=b.get('high');close=m.get('price') if event['date']==day and m['valid'] else b.get('close')
        q=quotes[c];valid=m['valid'];price=m.get('price');labels=[];change=m.get('feedback_pct')
        low=q.get('low');high=q.get('high');opening=q.get('open');prev=q.get('last_close')
        limit_down=D.limit_price(prev,-10) if num(prev) and prev>0 else None
        since=round(100*(price/close-1),2) if valid and num(close) and close>0 and event['date']<day else None
        from_last=round(100*(price/last['close']-1),2) if valid and num(last.get('close')) and last['close']>0 else None
        break_return=None
        ref=evidence.get('_ref_index',{}).get(c,{}).get(event['date'],{}).get('reference_close') or last.get('close')
        if num(close) and num(ref) and ref>0:break_return=round(100*(close/ref-1),2)
        if valid:
            if m['sealed']:labels.append('断板后再封板')
            if limit_down is not None and D.tick(price)==D.tick(limit_down):labels.append('跌停负反馈')
            elif num(change) and change<=P['large_loss_pct']:labels.append('明显负反馈')
            if num(bottom) and event['date']<day and price<bottom:labels.append('跌破断板日低点')
            if num(top) and event['date']<day and price>top:labels.append('突破断板日高点')
            repair=100*(price/opening-1) if num(opening) and opening>0 else None
            loc=(price-low)/(high-low) if all(num(v) for v in (price,low,high)) and high>low else None
            if (event['date']<day and num(break_return) and break_return<=0 and num(change) and change>0
                and num(repair) and repair>=P['broken_repair_pct'] and loc is not None and loc>=P['broken_close_position']):labels.append('弱后转强观察')
            elif num(change) and change>0:labels.append('反弹观察' if event['date']<day else '上涨未封观察')
            if not labels:labels.append('分歧延续观察')
        state=dict(**event,pending=provisional,valid=valid,source_at=m['quote_at'],
            was_market_highest=bool(maximum and event['height']==maximum),market_highest_before=maximum,
            break_low=bottom,break_high=top,break_close=close,break_return_pct=break_return,
            sessions_since=position[day]-position[event['date']],since_break_pct=since,from_last_seal_pct=from_last,
            limit_down=limit_down,labels=labels or ['最新反馈待更新'],
            basis='最近20个交易日内最后一轮≥3板的实际断板；再封1/2板保留反馈，新一轮正式达到3板后结束旧观察。停牌和未知不算断板。')
        m['break_watch']=state
        if valid:m['eligible']=True;m['roles'].append('高标断板观察');broken.append(c)
        else:pending.append(c)
    sealed.sort(key=lambda c:cap_key(models[c]));groups={}
    for c in sealed:
        m=models[c];key=str(m['height']) if m['height_exact'] else 'unknown';groups.setdefault(key,[]).append(c)
        m['cap_strength']['height_rank']=len(groups[key]) if m['cap_strength']['verified'] and m['height_exact'] else None
    broken.sort(key=lambda c:(not models[c]['break_watch']['was_market_highest'],-models[c]['break_watch']['height'],
        -position[models[c]['break_watch']['date']],-(models[c]['feedback_pct'] or 0),c))
    return dict(sealed=sealed,broken=broken,broken_pending=pending,groups=groups,
        strength_coverage=sum(models[c]['cap_strength']['verified'] for c in sealed),strength_expected=len(sealed),
        source_at=pool.get('fetched_at'),fetch_error=pool.get('fetch_error'),
        strength_basis='同板位：炸板次数升序 → 封板资金/当日成交额降序 → 最后封板时间、首次封板时间升序；明细不全单列，非成功概率。')
