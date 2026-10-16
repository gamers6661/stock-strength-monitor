import gzip,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import ma_trend as T
OUT=Path(__file__).parent;d=json.load(gzip.open(OUT/'inputs.json.gz','rt',encoding='utf8'))
bars=d['histories']['605058'];replay=[];previous=None
for i in range(21,len(bars)):
    s=T.daily(bars[:i+1],d['calendar'],limit_pct=10)
    marker=(s['stage'],(s.get('origin') or {}).get('date'))
    if marker!=previous:
        replay.append(dict(date=bars[i]['date'],close=bars[i]['close'],stage=s['stage'],origin=(s.get('origin') or {}).get('date'),
            last_exit=s.get('last_exit'),entry=s.get('ma20_entry'),transitions=s.get('transitions')))
    previous=marker
(OUT/'aohong_before.json').write_text(json.dumps(replay,ensure_ascii=False,indent=2),encoding='utf8')
for r in replay:print(json.dumps({k:v for k,v in r.items() if k not in ('last_exit','entry','transitions')},ensure_ascii=False))
