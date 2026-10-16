"""One-time complete-universe raw history acquisition with resumable caches."""
import json,sys,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import relay_data as D
OUT=Path(__file__).resolve().parent;universe=json.loads((OUT/'universe.json').read_text(encoding='utf-8'));cal=json.loads((OUT/'calendar.json').read_text(encoding='utf-8'));last=cal[-1]
need=[];records={};errors=[];start=time.monotonic()
for c in universe:
 r=D.read(D.root()/'raw'/(c+'.json'))
 if r:records[c]=r
 # Suspended securities are allowed to end before the market's last day; their
 # absence is resolved separately against dated suspension records.
 if not r or not any(b['date']==last for b in r['bars']) and universe[c].get('trade_status')!='no_trade':need.append(c)
print('request',len(need),'cached',len(records),flush=True)
with ThreadPoolExecutor(max_workers=6) as executor:
 jobs={executor.submit(D.fetch_raw,c):c for c in need}
 for n,job in enumerate(as_completed(jobs),1):
  c=jobs[job]
  try:r=job.result();records[c]=r;D.write(D.root()/'raw'/(c+'.json'),r)
  except Exception as e:errors.append(dict(code=c,reason=str(e)))
  if n%100==0 or n==len(jobs):print('collected',n,'/',len(jobs),'errors',len(errors),'seconds',round(time.monotonic()-start,1),flush=True)
result=dict(calendar=cal,raw=records,errors=errors,seconds=round(time.monotonic()-start,2))
(OUT/'raw_universe.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
print('done',len(records),'errors',len(errors),flush=True)
