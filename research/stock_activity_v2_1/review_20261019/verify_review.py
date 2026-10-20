"""只读既有冻结输入，对照上一轮V2.1实现与修订实现。"""
import gzip
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT))
import config
import stock_activity as A
import stock_activity_engine as E


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def main():
    started=time.monotonic()
    base=HERE.parent
    with gzip.open(base/'snapshot.before.json.gz','rt',encoding='utf8') as f:snap=json.load(f)
    with gzip.open(base/'frozen_inputs.json.gz','rt',encoding='utf8') as f:bundle=json.load(f)
    at=A.stamp(snap['quote_capture_at'])
    with gzip.open(base/'input_acquisitions/stock_activity_samples/2026-10-19.jsonl.gz','rt',encoding='utf8') as f:
        raw=[json.loads(line) for line in f][-1]
    record=dict(captured_at=raw['captured_at'],session=raw['session'],quotes={r[0]:dict(zip(raw['fields'][1:],r[1:])) for r in raw['rows']})
    page=A.live_view(snap,now=at,record=record)
    model=A.build(page,bundle['histories'],bundle['calendar'],frames=bundle['frames'])
    saved=model.pop('_state')
    repeated=A.build(page,bundle['histories'],bundle['calendar'],frames=bundle['frames'],previous=saved)
    repeated.pop('_state')
    assert repeated==model,'重启结果不一致'
    rule_module=sys.modules['stock_activity_rules']
    try:
        sys.modules['stock_activity_rules']=module('previous_rules',HERE/'before/stock_activity_rules.py')
        old_engine=module('previous_engine',HERE/'before/stock_activity_engine.py')
    finally:sys.modules['stock_activity_rules']=rule_module
    old=old_engine.build(page,bundle['histories'],bundle['calendar'],frames=bundle['frames'])
    old.pop('_state')
    changes=[dict(code=c,before=old['items'][c]['list_name'],after=m['list_name']) for c,m in model['items'].items() if m['list_name']!=old['items'][c]['list_name']]
    manifest=json.loads((HERE/'scope_before.json').read_text(encoding='utf8'))
    scope={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==v for f,v in manifest.items() if f!='shared_snapshot'}
    with config.SNAPSHOT_JSON.open('rb') as f:scope['shared_snapshot']=hashlib.file_digest(f,'sha256').hexdigest()==manifest['shared_snapshot']
    assert all(scope.values()),scope
    for m in model['items'].values():
        if m['role']=='独立进攻' and m['event']:assert not E.confirmed(m['event'],'timing')
        assert m['current_state'] in (None,'推进','领先保持','强势整理','转弱','失效')
    with gzip.open(HERE/'model.review.json.gz','wt',encoding='utf8') as f:json.dump(model,f,ensure_ascii=False)
    baseline=json.loads((base/'frozen_verification.json').read_text(encoding='utf8'))
    report=dict(version=A.VERSION,score_version=A.SCORE_VERSION,implementation_hash=A.IMPLEMENTATION_HASH,
        source_at=model['source_at'],captured_at=model['captured_at'],frames=len(bundle['frames']),
        counts=model['counts'],previous_counts=old['counts'],membership_changes=changes,
        same_input_baselines={k:v for k,v in baseline['comparisons'].items() if k in ('today_change','multi_period_rs','industry_top')},
        restart_same_result=True,scope_unchanged=scope,seconds=round(time.monotonic()-started,3),
        limitation='真实输入的确定性及两版差异验证；尚无独立核心标签与样本外效果结论。')
    (HERE/'frozen_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='same_input_baselines'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
