"""合格整理中的靠线→止跌→反弹证据；日线事实与盘中采样分开。"""
from statistics import mean

import config
import intraday_path
from consolidation_tracking import valid_number as number


def near(distance):
    p=config.TREND_CONSOLIDATION
    return -p['rebound_undercut_atr']-1e-9 <= distance <= p['rebound_near_atr']+1e-9


def enough(low,price,atr):
    p=config.TREND_CONSOLIDATION
    return (price-low >= p['rebound_min_atr']*atr-1e-9 and
            100*(price/low-1) >= p['rebound_min_pct']-1e-9)


def daily(setup,bars):
    """只用基准日前完成日；低点与正式收盘构成回踩和反弹事实，不倒推分钟路径。"""
    p=config.TREND_CONSOLIDATION
    if not all(setup.get(k) for k in ('baseline_asof','consolidation_start','atr20')):return None
    bars=sorted((b for b in bars if b['date']<=setup['baseline_asof']),key=lambda b:b['date'])
    atr=setup['atr20']; result=None
    for i,bar in enumerate(bars):
        if i<20 or bar['date']<setup['consolidation_start'] or len(bars)-i>p['rebound_max_age_days']+1:
            continue
        touches=[]
        for period in (5,10,20):
            level=mean(b['close'] for b in bars[i-period+1:i])
            distance=(bar['low']-level)/atr
            if near(distance) and bars[i-1]['close']-bar['low']>=p['rebound_approach_atr']*atr:
                touches.append((abs(distance),period,level))
        if not touches: continue
        _,period,level=min(touches)
        for j in range(i,len(bars)):
            if len(bars)-1-j>p['rebound_max_age_days']:continue
            # 不能跨过明显跌穿后的低点，再把后来的反弹追认给旧支撑。
            if any(b['low']<bar['low']-p['rebound_undercut_atr']*atr for b in bars[i+1:j+1]):break
            candidate=bars[j]
            if candidate['close']>=level and candidate['close']>=candidate['open'] and enough(bar['low'],candidate['close'],atr):
                result=dict(rebound_confirmed=True,rebound_line=period,rebound_touch_at=bar['date'],
                            rebound_touch_price=bar['low'],rebound_touch_level=level,
                            rebound_confirmed_at=candidate['date'],rebound_confirm_price=candidate['close'],
                            rebound_samples=1,rebound_evidence='完成日低点靠线及随后正式收盘反弹确认',
                            rebound_basis='completed_daily',rebound_atr=atr)
                break
    return result


def sampled(points,atr):
    """不同有效行情时间，先下降靠线、后连续两次抬高；单次上跳和重复报价不能确认。"""
    p=config.TREND_CONSOLIDATION
    watermark='';last=None;anchor=None;rises=0;result=None
    for point in points:
        at=str(point.get('at') or '')
        if not at or at<=watermark:continue
        watermark=at
        if (not point.get('valid') or not number(point.get('price')) or point['price']<=0 or
                not any(number(point.get(k)) and point[k]>0 for k in ('ma5_boundary','ma10','ma20'))):
            last=anchor=result=None;rises=0;continue
        if last:
            gap=intraday_path.gap_seconds(last['at'],at)
            if gap is None or gap>p['max_sample_gap_seconds'] or last['at'][:10]!=at[:10]:
                last=anchor=result=None;rises=0
        own_atr=point.get('atr20') if number(point.get('atr20')) and point['atr20']>0 else atr
        if anchor:
            if point['price']<anchor['price']-p['rebound_undercut_atr']*anchor['atr']:
                anchor=result=None;rises=0
            elif last and point['price']>last['price']:
                rises+=1
                if rises>=p['confirmation_samples'] and enough(anchor['price'],point['price'],anchor['atr']):
                    result=dict(rebound_confirmed=True,rebound_line=anchor['period'],rebound_touch_at=anchor['at'],
                                rebound_touch_price=anchor['price'],rebound_touch_level=anchor['level'],
                                rebound_confirmed_at=at,rebound_confirm_price=point['price'],rebound_samples=rises,
                                rebound_evidence='下降靠线后连续两次不同时间有效报价抬高',
                                rebound_basis='intraday_samples',rebound_atr=anchor['atr'])
            else:
                rises=0
        if last and last['price']-point['price']>=p['rebound_approach_atr']*own_atr:
            touches=[]
            for period,key in ((5,'ma5_boundary'),(10,'ma10'),(20,'ma20')):
                level=point.get(key)
                if number(level) and level>0 and near((point['price']-level)/own_atr):
                    touches.append((abs(point['price']-level),period,level))
            if touches:
                _,period,level=min(touches)
                anchor=dict(at=at,price=point['price'],period=period,level=level,atr=own_atr)
                result=None;rises=0
        last=point
    return result


def observe(setup,bars,context,row,points):
    """当前状态必须仍可跟踪；历史反弹不替代当前多头、MA10、风险和分歧修复条件。"""
    factor=context['scale_factor'];atr=context['atr20']
    now=dict(at=row['intraday_judgment_at'],valid=True,price=row['price'],atr20=atr,
             ma5_boundary=context['thresholds'][5],ma10=context['thresholds'][10],ma20=context['thresholds'][20])
    signal=sampled(list(points)+[now],atr)
    if signal is None:
        signal=daily(setup,bars)
        if signal:
            for key in ('rebound_touch_price','rebound_touch_level','rebound_confirm_price','rebound_atr'):
                signal[key]*=factor
    if not signal: return dict(rebound_confirmed=False)
    signal['rebound_active']=(row['price']>signal['rebound_touch_price']+.25*signal['rebound_atr'] and
                              row['price']>=context['thresholds'][signal['rebound_line']])
    signal['rebound_label']='回踩反弹·MA'+str(signal['rebound_line'])
    signal['rebound_gain_pct']=round(100*(row['price']/signal['rebound_touch_price']-1),3)
    return signal
