"""个股强度V3。完成日自身强度、形态、板块、盘中状态各自保留证据。"""
import copy
import hashlib
import json
import math
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

import config
import intraday
import market_strength
import stock_selection_data as amounts
from stock_selection_rules import RULES as R, QUALITY, VERSION

_LOCK=threading.RLock()
_DAILY_METRICS = {}
IMPLEMENTATION_HASH=hashlib.sha256(Path(__file__).read_bytes()+Path(amounts.__file__).read_bytes()+
    Path(__file__).with_name('stock_selection_rules.py').read_bytes()+Path(__file__).with_name('stock_selection_rollout.py').read_bytes()+Path(__file__).with_name('stock_selection_intraday.py').read_bytes()+Path(__file__).with_name('stock_selection_factors.py').read_bytes()+Path(__file__).with_name('stock_selection_turning.py').read_bytes()+Path(__file__).with_name('stock_selection_quality.py').read_bytes()).hexdigest()[:20]


def number(v):
    return isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v)


def clip(v,lo=0.,hi=1.):
    return max(lo,min(hi,v))


def scale(v,full):
    return 100*clip(v/full)


def folder():
    return config.CACHE_DIR/'stock_selection_v3'


def read(name,default=None):
    try:return json.loads((folder()/name).read_text(encoding='utf8'))
    except (OSError,ValueError):return default if default is not None else {}


def parse_at(value):
    try:
        text=str(value)
        return datetime.strptime(text,'%Y%m%d%H%M%S') if len(text)==14 and text.isdigit() else datetime.fromisoformat(text)
    except (ValueError,TypeError):return None


def unique_rows(snap):
    master=snap.get('_security_master') or {}
    asof=snap.get('_universe_at') or str(snap.get('quote_capture_at',''))[:10]
    def current(code):
        if not master:return True
        item=master.get(code)
        if not item:return False
        return not (item.get('outDate') and item['outDate']<=asof) and not (item.get('ipoDate') and item['ipoDate']>asof)
    return {r['code']:r for r in snap.get('coverage_catalog',[])+snap.get('stocks',[])
            if str(r.get('code','')).startswith(('600','601','603','605','000','001','002','003')) and current(r['code'])}


def clean_bars(bars,calendar,asof,require_volume=True):
    bs=[b for b in bars if b['date']<=asof]
    expected=[d for d in calendar if d<=asof][-R['min_bars']:]
    if len(bs)<R['min_bars'] or len(expected)<R['min_bars']:
        return [],'完成日历史不足26根'
    recent=bs[-R['min_bars']:]
    if [b['date'] for b in recent]!=expected:
        return [],'最近26个市场交易日存在缺口或停牌；保留历史参考'
    if not all(intraday._valid_historical_price_bar(b) and (not require_volume or number(b.get('volume')) and b['volume']>0) for b in recent):
        return [],'完成日OHLC或成交量无效'
    modes={(b.get('price_basis'),b.get('price_basis_source')) for b in recent}
    allowed={( 'qfq',s) for s in intraday._QFQ_HISTORY_SOURCES}|{('raw',s) for s in intraday._RAW_HISTORY_SOURCES}
    if len(modes)!=1 or not modes.issubset(allowed):
        return [],'历史价格来源或复权口径待核验'
    if not any(max(b['high']-b['low'],abs(b['high']-a['close']),abs(b['low']-a['close']))>0 for a,b in zip(recent[-21:-1],recent[-20:])):
        return [],'ATR为零，无法核验标准化推进'
    return bs,None


