import json, hashlib
from pathlib import Path
from collections import Counter

OUT=Path(__file__).resolve().parent
BEFORE=OUT/'before'
manifest={str(p.relative_to(BEFORE)):dict(size=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in BEFORE.rglob('*') if p.is_file()}
(OUT/'baseline_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
records=[]
with (BEFORE/'radar_opportunity_v1'/'2026-10-12.jsonl').open(encoding='utf-8') as f:
    for line in f:
        r=json.loads(line); records.append(r)
brief=[]
for i,r in enumerate(records):
    m=r.get('market',{}); trans=r.get('transitions',[])
    brief.append(dict(index=i,generated_at=r['generated_at'],source_at=m.get('source_at'),latest_source_at=m.get('latest_source_at'),version=r['version'],lists={k:len(v) for k,v in r['lists'].items()},market_ready=m.get('ready'),transitions=len(trans)))
(OUT/'yesterday_rounds.json').write_text(json.dumps(brief,ensure_ascii=False,indent=2),encoding='utf-8')
focus=[(i,r) for i,r in enumerate(records) if '14:2'<=str(r['generated_at'])[11:15]<='14:4']
event_state={}; observations={}; changes=[]
for i,r in enumerate(records):
    previous=observations
    current={x['code']:x for x in r.get('observations',[])}
    if any(i==j for j,_ in focus):
        lost=set((records[i-1]['lists']['current'] if i else []))-set(r['lists']['current'])
        for code in sorted(lost):
            observation=current.get(code,{})
            for e in observation.get('events',[]):
                old=event_state.get(e['event_id']); full=next((t.get('event') or t for t in r.get('transitions',[]) if (t.get('event') or t).get('event_id')==e['event_id']),None)
                changes.append(dict(round=i,generated_at=r['generated_at'],code=code,previous_observation=previous.get(code),current_observation=observation,previous_event=old,transition_event=full))
    for t in r.get('transitions',[]):
        e=t.get('event') or t
        if e.get('event_id'):event_state[e['event_id']]=e
    observations=current
(OUT/'reset_event_evidence.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding='utf-8')
for i,r in focus:
    print(json.dumps(brief[i],ensure_ascii=False))
    changes_here=[c for c in changes if c['round']==i]
    print('lost',len(set(c['code'] for c in changes_here)),'reasons',Counter(tuple((c['transition_event'] or {}).get('history',[{}])[-1].get('reasons',[])) for c in changes_here))
    for c in changes_here[:2]:
        old=c['previous_event'] or {};new=c['transition_event'] or {}
        print(c['code'],json.dumps(dict(old_status=old.get('status'),old_sequence=old.get('sequence'),old_last=old.get('last_source_at'),new_status=new.get('status'),new_sequence=new.get('sequence'),new_last=new.get('last_source_at'),high_water=new.get('high_water_at')),ensure_ascii=False))
