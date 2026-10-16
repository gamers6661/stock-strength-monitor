import gzip,json,random,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import ma_trend as T
OUT=Path(__file__).parent
d=json.load(gzip.open(OUT/'inputs.json.gz','rt',encoding='utf8'))
s=json.load(gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf8'))
names={r['code']:r['name'] for r in s['stocks']+s.get('coverage_catalog',[])}
comp=json.load(gzip.open(OUT/'models_comparison.json.gz','rt',encoding='utf8'));a=comp['after'];old=comp['before']
groups=defaultdict(list)
for c,m in a.items():
    if m['status']=='已退出':
        if old[c]['eligible']:groups['由旧有效观察退出'].append(c)
        continue
    if m.get('recovery_current'):groups['仍为收复候选'].append(c)
    elif m['eligible'] and not old[c]['eligible']:groups['新增有效观察'].append(c)
    elif m['status']=='MA20整理跟踪':groups['MA20跟踪未推荐'].append(c)
    elif m['pending'] and m.get('stage')==20:groups['MA20待核验不推荐'].append(c)
    elif m['eligible'] and old[c]['eligible']:groups['原有效观察对照'].append(c)
rng=random.Random(1602);selected=set(('000995','605058','603386','002639','002956','002913'))
for codes in groups.values():selected.update(rng.sample(sorted(codes),min(6,len(codes))))
audit=[]
for c in sorted(selected):
    m=a[c];bars=[b for b in d['histories'][c] if b['date']<=m['asof']];f=(m.get('origin') or {}).get('confirmation') or {}
    if m['status']=='MA20整理跟踪':
        assert not m['eligible'] and m['ma20_tracking']
        assert m['price']>=m['primary_support_price']
        assert m['ma20_entry']['rise_pct']>=20 and m['ma20_entry']['rise_atr']>=4
        assert not m['ma20_entry']['touch_confirmed']
    if f:
        event=next(i for i,b in enumerate(bars) if b['date']==f['event_date'])
        confirmed=next(i for i,b in enumerate(bars) if b['date']==f['date'])
        early=T.daily(bars[:confirmed],d['calendar'],10)
        assert ((early.get('origin') or {}).get('confirmation') or {}).get('date')!=f['date']
        assert event<=confirmed
        assert bars[confirmed]['close']>=T.average(bars,confirmed,5)
        assert T.average(bars,confirmed,5)>T.average(bars,confirmed-1,5)
        assert T.average(bars,confirmed,10)>T.average(bars,confirmed-1,10)
    audit.append(dict(code=c,name=names[c],groups=[g for g,cs in groups.items() if c in cs],
        before={k:old[c].get(k) for k in ('stage','status','eligible','origin')},
        after={k:m.get(k) for k in ('stage','status','eligible','origin','entry_date','quote_at','price','support_price','ma20_entry','ma20_restart_observation','reason','last_exit')},
        recent=[dict(date=b['date'],close=b['close'],low=b['low'],ma5=T.average(bars,i,5),ma10=T.average(bars,i,10),ma20=T.average(bars,i,20)) for i,b in list(enumerate(bars))[-7:]]))
result=dict(source=s['quote_capture_at'],groups={g:len(cs) for g,cs in groups.items()},sample_count=len(audit),samples=audit)
(OUT/'current_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k!='samples'},ensure_ascii=False))
for r in audit:
    m=r['after'];print(r['code'],r['name'],m['stage'],m['status'],m['eligible'],(m['origin'] or {}).get('date'),((m['origin'] or {}).get('confirmation') or {}).get('date'))
