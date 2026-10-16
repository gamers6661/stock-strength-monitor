import copy,gzip,json,sqlite3,sys,time
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,datafeed,strength,ma_trend
OUT=Path(__file__).resolve().parent
with gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf-8') as f:s=json.load(f)
before={r['code']:copy.deepcopy(r.get('market_strength')) for r in s['stocks']+s.get('coverage_catalog',[])}
old=copy.deepcopy(s['ma_trend']);rows=s['stocks']+s.get('coverage_catalog',[]);pool={r['code']:r for r in rows}
quotes=(s.get('market_strength_close_input') or {}).get('quotes') or {}
assert len(quotes)>2000,'Frozen original close inputs missing'
conn=sqlite3.connect((OUT/'baseline/market.db').resolve().as_uri()+'?mode=ro',uri=True)
h={c:datafeed.load_kline(conn,'kline','code',c,limit=160) for c in pool};conn.close()
calendar=strength.trading_calendar({c:strength.completed(v) for c,v in h.items()})
ma_trend.attach(s,quotes,pool,h,calendar,now=datetime.fromisoformat(s['quote_capture_at']),minute_data={},fetch_minutes=False)
ma_trend.validate(s)
assert before=={r['code']:r.get('market_strength') for r in rows}
report=dict(version=ma_trend.VERSION,hash=ma_trend.IMPLEMENTATION_HASH,source=s['quote_capture_at'],
    old_counts=old['counts'],new_counts=s['ma_trend']['counts'],market_strength_unchanged=True,
    ma20=[dict(code=r['code'],name=r['name'],status=r['ma_trend']['status'],platform=r['ma_trend']['platform']) for r in rows if r['ma_trend']['stage']==20 and r['ma_trend']['status']!='已退出'],
    example=next(r['ma_trend'] for r in rows if r['code']=='000993'))
(OUT/'frozen_comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ('ma20','example')},ensure_ascii=False))
m=report['example'];p=m.get('platform') or {}
print('闽东电力',m['stage'],m['status'],m['reason'])
print(json.dumps({k:p.get(k) for k in ('start','peak_date','formed_at','low','high','rise_pct','retained_pct','retained_atr','width_atr','width_pct','volume_ratio')},ensure_ascii=False))
