"""Recent turning observations. Completed strength and formal eligibility remain independent."""
import math
import hashlib
import json
from datetime import datetime
from statistics import mean,median

VERSION='近期转强观察20261028.2'
RULES=dict(min_market_coverage=.8,clock_tolerance_seconds=60,min_peers=6,
    advance3_min=2.,excess3_min=1.,improvement3_min=1.,local_buffer_atr=.1,
    close_position_min=.6,recent_volume_min=1.1,day_volume_min=1.2,current_positive_required=True,
    live_return_min=1.5,live_excess_min=1.,same_clock_volume_min=1.2,
    hold_samples=3,hold_seconds=240,max_sample_gap_seconds=180,
    near_breakout_atr=1.5,episode_gap_days=5)


def number(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)


def valid_price(b):
    return all(number(b.get(k)) and b[k]>0 for k in ('open','high','low','close')) and b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high']


def date_time(v):
    try:return datetime.fromisoformat(str(v))
    except (ValueError,TypeError):return None


def held_local(code,frames,at,price,level):
    """Only consecutive actual source-clock samples; never interpolate missing minutes."""
    samples=[]
    for _,frame in frames or []:
        point=frame.get(code) or {};t=date_time(point.get('at'));p=point.get('price')
        if t and t.date()==at.date() and 0<=(at-t).total_seconds()<=600 and number(p) and p>0:samples.append((t,p))
    samples=sorted(dict(samples+[(at,price)]).items());tail=[]
    for t,p in reversed(samples):
        if p<level or tail and (tail[-1][0]-t).total_seconds()>RULES['max_sample_gap_seconds']:break
        tail.append((t,p))
    seconds=(at-tail[-1][0]).total_seconds() if tail else 0
    return dict(confirmed=len(tail)>=RULES['hold_samples'] and seconds>=RULES['hold_seconds'],samples=len(tail),seconds=seconds)


def daily_inputs(bars,day):
    bs=[b for b in bars if b['date']<=day]
    if len(bs)<21 or not all(valid_price(b) and number(b.get('volume')) and b['volume']>0 for b in bs[-20:]):return None
    tr=[max(b['high']-b['low'],abs(b['high']-a['close']),abs(b['low']-a['close'])) for a,b in zip(bs[-21:-1],bs[-20:])]
    atr=mean(tr)
    if atr<=0:return None
    last=bs[-1];base=median(b['volume'] for b in bs[-13:-3])
    local_level=max(b['high'] for b in bs[-6:-1]);support=min(b['low'] for b in bs[-5:])
    return dict(bars=bs,close=last['close'],atr=atr,return1=100*(last['close']/bs[-2]['close']-1),
        return3=100*(last['close']/bs[-4]['close']-1),prior3=100*(bs[-4]['close']/bs[-7]['close']-1),
        local_level=local_level,support=support,local_break_atr=(last['close']-local_level)/atr,
        close_position=(last['close']-last['low'])/(last['high']-last['low']) if last['high']>last['low'] else .5,
        recent_volume_ratio=mean(b['volume'] for b in bs[-3:])/base,
        last_volume_ratio=last['volume']/median(b['volume'] for b in bs[-21:-1]))


