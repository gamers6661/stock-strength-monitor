"""Dated issuer disclosures and rolling deviation references, not regulator verdicts."""
import hashlib,json,re,time,urllib.parse,unicodedata
from datetime import datetime
import config,datafeed,intraday,relay_data as D

RULE_SOURCES=[
 'https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml',
 'https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf']
DATE=r'(\d{4})年(\d{1,2})月(\d{1,2})日'


def available_day(published,calendar,today):
    at=intraday.parse_quote_timestamp(published)
    if not at:return None
    dates=sorted(set(calendar+[today]));day=at.date().isoformat()
    if day in dates and at.hour*3600+at.minute*60+at.second<15*3600:return day
    return next((d for d in dates if d>day),None)


def metadata(codes,begin,end):
    records=[];page=1;total=None
    while total is None or len(records)<total:
        params=dict(sr=-1,page_size=100,page_index=page,ann_type='A',client_source='web',stock_list=','.join(codes),begin_time=begin,end_time=end)
        value=json.loads(datafeed.em_get('https://np-anotice-stock.eastmoney.com/api/security/ann?'+urllib.parse.urlencode(params),timeout=config.EMOTION_RELAY['request_seconds']))
        body=value.get('data') or {};items=body.get('list');count=body.get('total_hits')
        if not isinstance(items,list) or not isinstance(count,int) or body.get('page_index') not in (page,str(page)):raise ValueError('公告分页与完整性待核验')
        if total is None:total=count
        if count!=total or not items and len(records)<total:raise ValueError('公告分页采集期间集合变化')
        records.extend(items);page+=1
    if len(records)!=total or len({r['art_code'] for r in records})!=len(records):raise ValueError('公告数量或唯一性异常')
    return records


def content(item):
    art=item['art_code'];path=D.root()/'notices'/'content'/(art+'.json');saved=D.read(path)
    if saved:return saved
    url='https://np-cnotice-stock.eastmoney.com/api/content/ann?'+urllib.parse.urlencode(dict(art_code=art,client_source='web',page_index=1))
    body=(json.loads(datafeed.em_get(url,timeout=config.EMOTION_RELAY['request_seconds'])).get('data') or {})
    if body.get('art_code')!=art or not body.get('notice_content'):raise ValueError('公告正文或身份待核验')
    saved=dict(art_code=art,text=body['notice_content'],pdf_url=body.get('attach_url'),title=body.get('notice_title'))
    D.write(path,saved);return saved


def intervals(notices):
    events={}
    for n in notices:
        text=re.sub(r'\s+','',n.get('text') or '').replace('（','(').replace('）',')')
        if not text:continue
        for kind,expression in (
            ('start',r'(?:自|于)'+DATE+r'(?:\([^)]*\))?(?:上午)?(?:开市起|起|开市)(?:继续)?停牌'),
            ('resume',r'(?:自|于)'+DATE+r'(?:\([^)]*\))?(?:上午)?(?:开市起|起|开市)(?:恢复交易|复牌)')):
            for match in re.finditer(expression,text):
                day='%04d-%02d-%02d'%tuple(map(int,match.groups()))
                for c in n['codes']:events.setdefault(c,[]).append(dict(kind=kind,day=day,title=n['title'],source=n.get('pdf_url') or n['url'],published_at=n['published_at']))
    result=[]
    for c,items in events.items():
        items.sort(key=lambda x:(x['day'],x['kind']=='resume',x['published_at']));opening=None
        for event in items:
            if event['kind']=='start':
                if opening is None:opening=event
            elif opening is not None and event['day']>opening['day']:
                result.append(dict(code=c,start=opening['day'],resume=event['day'],source=opening['source'],resume_source=event['source'],reason=opening['title'],published_at=opening['published_at']));opening=None
        if opening:result.append(dict(code=c,start=opening['day'],resume=None,source=opening['source'],reason=opening['title'],published_at=opening['published_at']))
    return result


