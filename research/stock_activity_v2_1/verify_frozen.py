"""同一冻结行情输入比较；不写运行状态，不发网络请求。"""
import copy
import gzip
import hashlib
import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import config
import datafeed
import stock_activity as A

HERE=Path(__file__).resolve().parent


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def main():
    started=time.monotonic()
    with gzip.open(HERE/'snapshot.before.json.gz','rt',encoding='utf8') as stream:snap=json.load(stream)
    before=digest(snap)
    codes={r['code'] for r in snap['stocks']+snap.get('coverage_catalog',[])}
    bundle=HERE/'frozen_inputs.json.gz'
    if bundle.exists():
        with gzip.open(bundle,'rt',encoding='utf8') as stream:stored=json.load(stream)
        histories,calendar=stored['histories'],stored['calendar']
    else:
        con=sqlite3.connect('file:'+config.KLINE_DB.as_posix()+'?mode=ro',uri=True)
        try:histories={c:datafeed.load_kline(con,'kline','code',c,limit=90) for c in codes}
        finally:con.close()
        dates={}
        for bars in histories.values():
            for b in bars:dates[b['date']]=dates.get(b['date'],0)+1
        calendar=sorted(d for d,n in dates.items() if n>=len(codes)*.5)
    at=A.stamp(snap['quote_capture_at'])
    frames=[]
    for folder in sorted((HERE/'input_acquisitions').iterdir()):
        frames.extend(A.archive_frames(at,codes,folder,formal=True))
    frames.sort(key=lambda f:f[0])
    with gzip.open(HERE/'frozen_inputs.json.gz','wt',encoding='utf8',compresslevel=1) as stream:
        json.dump(dict(histories=histories,calendar=calendar,frames=frames),stream,ensure_ascii=False,separators=(',',':'))
    archive=HERE/'input_acquisitions'/'stock_activity_samples'/(str(at.date())+'.jsonl.gz')
    with gzip.open(archive,'rt',encoding='utf8') as stream:records=[json.loads(line) for line in stream]
    raw=records[-1]
    quote_record=dict(captured_at=raw['captured_at'],session=raw['session'],
                      quotes={r[0]:dict(zip(raw['fields'][1:],r[1:])) for r in raw['rows']})
    page_snap=A.live_view(snap,now=at,record=quote_record)
    model=A.build(page_snap,histories,calendar,frames=frames)
    state=model.pop('_state')
    assert digest(snap)==before, '共享快照被本页模型修改'
    repeated=A.build(page_snap,histories,calendar,frames=frames,previous=state)
    repeated.pop('_state')
    assert repeated==model, '同一源时点重启后结果不同'
    with gzip.open(HERE/'model.v21.json.gz','wt',encoding='utf8') as stream:json.dump(model,stream,ensure_ascii=False)
    spec=importlib.util.spec_from_file_location('stock_activity_legacy_frozen',HERE/'before'/'stock_activity.py')
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    old=legacy.build(page_snap,histories,calendar,frames=frames)
    assert digest(snap)==before
    rows={r['code']:r for r in snap['stocks']+snap.get('coverage_catalog',[])}
    def pct(c):return rows[c].get('change_pct') or 0.
    def rs(c):
        bars=[b for b in histories[c] if b['date']<str(at.date())]
        if len(bars)<21:return -999.
        return sum((bars[-1]['close']/bars[-h-1]['close']-1)*100*w for h,w in ((5,.5),(10,.3),(20,.2)))
    def top(codes):
        return [dict(code=c,name=rows[c].get('name'),change_pct=pct(c),
                     score=model['items'][c]['score'],role=model['items'][c]['role'],
                     list_name=model['items'][c]['list_name'],reason=model['items'][c]['reasons']) for c in codes[:20]]
    daily_rank=sorted(rows,key=pct,reverse=True)
    rs_rank=sorted(rows,key=rs,reverse=True)
    industry_rank=[]
    for group in set(model['assignments'].values()):
        industry_rank.extend(sorted([c for c in rows if model['assignments'].get(c)==group],key=pct,reverse=True)[:3])
    report=dict(rule_version=A.VERSION,score_version=A.SCORE_VERSION,implementation_hash=A.IMPLEMENTATION_HASH,
        snapshot_at=snap['quote_capture_at'],source_at=model['source_at'],frames=len(frames),
        shared_snapshot_unchanged=True,input_digest=before,restart_same_result=True,
        counts=model['counts'],legacy_counts=old['counts'],
        comparisons=dict(v21_core=top([c for c in model['order'] if model['items'][c]['list_name']=='core']),
                         v21_startup=top([c for c in model['order'] if model['items'][c]['list_name']=='startup']),
                         v21_daily_reference=top([c for c in model['order'] if model['items'][c]['list_name']=='reference']),
                         legacy=top([c for c in old['order'] if old['items'][c]['eligible']]),
                         today_change=top(daily_rank),multi_period_rs=top(rs_rank),industry_top=top(industry_rank)),
        seconds=round(time.monotonic()-started,3),
        limitation='单个冻结时点及当天采样回放，仅验证可重复与名单差异；无独立核心标注或样本外收益结论。')
    (HERE/'frozen_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='comparisons'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
