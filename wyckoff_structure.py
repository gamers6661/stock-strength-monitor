"""独立量价结构观察：固定整理周期，不改进攻分、名单或旧整理状态。"""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
import math
from statistics import mean, median

import config
import intraday
import intraday_path
import trend_consolidation

VERSION = '量价结构观察1'
DIRECTORY = config.CACHE_DIR / 'wyckoff_structure_v1'
STATE_FILE = DIRECTORY / 'state.json'
LABELS = {'consolidating':'固定平台整理', 'price_breakout':'收盘价格突破，量能确认不足',
          'volume_breakout':'收盘量价突破', 'retest_confirmed':'突破后缩量回测并再上行',
          'closed':'结构失效', 'expired':'整理观察到期'}

def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

def positive(v):
    return number(v) and v > 0

def parameters():
    return config.WYCKOFF_STRUCTURE

def tr(b, previous):
    return max(b['high']-b['low'], abs(b['high']-previous['close']),
               abs(b['low']-previous['close']))

def checked(history, asof, calendar, required=21):
    bars = sorted((dict(b) for b in history if str(b.get('date','')) <= asof), key=lambda b:b['date'])
    dates = [d for d in calendar if d <= asof][-required:]
    if not dates or dates[-1] != asof or len(dates) < required:
        return None, '完成交易日窗口不足'
    if len({b['date'] for b in bars}) != len(bars) or [b['date'] for b in bars[-required:]] != dates:
        return None, '完成日线缺口、重复或日期未对齐'
    window = bars[-required:]
    allowed = {('qfq',s) for s in intraday._QFQ_HISTORY_SOURCES} | {('raw',s) for s in intraday._RAW_HISTORY_SOURCES}
    modes = {(b.get('price_basis'),b.get('price_basis_source')) for b in window}
    if len(modes) != 1 or not modes.issubset(allowed):
        return None, '价格来源或复权方式待核验'
    if not all(intraday._valid_historical_price_bar(b) for b in window):
        return None, '完成日OHLC价格无效'
    return bars, None

def create_cycle(code, history, asof, calendar, observed_at, setup=None, price_factor=None):
    bars, issue = checked(history, asof, calendar, 40)
    if issue:
        return None, issue
    setup = setup or trend_consolidation._daily_setup(bars, asof, calendar)
    if not setup.get('eligible') or setup.get('phase') != 'consolidating':
        return None, setup.get('reason') or '未形成合格整理'
    volume = [b.get('volume') for b in bars[-20:]]
    a = mean(tr(bars[i], bars[i-1]) for i in range(len(bars)-20,len(bars)))
    if not positive(a):
        return None, '完整ATR20不可用'
    tick0=(parameters()['price_tick'] / price_factor if positive(price_factor) else
           parameters()['price_tick'] if bars[-1]['price_basis']=='raw' else None)
    if tick0 is None:
        return None, '首次识别时报价与历史价格单位待核验'
    # 存在源价格与原始单位，不用未来复权历史重写首次识别的证据。
    origin = [{k:b.get(k) for k in ('date','open','high','low','close','price_basis','price_basis_source')}
              for b in bars[-21:]]
    cycle = dict(version=VERSION, code=code, cycle_id=code+'|'+setup['consolidation_start']+'|'+asof,
                 created_asof=asof, created_at=observed_at, last_processed_asof=asof,
                 consolidation_start=setup['consolidation_start'], impulse_end=setup['impulse_end'],
                 platform_high=setup['platform_high'], platform_low=setup['platform_low'],
                 atr0=a, tick0=tick0, volume0=median(volume) if all(positive(v) for v in volume) else None,
                 volume0_dates=[b['date'] for b in bars[-20:]], origin=origin,
                 state='consolidating', attempts=[], events=[], below_upper_days=0,
                 closed_asof=None, pending_reason=None, reviewed_at=observed_at,
                 price_scale_factor=1.0)
    update_contraction(cycle,bars)
    return cycle, None

def update_contraction(cycle, bars):
    rise = [b for b in bars if b['date'] <= cycle['impulse_end']][-5:]
    quiet = [b for b in bars if cycle['consolidation_start'] <= b['date'] <= cycle['last_processed_asof']][-3:]
    indexed = {b['date']:i for i,b in enumerate(bars)}
    ratio = contraction = None
    if len(quiet)==3 and rise and all(positive(b.get('volume')) for b in rise+quiet):
        ratio = median(b['volume'] for b in quiet)/median(b['volume'] for b in rise)
    if len(quiet)==3 and rise and all(indexed[b['date']] > 0 for b in rise+quiet):
        rv = median(tr(b,bars[indexed[b['date']]-1]) for b in rise)
        if rv > 0:
            contraction = median(tr(b,bars[indexed[b['date']]-1]) for b in quiet)/rv
    p=parameters()
    cycle.update(shrink_ratio=ratio, contraction_ratio=contraction,
                 contraction_confirmed=ratio is not None and contraction is not None and
                    ratio <= p['shrink_ratio'] and contraction <= p['contraction_ratio'])

