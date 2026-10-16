"""核对仅改整理分类，并回放真实午休输入。"""
import gzip
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import intraday
import intraday_path
import strength
import trend_consolidation as tc

folder=Path(__file__).resolve().parent
before=json.loads((folder.parent/'trend_strict_20260930'/'before_snapshot.json').read_text(encoding='utf-8'))
with gzip.open(folder/'reviewed_close_snapshot.json.gz','rt',encoding='utf-8') as stream:after=json.load(stream)
top_changes=[k for k in before if k not in ('trend_consolidation','stocks','coverage_catalog') and before[k]!=after[k]]
row_changes=0
for collection in ('stocks','coverage_catalog'):
    b=before.get(collection,[]);a=after.get(collection,[])
    assert len(b)==len(a)
    for old,new in zip(b,a):
        row_changes+=int({k:v for k,v in old.items() if k!='trend_consolidation'} !=
                         {k:v for k,v in new.items() if k!='trend_consolidation'})
assert not top_changes and row_changes==0

with gzip.open(folder.parent/'intraday_path_20260930'/'first_published_snapshot.json.gz','rt',encoding='utf-8') as stream:snap=json.load(stream)
with gzip.open(folder.parent/'trend_consolidation_20260930'/'frozen_inputs.json.gz','rt',encoding='utf-8') as stream:klines=json.load(stream)['klines']
record=None
with gzip.open(intraday.HISTORY_DIR/'acquisitions'/'2026-09-30.jsonl.gz','rt',encoding='utf-8') as stream:
    for line in stream:
        candidate=json.loads(line)
        if candidate['captured_at']==snap['quote_capture_at']:record=candidate;break
assert record is not None
quotes={r[0]:dict(zip(record['fields'][1:],r[1:])) for r in record['rows']}
calendar=strength.trading_calendar({c:[b for b in bs if b['date']<'2026-09-30'] for c,bs in klines.items()})
contexts={r['code']:intraday.align_price_basis(quotes.get(r['code'],{}),klines.get(r['code'],[]),calendar,
    observation_day='2026-09-30',quote_at=r.get('intraday_judgment_at'))
    for r in snap['stocks']+snap.get('coverage_catalog',[]) if r.get('intraday_observation_available')}
history=intraday_path.load(intraday.HISTORY_DIR,'2026-09-30')
history={'points':{c:[p for p in ps if str(p.get('acquired_at') or '')<snap['quote_capture_at']]
                   for c,ps in history['points'].items()}}
model=tc.attach(snap,klines,quotes,contexts,calendar,history=history)
assert model['count']>0
for r in model['rows']:
    assert r['quote_at']=='2026-09-30 11:30:00'
    assert r['price']==snap['boundary_prices']['midday']['prices'][r['code']]['price']
codes={'002487','000710','600059','002388','601811'}
assert not codes.intersection(r['code'] for r in model['rows'])
old=json.loads((folder/'before_model.json').read_text(encoding='utf-8'))
latest=json.loads((folder/'verification.json').read_text(encoding='utf-8'))['model']
old_codes={r['code'] for r in old['rows']};new_codes={r['code'] for r in latest['rows']}
evidence=dict(other_top_field_changes=top_changes,other_stock_field_changes=row_changes,
              midday_count=model['count'],midday_judgment=model['last_valid_quote_at'],
              midday_boundary_prices_match=True,midday_completed=len(model['completed_rows']),
              old_count=len(old_codes),new_count=len(new_codes),retained=len(old_codes&new_codes),
              removed=len(old_codes-new_codes),added=len(new_codes-old_codes))
(folder/'controls.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(evidence,ensure_ascii=False))
