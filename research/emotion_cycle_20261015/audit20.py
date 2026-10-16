import csv,gzip,json,sys,time
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import relay_history as H,emotion_relay as E
OUT=Path(__file__).resolve().parent;cal=json.loads((OUT/'calendar.json').read_text(encoding='utf-8'));universe=json.loads((OUT/'universe.json').read_text(encoding='utf-8'));days=cal[-20:];replay=cal[-30:];start=time.monotonic()
reg=json.loads((OUT/'disclosures.json').read_text(encoding='utf-8'))
evidence=H.load(universe,replay,cal,'2026-10-15',fetch=False,verified_halts=reg['suspension_intervals']);evidence['regulation']=reg;H.index(evidence)
paths={c:E.chain(c,replay,cal,[],evidence) for c in universe};timeline=[];unknown=[]
for i,day in enumerate(replay):
 if day not in days:continue
 values=[p[i] for p in paths.values()];reasons=Counter(v['reason'] for v in values if v['sealed'] is None and not v['halted'])
 timeline.append(dict(date=day,valid=sum(v['sealed'] is not None or v['halted'] for v in values),suspended=sum(v['halted'] for v in values),sealed=sum(v['sealed'] is True for v in values),highest=max((v['height'] for v in values if v['sealed'] and v['exact']),default=0),unknown=dict(reasons)))
 for c,p in paths.items():
  v=p[i]
  if v['sealed'] is None and not v['halted']:unknown.append(dict(code=c,name=universe[c]['name'],**v))
cases=[]
for c in ('600825','002343','601811','605577'):
 cases.append(dict(code=c,name=universe[c]['name'],path=paths[c]))
rows=[dict(code=c,name=universe[c]['name'],peak=max((v['height'] for v in p if v['exact'] and v['date'] in days and (v['sealed'] or v['halted'])),default=0),latest=p[-1]) for c,p in paths.items()]
rows.sort(key=lambda r:(-r['peak'],r['code']))
report=dict(days=days,timeline=timeline,cases=cases,top=rows[:40],unknown=unknown,seconds=round(time.monotonic()-start,2))
(OUT/'audit20.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
with (OUT/'逐日核算.csv').open('w',encoding='utf-8-sig',newline='') as f:
 writer=csv.writer(f);writer.writerow(['日期','代码','名称','封板','停牌','完成板位','板位完整','原因'])
 for day in days:
  i=replay.index(day)
  for c,p in paths.items():
   v=p[i];writer.writerow([day,c,universe[c]['name'],v['sealed'],v['halted'],v['height'],v['exact'],v['reason']])
with gzip.open(OUT/'history_evidence.json.gz','wt',encoding='utf-8',compresslevel=1) as f:json.dump({k:v for k,v in evidence.items() if not k.startswith('_')},f,ensure_ascii=False)
print('timeline',json.dumps(timeline,ensure_ascii=False),flush=True)
print('cases',[(r['code'],[(v['date'],v['height'],'停' if v['halted'] else '封' if v['sealed'] else '-') for v in r['path'] if v['date'] in days]) for r in cases],flush=True)
print('tops',[(r['code'],r['name'],r['peak']) for r in rows[:15]],flush=True)
print('seconds',report['seconds'],flush=True)
