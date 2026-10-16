"""校验实际看板导出函数与正在运行的快照一致。"""
import csv
import gzip
import json
from pathlib import Path

folder=Path(__file__).resolve().parent
with gzip.open(folder/'live_snapshot.json.gz','rt',encoding='utf-8') as stream:
    snapshot=json.load(stream)
with (folder/'导出验收.csv').open(encoding='utf-8-sig',newline='') as stream:
    reader=csv.DictReader(stream)
    columns=reader.fieldnames
    rows=list(reader)
assert len(rows)==len(snapshot['stocks'])+len(snapshot.get('coverage_catalog',[]))
assert len(columns)==171
eligibility=next(c for c in columns if '整理' in c and '资格' in c)
code_field=next(c for c in columns if c in ('代码','股票代码'))
cases=['002487','000710','600059','002388','601811']
case_rows={r[code_field]:r for r in rows if r[code_field] in cases}
assert set(case_rows)==set(cases)
assert all(r[eligibility]=='已完成整理，退出观察' for r in case_rows.values())
model=snapshot['trend_consolidation']
main={r['code'] for r in model['rows']}
completed={r['code'] for r in model['completed_rows']}
assert not main.intersection(completed)
assert not main.intersection(cases) and set(cases).issubset(completed)
evidence=dict(rows=len(rows),columns=len(columns),cases={c:r[eligibility] for c,r in case_rows.items()},
              main_completed_disjoint=True,generated_at=snapshot['generated_at'])
(folder/'export_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(evidence,ensure_ascii=False))