def align_origin(cycle, bars):
    bydate={b['date']:b for b in bars}
    ratios=[]
    for old in cycle['origin']:
        current=bydate.get(old['date'])
        if not current:
            return None,None,'原整理价格尺度缺少对应历史'
        if (current.get('price_basis'),current.get('price_basis_source')) != (old['price_basis'],old['price_basis_source']):
            return None,None,'原整理与当前历史来源或复权方式变化'
        for k in ('open','high','low','close'):
            if not positive(current.get(k)) or not positive(old.get(k)):
                return None,None,'原整理价格尺度无效'
            ratios.append(current[k]/old[k])
    factor=median(ratios)
    # 只有整窗可确认的同比例变化才能换算；加法调整、历史修订不能猜测。
    if any(abs(r/factor-1)>parameters()['scale_tolerance'] for r in ratios):
        return None,None,'原整理历史发生非同比例变化，暂停结构判断'
    normalized=[]
    for b in bars:
        copied=dict(b)
        for k in ('open','high','low','close'):
            if positive(copied.get(k)): copied[k]/=factor
        normalized.append(copied)
    return normalized,factor,None

def event(cycle,kind,day,observed_at,**evidence):
    cycle['events'].append(dict(kind=kind, day=day, observed_at=observed_at, **evidence))

