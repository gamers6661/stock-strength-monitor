from pathlib import Path
import json,copy,hashlib,sys
from datetime import datetime
sys.path.insert(0,str(Path.cwd()))
import market_strength as M
out=Path('research/market_strength_v1_20261013');base=out/'baseline'
f=json.loads((base/'frozen_complete_inputs.json').read_text(encoding='utf8'));old=json.loads((base/'cache/snapshot.json').read_text(encoding='utf8'));s=copy.deepcopy(old)
before=hashlib.sha256((base/'frozen_complete_inputs.json').read_bytes()).hexdigest()
raw=json.loads((base/'raw_acquisition_113111.json').read_text(encoding='utf8'))
raw_quotes={r[0]:dict(zip(raw['fields'][1:],r[1:])) for r in raw['rows']}
assert raw['captured_at']==f['now']
for c,q in raw_quotes.items():
    assert all(f['quotes'][c].get(k)==v for k,v in q.items()), (c,'raw acquisition mismatch')
M.attach(s,f['quotes'],f['pool'],f['histories'],f['calendar'],now=datetime.fromisoformat(f['now']));M.validate(s)
oldrows={r['code']:r for r in old['stocks']+old['coverage_catalog']};newrows={r['code']:r for r in s['stocks']+s['coverage_catalog']}
compare={c:dict(name=r['name'],old_score=oldrows[c].get('stock_strength_score'),old_current=(oldrows[c].get('radar_opportunity') or {}).get('current'),new=r['market_strength']) for c,r in newrows.items()}
invariants={k:hashlib.sha256(json.dumps(f[k],sort_keys=True,ensure_ascii=False).encode()).hexdigest() for k in ('quotes','histories','pool','calendar','boards')}
assert before==hashlib.sha256((base/'frozen_complete_inputs.json').read_bytes()).hexdigest()
assert [b['member_codes'] for b in old['board_catalog']]==[b['member_codes'] for b in s['board_catalog']]
assert [{k:v for k,v in b.items() if k.startswith('index_')} for b in old['board_catalog']]==[{k:v for k,v in b.items() if k.startswith('index_')} for b in s['board_catalog']]
(out/'frozen_after.json').write_text(json.dumps(s,ensure_ascii=False,separators=(',',':')),encoding='utf8')
(out/'comparison.json').write_text(json.dumps(dict(now=f['now'],input_hash=before,invariants=invariants,raw_inputs_unchanged=True,counts=s['market_strength']['counts'],board_counts=s['market_strength']['board_counts'],stocks=compare,boards={b['id']:b['market_strength'] for b in s['board_catalog']}),ensure_ascii=False,indent=2),encoding='utf8')
print(s['market_strength']['counts'],s['market_strength']['board_counts'])
