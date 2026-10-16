"""同花顺板块分时批量报价；保留源日期/分钟，不以采集时间替代报价时间。"""
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from datetime import datetime
import json
import math
import re
import time
import threading

import config
import datafeed

CACHE = config.CACHE_DIR / 'ths_index_quotes.json'
VERSION = '同花顺指数缓存重验证2'
TOTAL_BUDGET_SECONDS = 60
BATCH_BUDGET_SECONDS = 45


def parse(raw):
    match = re.search(r'\((.*)\)\s*;?\s*$', raw.strip(), re.S)
    obj = json.loads(match.group(1)) if match else {}
    quotes = {}
    for key, row in obj.items():
        if not re.fullmatch(r'bk_\d{6}', key):
            continue
        try:
            day = datetime.strptime(row['date'], '%Y%m%d').strftime('%Y-%m-%d')
            points = []
            for item in row.get('data', '').split(';'):
                if not item:
                    continue
                p = item.split(',')
                at = datetime.strptime(day+' '+p[0], '%Y-%m-%d %H%M')
                price = float(p[1])
                if not math.isfinite(price) or price <= 0:
                    raise ValueError('分时价格异常')
                if points and at <= points[-1][0]:
                    raise ValueError('分时顺序异常')
                points.append((at, price))
            pre = float(row['pre'])
            if not points or not math.isfinite(pre) or pre <= 0:
                continue
            quotes[key[3:]] = dict(code=key[3:], name=row['name'], date=day,
                quote_at=points[-1][0].isoformat(sep=' ', timespec='seconds'),
                price=points[-1][1], previous_close=pre,
                sampled_low=min(p[1] for p in points), sampled_high=max(p[1] for p in points),
                source='同花顺板块指数分时', price_basis='同花顺指数原值',
                change_pct=(points[-1][1]/pre-1)*100)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    return quotes


