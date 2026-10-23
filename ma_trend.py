"""Strong-origin MA5/10/20 observation. Price histories are never rewritten."""
import copy
import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

import config
import intraday
import closing_price
import observed_history

P = config.MA_TREND
VERSION = P['version']
IMPLEMENTATION_HASH = hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).with_name('board_stock_rank.py').read_bytes() + Path(closing_price.__file__).read_bytes() + Path(intraday.__file__).read_bytes() + Path(observed_history.__file__).read_bytes() + json.dumps(P,sort_keys=True).encode()).hexdigest()
LABELS = {5:'MA5初期推进',10:'MA10承接整理',20:'MA20横盘再启动'}
_DAILY_CACHE = {}
_DAILY_CACHE_DAY = None
_DAILY_STATS = {'hits': 0, 'misses': 0, 'clears': 0}
_DAILY_CACHE_LIMIT = 8000


def number(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)


def positive(v):
    return number(v) and v>0


def r(v):
    return round(v,4) if number(v) else None


def average(bars,i,n):
    return round(sum(b['close'] for b in bars[i-n+1:i+1])/n,10) if i>=n-1 else None


def atr(bars,i):
    if i<20:return None
    return sum(max(bars[j]['high']-bars[j]['low'],abs(bars[j]['high']-bars[j-1]['close']),
                    abs(bars[j]['low']-bars[j-1]['close'])) for j in range(i-19,i+1))/20


def origin(bars,i,features=None,limit_pct=None):
    unit=features['atr'][i-1] if features else atr(bars,i-1)
    if not positive(unit):return None
    b=bars[i];prior=bars[i-P['breakout_days']:i]
    span=b['high']-b['low'];position=(b['close']-b['low'])/span if span>0 else 0.
    baseline=mean(x['volume'] for x in bars[i-5:i]) if all(positive(x.get('volume')) for x in bars[i-5:i]) else None
    ratio=b['volume']/baseline if positive(b.get('volume')) and positive(baseline) else None
    body=(b['close']-b['open'])/unit
    high=max(x['high'] for x in prior)
    day_pct=100*(b['close']/bars[i-1]['close']-1)
    two_pct=100*(b['close']/bars[i-2]['close']-1)
    one_rise=(b['close']-bars[i-1]['close'])/unit
    two_rise=(b['close']-bars[i-2]['close'])/unit
    one=day_pct>=P['impulse_day_pct'] and one_rise>=P['impulse_rise_atr']
    two=(day_pct>0 and bars[i-1]['close']>bars[i-2]['close']
         and two_pct>=P['impulse_two_day_pct'] and two_rise>=P['impulse_rise_atr'])
    impulse=(one or two) and number(ratio) and ratio>=P['volume_ratio']
    breakout=(b['close']>=high+P['breakout_atr']*unit and day_pct>=P['breakout_day_pct']
              and number(ratio) and ratio>=P['breakout_volume_ratio'])
    limit_pct=features.get('limit_pct') if features else limit_pct
    sealed=(P['limit_breakout_enabled'] and positive(limit_pct) and number(ratio)
            and abs(day_pct-limit_pct)<=P['limit_return_tolerance_pp']
            and abs(b['close']-b['high'])<1e-8 and b['close']>=high+P['breakout_atr']*unit)
    kinds=[]
    if position>=P['close_position']:
        if impulse:kinds.append('放量上攻')
        if breakout:kinds.append('有效突破')
    # A sealed one-price limit has no intraday range; its close-position ratio
    # is undefined and must not block the independent limit-breakout channel.
    if sealed:kinds.append('涨停突破')
    if not kinds:return None
    base=min(bars[i-P['origin_base_days']:i],key=lambda x:x['low'])
    return dict(date=b['date'],kind=' / '.join(kinds),body_atr=r(body),volume_ratio=r(ratio),
                day_return_pct=day_pct,two_day_return_pct=two_pct,rise_atr=one_rise if one or not two else two_rise,
                rise_days=2 if two and not one else 1,
                base_low=base['low'],base_at=base['date'],
                advance_start_close=bars[i-2 if two and not one else i-1]['close'],
                close_position=r(position) if span>0 else None,one_price_limit=bool(sealed and span==0),
                prior_high=r(high),breakout_price=r(high+P['breakout_atr']*unit),
                atr=unit,price=b['close'],basis='完成日量价',index=i,
                limit_pct=limit_pct if sealed else None,limit_return_tolerance_pp=P['limit_return_tolerance_pp'] if sealed else None)


def falling(window):
    return len(window)>=3 and all(window[j]['low']<window[j-1]['low'] and
                                  window[j]['close']<window[j-1]['close'] for j in (-1,-2))


def ma20_position(price,line,unit):
    allowance=min(P['ma20_below_atr']*unit,line*P['ma20_below_pct']/100)
    return price>=line-allowance,allowance


def ma20_rise(bars,i,root,features=None):
    """Latest strong rising leg, independent of secondary platform formation."""
    if not root or root['index']>=i:return None
    unit=features['atr'][i] if features else atr(bars,i)
    if not positive(unit):return None
    peak=max(range(root['index'],i+1),key=lambda j:(bars[j]['close'],-j))
    if not 1<=i-peak<=P['platform_max_days']:return None
    amplitude=bars[peak]['close']-root['base_low']
    gain=100*amplitude/root['base_low'];gain_atr=amplitude/root['atr']
    if gain<P['ma20_rise_pct'] or gain_atr<P['ma20_rise_atr']:return None
    line=features['ma'][20][i] if features else average(bars,i,20)
    previous=features['ma'][20][i-1] if features else average(bars,i-1,20)
    _,allowance=ma20_position(bars[i]['close'],line,unit)
    low=bars[i]['low'];close=bars[i]['close']
    ready=(line>=previous and line-allowance<=low<=line+P['near_atr']*unit and close>=line)
    return dict(id=root['date']+':'+bars[peak]['date'],origin=copy.deepcopy(root),
                rise_start=root['base_at'],rise_end=bars[peak]['date'],peak_date=bars[peak]['date'],
                rise_pct=gain,rise_atr=gain_atr,base_low=root['base_low'],base_at=root['base_at'],
                peak_close=bars[peak]['close'],line=line,atr20=unit,allowance=allowance,
                low=low,ready=ready,asof=bars[i]['date'])


def ma20_backup(platform):
    """Only a qualified, fixed floor may defend a lost MA20."""
    if not platform or not platform.get('confirmed') or not positive(platform.get('low')):return False
    # Qualification locks a defensive floor. Age and subsequent volume changes
    # affect the observation position, not the existence of that fixed support.
    ratio=platform.get('volume_ratio')
    return (platform.get('rise_pct',0)>=P['ma20_rise_pct'] and platform.get('rise_atr',0)>=P['ma20_rise_atr']
            and platform.get('days',0)<=P['platform_max_days']
            and platform.get('width_atr',math.inf)<=P['platform_width_atr']
            and number(ratio) and ratio<=P['platform_volume_ratio']
            and (not P['ma20_width_pct_hard'] or platform.get('current_width_pct',platform.get('width_pct',math.inf))<=P['platform_width_pct']))


def ma20_defense(line,platform):
    return min(line,platform['low']) if ma20_backup(platform) else line


def set_ma20_support(m,context):
    line=context['thresholds'][20];platform=m.get('platform') or {}
    floor=platform['low'] if ma20_backup(platform) else None
    support=ma20_defense(line,platform)
    m.update(primary_support_price=line,secondary_support_price=floor,
        support_price=support,support_basis='MA20与平台双支撑' if floor is not None else 'MA20触线价',
        defense_mode='MA20守线' if m['price']>=line else '平台承接' if floor is not None and m['price']>=floor else '双支撑失守' if floor is not None else 'MA20失守·无合格后备平台')
    context['support']=support


def structure(bars,i,root,features=None,require_position=True):
    """All boundaries come from completed bars at or before i."""
    if not root:return {}
    unit=features['atr'][i] if features else atr(bars,i);close=bars[i]['close'];choices={}
    def line_at(j,n):return features['ma'][n][j] if features else average(bars,j,n)
    if not positive(unit):return choices
    start=root['index']
    for n,minimum in ((10,P['ma10_days']),):
        if i-start<minimum:continue
        anchors=range(start,i-minimum+1)
        peak=max(anchors,key=lambda j:(bars[j]['close'],-j))
        window=bars[peak+1:i+1]
        if len(window)<minimum or len(window)>P['platform_max_days'] or falling(window):continue
        line=line_at(i,n);previous=line_at(i-1,n)
        if line<=previous:continue
        if require_position and ((close-line)/unit>P['entry_near_atr'] or
                n==10 and close<line or n==20 and not ma20_position(close,line,unit)[0]):continue
        low=min(b['low'] for b in window);high=max(b['high'] for b in window)
        width=(high-low)/unit;amplitude=bars[peak]['close']-root['base_low']
        rise_pct=100*amplitude/root['base_low'];rise_atr=amplitude/root['atr']
        if rise_pct<P[f'ma{n}_rise_pct'] or rise_atr<P[f'ma{n}_rise_atr']:continue
        if width>P['platform_width_atr']:continue
        if n==10:
            if not any(bars[j]['close']<line_at(j,5) for j in range(peak+1,i+1)):continue
        else:
            if 100*(high/low-1)>P['platform_width_pct']:continue
            if (bars[peak]['close']-low)/amplitude>P['platform_retrace_fraction']:continue
            if max(b['close'] for b in window)-bars[peak]['close']>P['platform_rise_atr']*unit:continue
        rise=bars[start:peak+1]
        vols=all(positive(b.get('volume')) for b in rise+window)
        vr=mean(b['volume'] for b in window)/mean(b['volume'] for b in rise) if vols else None
        if vr is None or vr>P['platform_volume_ratio']:continue
        choices[n]=dict(id=root['date']+':'+bars[peak]['date'],formed_at=bars[i]['date'],
            start=window[0]['date'],peak_date=bars[peak]['date'],days=len(window),
            low=low,high=high,atr20=unit,peak_close=bars[peak]['close'],
            rise_pct=rise_pct,rise_atr=rise_atr,base_low=root['base_low'],base_at=root['base_at'],
            width_atr=width,volume_ratio=vr,rise_volume=mean(b['volume'] for b in rise),
            width_pct=100*(high/low-1),origin=copy.deepcopy(root),confirmed=True)
    platform=latest_platform(bars,i,root,features,require_position)
    if platform:choices[20]=platform
    return choices