def base_metrics(bs,records):
    closes=[b['close'] for b in bs];last=bs[-1];previous=bs[-2]
    tr=[max(b['high']-b['low'],abs(b['high']-a['close']),abs(b['low']-a['close'])) for a,b in zip(bs[-21:-1],bs[-20:])]
    atr=mean(tr)
    returns={str(n):100*(last['close']/closes[-n-1]-1) for n in R['periods']}
    advances=[.6*scale(returns[str(n)],full)+.4*scale((last['close']-closes[-n-1])/atr,4.)
              for n,full in zip(R['periods'],R['return_scales'])]
    advance=sum(w*v for w,v in zip(R['period_weights'],advances))
    changes=[b['close']-a['close'] for a,b in zip(bs[-11:-1],bs[-10:])]
    gains=[max(0.,v) for v in changes]
    effective=sum(gains)**2/sum(v*v for v in gains) if any(gains) else 0.
    higher=sum(b['high']>a['high'] and b['low']>=a['low'] for a,b in zip(bs[-11:-1],bs[-10:]))/10
    persistence=.6*scale(effective,6)+.4*100*higher
    peak=max(b['high'] for b in bs[-20:]);low=min(b['low'] for b in bs[-20:])
    dd=max(0.,peak-last['close'])/atr
    retrace=clip((peak-last['close'])/max(peak-low,atr))
    # 奖励已取得的推进成果，横盘和弱势缩量本身不产生保持分。
    prior=bs[:-5]
    prior_advance=any(len(prior)>n and 100*(prior[-1]['close']/prior[-n-1]['close']-1)>=cut
                      for n,cut in zip(R['periods'],R['advance_min']))
    has_advance=prior_advance or any(returns[str(n)]>=cut for n,cut in zip(R['periods'],R['advance_min']))
    retention=100*(.5*(1-clip(dd/3.5))+.5*(1-retrace)) if has_advance else 0.
    from stock_selection_quality import assess
    quality=assess(bs,atr,retention,has_advance,QUALITY)
    quality["advance_before_quality"]=advance
    advance*=quality["impulse_multiplier"];retention=quality["retention"]
    price=(.50*advance+.25*persistence+.25*retention)*quality["damage_multiplier"]
    from stock_selection_factors import price_observations
    observed=price_observations(bs)
    volume_valid=all(number(b.get('volume')) and b['volume']>0 for b in bs[-26:])
    if not volume_valid:
        return dict(returns=returns,atr=atr,advance=advance,persistence=persistence,retention=retention,
            price=price,volume=None,has_advance=has_advance,prior_advance=prior_advance,
            drawdown_atr=dd,retrace=retrace,effective_up_days=effective,close=last['close'],
            median_amount=None,amount_days=0,amount_source=None,volume_valid=False,quality=quality,**observed)
    vbase=median(b['volume'] for b in bs[-21:-1]);vr=last['volume']/vbase
    pairs=list(zip(bs[-11:-1],bs[-10:]))
    up=[b['volume']/vbase for a,b in pairs if b['close']>a['close']]
    down=[b['volume']/vbase for a,b in pairs if b['close']<a['close']]
    participation=quality['volume_participation']
    asym=None
    volume_reference='量价方向：涨跌幅、开盘到收盘结果与收盘位置；近期加权'
    clv=lambda b:(b['close']-b['low'])/(b['high']-b['low']) if b['high']>b['low'] else .5
    result=quality['volume_result']
    contraction=mean(b['volume'] for b in bs[-5:])/mean(b['volume'] for b in bs[-10:-5])
    narrowing=mean(b['high']-b['low'] for b in bs[-5:])/max(mean(b['high']-b['low'] for b in bs[-20:-5]),1e-9)
    prior_support=min(b['low'] for b in prior[-5:])-R['support_buffer_atr']*atr
    contraction_qualified=bool(prior_advance and last['close']>=prior_support and
        dd<=R['pullback_max_atr'] and retrace<=R['retrace_max'] and contraction<=1. and narrowing<=1.2)
    rest=100*(.5*(1-clip((contraction-.5)/1.))+.5*(1-clip((narrowing-.5)/1.))) if contraction_qualified else 0.
    volume=.4*participation+.4*result+.2*rest
    verified=[];amount_sources=set()
    for b in bs[-20:]:
        value=amounts.verified_amount(b,records.get(b['date']))
        if value is None and number(b.get('amount')) and b['amount']>0:
            # 仅接受有明确真实金额标记的同源记录。
            value=b['amount'] if b.get('amount_source') in ('verified_daily','eastmoney_raw_daily') else None
        verified.append(value)
        if value is not None:
            amount_sources.add(records.get(b['date'],{}).get('source') or b.get('amount_source'))
    complete=all(v is not None for v in verified)
    return dict(returns=returns,atr=atr,advance=advance,persistence=persistence,retention=retention,
        price=price,volume=volume,volume_valid=True,volume_participation=participation,volume_reference=volume_reference,volume_up_days=len(up),volume_down_days=len(down),volume_asymmetry=asym,volume_result=result,contraction=contraction,
        has_advance=has_advance,prior_advance=prior_advance,contraction_qualified=contraction_qualified,
        contraction_score=rest,prior_support=prior_support,
        contraction_reference_at=prior[-1]['date'],
        range_contraction=narrowing,volume_ratio=vr,clv=clv(last),drawdown_atr=dd,retrace=retrace,
        effective_up_days=effective,high20=peak,low20=low,close=last['close'],
        median_amount=median(verified) if complete else None,amount_days=sum(v is not None for v in verified),
        amount_source=' / '.join(sorted(s for s in amount_sources if s)) if complete else None,quality=quality,**observed)


def daily_metrics(code, bars, records):
    # Full historical content and rules invalidate this pure completed-day cache.
    key = hashlib.sha256(json.dumps([bars, records, R, QUALITY], sort_keys=True,
        ensure_ascii=False, separators=(',', ':')).encode()).digest()
    cached = _DAILY_METRICS.get(code)
    if cached is None or cached[0] != key:
        cached = (key, base_metrics(bars, records))
        _DAILY_METRICS[code] = cached
    return copy.deepcopy(cached[1])


def assignments(snap,rows):
    import stock_activity
    return stock_activity.industry_groups(snap,sorted(rows))


def market_references(clean,calendar,asof,total):
    days=[d for d in calendar if d<=asof][-26:]
    daily={d:{} for d in days}
    for c,bs in clean.items():
        for a,b in zip(bs,bs[1:]):
            if b['date'] in daily:daily[b['date']][c]=100*(b['close']/a['close']-1)
    return daily


def board_support(code,metrics,clean,groups,assigned,names,cache=None):
    from bisect import bisect_left,bisect_right
    cache=cache if cache is not None else {};identity=assigned.get(code)
    if identity not in cache:
        members=groups.get(identity,[]);valid=[c for c in members if c in metrics]
        cache[identity]=dict(expected=len(members),valid=len(valid),values=sorted(metrics[c]['returns']['5'] for c in valid),
            positives=sum(metrics[c]['returns']['5']>0 for c in valid),
            previous_positives=sum(clean[c][-2]['close']>clean[c][-7]['close'] for c in valid))
    ref=cache[identity];count=ref['valid']-int(code in metrics and identity is not None)
    expected=ref['expected']-int(identity is not None)
    out=dict(industry=names.get(identity),available=False,valid=max(count,0),expected=max(expected,0),label='同行样本较少' if expected<R['min_peers'] else '行业数据不足')
    if count<1 or count/max(expected,1)<R['peer_coverage']:
        return out
    vals=ref['values'];own=metrics[code]['returns']['5'];removed=bisect_left(vals,own)
    def peer_median(n):
        if n<=0:return None
        a=(n-1)//2;b=n//2
        return (vals[a+int(a>=removed)]+vals[b+int(b>=removed)])/2
    med=peer_median(count);breadth=(ref['positives']-int(own>0))/count
    out.update(available=True,median5=med,positive_share=100*breadth,
        ex_top2_median5=peer_median(count-2),excess5=own-med,
        percentile=100*(bisect_left(vals,own)+.5*(bisect_right(vals,own)-bisect_left(vals,own)-1))/count,
        label='板块支持' if med>0 and breadth>=.6 else '板块分化' if med>0 else '逆板块走强' if own>0 else '板块偏弱')
    # 扩散必须有前后可比截面，不能把今天的广度冒充变化。
    if count<R['min_peers']:out.update(available=False,label='同行样本较少')
    out['reference']='同业成员5日收益与上涨广度，剔除本股'
    previous_positive=ref['previous_positives']-int(clean[code][-2]['close']>clean[code][-7]['close'])
    out['breadth_change_pp']=100*(breadth-previous_positive/count)
    return out


