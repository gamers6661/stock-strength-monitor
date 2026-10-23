"""独立的真实成交额档案。保留原始日线，绝不回写共享价格库或估算成交额。"""
import concurrent.futures
import json
import math
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime

import config

SOURCE = 'eastmoney_raw_daily'
SOURCES = {SOURCE, 'baostock_raw_daily', 'tencent_close_quote'}


def path():
    return config.CACHE_DIR / 'stock_selection_v3' / 'amounts.db'


def connect():
    path().parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path(), timeout=15)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('CREATE TABLE IF NOT EXISTS bars(code TEXT,date TEXT,open REAL,close REAL,high REAL,low REAL,volume REAL,amount REAL,source TEXT,observed_at TEXT,PRIMARY KEY(code,date))')
    return con


def fetch(code, days=90, timeout=8):
    params = dict(secid=('1.' if code.startswith('6') else '0.')+code, klt=101,
                  fqt=0, lmt=days, end='20500101', fields1='f1,f2,f3,f4,f5,f6',
                  fields2='f51,f52,f53,f54,f55,f56,f57')
    import datafeed
    data = json.loads(datafeed.em_get('https://push2his.eastmoney.com/api/qt/stock/kline/get?'+urllib.parse.urlencode(params),timeout=timeout)).get('data')
    if not data or data.get('code') != code:
        raise ValueError('证券代码不匹配或无日线')
    out=[]
    for line in data.get('klines', []):
        r=line.split(','); day=r[0]
        datetime.strptime(day, '%Y-%m-%d')
        op,cl,hi,lo,vol,amt=map(float,r[1:7]);vol*=100
        if not all(math.isfinite(v) and v>0 for v in (op,cl,hi,lo,vol,amt)):
            continue
        if not lo<=min(op,cl)<=max(op,cl)<=hi:
            raise ValueError('OHLC异常')
        # 成交均价必须落在原价区间；允许源金额/成交量舍入误差。
        if not lo-.02<=amt/vol<=hi+.02:
            raise ValueError('成交金额与成交量单位或均价异常')
        out.append(dict(date=day,open=op,close=cl,high=hi,low=lo,volume=vol,amount=amt,
                        price_basis='raw',price_basis_source=SOURCE))
    if not out or [b['date'] for b in out]!=sorted({b['date'] for b in out}):
        raise ValueError('日线日期异常或无有效成交')
    return out


def load():
    if not path().exists():
        return {}
    con=sqlite3.connect('file:'+path().as_posix()+'?mode=ro',uri=True)
    try:
        result={}
        for c,d,o,cl,h,l,v,a,s,at in con.execute('SELECT * FROM bars ORDER BY code,date'):
            result.setdefault(c,{})[d]=dict(date=d,open=o,close=cl,high=h,low=l,volume=v,amount=a,
                                           source=s,observed_at=at,price_basis='raw')
        return result
    finally:
        con.close()


def verified_amount(bar, record):
    """仅采纳同证券日期、成交量一致且来源明确的金额；不以小价差猜复权。"""
    if not record or record.get('date')!=bar.get('date') or record.get('source') not in SOURCES:
        return None
    v=bar.get('volume',0);rv=record.get('volume',0);amount=record.get('amount',0)
    import math
    if not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>0 for x in (v,rv,amount,record.get('low'),record.get('high'))):return None
    if abs(v/rv-1)>.005:
        return None
    if not record['low']-.02<=amount/rv<=record['high']+.02:
        return None
    return amount


