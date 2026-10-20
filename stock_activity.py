"""个股强度页专用投影。只读共享输入；不写行业、雷达、均线或接力结果。"""
import copy
import gzip
import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

import config
import intraday
import intraday_path
import market_strength
import observed_history


from stock_activity_rules import VERSION, SCORE_VERSION, RULES
import sqlite3
import threading
import time
from contextlib import contextmanager
STATE_PATH = config.CACHE_DIR / 'stock_activity_v21' / 'state.json'
_LOCK = threading.RLock()
_INPUT_CACHE = {}
IMPLEMENTATION_HASH = hashlib.sha256(Path(__file__).read_bytes() +
    Path(__file__).with_name('stock_activity_engine.py').read_bytes() +
    Path(__file__).with_name('stock_activity_close.py').read_bytes() +
    Path(__file__).with_name('stock_activity_rules.py').read_bytes()).hexdigest()[:16]

def number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def stamp(x):
    try:
        return datetime.fromisoformat(str(x))
    except (ValueError, TypeError):
        return None


def scale(x, k):
    if not number(x):
        return None
    x = max(x, 0.)
    return 100 * x / (x + k)


def industry_groups(snap, codes, previous=None):
    """优先股票明确的细行业；其次选择确认成员中最细的行业，不按表现挑行业。"""
    boards = {b['id']: b for b in snap.get('board_catalog', []) if b.get('type') == 'industry'}
    memberships = {c: [] for c in codes}
    for identity, b in boards.items():
        members = set(b.get('member_codes', [])) & set(codes)
        for c in members:
            memberships[c].append((len(members), identity, b['name']))
    rows = {r['code']: r for r in snap.get('stocks', []) + snap.get('coverage_catalog', [])}
    assignments = {}
    for c in codes:
        row = rows.get(c, {})
        names = row.get('industry') or []
        if isinstance(names, str):
            names = [names]
        preferred = row.get('industry_detail') or (names[0] if names else None)
        choices = sorted(memberships[c])
        match = next((x for x in choices if x[2] == preferred), None)
        if match or choices:
            assignments[c] = (match or choices[0])[1]
    # 同日先锁定完整基准成员，避免盘中成员变化产生伪领先变化。
    if previous and previous.get('day') == str(snap.get('quote_capture_at'))[:10]:
        assignments = {c: i for c, i in previous.get('assignments', assignments).items() if c in codes}
    groups = {}
    for c, identity in assignments.items():
        groups.setdefault(identity, []).append(c)
    return assignments, groups, {i: boards[i]['name'] for i in groups if i in boards}


def benchmark(values, code, assignments, groups, pool_count):
    identity = assignments.get(code)
    peers = [c for c in groups.get(identity, []) if c != code]
    available = [values[c] for c in peers if number(values.get(c))]
    market = [v for v in values.values() if number(v)]
    if (len(available) < RULES['min_peers'] or not peers
            or len(available) / len(peers) < RULES['coverage_min']
            or len(market) / max(pool_count, 1) < RULES['coverage_min']):
        return None
    return dict(market=median(market), industry=median(available),
                peer_valid=len(available), peer_expected=len(peers))


class Reference:
    """同一截面的基准只排序一次，逐股仍排除自身。"""
    def __init__(self, values, assignments, groups, count):
        self.values, self.assignments, self.groups = values, assignments, groups
        valid = [v for v in values.values() if number(v)]
        self.market = median(valid) if len(valid)/max(count,1) >= RULES['coverage_min'] else None
        self.industries = {i:sorted(values[c] for c in cs if number(values.get(c))) for i,cs in groups.items()}

    def get(self, code):
        from bisect import bisect_left
        identity = self.assignments.get(code)
        expected = len(self.groups.get(identity, []))-1
        peers = list(self.industries.get(identity, []))
        if number(self.values.get(code)) and peers:
            peers.pop(bisect_left(peers, self.values[code]))
        if self.market is None or expected <= 0 or len(peers) < RULES['min_peers'] or len(peers)/expected < RULES['coverage_min']:
            return None
        return dict(market=self.market, industry=median(peers), peer_valid=len(peers), peer_expected=expected)


