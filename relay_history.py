"""Complete daily relay evidence and dated suspensions, separate from MA bars."""
import json,time,urllib.parse
from concurrent.futures import ThreadPoolExecutor,as_completed,TimeoutError
from datetime import datetime
from decimal import Decimal
import config,datafeed,intraday,market_strength as M,relay_data as D,closing_price


def fetch_reference(codes,begin,asof):
    url='https://q.stock.sohu.com/hisHq?'+urllib.parse.urlencode(dict(code=','.join('cn_'+c for c in codes),start=begin.replace('-',''),end=asof.replace('-',''),stat=1,order='A',period='d'))
    values=json.loads(datafeed.http_get(url,timeout=config.EMOTION_RELAY['request_seconds'],retry=0))
    if not isinstance(values,list):raise ValueError('原价参考返回格式异常')
    result={}
    for value in values:
        code=str(value.get('code','')).removeprefix('cn_')
        if value.get('status')!=0 or code not in codes or code in result:raise ValueError('原价参考代码或状态异常')
        bars=[]
        for r in value.get('hq',[]):
            bar=dict(date=r[0],open=float(r[1]),close=float(r[2]),reference_close=float(Decimal(r[2])-Decimal(r[3])),
                change_pct=float(r[4].removesuffix('%')),low=float(r[5]),high=float(r[6]),volume=float(r[7])*100,
                turnover_pct=float(r[9].removesuffix('%')) if r[9]!='-' else None)
            if not intraday._valid_historical_price_bar(bar) or bar['reference_close']<=0:raise ValueError('原价参考OHLC或前收无效')
            bars.append(bar)
        if len({b['date'] for b in bars})!=len(bars):raise ValueError('原价参考日期重复')
        result[code]=dict(code=code,bars=bars,source='sohu_hisHq_raw',coverage_through=asof,requested_from=begin)
    return result


def fetch_halts(day):
    params=dict(reportName='RPT_CUSTOM_SUSPEND_DATA_INTERFACE',columns='ALL',pageSize=500,pageNumber=1,
        sortColumns='SUSPEND_START_DATE',sortTypes=-1,source='WEB',client='WEB',filter='(MARKET="全部")(DATETIME=\''+day+'\')')
    value=json.loads(datafeed.em_get('https://datacenter-web.eastmoney.com/api/data/v1/get?'+urllib.parse.urlencode(params),timeout=config.EMOTION_RELAY['request_seconds']))
    result=value.get('result') or {};rows=result.get('data')
    if not value.get('success') or not isinstance(rows,list) or len(rows)!=result.get('count'):raise ValueError('停牌表完整性待核验')
    return dict(day=day,source='eastmoney_exchange_suspension_table',rows=rows,fetched_at=str(datetime.now()))


def halt_on(evidence,code,day):
    for r in evidence.get('verified_halts',[]):
        if r['code']==code and r['start']<=day and (not r.get('resume') or day<r['resume']):
            return dict(start=r['start'],end=r.get('resume'),reason=r['reason'],source=r['source'],verified_day=day,known_at=r.get('published_at'))
    record=(evidence.get('halts') or {}).get(day) or {}
    for r in record.get('rows',[]):
        if r.get('SECURITY_CODE')!=code or r.get('SUSPEND_EXPIRE')!='连续停牌':continue
        start=str(r.get('SUSPEND_START_TIME') or '');end=str(r.get('SUSPEND_END_TIME') or '')
        if start and start<=day+' 09:30:00' and (not end or end>=day+' 15:00:00'):
            return dict(start=start,end=end or None,reason=r.get('SUSPEND_REASON'),source=record['source'],verified_day=day)
    assumed=(evidence.get('inferred_halts') or {}).get(code)
    if assumed and assumed.get('day')==day:
        return dict(start=day,end=None,reason=assumed.get('basis'),source='missing_quote_retry_policy',
            verified_day=day,inferred=True,known_at=assumed.get('checked_at'))
    return None