def fetch_index(symbol,asof,previous=None):
    # zs_ distinguishes an index from the cn_000002 stock. No stock-code fallback.
    code='zs_'+symbol[2:];url='https://q.stock.sohu.com/hisHq?'+urllib.parse.urlencode(dict(code=code,start='20260101',end=datetime.now().strftime('%Y%m%d'),stat=1,order='A',period='d'))
    values=json.loads(datafeed.http_get(url,timeout=config.EMOTION_RELAY['request_seconds'],retry=0))
    if not isinstance(values,list) or len(values)!=1 or values[0].get('code')!=code or values[0].get('status')!=0:raise ValueError('分类指数身份待核验')
    bars=[dict(date=r[0],open=float(r[1]),close=float(r[2]),low=float(r[5]),high=float(r[6])) for r in values[0].get('hq',[]) if r[0]<=asof]
    bars=sorted(bars,key=lambda b:b['date'])[-config.EMOTION_RELAY['raw_history_days']:]
    if not bars or any(not intraday._valid_historical_price_bar(b) for b in bars):raise ValueError('分类指数日线无效')
    result=dict(symbol=symbol,source='sohu_index_hisHq',bars=bars,completed_through=bars[-1]['date'],fetched_at=str(datetime.now()))
    if bars[-1]['date']!=asof:
        now=datetime.now()
        if asof!=now.date().isoformat() or now.hour*60+now.minute<905 or not previous or bars[-1]['date']!=previous:raise ValueError('分类指数完成日线尚未覆盖目标交易日')
        text=datafeed.http_get('https://qt.gtimg.cn/q='+symbol,encoding='gbk',timeout=config.EMOTION_RELAY['request_seconds'],retry=0)
        match=re.search(r'v_'+symbol+r'="([^\"]+)"',text)
        parts=match.group(1).split('~') if match else []
        if len(parts)<35:raise ValueError('分类指数收盘报价格式待核验')
        name=unicodedata.normalize('NFKC',parts[1]);allowed=('A股指数','上证A股','上证A股指数') if symbol=='sh000002' else ('深证A指','深证A股指数')
        at=intraday.parse_quote_timestamp(parts[30]);bar=dict(date=asof,open=float(parts[5]),close=float(parts[3]),high=float(parts[33]),low=float(parts[34]))
        if parts[2]!=symbol[2:] or name not in allowed or not at or at.date()!=now.date() or at.hour<15 or (at-now).total_seconds()>config.INTRADAY['max_quote_future_seconds']:raise ValueError('分类指数身份、日期或源时刻不符')
        if D.tick(float(parts[4]))!=D.tick(bars[-1]['close']) or not intraday._valid_historical_price_bar(bar):raise ValueError('分类指数前收衔接或收盘OHLC不符')
        bar.update(source='tencent_verified_index_close',quote_at=str(at),previous_date=previous,previous_close=float(parts[4]));result['bars'].append(bar)
        result.update(source='sohu_history+tencent_verified_index_close',completed_through=asof,closing_quote_at=str(at),closing_name=name)
    return result


