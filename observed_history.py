"""Observed trading sessions. Calendar gaps are suspension assumptions, never candles."""
import math

VERSION='observed-sessions-2026-10-15.1'

def positive(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>0

def valid_bar(b):
    return (all(positive(b.get(k)) for k in ('open','high','low','close'))
        and b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high'])

def traded_bars(bars):
    """A zero-volume placeholder is a nontrading session, not an observed candle."""
    return [b for b in bars if b.get('volume')!=0]

def gaps(bars,calendar,through=None):
    dates=sorted({b['date'] for b in bars if b.get('date') and valid_bar(b)})
    if not dates:return []
    end=through or dates[-1];known=set(dates)
    return [d for d in calendar if dates[0]<=d<=end and d not in known]

def annotation(bars,calendar,through=None):
    missing=gaps(bars,calendar,through)
    return dict(version=VERSION,observed_days=len(bars),suspension_days=missing,
        inferred=True,basis='缺失交易日按停牌处理；均线及波段仅使用有效成交日，不补造OHLC')

def quote_traded(q,day):
    stamp=str(q.get('quote_at') or q.get('ts') or '').replace('-','').replace(' ','').replace(':','')
    return (stamp.startswith(day.replace('-','')) and all(positive(q.get(k)) for k in ('price','open','high','low'))
        and (positive(q.get('volume_shou')) or positive(q.get('amount_wan'))))

def inferred_quote_halt(q):
    return (q.get('data_availability') or {}).get('kind')=='inferred_suspension'