def latest_platform(bars,i,root,features=None,require_position=True):
    """Only the latest rise peak and its following settled range can qualify.

    The initial pullback ends at the first lowest low after that peak. No older
    peak is searched when the latest rise has not finished. Once locked by daily,
    subsequent lower lows cannot move this floor down.
    """
    if not root:return None
    start=root['index'];unit=features['atr'][i] if features else atr(bars,i)
    if not positive(unit) or i-start<P['ma20_days']:return None
    peak=max(range(start,i+1),key=lambda j:(bars[j]['close'],-j))
    if not P['ma20_days']<=i-peak<=P['platform_max_days']:return None
    trough=min(range(peak+1,i+1),key=lambda j:(bars[j]['low'],j))
    window=bars[trough:i+1]
    if len(window)<P['ma20_days'] or falling(window):return None
    line=features['ma'][20][i] if features else average(bars,i,20)
    previous=features['ma'][20][i-1] if features else average(bars,i-1,20)
    if line<=previous:return None
    close=bars[i]['close']
    if require_position and (not ma20_position(close,line,unit)[0] or (close-line)/unit>P['entry_near_atr']):return None
    low=min(b['low'] for b in window);high=max(b['high'] for b in window)
    amplitude=bars[peak]['close']-root['base_low']
    rise_pct=100*amplitude/root['base_low'];rise_atr=amplitude/root['atr']
    retained_pct=100*(low/root['base_low']-1);retained_atr=(low-root['base_low'])/root['atr']
    width=(high-low)/unit;width_pct=100*(high/low-1)
    if rise_pct<P['ma20_rise_pct'] or rise_atr<P['ma20_rise_atr'] or width>P['platform_width_atr']:return None
    if P['ma20_width_pct_hard'] and width_pct>P['platform_width_pct']:return None
    if P['ma20_retained_gain']:
        if retained_pct<P['ma20_rise_pct'] or retained_atr<P['ma20_rise_atr']:return None
    elif (bars[peak]['close']-low)/amplitude>P['platform_retrace_fraction']:return None
    if max(b['close'] for b in window)>bars[peak]['close']+P['platform_rise_atr']*unit:return None
    rise=bars[max(start,peak-P['ma20_rise_volume_days']+1):peak+1]
    if not all(positive(b.get('volume')) for b in rise+window):return None
    rise_volume=mean(b['volume'] for b in rise);ratio=mean(b['volume'] for b in window)/rise_volume
    if ratio>P['platform_volume_ratio']:return None
    return dict(id=root['date']+':'+bars[peak]['date'],formed_at=bars[i]['date'],
        start=window[0]['date'],peak_date=bars[peak]['date'],rise_start=root['base_at'],rise_end=bars[peak]['date'],
        days=len(window),low=low,high=high,atr20=unit,peak_close=bars[peak]['close'],
        rise_pct=rise_pct,rise_atr=rise_atr,base_low=root['base_low'],base_at=root['base_at'],
        retained_pct=retained_pct,retained_atr=retained_atr,width_atr=width,width_pct=width_pct,
        volume_ratio=ratio,rise_volume=rise_volume,rise_volume_days=len(rise),origin=copy.deepcopy(root),
        confirmed=True,latest_cycle=True)


def catchment(bars,i,root,features=None):
    """A qualified MA5 wave moves to MA10 even before a tight platform forms."""
    start=root['index'];peak=max(range(start,i+1),key=lambda j:(bars[j]['close'],-j))
    window=bars[peak+1:i+1] or bars[i:i+1]
    unit=features['atr'][i] if features else atr(bars,i)
    low=min(b['low'] for b in window);high=max(b['high'] for b in window)
    amplitude=bars[peak]['close']-root['base_low'];rise=bars[start:peak+1]
    volume=mean(b['volume'] for b in rise) if all(positive(b.get('volume')) for b in rise) else None
    return dict(id=root['date']+':catchment',formed_at=bars[i]['date'],start=window[0]['date'],
        peak_date=bars[peak]['date'],days=len(window),low=low,high=high,atr20=unit,
        peak_close=bars[peak]['close'],rise_pct=100*amplitude/root['base_low'],
        rise_atr=amplitude/root['atr'],base_low=root['base_low'],base_at=root['base_at'],
        width_atr=(high-low)/unit,width_pct=100*(high/low-1),rise_volume=volume,
        volume_ratio=None,origin=copy.deepcopy(root),confirmed=False)


def platform_progress(platform,bars,i,unit):
    window=[b for b in bars[:i+1] if b['date']>=platform['start']]
    platform.update(current_days=len(window),validated_at=bars[i]['date'],
        current_width_atr=(max(b['high'] for b in window)-min(b['low'] for b in window))/unit,
        current_width_pct=100*(max(b['high'] for b in window)/min(b['low'] for b in window)-1),
        current_volume_ratio=(mean(b['volume'] for b in window)/platform['rise_volume']
            if positive(platform.get('rise_volume')) and all(positive(b.get('volume')) for b in window) else None))


def recovery_event(bars,i,features,previous_exit):
    """Independent completed-day event; it never creates a qualified MA origin."""
    if not P['limit_recovery_candidate_enabled'] or not previous_exit or features.get('limit_pct')!=10:return None
    b=bars[i];change=100*(b['close']/bars[i-1]['close']-1)
    lines={n:features['ma'][n][i] for n in (5,10)}
    if abs(change-10)>P['limit_return_tolerance_pp'] or abs(b['close']-b['high'])>1e-8:return None
    if not all(b['close']>=lines[n] and lines[n]>features['ma'][n][i-1] for n in lines):return None
    if not any(bars[i-1]['close']<features['ma'][n][i-1] for n in lines):return None
    baseline=mean(x['volume'] for x in bars[i-5:i]) if all(positive(x.get('volume')) for x in bars[i-5:i]) else None
    return dict(kind='涨停收复',date=b['date'],basis='完成日收盘封板并收复上行MA5及MA10',
        active=True,state='新启动候选',price=b['close'],ma5=lines[5],ma10=lines[10],
        cycle_id=b['date'],age_sessions=1,window_sessions=P['limit_recovery_candidate_days'],
        volume_ratio=b['volume']/baseline if positive(b.get('volume')) and positive(baseline) else None,
        day_return_pct=change,previous_origin=(previous_exit.get('origin') or {}).get('date'),
        previous_exit=previous_exit['date'],validated_at=b['date'])


def confirmed_price_origin(bars,start,features,kind,confirmation):
    """Keep the observed event date separate from its later close confirmation."""
    b=bars[start];unit=features['atr'][start-1];span=b['high']-b['low']
    volumes=bars[start-5:start]
    baseline=mean(v['volume'] for v in volumes) if all(positive(v.get('volume')) for v in volumes) else None
    base=min(bars[start-P['origin_base_days']:start],key=lambda v:v['low'])
    return dict(date=b['date'],index=start,kind=kind,basis='完成日事件与后续推进确认',
        confirmation=copy.deepcopy(confirmation),price=b['close'],atr=unit,
        body_atr=r((b['close']-b['open'])/unit),
        volume_ratio=b['volume']/baseline if positive(b.get('volume')) and positive(baseline) else None,
        day_return_pct=100*(b['close']/bars[start-1]['close']-1),
        two_day_return_pct=100*(b['close']/bars[start-2]['close']-1),
        rise_atr=(b['close']-bars[start-1]['close'])/unit,rise_days=1,
        base_low=base['low'],base_at=base['date'],advance_start_close=bars[start-1]['close'],
        close_position=(b['close']-b['low'])/span if span>0 else None,
        one_price_limit=span==0,prior_high=max(v['high'] for v in bars[start-P['breakout_days']:start]),
        breakout_price=None)


def recovery_followthrough(bars,i,features,event):
    if not event or not event.get('active'):return None
    start=next((j for j,b in enumerate(bars[:i+1]) if b['date']==event['date']),None)
    if start is None or not P['limit_recovery_follow_days']<=i-start<P['limit_recovery_candidate_days']:return None
    b=bars[i];line5=features['ma'][5][i];line10=features['ma'][10][i]
    if (b['close']<=bars[i-1]['close'] or b['close']<=event['price'] or b['close']<line5
            or line5<=features['ma'][5][i-1] or line10<=features['ma'][10][i-1]):return None
    if any(bars[j]['close']<features['ma'][10][j] for j in range(start+1,i+1)):return None
    proof=dict(kind='涨停收复后推进确认',date=b['date'],event_date=event['date'],
        follow_days=i-start,minimum_days=P['limit_recovery_follow_days'],close=b['close'],previous_close=bars[i-1]['close'],
        event_close=event['price'],ma5=line5,ma10=line10,ma5_previous=features['ma'][5][i-1],
        ma10_previous=features['ma'][10][i-1],ma10_held=True)
    return confirmed_price_origin(bars,start,features,proof['kind'],proof)


def recent_reclaim_anchor(bars,i,features,last_exit,signal):
    """Confirm a recent MA5 reclaim through a strong entry or another sealed close."""
    if features.get('limit_pct')!=10:return None
    if not all(features['ma'][n][i]>features['ma'][n][i-1] and bars[i]['close']>=features['ma'][n][i] for n in (5,10)):return None
    rebuild=not signal
    if not last_exit and not rebuild:return None
    if rebuild:
        if not P['limit_reclaim_rebuild_enabled']:return None
        change=100*(bars[i]['close']/bars[i-1]['close']-1)
        if abs(change-10)>P['limit_return_tolerance_pp'] or abs(bars[i]['close']-bars[i]['high'])>1e-8:return None
        signal=dict(kind='后续完成日涨停确认',date=bars[i]['date'],price=bars[i]['close'],
            day_return_pct=change,limit_pct=10,basis='再次收盘封板，MA5及MA10已转升')
    for start in range(max(21,i-P['origin_days']+1),i):
        b=bars[start];change=100*(b['close']/bars[start-1]['close']-1)
        if (last_exit and b['date']<=last_exit['date'] or abs(change-10)>P['limit_return_tolerance_pp']
                or abs(b['close']-b['high'])>1e-8 or b['close']<features['ma'][5][start]
                or bars[start-1]['close']>=features['ma'][5][start-1]):continue
        if not last_exit and bars[start-1]['close']>=features['ma'][10][start-1]:continue
        if bars[i]['close']<=b['close'] or any(bars[j]['close']<features['ma'][5][j] for j in range(start+1,i+1)):continue
        kind='涨停重建均线后确认' if rebuild else '涨停起涨后强势确认'
        proof=dict(kind=kind,date=bars[i]['date'],event_date=b['date'],
            close=bars[i]['close'],event_close=b['close'],ma5=features['ma'][5][i],ma10=features['ma'][10][i],
            independent_signal=copy.deepcopy(signal),basis='仅在既有强势入口成立后关联起涨日，不回填此前入选资格')
        if rebuild:
            proof.update(previous_exit=last_exit['date'] if last_exit else None,window_sessions=i-start+1,
                reset_date=last_exit['date'] if last_exit else bars[start-1]['date'],
                reset_basis='旧波段已退出' if last_exit else '尚无有效阶段，起涨前完成日失守MA10',
                event_previous_close=bars[start-1]['close'],event_previous_ma10=features['ma'][10][start-1],
                ma5_held=True,ma5_previous=features['ma'][5][i-1],ma10_previous=features['ma'][10][i-1],
                event_return_pct=change,confirmation_return_pct=signal['day_return_pct'],
                event_sealed=True,confirmation_sealed=True,
                basis='涨停收回MA5；5日内再次封板并收复转升的MA5及MA10，期间完成日守住MA5；'+('旧波段已退出' if last_exit else '起涨前完成日已失守MA10'))
        return confirmed_price_origin(bars,start,features,proof['kind'],proof)
    return None


