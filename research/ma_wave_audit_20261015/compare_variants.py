import json,sqlite3,sys
from collections import defaultdict
from pathlib import Path
from statistics import median
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import datafeed,ma_trend as T
OUT=Path(__file__).resolve().parent;r=json.loads((OUT/'study.json').read_text(encoding='utf-8'))
conn=sqlite3.connect((OUT/'baseline/market.db').resolve().as_uri()+'?mode=ro',uri=True);cache={}
for x in r['events']:
    if x['code'] not in cache:cache[x['code']]=datafeed.load_kline(conn,'kline','code',x['code'],limit=160)
    bars=cache[x['code']];i=next(i for i,b in enumerate(bars) if b['date']==x['date'])
    x['bar_index']=i
    x['close_high20']=max(b['close'] for b in bars[i-20:i])
    x['close_breakout']=x['close']>=x['close_high20']+T.P['breakout_atr']*T.atr(bars,i-1)
conn.close()

def independent(items):
    last={};out=[]
    for x in sorted(items,key=lambda x:(x['date'],x['code'])):
        if x['bar_index']-last.get(x['code'],-1000)<=10:continue
        last[x['code']]=x['bar_index'];out.append(x)
    return out

def summarize(items):
    out=dict(events=len(items),stocks=len({x['code'] for x in items}),followup={})
    for n in (1,3,5,10):
        eligible=[x['followup'][str(n)] for x in items if str(n) in x['followup']]
        if eligible:out['followup'][str(n)]=dict(n=len(eligible),hold=sum(x['all_closes_hold_ma10'] for x in eligible),
            median_close_return_pct=median(x['close_return_pct'] for x in eligible))
    return out

groups={}
for period in ('all','earlier','recent40'):
    for variant in ('existing','recover','recover_close_break','recover_ma20_up'):
        items=[x for x in r['events'] if (period=='all' or x['period']==period) and
            ((x['group']=='existing_entry') if variant=='existing' else
             (x['group']=='recovery_candidate' and (variant!='recover_close_break' or x['close_breakout']) and
              (variant!='recover_ma20_up' or x['above_rising_ma20'])))]
        groups[period+':'+variant]=summarize(independent(items))

chosen=[]
# Balance outcome groups for inspection; do not present this balanced sample as
# a population estimate. Every rate above uses the complete eligible event set.
for group in ('recovery_candidate','existing_entry'):
    for period in ('earlier','recent40'):
        for held in (True,False):
            items=independent([x for x in r['events'] if x['group']==group and x['period']==period
                and '5' in x['followup'] and x['followup']['5']['all_closes_hold_ma10']==held])
            items.sort(key=lambda x:(x['date'],x['code']))
            if items:chosen.append(items[len(items)//2])
            if group=='recovery_candidate' and len(items)>4:chosen.append(items[len(items)//4])
for code,date in [('000995','2026-10-13'),('601595','2026-10-09'),('600593','2026-10-13')]:
    x=next((x for x in r['events'] if x['code']==code and x['date']==date),None)
    if x and (code,date) not in {(t['code'],t['date']) for t in chosen}:chosen.append(x)
out=dict(coverage=r['coverage'],groups=groups,samples=chosen,
    origin_mismatch_stocks=sorted({(x['code'],x['name']) for x in r['audit_issues']['origin_exit_mismatch']}),
    overdue_stocks=sorted({(x['code'],x['name']) for x in r['audit_issues']['overdue_catchment']}))
(OUT/'variants_and_samples.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(coverage=out['coverage'],groups=groups),ensure_ascii=False,indent=2))
for x in chosen:
    print(x['name'],x['code'],x['date'],x['group'],x['volume_ratio'],x['above_rising_ma20'],x['close_breakout'],x['followup'])