def review_daily(previous, history, asof, calendar, observed_at):
    cycle=deepcopy(previous)
    if cycle.get('version') != VERSION:
        raise ValueError('禁止混用其他结构版本')
    if asof < cycle['last_processed_asof']:
        cycle['pending_reason']='完成日线日期回退，保留已有事实'
        return cycle
    if cycle['state'] in ('closed','expired'):
        return cycle
    bars, issue=checked(history,asof,calendar)
    if not issue:
        bars,factor,issue=align_origin(cycle,bars)
    if issue:
        cycle['pending_reason']=issue
        return cycle
    newdates=[d for d in calendar if cycle['last_processed_asof'] < d <= asof]
    bydate={b['date']:b for b in bars}
    if any(d not in bydate for d in newdates):
        cycle['pending_reason']='结构跟踪期间存在应有交易日缺口'
        return cycle
    cycle.update(pending_reason=None, price_scale_factor=factor, reviewed_at=observed_at)
    p=parameters(); a=cycle['atr0']; u=cycle['platform_high']; l=cycle['platform_low']
    # 日线在冻结源尺度上计算；最小变动单位同步转换，不能固定按复权后的0.01比较。
    eps=max(p['breakout_buffer_atr']*a,cycle['tick0'])
    for day in newdates:
        i=next(j for j,b in enumerate(bars) if b['date']==day)
        if i<20:
            cycle['pending_reason']='结构后续MA20窗口不足'; break
        b=bars[i]; prev=bars[i-1]
        window=bars[i-20:i+1]
        if (not all(intraday._valid_historical_price_bar(x) for x in window) or
                len({(x.get('price_basis'),x.get('price_basis_source')) for x in window}) != 1 or
                [x['date'] for x in window] != [d for d in calendar if d<=day][-21:]):
            cycle['pending_reason']='结构后续完整日线窗口待核验'; break
        cycle['last_processed_asof']=day
        ma20=mean(x['close'] for x in window[-20:])
        if b['close'] < l-p['failure_buffer_atr']*a or b['close'] < ma20:
            why='正式收盘失守MA20' if b['close'] < ma20 else '收盘跌穿原平台下沿缓冲'
            cycle.update(state='closed',closed_asof=day,close_reason=why)
            event(cycle,'structure_closed',day,observed_at,reason=why,close=b['close'],ma20=ma20)
            break
        active=cycle['attempts'][-1] if cycle['attempts'] and not cycle['attempts'][-1].get('failed_at') else None
        if active:
            cycle['below_upper_days']=cycle['below_upper_days']+1 if b['close']<u else 0
            if b['close'] < u-p['failure_buffer_atr']*a or cycle['below_upper_days'] >= 2:
                active['failed_at']=day
                event(cycle,'breakout_failed',day,observed_at,attempt_id=active['id'],close=b['close'])
                cycle.update(state='consolidating',below_upper_days=0)
                active=None
        if b['high']>u+eps and b['close']<u:
            event(cycle,'upper_rejection',day,observed_at,high=b['high'],close=b['close'])
        spread=b['high']-b['low']
        clv=(b['close']-b['low'])/spread if spread>0 else None
        v0=cycle['volume0']
        volume_ratio=b['volume']/v0 if positive(v0) and positive(b.get('volume')) else None
        full=(b['close']>u+eps and b['close']>prev['close'] and clv is not None and
              clv>=p['close_location_min'] and volume_ratio is not None and volume_ratio>=p['breakout_volume_ratio'])
        if not active and b['close']>u+eps:
            active=dict(id=cycle['cycle_id']+':'+str(len(cycle['attempts'])+1),
                        price_at=day, price_close=b['close'], volume_at=None,
                        breakout_volume=None,retest=None,failed_at=None)
            cycle['attempts'].append(active)
            cycle['state']='price_breakout'
            event(cycle,'price_breakout',day,observed_at,attempt_id=active['id'],close=b['close'],
                  clv=clv,volume_ratio=volume_ratio,volume_status='待核验' if volume_ratio is None else '未达确认条件')
        if active and not active['volume_at'] and full:
            preceding=[x for x in bars if x['date']<day][-3:]
            base_spread=median(x['high']-x['low'] for x in preceding) if preceding else None
            active.update(volume_at=day,breakout_volume=b['volume'],volume_close=b['close'],
                          volume_ratio=volume_ratio,close_location=clv,breakout_spread=spread,
                          preceding_spread=base_spread,
                          sos_features=bool(positive(base_spread) and spread>=p['sos_spread_ratio_min']*base_spread))
            cycle['state']='volume_breakout'
            event(cycle,'volume_breakout',day,observed_at,attempt_id=active['id'],
                  close=b['close'],volume_ratio=volume_ratio,clv=clv)
        if active and active['volume_at'] and day>active['volume_at']:
            age=len([d for d in calendar if active['volume_at']<d<=day])
            test=active['retest']
            if test is None and age<=p['retest_touch_days'] and u-p['retest_band_atr']*a<=b['low']<=u+p['retest_band_atr']*a:
                test=dict(touch_at=day,low=b['low'],high=b['high'],status='waiting',confirmed_at=None)
                active['retest']=test
                event(cycle,'retest_touch',day,observed_at,attempt_id=active['id'],low=b['low'])
            elif test and test['status']=='waiting' and day>test['touch_at']:
                test_age=len([d for d in calendar if test['touch_at']<d<=day])
                if b['low']<test['low']-p['retest_low_buffer_atr']*a:
                    test['status']='damaged'
                    event(cycle,'retest_damaged',day,observed_at,attempt_id=active['id'])
                elif test_age>p['retest_confirm_days']:
                    test['status']='expired'
                    event(cycle,'retest_expired',day,observed_at,attempt_id=active['id'])
                elif b['close']>test['high']+eps and b['close']>=u:
                    # 上行确认日允许放量；缩量只检查它之前真正的回测交易日。
                    testbars=[x for x in bars if test['touch_at']<=x['date']<day]
                    vv=[x.get('volume') for x in testbars]
                    reduced=bool(vv) and all(positive(v) for v in vv) and (
                        median(vv)<=p['retest_volume_ratio']*active['breakout_volume'] and median(vv)<=v0)
                    test['volume_status']='可比但未缩量' if vv and all(positive(v) for v in vv) else '待核验'
                    if reduced:
                        test_spread=median(x['high']-x['low'] for x in testbars)
                        test.update(status='confirmed',confirmed_at=day,test_volume=median(vv),volume_status='缩量确认',
                                    test_spread=test_spread,
                                    lps_features=bool(active.get('sos_features') and positive(active.get('breakout_spread')) and
                                                      test_spread<=p['lps_spread_ratio_max']*active['breakout_spread']))
                        cycle['state']='retest_confirmed'
                        event(cycle,'retest_confirmed',day,observed_at,attempt_id=active['id'],
                              test_dates=[x['date'] for x in testbars],test_volume=median(vv),close=b['close'])
            elif test is None and age>p['retest_touch_days'] and not active.get('no_retest_at'):
                active['no_retest_at']=day
                event(cycle,'no_retest',day,observed_at,attempt_id=active['id'])
        if volume_ratio is not None and volume_ratio>=p['stall_volume_ratio'] and (
                tr(b,prev)<=p['stall_range_atr']*a and abs(b['close']-prev['close'])<=p['stall_move_atr']*a):
            event(cycle,'volume_stall',day,observed_at,volume_ratio=volume_ratio,close=b['close'])
        duration=len([d for d in calendar if cycle['consolidation_start']<=d<=day])
        if not active and duration>p['max_setup_days']:
            cycle.update(state='expired',closed_asof=day,close_reason='原整理超过12个完成交易日')
            event(cycle,'setup_expired',day,observed_at)
            break
    update_contraction(cycle,bars)
    return cycle

