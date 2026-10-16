"""审计完整观察/完成名单与前置形态，不以股票名单设置规则。"""
import json,gzip,sys,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import config,datafeed,trend_consolidation as tc
folder=Path(__file__).resolve().parent
snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
if not (folder/'before_snapshot.json.gz').exists():
    with gzip.open(folder/'before_snapshot.json.gz','wt',encoding='utf-8') as f:json.dump(snap,f,ensure_ascii=False)
    before=folder/'before';before.mkdir(exist_ok=True)
    for name in ('config.py','trend_consolidation.py','test_trend_consolidation.py','dashboard_template.html','check_live_service.py'):
        shutil.copy2(config.ROOT/name,before/name)
model=snap['trend_consolidation'];conn=datafeed.db()
calendar=[r[0] for r in conn.execute('SELECT DISTINCT date FROM kline ORDER BY date') if r[0]<='2026-09-30']
items=model['rows']+model.get('completed_rows',[])
inputs={r['code']:datafeed.load_kline(conn,'kline','code',r['code'],limit=120) for r in items}
conn.close();records=[]
for item in items:
    code=item['code'];bars=inputs[code];asof=item['baseline_asof']
    selected=[b for b in bars if item['consolidation_start']<=b['date']<=asof]
    anchor=next(b for b in bars if b['date']==item['peak_date'])
    attack=next(b for b in bars if b['date']==item['impulse_end'])
    record=dict(code=code,name=item['name'],phase=item.get('phase'),days=item['days'],
        attack_end=item['impulse_end'],anchor=item['peak_date'],start=item['consolidation_start'],
        attack_gain=item['attack_gain_pct'],anchor_close=anchor['close'],attack_close=attack['close'],
        platform=item['platform_high'],price=item['price'],volume_ratio=item['volume_ratio'],
        width=item['width_atr'],pullback=item['pullback_atr'],contraction=item['contraction_ratio'],
        divergence=item['expanded_down_dates'],reason=item.get('reason'),
        bars=[{k:b[k] for k in ('date','open','high','low','close','volume')} for b in bars if b['date']>='2026-09-14'],
        daily_replay=[dict(day=d,**tc.daily_setup(bars,d,calendar)) for d in calendar if d>='2026-09-14'])
    records.append(record)
(folder/'inputs.json').write_text(json.dumps(inputs,ensure_ascii=False),encoding='utf-8')
(folder/'audit.json').write_text(json.dumps(dict(version=tc.VERSION,calendar=calendar,records=records),ensure_ascii=False,indent=2),encoding='utf-8')
for r in records:
    print(json.dumps({k:v for k,v in r.items() if k not in ('bars','daily_replay')},ensure_ascii=False))
    if r['code'] in ('600641','002242'):
        print(json.dumps(dict(name=r['name'],bars=r['bars']),ensure_ascii=False))
