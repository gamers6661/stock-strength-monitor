"""Observed price/volume quality; each evaluation uses only bars already supplied."""
import math
from statistics import median


def clip(value, low=0., high=1.):
    return max(low, min(high, value))


def location(bar):
    width=bar['high']-bar['low']
    return (bar['close']-bar['low'])/width if width>0 else .5


def assess(bars, atr, medium_retention, has_advance, policy):
    tail=list(zip(bars[-11:-1],bars[-10:]))
    gains=[max(0.,b['close']-a['close']) for a,b in tail]
    total=sum(gains)
    index=max(range(len(gains)),key=gains.__getitem__)
    previous,event=tail[index]
    share=gains[index]/total if total>0 else 0.
    gap=clip(max(0.,event['open']-previous['close'])/gains[index]) if gains[index]>0 else 0.
    after=[b for b in bars if b['date']>event['date']][-policy['confirmation_days']:]
    held=sum(b['close']>=event['close'] and b['close']>=b['open']-.1*atr
             and location(b)>=.5 for b in after)
    concentration=clip((share-policy['concentration_floor'])/(1-policy['concentration_floor']))
    impulse_risk=concentration*(.5+.5*gap)
    confirmation=held/policy['confirmation_days']
    multiplier=1-policy['impulse_discount_max']*impulse_risk*(1-confirmation)
    recent=bars[-policy['retention_days']:]
    peak=max(b['high'] for b in recent);low=min(b['low'] for b in recent)
    local_dd=max(0.,peak-bars[-1]['close'])/atr
    local_retrace=clip((peak-bars[-1]['close'])/max(peak-low,atr))
    local=100*(.5*(1-clip(local_dd/3.5))+.5*(1-local_retrace)) if has_advance else 0.
    retention=policy['local_retention_weight']*local+(1-policy['local_retention_weight'])*medium_retention
    out=dict(version=policy['version'],impulse_date=event['date'],largest_gain_share=share,
             gap_gain_share=gap,confirmed_follow_days=held,impulse_multiplier=multiplier,
             medium_retention=medium_retention,local_retention=local,retention=retention,
             local_drawdown_atr=local_dd,local_retrace=local_retrace,
             volume_available=False,distribution_pressure=None,damage_multiplier=1.,
             volume_participation=None,volume_result=None,last_day_result=None)
    volume_ok=all(isinstance(b.get('volume'),(int,float)) and not isinstance(b['volume'],bool)
                  and math.isfinite(b['volume']) and b['volume']>0 for b in bars[-26:])
    if not volume_ok:return out
    reference=median(b['volume'] for b in bars[-21:-1])
    demand=supply=weighted_result=weights=0.;day_results=[];pressures=[]
    for i,(a,b) in enumerate(tail):
        move=(b['close']-a['close'])/atr;body=(b['close']-b['open'])/atr;pos=location(b)
        rv=b['volume']/reference
        direction=.4*clip(move,-1.,1.)+.4*clip(body,-1.,1.)+.2*(2*pos-1)
        excess=clip((rv-1)/(policy['excess_volume_full']-1))
        adverse=max(clip(-body)*(1-pos),clip(-move)*(1-pos),clip((.5-pos)/.5))
        pressure=excess*adverse
        outcome=100*clip(.5+.2*clip(move,-1.,1.)+.2*clip(body,-1.,1.)
                         +.1*(2*pos-1)-policy['volume_pressure_penalty']*pressure)
        weight=2**(-(len(tail)-1-i)/policy['volume_half_life'])
        demand+=weight*rv*max(0.,direction);supply+=weight*rv*max(0.,-direction)
        weighted_result+=weight*outcome;weights+=weight
        day_results.append(dict(date=b['date'],volume_ratio=rv,close_move_atr=move,
                                body_move_atr=body,close_position=pos,direction=direction,
                                pressure=pressure,result=outcome))
        age=len(tail)-1-i
        if age<policy['pressure_days']:
            latest=bars[-1]
            repaired=age>0 and latest['close']>=b['high'] and latest['close']>=latest['open'] and location(latest)>=.6
            pressures.append(0. if repaired else pressure*policy['pressure_decay']**age)
    activity=(demand+supply)/weights
    participation=100*demand/(demand+supply)*clip(activity/.5) if demand+supply>0 else 0.
    pressure=max(pressures,default=0.)
    out.update(volume_available=True,volume_participation=participation,
               volume_result=weighted_result/weights,last_day_result=day_results[-1]['result'],
               distribution_pressure=pressure,damage_multiplier=1-policy['price_damage_max']*pressure,
               day_results=day_results,demand_volume=demand/weights,supply_volume=supply/weights)
    return out