def load(codes,days,calendar,today,fetch=True,verified_halts=None):
    result=D.load(days,fetch=False);result.update(reference={},halts={},verified_halts=verified_halts or []);start=time.monotonic();errors=[]
    asof=days[-1] if days else None
    if not asof:return result
    for c in codes:
        r=D.read(D.root()/'raw'/(c+'.json'))
        if r:result['raw'][c]=r
        r=D.read(D.root()/'reference'/(c+'.json'))
        if r:result['reference'][c]=r
    for day in days+[today]:
        r=D.read(D.root()/'halts'/(day+'.json'))
        if not r and fetch:
            try:r=fetch_halts(day);D.write(D.root()/'halts'/(day+'.json'),r)
            except Exception as e:errors.append(dict(day=day,reason=str(e)))
        if r:result['halts'][day]=r
    # A normal refresh is warm. The one-time history backfill is resumable, with
    # a time budget; missing data never turns into a false non-limit day.
    need=[c for c in codes if not any(b.get('date')==asof for b in result['raw'].get(c,{}).get('bars',[])) and not halt_on(result,c,asof)
        and not (isinstance(codes,dict) and (codes[c].get('trade_status')=='no_trade') and not any(b['date']>=days[0] for b in result['raw'].get(c,{}).get('bars',[])))]
    if fetch and need:
        executor=ThreadPoolExecutor(max_workers=config.EMOTION_RELAY['workers']);jobs={executor.submit(D.fetch_raw,c):c for c in need}
        try:
            for job in as_completed(jobs,timeout=config.EMOTION_RELAY['fetch_budget_seconds']):
                c=jobs[job]
                try:r=job.result();result['raw'][c]=r;D.write(D.root()/'raw'/(c+'.json'),r)
                except Exception as e:errors.append(dict(code=c,reason=str(e)))
        except TimeoutError:errors.append(dict(reason='原价历史补采预算到期'))
        finally:
            for job in jobs:
                if not job.done():job.cancel()
            executor.shutdown(wait=False,cancel_futures=True)
    active=[c for c in codes if any(b['date']>=days[0] for b in result['raw'].get(c,{}).get('bars',[]))]
    need=[c for c in active if (result['reference'].get(c) or {}).get('coverage_through','')<asof]
    for i in range(0,len(need),40):
        if not fetch or time.monotonic()-start>config.EMOTION_RELAY['fetch_budget_seconds']:break
        try:
            values=fetch_reference(need[i:i+40],calendar[max(0,len(calendar)-66)],asof)
            for c,r in values.items():result['reference'][c]=r;D.write(D.root()/'reference'/(c+'.json'),r)
        except Exception as e:
            errors.append(dict(reason='原价参考补采暂停：'+str(e)));break
        time.sleep(.8)
    result['fetch'].update(history_errors=errors,full_history_seconds=round(time.monotonic()-start,3),raw_codes=len(result['raw']),reference_codes=len(result['reference']))
    return result


def classify(code,day,calendar,evidence):
    raw=evidence.get('_raw_index',{}).get(code)
    if raw is None:raw={b['date']:b for b in evidence.get('raw',{}).get(code,{}).get('bars',[])}
    refs=evidence.get('_ref_index',{}).get(code)
    if refs is None:refs={b['date']:b for b in evidence.get('reference',{}).get(code,{}).get('bars',[])}
    bar=raw.get(day);ref=refs.get(day);halt=halt_on(evidence,code,day)
    if halt:
        if bar and bar.get('volume',0)>0:return None,'停牌表与实际成交日线冲突',False
        return None,'全天停牌，已完成板位保留且不增长',True
    if not bar or bar.get('volume')==0:
        return None,'缺失交易日按停牌处理，保留上一有效成交日板位',True
    if not ref:
        prior=[b for d,b in raw.items() if d<day and intraday._valid_historical_price_bar(b) and b.get('volume',0)>0]
        if not prior:return None,'尚无前一有效成交日参考价',False
        ref=dict(bar,reference_close=max(prior,key=lambda b:b['date'])['close'])
    if not intraday._valid_historical_price_bar(bar) or not bar.get('volume',0)>0 or not ref.get('volume',0)>0:return None,'无可核验成交日线',False
    if any(D.tick(bar[k])!=D.tick(ref[k]) for k in ('open','high','low','close')):return None,'两来源原价OHLC不一致',False
    if sum(b['date']<day and b.get('volume',0)>0 for b in raw.values())<5:return None,'上市初期涨跌幅制度待核验',False
    entry=((evidence.get('pools',{}).get(day) or {}).get('entries') or {}).get(code)
    if entry and str(entry.get('name','')).upper().startswith(('ST','*ST','N','C')):return None,'历史特殊涨跌幅制度不混比',False
    cap=D.limit_price(ref['reference_close'])
    if D.tick(bar['high'])>D.tick(cap):return None,'历史最高价超出普通10%限制，制度待核验',False
    sealed=D.tick(bar['close'])==D.tick(bar['high'])==D.tick(cap)
    pool=evidence.get('pools',{}).get(day) or {}
    if pool.get('date_verified') and bool(entry)!=sealed:return None,'历史涨停池与原价封板核算不一致',False
    return sealed,None,False


