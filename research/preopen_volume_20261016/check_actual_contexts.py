import gzip,json,sys
from pathlib import Path
from datetime import datetime
from contextlib import closing
from collections import Counter
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,datafeed as D,intraday as I,strength
OUT=Path(__file__).parent
with gzip.open(config.CACHE_DIR/'intraday_history/acquisitions/2026-10-16.jsonl.gz','rt',encoding='utf-8') as f:
    record=max((json.loads(line) for line in f),key=lambda r:r['captured_at'])
q={v[0]:dict(zip(record['fields'][1:],v[1:])) for v in record['rows']};now=datetime.fromisoformat(record['captured_at'])
with closing(D.db()) as con:h={c:strength.completed(D.load_kline(con,'kline','code',c,limit=160),now) for c in q}
cal=strength.trading_calendar(h);valid=0;reasons=Counter();partial=[]
for c,quote in q.items():
    context=I.align_price_basis(quote,h[c],cal,observation_day=now.date().isoformat())
    if context['valid']:
        moving=I.provisional_trend(context['aligned_bars'],quote['price'])
        assert all(I._positive(moving.get('intraday_ma'+str(n)+'_exact')) for n in (5,10,20)),c
        valid+=1
    else:reasons[context['reason']]+=1
    if 0<len(h[c])<20:
        new=I.align_price_basis(quote,h[c],cal,observation_day=now.date().isoformat(),allow_partial=True)
        partial.append(dict(code=c,bars=len(h[c]),legacy_valid=context['valid'],available_ma=new['daily_ma']))
result=dict(capture=record['captured_at'],quotes=len(q),complete_windows=valid,reasons=reasons,short_samples=partial)
(OUT/'actual_contexts.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