def raw_valid(q, now, session, center=None, formal=False):
    valid, at, reason = market_strength.quote_valid(q, now, session, center, formal)
    if not valid:
        return False, at, reason
    if not number(q.get('last_close')) or q['last_close'] <= 0:
        return False, at, '昨收缺失'
    if not number(q.get('volume_shou')) or q['volume_shou'] <= 0:
        return False, at, '本轮没有可核验成交'
    if (not all(number(q.get(k)) and q[k] > 0 for k in ('open','high','low'))
            or q['high'] < max(q['price'],q['open']) or q['low'] > min(q['price'],q['open'])):
        return False, at, 'OHLC价格关系无效'
    return True, at, None



def valid_frame(quotes, at, session, formal=False):
    times = sorted(t for q in quotes.values() if (t:=stamp(q.get('quote_at'))) and t.date()==at.date())
    center=times[len(times)//2] if times else None
    uncertainty=max([0.]+[(t-at).total_seconds() for t in times if 0<(t-at).total_seconds()<=RULES['quote_clock_error_max']])
    result={}
    for c,q in quotes.items():
        valid,t,_=raw_valid(q,at,session,center,formal)
        if not valid or (t-at).total_seconds()>RULES['quote_clock_error_max']:
            continue
        # 集合竞价与午休报价不能触发新的连续交易事件。
        minute=t.hour*60+t.minute
        if not (570<=minute<=690 or 780<=minute<=900):
            continue
        amount,volume=q.get('amount_wan'),q.get('volume_shou')
        vwap=100*amount/volume if number(amount) and number(volume) and volume>0 else None
        if vwap is not None and not q['low']-.011<=vwap<=q['high']+.011:
            vwap=None
        result[c]=dict(at=str(t),price=q['price'],last_close=q['last_close'],
                       change=100*(q['price']/q['last_close']-1),amount_wan=amount,
                       volume_shou=volume,vwap=vwap,received_at=q.get('received_at') or str(at),
                       clock_uncertainty_seconds=uncertainty,source_clock_offset_seconds=max(0.,(t-at).total_seconds()))
    return result


def archive_frames(now,codes,directory=None,anchor=None,formal=False):
    folders=([Path(directory)] if directory is not None else
             [intraday.HISTORY_DIR/'acquisitions',config.CACHE_DIR/'stock_activity_samples'/'acquisitions'])
    result=[]
    for folder in folders:
        path=folder/(str(now.date())+'.jsonl.gz')
        if not path.exists():continue
        try:
            with gzip.open(path,'rt',encoding='utf8') as stream:
                for line in stream:
                    record=json.loads(line);at=stamp(record.get('captured_at'))
                    if not at or at>now or at.date()!=now.date():continue
                    fields=record['fields']
                    quotes={r[0]:dict(zip(fields[1:],r[1:])) for r in record['rows'] if r[0] in codes}
                    frame=valid_frame(quotes,at,record.get('session','连续竞价'),formal)
                    if len(frame)>=len(codes)*RULES['coverage_min']:
                        result.append((str(at),frame))
        except (OSError,EOFError,ValueError):
            # 写入中的尾部不可用于确认；此前完整记录仍可回放。
            continue
    return sorted(result,key=lambda f:f[0])


def live_view(snap, now=None, record=None):
    """本页专用真实报价；收盘后可恢复有来源的尾盘采样，不改共享行。"""
    now=now or datetime.now()
    if record is None:
        path=config.CACHE_DIR/'stock_activity_samples'/'latest.json'
        if not path.exists():return snap
        record=json.loads(path.read_text(encoding='utf8'))
    at=stamp(record.get('captured_at'));original=stamp(snap.get('quote_capture_at'))
    formal=bool(at and original and at.date()==original.date() and snap.get('session')=='已收盘' and snap.get('close_daily_verified_at'))
    if not at or not original or at>now or at.date()!=now.date() or original>at and original.date()!=at.date():return snap
    if not formal and ((now-at).total_seconds()>RULES['quote_age_max']
                       or at<original and (original-at).total_seconds()>15):return snap
    rows={r['code']:r for r in snap.get('stocks',[])+snap.get('coverage_catalog',[])}
    quotes={c:q for c,q in (record.get('quotes') or {}).items() if c in rows}
    # The shared snapshot may have been generated seconds after a verified
    # independent acquisition but may lack its raw-price provenance fields.
    # Recover only genuinely comparable same-day per-stock quotes; never
    # overwrite a newer, fully sourced snapshot with an older quote.
    if not formal and at<=original:
        def near_sourced(c,q):
            row=rows[c]
            source,existing=stamp(q.get('quote_at')),stamp(row.get('quote_at'))
            return bool(source and existing and source.date()==original.date()
                and -10 <= (source-existing).total_seconds() <= 15
                and q.get('price_basis')=='raw'
                and q.get('last_close_semantics')=='previous_trade_day_raw_close'
                and q.get('price_basis_source')
                and number(q.get('last_close')) and number(row.get('last_close'))
                and abs(q['last_close']-row['last_close'])<=.005
                and (not row.get('last_close_semantics') or
                     row.get('last_close_semantics')==q.get('last_close_semantics'))
                and (not row.get('price_basis') or row.get('price_basis')==q.get('price_basis'))
                and (not row.get('price_basis_source') or row.get('price_basis_source')==q.get('price_basis_source'))
                and (not row.get('price_basis_source') or source>=existing))
        quotes={c:q for c,q in quotes.items() if near_sourced(c,q)}
        if len(quotes)<len(rows)*RULES['coverage_min']:return snap
    fallback=formal and at<=original
    if fallback:
        # 不是凭小价差猜复权：采样自身有明确来源、交易日、昨收语义，且是收盘边界真实报价。
        quotes={c:q for c,q in quotes.items() if (source:=stamp(q.get('quote_at'))) and source.date()==at.date()
                and source.hour==15 and source.minute<=2
                and number(q.get('price')) and number(rows[c].get('price')) and abs(q['price']-rows[c]['price'])<=.005
                and number(q.get('last_close')) and number(rows[c].get('last_close')) and abs(q['last_close']-rows[c]['last_close'])<=.005}
    quotes={c:dict(q,received_at=str(at)) for c,q in quotes.items()}
    captured=max(original,at) if fallback or at<=original else at
    session=snap['session'] if formal else record['session']
    if len(valid_frame(quotes,captured,session,formal))<len(rows)*RULES['coverage_min']:return snap
    result=dict(snap,quote_capture_at=str(captured),session=session)
    if at.date()!=original.date():result.pop('close_daily_verified_at',None)
    if fallback:result['stock_activity_quote_mode']='收盘采样参考'
    elif at<=original:
        result['stock_activity_quote_mode']='逐股校验独立采样'
    for group in ('stocks','coverage_catalog'):
        result[group]=[dict(r,**quotes[r['code']]) if r['code'] in quotes else dict(r,quote_at=None)
                       for r in snap.get(group,[])]
    return result


def build(snap,histories,calendar,frames=None,previous=None,detected_at=None):
    import stock_activity_engine
    model=stock_activity_engine.build(snap,histories,calendar,frames,previous,detected_at)
    model['implementation_hash']=IMPLEMENTATION_HASH
    return model


def state_path():
    return config.CACHE_DIR/'stock_activity_v21'/'state.json'


def load_state():
    try:return json.loads(state_path().read_text(encoding='utf8'))
    except (OSError,ValueError):return {}


def prepare(snap,live=False,previous=None,frames=None):
    import datafeed
    if live:snap=live_view(snap)
    codes={r['code'] for r in snap.get('stocks',[])+snap.get('coverage_catalog',[])}
    con=sqlite3.connect('file:'+config.KLINE_DB.as_posix()+'?mode=ro',uri=True)
    try:histories={c:datafeed.load_kline(con,'kline','code',c,limit=90) for c in codes}
    finally:con.close()
    dates={}
    for bars in histories.values():
        for b in bars:dates[b['date']]=dates.get(b['date'],0)+1
    calendar=sorted(d for d,n in dates.items() if n>=len(codes)*.5)
    return build(snap,histories,calendar,frames=frames,previous=load_state() if previous is None else previous,
                 detected_at=str(datetime.now()))


def save_state(state):
    if not state or state.get('error') or not state.get('processed_at'):
        return
    config.atomic_write_text(state_path(),json.dumps(state,ensure_ascii=False,separators=(',',':')))


@contextmanager
def projection_owner():
    """本页独占锁；与全站pipeline锁无关，防止手动发布与采样者覆盖状态。"""
    folder=state_path().parent
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'projection.lock').open('a+b') as stream:
        if stream.seek(0,2)==0:stream.write(b'0');stream.flush()
        deadline=time.monotonic()+30
        acquired=False
        while not acquired:
            try:
                stream.seek(0)
                if __import__('os').name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                acquired=True
            except OSError:
                if time.monotonic()>=deadline:raise TimeoutError('本页状态发布锁忙')
                time.sleep(.1)
        try:yield
        finally:
            stream.seek(0)
            if __import__('os').name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def snapshot_input():
    stat=config.SNAPSHOT_JSON.stat()
    key=(stat.st_mtime_ns,stat.st_size)
    if _INPUT_CACHE.get('key')!=key:
        full=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf8'))
        keys=('code','name','industry','industry_detail','board_type','price','open','high','low','last_close',
              'change_pct','quote_at','ts','intraday_quote_at','amount_wan','volume_shou','price_basis','price_basis_source',
              'last_close_semantics','last_close_precision_digits','limit_up','limit_down','data_availability')
        snap={k:full.get(k) for k in ('quote_capture_at','session','close_daily_verified_at')}
        snap['board_catalog']=[dict(b) for b in full.get('board_catalog',[]) if b.get('type')=='industry']
        for group in ('stocks','coverage_catalog'):
            snap[group]=[{k:r[k] for k in keys if k in r} for r in full.get(group,[])]
        _INPUT_CACHE.update(key=key,snap=snap)
    return _INPUT_CACHE['snap']