def ma20_restart_followthrough(bars,i,features,event,platform,entry,root,stage=20):
    if not event or i<=event['index']:return None
    b=bars[i]
    if (b['close']<=bars[i-1]['close'] or b['close']<=event['price']
            or b['close']<(ma20_defense(features['ma'][20][i],platform) if stage==20 else features['ma'][10][i])
            or not all(b['close']>=features['ma'][n][i] and features['ma'][n][i]>features['ma'][n][i-1] for n in (5,10))):return None
    proof=dict(kind='MA20整理后再启动' if stage==20 else 'MA10承接后再启动',date=b['date'],event_date=event['date'],close=b['close'],
        event_close=event['price'],previous_close=bars[i-1]['close'],ma5=features['ma'][5][i],ma10=features['ma'][10][i],
        prior_stage=stage,prior_origin=root['date'],prior_rise_pct=entry['rise_pct'],prior_rise_atr=entry['rise_atr'],
        prior_ma20_touched=bool(entry.get('touch_confirmed')),basis='同轮MA'+str(stage)+'整理后收复MA5，后续完成日继续推进且两线向上')
    return confirmed_price_origin(bars,event['index'],features,proof['kind'],proof)


def wave_gain(bars,i,root,features):
    """Accumulate this unbroken cycle's gain, never an already exited cycle."""
    if not root:return {}
    peak=max(range(root['index'],i+1),key=lambda j:(bars[j]['close'],-j))
    amount=bars[peak]['close']-root['base_low']
    return dict(rise_pct=100*amount/root['base_low'],rise_atr=amount/root['atr'],
        peak_close=bars[peak]['close'],peak_date=bars[peak]['date'],origin=copy.deepcopy(root),
        base_low=root['base_low'],base_at=root['base_at'])


def daily(bars,calendar,limit_pct=None):
    """Replay one cycle: a strong MA5 entry, sequential handoffs, and real exits."""
    global _DAILY_CACHE_DAY
    bars=observed_history.traded_bars(bars)
    if not bars:return dict(stage=None,reason='暂无有效成交日',pending=False,sample_only=True)
    dates=[b['date'] for b in bars]
    if dates!=sorted(dates) or len(set(dates))!=len(dates):
        return dict(stage=None,reason='完成日历史日期重复或逆序',pending=True)
    cache_day=calendar[-1] if calendar else dates[-1]
    if _DAILY_CACHE_DAY != cache_day:
        _DAILY_CACHE.clear()
        _DAILY_CACHE_DAY=cache_day
        _DAILY_STATS['clears'] += 1
    modes={(b.get('price_basis'),b.get('price_basis_source')) for b in bars}
    allowed={('qfq',s) for s in intraday._QFQ_HISTORY_SOURCES}|{('raw',s) for s in intraday._RAW_HISTORY_SOURCES}
    if len(modes)!=1 or not modes.issubset(allowed) or not all(intraday._valid_historical_price_bar(b) for b in bars):
        return dict(stage=None,reason='完成日价格口径或OHLC待核验',pending=True)
    if len(bars)<22:return dict(stage=None,reason='按'+str(len(bars))+'个有效成交日展示；强势入口所需完整周期尚未形成',
        pending=False,sample_only=True,asof=dates[-1],history_days=len(bars),history_from=dates[0],
        ma={str(n):r(average(bars,len(bars)-1,n)) for n in LABELS})
    key=(limit_pct,tuple((b['date'],b['open'],b['high'],b['low'],b['close'],b.get('volume'),b.get('price_basis'),b.get('price_basis_source')) for b in bars))
    if key in _DAILY_CACHE:
        _DAILY_STATS['hits'] += 1
        return copy.deepcopy(_DAILY_CACHE[key])
    _DAILY_STATS['misses'] += 1
    features={'ma':{n:[average(bars,i,n) for i in range(len(bars))] for n in LABELS},
              'atr':[atr(bars,i) for i in range(len(bars))],'limit_pct':limit_pct}
    active=None;root=None;leg=None;last_exit=None;roots=[];platform={};entered=None;exits=[]
    invalid_platforms=set();lifecycle=None;transitions=[];last_confirmation=None
    ma20_platform={};last_exit_index=-1;recovery=None;ma20_entry={};restart=None;last_phase=None;restart_event=None;progressing=False
    primary=None;candidates={};gain={}
    def transition(day,old,new,reason,**proof):
        transitions.append(dict(date=day,from_stage=old,to_stage=new,reason=reason,cycle_id=root['date'],**proof))
    for i in range(21,len(bars)):
        day=bars[i]['date'];close=bars[i]['close'];line5=features['ma'][5][i]
        signal=origin(bars,i,features)
        new_recovery=recovery_event(bars,i,features,last_exit) if not active else None
        # Only a confirmed strong MA5 entry can create a cycle. Later stages
        # never scan dormant origins or recreate an exited cycle.
        if not active:
            follow=recovery_followthrough(bars,i,features,recovery) if not new_recovery else None
            entry=follow or recent_reclaim_anchor(bars,i,features,last_exit,signal) or signal
            if entry:roots.append(entry)
            recent=[x for x in roots if i-x['index']<P['origin_days'] and x['index']>last_exit_index]
            if recent and close>=line5 and line5>features['ma'][5][i-1]:
                root=copy.deepcopy(recent[-1])
                if last_exit_index>=0:
                    # The new launch may use the preceding reversal low, but
                    # never a low from before the previous cycle ended.
                    base=min(bars[max(last_exit_index,root['index']-P['origin_base_days']):root['index']],key=lambda b:b['low'])
                    root.update(base_low=base['low'],base_at=base['date'],cycle_base_boundary=last_exit['date'])
                leg=copy.deepcopy(root);active=5;platform={};entered=day
                ma20_platform={};ma20_entry={};restart=None;restart_event=None;progressing=False;lifecycle='沿线推进'
                last_confirmation=dict(copy.deepcopy(root),date=(root.get('confirmation') or {}).get('date',day))
                transition(day,None,5,'完成日强势入口确认',event_date=root['date'])
        elif signal:last_confirmation=copy.deepcopy(signal)
        primary=ma20_rise(bars,i,root,features) if active else None
        gain=wave_gain(bars,i,root,features) if active else {}
        failed_platform=None
        if active:
            # A locked floor belongs to this leg's latest peak. Never move it
            # down using the very bar that broke it, or carry it into a restart.
            if ma20_platform:
                platform_progress(ma20_platform,bars,i,features['atr'][i])
                if close<ma20_platform['low'] or gain['peak_date']>ma20_platform['peak_date']:
                    if close<ma20_platform['low']:failed_platform=copy.deepcopy(ma20_platform)
                    invalid_platforms.add((20,ma20_platform['id']));ma20_platform={}
            formed=latest_platform(bars,i,root,features,require_position=False)
            if formed and not ma20_platform and (20,formed['id']) not in invalid_platforms:
                ma20_platform=formed
            if active==20:platform=copy.deepcopy(ma20_platform)
            if active==10 and platform and gain['peak_date']>platform['peak_date']:
                platform=catchment(bars,i,root,features)
        if active==5 and close<line5:
            transition(day,5,10,'正式收盘失守MA5，转MA10承接')
            active=10;platform=catchment(bars,i,root,features);entered=day;lifecycle='承接观察';restart=None;progressing=False
        if active==10 and close<features['ma'][10][i]:
            if ((primary and close>=features['ma'][20][i])
                    or ma20_backup(ma20_platform) and close>=ma20_platform['low']):
                transition(day,10,20,'MA10失守，同轮上涨达标，转MA20或合格平台承接')
                active=20;platform=copy.deepcopy(ma20_platform);entered=day;lifecycle='整理观察';restart=None;restart_event=None;progressing=False
                ma20_entry=copy.deepcopy(primary or platform)
                ma20_entry['touch_confirmed']=bool(primary and primary['ready'])
            else:
                reason='正式收盘失守MA10，未满足MA20守线或平台承接条件'
                reason+='（同轮前段上涨'+str(round(gain['rise_pct'],2))+'% / '+str(round(gain['rise_atr'],2))+' ATR；要求≥20%且≥4 ATR）'
                last_exit=dict(stage=10,date=day,reason=reason,price=r(close),support=features['ma'][10][i],
                    platform=copy.deepcopy(platform),origin=copy.deepcopy(root),leg_origin=copy.deepcopy(leg),cycle_id=root['date'])
        elif active==20 and close<ma20_defense(features['ma'][20][i],platform):
            # Keep the failed locked floor in the exit evidence even after it
            # becomes unusable for subsequent observations.
            reason='正式收盘同时失守MA20与平台底部' if failed_platform else '正式收盘失守MA20且无合格后备平台'
            floor=(failed_platform or {}).get('low')
            last_exit=dict(stage=20,date=day,reason=reason,price=r(close),
                support=min(features['ma'][20][i],floor) if floor else features['ma'][20][i],
                platform=copy.deepcopy(failed_platform or platform),origin=copy.deepcopy(root),
                leg_origin=copy.deepcopy(leg),cycle_id=root['date'])
        if active and last_exit and last_exit['date']==day:
            transition(day,active,None,last_exit['reason']);last_exit['transitions']=copy.deepcopy([t for t in transitions if t['cycle_id']==root['date']])
            exits.append(copy.deepcopy(last_exit));last_exit_index=i;active=None;platform={};ma20_platform={}
            primary=None;gain={};ma20_entry={};restart=None;progressing=False;lifecycle='本轮趋势结束'
        candidates={n:p for n,p in structure(bars,i,root,features).items() if (n,p['id']) not in invalid_platforms} if active else {}
        if active==10 and 10 in candidates and not platform.get('confirmed'):
            platform=candidates[10];lifecycle='整理观察'
        if active in (10,20):
            if platform:platform_progress(platform,bars,i,features['atr'][i])
            if active==20:
                if primary and primary['ready']:ma20_entry.update(touch_confirmed=True,touch_confirmed_at=day)
            # Recovery changes the state inside MA10/MA20. Standing above MA5
            # never reclassifies this established consolidation as initial MA5.
            if progressing and close<line5:progressing=False;lifecycle='整理观察'
            recovered=ma20_restart_followthrough(bars,i,features,restart,platform,
                ma20_entry if active==20 else gain,root,stage=active) if not progressing else None
            if recovered:
                previous=active
                last_phase=dict(stage=previous,date=day,origin=copy.deepcopy(root),leg_origin=copy.deepcopy(leg),
                    platform=copy.deepcopy(platform),support=ma20_defense(features['ma'][20][i],platform) if previous==20 else features['ma'][10][i],
                    reason='同轮MA'+str(previous)+'整理后再启动确认，进入本阶段推进状态',cause='stage_progression',cycle_id=root['date'])
                leg=recovered;restart_event=copy.deepcopy(recovered);lifecycle='推进延续';progressing=True;restart=None
                last_confirmation=dict(copy.deepcopy(recovered),date=day)
            elif progressing:lifecycle='推进延续';restart=None
            elif close<line5:restart=None
            elif not restart and close>bars[i-1]['close']:
                restart=dict(date=day,index=i,price=close,stage=active,cycle_id=root['date'])
        if new_recovery:recovery=new_recovery
        if recovery and recovery['active']:
            recovery['validated_at']=day
            recovery['age_sessions']=sum(b['date']>=recovery['date'] for b in bars[:i+1])
            if close<features['ma'][10][i]:recovery.update(active=False,state='候选已失效',ended_at=day,reason='完成日收盘失守MA10')
            elif active:recovery.update(active=False,state='强势入口已确认',ended_at=day,reason='完成日强势入口或后续推进已确认')
            elif recovery['age_sessions']>P['limit_recovery_candidate_days']:
                recovery.update(active=False,state='候选已过期',ended_at=day,reason='超出最近5个交易日候选窗口')
    i=len(bars)-1
    out=dict(stage=active,origin=root,leg_origin=leg,cycle_id=root['date'] if root else None,
        restart_event=restart_event,restart_observation=restart,progressing=progressing,platform=platform,entry_date=entered,last_exit=last_exit,
        recovery_candidate=recovery,exits=exits[-4:],asof=dates[-1],pending=False,
        reason='完成日阶段成立' if active else '当前没有合格均线阶段',atr=r(atr(bars,i)),
        ma={str(n):r(average(bars,i,n)) for n in LABELS},
        origin_age=i-leg['index'] if leg else None,lifecycle=lifecycle,
        ma5_holds=sum(bars[j]['close']>=features['ma'][5][j] for j in range(max(4,i-3),i+1)),
        recent_origin=copy.deepcopy(roots[-1]) if roots and i-roots[-1]['index']<P['origin_days'] else None,
        last_confirmation=last_confirmation,transitions=[t for t in transitions if root and t['cycle_id']==root['date']],
        ma20_candidate=ma20_platform,ma20_primary_candidate=primary,ma20_entry=ma20_entry,
        ma20_restart_observation=restart if active==20 else None,last_phase=last_phase,
        ma10_gain=gain,ma10_candidate=(candidates.get(10) if active else None) or (catchment(bars,i,root,features) if active==5 else platform if active==10 else {}),
        history_days=len(bars),history_from=dates[0])
    if len(_DAILY_CACHE) >= _DAILY_CACHE_LIMIT:
        _DAILY_CACHE.clear()
        _DAILY_STATS['clears'] += 1
    _DAILY_CACHE[key]=copy.deepcopy(out)
    return out