def live_status(row,bs,calendar,anchor,frames,now,formal=False,snap=None,completed_breakout_confirmed=False):
    out=dict(state='待报价',available=False,at=row.get('quote_at') or row.get('ts'),risks=[],
             breakout_pending=False,vwap=None,held=False,held_seconds=0,recovery_seconds=None,
             volume_ratio_same_time=None,same_time_volume_reason='同时间历史样本不足，暂停量比判断')
    at=parse_at(out['at']);qday=str(now.date());price=row.get('price')
    if not at or str(at.date())!=qday or not number(price) or price<=0:
        return out
    import closing_price
    proof=closing_price.verify(snap or {},row,bs,calendar,now) if formal else None
    valid,_,reason=market_strength.quote_valid(row,now,'已收盘' if formal else __import__('datafeed').session_label(now),None,formal_close=formal,completed_daily_proof=proof)
    if not valid:
        out.update(state='判断暂停',reason=reason);return out
    ctx=intraday.align_price_basis(row,[b for b in bs if b['date']<qday],calendar,observation_day=qday,allow_partial=True)
    if not ctx.get('valid'):
        out.update(state='口径待核验',reason=ctx.get('reason'));return out
    factor=ctx['scale_factor'];out.update(available=True,state='保持',basis_scale=factor)
    amount=row.get('amount_wan');vol=row.get('volume_shou')
    vwap=100*amount/vol if number(amount) and amount>0 and number(vol) and vol>0 else None
    if vwap and row['low']-.02<=vwap<=row['high']+.02:
        out.update(vwap=vwap,vwap_distance_pct=100*(price/vwap-1))
    ret=100*(price/row['last_close']-1);openret=100*(price/row['open']-1)
    retreat=100*(row['high']-price)/row['high']
    out.update(return_pct=ret,open_return_pct=openret,retreat_pct=retreat)
    bars=[b for b in bs if b['date']<qday]
    if len(bars)<21:return out
    atr=ctx.get('atr20') or 0;threshold=max(b['high'] for b in bars[-20:])*factor+R['breakout_atr']*atr
    points=[]
    for frame_at,frame in frames or []:
        p=frame.get(row['code']);t=parse_at(p.get('at')) if p else None
        if t and at and t.date()==at.date() and 0<=(at-t).total_seconds()<=600 and number(p.get('price')) and p['price']>0:
            points.append((t,p['price']))
    # 当前报价参与同一连续路径；不能拿过旧的尾点冒充当前守稳。
    points=sorted(dict(points+[(at,price)]).items());out['samples']=len(points)
    contiguous=[]
    for point in points:
        if contiguous and (point[0]-contiguous[-1][0]).total_seconds()>R['live_gap_seconds']:contiguous=[]
        contiguous.append(point)
    dip_at=None;was_above=False
    for t,p in contiguous:
        if p>=threshold:
            if dip_at is not None:out['recovery_seconds']=(t-dip_at).total_seconds();dip_at=None
            was_above=True
        elif was_above and dip_at is None:dip_at=t
    if dip_at is not None:out['recovery_seconds']=None
    tail=[]
    for t,p in reversed(points):
        if p<threshold or tail and (tail[-1][0]-t).total_seconds()>R['live_gap_seconds']:break
        tail.append((t,p))
    out['held']=bool(price>=threshold and len(tail)>=R['live_hold_samples'] and (at-tail[-1][0]).total_seconds()>=R['live_hold_seconds'])
    out['held_seconds']=(at-tail[-1][0]).total_seconds() if tail else 0
    out['breakout_pending']=price>=threshold
    out['breakout_price']=threshold
    out['state']='转弱' if ret<=R['live_weak_pct'] else ('价格突破待量价确认' if formal else '突破守稳待收盘' if out['held'] else '瞬时突破待确认') if out['breakout_pending'] else '分歧' if retreat>=2 else '增强' if ret>0 and openret>0 and retreat<1.5 else '整理' if ret<0 else '保持'
    if formal and completed_breakout_confirmed and out['state']!='转弱':out['state']='突破收盘确认'
    out['completed_breakout_confirmed']=bool(formal and completed_breakout_confirmed and out['state']!='转弱')
    if proof:out['completed_daily_proof']=proof
    if anchor and price<anchor['support']*factor:out['state']='结构失守'
    if atr>0 and (price-mean(b['close'] for b in bars[-5:])*factor)/atr>3.5:out['risks'].append('位置偏热')
    if retreat>=2:out['risks'].append('冲高回落')
    if row.get('limit_up') and price>=row['limit_up']-.005:out['risks'].append('涨停，成交受限')
    if row.get('limit_down') and price<=row['limit_down']+.005:out['risks'].append('跌停，成交受限')
    return out