def refresh_bulk(codes, dates, budget=180):
    """BaoStock官方逐日全A接口：原价、股、元；每次一个交易日，独立留档。"""
    import socket
    import sys
    vendor=path().parent/'vendor'
    if vendor.exists() and str(vendor) not in sys.path:sys.path.insert(0,str(vendor))
    import baostock as bs
    codes=set(codes);existing=load();start=time.monotonic()
    todo=sorted((d for d in dates if sum(d in existing.get(c,{}) for c in codes)<len(codes)*.95),reverse=True)
    status=dict(source='baostock_raw_daily',requested=0,succeeded=0,rows=0,errors={},started_at=str(datetime.now()))
    old_timeout=socket.getdefaulttimeout();socket.setdefaulttimeout(15)
    con=connect()
    try:
        login=bs.login()
        if login.error_code!='0':raise RuntimeError(login.error_msg)
        for day in todo:
            if time.monotonic()-start>budget:break
            query=bs.query_daily_history_k_AStock(day);status['requested']+=1;records=[]
            if query.error_code!='0':
                status['errors'][day]=query.error_msg
                if len(status['errors'])>=3:break
                continue
            at=str(datetime.now())
            while query.next():
                r=dict(zip(query.fields,query.get_row_data()));code=r.get('code','').split('.')[-1]
                if code not in codes or r.get('date')!=day or r.get('adjustflag')!='3':continue
                try:
                    op,cl,hi,lo,vol,amt=(float(r[k]) for k in ('open','close','high','low','volume','amount'))
                    if not all(math.isfinite(v) and v>0 for v in (op,cl,hi,lo,vol,amt)):continue
                    if not lo<=min(op,cl)<=max(op,cl)<=hi or not lo-.02<=amt/vol<=hi+.02:continue
                    records.append((code,day,op,cl,hi,lo,vol,amt,'baostock_raw_daily',at))
                except (TypeError,ValueError,KeyError):continue
            if records:
                con.executemany('INSERT OR REPLACE INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)',records);con.commit()
                status['succeeded']+=1;status['rows']+=len(records)
            else:status['errors'][day]='源未返回本日有效数据；保留已有档案'
            print('amount bulk',day,len(records),flush=True)
        bs.logout()
    finally:
        con.close();socket.setdefaulttimeout(old_timeout)
    status.update(seconds=round(time.monotonic()-start,2),completed_at=str(datetime.now()))
    config.atomic_write_text(path().parent/'amount_bulk_status.json',json.dumps(status,ensure_ascii=False,indent=2))
    return status


def refresh_candidates(codes, start_date, end_date, budget=180):
    """全市场逐日接口不可用时，逐股补齐候选窗口；失败不推断为零。"""
    import socket
    import sys
    vendor=path().parent/'vendor'
    if vendor.exists() and str(vendor) not in sys.path:sys.path.insert(0,str(vendor))
    import baostock as bs
    start=time.monotonic();status=dict(source='baostock_raw_daily',method='per_stock',requested=0,succeeded=0,rows=0,errors={})
    old_timeout=socket.getdefaulttimeout();socket.setdefaulttimeout(10);con=connect();failures=0
    try:
        login=bs.login()
        if login.error_code!='0':raise RuntimeError(login.error_msg)
        for code in codes:
            if time.monotonic()-start>budget or failures>=3:break
            query=bs.query_history_k_data_plus(('sh.' if code.startswith('6') else 'sz.')+code,
                'date,code,open,high,low,close,volume,amount',start_date=start_date,end_date=end_date,frequency='d',adjustflag='3')
            status['requested']+=1;records=[]
            if query.error_code!='0':
                failures+=1;status['errors'][code]=query.error_msg
                if failures<3:
                    # 超时后旧socket可能残留上一响应，重新登录后再查询下一只。
                    from baostock.common import context
                    old_socket=getattr(context,'default_socket',None)
                    if old_socket:old_socket.close()
                    bs.login()
                continue
            while query.next():
                r=dict(zip(query.fields,query.get_row_data()))
                validate_response_identity(r,code,start_date,end_date)
                try:
                    o,cl,h,l,v,a=(float(r[k]) for k in ('open','close','high','low','volume','amount'))
                    if not all(math.isfinite(x) and x>0 for x in (o,cl,h,l,v,a)) or not l-.02<=a/v<=h+.02:continue
                    records.append((code,r['date'],o,cl,h,l,v,a,'baostock_raw_daily',str(datetime.now())))
                except (KeyError,TypeError,ValueError):continue
            if records:
                con.executemany('INSERT OR REPLACE INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)',records);con.commit()
                status['succeeded']+=1;status['rows']+=len(records);failures=0
            print('amount stock',code,len(records),flush=True)
        bs.logout()
    finally:con.close();socket.setdefaulttimeout(old_timeout)
    status['seconds']=round(time.monotonic()-start,2)
    config.atomic_write_text(path().parent/'amount_stock_status.json',json.dumps(status,ensure_ascii=False,indent=2))
    return status


def validate_response_identity(row,code,start_date,end_date):
    expected=('sh.' if code.startswith('6') else 'sz.')+code
    if row.get('code')!=expected or not start_date<=row.get('date','')<=end_date:
        raise ValueError('成交日线响应代码或日期不一致，拒绝写入: '+str(row.get('code')))