def refresh_projection(snap=None):
    """独立采样者/全站发布共用本页锁，不占用全站扫描锁。"""
    with _LOCK,projection_owner():
        import stock_activity_close as C
        now=datetime.now();day=str(now.date());folder=state_path().parent
        previous=load_state()
        final_path=folder/('close-'+day+'.json')
        if C.closed(now) and final_path.exists():
            final=json.loads(final_path.read_text(encoding='utf8'))
            if (final.get('version')==VERSION and final.get('implementation_hash')==IMPLEMENTATION_HASH
                    and final.get('close_finalized') and final.get('day')==day):
                latest=folder/'latest.json'
                try:published=json.loads(latest.read_text(encoding='utf8'))
                except (OSError,ValueError):published={}
                if published.get('result_version')!=final.get('result_version'):
                    config.atomic_write_text(latest,json.dumps(final,ensure_ascii=False,separators=(',',':')))
                return final
        source=snapshot_input() if snap is None else snap
        checkpoint=folder/('open-'+day+'.json')
        if not checkpoint.exists():
            config.atomic_write_text(checkpoint,json.dumps(C.day_seed(previous,day),ensure_ascii=False,separators=(',',':')))
        if C.closed(now):
            try:terminal,frames,metadata=C.closing_input(source,now)
            except C.CloseNotReady:
                if (folder/'latest.json').exists():
                    return json.loads((folder/'latest.json').read_text(encoding='utf8'))
                raise
            seed=json.loads(checkpoint.read_text(encoding='utf8'))
            model=C.finalize(prepare(terminal,previous=seed,frames=frames),metadata,now)
        else:
            model=prepare(source,live=True,previous=previous)
        state=model.pop('_state')
        if not model.get('close_finalized') and previous.get('version')==VERSION and previous.get('processed_at') and state.get('processed_at') and state['processed_at']<previous['processed_at']:
            return json.loads((state_path().parent/'latest.json').read_text(encoding='utf8'))
        public=json.dumps(model,ensure_ascii=False,separators=(',',':'))
        model['result_version']=hashlib.sha256(public.encode()).hexdigest()[:24]
        folder=state_path().parent
        folder.mkdir(parents=True,exist_ok=True)
        # 只留状态变化与确认证据日志；稳定采样不重复记录同一事件。
        entries=[]
        for c,item in state['items'].items():
            old=previous.get('items',{}).get(c,{})
            seen={json.dumps(v,sort_keys=True,ensure_ascii=False) for v in old.get('journal',[])}
            for entry in item.get('journal',[]):
                if json.dumps(entry,sort_keys=True,ensure_ascii=False) not in seen:
                    entries.append(dict(code=c,rule_version=VERSION,score_version=SCORE_VERSION,
                                        result_version=model['result_version'],decision=entry,
                                        event=item.get('events',[])[-1] if item.get('events') else None,
                                        identity=item.get('identity')))
            old_marks={e['id']:e.get('evidence') for e in old.get('events',[])}
            for event in item.get('events',[]):
                if event.get('evidence')!=old_marks.get(event['id']):
                    entries.append(dict(code=c,rule_version=VERSION,result_version=model['result_version'],event=event))
        if entries:
            with (folder/('events-'+model['day']+'.jsonl')).open('a',encoding='utf8') as stream:
                for entry in entries:stream.write(json.dumps(entry,ensure_ascii=False,separators=(',',':'))+'\n')
        save_state(state)
        config.atomic_write_text(folder/'latest.json',json.dumps(model,ensure_ascii=False,separators=(',',':')))
        if model.get('close_finalized'):
            config.atomic_write_text(final_path,json.dumps(model,ensure_ascii=False,separators=(',',':')))
        return model