def display_cycle(cycle, row, context, points, session, observed_at):
    p=parameters(); factor=cycle.get('price_scale_factor',1.0)
    terminal=cycle['state'] in ('closed','expired')
    # 关闭周期不再追踪后续复权变化；待核验周期也不能借旧比例展示新报价边界。
    live_factor=(factor*context['scale_factor'] if context.get('valid') is True and
                 positive(context.get('scale_factor')) and not terminal and
                 not cycle.get('pending_reason') else None)
    normal=session in ('早盘','午盘','尾盘')
    valid=normal and row.get('intraday_quote_fresh') is True and context.get('valid') is True and not cycle.get('pending_reason') and positive(live_factor) and positive(row.get('price'))
    price=row.get('price'); upper=cycle['platform_high']*live_factor if live_factor else None
    eps=max(p['breakout_buffer_atr']*cycle['atr0']*live_factor,p['price_tick']) if live_factor else None
    samples=0; last_at=None
    if valid and not terminal:
        current=dict(at=row.get('intraday_judgment_at') or row.get('intraday_quote_at'),
                     price=price,valid=True)
        sequence=[]; watermark=''
        for point in list(points)+[current]:
            at=str(point.get('at') or '')
            if not at or at>str(current['at']) or at[:10]!=str(current['at'])[:10] or at<watermark: continue
            if at==watermark: sequence[-1]=point
            else: sequence.append(point)
            watermark=at
        for point in sequence:
            at=point['at']
            gap=intraday_path.gap_seconds(last_at,at) if last_at else None
            if last_at and (gap is None or gap>p['max_sample_gap_seconds']): samples=0
            last_at=at
            samples=samples+1 if point.get('valid') and positive(point.get('price')) and point['price']>upper+eps else 0
    restrictions=[]
    if cycle.get('pending_reason'): restrictions.append(cycle['pending_reason'])
    if not valid: restrictions.append('当前非连续盘中或报价/价格口径待核验')
    if terminal: restrictions.append(cycle.get('close_reason') or LABELS[cycle['state']])
    if valid and positive(price) and price<upper: restrictions.append('现价回到原平台上沿以下')
    if row.get('intraday_trend_ok') is not True: restrictions.append('当前趋势未在线')
    restrictions += list(row.get('intraday_risk_flags') or [])
    if row.get('intraday_trade_restriction'): restrictions.append('成交受限')
    if row.get('overheated') is True: restrictions.append('位置偏热')
    if row.get('trade_status') in ('no_trade','trade_recovered_wait_daily'): restrictions.append('停牌或恢复成交待日线对齐')
    if row.get('intraday_serious_weakness') is not False: restrictions.append('严重转弱状态待核验或已触发')
    if any(e['kind']=='volume_stall' and e['day']==cycle['last_processed_asof'] for e in cycle['events']): restrictions.append('最近完成日高量、低推进')
    attempt=cycle['attempts'][-1] if cycle['attempts'] else {}
    volume_confirmed=bool(attempt.get('volume_at') and not attempt.get('failed_at'))
    live_label=('盘中采样保持，待收盘确认' if samples>=p['confirmation_samples'] else
                '盘中越过平台，待收盘确认' if samples else '当前未越过突破门槛') if valid and not terminal else '历史结构参考'
    latest=cycle['events'][-1] if cycle['events'] else None
    sos=bool(volume_confirmed and attempt.get('sos_features'))
    lps=bool(sos and (attempt.get('retest') or {}).get('lps_features'))
    return dict(version=VERSION,code=cycle['code'],name=row.get('name',cycle['code']),
                cycle_id=cycle['cycle_id'],state=cycle['state'],label=LABELS[cycle['state']],
                created_asof=cycle['created_asof'],created_at=cycle['created_at'],
                evidence_asof=cycle['last_processed_asof'],observed_at=cycle['reviewed_at'],
                platform_high=cycle['platform_high'],platform_low=cycle['platform_low'],
                atr0=cycle['atr0'],atr_method='ATR20-SMA（真实波幅简单平均）',
                price_scale_factor=factor,volume0=cycle['volume0'],price_basis=cycle['origin'][-1]['price_basis'],
                wyckoff_evidence={'sos':sos,'lps':lps,'label':'LPS量缩幅窄特征' if lps else 'SOS量价扩张特征' if sos else '供需与努力/结果观察',
                                  'scope':'威科夫量价特征观察；未完成A-E阶段及点数图因果目标验证'},
                live_platform_high=upper,live_platform_low=cycle['platform_low']*live_factor if live_factor else None,
                live_atr0=cycle['atr0']*live_factor if live_factor else None,live_breakout_threshold=upper+eps if upper else None,
                contraction_confirmed=cycle['contraction_confirmed'],shrink_ratio=cycle['shrink_ratio'],
                contraction_ratio=cycle['contraction_ratio'],live_label=live_label,live_samples=samples,
                live_at=row.get('intraday_judgment_at') or row.get('intraday_quote_at'),
                live_valid=valid,current_structure_clear=bool(valid and volume_confirmed and not restrictions),
                restrictions=list(dict.fromkeys(restrictions)),pending_reason=cycle.get('pending_reason'),
                attempts=deepcopy(cycle['attempts']),events=deepcopy(cycle['events']),latest_event=deepcopy(latest),
                closed_asof=cycle['closed_asof'],close_reason=cycle.get('close_reason'))