def empty(code):
    return dict(version=VERSION,code=code,stage=None,stage_label='暂无合格阶段',eligible=False,pending=False,
                status='未入选',reason='',events=[],data_reasons=[],quote_at=None,mode='',origin=None,
                platform={},support_price=None,ma_value=None,distance_atr=None,rebound=None,
                volume={},board={},tracking={},entry_date=None,exit_at=None)


def minutes_status(bars,context,quote,at,entry_at=None):
    """Continuous raw minute evidence; 15 trading minutes excludes the lunch break."""
    import close_monitor as C
    filtered=[b for b in bars if b.get('at','')<=at[:16]]
    aligned=intraday.align_minute_bars(context,filtered)
    if not aligned.get('valid'):return dict(state='待核验',reason=aligned.get('reason') or '分钟价格口径待核验')
    items=aligned['bars'];now=datetime.fromisoformat(at[:16]);day=at[:10]
    start=entry_at if entry_at and entry_at[:10]==day else day+' 09:30'
    items=[b for b in items if b['at']>=start[:16]]
    coverage=dict(first_at=items[0]['at'] if items else None,last_at=items[-1]['at'] if items else None,
                  bars=len(items),quote_at=at,source=aligned.get('source'),
                  no_trade_minutes=sum(len(b.get('no_trade_before') or []) for a,b in zip(items,items[1:])
                      if C._trading_minutes(datetime.fromisoformat(a['at']),datetime.fromisoformat(b['at']))>1 and C._certified_gap(a,b)))
    if not items or C._trading_minutes(datetime.fromisoformat(items[-1]['at']),now)>2:
        return dict(state='待核验',reason='分钟记录未覆盖最新报价',coverage=coverage)
    allowance=1 if items[0].get('source')=='新浪1分钟OHLC' else 0
    recent=[b for b in items[-16:] if C._trading_minutes(datetime.fromisoformat(b['at']),now)<=15]
    recent_low=min(recent,key=lambda b:b['low']) if recent else None
    if C._trading_minutes(datetime.fromisoformat(start[:16]),datetime.fromisoformat(items[0]['at']))>allowance:
        return dict(state='待核验',reason='分钟记录未覆盖本轮观察起点',coverage=coverage)
    line=context['support'];active=None;last=None;reclaimed=None;exit_event=None;gap=False;floor=None;floor_at=None
    for b in items:
        t=datetime.fromisoformat(b['at'])
        if last and C._trading_minutes(last,t)>1 and not C._certified_gap(previous_bar,b):gap=True
        if floor is None or b['low']<floor:floor=b['low'];floor_at=b['at']
        if b['low']<line and active is None:
            active=t-timedelta(minutes=allowance)
        if active:
            elapsed=C._trading_minutes(active,t)
            if b['low']<=line-P['break_atr']*context['atr20'] and not gap:
                exit_event=dict(at=b['at'],reason='分钟价格明显破位')
            if b['close']>=line:
                if elapsed>P['repair_minutes'] and not gap:exit_event=dict(at=b['at'],reason='失守超过15个交易分钟后才收回')
                reclaimed=dict(at=b['at'],breach_at=str(active),minutes=elapsed);active=None
            elif elapsed>=P['repair_minutes'] and not gap:
                exit_event=dict(at=b['at'],reason='连续15个交易分钟未收回')
        last=t;previous_bar=b
    if gap:return dict(state='待核验',reason='分钟过程有缺口',floor=r(floor),floor_at=floor_at,coverage=coverage)
    if exit_event:return dict(state='退出',exit=exit_event,floor=r(floor),floor_at=floor_at,coverage=coverage)
    if active:
        elapsed=C._trading_minutes(active,now)
        if elapsed>=P['repair_minutes']:return dict(state='退出',exit=dict(at=at,reason='连续15个交易分钟未收回'),floor=r(floor),floor_at=floor_at,coverage=coverage)
        return dict(state='修复观察',breach_at=str(active),minutes=elapsed,floor=r(floor),floor_at=floor_at,coverage=coverage)
    return dict(state='快速收回' if reclaimed else '守线',reclaim=reclaimed,floor=r(floor),floor_at=floor_at,
                recent_floor=recent_low['low'] if recent_low else None,
                recent_floor_at=recent_low['at'] if recent_low else None,source=aligned.get('source'),coverage=coverage)


def scale_setup(setup,factor):
    out=copy.deepcopy(setup)
    def scale_origin(value):
        for k in ('price','prior_high','breakout_price','atr','base_low','advance_start_close'):
            if number(value.get(k)):value[k]*=factor
        proof=value.get('confirmation') or {}
        for k in ('close','previous_close','event_close','ma5','ma10','ma5_previous','ma10_previous','event_previous_close','event_previous_ma10'):
            if number(proof.get(k)):proof[k]*=factor
        if proof.get('independent_signal'):scale_origin(proof['independent_signal'])
    def scale_platform(value):
        for k in ('low','high','atr20','peak_close','base_low','line','allowance','defense_floor'):
            if number(value.get(k)):value[k]*=factor
        if value.get('origin'):scale_origin(value['origin'])
        if value.get('defense_platform'):scale_platform(value['defense_platform'])
    for k in ('atr',):
        if number(out.get(k)):out[k]*=factor
    for key in ('origin','leg_origin','restart_event','recent_origin','last_confirmation'):
        if out.get(key):scale_origin(out[key])
    scale_platform(out.get('platform') or {})
    for key in ('ma10_candidate','ma20_candidate','ma20_primary_candidate','ma20_entry','ma10_gain'):
        if out.get(key):scale_platform(out[key])
    for key in ('last_exit','last_phase'):
        if out.get(key):
            event=out[key]
            for k in ('price','support'):
                if number(event.get(k)):event[k]*=factor
            scale_platform(event.get('platform') or {})
            if event.get('origin'):scale_origin(event['origin'])
            if event.get('leg_origin'):scale_origin(event['leg_origin'])
    for event in out.get('exits') or []:
        for k in ('price','support'):
            if number(event.get(k)):event[k]*=factor
        scale_platform(event.get('platform') or {})
        if event.get('origin'):scale_origin(event['origin'])
        if event.get('leg_origin'):scale_origin(event['leg_origin'])
    if out.get('ma20_restart_observation'):out['ma20_restart_observation']['price']*=factor
    if out.get('restart_observation'):out['restart_observation']['price']*=factor
    out['ma']={k:v*factor for k,v in out.get('ma',{}).items() if number(v)}
    if out.get('recovery_candidate'):
        for k in ('price','ma5','ma10'):out['recovery_candidate'][k]*=factor
    return out