def save_close_quotes(snap,histories=None,calendar=None,now=None):
    """原始收盘报价与独立完成日线逐项核验后补金额，保留原始源时刻。"""
    import stock_selection as S
    import closing_price
    now=now or datetime.now()
    if snap.get('session')!='已收盘' or not snap.get('close_daily_verified_at'):return 0
    if histories is None:histories,calendar=S.inputs(snap)
    day=str(now.date());canonical=(snap.get('market_strength_close_input') or {}).get('quotes',{})
    quotes={q['code']:q for q in snap.get('coverage_catalog',[])+snap.get('stocks',[])}
    quotes.update({code:dict(q,code=code) for code,q in canonical.items()})
    records=[]
    for code,q in quotes.items():
        if not closing_price.verify(snap,q,histories.get(code,[]),calendar,now):continue
        vals=[q.get(k) for k in ('open','price','high','low','volume_shou','amount_wan')]
        if not all(isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v) and v>0 for v in vals):continue
        op,cl,hi,lo,vol,amt=vals;vol*=100;amt*=10000
        native=next(b for b in histories[code] if b['date']==day)
        record=dict(date=day,volume=vol,amount=amt,low=lo,high=hi,source='tencent_close_quote')
        if verified_amount(native,record) is None:continue
        records.append((code,day,op,cl,hi,lo,vol,amt,'tencent_close_quote',str(S.parse_at(q.get('quote_at') or q.get('ts')))))
    con=connect()
    try:
        before=con.total_changes
        con.executemany('INSERT OR IGNORE INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)',records);con.commit()
        return con.total_changes-before
    finally:con.close()


def refresh(codes, days=90, workers=4, budget=180, force=False):
    """有预算的盘后批量补采；连续故障停止扩大请求。"""
    start=time.monotonic();today=str(datetime.now().date())
    existing=load(); todo=[c for c in sorted(codes) if force or not existing.get(c) or max(existing[c])<today]
    status=dict(source=SOURCE,started_at=str(datetime.now()),requested=0,succeeded=0,failed=0,rows=0,errors={})
    con=connect(); failures=0
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for index in range(0,len(todo),workers):
                if time.monotonic()-start>=budget or failures>=12:
                    break
                batch={pool.submit(fetch,c,days):c for c in todo[index:index+workers]}
                for future in concurrent.futures.as_completed(batch):
                    code=batch[future];status['requested']+=1
                    try:
                        bars=future.result();at=str(datetime.now())
                        con.executemany('INSERT OR REPLACE INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)',
                            [(code,b['date'],b['open'],b['close'],b['high'],b['low'],b['volume'],b['amount'],SOURCE,at) for b in bars])
                        status['succeeded']+=1;status['rows']+=len(bars);failures=0
                    except Exception as exc:
                        failures+=1;status['failed']+=1
                        if len(status['errors'])<10:status['errors'][code]=type(exc).__name__+': '+str(exc)
                con.commit()
    finally:
        con.close()
    status.update(deferred=len(todo)-status['requested'],seconds=round(time.monotonic()-start,2),completed_at=str(datetime.now()))
    config.atomic_write_text(path().parent/'amount_status.json',json.dumps(status,ensure_ascii=False,indent=2))
    return status


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--budget',type=int,default=180);p.add_argument('--codes');p.add_argument('--bulk',action='store_true');p.add_argument('--candidates',action='store_true');p.add_argument('--maintain',action='store_true');p.add_argument('--days',type=int,default=25);args=p.parse_args()
    codes=args.codes.split(',') if args.codes else json.loads(config.POOL_CACHE.read_text(encoding='utf8')).keys()
    if args.bulk or args.candidates or args.maintain:
        import stock_selection as S
        snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf8'));_,calendar=S.inputs(snap)
        maintenance_start=time.monotonic();bulk=None
        if args.maintain:bulk=refresh_bulk(codes,calendar[-1:],budget=min(30,args.budget))
        if args.candidates or args.maintain:
            existing=load();model=S.read('latest.json');order=model.get('order',sorted(codes));expected=calendar[-20:]
            todo=[c for c in order if c in codes and any(d not in existing.get(c,{}) for d in expected)]
            budget=max(0,args.budget-(time.monotonic()-maintenance_start))
            result=refresh_candidates(todo,calendar[-args.days],calendar[-1],budget=budget) if todo and budget>0 else dict(skipped=True,remaining=len(todo))
            if args.maintain:result=dict(bulk=bulk,per_stock=result)
        else:result=refresh_bulk(codes,calendar[-args.days:],budget=args.budget)
    else:result=refresh(codes,budget=args.budget)
    print(json.dumps(result,ensure_ascii=False))
