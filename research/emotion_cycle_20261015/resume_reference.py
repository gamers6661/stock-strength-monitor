"""Resume the alternate history source slowly after its burst-rate rejection."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import relay_data as D
OUT=Path(__file__).resolve().parent
# Import only the parser/fetch definition, avoiding the original parallel runner.
namespace={};source=(OUT/'collect_reference.py').read_text(encoding='utf-8');exec(compile(source[:source.index('codes=list(universe)')],str(OUT/'collect_reference.py'),'exec'),dict(__file__=str(OUT/'collect_reference.py')),namespace)
fetch=namespace['fetch'];fetch.__globals__.update(namespace)
allraw=json.loads((OUT/'raw_universe.json').read_text(encoding='utf-8'));cal=allraw['calendar'];first=cal[-20];asof=cal[-1]
active=[c for c,r in allraw['raw'].items() if any(b['date']>=first for b in r['bars'])]
records={c:D.read(D.root()/'reference'/(c+'.json')) for c in active};need=[c for c,r in records.items() if not r or r.get('coverage_through')!=asof];errors=[];start=time.monotonic()
priority=['600825','002343','601811','605577'];need=sorted(need,key=lambda c:(c not in priority,c));batches=[need[i:i+40] for i in range(0,len(need),40)]
print('active',len(active),'remaining',len(need),'batches',len(batches),flush=True)
for i,chunk in enumerate(batches):
 time.sleep(.8)
 try:
  values=fetch(chunk)
  for c,r in values.items():records[c]=r;D.write(D.root()/'reference'/(c+'.json'),r)
  absent=set(chunk)-set(values)
  if absent:errors.append(dict(codes=sorted(absent),reason='返回未覆盖代码'))
 except Exception as e:errors.append(dict(codes=chunk,reason=repr(e)))
 if (i+1)%5==0:print('batches',i+1,'/',len(batches),'records',sum(bool(r) for r in records.values()),'errors',len(errors),flush=True)
(OUT/'reference_universe.json').write_text(json.dumps(dict(calendar=cal,reference={c:r for c,r in records.items() if r},errors=errors,seconds=round(time.monotonic()-start,2)),ensure_ascii=False),encoding='utf-8')
print('done','records',sum(bool(r) for r in records.values()),'errors',len(errors),flush=True)
