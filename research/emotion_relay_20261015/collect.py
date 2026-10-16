import gzip,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import config,relay_data as R
OUT=Path(__file__).resolve().parent
with gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf-8') as f:s=json.load(f)
asof=s['strength_model']['asof'];conn=sqlite3.connect(OUT/'baseline/market.db')
cal=[r[0] for r in conn.execute('SELECT date FROM kline WHERE date<=? GROUP BY date HAVING COUNT(DISTINCT code)>=1000 ORDER BY date',(asof,))];conn.close()
days=cal[-config.EMOTION_RELAY['history_days']:]
data=R.load(days)
(OUT/'evidence.json').write_text(json.dumps(dict(calendar=cal,**data),ensure_ascii=False),encoding='utf-8')
print(json.dumps(dict(days=days,pools={d:{k:p.get(k) for k in ('total','date_verified','checked','expected','mismatched')} for d,p in data['pools'].items()},raw=len(data['raw']),fetch=data['fetch']),ensure_ascii=False),flush=True)
