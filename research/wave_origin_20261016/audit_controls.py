"""Choose challenge samples from raw OHLC before looking at model membership."""
import gzip,json,random,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import ma_trend as T,observed_history
OUT=Path(__file__).parent
d=json.load(gzip.open(OUT/'inputs.json.gz','rt',encoding='utf8'))
s=json.load(gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf8'));names={r['code']:r['name'] for r in s['stocks']+s.get('coverage_catalog',[])}
day=s['quote_capture_at'][:10];groups=defaultdict(list)
for code,history in d['histories'].items():
    if d['quotes'].get(code,{}).get('limit_pct')!=10 or names[code].upper().startswith(('ST','*ST')):continue
    bars=observed_history.traded_bars([b for b in history if b['date']<day])
    ma={n:[T.average(bars,i,n) for i in range(len(bars))] for n in (5,10)}
    def sealed(i):return bars[i]['close']==bars[i]['high'] and abs(100*(bars[i]['close']/bars[i-1]['close']-1)-10)<=T.P['limit_return_tolerance_pp']
    for i in range(21,len(bars)-1):
        if not sealed(i) or not bars[i-1]['close']<ma[5][i-1] or bars[i]['close']<ma[5][i]:continue
        end=min(len(bars),i+5);window=range(i+1,end)
        possible=[j for j in window if sealed(j) and bars[j]['close']>max(bars[j-1]['close'],bars[i]['close'])
            and all(bars[j]['close']>=ma[n][j]>ma[n][j-1] for n in (5,10))
            and all(bars[k]['close']>=ma[5][k] for k in range(i+1,j+1))]
        group='原始形态满足后续确认' if possible else '期间失守MA5' if any(bars[j]['close']<ma[5][j] for j in window) else '没有第二次封板' if not any(sealed(j) for j in window) else '二次封板但均线未确认'
        groups[group].append(dict(code=code,name=names[code],event=bars[i]['date'],end=bars[end-1]['date'],index=i,possible=possible))
rng=random.Random(20261016804);samples=[]
for group,items in groups.items():
    for item in rng.sample(items,min(8,len(items))):
        bars=observed_history.traded_bars([b for b in d['histories'][item['code']] if b['date']<day]);i=item['index'];end=min(len(bars),i+5)
        early=T.daily(bars[:i+1],d['calendar'],10);late=T.daily(bars[:end],d['calendar'],10)
        proof=((late.get('origin') or {}).get('confirmation') or {})
        if not item['possible']:
            assert not (proof.get('kind')=='涨停重建均线后确认' and proof['event_date']==item['event'])
        assert not (((early.get('origin') or {}).get('confirmation') or {}).get('kind')=='涨停重建均线后确认' and early['origin']['date']==item['event'])
        item.update(group=group,first_day_stage=early['stage'],final_stage=late['stage'],final_origin=late.get('origin'),
            raw_bars=[dict(b,ma5=T.average(bars,j,5),ma10=T.average(bars,j,10)) for j,b in list(enumerate(bars))[i-1:end]])
        samples.append(item)
result=dict(raw_event_count=sum(map(len,groups.values())),groups={g:len(v) for g,v in groups.items()},sample_count=len(samples),samples=samples)
(OUT/'challenge_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k!='samples'},ensure_ascii=False))