def live(row,q,bars,calendar,now,session,previous=None,center=None,daily_proof=None,context=None):
    import market_strength as M
    code=row['code'];m=empty(code);old=previous or {};day=now.date().isoformat()
    formal=session=='已收盘' and (bool(daily_proof) or (row.get('market_strength') or {}).get('mode')=='正式收盘')
    if not formal and old.get('version')==VERSION and old.get('candidate_mode') and (old.get('tracking') or {}).get('exit_at'):
        m.update(candidate_mode=True,recovery_candidate=copy.deepcopy(old.get('recovery_candidate')),
                 tracking=copy.deepcopy(old['tracking']),exit_at=old.get('exit_at'))
    # Quote gaps must not erase a verified downgrade or a failed wave/platform.
    if not formal and old.get('version')==VERSION and old.get('stage') in LABELS and ((old.get('tracking') or {}).get('exit_at') or (old.get('tracking') or {}).get('transitions')):
        m.update(stage=old['stage'],stage_label=LABELS[old['stage']],platform=copy.deepcopy(old.get('platform') or {}),
                 origin=copy.deepcopy(old.get('origin')),transitions=copy.deepcopy(old.get('transitions') or []),
                 tracking=copy.deepcopy(old['tracking']),exit_at=old.get('exit_at'))
    m['mode']='午休参考' if session=='午间休市' else '正式收盘' if session=='已收盘' else '连续竞价'
    if session not in ('早盘','午盘','尾盘','午间休市','已收盘'):
        if old.get('version')==VERSION:
            m=copy.deepcopy(old);m.update(mode='参考行情 · 原时点 '+str(old.get('quote_at')),reference_only=True,eligible=False)
        else:m.update(pending=True,reason='等待正常交易时段报价',status='待核验')
        return m,None
    native=[b for b in observed_history.traded_bars(bars) if b['date']<day or formal and b['date']==day]
    completed=[d for d in calendar if d<day or formal and d==day]
    if not native:
        m.update(status='暂无成交数据',reason='暂无有效成交日，等待取得首根真实日线')
        return m,None
    m['history_observation']=observed_history.annotation(native,completed,completed[-1] if completed else None)
    # A historical limit signal requires a known main-board limit regime. Unknown
    # or special-treatment regimes do not get inferred from a 10% price change.
    limit_pct=q.get('limit_pct') if q.get('limit_pct')==10 and not str(row.get('name','')).upper().startswith(('ST','*ST')) else None
    setup=daily(native,calendar,limit_pct=limit_pct)
    m.update(asof=setup.get('asof'),reason=setup['reason'],pending=setup['pending'])
    if setup['pending']:m['data_reasons']=[setup['reason']];m['status']='待核验';return m,None
    if observed_history.inferred_quote_halt(q):
        m.update(status='停牌观察',reference_only=True,reason='单股重试仍未取得当日成交，按停牌规则保留最后有效阶段',
            stage=setup.get('stage'),stage_label=LABELS.get(setup.get('stage'),'暂无合格阶段'),origin=setup.get('origin'),
            suspension=q['data_availability'],history_days=len(native),ma=setup.get('ma'))
        for key in ('cycle_id','leg_origin','restart_event','restart_observation','transitions','last_exit','last_phase'):
            m[key]=copy.deepcopy(setup.get(key))
        return m,None
    if setup.get('sample_only'):
        m.update(status='有效样本观察',history_days=len(native),ma=setup.get('ma'))
        return m,None
    at=intraday.parse_quote_timestamp(q.get('quote_at') or q.get('ts'),now)
    valid,at,error=M.quote_valid(q,now,session,center,formal,daily_proof)
    if not valid:
        m.update(pending=True,status='报价待核验',reason=error,data_reasons=[error]);return m,None
    m['quote_at']=str(at);m['price']=q.get('price');m['change_pct']=q.get('change_pct')
    if formal:m.update(decision_at=day+' 15:00:00',judgment_basis='最终完成日线；分钟过程不覆盖收盘结论')
    if daily_proof:m['completed_daily_proof']=copy.deepcopy(daily_proof)
    m['valid_until']=str(at+timedelta(seconds=config.INTRADAY['max_quote_age_seconds']))
    if session=='午间休市':m['valid_until']=day+' 13:00:00'
    elif session=='已收盘':m['valid_until']=day+' 23:59:59'
    if old.get('quote_at') and m['quote_at']<old['quote_at']:
        m.update(pending=True,status='报价待核验',reason='逐股报价倒退',data_reasons=['逐股报价倒退']);return m,None
    if not (context and context.get('valid') and context.get('version') == intraday.PRICE_BASIS_VERSION
            and context.get('quote_day') == day and context.get('quote_at') == str(at)
            and context.get('quote_basis') == q.get('price_basis')
            and context.get('quote_basis_source') == q.get('price_basis_source')
            and (not formal or context.get('last_history_date') == (completed[-1] if completed else None))):
        context=intraday.align_price_basis(q,bars,calendar,observation_day=day)
    if not context.get('valid') or not positive(context.get('atr20')):
        error=context.get('reason') or context.get('atr20_reason') or 'ATR20待核验'
        m.update(pending=True,status='价格口径待核验',reason=error,data_reasons=[error]);return m,None
    setup=scale_setup(setup,context['scale_factor']);unit=context['atr20'];price=q['price']
    # Carry failure tracking through quote gaps, then match it to the actual
    # current event below. It must never contaminate a newer confirmed wave.
    if m.pop('candidate_mode',False):m.update(tracking={},exit_at=None)
    m['recovery_candidate']=copy.deepcopy(setup.get('recovery_candidate'))
    candidate=m['recovery_candidate'] or {}
    if candidate.get('active'):
        candidate['age_sessions']+=int(day>setup['asof'])
        candidate['observation_day']=day
        if candidate['age_sessions']>P['limit_recovery_candidate_days']:
            candidate.update(active=False,state='候选已过期',ended_at=day,reason='超出最近5个交易日候选窗口')
    stage=setup.get('stage');root=setup.get('origin');platform=setup.get('platform') or {}
    primary=setup.get('ma20_primary_candidate') or {}
    same_wave=bool(root and (old.get('origin') or {}).get('date')==root['date'])
    same_leg=bool((setup.get('leg_origin') or {}).get('date')==(old.get('leg_origin') or old.get('origin') or {}).get('date'))
    carried=False
    if (not formal and old.get('version')==VERSION and same_wave and same_leg
            and stage in (5,10) and old.get('stage') in (10,20) and old['stage']>stage
            and any(str(t.get('at') or t.get('date') or '')[:10]>setup['asof'] for t in (old.get('tracking') or {}).get('transitions',[]))):
        stage=old['stage'];platform=copy.deepcopy(old.get('platform') or setup.get('ma10_candidate') or {})
        carried=True
    line20=context['thresholds'][20];_,allowance=ma20_position(price,context['provisional_ma'][20],unit)
    primary_now=bool(primary and context['provisional_ma'][20]>=context['daily_ma'][20]
        and line20-allowance<=q['low']<=line20+P['near_atr']*unit and price>=line20)
    backup=setup.get('ma20_candidate') or {}
    backup_now=bool(ma20_backup(backup) and backup['low']<=price<line20)
    # A price near MA20 is position evidence only. It cannot create a stage;
    # intraday handoffs go through route_failure, just like completed closes.
    same_wave=bool(root and (old.get('origin') or {}).get('date')==root['date'])
    provisional=False
    # A fresh current-price breakout can enter early without pretending volume is completed.
    high=max(b['high'] for b in native[-P['breakout_days']:])*context['scale_factor']
    position=(price-q['low'])/(q['high']-q['low']) if positive(q.get('high')) and positive(q.get('low')) and q['high']>q['low'] else 0.
    day_pct=100*(price/q['last_close']-1) if positive(q.get('last_close')) else None
    if not stage and price>=high+P['breakout_atr']*unit and position>=P['close_position'] and number(day_pct) and day_pct>=P['breakout_day_pct'] and price>=context['thresholds'][5] and context['provisional_ma'][5]>context['daily_ma'][5]:
        stage=5;provisional=True;root=dict(date=day,kind='有效突破',price=r(price),prior_high=r(high),
            breakout_price=r(high+P['breakout_atr']*unit),atr=r(unit),basis='盘中价格暂态',volume_ratio=None,
            close_position=r(position),body_atr=None,day_return_pct=day_pct)
    if not stage:
        last_exit=setup.get('last_exit');m.update(last_exit=last_exit)
        if last_exit:
            n=last_exit['stage'];m.update(stage=n,stage_label=LABELS[n],status='已退出',exit_at=day+' 15:00:00',
                reason=last_exit['reason'],support_price=last_exit['support'],support_basis='平台底部' if n==20 else 'MA'+str(n)+'触线价',platform=last_exit['platform'])
            m['exit_at']=last_exit['date']+' 15:00:00'
        elif m['tracking'].get('exit_at'):
            m.update(status='已退出',reason=m['tracking']['exit_reason'])
        m.update(history_days=setup.get('history_days'),history_from=setup.get('history_from'),
                 origin=root,last_confirmation=setup.get('last_confirmation'),transitions=setup.get('transitions'))
        for key in ('cycle_id','leg_origin','restart_event','restart_observation','last_phase'):
            m[key]=copy.deepcopy(setup.get(key))
        candidate=m.get('recovery_candidate') or {}
        if candidate.get('active'):
            support=context['thresholds'][10]
            track=copy.deepcopy(old.get('tracking') or {}) if not formal and (old.get('recovery_candidate') or {}).get('date')==candidate['date'] and old.get('candidate_mode') else {}
            m.update(stage=None,stage_label='阶段待确认',status='涨停收复·新启动候选',candidate_mode=True,
                startup_pending=True,exit_at=None,pending=False,eligible=False,tracking=track,
                reason='涨停收复事件 '+candidate['date']+'；未通过独立强势入口，继续以MA10观察',
                support_price=support,support_basis='候选MA10触线价',ma_support_price=support,
                ma_value=context['provisional_ma'][10],atr20=unit,distance_atr=r((price-support)/unit),
                volume={'start_ratio':candidate.get('volume_ratio')})
            context=dict(context,support=support,setup=setup,formal=formal)
            if track.get('exit_at'):
                route_failure(m,context,q,dict(at=track['exit_at'],reason=track['exit_reason']))
                return m,None
            if price<=support-P['break_atr']*unit or formal and price<support:
                route_failure(m,context,q,dict(at=m['quote_at'],reason='明显跌破候选MA10' if not formal else '正式收盘失守候选MA10'))
                return m,None
            if not formal and q.get('low',math.inf)<support:
                m['minute_needed']=True
                if price<support:m.update(pending=True,status='支撑失守·修复观察',reason='涨停收复候选等待MA10分钟修复核验')
            return m,context
        return m,None
    support=ma20_defense(line20,platform) if stage==20 else context['thresholds'][stage]
    newly_confirmed=formal and setup.get('entry_date')==day
    m.update(stage=stage,stage_label=LABELS[stage],origin=root,platform=platform,
             entry_date=setup.get('entry_date') or day,entry_at=(day+' 15:00:00' if newly_confirmed else
                 (old.get('entry_at') if old.get('stage')==stage and same_wave else None) or (str(at) if provisional else None)),
             support_price=support,support_basis='MA20与平台双支撑' if stage==20 else 'MA'+str(stage)+'触线价',
             ma_support_price=context['thresholds'][stage],ma_value=context['provisional_ma'][stage],atr20=unit,
             ma5_support=context['thresholds'][5],
             distance_atr=r((price-support)/unit),near=0<=price-support<=P['near_atr']*unit,
             provisional=provisional,last_exit=setup.get('last_exit'),eligible=True,exit_at=None,status='守线观察',
             lifecycle=setup.get('lifecycle'),origin_age=setup.get('origin_age'),
             history_days=setup.get('history_days'),history_from=setup.get('history_from'),
             last_confirmation=setup.get('last_confirmation'),transitions=setup.get('transitions',[]),
             reason=(root or {}).get('kind','')+'起点；'+LABELS[stage]+'结构成立',
             background='中期未恢复' if context['provisional_ma'][20]<context['daily_ma'][20] or price<context['thresholds'][20] else '中期保持')
    for key in ('cycle_id','leg_origin','restart_event','restart_observation','ma10_gain','progressing'):
        m[key]=copy.deepcopy(setup.get(key))
    if provisional:m.update(cycle_id=None,leg_origin=copy.deepcopy(root))
    if m.get('progressing') and price<context['thresholds'][5]:m['progressing']=False
    if carried:
        m['entry_date']=old.get('entry_date') or m['entry_date']
        m['transitions']=copy.deepcopy(old.get('transitions') or m['transitions'])
    if stage==20:
        m['ma20_entry']=copy.deepcopy((old.get('ma20_entry') if carried else None) or (setup.get('ma20_entry') if setup.get('stage')==20 else None) or primary or platform)
        if primary_now:m['ma20_entry'].update(touch_confirmed=True,touch_confirmed_at=day)
        m['ma20_tracking']=not (m['ma20_entry'].get('touch_confirmed') or backup_now)
        m['ma20_restart_observation']=copy.deepcopy(setup.get('ma20_restart_observation'))
    m['last_phase']=copy.deepcopy(setup.get('last_phase'))
    m['volume']=dict(start_ratio=(root or {}).get('volume_ratio'),consolidation_ratio=platform.get('volume_ratio'),
                     status='完成日量价' if not provisional else '当日成交量未作完成日放量判断')
    if (root or {}).get('volume_ratio') is None:m['data_reasons'].append('起点量比缺失；仅使用已核验事件与后续推进证据' if (root or {}).get('confirmation') else '起点量能待核验；仅使用价格突破证据')
    same_wave=bool(root and (old.get('origin') or {}).get('date')==root['date'])
    same_platform=stage==20 and bool(platform.get('id')) and platform.get('id')==(old.get('platform') or {}).get('id')
    track=copy.deepcopy(old.get('tracking') or {}) if not formal and old.get('stage')==stage and (same_platform or same_wave) else {}
    if track.get('exit_at','9999')[:10]<=setup['asof']:track={}
    if track:
        current=[t for t in track.get('transitions',[]) if str(t.get('at') or t.get('date') or '')[:10]>setup['asof']]
        m['transitions']=copy.deepcopy(setup.get('transitions',[]))+copy.deepcopy(current)
    m['tracking']=track
    context=dict(context,support=support,setup=setup,formal=formal,
                 ma10_platform=setup.get('ma10_candidate') or {},ma20_platform=backup,ma20_primary=primary,ma20_primary_now=primary_now)
    if stage==20:
        set_ma20_support(m,context)
        if m['defense_mode']=='平台承接':m.update(status='MA20失守·平台承接',reason='MA20下方运行，合格整理平台底部仍有效')
    if track.get('exit_at'):
        m.update(eligible=False,status='已退出',exit_at=track['exit_at'],reason=track['exit_reason'])
        return m,None
    if price<=support-P['break_atr']*unit or formal and price<support:
        reason='明显跌破本阶段支撑' if price<=support-P['break_atr']*unit else '正式收盘失守本阶段支撑'
        route_failure(m,context,q,dict(at=m['quote_at'],reason=reason))
        if m['status']=='已退出':return m,None
        stage=m['stage'];platform=m['platform'];support=m['support_price']
    if price<support:m.update(eligible=False,pending=True,status='支撑失守·修复观察',reason='等待连续分钟核验15分钟修复窗口')
    elif m['near']:m['status']='接近支撑'
    needs=number(q.get('low')) and (q['low']<support or stage in (10,20) and
        (q['low']<=platform.get('low',-math.inf)+P['near_atr']*unit
         or abs(q['low']-context['provisional_ma'][stage])<=P['near_atr']*unit))
    if stage==20 and not platform and q.get('low',math.inf)>=support:needs=False
    if needs and not newly_confirmed and not formal:
        m['minute_needed']=True
    if formal and not newly_confirmed and stage in (10,20) and platform and price>=support:
        # Only today's verified completed close can confirm a current daily rebound.
        last=native[-1];floor=platform['low'];close=last['close']*context['scale_factor']
        low=last['low']*context['scale_factor']
        if last['date']==day and (low<=floor+P['near_atr']*unit or abs(low-m['ma_value'])<=P['near_atr']*unit) and close>=low+P['rebound_atr']*unit:
            m['rebound']=dict(basis='最新完成日底部反弹',floor=low,distance_atr=r((price-low)/unit),at=last['date']+' 15:00:00')
            m['events'].append('底部反弹');m['status']='底部反弹·再启动观察'
    m['price_context']={k:context.get(k) for k in ('valid','scale_factor','last_history_date','quote_day','history_basis_source','quote_basis_source')}
    m['position_state']=position_state(m,setup,context,day)
    return m,context