def prepare_page(snap,live=False):
    try:
        return refresh_projection(snap) if live else prepare(snap)
    except Exception as exc:
        import logging
        logging.exception('个股V2.1计算失败，其他页面继续发布')
        codes=sorted({r['code'] for r in snap.get('stocks',[])+snap.get('coverage_catalog',[])})
        reason='页面计算待核验：'+type(exc).__name__+'：'+str(exc)
        try:
            from stock_activity_engine import restore_previous
            recovered=restore_previous(copy.deepcopy(load_state()))
            saved=recovered.get('items',{}) if recovered.get('version')==VERSION else {}
        except Exception:
            saved={}
        items={}
        for c in codes:
            old=saved.get(c,{})
            event=copy.deepcopy(old.get('events',[])[-1]) if old.get('events') else None
            items[c]=dict(code=c,score=None,rank=None,factors={k:None for k in RULES['enabled_factors']+['R']},
                eligible=False,list_name='pending',state='pending',stage='数据待核验',current_state=old.get('current_state'),
                role=old.get('role','时序不明'),confirmation='判断暂停，保留已有证据',confidence=0,reasons=[reason],gates=[],
                source_at=old.get('last_point',{}).get('at'),identity=copy.deepcopy(old.get('identity',{})),event=event,
                events=copy.deepcopy(old.get('events',[])),industry=None,trading_constraints=[],
                data_quality=dict(available=False,status='unavailable',last_valid_sample_at=old.get('last_point',{}).get('at')),
                evidence=dict(confirmations=copy.deepcopy(event.get('evidence',{})) if event else {}))
        return dict(version=VERSION,score_version=SCORE_VERSION,implementation_hash=IMPLEMENTATION_HASH,error=reason,
                    source_at=snap.get('quote_capture_at'),captured_at=snap.get('quote_capture_at'),
                    mode='数据待核验',rules=copy.deepcopy(RULES),assignments={},order=codes,pool_count=len(codes),
                    counts=dict(core=0,startup=0,reference=0,watch=0,pending=len(codes)),
                    items=items)
