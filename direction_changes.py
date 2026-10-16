"""Small same-session observation ring; changes never gate strength eligibility."""
import copy
import hashlib
import json
from datetime import datetime
from statistics import mean


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def timestamp(value):
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def number(value):
    import math
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def attach(snap, previous, stocks, models, boards, rows, quotes, now, *, reference, parameters, implementation_hash):
    import market_strength as M
    p = parameters
    old_ring = (previous or {}).get('direction_observations', [])
    if reference and (previous or {}).get('market_strength',{}).get('implementation_hash') == implementation_hash:
        # A reference view keeps the last real comparison and its original date.
        # It must neither erase that evidence nor mint a new quote observation.
        snap['direction_observations']=copy.deepcopy(old_ring)
        snap['direction_changes']=copy.deepcopy(previous.get('direction_changes',{}))
        return
    valid = {c: [q.get('change_pct'), stocks[c].get('trend_score'), stocks[c].get('emotion_score')]
             for c, q in quotes.items() if c in stocks and stocks[c].get('quote_at') and number(q.get('change_pct'))}
    times = [timestamp(quotes[c].get('quote_at')) for c in valid]
    times = [t for t in times if t and t.date() == now.date() and t <= now]
    source = max(times) if times and not reference else None
    stock_pool_hash = digest(sorted(stocks))
    memberships = {b['id']: digest(sorted(b.get('member_codes', []))) for b in boards}
    sample = dict(at=str(source) if source else None, version=implementation_hash, pool_hash=stock_pool_hash,
                  stocks=valid, boards={i:dict(trend=m.get('trend_score'), emotion=m.get('emotion_score'),
                      membership=memberships[i]) for i,m in models.items()})
    sample['quote_evidence']={c:dict(at=stocks[c]['quote_at'],return_pct=quotes[c]['change_pct'],limit_pct=quotes[c].get('limit_pct'))
                             for c in valid}
    ring = [s for s in old_ring if s.get('version') == implementation_hash and timestamp(s.get('at'))
            and timestamp(s['at']).date() == now.date() and (not source or timestamp(s['at']) < source)]
    candidates = []
    if source:
        for s in ring:
            minutes = (source-timestamp(s['at'])).total_seconds()/60
            if p['direction_compare_min_minutes'] <= minutes <= p['direction_compare_max_minutes'] and s.get('pool_hash') == stock_pool_hash:
                candidates.append((abs(minutes-p['direction_compare_minutes']),s))
    baseline = min(candidates,key=lambda pair:pair[0])[1] if candidates else None
    changes = []
    old_models={r['code']:r.get('market_strength',{}) for r in (previous or {}).get('stocks',[])+(previous or {}).get('coverage_catalog',[])}
    for b in boards:
        i=b['id']; m=models[i]; expected=set(m.get('expected_codes', []))
        m['direction_change'] = None
        m['member_strength'] = dict(trend_pct=None,emotion_pct=None,valid=0,expected=len(expected))
        live_codes = [c for c in expected if c in valid]
        cov=M.coverage(live_codes,expected)
        if cov['eligible']:
            m['member_strength'].update(valid=len(live_codes),
                trend_pct=100*mean(number(valid[c][1]) and valid[c][1]>=p['strong_min'] for c in live_codes),
                emotion_pct=100*mean(number(valid[c][2]) and valid[c][2]>=p['strong_min'] for c in live_codes))
        old=(baseline or {}).get('boards',{}).get(i)
        if not old or old.get('membership') != memberships[i]:
            continue
        common=[c for c in expected if c in valid and c in baseline['stocks']]
        if not M.coverage(common,expected)['eligible']:
            continue
        current_return,_=M.trim({c:valid[c][0] for c in common})
        prior_return,_=M.trim({c:baseline['stocks'][c][0] for c in common})
        if not number(current_return) or not number(prior_return):
            continue
        delta_return=current_return-prior_return
        details=dict(from_at=baseline['at'],to_at=str(source),minutes=(source-timestamp(baseline['at'])).total_seconds()/60,
                     common_count=len(common),expected=len(expected),return_delta_pp=round(delta_return,4),axes={})
        for axis,index in (('trend',1),('emotion',2)):
            codes=[c for c in common if number(valid[c][index]) and number(baseline['stocks'][c][index])]
            if not M.coverage(codes,expected)['eligible'] or not number(m.get(axis+'_score')) or not number(old.get(axis)):
                continue
            current_share=100*mean(valid[c][index]>=p['strong_min'] for c in codes)
            prior_share=100*mean(baseline['stocks'][c][index]>=p['strong_min'] for c in codes)
            score=m[axis+'_score'];before=old[axis]
            kind=None
            # Relative-rank changes alone cannot claim a direction is strengthening.
            if score>=p['strong_min'] and delta_return>0:
                if before<p['strong_min'] and current_share>=prior_share:
                    kind='新进入强势'
                elif before>=p['strong_min'] and current_share>prior_share:
                    kind='强势继续增强'
            a=dict(score_delta=round(score-before,4),share_delta_pp=round(current_share-prior_share,4),
                   current_share_pct=round(current_share,2),prior_share_pct=round(prior_share,2),kind=kind)
            details['axes'][axis]=a
            if kind:
                changes.append(dict(id=i,name=b['name'],type=b['type'],axis=axis,score=score,**a,
                                    return_delta_pp=round(delta_return,4),from_at=baseline['at'],to_at=str(source)))
        if details['axes']:
            m['direction_change']=details
    for c,m in stocks.items():
        dp=m.get('trend_parts_by_period',{}).get(str(m.get('dominant_period')), {})
        ep=m.get('emotion_parts', {})
        m['display_evidence']=dict(structure=('结构受损' if number(dp.get('K')) and dp['K']<p['structure_factors']['pullback'] else
            '结构保持' if number(dp.get('K')) else '—'),drawdown_atr=dp.get('dd'),hold=ep.get('H'),
            ma_distance_pct={str(n):100*(quotes[c]['price']/part['MA_now']-1) for n,part in
                ((n,m.get('trend_parts_by_period',{}).get(str(n),{})) for n in (5,10,20))
                if c in quotes and number(part.get('MA_now')) and part['MA_now']>0})
        m['new_strong_axes']=[]
        hist=m.get('history_trend',[])
        if m.get('trend_strong') and hist and number(hist[-1].get('score')) and hist[-1]['score']<p['strong_min']:
            m['new_strong_axes'].append(dict(axis='trend',basis='前一完成日',from_at=hist[-1]['date'],to_at=m.get('quote_at')))
        old_model=old_models.get(c,{})
        old_at=timestamp(old_model.get('quote_at'))
        current_at=timestamp(m.get('quote_at'))
        if (previous or {}).get('market_strength',{}).get('implementation_hash')==implementation_hash and old_at and current_at and old_at.date()==current_at.date() and old_at<current_at:
            for axis in ('trend','emotion'):
                if m.get(axis+'_strong') and number(old_model.get(axis+'_score')) and old_model[axis+'_score']<p['strong_min']:
                    m['new_strong_axes'].append(dict(axis=axis,basis='上一有效行情',from_at=str(old_at),to_at=str(current_at)))
        labels=[]
        if m['new_strong_axes']:labels.append('新进入强势')
        labels.extend(m.get('events',[]))
        if m.get('phase')=='推进':labels.append('趋势推进')
        if m.get('phase')=='回踩整理':labels.append('回踩整理')
        if m.get('emotion_strong'):labels.append('情绪进攻')
        if any(r in m.get('risks',[]) for r in ('大幅下跌','接近跌停','一字跌停')):labels.append('明显回落')
        m['labels']=list(dict.fromkeys(labels))
    # No new quote timestamp means no synthetic observation, including after close.
    if source and valid:
        ring.append(sample)
    snap['direction_observations']=ring[-p['direction_observations_max']:]
    changes.sort(key=lambda r:(r['kind']!='新进入强势',-r['share_delta_pp'],-r['return_delta_pp'],-r['score'],r['id']))
    snap['direction_changes']=dict(source_at=str(source) if source else None,
        from_at=baseline['at'] if baseline else None,items=changes,
        temperature_change=None)
    if baseline:
        common=sorted(set(valid)&set(baseline['stocks']))
        if common:
            snap['direction_changes']['temperature_change']=dict(from_at=baseline['at'],to_at=str(source),common_count=len(common),
                up_ratio_delta_pp=round(100*(mean(valid[c][0]>0 for c in common)-mean(baseline['stocks'][c][0]>0 for c in common)),2))
    # The list projection is built after labels, from exactly the same model objects.
    for b in boards:
        for r in b.get('members',[]):
            if r['code'] in stocks:r['market_strength']=M.brief(stocks[r['code']])
