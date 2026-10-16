"""Dedicated raw daily evidence for relay research; never rewrites MA history."""
import json,time
from concurrent.futures import ThreadPoolExecutor,as_completed,TimeoutError
from datetime import datetime
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
import config,datafeed as D,intraday

def root():return config.CACHE_DIR/'emotion_relay'
def read(path):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return None
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    config.atomic_write_text(path,json.dumps(value,ensure_ascii=False,separators=(',',':')))
def mainboard(code):return str(code).startswith(config.BOARDS['sh_main']['prefix']+config.BOARDS['sz_main']['prefix'])
def tick(value):return Decimal(str(value)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
def limit_price(previous,pct=10):return float(tick(Decimal(str(previous))*(Decimal(1)+Decimal(str(pct))/100)))

def fetch_pool(day):
    params='ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt&Pageindex=0&pagesize=10000&sort=fbt:asc&date='+day.replace('-','')
    value=json.loads(D.em_get('https://push2ex.eastmoney.com/getTopicZTPool?'+params,timeout=config.EMOTION_RELAY['request_seconds']))
    data=value.get('data') or {};items=data.get('pool');total=data.get('tc')
    if value.get('rc')!=0 or not isinstance(items,list) or not isinstance(total,int) or total!=len(items) or not total:
        raise ValueError('涨停池总数/完整性待核验')
    entries={}
    for item in items:
        code=str(item.get('c') or '')
        if len(code)!=6 or not code.isdigit() or code in entries:raise ValueError('涨停池重复或无效代码：'+repr(code))
        price=item.get('p')
        if not isinstance(price,(int,float)) or price<=0:raise ValueError('涨停池价格缺失')
        entries[code]=dict(code=code,name=item.get('n'),price=float(price)/1000,
            turnover_pct=item.get('hs'),vendor_height=item.get('lbc'),
            first_seal=item.get('fbt'),last_seal=item.get('lbt'),reopen_count=item.get('zbc'),
            seal_amount_yuan=item.get('fund'),amount_yuan=item.get('amount'))
    # qdate is the provider's latest market date, NOT the requested historical
    # date. Each requested-day entry is cross-checked against raw bars below.
    return dict(day=day,entries=entries,total=total,source='eastmoney_daily_limit_pool',
        provider_market_date=data.get('qdate'),date_verified=False,fetched_at=str(datetime.now()))

def fetch_raw(code):
    symbol=('sh' if str(code).startswith('6') else 'sz')+code;error=None
    for host in config.KLINE['hosts'][:2]:
        try:
            data=json.loads(D.http_get(host+'?param='+symbol+',day,,,'+str(config.EMOTION_RELAY['raw_history_days'])+',',timeout=config.EMOTION_RELAY['request_seconds'],retry=0))
            rows=((data.get('data') or {}).get(symbol) or {}).get('day')
            if not isinstance(rows,list) or not rows:raise ValueError('原价日线缺失')
            bars=[]
            for r in rows:
                if len(r)<6:continue
                bar=dict(date=r[0],open=float(r[1]),close=float(r[2]),high=float(r[3]),low=float(r[4]),
                    volume=float(r[5])*config.volume_to_shares(code),price_basis='raw',price_basis_source='tencent_day',
                    corporate_action=any(isinstance(v,dict) and v for v in r[6:]))
                if not intraday._valid_historical_price_bar(bar):raise ValueError('原价日线OHLC无效')
                bars.append(bar)
            if len({b['date'] for b in bars})!=len(bars) or bars!=sorted(bars,key=lambda b:b['date']):raise ValueError('原价日线日期异常')
            return dict(code=code,bars=bars,source='tencent_day',fetched_at=str(datetime.now()))
        except (OSError,ValueError,RuntimeError,TypeError,KeyError) as e:error=e
    raise error or ValueError('原价历史无法获取')

def load(days,fetch=True):
    pools={};raw={};errors=[];requested=0;start=time.monotonic()
    for day in days:
        path=root()/'pools'/(day+'.json');record=read(path)
        if not record or record.get('day')!=day:
            if fetch:
                failed=read(path.with_suffix('.error.json')) or {}
                at=intraday.parse_quote_timestamp(failed.get('fetched_at'))
                if at and (datetime.now()-at).total_seconds()<3600:
                    errors.append(dict(day=day,reason=failed.get('reason')));continue
                try:record=fetch_pool(day);write(path,record);requested+=1
                except (OSError,ValueError,RuntimeError,TypeError) as e:
                    errors.append(dict(day=day,reason=str(e)));write(path.with_suffix('.error.json'),dict(fetched_at=str(datetime.now()),reason=str(e)));continue
            else:continue
        pools[day]=record
    codes=sorted({c for p in pools.values() for c in p['entries'] if mainboard(c)})
    need=[]
    for code in codes:
        record=read(root()/'raw'/(code+'.json'));required=[d for d,p in pools.items() if code in p['entries']]+days[-1:]
        have={b['date'] for b in (record or {}).get('bars',[])}
        if not set(required).issubset(have):need.append(code)
        if record:raw[code]=record
    if fetch and need:
        executor=ThreadPoolExecutor(max_workers=config.EMOTION_RELAY['workers'])
        jobs={executor.submit(fetch_raw,c):c for c in need};requested+=len(need)
        try:
            for job in as_completed(jobs,timeout=config.EMOTION_RELAY['fetch_budget_seconds']):
                code=jobs[job]
                try:
                    record=job.result();raw[code]=record;write(root()/'raw'/(code+'.json'),record)
                except (OSError,ValueError,RuntimeError,TypeError) as e:errors.append(dict(code=code,reason=str(e)))
        except TimeoutError:errors.append(dict(reason='原价批量采集预算到期，未完成项继续待核验'))
        finally:
            for job in jobs:
                if not job.done():job.cancel()
            executor.shutdown(wait=False,cancel_futures=True)
    for day,pool in pools.items():
        entries={c:e for c,e in pool['entries'].items() if mainboard(c)};checked=0;mismatch=[]
        for code,e in entries.items():
            bars={b['date']:b for b in raw.get(code,{}).get('bars',[])};b=bars.get(day)
            if b and tick(b['close'])==tick(e['price']) and tick(b['high'])==tick(e['price']):checked+=1
            else:mismatch.append(code)
        pool=dict(pool,date_verified=bool(entries) and checked==len(entries),checked=checked,expected=len(entries),mismatched=mismatch)
        pools[day]=pool
    return dict(pools=pools,raw=raw,fetch=dict(requested=requested,seconds=round(time.monotonic()-start,3),errors=errors))
