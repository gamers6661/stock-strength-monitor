import cProfile,io,json,pstats,sys,time
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import market_strength as M,scoring,strength
p=Path(__file__).parent;f=json.loads((p/'frozen_full.json').read_text('utf8'))
rows={r['code']:r for r in f['stocks']+f.get('coverage_catalog',[])}
h=scoring.formal_histories(rows);calendar=strength.trading_calendar({c:strength.completed(v) for c,v in h.items()})
days=[d for d in calendar if d< f['quote_capture_at'][:10]][-3:]
prof=cProfile.Profile();prof.enable();start=time.perf_counter()
history={d:M.historical_scores(h,calendar,d) for d in days}
elapsed=time.perf_counter()-start;prof.disable()
buf=io.StringIO();pstats.Stats(prof,stream=buf).sort_stats('cumulative').print_stats(35)
(p/'math_profile.txt').write_text(buf.getvalue(),'utf8')
print('historical background seconds',elapsed,flush=True)
