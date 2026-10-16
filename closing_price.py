"""Shared completed-close evidence. Source timestamps are never rewritten."""
from decimal import Decimal,ROUND_HALF_UP
from datetime import datetime,timedelta
from pathlib import Path
import hashlib,math
import config,intraday

IMPLEMENTATION_HASH=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def positive(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>0
def tick(v):return Decimal(str(v)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)

def assessment_time(snap,now):
    # The acquisition can precede the completed daily verification in one scan.
    # Advance only the evaluation clock to an actually observed verification;
    # the source quote clock remains untouched.
    at=intraday.parse_quote_timestamp(snap.get('close_daily_verified_at'))
    if (snap.get('session')=='已收盘' and at and at.date()==now.date() and at.hour*60+at.minute>=905
        and at<=datetime.now()+timedelta(seconds=config.INTRADAY['max_quote_future_seconds'])):return max(now,at)
    return now

def verify(snap,q,bars,calendar,now):
    at=intraday.parse_quote_timestamp(q.get('quote_at') or q.get('ts'))
    verified=intraday.parse_quote_timestamp(snap.get('close_daily_verified_at'))
    if (snap.get('session')!='已收盘' or not verified or verified.date()!=now.date() or
        verified.hour*60+verified.minute<905 or (verified-now).total_seconds()>config.INTRADAY['max_quote_future_seconds']):return None
    if not at or at.date()!=now.date() or at.hour<15 or (at-now).total_seconds()>config.INTRADAY['max_quote_future_seconds']:return None
    if q.get('price_basis')!='raw' or q.get('price_basis_source') not in intraday._RAW_QUOTE_SOURCES or q.get('last_close_semantics')!='previous_trade_day_raw_close':return None
    if not (positive(q.get('amount_wan')) or positive(q.get('volume_shou'))):return None
    native=[b for b in bars if b.get('date')==now.date().isoformat()]
    if len(native)!=1:return None
    native=native[0]
    if not intraday._valid_historical_price_bar(native) or not positive(native.get('volume')):return None
    sources={('qfq',s) for s in intraday._QFQ_HISTORY_SOURCES}|{('raw',s) for s in intraday._RAW_HISTORY_SOURCES}
    if (native.get('price_basis'),native.get('price_basis_source')) not in sources:return None
    context=intraday.align_price_basis(q,bars,calendar,observation_day=now.date().isoformat(),allow_partial=True)
    if not context.get('valid') or not positive(context.get('scale_factor')):return None
    # Today's native bar must use the same scale/source as the aligned history.
    previous=next((b for b in reversed(bars) if b.get('date')==context['last_history_date']),None)
    if not previous or (previous.get('price_basis'),previous.get('price_basis_source'))!=(native.get('price_basis'),native.get('price_basis_source')):return None
    factor=context['scale_factor'];converted={k:native[k]*factor for k in ('open','high','low','close')}
    for key,qkey in (('open','open'),('high','high'),('low','low'),('close','price')):
        if not positive(q.get(qkey)) or tick(converted[key])!=tick(q[qkey]):return None
    return dict(date=native['date'],verified_at=str(verified),quote_at=str(at),history_source=native['price_basis_source'],history_basis=native['price_basis'],scale_factor=factor,
        prices={k:float(tick(v)) for k,v in converted.items()},verified_suspension_days=[],
        inferred_suspension_days=(context.get('history_observation') or {}).get('suspension_days',[]),
        basis='已完成独立日线按经核验尺度转换，逐项匹配报价开高低收；保留实际收盘后源时刻')

def matches(proof,q,now):
    if not proof:return False
    at=intraday.parse_quote_timestamp(q.get('quote_at') or q.get('ts'))
    verified=intraday.parse_quote_timestamp(proof.get('verified_at'))
    if (not at or at.date()!=now.date() or at.hour<15 or proof.get('date')!=now.date().isoformat() or proof.get('quote_at')!=str(at)
        or not verified or verified.date()!=now.date() or verified.hour*60+verified.minute<905
        or max((at-now).total_seconds(),(verified-now).total_seconds())>config.INTRADAY['max_quote_future_seconds']):return False
    if q.get('price_basis')!='raw' or q.get('price_basis_source') not in intraday._RAW_QUOTE_SOURCES or q.get('last_close_semantics')!='previous_trade_day_raw_close':return False
    return all(positive((proof.get('prices') or {}).get(k)) and positive(q.get(qk)) and tick(proof['prices'][k])==tick(q[qk])
        for k,qk in (('open','open'),('high','high'),('low','low'),('close','price')))
