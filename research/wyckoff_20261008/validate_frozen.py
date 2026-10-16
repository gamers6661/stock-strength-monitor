"""在本轮冻结原报价上验证新增观察，不改任何原评分、主榜及风险字段。"""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import datafeed
import intraday
import intraday_path
import strength
import wyckoff_structure as w

def run():
    state_before = w.STATE_FILE.read_bytes() if w.STATE_FILE.exists() else None
    with gzip.open(ROOT/'backups/latest_before_wyckoff_round1/snapshot.json.gz','rt',encoding='utf-8') as f:
        snap=json.load(f)
    before=deepcopy(snap)
    acquisition=None
    with gzip.open(ROOT/'cache/intraday_history/acquisitions'/
                   (snap['quote_capture_at'][:10]+'.jsonl.gz'),'rt',encoding='utf-8') as f:
        for line in f:
            record=json.loads(line)
            if record['captured_at']==snap['quote_capture_at']:acquisition=record;break
    if acquisition is None:raise RuntimeError('未找到冻结扫描的实际原始报价，禁止补造协议字段')
    quotes={r[0]:dict(zip(acquisition['fields'][1:],r[1:])) for r in acquisition['rows']}
    conn=sqlite3.connect('file:'+str(ROOT/'cache/market.db')+'?mode=ro',uri=True)
    rows=snap['stocks']+snap.get('coverage_catalog',[])
    series={r['code']:datafeed.load_kline(conn,'kline','code',r['code']) for r in rows}
    asof=snap['strength_model']['asof']
    completed={c:[b for b in bars if b['date']<=asof] for c,bars in series.items()}
    calendar=strength.trading_calendar(completed)
    contexts={c:intraday.align_price_basis(q,series[c],calendar,
                  observation_day=snap['generated_at'][:10],quote_at=q.get('quote_at'))
              for c,q in quotes.items() if c in series}
    model=w.attach(snap,series,calendar,contexts=contexts)
    stripped=deepcopy(snap)
    stripped.pop('wyckoff_structure')
    for row in stripped['stocks']+stripped.get('coverage_catalog',[]):row.pop('wyckoff_structure',None)
    assert stripped==before,'新增结构改变了原模型字段'
    assert model['count']>0,'实际冻结输入没有形成结构，需检查接线'
    assert all(not x['events'] for x in model['rows']),'首次部署不得回填旧事件'
    state_after = w.STATE_FILE.read_bytes() if w.STATE_FILE.exists() else None
    assert state_after == state_before, '冻结验证不得写生产周期'
    evidence=dict(snapshot_at=snap['generated_at'],quote_capture_at=acquisition['captured_at'],
                  source='实际留存的原始报价与本地同源日线',rows_compared=len(rows),
                  original_snapshot_fields_unchanged=True,structure_count=model['count'],
                  state_counts=model['state_counts'],backfilled_events=model['event_count'],
                  structures=model['rows'])
    out=Path(__file__).resolve().parent/'frozen_comparison.json'
    out.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in evidence.items() if k!='structures'},ensure_ascii=False))

if __name__=='__main__':run()