def attach(model,source,histories,calendar,previous=None,frames=None,now=None,historical=False):
    """Derive the same ranking for UI and export; historical replay cannot create first-seen events."""
    import stock_selection as S
    previous=previous or {};now=now or datetime.now();rows=S.unique_rows(source);day=model['daily_at']
    historical=bool(historical or source.get('_historical_replay'))
    daily={}
    for code,item in model['items'].items():
        if item.get('score') is not None and (value:=daily_inputs(histories.get(code,[]),day)):daily[code]=value
    coverage=len(daily)/max(model.get('pool_count',len(model['items'])),1)
    market_ok=coverage>=RULES['min_market_coverage']
    daily_refs={k:median(x[k] for x in daily.values()) for k in ('return1','return3','prior3')} if market_ok else {}
    live={};clocks=[]
    if not historical:
        for code,d in daily.items():
            item=model['items'][code];q=rows.get(code,{})
            state=item.get('intraday') or {};at=date_time(state.get('at'));factor=state.get('basis_scale')
            if not state.get('available') or not at or str(at.date())!=model['day'] or not number(factor) or factor<=0:continue
            price=q.get('price')
            if not number(price) or price<=0:continue
            prior=[b for b in d['bars'] if b['date']<model['day']]
            if len(prior)<7:continue
            native=price/factor
            live[code]=dict(at=at,price=price,factor=factor,native=native,
                return1=state.get('return_pct'),return3=100*(native/prior[-3]['close']-1),
                prior3=100*(prior[-3]['close']/prior[-6]['close']-1),
                local_level=max(b['high'] for b in prior[-5:]),support=min(b['low'] for b in prior[-5:]))
            clocks.append(at)
    clock=sorted(clocks)[len(clocks)//2] if clocks else None
    aligned={c:v for c,v in live.items() if number(v['return1']) and abs((v['at']-clock).total_seconds())<=RULES['clock_tolerance_seconds']} if clock else {}
    live_coverage=len(aligned)/max(model.get('pool_count',1),1)
    live_ok=live_coverage>=RULES['min_market_coverage']
    live_refs={k:median(x[k] for x in aligned.values()) for k in ('return1','return3','prior3')} if live_ok else {}
    peer_groups={}
    for c,v in aligned.items():
        group=model['items'][c].get('board',{}).get('industry')
        if group:peer_groups.setdefault(group,[]).append((c,v['return1']))
    for code,item in model['items'].items():
        d=daily.get(code);state=item.get('intraday') or {};q=rows.get(code,{})
        old=((previous.get('items') or {}).get(code) or {}).get('turning_event') or {}
        out=dict(available=False,active=False,stage='待核验',metrics={},order=[0,0,-1e9,-1e9,-1e9],
            first_seen_at=None,first_seen_price=None,since_first_pct=None,distance_atr=None,reasons=[],risks=[])
        item['turning']=out;item['startup_observation']=False
        if not d or not market_ok:
            out['reasons']=['连续可比日线、量能或市场覆盖不足，暂停转强排序'];continue
        ex1=d['return1']-daily_refs['return1'];ex3=d['return3']-daily_refs['return3']
        improvement=ex3-(d['prior3']-daily_refs['prior3'])
        x=dict(return1=d['return1'],return3=d['return3'],excess1=ex1,excess3=ex3,improvement3=improvement,
            improvement_atr=improvement/(100*d['atr']/d['close']),local_break_atr=d['local_break_atr'],
            recent_volume_ratio=d['recent_volume_ratio'],close_position=d['close_position'],
            board_excess_pct=None,board_positive_share=None,same_time_volume_ratio=state.get('volume_ratio_same_time'),
            daily_at=day,evidence_mode='完成日',live_confirmed=False,live_benchmark_coverage=round(live_coverage,4),market_clock=str(clock) if clock else None)
        # Current data changes recent-return evidence; it never rewrites the completed score.
        l=aligned.get(code) if live_ok else None
        if l:
            x.update(evidence_mode='同刻盘中',return1=l['return1'],return3=l['return3'],excess1=l['return1']-live_refs['return1'],excess3=l['return3']-live_refs['return3'])
            x['improvement3']=x['excess3']-(l['prior3']-live_refs['prior3'])
            x['improvement_atr']=x['improvement3']/(100*d['atr']/l['native'])
            board=item.get('board') or {};peers=[v for c,v in peer_groups.get(board.get('industry'),[]) if c!=code]
            if len(peers)>=RULES['min_peers'] and len(peers)/max(board.get('expected') or 1,1)>=RULES['min_market_coverage']:
                x.update(board_excess_pct=l['return1']-median(peers),board_positive_share=100*mean(v>0 for v in peers))
        volume_ok=d['recent_volume_ratio']>=RULES['recent_volume_min'] or d['last_volume_ratio']>=RULES['day_volume_min']
        direction_ok=d['return3']>=RULES['advance3_min'] and ex3>=RULES['excess3_min'] and d['close_position']>=RULES['close_position_min']
        local=bool(direction_ok and volume_ok and d['local_break_atr']>=RULES['local_buffer_atr'])
        accelerating=bool(direction_ok and volume_ok and improvement>=RULES['improvement3_min'])
        qualified_liquidity=item.get('evidence',{}).get('median_amount')
        liquid=number(qualified_liquidity) and qualified_liquidity>=S.R['amount_min']
        own=live.get(code)
        safe=bool(historical or state.get('available') and own) and state.get('state') not in ('结构失守','转弱')
        current_native=own['native'] if own else d['close'];support=own['support'] if own else d['support']
        safe=safe and current_native>=support
        live_start=False;hold=None
        if l and model['daily_at']<model['day']:
            level=l['local_level']+RULES['local_buffer_atr']*d['atr']
            x['local_break_atr']=(l['native']-l['local_level'])/d['atr']
            pos=(q['price']-q['low'])/(q['high']-q['low']) if q.get('high',0)>q.get('low',0) else .5
            hold=held_local(code,frames,l['at'],l['price'],level*l['factor'])
            ratio=x['same_time_volume_ratio'];confirmed=bool(number(ratio) and ratio>=RULES['same_clock_volume_min'] or hold['confirmed'])
            x.update(live_confirmed=confirmed,live_hold=hold,current_close_position=pos)
            live_start=bool(l['native']>=level and x['return1']>=RULES['live_return_min'] and x['excess1']>=RULES['live_excess_min']
                and (state.get('open_return_pct') or 0)>=0 and pos>=RULES['close_position_min'] and confirmed)
            if l['native']>=level and not confirmed:out['reasons'].append('局部价格突破，等待同时间量能或连续真实采样确认')
        current_turning=not l or not RULES['current_positive_required'] or x['return1']>0 and x['excess1']>0
        active=bool(liquid and safe and current_turning and (local or accelerating or live_start or item.get('observation_only')))
        stage='盘中局部启动' if live_start else '局部启动' if local else '修复转强' if item.get('observation_only') else '趋势加速' if accelerating else '持续强势' if item.get('eligible') else '待观察'
        distance=(current_native-own['local_level'])/d['atr'] if own else x['local_break_atr'];near=abs(distance)<=RULES['near_breakout_atr']
        out.update(available=bool(liquid and safe),active=active,stage=stage if safe and liquid else '待核验',metrics=x,distance_atr=distance,
            order=[int(active),int(near),round(x['improvement_atr'],6),round(x['excess3'],6),round(x['excess1'],6)])
        if active:out['reasons'].append(stage+'观察；按超额改善、位置与近期超额排序')
        if not near:out['risks'].append('距离局部突破位超过1.5 ATR，位置偏远')
        if l and not current_turning:
            out['stage']='持续强势' if item.get('eligible') else '待观察'
            out['reasons'].append('当前未同时上涨并跑赢同刻市场，暂停活跃转强标识')
        if state.get('state')=='分歧':out['risks'].append('当前存在盘中分歧')
        # Persist only actual observed events. No historical reconstruction of detection times.
        if not historical:
            if old.get('version')!=VERSION:old={}
            basis=next((b for b in d['bars'] if b['date']==old.get('basis_date')),None)
            gap=sum(old.get('last_active_day','9999')<t<=model['day'] for t in calendar)
            if old and (not basis or gap>RULES['episode_gap_days'] or not safe):old={}
            event=dict(old)
            if active and not event:
                native=l['native'] if l else d['close'];factor=l['factor'] if l else state.get('basis_scale') or 1.
                event=dict(version=VERSION,first_seen_at=str(now),first_seen_price=q.get('price'),first_native=native,
                    basis_date=d['bars'][-1]['date'],basis_close=d['close'],last_active_day=model['day'],source_at=state.get('at'))
                event['id']=hashlib.sha256((code+'|'+str(state.get('at'))+'|'+VERSION).encode()).hexdigest()[:24]
                model.setdefault('_turning_new_events',[]).append(dict(event,code=code,name=item.get('name'),
                    version=VERSION,stage=stage,daily_at=day,eligible=bool(item.get('eligible')),metrics=dict(x)))
            if active:event['last_active_day']=model['day']
            if event:
                reference=next((b for b in d['bars'] if b['date']==event['basis_date']),None)
                initial=event['first_native']*(reference['close']/event['basis_close']) if reference else None
                out.update(first_seen_at=event['first_seen_at'],first_seen_price=event['first_seen_price'],
                    since_first_pct=100*(current_native/initial-1) if initial else None)
            if model.get('_state') is not None:
                model['_state']['items'].setdefault(code,{})['turning_event']=event
        item['startup_observation']=bool(active and not item.get('eligible') and not item.get('observation_only'))
    model['turning_order']=sorted(model['items'],key=lambda c:(tuple(-v for v in model['items'][c]['turning']['order']),c))
    model.setdefault('counts',{})['startup']=sum(x['startup_observation'] for x in model['items'].values())
    model['turning_rules']=dict(version=VERSION,parameters=RULES,default_order='活跃观察、突破距离、ATR标准化超额改善、3日超额、1日超额',effectiveness_validated=False,
        note='观察不升级确认强势；历史回放不回填首次记录；当前收益使用同时间可比股票池中位数')
    return model


def persist_events(model):
    """Keep actual observations even when an intraday false start later disappears."""
    import config
    events=model.pop('_turning_new_events',[])
    grouped={}
    for event in events:grouped.setdefault(event['first_seen_at'][:10],[]).append(event)
    for day,rows in grouped.items():
        folder=config.CACHE_DIR/'stock_selection_v3'/'turning_events';folder.mkdir(parents=True,exist_ok=True)
        path=folder/(day+'.jsonl')
        known={json.loads(line)['id'] for line in path.read_text(encoding='utf8').splitlines()} if path.exists() else set()
        with path.open('a',encoding='utf8') as stream:
            for event in rows:
                if event['id'] not in known:
                    stream.write(json.dumps(event,ensure_ascii=False,separators=(',',':'))+'\n');known.add(event['id'])
