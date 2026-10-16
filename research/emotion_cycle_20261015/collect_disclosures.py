import json,sys
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import relay_regulation as R,relay_data as D
OUT=Path(__file__).resolve().parent;cal=json.loads((OUT/'calendar.json').read_text(encoding='utf-8'));audit=json.loads((OUT/'audit20.json').read_text(encoding='utf-8'));raw=json.loads((OUT/'raw_universe.json').read_text(encoding='utf-8'))['raw'];focus=set()
for r in audit['top']:focus.add(r['code'])
for c,r in raw.items():
 bars=[b for b in r['bars'] if b['date'] in cal[-30:]];n=0
 for a,b in zip(bars,bars[1:]):
  n=n+1 if D.tick(b['close'])==D.tick(b['high'])==D.tick(D.limit_price(a['close'])) else 0
  if n>=1:focus.add(c)
ref=json.loads((OUT/'reference_universe.json').read_text(encoding='utf-8'))['reference']
for r in audit['unknown']:
 if r['code'] in ref:focus.add(r['code'])
focus.update(('600825','002343','601811','605577'))
print('focus',len(focus),flush=True)
now=datetime.now();result=R.load(sorted(focus),cal,now,fetch=True,budget_seconds=480)
(OUT/'disclosures.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('covered',len(result['covered_codes']),'notices',len(result['notices']),'intervals',len(result['suspension_intervals']),'errors',result['errors'],flush=True)
print('xinhua',[(n['title'],n['published_at'],n['available_day'],n['kind']) for n in result['notices'] if '600825' in n['codes']],flush=True)
print('intervals',[(r['code'],r['start'],r['resume']) for r in result['suspension_intervals']],flush=True)
print('indices',[(k,len(v['bars'])) for k,v in result['indices'].items()],flush=True)
