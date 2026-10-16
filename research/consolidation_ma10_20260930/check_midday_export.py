"""验证真实午休边界与当前全池CSV；不构造盘中报价。"""
import csv,gzip,json,sys
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config,intraday,intraday_path,strength,trend_consolidation as tc
folder=Path(__file__).resolve().parent
with gzip.open(folder.parent/'intraday_path_20260930'/'first_published_snapshot.json.gz','rt',encoding='utf-8') as f:source=json.load(f)
with gzip.open(folder.parent/'trend_consolidation_20260930'/'frozen_inputs.json.gz','rt',encoding='utf-8') as f:klines=json.load(f)['klines']
calendar=strength.trading_calendar(klines)
with gzip.open(intraday.HISTORY_DIR/'acquisitions'/'2026-09-30.jsonl.gz','rt',encoding='utf-8') as f:
    record=next(json.loads(line) for line in f if json.loads(line)['captured_at']==source['quote_capture_at'])
quotes={r[0]:dict(zip(record['fields'][1:],r[1:])) for r in record['rows']}
history=intraday_path.load(intraday.HISTORY_DIR,'2026-09-30')
history={'points':{c:[p for p in ps if str(p.get('acquired_at') or '')<source['quote_capture_at']] for c,ps in history['points'].items()}}
contexts={r['code']:intraday.align_price_basis(quotes.get(r['code'],{}),klines.get(r['code'],[]),calendar,
    observation_day='2026-09-30',quote_at=r.get('intraday_judgment_at'))
    for r in source['stocks']+source.get('coverage_catalog',[]) if r.get('intraday_observation_available')}
with patch.object(tc,'DIRECTORY',folder/'isolated_empty_archive'):
    model=tc.attach(source,klines,quotes,contexts,calendar,history=history)
for row in model['rows']+model['completed_rows']:
    assert row['price']==source['boundary_prices']['midday']['prices'][row['code']]['price']
    assert row['quote_at']=='2026-09-30 11:30:00'
assert not {'600641','002242'}.intersection(r['code'] for r in model['completed_rows'])
if '--midday-only' in sys.argv:
    evidence=dict(midday_rows=model['count'],midday_completed=len(model['completed_rows']),
                  midday_prices_match=True,midday_quote_at=model['last_valid_quote_at'])
    (folder/'midday_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False));sys.exit(0)
with gzip.open(folder/'live_snapshot.json.gz','rt',encoding='utf-8') as f:snap=json.load(f)
with (folder/'导出验收.csv').open(encoding='utf-8-sig',newline='') as f:
    reader=csv.DictReader(f);columns=reader.fieldnames;rows=list(reader)
assert len(rows)==len(snap['stocks'])+len(snap.get('coverage_catalog',[])) and len(columns)==192
code_field=next(c for c in columns if c in ('代码','股票代码'))
eligibility=next(c for c in columns if '整理' in c and '资格' in c)
completed={r['code'] for r in snap['trend_consolidation']['completed_rows']}
exported={r[code_field] for r in rows if r[eligibility]=='已完成整理，进入转强跟踪'}
for group in tc.GROUPS:
    for item in snap['trend_consolidation'][group]:
        if not item.get('completion_confirmed'):continue
        record=next(r for r in rows if r[code_field]==item['code'])
        assert record['历史转强确认']=='是' and record['整理状态']==item['stage']
        assert record['MA10退出时间']==str(item.get('trend_exit_at') or '')
assert completed==exported and not {'600641','002242'}.intersection(exported)
evidence=dict(midday_rows=model['count'],midday_completed=len(model['completed_rows']),
    midday_prices_match=True,midday_quote_at=model['last_valid_quote_at'],
    export_rows=len(rows),export_columns=len(columns),export_completed_match=True,
    named_completed_absent=True)
(folder/'midday_export_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(evidence,ensure_ascii=False))