def position_state(m,setup,context,day):
    price=m['price'];unit=m['atr20'];n=m['stage'];p=m['platform'];root=m.get('leg_origin') or m['origin']
    if m['provisional']:return '启动待确认'
    if n==5:
        age=setup['origin_age']+(day>setup['asof']);m['origin_age']=age
        if price<root['advance_start_close']+P['origin_hold_fraction']*(root['price']-root['advance_start_close']):return '启动成果回吐'
        required=min(3,setup['origin_age']+1) if root.get('confirmation') else 3
        if context['provisional_ma'][5]<=context['daily_ma'][5] or setup['ma5_holds']<required:return '沿线推进不足'
        if age>1 and price-m['support_price']>P['ma5_focus_atr']*unit:return '推进延续'
        return None
    if n==10:
        gain=m.get('ma10_gain') or setup.get('ma10_gain') or p
        if gain.get('rise_pct',0)<P['ma10_rise_pct'] or gain.get('rise_atr',0)<P['ma10_rise_atr']:
            m['structure_state']='同轮MA5失守后保留MA10承接跟踪；本段涨幅未达正式观察门槛'
            return '前段上涨不足'
    if n in (10,20) and m.get('progressing') and price>=context['thresholds'][5]:
        m['structure_state']='MA'+str(n)+'整理后已确认再启动，当前沿MA5推进；保留原阶段，不自动列为近线观察'
        return '推进延续'
    if n==10 and not p.get('confirmed',True):
        m['structure_state']='MA5失守后的承接观察；紧缩整理平台尚未确认'
        if context['provisional_ma'][10]<context['daily_ma'][10]:return '均线仍向下'
        if price-m['ma_value']>P['entry_near_atr']*unit:return '位置偏离'
        return None
    if n==20:
        # Width, contraction and platform age qualify the backup, not MA20 entry.
        primary=m.get('ma20_entry') or context.get('ma20_primary') or {}
        ceiling=p.get('high') if ma20_backup(p) else primary.get('peak_close')
        away=positive(ceiling) and price>=ceiling+P['breakout_atr']*unit
        if m.get('ma20_restart_observation') and (m.get('ma20_tracking') or away):return '再启动待确认'
        if m.get('ma20_tracking'):return 'MA20整理跟踪'
        if away:return '推进延续'
        m['structure_state']='MA20优先；失守后由合格平台底部承接；两者均失守退出'
        return None
    if setup.get('lifecycle')=='推进延续' or price>=p['high']+P['breakout_atr']*unit:return '推进延续'
    if p.get('current_days',p['days'])>P['platform_max_days']:return '平台观察到期'
    ratio=p.get('current_volume_ratio');m['volume']['consolidation_ratio']=ratio
    if ratio is None:return '整理量能待核验'
    if ratio>P['platform_volume_ratio'] or p.get('current_width_atr',p['width_atr'])>P['platform_width_atr']:return '整理结构扩散'
    if n==20 and P['ma20_width_pct_hard'] and p.get('current_width_pct',p['width_pct'])>P['platform_width_pct']:return '整理结构扩散'
    if context['provisional_ma'][n]<context['daily_ma'][n]:return '均线仍向下'
    if n==20:
        allowed,below=ma20_position(price,m['ma_value'],unit);m['ma20_below_allowance']=below
        if not allowed:return 'MA20偏离过多'
    if n!=20 and price-m['ma_value']>P['entry_near_atr']*unit:return '位置偏离'
    return None


