"""冻结输入对照及按日期前推回放；事后收益只作描述，绝不用于资格或调参。"""
from collections import Counter
import copy
import gzip
import json
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import intraday
import intraday_path
import strength
import stock_strength
import trend_consolidation as tc

folder=Path(__file__).resolve().parent
with gzip.open(folder/'frozen_inputs.json.gz','rt',encoding='utf-8') as stream: frozen=json.load(stream)
before=frozen['snapshot']; snap=copy.deepcopy(before)
klines=frozen['klines']; quotes=frozen['quotes']; day=snap['quote_capture_at'][:10]
calendar=strength.trading_calendar({c:[b for b in bs if b['date']<day] for c,bs in klines.items()})
contexts={r['code']:intraday.align_price_basis(quotes.get(r['code'],{}),klines.get(r['code'],[]),calendar,
            observation_day=day,quote_at=r.get('intraday_judgment_at'))
          for r in snap['stocks']+snap.get('coverage_catalog',[]) if r.get('intraday_observation_available')}
history=intraday_path.load(folder/'history',day)
with patch.object(stock_strength,'_daily_path',side_effect=lambda d:folder/'a_history'/(d+'.json')):
    model=tc.attach(snap,klines,quotes,contexts,calendar,history=history)
    a_dates=tc.historical_a_dates(snap['strength_model']['asof'],calendar)
    forward=[]; setup_differences=0
    days=calendar[-15:]
    for asof in days:
        for code,bars in klines.items():
            truncated=[b for b in bars if b['date']<=asof]
            past=tc.daily_setup(truncated,asof,calendar,a_dates.get(code,()))
            full=tc.daily_setup(bars,asof,calendar,a_dates.get(code,()))
            setup_differences+=int(past!=full)
            if not past['eligible']: continue
            future=[b for b in bars if b['date']>asof][:3]
            if len(future)<3: continue
            start=truncated[-1]['close']
            forward.append(dict(code=code,asof=asof,days=past['days'],shape=past['shape'],
                                impulse5_pct=past['impulse5_pct'],return3_pct=round((future[-1]['close']/start-1)*100,3),
                                low3_pct=round((min(b['low'] for b in future)/start-1)*100,3)))

old_by={r['code']:r for r in before['stocks']}
differences={key:sum(r.get(key)!=old_by[r['code']].get(key) for r in snap['stocks']) for key in
             ('stock_strength_score','stock_strength_parts','stock_strength_percentile','trend_online','daily_attack_tier','signal_date')}
assert not any(differences.values())
assert setup_differences==0
legacy={r['code'] for n in (5,10,20) for k in ('main_rows','reclaim_rows') for r in before.get('trend_ma'+str(n)+'_observation',{}).get(k,[])}
selected={r['code'] for r in model['rows']}
names={r['code']:r.get('name') for r in snap['stocks']+snap.get('coverage_catalog',[])}
comparison=dict(legacy_count=len(legacy),new_count=len(selected),both=len(legacy&selected),
                new_only=[dict(code=c,name=names[c]) for c in sorted(selected-legacy)],
                legacy_only=[dict(code=c,name=names[c],reason=next(r['trend_consolidation'].get('reason','本轮结构或风险未通过')
                                for r in snap['stocks']+snap.get('coverage_catalog',[]) if r['code']==c)) for c in sorted(legacy-selected)])
named={c:next((r['trend_consolidation'] for r in snap['stocks']+snap.get('coverage_catalog',[]) if r['code']==c),{})
       for c in ('000710','002962','603231')}
evidence=dict(captured_at=snap['quote_capture_at'],model=model,daily_differences=differences,
              comparison=comparison,named=named,forward_days=days,forward_complete_samples=len(forward),
              forward_positive3=sum(r['return3_pct']>0 for r in forward),
              future_isolation_differences=setup_differences,
              notes=['按日独立前推，不用未来K线确定平台或进攻依据','3日结果仅为描述性统计，存在重复股票、重叠窗口和当前股票池存活偏差，不代表策略胜率'])
(folder/'replay_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
(folder/'forward_observations.json').write_text(json.dumps(forward,ensure_ascii=False,indent=2),encoding='utf-8')
with gzip.open(folder/'replayed_snapshot.json.gz','wt',encoding='utf-8') as stream: json.dump(snap,stream,ensure_ascii=False)
print(json.dumps(dict(frozen_candidates=model['count'],stages=dict(Counter(r['stage'] for r in model['rows'])),
                      old_near_line=len(legacy),new_only=len(selected-legacy),
                      daily_differences=differences,forward_complete_samples=len(forward),
                      future_isolation_differences=setup_differences,named={c:r.get('reason',r.get('shape')) for c,r in named.items()}),ensure_ascii=False))