def fetch(codes, cache_path=None):
    """每20个指数合并为一请求，最多3路；失败缓存保持真实报价时间。"""
    started = time.monotonic()
    deadline = started+TOTAL_BUDGET_SECONDS
    batch_deadline = min(deadline, started+BATCH_BUDGET_SECONDS)
    target = cache_path or CACHE
    try:
        container=json.loads(target.read_text(encoding='utf-8'))
        raw_cache=container.get('quotes') if isinstance(container,dict) else {}
        cached={}
        for code,q in (raw_cache.items() if isinstance(raw_cache,dict) else []):
            try:
                at=datetime.fromisoformat(q['quote_at'])
                prices=[float(q[k]) for k in ('price','previous_close','sampled_low','sampled_high')]
                if (q.get('code')==code and at.tzinfo is None and q.get('date')==at.date().isoformat()
                        and all(math.isfinite(v) and v>0 for v in prices)
                        and prices[2]<=prices[0]<=prices[3]):
                    cached[code]=q
            except (KeyError,TypeError,ValueError):
                continue
    except (OSError, ValueError):
        cached = {}
    codes = sorted(set(str(c) for c in codes if re.fullmatch(r'\d{6}', str(c))))
    batches = [codes[i:i+20] for i in range(0, len(codes), 20)]
    refresh_bucket = int(time.time() // 300)
    now = datetime.now()
    session = datafeed.session_label(now)
    supplement_lock = threading.Lock()
    supplement_state = {'last': 0.0, 'requests': 0}
    headers = {'Referer': 'http://q.10jqka.com.cn/',
               'Cache-Control': 'no-cache', 'Pragma': 'no-cache'}

    def needs_supplement(q, old):
        if session in ('盘前', '非交易日', '集合竞价', '竞价结束'):
            return False  # 分时指数未发布时不为缺少当日报价展开大量补核。
        if not q or q.get('quote_at', '') < (old or {}).get('quote_at', ''):
            return True
        if freshness(q, now, session):
            return True
        # 批量响应虽未过期，也可能停留在上一轮；交易中延迟超过两分钟补核一次。
        return (session in ('早盘', '午盘', '尾盘')
                and (now-datetime.fromisoformat(q['quote_at'])).total_seconds() > 120)

    def single_quote(code, scheme):
        with supplement_lock:
            delay = .35-(time.monotonic()-supplement_state['last'])
            if deadline-time.monotonic() <= max(0,delay):
                raise TimeoutError('指数补核达到本轮时间预算')
            if delay > 0:
                time.sleep(delay)
            supplement_state['last'] = time.monotonic()
            supplement_state['requests'] += 1
        url = (scheme+'://d.10jqka.com.cn/v6/time/bk_'+code
               +'/last.js?refresh='+str(refresh_bucket))
        return parse(datafeed.http_get(url, headers=headers,
                     encoding='gbk', timeout=min(6,max(.01,deadline-time.monotonic())), retry=0)).get(code)

    def work(batch):
        try:
            remaining=batch_deadline-time.monotonic()
            if remaining<=0:
                return batch, {}, '指数批量获取达到本轮时间预算'
            url = ('http://d.10jqka.com.cn/v6/time/'+','.join('bk_'+c for c in batch)
                   +'/last.js?refresh='+str(refresh_bucket))
            # 同一批次URL可能被缓存节点返回更早分时；按HTTP语义要求重验证，
            # 并使用共享的5分钟缓存键，避免不遵循重验证头的中间缓存沿用旧响应。
            # 仍按源时间判断新鲜度，不增加请求频率或把抓取时间当报价时间。
            raw = datafeed.http_get(url, headers=headers,
                                   encoding='gbk', timeout=min(8,max(.01,remaining/2)), retry=1)
            fresh = parse(raw)
        except Exception as exc:
            # 真实网络拒绝不再叠加单指数请求，保留缓存，避免失败时扩大请求量。
            return batch, {}, str(exc)
        if not fresh:
            return batch, {}, '同花顺批量指数接口未返回有效数据'
        return batch, fresh, None

    def collect(tasks, worker, until):
        if not tasks or time.monotonic()>=until:
            return []
        pool=ThreadPoolExecutor(max_workers=3)
        futures=[pool.submit(worker,task) for task in tasks]
        done=[]
        timed_out=False
        try:
            for future in as_completed(futures,timeout=max(.01,until-time.monotonic())):
                done.append(future.result())
        except FuturesTimeoutError:
            timed_out=True
        finally:
            for future in futures:
                future.cancel()
            # Workers only return data. A late network response must not mutate the cache.
            pool.shutdown(wait=not timed_out)
        return done

    # Complete the whole-pool batch pass first; single-code verification cannot delay later batches.
    fetched={}
    errors={code:'指数批量获取达到本轮时间预算，下一轮继续核验' for code in codes}
    supplemental=[]
    for batch,fresh,error in collect(batches,work,batch_deadline):
        fetched.update(fresh)
        for code in batch:
            errors[code]=error
            if not error and needs_supplement(fresh.get(code),cached.get(code)):
                supplemental.append(code)
    if supplemental:
        # Rotate the starting point each normal 5-minute bucket to avoid starving the same tail.
        offset=refresh_bucket%len(supplemental)
        supplemental=supplemental[offset:]+supplemental[:offset]
    def supplement(code):
        q=fetched.get(code)
        try:
            single=single_quote(code,'http')
            if single and (not q or single['quote_at']>=q['quote_at']):
                q=single
            if needs_supplement(q,cached.get(code)) and time.monotonic()<deadline:
                verified=single_quote(code,'https')
                if verified and (not q or verified['quote_at']>=q['quote_at']):
                    q=verified
        except Exception:
            pass
        return code,q
    for code,q in collect(supplemental,supplement,deadline):
        if q:
            fetched[code]=q
    result = {}
    now=datetime.now()
    session=datafeed.session_label(now)
    for code in codes:
        q=fetched.get(code)
        old=cached.get(code)
        if q and (not old or q['quote_at']>=old.get('quote_at','')):
            cached[code]=q
        used=dict(cached.get(code) or {})
        if errors.get(code) or not q or q.get('quote_at','') < (old or {}).get('quote_at',''):
            used['fetch_error']=errors.get(code) or '本轮未返回更新的有效指数报价'
        elif freshness(used,now,session):
            used['fetch_error']=freshness(used,now,session)
        result[code]=used
    config.atomic_write_text(target, json.dumps(dict(quotes=cached, fetch_version=VERSION), ensure_ascii=False))
    failures = sum(bool(q.get('fetch_error')) for q in result.values())
    datafeed._source_mark('ths_index_quotes', 'partial' if failures else 'ok',
                         elapsed=time.monotonic()-started,
                         coverage=f'{len(codes)-failures}/{len(codes)}',
                         detail=f'{VERSION}；批量{len(batches)}次；延迟补核{supplement_state["requests"]}次；本轮异常{failures}个')
    return result


def freshness(quote, now, session):
    try:
        at = datetime.fromisoformat(quote['quote_at'])
    except (KeyError, TypeError, ValueError):
        return '尚无当日指数报价'
    if at.date() != now.date():
        return '指数报价不是当日数据'
    age = (now-at).total_seconds()
    if age < -config.INTRADAY['max_quote_future_seconds']:
        return '指数报价时间超前'
    minute = at.hour*60+at.minute
    if session in ('集合竞价', '竞价结束'):
        if not 9*60+15 <= minute < 9*60+30:
            return '尚无当日竞价指数报价'
    elif not (9*60+30 <= minute <= 11*60+30 or 13*60 <= minute <= 15*60):
        return '指数报价不在交易时段'
    if session == '午间休市':
        return None if minute == 11*60+30 else '尚无11:30上午收市指数报价'
    if session == '已收盘':
        return None if minute == 15*60 else '尚无15:00收盘指数报价'
    if session in ('午盘', '尾盘') and minute < 13*60:
        return '尚无下午指数报价'
    if age > config.INTRADAY['max_quote_age_seconds']:
        return '指数报价过期'
    return None