def route_failure(m,context,q,event):
    """A failed MA5 changes the line; MA10 can hand off to MA20 or its backup."""
    stage=m['stage'];unit=m['atr20'];price=q['price'];support=m['support_price']
    if m.get('candidate_mode'):
        m.update(eligible=False,pending=False,status='候选已失效',exit_at=event['at'],startup_pending=False,reason=event['reason'])
        m['recovery_candidate'].update(active=False,state='候选已失效',ended_at=event['at'],reason=event['reason'])
        m['tracking'].update(exit_at=event['at'],exit_reason=event['reason'])
        return
    platform=context.get('ma10_platform') if stage==5 else context.get('ma20_platform') if stage==10 else None
    ma20_ready=stage==10 and ((context.get('ma20_primary') and price>=context['thresholds'][20])
        or ma20_backup(platform) and platform['low']<=price<context['thresholds'][20])
    if stage==10 and not ma20_ready:platform=None
    if stage==20 or stage==10 and not ma20_ready or stage==5 and not platform:
        reason=event['reason']+('；MA10失守且没有合格MA20守线或平台承接' if stage==10 else
            '；MA20与平台同时失守' if stage==20 and ma20_backup(m.get('platform')) else '；MA20失守且无合格后备平台' if stage==20 else '')
        m.update(eligible=False,pending=False,status='已退出',exit_at=event['at'],reason=reason)
        stopped=dict(at=event['at'],from_stage=stage,to_stage=None,reason=reason,cycle_id=m.get('cycle_id'))
        m.setdefault('transitions',[]).append(stopped)
        m['tracking'].setdefault('transitions',[]).append(stopped)
        m['last_exit']=dict(stage=stage,date=event['at'],reason=reason,price=price,support=support,
            origin=copy.deepcopy(m.get('origin')),leg_origin=copy.deepcopy(m.get('leg_origin')),
            platform=copy.deepcopy(m.get('platform')),cycle_id=m.get('cycle_id'),transitions=copy.deepcopy(m['transitions']))
        m['tracking'].update(exit_at=event['at'],exit_reason=reason,exit_support=support,reentry_from=price)
        return
    n=10 if stage==5 else 20
    platform=platform or {}
    transition=dict(at=event['at'],from_stage=stage,to_stage=n,reason=event['reason'],cycle_id=m.get('cycle_id'))
    m['tracking'].setdefault('transitions',[]).append(transition);m['transitions'].append(transition)
    m.setdefault('minute_observation_at',m.get('entry_at'))
    support=ma20_defense(context['thresholds'][20],platform) if n==20 else context['thresholds'][10]
    m.update(stage=n,stage_label=LABELS[n],platform=copy.deepcopy(platform),support_price=support,
        support_basis='MA20与平台双支撑' if n==20 else 'MA10触线价',ma_support_price=context['thresholds'][n],
        ma_value=context['provisional_ma'][n],distance_atr=r((price-support)/unit),
        near=0<=price-support<=P['near_atr']*unit,pending=False,eligible=True,exit_at=None,
        entry_at=event['at'],entry_date=event['at'][:10],status='MA5失守·MA10承接观察' if n==10 else 'MA10失守·MA20承接观察',
        reason=event['reason']+'；转'+LABELS[n],lifecycle='承接观察' if n==10 else '整理观察')
    m['events'].append('降级至MA'+str(n));context['support']=support
    if n==20:
        m['ma20_entry']=copy.deepcopy(context.get('ma20_primary') or {})
        m['ma20_entry']['touch_confirmed']=bool(context.get('ma20_primary_now'))
        m['ma20_tracking']=not (context.get('ma20_primary_now') or ma20_backup(platform) and price<context['thresholds'][20])
        set_ma20_support(m,context)
    if price<=support-P['break_atr']*unit or context['formal'] and price<support:
        route_failure(m,context,q,dict(at=event['at'],reason='明显破位' if not context['formal'] else '正式收盘失守'))
    elif price<support:
        m.update(eligible=False,status='支撑失守·修复观察',reason='等待MA'+str(n)+'支撑的连续分钟过程');m['minute_needed']=True
    m['position_state']=position_state(m,context['setup'],context,m['quote_at'][:10])


def apply_minutes(m,context,q,bars):
    if context.get('formal'):return
    if not m.get('minute_needed'):return
    result=minutes_status(bars,context,q,m['quote_at'],m.get('minute_observation_at',m.get('entry_at')));m['minute_evidence']=result
    m['minute_coverage']=result.get('coverage')
    state=result['state']
    if state=='退出':
        event=result['exit'];m.setdefault('minute_history',[]).append(dict(stage=m['stage'],support=context['support'],evidence=result))
        route_failure(m,context,q,event)
        if m['status'] not in ('已退出','候选已失效'):apply_minutes(m,context,q,bars)
        return
    if state=='修复观察':m.update(eligible=False,pending=False,status='支撑失守·修复观察',reason='15个交易分钟内等待收回');return
    if state=='待核验':
        m['data_reasons'].append(result['reason'])
        if q['price']<context['support'] or q.get('low',math.inf)<context['support'] and not (m.get('provisional') or '重新入选' in m['events']):
            m.update(eligible=False,pending=True,status='支撑过程待核验',reason=result['reason'])
        return
    if q['price']<context['support']:
        m.update(eligible=False,pending=True,status='支撑失守·修复观察',reason='最新报价已失守，分钟尾部尚未反映');return
    if state=='快速收回':
        import close_monitor as C
        event=result['reclaim']
        if C._trading_minutes(datetime.fromisoformat(event['at']),datetime.fromisoformat(m['quote_at']))<=15:
            m['events'].append('快速收回');m['status']='快速收回'
        else:m['last_reclaim']=event
    floor=result.get('recent_floor');platform=m.get('platform') or {};unit=context['atr20']
    if m['stage'] in (10,20) and positive(floor) and platform and (floor<=platform['low']+P['near_atr']*unit or abs(floor-m['ma_value'])<=P['near_atr']*unit) and q['price']>=floor+P['rebound_atr']*unit:
        m['rebound']=dict(basis='连续分钟底部反弹',floor=floor,distance_atr=r((q['price']-floor)/unit),
                          at=m['quote_at'],floor_at=result.get('recent_floor_at'))
        if '底部反弹' not in m['events']:m['events'].append('底部反弹')
        m['status']='底部反弹·再启动观察'


def sort_key(m):
    event=0 if '底部反弹' in m.get('events',[]) else 1 if '快速收回' in m.get('events',[]) else 2 if m.get('near') else 3
    root=m.get('leg_origin') or m.get('origin') or {};platform=m.get('platform') or {};board=m.get('board') or {}
    if m['stage']==5:detail=(-int(str(root.get('date') or '0').replace('-','')),-float(root.get('body_atr') or 0),-float(root.get('volume_ratio') or 0))
    else:
        volume=(m.get('volume') or {}).get('consolidation_ratio',platform.get('current_volume_ratio'))
        width=platform.get('current_width_atr',platform.get('width_atr'))
        values=(float(volume) if number(volume) else 999,float(width) if number(width) else 999)
        detail=values if m['stage']==10 else tuple(reversed(values))
    return (event,*detail,-float(board.get('trend_pct') or 0),m['code'])


def progress(m,old):
    if m.get('reference_only') or m['status']=='已退出' or m['stage'] is None:return
    state=m.get('position_state')
    if state:
        m['eligible']=False
        if not m['pending'] and '修复观察' not in m['status']:
            m['status']=state;m['reason']=state
            if state=='推进延续':m['advance']=True;m['lifecycle']='推进延续'
            elif state=='再启动待确认':m['startup_pending']=True
            elif state=='启动待确认':m['pending']=True;m['startup_pending']=True
            elif state=='整理量能待核验':m['pending']=True;m['data_reasons'].append(state)
            else:m['displaced']=True
    if m['pending'] or m['stage'] not in (10,20):return
    price=m['price'];line=m['ma5_support'];m['ma5_position']='在MA5之上' if price>=line else '尚未站回MA5'
    newer=m.get('quote_at') and old.get('quote_at') and m['quote_at']>old['quote_at']
    if newer and number(old.get('ma5_support')) and old.get('price',math.inf)<old['ma5_support'] and price>=line:
        m['events'].append('收复MA5')
    if old.get('rebound') and not m.get('rebound') and (old.get('platform') or {}).get('id')==(m.get('platform') or {}).get('id'):
        m['last_rebound']=copy.deepcopy(old['rebound'])
    platform=m.get('platform') or {}
    if positive(platform.get('high')) and price>=platform['high']+P['breakout_atr']*m['atr20']:
        m['events'].append('平台上沿突破');m['status']='平台突破·推进延续';m['advance']=True;m['eligible']=False


_DETAIL_ONLY = ('last_exit','last_phase','leg_origin','transitions','history_observation','ma10_gain')


def brief(m):
    result = {k:v for k,v in m.items()
              if k not in _DETAIL_ONLY + ('tracking','minute_evidence','price_context','minute_needed','board_relations')
              and (k!='recovery_candidate' or m.get('recovery_current'))}
    # The list keeps only the fields needed for its labels; the full history is
    # fetched from the immutable detail generation when the drawer is opened.
    if m.get('last_exit'):
        result['last_exit'] = {}
    if isinstance(result.get('last_confirmation'), dict):
        result['last_confirmation'] = {'date': result['last_confirmation'].get('date')}
    if isinstance(result.get('restart_observation'), dict):
        result['restart_observation'] = {'date': result['restart_observation'].get('date')}
    if isinstance(result.get('restart_event'), dict):
        result['restart_event'] = {'date': result['restart_event'].get('date'),
                                   'confirmation': {'date': (result['restart_event'].get('confirmation') or {}).get('date')}}
    return result


def finalize_recovery(m):
    """One backend decision for current labels, selectors and board membership."""
    candidate=m.get('recovery_candidate') or {}
    m['recovery_current']=bool(candidate.get('active') and not m['pending'] and not m.get('reference_only')
        and m.get('quote_at') and not m.get('exit_at')
        and 1<=candidate.get('age_sessions',0)<=P['limit_recovery_candidate_days'])
    m['events']=[event for event in m['events'] if event!='涨停收复']
    if m['recovery_current']:m['events'].append('涨停收复')
    if m.get('candidate_mode'):m['startup_pending']=m['recovery_current']


