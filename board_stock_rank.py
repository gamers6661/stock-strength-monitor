"""Complete, board-relative stock ranks. Neither axis is a dragon prediction."""
import math

VERSION='board-stock-rank-2026-10-14.1'
SORTING='分别按趋势力度、情绪强度排板块内名次；优先更靠前的一轴（按有效成员数归一），再比该轴强度和另一轴。缺失数据排后；并列同名次。'

def numeric(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def rank_axis(codes,rows,axis):
    scores={c:(rows.get(c,{}).get('market_strength') or {}).get(axis+'_score') for c in codes}
    scores={c:s for c,s in scores.items() if numeric(s)}
    ordered=sorted(scores,key=lambda c:(-scores[c],c))
    first={}
    for i,c in enumerate(ordered,1):first.setdefault(scores[c],i)
    ranks={c:first[scores[c]] for c in ordered}
    return ordered,ranks,scores

def attach(snap):
    rows={r['code']:r for r in snap.get('stocks',[])+snap.get('coverage_catalog',[])}
    groups=list(snap.get('board_catalog',[]))+[dict(id='all',member_codes=list(rows))]
    for board in groups:
        codes=list(dict.fromkeys(board.get('member_codes') or []));axes={a:rank_axis(codes,rows,a) for a in ('trend','emotion')}
        def priority(c):
            # All first-place members share zero distance from the front. The
            # two axes can have different data coverage; that must not break a
            # first-place tie before comparing absolute strength.
            choices=sorted(((axes[a][1][c]-1)/max(1,len(axes[a][0])-1),-axes[a][2][c],a) for a in axes if c in axes[a][1])
            return (0,*choices[0][:2],-max((axes[a][2].get(c,-1) for a in axes)),c) if choices else (1,1,1,1,c)
        ordered=sorted(codes,key=priority);items={}
        for position,c in enumerate(ordered,1):
            row=rows.get(c,{})
            ms=row.get('market_strength') or {};mt=row.get('ma_trend') or {}
            trend=bool(mt.get('stage') and not mt.get('pending') and mt.get('status')!='已退出' and (mt.get('eligible') or mt.get('advance')))
            emotion=bool(ms.get('emotion_strong') and numeric(ms.get('emotion_score')))
            labels=['趋势观察'] if trend else []
            if not trend and mt.get('stage') and not mt.get('pending') and mt.get('status')!='已退出':labels.append('趋势跟踪')
            if emotion:labels.append('情绪强势')
            if mt.get('recovery_current'):labels.append('涨停收复')
            if not labels:labels=['暂未强势'] if any(c in axes[a][1] for a in axes) else ['数据待核验']
            for axis,title in (('trend','趋势'),('emotion','情绪')):
                if axes[axis][1].get(c,999)<=3 and axes[axis][2].get(c,-1)>=65:labels.append(title+'前排')
            member=next((r for r in board.get('members',[]) if r['code']==c),{}) if c not in rows else {}
            items[c]=dict(rank=position,trend_rank=axes['trend'][1].get(c),emotion_rank=axes['emotion'][1].get(c),
                style_labels=labels,trend=trend,emotion=emotion,missing=c not in rows,
                name=row.get('name') or member.get('name') or c,
                source_at=ms.get('quote_at') or ms.get('emotion_at') or mt.get('quote_at'))
        ranking=dict(all=ordered,trend=axes['trend'][0]+[c for c in ordered if c not in axes['trend'][1]],
            emotion=axes['emotion'][0]+[c for c in ordered if c not in axes['emotion'][1]],
            items=items,expected=len(codes),trend_valid=len(axes['trend'][0]),emotion_valid=len(axes['emotion'][0]))
        if board['id']=='all':snap['stock_board_ranking']=dict(version=VERSION,sorting=SORTING,all=ranking)
        else:board['stock_ranking']=ranking
    return snap['stock_board_ranking']

def validate(snap):
    for board in snap.get('board_catalog',[]):
        ranks=board['stock_ranking'];expected=set(board.get('member_codes') or [])
        assert set(ranks['all'])==expected and len(ranks['all'])==len(expected)
        assert set(ranks['items'])==expected
        for axis in ('trend','emotion'):assert set(ranks[axis])==expected
    return True
