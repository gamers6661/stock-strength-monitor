"""只读本地行情，重建日内证据并固定15:00收盘结果。"""
import copy
import gzip
import json
from pathlib import Path

import config
import intraday
import intraday_path
from stock_activity_rules import RULES

VERSION='收盘缓存定稿20261019.2'


class CloseNotReady(ValueError):
    pass


def closed(now):
    return now.weekday()<5 and (now.hour,now.minute)>=(15,0)


def day_seed(previous,day):
    """检查点只含当天开始以前的身份与事件，不将收盘知识提前放入早盘。"""
    seed=copy.deepcopy(previous or {})
    for key in ('processed_at','knowledge_at','source_at'):
        seed.pop(key,None)
    for state in seed.get('items',{}).values():
        state['events']=[e for e in state.get('events',[]) if e['observed_at'][:10]<day]
        identity=state.get('identity',{})
        if str(identity.get('first_observed_at') or identity.get('created_at') or day)[:10]>=day:
            state['identity']=dict(status='none')
        for key in ('last_point','movement','last_window','evaluated_at','attention_ratio','data_gap','recovery_required'):
            state.pop(key,None)
        state['points']=[]
        state['journal']=[j for j in state.get('journal',[]) if str(j.get('at') or day)[:10]<day]
        if not state['events']:
            state.update(role='时序不明',current_state=None)
    seed['day']=day
    return seed


def closing_input(snap,now):
    import stock_activity as A
    day=str(now.date());close_at=day+' 15:00:00'
    rows={r['code']:r for r in snap.get('stocks',[])+snap.get('coverage_catalog',[])}
    quotes={};sources=[];latest=None
    verified=str(snap.get('close_daily_verified_at') or '').startswith(day)
    for folder in (intraday.HISTORY_DIR/'acquisitions',config.CACHE_DIR/'stock_activity_samples/acquisitions'):
        path=folder/(day+'.jsonl.gz');count=0
        if path.exists():
            try:
                with gzip.open(path,'rt',encoding='utf8') as f:
                    for line in f:
                        r=json.loads(line);capture=A.stamp(r.get('captured_at'))
                        if not capture or capture>now or str(capture.date())!=day:continue
                        count+=1
                        if str(capture)<close_at:continue
                        for values in r.get('rows',[]):
                            c=values[0]
                            if c not in rows:continue
                            q=dict(zip(r['fields'][1:],values[1:]));at=A.stamp(q.get('quote_at'))
                            if not at or str(at.date())!=day or at.hour!=15 or at.minute!=0 or (at-capture).total_seconds()>RULES['quote_clock_error_max']:continue
                            if q.get('price_basis')!='raw' or not q.get('price_basis_source') or not q.get('last_close_semantics'):continue
                            if not A.raw_valid(q,capture,'已收盘',formal=True)[0]:continue
                            if verified and (not A.number(rows[c].get('price')) or abs(q['price']-rows[c]['price'])>.005
                                             or not A.number(rows[c].get('last_close')) or abs(q['last_close']-rows[c]['last_close'])>.005):continue
                            if c not in quotes or str(capture)>quotes[c]['received_at']:
                                quotes[c]=dict(q,received_at=str(capture))
                                latest=max(latest or capture,capture)
            except (OSError,EOFError,ValueError):
                pass  # 压缩文件写入中的尾部不参与；前面的完整记录仍然有效。
        sources.append(dict(path=str(path),records=count))
    if not latest or len(quotes)<len(rows)*RULES['coverage_min']:
        raise CloseNotReady('本地15:00最终报价覆盖不足，保留最后结果，等待收盘边界缓存')
    result=dict(snap,quote_capture_at=str(latest),session='已收盘',stock_activity_quote_mode='收盘定稿')
    for group in ('stocks','coverage_catalog'):
        result[group]=[dict(r,**quotes[r['code']]) if r['code'] in quotes else dict(r,quote_at=None)
                       for r in snap.get(group,[])]
    frames=A.archive_frames(latest,set(rows),formal=True)
    metadata=dict(version=VERSION,market_close_at=close_at,terminal_captured_at=str(latest),
        terminal_count=len(quotes),pool_count=len(rows),raw_sources=sources,replay_batches=len(frames),
        source_time_preserved=True,interpolation=False)
    return result,frames,metadata


def add_minute_evidence(model,now):
    """选择性分钟缓存仅补充价格结构，不补造全池时序或统一评分因子。"""
    import stock_activity as A
    day=model['day'];path=config.CACHE_DIR/'trend_monitor_minutes'/(day+'.json')
    try:cache=json.loads(path.read_text(encoding='utf8'))
    except (OSError,ValueError):cache={}
    used=0
    for c,bars in cache.get('stocks',{}).items():
        item=model['items'].get(c)
        fetched=A.stamp(cache.get('fetched_at',{}).get(c))
        if not item or not fetched or fetched>now:continue
        clean=[b for b in bars if str(b.get('at','')).startswith(day) and day+' 09:30'<=b['at'][:16]<=day+' 15:00'
               and b.get('price_basis')=='raw' and all(A.number(b.get(k)) and b[k]>0 for k in ('open','high','low','close'))]
        clean.sort(key=lambda b:b['at'])
        price=item['quote'].get('price')
        if not clean or clean[-1]['at']<day+' 14:59' or not A.number(price) or abs(clean[-1]['close']-price)>.011:continue
        tail=[b for b in clean if b['at'][:16]<=day+' 14:30']
        peak=max(b['high'] for b in clean)
        item['evidence']['close_minute_review']=dict(samples=len(clean),first_at=clean[0]['at'],last_at=clean[-1]['at'],
            fetched_at=str(fetched),source=sorted({b.get('source','缓存分钟线') for b in clean}),
            close_from_observed_high_pct=100*(price/peak-1),
            last_half_hour_return_pct=100*(price/tail[-1]['close']-1) if tail else None,
            continuous=all(intraday_path.gap_seconds(a['at'],b['at']) in (0,60) for a,b in zip(clean,clean[1:])),
            used_in_score=False,used_in_timing=False)
        used+=1
    model['close_review']['minute_cache']=dict(cached=len(cache.get('stocks',{})),verified=used,
        used_in_score=False,used_in_timing=False,reason='选择性覆盖，仅补充核验后的收盘价格结构')


def finalize(model,metadata,now):
    model.update(mode='收盘定稿',close_finalized=True,market_close_at=metadata['market_close_at'],
                 finalized_at=str(now),close_review=metadata)
    for item in model['items'].values():
        q=item['data_quality']
        q['intraday_status']=q['status']
        q['status']='close_replayed' if q.get('available') else 'close_unavailable'
        item['reasons']=[r.replace('连续观察窗口重建中；保留事件与最后确认身份','今日缓存已回放；有效连续证据不足，保留已有身份') for r in item['reasons']]
    add_minute_evidence(model,now)
    return model