def attach(snap,quotes,pool,histories,calendar,now=None,previous=None,minute_data=None,fetch_minutes=True,contexts=None):
    import close_monitor as C
    daily_stats_before=dict(_DAILY_STATS)
    now=closing_price.assessment_time(snap,now or datetime.fromisoformat(snap['quote_capture_at']));day=now.date().isoformat()
    prior_meta=(previous or {}).get('ma_trend') or {}
    prior_rows={r['code']:r.get('ma_trend') or {} for r in (previous or {}).get('stocks',[])+(previous or {}).get('coverage_catalog',[])} if prior_meta.get('implementation_hash')==IMPLEMENTATION_HASH else {}
    supplied_contexts=contexts or {}
    models={};contexts={};rows=snap.get('stocks',[])+snap.get('coverage_catalog',[])
    owners={row['code']:row for row in rows}
    # Respect the canonical preserved morning/closing batch and its actual clock.
    # The market module may have replaced invalid after-session supplier quotes.
    effective=dict(quotes)
    for row in rows:
        canonical=row.get('market_strength') or {};clock=intraday.parse_quote_timestamp(canonical.get('quote_at'))
        row_clock=intraday.parse_quote_timestamp(row.get('quote_at') or row.get('ts'))
        supplied=intraday.parse_quote_timestamp((quotes.get(row['code']) or {}).get('quote_at') or (quotes.get(row['code']) or {}).get('ts'))
        if clock and clock==row_clock and clock!=supplied and (canonical.get('price_context') or {}).get('valid'):
            preserved=(snap.get('market_strength_close_input') if canonical.get('mode')=='正式收盘' else snap.get('market_strength_morning_input')) or {}
            saved=(preserved.get('quotes') or {}).get(row['code']) or {}
            saved_clock=intraday.parse_quote_timestamp(saved.get('quote_at') or saved.get('ts'))
            effective[row['code']]=saved if saved_clock==clock and saved.get('price')==row.get('price') else row
    quotes=effective
    proofs={c:p for c,q in quotes.items() if (p:=closing_price.verify(snap,q,histories.get(c) or [],calendar,now))} if snap.get('session')=='已收盘' else {}
    import market_strength as M
    # Rejected after-close timestamps must not move the center away from a valid
    # preserved closing batch. Build the clock only from individually valid input.
    times=[]
    for row in rows:
        valid,clock,_=M.quote_valid(quotes.get(row['code']) or {},now,snap.get('session'),None,
            (row.get('market_strength') or {}).get('mode')=='正式收盘',proofs.get(row['code']))
        if valid:times.append(clock)
    times.sort()
    center=times[len(times)//2] if times else None
    for row in rows:
        code=row['code'];m,ctx=live(row,quotes.get(code) or {},histories.get(code) or [],calendar,now,snap.get('session'),prior_rows.get(code),center,proofs.get(code),supplied_contexts.get(code))
        models[code]=m;row['ma_trend']=m
        if ctx:contexts[code]=ctx
    # Reference-only copies can retain yesterday's minute_needed flag. They have
    # no live context (and may have no current quote), so never replay minutes.
    needed=sorted(c for c,m in models.items() if m.get('minute_needed') and c in contexts and c in quotes)
    # Fetch every required stock; prioritize prices already below support.
    selected=sorted(needed,key=lambda c:(quotes[c]['price']>=contexts[c]['support'],c))
    fetch_stats={}
    if minute_data is None:
        minute_data=C._get_minutes(selected,day,{c:models[c]['quote_at'] for c in selected},request_stats=fetch_stats) if selected and fetch_minutes else C._load_minute_cache(day).get('stocks',{})
    for c in needed:apply_minutes(models[c],contexts[c],quotes[c],minute_data.get(c) or [])
    for c,m in models.items():
        progress(m,prior_rows.get(c) or {})
        finalize_recovery(m)
    boards=[]
    for b in snap.get('board_catalog',[]):
        codes=set(b.get('member_codes') or [])&set(models)
        valid=[c for c in codes if models[c].get('quote_at') and not models[c]['pending']]
        current=[c for c in valid if models[c]['eligible']]
        cov=len(valid)/len(codes)*100 if codes else 0.
        eligible=len(valid)>=P['board_min_members'] and cov>=P['board_min_coverage']
        boards.append(dict(id=b['id'],name=b['name'],type=b['type'],expected=len(codes),valid=len(valid),coverage_pct=r(cov),
            eligible=eligible,count=len(current),trend_pct=r(len(current)/len(valid)*100) if valid else None,
            stages={str(n):sum(models[c]['stage']==n for c in current) for n in LABELS},
            leaders=sorted(current,key=lambda c:sort_key(models[c]))[:3]))
        for c in current:
            if eligible:
                relation={k:boards[-1][k] for k in ('id','name','type','trend_pct','valid','expected','coverage_pct')}
                models[c].setdefault('board_relations',[]).append(relation)
                owner=owners[c]
                name=owner.get('industry_detail') or owner.get('industry')
                if b['type']=='industry' and (not models[c]['board'] or b['name']==name):
                    models[c]['board']=relation
    lists={str(n):sorted((c for c,m in models.items() if m['eligible'] and m['stage']==n),key=lambda c:sort_key(models[c])) for n in LABELS}
    active=sum(lists.values(),[])
    snap['ma_trend']=dict(version=VERSION,implementation_hash=IMPLEMENTATION_HASH,parameters=copy.deepcopy(P),at=str(now),
        source_at=max((m['quote_at'] for m in models.values() if m.get('quote_at')),default=None),
        mode=snap.get('session'),lists=lists,current=active,counts={n:len(codes) for n,codes in lists.items()},
        pending=[c for c,m in models.items() if m['pending']],
        advance=sorted((c for c,m in models.items() if m.get('advance') and not m['pending'] and m['status']!='已退出'),key=lambda c:sort_key(models[c])),
        displaced=[c for c,m in models.items() if m.get('displaced') and not m['pending']],
        startup_pending=[c for c,m in models.items() if m.get('startup_pending')],
        recovery_candidates=[c for c,m in models.items() if m.get('recovery_current')],
        repair=[c for c,m in models.items() if m['status']=='支撑失守·修复观察'],
        exited=[c for c,m in models.items() if m['status']=='已退出'],
        boards=sorted((b for b in boards if b['eligible'] and b['count']),key=lambda b:(-b['trend_pct'],-b['count'],b['id'])),
        minute_cursor=0,minute_requested=fetch_stats.get('requested',0),minute_needed=len(needed),minute_fetch=fetch_stats,
        sorting={'5':'事件、起点新近度、起点实体、量比、行业同步','10':'事件、整理量比、整理区间、行业同步','20':'事件、横盘区间、整理量比、行业同步'})
    snap['ma_trend']['daily_cache']=dict(
        hits=_DAILY_STATS['hits']-daily_stats_before['hits'],
        misses=_DAILY_STATS['misses']-daily_stats_before['misses'],
        clears=_DAILY_STATS['clears']-daily_stats_before['clears'],
        entries=len(_DAILY_CACHE), day=_DAILY_CACHE_DAY)
    import board_stock_rank
    board_stock_rank.attach(snap)
    return snap['ma_trend']


def validate(snap):
    import board_stock_rank
    board_stock_rank.validate(snap)
    meta=snap['ma_trend'];assert meta['version']==VERSION and meta['implementation_hash']==IMPLEMENTATION_HASH
    models={r['code']:r['ma_trend'] for r in snap.get('stocks',[])+snap.get('coverage_catalog',[])}
    assert len(meta['current'])==len(set(meta['current']))
    for n in LABELS:
        expected=sorted((c for c,m in models.items() if m['eligible'] and m['stage']==n),key=lambda c:sort_key(models[c]))
        assert meta['lists'][str(n)]==expected
        assert meta['counts'][str(n)]==len(expected)
    assert meta['current']==sum(meta['lists'].values(),[])
    assert meta['recovery_candidates']==[c for c,m in models.items() if m.get('recovery_current')]
    for m in models.values():
        assert m['version']==VERSION
        if m.get('recovery_current'):
            event=m['recovery_candidate']
            assert event['active'] and not m['pending'] and not m.get('reference_only') and not m.get('exit_at')
            assert 1<=event['age_sessions']<=P['limit_recovery_candidate_days'] and '涨停收复' in m['events']
        else:assert '涨停收复' not in m['events']
        if m['eligible']:
            assert m['stage'] in LABELS and m['origin'] and positive(m['support_price']) and m['status']!='已退出'
            assert not m['pending'] and not m.get('provisional') and not m.get('position_state')
            assert m['cycle_id']==m['origin']['date']
            chain=m['transitions'];assert chain and chain[0]['from_stage'] is None and chain[0]['to_stage']==5
            assert all(t['cycle_id']==m['cycle_id'] and (t['from_stage'],t['to_stage']) in ((None,5),(5,10),(10,20)) for t in chain)
            assert chain[-1]['to_stage']==m['stage']
            for left,right in zip(chain,chain[1:]):assert left['to_stage']==right['from_stage']
            if m['stage']==10:
                assert m['ma10_gain']['rise_pct']>=P['ma10_rise_pct'] and m['ma10_gain']['rise_atr']>=P['ma10_rise_atr']
            proof=m['origin'].get('confirmation') or {}
            assert m['origin']['volume_ratio'] is not None or proof
            if proof:
                assert proof['kind'] in ('涨停收复后推进确认','涨停起涨后强势确认','涨停重建均线后确认','MA20整理后再启动')
                assert proof['event_date']==m['origin']['date']<=proof['date']<=m['asof']
                assert proof['close']>=proof['ma5'] and proof['close']>=proof['ma10']
                if proof['kind']=='涨停收复后推进确认':
                    assert proof['minimum_days']<=proof['follow_days']<P['limit_recovery_candidate_days']
                    assert proof['close']>max(proof['previous_close'],proof['event_close']) and proof['ma10_held']
                    assert proof['ma5']>proof['ma5_previous'] and proof['ma10']>proof['ma10_previous']
                if proof['kind']=='涨停起涨后强势确认':assert proof['independent_signal']['date']==proof['date']
                if proof['kind']=='涨停重建均线后确认':
                    assert proof['reset_date']<proof['event_date']<proof['date']
                    if proof['previous_exit']:assert proof['previous_exit']<proof['event_date']
                    else:assert proof['event_previous_close']<proof['event_previous_ma10']
                    assert 2<=proof['window_sessions']<=P['origin_days'] and proof['ma5_held']
                    assert proof['event_sealed'] and proof['confirmation_sealed']
                    assert abs(proof['event_return_pct']-10)<=P['limit_return_tolerance_pp']
                    assert abs(proof['confirmation_return_pct']-10)<=P['limit_return_tolerance_pp']
                    assert proof['ma5']>proof['ma5_previous'] and proof['ma10']>proof['ma10_previous']
                if proof['kind']=='MA20整理后再启动':
                    assert proof['prior_stage']==20 and proof['prior_origin']<=proof['event_date']
                    assert proof['prior_rise_pct']>=P['ma20_rise_pct'] and proof['prior_rise_atr']>=P['ma20_rise_atr']
            if m['stage']==20:
                assert positive(m['primary_support_price'])
                assert m['support_price']==ma20_defense(m['primary_support_price'],m['platform'])
                evidence=m.get('ma20_entry') or m['platform']
                assert evidence['rise_pct']>=P['ma20_rise_pct'] and evidence['rise_atr']>=P['ma20_rise_atr']
                if m.get('secondary_support_price') is not None:
                    assert ma20_backup(m['platform']) and m['secondary_support_price']==m['platform']['low']
                    assert m['platform']['latest_cycle']
                if m.get('secondary_support_price') is not None and P['ma20_retained_gain']:
                    assert m['platform']['retained_pct']>=P['ma20_rise_pct'] and m['platform']['retained_atr']>=P['ma20_rise_atr']
        if m['status']=='已退出':assert not m['eligible'] and m['exit_at']
        if m.get('progressing') and m['status']!='已退出' and not m.get('pending') and not m.get('reference_only'):
            event=m['restart_event'];proof=event['confirmation']
            assert m['stage'] in (10,20) and proof['prior_stage']==m['stage']
            assert proof['prior_origin']==m['origin']['date']<=event['date']<proof['date']<=m['asof']
            assert proof['close']>max(proof['previous_close'],proof['event_close'])
            assert m['origin']['date']==m['cycle_id']
    return True
