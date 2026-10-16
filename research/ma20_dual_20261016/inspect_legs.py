import gzip,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import ma_trend as T
d=json.load(gzip.open(Path(__file__).parent/'inputs.json.gz','rt',encoding='utf8'))
for code in ('601298','603170','600789'):
    bars=d['histories'][code];s=T.daily(bars,d['calendar'],limit_pct=10)
    print(code,json.dumps({k:s[k] for k in ('entry_date','origin','ma20_entry','last_exit','transitions')},ensure_ascii=False))
    for b in bars[-22:]:
        i=bars.index(b)
        print(b['date'],b['close'],b['low'],round(T.average(bars,i,5),3),round(T.average(bars,i,10),3),round(T.average(bars,i,20),3))