def load(codes,calendar,now,fetch=True,budget_seconds=None):
    today=now.date().isoformat();begin=calendar[max(0,len(calendar)-45)];codes=sorted(set(codes));records={};errors=[];started=time.monotonic();need=[];covered=[]
    for c in codes:
        path=D.root()/'notices'/'stocks'/(c+'_'+today+'.json');saved=D.read(path)
        try:at=datetime.fromisoformat((saved or {}).get('fetched_at',''))
        except ValueError:at=None
        usable=saved and saved.get('begin','9999')<=begin
        if usable:
            covered.append(c)
            for r in saved['items']:records[r['art_code']]=r
        if not usable or not at or (now-at).total_seconds()>1800:need.append(c)
    # Backfills finish missing codes before renewing already covered codes.
    need.sort(key=lambda c:c in covered)
    budget=config.EMOTION_RELAY['fetch_budget_seconds'] if budget_seconds is None else budget_seconds
    for i in range(0,len(need),20):
        if not fetch or time.monotonic()-started>=budget:break
        chunk=need[i:i+20]
        try:
            items=metadata(chunk,begin,today)
            for c in chunk:
                selected=[r for r in items if any(v.get('stock_code')==c for v in r.get('codes',[]))]
                D.write(D.root()/'notices'/'stocks'/(c+'_'+today+'.json'),dict(items=selected,begin=begin,fetched_at=str(now)))
                if c not in covered:covered.append(c)
            for r in items:records[r['art_code']]=r
        except Exception as e:errors.append(str(e))
    notices=[]
    for item in records.values():
        title=item.get('title') or '';published=str(item.get('display_time') or '')[:19];at=intraday.parse_quote_timestamp(published)
        if not at or at>now or not any(k in title for k in ('异常波动','停牌','复牌','股票交易风险')):continue
        related=[c['stock_code'] for c in item.get('codes',[]) if c.get('stock_code') in codes]
        if not related:continue
        n=dict(id=item['art_code'],title=title,codes=related,published_at=published,notice_date=str(item.get('notice_date',''))[:10],available_day=available_day(published,calendar,today),
            kind='serious' if '严重异常波动' in title else 'abnormal' if '异常波动' in title else 'suspension' if '停牌' in title else 'resume' if '复牌' in title else 'risk',
            url='https://data.eastmoney.com/notices/detail/'+related[0]+'/'+item['art_code']+'.html')
        if any(k in title for k in ('停牌','复牌')):
            try:
                saved=D.read(D.root()/'notices'/'content'/(item['art_code']+'.json'))
                if not saved and fetch and time.monotonic()-started<budget:saved=content(item)
                if saved:n.update(text=saved['text'],pdf_url=saved.get('pdf_url'))
            except Exception as e:errors.append(str(e))
        notices.append(n)
    indices={}
    for symbol in ('sh000002','sz399107'):
        path=D.root()/'benchmarks'/(symbol+'.json');record=D.read(path)
        if record:record=dict(record,bars=[b for b in record.get('bars',[]) if b['date']<=record.get('completed_through',today if now.hour>=15 else calendar[-1]) and b['date']<=calendar[-1]])
        if fetch and (not record or not any(b['date']==calendar[-1] for b in record.get('bars',[])) or calendar[-1]==today and record.get('completed_through','')<today):
            try:record=fetch_index(symbol,calendar[-1],calendar[-2] if len(calendar)>1 else None);D.write(path,record)
            except Exception as e:errors.append(str(e))
        if record:indices[symbol]=record
    return dict(notices=notices,suspension_intervals=intervals(notices),indices=indices,scope_codes=codes,covered_codes=covered,errors=errors,asof=str(now),rule_sources=RULE_SOURCES)


def deviation(code,days,evidence,indices):
    symbol='sh000002' if code.startswith('6') else 'sz399107';index={b['date']:b for b in indices.get(symbol,{}).get('bars',[])}
    raw=evidence.get('_raw_index',{}).get(code,{ });refs=evidence.get('_ref_index',{}).get(code,{ });windows=[]
    for count,threshold in ((3,20),(10,100),(30,200)):
        selected=days[-count:];before=days[-count-1] if len(days)>count else None;factor=1.;reason=None
        if len(selected)<count or not before or before not in index or selected[-1] not in index:reason='分类指数或交易日窗口未覆盖'
        if not reason:
            for day in selected:
                if H_halted(evidence,code,day):continue
                bar=raw.get(day);ref=refs.get(day)
                if not bar or not ref or any(D.tick(bar[k])!=D.tick(ref[k]) for k in ('open','high','low','close')):reason='原价与每日涨跌额未完成交叉核验';break
                if sum(b['date']<day and b.get('volume',0)>0 for b in raw.values())<5:reason='窗口含上市初期，普通制度不适用';break
                factor*=ref['close']/ref['reference_close']
        value=None if reason else round((factor-index[selected[-1]]['close']/index[before]['close'])*100,2)
        windows.append(dict(days=count,asof=selected[-1] if selected else None,deviation_pp=value,threshold_pp=threshold,remaining_pp=None if value is None else round(threshold-value,2),reason=reason))
    return dict(benchmark=symbol,windows=windows,basis='按市场交易日计算股票滚动区间涨幅减分类指数区间涨幅，停牌日股票收益不增长；尚未核验交易所公告/复牌重置，不作为正式异动认定或次数计数')


def H_halted(evidence,code,day):
    import relay_history
    return relay_history.halt_on(evidence,code,day)