def index(evidence):
    evidence['_raw_index']={c:{b['date']:b for b in r['bars']} for c,r in evidence.get('raw',{}).items()}
    evidence['_ref_index']={c:{b['date']:b for b in r['bars']} for c,r in evidence.get('reference',{}).items()}


def close_proof(snap,q,bars,calendar,now,code=None):
    """Verify a post-close quote against an independently completed native bar.

    The provider's actual timestamp is retained. A late timestamp alone never
    establishes a closing price; all four prices and the native scale must match.
    """
    proof=closing_price.verify(snap,q,bars,calendar,now)
    if proof:return proof
    if not code:return None
    context=intraday.align_price_basis(q,bars,calendar,observation_day=now.date().isoformat())
    suspension_days=[]
    if not context.get('valid') and code and '历史窗口缺口' in str(context.get('reason')):
        import relay_regulation
        reg=relay_regulation.load([code],calendar,now,fetch=False)
        evidence=dict(verified_halts=reg['suspension_intervals']);native_dates={b['date'] for b in bars if b.get('volume',0)>0}
        suspension_days=[d for d in calendar if d not in native_dates and halt_on(evidence,code,d)]
        if suspension_days:context=intraday.align_price_basis(q,bars,[d for d in calendar if d not in suspension_days],observation_day=now.date().isoformat())
    if not suspension_days:return None
    proof=closing_price.verify(snap,q,bars,[d for d in calendar if d not in suspension_days],now)
    if proof:proof['verified_suspension_days']=suspension_days
    return proof


def ingest_close(snap,quotes,now,proofs=None):
    if snap.get('session')!='已收盘':return
    proofs=proofs or {}
    for row in snap.get('stocks',[])+snap.get('coverage_catalog',[]):
        if (row.get('market_strength') or {}).get('mode')!='正式收盘' and row['code'] not in proofs:continue
        c=row['code'];q=quotes.get(c) or {}
        if (not M.quote_valid(q,now,'已收盘',None,True)[0] and c not in proofs) or q.get('price_basis')!='raw' or q.get('price_basis_source') not in intraday._RAW_QUOTE_SOURCES or q.get('last_close_semantics')!='previous_trade_day_raw_close':continue
        if not all(isinstance(q.get(k),(int,float)) and q[k]>0 for k in ('open','high','low','price','last_close')):continue
        day=now.date().isoformat();bar=dict(date=day,open=q['open'],high=q['high'],low=q['low'],close=q['price'],volume=(q.get('volume_shou') or 0)*100,price_basis='raw',price_basis_source='verified_close_quote')
        if c in proofs:bar.update(proofs[c]['prices'],completed_daily_proof=proofs[c])
        if not intraday._valid_historical_price_bar(bar) or bar['volume']<=0:continue
        for folder in ('raw','reference'):
            path=D.root()/folder/(c+'.json');record=D.read(path) or dict(code=c,source='verified_close_quote',bars=[])
            values={b['date']:b for b in record['bars']};incoming=dict(bar,reference_close=q['last_close'],turnover_pct=q.get('turnover_pct')) if folder=='reference' else bar
            old=values.get(day) or {};keys=('open','high','low','close','volume')+(('reference_close','turnover_pct') if folder=='reference' else ())
            if all(old.get(k)==incoming.get(k) for k in keys) and (c not in proofs or old.get('completed_daily_proof')):continue
            values[day]=incoming
            record.update(bars=[values[d] for d in sorted(values)][-config.EMOTION_RELAY['raw_history_days']:],coverage_through=day)
            D.write(path,record)
