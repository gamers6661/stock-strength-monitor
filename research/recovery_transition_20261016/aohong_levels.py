import gzip,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import ma_trend as T
OUT=Path(__file__).parent;d=json.load(gzip.open(OUT/'inputs.json.gz','rt',encoding='utf8'))
bars=d['histories']['605058'];root=T.daily([b for b in bars if b['date']<='2026-09-24'],d['calendar'],10)['origin']
out=[]
for i,b in enumerate(bars):
    if b['date']<'2026-09-24':continue
    unit=T.atr(bars,i);line=T.average(bars,i,20)
    recovery=T.recovery_event(bars,i,dict(ma={n:[T.average(bars,k,n) for k in range(len(bars))] for n in (5,10,20)},limit_pct=10),dict(date='2026-10-08',origin={}))
    platform=T.latest_platform(bars,i,root,require_position=False)
    out.append(dict(date=b['date'],close=b['close'],low=b['low'],ma5=T.average(bars,i,5),ma10=T.average(bars,i,10),ma20=line,
        ma10_previous=T.average(bars,i-1,10),low_dist_ma20_atr=(b['low']-line)/unit,
        close_ma20_pct=100*(b['close']/line-1),primary=T.ma20_rise(bars,i,root),platform=platform,
        recovery=bool(recovery)))
(OUT/'aohong_levels.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
for r in out:print(json.dumps({k:v for k,v in r.items() if k not in ('primary','platform')},ensure_ascii=False), 'primary_ready=',(r['primary'] or {}).get('ready'),'platform=',bool(r['platform']))