def fund_summary(record,calendar,asof):
    """仅展示有明确交易日的同源资金；不将统计净额混入自身强度。"""
    if record.get('source')!='新浪超大单+大单日级净额':record={}
    dates=[d for d in calendar if d<=asof]
    bydate={r.get('date'):r['main_net'] for r in record.get('rows',[]) if number(r.get('main_net')) and r.get('date','')<=asof}
    out=dict(available=asof in bydate,asof=asof,source=record.get('source'),unit='元',days=sum(d in bydate for d in dates[-20:]),
             main_net=bydate.get(asof),net5=None,net10=None,
             label='资金待补齐',reason=record.get('error') or '资金源未返回目标完成日')
    for n in (5,10):
        dates=[d for d in calendar if d<=asof][-n:]
        if len(dates)==n and all(d in bydate for d in dates):out['net'+str(n)]=sum(bydate[d] for d in dates)
    if out['available']:
        out['label']='完成日净流入' if out['main_net']>0 else '完成日净流出' if out['main_net']<0 else '完成日净额为零'
        out['reason']=None
    return out


def repair_observation(bs, metrics, excess, live, liquid, relative):
    """Completed-day repair evidence; never upgrades current strong eligibility."""
    last=bs[-1]; recent=bs[-5:]
    up=sum(b['close']>a['close'] for a,b in zip(bs[-6:-1],recent))
    local_high=max(b['high'] for b in bs[-6:-1])
    local_drawdown=max(0.,max(b['high'] for b in recent)-last['close'])/metrics['atr']
    support=min(b['low'] for b in recent)
    checks=[dict(name='5日推进%',actual=metrics['returns']['5'],threshold=R['repair_return5'],passed=metrics['returns']['5']>=R['repair_return5']),
        dict(name='5日市场超额百分点',actual=excess['5'],threshold=R['repair_excess5'],passed=relative is not None and excess['5']>=R['repair_excess5']),
        dict(name='5日上涨天数',actual=up,threshold=R['repair_up_days'],passed=up>=R['repair_up_days']),
        dict(name='完成日突破此前5日高点',actual=last['close'],threshold=local_high,passed=last['close']>local_high),
        dict(name='完成日相对历史量',actual=metrics['volume_ratio'],threshold=R['repair_volume_ratio'],passed=metrics['volume_ratio']>=R['repair_volume_ratio']),
        dict(name='完成日收盘位置',actual=metrics['clv'],threshold=R['repair_clv'],passed=metrics['clv']>=R['repair_clv']),
        dict(name='短期高点回撤ATR上限',actual=local_drawdown,threshold=R['repair_drawdown_atr'],passed=local_drawdown<=R['repair_drawdown_atr']),
        dict(name='长期结构仍待修复',passed=metrics['returns']['20']<=0 or metrics['drawdown_atr']>R['repair_drawdown_atr']),
        dict(name='真实流动性',passed=liquid)]
    historical=all(c['passed'] for c in checks)
    # Current disagreement remains visible, but invalid quotes or broken support cannot enter.
    available=live.get('available') is True
    return dict(historical=historical,qualified=historical and available,
        support=support,checks=checks,order=[round(excess['5'],4),round(metrics['returns']['5'],4),round(metrics['clv'],4)],
        note='完成日短期修复证据；非确认强势，今日状态独立展示；研究初值未验证收益')


