"""Completed-day explanatory factors; research candidates do not change core weights."""
from statistics import mean


def price_observations(bars):
    closes=[b['close'] for b in bars[-11:]]
    changes=[b-a for a,b in zip(closes,closes[1:])]
    distance=sum(abs(v) for v in changes)
    efficiency=max(0.,closes[-1]-closes[0])/distance if distance else 0.
    # Close-to-close recovery: latest peak followed by a drawdown, then first recovery.
    values=[b['close'] for b in bars[-21:]];peak=values[0];peak_i=0;episode=None
    for i,p in enumerate(values[1:],1):
        if p<peak and (episode is None or episode['recovered']):
            episode=dict(peak=peak,start=peak_i,trough=p,recovered=False,recovery_days=None)
        if episode and not episode['recovered']:
            episode['trough']=min(episode['trough'],p)
            if p>=episode['peak']:
                episode.update(recovered=True,recovery_days=i-episode['start'])
        if p>=peak:peak=p;peak_i=i
    return dict(advance_efficiency=100*efficiency,
        recovery_days=episode['recovery_days'] if episode else None,
        recovery_observed=episode is not None,recovered=episode['recovered'] if episode else None,
        unrecovered_days=len(values)-1-episode['start'] if episode and not episode['recovered'] else None,
        pullback_depth_pct=100*(1-episode['trough']/episode['peak']) if episode else None)


def attach_observations(item,bars,records,fund_record,refs,daily_medians,calendar):
    import stock_selection as S
    e=item['evidence'];day=item['daily_at'];code=item['code']
    downside=[refs[d][code]-v for d,v in daily_medians.items()
              if d<=day and v<0 and code in refs[d]]
    e['down_market_days']=len(downside)
    e['down_market_excess_pp']=mean(downside) if len(downside)>=3 else None
    e['down_market_note']='至少3个市场下跌日；仅观察，不加分'
    # Candidate only. Keep its changed persistence separate from the current score.
    price_candidate=e['price']+.25*(.5*e['advance_efficiency']-.5*e['persistence'])
    e['candidate_price']=round(price_candidate,2)
    d=item['dimensions']
    e['candidate_score']=round(.45*price_candidate+.30*d['relative']+.25*d['volume'],2) if all(v is not None for v in d.values()) else None
    e['candidate_note']='推进效率替换一半持续性；研究对照，未用于入选及默认排序'
    fund=item['fund'];frows={r.get('date'):r.get('main_net') for r in fund_record.get('rows',[])} if fund_record.get('source')=='新浪超大单+大单日级净额' else {}
    amount=S.amounts.verified_amount(bars[-1],records.get(day))
    fund['net_amount_pct']=100*fund['main_net']/amount if fund.get('available') and amount else None
    dates=[d for d in calendar if d<=day][-5:]
    complete=len(dates)==5 and all(S.number(frows.get(d)) for d in dates)
    fund['positive_days5']=sum(frows[d]>0 for d in dates) if complete else None
    fund['ratio_reason']=None if fund['net_amount_pct'] is not None else '同日已核验资金或真实成交额不足'
    fund['ratio_basis']='同日供应商大单净额 / 已核验真实成交额；不同源统计口径，仅观察'


def pattern_order(item):
    """Lexicographic order inside a path, not a new combined strength score."""
    e=item['evidence'];p=item['pattern'];live=item['intraday']
    if p in ('突破启动','再启动','盘中突破待确认'):
        return [int(p!='盘中突破待确认'),int(live.get('held',False)),e.get('clv',0),-(e.get('drawdown_atr') or 0),item.get('score') or 0]
    if p=='强势整理':
        return [int(bool(item.get('anchor'))),-(e.get('drawdown_atr') or 0),-(e.get('range_contraction') or 0),e.get('advance_efficiency',0),item.get('score') or 0]
    return [e.get('advance_efficiency',0),item['dimensions'].get('relative') or 0,-(e.get('drawdown_atr') or 0),item.get('score') or 0]


def board_continuity(board,previous,day,calendar,members):
    import hashlib
    identity=hashlib.sha256('|'.join(sorted(members)).encode()).hexdigest()[:16]
    previous=previous or {};days=[d for d in calendar if d<day]
    supported=bool(board.get('available') and board.get('label')=='板块支持')
    if previous.get('day')==day and previous.get('members')==identity:
        streak=previous.get('streak',0) if supported else 0
        if supported and not streak:streak=1
    else:
        continuous=bool(days and previous.get('day')==days[-1] and previous.get('members')==identity)
        streak=(previous.get('streak',0) if continuous else 0)+1 if supported else 0
    board['support_observed_days']=streak if board.get('available') else None
    board['continuity_note']=('连续记录 '+str(streak)+' 个完成交易日；记录起点之前未知') if supported else '当前未满足板块支持' if board.get('available') else '同行数据不足，连续性暂停'
    return dict(day=day,members=identity,streak=streak)
