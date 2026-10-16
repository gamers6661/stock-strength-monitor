import gzip,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import datafeed,ma_trend as T
OUT=Path(__file__).resolve().parent
with gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf-8') as f:s=json.load(f)
rows={r['code']:r for r in s['stocks']+s.get('coverage_catalog',[])}
conn=sqlite3.connect((OUT/'baseline/market.db').resolve().as_uri()+'?mode=ro',uri=True)
samples=[]
for code in ('002811','600812','001318','002578','002636','601019','603115','603991'):
    row=rows[code];bars=datafeed.load_kline(conn,'kline','code',code,limit=160);m=row['ma_trend']
    setup=T.daily(bars,[b['date'] for b in bars],limit_pct=10);origin=(m.get('origin') or {}).get('date');last=m.get('last_exit') or {}
    after=[dict(date=b['date'],close=b['close'],ma10=T.average(bars,i,10)) for i,b in enumerate(bars) if origin and b['date']>=origin and i>=21]
    losses=[b for b in after if b['close']<b['ma10']]
    item=dict(code=code,name=row['name'],stage=m['stage'],status=m['status'],origin=origin,confirmation=(m.get('last_confirmation') or {}).get('date'),
        entry=setup.get('entry_date'),lifecycle=setup.get('lifecycle'),last_exit=last,
        completed_ma10_losses=losses,closes=after)
    samples.append(item)
    print(row['name'],code,'origin',origin,'confirm',item['confirmation'],'status',m['status'],'lifecycle',item['lifecycle'],
        'exit',last.get('date'),'exit_origin',(last.get('origin') or {}).get('date'),'losses',json.dumps(losses,ensure_ascii=False))
conn.close();(OUT/'state_spot_checks.json').write_text(json.dumps(samples,ensure_ascii=False,indent=2),encoding='utf-8')
