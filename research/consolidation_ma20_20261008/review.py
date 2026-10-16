# -*- coding: utf-8 -*-
"""同一全池真实采样对照；收盘复核另列；显式--publish才发布版本升级留档。"""
import copy,gzip,importlib.util,json,sys
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config,datafeed,intraday,intraday_path,strength,trend_consolidation as tc
folder=Path(__file__).resolve().parent
source=json.loads((folder.parent/'trend_strict_20260930'/'before_snapshot.json').read_text(encoding='utf-8'))
with gzip.open(folder.parent/'trend_consolidation_20260930'/'frozen_inputs.json.gz','rt',encoding='utf-8') as stream:
    klines=json.load(stream)['klines']
calendar=strength.trading_calendar({c:[b for b in bs if b['date']<'2026-09-30'] for c,bs in klines.items()})
with gzip.open(intraday.HISTORY_DIR/'acquisitions'/'2026-09-30.jsonl.gz','rt',encoding='utf-8') as stream:
    record=next(json.loads(line) for line in stream if json.loads(line)['captured_at']==source['quote_capture_at'])
quotes={r[0]:dict(zip(record['fields'][1:],r[1:])) for r in record['rows']}
history=intraday_path.load(intraday.HISTORY_DIR,'2026-09-30')
history={'points':{c:[p for p in ps if str(p.get('acquired_at') or '')<source['quote_capture_at']]
                   for c,ps in history['points'].items()}}
contexts={r['code']:intraday.align_price_basis(quotes.get(r['code'],{}),klines.get(r['code'],[]),calendar,
    observation_day='2026-09-30',quote_at=r.get('intraday_judgment_at'))
    for r in source['stocks']+source.get('coverage_catalog',[]) if r.get('intraday_observation_available')}
def compute(module):
    work=copy.deepcopy(source);work['session']='尾盘'
    # 隔离正在运行的留档，确保前后只使用完全相同的输入。
    with patch.object(module,'DIRECTORY',folder/'isolated_empty_archive'):
        model=module.attach(work,klines,quotes,contexts,calendar,history=history)
    return work,model
spec=importlib.util.spec_from_file_location('ma20_old_model',folder/'before'/'trend_consolidation.py')
old_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(old_module)
spec_tracking=importlib.util.spec_from_file_location('old_tracking',folder/'before'/'consolidation_tracking.py')
old_tracking=importlib.util.module_from_spec(spec_tracking);spec_tracking.loader.exec_module(old_tracking)
old_module.consolidation_tracking=old_tracking
old_work,old=compute(old_module)
work,model=compute(tc)
assert old['count']==13 and len(old['completed_rows'])==14
main={r['code'] for r in model['rows']};completed={r['code'] for r in model['completed_rows']}
assert not main.intersection(completed)
assert not {'600641','002242'}.intersection(completed)
for r in model['rows']+model['completed_rows']:
    assert r['attack_trend_online'] and r['days']>=2
    assert r['impulse5_pct']>=15 or r['impulse10_pct']>=20
    if r['phase']=='completed':
        assert r['completion_confirmed'] and not r['trend_exited']
        assert r['completion_type'] in ('平台突破转强','回踩修复转强')
other_changes=0
for a,b in zip(old_work['stocks']+old_work.get('coverage_catalog',[]),work['stocks']+work.get('coverage_catalog',[])):
    other_changes+=int({k:v for k,v in a.items() if k!='trend_consolidation'}!={k:v for k,v in b.items() if k!='trend_consolidation'})
assert other_changes==0
entry_changes=sum({k:v for k,v in old_module._daily_setup(bs,'2026-09-29',calendar).items() if k!='platform_low'}!={k:v for k,v in tc._daily_setup(bs,'2026-09-29',calendar).items() if k!='platform_low'} for bs in klines.values())
assert entry_changes==0
def category(code,m):
    for group in tc.GROUPS:
        for r in m[group]:
            if r['code']==code:return dict(group=group,**r)
    return dict(group='excluded')
all_codes={r['code'] for m in (old,model) for group in tc.GROUPS for r in m[group]}
changes=[dict(code=c,before=category(c,old),after=category(c,model)) for c in sorted(all_codes)
         if (category(c,old)['group'],category(c,old).get('stage'))!=(category(c,model)['group'],category(c,model).get('stage'))]
intraday_model=copy.deepcopy(model)
model.update(current_count=0,reference_count=model['count'],review_mode='rule_upgrade_close_review',
    observed_at=datetime.now().isoformat(sep=' ',timespec='seconds'),
    review_note='按15:00真实采样重算转强后MA20跟踪，并用正式完成日线独立复核；属于规则升级复核，非历史实盘预警')
model['phase_note']=model['review_note']
for r in model['rows']+model['completed_rows']:r.update(reference_only=True,reference_reason=model['review_note'])
conn=datafeed.db()
close_klines={c:datafeed.load_kline(conn,'kline','code',c,limit=120) for c in all_codes}
conn.close()
close_calendar=strength.trading_calendar(close_klines)
with gzip.open(folder/'formal_close_inputs.json.gz','wt',encoding='utf-8') as stream:json.dump(dict(klines=close_klines,calendar=close_calendar),stream,ensure_ascii=False)
work['session']='已收盘';work['strength_model']['asof']='2026-09-30'
closed=tc.attach(work,close_klines,quotes,contexts,close_calendar,previous={'trend_consolidation':model})
with gzip.open(folder/'reviewed_close_snapshot.json.gz','wt',encoding='utf-8') as f:json.dump(work,f,ensure_ascii=False)
evidence=dict(version=tc.VERSION,before_main=old['count'],before_completed=len(old['completed_rows']),
    intraday_main=intraday_model['count'],intraday_completed=len(intraday_model['completed_rows']),
    main=closed['count'],completed=len(closed['completed_rows']),pending=len(closed['pending_rows']),withdrawn=len(closed['withdrawn_rows']),
    pool=len(work['stocks'])+len(work.get('coverage_catalog',[])),source_at=source['quote_capture_at'],
    entry_qualification_changes=entry_changes,other_stock_field_changes=other_changes,
    changes=changes,intraday_model=intraday_model,model=closed)
(folder/'review.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# 全池同输入复核','','正式收盘复核与15:00盘中重算分开；以下均为规则升级复核，不是历史实盘预警。','',
       '| 个股 | 原类别/状态 | 新盘中类别/状态 | 原因 |','| --- | --- | --- | --- |']
for change in changes:
    a,b=change['before'],change['after']
    lines.append('| '+(b.get('name') or a.get('name') or change['code'])+' '+change['code']+' | '+a['group']+' / '+a.get('stage','')+' | '+b['group']+' / '+b.get('stage','')+' | '+b.get('reason','')+' |')
(folder/'名单复核.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in evidence.items() if k not in ('model','intraday_model','changes')},ensure_ascii=False))
print(json.dumps({r['name']:r['stage'] for r in closed['completed_rows']+closed['withdrawn_rows'] if r.get('completion_confirmed')},ensure_ascii=False))
