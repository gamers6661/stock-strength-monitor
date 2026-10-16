"""同输入规则对照、三个案例和真实午休/收市输入验收；不写运行快照。"""
from collections import Counter
import copy
import gzip
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config
import intraday
import intraday_path
import strength
import trend_consolidation as tc

folder=Path(__file__).resolve().parent
prior=folder.parent/'trend_consolidation_20260930'
with gzip.open(prior/'frozen_inputs.json.gz','rt',encoding='utf-8') as stream:frozen=json.load(stream)
klines=frozen['klines']
calendar=strength.trading_calendar({c:[b for b in bs if b['date']<'2026-09-30'] for c,bs in klines.items()})
spec=importlib.util.spec_from_file_location('old_consolidation',folder/'before'/'trend_consolidation.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
original_config=copy.deepcopy(config.TREND_CONSOLIDATION)
legacy_parameters=json.loads((folder/'before_model.json').read_text(encoding='utf-8'))['parameters']

def verify_rows(model):
    for r in model['rows']:
        assert r['trend_online'] and r['live_trend_online']
        assert r['impulse5_pct']>=15 or r['impulse10_pct']>=20
        assert r['impulse_end']<r['consolidation_start']
        if r['needs_repair_confirmation']:assert r['repair_samples']>=2

def replay(source,quotes,history):
    contexts={r['code']:intraday.align_price_basis(quotes.get(r['code'],{}),klines.get(r['code'],[]),calendar,
        observation_day='2026-09-30',quote_at=r.get('intraday_judgment_at'))
        for r in source['stocks']+source.get('coverage_catalog',[]) if r.get('intraday_observation_available')}
    snap=copy.deepcopy(source)
    model=tc.attach(snap,klines,quotes,contexts,calendar,history=history)
    verify_rows(model)
    return snap,model

history=intraday_path.load(prior/'history','2026-09-30')
snap,model=replay(frozen['snapshot'],frozen['quotes'],history)
with patch.object(config,'TREND_CONSOLIDATION',legacy_parameters):
    legacy=copy.deepcopy(frozen['snapshot'])
    contexts={r['code']:intraday.align_price_basis(frozen['quotes'].get(r['code'],{}),klines.get(r['code'],[]),calendar,
        observation_day='2026-09-30',quote_at=r.get('intraday_judgment_at'))
        for r in legacy['stocks']+legacy.get('coverage_catalog',[]) if r.get('intraday_observation_available')}
    old_model=old.attach(legacy,klines,frozen['quotes'],contexts,calendar,history=history)

names={'002487':'大金重工','000710':'贝瑞基因','600059':'古越龙山','603231':'索宝蛋白'}
all_rows=snap['stocks']+snap.get('coverage_catalog',[])
named={c:dict(name=n,setup=next(r['trend_consolidation'] for r in all_rows if r['code']==c),
               in_main=any(r['code']==c for r in model['rows'])) for c,n in names.items()}
assert named['002487']['setup']['shape']=='整理后再突破'
assert named['000710']['setup']['expanded_down_dates']==['2026-09-28']
assert named['600059']['setup']['shape']=='横盘整理'
assert not named['603231']['in_main']

keys=('stock_strength_score','stock_strength_parts','stock_strength_percentile','trend_online','daily_attack_tier','signal_date')
before={r['code']:r for r in frozen['snapshot']['stocks']}
daily_changes={key:sum(r.get(key)!=before[r['code']].get(key) for r in snap['stocks']) for key in keys}
assert not any(daily_changes.values())
future_changes=0
for asof in calendar[-12:]:
    for c,bars in klines.items():
        short=[b for b in bars if b['date']<=asof]
        future_changes+=int(tc.daily_setup(bars,asof,calendar)!=tc.daily_setup(short,asof,calendar))
assert future_changes==0

with gzip.open(prior.parent/'intraday_path_20260930'/'first_published_snapshot.json.gz','rt',encoding='utf-8') as stream:lunch=json.load(stream)
close=json.loads((folder/'before_snapshot.json').read_text(encoding='utf-8'))
acquisitions={}
with gzip.open(intraday.HISTORY_DIR/'acquisitions'/'2026-09-30.jsonl.gz','rt',encoding='utf-8') as stream:
    for line in stream:
        record=json.loads(line)
        if record['captured_at'] in (lunch['quote_capture_at'],close['quote_capture_at']):acquisitions[record['captured_at']]=record
whole_history=intraday_path.load(intraday.HISTORY_DIR,'2026-09-30')
results={}
for label,source in [('lunch',lunch),('close_review',close)]:
    acquired=acquisitions[source['quote_capture_at']]
    quotes={r[0]:dict(zip(acquired['fields'][1:],r[1:])) for r in acquired['rows']}
    past={'points':{c:[p for p in ps if str(p.get('acquired_at') or '') < source['quote_capture_at']]
                    for c,ps in whole_history['points'].items()}}
    if label=='close_review':
        assert source['session']=='已收盘' and source['strength_model']['asof']<'2026-09-30'
        assert source['boundary_prices']['close']['captured_at'].startswith('2026-09-30')
        # 仅离线复核收市实际报价；发布时全部标为参考，不写盘中路径或事件。
        source=copy.deepcopy(source);source['session']='尾盘'
    checked,selected=replay(source,quotes,past)
    if label=='lunch':
        assert selected['count']>0
        for r in selected['rows']:
            assert r['quote_at']=='2026-09-30 11:30:00'
            assert r['price']==source['boundary_prices']['midday']['prices'][r['code']]['price']
    if label=='close_review':
        checked['session']='已收盘'
        selected.update(current_count=0,reference_count=selected['count'],review_mode='rule_upgrade_close_review',
            review_note='新规则按15:00收市实际报价复核，供下次开盘参考；不是盘中历史信号')
        selected['phase_note']=selected['review_note']
        for r in selected['rows']:
            r.update(reference_only=True,reference_reason=selected['review_note'])
            assert r['quote_at'].startswith('2026-09-30 15:00:')
            assert r['price']==source['boundary_prices']['close']['prices'][r['code']]['price']
        for r in checked['stocks']+checked.get('coverage_catalog',[]):
            if r['trend_consolidation'].get('quote_at'):r['trend_consolidation'].update(reference_only=True)
        with gzip.open(folder/'reviewed_close_snapshot.json.gz','wt',encoding='utf-8') as stream:json.dump(checked,stream,ensure_ascii=False)
    results[label]=dict(source_at=source['quote_capture_at'],count=selected['count'],rows=selected['rows'],
                       named={c:next(r['trend_consolidation'] for r in checked['stocks']+checked.get('coverage_catalog',[]) if r['code']==c) for c in names})

old_codes={r['code'] for r in old_model['rows']};new_codes={r['code'] for r in model['rows']}
evidence=dict(frozen_at=frozen['snapshot']['quote_capture_at'],old_count=len(old_codes),new_count=len(new_codes),
              retained_count=len(old_codes&new_codes),removed_count=len(old_codes-new_codes),
              added_count=len(new_codes-old_codes),named=named,daily_changes=daily_changes,
              future_isolation_changes=future_changes,excluded_counts=model['excluded_counts'],
              removed=[dict(code=c,name=next(r.get('name') for r in all_rows if r['code']==c),
                            reason=next(r['trend_consolidation'].get('reason','本轮结构未通过') for r in all_rows if r['code']==c)) for c in sorted(old_codes-new_codes)],
              rows=model['rows'],actual=results)
(folder/'verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
with gzip.open(folder/'replayed_snapshot.json.gz','wt',encoding='utf-8') as stream:json.dump(snap,stream,ensure_ascii=False)
print(json.dumps({k:v for k,v in evidence.items() if k not in ('named','rows','removed','actual')},ensure_ascii=False))
print(json.dumps({label:dict(count=r['count'],named={c:dict(shape=x.get('shape'),stage=x.get('stage'),reason=x.get('reason')) for c,x in r['named'].items()}) for label,r in results.items()},ensure_ascii=False))