def load_state():
    try:
        saved=json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'version':VERSION,'cycles':{},'archived_cycles':[]}
    except (OSError,ValueError) as exc:
        raise RuntimeError('结构留档无法读取，保留文件并停止覆盖') from exc
    if saved.get('version')!=VERSION:
        return {'version':VERSION,'cycles':{},'archived_cycles':[]}
    return saved

def attach(snap, klines, calendar, contexts=None, history=None, state=None, persist=False,
           daily_history_loader=None):
    contexts=contexts or {}; history=history or {}
    saved=deepcopy(state) if state and state.get('version')==VERSION else load_state() if persist else {
        'version':VERSION,'cycles':{},'archived_cycles':[]}
    rows=(snap.get('stocks') or [])+(snap.get('coverage_catalog') or [])
    asof=(snap.get('strength_model') or {}).get('asof')
    at=snap.get('generated_at'); cycles=saved.setdefault('cycles',{}); items=[]
    daily_allowed=bool(asof and at and (asof<str(at)[:10] or
        (asof==str(at)[:10] and snap.get('session')=='已收盘' and str(at)[11:16]>='15:05')))
    for row in rows:
        code=str(row['code']); bars=klines.get(code,[]); cycle=cycles.get(code)
        seed=row.get('trend_consolidation') or {}
        # quick的当日报价合成K线不能成为正式量价日线；只读已入库的日线源。
        if daily_history_loader and (cycle or seed.get('eligible') is True):
            bars=daily_history_loader(code)
        if cycle and not daily_allowed:
            cycle=deepcopy(cycle); cycle['pending_reason']='本轮完成日线日期未通过交易阶段核验'
        if cycle and daily_allowed and bars:
            cycle=review_daily(cycle,bars,asof,calendar,at)
        if daily_allowed and bars and seed.get('eligible') is True and (not cycle or (
                cycle['state'] in ('closed','expired') and seed.get('consolidation_start','')>cycle['closed_asof']
                and seed.get('impulse_end','')>cycle['closed_asof'])):
            new,_=create_cycle(code,bars,asof,calendar,at,price_factor=contexts.get(code,{}).get('scale_factor') if contexts.get(code,{}).get('valid') else None)
            if new:
                if cycle: saved.setdefault('archived_cycles',[]).append(cycle)
                cycle=new
        row.pop('wyckoff_structure',None)
        if not cycle: continue
        cycles[code]=cycle
        context=contexts.get(code,{})
        # 没有历史数据时，只能显示留档，不能借用旧尺度判断新报价。
        if not bars: context={}
        item=display_cycle(cycle,row,context,(history.get('points') or {}).get(code,[]),snap.get('session'),at)
        row['wyckoff_structure']=item; items.append(item)
    counts=Counter(x['state'] for x in items)
    model=dict(version=VERSION,asof=asof,observed_at=at,parameters=deepcopy(parameters()),
               rows=items,count=len(items),state_counts=dict(counts),
               event_count=sum(len(x['events']) for x in items),
               archived_cycle_count=len(saved.get('archived_cycles',[])),
               note='独立结构观察；不参与进攻评分或原候选筛选。盘中价格行为待正式收盘量价核验。')
    snap['wyckoff_structure']=model
    if persist:
        DIRECTORY.mkdir(parents=True,exist_ok=True)
        config.atomic_write_text(STATE_FILE,json.dumps(saved,ensure_ascii=False,separators=(',',':')))
    return model
