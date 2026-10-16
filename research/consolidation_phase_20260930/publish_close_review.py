"""规则升级后的收市复核：只替换整理留档，不修改日线评分或真实盘中历史。"""
import copy
from datetime import datetime
import gzip
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config
import intraday
import intraday_path
import strength
import trend_consolidation as tc

folder=Path(__file__).resolve().parent
source=json.loads((folder.parent/'trend_strict_20260930'/'before_snapshot.json').read_text(encoding='utf-8'))
assert source['session']=='已收盘' and source['strength_model']['asof']<'2026-09-30'
with gzip.open(folder.parent/'trend_consolidation_20260930'/'frozen_inputs.json.gz','rt',encoding='utf-8') as stream:klines=json.load(stream)['klines']
calendar=strength.trading_calendar({c:[b for b in bs if b['date']<'2026-09-30'] for c,bs in klines.items()})
record=None
with gzip.open(intraday.HISTORY_DIR/'acquisitions'/'2026-09-30.jsonl.gz','rt',encoding='utf-8') as stream:
    for line in stream:
        candidate=json.loads(line)
        if candidate['captured_at']==source['quote_capture_at']:record=candidate;break
assert record is not None
quotes={r[0]:dict(zip(record['fields'][1:],r[1:])) for r in record['rows']}
history=intraday_path.load(intraday.HISTORY_DIR,'2026-09-30')
history={'points':{c:[p for p in ps if str(p.get('acquired_at') or '')<source['quote_capture_at']]
                   for c,ps in history['points'].items()}}
contexts={r['code']:intraday.align_price_basis(quotes.get(r['code'],{}),klines.get(r['code'],[]),calendar,
    observation_day='2026-09-30',quote_at=r.get('intraday_judgment_at'))
    for r in source['stocks']+source.get('coverage_catalog',[]) if r.get('intraday_observation_available')}
work=copy.deepcopy(source)
work['session']='尾盘' # 离线规则复核仅复用计算函数；产物明确标为收市参考，不发布盘中事件。
model=tc.attach(work,klines,quotes,contexts,calendar,history=history)
model.update(current_count=0,reference_count=model['count'],review_mode='rule_upgrade_close_review',
    observed_at=datetime.now().isoformat(sep=' ',timespec='seconds'),
    review_note='按15:00收市实际报价复核整理/初启动；已整理完毕转强已移出主名单，不是历史盘中信号')
model['phase_note']=model['review_note']
for r in model['rows']:
    r.update(reference_only=True,reference_reason=model['review_note'])
    assert r['trend_online'] is True and r['live_trend_online'] is True
    assert r['impulse5_pct']>=15 or r['impulse10_pct']>=20
    assert r['phase'] in ('consolidating','initial')
    if r['needs_repair_confirmation'] and r['phase']=='initial':assert r['repair_samples']>=2
    assert r['quote_at'].startswith('2026-09-30 15:00:')
    assert r['price']==source['boundary_prices']['close']['prices'][r['code']]['price']
codes={'002487','000710','600059','002388','601811'}
assert not codes.intersection(r['code'] for r in model['rows'])
assert codes.issubset(r['code'] for r in model['completed_rows'])
for r in model['completed_rows']:r.update(reference_only=True,reference_reason=model['review_note'])
work['session']='已收盘'
tc.attach(work,klines,quotes,contexts,calendar,previous={'trend_consolidation':model})
with gzip.open(folder/'reviewed_close_snapshot.json.gz','wt',encoding='utf-8') as stream:json.dump(work,stream,ensure_ascii=False)
config.atomic_write_text(tc.DIRECTORY/'2026-09-30.json',json.dumps(model,ensure_ascii=False,separators=(',',':')))
evidence=dict(model=model,source_at=source['quote_capture_at'],named={c:next((r for r in model['completed_rows'] if r['code']==c),
    next(r['trend_consolidation'] for r in work['stocks']+work.get('coverage_catalog',[]) if r['code']==c))
    for c in codes})
(folder/'verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(version=model['version'],reference_count=model['count'],current_count=0,
    completed_count=model['completed_count'],baseline=model['baseline_asof'],quote_at=model['last_valid_quote_at'],reviewed_at=model['observed_at']),ensure_ascii=False))
