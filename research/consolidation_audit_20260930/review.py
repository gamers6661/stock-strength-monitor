"""全池冻结输入对照与七例逐日回放；显式--publish才更新收盘整理留档。"""
import copy,gzip,importlib.util,json,sys
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config,intraday,intraday_path,strength,trend_consolidation as tc
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
    model=module.attach(work,klines,quotes,contexts,calendar,history=history)
    return work,model
spec=importlib.util.spec_from_file_location('audit_old_model',folder/'before'/'trend_consolidation.py')
old_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(old_module)
with gzip.open(folder/'before_snapshot.json.gz','rt',encoding='utf-8') as f:old_parameters=json.load(f)['trend_consolidation']['parameters']
with patch.object(config,'TREND_CONSOLIDATION',old_parameters):old_work,old=compute(old_module)
work,model=compute(tc)
assert len(old['completed_rows'])==33 and old['count']==20
main={r['code'] for r in model['rows']};completed={r['code'] for r in model['completed_rows']}
assert not main.intersection(completed)
assert not {'600641','002242'}.intersection(completed)
for r in model['rows']+model['completed_rows']:
    assert r['attack_trend_online'] and r['days']>=2
    assert r['impulse5_pct']>=15 or r['impulse10_pct']>=20
    if r['phase']=='completed':
        assert r['completion_confirmed'] and r['price']>=r['completion_trigger_price']-0.0001
        assert r['completion_type'] in ('平台突破转强','回踩修复转强')
for a,b in zip(old_work['stocks']+old_work.get('coverage_catalog',[]),work['stocks']+work.get('coverage_catalog',[])):
    assert {k:v for k,v in a.items() if k!='trend_consolidation'}=={k:v for k,v in b.items() if k!='trend_consolidation'}
def category(code,m):
    for group in ('rows','completed_rows','pending_rows','withdrawn_rows'):
        for r in m[group]:
            if r['code']==code:return dict(group=group,**r)
    row=next((r for r in work['stocks']+work.get('coverage_catalog',[]) if r['code']==code),{})
    return dict(group='excluded',reason=(row.get('trend_consolidation') or {}).get('reason','整理资格未通过'))
changes=[dict(code=r['code'],name=r['name'],before=r,after=category(r['code'],model)) for r in old['completed_rows']]
data=json.loads((folder/'audit.json').read_text(encoding='utf-8'))
inputs=json.loads((folder/'inputs.json').read_text(encoding='utf-8'))
names={'600641':'先导基电','002242':'九阳股份','002487':'大金重工','000710':'贝瑞基因',
       '600059':'古越龙山','002388':'新亚制程','601811':'新华文轩'}
cases={};future_differences=0
for code,name in names.items():
    rows=[]
    for day in [d for d in data['calendar'] if d>='2026-08-01']:
        full=tc.daily_setup(inputs[code],day,data['calendar'])
        cut=tc.daily_setup([b for b in inputs[code] if b['date']<=day],day,data['calendar'])
        future_differences+=int(full!=cut)
        rows.append(dict(day=day,**full))
    cases[code]=dict(name=name,rows=rows,current=category(code,model))
assert future_differences==0
model.update(current_count=0,reference_count=model['count'],review_mode='rule_upgrade_close_review',
    observed_at=datetime.now().isoformat(sep=' ',timespec='seconds'),
    review_note='按15:00真实报价复核；须先有合格整理，转强经连续采样或完成日确认，且当前守住转强位置；非历史实盘信号')
model['phase_note']=model['review_note']
for r in model['rows']+model['completed_rows']:r.update(reference_only=True,reference_reason=model['review_note'])
work['session']='已收盘';tc.attach(work,klines,quotes,contexts,calendar,previous={'trend_consolidation':model})
with gzip.open(folder/'reviewed_close_snapshot.json.gz','wt',encoding='utf-8') as f:json.dump(work,f,ensure_ascii=False)
evidence=dict(version=tc.VERSION,before_main=old['count'],before_completed=len(old['completed_rows']),
    main=model['count'],completed=len(model['completed_rows']),pending=len(model['pending_rows']),
    withdrawn=len(model['withdrawn_rows']),pool=len(work['stocks'])+len(work.get('coverage_catalog',[])),
    source_at=source['quote_capture_at'],before_other_stock_changes=0,future_isolation_differences=future_differences,
    completed_changes=changes,cases=cases,model=model)
(folder/'review.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# 七例回放与整个完成名单复核','',
       '同一全池冻结输入，不按案例设置生产白名单。日线回放不是历史实盘预警或收益。','',
       '| 个股 | 9月14日起整理资格通过日 | 完成整理确认日 | 当前收盘复核类别 |',
       '| --- | --- | --- | --- |']
for code,item in cases.items():
    recent=[r for r in item['rows'] if r['day']>='2026-09-14']
    observed='、'.join(r['day'][5:] for r in recent if r['eligible']) or '未通过'
    ended='、'.join(sorted({r['completed_at'][5:] for r in recent if r.get('phase')=='completed'})) or '未确认'
    lines.append('| '+item['name']+' | '+observed+' | '+ended+' | '+item['current']['group']+' |')
lines+=['','类别：rows=整理观察；completed_rows=已整理完毕转强；pending_rows=待确认/待核验；withdrawn_rows=转弱退出；excluded=前置资格未通过。','',
        '| 原完成名单 | 本次分类 | 本次原因 |','| --- | --- | --- |']
for r in changes:lines.append('| '+r['name']+' '+r['code']+' | '+r['after']['group']+' | '+(r['after'].get('reason') or r['after'].get('stage') or '整理资格未通过')+' |')
(folder/'名单全量复核.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
if '--publish' in sys.argv:
    config.atomic_write_text(tc.DIRECTORY/'2026-09-30.json',json.dumps(model,ensure_ascii=False,separators=(',',':')))
print(json.dumps({k:v for k,v in evidence.items() if k not in ('model','cases','completed_changes')},ensure_ascii=False))
print(json.dumps({c:dict(name=i['name'],current=i['current']['group'],reason=i['current'].get('reason')) for c,i in cases.items()},ensure_ascii=False))