def build(snap,histories,calendar,previous=None,amount_records=None,frames=None,now=None):
    previous=previous or {};amount_records=amount_records or {};rows=unique_rows(snap)
    fund_records=snap.get('_fund_records',{})
    captured=parse_at(snap.get('quote_capture_at') or snap.get('generated_at')) or datetime.now()
    now=now or captured;day=str(max(captured.date(),now.date()))
    verified=parse_at(snap.get('close_daily_verified_at'))
    formal=bool(snap.get('session')=='已收盘' and verified and verified<=now and
                str(captured.date())==day==str(verified.date()) and day in calendar and now.hour>=15)
    canonical=(snap.get('market_strength_close_input') or {}).get('quotes',{}) if formal else {}
    for c,row in list(rows.items()):
        q=canonical.get(c)
        # 从同快照的原始来源恢复被列表裁剪的口径；报价时间与OHLC必须逐项相同。
        if q and parse_at(q.get('quote_at') or q.get('ts'))==parse_at(row.get('quote_at') or row.get('ts')) and all(q.get(k)==row.get(k) for k in ('price','open','high','low','last_close')):
            rows[c]=dict(row,**q)
        source_at=parse_at(rows[c].get('quote_at') or rows[c].get('ts'))
        rows[c]=dict(rows[c],quote_at=str(source_at) if source_at else None)
    eligible_days=[d for d in calendar if d<=day] if formal else [d for d in calendar if d<day]
    asof=eligible_days[-1] if eligible_days else ''
    clean={};metrics={};errors={}
    for c,row in rows.items():
        bs,reason=clean_bars(histories.get(c,[]),calendar,asof,require_volume=False)
        if reason:errors[c]=reason;continue
        clean[c]=bs;metrics[c]=daily_metrics(c,bs,amount_records.get(c,{}))
    assigned,groups,names=assignments(snap,rows)
    theme_groups={};theme_names={};theme_assignments={c:[] for c in rows};seen_members={}
    for board in snap.get('board_catalog',[]):
        if board.get('type')!='theme':continue
        members=tuple(sorted(set(board.get('member_codes',[]))&set(rows)))
        if len(members)<R['min_peers']+1:continue
        if members in seen_members:
            theme_names[seen_members[members]]+=' / '+board['name'];continue
        identity=board['id'];seen_members[members]=identity;theme_groups[identity]=members;theme_names[identity]=board['name']
        for c in members:theme_assignments[c].append(identity)
    refs=market_references(clean,calendar,asof,len(rows));pastdays=[d for d in calendar if d<=asof][-10:]
    daily_medians={d:median(v.values()) for d,v in refs.items() if len(v)>=len(rows)*R['market_coverage']}
    period_refs={str(n):median(m['returns'][str(n)] for m in metrics.values()) for n in R['periods']} if metrics else {}
    coverage=len(metrics)/max(len(rows),1);benchmark_ok=coverage>=R['market_coverage']
    state={};items={};industry_cache={};theme_cache={}
    for c,row in rows.items():
        m=dict(code=c,name=row.get('name',c),score=None,rank=None,dimensions=dict(price=None,relative=None,volume=None),
            eligible=False,list_name='pending',pattern='待核验',daily_at=asof,quote_at=row.get('quote_at'),
            reasons=[],risks=[],gates=[],data_status='数据待核验',board={},fund=fund_summary(fund_records.get(c,{}),calendar,asof),
            quote=dict(price=row.get('price'),change_pct=row.get('change_pct'),amount=row.get('amount_wan')*10000 if number(row.get('amount_wan')) else None,at=row.get('quote_at') or row.get('ts')),
            evidence={},intraday=dict(state='待报价',available=False),anchor=None)
        items[c]=m
        if c not in clean:
            proof=(snap.get('_gap_proofs') or {}).get(c) or {}
            m['evidence']['history_gap']=proof
            if proof.get('asof')==asof and proof.get('halted_dates'):
                m['pattern']='停复牌观察';m['data_status']='停牌日已核验'
                m['reasons']=['最近26个市场交易日含已核验停牌日 '+ ' / '.join(proof['halted_dates'])+'；当前周期不满足连续成交窗口']
            elif proof.get('asof')==asof and proof.get('ipo_date') and proof['ipo_date']>calendar[-R['min_bars']]:
                m['pattern']='新股观察';m['data_status']='上市历史不足'
                m['reasons']=['上市日 '+proof['ipo_date']+'；实际历史 '+str(proof.get('rows',0))+' 根，尚不足26根']
            else:m['reasons']=[errors[c]]
            state[c]=copy.deepcopy(previous.get('items',{}).get(c,{}));continue
        bs=clean[c];b=bs[-1];x=metrics[c];excess={str(n):x['returns'][str(n)]-period_refs[str(n)] for n in R['periods']}
        aligned_daily=[]
        for d in pastdays:
            values=refs[d]
            if d not in daily_medians or c not in values:break
            aligned_daily.append(values[c]-daily_medians[d])
        relative=None
        if benchmark_ok and len(aligned_daily)==10:
            strength=sum(w*scale(excess[str(n)],f) for w,n,f in zip(R['period_weights'],R['periods'],R['excess_scales']))
            beats=sum(v>0 for v in aligned_daily)/10
            acceleration=sum(aligned_daily[-5:])-sum(aligned_daily[:5])
            relative=.60*strength+.25*100*beats+.15*scale(acceleration+2,6)
        m['dimensions']=dict(price=round(x['price'],2),relative=round(relative,2) if relative is not None else None,volume=round(x['volume'],2) if x['volume'] is not None else None)
        m['evidence']=dict(x,market_returns=period_refs,excess=excess,market_coverage=coverage,daily_excess=aligned_daily,
                           amount_estimated=False,metrics_at=asof)
        m['board']=board_support(c,metrics,clean,groups,assigned,names,industry_cache)
        m['themes']=[board_support(c,metrics,clean,theme_groups,{c:i},theme_names,theme_cache) for i in theme_assignments[c]]
        from stock_selection_factors import attach_observations
        attach_observations(m,bs,records=amount_records.get(c,{}),fund_record=fund_records.get(c,{}),
                            refs=refs,daily_medians=daily_medians,calendar=calendar)
        if not x['volume_valid']:
            m['data_status']='成交量待核验';m['reasons'].append('价格与相对强度保留；成交量缺失，总分与入选判断暂停')
            m['intraday']=live_status(dict(row,code=c),bs,calendar,None,frames,now,formal,snap)
            state[c]=copy.deepcopy(previous.get('items',{}).get(c,{}));continue
        old=copy.deepcopy(previous.get('items',{}).get(c,{}));anchor=old.get('anchor')
        from stock_selection_factors import board_continuity
        board_observation=board_continuity(m['board'],old.get('board_observation'),asof,
            calendar,groups.get(assigned.get(c),[])) if not snap.get('_historical_replay') else None
        # 历史修订/除权时用相同日期收盘换算锚点；不可找到参照时暂停锚点判断。
        if anchor:
            basis=next((v for v in bs if v['date']==anchor['basis_date']),None)
            if basis:
                ratio=basis['close']/anchor['basis_close']
                for key in ('support','peak','base','atr','breakout_level'):anchor[key]*=ratio
                anchor['basis_close']=basis['close']
            else:
                m['reasons'].append('历史锚点参照缺失');anchor=None
        liquid=x['median_amount'] is not None and x['median_amount']>=R['amount_min']
        liquidity='通过' if liquid else '流动性不足' if x['median_amount'] is not None else '真实成交额待补齐'
        # 数据质量与不满足门槛分别记录；不以估算金额通过流动性资格。
        m['gates']=[dict(name='真实成交额20日中位数',actual=x['median_amount'],threshold=R['amount_min'],passed=liquid,status=liquidity)]
        if relative is None:
            m['reasons'].append('市场可比历史覆盖不足');m['data_status']='市场基准待核验'
        else:
            m['score']=round(sum(R['weights'][k]*m['dimensions'][k] for k in R['weights']),2)
            m['list_name']='watch';m['data_status']='有效' if liquid else liquidity
        advances=any(x['returns'][str(n)]>=cut and excess[str(n)]>0 for n,cut in zip(R['periods'],R['advance_min']))
        sustained=m['score'] is not None and m['score']>=R['strong_score'] and x['price']>=R['price_floor'] and advances and x['drawdown_atr']<=3.5
        prior=bs[-21:-1];level=max(z['high'] for z in prior)
        price_break=b['close']>=level+R['breakout_atr']*x['atr']
        volume_confirm=x['volume_ratio']>=R['breakout_volume']
        old_break=old.get('breakout') or {}
        if old_break and old_break.get('basis_date'):
            basis=next((z for z in bs if z['date']==old_break['basis_date']),None)
            if basis:
                ratio=basis['close']/old_break['basis_close'];old_break['level']*=ratio;old_break['basis_close']=basis['close']
            else:old_break={}
        held_break=bool(old_break and not old_break.get('volume_confirmed') and
                        len([d for d in calendar if old_break['date']<d<=asof])==1 and
                        b['close']>=old_break.get('level',math.inf))
        breakout=(price_break and x['clv']>=R['breakout_clv'] and volume_confirm) or held_break
        breakout_record=(dict(date=asof,level=level+R['breakout_atr']*x['atr'],volume_confirmed=volume_confirm,
                             basis_date=asof,basis_close=b['close']) if price_break and x['clv']>=R['breakout_clv']
                         else old_break if held_break else None)
        support_lost=bool(anchor and b['close']<anchor['support'])
        last_strong=old.get('last_strong_at',anchor.get('created_at') if anchor else None)
        strong_age=len([d for d in calendar if last_strong and last_strong<d<=asof])
        rest=bool(anchor and anchor.get('status')!='invalid' and strong_age<=R['recent_strong_days'] and not support_lost and x['drawdown_atr']<=R['pullback_max_atr'] and
                  (anchor['peak']-b['close'])/max(anchor['peak']-anchor['base'],anchor['atr'])<=R['retrace_max'] and
                  x['contraction']<=1. and x['range_contraction']<=1.2)
        restart=bool(anchor and rest and b['close']>max(z['high'] for z in bs[-4:-1])+.2*x['atr'] and volume_confirm)
        if support_lost:
            m['pattern']='结构失效';m['risks'].append('跌破冻结支撑');anchor['status']='invalid'
        elif anchor and anchor.get('status')=='invalid':
            m['pattern']='结构失效'
        elif restart:m['pattern']='再启动'
        elif rest and not sustained:m['pattern']='强势整理'
        elif breakout:m['pattern']='突破启动'
        elif sustained:m['pattern']='持续推进'
        elif price_break:m['pattern']='突破待确认'
        else:m['pattern']='普通观察'
        qualifies=(sustained or breakout or rest or restart) and not support_lost
        if anchor and anchor.get('status')=='invalid':
            if (sustained or breakout) and asof>anchor.get('invalid_at',asof):
                anchor=None;m['pattern']='突破启动' if breakout else '持续推进'
            else:qualifies=False
        if sustained or breakout:
            if not anchor:
                anchor=dict(created_at=asof,basis_date=asof,basis_close=b['close'],support=min(z['low'] for z in bs[-5:])-.3*x['atr'],
                            peak=b['high'],base=min(z['low'] for z in bs[-20:]),atr=x['atr'],breakout_level=level,status='active',
                            origin='完成日历史重建，非当时实测' if snap.get('_historical_replay') else '实际运行识别')
            elif anchor.get('status')!='invalid':
                anchor['peak']=max(anchor['peak'],b['high'])
        if support_lost:anchor['invalid_at']=asof
        m['anchor']=anchor
        m['intraday']=live_status(dict(row,code=c),bs,calendar,anchor,frames,now,formal,snap,completed_breakout_confirmed=bool(breakout and qualifies))
        m['risks']+=m['intraday'].get('risks',[])
        if m['intraday'].get('state')=='结构失守':
            qualifies=False;m['risks'].append('当前报价失守冻结支撑')
        if m['intraday'].get('state')=='转弱':
            qualifies=False;m['reasons'].append('历史强势，今日转弱')
        live_start=(not formal and m['intraday'].get('breakout_pending') and
                    m['intraday'].get('return_pct',0)>0 and m['intraday'].get('open_return_pct',-1)>=0 and
                    m['intraday'].get('retreat_pct',99)<2 and m['intraday'].get('state')!='结构失守')
        if live_start and not qualifies:
            qualifies=True;m['pattern']='盘中突破待确认'
            m['reasons'].append('现价突破已完成日高点；正式日线及量能待收盘确认')
        if qualifies and relative is not None:
            if liquid:
                m['eligible']=True;m['list_name']='consolidation' if m['pattern']=='强势整理' else 'breakout' if m['pattern'] in ('突破启动','再启动','盘中突破待确认') else 'strong'
            elif x['median_amount'] is None:m['list_name']='pending'
            else:m['list_name']='excluded'
        elif relative is not None and x['median_amount'] is not None and not liquid:m['list_name']='excluded'
        if not m['eligible']:
            if qualifies and not liquid:m['reasons'].append(liquidity)
            elif not qualifies:m['reasons'].append('未满足持续推进、突破或强势整理路径')
        m['historical_qualified']=bool(qualifies and relative is not None and liquid)
        if not m['intraday'].get('available') and not snap.get('_historical_replay'):
            m['eligible']=False
            if m['list_name']!='excluded':m['list_name']='pending'
            m['data_status']='当前成交待核验'
            m['reasons'].append('当前报价或真实成交不可核验；保留完成日强度，暂停当前入选')
        repair=repair_observation(bs,x,excess,m['intraday'],liquid,relative)
        current_support=repair['support']*m['intraday'].get('basis_scale',1.)
        repair['qualified']=bool(repair['qualified'] and number(row.get('price')) and row['price']>=current_support
            and m['intraday'].get('state') not in ('结构失守','转弱') and not support_lost)
        repair['current_support']=current_support
        m['repair_observation']=repair
        m['observation_only']=bool(repair['qualified'] and not m['eligible'])
        m['startup_order']=repair['order']
        if m['observation_only']:
            m['list_name']='repair';m['pattern']='短期修复转强观察'
            m['reasons']=[r for r in m['reasons'] if r!='未满足持续推进、突破或强势整理路径']
            m['reasons'].append('短期修复路径通过；尚未满足原有强势路径，今日状态单独判断')
        from stock_selection_factors import pattern_order
        m['pattern_order']=pattern_order(m)
        if m['eligible']:m['reasons'].append(m['pattern']+'路径通过；价格、相对强度和量价分别可核验')
        m['gates']+= [dict(name='持续推进',passed=sustained),dict(name='突破确认',passed=breakout),
                      dict(name='强势整理',passed=rest),dict(name='再启动',passed=restart),dict(name='盘中突破待确认',passed=bool(live_start))]
        state[c]=dict(board_observation=board_observation,anchor=anchor,breakout=breakout_record,last_daily_at=asof,pattern=m['pattern'],
                      last_strong_at=asof if sustained or breakout else last_strong)
    order=sorted(items,key=lambda c:(items[c]['score'] is None,-(items[c]['score'] or 0),c))
    for i,c in enumerate([c for c in order if items[c]['score'] is not None],1):items[c]['rank']=i+0
    counts={k:sum(m['list_name']==k for m in items.values()) for k in ('strong','breakout','consolidation','repair','watch','pending','excluded')}
    quote_times=sorted(str(r.get('quote_at') or r.get('ts')) for r in rows.values() if parse_at(r.get('quote_at') or r.get('ts')))
    model=dict(version=VERSION,implementation_hash=IMPLEMENTATION_HASH,day=day,daily_at=asof,source_at=quote_times[len(quote_times)//2] if quote_times else None,
        captured_at=str(now),mode='收盘确认' if formal else '收盘待核验' if snap.get('session')=='已收盘' and now.hour>=15 else '盘中观察',close_finalized=formal,rules=dict(copy.deepcopy(R),quality=copy.deepcopy(QUALITY)),items=items,order=order,
        counts=counts,pool_count=len(rows),coverage=dict(daily=len(clean),market=round(coverage,4),amount_complete=sum(m['evidence'].get('amount_days')==20 for m in items.values()),fund_latest=sum(m['fund']['available'] for m in items.values()),fund20=sum(m['fund']['days']==20 for m in items.values())),
        _state=dict(version=VERSION,day=day,daily_at=asof,items=state))
    model['result_version']=hashlib.sha256(json.dumps(model,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]
    return model


def input_revision():
    names = ['market.db', 'market.db-wal', 'stock_selection_v3/amounts.db',
             'stock_selection_v3/amounts.db-wal', 'fund_history/sina_main.json',
             'stock_selection_v3/security_master.json', 'stock_selection_v3/history_gap_verification.json',
             'stock_selection_v3/rollout.json']
    result = {}
    for name in names:
        path = config.CACHE_DIR / name
        if path.exists():
            stamp = path.stat()
            result[name] = [stamp.st_mtime_ns, stamp.st_size]
    return result


def catalog_revision(snap):
    rows = unique_rows(snap)
    context = [sorted((c, r.get('name'), r.get('industry'), r.get('industry_detail')) for c, r in rows.items()),
               [{k: b.get(k) for k in ('id', 'name', 'type', 'member_codes')} for b in snap.get('board_catalog', [])]]
    return hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def quote_revision(source, now):
    fields = ('price', 'open', 'high', 'low', 'last_close', 'amount_wan', 'volume_shou',
              'limit_up', 'limit_down', 'change_pct', 'price_basis', 'price_basis_source', 'last_close_semantics',
              'last_close_precision_digits')
    session = __import__('datafeed').session_label(now)
    rows = []
    for code, row in sorted(unique_rows(source).items()):
        valid, at, reason = market_strength.quote_valid(row, now, session, None)
        rows.append([code, str(at) if at else None, valid, reason] + [row.get(k) for k in fields])
    content = [source.get('session'), session, source.get('close_daily_verified_at'), rows]
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def path_revision(now):
    paths = [intraday.HISTORY_DIR / 'acquisitions', config.CACHE_DIR / 'stock_activity_samples' / 'acquisitions']
    result = {}
    for folder in paths:
        path = folder / (str(now.date()) + '.jsonl.gz')
        if path.exists():
            stat = path.stat()
            result[str(path)] = [stat.st_mtime_ns, stat.st_size]
    return result


def history_revision(histories, calendar):
    return hashlib.sha256(json.dumps([histories, calendar], sort_keys=True,
        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def page_model(snap):
    """个股结果异常不阻止其他页面发布；失败以明确待核验结果表示。"""
    try:
        import closing_price
        captured = parse_at(snap.get('quote_capture_at') or snap.get('generated_at')) or datetime.now()
        assessment = closing_price.assessment_time(snap, captured)
        return refresh_projection(snap, now=assessment, shared=True)
    except Exception as exc:
        import logging
        logging.exception('个股强度V3发布失败')
        rows=unique_rows(snap)
        return dict(version=VERSION,implementation_hash=IMPLEMENTATION_HASH,result_version='unavailable',
            day=str(snap.get('quote_capture_at',''))[:10],daily_at=None,source_at=None,captured_at=str(datetime.now()),
            close_finalized=False,rules=copy.deepcopy(R),pool_count=len(rows),order=sorted(rows),
            counts=dict(strong=0,breakout=0,consolidation=0,watch=0,pending=len(rows),excluded=0),
            error=type(exc).__name__+': '+str(exc),items={c:dict(code=c,name=r.get('name',c),score=None,rank=None,
                dimensions=dict(price=None,relative=None,volume=None),eligible=False,list_name='pending',pattern='待核验',daily_at=None,
                reasons=['本轮模型计算失败，判断暂停'],risks=[],data_status='数据待核验',board={},fund=dict(label='未启用'),
                evidence={},anchor=None,intraday=dict(state='判断暂停',available=False,at=None)) for c,r in rows.items()})


def inputs(snap):
    import datafeed
    rows=unique_rows(snap)
    con=sqlite3.connect('file:'+config.KLINE_DB.as_posix()+'?mode=ro',uri=True)
    try:histories={c:datafeed.load_kline(con,'kline','code',c,limit=100) for c in rows}
    finally:con.close()
    dates={}
    for bs in histories.values():
        for b in bs:dates[b['date']]=dates.get(b['date'],0)+1
    calendar=sorted(d for d,n in dates.items() if n>=len(rows)*.5)
    return histories,calendar


def refresh_projection(snap=None,now=None,bootstrap=False,shared=False):
    import stock_activity
    import stock_selection_rollout as rollout
    now=now or datetime.now()
    with _LOCK,stock_activity.projection_owner():
        source=snap if snap is not None else json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf8'))
        if not shared:
            source=stock_activity.live_view(source,now=now)
        import fund_history
        revision = input_revision()
        master=read('security_master.json')
        original=unique_rows(source)
        source=dict(source,_fund_records=fund_history.load(),_security_master=master.get('stocks',{}),_universe_at=str(now.date()),_gap_proofs=read('history_gap_verification.json'))
        current_rows = unique_rows(source)
        exclusions=[dict(code=c,name=r.get('name'),security=master.get('stocks',{}).get(c),
                         reason='已退市或已合并' if master.get('stocks',{}).get(c,{}).get('outDate') else '未在已核验证券主表中上市')
                    for c,r in original.items() if c not in current_rows]

        histories,calendar=inputs(source)
        at=parse_at(source.get('quote_capture_at')) or datetime.now()
        # 最近采样只作盘中守稳证据，不参与完成日分数。
        frame_revision = path_revision(now)
        since = None
        if read('rollout.json').get('stage') == 'live':
            # live_status only consumes the preceding 600 seconds of each valid
            # source clock. Include the archive's allowed positive clock offset.
            clocks = [stamp for row in current_rows.values()
                      if (check := market_strength.quote_valid(row, now, source.get('session'), None))[0]
                      and (stamp := check[1]) is not None]
            if clocks:
                since = min(clocks) - timedelta(seconds=600 + stock_activity.RULES['quote_clock_error_max'])
        frames=stock_activity.archive_frames(at,set(current_rows),since=since) if source.get('session')!='已收盘' else []
        production_previous=read('state.json')
        previous={} if bootstrap else rollout.candidate_state(production_previous)
        amounts.save_close_quotes(source,histories,calendar,now)
        revision=input_revision()  # Include verified close amounts written by this publication.
        records=amounts.load()
        if not previous and len(calendar)>40:
            # 首次上线只重建日线结构锚点；不回填盘中事件或历史核心身份。
            for d in calendar[-R['recent_strong_days']-1:-1]:
                if d>=str(at.date()):continue
                seed=dict(source,quote_capture_at=d+' 15:00:00',session='已收盘',close_daily_verified_at=d+' 16:00:00',_historical_replay=True,board_catalog=[])
                previous=build(seed,histories,calendar,previous,records,now=parse_at(d+' 16:00:00'))['_state']
        model=build(source,histories,calendar,previous,records,frames,now=now)
        if shared:
            model['source_round_at'] = source.get('quote_capture_at')
            model['refresh_policy'] = 'shared-round-5m-v1'
        import stock_selection_intraday
        stock_selection_intraday.attach(model,source,calendar)
        import stock_selection_turning
        stock_selection_turning.attach(model,source,histories,calendar,previous,frames,now=datetime.now())
        stock_selection_turning.persist_events(model)
        model['result_version']=hashlib.sha256(json.dumps({k:v for k,v in model.items() if k!='result_version'},ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]
        model=rollout.project(model,source,histories,calendar,records,frames,now,production_previous)
        model['catalog_revision'] = catalog_revision(source)
        model['input_revision'] = revision
        model['projection_quote_revision'] = quote_revision(source, now)
        model['projection_path_revision'] = frame_revision
        model['history_revision'] = history_revision(histories, calendar)
        model['universe_exclusions']=exclusions
        model['security_master_at']=master.get('observed_at')
        state=model.pop('_state');folder().mkdir(parents=True,exist_ok=True)
        config.atomic_write_text(folder()/'state.json',json.dumps(state,ensure_ascii=False,separators=(',',':')))
        text=json.dumps(model,ensure_ascii=False,separators=(',',':'))
        config.atomic_write_text(folder()/'latest.json',text)
        if model['close_finalized'] and model['day']==model['daily_at']:
            config.atomic_write_text(folder()/('close-'+model['daily_at']+'.json'),text)
        # 保存当时股票池和成员，支持之后真实样本外研究。
        membership=dict(day=model['day'],observed_at=str(datetime.now()),codes=sorted(current_rows),
            boards=[{k:b.get(k) for k in ('id','name','type','member_codes')} for b in source.get('board_catalog',[])])
        config.atomic_write_text(folder()/('members-'+model['day']+'.json'),json.dumps(membership,ensure_ascii=False,separators=(',',':')))
        return model


if __name__=='__main__':
    m=refresh_projection();print(json.dumps({k:m[k] for k in ('version','daily_at','counts','coverage','result_version')},ensure_ascii=False))
