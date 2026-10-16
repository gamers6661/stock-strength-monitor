"""Audit transition claims directly against frozen OHLC, independently of signals."""
import gzip,json,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import ma_trend as T,observed_history
OUT=Path(__file__).parent
d=json.load(gzip.open(OUT/'inputs.json.gz','rt',encoding='utf8'))
v=json.load(gzip.open(OUT/'daily_setups.json.gz','rt',encoding='utf8'))
s=json.load(gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf8'))
names={r['code']:r['name'] for r in s['stocks']+s.get('coverage_catalog',[])}
day=s['quote_capture_at'][:10];counts=Counter();cases=[]
for c,setup in v.items():
    if not setup.get('cycle_id'):continue
    bars=observed_history.traded_bars([b for b in d['histories'][c] if b['date']<day])
    by_day={b['date']:i for i,b in enumerate(bars)};root=setup['origin'];start=by_day[root['date']]
    for event in setup['transitions']:
        i=by_day[event['date']];close=bars[i]['close'];line=lambda n:sum(b['close'] for b in bars[i-n+1:i+1])/n
        pair=(event['from_stage'],event['to_stage'])
        assert pair in ((None,5),(5,10),(10,20),(5,None),(10,None),(20,None)),(c,event)
        if pair==(None,5):assert close>=line(5)
        elif pair==(5,10):assert close<line(5)
        elif pair==(10,20):
            assert close<line(10)
            gain=max(b['close'] for b in bars[start:i+1])-root['base_low']
            assert 100*gain/root['base_low']>=T.P['ma20_rise_pct'] and gain/root['atr']>=T.P['ma20_rise_atr']
        elif pair[1] is None:
            assert close<setup['last_exit']['support']
            assert setup['last_exit']['origin']['date']==root['date']
        counts[str(pair)]+=1
    if setup['stage'] and setup.get('last_exit'):
        assert setup['last_exit']['date']<root['date']
        assert root['base_at']>=setup['last_exit']['date']
    if setup.get('progressing'):
        assert setup['stage']==setup['restart_event']['confirmation']['prior_stage']
        counts['confirmed_progression_retains_stage']+=1
    if names[c] in ('澳弘电子','皇台酒业','骏亚科技','宝鼎科技','闽东电力','贝瑞基因','澳洋健康'):
        cases.append(dict(code=c,name=names[c],stage=setup['stage'],origin=root['date'],entry=setup['entry_date'],
            progressing=setup.get('progressing'),restart=(setup.get('restart_event') or {}).get('date'),
            restart_confirm=((setup.get('restart_event') or {}).get('confirmation') or {}).get('date'),
            exit=(setup.get('last_exit') or {}).get('date'),transitions=setup['transitions']))
result=dict(version=T.VERSION,hash=T.IMPLEMENTATION_HASH,counts=dict(counts),cases=cases)
(OUT/'raw_ohlc_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(dict(counts=dict(counts),cases=[{k:w for k,w in r.items() if k!='transitions'} for r in cases]),ensure_ascii=False))
