"""Preopen view: replay completed local evidence, preserving the source clocks."""
import copy,gzip,json
from contextlib import closing
from datetime import datetime
import config

def usable(previous):
    import market_strength as M,ma_trend as T,emotion_relay as E
    day=(previous.get('strength_model') or {}).get('asof')
    return bool(day and (previous.get('market_strength') or {}).get('close_verification',{}).get('date')==day
        and (previous.get('emotion_relay') or {}).get('mode')=='正式收盘'
        and all((previous.get(name) or {}).get('implementation_hash')==mod.IMPLEMENTATION_HASH
            for name,mod in [('market_strength',M),('ma_trend',T),('emotion_relay',E)]))


def latest_acquisition(day,before):
    path=config.CACHE_DIR/'intraday_history'/'acquisitions'/(day+'.jsonl.gz')
    selected=None
    try:
        with gzip.open(path,'rt',encoding='utf-8') as stream:
            for line in stream:
                try:
                    r=json.loads(line);at=datetime.fromisoformat(r['captured_at'])
                    if at.date().isoformat()!=day or at>before or r.get('session')!='已收盘':continue
                    if selected is None or r['captured_at']>selected['captured_at']:selected=r
                except (ValueError,KeyError,TypeError):continue
    except FileNotFoundError:pass
    return selected


def build(previous,now,mode='quick'):
    import datafeed as df,strength,intraday,market_strength as M,ma_trend as T,emotion_relay as E,relay_history as H
    if not previous.get('stocks') and not previous.get('coverage_catalog'):
        from scoring import DataNotReady
        raise DataNotReady('盘前暂无上一完成日结果，等待交易数据')
    snap=copy.deepcopy(previous)
    day=(snap.get('strength_model') or {}).get('asof') or str(snap.get('quote_capture_at') or '')[:10]
    migration=any((snap.get(name) or {}).get('implementation_hash')!=mod.IMPLEMENTATION_HASH
        for name,mod in [('market_strength',M),('ma_trend',T),('emotion_relay',E)])
    if migration:
        rows=snap.get('stocks',[])+snap.get('coverage_catalog',[]);pool={r['code']:r for r in rows}
        record=latest_acquisition(day,now)
        capture=record['captured_at'] if record else snap.get('quote_capture_at')
        at=datetime.fromisoformat(capture)
        if record:
            q={v[0]:dict(zip(record['fields'][1:],v[1:])) for v in record['rows'] if v[0] in pool}
        else:q=copy.deepcopy((snap.get('market_strength_close_input') or {}).get('quotes') or {})
        if not q:
            from scoring import DataNotReady
            raise DataNotReady('盘前模型更新所需的上一完成日原始记录未覆盖；保留历史页面')
        with closing(df.db()) as con:h={c:df.load_kline(con,'kline','code',c,limit=160) for c in pool}
        calendar=strength.trading_calendar(h)
        snap.update(session='已收盘',quote_capture_at=capture)
        snap['data_availability']={c:v['data_availability'] for c,v in q.items() if v.get('data_availability')}
        for r in rows:r.update(copy.deepcopy(q.get(r['code']) or {}))
        print('[PREOPEN] 用'+day+'完成日及原始收市记录更新模型，保留原报价时刻',flush=True)
        M.attach(snap,q,pool,h,calendar,now=at);M.validate(snap)
        T.attach(snap,q,pool,h,calendar,now=at,fetch_minutes=False,minute_data={});T.validate(snap)
        dates=[d for d in calendar if d<day];replay=dates[-(config.EMOTION_RELAY['history_days']+config.EMOTION_RELAY['warmup_days']):]
        evidence=H.load(pool,replay,dates,day,fetch=False)
        E.attach(snap,q,pool,h,calendar,now=at,evidence=evidence,fetch=False,persist=False);E.validate(snap)
    snap.update(session='盘前',mode='preopen_reference',scan_started_at=str(now),scan_completed_at=str(now),generated_at=str(now))
    snap.pop('scan_performance',None)
    snap.pop('kline_acquisition',None)
    snap['reference_view']=dict(kind='preopen',asof=day,checked_at=str(now),model_replayed=migration,
        source_quote_at=(snap.get('market_strength') or {}).get('close_verification',{}).get('source_at') or snap.get('quote_capture_at'),
        label='盘前 · 沿用上一完成日结果；9:15后接入当日竞价')
    return snap
